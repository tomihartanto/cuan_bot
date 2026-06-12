"""
CuanBot - Smart Crypto Investment Manager
Configuration module
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    API_KEY = os.getenv("TOKOCRYPTO_API_KEY", "")
    SECRET_KEY = os.getenv("TOKOCRYPTO_SECRET_KEY", "")
    BASE_CURRENCY = os.getenv("BASE_CURRENCY", "IDR")
    INITIAL_TRADE_AMOUNT = float(os.getenv("INITIAL_TRADE_AMOUNT", "10000"))
    DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
    AUTO_COMPOUND = os.getenv("AUTO_COMPOUND", "true").lower() == "true"
    MAX_TRADE_AMOUNT = float(os.getenv("MAX_TRADE_AMOUNT", "50000"))
    MIN_SCORE_TO_BUY = int(os.getenv("MIN_SCORE_TO_BUY", "63"))       # Selektif tapi tidak terlalu ketat
    MIN_SCORE_TO_HOLD = int(os.getenv("MIN_SCORE_TO_HOLD", "38"))
    MAX_TRADES_PER_DAY = int(os.getenv("MAX_TRADES_PER_DAY", "12"))    # Scalping: lebih banyak peluang
    STOP_LOSS_PERCENT = float(os.getenv("STOP_LOSS_PERCENT", "1.2"))   # Ketat: proteksi modal
    TAKE_PROFIT_PERCENT = float(os.getenv("TAKE_PROFIT_PERCENT", "1.8")) # Cepat ambil profit
    COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "8"))          # Lebih agresif
    TRAILING_STOP_ENABLED = os.getenv("TRAILING_STOP_ENABLED", "true").lower() == "true"
    TRAILING_PERCENT = float(os.getenv("TRAILING_PERCENT", "0.4"))      # Trailing lebih ketat
    TRAILING_ACTIVATION = float(os.getenv("TRAILING_ACTIVATION", "0.8")) # Aktif setelah profit 0.8%
    # Emergency stop: pause trading N jam kalau rugi berturut-turut
    EMERGENCY_STOP_LOSSES = int(os.getenv("EMERGENCY_STOP_LOSSES", "3"))
    EMERGENCY_PAUSE_HOURS = float(os.getenv("EMERGENCY_PAUSE_HOURS", "2"))

    SCAN_COINS = [
        "BTC", "ETH", "BNB", "SOL", "XRP",
        "ADA", "DOGE", "AVAX", "ARB", "DOT",
        "LINK", "UNI", "ATOM", "LTC", "NEAR",
        "SUI", "TON", "WIF", "WLD", "FLOKI",
        "ONDO", "HBAR", "SHIB", "APE", "OP",
    ]

    STATE_FILE = os.getenv("STATE_FILE", "state.json")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    NOTIFY_TRADES = os.getenv("NOTIFY_TRADES", "true").lower() == "true"
    NOTIFY_SCAN = os.getenv("NOTIFY_SCAN", "false").lower() == "true"
    RSI_PERIOD = 14
    BB_PERIOD = 20
    BB_STD = 2.0
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9
    VOLUME_MA_PERIOD = 20
    TIMEFRAME = "5m"
    CANDLE_LIMIT = 100
    TIMEFRAMES = ["5m", "15m", "1h"]
    TIMEFRAME_WEIGHTS = {"5m": 0.5, "15m": 0.3, "1h": 0.2}

    @classmethod
    def get_trade_amount(cls) -> float:
        try:
            import json
            if os.path.exists(cls.STATE_FILE):
                with open(cls.STATE_FILE, "r", encoding="utf-8-sig") as f:
                    state = json.load(f)
                    if cls.AUTO_COMPOUND:
                        amount = cls.INITIAL_TRADE_AMOUNT + state.get("compound_profit", 0)
                        return min(amount, cls.MAX_TRADE_AMOUNT)
        except: pass
        return cls.INITIAL_TRADE_AMOUNT
