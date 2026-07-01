"""
CuanBot v4 - WebSocket Real-Time Module
Streaming harga real-time dari Tokocrypto + account updates.

WSS Tokocrypto:
  - Type 1 (MBX):  wss://stream-bn.2meta.app/ws (BTC, ETH, dll legacy)
  - Type 2:         wss://www.tokocrypto.com/ws (tidak dipakai)
  - Type 3 (NextMe): wss://stream-toko.2meta.app/ws (SEMUA pair IDR aktif)

Untuk account updates (balance change, order fills):
  POST /open/v1/user-listen-token → listenToken → subscribe WSS

Fitur:
  - Real-time harga semua pair IDR (tidak perlu polling depth per pair)
  - Account balance update otomatis saat trade eksekusi
  - Cache harga terbaru untuk scan/sell cepat tanpa API call
"""

import json
import time as _time
import threading
import logging
from config import Config
from bot.exchange import _signed_post, _format_nextme, _load_symbols

logger = logging.getLogger("cuanbot")

# ── WSS URLs ────────────────────────────────────────────────────────
WSS_NEXTME = "wss://stream-toko.2meta.app/ws"

# ── State ────────────────────────────────────────────────────────────
_price_cache = {}      # {"BTC/IDR": {"price": 12345.0, "bid": 12340, "ask": 12350, "ts": 1234567890}}
_cache_lock = threading.Lock()

_balance_cache = None  # dari account stream
_balance_ts = 0

_ws_thread = None
_ws_running = False
_listen_token = None
_listen_token_ts = 0
_LISTEN_TOKEN_TTL = 1800  # 30 menit (must ping)


def get_latest_price(symbol: str) -> dict:
    """Ambil harga terbaru dari WebSocket cache. Return {} kalau belum ada."""
    with _cache_lock:
        return _price_cache.get(symbol, {})


def get_all_prices() -> dict:
    """Return seluruh price cache {symbol: {price, bid, ask, ts}}."""
    with _cache_lock:
        return dict(_price_cache)


def get_cached_balance():
    """Return balance cache dari account stream, atau None."""
    if _balance_cache and (_time.time() - _balance_ts) < 60:
        return _balance_cache
    return None


def is_running() -> bool:
    return _ws_running


# ── WebSocket Thread ────────────────────────────────────────────────

def _start_ws_market():
    """
    Koneksi ke WSS market stream → mini-ticker semua pair IDR.
    Format stream: btc_idr@miniTicker (NextMe).
    
    NOTE: WSS Tokocrypto mungkin tidak mengirim data untuk semua pair IDR.
    Jika tidak ada data setelah 10 detik, fallback ke polling biasa.
    Harga tetap diambil via fetch_ticker_price (HTTP) — WebSocket hanya bonus.
    """
    global _ws_running

    # Ambil semua pair IDR
    syms = _load_symbols()
    idr_pairs = [s for s in syms if "/" in s and syms[s].get("quote") == Config.BASE_CURRENCY]

    if not idr_pairs:
        logger.error("[WSS] Tidak ada pair IDR untuk di-stream")
        return

    # Subscribe ke mini-ticker semua pair
    streams = [f"{_format_nextme(p).lower()}@miniTicker" for p in idr_pairs]
    # WSS NextMe supports combined streams
    sub_msg = {
        "method": "SUBSCRIBE",
        "params": streams,
        "id": 1,
    }

    try:
        import websocket
    except ImportError:
        logger.warning("[WSS] websocket-client tidak terinstall. Pakai polling biasa.")
        logger.warning("[WSS] Install: pip install websocket-client")
        return

    ws = websocket.WebSocket()
    connected = False

    for attempt in range(3):
        try:
            ws.connect(WSS_NEXTME, timeout=10)
            connected = True
            break
        except Exception as e:
            logger.warning(f"[WSS] Koneksi gagal attempt {attempt+1}: {e}")
            _time.sleep(2)

    if not connected:
        logger.error("[WSS] Gagal koneksi ke market stream")
        return

    ws.send(json.dumps(sub_msg))
    logger.info(f"[WSS] ✅ Market stream connected — {len(streams)} pair IDR")

    try:
        while _ws_running:
            try:
                ws.settimeout(30)
                msg = ws.recv()
                if not msg:
                    continue

                data = json.loads(msg)

                # Ping response
                if isinstance(data, dict) and data.get("id") == 1:
                    if data.get("result") is None:
                        logger.info("[WSS] Subscribed ke market streams")
                    continue

                # Mini-ticker update
                if isinstance(data, dict) and "s" in data:
                    sym_raw = data["s"]  # BTC_IDR
                    sym = sym_raw.replace("_", "/")

                    price = float(data.get("c", 0) or 0)
                    if price <= 0:
                        continue

                    update = {
                        "price": price,
                        "bid": float(data.get("b", 0) or price),
                        "ask": float(data.get("a", 0) or price),
                        "high": float(data.get("h", 0) or 0),
                        "low": float(data.get("l", 0) or 0),
                        "volume": float(data.get("v", 0) or 0),
                        "change_pct": float(data.get("P", 0) or 0),
                        "ts": int(data.get("E", 0) or _time.time() * 1000),
                    }

                    with _cache_lock:
                        _price_cache[sym] = update

            except websocket.WebSocketTimeoutException:
                # Send ping to keep alive
                try:
                    ws.ping()
                    ws.recv()  # wait for pong
                except Exception:
                    pass

            except json.JSONDecodeError:
                continue

            except Exception as e:
                logger.warning(f"[WSS] Market stream error: {e}")
                _time.sleep(1)

    except Exception as e:
        logger.error(f"[WSS] Market stream crashed: {e}")
    finally:
        try:
            ws.close()
        except Exception:
            pass
        logger.info("[WSS] Market stream disconnected")


