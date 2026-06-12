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

    # === Strategy ===
    MIN_SCORE_TO_BUY = int(os.getenv("MIN_SCORE_TO_BUY", "68"))
    MIN_SCORE_TO_HOLD = int(os.getenv("MIN_SCORE_TO_HOLD", "35"))

    # === Risk Management ===
    MAX_TRADES_PER_DAY = int(os.getenv("MAX_TRADES_PER_DAY", "5"))
    STOP_LOSS_PERCENT = float(os.getenv("STOP_LOSS_PERCENT", "2.0"))
    TAKE_PROFIT_PERCENT = float(os.getenv("TAKE_PROFIT_PERCENT", "3.0"))
    COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "30"))

    # === Scanner ===
    SCAN_COINS = [
        "BTC", "ETH", "BNB", "SOL", "XRP",
        "ADA", "DOGE", "DOT", "MATIC", "AVAX",
        "SHIB", "LINK", "UNI", "ATOM", "LTC",
        "NEAR", "FTM", "ALGO", "MANA", "SAND",
        "AXS", "APE", "DYDX", "OP", "ARB",
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
    TIMEFRAME = "15m"
    CANDLE_LIMIT = 100
