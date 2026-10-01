"""Deterministic lifecycle validator for T212 DEMO trading operations.

This module does not submit orders. It enforces allowed state transitions and
broker-evidence requirements so research/configuration cannot be mislabeled as
execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


STATES = {
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
    "REJECTED",
    "BLOCKED",
}

ALLOWED_TRANSITIONS = {
    "DISCOVERY": {"QUALIFICATION", "REJECTED"},
    "QUALIFICATION": {"CATALYST_VERIFIED", "REJECTED", "BLOCKED"},
    "CATALYST_VERIFIED": {"RISK_GATED", "REJECTED", "BLOCKED"},
    "RISK_GATED": {"PROPOSAL", "REJECTED", "BLOCKED"},
    "PROPOSAL": {"HUMAN_APPROVAL", "REJECTED", "BLOCKED"},
    "HUMAN_APPROVAL": {"DEMO_EXECUTION", "REJECTED", "BLOCKED"},
    "DEMO_EXECUTION": {"BROKER_VERIFICATION", "BLOCKED"},
    "BROKER_VERIFICATION": {"MONITORING", "BLOCKED"},
    "MONITORING": {"EXIT", "BLOCKED"},
    "EXIT": {"REVIEW", "BLOCKED"},
    "REJECTED": {"REVIEW"},
    "BLOCKED": set(),
    "REVIEW": set(),
}


class TradingStateError(ValueError):
    pass


@dataclass(frozen=True)
class TransitionEvidence:
    source: str
    refs: tuple[str, ...]


def _bool(record: Mapping[str, Any], key: str) -> bool:
    return record.get(key) is True


def validate_transition(
    current: str,
    target: str,
    record: Mapping[str, Any],
) -> None:
    current = str(current or "").upper()
    target = str(target or "").upper()

    if current not in STATES or target not in STATES:
        raise TradingStateError("unknown trading lifecycle state")
    if target not in ALLOWED_TRANSITIONS[current]:
        raise TradingStateError(f"invalid transition {current} -> {target}")

    safety = record.get("safety") or {}
    if safety.get("environment") != "DEMO":
        raise TradingStateError("trading lifecycle must remain DEMO")
    if safety.get("live_trading") is not False:
        raise TradingStateError("LIVE trading must remain disabled")

    if target == "CATALYST_VERIFIED":
        confidence = record.get("cause_confidence")
        evidence = record.get("catalyst_evidence")
        if confidence not in {"CONFIRMED", "PROBABLE"}:
            raise TradingStateError("verified catalyst requires CONFIRMED or PROBABLE confidence")
        if not isinstance(evidence, list) or not evidence:
            raise TradingStateError("verified catalyst requires evidence")

    if target == "RISK_GATED" and not _bool(record, "risk_gate_passed"):
        raise TradingStateError("risk gate must explicitly pass")

    if target == "HUMAN_APPROVAL":
        if not record.get("proposal_id"):
            raise TradingStateError("proposal_id required before human approval")
        if record.get("approval_state") != "PENDING":
            raise TradingStateError("proposal must be pending before human approval")

    if target == "DEMO_EXECUTION":
        if record.get("approval_state") != "APPROVED":
            raise TradingStateError("explicit human approval required before DEMO execution")
        if safety.get("order_mutation_authorized") is not True:
            raise TradingStateError("order mutation must be separately authorized")

    if target == "BROKER_VERIFICATION":
        if not record.get("broker_order_id"):
            raise TradingStateError("broker acknowledgement identifier required")
        if not record.get("broker_response_ref"):
            raise TradingStateError("broker response evidence required")

    if target == "MONITORING":
        if not record.get("broker_position_ref"):
            raise TradingStateError("broker position evidence required before monitoring")
        if record.get("execution_state") not in {"FILLED", "PARTIAL"}:
            raise TradingStateError("position monitoring requires a broker-confirmed fill state")

    if target == "EXIT" and not record.get("exit_trigger"):
        raise TradingStateError("exit requires a recorded trigger or rationale")

    if target == "REVIEW":
        if current == "EXIT":
            if record.get("execution_state") != "CLOSED":
                raise TradingStateError("trade review after exit requires broker-confirmed closure")
            if not record.get("broker_closure_ref"):
                raise TradingStateError("trade review requires broker closure evidence")
        if current == "REJECTED" and not record.get("rejection_code"):
            raise TradingStateError("rejected candidate review requires rejection code")


def next_states(current: str) -> list[str]:
    state = str(current or "").upper()
    if state not in STATES:
        raise TradingStateError("unknown trading lifecycle state")
    return sorted(ALLOWED_TRANSITIONS[state])
