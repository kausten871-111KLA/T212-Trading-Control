"""Pure staged-patch checks; no database, provider, broker, or live WebUI writes."""
import ast
import pathlib
import unittest
ROOT = pathlib.Path(__file__).parents[1]
MODEL = ROOT / "patches/openwebui-v0.11.3/open_webui/models/automations.py"
UTILS = ROOT / "patches/openwebui-v0.11.3/open_webui/utils/automations.py"
def load_helper():
    tree = ast.parse(UTILS.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_bounded_chat_context")
    ns = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), "<helper>", "exec"), ns)
    return ns["_bounded_chat_context"]
bounded = load_helper()
class PersistentTargetPatch(unittest.TestCase):
    def chat(self):
        return {"history":{"currentId":"a2","messages":{
            "u1":{"id":"u1","role":"user","content":"one","parentId":None},
            "a1":{"id":"a1","role":"assistant","content":"two","parentId":"u1"},
            "u2":{"id":"u2","role":"user","content":"three","parentId":"a1"},
            "a2":{"id":"a2","role":"assistant","content":"four","parentId":"u2"}}}}
    def test_active_branch_is_chronological_and_bounded(self):
        self.assertEqual(bounded(self.chat(), 3), [
            {"role":"assistant","content":"two"},{"role":"user","content":"three"},{"role":"assistant","content":"four"}])
    def test_zero_and_hard_cap(self):
        self.assertEqual(bounded(self.chat(), 0), [])
        self.assertEqual(len(bounded(self.chat(), 999)), 4)
    def test_context_has_character_ceiling(self):
        c=self.chat()
        c["history"]["messages"]["a2"]["content"]="x"*40000
        result=bounded(c, 50)
        self.assertEqual(sum(len(m["content"]) for m in result), 32000)
        self.assertEqual(len(result), 1)

    def test_blank_placeholder_excluded_and_cycle_safe(self):
        c=self.chat(); c["history"]["messages"]["a2"]["content"]=""; c["history"]["messages"]["u1"]["parentId"]="a2"
        self.assertEqual([m["content"] for m in bounded(c, 50)], ["one","two","three"])
    def test_schema_exposes_persistent_target_fields(self):
        tree=ast.parse(MODEL.read_text())
        target=next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name=="AutomationTarget")
        fields={n.target.id for n in target.body if isinstance(n, ast.AnnAssign)}
        self.assertTrue({"type","channel_id","chat_id","context_messages"} <= fields)
    def test_executor_fails_closed_before_completion(self):
        source=UTILS.read_text(); owner_check=source.index("Chats.get_chat_by_id_and_user_id"); completion=source.index("await app.state.CHAT_COMPLETION_HANDLER", owner_check)
        self.assertLess(owner_check, completion)
        self.assertIn("Persistent target chat not found or not owned", source)
        self.assertIn("'parent_id': parent_id", source)
        self.assertIn("[*conversation_messages, {'role': 'user', 'content': prompt}]", source)
if __name__ == "__main__": unittest.main()
