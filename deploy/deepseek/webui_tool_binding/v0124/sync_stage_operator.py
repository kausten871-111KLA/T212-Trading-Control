#!/usr/bin/env python3
"""Operator-only v0.12.4 stage sync. Does NOT deploy/restart production.

Run manually on Contabo as katie AFTER reviewing the pinned PR and receipts:
  python3 /path/to/sync_stage_operator.py

Copies ONLY three audited scripts from a pinned Git commit to the private
STAGING directory. Fail-closed old/target blob checks, private backups,
atomic replacement and a read-only --check preflight. On preflight failure
restores staged files from the backups. Never changes Compose or WebUI data.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO = Path("/home/katie/t212-brain-benchmark-stage-20261020")
STAGE = Path("/home/katie/webui-v0124-stage-20261025")
COMMIT = "575a3f7a350933c2d14a2b0cac755e4224d703af"
REL = "deploy/deepseek/webui_tool_binding/v0124/"
# These are actual 04:58 GMT 26 Oct staged Git blob hashes, read over
# authorised strict-host-key SSH. The third file already matches the PR.
BEFORE = {
    "upgrade_supervised.sh": "da35812396abbe8226cd7ea508460e83b0143a0c",
    "v0124_acceptance.py": "3b32c9ab134f354abc848b32978f74079d2f086d",
    "v0124_restore_db.py": "14140f8a7ee2ac1dc3e54120e469199bb2cd41f4",
}
TARGET = {
    "upgrade_supervised.sh": "6d100ca641f08ef3894b4d604aa3979215a55161",
    "v0124_acceptance.py": "c77bc38f2c53ccbdb3ff84178533f81fb4f9d58b",
    "v0124_restore_db.py": "14140f8a7ee2ac1dc3e54120e469199bb2cd41f4",
}
OLD_STAGE_SHA256 = "407f11aa9a90806b2feef03bdb9cfb0ec45a2ae4f33c588eae9b4868b64678c8"


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def git_sources() -> dict[str, bytes]:
    if not REPO.is_dir():
        raise RuntimeError("Expected existing server Git checkout missing")
    if subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", COMMIT + "^{commit}"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        subprocess.run(["git", "-C", str(REPO), "fetch", "--quiet", "origin",
                        "feature/t212-runtime-integrated-stage-20261018"], check=True)
    subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", COMMIT + "^{commit}"], check=True)
    sources = {}
    for name, expected in TARGET.items():
        data = subprocess.check_output(["git", "-C", str(REPO), "show", f"{COMMIT}:{REL}{name}"])
        if blob_sha(data) != expected:
            raise RuntimeError(f"Git source blob drift: {name}")
        sources[name] = data
    return sources


def preflight() -> None:
    subprocess.run(["bash", str(STAGE / "upgrade_supervised.sh"), "--check"], check=True)


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".v0124-stage-sync-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def synchronize(sources: dict[str, bytes], check=preflight) -> str:
    if not STAGE.is_dir() or STAGE.is_symlink():
        raise RuntimeError("Expected private staging directory missing or symlink")
    previous = {}
    modes = {}
    for name, expected_target in TARGET.items():
        path = STAGE / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"Unsafe or missing staged script: {name}")
        current = path.read_bytes()
        current_blob = blob_sha(current)
        if current_blob not in (BEFORE[name], expected_target):
            raise RuntimeError(f"Unexpected stage drift; refusing to overwrite: {name}")
        if name == "upgrade_supervised.sh" and current_blob == BEFORE[name]:
            if hashlib.sha256(current).hexdigest() != OLD_STAGE_SHA256:
                raise RuntimeError("Previous staged upgrade script SHA256 mismatch")
        if blob_sha(sources[name]) != expected_target:
            raise RuntimeError(f"Source verification failed: {name}")
        previous[name] = current
        modes[name] = path.stat().st_mode & 0o777
    if all(blob_sha(previous[name]) == TARGET[name] for name in TARGET):
        check()
        print("V0124_STAGE_SYNC_ALREADY_CURRENT preflight_pass", flush=True)
        return "already-current"
    backup = Path(tempfile.mkdtemp(prefix="v0124-stage-before-sync-", dir=STAGE))
    os.chmod(backup, 0o700)
    for name, content in previous.items():
        saved = backup / name
        saved.write_bytes(content)
        os.chmod(saved, 0o600)
    changed = []
    try:
        for name, content in sources.items():
            if blob_sha(previous[name]) != TARGET[name]:
                atomic_write(STAGE / name, content, modes[name])
                changed.append(name)
        for name, expected in TARGET.items():
            if blob_sha((STAGE / name).read_bytes()) != expected:
                raise RuntimeError(f"Post-copy verification failed: {name}")
        check()
    except BaseException:
        for name in changed:
            atomic_write(STAGE / name, previous[name], modes[name])
        print("V0124_STAGE_SYNC_ROLLED_BACK staged_scripts_restored production_unchanged", flush=True)
        raise
    print("V0124_STAGE_SYNC_PASS", "updated", ",".join(changed),
          "backup", backup, "preflight_pass", flush=True)
    return "updated"


if __name__ == "__main__":
    os.umask(0o077)
    try:
        synchronize(git_sources())
    except Exception as exc:
        print("V0124_STAGE_SYNC_BLOCKED", type(exc).__name__, str(exc)[:600], flush=True)
        sys.exit(1)
