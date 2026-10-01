#!/usr/bin/env python3
"""One-command, read-only preflight for the WebUI control-plane branch."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openwebui.tools.model_router import validate_router_config
from openwebui.tools.plugin_registry import validate_registry
from openwebui.tools.workspace_pipeline import validate_pipeline_config
from openwebui.tools.credit_control import validate_policy
from scripts.validate_workspace_runtime_contract import validate as validate_workspace_contract


CONFIG_FILES = [
    "webui-control/workspaces.json",
    "webui-control/agent-contract.json",
    "webui-control/handoff-schema.json",
    "webui-control/model-router.json",
    "webui-control/plugin-registry.json",
    "webui-control/automation-run-schema.json",
    "webui-control/shift-handoff-schema.json",
    "webui-control/books-pipeline.json",
    "webui-control/you-heal-pipeline.json",
    "webui-control/dashboard-schema.json",
    "webui-control/credit-policy.json",
    "webui-control/morning-human-actions.json",
    "webui-control/server-target.json",
    "webui-control/t212-methodology.json",
    "webui-control/t212-risk-controls.json",
    "webui-control/t212-failure-taxonomy.json",
    "webui-control/trade-proposal.schema.json",
    "webui-control/nontrading-model-bindings.json",
    "webui-control/workspace-runtime-contract.json",
    "webui-control/t212-implementation-map.json",
    "webui-control/release-manifest.json",
]


def load_json(relative: str) -> dict:
    with (ROOT / relative).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_server_target(config: dict) -> None:
    required = (
        "repository_checkout",
        "runtime_target",
        "state_target",
        "openwebui_container",
        "openwebui_data_dir",
    )
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise ValueError(f"server target missing fields: {', '.join(missing)}")
    for key in ("repository_checkout", "runtime_target", "state_target", "openwebui_data_dir"):
        value = config[key]
        if not isinstance(value, str) or not value.startswith("/") or ".." in Path(value).parts:
            raise ValueError(f"server target has unsafe path for {key}")
    if config["repository_checkout"] == config["runtime_target"]:
        raise ValueError("server target must distinguish source checkout from runtime target")


def validate_t212_methodology(config: dict) -> None:
    safety = config.get("safety") or {}
    if safety.get("environment") != "DEMO":
        raise ValueError("T212 methodology must remain DEMO")
    if safety.get("live_trading") is not False:
        raise ValueError("T212 methodology must keep live trading disabled")
    if safety.get("order_mutation_during_control_validation") is not False:
        raise ValueError("T212 methodology must deny order mutation during control validation")
    if safety.get("fail_closed_on_stale_or_missing_data") is not True:
        raise ValueError("T212 methodology must fail closed on stale or missing data")

    required_lifecycle = [
        "DISCOVERY",
        "QUALIFICATION",
        "CATALYST_VERIFIED",
        "RISK_GATED",
        "PROPOSAL",
        "HUMAN_APPROVAL",
        "DEMO_EXECUTION",
        "BROKER_VERIFICATION",
        "MONITORING",
        "EXIT",
        "REVIEW",
    ]
    if config.get("lifecycle") != required_lifecycle:
        raise ValueError("T212 lifecycle is incomplete or out of sequence")

    evidence = config.get("evidence_rules") or {}
    if evidence.get("no_operational_success_from_prompt_or_config_alone") is not True:
        raise ValueError("T212 evidence rules must reject prompt-only success claims")
    if evidence.get("no_fill_or_position_claim_without_broker_evidence") is not True:
        raise ValueError("T212 evidence rules must require broker verification")


def validate_risk_controls(config: dict) -> None:
    if config.get("environment") != "DEMO":
        raise ValueError("risk controls must remain DEMO")
    controls = config.get("controls") or {}
    if controls.get("long_only") is not True or controls.get("shorting") is not False:
        raise ValueError("risk controls must remain long-only with shorting disabled")
    if controls.get("max_concurrent_positions") != 3:
        raise ValueError("recovered max concurrent position control drifted")
    if float(controls.get("normal_session_spread_ceiling_pct_midpoint", -1)) != 2.5:
        raise ValueError("recovered spread ceiling drifted")
    if controls.get("averaging_down") is not False:
        raise ValueError("averaging down must remain disabled")
    authority = config.get("portfolio_authority") or {}
    if authority.get("broker_truth_authoritative") is not True:
        raise ValueError("broker truth must remain authoritative")
    if authority.get("shared_cash_risk_positions_pool") is not True:
        raise ValueError("UK/US controllers must share one cash/risk pool")


def validate_failure_taxonomy(config: dict) -> None:
    required = {"DATA", "MARKET", "STRATEGY", "T212_API", "TOOL", "AUTH", "ORCHESTRATION", "EXECUTION", "VERIFICATION", "HUMAN_ACTION"}
    if not required.issubset(set(config.get("operational_failure_codes") or [])):
        raise ValueError("operational failure taxonomy is incomplete")
    rules = config.get("rules") or {}
    if rules.get("no_silent_retry") is not True:
        raise ValueError("failure taxonomy must prohibit silent retry")
    if rules.get("no_advancing_past_failed_gate") is not True:
        raise ValueError("failure taxonomy must stop at failed gate")


def validate_trade_proposal_schema(config: dict) -> None:
    required = set(config.get("required") or [])
    for field in ("proposal_id", "t212_ticker", "catalyst_evidence", "risk_stop", "approval_state", "execution_state", "safety"):
        if field not in required:
            raise ValueError(f"trade proposal schema missing {field}")
    safety = ((config.get("properties") or {}).get("safety") or {}).get("properties") or {}
    if (safety.get("environment") or {}).get("const") != "DEMO":
        raise ValueError("trade proposal schema must constrain environment to DEMO")
    if (safety.get("live_trading") or {}).get("const") is not False:
        raise ValueError("trade proposal schema must constrain LIVE trading to false")


def main() -> int:
    report = {
        "status": "PASS",
        "live_effect": False,
        "configs_checked": [],
        "components_checked": [],
        "tests_run": 0,
        "failures": [],
        "trading": {
            "environment": "DEMO",
            "live_trading": False,
            "order_mutation": False,
        },
        "server_target": {},
        "methodology_version": None,
        "risk_controls_version": None,
    }

    configs: dict[str, dict] = {}
    for relative in CONFIG_FILES:
        try:
            configs[relative] = load_json(relative)
            report["configs_checked"].append(relative)
        except (OSError, json.JSONDecodeError) as exc:
            report["failures"].append(f"{relative}: {exc}")

    if not report["failures"]:
        try:
            validate_router_config(configs["webui-control/model-router.json"])
            validate_registry(configs["webui-control/plugin-registry.json"])
            validate_pipeline_config(configs["webui-control/books-pipeline.json"])
            validate_pipeline_config(configs["webui-control/you-heal-pipeline.json"])
            validate_policy(configs["webui-control/credit-policy.json"])
            validate_server_target(configs["webui-control/server-target.json"])
            validate_t212_methodology(configs["webui-control/t212-methodology.json"])
            validate_risk_controls(configs["webui-control/t212-risk-controls.json"])
            validate_failure_taxonomy(configs["webui-control/t212-failure-taxonomy.json"])
            validate_trade_proposal_schema(configs["webui-control/trade-proposal.schema.json"])
            workspace_report = validate_workspace_contract()
            if workspace_report.get("status") != "PASS":
                raise ValueError("workspace runtime contract validation failed: " + "; ".join(workspace_report.get("failures", [])))
            target = configs["webui-control/server-target.json"]
            report["server_target"] = {
                "repository_checkout": target["repository_checkout"],
                "runtime_target": target["runtime_target"],
                "state_target": target["state_target"],
            }
            report["methodology_version"] = configs["webui-control/t212-methodology.json"].get("version")
            report["risk_controls_version"] = configs["webui-control/t212-risk-controls.json"].get("version")
        except (ValueError, TypeError) as exc:
            report["failures"].append(f"control config: {exc}")

    manifest = configs.get("webui-control/release-manifest.json", {})
    for component in manifest.get("components", []):
        for key in ("config", "code"):
            relative = component.get(key)
            if relative and not (ROOT / relative).is_file():
                report["failures"].append(
                    f'{component.get("id", "unknown")}: missing {key} {relative}'
                )
        report["components_checked"].append(component.get("id"))

    trading = manifest.get("trading_safety", {})
    if (
        trading.get("environment") != "DEMO"
        or trading.get("live_trading") is not False
        or trading.get("order_mutation_during_control_plane_validation") is not False
        or trading.get("fail_closed") is not True
    ):
        report["failures"].append("release manifest violates T212 DEMO safety")

    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(suite)
    report["tests_run"] = result.testsRun
    if not result.wasSuccessful():
        report["failures"].append(
            f"unit tests: {len(result.failures)} failures, {len(result.errors)} errors"
        )

    if report["failures"]:
        report["status"] = "FAIL"

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
