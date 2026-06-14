"""
CuanBot v4 - Exchange Connection
Fix: quoteOrderQty untuk market buy, validasi minimum order, price fetching yang reliable.
"""

import ccxt
import requests
import time as _time
from config import Config
import logging
from bot import notifier

logger = logging.getLogger("cuanbot")

_usdt_idr_rate = None


def get_usdt_idr_rate() -> float:
    """Ambil kurs USDT/IDR (cached per session)."""
    global _usdt_idr_rate
    if _usdt_idr_rate:
        return _usdt_idr_rate
    # Primary: Binance USDTIDR
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/ticker/price",
            params={"symbol": "USDTIDR"}, timeout=10
        )
        if r.status_code == 200:
            _usdt_idr_rate = float(r.json()["price"])
            logger.info(f"USDT/IDR rate: {_usdt_idr_rate:,.0f}")
            return _usdt_idr_rate
    except Exception:
        pass
    # Fallback: BNB cross rate
    try:
        r1 = requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": "BNBIDR"}, timeout=10)
        r2 = requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": "BNBUSDT"}, timeout=10)
        if r1.status_code == 200 and r2.status_code == 200:
            _usdt_idr_rate = float(r1.json()["price"]) / float(r2.json()["price"])
            logger.info(f"USDT/IDR rate (via BNB cross): {_usdt_idr_rate:,.0f}")
            return _usdt_idr_rate
    except Exception:
        pass
    _usdt_idr_rate = 16500.0
    logger.warning(f"Pakai kurs fallback: {_usdt_idr_rate}")
    return _usdt_idr_rate


def create_exchange() -> ccxt.Exchange:
    return ccxt.tokocrypto({
        "apiKey": Config.API_KEY,
        "secret": Config.SECRET_KEY,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })


def get_trade_pairs(exchange=None) -> list:
    pairs = []
    available_markets = None
    if exchange is not None:
        try:
            exchange.load_markets()
            available_markets = exchange.markets
        except Exception as e:
            logger.warning(f"Gagal memuat daftar market dari exchange: {e}")

    for s in Config.SCAN_COINS:
        pair = f"{s}/{Config.BASE_CURRENCY}"
        if available_markets is not None:
            if pair in available_markets:
                pairs.append(pair)
            else:
                logger.warning(f"Pasang {pair} dilewati karena tidak tersedia di Tokocrypto.")
        else:
            pairs.append(pair)

    logger.info(f"Scan {len(pairs)} pasang {Config.BASE_CURRENCY} dari {len(Config.SCAN_COINS)} di config")
    return pairs


