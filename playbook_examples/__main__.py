"""
playbook_examples/__main__.py — CLI entry point.

Split out of the old single playbook_examples.py's `if __name__ ==
"__main__":` block (2026-08-01, file-size cleanup); no logic changed, only
relocated. Invoke with `python -m playbook_examples` (was `python
playbook_examples.py` before this became a package — see package
docstring in __init__.py).
"""

import logging as _lg

from playbook_examples import _EVALUATORS, mine_all_examples

if __name__ == "__main__":
    _lg.basicConfig(level=_lg.INFO)
    result = mine_all_examples()
    print("\n=== Real example mining complete ===")
    for strategy_id, _fn in _EVALUATORS:
        n = len(result.get(strategy_id, []))
        status = f"{n} real example(s)" if n else "NONE — hasn't fired in this window yet"
        print(f"  {strategy_id:12} {status}")
