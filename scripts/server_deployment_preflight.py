#!/usr/bin/env python3
"""Read-only server deployment-readiness preflight for the WebUI control repo."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_BRANCH = "feature/t212-instrument-cache-v03"
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
SAFE_ABSOLUTE_PATH = re.compile(r"^/[A-Za-z0-9_./-]+$")


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)


def _value(result: subprocess.CompletedProcess[str]) -> str | None:
    return result.stdout.strip() if result.returncode == 0 else None


def parse_file_stats(text: str | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not text:
        return records
    for line in text.splitlines():
        parts = line.rsplit("|", 2)
        if len(parts) != 3:
            continue
        try:
            records.append({"path": parts[0], "size": int(parts[1]), "mtime": float(parts[2])})
        except ValueError:
            continue
    return sorted(records, key=lambda item: item["mtime"], reverse=True)


def latest_summary(records: list[dict[str, Any]], now_epoch: float) -> dict[str, Any] | None:
    if not records:
        return None
    item = records[0]
    return {
        "name": Path(item["path"]).name,
        "size_bytes": item["size"],
        "age_hours": round(max(0.0, now_epoch - item["mtime"]) / 3600, 2),
    }


def assess(
    snapshot: dict[str, Any],
    *,
    now_epoch: float,
    max_backup_age_hours: float,
    min_disk_bytes: int,
    expected_branch: str,
    expected_commit: str | None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    branch = snapshot.get("git_branch")
    commit = snapshot.get("git_commit")
    add("expected_branch", branch == expected_branch, f"branch={branch or 'unavailable'}")
    add("clean_worktree", snapshot.get("git_clean") is True, "clean" if snapshot.get("git_clean") else "dirty_or_unavailable")
    add("commit_available", bool(commit), f"commit={commit or 'unavailable'}")
    if expected_commit:
        add("expected_commit", commit == expected_commit, "matched" if commit == expected_commit else "mismatch")

    add("container_running", snapshot.get("container_running") is True, "running" if snapshot.get("container_running") else "not_running_or_unavailable")
    db = snapshot.get("database")
    add("database_present", bool(db and db.get("size", 0) > 0), f"size_bytes={db.get('size', 0) if db else 0}")

    for key, label in (("database_backups", "database_backup"), ("tool_backups", "tool_table_backup")):
        latest = latest_summary(snapshot.get(key, []), now_epoch)
        passed = bool(latest and latest["size_bytes"] > 0 and latest["age_hours"] <= max_backup_age_hours)
        detail = (
            f"name={latest['name']};size_bytes={latest['size_bytes']};age_hours={latest['age_hours']}"
            if latest
            else "missing"
        )
        add(label, passed, detail)

    disk_free = int(snapshot.get("disk_free_bytes") or 0)
    add("disk_space", disk_free >= min_disk_bytes, f"free_bytes={disk_free}")
    add("repository_preflight", snapshot.get("repository_preflight") is True, "passed" if snapshot.get("repository_preflight") else "failed_or_unavailable")

    safety = snapshot.get("safety") or {}
    safe = (
        safety.get("environment") == "DEMO"
        and safety.get("live_trading_enabled") is False
        and safety.get("order_mutation_enabled") is False
    )
    add(
        "demo_safety",
        safe,
        "DEMO;live_trading=false;order_mutation=false" if safe else "unsafe_or_unavailable",
    )

    failed = [item["name"] for item in checks if not item["passed"]]
    if failed:
        status = "NOT_READY"
    elif expected_commit:
        status = "READY"
    else:
        status = "READY_FOR_COMMIT_APPROVAL"

    return {
        "status": status,
        "branch": branch,
        "commit": commit,
        "checks": checks,
        "failed_checks": failed,
        "side_effects": "none",
    }


def collect(repo_dir: Path, container: str, data_dir: str) -> dict[str, Any]:
    branch = _value(_run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir))
    commit = _value(_run(["git", "rev-parse", "HEAD"], cwd=repo_dir))
    status = _run(["git", "status", "--porcelain"], cwd=repo_dir)

    running_result = _run(["docker", "inspect", "-f", "{{.State.Running}}", container])
    container_running = running_result.returncode == 0 and running_result.stdout.strip().lower() == "true"

    database: dict[str, Any] | None = None
    database_backups: list[dict[str, Any]] = []
    tool_backups: list[dict[str, Any]] = []
    if container_running:
        db_result = _run(["docker", "exec", container, "stat", "-c", "%n|%s|%Y", f"{data_dir}/webui.db"])
        db_records = parse_file_stats(_value(db_result))
        database = db_records[0] if db_records else None

        db_backup_result = _run([
            "docker", "exec", container, "find", data_dir, "-maxdepth", "1", "-type", "f",
            "-name", "webui_backup_*.db", "-printf", "%p|%s|%T@\n",
        ])
        database_backups = parse_file_stats(_value(db_backup_result))

        tool_backup_result = _run([
            "docker", "exec", container, "find", data_dir, "-maxdepth", "1", "-type", "f",
            "-name", "tool_table_backup_*.json", "-printf", "%p|%s|%T@\n",
        ])
        tool_backups = parse_file_stats(_value(tool_backup_result))

    preflight = _run([sys.executable, str(repo_dir / "scripts" / "verify_webui_control.py")], cwd=repo_dir)

    safety: dict[str, Any] = {}
    manifest_path = repo_dir / "webui-control" / "release-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        trading_safety = manifest.get("trading_safety", {})
        safety = {
            "environment": trading_safety.get("environment"),
            "live_trading_enabled": trading_safety.get("live_trading"),
            "order_mutation_enabled": trading_safety.get("order_mutation_during_control_plane_validation"),
        }
    except (OSError, json.JSONDecodeError):
        pass

    return {
        "git_branch": branch,
        "git_commit": commit,
        "git_clean": status.returncode == 0 and not status.stdout.strip(),
        "container_running": container_running,
        "database": database,
        "database_backups": database_backups,
        "tool_backups": tool_backups,
        "disk_free_bytes": shutil.disk_usage(repo_dir).free,
        "repository_preflight": preflight.returncode == 0,
        "safety": safety,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a read-only WebUI deployment-readiness preflight.")
    parser.add_argument("--repo-dir", default=".", help="Checked-out repository directory.")
    parser.add_argument("--container", default="open-webui", help="OpenWebUI Docker container name.")
    parser.add_argument("--data-dir", default="/app/backend/data", help="OpenWebUI data directory in the container.")
    parser.add_argument("--expected-branch", default=DEFAULT_BRANCH)
    parser.add_argument("--expected-commit", help="Approved 40-character Git commit SHA.")
    parser.add_argument("--max-backup-age-hours", type=float, default=24.0)
    parser.add_argument("--min-disk-gib", type=float, default=1.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_dir = Path(args.repo_dir).expanduser().resolve()

    if not SAFE_NAME.fullmatch(args.container):
        raise SystemExit("Invalid container name.")
    if not SAFE_ABSOLUTE_PATH.fullmatch(args.data_dir) or ".." in Path(args.data_dir).parts:
        raise SystemExit("Invalid data directory.")
    if args.expected_commit and not re.fullmatch(r"[0-9a-fA-F]{40}", args.expected_commit):
        raise SystemExit("Expected commit must be a 40-character hexadecimal SHA.")
    if args.max_backup_age_hours <= 0 or args.min_disk_gib <= 0:
        raise SystemExit("Backup age and minimum disk space must be positive.")
    if not repo_dir.is_dir():
        raise SystemExit("Repository directory does not exist.")

    report = assess(
        collect(repo_dir, args.container, args.data_dir),
        now_epoch=time.time(),
        max_backup_age_hours=args.max_backup_age_hours,
        min_disk_bytes=int(args.min_disk_gib * 1024**3),
        expected_branch=args.expected_branch,
        expected_commit=args.expected_commit.lower() if args.expected_commit else None,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] in {"READY", "READY_FOR_COMMIT_APPROVAL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
