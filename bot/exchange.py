"""
CuanBot v4 - Exchange Connection (Full Tokocrypto API)
No CCXT, no Binance dependency. Langsung Tokocrypto API.
"""

import hashlib
import hmac
import time as _time
import requests
from config import Config
import logging

logger = logging.getLogger("cuanbot")

# ── Base URLs ──────────────────────────────────────────────────────
BASE_URL   = "https://www.tokocrypto.com"
MBX_URL    = "https://www.tokocrypto.site/api/v3"
NEXTME_URL = "https://cloudme-toko.2meta.app/api/v1"

# ── Cache ───────────────────────────────────────────────────────────
_symbol_info  = {}  # "BTC/IDR" -> {type, base, quote, ...}
_symbol_loaded = False


# ── HMAC Helpers ────────────────────────────────────────────────────

def _hmac_sha256(secret: str, data: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), data.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _signed_get(endpoint: str, params: dict = None, retries: int = 2) -> dict:
    if params is None:
        params = {}
    params["timestamp"]  = int(_time.time() * 1000)
    params["recvWindow"] = 5000

    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    signature = _hmac_sha256(Config.SECRET_KEY, query)

    url = f"{BASE_URL}{endpoint}?{query}&signature={signature}"
    headers = {"X-MBX-APIKEY": Config.API_KEY}

    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            data = resp.json()
            if data.get("code") != 0:
                logger.error(f"API error GET {endpoint}: {data.get('msg', resp.text[:200])}")
                return {}
            return data.get("data", {})
        except Exception as e:
            logger.error(f"API request failed GET {endpoint} (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                _time.sleep(1)
    return {}


def _signed_post(endpoint: str, params: dict, retries: int = 2) -> dict:
    params["timestamp"]  = int(_time.time() * 1000)
    params["recvWindow"] = 5000

    body = "&".join(f"{k}={v}" for k, v in params.items())
    signature = _hmac_sha256(Config.SECRET_KEY, body)

    url = f"{BASE_URL}{endpoint}"
    headers = {
        "X-MBX-APIKEY": Config.API_KEY,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    for attempt in range(retries):
        try:
            resp = requests.post(
                f"{url}?signature={signature}", data=body, headers=headers, timeout=15
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error(
                    f"API error POST {endpoint}: {data.get('msg') or data.get('message', resp.text[:200])}"
                )
                return {}
            return data.get("data", {})
        except Exception as e:
            logger.error(f"API request failed POST {endpoint} (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                _time.sleep(1)
    return {}


# ── Symbol Info ─────────────────────────────────────────────────────

def _load_symbols():
    global _symbol_info, _symbol_loaded
    if _symbol_loaded:
        return _symbol_info

    try:
        resp = requests.get(f"{BASE_URL}/open/v1/common/symbols", timeout=15)
        data = resp.json()
        if data.get("code") != 0:
            logger.error(f"Gagal load symbols: {data.get('msg')}")
            return {}
    except Exception as e:
        logger.error(f"Symbol load error: {e}")
        return {}

    symbols = data.get("data", {}).get("list", [])
    for s in symbols:
        if s.get("spotTradingEnable") != 1:
            continue
        pair   = f"{s['baseAsset']}/{s['quoteAsset']}"
        info   = {
            "type":  s.get("type", 3),
            "base":  s["baseAsset"],
            "quote": s["quoteAsset"],
            "base_precision":  s.get("basePrecision", 8),
            "quote_precision": s.get("quotePrecision", 8),
            "active": True,
        }
        _symbol_info[pair] = info

    _symbol_loaded = True
    n = len([k for k in _symbol_info if "/" in k])
    logger.info(f"Loaded {n} trading symbols dari Tokocrypto")
    return _symbol_info


def _get_symbol_type(symbol: str) -> int:
    syms = _load_symbols()
    info = syms.get(symbol)
    return info["type"] if info else 3


def _get_base_precision(symbol: str) -> int:
    """Ambil base asset precision (jumlah desimal) untuk quantity formatting."""
    syms = _load_symbols()
    info = syms.get(symbol)
    return info.get("base_precision", 8) if info else 8


def _format_mbx(symbol: str) -> str:
    """BTC/IDR -> BTCIDR (format MBX engine type 1)."""
    return symbol.replace("/", "")


def _format_nextme(symbol: str) -> str:
    """BTC/IDR -> BTC_IDR (format NextMe engine)."""
    return symbol.replace("/", "_")


def _market_url_and_symbol(symbol: str):
    """Return (base_url, formatted_symbol) based on symbol type."""
    stype = _get_symbol_type(symbol)
    if stype == 1:
        return MBX_URL, _format_mbx(symbol)
    return NEXTME_URL, _format_nextme(symbol)


# ── Public Market Data ──────────────────────────────────────────────

_volume_cache = None
_volume_cache_time = 0


def get_24h_volume_map() -> dict:
    """Return {pair_slash: quoteVolume_24h} untuk semua pair IDR. Cached 5 menit."""
    global _volume_cache, _volume_cache_time
    now = _time.time()
    if _volume_cache is not None and (now - _volume_cache_time) < 300:
        return _volume_cache

    try:
        resp = requests.get(f"{MBX_URL}/ticker/24hr", timeout=15)
        data = resp.json()
        if not isinstance(data, list):
            return {}

        volumes = {}
        for item in data:
            sym = item.get("symbol", "")
            qv  = float(item.get("quoteVolume", 0) or 0)
            volumes[sym] = qv

        _volume_cache = volumes
        _volume_cache_time = now
        return volumes
    except Exception as e:
        logger.warning(f"24h ticker error: {e}")
        return _volume_cache or {}


def get_trade_pairs(min_volume: float = None) -> list:
    """
    Return list pasangan IDR aktif & likuid di Tokocrypto.
    Filter otomatis by volume 24 jam (MIN_VOLUME_IDR).
    """
    syms = _load_symbols()
    all_pairs = sorted(
        name for name, info in syms.items()
        if "/" in name and info["quote"] == Config.BASE_CURRENCY
    )

    threshold = min_volume if min_volume is not None else Config.MIN_VOLUME_IDR
    if not threshold or threshold <= 0:
        logger.info(f"Scan semua {len(all_pairs)} pair {Config.BASE_CURRENCY} (no volume filter)")
        return all_pairs

    vol_map = get_24h_volume_map()
    if not vol_map:
        logger.warning("Volume map kosong — scan semua pair tanpa filter")
        return all_pairs

    filtered = []
    for pair in all_pairs:
        ticker_sym = pair.replace("/", "")  # BTC/IDR -> BTCIDR
        vol = vol_map.get(ticker_sym, 0)
        if vol >= threshold:
            filtered.append(pair)

    logger.info(
        f"Scan {len(filtered)}/{len(all_pairs)} pair {Config.BASE_CURRENCY} "
        f"(volume >= Rp {threshold:,.0f}/24h)"
    )
    return filtered


def fetch_candles(symbol: str, timeframe: str = None, limit: int = None) -> list:
    """Ambil candle dari Tokocrypto API langsung (harga IDR asli)."""
    tf  = timeframe or Config.TIMEFRAME
    lim = limit or Config.CANDLE_LIMIT

    base_url, sym_str = _market_url_and_symbol(symbol)
    url = f"{base_url}/klines"
    params = {"symbol": sym_str, "interval": tf, "limit": lim}

    try:
        resp = requests.get(url, params=params, timeout=15)
        raw  = resp.json()
        if isinstance(raw, dict):
            if raw.get("code") != 0:
                logger.warning(f"Klines API error {symbol}: {raw.get('msg', '')}")
                return []
            candles = raw.get("data", [])
        elif isinstance(raw, list):
            candles = raw
        else:
            candles = []

        if not candles or len(candles) == 0:
            return []

        return [
            {
                "timestamp": c[0],
                "open":      float(c[1]),
                "high":      float(c[2]),
                "low":       float(c[3]),
                "close":     float(c[4]),
                "volume":    float(c[5]),
            }
            for c in candles
        ]
    except Exception as e:
        logger.warning(f"Candle error {symbol}: {e}")
        return []


def fetch_ticker_price(symbol: str) -> float:
    """
    Ambil harga terkini: mid price dari order book Tokocrypto.
    (best bid + best ask) / 2. Fallback ke MBX klines last close.
    """
    # Gunakan format yang sesuai dengan symbol type
    stype = _get_symbol_type(symbol)
    sym_str = _format_nextme(symbol) if stype != 1 else _format_mbx(symbol)

    for attempt in range(2):
        try:
            resp = requests.get(
                f"{BASE_URL}/open/v1/market/depth",
                params={"symbol": sym_str, "limit": 5},
                headers={"X-MBX-APIKEY": Config.API_KEY},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    depth = data.get("data", {})
                    bids  = depth.get("bids", [])
                    asks  = depth.get("asks", [])
                    if bids and asks:
                        best_bid = float(bids[0][0])
                        best_ask = float(asks[0][0])
                        return (best_bid + best_ask) / 2
        except Exception as e:
            logger.warning(f"Depth error {symbol} (attempt {attempt+1}): {e}")
            if attempt < 1:
                _time.sleep(0.5)

    # Fallback: pakai last close dari klines
    try:
        candles = fetch_candles(symbol, timeframe="5m", limit=5)
        if candles:
            return float(candles[-1]["close"])
    except Exception:
        pass

    return 0.0


def check_market_active(symbol: str) -> bool:
    """Cek apakah pair aktif di Tokocrypto."""
    syms = _load_symbols()
    info = syms.get(symbol)
    if not info:
        return False
    return info.get("active", True)


# ── Account ─────────────────────────────────────────────────────────

def check_idr_balance() -> float:
    """Cek saldo IDR free."""
    data = _signed_get("/open/v1/account/spot")
    if not data:
        return 0.0

    assets = data.get("accountAssets", [])
    for a in assets:
        if a.get("asset") == Config.BASE_CURRENCY:
            free = float(a.get("free", 0))
            logger.info(f"[Balance] Saldo IDR: Rp {free:,.0f}")
            return free
    return 0.0


def get_balance() -> dict:
    """Ambil saldo IDR dan semua holdings crypto."""
    data = _signed_get("/open/v1/account/spot")
    if not data:
        return {"quote": {"free": 0, "used": 0, "total": 0}, "holdings": {}}

    cur    = Config.BASE_CURRENCY
    assets = data.get("accountAssets", [])

    free = 0.0
    used = 0.0
    holdings = {}

    for a in assets:
        asset    = a.get("asset")
        a_free   = float(a.get("free", 0) or 0)
        a_locked = float(a.get("locked", 0) or 0)
        a_total  = a_free + a_locked

        if asset == cur:
            free = a_free
            used = a_locked
        elif a_total > 0:
            holdings[asset] = {
                "free":  a_free,
                "used":  a_locked,
                "total": a_total,
            }

    return {
        "quote": {"free": free, "used": used, "total": free + used},
        "holdings": holdings,
    }


# ── Orders ──────────────────────────────────────────────────────────

def place_order(symbol: str, side: str, amount_idr: float = None,
                amount_base: float = None, price: float = None) -> dict:
    """
    Eksekusi market order via Tokocrypto API.
    BUY  -> quoteOrderQty (nominal IDR)
    SELL -> quantity (jumlah crypto)
    """
    if Config.DRY_RUN:
        qty = amount_base or (amount_idr / price if price and price > 0 else 0)
        val = amount_idr or (amount_base * price if price else 0)
        logger.info(f"[DRY RUN] {side.upper()} {symbol} | qty={qty:.6f} | nilai=Rp {val:,.0f}")
        return {
            "dry_run": True, "symbol": symbol, "side": side,
            "amount": qty, "value_idr": val, "price": price, "status": "simulated",
        }

    sym_str   = _format_nextme(symbol)
    side_enum = 0 if side == "buy" else 1

    params = {
        "symbol": sym_str,
        "side":   side_enum,
        "type":   2,  # MARKET
    }

    if side == "buy":
        if amount_idr is None or amount_idr < Config.MIN_ORDER_IDR:
            return {"error": f"Amount IDR terlalu kecil: {amount_idr} < {Config.MIN_ORDER_IDR}"}
        params["quoteOrderQty"] = str(int(amount_idr))
    else:
        if amount_base is None or amount_base <= 0:
            return {"error": f"Amount crypto tidak valid: {amount_base}"}
        # Gunakan precision dari symbol info (hindari order rejection karena stepSize)
        precision = _get_base_precision(symbol)
        params["quantity"] = f"{amount_base:.{precision}f}"

    data = _signed_post("/open/v1/orders", params)
    if not data:
        return {"error": "Order gagal, response kosong"}

    filled_qty   = float(data.get("executedQty", 0) or 0)
    filled_price = float(data.get("executedPrice", 0) or price or 0)

    logger.info(
        f"{side.upper()} ORDER OK: {symbol} | {filled_qty:.6f} "
        f"| avg Rp {filled_price:,.0f} | ID: {data.get('orderId')}"
    )

    return {
        "dry_run":   False,
        "id":        str(data.get("orderId", "")),
        "symbol":    symbol,
        "side":      side,
        "amount":    filled_qty,
        "value_idr": amount_idr or (filled_qty * filled_price),
        "price":     filled_price,
        "status":    "filled" if filled_qty > 0 else "new",
    }
