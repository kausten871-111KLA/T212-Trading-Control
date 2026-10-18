"""Persistent phase dispatcher. No scheduler, model or broker connection.

This service drains authenticated phase events into the existing controller
outbox. It deliberately does not advertise full trading readiness: the WebUI
host hook and instruction consumer must be installed separately.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import sqlite3
import threading
import time

from .orchestrator import StateDB
from .worker_supervisor import WorkerSupervisor
from .controller_worker import ControllerPhaseWorker
from .controller_dispatch import ControllerPhaseDispatcher
from .controller_ack import ControllerAcknowledgements


def migrate(path):
    """Back up an existing DB using SQLite's online backup before migrations."""
    path = Path(path).resolve()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = None
    if path.exists():
        backup = path.with_name(path.name + '.pre-migrate-' + str(time.time_ns()))
        with sqlite3.connect(path) as src, sqlite3.connect(backup) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Backup integrity check failed')
        os.chmod(backup, 0o600)
    db = StateDB(str(path))
    try:
        db.init_schema()
        WorkerSupervisor(db).install_schema()
        ControllerPhaseDispatcher(db).install_schema()
        ControllerAcknowledgements(db, lambda *_: False).install_schema()
        if db.conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Runtime integrity check failed')
    finally:
        db.conn.close()
    os.chmod(path, 0o600)
    return str(backup) if backup else None


class PhaseService:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.stop = threading.Event()

    def run(self, *, interval=1.0, once=False):
        if not 0 < interval <= 60:
            raise ValueError('Polling interval must be >0 and <=60 seconds')
        # An OS lock excludes competing processes including migration; unlike
        # a lease it is automatically released on SIGKILL or host restart.
        with open(str(self.path) + '.service.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if not self.path.is_file():
                raise RuntimeError('Run explicit migration before service startup')
            db = StateDB(str(self.path))
            try:
                indexes = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
                if not {'idx_worker_one_active_role', 'idx_ctl_result_phase_event', 'idx_controller_ack_once'} <= indexes:
                    raise RuntimeError('Runtime migration incomplete')
                worker = ControllerPhaseWorker(db, WorkerSupervisor(db))
                while not self.stop.is_set():
                    counts = worker.run_once()
                    print(json.dumps({'component': 'phase_dispatcher', 'counts': counts,
                        'trading_ready': False}), flush=True)
                    if once:
                        break
                    self.stop.wait(interval)
            finally:
                db.conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', required=True)
    parser.add_argument('--migrate', action='store_true')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    if args.migrate:
        path = Path(args.db).resolve()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(str(path) + '.service.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            print(json.dumps({'backup': migrate(path), 'migrated': True}))
        return
    service = PhaseService(args.db)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: service.stop.set())
    service.run(once=args.once)


if __name__ == '__main__':
    main()
