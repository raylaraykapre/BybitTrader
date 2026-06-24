"""
indicators.py - All technical indicator calculations
Pure Python stdlib only. All functions take lists of floats (closes, highs, lows, volumes).
"""
import math


# ─── BASIC HELPERS ────────────────────────────────────────────

def sma(data, period):
    """Simple Moving Average."""
    if len(data) < period:
        return []
    result = []
    for i in range(period - 1, len(data)):
        result.append(sum(data[i - period + 1:i + 1]) / period)
    return result


def ema(data, period):
    """Exponential Moving Average."""
    if len(data) < period:
        return []
    k = 2.0 / (period + 1)
    result = [sum(data[:period]) / period]
    for i in range(period, len(data)):
        result.append(data[i] * k + result[-1] * (1 - k))
    return result


def wma(data, period):
    """Weighted Moving Average."""
    if len(data) < period:
        return []
    result = []
    denom = period * (period + 1) / 2.0
    for i in range(period - 1, len(data)):
        s = 0.0
        for j in range(period):
            s += data[i - period + 1 + j] * (j + 1)
        result.append(s / denom)
    return result


def true_range(highs, lows, closes):
    """True Range series."""
    tr = [highs[0] - lows[0]]
    for i in range(1, len(highs)):
        tr.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        ))
    return tr


def stdev(data, period):
    """Standard deviation over rolling window."""
    if len(data) < period:
        return []
    result = []
    for i in range(period - 1, len(data)):
        window = data[i - period + 1:i + 1]
        mean = sum(window) / period
        variance = sum((x - mean) ** 2 for x in window) / period
        result.append(math.sqrt(variance))
    return result


# ─── RSI ──────────────────────────────────────────────────────

def rsi(closes, period=14):
    """Relative Strength Index."""
    if len(closes) < period + 1:
        return []
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    result = []
    if avg_loss == 0:
        result.append(100.0)
    else:
        rs = avg_gain / avg_loss
        result.append(100.0 - 100.0 / (1.0 + rs))

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100.0 - 100.0 / (1.0 + rs))
    return result


# ─── STOCHASTIC RSI ───────────────────────────────────────────

def stoch_rsi(closes, rsi_period=14, stoch_period=14, k_smooth=3, d_smooth=3):
    """Stochastic RSI with %K and %D."""
    rsi_vals = rsi(closes, rsi_period)
    if len(rsi_vals) < stoch_period:
        return [], []

    stoch_k_raw = []
    for i in range(stoch_period - 1, len(rsi_vals)):
        window = rsi_vals[i - stoch_period + 1:i + 1]
        low = min(window)
        high = max(window)
        if high == low:
            stoch_k_raw.append(50.0)
        else:
            stoch_k_raw.append((rsi_vals[i] - low) / (high - low) * 100.0)

    k_line = sma(stoch_k_raw, k_smooth)
    d_line = sma(k_line, d_smooth)
    return k_line, d_line


# ─── MACD ─────────────────────────────────────────────────────

def macd(closes, fast=12, slow=26, signal=9):
    """MACD line, Signal line, Histogram."""
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)

    offset = slow - fast
    macd_line = [ema_fast[i + offset] - ema_slow[i] for i in range(len(ema_slow))]

    signal_line = ema(macd_line, signal)
    offset2 = signal - 1
    histogram = [macd_line[i + offset2] - signal_line[i] for i in range(len(signal_line))]

    return macd_line, signal_line, histogram


# ─── BOLLINGER BANDS ──────────────────────────────────────────

def bollinger_bands(closes, period=20, mult=2.0):
    """Returns (upper, middle, lower, bandwidth)."""
    mid = sma(closes, period)
    sd = stdev(closes, period)
    upper = [mid[i] + mult * sd[i] for i in range(len(mid))]
    lower = [mid[i] - mult * sd[i] for i in range(len(mid))]
    bandwidth = [(upper[i] - lower[i]) / mid[i] * 100 if mid[i] != 0 else 0
                 for i in range(len(mid))]
    return upper, mid, lower, bandwidth


# ─── KELTNER CHANNEL ──────────────────────────────────────────

