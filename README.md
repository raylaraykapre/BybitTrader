# Autonomous Crypto Trading Bot

A Python-based autonomous crypto trading bot for Bybit USDT perpetual futures.  
Runs on **Linux**, **Ubuntu/Debian**, and **Termux** (Android).  
**No pip required** — uses only Python 3 standard library + `urllib`.

---

## Features

- Scans all Bybit USDT perpetual pairs (or your whitelist)
- Dual timeframe analysis: 1H trend bias + 5M entry precision
- 8 TradingView-proven strategy calculations (SuperTrend, Squeeze, SSL, WAE, VWAP, HMA, Pivots, Ichimoku)
- Signal scoring system with configurable threshold
- Demo mode with live prices and virtual balance
- Trailing stop with activation threshold
- All values displayed in Philippine Peso (₱)
- Graceful Ctrl+C shutdown with position summary
- Auto-reconnect on network failure

---

## File Structure

```
bot.py           → Main loop, scheduler, position slot manager
config.py        → ALL user-editable settings
exchange.py      → Bybit API v5 wrapper (klines, orders, balance, funding, orderbook)
strategy.py      → Dual TF engine + TV strategy scoring
indicators.py    → RSI, EMA, MACD, BB, KC, ATR, SuperTrend, HMA, SSL, WAE, VWAP, StochRSI, Ichimoku, Pivots
trader.py        → Live order placement, trailing stop loop, position tracker
demo.py          → Paper trade engine (live prices, virtual fills)
logger.py        → Clean short log formatter + errors.log writer
test_indicators.py → Indicator validation tests
```

---

## Setup Guide

### Linux (Ubuntu/Debian)

```bash
# Python 3 is usually pre-installed. Verify:
python3 --version

# Clone or copy bot files to a directory:
mkdir ~/trading-bot && cd ~/trading-bot
# (copy all .py files here)

# Edit config:
nano config.py

# Run indicator tests first:
python3 test_indicators.py

# Start the bot:
python3 bot.py
```

### Termux (Android)

```bash
# Install Python (if not already):
pkg update && pkg install python

# Create bot directory:
mkdir ~/trading-bot && cd ~/trading-bot
# (copy all .py files here)

# Edit config:
nano config.py

# Run tests:
python test_indicators.py

# Start the bot:
python bot.py
```

---

## Configuration (config.py)

| Field | Description | Default |
|-------|-------------|---------|
| `BYBIT_API_KEY` | Your Bybit API key | `""` |
| `BYBIT_API_SECRET` | Your Bybit API secret | `""` |
| `TESTNET_MODE` | Use Bybit testnet | `False` |
| `TRADE_MODE` | `"DEMO"` or `"LIVE"` | `"DEMO"` |
| `DEMO_BALANCE_PHP` | Virtual starting balance in PHP | `10000` |
| `WALLET_USAGE_PCT` | % of wallet per trade (0.10 to 1.0) | `0.85` |
| `MAX_OPEN_POSITIONS` | Simultaneous positions (1-10) | `1` |
| `STOP_LOSS_ROI_PCT` | Stop loss by ROI % | `-42` |
| `TAKE_PROFIT_ROI_PCT` | Take profit by ROI % | `350` |
| `TRAILING_STOP_ACTIVATE_ROI` | Activate trailing at this ROI% | `80` |
| `TRAILING_STOP_TRAIL_ROI` | Trail by this ROI% | `15` |
| `SIGNAL_MIN_SCORE` | Minimum score to trade (0-100) | `75` |
| `LEVERAGE` | Default leverage (1-125) | `10` |
| `PRIMARY_TF` | Higher TF for trend (minutes) | `"60"` |
| `ENTRY_TF` | Lower TF for entry (minutes) | `"5"` |
| `WHITELIST_PAIRS` | Only trade these (empty = all) | `[]` |
| `BLACKLIST_PAIRS` | Never trade these | `["LUNA2USDT","USTCUSDT"]` |

---