def check_and_allocate_funds(exchange) -> tuple[str, float]:
    """
    Memeriksa saldo IDR & USDT dan mengalokasikan mata uang aktif secara dinamis.
    Melakukan konversi otomatis IDR -> USDT jika saldo IDR >= Rp 180.000 dan USDT < 10.
    Returns:
        (active_currency, available_balance)
    """
    try:
        balance = exchange.fetch_balance()
        idr_free = float(balance.get("IDR", {}).get("free", 0) or 0)
        usdt_free = float(balance.get("USDT", {}).get("free", 0) or 0)
        
        logger.info(f"[Alloc Manager] Saldo: Rp {idr_free:,.0f} IDR | {usdt_free:.4f} USDT")
        
        # Batas konversi minimum (misal Rp 180.000)
        CONVERSION_THRESHOLD_IDR = 180000.0
        
        if usdt_free >= 10.0:
            logger.info("[Alloc Manager] Saldo USDT mencukupi (>= 10 USDT). Menggunakan mode USDT.")
            return "USDT", usdt_free
            
        if idr_free >= CONVERSION_THRESHOLD_IDR:
            logger.info(f"[Alloc Manager] Saldo IDR (Rp {idr_free:,.0f}) cukup untuk konversi. Memulai auto-conversion...")
            # Sisa saldo disisakan sedikit untuk fee (misal Rp 5.000)
            amount_to_convert = idr_free - 5000.0
            
            try:
                logger.info(f"[Alloc Manager] Membeli USDT menggunakan Rp {amount_to_convert:,.0f} IDR di market USDT/IDR...")
                order = exchange.create_order(
                    "USDT/IDR", "MARKET", "buy",
                    None, None,
                    {"quoteOrderQty": amount_to_convert}
                )
                logger.info(f"[Alloc Manager] Konversi sukses! Order ID: {order.get('id')}")
                
                # Re-fetch balance
                balance = exchange.fetch_balance()
                usdt_free = float(balance.get("USDT", {}).get("free", 0) or 0)
                idr_free = float(balance.get("IDR", {}).get("free", 0) or 0)
                
                notifier.send_telegram(
                    f"🔄 <b>Auto-Allocation Manager</b>\n"
                    f"Berhasil mengonversi Rp {amount_to_convert:,.0f} IDR menjadi USDT.\n"
                    f"Saldo saat ini: {usdt_free:.4f} USDT | Rp {idr_free:,.0f} IDR.\n"
                    f"Bot sekarang beralih ke mode trading <b>USDT</b>."
                )
                return "USDT", usdt_free
            except Exception as e:
                logger.error(f"[Alloc Manager] Gagal konversi IDR -> USDT: {e}")
                notifier.notify_error(f"Gagal konversi otomatis IDR -> USDT: {e}")
                # Fallback ke IDR mode if conversion failed
                
        if idr_free >= 10000.0:
            logger.info("[Alloc Manager] Saldo USDT tidak cukup (< 10 USDT), saldo IDR mencukupi (>= Rp 10.000). Menggunakan mode IDR.")
            return "IDR", idr_free
            
        return "NONE", 0.0
    except Exception as e:
        logger.error(f"[Alloc Manager] Error saat memeriksa/mengalokasikan saldo: {e}")
        # Default fallback ke IDR jika fetch balance error, agar tidak memutus flow di tempat lain
        return "IDR", 0.0


def fetch_candles(exchange, symbol: str, timeframe: str = None, limit: int = None) -> list:
    """Ambil candle dari Binance (lebih stabil dari Tokocrypto untuk data historis)."""
    try:
        tf  = timeframe or Config.TIMEFRAME
        lim = limit or Config.CANDLE_LIMIT
        base = symbol.split("/")[0]
        rate = get_usdt_idr_rate()

        binance_sym = f"{base}USDT"
        resp = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": binance_sym, "interval": tf, "limit": lim},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return [
                    {
                        "timestamp": c[0],
                        "open":      float(c[1]) * rate,
                        "high":      float(c[2]) * rate,
                        "low":       float(c[3]) * rate,
                        "close":     float(c[4]) * rate,
                        "volume":    float(c[5]),
                    }
                    for c in data
                ]
            logger.warning(f"Binance: 0 candles untuk {binance_sym}")
        elif resp.status_code == 400:
            # Symbol tidak ada di Binance (e.g. bukan USDT pair)
            logger.debug(f"Symbol tidak ditemukan di Binance: {binance_sym}")
        else:
            logger.warning(f"Binance error {binance_sym}: {resp.status_code}")
        return []
    except Exception as e:
        logger.warning(f"Candle error {symbol}: {e}")
        return []


def fetch_ticker_price(exchange, symbol: str) -> float:
    """Ambil harga terkini dari Tokocrypto (untuk cek TP/SL posisi aktif)."""
    try:
        ticker = exchange.fetch_ticker(symbol)
        price = ticker.get("last") or ticker.get("close") or 0
        return float(price)
    except Exception as e:
        logger.warning(f"Ticker error {symbol}: {e}")
        # Fallback: hitung dari Binance
        try:
            base = symbol.split("/")[0]
            rate = get_usdt_idr_rate()
            r = requests.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbol": f"{base}USDT"}, timeout=10
            )
            if r.status_code == 200:
                return float(r.json()["price"]) * rate
        except Exception:
            pass
        return 0.0


