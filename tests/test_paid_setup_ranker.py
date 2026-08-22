from datetime import date

import numpy as np

from research.jobs.evaluate_paid_setup_ranker import causal_features, parse_contract


def test_parse_contract_extracts_expiry_type_and_strike():
    assert parse_contract("SPY   260519P00733000") == (date(2026, 5, 19), "P", 733.0)


def test_causal_features_use_entry_information():
    row = {
        "signal_time": "2026-05-12T11:10:00-04:00",
        "contract": "SPY   260519P00733000",
        "underlying_entry": 733.225,
        "entry_ask": 5.43,
        "strategy_id": "V2_SPY_TREND_CONT",
        # These future outcomes must not affect the feature vector.
        "exit_bid": 1.0,
        "return_pct": -80.0,
    }
    before = causal_features(row)
    row["exit_bid"] = 20.0
    row["return_pct"] = 200.0
    np.testing.assert_allclose(before, causal_features(row))


def test_put_directional_moneyness_is_positive_when_in_the_money():
    row = {
        "signal_time": "2026-05-12T11:10:00-04:00",
        "contract": "SPY   260519P00735000",
        "underlying_entry": 733.0,
        "entry_ask": 5.0,
        "strategy_id": "V2_SPY_TREND_CONT",
    }
    features = causal_features(row)
    assert features[7] > 0
