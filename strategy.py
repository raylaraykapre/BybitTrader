"""
strategy.py - Multi-timeframe analysis engine + TradingView strategy scoring

Scans timeframes from highest to lowest (D, 720, 240, 60, 30, 15, 5).
Picks the highest TF with a clear trend as "trend TF", then uses the
next lower TF as "entry TF" for precise signal scoring.
"""
import indicators as ind
import config
from logger import log, log_error


# ─── TIMEFRAME HIERARCHY ─────────────────────────────────────
# Ordered from highest to lowest. Each entry: (bybit_interval, label, minutes)
TF_HIERARCHY = [
    ("D",   "24H",   1440),
    ("720", "12H",    720),
    ("240", "4H",     240),
    ("60",  "1H",     60),
    ("30",  "30M",    30),
    ("15",  "15M",    15),
    ("5",   "5M",     5),
]

# Minimum candles needed for analysis
MIN_CANDLES_TREND = 100   # trend TF needs at least 100 candles
MIN_CANDLES_ENTRY = 80    # entry TF needs at least 80 candles


# ─── TREND BIAS ANALYSIS (any timeframe) ─────────────────────

def analyze_trend(candles, funding_rate=0.0):
    """Analyze a timeframe for trend bias.
    Works on any TF — uses EMA alignment, MACD, RSI, ADX, SuperTrend.
    Returns: {bias: 'BULL'|'BEAR'|'NEUTRAL', strength: 0-5, details: {...}}
    """
    if len(candles) < MIN_CANDLES_TREND:
        return {"bias": "NEUTRAL", "strength": 0, "details": {}}

    closes = [c[4] for c in candles]
    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]

    # EMA alignment
    ema21 = ind.ema(closes, 21)
    ema50 = ind.ema(closes, 50)

    # Use EMA 200 if we have enough data, else EMA 100
    if len(candles) >= 200:
        ema_long = ind.ema(closes, 200)
    else:
        ema_long = ind.ema(closes, 100)

    if not ema21 or not ema50 or not ema_long:
        return {"bias": "NEUTRAL", "strength": 0, "details": {}}

    ema_bull = ema21[-1] > ema50[-1] > ema_long[-1]
    ema_bear = ema21[-1] < ema50[-1] < ema_long[-1]

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

    # ADX
    adx_vals = ind.adx(highs, lows, closes, 14)
    adx_val = adx_vals[-1] if adx_vals else 0.0
    trending = adx_val > 25

    # SuperTrend
    st_line, st_dir = ind.supertrend(highs, lows, closes, 10, 3.0)
    st_bull = len(st_dir) > 0 and st_dir[-1] == 1
    st_bear = len(st_dir) > 0 and st_dir[-1] == -1

    # Bollinger Band width (squeeze detection)
    _, _, _, bandwidth = ind.bollinger_bands(closes, 20, 2.0)
    bb_squeeze = len(bandwidth) > 0 and bandwidth[-1] < 4.0

    # Funding rate bias (only relevant for crypto)
    funding_bull = funding_rate < -0.0001
    funding_bear = funding_rate > 0.0003

    # Score each direction
    bull_score = sum([ema_bull, macd_bull, rsi_bull, trending and st_bull, funding_bull])
    bear_score = sum([ema_bear, macd_bear, rsi_bear, trending and st_bear, funding_bear])

    # Determine bias
    if rsi_neutral and not trending:
        bias = "NEUTRAL"
        strength = 0
    elif bull_score >= 3:
        bias = "BULL"
        strength = bull_score
    elif bear_score >= 3:
        bias = "BEAR"
        strength = bear_score
    else:
        bias = "NEUTRAL"
        strength = max(bull_score, bear_score)

    details = {
        "ema_bull": ema_bull, "ema_bear": ema_bear,
        "macd_bull": macd_bull, "macd_bear": macd_bear,
        "rsi": rsi_val, "adx": adx_val, "trending": trending,
        "bb_squeeze": bb_squeeze, "st_bull": st_bull, "st_bear": st_bear,
        "funding_rate": funding_rate
    }

    return {"bias": bias, "strength": strength, "details": details}


