import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYSTEMD = ROOT / "deploy" / "systemd"
SERVICES = sorted(SYSTEMD.glob("t212-*.service"))


class SystemdReadinessTests(unittest.TestCase):
    def read(self, name):
        return (SYSTEMD / name).read_text(encoding="utf-8")

    def test_wall_clock_timers_use_explicit_uk_timezone(self):
        cache = self.read("t212-cache-refresh.timer")
        eod = self.read("t212-eod-audit.timer")
        self.assertRegex(cache, r"(?m)^OnCalendar=.*Europe/London$")
        self.assertRegex(eod, r"(?m)^OnCalendar=.*Europe/London$")

    def test_discovery_timer_has_explicit_uk_outer_window(self):
        discovery = self.read("t212-discovery.timer")
        expected = (
            "OnCalendar=Mon..Fri *-*-* 14:20/5:00 Europe/London",
            "OnCalendar=Mon..Fri *-*-* 15..20:00/5:00 Europe/London",
            "OnCalendar=Mon..Fri *-*-* 21:00..05/5:00 Europe/London",
        )
        for calendar in expected:
            self.assertIn(calendar, discovery)
        self.assertNotIn("OnCalendar=*:0/5", discovery)
        self.assertIn("Persistent=true", discovery)

    def test_discovery_service_produces_snapshot_before_scanning(self):
        discovery = self.read("t212-discovery.service")
        self.assertIn(
            "ExecStartPre=/usr/bin/python3 /home/katie/t212-scanner/worker/produce_market_snapshot.py",
            discovery,
        )
        self.assertIn("EnvironmentFile=-/etc/t212-scanner/runtime.env", discovery)

    def test_all_worker_services_are_bounded_and_retry_failures(self):
        for path in SERVICES:
            text = path.read_text(encoding="utf-8")
            with self.subTest(service=path.name):
                self.assertRegex(text, r"(?m)^TimeoutStartSec=\S+")
                self.assertIn("Restart=on-failure", text)
                self.assertRegex(text, r"(?m)^RestartSec=\S+")
                self.assertIn("StartLimitBurst=3", text)

    def test_all_worker_services_have_filesystem_hardening(self):
        required = (
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "ProtectSystem=strict",
            "ProtectHome=read-only",
            "UMask=0077",
            "ReadWritePaths=/var/lib/t212-scanner",
        )
        for path in SERVICES:
            text = path.read_text(encoding="utf-8")
            with self.subTest(service=path.name):
                for setting in required:
                    self.assertIn(setting, text)

    def test_instrument_refresh_is_demo_only(self):
        worker = (ROOT / "scripts" / "refresh_t212_cache_worker.py").read_text(encoding="utf-8")
        self.assertIn("https://demo.trading212.com/", worker)
        self.assertNotIn("https://live.trading212.com/", worker)
        self.assertNotIn("https://api.trading212.com/", worker)

    def test_scheduled_workers_do_not_submit_orders(self):
        paths = [
            ROOT / "scripts" / "refresh_t212_cache_worker.py",
            ROOT / "worker" / "produce_market_snapshot.py",
            ROOT / "worker" / "run_discovery_cycle.py",
            ROOT / "worker" / "run_eod_audit.py",
        ]
        mutation_patterns = (
            r"requests\.post\(",
            r"urllib\.request\.Request\([^\n]+method=[\"']POST",
            r"place_order\(",
            r"submit_order\(",
        )
        for path in paths:
            text = path.read_text(encoding="utf-8")
            with self.subTest(worker=path.name):
                for pattern in mutation_patterns:
                    self.assertIsNone(re.search(pattern, text, flags=re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
