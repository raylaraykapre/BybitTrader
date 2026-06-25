"""
smc.py - Smart Money Concepts (SMC) analysis
Implements: Break of Structure (BOS), Change of Character (CHoCH),
Fair Value Gaps (FVG), Order Blocks, Liquidity Sweeps
"""


def find_swing_points(highs, lows, lookback=5):
    """Identify swing highs and swing lows.
    A swing high = high[i] is the highest of the surrounding `lookback` candles.
    A swing low = low[i] is the lowest of the surrounding `lookback` candles.
    Returns: (swing_highs, swing_lows) — lists of (index, price)
    """
    swing_highs = []
    swing_lows = []
    n = len(highs)

    for i in range(lookback, n - lookback):
        # Swing high: current high is highest in window
        is_sh = True
        for j in range(i - lookback, i + lookback + 1):
            if j != i and highs[j] >= highs[i]:
                is_sh = False
                break
        if is_sh:
            swing_highs.append((i, highs[i]))

        # Swing low: current low is lowest in window
        is_sl = True
        for j in range(i - lookback, i + lookback + 1):
            if j != i and lows[j] <= lows[i]:
                is_sl = False
                break
        if is_sl:
            swing_lows.append((i, lows[i]))

    return swing_highs, swing_lows


def detect_bos(highs, lows, closes, lookback=5):
    """Detect Break of Structure (BOS).
    BOS Bull: price breaks above the most recent swing high (trend continuation UP)
    BOS Bear: price breaks below the most recent swing low (trend continuation DOWN)

    Returns: {"direction": "BULL"|"BEAR"|None, "level": float, "candle_idx": int}
    """
    swing_highs, swing_lows = find_swing_points(highs, lows, lookback)

    if not swing_highs or not swing_lows:
        return {"direction": None, "level": 0, "candle_idx": -1}

    last_sh_idx, last_sh_price = swing_highs[-1]
    last_sl_idx, last_sl_price = swing_lows[-1]

    n = len(closes)
    latest_close = closes[-1]

    # BOS Bullish: current price broke above the last swing high
    if latest_close > last_sh_price and (n - 1) > last_sh_idx:
        return {"direction": "BULL", "level": last_sh_price, "candle_idx": n - 1}

    # BOS Bearish: current price broke below the last swing low
    if latest_close < last_sl_price and (n - 1) > last_sl_idx:
        return {"direction": "BEAR", "level": last_sl_price, "candle_idx": n - 1}

    return {"direction": None, "level": 0, "candle_idx": -1}


def detect_choch(highs, lows, closes, lookback=5):
    """Detect Change of Character (CHoCH).
    CHoCH = first sign of trend reversal.
    - In uptrend (making higher highs/lows), a break below the last swing low = CHoCH bearish
    - In downtrend (lower highs/lows), a break above the last swing high = CHoCH bullish

    Returns: {"reversal": "BULL"|"BEAR"|None, "level": float}
    """
    swing_highs, swing_lows = find_swing_points(highs, lows, lookback)

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return {"reversal": None, "level": 0}

    # Determine current trend from swing structure
    sh1_price = swing_highs[-2][1]
    sh2_price = swing_highs[-1][1]
    sl1_price = swing_lows[-2][1]
    sl2_price = swing_lows[-1][1]

    latest_close = closes[-1]

    # Uptrend: higher highs AND higher lows
    is_uptrend = sh2_price > sh1_price and sl2_price > sl1_price
    # Downtrend: lower highs AND lower lows
    is_downtrend = sh2_price < sh1_price and sl2_price < sl1_price

    if is_uptrend:
        # CHoCH bearish: price breaks below the last swing low in an uptrend
        if latest_close < sl2_price:
            return {"reversal": "BEAR", "level": sl2_price}

    if is_downtrend:
        # CHoCH bullish: price breaks above the last swing high in a downtrend
        if latest_close > sh2_price:
            return {"reversal": "BULL", "level": sh2_price}

    return {"reversal": None, "level": 0}


