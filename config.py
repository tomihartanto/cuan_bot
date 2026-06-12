"""
CuanBot - Smart Crypto Investment Manager
Configuration module
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # === Tokocrypto API ===
    API_KEY = os.getenv("TOKOCRYPTO_API_KEY", "")
    SECRET_KEY = os.getenv("TOKOCRYPTO_SECRET_KEY", "")

    # === Trading ===
    BASE_CURRENCY = os.getenv("BASE_CURRENCY", "IDR")
    TRADE_AMOUNT_IDR = float(os.getenv("TRADE_AMOUNT_IDR", "10000"))
    DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

    # === Strategy - AGGRESSIVE MODE ===
    MIN_SCORE_TO_BUY = int(os.getenv("MIN_SCORE_TO_BUY", "58"))
    MIN_SCORE_TO_HOLD = int(os.getenv("MIN_SCORE_TO_HOLD", "38"))

    # === Risk Management - FAST PROFIT ===
    MAX_TRADES_PER_DAY = int(os.getenv("MAX_TRADES_PER_DAY", "10"))
    STOP_LOSS_PERCENT = float(os.getenv("STOP_LOSS_PERCENT", "1.0"))
    TAKE_PROFIT_PERCENT = float(os.getenv("TAKE_PROFIT_PERCENT", "1.2"))
    COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "10"))

    # === Scanner ===
    SCAN_COINS = [
        "BTC", "ETH", "BNB", "SOL", "XRP",
        "ADA", "DOGE", "DOT", "AVAX", "ARB",
        "SHIB", "LINK", "UNI", "ATOM", "LTC",
        "NEAR", "FTM", "ALGO", "SAND", "AXS",
        "APE", "DYDX", "OP", "SUI", "TON",
        "WIF", "WLD", "FLOKI", "ONDO", "HBAR",
        "DOGS", "POL", "TKO", "USDC", "USDT",
        "MANTA", "GOAT", "SCR", "SPX", "VIRTUAL",
    ]

    # === State ===
    STATE_FILE = os.getenv("STATE_FILE", "state.json")

    # === Telegram Notifications ===
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    NOTIFY_TRADES = os.getenv("NOTIFY_TRADES", "true").lower() == "true"
    NOTIFY_SCAN = os.getenv("NOTIFY_SCAN", "false").lower() == "true"

    # === Indicator Periods ===
    RSI_PERIOD = 14
    RSI_OVERSOLD = 30
    RSI_OVERBOUGHT = 70
    BB_PERIOD = 20
    BB_STD = 2.0
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9
    VOLUME_MA_PERIOD = 20

    # === Candles ===
    TIMEFRAME = "5m"
    CANDLE_LIMIT = 100
