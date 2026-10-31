#!/usr/bin/env python3
"""No-network/no-data acceptance of the pinned v0.12.4 custom Docker image.

Feed this file to an isolated candidate container's Python stdin. Generate a
DISPOSABLE WebUI secret outside the script; never mount production DB, tokens,
host Docker socket, broker credentials or data.
"""
import ast
import hashlib
import os
from pathlib import Path
import sys

assert sys.version_info[:2] == (3, 12), f"Unexpected Python: {sys.version}"
assert len(os.environ.get("WEBUI_SECRET_KEY", "")) >= 48, "Disposable WEBUI_SECRET_KEY missing"
root = Path("/app/backend/open_webui/utils")
expected = {
    "automations.py": "e3013aa1e876e6321e7bc512be6c816142c558f685f427eae4d2e8097dc025e8",
    "middleware.py": "b49bc30bd642adf56fcfcca6938595313bc883bfd227396bedf263f459462a62",
    "automation_tool_contract.py": "c7af916b301cf507a613493614068ce5cdde6e1905d92aa7517f62d67e6fb62f",
}
for name, digest in expected.items():
    path = root / name
    source = path.read_bytes()
    assert hashlib.sha256(source).hexdigest() == digest, f"Unexpected candidate source {name}"
    ast.parse(source.decode("utf8"), filename=name)

import open_webui.utils.automation_tool_contract as contract
assert hasattr(contract, "assess_automation_tools")
import open_webui.utils.automations as automations
assert hasattr(automations, "execute_automation")
assert hasattr(automations, "_resolve_model_defaults")
import open_webui.utils.middleware as middleware
assert middleware is not None
print("V0124_IMAGE_IMPORT_PASS", "python", sys.version.split()[0],
      "custom_files", len(expected), "offline", True, flush=True)
