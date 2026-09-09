import unittest
from pathlib import Path

class StaticFrontendTests(unittest.TestCase):
    def test_named_celo_favicon_is_svg_not_spa_html(self):
        source = (Path(__file__).parents[1] / "api" / "main" / "static.py").read_text(encoding="utf-8")
        self.assertIn('"celo-favicon-20260909.svg",', source)
        self.assertLess(
            source.index('"celo-favicon-20260909.svg",'),
            source.index('@app.get("/{full_path:path}"'),
        )


if __name__ == "__main__":
    unittest.main()
