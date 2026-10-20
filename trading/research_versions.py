"""Explicit research entry cohorts; reviewed order versions stay unchanged."""
EXPANDED_IDS = frozenset({
    'CTX_ORB_NR7_OR_INSIDE', 'CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG',
    'CTX_VWAP_PULLBACK_KER10_LONG', 'CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG',
    'V2_FAILED_OR_BREAK_VWAP_REVERSION',
    'V2_TSLA_TWO_LEG_TREND_PULLBACK',
    'V2_ORB_PULLBACK',
})


def evidence_version(strategy_id, version):
    if strategy_id == 'V2_TSLA_TWO_LEG_TREND_PULLBACK' and version == '2.2.0':
        return '2.1.0.research.2'
    return f'{version}.research.2' if strategy_id in EXPANDED_IDS else version


def capture_versions(strategy_id, reviewed_version):
    # Finish existing experiments as well as new plays; summaries select the
    # exact cohort separately, never pool these versions into current proof.
    versions = {reviewed_version, evidence_version(strategy_id, reviewed_version)}
    if strategy_id == 'V2_TSLA_TWO_LEG_TREND_PULLBACK' and reviewed_version == '2.2.0':
        versions.add('2.1.0')
    return tuple(sorted(versions))
