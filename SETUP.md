# Celo Trader — Setup Guide

A fully automated options trading bot for $100–$2,000 accounts.

---

## ⚠️ Risk Disclaimer

Options trading involves substantial risk of loss and is not suitable for all investors.
Start with **paper trading only** (simulated money). The $100 starting capital is real risk capital.
Past backtested results do not guarantee future performance.

---

## File Structure

```
celo_trader/
├── config.py          # All settings and constants
├── database.py        # SQLite trade journal
├── broker.py          # Alpaca + Tradier API clients
├── signals.py         # RSI, MACD, candlestick, multi-timeframe logic
├── risk.py            # Position sizing, stop-loss, daily limits
├── trading_logic.py   # Main trading loop orchestrator
├── backtester.py      # Historical simulation engine
├── alerts.py          # Email notification system
├── dashboard.py       # Streamlit web UI (5 pages)
├── main.py            # CLI entry point for headless mode
├── requirements.txt   # Python dependencies
├── .env.example       # Environment variable template
└── SETUP.md           # This file
```

---

## Step 1: Python Environment

Requires **Python 3.11+**.

```bash
# Create a virtual environment (strongly recommended)
python -m venv venv

# Activate it
# macOS/Linux:
source venv/bin/activate
# Windows:
venv\Scripts\activate
```

---

## Step 2: Install TA-Lib (C Library)

TA-Lib requires a native C library. Install it BEFORE running `pip install`.

### macOS
```bash
brew install ta-lib
```

### Ubuntu/Debian Linux
```bash
sudo apt-get install -y libta-lib-dev
```

### Windows
1. Download the pre-built wheel from: https://github.com/cgohlke/talib-build/releases
2. Pick the `.whl` file matching your Python version (e.g. `TA_Lib-0.4.28-cp311-cp311-win_amd64.whl`)
3. `pip install TA_Lib-0.4.28-cp311-cp311-win_amd64.whl`

**If TA-Lib installation fails:** The bot will automatically fall back to `pandas_ta`
for RSI and MACD. Candlestick pattern recognition won't be available, but the bot
will still work using RSI + MACD signals only.

---

## Step 3: Install Python Dependencies

```bash
pip install -r requirements.txt
```

---

## Step 4: API Keys

### Alpaca (Free — Required)
1. Create a free account: https://alpaca.markets/
2. Go to **Paper Trading** dashboard → API Keys → Generate New Key
3. Copy `API Key ID` and `Secret Key`

### Tradier (Free Sandbox — Recommended)
1. Sign up: https://developer.tradier.com/
2. Create an app to get your sandbox API key
3. For live options trading, open a Tradier brokerage account (no minimum)

### Configure your .env file
```bash
cp .env.example .env
# Edit .env with your actual keys
nano .env   # or use any text editor
```

---

## Step 5: Run the Dashboard

```bash
ls -al /Applications/celo_trader
```

This opens a browser at `http://localhost:8501`.

**First time checklist:**
1. ✅ Confirm "Paper Trading" toggle is ON (yellow notice in sidebar)
2. Click **Risk Settings** → verify defaults match your risk tolerance
3. Click **Start Bot** in the sidebar
4. Watch **Live Trading** page for scanner activity
5. Run a **Backtest** before enabling any real trades

---

## Step 6: Headless Mode (bot only, no dashboard)

```bash
# Paper trading (safe default)
python3.11 main.py --paper

# Live trading (REAL MONEY — only after extensive paper testing)
python main.py --live
```

---

## Step 7: Keep Your Computer Awake

The bot runs locally and **will stop if your computer sleeps**.

### macOS
```bash
# Keep awake during market hours
caffeinate -i python main.py --paper
```

### Windows
Use the "Power & sleep" settings to disable sleep, or use a tool like Caffeine.

### Linux
```bash
systemd-inhibit python main.py --paper
```

---

## Step 8: Deploy Dashboard to Streamlit Cloud (Optional)

To access the dashboard from your phone or share with others:

1. Push your code to a **private** GitHub repository (NEVER include `.env` — it's in `.gitignore`)
2. Go to: https://share.streamlit.io/
3. Click "New app" → select your repo → set `dashboard.py` as the main file
4. Add your environment variables in Streamlit Cloud's "Secrets" section (same keys as `.env`)
5. Deploy

**Note:** The trading loop won't run on Streamlit Cloud (no persistent compute).
Run `main.py` locally and use Streamlit Cloud only for the dashboard UI.

---

## Trading Schedule

The bot automatically trades only during these windows (Eastern Time):

| Window | Hours | Rationale |
|--------|-------|-----------|
| Morning | 9:45 AM – 11:00 AM | Post-open momentum settles; best liquidity |
| Afternoon | 2:00 PM – 3:45 PM | Institutional activity resumes; trends resume |

**Outside these windows:** The bot scans but does not enter new positions.
All positions are closed by 3:45 PM to avoid overnight risk.

---

## Capital Scaling Logic

| Account Balance | Ticker Universe | Strategy |
|-----------------|----------------|----------|
| $100 – $1,999 | AMC, SNDL, CLOV, BBBY, MMAT | Penny options ($0.20–$0.80/contract) |
| $2,000+ | SPY, TSLA, AMZN + 2 momentum picks | Liquid large-cap options |

---

## Risk Parameters (Defaults)

| Parameter | Default | Explanation |
|-----------|---------|-------------|
| Risk per trade | $25 | Max dollar risk on a single trade |
| Stop loss | 50% | Exit when option loses half its value |
| Take profit | 100% | Exit when option doubles |
| Max daily loss | 12% | Bot halts for the day at this threshold |
| Max position size | 2% of account | Hard cap per position |
| Simultaneous positions | 1 | Only one open trade at a time |

All adjustable via the **Risk Settings** page in real-time.

---

## Frequently Asked Questions

**Q: Do I need Tradier for the bot to work?**  
A: No. Without Tradier keys, the bot runs in paper-only mode using Alpaca for stock data.
Options order routing uses Alpaca when Tradier is not configured.

**Q: Why is the win rate lower in live trading than in backtest?**  
A: The backtest uses simulated option prices (Black-Scholes approximation).
Real options have wider spreads, slippage, and liquidity constraints.
A 70% backtest win rate might translate to 55–60% live. This is normal.

**Q: Can I run this on a Raspberry Pi?**  
A: Yes, if you can install TA-Lib. Use the `--paper` flag and keep it plugged in.

**Q: What if the API rate limit is hit?**  
A: The broker module has automatic retry with exponential backoff (3 attempts).
If all retries fail, an alert email is sent and the tick is skipped.

**Q: How do I add a new ticker to the penny-tier list?**  
A: Edit `PENNY_TICKERS` in `config.py`. Make sure the ticker has liquid weekly options
(check on your broker's options chain tool before adding).

---

## Support & Debugging

Check `bot.log` in the project directory for detailed logs.

Common issues:
- `ImportError: No module named 'talib'` → TA-Lib C library not installed (see Step 2)
- `alpaca.markets 403 Forbidden` → Wrong API key or paper/live URL mismatch
- `No bars available` → Market is closed or ticker is halted
- `No suitable contract found` → Spread too wide or no liquid contracts at that strike/expiry
