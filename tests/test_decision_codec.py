import base64
import json
import zlib
import unittest
from trading.decision_codec import encode_event, decode_event, MAX_BYTES


class DecisionCodecTests(unittest.TestCase):
    def event(self):
        return dict(event_id='one', recorded_at='2026-11-09T18:00:00+00:00', stage='hold',
                    snapshot={'price':1.23456789,'reason':'hold','state':['original state']*5000})

    def test_large_event_roundtrip_smaller_with_same_values(self):
        event=self.event(); encoded=encode_event(event)
        self.assertEqual(event,decode_event(encoded))
        self.assertLess(len(encoded),len(json.dumps(event))//2)
        self.assertEqual('hold',json.loads(encoded)['stage'])

    def test_legacy_and_writer_rollback(self):
        event=self.event()
        legacy=encode_event(event,compress=False)
        self.assertNotIn('_celo_storage',json.loads(legacy))
        self.assertEqual(event,decode_event(legacy))
        self.assertEqual(event,decode_event(encode_event(event)))

    def test_small_events_remain_plain_json(self):
        self.assertEqual({'stage':'hold'},json.loads(encode_event({'stage':'hold'})))

    def test_corrupt_stream_checksum_and_header_rejected(self):
        original=json.loads(encode_event(self.event()))
        for changes in ({'sha256':'bad'}, {'event_id':'wrong'}, {'stage':'wrong'},
                        {'data':'not-base64?'},{'raw_bytes':MAX_BYTES+1},
                        {'raw_bytes':True},{'_celo_storage':'future-version'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                decode_event(json.dumps(dict(original,**changes)))

    def test_truncated_appended_and_expansion_bomb_rejected(self):
        envelope=json.loads(encode_event(self.event()))
        packed=base64.b64decode(envelope['data'])
        for data in (packed[:-1],packed+b'trailing',zlib.compress(b'x'*(MAX_BYTES+100))):
            with self.assertRaises(ValueError):
                decode_event(json.dumps(dict(envelope,data=base64.b64encode(data).decode())))

    def test_input_limits_and_type(self):
        for value in ('x'*(MAX_BYTES+1), '[]', None):
            with self.assertRaises(ValueError):decode_event(value)
        with self.assertRaises(ValueError):encode_event({'data':'x'*(MAX_BYTES+1)})
