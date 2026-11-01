"""Inspect SAVED Open WebUI automation tool receipts without fetching any website.

Pure normalization. Only a successful real tool output proves a fetch was
attempted; a model prompt mentioning a URL is not evidence. This module does
not call WebUI, the broker, a model provider or any external network.
"""
import json
from urllib.parse import urlsplit

WEB_TOOLS = frozenset({"fetch_url", "search_web"})
ERROR_MARKERS = ("something went wrong", "verify you're not a robot",
                 "access denied", "captcha", "too many requests")


def _as_json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def _output_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(x.get("text", "")) for x in value
                         if isinstance(x, dict) and x.get("type") == "input_text")
    return ""


def audit_saved_web_tools(chat):
    """Return bounded evidence from existing run chat.

    The result never includes page text or arbitrary URL query parameters
    (they might contain auth tokens). Retrieval timestamp is UNKNOWN unless
    separately verified at the data-provider level.
    """
    if not isinstance(chat, dict):
        raise ValueError("Saved WebUI chat dict required")
    history = chat.get("history") or {}
    messages = history.get("messages") or {}
    if not isinstance(messages, dict):
        raise ValueError("Unexpected WebUI history")
    receipts = []
    for msg in messages.values():
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        output = msg.get("output") or []
        if not isinstance(output, list):
            continue
        responses = {x.get("call_id"): x for x in output
                     if isinstance(x, dict) and x.get("type") == "function_call_output"}
        for call in output:
            if not isinstance(call, dict) or call.get("type") != "function_call":
                continue
            name = call.get("name")
            if name not in WEB_TOOLS:
                continue
            args = _as_json(call.get("arguments"))
            target = args.get("url") if name == "fetch_url" else None
            host = None
            path = None
            if isinstance(target, str):
                parts = urlsplit(target)
                if parts.scheme == "https" and parts.hostname:
                    host = parts.hostname.lower()
                    path = parts.path[:180]
            reply = responses.get(call.get("call_id"))
            content = _output_text(reply.get("output")) if reply else ""
            markers = [s for s in ERROR_MARKERS if s in content.lower()]
            if not reply or not content.strip():
                status = "missing_or_empty_result"
            elif markers:
                status = "degraded_result"
            else:
                status = "result_received_unvalidated"
            receipts.append({
                "tool": name,
                "call_completed": call.get("status") == "completed",
                "source_host": host,
                "source_path": path,
                "status": status,
                "error_markers": markers,
                "result_size_chars": len(content),
                "retrieved_at_source_utc": None,
                "market_rows_verified": False,
            })
    return receipts
