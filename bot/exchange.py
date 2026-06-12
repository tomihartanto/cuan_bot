"""
CuanBot - Exchange Connection & Market Data
Uses Tokocrypto for trading + prices, Binance for candle data
"""

import ccxt
import requests
from config import Config
import logging

logger = logging.getLogger("cuanbot")

# Cache USDT/IDR rate
_usdt_idr_rate = None


def get_usdt_idr_rate() -> float:
    """Get current USDT/IDR conversion rate."""
    global _usdt_idr_rate
    if _usdt_idr_rate:
        return _usdt_idr_rate
    try:
        # Try Tokocrypto first
        url = "https://www.tokocrypto.com/open/v1/market/ticker?symbol=USDT_IDR"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            ticker_data = data.get("data", {})
            if isinstance(ticker_data, dict):
                _usdt_idr_rate = float(ticker_data.get("last", 0)) or float(ticker_data.get("c", 0))
            elif isinstance(ticker_data, list) and len(ticker_data) > 0:
                _usdt_idr_rate = float(ticker_data[0].get("last", 0)) or float(ticker_data[0].get("c", 0))
            if _usdt_idr_rate:
                return _usdt_idr_rate
    except:
        pass
    # Fallback: use Tokocrypto ticker via ccxt
    try:
        ex = ccxt.tokocrypto({"enableRateLimit": True})
        t = ex.fetch_ticker("USDT/IDR")
        _usdt_idr_rate = t["last"]
        return _usdt_idr_rate
    except:
        pass
    # Last resort
    return 17000.0


def create_exchange() -> ccxt.Exchange:
    """Create Tokocrypto exchange for trading."""
    exchange = ccxt.tokocrypto({
        "apiKey": Config.API_KEY,
        "secret": Config.SECRET_KEY,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    return exchange


def get_idr_pairs(exchange: ccxt.Exchange) -> list:
    """Get all available /IDR trading pairs from Tokocrypto."""
    try:
        markets = exchange.load_markets()
        pairs = []
        for symbol in Config.SCAN_COINS:
            pair = f"{symbol}/{Config.BASE_CURRENCY}"
            if pair in markets:
                pairs.append(pair)
        logger.info(f"Found {len(pairs)} tradeable pairs")
        return pairs
    except Exception as e:
        logger.error(f"Error loading markets: {e}")
        return []


def fetch_candles(exchange: ccxt.Exchange, symbol: str, timeframe: str = None, limit: int = None) -> list:
    """Fetch OHLCV candles from Binance (USDT pairs) and convert prices to IDR."""
    try:
        tf = timeframe or Config.TIMEFRAME
        lim = limit or Config.CANDLE_LIMIT
        base = symbol.split("/")[0]
        binance_symbol = f"{base}USDT"
        rate = get_usdt_idr_rate()

        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": binance_symbol, "interval": tf, "limit": lim}
        resp = requests.get(url, params=params, timeout=15)

        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                candles = []
                for c in data:
                    candles.append({
                        "timestamp": c[0],
                        "open": float(c[1]) * rate,
                        "high": float(c[2]) * rate,
                        "low": float(c[3]) * rate,
                        "close": float(c[4]) * rate,
                        "volume": float(c[5]),
                    })
                return candles

        return []
    except Exception as e:
        logger.warning(f"Error fetching candles for {symbol}: {e}")
        return []


def get_balance(exchange: ccxt.Exchange, currency: str = None) -> dict:
    """Get account balance."""
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
        logger.error(f"Error fetching balance: {e}")
        return {"base": {"currency": currency or Config.BASE_CURRENCY, "free": 0, "used": 0, "total": 0}, "holdings": {}}


def place_order(exchange: ccxt.Exchange, symbol: str, side: str, amount: float, price: float = None) -> dict:
    """Place a buy or sell order on Tokocrypto."""
    try:
        if Config.DRY_RUN:
            logger.info(f"[DRY RUN] {side.upper()} {amount} {symbol} @ ~{price}")
            return {"dry_run": True, "symbol": symbol, "side": side, "amount": amount, "price": price, "status": "simulated"}
        if side == "buy":
            order = exchange.create_market_buy_order(symbol, amount) if not price else exchange.create_limit_buy_order(symbol, amount, price)
        else:
            order = exchange.create_market_sell_order(symbol, amount) if not price else exchange.create_limit_sell_order(symbol, amount, price)
        logger.info(f"Order placed: {side.upper()} {amount} {symbol} | ID: {order.get('id')}")
        return {"dry_run": False, "id": order.get("id"), "symbol": symbol, "side": side, "amount": amount, "price": order.get("price", price), "status": order.get("status")}
    except Exception as e:
        logger.error(f"Error placing order: {e}")
        return {"error": str(e), "symbol": symbol, "side": side}
