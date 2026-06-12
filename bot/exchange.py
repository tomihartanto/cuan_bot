"""
CuanBot - Exchange Connection & Market Data v2
Uses Binance for market data (works from GitHub),
Tokocrypto only for trade execution
"""

import ccxt
import requests
from config import Config
import logging

logger = logging.getLogger("cuanbot")

_usdt_idr_rate = None
_tokocrypto_blocked = False


def get_usdt_idr_rate() -> float:
    global _usdt_idr_rate
    if _usdt_idr_rate:
        return _usdt_idr_rate
    try:
        url = "https://api.binance.com/api/v3/ticker/price"
        resp = requests.get(url, params={"symbol": "USDTIDR"}, timeout=10)
        if resp.status_code == 200:
            _usdt_idr_rate = float(resp.json()["price"])
            return _usdt_idr_rate
    except:
        pass
    try:
        resp = requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": "USDTTRY"}, timeout=10)
        if resp.status_code == 200:
            _usdt_idr_rate = 17000.0
            return _usdt_idr_rate
    except:
        pass
    return 17000.0


def create_exchange() -> ccxt.Exchange:
    global _tokocrypto_blocked
    exchange = ccxt.tokocrypto({
        "apiKey": Config.API_KEY,
        "secret": Config.SECRET_KEY,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    try:
        exchange.load_markets()
    except Exception as e:
        if "451" in str(e) or "not-support" in str(e):
            logger.warning("Tokocrypto API blocked from this IP. Using Binance for data, Tokocrypto for trade only.")
            _tokocrypto_blocked = True
            try:
                exchange.markets = {}
                resp = requests.get("https://api.binance.com/api/v3/exchangeInfo", timeout=15)
                if resp.status_code == 200:
                    for s in resp.json().get("symbols", []):
                        if s["quoteAsset"] == "IDR" and s["status"] == "TRADING":
                            pair = f"{s['baseAsset']}/IDR"
                            exchange.markets[pair] = {"id": f"{s['baseAsset']}_IDR", "symbol": pair, "base": s["baseAsset"], "quote": "IDR"}
            except:
                pass
        else:
            raise
    return exchange


def get_idr_pairs(exchange: ccxt.Exchange) -> list:
    try:
        if not exchange.markets:
            exchange.load_markets()
        pairs = []
        for symbol in Config.SCAN_COINS:
            pair = f"{symbol}/{Config.BASE_CURRENCY}"
            if pair in exchange.markets:
                pairs.append(pair)
        logger.info(f"Found {len(pairs)} tradeable pairs")
        return pairs
    except Exception as e:
        logger.error(f"Error loading markets: {e}")
        # Fallback: return all configured pairs
        return [f"{s}/{Config.BASE_CURRENCY}" for s in Config.SCAN_COINS]


def fetch_candles(exchange: ccxt.Exchange, symbol: str, timeframe: str = None, limit: int = None) -> list:
    try:
        tf = timeframe or Config.TIMEFRAME
        lim = limit or Config.CANDLE_LIMIT
        base = symbol.split("/")[0]

        # Always use Binance for candle data
        binance_symbol = f"{base}USDT"
        rate = get_usdt_idr_rate()

        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": binance_symbol, "interval": tf, "limit": lim}
        resp = requests.get(url, params=params, timeout=15)

        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return [{"timestamp": c[0], "open": float(c[1]) * rate, "high": float(c[2]) * rate,
                          "low": float(c[3]) * rate, "close": float(c[4]) * rate, "volume": float(c[5])} for c in data]

        # Fallback: try Binance with IDR pairs directly
        try:
            params2 = {"symbol": f"{base}IDR", "interval": tf, "limit": lim}
            resp2 = requests.get(url, params=params2, timeout=15)
            if resp2.status_code == 200:
                data2 = resp2.json()
                if isinstance(data2, list) and len(data2) > 0:
                    return [{"timestamp": c[0], "open": float(c[1]), "high": float(c[2]),
                              "low": float(c[3]), "close": float(c[4]), "volume": float(c[5])} for c in data2]
        except:
            pass

        return []
    except Exception as e:
        logger.warning(f"Error fetching candles for {symbol}: {e}")
        return []


def get_balance(exchange: ccxt.Exchange, currency: str = None) -> dict:
    global _tokocrypto_blocked
    if _tokocrypto_blocked:
        try:
            balance = exchange.fetch_balance()
            cur = currency or Config.BASE_CURRENCY
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
            logger.info(f"[DRY RUN] {side.upper()} {amount} {symbol} @ ~{price}")
            return {"dry_run": True, "symbol": symbol, "side": side, "amount": amount, "price": price, "status": "simulated"}
        if side == "buy":
            order = exchange.create_market_buy_order(symbol, amount)
        else:
            order = exchange.create_market_sell_order(symbol, amount)
        logger.info(f"Order placed: {side.upper()} {amount} {symbol} | ID: {order.get('id')}")
        return {"dry_run": False, "id": order.get("id"), "symbol": symbol, "side": side, "amount": amount, "price": order.get("price", price), "status": order.get("status")}
    except Exception as e:
        logger.error(f"Order error: {e}")
        return {"error": str(e), "symbol": symbol, "side": side}
