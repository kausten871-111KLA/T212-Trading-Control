import json
import unittest
from pathlib import Path

from openwebui.tools.model_router import RoutingBlocked, route_task, validate_router_config


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "webui-control" / "model-router.json").read_text())


class ModelRouterTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            "WEBUI_MODEL_FAST_TEXT": "fast-test-model",
            "WEBUI_MODEL_DEEP_REASONING": "deep-test-model",
            "WEBUI_MODEL_VISION": "vision-test-model",
            "WEBUI_MODEL_HIGH_CAPABILITY": "high-test-model",
        }

    def test_contract_is_valid(self):
        validate_router_config(CONFIG)

    def test_image_forces_genuine_vision_role(self):
        decision = route_task(
            CONFIG,
            {
                "workspace": "you-heal-content",
                "task_type": "extraction",
                "attachments": [{"kind": "image", "name": "frame.jpg"}],
            },
            self.env,
        )
        self.assertEqual(decision["selected_role"], "vision")
        self.assertIn("vision", decision["required_capabilities"])

    def test_visual_task_never_falls_back_to_text_only(self):
        env = dict(self.env)
        del env["WEBUI_MODEL_VISION"]
        with self.assertRaises(RoutingBlocked):
            route_task(
                CONFIG,
                {"task_type": "summary", "input_kinds": ["screenshot"]},
                env,
            )

    def test_routine_extraction_uses_low_cost_role(self):
        decision = route_task(
            CONFIG,
            {"workspace": "books-publishing", "task_type": "extraction"},
            self.env,
        )
        self.assertEqual(decision["selected_role"], "fast_text")
        self.assertEqual(decision["estimated_cost_tier"], "low")

    def test_science_review_requires_human_review(self):
        decision = route_task(
            CONFIG,
            {"workspace": "you-heal-content", "task_type": "science_review"},
            self.env,
        )
        self.assertEqual(decision["selected_role"], "high_capability")
        self.assertTrue(decision["human_review_required"])

    def test_missing_configured_model_blocks(self):
        with self.assertRaises(RoutingBlocked):
            route_task(CONFIG, {"task_type": "coding"}, {})


if __name__ == "__main__":
    unittest.main()
