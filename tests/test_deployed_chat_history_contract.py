"""Read-only regression checks against exact deployed Chats source.
No app import, database access, provider call or broker operation.
Usage: python3 tests/test_deployed_chat_history_contract.py --source /path/to/chats.py
"""
import ast
import copy
import pathlib
import sys
import time
import unittest

source = pathlib.Path(sys.argv[sys.argv.index("--source")+1]).read_text()
sys.argv = [sys.argv[0]]
tree = ast.parse(source)
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ChatTable")
names = {"_add_child_id_to_parent", "upsert_message_to_history", "get_unresolved_parent_ids"}
cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
if len(cls.body) != len(names):
    raise RuntimeError("Required deployed history API missing")
module = ast.Module(body=[cls], type_ignores=[])
namespace = {"time": time}
exec(compile(ast.fix_missing_locations(module), "<deployed-history-api>", "exec"), namespace)
History = namespace["ChatTable"]

class HistoryContract(unittest.TestCase):
    def setUp(self):
        self.history={"currentId":"a0","messages":{
            "u0":{"id":"u0","role":"user","content":"original question","parentId":None,"childrenIds":["a0"],"timestamp":1},
            "a0":{"id":"a0","role":"assistant","content":"original answer","parentId":"u0","childrenIds":[],"timestamp":2}}}
    def append(self):
        History.upsert_message_to_history(self.history,"u1",{"role":"user","parentId":"a0","content":"next run","childrenIds":["a1"]})
        History.upsert_message_to_history(self.history,"a1",{"role":"assistant","parentId":"u1","content":"","done":False})
    def test_preserves_original_contents(self):
        before=copy.deepcopy(self.history)
        self.append()
        for key in ("u0","a0"):
            self.assertEqual(before["messages"][key]["content"],self.history["messages"][key]["content"])
    def test_parent_and_child_links(self):
        self.append()
        self.assertEqual(self.history["messages"]["a0"]["childrenIds"],["u1"])
        self.assertEqual(self.history["messages"]["u1"]["childrenIds"],["a1"])
        self.assertEqual(self.history["messages"]["a1"]["parentId"],"u1")
    def test_current_leaf(self):
        self.append()
        self.assertEqual(self.history["currentId"],"a1")
    def test_placeholder_completion_preserves_links(self):
        self.append()
        History.upsert_message_to_history(self.history,"a1",{"content":"complete","done":True})
        self.assertEqual(self.history["messages"]["a1"]["parentId"],"u1")
        self.assertTrue(self.history["messages"]["a1"]["done"])
    def test_retry_same_ids_no_duplicate_messages(self):
        self.append()
        self.append()
        self.assertEqual(len(self.history["messages"]),4)
        self.assertEqual(self.history["messages"]["a0"]["childrenIds"],["u1"])
    def test_repeated_runs_same_history(self):
        self.append()
        History.upsert_message_to_history(self.history,"u2",{"role":"user","parentId":"a1","content":"close"})
        History.upsert_message_to_history(self.history,"a2",{"role":"assistant","parentId":"u2","content":"result"})
        self.assertEqual(len(self.history["messages"]),6)
        self.assertFalse(History.get_unresolved_parent_ids(self.history["messages"]))
    def test_preserves_existing_branch(self):
        self.history["messages"]["a0"]["childrenIds"]=["other"]
        self.history["messages"]["other"]={"id":"other","role":"user","parentId":"a0","childrenIds":[],"content":"manual branch"}
        self.append()
        self.assertEqual(self.history["messages"]["a0"]["childrenIds"],["other","u1"])
    def test_missing_parent_detectable(self):
        History.upsert_message_to_history(self.history,"bad",{"role":"user","parentId":"missing","content":"bad"})
        self.assertEqual(History.get_unresolved_parent_ids(self.history["messages"]),{"missing"})
    def test_null_parent_does_not_automatically_append_to_current_leaf(self):
        History.upsert_message_to_history(self.history,"root2",{"role":"user","parentId":None,"content":"new root"})
        self.assertIsNone(self.history["messages"]["root2"]["parentId"])
        self.assertEqual(self.history["messages"]["a0"]["childrenIds"],[])

unittest.main()
