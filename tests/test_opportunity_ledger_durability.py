import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

MODULE=Path(__file__).resolve().parents[1]/'openwebui/tools/opportunity_ledger.py'
spec=importlib.util.spec_from_file_location('ledger',MODULE)
L=importlib.util.module_from_spec(spec);spec.loader.exec_module(L)


class DurableLedger(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'events.jsonl'

    def test_ids_correlation_permissions_and_reload(self):
        event=L.OpportunityLedger(self.path).append('scan',{'symbol':'ACME'},event_id='scan-1',correlation_id='run-1')
        self.assertEqual(event['event_id'],'scan-1')
        self.assertEqual(event['correlation_id'],'run-1')
        self.assertEqual(L.OpportunityLedger(self.path).read_recent(),[event])
        self.assertEqual(self.path.stat().st_mode&0o777,0o600)

    def test_independent_processes_append_without_corrupting_lines(self):
        child="import importlib.util,sys; s=importlib.util.spec_from_file_location('l',sys.argv[1]); l=importlib.util.module_from_spec(s); s.loader.exec_module(l); ledger=l.OpportunityLedger(sys.argv[2]); [ledger.append('scan',{'worker':sys.argv[3],'row':i},correlation_id='shared-run') for i in range(25)]"
        children=[subprocess.Popen([sys.executable,'-c',child,str(MODULE),str(self.path),str(i)]) for i in range(4)]
        self.assertEqual([p.wait(timeout=10) for p in children],[0]*4)
        events=[json.loads(line) for line in self.path.read_text().splitlines()]
        self.assertEqual(len(events),100)
        self.assertEqual(len({e['event_id'] for e in events}),100)
        self.assertTrue(all(e['correlation_id']=='shared-run' for e in events))

    def test_append_survives_immediate_process_exit(self):
        child="import importlib.util,sys,os; s=importlib.util.spec_from_file_location('l',sys.argv[1]); l=importlib.util.module_from_spec(s); s.loader.exec_module(l); l.OpportunityLedger(sys.argv[2]).append('scan',{'symbol':'ACME'},event_id='crash-1'); os._exit(33)"
        p=subprocess.run([sys.executable,'-c',child,str(MODULE),str(self.path)])
        self.assertEqual(p.returncode,33)
        self.assertEqual(L.OpportunityLedger(self.path).read_recent()[0]['event_id'],'crash-1')

    def test_invalid_payload_rejected_before_create(self):
        with self.assertRaises(ValueError):L.OpportunityLedger(self.path).append('scan',{'price':float('nan')})
        self.assertFalse(self.path.exists())
        with self.assertRaises(ValueError):L.OpportunityLedger(self.path).append('scan',{},event_id='')

    def test_symlink_destination_refused(self):
        target=Path(self.temp.name)/'target';target.write_text('keep')
        self.path.symlink_to(target)
        with self.assertRaises(OSError):L.OpportunityLedger(self.path).append('scan',{})
        self.assertEqual(target.read_text(),'keep')


if __name__=='__main__':unittest.main(verbosity=2)