def _start_ws_account():
    """
    Koneksi ke WSS account stream untuk balance & order updates.
    Endpoint: POST /open/v1/user-listen-token (BARU, mengganti user-data-stream)
    """
    global _listen_token, _listen_token_ts, _balance_cache, _balance_ts

    try:
        import websocket
    except ImportError:
        return

    # Get listen token
    token = _get_listen_token()
    if not token:
        logger.warning("[WSS-Account] Gagal ambil listen token")
        return

    ws = websocket.WebSocket()
    try:
        ws.connect(WSS_NEXTME, timeout=10)
        # Subscribe dengan listen token
        ws.send(json.dumps({
            "method": "subscribe",
            "listenToken": token,
            "id": 2,
        }))
        logger.info("[WSS-Account] ✅ Account stream connected")
    except Exception as e:
        logger.error(f"[WSS-Account] Koneksi gagal: {e}")
        try:
            ws.close()
        except Exception:
            pass
        return

    try:
        while _ws_running:
            try:
                ws.settimeout(60)
                msg = ws.recv()
                if not msg:
                    continue

                data = json.loads(msg)

                # Ping/pong
                if isinstance(data, dict) and data.get("id") == 2:
                    continue

                # Account update
                if isinstance(data, dict) and data.get("e") == "outboundAccountPosition":
                    _handle_balance_update(data)

                # Order update
                if isinstance(data, dict) and data.get("e") == "executionReport":
                    _handle_order_update(data)

            except websocket.WebSocketTimeoutException:
                # Refresh listen token kalau sudah dekat expired
                if _time.time() - _listen_token_ts > _LISTEN_TOKEN_TTL - 60:
                    new_token = _get_listen_token()
                    if new_token and new_token != _listen_token:
                        logger.info("[WSS-Account] Refresh listen token")
                        ws.send(json.dumps({
                            "method": "unsubscribe",
                            "listenToken": _listen_token,
                            "id": 99,
                        }))
                        _listen_token = new_token
                        ws.send(json.dumps({
                            "method": "subscribe",
                            "listenToken": _listen_token,
                            "id": 2,
                        }))
                try:
                    ws.ping()
                    ws.recv()
                except Exception:
                    pass

            except Exception as e:
                logger.debug(f"[WSS-Account] Stream error: {e}")

    except Exception as e:
        logger.error(f"[WSS-Account] Stream crashed: {e}")
    finally:
        try:
            ws.close()
        except Exception:
            pass


def _handle_balance_update(data: dict):
    """Handle balance update dari account stream."""
    global _balance_cache, _balance_ts
    balances = data.get("B", [])
    if not balances:
        return

    holdings = {}
    quote_free = 0.0
    for b in balances:
        asset = b.get("a", "")
        free = float(b.get("f", 0) or 0)
        locked = float(b.get("l", 0) or 0)
        total = free + locked

        if asset == Config.BASE_CURRENCY:
            quote_free = free
        elif total > 0:
            holdings[asset] = {"free": free, "used": locked, "total": total}

    _balance_cache = {
        "quote": {"free": quote_free, "used": 0, "total": quote_free},
        "holdings": holdings,
    }
    _balance_ts = _time.time()
    logger.debug(f"[WSS-Account] Balance updated: IDR Rp {quote_free:,.0f}, {len(holdings)} coins")


def _handle_order_update(data: dict):
    """Handle order execution report dari account stream."""
    sym = data.get("s", "").replace("_", "/")
    side = "BUY" if data.get("S") == "BUY" else "SELL"
    status = data.get("X", "")
    qty = float(data.get("l", 0) or 0)
    price = float(data.get("L", 0) or 0)

    if qty > 0 and status in ("TRADE", "FILLED"):
        logger.info(f"[WSS-Account] Order filled: {side} {sym} | {qty:.6f} @ Rp {price:,.0f}")


def _get_listen_token() -> str:
    """
    Ambil listen token via POST /open/v1/user-listen-token (endpoint BARU).
    Menggantikan user-data-stream yang deprecated per 30 April 2026.
    """
    global _listen_token, _listen_token_ts

    # Cache: kalau masih valid, pakai ulang
    if _listen_token and (_time.time() - _listen_token_ts) < _LISTEN_TOKEN_TTL - 60:
        return _listen_token

    try:
        data = _signed_post("/open/v1/user-listen-token", {})
        if isinstance(data, dict) and data.get("__api_error__"):
            logger.warning(f"[WSS] Gagal ambil listen token: {data.get('msg')}")
            return _listen_token  # fallback ke token lama kalau ada

        token = data.get("listenKey", data.get("token", ""))
        if token:
            _listen_token = token
            _listen_token_ts = _time.time()
            return token
    except Exception as e:
        logger.warning(f"[WSS] Listen token error: {e}")

    return _listen_token or ""


def start():
    """Mulai WebSocket threads (market + account). Non-blocking."""
    global _ws_thread, _ws_running

    if _ws_running:
        return

    try:
        import websocket  # noqa: F401
    except ImportError:
        logger.warning("[WSS] websocket-client tidak terinstall. Install: pip install websocket-client")
        return

    _ws_running = True

    # Market stream (harga real-time)
    t_market = threading.Thread(target=_start_ws_market, daemon=True, name="wss-market")
    t_market.start()

    # Account stream (balance + order updates)
    t_account = threading.Thread(target=_start_ws_account, daemon=True, name="wss-account")
    t_account.start()

    _ws_thread = t_market  # keep reference
    logger.info("[WSS] 🚀 Real-time streams started (market + account)")


def stop():
    """Stop WebSocket threads."""
    global _ws_running
    _ws_running = False
    logger.info("[WSS] Stopping real-time streams...")
