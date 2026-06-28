"""
CuanBot v4 - Market Intelligence Module
Sumber data eksternal untuk second opinion (bukan dari Tokocrypto).

Sumber:
  - Binance.vision  → harga global (BTC, ETH, SOL, dll) untuk cek arah market
  - CoinGecko       → trending coins, kategori hot, global market sentiment

Dipakai untuk:
  1. Bonus skor kalau coin di Tokocrypto juga trending di CoinGecko
  2. Penalty kalau market global lagi bearish (BTC turun)
  3. Sentiment global (BTC dominance, total market cap change)
"""

import time as _time
import requests
import logging

logger = logging.getLogger("cuanbot")

# ── Cache ────────────────────────────────────────────────────────────
_cache = {}
_cache_time = {}
_CACHE_TTL = 300  # 5 menit

def _get_cached(key: str, fetch_fn, ttl: int = None):
    """Fetch + cache helper."""
    ttl = ttl or _CACHE_TTL
    now = _time.time()
    if key in _cache and (now - _cache_time.get(key, 0)) < ttl:
        return _cache[key]
    try:
        result = fetch_fn()
        _cache[key] = result
        _cache_time[key] = now
        return result
    except Exception as e:
        logger.debug(f"[MarketIntel] Cache miss for '{key}': {e}")
        return _cache.get(key)  # return stale cache if available


# ── Binance.vision (global price data) ──────────────────────────────

_BINANCE_VISION = "https://data-api.binance.vision"

# Map coin base (BTC, ETH, dll) ke USDT pair di Binance
_GLOBAL_PAIRS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]


def get_global_prices() -> dict:
    """
    Ambil harga global (USDT) dari Binance.vision untuk major coins.
    Return: {"BTC": {"price": 95000, "change_pct": -1.5}, ...}
    """
    def fetch():
        resp = requests.get(
            f"{_BINANCE_VISION}/api/v3/ticker/24hr",
            timeout=10,
        )
        data = resp.json()
        if not isinstance(data, list):
            return {}

        result = {}
        for item in data:
            sym = item.get("symbol", "")
            if sym not in _GLOBAL_PAIRS:
                continue
            base = sym.replace("USDT", "")
            result[base] = {
                "price": float(item.get("lastPrice", 0)),
                "change_pct": float(item.get("priceChangePercent", 0)),
                "volume_usd": float(item.get("quoteVolume", 0)),
            }
        return result

    return _get_cached("global_prices", fetch)


def get_market_sentiment() -> dict:
    """
    Ambil sentiment market global dari Binance major coins.
    Return: {
        "direction": "bullish" | "bearish" | "neutral",
        "btc_change": -1.5,
        "avg_change": -0.8,
        "bearish_count": 4,
        "bullish_count": 2,
    }
    """
    prices = get_global_prices()
    if not prices:
        return {"direction": "neutral", "btc_change": 0, "avg_change": 0, "bearish_count": 0, "bullish_count": 0}

    changes = [v["change_pct"] for v in prices.values()]
    btc_change = prices.get("BTC", {}).get("change_pct", 0)
    avg_change = sum(changes) / len(changes) if changes else 0

    bullish = sum(1 for c in changes if c > 0)
    bearish = sum(1 for c in changes if c < 0)

    if avg_change < -2.0 or btc_change < -3.0:
        direction = "bearish"
    elif avg_change > 1.5 and btc_change > 0:
        direction = "bullish"
    else:
        direction = "neutral"

    return {
        "direction": direction,
        "btc_change": round(btc_change, 2),
        "avg_change": round(avg_change, 2),
        "bearish_count": bearish,
        "bullish_count": bullish,
    }


# ── CoinGecko (trending + categories) ───────────────────────────────

_CG_BASE = "https://api.coingecko.com/api/v3"


def get_trending_coins() -> list:
    """
    Ambil daftar trending coin dari CoinGecko.
    Return: ["BTC", "ETH", "SOL", ...] (list of symbols uppercase)
    """
    def fetch():
        resp = requests.get(f"{_CG_BASE}/search/trending", timeout=10)
        data = resp.json()
        coins = data.get("coins", [])
        symbols = []
        for item in coins:
            sym = item.get("item", {}).get("symbol", "")
            if sym:
                symbols.append(sym.upper())
        return symbols

    return _get_cached("trending", fetch, ttl=600)  # 10 menit


def get_global_market_data() -> dict:
    """
    Ambil data market global dari CoinGecko.
    Return: {"total_mcap_change": -0.8, "btc_dominance": 55.7}
    """
    def fetch():
        resp = requests.get(f"{_CG_BASE}/global", timeout=10)
        data = resp.json().get("data", {})
        return {
            "total_mcap_change": round(data.get("market_cap_change_percentage_24h_usd", 0), 2),
            "btc_dominance": round(data.get("market_cap_percentage", {}).get("btc", 0), 1),
        }

    return _get_cached("global_market", fetch, ttl=600)


# ── Composite: Scoring Bonus untuk Bot ──────────────────────────────

def get_intel_bonus(coin_base: str) -> dict:
    """
    Hitung bonus/penalty skor berdasarkan market intel eksternal.

    Input: coin_base (mis. "BTC", "DOGE", "ETH")
    Return: {
        "bonus": int,          # -10 sampai +15
        "reason": str,         # penjelasan
        "market_dir": str,     # bullish/bearish/neutral
        "is_trending": bool,
    }
    """
    sentiment = get_market_sentiment()
    trending = get_trending_coins()
    global_data = get_global_market_data()

    bonus = 0
    reasons = []
    is_trending = coin_base.upper() in trending

    # 1. Trending bonus
    if is_trending:
        bonus += 5
        reasons.append("Trending di CoinGecko")

    # 2. Market sentiment adjustment
    market_dir = sentiment["direction"]
    if market_dir == "bearish":
        penalty = min(10, int(abs(sentiment["btc_change"]) * 1.5))
        bonus -= penalty
        reasons.append(f"Market bearish (BTC {sentiment['btc_change']:+.1f}%)")
    elif market_dir == "bullish":
        bonus += 3
        reasons.append(f"Market bullish (BTC {sentiment['btc_change']:+.1f}%)")

    # 3. Global market cap crash warning
    mcap_change = global_data.get("total_mcap_change", 0)
    if mcap_change < -3.0:
        bonus -= 5
        reasons.append(f"Market cap global turun {mcap_change:+.1f}%")

    bonus = max(-10, min(15, bonus))  # clamp

    return {
        "bonus": bonus,
        "reason": " | ".join(reasons) if reasons else "Tidak ada sinyal eksternal",
        "market_dir": market_dir,
        "is_trending": is_trending,
        "btc_change": sentiment["btc_change"],
        "avg_change": sentiment["avg_change"],
        "mcap_change": mcap_change,
    }


def get_market_summary() -> str:
    """
    Summary singkat kondisi market global untuk notifikasi.
    """
    sentiment = get_market_sentiment()
    global_data = get_global_market_data()
    trending = get_trending_coins()[:3]

    dir_emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}.get(sentiment["direction"], "⚪")

    parts = [
        f"Market Global: {dir_emoji} {sentiment['direction'].upper()}",
        f"BTC {sentiment['btc_change']:+.1f}% | Avg {sentiment['avg_change']:+.1f}%",
    ]
    if global_data.get("total_mcap_change") is not None:
        parts.append(f"MCap {global_data['total_mcap_change']:+.1f}%")
    if trending:
        parts.append(f"🔥 Trending: {', '.join(trending)}")

    return " | ".join(parts)
