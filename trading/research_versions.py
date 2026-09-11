"""Explicit research entry cohorts; reviewed order versions stay unchanged."""
EXPANDED_IDS = frozenset({
    'CTX_ORB_NR7_OR_INSIDE', 'CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG',
    'CTX_VWAP_PULLBACK_KER10_LONG', 'CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG',
    'V2_FAILED_OR_BREAK_VWAP_REVERSION',
    'V2_TSLA_TWO_LEG_TREND_PULLBACK',
})


def evidence_version(strategy_id, version):
    return f'{version}.research.2' if strategy_id in EXPANDED_IDS else version


def capture_versions(strategy_id, reviewed_version):
    # Finish existing experiments as well as new plays; summaries select the
    # exact cohort separately, never pool these versions into current proof.
    return tuple(sorted({reviewed_version, evidence_version(strategy_id, reviewed_version)}))
