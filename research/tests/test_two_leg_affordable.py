import copy
from datetime import datetime, timedelta
import unittest

import pandas as pd
from research.jobs.replay_two_leg_affordable import choose, price, validate_baseline


class TwoLegAffordableTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime.fromisoformat("2026-01-05T15:00:00+00:00")
        self.end = self.start + timedelta(minutes=91)
        self.control = self.raw(101, "2.00", "1.98")
        self.candidate = self.raw(110, "1.20", "1.18")
        self.entry = dict(date="2026-01-05", direction="bullish", stock_reference=100,
            entry_time=self.start.isoformat(), exit_time=self.end.isoformat(),
            contract=self.control["symbol"], entry_ask=2, entry_bid=1.98,
            exit_bid=2.2, net_pnl_one_contract=16.7)

    def raw(self, strike, ask, bid, *, expiry="260112", side="C"):
        return dict(symbol=f"TSLA  {expiry}{side}{strike*1000:08d}", bid_px_00=bid,
                    ask_px_00=ask, bid_sz_00="5", ask_sz_00="5")

    def groups(self, candidate_exit=True):
        exits = [{**self.control, "bid_px_00":"2.20", "ask_px_00":"2.22"}]
        if candidate_exit:
            exits.append({**self.candidate, "bid_px_00":"1.30", "ask_px_00":"1.32"})
        return [(self.start, pd.DataFrame([self.control, self.candidate])), (self.end, pd.DataFrame(exits))]

    def test_only_premium_cap_changes_selection(self):
        picks = choose(self.entry, [self.control, self.candidate], self.start)
        self.assertEqual(self.control["symbol"].strip(), picks["control"]["contract"])
        self.assertEqual(self.candidate["symbol"].strip(), picks["candidate"]["contract"])

    def test_direction_dte_spread_and_price_bounds(self):
        bad = [self.raw(99,"1.2","1.18"), self.raw(110,"1.2","1.18",side="P"),
            self.raw(110,"1.43","1.41"), self.raw(110,".79",".78"),
            self.raw(110,"1.2",".8"), self.raw(110,"1.2","1.18",expiry="260111"),
            self.raw(110,"1.2","1.18",expiry="260127")]
        for row in bad:
            with self.subTest(row=row):
                self.assertIsNone(choose(self.entry,[row],self.start)["candidate"])
        for ask in (".80", "1.42"):
            self.assertIsNotNone(choose(self.entry,[self.raw(110,ask,ask)],self.start)["candidate"])

    def test_put_direction_and_first_three_expiries(self):
        entry = {**self.entry,"direction":"bearish"}
        self.assertIsNotNone(choose(entry,[self.raw(99,"1.2","1.18",side="P")],self.start)["candidate"])
        rows = [self.raw(99,"1.2","1.18",expiry=d) for d in ("260112","260113","260114")]
        rows.append(self.raw(110,"1.2","1.18",expiry="260115"))
        self.assertIsNone(choose(self.entry,rows,self.start)["control"])

    def test_conflicting_duplicate_rejected(self):
        with self.assertRaisesRegex(ValueError,"Conflicting"):
            choose(self.entry,[self.control,{**self.control,"ask_px_00":"2.01"}],self.start)

    def test_reproduces_control_and_costs(self):
        row = price(self.entry,self.groups())
        self.assertEqual("16.70",row["outcomes"]["control"]["net"])
        self.assertEqual("6.70",row["outcomes"]["candidate"]["net"])
        self.assertEqual(2,len(row["paths"]["candidate"]))

    def test_missing_candidate_exit_remains_missing(self):
        row = price(self.entry,self.groups(False))
        self.assertEqual("missing_exit",row["outcomes"]["candidate"]["status"])
        self.assertNotIn("net",row["outcomes"]["candidate"])

    def test_control_mismatch_or_changed_hold_rejected(self):
        for changes in ({"entry_ask":2.01}, {"net_pnl_one_contract":17},
                        {"exit_time":(self.end-timedelta(minutes=1)).isoformat()}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                price({**self.entry,**changes},self.groups())

    def test_missing_entry_snapshot_rejected(self):
        with self.assertRaisesRegex(ValueError,"entry snapshot"):
            price(self.entry,self.groups()[1:])

    def test_session_coverage_is_frozen(self):
        rows = [dict(date=(self.start.date()+timedelta(days=i)).isoformat(),
                     status="priced" if i<119 else "no_setup" if i<237 else "incomplete_morning") for i in range(251)]
        baseline = dict(protocol="two_leg_causal_prefix_snapshot_clock_baseline_v2",
            quote_clock_policy="cbbo_interval_end_ts_recv_v2",complete=True,sessions=251,rows=rows,manifest=copy.deepcopy(rows))
        self.assertEqual(119,validate_baseline(baseline)["priced"])
        baseline["rows"][0]["status"] = "no_setup"
        with self.assertRaises(ValueError):
            validate_baseline(baseline)


if __name__ == "__main__":
    unittest.main()
