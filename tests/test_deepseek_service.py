import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from runtime.deepseek.service import migrate
from runtime.deepseek.orchestrator import StateDB
from runtime.deepseek.controller_phase_bridge import ControllerPhaseBridge, PHASE_BY_AUTOMATION

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'runtime.db'
        migrate(self.path)
    def tearDown(self):
        self.tmp.cleanup()
    def command(self, *extra):
        return [sys.executable, '-m', 'runtime.deepseek.service', '--db', str(self.path), *extra]
    def enqueue(self):
        db = StateDB(str(self.path))
        try:
            return ControllerPhaseBridge(db, lambda p,a: p == 'host-owner').enqueue(
                automation_id=next(iter(PHASE_BY_AUTOMATION)), market_date='2026-10-19', principal='host-owner')
        finally:
            db.conn.close()
    def test_restart_preserves_one_instruction(self):
        self.enqueue()
        for _ in range(2):
            subprocess.run(self.command('--once'), check=True, capture_output=True)
            self.enqueue()
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM controller_instruction').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM intent').fetchone()[0], 0)
    def test_migration_backup_restores_existing_data(self):
        self.enqueue()
        backup = migrate(self.path)
        with sqlite3.connect(backup) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM event_queue').fetchone()[0], 1)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
    def test_kill_restart_and_single_instance(self):
        self.enqueue()
        proc = subprocess.Popen(self.command(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            line = proc.stdout.readline()
            self.assertFalse(json.loads(line)['trading_ready'])
            duplicate = subprocess.run(self.command('--once'), capture_output=True)
            self.assertNotEqual(duplicate.returncode, 0)
            migration = subprocess.run(self.command('--migrate'), capture_output=True)
            self.assertNotEqual(migration.returncode, 0)
            proc.kill()
            proc.wait(timeout=5)
            subprocess.run(self.command('--once'), check=True, capture_output=True)
            with sqlite3.connect(self.path) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM controller_instruction').fetchone()[0], 1)
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.communicate(timeout=5)
    def test_missing_schema_fails_without_creating_database(self):
        self.path.unlink()
        result = subprocess.run(self.command('--once'), capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.path.exists())
