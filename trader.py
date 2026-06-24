"""
trader.py - Order placement, trailing stop loop, position tracker (LIVE mode)
"""
import time
import threading

import config
import exchange
from logger import log, log_error


class Position:
    """Represents an open position."""
    def __init__(self, symbol, side, entry_price, qty, leverage, usd_php, tp_roi=None):
        self.symbol = symbol
        self.side = side  # "LONG" or "SHORT"
        self.entry_price = entry_price
        self.qty = qty
        self.leverage = leverage
        self.usd_php = usd_php
        self.tp_roi = tp_roi if tp_roi else 350  # dynamic TP per position
        self.open_time = time.time()
        self.trailing_active = False
        self.trail_floor_roi = 0.0
        self.closed = False
        self.close_reason = ""
        self.close_pnl = 0.0

    def calc_roi(self, current_price):
        """Calculate ROI % with leverage."""
        if self.entry_price == 0:
            return 0.0
        if self.side == "LONG":
            roi = ((current_price - self.entry_price) / self.entry_price) * 100 * self.leverage
        else:
            roi = ((self.entry_price - current_price) / self.entry_price) * 100 * self.leverage
        return roi

    def calc_pnl_usdt(self, current_price):
        """Calculate PnL in USDT."""
        if self.side == "LONG":
            return (current_price - self.entry_price) * self.qty
        else:
            return (self.entry_price - current_price) * self.qty

    def calc_pnl_php(self, current_price):
        """Calculate PnL in PHP."""
        return self.calc_pnl_usdt(current_price) * self.usd_php