def keltner_channel(highs, lows, closes, period=20, atr_mult=1.5):
    """Returns (upper, middle, lower)."""
    mid = ema(closes, period)
    tr = true_range(highs, lows, closes)
    atr_vals = ema(tr, period)

    # Align lengths
    min_len = min(len(mid), len(atr_vals))
    mid = mid[-min_len:]
    atr_vals = atr_vals[-min_len:]

    upper = [mid[i] + atr_mult * atr_vals[i] for i in range(min_len)]
    lower = [mid[i] - atr_mult * atr_vals[i] for i in range(min_len)]
    return upper, mid, lower


# ─── ATR ──────────────────────────────────────────────────────

def atr(highs, lows, closes, period=14):
    """Average True Range using EMA smoothing."""
    tr = true_range(highs, lows, closes)
    return ema(tr, period)


# ─── ADX ──────────────────────────────────────────────────────

def adx(highs, lows, closes, period=14):
    """Average Directional Index."""
    if len(highs) < period + 1:
        return []

    plus_dm = []
    minus_dm = []
    for i in range(1, len(highs)):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)

    tr_vals = true_range(highs, lows, closes)[1:]  # skip first
    atr_smooth = ema(tr_vals, period)
    plus_dm_smooth = ema(plus_dm, period)
    minus_dm_smooth = ema(minus_dm, period)

    min_len = min(len(atr_smooth), len(plus_dm_smooth), len(minus_dm_smooth))
    atr_smooth = atr_smooth[-min_len:]
    plus_dm_smooth = plus_dm_smooth[-min_len:]
    minus_dm_smooth = minus_dm_smooth[-min_len:]

    dx_vals = []
    for i in range(min_len):
        if atr_smooth[i] == 0:
            dx_vals.append(0.0)
            continue
        plus_di = 100.0 * plus_dm_smooth[i] / atr_smooth[i]
        minus_di = 100.0 * minus_dm_smooth[i] / atr_smooth[i]
        denom = plus_di + minus_di
        if denom == 0:
            dx_vals.append(0.0)
        else:
            dx_vals.append(100.0 * abs(plus_di - minus_di) / denom)

    adx_vals = ema(dx_vals, period)
    return adx_vals


# ─── SUPERTREND ───────────────────────────────────────────────

def supertrend(highs, lows, closes, period=10, multiplier=3.0):
    """SuperTrend indicator. Returns (st_line, direction) lists.
    direction: 1 = bullish (price above), -1 = bearish (price below).
    """
    atr_vals = atr(highs, lows, closes, period)
    if not atr_vals:
        return [], []

    # Align data to ATR length
    offset = len(closes) - len(atr_vals)
    h = highs[offset:]
    l = lows[offset:]
    c = closes[offset:]
    n = len(c)

    upper_band = [0.0] * n
    lower_band = [0.0] * n
    st = [0.0] * n
    direction = [1] * n

    for i in range(n):
        hl2 = (h[i] + l[i]) / 2.0
        upper_band[i] = hl2 + multiplier * atr_vals[i]
        lower_band[i] = hl2 - multiplier * atr_vals[i]

        if i == 0:
            st[i] = upper_band[i]
            direction[i] = -1 if c[i] < st[i] else 1
            continue

        # Adjust bands
        if lower_band[i] > lower_band[i - 1] or c[i - 1] < lower_band[i - 1]:
            pass
        else:
            lower_band[i] = lower_band[i - 1]

        if upper_band[i] < upper_band[i - 1] or c[i - 1] > upper_band[i - 1]:
            pass
        else:
            upper_band[i] = upper_band[i - 1]

        if direction[i - 1] == 1:
            if c[i] < lower_band[i]:
                direction[i] = -1
                st[i] = upper_band[i]
            else:
                direction[i] = 1
                st[i] = lower_band[i]
        else:
            if c[i] > upper_band[i]:
                direction[i] = 1
                st[i] = lower_band[i]
            else:
                direction[i] = -1
                st[i] = upper_band[i]

    return st, direction


# ─── SQUEEZE MOMENTUM (LazyBear) ─────────────────────────────

