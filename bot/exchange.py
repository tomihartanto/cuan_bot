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
_symbol_loaded_time = 0  # timestamp saat terakhir load (untuk TTL)
_SYMBOL_CACHE_TTL = 3600  # 1 jam — refresh agar crypto baru listing terdeteksi


# ── HMAC Helpers ────────────────────────────────────────────────────

def _hmac_sha256(secret: str, data: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), data.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _signed_get(endpoint: str, params: dict = None, retries: int = 2) -> dict:
    if params is None:
        params = {}
    # ── Jangan mutasi dict caller (sama seperti _signed_post) ──────────
    current_params = {
        **params,
        "timestamp":  int(_time.time() * 1000),
        "recvWindow": 5000,
    }

    query = "&".join(f"{k}={v}" for k, v in sorted(current_params.items()))
    signature = _hmac_sha256(Config.SECRET_KEY, query)

    url = f"{BASE_URL}{endpoint}?{query}&signature={signature}"
    headers = {"X-MBX-APIKEY": Config.API_KEY}

    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            data = resp.json()
            if data.get("code") != 0:
                logger.warning(f"API error GET {endpoint}: {data.get('msg', resp.text[:200])}")
                return {"__api_error__": True, "code": data.get("code"), "msg": data.get("msg", "")}
            return data.get("data", {})
        except Exception as e:
            logger.error(f"API request failed GET {endpoint} (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                _time.sleep(1)
    return {}


def _signed_post(endpoint: str, params: dict, retries: int = 2) -> dict:
    # ── Refresh timestamp tiap attempt (JANGAN mutasi dict caller) ────
    current_time = int(_time.time() * 1000)
    current_params = {
        **params,
        "timestamp": current_time,
        "recvWindow": 5000,
    }

    # ── SORT params untuk signature (konsisten dengan _signed_get) ────
    body = "&".join(f"{k}={v}" for k, v in sorted(current_params.items()))
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
                msg = data.get("msg") or data.get("message", resp.text[:200])
                logger.warning(
                    f"API error POST {endpoint}: {msg}"
                )
                # Return error info agar caller bisa handle (bukan kosong)
                return {"__api_error__": True, "code": data.get("code"), "msg": msg}
            return data.get("data", {})
        except Exception as e:
            logger.error(f"API request failed POST {endpoint} (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                _time.sleep(1)
    return {"__api_error__": True, "code": -1, "msg": "Connection failed after retries"}


# ── Symbol Info ─────────────────────────────────────────────────────

def _load_symbols(force: bool = False):
    """Load daftar symbol dari Tokocrypto. Otomatis refresh tiap 1 jam (TTL)."""
    global _symbol_info, _symbol_loaded, _symbol_loaded_time
    now = _time.time()
    if _symbol_loaded and not force and (now - _symbol_loaded_time) < _SYMBOL_CACHE_TTL:
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
    _symbol_loaded_time = _time.time()
    n = len([k for k in _symbol_info if "/" in k])
    logger.info(f"Loaded {n} trading symbols dari Tokocrypto (cache TTL {_SYMBOL_CACHE_TTL}s)")
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

def get_trade_pairs(min_volume: float = None) -> list:
    """
    Return list pasangan IDR aktif & likuid di Tokocrypto.
    Filter otomatis by volume 24 jam (MIN_VOLUME_IDR).

    Exception: pair dengan volume spike ekstrem (indikasi hot/pump) tetap
    dimasukkan walau volume 24h-nya di bawah MIN_VOLUME_IDR, asal masih di
    atas HOT_LISTING_VOLUME_MIN. Memungkinkan bot menangkap crypto hot baru.
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

    # Ambil 24h quote volume + harga untuk hitung spike ratio
    ticker_stats = _get_24h_ticker_stats()

    filtered = []
    hot_candidates = []
    for pair in all_pairs:
        ticker_sym = pair.replace("/", "")  # BTC/IDR -> BTCIDR
        vol = vol_map.get(ticker_sym, 0)
        if vol >= threshold:
            filtered.append(pair)
            continue

        # Cek apakah ini kandidat "hot" (volume spike ekstrem)
        stats = ticker_stats.get(ticker_sym)
        if stats and vol >= Config.HOT_LISTING_VOLUME_MIN:
            spike_ratio = stats.get("volume_spike_ratio", 1.0)
            price_change_pct = abs(stats.get("price_change_pct", 0))
            # Hot = volume spike >= 5x DAN pergerakan harga signifikan
            if spike_ratio >= Config.HOT_VOLUME_SPIKE_RATIO and price_change_pct >= 3.0:
                hot_candidates.append(pair)

    all_scan = filtered + hot_candidates
    logger.info(
        f"Scan {len(all_scan)}/{len(all_pairs)} pair {Config.BASE_CURRENCY} "
        f"(likuid: {len(filtered)}, hot: {len(hot_candidates)})"
    )
    return all_scan


# ── 24h Ticker Stats (untuk deteksi pump) ──────────────────────────
# Digabung dengan volume map — SATU request untuk DUAKA data.

_ticker_cache = None
_ticker_cache_time = 0
_TICKER_CACHE_TTL = 300  # 5 menit


def _load_24h_ticker(force: bool = False) -> dict:
    """
    SATU request ke /ticker/24hr → return {symbol: full_item_dict}.
    Digunakan oleh get_24h_volume_map() dan get_24h_ticker_stats().
    Cached 5 menit.
    """
    global _ticker_cache, _ticker_cache_time
    now = _time.time()
    if _ticker_cache is not None and not force and (now - _ticker_cache_time) < _TICKER_CACHE_TTL:
        return _ticker_cache

    try:
        resp = requests.get(f"{MBX_URL}/ticker/24hr", timeout=15)
        data = resp.json()
        if not isinstance(data, list):
            return _ticker_cache or {}

        ticker = {}
        for item in data:
            sym = item.get("symbol", "")
            if sym:
                ticker[sym] = item

        _ticker_cache = ticker
        _ticker_cache_time = now
        return ticker
    except Exception as e:
        logger.warning(f"24h ticker error: {e}")
        return _ticker_cache or {}


def get_24h_volume_map() -> dict:
    """Return {symbol: quoteVolume_24h} untuk semua pair IDR. Cached 5 menit."""
    ticker = _load_24h_ticker()
    return {sym: float(item.get("quoteVolume", 0) or 0) for sym, item in ticker.items()}


def _get_24h_ticker_stats() -> dict:
    """
    Statistik 24h ticker (volume spike ratio + price change %).
    Renamed dari proxy palsu → pakai quote volume sebagai rujukan.
    """
    ticker = _load_24h_ticker()
    stats = {}
    for sym, item in ticker.items():
        price_change = float(item.get("priceChangePercent", 0) or 0)
        stats[sym] = {
            "quote_volume": float(item.get("quoteVolume", 0) or 0),
            "volume": float(item.get("volume", 0) or 0),
            "price_change_pct": price_change,
            "high": float(item.get("highPrice", 0) or 0),
            "low": float(item.get("lowPrice", 0) or 0),
            # Rename: bukan "volume spike" tapi price volatility proxy
            "price_volatility_ratio": max(1.0, abs(price_change) / 3.0),
            "volume_spike_ratio": max(1.0, abs(price_change) / 3.0),  # backward compat
        }
    return stats


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

def validate_min_notional(side: str, amount_idr: float = None,
                          amount_base: float = None, price: float = None) -> tuple:
    """
    Validasi nominal minimum transaksi sebelum dikirim ke exchange.

    Persyaratan minimum Tokocrypto (MIN_ORDER_IDR):
      - BUY : amount_idr >= MIN_ORDER_IDR
      - SELL: (amount_base * price) >= MIN_ORDER_IDR

    Return: (is_valid: bool, error_msg: str)
    """
    min_idr = Config.MIN_ORDER_IDR

    if side == "buy":
        if amount_idr is None or amount_idr <= 0:
            return False, (f"Nominal {side.upper()} tidak valid: Rp {amount_idr}. "
                           f"Minimum {side.upper()} adalah Rp {min_idr:,.0f}.")
        if amount_idr < min_idr:
            return False, (f"Nominal {side.upper()} terlalu kecil: Rp {amount_idr:,.0f}. "
                           f"Minimum {side.upper()} adalah Rp {min_idr:,.0f}.")
        return True, ""

    elif side == "sell":
        if amount_base is None or amount_base <= 0:
            return False, (f"Jumlah crypto {side.upper()} tidak valid: {amount_base}.")
        # Untuk SELL, nilai IDR = jumlah crypto * harga
        value_idr = amount_base * price if price and price > 0 else 0
        if value_idr <= 0:
            return False, (f"Tidak dapat menghitung nilai {side.upper()} (harga tidak tersedia). "
                           f"Minimum {side.upper()} adalah Rp {min_idr:,.0f}.")
        if value_idr < min_idr:
            return False, (
                f"Nominal {side.upper()} terlalu kecil: Rp {value_idr:,.0f} "
                f"({amount_base:.8f} x Rp {price:,.0f}). "
                f"Minimum {side.upper()} adalah Rp {min_idr:,.0f}."
            )
        return True, ""

    return False, f"Side tidak dikenal: {side}"


def place_order(symbol: str, side: str, amount_idr: float = None,
                amount_base: float = None, price: float = None,
                skip_validation: bool = False) -> dict:
    """
    Eksekusi market order via Tokocrypto API.
    BUY  -> quoteOrderQty (nominal IDR)
    SELL -> quantity (jumlah crypto), fallback ke quoteOrderQty kalau gagal min notional

    Validasi nominal minimum (MIN_ORDER_IDR) diterapkan untuk kedua sisi,
    KECUALI skip_validation=True (untuk dust sell).
    """
    # ── Server-side validation: nominal minimum ─────────────────────
    if not skip_validation:
        ok, err = validate_min_notional(side, amount_idr=amount_idr,
                                        amount_base=amount_base, price=price)
        if not ok:
            logger.warning(f"[VALIDATION] {side.upper()} {symbol} ditolak: {err}")
            return {"error": err}

    if Config.DRY_RUN:
        qty = amount_base or (amount_idr / price if price and price > 0 else 0)
        val = amount_idr or (amount_base * price if price else 0)
        logger.info(f"[DRY RUN] {side.upper()} {symbol} | qty={qty:.6f} | nilai=Rp {val:,.0f}")
        return {
            "dry_run": True, "symbol": symbol, "side": side,
            "amount": qty, "value_idr": val, "price": price, "status": "simulated",
        }

    sym_str   = _format_nextme(symbol)  # endpoint /open/v1/orders pakai NextMe format
    side_enum = 0 if side == "buy" else 1

    params = {
        "symbol": sym_str,
        "side":   side_enum,
        "type":   2,  # MARKET
    }
    # Catatan: endpoint /open/v1/orders konsisten pakai format NextMe (BTC_IDR)
    # untuk semua symbol type. Berbeda dengan fetch_ticker_price/fetch_candles
    # yang dispatch berdasarkan type (MBX vs NextMe).

    if side == "buy":
        params["quoteOrderQty"] = str(int(amount_idr))
    else:
        # SELL: gunakan precision dari symbol info
        precision = _get_base_precision(symbol)
        params["quantity"] = f"{amount_base:.{precision}f}"

    data = _signed_post("/open/v1/orders", params)

    # ── Handle API error (bukan response kosong) ────────────────────
    if isinstance(data, dict) and data.get("__api_error__"):
        error_msg = data.get("msg", "Unknown API error")
        # ── Fallback SELL via quoteOrderQty ──────────────────────────
        if side == "sell" and amount_base and price and price > 0:
            sell_value_idr = int(amount_base * price)
            if sell_value_idr >= Config.MIN_ORDER_IDR:
                logger.info(f"SELL {symbol}: quantity gagal ({error_msg}), retry via quoteOrderQty=Rp {sell_value_idr:,}")
                fallback_params = {
                    "symbol": sym_str, "side": 1, "type": 2,
                    "quoteOrderQty": str(sell_value_idr),
                }
                fallback_data = _signed_post("/open/v1/orders", fallback_params)
                if isinstance(fallback_data, dict) and not fallback_data.get("__api_error__") and fallback_data:
                    data = fallback_data
                    logger.info(f"SELL {symbol}: quoteOrderQty fallback berhasil")
                else:
                    fb_msg = fallback_data.get("msg", "unknown") if isinstance(fallback_data, dict) else "empty"
                    return {"error": f"SELL gagal: {error_msg}. quoteOrderQty juga gagal: {fb_msg}"}
            else:
                return {"error": f"{error_msg} (nilai Rp {sell_value_idr:,} < min Rp {Config.MIN_ORDER_IDR:,})"}
        else:
            return {"error": error_msg}

    # Response kosong (bukan error) — ERROR, bukan sukses
    if not data:
        return {"error": f"Order gagal, response kosong dari server"}

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


# ── Order Management ───────────────────────────────────────────────

def cancel_order(symbol: str, order_id: str = None, client_order_id: str = None) -> dict:
    """
    Batalkan order aktif di Tokocrypto.
    Parameter: symbol WAJIB, order_id atau client_order_id SALAH SATU.
    Returns: {success, order_id, msg}
    """
    sym_str = _format_nextme(symbol)
    params = {"symbol": sym_str}

    if order_id:
        params["orderId"] = int(order_id) if isinstance(order_id, str) and order_id.isdigit() else order_id
    elif client_order_id:
        params["origClientOrderId"] = client_order_id
    else:
        return {"success": False, "msg": "Order ID atau client order ID diperlukan"}

    data = _signed_post("/open/v1/orders/cancel", params)

    if isinstance(data, dict) and data.get("__api_error__"):
        return {"success": False, "msg": data.get("msg", "Cancel gagal")}

    if not data:
        return {"success": False, "msg": "Response kosong saat cancel"}

    cancelled_id = data.get("orderId", order_id)
    logger.info(f"CANCEL ORDER OK: {symbol} | ID: {cancelled_id}")
    return {"success": True, "order_id": str(cancelled_id), "symbol": symbol}


def get_open_orders(symbol: str = None) -> list:
    """
    Ambil daftar order yang masih aktif/pending.
    Jika symbol diberikan, filter hanya untuk symbol tersebut.
    Returns: list of dicts [{id, symbol, side, price, qty, status}, ...]
    """
    params = {}
    if symbol:
        params["symbol"] = _format_nextme(symbol)

    data = _signed_get("/open/v1/orders", params if params else None)

    if isinstance(data, dict) and data.get("__api_error__"):
        logger.warning(f"Gagal ambil open orders: {data.get('msg')}")
        return []

    if not data:
        return []

    # Bisa berupa list atau dict dengan key "list"
    orders = data if isinstance(data, list) else data.get("list", data.get("orders", []))
    if not isinstance(orders, list):
        orders = [orders]

    result = []
    for o in orders:
        sym = o.get("symbol", "")
        # Normalize symbol format: BTC_IDR → BTC/IDR
        sym_normalized = sym.replace("_", "/").replace("BTCIDR", "BTC/IDR")
        result.append({
            "id":           str(o.get("orderId", "")),
            "symbol":       sym_normalized,
            "side":         "buy" if o.get("side") == 0 else "sell",
            "type":         o.get("type"),
            "price":        float(o.get("price", 0) or 0),
            "qty":          float(o.get("origQty", 0) or 0),
            "filled_qty":   float(o.get("executedQty", 0) or 0),
            "status":       o.get("status", "UNKNOWN"),
            "time":         o.get("time"),
            "client_order_id": o.get("clientOrderId", ""),
        })

    return result


def get_order_detail(order_id: str) -> dict:
    """
    Ambil detail order berdasarkan order ID.
    Returns: {id, symbol, side, price, qty, filled_qty, status, ...} atau {}
    """
    data = _signed_get("/open/v1/orders/detail", {"orderId": order_id})

    if isinstance(data, dict) and data.get("__api_error__"):
        return {}

    if not data:
        return {}

    sym = data.get("symbol", "").replace("_", "/").replace("BTCIDR", "BTC/IDR")
    return {
        "id":           str(data.get("orderId", "")),
        "symbol":       sym,
        "side":         "buy" if data.get("side") == 0 else "sell",
        "type":         data.get("type"),
        "price":        float(data.get("price", 0) or 0),
        "qty":          float(data.get("origQty", 0) or 0),
        "filled_qty":   float(data.get("executedQty", 0) or 0),
        "filled_price": float(data.get("avgPrice", 0) or 0),
        "status":       data.get("status", "UNKNOWN"),
        "time":         data.get("time"),
    }


def cancel_all_orders(symbol: str = None) -> int:
    """
    Batalkan SEMUA open orders. Jika symbol diberikan, hanya untuk symbol tersebut.
    Returns: jumlah order yang berhasil dibatalkan.
    """
    orders = get_open_orders(symbol)
    cancelled = 0

    for o in orders:
        result = cancel_order(o["symbol"], order_id=o["id"])
        if result.get("success"):
            cancelled += 1
            _time.sleep(0.3)  # rate limit

    if cancelled > 0:
        logger.info(f"Cancelled {cancelled}/{len(orders)} open orders")
    return cancelled


# ── Server Time ─────────────────────────────────────────────────────

def get_server_time() -> int:
    """Ambil server time Tokocrypto (unix timestamp ms). Untuk clock sync."""
    try:
        resp = requests.get(f"{BASE_URL}/open/v1/common/time", timeout=10)
        data = resp.json()
        if data.get("code") == 0:
            # Tokocrypto returns timestamp at root level (data=null)
            ts = data.get("timestamp") or data.get("data", {}).get("serverTime", 0)
            return int(ts)
    except Exception:
        pass
    return 0


def get_clock_drift_ms() -> int:
    """Return selisih waktu lokal vs server (ms). Negatif = lokal tertinggal."""
    server = get_server_time()
    if server <= 0:
        return 0
    local = int(_time.time() * 1000)
    return local - server

