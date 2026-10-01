import copy
import json
import unittest
from pathlib import Path

from openwebui.tools.workspace_pipeline import (
    PipelineValidationError,
    file_visibility_allowed,
    transition_item,
    validate_pipeline_config,
)


ROOT = Path(__file__).resolve().parents[1]
BOOKS = json.loads(
    (ROOT / "webui-control" / "books-pipeline.json").read_text(encoding="utf-8")
)
YOU_HEAL = json.loads(
    (ROOT / "webui-control" / "you-heal-pipeline.json").read_text(encoding="utf-8")
)


def item(state="DRAFT", checks=None, approvals=None):
    return {
        "item_id": "item-001",
        "title": "Working title",
        "state": state,
        "version": 1,
        "source_refs": ["library://source-document"],
        "owner": "established-workstream",
        "updated_at": "2026-10-01T00:00:00Z",
        "rights_status": "VERIFIED",
        "privacy": "PRIVATE",
        "approvals": approvals or [],
        "checks": checks or {},
    }


class WorkspacePipelineTests(unittest.TestCase):
    def test_both_pipeline_contracts_are_safe(self):
        validate_pipeline_config(BOOKS)
        validate_pipeline_config(YOU_HEAL)

    def test_unsafe_publish_flag_is_rejected(self):
        changed = copy.deepcopy(BOOKS)
        changed["actions"]["publish_enabled"] = True
        with self.assertRaises(PipelineValidationError):
            validate_pipeline_config(changed)

    def test_books_ready_requires_quality_and_rights_checks(self):
        source = item(
            state="LAYOUT",
            checks={
                "continuity_complete": True,
                "fact_check_complete": True,
                "sources_linked": True,
            }
        )
        with self.assertRaises(PermissionError) as raised:
            transition_item(BOOKS, source, "READY_FOR_APPROVAL", 2)
        self.assertIn("rights_verified", str(raised.exception))

    def test_you_heal_ready_requires_claims_brand_rights_privacy_and_visual_checks(self):
        source = item(
            state="THUMBNAILS",
            checks={
                "claims_review_complete": True,
                "brand_tone_complete": True,
                "rights_verified": True,
                "privacy_reviewed": True,
            },
        )
        with self.assertRaises(PermissionError) as raised:
            transition_item(YOU_HEAL, source, "READY_FOR_APPROVAL", 2)
        self.assertIn("visual_quality_reviewed", str(raised.exception))

    def test_transition_creates_new_record_without_mutating_source(self):
        source = item(
            state="LAYOUT",
            checks={
                "continuity_complete": True,
                "fact_check_complete": True,
                "sources_linked": True,
                "rights_verified": True,
            }
        )
        updated = transition_item(
            BOOKS,
            source,
            "READY_FOR_APPROVAL",
            2,
            updated_at="2026-10-01T01:00:00Z",
        )
        self.assertEqual(source["state"], "DRAFT")
        self.assertEqual(source["version"], 1)
        self.assertEqual(updated["state"], "READY_FOR_APPROVAL")
        self.assertEqual(updated["version"], 2)
        self.assertEqual(updated["previous_version_ref"], "item-001:v1")

    def test_version_skip_is_rejected(self):
        with self.assertRaises(PipelineValidationError):
            transition_item(BOOKS, item(), "RESEARCH", 3)

    def test_forward_state_skip_is_rejected(self):
        with self.assertRaises(PipelineValidationError):
            transition_item(BOOKS, item(state="DRAFT"), "READY_FOR_APPROVAL", 2)

    def test_approval_state_requires_human_content_approval(self):
        source = item(state="READY_FOR_APPROVAL")
        with self.assertRaises(PermissionError):
            transition_item(BOOKS, source, "APPROVED", 2)
        updated = transition_item(
            BOOKS,
            source,
            "APPROVED",
            2,
            approval_actions=["human_content_approval"],
        )
        self.assertEqual(updated["state"], "APPROVED")

    def test_publishing_remains_blocked_even_with_approval(self):
        source = item(
            state="APPROVED",
            approvals=[
                {"action": "human_content_approval", "state": "APPROVED"},
                {"action": "human_publish_approval", "state": "APPROVED"},
            ],
        )
        with self.assertRaises(PermissionError):
            transition_item(
                YOU_HEAL,
                source,
                "PUBLISHED",
                2,
                approval_actions=["human_content_approval", "human_publish_approval"],
            )

    def test_cross_workspace_and_external_file_visibility_are_denied(self):
        source = item()
        self.assertTrue(file_visibility_allowed(BOOKS, source, "books-publishing"))
        self.assertFalse(file_visibility_allowed(BOOKS, source, "you-heal-content"))
        self.assertFalse(
            file_visibility_allowed(BOOKS, source, "books-publishing", external=True)
        )


if __name__ == "__main__":
    unittest.main()
