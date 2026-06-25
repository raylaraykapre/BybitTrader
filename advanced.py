"""
advanced.py - Advanced strategy layers
Implements: Hidden Divergence, Session Filter, BTC Correlation,
Volatility Regime, Volume Profile approximation
"""
import math
from datetime import datetime, timezone

import indicators as ind


# ─── SESSION FILTER ───────────────────────────────────────────

# Session times in UTC
SESSIONS = {
    "ASIAN":  (0, 8),    # 00:00 - 08:00 UTC (Tokyo/Sydney)
    "LONDON": (8, 13),   # 08:00 - 13:00 UTC (London open)
    "NY":     (13, 21),  # 13:00 - 21:00 UTC (New York)
    "DEAD":   (21, 24),  # 21:00 - 00:00 UTC (low volume)
}


def get_current_session():
    """Get current trading session based on UTC time.
    Returns: {"session": str, "quality": str, "score_mult": float}
    """
    now = datetime.now(timezone.utc)
    hour = now.hour

    if 8 <= hour < 13:
        return {
            "session": "LONDON",
            "quality": "HIGH",
            "score_mult": 1.2  # boost signals during London
        }
    elif 13 <= hour < 21:
        return {
            "session": "NY",
            "quality": "HIGH",
            "score_mult": 1.15  # good volume during NY
        }
    elif 0 <= hour < 8:
        return {
            "session": "ASIAN",
            "quality": "MEDIUM",
            "score_mult": 0.9  # reduce during Asian (ranging)
        }
    else:
        return {
            "session": "DEAD",
            "quality": "LOW",
            "score_mult": 0.7  # heavily reduce during dead zone
        }


# ─── HIDDEN DIVERGENCE ───────────────────────────────────────

def detect_hidden_divergence(closes, period=14, lookback=30):
    """Detect hidden RSI divergence (continuation signals).

    Hidden Bullish: price makes HIGHER low, RSI makes LOWER low → strong buy
    Hidden Bearish: price makes LOWER high, RSI makes HIGHER high → strong sell

    These have higher win rates than regular divergence in trending markets.

    Returns: {"type": "BULL"|"BEAR"|None, "strength": float}
    """
    rsi_vals = ind.rsi(closes, period)
    if len(rsi_vals) < lookback:
        return {"type": None, "strength": 0}

    # Align closes with RSI (RSI is shorter by `period` elements)
    offset = len(closes) - len(rsi_vals)
    aligned_closes = closes[offset:]

    n = len(aligned_closes)
    if n < lookback:
        return {"type": None, "strength": 0}

    # Find recent swing lows in price and RSI (for hidden bullish)
    # Look at last `lookback` bars
    recent_closes = aligned_closes[-lookback:]
    recent_rsi = rsi_vals[-lookback:]

    # Find two significant lows (simple: split window in half)
    half = lookback // 2
    first_half_c = recent_closes[:half]
    second_half_c = recent_closes[half:]
    first_half_r = recent_rsi[:half]
    second_half_r = recent_rsi[half:]

    price_low1 = min(first_half_c)
    price_low2 = min(second_half_c)
    rsi_low1 = min(first_half_r)
    rsi_low2 = min(second_half_r)

    price_high1 = max(first_half_c)
    price_high2 = max(second_half_c)
    rsi_high1 = max(first_half_r)
    rsi_high2 = max(second_half_r)

    # Hidden Bullish: price higher low + RSI lower low
    if price_low2 > price_low1 and rsi_low2 < rsi_low1:
        strength = (price_low2 - price_low1) / price_low1 * 100
        return {"type": "BULL", "strength": strength}

    # Hidden Bearish: price lower high + RSI higher high
    if price_high2 < price_high1 and rsi_high2 > rsi_high1:
        strength = (price_high1 - price_high2) / price_high1 * 100
        return {"type": "BEAR", "strength": strength}

    return {"type": None, "strength": 0}


# ─── VOLATILITY REGIME ────────────────────────────────────────

