#!/usr/bin/env python3
"""Restore a pre-upgrade SQLite backup after WebUI has been stopped.

SOURCE /source is a pre-upgrade full-volume snapshot mounted read-only.
TARGET /target is the original named Docker volume mounted read-write.
Only the WebUI DB + sidecars are changed, never other user files.
No network, broker API, or service operations.
"""
from pathlib import Path
import os
import shutil
import sqlite3
import stat

source=Path("/source/webui.db")
target=Path("/target")
assert source.is_file() and not source.is_symlink()
assert target.is_dir() and not target.is_symlink()
with sqlite3.connect("file:/source/webui.db?mode=ro&immutable=1",uri=True,timeout=8) as conn:
    assert conn.execute("pragma integrity_check").fetchone()[0]=="ok"
    before=conn.execute("select count(*) from sqlite_master where type='table'").fetchone()[0]
assert 40<=before<=45, "Expected pre-0.12.3 WebUI database"
assert (target/"webui.db").is_file(), "Unexpected target, refusing"
temp=target/".webui-v0123-rollback-incomplete.db"
assert not temp.exists()
try:
    shutil.copy2(source,temp)
    os.chmod(temp,0o600)
    # Caller must have STOPPED WebUI before this operation.
    for extension in ("-wal","-shm","-journal"):
        part=target/("webui.db"+extension)
        if part.exists():
            assert part.is_file() and not part.is_symlink(), "Unexpected SQLite sidecar"
            part.unlink()
    os.replace(temp,target/"webui.db")
finally:
    if temp.exists():
        temp.unlink()
with sqlite3.connect("file:/target/webui.db?mode=ro",uri=True,timeout=8) as conn:
    assert conn.execute("pragma integrity_check").fetchone()[0]=="ok"
    after=conn.execute("select count(*) from sqlite_master where type='table'").fetchone()[0]
assert after==before
print("V0123_DB_ROLLBACK_PASS preupgrade_tables",before,flush=True)
