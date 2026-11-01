#!/usr/bin/env python3
"""Restore ONLY the WebUI SQLite DB from a v0.12.4 pre-cutover snapshot.

Operator must stop production WebUI first. Source snapshot is mounted :ro,
target is the existing named volume. Do not invoke for any other database.
No broker or model calls. No network.
"""
from pathlib import Path
import os
import shutil
import sqlite3

SOURCE=Path("/source/webui.db")
TARGET_DIR=Path("/target")
TARGET=TARGET_DIR/"webui.db"
TEMP=TARGET_DIR/".webui-v0124-rollback-incomplete.db"

def check(path, expected=None):
    assert path.is_file() and not path.is_symlink(), "Unexpected DB path"
    with sqlite3.connect(path.as_uri()+"?mode=ro&immutable=1",uri=True,timeout=10) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0]=="ok", "DB corrupt"
        count=db.execute("select count(*) from sqlite_master where type='table'").fetchone()[0]
    assert count>=48, f"Unexpected DB table count {count}"
    if expected is not None:
        assert count==expected, "Restored DB schema differs"
    return count

assert SOURCE.is_file() and not SOURCE.is_symlink(), "Missing snapshot"
assert TARGET_DIR.is_dir() and not TARGET_DIR.is_symlink(), "Unexpected target volume"
assert TARGET.is_file() and not TARGET.is_symlink(), "Missing live DB"
assert not TEMP.exists(), "Incomplete earlier restore exists: manual inspection required"
tables=check(SOURCE)
# Copy/validate first; never overwrite source snapshot or alter non-DB user files.
try:
    shutil.copy2(SOURCE,TEMP)
    os.chmod(TEMP,0o600)
    check(TEMP,expected=tables)
    # Caller must have STOPPED WebUI before removing journal files.
    for ext in ("-wal","-shm","-journal"):
        sidecar=TARGET_DIR/("webui.db"+ext)
        if sidecar.exists():
            assert sidecar.is_file() and not sidecar.is_symlink(), "Unexpected SQLite sidecar"
            sidecar.unlink()
    os.replace(TEMP,TARGET)
finally:
    if TEMP.exists():
        TEMP.unlink()
check(TARGET,expected=tables)
print("V0124_DB_ROLLBACK_PASS", "restored_tables",tables,flush=True)