def get_volatility_regime(highs, lows, closes, atr_period=14, lookback=100):
    """Determine if market is in low/normal/high volatility regime.

    Uses ATR percentile over the last `lookback` candles.
    - Bottom 20% → LOW volatility (skip or tighten TP)
    - 20-80% → NORMAL
    - Top 20% → HIGH volatility (reduce size, widen stops)

    Returns: {"regime": "LOW"|"NORMAL"|"HIGH", "atr_pct": float, "multiplier": float}
    """
    atr_vals = ind.atr(highs, lows, closes, atr_period)
    if len(atr_vals) < lookback:
        return {"regime": "NORMAL", "atr_pct": 50, "multiplier": 1.0}

    recent_atrs = atr_vals[-lookback:]
    current_atr = atr_vals[-1]

    # Calculate percentile
    sorted_atrs = sorted(recent_atrs)
    rank = sum(1 for a in sorted_atrs if a <= current_atr)
    percentile = (rank / len(sorted_atrs)) * 100

    if percentile < 20:
        return {
            "regime": "LOW",
            "atr_pct": percentile,
            "multiplier": 0.7  # reduce position size / skip
        }
    elif percentile > 80:
        return {
            "regime": "HIGH",
            "atr_pct": percentile,
            "multiplier": 0.8  # reduce size due to wild swings
        }
    else:
        return {
            "regime": "NORMAL",
            "atr_pct": percentile,
            "multiplier": 1.0
        }


# ─── BTC CORRELATION CHECK ───────────────────────────────────

def check_btc_correlation(btc_candles_1h, alt_direction):
    """Check if BTC trend supports the alt trade direction.

    Rule: Don't long alts when BTC is breaking down.
          Don't short alts when BTC is pumping.

    Returns: {"aligned": bool, "btc_bias": str, "penalty": int}
    """
    if not btc_candles_1h or len(btc_candles_1h) < 50:
        return {"aligned": True, "btc_bias": "UNKNOWN", "penalty": 0}

    closes = [c[4] for c in btc_candles_1h]
    highs = [c[2] for c in btc_candles_1h]
    lows = [c[3] for c in btc_candles_1h]

    # BTC trend from EMA alignment
    ema21 = ind.ema(closes, 21)
    ema50 = ind.ema(closes, 50)

    if not ema21 or not ema50:
        return {"aligned": True, "btc_bias": "UNKNOWN", "penalty": 0}

    btc_bull = ema21[-1] > ema50[-1] and closes[-1] > ema21[-1]
    btc_bear = ema21[-1] < ema50[-1] and closes[-1] < ema21[-1]

    # Check recent momentum (last 3 candles)
    recent_momentum = closes[-1] - closes[-4] if len(closes) >= 4 else 0
    strong_dump = recent_momentum < 0 and abs(recent_momentum) / closes[-4] > 0.02  # >2% drop
    strong_pump = recent_momentum > 0 and recent_momentum / closes[-4] > 0.02

    if btc_bull or strong_pump:
        btc_bias = "BULL"
    elif btc_bear or strong_dump:
        btc_bias = "BEAR"
    else:
        btc_bias = "NEUTRAL"

    # Check alignment
    if alt_direction == "LONG" and btc_bias == "BEAR":
        return {"aligned": False, "btc_bias": btc_bias, "penalty": -15}
    elif alt_direction == "SHORT" and btc_bias == "BULL":
        return {"aligned": False, "btc_bias": btc_bias, "penalty": -15}
    elif alt_direction == "LONG" and btc_bias == "BULL":
        return {"aligned": True, "btc_bias": btc_bias, "penalty": 10}  # bonus
    elif alt_direction == "SHORT" and btc_bias == "BEAR":
        return {"aligned": True, "btc_bias": btc_bias, "penalty": 10}  # bonus
    else:
        return {"aligned": True, "btc_bias": btc_bias, "penalty": 0}


# ─── VOLUME PROFILE (simplified) ─────────────────────────────

def volume_profile_poc(highs, lows, closes, volumes, bins=20):
    """Calculate approximate Point of Control (price level with most volume).

    Returns: {"poc": float, "value_area_high": float, "value_area_low": float,
              "price_vs_poc": "ABOVE"|"BELOW"|"AT"}
    """
    if not highs or not volumes:
        return {"poc": 0, "value_area_high": 0, "value_area_low": 0, "price_vs_poc": "AT"}

    price_min = min(lows)
    price_max = max(highs)
    if price_max == price_min:
        return {"poc": price_max, "value_area_high": price_max,
                "value_area_low": price_min, "price_vs_poc": "AT"}

    bin_size = (price_max - price_min) / bins
    volume_at_price = [0.0] * bins

    # Distribute volume across price bins
    for i in range(len(closes)):
        typical = (highs[i] + lows[i] + closes[i]) / 3.0
        bin_idx = int((typical - price_min) / bin_size)
        bin_idx = min(bin_idx, bins - 1)
        volume_at_price[bin_idx] += volumes[i]

    # POC = bin with highest volume
    poc_bin = volume_at_price.index(max(volume_at_price))
    poc = price_min + (poc_bin + 0.5) * bin_size

    # Value Area = 70% of volume around POC
    total_vol = sum(volume_at_price)
    target_vol = total_vol * 0.7
    accumulated = volume_at_price[poc_bin]
    low_bin = poc_bin
    high_bin = poc_bin

    while accumulated < target_vol:
        expand_up = volume_at_price[high_bin + 1] if high_bin + 1 < bins else 0
        expand_down = volume_at_price[low_bin - 1] if low_bin - 1 >= 0 else 0

        if expand_up >= expand_down and high_bin + 1 < bins:
            high_bin += 1
            accumulated += volume_at_price[high_bin]
        elif low_bin - 1 >= 0:
            low_bin -= 1
            accumulated += volume_at_price[low_bin]
        else:
            break

    value_area_high = price_min + (high_bin + 1) * bin_size
    value_area_low = price_min + low_bin * bin_size

    # Current price vs POC
    current = closes[-1]
    if current > poc * 1.002:
        pos = "ABOVE"
    elif current < poc * 0.998:
        pos = "BELOW"
    else:
        pos = "AT"

    return {
        "poc": poc,
        "value_area_high": value_area_high,
        "value_area_low": value_area_low,
        "price_vs_poc": pos
    }