# ─── ENTRY SIGNAL SCORING (any timeframe) ────────────────────

def score_entry(candles, primary_bias, orderbook_ratio=1.0):
    """Score entry signals on a timeframe using all TV strategies.
    Returns: {direction: 'LONG'|'SHORT'|None, score: int, strategies: {...}}
    """
    if len(candles) < MIN_CANDLES_ENTRY:
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

    # RSI extremes
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
        if (prev[4] < prev[1] and curr[4] > curr[1] and
            curr[4] > prev[1] and curr[1] < prev[4]):
            direction_votes["LONG"] += 1
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
    if len(candles) > 50:
        session_candles = candles[-288:] if len(candles) >= 288 else candles
        prev_h = max(c[2] for c in session_candles[:-1])
        prev_l = min(c[3] for c in session_candles[:-1])
        prev_c = session_candles[-2][4]
        pivots = ind.pivot_points(prev_h, prev_l, prev_c)
        price = closes[-1]

        levels = sorted(pivots.values())
        near_level = False
        for lvl in levels:
            if abs(price - lvl) / price < 0.002:
                near_level = True
                break

        in_chop = False
        for i in range(len(levels) - 1):
            if levels[i] < price < levels[i + 1]:
                gap = (levels[i + 1] - levels[i]) / price
                if gap < 0.003:
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

        tk_cross_bull = (len(tenkan) > 1 and len(kijun) > 1 and
                         tenkan[-1] > kijun[-1] and tenkan[-2] <= kijun[-2])
        tk_cross_bear = (len(tenkan) > 1 and len(kijun) > 1 and
                         tenkan[-1] < kijun[-1] and tenkan[-2] >= kijun[-2])

        if price > cloud_top:
            direction_votes["LONG"] += 1
            strategies["ICHI"] = "LONG"
            score += 15 if tk_cross_bull else 10
        elif price < cloud_bottom:
            direction_votes["SHORT"] += 1
            strategies["ICHI"] = "SHORT"
            score += 15 if tk_cross_bear else 10

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

    # ─── TREND ALIGNMENT BONUS ────────────────────────────────
    if direction:
        if (direction == "LONG" and primary_bias == "BULL") or \
           (direction == "SHORT" and primary_bias == "BEAR"):
            score += 20
        elif (direction == "LONG" and primary_bias == "BEAR") or \
             (direction == "SHORT" and primary_bias == "BULL"):
            # Conflict — always skip
            direction = None
            score = 0

    return {"direction": direction, "score": score, "strategies": strategies}


# ─── MULTI-TIMEFRAME SCANNER ─────────────────────────────────

def find_best_timeframes(candles_by_tf, funding_rate=0.0):
    """Scan all timeframes from highest to lowest.
    Find the highest TF with a clear trend, then use the next lower TF for entry.

    Args:
        candles_by_tf: dict of {interval_str: candles_list}
        funding_rate: current funding rate

    Returns: {
        trend_tf: str (interval),
        trend_tf_label: str,
        trend_bias: str,
        trend_strength: int,
        entry_tf: str (interval),
        entry_tf_label: str,
    } or None if no clear setup found.
    """
    # Filter to timeframes we actually have data for
    available_tfs = []
    for interval, label, minutes in TF_HIERARCHY:
        if interval in candles_by_tf and len(candles_by_tf[interval]) >= MIN_CANDLES_ENTRY:
            available_tfs.append((interval, label, minutes))

    if len(available_tfs) < 2:
        return None

    # Scan from highest to lowest — find highest TF with clear bias
    trend_tf = None
    trend_label = None
    trend_bias = "NEUTRAL"
    trend_strength = 0

    for i, (interval, label, minutes) in enumerate(available_tfs):
        candles = candles_by_tf[interval]
        result = analyze_trend(candles, funding_rate)

        if result["bias"] != "NEUTRAL" and result["strength"] >= 3:
            trend_tf = interval
            trend_label = label
            trend_bias = result["bias"]
            trend_strength = result["strength"]
            break  # Use the highest TF with a clear trend

    if trend_tf is None:
        return None

    # Find entry TF = next lower TF after the trend TF
    trend_idx = None
    for i, (interval, label, minutes) in enumerate(available_tfs):
        if interval == trend_tf:
            trend_idx = i
            break

    if trend_idx is None or trend_idx >= len(available_tfs) - 1:
        return None

    # Entry TF is the next one down
    entry_tf, entry_label, _ = available_tfs[trend_idx + 1]

    return {
        "trend_tf": trend_tf,
        "trend_tf_label": trend_label,
        "trend_bias": trend_bias,
        "trend_strength": trend_strength,
        "entry_tf": entry_tf,
        "entry_tf_label": entry_label,
    }


