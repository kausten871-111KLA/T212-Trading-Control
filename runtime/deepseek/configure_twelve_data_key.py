"""Safely install Twelve Data API key in existing private Contabo configuration.

This script prompts locally without echo, preserves other keys and comments,
writes atomically as 0600, and never prints key values.
"""
from __future__ import annotations

from getpass import getpass
import os
from pathlib import Path
import re
import tempfile

ENV_FILE=Path.home()/".config/deepseek-runtime/data-api.env"

def configure(path=ENV_FILE, *, prompt=getpass):
    file=Path(path)
    file.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    # Only manipulate the single named key line; avoid duplicate entries.
    value=prompt("Twelve Data API key (hidden; input is not echoed): ").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,256}",value):
        raise SystemExit("KEY_FORMAT_INVALID: existing configuration unchanged")
    old=file.read_text(encoding="utf-8").splitlines() if file.is_file() else []
    preserved=[x for x in old if not x.startswith("TWELVEDATA_API_KEY=")]
    preserved.append("TWELVEDATA_API_KEY="+value)
    fd,temp=tempfile.mkstemp(dir=file.parent,prefix=".twelve-data-env-",text=True)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as output:
            output.write("\n".join(preserved)+"\n")
        os.replace(temp,file)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    print("TWELVEDATA_PRIVATE_KEY_CONFIGURED; no key displayed")
    return True

if __name__=="__main__":
    configure()
