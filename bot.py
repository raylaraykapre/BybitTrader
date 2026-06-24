#!/usr/bin/env python3
"""
bot.py - Main loop, scheduler, position slot manager
Autonomous crypto trading bot for Bybit USDT perpetuals.
"""
import sys
import os
import time
import signal
import threading

# Ensure local imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import exchange
import strategy
import news
from logger import log, log_error, close as close_logger
from trader import LiveTrader
from demo import DemoTrader

# ─── GLOBALS ──────────────────────────────────────────────────
_shutdown = threading.Event()
_trader = None


def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully."""
    _shutdown.set()


# ─── STARTUP VALIDATION ──────────────────────────────────────

def validate_startup():
    """Run all pre-flight checks. Returns (success, usd_php_rate)."""
    log("BOOT", "Running startup validation...")

    # 1. Check USD/PHP rate
    usd_php = exchange.get_usd_php_rate()
    if usd_php <= 0:
        log("BOOT", "ERROR: Cannot fetch USD/PHP rate")
        return False, 0

    log("BOOT", f"USD/PHP rate: ₱{usd_php:.2f}")

    # 2. Check Bybit connectivity - fetch pairs
    pairs = exchange.get_usdt_perpetual_pairs()
    if not pairs:
        log("BOOT", "ERROR: Cannot fetch trading pairs from Bybit")
        return False, 0

    log("BOOT", f"Available pairs: {len(pairs)}")

    # 3. For LIVE mode, validate API keys
    if config.TRADE_MODE == "LIVE":
        if not config.BYBIT_API_KEY or not config.BYBIT_API_SECRET:
            log("BOOT", "ERROR: API keys not configured for LIVE mode")
            return False, 0

        # Check balance
        balance = exchange.get_wallet_balance()
        if balance <= 0:
            log("BOOT", "WARNING: Wallet balance is 0 USDT")

        balance_php = balance * usd_php
        log("BOOT", f"Wallet: {balance:.2f} USDT (₱{balance_php:,.0f})")

        # Check permissions
        if not exchange.check_api_permissions():
            log("BOOT", "WARNING: API may lack trading permissions")

    return True, usd_php


# ─── SCAN LOOP ────────────────────────────────────────────────

def scan_pairs(pairs, trader, usd_php):
    """Scan all pairs for trading signals, prioritized by news sentiment."""
    if trader.open_slots() <= 0:
        return

    # Refresh news and prioritize pairs by sentiment
    news.refresh_if_needed()
    ordered_pairs = news.get_prioritized_pairs(pairs)

    for symbol in ordered_pairs:
        if _shutdown.is_set():
            break

        if trader.has_position(symbol):
            continue

        if trader.open_slots() <= 0:
            break

        # Skip pairs with extreme negative news
        if news.should_avoid_pair(symbol):
            log("SKIP", f"{symbol} | Heavy bearish news — avoiding")
            continue

        try:
            # Fetch candle data for both timeframes
            candles_1h = exchange.get_klines(symbol, config.PRIMARY_TF, 200)
            if len(candles_1h) < 200:
                continue

            candles_5m = exchange.get_klines(symbol, config.ENTRY_TF, 200)
            if len(candles_5m) < 100:
                continue

            # Get funding rate
            funding = exchange.get_funding_rate(symbol)

            # Get orderbook imbalance
            bids, asks = exchange.get_orderbook(symbol, 25)
            ob_ratio = bids / asks if asks > 0 else 1.0

            # Get signal
            sig = strategy.get_signal(candles_1h, candles_5m, funding, ob_ratio)

            direction = sig["direction"]
            score = sig["score"]
            bias_1h = sig["bias_1h"]

            # Log skip reasons
            if sig["skip_reason"]:
                if direction and score > 0:
                    log("SKIP", f"{symbol} | Score:{score}% | {sig['skip_reason']}")
                continue

            if direction is None:
                continue

            # Check conflict
            if (direction == "LONG" and bias_1h == "BEAR") or \
               (direction == "SHORT" and bias_1h == "BULL"):
                log("SKIP", f"{symbol} | 1H:{bias_1h} 5M:{direction} | Conflict")
                continue

            # ── NEWS SENTIMENT BONUS/PENALTY ──
            news_bonus = news.get_news_score_bonus(symbol, direction)
            score += news_bonus
            news_info = news.get_sentiment(symbol)
            news_tag = ""
            if news_info:
                news_tag = f" News:{news_info['bias']}({news_bonus:+d})"

            # Log the scan result
            side_5m = direction
            log("SCAN", f"{symbol} 1H:{bias_1h} 5M:{side_5m} | "
                f"Score: {score}%{news_tag}")

            # Log strategies
            strats = sig["strategies"]
            strat_str = " ".join(
                f"{k}:{'✓' if v else '✗'}" for k, v in strats.items()
            )
            if strat_str:
                log("STRATEGIES", strat_str)

            # Check minimum score
            if score < config.SIGNAL_MIN_SCORE:
                log("SKIP", f"{symbol} | Score:{score}% | Below threshold")
                continue

            # Execute trade
            if config.TRADE_MODE == "DEMO":
                trader.open_position(symbol, direction)
            else:
                balance = exchange.get_wallet_balance()
                trader.open_position(symbol, direction, balance)

            # Rate limit between successful trades
            time.sleep(1)

        except Exception as e:
            log_error("SCAN", f"{symbol}: {e}")
            continue

        # Rate limit between pair scans
        time.sleep(0.3)


# ─── MAIN ─────────────────────────────────────────────────────

def main():
    global _trader

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Validate
    success, usd_php = validate_startup()
    if not success:
        log("BOOT", "Startup validation failed. Exiting.")
        sys.exit(1)

    # Get pairs
    pairs = exchange.get_usdt_perpetual_pairs()

    # Initialize news sentiment (first fetch)
    log("BOOT", "Fetching crypto news sentiment...")
    news.update_news_sentiment()

    # Initialize trader
    if config.TRADE_MODE == "DEMO":
        _trader = DemoTrader(usd_php)
        balance_php = config.DEMO_BALANCE_PHP
    else:
        _trader = LiveTrader(usd_php)
        balance_usdt = exchange.get_wallet_balance()
        balance_php = balance_usdt * usd_php

    log("BOOT", f"Mode: {config.TRADE_MODE} | Balance: ₱{balance_php:,.0f} | "
        f"Pairs: {len(pairs)}")
    log("BOOT", f"Leverage: {config.LEVERAGE}x | SL: {config.STOP_LOSS_ROI_PCT}% | "
        f"TP: +{config.TAKE_PROFIT_ROI_PCT}% | Trail: {config.TRAILING_STOP_ACTIVATE_ROI}%/"
        f"{config.TRAILING_STOP_TRAIL_ROI}%")

    # Start trailing stop monitor
    _trader.start_trailing_monitor()

    # Main loop
    scan_interval = 60  # seconds between full scans
    position_log_interval = 30
    last_position_log = 0

    log("BOOT", "Bot started. Press Ctrl+C to stop.")
    print("-" * 60)

    while not _shutdown.is_set():
        try:
            # Refresh pairs periodically (every 10 scans just re-use cached)
            scan_pairs(pairs, _trader, usd_php)

            # Log positions
            now = time.time()
            if now - last_position_log > position_log_interval:
                _trader.log_positions()
                last_position_log = now

            # Check for closed positions (LIVE mode)
            if config.TRADE_MODE == "LIVE":
                _trader.check_closed_positions()

            # Wait for next scan
            for _ in range(scan_interval):
                if _shutdown.is_set():
                    break
                time.sleep(1)

        except KeyboardInterrupt:
            break
        except Exception as e:
            log_error("MAIN", str(e))
            time.sleep(10)

    # ─── SHUTDOWN ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    log("SHUTDOWN", "Graceful shutdown initiated...")

    _trader.stop()

    if config.TRADE_MODE == "DEMO":
        summary = _trader.get_position_summary()
        log("SUMMARY", f"Total trades: {summary['total_trades']}")
        log("SUMMARY", f"Final balance: ₱{summary['balance_php']:,.0f}")
        log("SUMMARY", f"Total PnL: ₱{summary['pnl_php']:+,.0f}")
        if summary["history"]:
            print("\nLast trades:")
            for t in summary["history"]:
                print(f"  {t['symbol']} {t['side']} ROI:{t['roi']:+.1f}% "
                      f"PnL:₱{t['pnl_php']:+,.0f} [{t['reason']}]")
    else:
        active, closed = _trader.get_position_summary()
        log("SUMMARY", f"Active: {len(active)} | Closed: {len(closed)}")
        total_pnl = sum(p.close_pnl for p in closed)
        log("SUMMARY", f"Realized PnL: ₱{total_pnl:+,.0f}")

    print("=" * 60)
    close_logger()


if __name__ == "__main__":
    main()
