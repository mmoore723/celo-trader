import hashlib
import unittest
import zlib

from trading.diagnostics.bar_replay import read_frame_rows
from trading.diagnostics.orb_evidence import canonical


class FrameChunkTests(unittest.TestCase):
    def blob(self, rows):
        raw = canonical(rows)
        digest = hashlib.sha256(raw).hexdigest()
        return digest, zlib.compress(raw)

    def test_legacy_inline_rows_remain_readable(self):
        self.assertEqual(read_frame_rows(dict(data=[[1, 2]]), None), [[1, 2]])

    def test_mixed_input_formats_rejected(self):
        with self.assertRaises(ValueError):
            read_frame_rows(dict(data=[], data_chunks=[], row_count=0), None)

    def test_empty_frame_roundtrip(self):
        self.assertEqual(read_frame_rows(dict(data_chunks=[], row_count=0), None), [])

    def test_counts_and_reference_budget_rejected(self):
        for inputs in (dict(data_chunks=[], row_count=True), dict(data_chunks=[], row_count=1001),
                       dict(data_chunks=['x']*9, row_count=1), dict(data_chunks=[], row_count=1)):
            with self.subTest(inputs=inputs), self.assertRaises(ValueError):
                read_frame_rows(inputs, lambda ref: self.fail('Should reject before reading'))

    def test_oversized_chunk_rejected(self):
        digest, data = self.blob([[1]]*129)
        with self.assertRaisesRegex(ValueError, 'Frame row budget'):
            read_frame_rows(dict(data_chunks=[digest], row_count=129), lambda ref: data)

    def test_hash_tampering_rejected(self):
        digest, _ = self.blob([[1]])
        _, changed = self.blob([[2]])
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            read_frame_rows(dict(data_chunks=[digest], row_count=1), lambda ref: changed)


if __name__ == '__main__':
    unittest.main()
