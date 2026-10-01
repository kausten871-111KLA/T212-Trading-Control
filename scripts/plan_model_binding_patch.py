#!/usr/bin/env python3
"""Prepare additive OpenWebUI model skill bindings from an exported model JSON.

This script never talks to OpenWebUI. It preserves complete exported model
objects and only unions approved skill IDs into meta.skillIds.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BINDINGS_PATH = ROOT / "webui-control" / "nontrading-model-bindings.json"


class BindingPlanError(ValueError):
    pass


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BindingPlanError(f"unable to read JSON: {path}") from exc


def normalize_models(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("models"), list):
        rows = payload["models"]
    else:
        raise BindingPlanError("export must be a model array or object containing models")
    if not all(isinstance(row, dict) and row.get("id") for row in rows):
        raise BindingPlanError("every exported model must have an id")
    return rows


def build_plan(
    exported: list[dict[str, Any]],
    bindings: dict[str, Any],
) -> dict[str, Any]:
    policy = bindings.get("policy") or {}
    if policy.get("additive_only") is not True or policy.get("preserve_unknown_model_fields") is not True:
        raise BindingPlanError("binding policy must be additive and preserve unknown fields")
    if policy.get("publishing_enabled") is not False or policy.get("scheduling_changes_enabled") is not False:
        raise BindingPlanError("binding plan may not enable publishing or scheduling changes")

    by_id = {str(row["id"]): row for row in exported}
    updates: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []

    for spec in bindings.get("models", []):
        model_id = str(spec.get("id") or "")
        if model_id not in by_id:
            raise BindingPlanError(f"required model missing from export: {model_id}")

        model = copy.deepcopy(by_id[model_id])
        meta = model.get("meta")
        if meta is None:
            meta = {}
        if not isinstance(meta, dict):
            raise BindingPlanError(f"model meta must be an object: {model_id}")

        current = [str(item) for item in (meta.get("skillIds") or [])]
        required = [str(item) for item in (spec.get("required_skills") or [])]
        merged = current + [item for item in required if item not in current]
        added = [item for item in merged if item not in current]

        meta["skillIds"] = merged
        model["meta"] = meta
        updates.append(model)
        changes.append(
            {
                "model_id": model_id,
                "existing_skill_ids": current,
                "required_skill_ids": required,
                "added_skill_ids": added,
                "removed_skill_ids": [],
            }
        )

    return {
        "mode": "ADDITIVE_ONLY",
        "preserve_unknown_model_fields": True,
        "models_json": updates,
        "changes": changes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", required=True, help="Configurator export_models JSON file.")
    parser.add_argument("--bindings", default=str(BINDINGS_PATH))
    parser.add_argument("--output", help="Optional output JSON file.")
    args = parser.parse_args()

    exported = normalize_models(load_json(Path(args.export)))
    bindings = load_json(Path(args.bindings))
    plan = build_plan(exported, bindings)
    encoded = json.dumps(plan, indent=2, sort_keys=True)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
