import os
"""Disposable create/update ownership contract tests for the staged v0.11.3 router."""
import ast
import asyncio
import pathlib
import types
import unittest

ROOT=pathlib.Path(__file__).parents[1]
ROUTER=ROOT/f"patches/openwebui-{os.environ.get('WEBUI_PATCH_VERSION','v0.11.3')}/open_webui/routers/automations.py"

tree=ast.parse(ROUTER.read_text())
fn=next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name=="check_automation_chat_access")

class HTTPException(Exception):
    def __init__(self,status_code,detail):
        self.status_code=status_code; self.detail=detail

class ChatStore:
    owned={("owned","u1"):object()}
    calls=[]
    @classmethod
    async def get_chat_by_id_and_user_id(cls,chat_id,user_id,db=None):
        cls.calls.append((chat_id,user_id,db))
        return cls.owned.get((chat_id,user_id))

ns={
    "Chats":ChatStore,
    "HTTPException":HTTPException,
    "status":types.SimpleNamespace(HTTP_404_NOT_FOUND=404),
    "ERROR_MESSAGES":types.SimpleNamespace(NOT_FOUND="not found"),
    "AutomationForm":object,
    "AsyncSession":object,
}
exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),"<router-helper>","exec"),ns)
check=ns["check_automation_chat_access"]

def form(chat_id=None,target_type="chat"):
    target=types.SimpleNamespace(type=target_type,chat_id=chat_id)
    return types.SimpleNamespace(data=types.SimpleNamespace(target=target))

class RouterOwnershipContract(unittest.TestCase):
    def setUp(self): ChatStore.calls.clear()
    def run_check(self,f,user="u1"):
        return asyncio.run(check(f,types.SimpleNamespace(id=user),db="db"))
    def test_same_owner_allowed(self):
        self.run_check(form("owned"))
        self.assertEqual(ChatStore.calls,[("owned","u1","db")])
    def test_foreign_owner_hidden_as_not_found(self):
        with self.assertRaises(HTTPException) as ctx: self.run_check(form("owned"),"u2")
        self.assertEqual(ctx.exception.status_code,404)
    def test_missing_or_deleted_target_rejected(self):
        with self.assertRaises(HTTPException) as ctx: self.run_check(form("missing"))
        self.assertEqual(ctx.exception.status_code,404)
    def test_unbound_chat_and_channel_skip_chat_lookup(self):
        self.run_check(form(None))
        self.run_check(form("owned","channel"))
        self.assertEqual(ChatStore.calls,[])
    def test_create_and_update_validate_before_write(self):
        source=ROUTER.read_text()
        create=source[source.index("async def create_new_automation"):source.index("async def get_automation_by_id")]
        update=source[source.index("async def update_automation_by_id"):source.index("async def toggle_automation_by_id")]
        self.assertLess(create.index("check_automation_chat_access"),create.index("Automations.insert"))
        self.assertLess(update.index("check_automation_chat_access"),update.index("Automations.update_by_id"))

if __name__=="__main__": unittest.main()
