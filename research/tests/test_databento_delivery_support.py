from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import sys
import unittest
from unittest.mock import MagicMock, patch
from zipfile import ZipFile

from research.engine.providers.databento import convert_databento_dbn_file
from research.jobs.run_paid_databento_job import archive_filenames, batch_file_date


class DatabentoDeliverySupportTests(unittest.TestCase):
    def test_native_dbn_daily_files_are_discoverable(self) -> None:
        filename = "opra-pillar-20260304.cbbo-1m.dbn.zst"
        self.assertEqual(date(2026, 3, 4), batch_file_date(filename))
        with TemporaryDirectory() as directory:
            archive = Path(directory) / "paid.zip"
            with ZipFile(archive, "w") as handle:
                handle.writestr("metadata.json", "{}")
                handle.writestr(filename, "paid bytes")
            self.assertEqual((filename,), archive_filenames(archive))

    def test_native_dbn_conversion_applies_symbol_mappings(self) -> None:
        store = MagicMock()
        fake_databento = SimpleNamespace(
            DBNStore=SimpleNamespace(from_file=MagicMock(return_value=store)),
        )
        with TemporaryDirectory() as directory, patch.dict(
            sys.modules, {"databento": fake_databento},
        ):
            source = Path(directory) / "paid.dbn.zst"
            destination = Path(directory) / "decoded.csv.zst"
            source.write_bytes(b"paid delivery")

            self.assertEqual(
                destination, convert_databento_dbn_file(source, destination),
            )

        fake_databento.DBNStore.from_file.assert_called_once_with(source)
        store.to_csv.assert_called_once_with(
            destination,
            pretty_px=True,
            pretty_ts=True,
            map_symbols=True,
            compression="zstd",
        )


if __name__ == "__main__":
    unittest.main()