## First-Run Checklist

1. **Edit `config.py`** — Set your API keys (or leave empty for DEMO mode)
2. **Run `python3 test_indicators.py`** — Verify all indicator math is correct
3. **Start in DEMO mode first** — `TRADE_MODE = "DEMO"` to paper trade with live data
4. **Monitor for a few days** — Check signal quality and PnL in demo
5. **Switch to LIVE** — Only after confirming strategy profitability
6. **Set `TESTNET_MODE = True` first** — Test live execution on testnet before real funds

### API Key Permissions Required (LIVE mode)

- Contract Trading: **Order** + **Position**
- Read wallet balance
- No withdrawal permission needed (keep it disabled for safety)

---

## How It Works

### Signal Flow

1. Fetch 1H candles → Analyze trend bias (BULL/BEAR/NEUTRAL)
2. Fetch 5M candles → Run 8 TV strategies + entry indicators
3. Score each strategy hit (+10 to +15 points each)
4. Add +20 bonus if 5M direction aligns with 1H trend
5. If score ≥ `SIGNAL_MIN_SCORE` → Enter trade
6. If 1H and 5M conflict → Always SKIP
7. Monitor positions for SL/TP/Trailing Stop

### Strategies Scored

| Strategy | Points | Condition |
|----------|--------|-----------|
| SuperTrend | +15 | Price above/below ST line |
| Squeeze Momentum | +15 | Squeeze release in trend direction |
| SSL Channel | +10 | SSL cross in EMA bias direction |
| WAE | +15 | Explosion above dead zone |
| VWAP | +10 | Price above/below VWAP |
| HMA | +10 | HMA slope direction |
| Pivot Points | +10 | Near key pivot level |
| Ichimoku | +15 | Price vs cloud + TK cross |
| 1H Alignment | +20 | 5M direction matches 1H bias |

**Maximum possible score: ~120+**

---

## Log Format

```
[HH:MM:SS] BOOT      | Mode: DEMO | Balance: ₱10,000 | Pairs: 47
[HH:MM:SS] SCAN      | BTCUSDT 1H:BULL 5M:LONG | Score: 91%
[HH:MM:SS] STRATEGIES| ST:LONG SQZ:LONG SSL:LONG WAE:LONG VWAP:LONG HMA:LONG
[HH:MM:SS] ORDER     | LONG BTCUSDT | Entry:₱3.18M SL:-42% TP:+350%
[HH:MM:SS] POSITION  | #1 BTCUSDT | PnL:+₱1,240 | ROI:+3.2% | Trail:OFF
[HH:MM:SS] TRAIL ON  | BTCUSDT | Floor locked at +80% ROI
[HH:MM:SS] SKIP      | ETHUSDT | Score:62% | Below threshold
[HH:MM:SS] CLOSED    | BTCUSDT | PnL:+₱38,500 | ROI:+350% TP HIT
```

Errors are written to `errors.log` only (not displayed in console).

---

## Safety Notes

- Always start with DEMO mode
- Use testnet before going live
- Never give your API key withdrawal permissions
- The bot uses market orders — slippage is possible in volatile conditions
- Past demo performance does not guarantee live results
- Monitor the bot regularly, especially in the first days of live trading

---

## Stopping the Bot

Press `Ctrl+C` for a graceful shutdown. The bot will:
1. Stop scanning for new trades
2. Display position summary
3. Show total PnL
4. Close log files

In LIVE mode, open positions remain on Bybit with their SL/TP intact.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Cannot fetch USD/PHP rate" | Check internet connection |
| "Cannot fetch trading pairs" | Bybit API may be down; retry in a few minutes |
| "API may lack trading permissions" | Enable Contract Trading in Bybit API settings |
| No trades happening | Lower `SIGNAL_MIN_SCORE` or check if market is ranging |
| "Network error" in errors.log | Bot will auto-retry; check WiFi/data |

---

## License

Use at your own risk. This bot is for educational purposes. Crypto trading involves significant financial risk.