class LiveTrader:
    """Manages live trading execution."""

    def __init__(self, usd_php_rate):
        self.positions = []
        self.usd_php = usd_php_rate
        self.lock = threading.Lock()
        self._trailing_thread = None
        self._running = True

    def recover_positions(self):
        """Load existing open positions from Bybit on startup.
        This allows the bot to resume tracking after a restart.
        """
        try:
            open_positions = exchange.get_positions()
            if not open_positions:
                log("RECOVER", "No open positions found on Bybit")
                return

            recovered = 0
            for p in open_positions:
                size = float(p.get("size", 0))
                if size <= 0:
                    continue

                symbol = p.get("symbol", "")
                side_str = p.get("side", "")
                entry_price = float(p.get("avgPrice", 0) or p.get("entryPrice", 0))
                leverage = int(float(p.get("leverage", config.LEVERAGE)))
                qty = size

                # Map Bybit side to our direction
                if side_str == "Buy":
                    direction = "LONG"
                elif side_str == "Sell":
                    direction = "SHORT"
                else:
                    continue

                if entry_price <= 0:
                    continue

                # Create position object
                pos = Position(symbol, direction, entry_price, qty, leverage, self.usd_php)

                # Check if trailing should already be active based on current ROI
                current_price = exchange.get_ticker_price(symbol)
                if current_price > 0:
                    roi = pos.calc_roi(current_price)
                    if roi >= config.TRAILING_STOP_ACTIVATE_ROI:
                        pos.trailing_active = True
                        pos.trail_floor_roi = roi - config.TRAILING_STOP_TRAIL_ROI

                with self.lock:
                    self.positions.append(pos)

                # Log recovered position
                if current_price > 0:
                    pnl_php = pos.calc_pnl_php(current_price)
                    roi = pos.calc_roi(current_price)
                    trail = "ON" if pos.trailing_active else "OFF"
                    log("RECOVER", f"{direction} {symbol} | Entry:₱{entry_price * self.usd_php:,.0f} | "
                        f"PnL:₱{pnl_php:+,.0f} | ROI:{roi:+.1f}% | Trail:{trail}")
                else:
                    log("RECOVER", f"{direction} {symbol} | Entry:₱{entry_price * self.usd_php:,.0f}")

                recovered += 1

            if recovered > 0:
                log("RECOVER", f"Resumed tracking {recovered} open position(s)")
            else:
                log("RECOVER", "No open positions found on Bybit")

        except Exception as e:
            log_error("RECOVER", f"Position recovery failed: {e}")

    def start_trailing_monitor(self):
        """Start background thread for trailing stop monitoring."""
        self._trailing_thread = threading.Thread(target=self._trailing_loop, daemon=True)
        self._trailing_thread.start()

    def stop(self):
        self._running = False

    def open_slots(self):
        with self.lock:
            active = [p for p in self.positions if not p.closed]
            return config.MAX_OPEN_POSITIONS - len(active)

    def has_position(self, symbol):
        with self.lock:
            return any(p.symbol == symbol and not p.closed for p in self.positions)

    def open_position(self, symbol, direction, balance_usdt, tp_roi=None):
        """Execute a new position entry."""
        if self.open_slots() <= 0:
            return None
        if self.has_position(symbol):
            return None

        # Use dynamic TP or fallback to config
        if tp_roi is None:
            tp_roi = config.TAKE_PROFIT_ROI_PCT

        # Calculate position size (WALLET_USAGE_PCT is whole number e.g. 85 = 85%)
        alloc_usdt = (balance_usdt * config.WALLET_USAGE_PCT / 100) / config.MAX_OPEN_POSITIONS

        # Calculate leverage based on pair's max and LEVERAGE_USAGE_PCT
        leverage = exchange.calc_leverage(symbol)

        # Set leverage
        exchange.set_leverage(symbol, leverage)

        # Get current price
        price = exchange.get_ticker_price(symbol)
        if price <= 0:
            log_error("TRADE", f"Cannot get price for {symbol}")
            return None

        # Calculate quantity
        qty = (alloc_usdt * leverage) / price
        # Round to reasonable precision
        if price > 1000:
            qty = round(qty, 3)
        elif price > 1:
            qty = round(qty, 1)
        else:
            qty = round(qty, 0)

        if qty <= 0:
            return None

        # ── Calculate SL/TP prices using Bybit ROI% formula ──
        # Bybit ROI formula:
        #   LONG ROI% = ((mark - entry) / entry) * leverage * 100
        #   SHORT ROI% = ((entry - mark) / entry) * leverage * 100
        # Solving for price at target ROI%:
        #   LONG:  target_price = entry * (1 + ROI% / (leverage * 100))
        #   SHORT: target_price = entry * (1 - ROI% / (leverage * 100))
        #
        # Example: entry=100, leverage=10x, SL ROI=-42%
        #   LONG SL price = 100 * (1 + (-42)/(10*100)) = 100 * 0.958 = 95.8
        #   Verify: ((95.8-100)/100)*10*100 = -42% ✓

        sl_roi = config.STOP_LOSS_ROI_PCT   # e.g. -42 (negative)

        if direction == "LONG":
            side = "Buy"
            sl_price = price * (1 + sl_roi / (leverage * 100))
            tp_price = price * (1 + tp_roi / (leverage * 100))
        else:
            side = "Sell"
            sl_price = price * (1 - sl_roi / (leverage * 100))
            tp_price = price * (1 - tp_roi / (leverage * 100))

        # ── Liquidation price safety check ──
        # Liquidation occurs at ~100% ROI loss (margin fully consumed)
        # Liq price approximation (isolated margin):
        #   LONG liq = entry * (1 - 1/leverage)  (simplified, ignores fees)
        #   SHORT liq = entry * (1 + 1/leverage)
        # Ensure SL is at least LIQUIDATION_BUFFER_PCT% of price BEFORE liquidation
        liq_buffer = config.LIQUIDATION_BUFFER_PCT / 100.0

        if direction == "LONG":
            liq_price = price * (1 - 1.0 / leverage)
            min_sl = liq_price * (1 + liq_buffer)  # buffer above liquidation
            if sl_price < min_sl:
                old_sl = sl_price
                sl_price = min_sl
                actual_roi = ((sl_price - price) / price) * leverage * 100
                log("SL ADJUST", f"{symbol} SL moved from {old_sl:.2f} to "
                    f"{sl_price:.2f} (liq safety) ROI:{actual_roi:.1f}%")
        else:
            liq_price = price * (1 + 1.0 / leverage)
            max_sl = liq_price * (1 - liq_buffer)  # buffer below liquidation
            if sl_price > max_sl:
                old_sl = sl_price
                sl_price = max_sl
                actual_roi = ((price - sl_price) / price) * leverage * 100
                log("SL ADJUST", f"{symbol} SL moved from {old_sl:.2f} to "
                    f"{sl_price:.2f} (liq safety) ROI:{actual_roi:.1f}%")

        sl_price = round(sl_price, 2)
        tp_price = round(tp_price, 2)

        # Place order
        order_id = exchange.place_order(symbol, side, qty, sl_price, tp_price)
        if not order_id:
            log_error("TRADE", f"Order failed for {symbol}")
            return None

        # Create position tracker
        pos = Position(symbol, direction, price, qty, leverage, self.usd_php, tp_roi)
        with self.lock:
            self.positions.append(pos)

        entry_php = price * self.usd_php
        log("ORDER", f"{direction} {symbol} | Entry:₱{entry_php:,.0f} "
            f"SL:{config.STOP_LOSS_ROI_PCT}% TP:+{tp_roi}% "
            f"Lev:{leverage}x")

        return pos

    def _trailing_loop(self):
        """Background loop to manage trailing stops."""
        while self._running:
            try:
                with self.lock:
                    active = [p for p in self.positions if not p.closed]

                for pos in active:
                    price = exchange.get_ticker_price(pos.symbol)
                    if price <= 0:
                        continue

                    roi = pos.calc_roi(price)

                    # Check if trailing should activate
                    if not pos.trailing_active and roi >= config.TRAILING_STOP_ACTIVATE_ROI:
                        pos.trailing_active = True
                        pos.trail_floor_roi = roi - config.TRAILING_STOP_TRAIL_ROI

                        # Set trailing stop on exchange
                        trail_dist = price * (config.TRAILING_STOP_TRAIL_ROI / (100 * pos.leverage))
                        exchange.set_trailing_stop(pos.symbol, round(trail_dist, 2))

                        log("TRAIL ON", f"{pos.symbol} | Floor locked at "
                            f"+{pos.trail_floor_roi:.0f}% ROI")

                    # Update trail floor if ROI keeps climbing
                    elif pos.trailing_active:
                        new_floor = roi - config.TRAILING_STOP_TRAIL_ROI
                        if new_floor > pos.trail_floor_roi:
                            pos.trail_floor_roi = new_floor

                time.sleep(5)
            except Exception as e:
                log_error("TRAIL", str(e))
                time.sleep(10)

    def check_closed_positions(self):
        """Check exchange for positions that have been closed (SL/TP hit)."""
        try:
            open_positions = exchange.get_positions()
            open_symbols = {p.get("symbol") for p in open_positions
                          if float(p.get("size", 0)) > 0}

            with self.lock:
                for pos in self.positions:
                    if not pos.closed and pos.symbol not in open_symbols:
                        price = exchange.get_ticker_price(pos.symbol)
                        pos.closed = True
                        pos.close_pnl = pos.calc_pnl_php(price)
                        roi = pos.calc_roi(price)

                        if roi <= config.STOP_LOSS_ROI_PCT:
                            pos.close_reason = "SL HIT"
                        elif roi >= pos.tp_roi:
                            pos.close_reason = "TP HIT"
                        else:
                            pos.close_reason = "TRAIL HIT" if pos.trailing_active else "CLOSED"

                        log("CLOSED", f"{pos.symbol} | PnL:₱{pos.close_pnl:+,.0f} | "
                            f"ROI:{roi:+.1f}% {pos.close_reason}")
        except Exception as e:
            log_error("CHECK", str(e))

    def get_position_summary(self):
        """Get summary of all positions."""
        with self.lock:
            active = [p for p in self.positions if not p.closed]
            closed = [p for p in self.positions if p.closed]
        return active, closed

    def log_positions(self):
        """Log current position status."""
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
