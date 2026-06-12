"""
CuanBot - Exchange Connection v5
Simplified Binance access - no symbol pre-check
"""

import ccxt
import requests
import time as _time
from config import Config
import logging

logger = logging.getLogger("cuanbot")

_usdt_idr_rate = None


def get_usdt_idr_rate() -> float:
    global _usdt_idr_rate
    if _usdt_idr_rate:
        return _usdt_idr_rate
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": "USDTIDR"}, timeout=10)
        if r.status_code == 200:
            _usdt_idr_rate = float(r.json()["price"])
            logger.info(f"USDT/IDR rate: {_usdt_idr_rate}")
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


def create_exchange() -> ccxt.Exchange:
    return ccxt.tokocrypto({
        "apiKey": Config.API_KEY, "secret": Config.SECRET_KEY,
        "enableRateLimit": True, "options": {"defaultType": "spot"},
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
        url = "https://api.binance.com/api/v3/klines"

        # Simple: just try BTCUSDT, ETHUSDT etc directly
        binance_sym = f"{base}USDT"
        resp = requests.get(url, params={"symbol": binance_sym, "interval": tf, "limit": lim}, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return [{"timestamp": c[0], "open": float(c[1]) * rate, "high": float(c[2]) * rate,
                          "low": float(c[3]) * rate, "close": float(c[4]) * rate, "volume": float(c[5])} for c in data]
            else:
                logger.warning(f"Binance returned 0 candles for {binance_sym}")
        else:
            logger.warning(f"Binance error {binance_sym}: {resp.status_code}")
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
