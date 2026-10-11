import importlib.util
import multiprocessing
import tempfile
import unittest
from pathlib import Path

SOURCE=Path(__file__).resolve().parents[1]/'openwebui/tools/catalyst_handoff_queue.py'
spec=importlib.util.spec_from_file_location('queue_concurrency',SOURCE)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def enqueue_many(path, worker):
    queue=module.CatalystHandoffQueue(path,max_per_day=1000)
    for index in range(20):
        queue.enqueue({'symbol':f'TEST{worker}_{index}','tier_state':{'current_tier':1}})
        queue.enqueue({'symbol':'SHARED','tier_state':{'current_tier':1}})

def claim_once(path,event_id,outputs):
    result=module.CatalystHandoffQueue(path).claim(event_id)
    outputs.put(bool(result))

class ConcurrentQueue(unittest.TestCase):
    def test_multiple_processes_preserve_unique_rows_and_deduplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            path=str(Path(directory)/'queue.jsonl')
            workers=[multiprocessing.Process(target=enqueue_many,args=(path,index)) for index in range(4)]
            for worker in workers:worker.start()
            for worker in workers:
                worker.join(10);self.assertFalse(worker.is_alive());self.assertEqual(worker.exitcode,0)
            queue=module.CatalystHandoffQueue(path)
            rows=queue._read()
            self.assertEqual(len(rows),81)
            self.assertEqual(len({row['dedup_key'] for row in rows}),81)
            self.assertEqual(Path(path).stat().st_mode & 0o777,0o600)

    def test_only_one_process_claims_unexpired_event(self):
        with tempfile.TemporaryDirectory() as directory:
            path=str(Path(directory)/'queue.jsonl')
            queue=module.CatalystHandoffQueue(path)
            event=queue.enqueue({'symbol':'TEST'})['event']
            outputs=multiprocessing.Queue()
            workers=[multiprocessing.Process(target=claim_once,args=(path,event['id'],outputs)) for _ in range(4)]
            for worker in workers:worker.start()
            for worker in workers:
                worker.join(10);self.assertFalse(worker.is_alive());self.assertEqual(worker.exitcode,0)
            self.assertEqual(sum(outputs.get(timeout=2) for _ in workers),1)
            self.assertEqual(queue._read()[0]['attempts'],1)

    def test_symlink_destination_cannot_replace_target(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'target';target.write_text('private')
            path=Path(directory)/'queue.jsonl';path.symlink_to(target)
            with self.assertRaises(ValueError):module.CatalystHandoffQueue(path).enqueue({'symbol':'TEST'})
            self.assertEqual(target.read_text(),'private')

    def test_invalid_numeric_payload_preserves_previous_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'queue.jsonl'
            queue=module.CatalystHandoffQueue(path)
            queue.enqueue({'symbol':'GOOD'})
            before=path.read_bytes()
            with self.assertRaises(ValueError):queue.enqueue({'symbol':'BAD','value':float('nan')})
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(list(path.parent.glob('*.tmp')),[])

if __name__=='__main__':unittest.main()
