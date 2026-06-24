"""
strategy.py - Dual timeframe analysis engine + TradingView strategy scoring
"""
import indicators as ind
from logger import log, log_error


# ─── 1H TREND BIAS ANALYSIS ──────────────────────────────────

def analyze_primary_tf(candles, funding_rate=0.0):
    """Analyze PRIMARY_TF (1H) for trend bias.
    Returns dict: {bias: 'BULL'|'BEAR'|'NEUTRAL', details: {...}}
    """
    if len(candles) < 200:
        return {"bias": "NEUTRAL", "details": {}}

    closes = [c[4] for c in candles]
    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]

    # EMA alignment
    ema21 = ind.ema(closes, 21)
    ema50 = ind.ema(closes, 50)
    ema200 = ind.ema(closes, 200)

    if not ema21 or not ema50 or not ema200:
        return {"bias": "NEUTRAL", "details": {}}

    ema_bull = ema21[-1] > ema50[-1] > ema200[-1]
    ema_bear = ema21[-1] < ema50[-1] < ema200[-1]

    # MACD
    macd_line, signal_line, histogram = ind.macd(closes)
    macd_bull = len(histogram) > 1 and histogram[-1] > 0 and histogram[-1] > histogram[-2]
    macd_bear = len(histogram) > 1 and histogram[-1] < 0 and histogram[-1] < histogram[-2]

    # RSI
    rsi_vals = ind.rsi(closes, 14)
    rsi_val = rsi_vals[-1] if rsi_vals else 50.0
    rsi_bull = rsi_val > 55
    rsi_bear = rsi_val < 45
    rsi_neutral = 45 <= rsi_val <= 55

    # Bollinger Band width (squeeze detection)
    _, _, _, bandwidth = ind.bollinger_bands(closes, 20, 2.0)
    bb_squeeze = len(bandwidth) > 0 and bandwidth[-1] < 4.0  # tight squeeze

    # ADX
    adx_vals = ind.adx(highs, lows, closes, 14)
    adx_val = adx_vals[-1] if adx_vals else 0.0
    trending = adx_val > 25

    # Funding rate bias
    funding_bull = funding_rate < -0.0001  # negative = shorts paying longs
    funding_bear = funding_rate > 0.0003   # high positive = potential top

    # SuperTrend 1H
    st_line, st_dir = ind.supertrend(highs, lows, closes, 10, 3.0)
    st_bull = len(st_dir) > 0 and st_dir[-1] == 1
    st_bear = len(st_dir) > 0 and st_dir[-1] == -1

    # Determine overall bias
    bull_score = sum([ema_bull, macd_bull, rsi_bull, trending and st_bull, funding_bull])
    bear_score = sum([ema_bear, macd_bear, rsi_bear, trending and st_bear, funding_bear])

    if rsi_neutral and not trending:
        bias = "NEUTRAL"
    elif bull_score >= 3:
        bias = "BULL"
    elif bear_score >= 3:
        bias = "BEAR"
    else:
        bias = "NEUTRAL"

    details = {
        "ema_bull": ema_bull, "ema_bear": ema_bear,
        "macd_bull": macd_bull, "macd_bear": macd_bear,
        "rsi": rsi_val, "adx": adx_val, "trending": trending,
        "bb_squeeze": bb_squeeze, "st_bull": st_bull,
        "funding_rate": funding_rate
    }

    return {"bias": bias, "details": details}


# ─── 5M ENTRY ANALYSIS + TV STRATEGIES ───────────────────────

