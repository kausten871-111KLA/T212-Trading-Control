"""Offline acceptance: optional task hook shares existing phase supervisor loop.

No new daemon, external model call, T212 broker connection or credentials.
"""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from runtime.deepseek.service import PhaseService, migrate


class PhaseServiceTaskHookTests(unittest.TestCase):
    def prepare(self, directory):
        path=Path(directory)/"state.sqlite3"
        migrate(path)
        return path

    def capture(self, path, callback=None):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            PhaseService(path,model_task_cycle=callback).run(once=True)
        return [json.loads(s) for s in output.getvalue().splitlines() if s.strip()]

    def test_default_existing_service_has_no_model_task_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            path=self.prepare(directory)
            self.assertIsNone(PhaseService(path).model_task_cycle)
            result=self.capture(path)
            self.assertFalse(any(r.get("component")=="model_task_cycle" for r in result))

    def test_explicit_callback_invoked_once_by_existing_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            path=self.prepare(directory)
            calls=[]
            def stub():
                calls.append("synthetic")
                return {"completed":1,"retry":0,"failed":0}
            result=self.capture(path,stub)
            self.assertEqual(calls,["synthetic"])
            hooks=[r for r in result if r.get("component")=="model_task_cycle"]
            self.assertEqual(len(hooks),1)
            self.assertEqual(hooks[0]["counts"]["completed"],1)
            self.assertEqual(hooks[0]["broker_calls_by_phase_service"],0)

    def test_exception_is_contained_and_phase_loop_survives(self):
        with tempfile.TemporaryDirectory() as directory:
            path=self.prepare(directory)
            def broken():
                raise RuntimeError("offline mock failure")
            result=self.capture(path,broken)
            self.assertTrue(any(r.get("component")=="model_task_cycle"
                                and r.get("error_type")=="RuntimeError" for r in result))
            self.assertTrue(any(r.get("component")=="phase_dispatcher" for r in result))

    def test_non_callable_callback_rejected_before_any_io(self):
        with self.assertRaises(TypeError):
            PhaseService("/unneeded",model_task_cycle="untrusted")

    def test_invalid_counts_are_not_reported_as_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            path=self.prepare(directory)
            result=self.capture(path,lambda:{"completed":-1})
            self.assertTrue(any(r.get("component")=="model_task_cycle"
                                and r.get("error_type")=="ValueError" for r in result))


if __name__=="__main__":
    unittest.main()
