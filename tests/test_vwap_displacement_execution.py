from __future__ import annotations

from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

import pandas as pd

from trading.entry.contract import select_reviewed_v2_contract
from trading.vwap_displacement_exit import evaluate_vwap_displacement_exit
from broker.tradier_chain import TradierChainMixin


STRATEGY_ID = "CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG"


class _FakeTradier:
    def __init__(self, chains: dict[str, list[dict]]) -> None:
        self.chains = chains

    def get_expirations(self, _ticker: str, **_window) -> list[str]:
        return list(self.chains)

    def get_option_chain(self, _ticker: str, expiry: str, _option_type: str) -> list[dict]:
        return self.chains[expiry]


class _WindowedTradier(TradierChainMixin, _FakeTradier):
    """Keep the REAL broker expiration filter; mock only its HTTP response."""
    api_key = 'test-only-not-a-secret'
    get_option_chain = _FakeTradier.get_option_chain

    def _get(self, endpoint, params):
        assert endpoint == '/markets/options/expirations'
        return {'expirations': {'date': list(self.chains)}}


def _frame(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=("time", "high", "low", "close", "volume"))


class VwapDisplacementContractTests(unittest.TestCase):
    def test_other_reviewed_rules_keep_seven_to_twenty_one_days_and_three_expirations(self):
        now=datetime(2026,9,10,11)
        broker=_WindowedTradier({
            (now.date()+timedelta(days=i)).isoformat():[dict(symbol=f'DTE_{i}',strike=101,bid=1.96,ask=2.0)]
            for i in (1,7,8,9,14,22)
        })
        for sid in ('V2_ORB_PULLBACK','V2_SPY_TREND_CONT','V2_SPY_AFTERNOON_FVG',
                    'V2_FAILED_OR_BREAK_VWAP_REVERSION','V2_TSLA_TWO_LEG_TREND_PULLBACK'):
            with self.subTest(strategy=sid), patch('trading.entry.contract._now_et',return_value=now), patch('broker.tradier_chain._market_date',return_value=now.date()):
                contract,info=select_reviewed_v2_contract(broker,'TSLA','bullish',100,500,strategy_id=sid)
            self.assertEqual('DTE_7',contract['symbol']);self.assertEqual(3,info['eligible_contract_count'])

    def test_expiration_fix_does_not_bypass_spread_or_user_budget(self):
        now=datetime(2026,9,10,11)
        broker=_WindowedTradier({'2026-09-11':[dict(symbol='ONE_DAY',strike=101,bid=1.96,ask=2.0)]})
        with patch('trading.entry.contract._now_et',return_value=now), patch('broker.tradier_chain._market_date',return_value=now.date()):
            contract,info=select_reviewed_v2_contract(broker,'TSLA','bullish',100,199,strategy_id=STRATEGY_ID)
            self.assertIsNone(contract);self.assertEqual('over_budget',info['reason'])
            broker.chains['2026-09-11'][0]['bid']=1.0
            contract,info=select_reviewed_v2_contract(broker,'TSLA','bullish',100,500,strategy_id=STRATEGY_ID)
            self.assertIsNone(contract);self.assertEqual('illiquid',info['reason'])

    def test_real_broker_expiration_filter_honors_displacement_window(self):
        now = datetime(2026, 9, 10, 11)
        broker = _WindowedTradier({
            '2026-09-11': [{'symbol': 'QUALIFYING_1D', 'strike': 101, 'bid': 1.96, 'ask': 2.0}],
            '2026-09-18': [{'symbol': 'OUTSIDE_8D', 'strike': 101, 'bid': 1.96, 'ask': 2.0}],
        })
        with patch('trading.entry.contract._now_et', return_value=now), patch('broker.tradier_chain._market_date', return_value=now.date()):
            contract, info = select_reviewed_v2_contract(broker, 'TSLA', 'bullish', 100, 500, strategy_id=STRATEGY_ID)
        self.assertIsNotNone(contract, info)
        self.assertEqual('QUALIFYING_1D', contract['symbol'])

    def test_all_same_week_expirations_are_considered_not_only_first_three(self):
        now = datetime(2026, 9, 10, 11)
        broker = _WindowedTradier({
            (now.date()+timedelta(days=i)).isoformat(): [dict(symbol=f'DTE_{i}',strike=101,bid=ask-.04,ask=ask)]
            for i, ask in ((0,1.7),(1,1.8),(2,1.9),(4,2.0),(7,2.2),(8,2.0))
        })
        with patch('trading.entry.contract._now_et', return_value=now), patch('broker.tradier_chain._market_date', return_value=now.date()):
            contract, info = select_reviewed_v2_contract(broker,'AMZN','bullish',100,500,strategy_id=STRATEGY_ID)
        self.assertEqual('DTE_4',contract['symbol'])
        self.assertEqual(5,info['eligible_contract_count'])

    def test_selector_uses_paid_zero_to_seven_dte_two_dollar_profile(self) -> None:
        now = datetime.fromisoformat("2026-09-03T12:00:00-04:00")
        expiries = {
            (now.date() + timedelta(days=3)).isoformat(): [
                {"symbol": "BEST_TWO_DOLLAR", "strike": 110, "bid": 1.98, "ask": 2.02},
            ],
            (now.date() + timedelta(days=7)).isoformat(): [
                {"symbol": "NEARER_STRIKE", "strike": 101, "bid": 1.91, "ask": 1.95},
                {"symbol": "TOO_EXPENSIVE", "strike": 102, "bid": 2.48, "ask": 2.51},
            ],
            (now.date() + timedelta(days=8)).isoformat(): [
                {"symbol": "WRONG_DTE", "strike": 101, "bid": 1.99, "ask": 2.00},
            ],
        }
        with patch("trading.entry.contract._now_et", return_value=now):
            selected, info = select_reviewed_v2_contract(
                _FakeTradier(expiries), "TSLA", "bullish", 100, 500,
                strategy_id=STRATEGY_ID,
            )

        self.assertEqual("BEST_TWO_DOLLAR", selected["symbol"])
        self.assertEqual("ctx_vwap_displacement_paid_target_150_250_v1", selected["selection_model"])
        self.assertEqual(0, info["research_eligibility"]["min_dte"])
        self.assertEqual(7, info["research_eligibility"]["max_dte"])
        self.assertEqual(1.5, info["research_eligibility"]["min_premium"])
        self.assertEqual(2.5, info["research_eligibility"]["max_premium"])
        self.assertEqual("reviewed_target_150_250", info["research_eligibility"]["primary_policy"])


class VwapDisplacementExitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.entry = datetime.fromisoformat("2026-09-03T10:31:00-04:00")

    def test_target_uses_first_completed_one_minute_bar_after_entry(self) -> None:
        one = _frame([
            ("2026-09-03 10:31:00", 100.8, 100.0, 100.5, 1000),
            ("2026-09-03 10:32:00", 101.2, 100.5, 101.0, 1000),
        ])
        self.assertEqual(
            (False, "hold"),
            evaluate_vwap_displacement_exit(
                self.entry, datetime.fromisoformat("2026-09-03T10:32:30-04:00"),
                one_minute_bars=one, five_minute_bars=None,
                strategy_context={"previous_high": 101.0},
            ),
        )
        should_exit, reason = evaluate_vwap_displacement_exit(
            self.entry, datetime.fromisoformat("2026-09-03T10:33:00-04:00"),
            one_minute_bars=one, five_minute_bars=None,
            strategy_context='{"previous_high": 101.0}',
        )
        self.assertTrue(should_exit)
        self.assertEqual("vwap_displacement_prior_high_target", reason)

    def test_incomplete_five_minute_bar_cannot_fire_vwap_stop(self) -> None:
        five = _frame([
            ("2026-09-03 09:30:00", 101.0, 99.0, 100.0, 1000),
            ("2026-09-03 10:30:00", 100.0, 98.0, 98.5, 1000),
        ])
        self.assertEqual(
            (False, "hold"),
            evaluate_vwap_displacement_exit(
                self.entry, datetime.fromisoformat("2026-09-03T10:34:59-04:00"),
                one_minute_bars=None, five_minute_bars=five,
                strategy_context={"previous_high": 105.0},
            ),
        )
        should_exit, reason = evaluate_vwap_displacement_exit(
            self.entry, datetime.fromisoformat("2026-09-03T10:35:00-04:00"),
            one_minute_bars=None, five_minute_bars=five,
            strategy_context={"previous_high": 105.0},
        )
        self.assertTrue(should_exit)
        self.assertEqual("vwap_displacement_5m_close_below_vwap", reason)

    def test_earliest_structural_decision_wins_after_restart(self) -> None:
        one = _frame([
            ("2026-09-03 10:39:00", 106.0, 104.0, 105.0, 1000),
        ])
        five = _frame([
            ("2026-09-03 09:30:00", 101.0, 99.0, 100.0, 1000),
            ("2026-09-03 10:30:00", 100.0, 98.0, 98.5, 1000),
        ])
        should_exit, reason = evaluate_vwap_displacement_exit(
            self.entry, datetime.fromisoformat("2026-09-03T10:40:00-04:00"),
            one_minute_bars=one, five_minute_bars=five,
            strategy_context={"previous_high": 105.0},
        )
        self.assertTrue(should_exit)
        self.assertEqual("vwap_displacement_5m_close_below_vwap", reason)

    def test_missing_structure_has_bounded_safety_exit(self) -> None:
        self.assertEqual(
            (False, "hold"),
            evaluate_vwap_displacement_exit(
                self.entry, self.entry + timedelta(minutes=89, seconds=59),
                one_minute_bars=None, five_minute_bars=None, strategy_context=None,
            ),
        )
        should_exit, reason = evaluate_vwap_displacement_exit(
            self.entry, self.entry + timedelta(minutes=90),
            one_minute_bars=None, five_minute_bars=None, strategy_context=None,
        )
        self.assertTrue(should_exit)
        self.assertEqual("vwap_displacement_missing_structure_90m_safety", reason)

    def test_one_missing_required_bar_feed_still_uses_bounded_safety(self) -> None:
        one = _frame([
            ("2026-09-03 11:59:00", 101.0, 100.0, 100.5, 1000),
        ])
        should_exit, reason = evaluate_vwap_displacement_exit(
            self.entry, self.entry + timedelta(minutes=90),
            one_minute_bars=one, five_minute_bars=None,
            strategy_context={"previous_high": 105.0},
        )

        self.assertTrue(should_exit)
        self.assertEqual("vwap_displacement_missing_structure_90m_safety", reason)

    def test_end_of_day_is_a_hard_cap(self) -> None:
        should_exit, reason = evaluate_vwap_displacement_exit(
            self.entry, datetime.fromisoformat("2026-09-03T15:55:00-04:00"),
            one_minute_bars=None, five_minute_bars=None,
            strategy_context={"previous_high": 105.0},
        )
        self.assertTrue(should_exit)
        self.assertEqual("vwap_displacement_eod_1555", reason)


if __name__ == "__main__":
    unittest.main()
