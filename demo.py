"""
demo.py - Paper trade engine using live Bybit prices, virtual fills
"""
import json
import os
import time
import threading

import config
import exchange
from logger import log, log_error

# State file for persisting demo positions across restarts
_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo_state.json")


class DemoPosition:
    """Virtual position for demo trading."""
    def __init__(self, symbol, side, entry_price, qty, leverage, usd_php, alloc_usdt):
        self.symbol = symbol
        self.side = side  # "LONG" or "SHORT"
        self.entry_price = entry_price
        self.qty = qty
        self.leverage = leverage
        self.usd_php = usd_php
        self.alloc_usdt = alloc_usdt
        self.open_time = time.time()
        self.trailing_active = False
        self.trail_floor_roi = 0.0
        self.trail_highest_roi = 0.0
        self.closed = False
        self.close_reason = ""
        self.close_pnl_usdt = 0.0
        self.close_price = 0.0
        self.sl_roi = config.STOP_LOSS_ROI_PCT  # effective SL (may be adjusted for liq safety)
        self.tp_roi = config.TAKE_PROFIT_ROI_PCT  # effective TP (dynamic per trade)

    def calc_roi(self, current_price):
        if self.entry_price == 0:
            return 0.0
        if self.side == "LONG":
            return ((current_price - self.entry_price) / self.entry_price) * 100 * self.leverage
        else:
            return ((self.entry_price - current_price) / self.entry_price) * 100 * self.leverage

    def calc_pnl_usdt(self, current_price):
        if self.side == "LONG":
            return (current_price - self.entry_price) * self.qty
        else:
            return (self.entry_price - current_price) * self.qty

    def calc_pnl_php(self, current_price):
        return self.calc_pnl_usdt(current_price) * self.usd_php