def get_balance(exchange) -> dict:
    """Ambil saldo quote currency (IDR/USDT) dan semua holdings crypto."""
    try:
        cur     = Config.BASE_CURRENCY
        balance = exchange.fetch_balance()
        free    = float(balance.get(cur, {}).get("free", 0) or 0)
        used    = float(balance.get(cur, {}).get("used", 0) or 0)
        total   = float(balance.get(cur, {}).get("total", 0) or 0)

        holdings = {}
        for asset, amounts in balance.items():
            if not isinstance(amounts, dict):
                continue
            if asset in ("info", "free", "used", "total", cur):
                continue
            total_amt = float(amounts.get("total", 0) or 0)
            if total_amt > 0:
                holdings[asset] = {
                    "free":  float(amounts.get("free", 0) or 0),
                    "used":  float(amounts.get("used", 0) or 0),
                    "total": total_amt,
                }
        return {"quote": {"free": free, "used": used, "total": total}, "holdings": holdings}
    except Exception as e:
        logger.error(f"Balance error: {e}")
        raise e


def place_order(exchange, symbol: str, side: str, amount_idr: float = None,
                amount_base: float = None, price: float = None) -> dict:
    """
    Eksekusi market order.
    
    Untuk BUY  → gunakan amount_idr (IDR) via quoteOrderQty agar tidak under-minimum
    Untuk SELL → gunakan amount_base (jumlah crypto yang dipegang)
    """
    try:
        if Config.DRY_RUN:
            qty = amount_base or (amount_idr / price if price and price > 0 else 0)
            val = amount_idr or (amount_base * price if price else 0)
            logger.info(f"[DRY RUN] {side.upper()} {symbol} | qty={qty:.6f} | nilai=Rp {val:,.0f}")
            return {
                "dry_run": True, "symbol": symbol, "side": side,
                "amount": qty, "value_idr": val, "price": price, "status": "simulated",
            }

        if side == "buy":
            # ✅ FIX #1: Pakai quoteOrderQty → bot kasih IDR, exchange kasih crypto
            if amount_idr is None or amount_idr < Config.MIN_ORDER_IDR:
                return {"error": f"Amount IDR terlalu kecil: {amount_idr} < {Config.MIN_ORDER_IDR}"}
            try:
                # Cara 1: quoteOrderQty via params
                order = exchange.create_order(
                    symbol, "MARKET", "buy",
                    None, None,
                    {"quoteOrderQty": amount_idr}
                )
            except Exception:
                # Cara 2: fallback ke base amount kalau exchange tidak support quoteOrderQty
                if price and price > 0:
                    base_qty = amount_idr / price
                    order = exchange.create_market_buy_order(symbol, base_qty)
                else:
                    raise
            filled_qty   = float(order.get("filled") or order.get("amount") or 0)
            filled_price = float(order.get("average") or order.get("price") or price or 0)
            logger.info(f"BUY ORDER OK: {symbol} | {filled_qty:.6f} | avg Rp {filled_price:,.0f} | ID: {order.get('id')}")
            return {
                "dry_run": False, "id": order.get("id"), "symbol": symbol, "side": "buy",
                "amount": filled_qty, "value_idr": amount_idr,
                "price": filled_price, "status": order.get("status"),
            }

        else:  # sell
            if amount_base is None or amount_base <= 0:
                return {"error": f"Amount crypto tidak valid: {amount_base}"}
            order = exchange.create_market_sell_order(symbol, amount_base)
            filled_qty   = float(order.get("filled") or order.get("amount") or amount_base)
            filled_price = float(order.get("average") or order.get("price") or price or 0)
            logger.info(f"SELL ORDER OK: {symbol} | {filled_qty:.6f} | avg Rp {filled_price:,.0f} | ID: {order.get('id')}")
            return {
                "dry_run": False, "id": order.get("id"), "symbol": symbol, "side": "sell",
                "amount": filled_qty, "value_idr": filled_qty * filled_price,
                "price": filled_price, "status": order.get("status"),
            }

    except Exception as e:
        logger.error(f"Order ERROR {side} {symbol}: {e}")
        return {"error": str(e), "symbol": symbol, "side": side}
