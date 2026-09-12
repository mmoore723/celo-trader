import copy
import unittest

from research.tests import test_two_leg_affordable as fixtures
from research.jobs.replay_two_leg_affordable import price
from research.jobs.verify_two_leg_affordable import validate, metrics, analyze
from decimal import Decimal


class TwoLegAffordableVerifierTests(unittest.TestCase):
    def setUp(self):
        f = fixtures.TwoLegAffordableTests()
        f.setUp()
        self.baseline = {"rows":[dict(f.entry,status="priced")]}
        self.data = dict(protocol="two_leg_affordable_fixed142_original90m_v1",complete=True,
            coverage={"priced":1},member_sha256={f.entry["date"]:"fixture"},rows=[price(f.entry,f.groups())])

    def test_valid_prices_and_costs(self):
        validate(self.data,self.baseline)

    def test_hidden_cost_or_wrong_exit_rejected(self):
        for key, value in (("net","10"),("exit_bid","1.31"),("exit_time","2026-01-05T16:30:00+00:00")):
            data=copy.deepcopy(self.data)
            data["rows"][0]["outcomes"]["candidate"][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate(data,self.baseline)

    def test_dropped_arm_or_cohort_rejected(self):
        data=copy.deepcopy(self.data)
        del data["rows"][0]["outcomes"]["candidate"]
        with self.assertRaises(ValueError):
            validate(data,self.baseline)
        self.data["rows"]=[]
        with self.assertRaises(ValueError):
            validate(self.data,self.baseline)

    def test_cross_contract_or_duplicate_path_rejected(self):
        for kind in ("contract","duplicate"):
            data=copy.deepcopy(self.data)
            path=data["rows"][0]["paths"]["candidate"]
            if kind=="contract":
                path[-1]["contract"]="SPY  260112C00110000"
            else:
                path.append(copy.deepcopy(path[-1]))
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                validate(data,self.baseline)

    def test_missing_candidate_price_is_not_zero_pnl(self):
        row=self.data["rows"][0]
        row["paths"]["candidate"]=row["paths"]["candidate"][:1]
        row["outcomes"]["candidate"]={"status":"missing_exit","exit_time":row["outcomes"]["control"]["exit_time"]}
        validate(self.data,self.baseline)
        row["outcomes"]["candidate"]["net"]="0"
        with self.assertRaises(ValueError):
            validate(self.data,self.baseline)

    def test_incomplete_is_not_accepted(self):
        self.data["complete"]=False
        with self.assertRaises(ValueError):
            validate(self.data,self.baseline)

    def test_metrics_aggregate_dollars_not_average_ratios(self):
        self.assertEqual(dict(results=3,wins=2,net=10.0,pf=1.5),metrics(list(map(Decimal,[10,20,-20]))))

    def test_account_uses_costs_sizing_and_exposes_path_gap(self):
        settings=dict(growth_mode=False,risk_per_trade=.03,max_concurrent_positions=3,
            daily_loss_hard_cap_pct=30,max_daily_loss_pct=.1,kill_lock_hours=24,paper_trading=True)
        result=analyze(self.data,settings,["2026-01-05","2026-01-06"])
        self.assertAlmostEqual(5006.7,result["accounts"]["candidate_0"]["ending_equity"])
        self.assertAlmostEqual(4996.7,result["accounts"]["candidate_0.05"]["ending_equity"])
        self.assertEqual(5000,result["accounts"]["control_0"]["ending_equity"])
        self.assertEqual({"existing_risk_budget":1},result["accounts"]["control_0"]["skip_counts"])
        self.assertTrue(result["accounts"]["candidate_0"]["account_replay_has_unresolved_evidence"])
        self.assertEqual(["2026-01-05"],result["accounts"]["candidate_0"]["quote_paths_with_gaps_over_120s"])


if __name__=="__main__":
    unittest.main()