def find_fvg(highs, lows, opens, closes):
    """Find Fair Value Gaps (FVG) — imbalances where price moved too fast.
    Bullish FVG: gap between candle[i-2] high and candle[i] low (candle[i-1] body too large)
    Bearish FVG: gap between candle[i] high and candle[i-2] low

    Returns list of recent FVGs: [{"type": "BULL"|"BEAR", "top": float, "bottom": float, "idx": int}]
    """
    fvgs = []
    n = len(highs)

    for i in range(2, n):
        # Bullish FVG: low of current candle > high of candle 2 bars ago
        if lows[i] > highs[i - 2]:
            fvgs.append({
                "type": "BULL",
                "top": lows[i],
                "bottom": highs[i - 2],
                "idx": i
            })

        # Bearish FVG: high of current candle < low of candle 2 bars ago
        if highs[i] < lows[i - 2]:
            fvgs.append({
                "type": "BEAR",
                "top": lows[i - 2],
                "bottom": highs[i],
                "idx": i
            })

    # Return only recent unfilled FVGs (last 20 candles)
    recent = [f for f in fvgs if f["idx"] >= n - 20]

    # Check if FVG has been filled (price returned to the gap)
    unfilled = []
    for fvg in recent:
        filled = False
        for j in range(fvg["idx"] + 1, n):
            if fvg["type"] == "BULL":
                # Filled if price came back down into the gap
                if lows[j] <= fvg["top"]:
                    filled = True
                    break
            else:
                # Filled if price came back up into the gap
                if highs[j] >= fvg["bottom"]:
                    filled = True
                    break
        if not filled:
            unfilled.append(fvg)

    return unfilled


def find_order_blocks(highs, lows, opens, closes, lookback=5):
    """Find Order Blocks — the last opposing candle before a strong move.
    Bullish OB: last bearish candle before a strong bullish BOS
    Bearish OB: last bullish candle before a strong bearish BOS

    Returns list of recent OBs: [{"type": "BULL"|"BEAR", "top": float, "bottom": float, "idx": int}]
    """
    obs = []
    n = len(closes)
    swing_highs, swing_lows = find_swing_points(highs, lows, lookback)

    # Find bullish order blocks (last red candle before break of swing high)
    for sh_idx, sh_price in swing_highs:
        # Look for candles after this swing high that broke it
        for i in range(sh_idx + 1, min(sh_idx + 15, n)):
            if closes[i] > sh_price:
                # Found the break. Now find the last bearish candle before the break
                for j in range(i - 1, max(i - 6, sh_idx - 1), -1):
                    if closes[j] < opens[j]:  # bearish candle
                        obs.append({
                            "type": "BULL",
                            "top": highs[j],
                            "bottom": lows[j],
                            "idx": j
                        })
                        break
                break

    # Find bearish order blocks (last green candle before break of swing low)
    for sl_idx, sl_price in swing_lows:
        for i in range(sl_idx + 1, min(sl_idx + 15, n)):
            if closes[i] < sl_price:
                for j in range(i - 1, max(i - 6, sl_idx - 1), -1):
                    if closes[j] > opens[j]:  # bullish candle
                        obs.append({
                            "type": "BEAR",
                            "top": highs[j],
                            "bottom": lows[j],
                            "idx": j
                        })
                        break
                break

    # Return only recent and untested OBs
    recent = [ob for ob in obs if ob["idx"] >= n - 50]

    # Filter: only keep OBs that price hasn't returned to yet
    untested = []
    for ob in recent:
        tested = False
        for j in range(ob["idx"] + 1, n):
            if ob["type"] == "BULL":
                if lows[j] <= ob["top"]:
                    tested = True
                    break
            else:
                if highs[j] >= ob["bottom"]:
                    tested = True
                    break
        if not tested:
            untested.append(ob)

    return untested[-5:]  # keep last 5 relevant OBs


