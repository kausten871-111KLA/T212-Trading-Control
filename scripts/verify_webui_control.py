#!/usr/bin/env python3
"""One-command, read-only preflight for the WebUI control-plane branch."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openwebui.tools.model_router import validate_router_config
from openwebui.tools.plugin_registry import validate_registry


CONFIG_FILES = [
    "webui-control/workspaces.json",
    "webui-control/agent-contract.json",
    "webui-control/handoff-schema.json",
    "webui-control/model-router.json",
    "webui-control/plugin-registry.json",
    "webui-control/automation-run-schema.json",
    "webui-control/shift-handoff-schema.json",
    "webui-control/release-manifest.json",
]


def load_json(relative: str) -> dict:
    with (ROOT / relative).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    report = {
        "status": "PASS",
        "live_effect": False,
        "configs_checked": [],
        "components_checked": [],
        "tests_run": 0,
        "failures": [],
        "trading": {
            "environment": "DEMO",
            "live_trading": False,
            "order_mutation": False,
        },
    }

    configs: dict[str, dict] = {}
    for relative in CONFIG_FILES:
        try:
            configs[relative] = load_json(relative)
            report["configs_checked"].append(relative)
        except (OSError, json.JSONDecodeError) as exc:
            report["failures"].append(f"{relative}: {exc}")

    if not report["failures"]:
        try:
            validate_router_config(configs["webui-control/model-router.json"])
            validate_registry(configs["webui-control/plugin-registry.json"])
        except ValueError as exc:
            report["failures"].append(f"control config: {exc}")

    manifest = configs.get("webui-control/release-manifest.json", {})
    for component in manifest.get("components", []):
        for key in ("config", "code"):
            relative = component.get(key)
            if relative and not (ROOT / relative).is_file():
                report["failures"].append(
                    f'{component.get("id", "unknown")}: missing {key} {relative}'
                )
        report["components_checked"].append(component.get("id"))

    trading = manifest.get("trading_safety", {})
    if (
        trading.get("environment") != "DEMO"
        or trading.get("live_trading") is not False
        or trading.get("order_mutation_during_control_plane_validation") is not False
        or trading.get("fail_closed") is not True
    ):
        report["failures"].append("release manifest violates T212 DEMO safety")

    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(suite)
    report["tests_run"] = result.testsRun
    if not result.wasSuccessful():
        report["failures"].append(
            f"unit tests: {len(result.failures)} failures, {len(result.errors)} errors"
        )

    if report["failures"]:
        report["status"] = "FAIL"

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
