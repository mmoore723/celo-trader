"""Chart session selection must not change the default used by other callers."""
import unittest
from unittest.mock import patch
import pandas as pd
from api.routes.market import get_bars

class ChartPremarketTest(unittest.TestCase):
    def test_extended_display_and_default_session(self):
        index=pd.date_range('2026-11-12 04:00', '2026-11-12 16:00',freq='min',tz='America/New_York')
        frame=pd.DataFrame({'Open':100.,'High':101.,'Low':99.,'Close':100.,'Volume':1000},index=index)
        with patch('yfinance.download',return_value=frame):
            regular=get_bars('SPY','1Min',1000,False)
            extended=get_bars('SPY','1Min',1000,True)
        self.assertEqual(len(regular),390)
        self.assertEqual(len(extended),720)
        self.assertIn('T09:30:',regular[0].time)
        self.assertIn('T04:00:',extended[0].time)
        self.assertIn('T15:59:',extended[-1].time)
