from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import unittest

from strategy_health.modeled_exit_fees import FeeComponent, ModeledFeeSchedule
from strategy_health.paired_exit_accounting import summarize, EntryFeeFill
from tests.test_paired_exit_accounting import PairedExitTests, T


def schedule():
    # Synthetic rates for arithmetic tests, not an activated broker schedule.
    return ModeledFeeSchedule('synthetic-v1', 'https://example.test/fees', 'a' * 64,
        'test-retail-equity-options', T-timedelta(days=2), T-timedelta(days=1), (
            FeeComponent('both', 'both', D('.025'), D(0)),
            FeeComponent('sell', 'sell', D('.003'), D('.00002'))))


class FeeScheduleTests(unittest.TestCase):
    def charge(self, **changes):
        args=dict(side='sell',contracts=2,premium=D(3),rounding='unrounded',entry_at=T)
        args.update(changes)
        return schedule().charge(**args)

    def test_side_quantity_and_notional_math(self):
        self.assertEqual(D('.068'), self.charge()['total'])
        self.assertEqual(D('.05'), self.charge(side='buy')['total'])
        self.assertEqual(D('.072'), self.charge(premium=D(4))['total'])

    def test_ceiling_is_per_component_and_explicitly_modeled(self):
        result=self.charge(rounding='per_fill_ceiling')
        self.assertEqual(D('.07'),result['total'])
        self.assertEqual('modeled_not_broker_charged',result['provenance'])
        self.assertEqual(D('.02'),result['components']['sell'])

    def test_invalid_fills_and_rounding_rejected(self):
        for changes in ({'contracts':True},{'contracts':0},{'contracts':1.5},
                        {'premium':'NaN'},{'premium':-1},{'side':'short'}, {'rounding':'nearest'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.charge(**changes)

    def test_future_or_missing_provenance_rejected(self):
        for changes in ({'known_at':T+timedelta(seconds=1)},
                        {'effective_from':T+timedelta(seconds=1)}, {'known_at':T.replace(tzinfo=None)},
                        {'source':''},{'source_sha256':'x'},{'account_profile':''},{'components':()}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(schedule(),**changes).validate(T)

    def test_duplicate_invalid_components_rejected(self):
        for components in ((schedule().components[0],)*2,
                           (FeeComponent('bad','both',D('NaN'),D(0)),),
                           (FeeComponent('bad','both',D(0),D(-1)),),
                           (FeeComponent('bad','invalid',D(0),D(0)),)):
            with self.assertRaises(ValueError): replace(schedule(),components=components).validate(T)

    def test_schedule_hash_changes_with_rate_not_just_label(self):
        changed=replace(schedule(),components=(FeeComponent('both','both',D('.03'),D(0)),))
        self.assertNotEqual(schedule().fingerprint(),changed.fingerprint())


class ModeledPairedFeesTests(PairedExitTests):
    def setUp(self):
        super().setUp()
        self.entry=replace(self.entry,fee_fills=(EntryFeeFill(2,D(2),'actual-entry-fill'),))

    def model_config(self, **changes):
        return replace(self.config,exit_fee_per_contract=D(0),fee_schedule_version='synthetic-v1',
                       modeled_fees=schedule(),**changes)

    def test_model_does_not_double_count_original_entry_fees(self):
        result=self.run_pair(pricing=self.model_config())
        self.assertEqual('evaluable',result['status'])
        self.assertEqual(D('157.88284'),result['baseline']['net'])
        self.assertEqual(D(1),result['baseline']['original_entry_fee_input'])
        self.assertEqual(D('.05'),result['baseline']['entry_fee_applied'])
        self.assertEqual(D(1),self.entry.entry_fees)

    def test_model_partial_fill_fees_and_conservative_sensitivity(self):
        intents=[replace(self.candidate[0],contracts=1),replace(self.base[0],contracts=1)]
        primary=self.run_pair(baseline=intents,pricing=self.model_config())
        conservative=self.run_pair(baseline=intents,pricing=self.model_config(fee_rounding='per_fill_ceiling'))
        self.assertEqual('evaluable',primary['status'])
        self.assertLessEqual(conservative['baseline']['net'],primary['baseline']['net'])
        self.assertEqual(2,len(conservative['baseline']['fills']))

    def test_conflicting_or_unavailable_model_blocks_attempt(self):
        for config in (replace(self.model_config(),exit_fee_per_contract=D('.5')),
                       replace(self.model_config(),fee_schedule_version='other'),
                       replace(self.model_config(),modeled_fees=replace(schedule(),known_at=T+timedelta(days=1)))):
            self.assertEqual('blocked',self.run_pair(pricing=config)['status'])

    def test_cost_variants_cannot_pool_or_count_as_duplicate_trades(self):
        primary=self.run_pair(pricing=self.model_config())
        conservative=self.run_pair(pricing=self.model_config(fee_rounding='per_fill_ceiling'))
        slipped=self.run_pair(pricing=replace(self.model_config(),slippage_per_share=D('.03')))
        rows=summarize([primary,conservative,slipped])
        self.assertEqual(3,len(rows))
        self.assertTrue(all(r['evaluable']==1 for r in rows))

    def test_rounding_cannot_guess_entry_partial_fills(self):
        result=self.run_pair(entry=replace(self.entry,fee_fills=()),
            pricing=self.model_config(fee_rounding='per_fill_ceiling'))
        self.assertEqual('blocked',result['status'])
        self.assertIn('baseline:entry_fill_breakdown_required_for_fee_rounding',result['errors'])

    def test_entry_fill_reconciliation_and_duplicates(self):
        for fills in ((EntryFeeFill(1,D(2),'one'),),
                      (EntryFeeFill(2,D(3),'one'),),
                      (EntryFeeFill(1,D(2),'same'),EntryFeeFill(1,D(2),'same'))):
            self.assertEqual('blocked',self.run_pair(entry=replace(self.entry,fee_fills=fills),
                             pricing=self.model_config())['status'])

    def test_entry_partial_fill_rounding_is_per_fill(self):
        entry=replace(self.entry,fee_fills=(EntryFeeFill(1,D(1),'one'),EntryFeeFill(1,D(3),'two')))
        result=self.run_pair(entry=entry,pricing=self.model_config(fee_rounding='per_fill_ceiling'))
        self.assertEqual('evaluable',result['status'])
        self.assertEqual(D('.06'),result['baseline']['entry_fee_applied'])
