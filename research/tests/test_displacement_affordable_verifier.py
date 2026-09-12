from datetime import timedelta
import unittest

from research.tests import test_displacement_affordable as fixtures
from research.jobs.replay_displacement_affordable import price_day
from research.jobs.verify_displacement_affordable import validate,at


class VerifierTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.AffordableDisplacementTests();fixture.setUp()
        self.original=fixture.entry
        self.original.update(profile='reviewed_bounds',native=True,independent=True)
        for leg in self.original['legs'].values():
            leg['decision_at']=(at(leg['quote_at'])-timedelta(minutes=1)).isoformat()
        self.assessment={'rows':[self.original]}
        self.data=dict(complete=True,protocol='displacement_native_fixed080_142_contract_comparison_v1',
                       rows=price_day([self.original],fixture.groups()))

    def test_correct_prices_and_clocks_pass(self):
        validate(self.data,self.assessment)

    def test_changed_cost_result_fails(self):
        self.data['rows'][0]['legs']['candidate']['structural']['net']='999'
        with self.assertRaisesRegex(ValueError,'cost mismatch'):
            validate(self.data,self.assessment)

    def test_missing_leg_fails(self):
        del self.data['rows'][0]['legs']['candidate']['timer']
        with self.assertRaisesRegex(ValueError,'Missing exit'):
            validate(self.data,self.assessment)

    def test_missing_source_entry_fails(self):
        self.data['rows']=[]
        with self.assertRaisesRegex(ValueError,'cohort'):
            validate(self.data,self.assessment)

    def test_changed_entry_time_fails(self):
        self.data['rows'][0]['entry_time']='2026-06-01T12:30:00-04:00'
        with self.assertRaisesRegex(ValueError,'identity'):
            validate(self.data,self.assessment)

    def test_wrong_quote_contract_fails(self):
        self.data['rows'][0]['paths']['candidate'][-1]['contract']='different'
        with self.assertRaisesRegex(ValueError,'retained quote'):
            validate(self.data,self.assessment)

    def test_partial_experiment_is_not_a_result(self):
        self.data['complete']=False
        with self.assertRaisesRegex(ValueError,'Incomplete'):
            validate(self.data,self.assessment)


if __name__=='__main__':
    unittest.main()
