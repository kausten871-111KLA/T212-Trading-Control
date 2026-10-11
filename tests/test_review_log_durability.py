import json
import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path
from worker.run_catalyst_consumer import append_jsonl

def write_reviews(path, worker):
    for index in range(20):
        append_jsonl(Path(path),{'event_id':f'{worker}-{index}','scan_id':'scan','result':{'disposition':'watch'}})
    os._exit(0)

class ReviewLog(unittest.TestCase):
    def test_concurrent_reviews_survive_process_exit_and_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'reviews.jsonl'
            workers=[multiprocessing.Process(target=write_reviews,args=(str(path),index)) for index in range(4)]
            for worker in workers:worker.start()
            for worker in workers:
                worker.join(10);self.assertFalse(worker.is_alive());self.assertEqual(worker.exitcode,0)
            rows=[json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(rows),80)
            self.assertEqual(len({row['event_id'] for row in rows}),80)
            self.assertEqual(path.stat().st_mode & 0o777,0o600)

    def test_bad_json_and_symlink_do_not_damage_existing_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'reviews.jsonl'
            append_jsonl(path,{'event_id':'good'})
            before=path.read_bytes()
            with self.assertRaises(ValueError):append_jsonl(path,{'confidence':float('nan')})
            self.assertEqual(path.read_bytes(),before)
            link=Path(directory)/'link';link.symlink_to(path)
            with self.assertRaises(OSError):append_jsonl(link,{'event_id':'bad'})
            self.assertEqual(path.read_bytes(),before)

if __name__=='__main__':unittest.main()