def detect_liquidity_sweep(highs, lows, closes, lookback=5):
    """Detect liquidity sweeps — price wicks beyond swing level then closes back.
    Bullish sweep: wick below swing low but close above it (grabbed sell stops)
    Bearish sweep: wick above swing high but close below it (grabbed buy stops)

    Returns: {"type": "BULL"|"BEAR"|None, "swept_level": float}
    """
    swing_highs, swing_lows = find_swing_points(highs, lows, lookback)

    if not swing_highs or not swing_lows:
        return {"type": None, "swept_level": 0}

    last_close = closes[-1]
    last_low = lows[-1]
    last_high = highs[-1]

    # Bullish sweep: wick went below recent swing low but closed above it
    for sl_idx, sl_price in reversed(swing_lows[-3:]):
        if last_low < sl_price and last_close > sl_price:
            return {"type": "BULL", "swept_level": sl_price}

    # Bearish sweep: wick went above recent swing high but closed below it
    for sh_idx, sh_price in reversed(swing_highs[-3:]):
        if last_high > sh_price and last_close < sh_price:
            return {"type": "BEAR", "swept_level": sh_price}

    return {"type": None, "swept_level": 0}


# ─── COMBINED SMC SIGNAL ──────────────────────────────────────

def analyze_smc(candles):
    """Full SMC analysis on candle data.
    Returns: {
        "direction": "LONG"|"SHORT"|None,
        "score": int (0-25),
        "bos": dict,
        "choch": dict,
        "fvg_count": int,
        "ob_near": bool,
        "sweep": dict
    }
    """
    if len(candles) < 30:
        return {"direction": None, "score": 0}

    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]
    opens = [c[1] for c in candles]
    closes = [c[4] for c in candles]
    price = closes[-1]

    score = 0
    direction_votes = {"LONG": 0, "SHORT": 0}

    # 1. Break of Structure
    bos = detect_bos(highs, lows, closes)
    if bos["direction"] == "BULL":
        direction_votes["LONG"] += 2
        score += 10
    elif bos["direction"] == "BEAR":
        direction_votes["SHORT"] += 2
        score += 10

    # 2. Change of Character (reversal warning)
    choch = detect_choch(highs, lows, closes)
    if choch["reversal"] == "BULL":
        direction_votes["LONG"] += 1
        score += 5
    elif choch["reversal"] == "BEAR":
        direction_votes["SHORT"] += 1
        score += 5

    # 3. Fair Value Gaps — price near an unfilled FVG = high probability entry
    fvgs = find_fvg(highs, lows, opens, closes)
    bull_fvg_near = False
    bear_fvg_near = False
    for fvg in fvgs:
        if fvg["type"] == "BULL":
            # Price near/at bullish FVG = potential long entry
            if fvg["bottom"] <= price <= fvg["top"] * 1.005:
                bull_fvg_near = True
        elif fvg["type"] == "BEAR":
            if fvg["bottom"] * 0.995 <= price <= fvg["top"]:
                bear_fvg_near = True

    if bull_fvg_near:
        direction_votes["LONG"] += 1
        score += 5
    if bear_fvg_near:
        direction_votes["SHORT"] += 1
        score += 5

    # 4. Order Blocks — price at OB = institutional entry zone
    obs = find_order_blocks(highs, lows, opens, closes)
    ob_near = False
    for ob in obs:
        if ob["type"] == "BULL":
            # Price at or near bullish OB
            if ob["bottom"] * 0.998 <= price <= ob["top"] * 1.002:
                direction_votes["LONG"] += 1
                score += 5
                ob_near = True
        elif ob["type"] == "BEAR":
            if ob["bottom"] * 0.998 <= price <= ob["top"] * 1.002:
                direction_votes["SHORT"] += 1
                score += 5
                ob_near = True

    # 5. Liquidity Sweep
    sweep = detect_liquidity_sweep(highs, lows, closes)
    if sweep["type"] == "BULL":
        direction_votes["LONG"] += 2
        score += 10
    elif sweep["type"] == "BEAR":
        direction_votes["SHORT"] += 2
        score += 10

    # Determine direction
    if direction_votes["LONG"] > direction_votes["SHORT"]:
        direction = "LONG"
    elif direction_votes["SHORT"] > direction_votes["LONG"]:
        direction = "SHORT"
    else:
        direction = None

    return {
        "direction": direction,
        "score": score,
        "bos": bos,
        "choch": choch,
        "fvg_count": len(fvgs),
        "ob_near": ob_near,
        "sweep": sweep
    }