def squeeze_momentum(highs, lows, closes, bb_period=20, bb_mult=2.0,
                     kc_period=20, kc_mult=1.5):
    """Squeeze Momentum. Returns (histogram, is_squeeze) lists."""
    bb_upper, bb_mid, bb_lower, _ = bollinger_bands(closes, bb_period, bb_mult)
    kc_upper, kc_mid, kc_lower = keltner_channel(highs, lows, closes, kc_period, kc_mult)

    min_len = min(len(bb_upper), len(kc_upper))
    bb_upper = bb_upper[-min_len:]
    bb_lower = bb_lower[-min_len:]
    kc_upper = kc_upper[-min_len:]
    kc_lower = kc_lower[-min_len:]

    is_squeeze = [bb_lower[i] > kc_lower[i] and bb_upper[i] < kc_upper[i]
                  for i in range(min_len)]

    # Momentum histogram: linear regression of (close - avg(highest_high, lowest_low, sma))
    c = closes[-min_len:]
    h = highs[-min_len:]
    l = lows[-min_len:]

    # Simplified: use close - midline
    midline = [(h[i] + l[i]) / 2.0 for i in range(min_len)]
    sma_mid = sma(c, bb_period)
    offset = min_len - len(sma_mid)
    histogram = []
    for i in range(len(sma_mid)):
        idx = i + offset
        histogram.append(c[idx] - (midline[idx] + sma_mid[i]) / 2.0)

    return histogram, is_squeeze[-len(histogram):]


# ─── SSL CHANNEL ──────────────────────────────────────────────

def ssl_channel(highs, lows, closes, period=10):
    """SSL Channel. Returns (ssl_up, ssl_down) lists."""
    sma_high = sma(highs, period)
    sma_low = sma(lows, period)

    min_len = min(len(sma_high), len(sma_low))
    sma_high = sma_high[-min_len:]
    sma_low = sma_low[-min_len:]
    c = closes[-min_len:]

    ssl_up = [0.0] * min_len
    ssl_down = [0.0] * min_len
    hlv = 1

    for i in range(min_len):
        if c[i] > sma_high[i]:
            hlv = 1
        elif c[i] < sma_low[i]:
            hlv = -1
        ssl_up[i] = sma_high[i] if hlv == 1 else sma_low[i]
        ssl_down[i] = sma_low[i] if hlv == 1 else sma_high[i]

    return ssl_up, ssl_down


# ─── WADDAH ATTAR EXPLOSION (WAE) ────────────────────────────

def waddah_attar(closes, fast=20, slow=40, sensitivity=150, dead_zone_mult=3.7,
                 bb_period=20, bb_mult=2.0):
    """WAE indicator. Returns (explosion_up, explosion_down, dead_zone) lists."""
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)

    offset = slow - fast
    macd_diff = [ema_fast[i + offset] - ema_slow[i] for i in range(len(ema_slow))]

    _, _, _, bw = bollinger_bands(closes, bb_period, bb_mult)

    min_len = min(len(macd_diff), len(bw))
    macd_diff = macd_diff[-min_len:]
    bw = bw[-min_len:]

    explosion_up = []
    explosion_down = []
    dead_zone = []

    for i in range(1, min_len):
        t1 = (macd_diff[i] - macd_diff[i - 1]) * sensitivity
        dz = bw[i] * dead_zone_mult if len(bw) > i else 0

        if t1 > 0:
            explosion_up.append(t1)
            explosion_down.append(0.0)
        else:
            explosion_up.append(0.0)
            explosion_down.append(abs(t1))
        dead_zone.append(dz)

    return explosion_up, explosion_down, dead_zone


# ─── VWAP ─────────────────────────────────────────────────────

def vwap(highs, lows, closes, volumes):
    """Session VWAP with upper/lower bands (1 std dev).
    Returns (vwap_line, upper_band, lower_band).
    """
    if not highs or not volumes:
        return [], [], []

    n = len(closes)
    typical = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(n)]

    cum_tp_vol = 0.0
    cum_vol = 0.0
    vwap_line = []
    vwap_sq = []

    for i in range(n):
        cum_tp_vol += typical[i] * volumes[i]
        cum_vol += volumes[i]
        if cum_vol == 0:
            vwap_line.append(typical[i])
            vwap_sq.append(0.0)
        else:
            v = cum_tp_vol / cum_vol
            vwap_line.append(v)
            vwap_sq.append(cum_tp_vol / cum_vol)

    # Standard deviation bands
    cum_tp_vol = 0.0
    cum_vol = 0.0
    cum_tp2_vol = 0.0
    upper = []
    lower = []

    for i in range(n):
        cum_tp_vol += typical[i] * volumes[i]
        cum_tp2_vol += (typical[i] ** 2) * volumes[i]
        cum_vol += volumes[i]
        if cum_vol == 0:
            upper.append(vwap_line[i])
            lower.append(vwap_line[i])
        else:
            mean = cum_tp_vol / cum_vol
            variance = max(0, cum_tp2_vol / cum_vol - mean ** 2)
            sd = math.sqrt(variance)
            upper.append(mean + sd)
            lower.append(mean - sd)

    return vwap_line, upper, lower


