"""Frozen second DEVELOPMENT experiment, never production authority.

The first candidate exited 84/104 failed retests while >=2 higher timeframes
still supported the position. Test only the causal rule mismatch: a retest
timeout cannot exit while that alignment remains. Keep initial stop, pivots,
tightening, opposing-volume exit, 20% premium guard and original time cap fixed.
This is selected after reviewing v1, so results are NOT untouched validation.
No parameter grid. No promotion based on this development cohort alone.
"""
from research.jobs.structure_exit_candidate import ExitState

PROTOCOL = 'structure_retest_alignment_v2'


class AlignmentExitState(ExitState):
    def step(self, context, option_bid):
        decision = super().step(context, option_bid)
        if decision['reason'] != 'structure_retest_failed':
            return decision
        frames = [context['frames'].get(n) for n in (5,15,60)]
        if any(f is None for f in frames):
            raise ValueError('Retest decision had incomplete frames')
        aligned = sum(self.direction*(f['fast']-f['slow']) > 0
                      and self.direction*(f['close']-f['slow']) > 0 for f in frames)
        if aligned >= 2:
            self.exit_reason = None
            return dict(action='hold',reason='higher_timeframes_still_support_trade',
                        protection=self.protection)
        return decision
