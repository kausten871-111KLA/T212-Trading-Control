"""Configure the optional TradingAgents lab key without displaying credentials.

Only run on your own authorised Contabo terminal. Stores one key in a
private mode-0600 file outside GitHub and outside production WebUI.
"""
from getpass import getpass
import os
from pathlib import Path
import re
import tempfile

def main():
    folder=Path.home()/".config/deepseek-runtime"
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    dest=folder/"tradingagents-openrouter.key"
    secret=getpass("Enter OpenRouter API key for optional research lab (hidden): ").strip()
    if not (secret.startswith("sk-or-") and
            re.fullmatch(r"[A-Za-z0-9_-]{16,256}",secret)):
        raise SystemExit("Invalid OpenRouter key format; no change made.")
    fd,temp=tempfile.mkstemp(prefix=".lab-key-",dir=folder)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"w") as out:
            out.write(secret+"\n")
        os.replace(temp,dest)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    print("PRIVATE_OPENROUTER_LAB_KEY_SAVED; key not displayed")

if __name__=="__main__":
    main()