# ─── HULL MOVING AVERAGE ─────────────────────────────────────

def hma(data, period=55):
    """Hull Moving Average."""
    half_period = period // 2
    sqrt_period = int(math.sqrt(period))

    wma_half = wma(data, half_period)
    wma_full = wma(data, period)

    if not wma_half or not wma_full:
        return []

    min_len = min(len(wma_half), len(wma_full))
    wma_half = wma_half[-min_len:]
    wma_full = wma_full[-min_len:]

    diff = [2.0 * wma_half[i] - wma_full[i] for i in range(min_len)]
    result = wma(diff, sqrt_period)
    return result


# ─── PIVOT POINTS ─────────────────────────────────────────────

def pivot_points(prev_high, prev_low, prev_close):
    """Standard Pivot Points from previous session OHLC.
    Returns dict with PP, R1, R2, R3, S1, S2, S3.
    """
    pp = (prev_high + prev_low + prev_close) / 3.0
    r1 = 2.0 * pp - prev_low
    s1 = 2.0 * pp - prev_high
    r2 = pp + (prev_high - prev_low)
    s2 = pp - (prev_high - prev_low)
    r3 = prev_high + 2.0 * (pp - prev_low)
    s3 = prev_low - 2.0 * (prev_high - pp)
    return {"PP": pp, "R1": r1, "R2": r2, "R3": r3, "S1": s1, "S2": s2, "S3": s3}


# ─── ICHIMOKU CLOUD ───────────────────────────────────────────

def ichimoku(highs, lows, closes, tenkan=9, kijun=26, senkou_b=52):
    """Ichimoku Cloud. Returns (tenkan_sen, kijun_sen, senkou_a, senkou_b_line, chikou)."""
    def donchian_mid(data, period, idx):
        window = data[max(0, idx - period + 1):idx + 1]
        return (max(window) + min(window)) / 2.0 if window else 0.0

    n = len(closes)
    tenkan_sen = [donchian_mid(highs, tenkan, i) + donchian_mid(lows, tenkan, i)
                  for i in range(n)]
    tenkan_sen = [(donchian_mid(highs, tenkan, i) + donchian_mid(lows, tenkan, i)) / 2.0
                  if i >= tenkan - 1 else 0.0 for i in range(n)]

    # Recalculate properly
    tenkan_sen = []
    kijun_sen = []
    for i in range(n):
        if i >= tenkan - 1:
            h_win = highs[i - tenkan + 1:i + 1]
            l_win = lows[i - tenkan + 1:i + 1]
            tenkan_sen.append((max(h_win) + min(l_win)) / 2.0)
        else:
            tenkan_sen.append(0.0)

        if i >= kijun - 1:
            h_win = highs[i - kijun + 1:i + 1]
            l_win = lows[i - kijun + 1:i + 1]
            kijun_sen.append((max(h_win) + min(l_win)) / 2.0)
        else:
            kijun_sen.append(0.0)

    senkou_a = [(tenkan_sen[i] + kijun_sen[i]) / 2.0 for i in range(n)]

    senkou_b_line = []
    for i in range(n):
        if i >= senkou_b - 1:
            h_win = highs[i - senkou_b + 1:i + 1]
            l_win = lows[i - senkou_b + 1:i + 1]
            senkou_b_line.append((max(h_win) + min(l_win)) / 2.0)
        else:
            senkou_b_line.append(0.0)

    chikou = closes  # shifted back 26 periods (handled by caller)

    return tenkan_sen, kijun_sen, senkou_a, senkou_b_line, chikou
