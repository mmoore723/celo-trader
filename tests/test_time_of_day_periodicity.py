import unittest

from research.jobs.screen_time_of_day_periodicity import qualifies, summarize


class TimeOfDayPeriodicityTests(unittest.TestCase):
    def test_qualification_requires_positive_median(self):
        self.assertTrue(qualifies(summarize([1.0, 0.5, 0.25, -0.1]), 4))
        self.assertFalse(qualifies(summarize([4.0, -0.5, -0.5, -0.5]), 4))

    def test_sample_floor(self):
        self.assertFalse(qualifies(summarize([1.0, 0.5, -0.1]), 4))


if __name__ == "__main__":
    unittest.main()
