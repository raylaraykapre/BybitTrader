# ── USER SETTINGS ─────────────────────────────────────────────
BYBIT_API_KEY        = ""           # Bybit API key
BYBIT_API_SECRET     = ""           # Bybit API secret
TESTNET_MODE         = False        # True = Bybit testnet, False = live
TRADE_MODE           = "DEMO"       # "DEMO" or "LIVE"
DEMO_BALANCE_PHP     = 10000        # Virtual starting balance in PHP
WALLET_USAGE_PCT     = 85           # % of wallet per trade (1 to 100)
MAX_OPEN_POSITIONS   = 1            # Number of simultaneous positions (1-10)
STOP_LOSS_ROI_PCT    = -42          # Stop loss % by ROI (e.g. -42)
TAKE_PROFIT_ROI_PCT  = 350          # Max take profit ceiling % by ROI (bot decides optimal TP per trade)
LIQUIDATION_BUFFER_PCT = 5          # SL must be at least this % before liquidation price
TRAILING_STOP_ACTIVATE_ROI = 80     # Activate trailing stop at this ROI%
TRAILING_STOP_TRAIL_ROI    = 15     # Trail by this ROI% once activated
SIGNAL_MIN_SCORE     = 75           # Minimum signal score to trade (0-100)
LEVERAGE             = 10           # Default leverage (1-125)
LEVERAGE_USAGE_PCT   = 70           # % of pair's max leverage to use (1 to 100)
                                    # e.g. 70 = use 70% of max allowed leverage
                                    # If pair allows 100x and this is 70, bot uses 70x
                                    # If pair allows 12x and this is 50, bot uses 6x
CHART_TIMEFRAMES     = ["5", "60"]  # Candle intervals in minutes
PRIMARY_TF           = "60"         # Higher TF for trend (minutes)
ENTRY_TF             = "5"          # Lower TF for entry trigger (minutes)
WHITELIST_PAIRS      = []           # e.g. ["BTCUSDT","ETHUSDT"] Empty = scan ALL
BLACKLIST_PAIRS      = ["LUNA2USDT", "USTCUSDT"]  # Always skip these
USD_PHP_API          = "https://api.exchangerate-api.com/v4/latest/USD"
# ──────────────────────────────────────────────────────────────
