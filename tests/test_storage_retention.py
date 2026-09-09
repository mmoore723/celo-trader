from __future__ import annotations

import gzip
import os
import tarfile
import tempfile
import unittest
from datetime import date
from pathlib import Path

from deploy.application_log_retention import maintain_archived_logs
from deploy.release_retention import cleanup_release_artifacts
from logger_config.handlers import _gzip_rotated_log, _make_rotating_handler


class ReleaseRetentionTests(unittest.TestCase):
    def _rollback(self, root: Path, name: str) -> Path:
        path = root / name
        path.mkdir()
        payload = path / "payload.txt"
        payload.write_text(name)
        with tarfile.open(path / "source.tar.gz", "w:gz") as archive:
            archive.add(payload, arcname="payload.txt")
        return path

    def test_keeps_two_newest_usable_rollbacks_and_removes_staging_and_failed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old = self._rollback(root, "celo-old-rollback.1")
            middle = self._rollback(root, "celo-middle-rollback.2")
            newest = self._rollback(root, "celo-new-rollback.3")
            os.utime(old, (1, 1))
            os.utime(middle, (2, 2))
            os.utime(newest, (3, 3))
            stage = root / "celo-new-stage.4"
            stage.mkdir()
            (stage / "file").write_text("stage")
            failed = self._rollback(root, "celo-bad-rollback.5.failed")
            unrelated = root / "some-other-folder"
            unrelated.mkdir()

            result = cleanup_release_artifacts(root, keep=2)

            self.assertFalse(old.exists())
            self.assertTrue(middle.exists())
            self.assertTrue(newest.exists())
            self.assertFalse(stage.exists())
            self.assertFalse(failed.exists())
            self.assertTrue(unrelated.exists())
            self.assertEqual(3, len(result["removed"]))

    def test_dry_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "celo-example-stage.1"
            target.mkdir()
            result = cleanup_release_artifacts(root, dry_run=True)
            self.assertTrue(target.exists())
            self.assertTrue(result["dry_run"])


class ApplicationLogRetentionTests(unittest.TestCase):
    def test_preserves_active_log_deletes_expired_and_compresses_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "bot.log").write_text("active")
            (root / "bot.log.5").write_text("legacy")
            (root / "bot.log.2026-08-01").write_text("expired")
            (root / "bot.log.2026-09-08").write_text("recent")
            (root / "dashboard.log").write_text("separate policy")

            result = maintain_archived_logs(root, 14, today=date(2026, 9, 9))

            self.assertEqual("active", (root / "bot.log").read_text())
            self.assertFalse((root / "bot.log.5").exists())
            self.assertFalse((root / "bot.log.2026-08-01").exists())
            self.assertFalse((root / "bot.log.2026-09-08").exists())
            with gzip.open(root / "bot.log.2026-09-08.gz", "rt") as archive:
                self.assertEqual("recent", archive.read())
            self.assertTrue((root / "dashboard.log").exists())
            self.assertEqual(2, len(result["deleted"]))

    def test_runtime_handler_uses_bounded_compressed_rotation(self):
        handler = _make_rotating_handler()
        try:
            self.assertEqual(14, handler.backupCount)
            self.assertEqual("example.gz", handler.namer("example"))
        finally:
            handler.close()

    def test_rotator_compresses_and_removes_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.log"
            destination = Path(folder) / "source.log.gz"
            source.write_text("hello")
            _gzip_rotated_log(str(source), str(destination))
            self.assertFalse(source.exists())
            with gzip.open(destination, "rt") as archive:
                self.assertEqual("hello", archive.read())


if __name__ == "__main__":
    unittest.main()
