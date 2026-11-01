#!/usr/bin/env python3
"""Rebase ONLY audited v0.11.4 automation tool-binding fix onto pinned v0.12.3.

This prepares source overlays in an isolated directory. Does not touch live
WebUI or any database.
"""
from pathlib import Path
import ast
import hashlib
import shutil

BASE = Path("/home/katie/webui-v0123-stage-20261020")
UP = BASE / "upstream"
OLD = BASE / "installed"
OUT = BASE / "candidate"

AUT_META = "    meta = model.get('info', {}).get('meta', {})\n"
AUT_END = "\n    defaults = {"
MIDDLE_ANCHOR = "        if tools_dict:\n"

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def rebase():
    assert digest(UP / "automations.py") == "cbc6e209cd9d6ddce8c959527804346b599e4c1f6cf0ec33c4221f4691389b74"
    assert digest(UP / "middleware.py") == "f241322f2a463a8ad49085ad8727665f94f1e37c017736041f47b99e991dcbb8"
    assert digest(OLD / "automations.py") == "099046d7633d8af5fac47af4c18bf3311918f5f13a2472a4449e56f331110c5f"
    assert digest(OLD / "middleware.py") == "8c907a84b41a6fee7991113dd868760217835cfd9e734632b1396ca857e68d69"

    upstream = (UP / "automations.py").read_text()
    previous = (OLD / "automations.py").read_text()
    begin = previous.index("    meta = ((model.get('info') or {}).get('meta') or {})")
    end = previous.index(AUT_END, begin)
    retained = previous[begin:end]
    assert retained.count("persisted_tool_ids") >= 3
    assert "refresh model registry before running" in retained
    assert upstream.count(AUT_META) == 1
    staged_automation = upstream.replace(AUT_META, retained+"\n", 1)

    upstream = (UP / "middleware.py").read_text()
    previous = (OLD / "middleware.py").read_text()
    begin = previous.index("        # The model must receive the functions configured for this automation.")
    end = previous.index(MIDDLE_ANCHOR, begin)
    retained = previous[begin:end]
    assert "assess_automation_tools" in retained
    assert "raise RuntimeError" in retained
    assert "capability_manifest" in retained
    assert upstream.count(MIDDLE_ANCHOR) == 1
    # Put check after all normal/tool-server/shell-tool resolution, before the
    # provider-facing native function/tool-search dispatch in v0.12.3.
    staged_middleware = upstream.replace(MIDDLE_ANCHOR, retained + MIDDLE_ANCHOR, 1)

    OUT.mkdir(parents=True,exist_ok=True)
    for name,source in (("automations.py",staged_automation),
                        ("middleware.py",staged_middleware)):
        ast.parse(source)
        (OUT / name).write_text(source)
    shutil.copy2(OLD/"automation_tool_contract.py",OUT/"automation_tool_contract.py")
    assert ast.parse((OUT/"automation_tool_contract.py").read_text())
    # Key upstream behavior is retained rather than reverting v0.12.3 to 0.11.4.
    assert "await apply_tool_search(" in staged_middleware
    assert "async def execute_automation(" in staged_automation
    assert "await _record_run(automation.id, 'success'" in staged_automation
    print("REBASE_PASS: 3 version-matched candidate Python modules",flush=True)
    for p in sorted(OUT.glob("*.py")):
        print("CANDIDATE_FILE",p.name,"SHA256",digest(p),flush=True)

if __name__=="__main__":
    rebase()
