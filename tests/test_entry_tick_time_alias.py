import ast
from pathlib import Path
import unittest


class EntryTickTimeAliasTests(unittest.TestCase):
    def test_datetime_time_does_not_shadow_stdlib_time_module(self):
        """Qualified entries must reach order submission after contract selection."""
        source_path = Path(__file__).parents[1] / "trading" / "entry" / "tick.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        tick_fn = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_tick"
        )

        shadowing_imports = []
        for node in ast.walk(tick_fn):
            if isinstance(node, ast.ImportFrom) and node.module == "datetime":
                for alias in node.names:
                    if alias.name == "time" and (alias.asname or alias.name) == "_time":
                        shadowing_imports.append(node.lineno)

        self.assertEqual(
            shadowing_imports,
            [],
            "datetime.time must not shadow the stdlib time module used after contract selection",
        )


if __name__ == "__main__":
    unittest.main()
