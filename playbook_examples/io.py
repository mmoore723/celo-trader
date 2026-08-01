"""
playbook_examples/io.py — Entry point (mine_all_examples), cache file path,
and save/load helpers for the mined examples JSON.

Split out of the old single playbook_examples.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from playbook_examples.evaluators import _EVALUATORS
from playbook_examples.mining import mine_strategy_examples

logger = logging.getLogger("celo_trader.playbook_examples")

# NOTE: this path used to be Path(__file__).resolve().parent / "playbook_examples.json"
# when this module was the flat file playbook_examples.py directly in the
# project root. Now that this file lives one level deeper at
# playbook_examples/io.py, the extra .parent below compensates for that —
# same nesting-depth fix pattern applied to config/paths.py and
# tax_engine/constants.py earlier this session, applied proactively here.
EXAMPLES_PATH = Path(__file__).resolve().parent.parent / "playbook_examples.json"


def mine_all_examples(save: bool = True) -> dict:
    """Entry point — fetches real bars via Alpaca and mines all 8 strategies."""
    from broker import get_clients
    alpaca, _tradier = get_clients()
    examples = mine_strategy_examples(alpaca)

    # Strategies with zero real fires are intentionally left OUT of the dict
    # (not filled with a placeholder) — see package docstring re: MID_BRK / AFT_REV.
    for strategy_id, _fn in _EVALUATORS:
        if strategy_id not in examples:
            logger.warning(
                "No real examples found for %s — it hasn't fired in this "
                "historical window. Playbooks must show 'awaiting real signal', "
                "not a fabricated example.", strategy_id,
            )

    if save:
        save_examples(examples)
    return examples


def save_examples(examples: dict, path: Path = EXAMPLES_PATH) -> None:
    with open(path, "w") as f:
        json.dump({
            "generated_at": datetime.utcnow().isoformat(),
            "examples":     examples,
        }, f, indent=2)
    logger.info("Saved real playbook examples to %s (%d strategies represented)",
                path, len(examples))


def load_examples(path: Path = EXAMPLES_PATH) -> dict:
    """
    Load the cached real examples. Returns {} if the cache doesn't exist yet
    (e.g. fresh install before the first mining run, or this exact file has
    never been regenerated) — callers MUST handle the empty/missing-strategy
    case by showing an honest "no real example yet" state, never by silently
    falling back to fabricated data.
    """
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        return data.get("examples", {})
    except Exception as e:
        logger.error("load_examples failed: %s", e)
        return {}
