#!/usr/bin/env python3
"""Run the read-only T212 DEMO pre-open evidence and readiness sequence.

The bundle makes no provider, model or broker call and has no order authority.
It writes only three evidence artifacts: runtime inventory, trading dashboard and
the fail-closed pre-open gate.  A missing, stale or unsafe dependency produces
NO_GO and exit code 2.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
from typing import Any, Callable

from scripts.build_preopen_readiness import atomic_json as write_gate
from scripts.build_preopen_readiness import build_gate, load_object
from scripts.build_trading_dashboard import atomic_json as write_dashboard
from scripts.build_trading_dashboard import build_from_state


DEFAULT_STATE = Path(os.getenv("T212_SCANNER_STATE_DIR", "/var/lib/t212-scanner"))


def write_runtime(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def run_bundle(
    *,
    state_dir: Path,
    bindings: Path,
    acceptance_evidence: Path,
    runtime_output: Path,
    dashboard_output: Path,
    gate_output: Path,
    generated_at: str | None = None,
    collect_runtime: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if collect_runtime is None:
        from scripts.collect_runtime_evidence import collect

        collect_runtime = collect
    runtime = collect_runtime()
    write_runtime(runtime_output, runtime)

    pipeline_error = None
    dashboard = None
    try:
        dashboard = build_from_state(
            state_dir, bindings_path=bindings, generated_at=generated_at
        )
        write_dashboard(dashboard_output, dashboard)
    except Exception as exc:  # Preserve NO_GO evidence instead of losing the gate.
        pipeline_error = f"{type(exc).__name__}: {exc}"

    gate = build_gate(
        runtime,
        dashboard,
        load_object(acceptance_evidence),
        generated_at=generated_at,
    )
    gate["evidence_paths"] = {
        "runtime": str(runtime_output),
        "dashboard": str(dashboard_output),
        "acceptance": str(acceptance_evidence),
        "gate": str(gate_output),
    }
    gate["pipeline_error"] = pipeline_error
    gate["side_effects"] = {
        "provider_calls": 0,
        "model_calls": 0,
        "broker_calls": 0,
        "order_actions": 0,
        "writes": [str(runtime_output), str(dashboard_output), str(gate_output)],
    }
    if pipeline_error:
        gate["decision"] = "NO_GO"
        gate["statement"] = "NO_GO: the evidence pipeline did not complete."
    write_gate(gate_output, gate)
    return gate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    parser.add_argument(
        "--bindings", type=Path,
        default=Path(__file__).resolve().parents[1] / "webui-control" / "t212-agent-bindings.json",
    )
    parser.add_argument(
        "--acceptance-evidence", type=Path,
        default=DEFAULT_STATE / "preopen_acceptance_evidence.json",
    )
    parser.add_argument("--runtime-output", type=Path, default=DEFAULT_STATE / "runtime_evidence.json")
    parser.add_argument("--dashboard-output", type=Path, default=DEFAULT_STATE / "trading_dashboard_latest.json")
    parser.add_argument("--gate-output", type=Path, default=DEFAULT_STATE / "preopen_readiness_latest.json")
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_STATE / "preopen_assurance.lock")
    parser.add_argument("--generated-at", help="Timezone-aware test/inspection timestamp.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.lock_file.parent.mkdir(parents=True, exist_ok=True)
    with args.lock_file.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({
                "decision": "NO_GO", "reason": "preopen_assurance_already_running",
                "orders_submitted": 0,
            }, sort_keys=True))
            return 3
        gate = run_bundle(
            state_dir=args.state_dir,
            bindings=args.bindings,
            acceptance_evidence=args.acceptance_evidence,
            runtime_output=args.runtime_output,
            dashboard_output=args.dashboard_output,
            gate_output=args.gate_output,
            generated_at=args.generated_at,
        )
    print(json.dumps({
        "decision": gate["decision"],
        "counts": gate["counts"],
        "orders_submitted": 0,
        "evidence_paths": gate["evidence_paths"],
    }, sort_keys=True))
    return 0 if gate["decision"] == "GO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
