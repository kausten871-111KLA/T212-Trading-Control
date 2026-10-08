import os
"""Exercise the staged shared lock in independent OS processes; no application import."""
import ast, asyncio, hashlib, multiprocessing, os, pathlib, queue, sys, tempfile, time, types, unittest
from contextlib import asynccontextmanager
SOURCE=pathlib.Path(__file__).parents[1]/f"patches/openwebui-{os.environ.get('WEBUI_PATCH_VERSION','v0.11.3')}/open_webui/utils/automations.py"

def worker(directory,chat,hold,events,timeout):
    env=types.ModuleType("open_webui.env");env.DATA_DIR=directory
    sys.modules["open_webui"]=types.ModuleType("open_webui")
    sys.modules["open_webui.env"]=env
    os.environ["AUTOMATION_CHAT_LOCK_TIMEOUT_SECONDS"]=str(timeout)
    tree=ast.parse(SOURCE.read_text())
    node=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=="_shared_chat_execution_lock")
    namespace={"asyncio":asyncio,"asynccontextmanager":asynccontextmanager,"Path":pathlib.Path,"hashlib":hashlib,"os":os,"time":time}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(SOURCE),"exec"),namespace)
    async def run():
        try:
            async with namespace["_shared_chat_execution_lock"](chat):
                events.put(("acquired",time.monotonic()))
                while not hold.is_set():await asyncio.sleep(.02)
            events.put(("released",time.monotonic()))
        except Exception as exc:
            events.put(("error",type(exc).__name__))
    asyncio.run(run())

class SharedLockAcceptance(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.ctx=multiprocessing.get_context("spawn");self.processes=[]
    def tearDown(self):
        for process in self.processes:
            if process.is_alive():process.terminate()
            process.join(timeout=3)
        self.tmp.cleanup()
    def start(self,chat,timeout=3):
        hold=self.ctx.Event();events=self.ctx.Queue()
        p=self.ctx.Process(target=worker,args=(self.tmp.name,chat,hold,events,timeout))
        p.start();self.processes.append(p)
        return p,hold,events
    def test_same_chat_serializes_two_processes(self):
        p1,h1,q1=self.start("same")
        self.assertEqual(q1.get(timeout=5)[0],"acquired")
        p2,h2,q2=self.start("same")
        with self.assertRaises(queue.Empty):q2.get(timeout=.3)
        h1.set()
        self.assertEqual(q2.get(timeout=5)[0],"acquired")
        h2.set();p1.join(3);p2.join(3)
        self.assertEqual(p1.exitcode,0);self.assertEqual(p2.exitcode,0)
    def test_different_chats_do_not_block(self):
        p1,h1,q1=self.start("one");self.assertEqual(q1.get(timeout=5)[0],"acquired")
        p2,h2,q2=self.start("two");self.assertEqual(q2.get(timeout=5)[0],"acquired")
        h1.set();h2.set()
    def test_killed_holder_releases_kernel_lock(self):
        p1,h1,q1=self.start("same");self.assertEqual(q1.get(timeout=5)[0],"acquired")
        p2,h2,q2=self.start("same")
        with self.assertRaises(queue.Empty):q2.get(timeout=.3)
        p1.terminate();p1.join(3)
        self.assertEqual(q2.get(timeout=5)[0],"acquired")
        h2.set();p2.join(3);self.assertEqual(p2.exitcode,0)
    def test_waiter_times_out_without_entering(self):
        p1,h1,q1=self.start("same");self.assertEqual(q1.get(timeout=5)[0],"acquired")
        p2,h2,q2=self.start("same",timeout=1)
        self.assertEqual(q2.get(timeout=5),("error","TimeoutError"))
        p2.join(3);self.assertEqual(p2.exitcode,0)
        h1.set()
if __name__=="__main__":unittest.main()
