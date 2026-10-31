"""Loopback HTTP contract for existing bridge with optional dedicated model-task route."""
import http.client
import json
import os
import threading
import unittest
from http.server import HTTPServer
from unittest.mock import patch
from runtime.deepseek import host_command_bridge as bridge

MODEL_SECRET="model-task-token-"+("M"*50)
BRIDGE_SECRET="general-command-token-"+("G"*50)


class ModelTaskHTTPTests(unittest.TestCase):
    def setUp(self):
        self.server=HTTPServer(("127.0.0.1",0),bridge.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.original=bridge.TOKEN
        bridge.TOKEN=BRIDGE_SECRET

    def tearDown(self):
        bridge.TOKEN=self.original
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def send(self,path="/model-task",token=MODEL_SECRET,body=None,header="X-Model-Task-Token"):
        if body is None:
            body={"action":"status","payload":{"task_id":"test-task"}}
        conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=3)
        headers={"Content-Type":"application/json"}
        if token is not None:
            headers[header]=token
        conn.request("POST",path,json.dumps(body),headers)
        resp=conn.getresponse()
        data=json.loads(resp.read())
        status=resp.status
        conn.close()
        return status,data

    def test_disabled_without_dedicated_secret(self):
        with patch.dict(os.environ,{"CONTABO_MODEL_TASK_TOKEN":""}):
            code,data=self.send()
        self.assertEqual(code,503)
        self.assertEqual(data["error"],"model_task_not_configured")

    def test_old_general_token_cannot_access_tasks(self):
        with patch.dict(os.environ,{"CONTABO_MODEL_TASK_TOKEN":MODEL_SECRET}):
            code,_=self.send(token=BRIDGE_SECRET,header="X-Bridge-Token")
        self.assertEqual(code,401)

    def test_invalid_model_token_rejected(self):
        with patch.dict(os.environ,{"CONTABO_MODEL_TASK_TOKEN":MODEL_SECRET}):
            code,_=self.send(token="wrong")
        self.assertEqual(code,401)

    def test_valid_token_dispatches_without_inference(self):
        with patch.dict(os.environ,{"CONTABO_MODEL_TASK_TOKEN":MODEL_SECRET}):
            with patch("runtime.deepseek.model_task_host_commands.dispatch_model_task",
                       return_value={"ok":True,"state":"pending"}) as dispatch:
                code,data=self.send()
        self.assertEqual(code,200)
        self.assertTrue(data["ok"])
        self.assertEqual(dispatch.call_count,1)
        self.assertIs(dispatch.call_args.kwargs["verified"],True)

    def test_malformed_content_length_fails_closed_without_dispatch(self):
        with patch.dict(os.environ,{"CONTABO_MODEL_TASK_TOKEN":MODEL_SECRET}):
            with patch("runtime.deepseek.model_task_host_commands.dispatch_model_task") as dispatch:
                conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=3)
                try:
                    conn.putrequest("POST","/model-task")
                    conn.putheader("X-Model-Task-Token",MODEL_SECRET)
                    conn.putheader("Content-Length","not-a-number")
                    conn.endheaders()
                    resp=conn.getresponse()
                    data=json.loads(resp.read())
                    self.assertEqual(resp.status,400)
                    self.assertEqual(data["error"],"invalid_length")
                    dispatch.assert_not_called()
                finally:
                    conn.close()

    def test_duplicate_content_length_rejected_before_dispatch(self):
        with patch.dict(os.environ,{"CONTABO_MODEL_TASK_TOKEN":MODEL_SECRET}):
            with patch("runtime.deepseek.model_task_host_commands.dispatch_model_task") as dispatch:
                conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=3)
                try:
                    conn.putrequest("POST","/model-task")
                    conn.putheader("X-Model-Task-Token",MODEL_SECRET)
                    conn.putheader("Content-Length","2")
                    conn.putheader("Content-Length","2")
                    conn.endheaders(b"{}")
                    resp=conn.getresponse()
                    self.assertEqual(resp.status,400)
                    self.assertEqual(json.loads(resp.read())["error"],"invalid_length")
                    dispatch.assert_not_called()
                finally:
                    conn.close()

    def test_transfer_encoding_and_length_rejected_before_dispatch(self):
        with patch.dict(os.environ,{"CONTABO_MODEL_TASK_TOKEN":MODEL_SECRET}):
            with patch("runtime.deepseek.model_task_host_commands.dispatch_model_task") as dispatch:
                conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=3)
                try:
                    conn.putrequest("POST","/model-task")
                    conn.putheader("X-Model-Task-Token",MODEL_SECRET)
                    conn.putheader("Transfer-Encoding","chunked")
                    conn.putheader("Content-Length","2")
                    conn.endheaders(b"{}")
                    resp=conn.getresponse()
                    self.assertEqual(resp.status,400)
                    self.assertEqual(json.loads(resp.read())["error"],"invalid_length")
                    dispatch.assert_not_called()
                finally:
                    conn.close()

    def test_duplicate_model_token_headers_rejected_before_dispatch(self):
        with patch.dict(os.environ,{"CONTABO_MODEL_TASK_TOKEN":MODEL_SECRET}):
            with patch("runtime.deepseek.model_task_host_commands.dispatch_model_task") as dispatch:
                conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=3)
                try:
                    conn.putrequest("POST","/model-task")
                    conn.putheader("X-Model-Task-Token",MODEL_SECRET)
                    conn.putheader("X-Model-Task-Token",MODEL_SECRET)
                    conn.putheader("Content-Length","2")
                    conn.endheaders(b"{}")
                    resp=conn.getresponse()
                    self.assertEqual(resp.status,401)
                    self.assertEqual(json.loads(resp.read())["error"],"not_authorized")
                    dispatch.assert_not_called()
                finally:
                    conn.close()

    def test_duplicate_json_keys_rejected_before_dispatch(self):
        """Both top-level and nested ambiguous JSON fields must fail closed."""
        bodies = (
            b'{"action":"status","action":"cancel","payload":{"task_id":"x"}}',
            b'{"action":"status","payload":{"task_id":"x","task_id":"y"}}',
        )
        with patch.dict(os.environ, {"CONTABO_MODEL_TASK_TOKEN": MODEL_SECRET}):
            with patch("runtime.deepseek.model_task_host_commands.dispatch_model_task") as dispatch:
                for body in bodies:
                    with self.subTest(body=body):
                        conn = http.client.HTTPConnection(
                            "127.0.0.1", self.server.server_port, timeout=3)
                        try:
                            conn.request(
                                "POST", "/model-task", body=body,
                                headers={
                                    "X-Model-Task-Token": MODEL_SECRET,
                                    "Content-Type": "application/json",
                                })
                            resp = conn.getresponse()
                            self.assertEqual(resp.status, 400)
                            self.assertEqual(
                                json.loads(resp.read())["error"], "invalid_json")
                        finally:
                            conn.close()
                dispatch.assert_not_called()

    def test_nonfinite_json_constants_rejected_before_dispatch(self):
        """Python accepts NaN/Infinity by default; bridge JSON must not."""
        bodies = (
            b'{"action":"status","payload":{"task_id":"x","hint":NaN}}',
            b'{"action":"status","payload":{"task_id":"x","hint":Infinity}}',
            b'{"action":"status","payload":{"task_id":"x","hint":-Infinity}}',
        )
        with patch.dict(os.environ, {"CONTABO_MODEL_TASK_TOKEN": MODEL_SECRET}):
            with patch("runtime.deepseek.model_task_host_commands.dispatch_model_task") as dispatch:
                for body in bodies:
                    with self.subTest(body=body):
                        conn = http.client.HTTPConnection(
                            "127.0.0.1", self.server.server_port, timeout=3)
                        try:
                            conn.request(
                                "POST", "/model-task", body=body,
                                headers={
                                    "X-Model-Task-Token": MODEL_SECRET,
                                    "Content-Type": "application/json",
                                })
                            resp = conn.getresponse()
                            self.assertEqual(resp.status, 400)
                            self.assertEqual(
                                json.loads(resp.read())["error"], "invalid_json")
                        finally:
                            conn.close()
                dispatch.assert_not_called()

    def test_deeply_nested_json_returns_400_and_bridge_survives(self):
        """Bounded-size nesting must not crash the HTTP handler thread."""
        body = (b'{"action":"status","payload":{"task_id":'
                + b'[' * 1200 + b'0' + b']' * 1200 + b'}}')
        self.assertLess(len(body), 16384)
        with patch.dict(os.environ, {"CONTABO_MODEL_TASK_TOKEN": MODEL_SECRET}):
            with patch("runtime.deepseek.model_task_host_commands.dispatch_model_task",
                       return_value={"ok": True, "state": "pending"}) as dispatch:
                conn = http.client.HTTPConnection(
                    "127.0.0.1", self.server.server_port, timeout=3)
                try:
                    conn.request(
                        "POST", "/model-task", body=body,
                        headers={"X-Model-Task-Token": MODEL_SECRET,
                                 "Content-Type": "application/json"})
                    resp = conn.getresponse()
                    self.assertEqual(resp.status, 400)
                    self.assertEqual(json.loads(resp.read())["error"], "invalid_json")
                finally:
                    conn.close()
                dispatch.assert_not_called()
                code, data = self.send()
                self.assertEqual(code, 200)
                self.assertTrue(data["ok"])
                dispatch.assert_called_once()

    def test_nonascii_dedicated_token_fails_closed(self):
        with patch.dict(os.environ,{"CONTABO_MODEL_TASK_TOKEN":MODEL_SECRET}):
            code,data=self.send(token="é")
        self.assertEqual(code,401)
        self.assertEqual(data["error"],"not_authorized")

    def test_unexpected_route_not_accepted(self):
        with patch.dict(os.environ,{"CONTABO_MODEL_TASK_TOKEN":MODEL_SECRET}):
            code,_=self.send(path="/model-task/run")
        self.assertEqual(code,404)

    def test_existing_command_route_still_works(self):
        code,data=self.send(path="/command",token=BRIDGE_SECRET,
                            header="X-Bridge-Token",body={"command":"not_a_command"})
        self.assertEqual(code,200)
        self.assertEqual(data["error"],"unknown_command")

    def test_spoofed_host_identity_rejected(self):
        body={"action":"create","payload":{"principal":"host","job_kind":"research"}}
        with patch.dict(os.environ,{"CONTABO_MODEL_TASK_TOKEN":MODEL_SECRET}):
            code,data=self.send(body=body)
        self.assertEqual(code,400)
        self.assertEqual(data["error_type"],"ValueError")


if __name__=="__main__":
    unittest.main()
