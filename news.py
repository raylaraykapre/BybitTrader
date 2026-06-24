"""
news.py - Crypto news sentiment analysis via CryptoPanic free API
Fetches trending news, scores sentiment per coin, and provides
pair prioritization for the scanner.
"""
import json
import time
import urllib.request
import urllib.error
import threading
from datetime import datetime

from logger import log, log_error

# ─── CONFIG ───────────────────────────────────────────────────

CRYPTOPANIC_URL = "https://cryptopanic.com/api/free/v1/posts/"
# Free tier: no auth token needed for basic access
# Rate limit: be gentle, cache results

# Sentiment keywords for scoring headlines
BULLISH_KEYWORDS = [
    "surge", "surges", "soars", "rallies", "rally", "pump", "breakout",
    "bullish", "all-time high", "ath", "moon", "partnership", "adoption",
    "upgrade", "launch", "listing", "approval", "etf", "institutional",
    "accumulation", "buy", "upgrade", "milestone", "record", "growth",
    "integrate", "integration", "mainnet", "staking", "burn", "halving",
    "outperform", "gain", "gains", "positive", "boost", "strong",
    "expansion", "deal", "investment", "funding", "backed"
]

BEARISH_KEYWORDS = [
    "crash", "crashes", "dump", "dumps", "plunge", "plunges", "bearish",
    "hack", "hacked", "exploit", "vulnerability", "sec", "lawsuit",
    "ban", "banned", "regulation", "crackdown", "fraud", "scam",
    "rugpull", "rug pull", "delisting", "delist", "bankrupt", "bankruptcy",
    "liquidation", "liquidated", "sell-off", "selloff", "decline",
    "loss", "losses", "fear", "fud", "warning", "risk", "collapse",
    "investigation", "subpoena", "fine", "penalty", "shutdown",
    "manipulation", "ponzi", "exit scam", "negative", "drop", "drops"
]

# Map common coin names to USDT pair symbols
COIN_TO_PAIR = {
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT",
    "BNB": "BNBUSDT", "XRP": "XRPUSDT", "DOGE": "DOGEUSDT",
    "ADA": "ADAUSDT", "AVAX": "AVAXUSDT", "DOT": "DOTUSDT",
    "MATIC": "MATICUSDT", "LINK": "LINKUSDT", "UNI": "UNIUSDT",
    "ATOM": "ATOMUSDT", "LTC": "LTCUSDT", "FIL": "FILUSDT",
    "APT": "APTUSDT", "ARB": "ARBUSDT", "OP": "OPUSDT",
    "NEAR": "NEARUSDT", "SUI": "SUIUSDT", "SEI": "SEIUSDT",
    "PEPE": "PEPEUSDT", "WIF": "WIFUSDT", "FET": "FETUSDT",
    "INJ": "INJUSDT", "TIA": "TIAUSDT", "JUP": "JUPUSDT",
    "RENDER": "RENDERUSDT", "STX": "STXUSDT", "IMX": "IMXUSDT",
    "AAVE": "AAVEUSDT", "MKR": "MKRUSDT", "CRV": "CRVUSDT",
    "RUNE": "RUNEUSDT", "ALGO": "ALGOUSDT", "FTM": "FTMUSDT",
    "SAND": "SANDUSDT", "MANA": "MANAUSDT", "AXS": "AXSUSDT",
    "GALA": "GALAUSDT", "ICP": "ICPUSDT", "VET": "VETUSDT",
    "HBAR": "HBARUSDT", "EOS": "EOSUSDT", "XLM": "XLMUSDT",
    "SHIB": "SHIBUSDT", "TRX": "TRXUSDT", "ETC": "ETCUSDT",
    "BCH": "BCHUSDT", "APE": "APEUSDT", "LDO": "LDOUSDT",
    "WLD": "WLDUSDT", "BONK": "BONKUSDT", "ORDI": "ORDIUSDT",
    "TAO": "TAOUSDT", "TON": "TONUSDT", "PYTH": "PYTHUSDT",
}


# ─── NEWS CACHE ───────────────────────────────────────────────

class NewsCache:
    """Thread-safe cache for news sentiment data."""
    def __init__(self):
        self.lock = threading.Lock()
        self.sentiment = {}       # symbol -> {"score": int, "articles": int, "bias": str}
        self.prioritized = []     # sorted list of (symbol, score) for scanner
        self.last_update = 0
        self.update_interval = 300  # refresh every 5 minutes

    def is_stale(self):
        return time.time() - self.last_update > self.update_interval


_cache = NewsCache()


# ─── SENTIMENT SCORING ────────────────────────────────────────

def _score_headline(title):
    """Score a headline: positive = bullish, negative = bearish."""
    title_lower = title.lower()
    bull_hits = sum(1 for kw in BULLISH_KEYWORDS if kw in title_lower)
    bear_hits = sum(1 for kw in BEARISH_KEYWORDS if kw in title_lower)
    return bull_hits - bear_hits


def _extract_coins(post):
    """Extract coin symbols from a CryptoPanic post."""
    coins = []
    # CryptoPanic provides currencies in the post
    currencies = post.get("currencies", [])
    if currencies:
        for c in currencies:
            code = c.get("code", "").upper()
            if code:
                coins.append(code)
    return coins


# ─── FETCH NEWS ───────────────────────────────────────────────