class DemoTrader:
    """Paper trading engine with live prices."""

    def __init__(self, usd_php_rate):
        self.usd_php = usd_php_rate
        self.balance_php = float(config.DEMO_BALANCE_PHP)
        self.balance_usdt = self.balance_php / usd_php_rate
        self.initial_balance_php = self.balance_php
        self.positions = []
        self.trade_history = []
        self.lock = threading.Lock()
        self._running = True
        self._monitor_thread = None

        # Try to recover saved state
        self._load_state()

    def _save_state(self):
        """Persist demo state to disk so positions survive restarts."""
        try:
            with self.lock:
                state = {
                    "balance_usdt": self.balance_usdt,
                    "balance_php": self.balance_php,
                    "initial_balance_php": self.initial_balance_php,
                    "positions": [],
                    "trade_history": self.trade_history[-50:]  # keep last 50
                }
                for p in self.positions:
                    if not p.closed:
                        state["positions"].append({
                            "symbol": p.symbol,
                            "side": p.side,
                            "entry_price": p.entry_price,
                            "qty": p.qty,
                            "leverage": p.leverage,
                            "alloc_usdt": p.alloc_usdt,
                            "open_time": p.open_time,
                            "trailing_active": p.trailing_active,
                            "trail_floor_roi": p.trail_floor_roi,
                            "trail_highest_roi": p.trail_highest_roi,
                            "sl_roi": p.sl_roi,
                            "tp_roi": p.tp_roi
                        })

            with open(_STATE_FILE, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            log_error("DEMO", f"Failed to save state: {e}")

    def _load_state(self):
        """Load demo state from disk on startup."""
        if not os.path.exists(_STATE_FILE):
            return

        try:
            with open(_STATE_FILE, "r") as f:
                state = json.load(f)

            self.balance_usdt = state.get("balance_usdt", self.balance_usdt)
            self.balance_php = state.get("balance_php", self.balance_php)
            self.initial_balance_php = state.get("initial_balance_php", self.initial_balance_php)
            self.trade_history = state.get("trade_history", [])

            recovered = 0
            for pd in state.get("positions", []):
                pos = DemoPosition(
                    symbol=pd["symbol"],
                    side=pd["side"],
                    entry_price=pd["entry_price"],
                    qty=pd["qty"],
                    leverage=pd["leverage"],
                    usd_php=self.usd_php,
                    alloc_usdt=pd["alloc_usdt"]
                )
                pos.open_time = pd.get("open_time", time.time())
                pos.trailing_active = pd.get("trailing_active", False)
                pos.trail_floor_roi = pd.get("trail_floor_roi", 0.0)
                pos.trail_highest_roi = pd.get("trail_highest_roi", 0.0)
                pos.sl_roi = pd.get("sl_roi", config.STOP_LOSS_ROI_PCT)
                pos.tp_roi = pd.get("tp_roi", config.TAKE_PROFIT_ROI_PCT)

                self.positions.append(pos)

                # Log recovered position with current PnL
                current_price = exchange.get_ticker_price(pos.symbol)
                if current_price > 0:
                    pnl = pos.calc_pnl_php(current_price)
                    roi = pos.calc_roi(current_price)
                    trail = "ON" if pos.trailing_active else "OFF"
                    log("RECOVER", f"{pos.side} {pos.symbol} | "
                        f"Entry:₱{pos.entry_price * self.usd_php:,.0f} | "
                        f"PnL:₱{pnl:+,.0f} | ROI:{roi:+.1f}% | Trail:{trail}")
                else:
                    log("RECOVER", f"{pos.side} {pos.symbol} | "
                        f"Entry:₱{pos.entry_price * self.usd_php:,.0f}")
                recovered += 1

            if recovered > 0:
                log("RECOVER", f"Resumed {recovered} demo position(s) | "
                    f"Balance:₱{self.balance_php:,.0f}")
            else:
                log("RECOVER", f"No open demo positions | Balance:₱{self.balance_php:,.0f}")

        except Exception as e:
            log_error("DEMO", f"Failed to load state: {e}")
            log("RECOVER", "Starting fresh (state file corrupt or unreadable)")

    def start_trailing_monitor(self):
        """Start background monitoring for SL/TP/trailing."""
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop(self):
        self._running = False

    def open_slots(self):
        with self.lock:
            active = [p for p in self.positions if not p.closed]
            return config.MAX_OPEN_POSITIONS - len(active)

    def has_position(self, symbol):
        with self.lock:
            return any(p.symbol == symbol and not p.closed for p in self.positions)

    def get_free_balance_usdt(self):
        with self.lock:
            used = sum(p.alloc_usdt for p in self.positions if not p.closed)
            return max(0, self.balance_usdt - used)

    def open_position(self, symbol, direction, tp_roi=None):
        """Paper execute a new position."""
        if self.open_slots() <= 0:
            return None
        if self.has_position(symbol):
            return None

        # Use dynamic TP or fallback to config
        if tp_roi is None:
            tp_roi = config.TAKE_PROFIT_ROI_PCT

        free_usdt = self.get_free_balance_usdt()
        alloc_usdt = (free_usdt * config.WALLET_USAGE_PCT / 100) / max(1, self.open_slots())

        # Calculate leverage based on pair's max and LEVERAGE_USAGE_PCT
        leverage = exchange.calc_leverage(symbol)

        # Get current live price
        price = exchange.get_ticker_price(symbol)
        if price <= 0:
            log_error("DEMO", f"Cannot get price for {symbol}")
            return None

        # Calculate quantity
        qty = (alloc_usdt * leverage) / price
        if qty <= 0:
            return None

        # ── Liquidation price safety check ──
        # Ensure SL ROI doesn't exceed liquidation threshold
        # At 100% loss ROI = liquidation. Buffer by LIQUIDATION_BUFFER_PCT.
        # Max safe SL ROI = -(100 - LIQUIDATION_BUFFER_PCT)%
        sl_roi = config.STOP_LOSS_ROI_PCT  # e.g. -42
        max_loss_roi = -(100 - config.LIQUIDATION_BUFFER_PCT)  # e.g. -95
        if sl_roi < max_loss_roi:
            sl_roi = max_loss_roi
            log("SL ADJUST", f"{symbol} SL capped at {sl_roi}% ROI (liq safety)")

        pos = DemoPosition(symbol, direction, price, qty, leverage,
                          self.usd_php, alloc_usdt)
        pos.sl_roi = sl_roi  # store effective SL ROI for monitoring
        pos.tp_roi = tp_roi  # store dynamic TP ROI

        with self.lock:
            self.positions.append(pos)

        entry_php = price * self.usd_php
        log("ORDER", f"{direction} {symbol} | Entry:₱{entry_php:,.0f} "
            f"SL:{sl_roi}% TP:+{tp_roi}% Lev:{leverage}x")

        self._save_state()
        return pos

    def _close_position(self, pos, price, reason):
        """Close a demo position."""
        pos.closed = True
        pos.close_price = price
        pos.close_reason = reason
        pos.close_pnl_usdt = pos.calc_pnl_usdt(price)

        pnl_php = pos.close_pnl_usdt * self.usd_php
        roi = pos.calc_roi(price)

        with self.lock:
            self.balance_usdt += pos.close_pnl_usdt
            self.balance_php = self.balance_usdt * self.usd_php
            self.trade_history.append({
                "symbol": pos.symbol,
                "side": pos.side,
                "entry": pos.entry_price,
                "exit": price,
                "pnl_usdt": pos.close_pnl_usdt,
                "pnl_php": pnl_php,
                "roi": roi,
                "reason": reason
            })

        log("CLOSED", f"{pos.symbol} | PnL:₱{pnl_php:+,.0f} | ROI:{roi:+.1f}% {reason}")
        log("BALANCE", f"Total:₱{self.balance_php:,.0f} | "
            f"Free:₱{self.get_free_balance_usdt() * self.usd_php:,.0f}")
        self._save_state()

    def _monitor_loop(self):
        """Background loop to check SL/TP/trailing for all positions."""
        while self._running:
            try:
                with self.lock:
                    active = [p for p in self.positions if not p.closed]

                for pos in active:
                    price = exchange.get_ticker_price(pos.symbol)
                    if price <= 0:
                        continue

                    roi = pos.calc_roi(price)

                    # Check stop loss (use position's effective SL ROI)
                    effective_sl = getattr(pos, 'sl_roi', config.STOP_LOSS_ROI_PCT)
                    if roi <= effective_sl:
                        self._close_position(pos, price, "SL HIT")
                        continue

                    # Check take profit (use position's dynamic TP ROI)
                    effective_tp = getattr(pos, 'tp_roi', config.TAKE_PROFIT_ROI_PCT)
                    if roi >= effective_tp:
                        self._close_position(pos, price, "TP HIT")
                        continue

                    # Trailing stop logic
                    if not pos.trailing_active:
                        if roi >= config.TRAILING_STOP_ACTIVATE_ROI:
                            pos.trailing_active = True
                            pos.trail_highest_roi = roi
                            pos.trail_floor_roi = roi - config.TRAILING_STOP_TRAIL_ROI
                            log("TRAIL ON", f"{pos.symbol} | Floor locked at "
                                f"+{pos.trail_floor_roi:.0f}% ROI")
                    else:
                        # Update highest ROI seen
                        if roi > pos.trail_highest_roi:
                            pos.trail_highest_roi = roi
                            pos.trail_floor_roi = roi - config.TRAILING_STOP_TRAIL_ROI

                        # Check if price fell below trail floor
                        if roi <= pos.trail_floor_roi:
                            self._close_position(pos, price, "TRAIL HIT")
                            continue

                time.sleep(3)
            except Exception as e:
                log_error("DEMO_MON", str(e))
                time.sleep(10)

    def log_positions(self):
        """Log current demo positions."""
        with self.lock:
            active = [p for p in self.positions if not p.closed]

        for i, pos in enumerate(active, 1):
            price = exchange.get_ticker_price(pos.symbol)
            if price > 0:
                pnl = pos.calc_pnl_php(price)
                roi = pos.calc_roi(price)
                trail = "ON" if pos.trailing_active else "OFF"
                log("POSITION", f"#{i} {pos.symbol} | PnL:₱{pnl:+,.0f} | "
                    f"ROI:{roi:+.1f}% | Trail:{trail}")

    def get_position_summary(self):
        """Get summary for shutdown display."""
        with self.lock:
            active = [p for p in self.positions if not p.closed]
            return {
                "active": len(active),
                "total_trades": len(self.trade_history),
                "balance_php": self.balance_php,
                "pnl_php": self.balance_php - self.initial_balance_php,
                "history": self.trade_history[-10:]  # last 10
            }
