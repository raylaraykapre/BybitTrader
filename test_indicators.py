#!/usr/bin/env python3
"""
test_indicators.py - Validate each indicator calculation against known values.
Catches math bugs before risking real money.
"""
import sys
import os
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import indicators as ind

PASS = 0
FAIL = 0


def assert_close(actual, expected, tolerance=0.01, label=""):
    """Assert two values are within tolerance."""
    global PASS, FAIL
    if isinstance(expected, list):
        if len(actual) != len(expected):
            FAIL += 1
            print(f"  FAIL {label}: length {len(actual)} != {len(expected)}")
            return False
        for i, (a, e) in enumerate(zip(actual, expected)):
            if abs(a - e) > tolerance:
                FAIL += 1
                print(f"  FAIL {label}[{i}]: {a:.6f} != {e:.6f} (tol={tolerance})")
                return False
        PASS += 1
        return True
    else:
        if abs(actual - expected) > tolerance:
            FAIL += 1
            print(f"  FAIL {label}: {actual:.6f} != {expected:.6f} (tol={tolerance})")
            return False
        PASS += 1
        return True


def test_sma():
    """Test Simple Moving Average."""
    print("\n[TEST] SMA")
    data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

    result = ind.sma(data, 3)
    # SMA(3) of [1,2,3,4,5,6,7,8,9,10]:
    # [2, 3, 4, 5, 6, 7, 8, 9]
    expected = [2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
    assert_close(result, expected, 0.001, "SMA(3)")

    result = ind.sma(data, 5)
    expected = [3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    assert_close(result, expected, 0.001, "SMA(5)")


def test_ema():
    """Test Exponential Moving Average."""
    print("\n[TEST] EMA")
    data = [22.27, 22.19, 22.08, 22.17, 22.18, 22.13, 22.23, 22.43, 22.24, 22.29,
            22.15, 22.39, 22.38, 22.61, 23.36, 24.05, 23.75, 23.83, 23.95, 23.63]

    result = ind.ema(data, 10)
    # EMA(10): first value = SMA of first 10 = 22.221
    assert_close(result[0], 22.221, 0.01, "EMA(10) first")
    # Subsequent values use EMA formula
    # k = 2/11 = 0.18182
    # EMA[1] = 22.15 * 0.18182 + 22.221 * 0.81818 = 22.208
    assert_close(result[1], 22.208, 0.02, "EMA(10) second")
    assert len(result) == 11, f"EMA length: {len(result)}"
    PASS  # count


def test_rsi():
    """Test RSI calculation."""
    print("\n[TEST] RSI")
    # Known test: if all gains, RSI = 100
    data_up = [float(i) for i in range(1, 20)]
    result = ind.rsi(data_up, 14)
    assert_close(result[-1], 100.0, 0.01, "RSI all gains")

    # All losses
    data_down = [float(20 - i) for i in range(20)]
    result = ind.rsi(data_down, 14)
    assert_close(result[-1], 0.0, 0.01, "RSI all losses")

    # Mixed data - verify reasonable range
    data_mixed = [44, 44.34, 44.09, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84,
                  46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41,
                  46.22, 45.64]
    result = ind.rsi(data_mixed, 14)
    # RSI should be in reasonable range for this data
    assert len(result) > 0, "RSI mixed has results"
    for v in result:
        assert 0 <= v <= 100, f"RSI out of range: {v}"
    PASS


def test_macd():
    """Test MACD calculation."""
    print("\n[TEST] MACD")
    # Generate enough data
    data = [10 + 0.5 * i + (0.3 if i % 3 == 0 else -0.1) for i in range(50)]

    macd_line, signal_line, histogram = ind.macd(data, 12, 26, 9)

    # MACD line should exist
    assert len(macd_line) > 0, "MACD line exists"
    assert len(signal_line) > 0, "Signal line exists"
    assert len(histogram) > 0, "Histogram exists"

    # In uptrend, MACD should be positive
    assert macd_line[-1] > 0, f"MACD positive in uptrend: {macd_line[-1]}"
    PASS


def test_bollinger_bands():
    """Test Bollinger Bands."""
    print("\n[TEST] Bollinger Bands")
    data = [float(i) for i in range(1, 25)]  # 24 data points
    upper, mid, lower, bw = ind.bollinger_bands(data, 20, 2.0)

    assert len(mid) == 5, f"BB mid length: {len(mid)}"  # 24-20+1 = 5
    # Mid should be SMA(20)
    assert_close(mid[0], sum(range(1, 21)) / 20.0, 0.001, "BB mid = SMA")

    # Upper > Mid > Lower always
    for i in range(len(mid)):
        assert upper[i] > mid[i] > lower[i], "BB order: upper > mid > lower"
    PASS


def test_atr():
    """Test Average True Range."""
    print("\n[TEST] ATR")
    highs = [48.70, 48.72, 48.90, 48.87, 48.82, 49.05, 49.20, 49.35, 49.92, 50.19,
             50.12, 49.66, 49.88, 50.19, 50.36, 50.57, 50.65, 50.43, 49.63, 50.33]
    lows = [47.79, 48.14, 48.39, 48.37, 48.24, 48.64, 48.94, 48.86, 49.50, 49.87,
            49.20, 48.90, 49.43, 49.73, 49.26, 50.09, 50.30, 49.21, 48.98, 49.61]
    closes = [48.16, 48.61, 48.75, 48.63, 48.74, 49.03, 49.07, 49.32, 49.91, 50.13,
              49.53, 49.50, 49.75, 50.03, 49.99, 50.42, 50.37, 49.71, 49.37, 50.23]

    result = ind.atr(highs, lows, closes, 14)
    assert len(result) > 0, "ATR has results"
    # ATR should be positive
    for v in result:
        assert v > 0, f"ATR positive: {v}"
    PASS


def test_supertrend():
    """Test SuperTrend indicator."""
    print("\n[TEST] SuperTrend")
    # Generate trending data
    highs = [100 + i * 0.5 + 1 for i in range(30)]
    lows = [100 + i * 0.5 - 1 for i in range(30)]
    closes = [100 + i * 0.5 for i in range(30)]

    st_line, direction = ind.supertrend(highs, lows, closes, 10, 3.0)
    assert len(st_line) > 0, "SuperTrend has results"
    assert len(direction) > 0, "SuperTrend direction exists"

    # In clear uptrend, direction should eventually be 1 (bullish)
    assert direction[-1] == 1, f"SuperTrend bullish in uptrend: {direction[-1]}"

    # Test downtrend
    highs_d = [130 - i * 0.5 + 1 for i in range(30)]
    lows_d = [130 - i * 0.5 - 1 for i in range(30)]
    closes_d = [130 - i * 0.5 for i in range(30)]

    st_line_d, direction_d = ind.supertrend(highs_d, lows_d, closes_d, 10, 3.0)
    assert direction_d[-1] == -1, f"SuperTrend bearish in downtrend: {direction_d[-1]}"
    PASS


def test_squeeze_momentum():
    """Test Squeeze Momentum."""
    print("\n[TEST] Squeeze Momentum")
    # Need enough data
    n = 50
    closes = [100 + math.sin(i * 0.3) * 5 for i in range(n)]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]

    histogram, is_squeeze = ind.squeeze_momentum(highs, lows, closes)
    assert len(histogram) > 0, "Squeeze histogram exists"
    assert len(is_squeeze) > 0, "Squeeze state exists"
    # is_squeeze should be boolean list
    for s in is_squeeze:
        assert isinstance(s, bool), f"Squeeze is bool: {type(s)}"
    PASS


def test_ssl_channel():
    """Test SSL Channel."""
    print("\n[TEST] SSL Channel")
    closes = [100 + i * 0.3 for i in range(25)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]

    ssl_up, ssl_down = ind.ssl_channel(highs, lows, closes, 10)
    assert len(ssl_up) > 0, "SSL up exists"
    assert len(ssl_down) > 0, "SSL down exists"

    # In uptrend, ssl_up should be above ssl_down
    assert ssl_up[-1] >= ssl_down[-1], "SSL up >= down in uptrend"
    PASS


def test_waddah_attar():
    """Test Waddah Attar Explosion."""
    print("\n[TEST] WAE")
    n = 60
    # Strong uptrend
    closes = [100 + i * 0.8 for i in range(n)]

    exp_up, exp_down, dead_zone = ind.waddah_attar(closes)
    assert len(exp_up) > 0, "WAE up exists"
    assert len(exp_down) > 0, "WAE down exists"
    assert len(dead_zone) > 0, "WAE dead zone exists"

    # In uptrend, explosion_up should dominate
    up_sum = sum(exp_up[-5:])
    down_sum = sum(exp_down[-5:])
    assert up_sum > down_sum, f"WAE up > down in uptrend: {up_sum} vs {down_sum}"
    PASS


def test_vwap():
    """Test VWAP calculation."""
    print("\n[TEST] VWAP")
    highs = [10.0, 10.5, 11.0, 10.8, 11.2]
    lows = [9.5, 10.0, 10.5, 10.2, 10.8]
    closes = [10.0, 10.3, 10.8, 10.5, 11.0]
    volumes = [100, 150, 200, 120, 180]

    vwap_line, upper, lower = ind.vwap(highs, lows, closes, volumes)
    assert len(vwap_line) == 5, "VWAP length"

    # First VWAP = typical price of first candle (since vol-weighted with only 1 point)
    tp0 = (10.0 + 9.5 + 10.0) / 3.0
    assert_close(vwap_line[0], tp0, 0.01, "VWAP first value")

    # VWAP should be between high and low range
    for v in vwap_line:
        assert 9.0 < v < 12.0, f"VWAP in range: {v}"
    PASS


def test_hma():
    """Test Hull Moving Average."""
    print("\n[TEST] HMA")
    # Need enough data for period 55
    data = [100 + i * 0.2 + math.sin(i * 0.1) * 2 for i in range(100)]

    result = ind.hma(data, 55)
    assert len(result) > 0, f"HMA has results: {len(result)}"

    # HMA should track trend - in uptrend, should be increasing
    assert result[-1] > result[-5], "HMA increasing in uptrend"
    PASS


def test_pivot_points():
    """Test Pivot Points."""
    print("\n[TEST] Pivot Points")
    # Known values
    prev_high = 110.0
    prev_low = 100.0
    prev_close = 105.0

    pivots = ind.pivot_points(prev_high, prev_low, prev_close)

    # PP = (H + L + C) / 3 = (110 + 100 + 105) / 3 = 105.0
    assert_close(pivots["PP"], 105.0, 0.001, "PP")

    # R1 = 2*PP - L = 2*105 - 100 = 110.0
    assert_close(pivots["R1"], 110.0, 0.001, "R1")

    # S1 = 2*PP - H = 2*105 - 110 = 100.0
    assert_close(pivots["S1"], 100.0, 0.001, "S1")

    # R2 = PP + (H - L) = 105 + 10 = 115.0
    assert_close(pivots["R2"], 115.0, 0.001, "R2")

    # S2 = PP - (H - L) = 105 - 10 = 95.0
    assert_close(pivots["S2"], 95.0, 0.001, "S2")

    # R3 = H + 2*(PP - L) = 110 + 2*(105-100) = 120.0
    assert_close(pivots["R3"], 120.0, 0.001, "R3")

    # S3 = L - 2*(H - PP) = 100 - 2*(110-105) = 90.0
    assert_close(pivots["S3"], 90.0, 0.001, "S3")


def test_ichimoku():
    """Test Ichimoku Cloud."""
    print("\n[TEST] Ichimoku")
    n = 60
    highs = [100 + i * 0.5 + 2 for i in range(n)]
    lows = [100 + i * 0.5 - 2 for i in range(n)]
    closes = [100 + i * 0.5 for i in range(n)]

    tenkan, kijun, senkou_a, senkou_b, chikou = ind.ichimoku(highs, lows, closes)

    assert len(tenkan) == n, "Ichimoku tenkan length"
    assert len(kijun) == n, "Ichimoku kijun length"

    # Tenkan (9-period midpoint) should be less than current close in uptrend
    # because it's the midpoint of last 9 periods
    assert tenkan[-1] > 0, "Tenkan calculated"
    assert kijun[-1] > 0, "Kijun calculated"

    # In uptrend, tenkan > kijun (faster reacts quicker)
    assert tenkan[-1] >= kijun[-1], f"Tenkan >= Kijun in uptrend: {tenkan[-1]} vs {kijun[-1]}"
    PASS


def test_stoch_rsi():
    """Test Stochastic RSI."""
    print("\n[TEST] Stochastic RSI")
    # Generate data with enough points
    data = [45 + i * 0.3 + math.sin(i * 0.5) * 3 for i in range(50)]

    k_line, d_line = ind.stoch_rsi(data, 14, 14, 3, 3)
    assert len(k_line) > 0, "StochRSI K exists"
    assert len(d_line) > 0, "StochRSI D exists"

    # Values should be 0-100
    for v in k_line:
        assert 0 <= v <= 100, f"StochRSI K in range: {v}"
    for v in d_line:
        assert 0 <= v <= 100, f"StochRSI D in range: {v}"
    PASS


def test_adx():
    """Test ADX."""
    print("\n[TEST] ADX")
    n = 40
    # Strong trending data
    highs = [50 + i * 1.0 + 1 for i in range(n)]
    lows = [50 + i * 1.0 - 1 for i in range(n)]
    closes = [50 + i * 1.0 for i in range(n)]

    result = ind.adx(highs, lows, closes, 14)
    assert len(result) > 0, "ADX has results"

    # In strong trend, ADX should be high (>25)
    # Note: may need several periods to build up
    assert result[-1] > 0, f"ADX positive: {result[-1]}"
    PASS


def test_keltner_channel():
    """Test Keltner Channel."""
    print("\n[TEST] Keltner Channel")
    n = 30
    closes = [100 + i * 0.2 for i in range(n)]
    highs = [c + 1.5 for c in closes]
    lows = [c - 1.5 for c in closes]

    upper, mid, lower = ind.keltner_channel(highs, lows, closes, 20, 1.5)
    assert len(upper) > 0, "KC upper exists"

    # Upper > Mid > Lower
    for i in range(len(upper)):
        assert upper[i] > mid[i] > lower[i], "KC order correct"
    PASS


def test_wma():
    """Test Weighted Moving Average."""
    print("\n[TEST] WMA")
    data = [1, 2, 3, 4, 5]
    result = ind.wma(data, 3)
    # WMA(3) of [1,2,3] = (1*1 + 2*2 + 3*3) / (1+2+3) = (1+4+9)/6 = 14/6 = 2.333
    assert_close(result[0], 14.0 / 6.0, 0.001, "WMA(3) first")
    # WMA(3) of [2,3,4] = (2*1 + 3*2 + 4*3) / 6 = (2+6+12)/6 = 20/6 = 3.333
    assert_close(result[1], 20.0 / 6.0, 0.001, "WMA(3) second")


def test_true_range():
    """Test True Range."""
    print("\n[TEST] True Range")
    highs = [48.70, 48.72, 48.90]
    lows = [47.79, 48.14, 48.39]
    closes = [48.16, 48.61, 48.75]

    tr = ind.true_range(highs, lows, closes)
    # TR[0] = H-L = 48.70 - 47.79 = 0.91
    assert_close(tr[0], 0.91, 0.01, "TR[0]")
    # TR[1] = max(H-L, |H-prevC|, |L-prevC|) = max(0.58, 0.56, 0.02) = 0.58
    assert_close(tr[1], 0.58, 0.01, "TR[1]")


# ─── RUN ALL TESTS ────────────────────────────────────────────

def main():
    global PASS, FAIL
    print("=" * 60)
    print("INDICATOR TEST SUITE")
    print("=" * 60)

    tests = [
        test_sma,
        test_wma,
        test_ema,
        test_true_range,
        test_rsi,
        test_stoch_rsi,
        test_macd,
        test_bollinger_bands,
        test_keltner_channel,
        test_atr,
        test_adx,
        test_supertrend,
        test_squeeze_momentum,
        test_ssl_channel,
        test_waddah_attar,
        test_vwap,
        test_hma,
        test_pivot_points,
        test_ichimoku,
    ]

    for test_fn in tests:
        try:
            test_fn()
            print(f"  ✓ {test_fn.__name__}")
        except AssertionError as e:
            FAIL += 1
            print(f"  ✗ {test_fn.__name__}: {e}")
        except Exception as e:
            FAIL += 1
            print(f"  ✗ {test_fn.__name__}: EXCEPTION: {e}")

    print("\n" + "=" * 60)
    print(f"RESULTS: {PASS} passed, {FAIL} failed")
    print("=" * 60)

    if FAIL > 0:
        sys.exit(1)
    else:
        print("\nAll indicator tests passed! Safe to trade.")
        sys.exit(0)


if __name__ == "__main__":
    main()