def _fetch_cryptopanic(filter_type="trending"):
    """Fetch posts from CryptoPanic free API.
    filter_type: 'trending', 'hot', 'bullish', 'bearish', 'important'
    """
    url = f"{CRYPTOPANIC_URL}?auth_token=free&filter={filter_type}&public=true"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "CryptoBot/1.0"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("results", [])
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        log_error("NEWS", f"CryptoPanic fetch failed: {e}")
        return []
    except Exception as e:
        log_error("NEWS", f"News error: {e}")
        return []


def _fetch_all_news():
    """Fetch trending + hot news and combine."""
    posts = []
    for f in ["trending", "hot", "bullish"]:
        result = _fetch_cryptopanic(f)
        posts.extend(result)
        time.sleep(1)  # rate limit
    return posts


# ─── UPDATE SENTIMENT ─────────────────────────────────────────

def update_news_sentiment():
    """Fetch latest news and update sentiment cache."""
    global _cache

    posts = _fetch_all_news()
    if not posts:
        return

    # Score by coin
    coin_scores = {}  # coin_code -> [list of scores]

    for post in posts:
        title = post.get("title", "")
        score = _score_headline(title)

        # Also use CryptoPanic's own vote data if available
        votes = post.get("votes", {})
        cp_positive = votes.get("positive", 0) + votes.get("liked", 0)
        cp_negative = votes.get("negative", 0) + votes.get("disliked", 0)
        vote_score = cp_positive - cp_negative

        # Combined score
        combined = score + (1 if vote_score > 2 else (-1 if vote_score < -2 else 0))

        coins = _extract_coins(post)
        for coin in coins:
            if coin not in coin_scores:
                coin_scores[coin] = []
            coin_scores[coin].append(combined)

    # Build sentiment map
    sentiment = {}
    for coin, scores in coin_scores.items():
        pair = COIN_TO_PAIR.get(coin, f"{coin}USDT")
        total = sum(scores)
        count = len(scores)
        avg = total / count if count > 0 else 0

        if avg > 0.3:
            bias = "BULLISH"
        elif avg < -0.3:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"

        sentiment[pair] = {
            "score": total,
            "avg": round(avg, 2),
            "articles": count,
            "bias": bias,
            "coin": coin
        }

    # Sort by bullish potential (highest positive score first)
    prioritized = sorted(
        [(pair, data["score"], data["bias"]) for pair, data in sentiment.items()],
        key=lambda x: x[1],
        reverse=True
    )

    with _cache.lock:
        _cache.sentiment = sentiment
        _cache.prioritized = prioritized
        _cache.last_update = time.time()

    # Log summary
    bull_count = sum(1 for _, d in sentiment.items() if d["bias"] == "BULLISH")
    bear_count = sum(1 for _, d in sentiment.items() if d["bias"] == "BEARISH")
    log("NEWS", f"Updated: {len(sentiment)} coins | "
        f"Bullish:{bull_count} Bearish:{bear_count} | "
        f"Top: {prioritized[0][0] if prioritized else 'N/A'}")


# ─── PUBLIC API ───────────────────────────────────────────────

def get_sentiment(symbol):
    """Get news sentiment for a trading pair.
    Returns: {"score": int, "bias": str, "articles": int} or None
    """
    with _cache.lock:
        return _cache.sentiment.get(symbol)


def get_news_score_bonus(symbol, direction):
    """Get bonus score points based on news sentiment alignment.
    Returns: int (0 to 15 bonus points)
    
    - If news is BULLISH and direction is LONG: +15
    - If news is BEARISH and direction is SHORT: +15
    - If news conflicts with direction: -10 (penalty)
    - If no news or neutral: 0
    """
    sent = get_sentiment(symbol)
    if not sent:
        return 0

    bias = sent["bias"]
    articles = sent["articles"]

    # More articles = more confidence
    confidence = min(articles, 5)  # cap at 5 articles

    if bias == "BULLISH" and direction == "LONG":
        return min(15, 5 + confidence * 2)
    elif bias == "BEARISH" and direction == "SHORT":
        return min(15, 5 + confidence * 2)
    elif bias == "BULLISH" and direction == "SHORT":
        return -10  # penalty: shorting against bullish news
    elif bias == "BEARISH" and direction == "LONG":
        return -10  # penalty: longing against bearish news
    return 0


def should_avoid_pair(symbol):
    """Check if a pair should be avoided due to extreme negative sentiment.
    Returns True if the pair has very bearish news (score <= -3).
    """
    sent = get_sentiment(symbol)
    if not sent:
        return False
    return sent["score"] <= -3 and sent["articles"] >= 2


def get_prioritized_pairs(available_pairs):
    """Reorder available pairs by news sentiment priority.
    Bullish-news pairs get scanned first for faster entry.
    Bearish-heavy pairs get pushed to the end.
    
    Returns: reordered list of pairs
    """
    if _cache.is_stale():
        update_news_sentiment()

    with _cache.lock:
        sentiment = _cache.sentiment.copy()

    if not sentiment:
        return available_pairs

    # Score each available pair
    scored = []
    for pair in available_pairs:
        sent = sentiment.get(pair)
        if sent:
            scored.append((pair, sent["score"]))
        else:
            scored.append((pair, 0))

    # Sort: highest news score first
    scored.sort(key=lambda x: x[1], reverse=True)
    return [pair for pair, _ in scored]


def refresh_if_needed():
    """Call this in the main loop to refresh news data periodically."""
    if _cache.is_stale():
        try:
            update_news_sentiment()
        except Exception as e:
            log_error("NEWS", f"Refresh failed: {e}")
