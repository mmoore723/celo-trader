from research.tests import test_structure_exit_candidate as base
from research.jobs.structure_alignment_candidate import AlignmentExitState


class AlignmentTests(base.StructureExitTests):
    # Keep all base-policy invariants except the one intentionally changed rule.
    def state(self,direction=1):
        return AlignmentExitState(direction,100,100-direction,5,self.start,30)

    def test_unreclaimed_break_exits_after_two_minutes(self):
        for d in (1,-1):
            s=self.state(d)
            for minute in (1,2):
                self.assertEqual('allow_retest',s.step(self.context(minute,100-1.1*d,d),5)['action'])
            result=s.step(self.context(3,100-1.1*d,d),5)
            self.assertEqual('hold',result['action'])
            self.assertIsNone(s.exit_reason)
            result=s.step(self.context(4,100-1.1*d,-d),5)
            self.assertEqual('structure_retest_failed',result['reason'])

    def test_guard_still_exits_while_higher_frames_support(self):
        s=self.state()
        for minute in (1,2,3):
            s.step(self.context(minute,98.9),5)
        self.assertEqual('maximum_premium_loss_20pct',s.step(self.context(4,98.9),4)['reason'])

    def test_cap_still_exits_while_higher_frames_support(self):
        s=self.state()
        for minute in (1,2,3):
            s.step(self.context(minute,98.9),5)
        self.assertEqual('original_time_cap',s.step(self.context(30,98.9),5)['reason'])