# ─── COMBINED ADVANCED ANALYSIS ───────────────────────────────

def get_advanced_score(candles_5m, candles_1h, direction, btc_candles_1h=None):
    """Run all advanced analysis layers and return score adjustment.

    Returns: {
        "score_adjustment": int,
        "session": dict,
        "divergence": dict,
        "volatility": dict,
        "btc_check": dict,
        "volume_profile": dict,
        "reasons": list
    }
    """
    score_adj = 0
    reasons = []

    closes_5m = [c[4] for c in candles_5m]
    highs_5m = [c[2] for c in candles_5m]
    lows_5m = [c[3] for c in candles_5m]
    volumes_5m = [c[5] for c in candles_5m]
    closes_1h = [c[4] for c in candles_1h]
    highs_1h = [c[2] for c in candles_1h]
    lows_1h = [c[3] for c in candles_1h]

    # 1. Session filter
    session = get_current_session()
    if session["quality"] == "LOW":
        score_adj -= 10
        reasons.append(f"Dead session (-10)")
    elif session["quality"] == "HIGH":
        score_adj += 5
        reasons.append(f"{session['session']} session (+5)")

    # 2. Hidden divergence
    divergence = detect_hidden_divergence(closes_5m)
    if divergence["type"] == "BULL" and direction == "LONG":
        score_adj += 15
        reasons.append("Hidden bull divergence (+15)")
    elif divergence["type"] == "BEAR" and direction == "SHORT":
        score_adj += 15
        reasons.append("Hidden bear divergence (+15)")
    elif divergence["type"] and divergence["type"] != direction[0:4]:
        score_adj -= 5
        reasons.append(f"Divergence conflicts (-5)")

    # 3. Volatility regime
    volatility = get_volatility_regime(highs_1h, lows_1h, closes_1h)
    if volatility["regime"] == "LOW":
        score_adj -= 10
        reasons.append("Low volatility regime (-10)")
    elif volatility["regime"] == "HIGH":
        score_adj -= 5
        reasons.append("High volatility (caution) (-5)")

    # 4. BTC correlation
    btc_check = {"aligned": True, "btc_bias": "N/A", "penalty": 0}
    if btc_candles_1h:
        btc_check = check_btc_correlation(btc_candles_1h, direction)
        score_adj += btc_check["penalty"]
        if not btc_check["aligned"]:
            reasons.append(f"BTC {btc_check['btc_bias']} conflicts ({btc_check['penalty']:+d})")
        elif btc_check["penalty"] > 0:
            reasons.append(f"BTC {btc_check['btc_bias']} confirms (+{btc_check['penalty']})")

    # 5. Volume Profile
    vp = volume_profile_poc(highs_5m, lows_5m, closes_5m, volumes_5m)
    if direction == "LONG" and vp["price_vs_poc"] == "ABOVE":
        score_adj += 5
        reasons.append("Price above POC (+5)")
    elif direction == "SHORT" and vp["price_vs_poc"] == "BELOW":
        score_adj += 5
        reasons.append("Price below POC (+5)")
    elif direction == "LONG" and vp["price_vs_poc"] == "BELOW":
        score_adj -= 5
        reasons.append("Price below POC, risky long (-5)")

    return {
        "score_adjustment": score_adj,
        "session": session,
        "divergence": divergence,
        "volatility": volatility,
        "btc_check": btc_check,
        "volume_profile": vp,
        "reasons": reasons
    }
