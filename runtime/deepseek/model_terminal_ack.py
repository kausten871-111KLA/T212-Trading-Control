"""Bridge a durable host-verified model terminal receipt to one controller ACK.

The authenticated WebUI host is responsible for ModelInvocationGate.complete()
and its independent terminal-stream verifier. This adapter neither invokes a
model nor infers a broker order/fill from model completion.
"""


class ModelTerminalAcknowledger:
    def __init__(self, invocation_gate, controller_ack):
        if invocation_gate is None or controller_ack is None:
            raise ValueError("Invocation gate and controller acknowledgements required")
        self.gate = invocation_gate
        self.ack = controller_ack

    def acknowledge_verified(self, *, instruction_id, principal):
        """ACK only persisted terminal evidence; UNKNOWN claims stay unacknowledged.

        A crash between terminal persistence and this call is recoverable:
        re-reading the same receipt produces the same idempotent ACK payload.
        This method must never re-invoke DeepSeek or submit broker requests.
        """
        status = self.gate.status(instruction_id=instruction_id, principal=principal)
        if status.get("state") != "terminal":
            raise RuntimeError("No host-verified terminal model receipt; do not ACK")
        claim, result = status.get("claim"), status.get("result")
        if not isinstance(claim, dict) or not isinstance(result, dict):
            raise ValueError("Incomplete terminal receipt")
        if (not claim.get("invocation_id") or not claim.get("chat_id") or
                result.get("invocation_id") != claim["invocation_id"] or
                result.get("chat_id") != claim["chat_id"] or
                not isinstance(result.get("message_id"), str) or
                not result["message_id"].strip() or
                result.get("terminal") not in ("completed", "failed")):
            raise ValueError("Conflicting or malformed terminal receipt")
        outcome = {
            "kind": "verified_model_terminal",
            "model_terminal": result["terminal"],
            "invocation_id": claim["invocation_id"],
            "chat_id": claim["chat_id"],
            "message_id": result["message_id"],
        }
        return self.ack.acknowledge(
            instruction_id=instruction_id, principal=principal, outcome=outcome)
