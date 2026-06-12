"""
CuanBot - Exchange Connection & Market Data v3
Fully works from GitHub - Binance for data, Tokocrypto for trade
"""

import ccxt
import requests
from config import Config
import logging

logger = logging.getLogger("cuanbot")

_usdt_idr_rate = None


def get_usdt_idr_rate() -> float:
    global _usdt_idr_rate
    if _usdt_idr_rate:
        return _usdt_idr_rate
    # Try Binance IDR pair first
    try:
        resp = requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": "USDTIDR"}, timeout=10)
        if resp.status_code == 200:
            _usdt_idr_rate = float(resp.json()["price"])
            return _usdt_idr_rate
    except:
        pass
    # Fallback: estimate from BNB/IDR and BNB/USDT
    try:
        bnb_idr = requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": "BNBIDR"}, timeout=10)
        bnb_usdt = requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": "BNBUSDT"}, timeout=10)
        if bnb_idr.status_code == 200 and bnb_usdt.status_code == 200:
            _usdt_idr_rate = float(bnb_idr.json()["price"]) / float(bnb_usdt.json()["price"])
            return _usdt_idr_rate
    except:
        pass
    _usdt_idr_rate = 17000.0
    return _usdt_idr_rate


def create_exchange() -> ccxt.Exchange:
    exchange = ccxt.tokocrypto({
        "apiKey": Config.API_KEY,
        "secret": Config.SECRET_KEY,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    return exchange


def get_idr_pairs(exchange: ccxt.Exchange = None) -> list:
    """Get tradeable pairs. Works even if Tokocrypto is blocked."""
    pairs = []
    for symbol in Config.SCAN_COINS:
        pairs.append(f"{symbol}/{Config.BASE_CURRENCY}")
    logger.info(f"Using {len(pairs)} configured pairs")
    return pairs


def fetch_candles(exchange: ccxt.Exchange, symbol: str, timeframe: str = None, limit: int = None) -> list:
    try:
        tf = timeframe or Config.TIMEFRAME
        lim = limit or Config.CANDLE_LIMIT
        base = symbol.split("/")[0]
        rate = get_usdt_idr_rate()

        # Try Binance USDT pair (most reliable)
        url = "https://api.binance.com/api/v3/klines"
        for quote in ["USDT", "BTC", "BNB", "ETH"]:
            binance_symbol = f"{base}{quote}"
            try:
                resp = requests.get(url, params={"symbol": binance_symbol, "interval": tf, "limit": lim}, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list) and len(data) > 0:
                        if quote == "USDT":
                            multiplier = rate
                        else:
                            # Get quote/USDT rate
                            try:
                                qr = requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": f"{quote}USDT"}, timeout=5)
                                multiplier = float(qr.json()["price"]) * rate if qr.status_code == 200 else rate
                            except:
                                multiplier = rate
                        return [{"timestamp": c[0], "open": float(c[1]) * multiplier, "high": float(c[2]) * multiplier,
                                  "low": float(c[3]) * multiplier, "close": float(c[4]) * multiplier, "volume": float(c[5])} for c in data]
            except:
                continue
        return []
    except Exception as e:
        logger.warning(f"Error fetching candles for {symbol}: {e}")
        return []


def get_balance(exchange: ccxt.Exchange, currency: str = None) -> dict:
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


def place_order(exchange: ccxt.Exchange, symbol: str, side: str, amount: float, price: float = None) -> dict:
    try:
        if Config.DRY_RUN:
            logger.info(f"[DRY RUN] {side.upper()} {amount:.8f} {symbol} @ ~Rp {price:,.0f}")
            return {"dry_run": True, "symbol": symbol, "side": side, "amount": amount, "price": price, "status": "simulated"}
        if side == "buy":
            order = exchange.create_market_buy_order(symbol, amount)
        else:
            order = exchange.create_market_sell_order(symbol, amount)
        logger.info(f"Order placed: {side.upper()} {amount:.8f} {symbol} | ID: {order.get('id')}")
        return {"dry_run": False, "id": order.get("id"), "symbol": symbol, "side": side, "amount": amount,
                "price": order.get("price", price), "status": order.get("status")}
    except Exception as e:
        logger.error(f"Order error: {e}")
        return {"error": str(e), "symbol": symbol, "side": side}
