"""Every exposed engine input must carry display-only, plain-language help."""
import json
import unittest
from pathlib import Path
from config.engine_parameters import definition
from config.strategy_catalog import REVIEWED_STRATEGIES

class SettingHelpTests(unittest.TestCase):
    def test_all_registered_entry_inputs_explained(self):
        source = (Path(__file__).resolve().parents[1] / 'frontend/src/lib/strategySettingHelp.js').read_text()
        help_text = json.loads(source.split('export const settingHelp = ', 1)[1].rstrip(';\n'))
        for sid in REVIEWED_STRATEGIES:
            for key in definition(sid):
                with self.subTest(strategy=sid, key=key):
                    self.assertIn(key, help_text)
                    for field in ('label', 'meaning', 'effect'):
                        self.assertTrue(help_text[key][field])
        self.assertIn('0.01 means 1%', help_text['minimum_risk_pct']['meaning'])
        self.assertIn('not an account risk', help_text['minimum_risk_pct']['effect'])
        self.assertIn('not option-price', help_text['giveback_pct']['effect'])
