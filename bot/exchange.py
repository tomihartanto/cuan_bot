"""
CuanBot - Exchange Connection v4
Handles rate limiting, works from GitHub
"""

import ccxt
import requests
import time
from config import Config
import logging

logger = logging.getLogger("cuanbot")

_usdt_idr_rate = None
_binance_symbols = None


def get_usdt_idr_rate() -> float:
    global _usdt_idr_rate
    if _usdt_idr_rate:
        return _usdt_idr_rate
    try:
        resp = requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": "USDTIDR"}, timeout=10)
        if resp.status_code == 200:
            _usdt_idr_rate = float(resp.json()["price"])
            return _usdt_idr_rate
    except: pass
    try:
        r1 = requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": "BNBIDR"}, timeout=10)
        r2 = requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": "BNBUSDT"}, timeout=10)
        if r1.status_code == 200 and r2.status_code == 200:
            _usdt_idr_rate = float(r1.json()["price"]) / float(r2.json()["price"])
            return _usdt_idr_rate
    except: pass
    _usdt_idr_rate = 17000.0
    return _usdt_idr_rate


def _get_binance_symbols() -> set:
    global _binance_symbols
    if _binance_symbols is not None:
        return _binance_symbols
    try:
        resp = requests.get("https://api.binance.com/api/v3/exchangeInfo", timeout=15)
        if resp.status_code == 200:
            _binance_symbols = {s["symbol"] for s in resp.json().get("symbols", []) if s["status"] == "TRADING"}
            return _binance_symbols
    except: pass
    _binance_symbols = set()
    return _binance_symbols


def create_exchange() -> ccxt.Exchange:
    return ccxt.tokocrypto({
        "apiKey": Config.API_KEY,
        "secret": Config.SECRET_KEY,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })


def get_idr_pairs(exchange=None) -> list:
    pairs = [f"{s}/{Config.BASE_CURRENCY}" for s in Config.SCAN_COINS]
    logger.info(f"Using {len(pairs)} configured pairs")
    return pairs


def fetch_candles(exchange, symbol: str, timeframe: str = None, limit: int = None) -> list:
    try:
        tf = timeframe or Config.TIMEFRAME
        lim = limit or Config.CANDLE_LIMIT
        base = symbol.split("/")[0]
        rate = get_usdt_idr_rate()
        available = _get_binance_symbols()

        url = "https://api.binance.com/api/v3/klines"

        # Try quote assets in order of preference
        for quote in ["USDT", "BTC", "BNB", "ETH", "IDR"]:
            sym = f"{base}{quote}"
            if available and sym not in available:
                continue
            try:
                resp = requests.get(url, params={"symbol": sym, "interval": tf, "limit": lim}, timeout=15)
                if resp.status_code == 429:
                    logger.warning("Binance rate limit hit, waiting...")
                    time.sleep(2)
                    resp = requests.get(url, params={"symbol": sym, "interval": tf, "limit": lim}, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list) and len(data) > 0:
                        if quote == "IDR":
                            multiplier = 1
                        elif quote == "USDT":
                            multiplier = rate
                        else:
                            try:
                                qr = requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": f"{quote}USDT"}, timeout=5)
                                multiplier = float(qr.json()["price"]) * rate if qr.status_code == 200 else rate
                            except:
                                multiplier = rate
                        return [{"timestamp": c[0], "open": float(c[1]) * multiplier, "high": float(c[2]) * multiplier,
                                  "low": float(c[3]) * multiplier, "close": float(c[4]) * multiplier, "volume": float(c[5])} for c in data]
            except: continue
        return []
    except Exception as e:
        logger.warning(f"Candle error {symbol}: {e}")
        return []


def get_balance(exchange, currency=None) -> dict:
    try:
        cur = currency or Config.BASE_CURRENCY
        balance = exchange.fetch_balance()
        free = balance.get(cur, {}).get("free", 0)
        used = balance.get(cur, {}).get("used", 0)
        total = balance.get(cur, {}).get("total", 0)
        holdings = {}
        for asset, amounts in balance.items():
            if isinstance(amounts, dict) and amounts.get("total", 0) > 0:
                if asset not in ["info", "free", "used", "total"]:
                    holdings[asset] = {"free": amounts.get("free", 0), "used": amounts.get("used", 0), "total": amounts.get("total", 0)}
        return {"base": {"currency": cur, "free": free, "used": used, "total": total}, "holdings": holdings}
    except Exception as e:
        logger.error(f"Balance error: {e}")
        return {"base": {"currency": currency or Config.BASE_CURRENCY, "free": 0, "used": 0, "total": 0}, "holdings": {}}


def place_order(exchange, symbol, side, amount, price=None) -> dict:
    try:
        if Config.DRY_RUN:
            logger.info(f"[DRY RUN] {side.upper()} {amount:.8f} {symbol} @ ~Rp {price:,.0f}")
            return {"dry_run": True, "symbol": symbol, "side": side, "amount": amount, "price": price, "status": "simulated"}
        if side == "buy":
            order = exchange.create_market_buy_order(symbol, amount)
        else:
            order = exchange.create_market_sell_order(symbol, amount)
        logger.info(f"Order: {side.upper()} {amount:.8f} {symbol} | ID: {order.get('id')}")
        return {"dry_run": False, "id": order.get("id"), "symbol": symbol, "side": side, "amount": amount,
                "price": order.get("price", price), "status": order.get("status")}
    except Exception as e:
        logger.error(f"Order error: {e}")
        return {"error": str(e), "symbol": symbol, "side": side}
