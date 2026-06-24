"""
exchange.py - Bybit API v5 wrapper
Handles: klines, orders, balance, funding rate, orderbook, tickers
Uses only urllib (stdlib) for HTTP requests.
"""
import json
import hmac
import hashlib
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime

import config
from logger import log, log_error

# ─── BASE URL ─────────────────────────────────────────────────

def _base_url():
    if config.TESTNET_MODE:
        return "https://api-testnet.bybit.com"
    return "https://api.bybit.com"


# ─── AUTH HELPERS ─────────────────────────────────────────────

def _sign(params_str, timestamp, recv_window="5000"):
    """Generate Bybit v5 HMAC-SHA256 signature."""
    pre_sign = f"{timestamp}{config.BYBIT_API_KEY}{recv_window}{params_str}"
    return hmac.new(
        config.BYBIT_API_SECRET.encode("utf-8"),
        pre_sign.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()



def _auth_headers(params_str=""):
    """Build authenticated headers for Bybit v5."""
    timestamp = str(int(time.time() * 1000))
    recv_window = "5000"
    signature = _sign(params_str, timestamp, recv_window)
    return {
        "X-BAPI-API-KEY": config.BYBIT_API_KEY,
        "X-BAPI-SIGN": signature,
        "X-BAPI-TIMESTAMP": timestamp,
        "X-BAPI-RECV-WINDOW": recv_window,
        "Content-Type": "application/json"
    }


# ─── HTTP HELPERS ─────────────────────────────────────────────

def _request(method, path, params=None, auth=False, retries=3):
    """Make HTTP request with retry logic."""
    url = _base_url() + path
    body = None
    params_str = ""

    if method == "GET" and params:
        params_str = urllib.parse.urlencode(params)
        url = f"{url}?{params_str}"
    elif method == "POST" and params:
        params_str = json.dumps(params)
        body = params_str.encode("utf-8")

    for attempt in range(retries):
        try:
            headers = {}
            if auth:
                headers = _auth_headers(params_str)
            else:
                headers = {"Content-Type": "application/json"}

            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("retCode", 0) != 0:
                    log_error("API", f"{path} retCode={data.get('retCode')} msg={data.get('retMsg')}")
                    if attempt < retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                return data
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            log_error("NET", f"Attempt {attempt+1}/{retries} {path}: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                return None
        except Exception as e:
            log_error("ERR", f"{path}: {e}")
            return None
    return None


# ─── PUBLIC ENDPOINTS ─────────────────────────────────────────

def get_usdt_perpetual_pairs():
    """Get all USDT perpetual trading pairs with max leverage info."""
    data = _request("GET", "/v5/market/instruments-info",
                    {"category": "linear", "limit": "1000"})
    if not data or "result" not in data:
        return []
    pairs = []
    for item in data["result"].get("list", []):
        symbol = item.get("symbol", "")
        if (item.get("status") == "Trading" and
            item.get("settleCoin") == "USDT" and
            symbol.endswith("USDT")):
            if symbol not in config.BLACKLIST_PAIRS:
                if not config.WHITELIST_PAIRS or symbol in config.WHITELIST_PAIRS:
                    pairs.append(symbol)
    return sorted(pairs)


def get_max_leverage(symbol):
    """Get maximum allowed leverage for a symbol."""
    data = _request("GET", "/v5/market/instruments-info",
                    {"category": "linear", "symbol": symbol})
    if not data or "result" not in data:
        return config.LEVERAGE
    lst = data["result"].get("list", [])
    if lst:
        leverage_filter = lst[0].get("leverageFilter", {})
        max_lev = float(leverage_filter.get("maxLeverage", config.LEVERAGE))
        return int(max_lev)
    return config.LEVERAGE


def calc_leverage(symbol):
    """Calculate leverage to use based on pair's max leverage and LEVERAGE_USAGE_PCT.
    e.g. max=100x, usage=70% → 70x; max=12x, usage=50% → 6x
    Always returns whole integer (no decimals).
    """
    max_lev = get_max_leverage(symbol)
    adjusted = int(max_lev * config.LEVERAGE_USAGE_PCT / 100)
    # Minimum 1x, cap at config.LEVERAGE if set lower
    adjusted = max(1, adjusted)
    if config.LEVERAGE > 0:
        adjusted = min(adjusted, config.LEVERAGE)
    log("LEVERAGE", f"{symbol} max:{max_lev}x → using:{adjusted}x "
        f"({config.LEVERAGE_USAGE_PCT}% of max)")
    return adjusted


def get_klines(symbol, interval, limit=200):
    """Fetch OHLCV klines. Returns list of [timestamp, open, high, low, close, volume]."""
    data = _request("GET", "/v5/market/kline", {
        "category": "linear",
        "symbol": symbol,
        "interval": interval,
        "limit": str(limit)
    })
    if not data or "result" not in data:
        return []
    candles = []
    for c in reversed(data["result"].get("list", [])):
        candles.append([
            int(c[0]),       # timestamp ms
            float(c[1]),     # open
            float(c[2]),     # high
            float(c[3]),     # low
            float(c[4]),     # close
            float(c[5])      # volume
        ])
    return candles


def get_ticker_price(symbol):
    """Get latest mark price for a symbol."""
    data = _request("GET", "/v5/market/tickers", {
        "category": "linear",
        "symbol": symbol
    })
    if not data or "result" not in data:
        return 0.0
    lst = data["result"].get("list", [])
    if lst:
        return float(lst[0].get("lastPrice", 0))
    return 0.0


def get_funding_rate(symbol):
    """Get current funding rate."""
    data = _request("GET", "/v5/market/funding/history", {
        "category": "linear",
        "symbol": symbol,
        "limit": "1"
    })
    if not data or "result" not in data:
        return 0.0
    lst = data["result"].get("list", [])
    if lst:
        return float(lst[0].get("fundingRate", 0))
    return 0.0


def get_orderbook(symbol, limit=25):
    """Get orderbook. Returns (bids_total_qty, asks_total_qty)."""
    data = _request("GET", "/v5/market/orderbook", {
        "category": "linear",
        "symbol": symbol,
        "limit": str(limit)
    })
    if not data or "result" not in data:
        return 0.0, 0.0
    result = data["result"]
    bids = sum(float(b[1]) for b in result.get("b", []))
    asks = sum(float(a[1]) for a in result.get("a", []))
    return bids, asks


def get_usd_php_rate():
    """Fetch live USD/PHP exchange rate."""
    try:
        req = urllib.request.Request(config.USD_PHP_API)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return float(data.get("rates", {}).get("PHP", 56.0))
    except Exception as e:
        log_error("FX", f"USD/PHP fetch failed: {e}")
        return 56.0  # fallback


# ─── PRIVATE ENDPOINTS ────────────────────────────────────────

def get_wallet_balance():
    """Get USDT wallet balance. Returns float."""
    data = _request("GET", "/v5/account/wallet-balance",
                    {"accountType": "UNIFIED"}, auth=True)
    if not data or "result" not in data:
        return 0.0
    coins = data["result"].get("list", [])
    for account in coins:
        for coin in account.get("coin", []):
            if coin.get("coin") == "USDT":
                return float(coin.get("walletBalance", 0))
    return 0.0


def set_leverage(symbol, leverage):
    """Set leverage for a symbol."""
    data = _request("POST", "/v5/position/set-leverage", {
        "category": "linear",
        "symbol": symbol,
        "buyLeverage": str(leverage),
        "sellLeverage": str(leverage)
    }, auth=True)
    return data


def place_order(symbol, side, qty, sl_price=None, tp_price=None):
    """Place a market order with optional SL/TP."""
    params = {
        "category": "linear",
        "symbol": symbol,
        "side": side,
        "orderType": "Market",
        "qty": str(qty),
        "timeInForce": "GTC",
        "positionIdx": 0
    }
    if sl_price:
        params["stopLoss"] = str(sl_price)
    if tp_price:
        params["takeProfit"] = str(tp_price)

    data = _request("POST", "/v5/order/create", params, auth=True)
    if data and data.get("retCode") == 0:
        order_id = data["result"].get("orderId", "")
        log("ORDER", f"{side} {symbol} qty={qty} id={order_id}")
        return order_id
    return None


def set_trailing_stop(symbol, trailing_stop_distance):
    """Set trailing stop on an open position."""
    data = _request("POST", "/v5/position/set-trading-stop", {
        "category": "linear",
        "symbol": symbol,
        "trailingStop": str(trailing_stop_distance),
        "positionIdx": 0
    }, auth=True)
    return data


def get_positions():
    """Get all open positions."""
    data = _request("GET", "/v5/position/list",
                    {"category": "linear", "settleCoin": "USDT"}, auth=True)
    if not data or "result" not in data:
        return []
    return data["result"].get("list", [])


def close_position(symbol, side, qty):
    """Close a position by placing opposite market order."""
    close_side = "Sell" if side == "Buy" else "Buy"
    return place_order(symbol, close_side, qty)


def check_api_permissions():
    """Verify API key has required permissions. Returns True/False."""
    data = _request("GET", "/v5/user/query-api", {}, auth=True)
    if not data or "result" not in data:
        return False
    permissions = data["result"].get("permissions", {})
    # Check for contract trading permission
    contract = permissions.get("ContractTrade", [])
    if "Order" in contract and "Position" in contract:
        return True
    return False
