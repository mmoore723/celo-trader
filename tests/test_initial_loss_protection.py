from datetime import datetime, timedelta
import json
import unittest

from strategy_health.initial_loss_protection import start, step, outcomes, active, comparison, STATE_KEY, attach, metadata
from strategy_health.authored_exit_summary import net_profit
from strategy_health.option_profit_protection import initialize, advance

ENTRY = datetime(2026, 9, 11, 10)


def quote(bid, second):
    stamp = (ENTRY+timedelta(seconds=second)).isoformat()
    return dict(symbol='XYZ', source_symbol='XYZ', bid=bid, ask=bid+.04,
                bid_date=stamp, ask_date=stamp)


class InitialLossProtectionTests(unittest.TestCase):
    def advance(self, state, second, bid=None, allow=True, exchange=None):
        return step(state, contract='XYZ', now=ENTRY+timedelta(seconds=second),
                    quote=quote(bid, second if exchange is None else exchange) if bid is not None else None,
                    allow_profit_arm=allow)

    def test_loss_limit_before_profit_arm_is_not_same_quote_fill(self):
        state = start(ENTRY, 2, 1.96)
        state = self.advance(state, 30, 1.59, allow=False)
        for name in ('loss_only', 'loss_and_trail'):
            leg = outcomes(state)[name]
            self.assertEqual('pending_quote', leg['status'])
            self.assertEqual('initial_loss_20pct', leg['reason'])
            self.assertNotIn('bid', leg)
        self.assertEqual('collecting', outcomes(state)['profit_trail']['status'])
        state = self.advance(state, 40, 1.58, exchange=30)
        self.assertEqual('pending_quote', outcomes(state)['loss_only']['status'])
        state = self.advance(state, 60, 1.5)
        self.assertEqual(-53.3, net_profit(dict(entry_ask=2, **outcomes(state)['loss_only'])))
        self.assertTrue(active(state))  # Original control still needs completion.

    def test_loss_only_does_not_follow_profitable_peaks(self):
        state = self.advance(start(ENTRY, 2, 1.96), 30, 2.2)
        self.assertAlmostEqual(1.6, state['loss_only']['stop'])
        self.assertAlmostEqual(2.12, state['loss_and_trail']['stop'])
        state = self.advance(state, 60, 2.1)
        self.assertEqual('collecting', outcomes(state)['loss_only']['status'])
        self.assertEqual('option_profit_trail', outcomes(state)['loss_and_trail']['reason'])

    def test_quote_gap_invalidates_path_instead_of_simulating_stop(self):
        state = self.advance(start(ENTRY, 2, 1.96), 121, .1)
        for name in ('profit_trail', 'loss_only', 'loss_and_trail'):
            self.assertEqual('missing_path', outcomes(state)[name]['status'])
        state = self.advance(state, 1801, 1.8)
        self.assertEqual('priced', outcomes(state)['original']['status'])
        self.assertFalse(active(state))

    def test_invalid_entry_and_wrong_protocol(self):
        state = start(ENTRY, 0, 0)
        self.assertFalse(active(state))
        self.assertIsNone(state['loss_floor'])
        state['protocol'] = 'wrong'
        with self.assertRaises(ValueError):
            self.advance(state, 30, 2)

    def test_unstamped_and_other_strategy_cannot_enroll(self):
        state = initialize(ENTRY, 2, 1.96)
        for sid, meta in [('V2_SPY_TREND_CONT', {}), ('OTHER', metadata('V2_SPY_TREND_CONT'))]:
            result=attach(state,strategy_id=sid,meta=meta,entry_at=ENTRY,ask=2,bid=1.96,minutes=30)
            self.assertNotIn(STATE_KEY,result)

    def test_summary_requires_all_four_arms_for_same_play(self):
        state=start(ENTRY,2,1.96)
        rows=[dict(candidate_id='one',contract_symbol='XYZ',entry_ask=2,entry_quote_at=ENTRY.isoformat(),state={STATE_KEY:state})]
        result=comparison(rows)
        self.assertEqual(0,result['paired_results'])
        self.assertEqual(1,result['unpaired'])
        self.assertTrue(all(r['net_pnl'] is None for r in result['arms'].values()))
        self.assertIsNone(comparison([dict(state={})]))

    def test_baseline_identical_to_frozen_engine(self):
        state = start(ENTRY, 2, 1.96)
        original = initialize(ENTRY, 2, 1.96)
        for second in range(30, 1861, 30):
            bid = 2.2 if second < 300 else 1.5 if second < 600 else 2.3
            state = self.advance(state, second, bid)
            original = advance(original, entry_at=ENTRY, ask=2, contract='XYZ',
                               now=ENTRY+timedelta(seconds=second), quote=quote(bid, second))
            self.assertEqual(original, state['baseline'])

    def test_rebound_can_make_loss_stop_worse_than_original(self):
        state = start(ENTRY, 2, 1.96)
        for second in range(30, 1800, 30):
            state = self.advance(state, second, 1.5 if second <= 60 else 2.1)
        state = self.advance(state, 1801, 2.2)
        legs = outcomes(state)
        self.assertEqual(-53.3, net_profit(dict(entry_ask=2, **legs['loss_only'])))
        self.assertEqual(16.7, net_profit(dict(entry_ask=2, **legs['original'])))

    def test_restart_retains_trigger_and_floor(self):
        state = self.advance(start(ENTRY, 2, 1.96), 30, 1.59)
        before = json.loads(json.dumps(state))
        result = self.advance(before, 60, 1.55)
        self.assertEqual('pending_quote', outcomes(before)['loss_only']['status'])
        self.assertEqual('priced', outcomes(result)['loss_only']['status'])
        self.assertEqual(outcomes(before)['loss_only']['trigger'], outcomes(result)['loss_only']['trigger'])

    def test_preobjective_peak_cannot_arm_later_profit_trail(self):
        state = self.advance(start(ENTRY, 2, 1.96), 30, 3, allow=False)
        self.assertEqual(1.6, state['loss_and_trail']['stop'])
        state = self.advance(state, 60, 2.01, allow=True)
        self.assertEqual(1.6, state['loss_and_trail']['stop'])

    def test_temporarily_disallowed_profit_arm_never_loosens_stop(self):
        state = self.advance(start(ENTRY, 2, 1.96), 30, 2.2)
        prior = state['loss_and_trail']['stop']
        state = self.advance(state, 60, 2.3, allow=False)
        self.assertEqual(prior, state['loss_and_trail']['stop'])


if __name__ == '__main__':
    unittest.main()
