"""Side-effect-free scheduled automation tool capability receipt. No provider or broker calls."""
from dataclasses import dataclass
from typing import Any, Mapping

@dataclass(frozen=True)
class CapabilityReceipt:
    expected_ids: tuple[str, ...]
    resolved_ids: tuple[str, ...]
    missing_ids: tuple[str, ...]
    function_names: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return bool(self.expected_ids) and not self.missing_ids

def assess_automation_tools(configured_tool_ids, requested_tool_ids, resolved_tools: Mapping[str, Mapping[str, Any]]):
    local_expected = {str(x) for x in configured_tool_ids or [] if not str(x).startswith(("server:", "terminal:"))}
    requested = {str(x) for x in requested_tool_ids or []}
    resolved = {str(tool["tool_id"]) for tool in resolved_tools.values() if isinstance(tool, Mapping) and tool.get("tool_id")}
    matched = local_expected & requested & resolved
    function_names = tuple(sorted(
        str(name) for name, tool in resolved_tools.items()
        if isinstance(tool, Mapping) and tool.get("tool_id") in matched
    ))
    return CapabilityReceipt(
        tuple(sorted(local_expected)),
        tuple(sorted(matched)),
        tuple(sorted(local_expected - matched)),
        function_names,
    )

def capability_manifest(receipt: CapabilityReceipt):
    if not receipt.ready:
        return None
    return (
        "WEBUI-SERVER TOOL INVENTORY: "
        + str(len(receipt.function_names))
        + " callable functions were resolved for this scheduled run. "
        + "Function names: " + ", ".join(receipt.function_names)
        + ". Tool availability is verified by the server, not by self-inspection. "
        + "Do not assert that there are no broker tools if a named broker tool is listed. "
        + "A listed tool may still return an error when invoked; report that separately. "
        + "This does not authorize a new trading decision."
    )
