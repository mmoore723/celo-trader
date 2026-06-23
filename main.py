"""
main.py — Entry point for the trading bot (non-dashboard mode).

Usage:
    python main.py          # runs the live trading loop (blocking)
    python main.py --paper  # force paper trading mode

The dashboard (dashboard.py) starts the loop in a background thread via Streamlit.
Use this file to run the bot headlessly (e.g. on a dedicated terminal session
while the dashboard runs separately).
"""

import argparse
import sys
import logging

from config import save_settings
from logger_config import setup_logging
from database import init_db
from trading_logic import run_trading_loop

logger = setup_logging()


def main():
    parser = argparse.ArgumentParser(description="Algorithmic Options Trading Bot")
    parser.add_argument("--paper",  action="store_true", help="Force paper trading mode")
    parser.add_argument("--live",   action="store_true", help="Enable live trading (REAL MONEY)")
    parser.add_argument("--interval", type=int, default=60, help="Poll interval in seconds (default: 60)")
    args = parser.parse_args()

    if args.paper:
        save_settings({"paper_trading": True})
        logger.info("Paper trading mode forced via CLI flag")
    elif args.live:
        confirm = input("⚠️  You are about to trade with REAL MONEY. Type 'CONFIRM' to proceed: ")
        if confirm != "CONFIRM":
            print("Aborted.")
            sys.exit(0)
        save_settings({"paper_trading": False})
        logger.warning("LIVE trading mode enabled!")

    logger.info("=" * 60)
    logger.info("CeloTrader Bot Starting")
    logger.info("=" * 60)

    init_db()

    try:
        run_trading_loop(poll_interval=args.interval)
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")


if __name__ == "__main__":
    main()
