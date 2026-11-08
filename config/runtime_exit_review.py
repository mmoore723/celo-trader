"""Append-only runtime correction review, separate from historical research.

The packaged release selects its reviewed runtime by default. Selection never
changes historical evidence, upgrades a grade, or grants strategy enablement.
"""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION = 'exit-action-capture-20261108.1'
MANIFEST = 'config/runtime_reviews/' + REVISION + '.json'


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _path(root, name):
    path = (root / name).resolve()
    path.relative_to(root.resolve())
    return path


def review(rule, evidence, *, root=None):
    """Validate selected review and immutable parent; fail closed on mismatch."""
    selected = os.environ.get('CELO_RUNTIME_EXIT_REVIEW', REVISION)
    if selected != REVISION:
        raise ValueError('runtime_review_does_not_match_packaged_release')
    root = Path(root or ROOT)
    manifest = json.loads((root / MANIFEST).read_text())
    if (manifest.get('schema_version') != 1 or manifest.get('runtime_revision') != selected
            or manifest.get('status') != 'runtime_correctness_reviewed'
            or manifest.get('profitability_validated') is not False):
        raise ValueError('invalid_runtime_review')
    entry = manifest['strategies'].get(rule.strategy_id)
    if entry is None:
        return None
    if (entry['strategy_version'] != rule.version
            or entry['historical_evidence_path'] != rule.evidence_artifact
            or entry['historical_evidence_sha256'] != _sha(_path(root, rule.evidence_artifact))
            or entry['historical_policy_sources'] != evidence.get('runtime_policy_sources', [])):
        raise ValueError('runtime_review_parent_mismatch')
    sources = manifest['runtime_sources']
    if not sources or len({s['path'] for s in sources}) != len(sources):
        raise ValueError('invalid_runtime_review_sources')
    for source in sources:
        if _sha(_path(root, source['path'])) != source['sha256']:
            raise ValueError('runtime_review_source_hash_mismatch')
    replacements = {s['path']: s['sha256'] for s in sources}
    implementation = rule.implementation.removesuffix('.evaluate').replace('.', '/') + '.py'
    return {
        'runtime_revision': selected,
        'runtime_review_sha256': _sha(root / MANIFEST),
        'historical_evidence_sha256': entry['historical_evidence_sha256'],
        'runtime_policy_sources': [dict(s, sha256=replacements.get(s['path'], s['sha256']))
                                   for s in evidence.get('runtime_policy_sources', [])],
        'profitability_validated': False,
        'implementation_sha256': replacements.get(implementation, evidence.get('implementation_sha256_at_review')),
    }


def provenance(rule):
    if rule is None:
        return {}
    evidence = json.loads((ROOT / rule.evidence_artifact).read_text())
    current = review(rule, evidence)
    if current is None:
        return {}
    return {key: current[key] for key in ('runtime_revision', 'runtime_review_sha256',
                                         'historical_evidence_sha256')}
