#!/usr/bin/env python3
"""Supervised additive update of the EXISTING Open WebUI market-data tool.

Run inside the existing WebUI container. Uses authenticated WebUI REST API,
not direct SQLite writes. Never invokes providers, brokers, models or crawlers.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request

MODEL = "trading-operations--deepseek"
TOOL = "market_data_gateway"
FUNCTION = "market_insights_discovery"
ANCHOR = "    async def market_insights_discovery("
CANDIDATE = Path("/tmp/market_data_gateway_candidate_v0124.py")
SNAPSHOT = Path("/app/backend/data/market_data_gateway_before_insights.json")
EXPECTED = {
    "trading_212_demo_gateway_tool", "market_data_gateway",
    "contabo_command_bridge", "trading_brain_research_context",
    "twelve_data_global_research",
}
JOBS = ("Morning Research Runner", "US CONTROLLER", "US OPEN", "US MIDDAY", "US CLOSE")

def fail(reason):
    raise RuntimeError(reason)

def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def api(method, path, data=None):
    token = os.environ.get("OPENWEBUI_ADMIN_API_KEY", "").strip()
    if not token:
        fail("admin_api_key_missing")
    if not path.startswith("/api/v1/"):
        fail("invalid_api_path")
    body = json.dumps(data).encode("utf-8") if data is not None else None
    request = urllib.request.Request(
        "http://127.0.0.1:8080" + path, data=body, method=method,
        headers={"Authorization": "Bearer " + token, "Accept": "application/json",
                 **({"Content-Type": "application/json"} if body is not None else {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            output = response.read()
            return json.loads(output) if output else None
    except urllib.error.HTTPError as exc:
        fail("webui_api_http_" + str(exc.code) + "_" + method)
    except urllib.error.URLError:
        fail("webui_api_unavailable")

def model_and_jobs():
    model = api("GET", "/api/v1/models/model?id=" + urllib.parse.quote(MODEL))
    ids = ((model or {}).get("meta") or {}).get("toolIds") or []
    if not model or not model.get("is_active") or len(ids) != 5 or set(ids) != EXPECTED:
        fail("existing_owner_model_or_five_tool_bindings_changed")
    db = sqlite3.connect("file:/app/backend/data/webui.db?mode=ro", uri=True)
    try:
        all_rows = db.execute("select name,is_active,data from automation").fetchall()
    finally:
        db.close()
    relevant = []
    for name, enabled, raw in all_rows:
        try:
            info = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if info.get("model_id") == MODEL:
            relevant.append((name, enabled, raw))
    if len(relevant) != 5 or not all(r[1] for r in relevant):
        fail("existing_five_automations_changed")
    for prefix in JOBS:
        if sum(row[0].startswith(prefix) for row in relevant) != 1:
            fail("missing_or_duplicate_automation_" + prefix)
    return sha(json.dumps(sorted(relevant))), ids

def live_tool():
    tool = api("GET", "/api/v1/tools/id/" + TOOL)
    if not tool or tool.get("id") != TOOL or not isinstance(tool.get("content"), str):
        fail("existing_market_data_gateway_missing")
    return tool

def new_content(tool):
    if CANDIDATE.is_symlink() or not CANDIDATE.is_file():
        fail("candidate_source_not_staged")
    candidate = CANDIDATE.read_text(encoding="utf-8")
    if candidate.count(ANCHOR) != 1 or candidate.count("class Tools:") != 1:
        fail("unexpected_candidate_method")
    compile(candidate, str(CANDIDATE), "exec")
    before, method = candidate.split(ANCHOR, 1)
    old = tool["content"]
    if ANCHOR in old:
        fail("function_already_installed")
    # A deliberate content-drift gate: preserve all previously installed code.
    if old.strip() != before.strip():
        # Approved one-field rebase for the v0.12.4 live gateway.
        # Fail closed unless adding previousVolume exactly reproduces
        # the AST of the already reviewed candidate base.
        original_key = '            "previousClose": prev_close,\n'
        volume_key = '            "previousVolume": prev_bar.get("v"),\n'
        if old.count(original_key) != 1 or volume_key in old:
            fail("existing_tool_differs_from_candidate_base_stop")
        rebased = old.replace(original_key, original_key + volume_key, 1)
        if ast.dump(ast.parse(rebased), include_attributes=False) != ast.dump(
            ast.parse(before), include_attributes=False
        ):
            fail("existing_tool_differs_from_candidate_base_stop")
        old = rebased
        print("SOURCE_REBASE_PASS", "reviewed_previous_volume_only", flush=True)
    addition = ANCHOR + method
    if "await self.candidate_scan(" not in addition or '"orders_submitted_by_tool": 0' not in addition:
        fail("unreviewed_discovery_method")
    updated = old.rstrip() + "\n\n" + addition
    compile(updated, "<proposed_additive_gateway>", "exec")
    return updated

def preflight():
    digest, ids = model_and_jobs()
    tool = live_tool()
    source = new_content(tool)
    names = [x.get("name") for x in tool.get("specs") or []]
    if not names or len(names) != len(set(names)) or FUNCTION in names:
        fail("existing_gateway_specs_unexpected")
    if SNAPSHOT.exists():
        fail("previous_upgrade_manifest_exists")
    print("MARKET_INSIGHTS_PREFLIGHT_PASS", "five_model_tool_ids", len(ids),
          "five_automations", 5, "previous_functions", len(names),
          "current_sha256", sha(tool["content"]), "candidate_sha256", sha(source),
          "schedule_digest", digest, "provider_calls", 0, "orders", 0, flush=True)
    return digest, tool, source, names

def manifest():
    if not SNAPSHOT.is_file() or SNAPSHOT.is_symlink():
        fail("upgrade_snapshot_missing")
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))

def verify():
    saved = manifest()
    current_digest, ids = model_and_jobs()
    if current_digest != saved["schedule_digest"]:
        fail("existing_automations_changed_during_upgrade")
    tool = live_tool()
    if sha(tool["content"]) != saved["new_sha256"]:
        fail("new_tool_content_not_active")
    methods = [x.get("name") for x in tool.get("specs") or []]
    if methods != saved["previous_specs"] + [FUNCTION]:
        fail("new_function_not_resolved_by_webui")
    print("MARKET_INSIGHTS_VERIFY_PASS", FUNCTION, "five_tools", len(ids),
          "five_jobs", 5, "market_gateway_functions", len(methods), flush=True)

def install():
    digest, tool, new, names = preflight()
    saved = {"before": {k:tool[k] for k in ("id","name","content","meta")},
             "previous_specs": names, "schedule_digest": digest,
             "old_sha256": sha(tool["content"]), "new_sha256": sha(new)}
    fd = os.open(SNAPSHOT, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(saved, stream)
    response = api("POST", "/api/v1/tools/id/" + TOOL + "/update",
                   {"id": TOOL, "name": tool["name"], "content": new,
                    "meta": tool["meta"],
                    "commit_message": "Add Alpaca discovery to existing trading market gateway"})
    if not response or response.get("id") != TOOL:
        fail("admin_api_update_not_confirmed")
    print("MARKET_INSIGHTS_INSTALL_SUBMITTED", "rollback_snapshot_saved", flush=True)
    verify()

def rollback():
    saved = manifest()
    digest, ids = model_and_jobs()
    if digest != saved["schedule_digest"]:
        fail("automation_configuration_drift_refuse_rollback")
    tool = live_tool()
    if sha(tool["content"]) == saved["old_sha256"]:
        print("MARKET_INSIGHTS_ALREADY_ORIGINAL", flush=True)
        return
    if sha(tool["content"]) != saved["new_sha256"]:
        fail("tool_changed_since_install_refuse_rollback")
    old = saved["before"]
    api("POST", "/api/v1/tools/id/" + TOOL + "/update",
        {"id": TOOL, "name": old["name"], "content": old["content"],
         "meta": old["meta"], "commit_message": "Restore previous market gateway"})
    if sha(live_tool()["content"]) != saved["old_sha256"]:
        fail("rollback_verification_failed")
    print("MARKET_INSIGHTS_ROLLBACK_PASS", "five_tools", len(ids), flush=True)

if __name__ == "__main__":
    os.umask(0o077)
    try:
        if "--key-stdin" in sys.argv:
            supplied = sys.stdin.readline().strip()
            if not supplied.startswith("sk-") or len(supplied) < 25:
                fail("invalid_operator_key_format")
            os.environ["OPENWEBUI_ADMIN_API_KEY"] = supplied
            sys.argv.remove("--key-stdin")
        action = sys.argv[1] if len(sys.argv) > 1 else "preflight"
        if action == "preflight":
            preflight()
        elif action == "install":
            install()
        elif action == "verify":
            verify()
        elif action == "rollback":
            rollback()
        else:
            fail("unknown_action_use_preflight_install_verify_rollback")
    except Exception as exc:
        print("MARKET_INSIGHTS_BLOCKED", type(exc).__name__, str(exc)[:260], flush=True)
        sys.exit(1)
