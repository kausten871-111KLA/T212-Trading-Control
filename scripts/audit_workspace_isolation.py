#!/usr/bin/env python3
"""Static workspace isolation audit for the staged connector/control registry.

Repository-only and read-only. This does not prove runtime enforcement, but it
fails if staged policy grants obviously forbidden cross-workspace access.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load(relative: str) -> dict[str, Any]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def main() -> int:
    registry = load("webui-control/plugin-registry.json")
    bindings = load("webui-control/nontrading-model-bindings.json")
    failures = []
    checks = []

    connectors = {row.get("id"): row for row in registry.get("connectors", [])}
    t212 = connectors.get("t212-demo-readiness") or {}
    t212_access = set(t212.get("available_to") or [])
    checks.append({"check": "t212_workspace_scope", "actual": sorted(t212_access)})
    if t212_access != {"t212-demo"}:
        failures.append("T212 readiness connector must be available only to t212-demo")

    file_store = connectors.get("openwebui-file-store") or {}
    denied = set(file_store.get("denied_operations") or [])
    checks.append({"check": "file_store_denials", "actual": sorted(denied)})
    for required in ("delete_source_file", "overwrite_source_file", "cross_workspace_retrieval", "public_share"):
        if required not in denied:
            failures.append(f"file store missing denial: {required}")

    for connector in registry.get("connectors", []):
        secret_env = connector.get("secret_env") or []
        for value in secret_env:
            if not isinstance(value, str) or "=" in value:
                failures.append(f"{connector.get('id')}: secret registry contains value instead of env name")

    policy = bindings.get("policy") or {}
    if policy.get("publishing_enabled") is not False:
        failures.append("non-trading model bindings must not enable publishing")
    if policy.get("scheduling_changes_enabled") is not False:
        failures.append("non-trading model bindings must not enable scheduling changes")
    if policy.get("additive_only") is not True:
        failures.append("non-trading model bindings must remain additive-only")

    return_code = 0 if not failures else 1
    print(json.dumps({
        "status": "PASS" if not failures else "FAIL",
        "runtime_proof": False,
        "checks": checks,
        "failures": failures,
    }, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
