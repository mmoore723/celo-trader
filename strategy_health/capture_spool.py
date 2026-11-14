"""Durable receipt queue keeps SQLite persistence off the quote request loop."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import time


class ReceiptSpool:
    def __init__(self, root, *, start=True):
        self.root = Path(root)
        self.path = self.root / 'receipts'
        self.path.mkdir(parents=True, exist_ok=True)
        self.error = None
        self.last_saved = None
        self.stop = threading.Event()
        self.next_due = {}
        # Recover dispatch clocks from durable, not yet indexed receipts.
        for path in sorted(self.path.glob('*.json')):
            try:
                item = json.loads(path.read_text())
                from strategy_health.fast_capture import stamp, CADENCE
                for symbol in item['symbols']:
                    self.next_due[symbol] = max(self.next_due.get(symbol, 0), stamp(item['requested']).timestamp()+CADENCE)
            except Exception as exc:
                self.error = 'receipt_recovery_' + type(exc).__name__
                raise ValueError(self.error) from exc
        self.thread = None
        if start:
            self.thread = threading.Thread(target=self._run, daemon=True, name='capture-receipt-writer')
            self.thread.start()

    def enqueue(self, symbols, payload, requested, received):
        from strategy_health.fast_capture import CADENCE
        if len(list(self.path.glob('*.json'))) >= 1000:
            raise ValueError('capture_receipt_backlog_limit')
        if shutil.disk_usage(self.root).free < 1024**3:
            raise ValueError('capture_disk_reserve_below_1GB')
        item = dict(symbols=symbols, payload=payload, requested=requested.isoformat(), received=received.isoformat())
        data = json.dumps(item, allow_nan=False).encode()
        key = requested.strftime('%Y%m%dT%H%M%S%f') + '-' + hashlib.sha256(data).hexdigest()[:16]
        final = self.path / (key+'.json')
        temporary = self.path / (key+'.tmp')
        with temporary.open('wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, final)
        fd = os.open(self.path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        for symbol in symbols:
            self.next_due[symbol] = requested.timestamp()+CADENCE

    def drain_one(self, registry):
        from strategy_health.fast_capture import stamp
        paths = sorted(self.path.glob('*.json'))
        if not paths:
            return False
        path = paths[0]
        item = json.loads(path.read_text())
        # record is atomic and idempotent. A crash after commit, before unlink,
        # safely replays the same receipt and does not invent a new timestamp.
        registry.record(item['symbols'], item['payload'], stamp(item['requested']), stamp(item['received']))
        path.unlink()
        self.last_saved = item['received']
        self.error = None
        return True

    def _run(self):
        from strategy_health.fast_capture import Registry
        registry = None
        try:
            registry = Registry(self.root, timeout=.2)
            while not self.stop.is_set():
                try:
                    if not self.drain_one(registry):
                        self.stop.wait(.1)
                except Exception as exc:
                    self.error = 'receipt_write_' + type(exc).__name__
                    self.stop.wait(1)
        except Exception as exc:
            self.error = 'receipt_worker_' + type(exc).__name__
        finally:
            if registry:
                registry.db.close()

    def health(self):
        paths = sorted(self.path.glob('*.json'))
        return dict(pending_batches=len(paths), error=self.error, last_persisted_receipt=self.last_saved,
                    worker_alive=bool(self.thread and self.thread.is_alive()))
