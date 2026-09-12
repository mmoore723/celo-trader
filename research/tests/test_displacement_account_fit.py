from copy import deepcopy
import unittest

from research.jobs.audit_displacement_account_fit import audit


class DisplacementFitTests(unittest.TestCase):
    def setUp(self):
        self.settings = {'growth_mode': True, 'growth_risk_boundary_boot': 5000,
                         'risk_per_trade': None}
        self.report = dict(protocol='displacement_recovered_complete_cohort_assessment_v1', rows=[
            dict(candidate_id=str(i), ticker='TSLA', entry_snapshot_at='2026-06-01T12:31:00-04:00',
                 profile='reviewed_bounds', native=True, independent=True, entry_ask='2.00',
                 legs={name: dict(status='priced', exit_bid='2.10', net_pnl_one_contract=6.7)
                       for name in ('structural', 'timer')}) for i in range(7)])

    def test_no_contract_can_fit_the_declared_minimum_at_5000(self):
        result = audit(self.report, self.settings)
        self.assertFalse(result['eligible_profile_minimum_fits_5000'])
        self.assertEqual(0, result['minimum_profile_quantity_at_5000'])
        self.assertEqual([0]*7, [r['contracts_at_5000'] for r in result['rows']])
        self.assertEqual([1.42, 2.38], [b['maximum_ask'] for b in result['budget_boundary']])

    def test_missing_native_entry_is_not_silently_excluded(self):
        self.report['rows'].pop()
        with self.assertRaisesRegex(ValueError, 'cohort changed'):
            audit(self.report, self.settings)

    def test_changed_profit_is_rejected(self):
        self.report['rows'][0]['legs']['structural']['net_pnl_one_contract'] = 999
        with self.assertRaisesRegex(ValueError, 'arithmetic'):
            audit(self.report, self.settings)

    def test_unpriced_leg_cannot_be_called_complete(self):
        self.report['rows'][0]['legs']['timer']['status'] = 'missing_exit'
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            audit(self.report, self.settings)

    def test_settings_and_report_remain_unchanged(self):
        before = deepcopy((self.report, self.settings))
        audit(self.report, self.settings)
        self.assertEqual(before, (self.report, self.settings))


if __name__ == '__main__':
    unittest.main()
