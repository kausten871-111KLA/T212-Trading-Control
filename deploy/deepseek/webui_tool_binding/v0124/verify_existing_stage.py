#!/usr/bin/env python3
"""Recheck v0.12.4 tool-resolution acceptance on an ALREADY verified stage copy.

This does NOT copy the full archive again. Only existing disposable staging
data is mounted; the original backup, production data volume, broker and
provider credentials are never mounted. Network disabled, no inference.
Run from a git worktree after fetching the intended exact branch HEAD.
"""
import ast
import os
from pathlib import Path
import secrets
import subprocess
import sys

IMAGE = "local/open-webui-toolbinding-v0124-stage:20261025"
OLD_ID = "sha256:7d8d04ead2b7c38d99b12b80a777b6030f3c694c491ca93e6bb010b5c3e82483"
STAGE = Path("/home/katie/webui-v0124-stage-20261025/data-test-retry-4")
SOURCE = "deploy/deepseek/webui_tool_binding/v0124/run_isolated_db_acceptance.py"

def out(args):
    return subprocess.check_output(args, text=True).strip()

def check():
    assert out(["docker", "inspect", "-f", "{{.Image}}", "open-webui"]) == OLD_ID, "Production image changed"
    assert out(["docker", "inspect", "-f", "{{.State.Health.Status}}", "open-webui"]) == "healthy", "Production unhealthy"
    assert STAGE.is_dir() and not STAGE.is_symlink(), "Existing isolated stage missing/unsafe"
    assert (STAGE/"webui.db").is_file() and not (STAGE/"webui.db").is_symlink(), "Stage database missing"
    source = out(["git", "show", "FETCH_HEAD:"+SOURCE])
    module = ast.parse(source, filename=SOURCE)
    checks = [n.value.value for n in module.body
              if isinstance(n, ast.Assign) and any(
                  isinstance(target, ast.Name) and target.id == "CHECK" for target in n.targets)
              and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)]
    assert len(checks) == 1, "Cannot locate current pinned CHECK source"
    assert 'assert len(got)>=30' in checks[0], "Missing minimum 30-function acceptance gate"
    env = dict(os.environ)
    env["WEBUI_SECRET_KEY"] = secrets.token_hex(32)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    cmd = [
        "docker", "run", "--rm", "-i", "--network", "none", "--read-only",
        "--tmpfs", "/tmp:rw,nosuid,size=128m",
        "--security-opt", "no-new-privileges",
        "--cpus", "2", "--memory", "3g",
        "-v", str(STAGE)+":/app/backend/data",
        "-e", "WEBUI_SECRET_KEY", "-e", "PYTHONDONTWRITEBYTECODE",
        "-e", "ENABLE_OLLAMA_API=false", "-e", "ENABLE_OPENAI_API=false",
        "--entrypoint", "python", IMAGE, "-"
    ]
    subprocess.run(cmd, input=checks[0], text=True, env=env, check=True)
    assert out(["docker", "inspect", "-f", "{{.Image}}", "open-webui"]) == OLD_ID
    assert out(["docker", "inspect", "-f", "{{.State.Health.Status}}", "open-webui"]) == "healthy"
    print("V0124_EXISTING_STAGE_RECHECK_PASS no_new_copy=True offline=True", flush=True)
    print("PRODUCTION_UNCHANGED staging_only", flush=True)

if __name__ == "__main__":
    try:
        check()
    except Exception as exc:
        print("V0124_EXISTING_STAGE_RECHECK_BLOCKED", type(exc).__name__, str(exc)[:500], flush=True)
        sys.exit(1)
