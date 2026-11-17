"""Durable receipt queue keeps SQLite persistence off the quote request loop."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import time
from datetime import datetime, timezone


def error_code(exc):
    # Only expose known validation codes, never arbitrary provider payloads.
    reason = str(exc)
    if isinstance(exc, ValueError) and reason in {
        "capture_disk_reserve_below_1GB", "capture_receipt_backlog_limit",
        "unexpected_or_duplicate_contract", "capture_timestamp_requires_timezone",
    }:
        return reason
    return getattr(exc, "sqlite_errorname", type(exc).__name__)


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
            registry = Registry(self.root, timeout=.2, reclaim_index=True)
            registry.db.execute('PRAGMA cache_size=-65536')
            checkpoint_at = 0
            while not self.stop.is_set():
                try:
                    if time.monotonic() >= checkpoint_at:
                        # Outside the write transaction. Do not wait for readers
                        # or hold up quote requests; retry on the next interval.
                        registry.db.execute('PRAGMA busy_timeout=0')
                        try:
                            registry.db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchall()
                        finally:
                            registry.db.execute('PRAGMA busy_timeout=200')
                        checkpoint_at = time.monotonic()+30
                    if not self.drain_one(registry):
                        self.stop.wait(.1)
                except Exception as exc:
                    self.error = 'receipt_write_' + error_code(exc)
                    self.stop.wait(1)
        except Exception as exc:
            self.error = 'receipt_worker_' + error_code(exc)
        finally:
            if registry:
                registry.db.close()

    def health(self):
        paths = sorted(self.path.glob('*.json'))
        oldest = None
        if paths:
            try:
                # Filename is the original request clock, not modification time.
                oldest = datetime.strptime(paths[0].name.split('-')[0], '%Y%m%dT%H%M%S%f').replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return dict(pending_batches=len(paths), error=self.error, last_persisted_receipt=self.last_saved,
                    oldest_pending_at=oldest.isoformat() if oldest else None,
                    oldest_pending_seconds=max(0,(datetime.now(timezone.utc)-oldest).total_seconds()) if oldest else 0,
                    disk_free_bytes=shutil.disk_usage(self.root).free,
                    worker_alive=bool(self.thread and self.thread.is_alive()))
