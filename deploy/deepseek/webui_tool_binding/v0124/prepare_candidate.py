#!/usr/bin/env python3
"""Isolated Open WebUI 0.12.4 custom-image staging. NO production changes.

Run as the authorized Contabo operator after backing up WebUI. Extracts the
ALREADY DEPLOYED automation/tool-binding fix from the running v0.12.3 image
and ports only that fix onto the official pinned v0.12.4 image. Refuses
unexpected source changes. No model/broker requests, data migrations,
Compose edits, production restarts, or secret reads.
"""
import ast
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path("/home/katie/webui-v0124-stage-20261025")
OLD_IMAGE = "local/open-webui-toolbinding-v0123-stage:20261020"
OLD_ID = "sha256:7d8d04ead2b7c38d99b12b80a777b6030f3c694c491ca93e6bb010b5c3e82483"
NEW_SOURCE = "ghcr.io/open-webui/open-webui@sha256:a5b9e403d19154796850679c8c5d1295301cee954be8b84ddd62af92426558f7"
NEW_TAG = "local/open-webui-toolbinding-v0124-stage:20261025"
PACKAGE = "/app/backend/open_webui/utils"
AUT_BEGIN = "    meta = ((model.get('info') or {}).get('meta') or {})"
AUT_END = "\n    defaults = {"
UPSTREAM_AUT = "    meta = model.get('info', {}).get('meta', {})\n"
MIDDLE_BEGIN = "        # The model must receive the functions configured for this automation."
MIDDLE_END = "        if tools_dict:\n"

def cmd(*args):
    print("STAGE_STEP", args[0], flush=True)
    subprocess.run(args, check=True)

def capture(*args):
    return subprocess.check_output(args, text=True).strip()

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def require(value, reason):
    if not value:
        raise RuntimeError(reason)

def take(container, name, dest):
    cmd("docker", "cp", f"{container}:{PACKAGE}/{name}", str(dest))

def build_sources():
    live = capture("docker", "inspect", "-f", "{{.Image}}", "open-webui")
    require(live == OLD_ID, "Production container image drift: STOP")
    require(capture("docker", "inspect", "-f", "{{.State.Health.Status}}", "open-webui") == "healthy", "Production not healthy: STOP")
    require(capture("docker", "image", "inspect", "-f", "{{.Id}}", OLD_IMAGE) == OLD_ID, "Old image ID drift")
    require(capture("docker", "image", "inspect", "-f", "{{.Id}}", NEW_SOURCE) == "sha256:a5b9e403d19154796850679c8c5d1295301cee954be8b84ddd62af92426558f7", "Official 0.12.4 image digest mismatch")
    require(not ROOT.exists(), "Candidate stage directory already exists: inspect manually, do not overwrite")
    ROOT.mkdir(mode=0o700, parents=True)
    old, up, out = (ROOT / d for d in ("installed", "upstream", "candidate"))
    for directory in (old, up, out):
        directory.mkdir(mode=0o700)

    for name in ("automations.py", "middleware.py", "automation_tool_contract.py"):
        take("open-webui", name, old / name)

    ident = capture("docker", "create", NEW_SOURCE)
    try:
        for name in ("automations.py", "middleware.py"):
            take(ident, name, up / name)
    finally:
        cmd("docker", "rm", ident)

    existing = (old / "automations.py").read_text()
    upstream = (up / "automations.py").read_text()
    require(existing.count(AUT_BEGIN) == 1 and existing.count(AUT_END) >= 1, "Unexpected deployed automation patch")
    first = existing.index(AUT_BEGIN)
    last = existing.index(AUT_END, first)
    addition = existing[first:last]
    require("persisted_tool_ids" in addition and "refresh model registry before running" in addition, "Missing proven automation-binding fix")
    require(upstream.count(UPSTREAM_AUT) == 1, "0.12.4 automation source changed; manual code review needed")
    candidate_auto = upstream.replace(UPSTREAM_AUT, addition + "\n", 1)

    existing = (old / "middleware.py").read_text()
    upstream = (up / "middleware.py").read_text()
    require(existing.count(MIDDLE_BEGIN) == 1, "Unexpected deployed middleware patch")
    first = existing.index(MIDDLE_BEGIN)
    last = existing.index(MIDDLE_END, first)
    addition = existing[first:last]
    require("assess_automation_tools" in addition and "capability_manifest" in addition
            and "raise RuntimeError" in addition, "Missing proven middleware tool-contract fix")
    require(upstream.count(MIDDLE_END) == 1, "0.12.4 middleware tool-resolution anchor changed; manual review needed")
    require("await apply_tool_search(" in upstream, "Missing upstream deferred tool search")
    candidate_middle = upstream.replace(MIDDLE_END, addition + MIDDLE_END, 1)

    for name, source in (("automations.py", candidate_auto),
                         ("middleware.py", candidate_middle)):
        ast.parse(source, filename=name)
        (out / name).write_text(source)

    shutil.copy2(old / "automation_tool_contract.py", out / "automation_tool_contract.py")
    ast.parse((out / "automation_tool_contract.py").read_text(), filename="automation_tool_contract.py")
    require("async def execute_automation(" in candidate_auto, "Missing scheduler entrypoint")
    require("await _record_run(automation.id, 'success'" in candidate_auto,
            "Missing upstream terminal-success accounting")
    require("await apply_tool_search(" in candidate_middle,
            "Missing 0.12.4 tool-search dispatch")
    for path in sorted(out.iterdir()):
        print("CANDIDATE_SOURCE_SHA256", path.name, sha(path), flush=True)
    (ROOT / "Dockerfile").write_text(
        "FROM " + NEW_SOURCE + "\n"
        "COPY candidate/automations.py /app/backend/open_webui/utils/automations.py\n"
        "COPY candidate/middleware.py /app/backend/open_webui/utils/middleware.py\n"
        "COPY candidate/automation_tool_contract.py /app/backend/open_webui/utils/automation_tool_contract.py\n"
    )

def build_and_smoke():
    cmd("docker", "build", "--pull=false", "-t", NEW_TAG, str(ROOT))
    verify = """
import ast, pathlib, sys
assert sys.version_info[:2] == (3,12), sys.version
root=pathlib.Path('/app/backend/open_webui/utils')
for name in ('automations.py','middleware.py','automation_tool_contract.py'):
    ast.parse((root/name).read_text(),filename=name)
import open_webui.utils.automation_tool_contract as contract
assert hasattr(contract,'assess_automation_tools')
import open_webui.utils.automations as automations
assert hasattr(automations,'execute_automation')
print('V0124_IMAGE_IMPORT_PASS Python',sys.version.split()[0],flush=True)
"""
    cmd("docker", "run", "--rm", "--network", "none", "--read-only",
        "--tmpfs", "/tmp:rw,nosuid,size=128m", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--entrypoint", "python", NEW_TAG, "-c", verify)
    require(capture("docker", "inspect", "-f", "{{.Image}}", "open-webui") == OLD_ID,
            "Production image unexpectedly changed")
    print("V0124_CANDIDATE_STATIC_PASS", "image_id",
          capture("docker", "image", "inspect", "-f", "{{.Id}}", NEW_TAG), flush=True)
    print("PRODUCTION_UNCHANGED stage_only_no_database_or_broker_access", flush=True)

if __name__ == "__main__":
    os.umask(0o077)
    try:
        build_sources()
        build_and_smoke()
    except (OSError, RuntimeError, subprocess.CalledProcessError, SyntaxError) as exc:
        print("V0124_STAGE_BLOCKED", type(exc).__name__, str(exc)[:400], flush=True)
        sys.exit(1)
