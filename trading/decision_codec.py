"""Versioned lossless decision storage; bounded decoding and legacy JSON support."""
import base64
import binascii
import hashlib
import json
import zlib

MAX_BYTES = 512000
ENCODING = 'zlib-base64-v1'
HEADER_FIELDS = ('event_id', 'recorded_at', 'stage')


def encode_event(event, *, compress=True):
    raw = json.dumps(event, allow_nan=False).encode('utf-8')
    if len(raw) > MAX_BYTES:
        raise ValueError('decision_payload_size_limit')
    if not compress or len(raw) < 2048:
        return raw.decode('utf-8')
    envelope = dict(_celo_storage=ENCODING, raw_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        data=base64.b64encode(zlib.compress(raw, 3)).decode('ascii'),
        **{key:event.get(key) for key in HEADER_FIELDS})
    encoded = json.dumps(envelope, allow_nan=False)
    return encoded if len(encoded.encode('utf-8')) < len(raw) else raw.decode('utf-8')


def decode_event(payload):
    if not isinstance(payload, str) or len(payload.encode('utf-8')) > MAX_BYTES:
        raise ValueError('decision_payload_size_limit')
    try:
        envelope = json.loads(payload)
        if not isinstance(envelope, dict):
            raise ValueError('decision_payload_not_object')
        if '_celo_storage' not in envelope:
            return envelope
        if envelope['_celo_storage'] != ENCODING:
            raise ValueError('unsupported_decision_encoding')
        size = envelope.get('raw_bytes')
        if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_BYTES:
            raise ValueError('decision_expanded_size_limit')
        compressed = base64.b64decode(envelope['data'], validate=True)
        stream = zlib.decompressobj()
        raw = stream.decompress(compressed, size+1)
        if len(raw) != size or not stream.eof or stream.unconsumed_tail or stream.unused_data:
            raise ValueError('invalid_decision_compressed_stream')
        if hashlib.sha256(raw).hexdigest() != envelope.get('sha256'):
            raise ValueError('decision_checksum_mismatch')
        event = json.loads(raw)
        if not isinstance(event, dict) or any(event.get(key) != envelope.get(key) for key in HEADER_FIELDS):
            raise ValueError('decision_envelope_identity_mismatch')
        return event
    except (KeyError, TypeError, binascii.Error, zlib.error, UnicodeError) as exc:
        raise ValueError('invalid_decision_payload') from exc
