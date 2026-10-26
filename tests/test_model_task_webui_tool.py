"""Offline tests for staged model-task method on the EXISTING Contabo WebUI tool.

No server, provider, broker, real credentials or production database required.
"""
import asyncio
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "contabo_command_bridge_staged", ROOT / "openwebui/tools/contabo_command_bridge.py")
bridge_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge_tool)
FAKE_TOKEN = "offline-only-dedicated-" + "X" * 52


class FakeResponse:
    status_code = 200
    text = '{"ok":true,"state":"pending"}'


class FakeClient:
    last_request = None
    init_args = None

    def __init__(self, **kwargs):
        type(self).init_args = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def post(self, url, **kwargs):
        type(self).last_request = (url, kwargs)
        return FakeResponse()


class ModelTaskWebUIToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tool = bridge_tool.Tools()
        FakeClient.last_request = None
        FakeClient.init_args = None

    async def test_missing_dedicated_token_fails_closed(self):
        with patch.object(Path, "read_text", side_effect=FileNotFoundError):
            result = json.loads(await self.tool.model_task("status", task_id="abc"))
        self.assertEqual(result["error"], "model_task_not_configured")

    async def test_general_bridge_token_is_never_used_as_fallback(self):
        with patch.object(Path, "read_text", return_value="too-short"):
            result = json.loads(await self.tool.model_task("status", task_id="abc"))
        self.assertEqual(result["error"], "model_task_not_configured")

    async def test_missing_required_create_fields_rejected_before_token_access(self):
        with patch.object(Path, "read_text", side_effect=AssertionError("token read")):
            result = json.loads(await self.tool.model_task(
                "create", instruction="", dedupe_key="key", scheduled_at_utc="2026-10-26T14:00:00Z"))
        self.assertEqual(result["error"], "invalid_create_fields")

    async def test_missing_task_id_rejected(self):
        result = json.loads(await self.tool.model_task("cancel"))
        self.assertEqual(result["error"], "task_id_required")

    async def test_unexpected_socket_path_rejected(self):
        self.tool.valves.endpoint = "/tmp/untrusted.sock"
        result = json.loads(await self.tool.model_task("status", task_id="abc"))
        self.assertEqual(result["error"], "unexpected_endpoint")

    async def test_valid_create_uses_only_dedicated_token_and_fixed_endpoint(self):
        with patch.object(Path, "read_text", return_value=FAKE_TOKEN):
            with patch.object(bridge_tool.httpx, "AsyncClient", FakeClient):
                result = json.loads(await self.tool.model_task(
                    "create", job_kind="research", instruction="Review market movers",
                    scheduled_at_utc="2026-10-26T14:00:00Z",
                    dedupe_key="research:20261026:1400"))
        self.assertTrue(result["ok"])
        url, kwargs = FakeClient.last_request
        self.assertEqual(url, "http://localhost/model-task")
        self.assertEqual(kwargs["headers"]["X-Model-Task-Token"], FAKE_TOKEN)
        self.assertNotIn("X-Bridge-Token", kwargs["headers"])
        self.assertEqual(set(kwargs["json"]), {"action", "payload"})
        self.assertEqual(kwargs["json"]["action"], "create")
        self.assertEqual(kwargs["json"]["payload"]["cost_tier"], "light")
        self.assertNotIn("model_id", kwargs["json"]["payload"])
        self.assertNotIn("principal", kwargs["json"]["payload"])
        self.assertNotIn("broker", kwargs["json"]["payload"])
        self.assertEqual(FakeClient.init_args["transport"]._uds,
                         "/run/contabo-bridge/command.sock")

    async def test_status_and_cancel_only_send_explicit_task_id(self):
        for action in ("status", "cancel"):
            with self.subTest(action=action):
                with patch.object(Path, "read_text", return_value=FAKE_TOKEN):
                    with patch.object(bridge_tool.httpx, "AsyncClient", FakeClient):
                        result = json.loads(await self.tool.model_task(action, task_id="abc"))
                self.assertTrue(result["ok"])
                self.assertEqual(FakeClient.last_request[1]["json"],
                                 {"action": action, "payload": {"task_id": "abc"}})

    async def test_invalid_action_rejected(self):
        result = json.loads(await self.tool.model_task("execute"))
        self.assertEqual(result["error"], "invalid_action")


if __name__ == "__main__":
    unittest.main()
