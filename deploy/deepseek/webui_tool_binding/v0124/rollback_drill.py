#!/usr/bin/env python3
"""Offline rollback rehearsal: only disposable DB copy, never production volume.

Uses Oct 25 backup as read-only source, adds sentinel table to a separate
staging DB, invokes the exact v0.12.4 restore helper, proves sentinel removed.
"""
from pathlib import Path
import os
import subprocess
import sys

ROOT=Path("/home/katie/webui-v0124-stage-20261025")
BACKUP=Path("/home/katie/backups/webui-v0124-security-20261025/data")
STAGE=ROOT/"rollback-drill-20261025"
RESTORE=ROOT/"v0124_restore_db.py"
OLD="local/open-webui-toolbinding-v0123-stage:20261020"
NEW="local/open-webui-toolbinding-v0124-stage:20261025"
OLD_ID="sha256:7d8d04ead2b7c38d99b12b80a777b6030f3c694c491ca93e6bb010b5c3e82483"

SETUP=r'''
from pathlib import Path
import hashlib,shutil,sqlite3
source=Path("/source/webui.db")
target=Path("/target/webui.db")
assert source.is_file() and not target.exists()
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
original=sha(source)
shutil.copy2(source,target)
assert sha(target)==original
with sqlite3.connect(target) as db:
    db.execute("create table v0124_rollback_sentinel (id integer)")
    db.commit()
    assert db.execute("select count(*) from sqlite_master where type='table'").fetchone()[0]==49
print("V0124_ROLLBACK_DRILL_SETUP_PASS",flush=True)
'''
VERIFY=r'''
from pathlib import Path
import hashlib,sqlite3
source=Path("/source/webui.db")
target=Path("/target/webui.db")
with sqlite3.connect("file:/target/webui.db?mode=ro&immutable=1",uri=True) as db:
    assert db.execute("pragma integrity_check").fetchone()[0]=="ok"
    assert db.execute("select count(*) from sqlite_master where type='table'").fetchone()[0]==48
    assert not db.execute("select name from sqlite_master where name='v0124_rollback_sentinel'").fetchone()
assert hashlib.sha256(source.read_bytes()).hexdigest()==hashlib.sha256(target.read_bytes()).hexdigest()
print("V0124_ROLLBACK_DRILL_PASS", "restored_tables",48,"snapshot_unchanged",True,flush=True)
'''

def run(script):
    subprocess.run(["docker","run","--rm","-i","--network","none",
      "--security-opt","no-new-privileges",
      "-v",f"{BACKUP}:/source:ro","-v",f"{STAGE}:/target",
      "--entrypoint","python",OLD,"-"],input=script,text=True,check=True)

def main():
    assert subprocess.check_output(["docker","inspect","-f","{{.Image}}","open-webui"],text=True).strip()==OLD_ID
    assert BACKUP.is_dir() and (BACKUP/"webui.db").is_file()
    assert RESTORE.is_file()
    assert not STAGE.exists(), "Rollback drill directory already exists; preserve it"
    STAGE.mkdir(mode=0o700)
    run(SETUP)
    subprocess.run(["docker","run","--rm","--network","none",
      "--security-opt","no-new-privileges",
      "-v",f"{BACKUP}:/source:ro","-v",f"{STAGE}:/target",
      "-v",f"{RESTORE}:/restore.py:ro",
      "--entrypoint","python",NEW,"/restore.py"],check=True)
    run(VERIFY)
    assert subprocess.check_output(["docker","inspect","-f","{{.Image}}","open-webui"],text=True).strip()==OLD_ID
    print("PRODUCTION_UNCHANGED", "rollback_drill_only",flush=True)

if __name__=="__main__":
    os.umask(0o077)
    try:
        main()
    except Exception as e:
        print("V0124_ROLLBACK_DRILL_BLOCKED",type(e).__name__,str(e)[:400],flush=True)
        sys.exit(1)