def analyze_entry_tf(candles, primary_bias, orderbook_ratio=1.0):
    """Analyze ENTRY_TF (5M) for entry signals with TV strategy scoring.
    Returns dict: {direction: 'LONG'|'SHORT'|None, score: int, strategies: {...}}
    """
    if len(candles) < 100:
        return {"direction": None, "score": 0, "strategies": {}}

    closes = [c[4] for c in candles]
    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]
    volumes = [c[5] for c in candles]

    score = 0
    direction_votes = {"LONG": 0, "SHORT": 0}
    strategies = {}

    # ─── BASE INDICATORS ─────────────────────────────────────
    ema9 = ind.ema(closes, 9)
    ema21 = ind.ema(closes, 21)
    rsi_vals = ind.rsi(closes, 14)
    macd_line, signal_line, histogram = ind.macd(closes)

    # EMA crossover
    if len(ema9) > 1 and len(ema21) > 1:
        min_l = min(len(ema9), len(ema21))
        if ema9[-1] > ema21[-1] and ema9[-2] <= ema21[-2]:
            direction_votes["LONG"] += 1
        elif ema9[-1] < ema21[-1] and ema9[-2] >= ema21[-2]:
            direction_votes["SHORT"] += 1

    # MACD signal cross
    if len(macd_line) > 1 and len(signal_line) > 1:
        ml = min(len(macd_line), len(signal_line))
        macd_l = macd_line[-ml:]
        sig_l = signal_line[-min(ml, len(signal_line)):]
        if len(sig_l) > 1:
            if macd_l[-1] > sig_l[-1] and macd_l[-2] <= sig_l[-2]:
                direction_votes["LONG"] += 1
            elif macd_l[-1] < sig_l[-1] and macd_l[-2] >= sig_l[-2]:
                direction_votes["SHORT"] += 1

    # RSI divergence (simplified)
    if len(rsi_vals) > 2:
        if rsi_vals[-1] < 30:
            direction_votes["LONG"] += 1
        elif rsi_vals[-1] > 70:
            direction_votes["SHORT"] += 1

    # Orderbook imbalance
    if orderbook_ratio > 1.5:
        direction_votes["LONG"] += 1
    elif orderbook_ratio < 0.67:
        direction_votes["SHORT"] += 1

    # Engulfing candle
    if len(candles) >= 2:
        prev = candles[-2]
        curr = candles[-1]
        # Bullish engulfing
        if (prev[4] < prev[1] and curr[4] > curr[1] and
            curr[4] > prev[1] and curr[1] < prev[4]):
            direction_votes["LONG"] += 1
        # Bearish engulfing
        elif (prev[4] > prev[1] and curr[4] < curr[1] and
              curr[4] < prev[1] and curr[1] > prev[4]):
            direction_votes["SHORT"] += 1

    # ─── TV STRATEGY 1: SUPERTREND ───────────────────────────
    st_line, st_dir = ind.supertrend(highs, lows, closes, 10, 3.0)
    if st_dir:
        if st_dir[-1] == 1:
            direction_votes["LONG"] += 1
            strategies["ST"] = "LONG"
            score += 15
        elif st_dir[-1] == -1:
            direction_votes["SHORT"] += 1
            strategies["ST"] = "SHORT"
            score += 15

    # ─── TV STRATEGY 2: SQUEEZE MOMENTUM ─────────────────────
    sqz_hist, sqz_on = ind.squeeze_momentum(highs, lows, closes)
    if len(sqz_hist) >= 2 and len(sqz_on) >= 2:
        # Squeeze release with momentum flip
        if not sqz_on[-1] and sqz_on[-2]:  # squeeze just released
            if sqz_hist[-1] > 0 and sqz_hist[-2] <= 0:
                direction_votes["LONG"] += 1
                strategies["SQZ"] = "LONG"
                score += 15
            elif sqz_hist[-1] < 0 and sqz_hist[-2] >= 0:
                direction_votes["SHORT"] += 1
                strategies["SQZ"] = "SHORT"
                score += 15
        elif sqz_hist[-1] > 0 and sqz_hist[-2] <= 0:
            strategies["SQZ"] = "LONG"
            score += 10
            direction_votes["LONG"] += 1
        elif sqz_hist[-1] < 0 and sqz_hist[-2] >= 0:
            strategies["SQZ"] = "SHORT"
            score += 10
            direction_votes["SHORT"] += 1

    # ─── TV STRATEGY 3: SSL CHANNEL ──────────────────────────
    ssl_up, ssl_down = ind.ssl_channel(highs, lows, closes, 10)
    if len(ssl_up) >= 2 and len(ssl_down) >= 2:
        # Cross detection
        if ssl_up[-1] > ssl_down[-1] and ssl_up[-2] <= ssl_down[-2]:
            direction_votes["LONG"] += 1
            strategies["SSL"] = "LONG"
            score += 10
        elif ssl_up[-1] < ssl_down[-1] and ssl_up[-2] >= ssl_down[-2]:
            direction_votes["SHORT"] += 1
            strategies["SSL"] = "SHORT"
            score += 10
        elif ssl_up[-1] > ssl_down[-1]:
            strategies["SSL"] = "LONG"
        elif ssl_up[-1] < ssl_down[-1]:
            strategies["SSL"] = "SHORT"

    # ─── TV STRATEGY 4: WAE ──────────────────────────────────
    wae_up, wae_down, wae_dz = ind.waddah_attar(closes)
    if wae_up and wae_down and wae_dz:
        if wae_up[-1] > wae_dz[-1] and wae_up[-1] > 0:
            direction_votes["LONG"] += 1
            strategies["WAE"] = "LONG"
            score += 15
        elif wae_down[-1] > wae_dz[-1] and wae_down[-1] > 0:
            direction_votes["SHORT"] += 1
            strategies["WAE"] = "SHORT"
            score += 15

    # ─── TV STRATEGY 5: VWAP ─────────────────────────────────
    vwap_line, vwap_upper, vwap_lower = ind.vwap(highs, lows, closes, volumes)
    if vwap_line:
        price = closes[-1]
        if price > vwap_line[-1]:
            direction_votes["LONG"] += 1
            strategies["VWAP"] = "LONG"
            score += 10
        elif price < vwap_line[-1]:
            direction_votes["SHORT"] += 1
            strategies["VWAP"] = "SHORT"
            score += 10

    # ─── TV STRATEGY 6: HMA ──────────────────────────────────
    hma_vals = ind.hma(closes, 55)
    if len(hma_vals) >= 2:
        if hma_vals[-1] > hma_vals[-2]:
            direction_votes["LONG"] += 1
            strategies["HMA"] = "LONG"
            score += 10
        elif hma_vals[-1] < hma_vals[-2]:
            direction_votes["SHORT"] += 1
            strategies["HMA"] = "SHORT"
            score += 10

    # ─── TV STRATEGY 7: PIVOT POINTS ─────────────────────────
    # Use the previous session's candle data for pivots
    if len(candles) > 50:
        # Approximate previous session (last 288 5m candles = 24h)
        session_candles = candles[-288:] if len(candles) >= 288 else candles
        prev_h = max(c[2] for c in session_candles[:-1])
        prev_l = min(c[3] for c in session_candles[:-1])
        prev_c = session_candles[-2][4]
        pivots = ind.pivot_points(prev_h, prev_l, prev_c)
        price = closes[-1]

        # Check proximity to pivot levels
        levels = sorted(pivots.values())
        near_level = False
        for lvl in levels:
            if abs(price - lvl) / price < 0.002:  # within 0.2%
                near_level = True
                break

        # Check chop zone (between two close pivots)
        in_chop = False
        for i in range(len(levels) - 1):
            if levels[i] < price < levels[i + 1]:
                gap = (levels[i + 1] - levels[i]) / price
                if gap < 0.003:  # pivots too close
                    in_chop = True
                break

        if near_level and not in_chop:
            if price > pivots["PP"]:
                strategies["PIV"] = "LONG"
                score += 10
            else:
                strategies["PIV"] = "SHORT"
                score += 10

    # ─── TV STRATEGY 8: ICHIMOKU ─────────────────────────────
    tenkan, kijun, senkou_a, senkou_b, chikou = ind.ichimoku(highs, lows, closes)
    if len(senkou_a) > 26 and len(senkou_b) > 26:
        price = closes[-1]
        cloud_top = max(senkou_a[-26], senkou_b[-26])
        cloud_bottom = min(senkou_a[-26], senkou_b[-26])

        # TK cross
        tk_cross_bull = (len(tenkan) > 1 and len(kijun) > 1 and
                         tenkan[-1] > kijun[-1] and tenkan[-2] <= kijun[-2])
        tk_cross_bear = (len(tenkan) > 1 and len(kijun) > 1 and
                         tenkan[-1] < kijun[-1] and tenkan[-2] >= kijun[-2])

        if price > cloud_top:
            direction_votes["LONG"] += 1
            strategies["ICHI"] = "LONG"
            if tk_cross_bull:
                score += 15
            else:
                score += 10
        elif price < cloud_bottom:
            direction_votes["SHORT"] += 1
            strategies["ICHI"] = "SHORT"
            if tk_cross_bear:
                score += 15
            else:
                score += 10

    # ─── STOCHASTIC RSI ──────────────────────────────────────
    stoch_k, stoch_d = ind.stoch_rsi(closes)
    if len(stoch_k) >= 2 and len(stoch_d) >= 2:
        if stoch_k[-1] < 20 and stoch_k[-1] > stoch_d[-1] and stoch_k[-2] <= stoch_d[-2]:
            direction_votes["LONG"] += 1
        elif stoch_k[-1] > 80 and stoch_k[-1] < stoch_d[-1] and stoch_k[-2] >= stoch_d[-2]:
            direction_votes["SHORT"] += 1

    # ─── DETERMINE FINAL DIRECTION ───────────────────────────
    long_votes = direction_votes["LONG"]
    short_votes = direction_votes["SHORT"]

    if long_votes > short_votes:
        direction = "LONG"
    elif short_votes > long_votes:
        direction = "SHORT"
    else:
        direction = None

    # ─── 1H TREND ALIGNMENT BONUS ────────────────────────────
    if direction:
        if (direction == "LONG" and primary_bias == "BULL") or \
           (direction == "SHORT" and primary_bias == "BEAR"):
            score += 20
        elif (direction == "LONG" and primary_bias == "BEAR") or \
             (direction == "SHORT" and primary_bias == "BULL"):
            # Conflict - always skip
            direction = None
            score = 0

    return {"direction": direction, "score": score, "strategies": strategies}


# ─── COMBINED SIGNAL ──────────────────────────────────────────

def get_signal(candles_1h, candles_5m, funding_rate=0.0, orderbook_ratio=1.0):
    """Full dual-TF signal analysis.
    Returns: {direction, score, bias_1h, strategies, skip_reason}
    """
    primary = analyze_primary_tf(candles_1h, funding_rate)
    entry = analyze_entry_tf(candles_5m, primary["bias"], orderbook_ratio)

    skip_reason = None
    if primary["bias"] == "NEUTRAL":
        skip_reason = "1H neutral/ranging"
    elif entry["direction"] is None:
        skip_reason = "No clear 5M direction"
    elif entry["score"] == 0:
        skip_reason = f"1H:{primary['bias']} 5M:{entry['direction']} Conflict"

    return {
        "direction": entry["direction"],
        "score": entry["score"],
        "bias_1h": primary["bias"],
        "strategies": entry["strategies"],
        "skip_reason": skip_reason,
        "details_1h": primary["details"]
    }
