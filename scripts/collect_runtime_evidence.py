#!/usr/bin/env python3
"""Collect non-secret runtime evidence for the WebUI/T212 control plane.

Read-only: no container restart, no database writes, no systemd mutations,
no broker calls and no secret/environment inspection.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=False)


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def systemd_state(unit: str) -> dict[str, Any]:
    active = run(["systemctl", "is-active", unit])
    enabled = run(["systemctl", "is-enabled", unit])
    return {
        "unit": unit,
        "active": active.stdout.strip() if active.stdout else "unknown",
        "enabled": enabled.stdout.strip() if enabled.stdout else "unknown",
    }


def file_summary(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"name": path.name, "present": False}
    stat = path.stat()
    return {
        "name": path.name,
        "present": True,
        "size_bytes": stat.st_size,
        "age_seconds": round(max(0.0, time.time() - stat.st_mtime), 2),
    }


def query_openwebui(container: str, data_dir: str) -> dict[str, Any]:
    py = r'''
import json, sqlite3
db_path = DATA_DIR + "/webui.db"
db = sqlite3.connect("file:" + db_path + "?mode=ro", uri=True)
db.row_factory = sqlite3.Row
out = {"tools": [], "models": [], "skills": []}
for row in db.execute("SELECT id,name FROM tool ORDER BY name"):
    out["tools"].append({"id": row["id"], "name": row["name"]})
for row in db.execute("SELECT id,name,is_active FROM skill ORDER BY name"):
    out["skills"].append({"id": row["id"], "name": row["name"], "is_active": bool(row["is_active"])})
for row in db.execute("SELECT id,name,meta FROM model ORDER BY name"):
    meta = {}
    try:
        meta = json.loads(row["meta"] or "{}")
    except Exception:
        pass
    knowledge = []
    for item in meta.get("knowledge") or []:
        if isinstance(item, dict):
            knowledge.append({"id": item.get("id"), "name": item.get("name")})
    out["models"].append({
        "id": row["id"],
        "name": row["name"],
        "toolIds": meta.get("toolIds") or [],
        "skillIds": meta.get("skillIds") or [],
        "knowledge": knowledge,
    })
print(json.dumps(out))
db.close()
'''.replace("DATA_DIR", repr(data_dir))
    result = run(["docker", "exec", container, "python3", "-c", py])
    if result.returncode != 0:
        return {"ok": False, "error": "OpenWebUI metadata query failed"}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": "OpenWebUI metadata query returned invalid JSON"}
    payload["ok"] = True
    return payload


def component(id_: str, *, deployed=False, running=False, callable_=False, evidence=None, blocker=None, next_action=None):
    return {
        "id": id_,
        "deployed": bool(deployed),
        "running": bool(running),
        "callable": bool(callable_),
        "last_verified": datetime.now(timezone.utc).isoformat(),
        "evidence": list(evidence or []),
        "blocker": blocker,
        "next_action": next_action,
    }


def binding_evidence(model_rows: dict[str, dict[str, Any]], bindings: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for spec in bindings.get("models", []):
        model_id = str(spec.get("id") or "")
        model = model_rows.get(model_id)
        required = {str(item) for item in (spec.get("required_skills") or [])}
        actual = {str(item) for item in ((model or {}).get("skillIds") or [])}
        missing = sorted(required - actual)
        rows.append({
            "model_id": model_id,
            "present": model is not None,
            "required_skill_ids": sorted(required),
            "actual_skill_ids": sorted(actual),
            "missing_skill_ids": missing,
            "complete": model is not None and not missing,
        })
    return rows


def collect() -> dict[str, Any]:
    target = load_json(ROOT / "webui-control" / "server-target.json", {})
    bindings = load_json(ROOT / "webui-control" / "nontrading-model-bindings.json", {})
    container = str(target.get("openwebui_container") or "open-webui")
    data_dir = str(target.get("openwebui_data_dir") or "/app/backend/data")
    state_dir = Path(str(target.get("state_target") or "/var/lib/t212-scanner"))

    running_result = run(["docker", "inspect", "-f", "{{.State.Running}}", container])
    container_running = running_result.returncode == 0 and running_result.stdout.strip().lower() == "true"
    image_result = run(["docker", "inspect", "-f", "{{.Config.Image}}", container])
    image = image_result.stdout.strip() if image_result.returncode == 0 else None

    webui = query_openwebui(container, data_dir) if container_running else {"ok": False, "error": "container not running"}
    tool_ids = {row.get("id") for row in webui.get("tools", []) if isinstance(row, dict)}
    active_skill_ids = {
        row.get("id")
        for row in webui.get("skills", [])
        if isinstance(row, dict) and row.get("id") and row.get("is_active") is True
    }
    model_rows = {
        row.get("id"): row
        for row in webui.get("models", [])
        if isinstance(row, dict) and row.get("id")
    }

    trading = model_rows.get("trading-operations--deepseek") or {}
    trading_tools = set(trading.get("toolIds") or [])
    trading_skills = set(trading.get("skillIds") or [])
    knowledge_names = {
        str(item.get("name"))
        for item in trading.get("knowledge") or []
        if isinstance(item, dict) and item.get("name")
    }
    binding_rows = binding_evidence(model_rows, bindings)

    required_models = {
        "trading-operations--deepseek",
        "apps-plugins-bots--deepseek",
        "you-heal-content-production--deepseek",
        "books-publishing--deepseek",
        "open-webui-site-configurator--deepseek",
    }
    required_tools = {
        "trading_212_demo_gateway_tool",
        "market_data_gateway",
        "open_webui_site_configurator",
    }
    model_coverage = sorted(required_models & set(model_rows))
    tool_coverage = sorted(required_tools & tool_ids)

    discovery_service = systemd_state("t212-discovery.service")
    discovery_timer = systemd_state("t212-discovery.timer")
    cache_timer = systemd_state("t212-cache-refresh.timer")
    eod_timer = systemd_state("t212-eod-audit.timer")

    status_file = file_summary(state_dir / "status.json")
    scan_file = file_summary(state_dir / "scanner_latest.json")
    cache_file = file_summary(state_dir / "t212_instrument_cache.json")
    cache_status_file = file_summary(state_dir / "t212_instrument_cache_status.json")
    automation_file = file_summary(state_dir / "automation_runs.jsonl")
    dashboard_file = file_summary(state_dir / "trading_dashboard_latest.json")

    webui_evidence = [
        f"container_running={container_running}",
        f"model_coverage={len(model_coverage)}/{len(required_models)}",
        f"tool_coverage={len(tool_coverage)}/{len(required_tools)}",
    ]

    components = [
        component(
            "workspace-registry",
            deployed=required_models.issubset(set(model_rows)),
            running=container_running,
            evidence=webui_evidence,
            next_action="prove each project model can respond and surface configured tools/skills/knowledge",
        ),
        component(
            "t212-methodology",
            deployed="Trading Operations Canonical v2" in knowledge_names,
            running=container_running,
            evidence=[f"knowledge={sorted(knowledge_names)}"],
            next_action="retain canonical v2 and reconcile/attach the prepared current methodology without deleting existing knowledge",
        ),
        component(
            "discovery-adapter",
            deployed=scan_file["present"] or discovery_service["active"] in {"active", "activating"},
            running=discovery_service["active"] in {"active", "activating"},
            evidence=[f"service_active={discovery_service['active']}", f"scan={scan_file}", f"cache_status={cache_status_file}"],
            blocker=None if scan_file["present"] else "no scanner runtime artifact found",
            next_action="run one manual read-only discovery cycle with fresh market/cache inputs",
        ),
        component(
            "discovery-worker",
            deployed=discovery_service["active"] not in {"unknown", "not-found"} or discovery_timer["enabled"] not in {"unknown", "not-found"},
            running=discovery_timer["active"] == "active",
            evidence=[f"service={discovery_service}", f"timer={discovery_timer}", f"status={status_file}"],
            next_action="validate worker manually before any timer enablement",
        ),
        component(
            "automation-ledger",
            deployed=automation_file["present"],
            running=automation_file["present"] and automation_file.get("size_bytes", 0) > 0,
            evidence=[f"automation_ledger={automation_file}"],
            next_action="produce a verified discovery run and confirm ledger append",
        ),
        component(
            "nontrading-model-bindings",
            deployed=bool(binding_rows) and all(row["complete"] for row in binding_rows),
            running=container_running,
            evidence=[
                f"{row['model_id']}:missing={row['missing_skill_ids']}"
                for row in binding_rows
            ],
            blocker=None if binding_rows and all(row["complete"] for row in binding_rows) else "one or more non-trading model skill bindings are incomplete",
            next_action="use Configurator audit/export then apply additive preserve-all-fields binding patch",
        ),
        component(
            "managed-skills",
            deployed=all(
                skill in active_skill_ids
                for skill in {
                    "trading-cito-orchestrator",
                    "market-intelligence",
                    "trading-decision-engine",
                    "execution-position-control",
                    "learning-qa",
                    "shared-portfolio-ledger",
                    "trading-operations-dashboard",
                    "autonomy-safety-guardrails",
                }
            ),
            running=container_running,
            evidence=[f"active_skill_count={len(active_skill_ids)}"],
            next_action="install/update only managed GitHub skill assets that differ from audited runtime",
        ),
        component(
            "model-router",
            evidence=["no runtime registration evidence collected for model-router"],
            next_action="register through bounded OpenWebUI integration path and prove call routing",
        ),
        component(
            "plugin-registry",
            evidence=["no runtime registration evidence collected for plugin-registry"],
            next_action="register through bounded OpenWebUI integration path and prove permission enforcement",
        ),
        component(
            "dashboard-snapshot",
            deployed=dashboard_file["present"],
            running=False,
            evidence=[f"trading_dashboard={dashboard_file}"],
            blocker=None if dashboard_file["present"] else "no trading dashboard runtime artifact found",
            next_action=(
                "inspect freshness and blocked evidence in trading_dashboard_latest.json"
                if dashboard_file["present"]
                else "run the read-only trading dashboard builder from verified state files"
            ),
        ),
        component(
            "shift-handoff",
            evidence=["no handoff runtime artifact collected"],
            next_action="generate handoff from verified runtime ledger evidence",
        ),
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "side_effects": "none",
        "container": {"name": container, "running": container_running, "image": image},
        "openwebui": {
            "metadata_query_ok": webui.get("ok") is True,
            "model_ids": sorted(model_rows),
            "tool_ids": sorted(tool_ids),
            "active_skill_ids": sorted(active_skill_ids),
            "trading_tool_ids": sorted(trading_tools),
            "trading_skill_ids": sorted(trading_skills),
            "trading_knowledge": sorted(knowledge_names),
            "nontrading_binding_audit": binding_rows,
        },
        "workers": {
            "discovery_service": discovery_service,
            "discovery_timer": discovery_timer,
            "cache_timer": cache_timer,
            "eod_timer": eod_timer,
        },
        "artifacts": {
            "status": status_file,
            "scan": scan_file,
            "instrument_cache": cache_file,
            "instrument_cache_status": cache_status_file,
            "automation_ledger": automation_file,
            "trading_dashboard": dashboard_file,
        },
        "components": components,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="Optional JSON output path.")
    args = parser.parse_args()
    payload = collect()
    encoded = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
