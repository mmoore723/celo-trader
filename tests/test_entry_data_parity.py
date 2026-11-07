import ast
import copy
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from config.strategy_catalog import REVIEWED_STRATEGIES
from trading.entry import data_parity as guard


class DataParityTests(TestCase):
    def test_paper_bypasses_evidence_read(self):
        with patch.object(guard, "evidence_source") as read:
            self.assertIsNone(guard.live_data_refusal("UNKNOWN", {"paper_trading": True}))
            self.assertIsNone(guard.live_data_refusal("UNKNOWN", {}))
            read.assert_not_called()

    def test_unknown_refused_even_with_premium(self):
        for plan in ("free", "premium", None):
            with self.subTest(plan=plan):
                self.assertIn("unknown research", guard.live_data_refusal(
                    "UNKNOWN", {"paper_trading": False, "alpaca_data_plan": plan}))

    def test_consolidated_requires_exact_plan(self):
        with patch.object(guard, "evidence_source", return_value=("consolidated", "OPRA")):
            for plan in ("free", "", None, "Premium"):
                self.assertIn("premium", guard.live_data_refusal(
                    "S", {"paper_trading": False, "alpaca_data_plan": plan}))
            self.assertIsNone(guard.live_data_refusal(
                "S", {"paper_trading": False, "alpaca_data_plan": "premium"}))

    def test_iex_explicit_evidence(self):
        with patch.object(guard, "evidence_source", return_value=("iex", "Alpaca IEX")):
            self.assertIsNone(guard.live_data_refusal("S", {"paper_trading": False}))

    def test_no_inference_from_reports_or_predecessors(self):
        for payload in ({}, {"source_reports": ["paid_OPRA.json"]},
                        {"predecessor": {"source": "OPRA"}},
                        {"market_data": {"source": "Alpaca regular-session bars"}},
                        {"market_data": None}):
            self.assertEqual(guard.classify_source(payload)[0], "unknown")

    def test_real_catalog_all_versions_readable_without_mutation(self):
        before = copy.deepcopy(REVIEWED_STRATEGIES)
        self.assertEqual(guard.evidence_source("V2_ORB_PULLBACK")[0], "consolidated")
        for sid in REVIEWED_STRATEGIES:
            self.assertIn(guard.evidence_source(sid)[0], {"consolidated", "iex", "unknown"})
        self.assertEqual(REVIEWED_STRATEGIES, before)

    def test_malformed_missing_and_mismatched_artifacts_refused(self):
        for content in ("broken", "[]", '{"strategy_id":"wrong"}'):
            guard.evidence_source.cache_clear()
            with patch.object(Path, "read_text", return_value=content):
                self.assertEqual(guard.evidence_source("V2_ORB_PULLBACK")[0], "unknown")
        guard.evidence_source.cache_clear()
        with patch.object(Path, "read_text", side_effect=OSError):
            self.assertEqual(guard.evidence_source("V2_ORB_PULLBACK")[0], "unknown")
        guard.evidence_source.cache_clear()

    def test_account_settings_are_not_mutated_or_cached(self):
        paper = {"paper_trading": True, "risk_per_trade_pct": 2}
        live = {"paper_trading": False, "risk_per_trade_pct": 2}
        before = copy.deepcopy((paper, live))
        self.assertIsNone(guard.live_data_refusal("UNKNOWN", paper))
        self.assertIsNotNone(guard.live_data_refusal("UNKNOWN", live))
        self.assertEqual((paper, live), before)

    def test_final_order_boundary_rechecks_and_stops_submission(self):
        # Execute the actual final guard block, not a duplicate implementation.
        path = guard.ROOT / "trading/entry/tick.py"
        tree = ast.parse(path.read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_tick")
        checks = [i for i, n in enumerate(function.body) if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "_data_refusal" for t in n.targets)]
        self.assertEqual(len(checks), 2)
        i = checks[-1]
        self.assertIn("get_settings()", ast.unparse(function.body[i]))
        self.assertIn("place_option_order", ast.unparse(function.body[i + 2]))
        body = function.body[i:i + 2] + ast.parse("submit()").body
        wrapper = ast.FunctionDef(name="run", args=ast.arguments(posonlyargs=[], args=[],
            kwonlyargs=[], kw_defaults=[], defaults=[]), body=body, decorator_list=[])
        module = ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[]))
        submit, skip = Mock(), Mock()
        env = dict(live_data_refusal=guard.live_data_refusal, strategy_id="UNKNOWN",
                   get_settings=lambda: {"paper_trading": False}, _skip_log=skip,
                   ticker="QQQ", submit=submit)
        exec(compile(module, str(path), "exec"), env)
        env["run"]()
        submit.assert_not_called()
        self.assertIn("unknown research", skip.call_args.kwargs["detail"])