# ─── DYNAMIC TAKE PROFIT CALCULATION ─────────────────────────

def calc_dynamic_tp(candles_entry, candles_trend, direction, score, leverage):
    """Calculate optimal take profit ROI% based on market structure.
    Uses ATR, key levels, BB, SuperTrend distance, and trend strength.
    Returns: int (TP as ROI%)
    """
    closes_e = [c[4] for c in candles_entry]
    highs_e = [c[2] for c in candles_entry]
    lows_e = [c[3] for c in candles_entry]
    closes_t = [c[4] for c in candles_trend]
    highs_t = [c[2] for c in candles_trend]
    lows_t = [c[3] for c in candles_trend]

    price = closes_e[-1]
    if price <= 0:
        return config.TAKE_PROFIT_ROI_PCT

    # 1. ATR-based target from trend TF
    atr_vals = ind.atr(highs_t, lows_t, closes_t, 14)
    atr_val = atr_vals[-1] if atr_vals else price * 0.02
    atr_pct = (atr_val / price) * 100

    if score >= 100:
        atr_mult = 5.0
    elif score >= 85:
        atr_mult = 4.0
    elif score >= 75:
        atr_mult = 3.0
    else:
        atr_mult = 2.5

    atr_tp_roi = atr_pct * atr_mult * leverage

    # 2. Key level distance (pivots)
    level_tp_roi = None
    if len(candles_entry) > 50:
        session_candles = candles_entry[-288:] if len(candles_entry) >= 288 else candles_entry
        prev_h = max(c[2] for c in session_candles[:-1])
        prev_l = min(c[3] for c in session_candles[:-1])
        prev_c = session_candles[-2][4]
        pivots = ind.pivot_points(prev_h, prev_l, prev_c)

        if direction == "LONG":
            targets = sorted([v for v in pivots.values() if v > price])
            if targets:
                dist_pct = (targets[0] - price) / price * 100
                level_tp_roi = dist_pct * leverage * 0.9
        else:
            targets = sorted([v for v in pivots.values() if v < price], reverse=True)
            if targets:
                dist_pct = (price - targets[0]) / price * 100
                level_tp_roi = dist_pct * leverage * 0.9

    # 3. Bollinger Band target
    bb_upper, bb_mid, bb_lower, _ = ind.bollinger_bands(closes_e, 20, 2.0)
    bb_tp_roi = None
    if bb_upper and bb_lower:
        if direction == "LONG" and bb_upper[-1] > price:
            dist_pct = (bb_upper[-1] - price) / price * 100
            bb_tp_roi = dist_pct * leverage
        elif direction == "SHORT" and bb_lower[-1] < price:
            dist_pct = (price - bb_lower[-1]) / price * 100
            bb_tp_roi = dist_pct * leverage

    # 4. ADX trend strength multiplier
    adx_vals = ind.adx(highs_t, lows_t, closes_t, 14)
    adx_val = adx_vals[-1] if adx_vals else 20.0

    if adx_val > 40:
        trend_mult = 1.5
    elif adx_val > 30:
        trend_mult = 1.3
    elif adx_val > 25:
        trend_mult = 1.1
    else:
        trend_mult = 0.9

    # Combine targets
    targets = [atr_tp_roi]
    if level_tp_roi and level_tp_roi > 5:
        targets.append(level_tp_roi)
    if bb_tp_roi and bb_tp_roi > 5:
        targets.append(bb_tp_roi)

    targets.sort()
    if len(targets) >= 3:
        tp_roi = targets[len(targets) // 2]
    elif len(targets) == 2:
        tp_roi = (targets[0] + targets[1]) / 2.0
    else:
        tp_roi = targets[0]

    tp_roi = tp_roi * trend_mult

    # Bounds: min 2:1 R:R, max config ceiling
    sl_roi = abs(config.STOP_LOSS_ROI_PCT)
    min_tp = sl_roi * 2
    max_tp = config.TAKE_PROFIT_ROI_PCT
    tp_roi = max(min_tp, min(tp_roi, max_tp))

    return int(tp_roi)


# ─── MAIN SIGNAL FUNCTION ────────────────────────────────────

def get_signal(candles_1h, candles_5m, funding_rate=0.0, orderbook_ratio=1.0,
               candles_by_tf=None):
    """Full multi-TF signal analysis.

    If candles_by_tf is provided (dict of interval->candles), uses multi-TF
    scanning to find the best trend+entry combination.

    Falls back to the classic 1H trend + 5M entry if multi-TF data not available.

    Returns: {direction, score, bias_1h, strategies, skip_reason, tp_roi,
              trend_tf, entry_tf}
    """
    trend_tf_label = "1H"
    entry_tf_label = "5M"
    trend_candles = candles_1h
    entry_candles = candles_5m

    # ── Multi-TF auto-selection ──
    selected_tf_info = None
    if candles_by_tf and len(candles_by_tf) >= 2:
        tf_result = find_best_timeframes(candles_by_tf, funding_rate)
        if tf_result:
            trend_tf_label = tf_result["trend_tf_label"]
            entry_tf_label = tf_result["entry_tf_label"]
            trend_candles = candles_by_tf[tf_result["trend_tf"]]
            entry_candles = candles_by_tf[tf_result["entry_tf"]]
            selected_tf_info = tf_result

    # ── Analyze trend ──
    primary = analyze_trend(trend_candles, funding_rate)

    # ── Score entry ──
    entry = score_entry(entry_candles, primary["bias"], orderbook_ratio)

    # ── Determine skip reason ──
    skip_reason = None
    if primary["bias"] == "NEUTRAL":
        skip_reason = f"{trend_tf_label} neutral/ranging"
    elif entry["direction"] is None:
        skip_reason = f"No clear {entry_tf_label} direction"
    elif entry["score"] == 0:
        skip_reason = (f"{trend_tf_label}:{primary['bias']} "
                       f"{entry_tf_label}:{entry['direction']} Conflict")

    # ── Dynamic TP ──
    tp_roi = config.TAKE_PROFIT_ROI_PCT
    if entry["direction"] and not skip_reason:
        tp_roi = calc_dynamic_tp(
            entry_candles, trend_candles,
            entry["direction"], entry["score"],
            config.LEVERAGE
        )
        # Only log MTF selection for valid signals
        if selected_tf_info:
            log("MTF", f"Trend:{trend_tf_label}({primary['bias']}) "
                f"Entry:{entry_tf_label} Str:{selected_tf_info['trend_strength']}/5")

    return {
        "direction": entry["direction"],
        "score": entry["score"],
        "bias_1h": primary["bias"],
        "strategies": entry["strategies"],
        "skip_reason": skip_reason,
        "details_1h": primary["details"],
        "tp_roi": tp_roi,
        "trend_tf": trend_tf_label,
        "entry_tf": entry_tf_label,
    }
