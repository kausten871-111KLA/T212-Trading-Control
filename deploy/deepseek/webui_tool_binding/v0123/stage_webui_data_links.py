#!/usr/bin/env python3
"""Isolated WebUI data copy. Live volume is mounted read-only.

Use ONLY in a disposable helper container with /source:ro and /dest:rw.
No changes to running Open WebUI or source volume.
"""
from pathlib import Path
import hashlib
import os
import shutil
import sqlite3
import stat
import time

source=Path("/source")
dest=Path("/dest")
assert source.is_dir() and dest.is_dir()
assert (source/"webui.db").is_file()
assert not list(dest.iterdir()), "Stage destination must be empty"

start=time.monotonic()
count=0
bytes_total=0
for root,dirs,files in os.walk(source):
    here=Path(root)
    rel=here.relative_to(source)
    target=dest/rel
    target.mkdir(parents=True,exist_ok=True)
    for name in files:
        p=here/name
        if rel == Path(".") and name in {"webui.db","webui.db-wal","webui.db-shm","webui.db-journal"}:
            continue
        if p.is_symlink():
            # The model cache uses relative Hugging Face blob links.
            # Never dereference them; validate containment and preserve as links.
            resolved = p.resolve(strict=True)
            if not resolved.is_relative_to(source.resolve()) or not resolved.is_file():
                raise RuntimeError("Symlink target escapes source or is not a file")
            raw_target = os.readlink(p)
            if os.path.isabs(raw_target):
                raise RuntimeError("Absolute symlink not permitted in staged copy")
            (target/name).symlink_to(raw_target)
            count += 1
            continue
        if not p.is_file():
            continue
        shutil.copy2(p,target/name,follow_symlinks=False)
        count+=1
        bytes_total+=p.stat().st_size

db_src=sqlite3.connect("file:/source/webui.db?mode=ro",uri=True,timeout=30)
db_target=sqlite3.connect(str(dest/"webui.db"),timeout=30)
try:
    db_src.backup(db_target,pages=700,sleep=.01)
    assert db_target.execute("pragma integrity_check").fetchone()[0]=="ok"
    tables=db_target.execute("select count(*) from sqlite_master where type='table'").fetchone()[0]
finally:
    db_target.close()
    db_src.close()
os.chmod(dest/"webui.db",0o600)
assert tables>=40
print("ISOLATED_VOLUME_COPY_PASS", "files",count,"other_file_bytes",bytes_total,
      "db_bytes",(dest/"webui.db").stat().st_size,"tables",tables,
      "elapsed_seconds",round(time.monotonic()-start,1),flush=True)
