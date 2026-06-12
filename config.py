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
    INITIAL_TRADE_AMOUNT = float(os.getenv("INITIAL_TRADE_AMOUNT", "10000"))
    DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

    # === Auto Compound ===
    AUTO_COMPOUND = os.getenv("AUTO_COMPOUND", "true").lower() == "true"
    MAX_TRADE_AMOUNT = float(os.getenv("MAX_TRADE_AMOUNT", "50000"))

    # === Strategy ===
    MIN_SCORE_TO_BUY = int(os.getenv("MIN_SCORE_TO_BUY", "60"))
    MIN_SCORE_TO_HOLD = int(os.getenv("MIN_SCORE_TO_HOLD", "38"))

    # === Risk Management ===
    MAX_TRADES_PER_DAY = int(os.getenv("MAX_TRADES_PER_DAY", "10"))
    STOP_LOSS_PERCENT = float(os.getenv("STOP_LOSS_PERCENT", "1.2"))
    TAKE_PROFIT_PERCENT = float(os.getenv("TAKE_PROFIT_PERCENT", "1.5"))
    COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "10"))

    # === Trailing Stop ===
    TRAILING_STOP_ENABLED = os.getenv("TRAILING_STOP_ENABLED", "true").lower() == "true"
    TRAILING_PERCENT = float(os.getenv("TRAILING_PERCENT", "0.5"))
    TRAILING_ACTIVATION = float(os.getenv("TRAILING_ACTIVATION", "0.5"))

    # === Multi-Timeframe ===
    TIMEFRAMES = ["5m", "15m", "1h"]
    TIMEFRAME_WEIGHTS = {"5m": 0.5, "15m": 0.3, "1h": 0.2}

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
        "ALCH", "ASTER", "CARV", "DRX", "JELLYJELLY",
        "MOODENG", "NBT", "RENDER", "SKYA", "SOON",
        "TAO", "U", "VELO", "ZIL",
    ]

    # === State ===
    STATE_FILE = os.getenv("STATE_FILE", "state.json")

    # === Telegram ===
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    NOTIFY_TRADES = os.getenv("NOTIFY_TRADES", "true").lower() == "true"
    NOTIFY_SCAN = os.getenv("NOTIFY_SCAN", "false").lower() == "true"

    # === Indicator Periods ===
    RSI_PERIOD = 14
    BB_PERIOD = 20
    BB_STD = 2.0
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9
    VOLUME_MA_PERIOD = 20

    # === Candles ===
    TIMEFRAME = "5m"
    CANDLE_LIMIT = 100

    @classmethod
    def get_trade_amount(cls) -> float:
        """Get current trade amount (with compound if enabled)."""
        try:
            import json
            if os.path.exists(cls.STATE_FILE):
                with open(cls.STATE_FILE, "r") as f:
                    state = json.load(f)
                    if cls.AUTO_COMPOUND:
                        amount = cls.INITIAL_TRADE_AMOUNT + state.get("compound_profit", 0)
                        return min(amount, cls.MAX_TRADE_AMOUNT)
        except:
            pass
        return cls.INITIAL_TRADE_AMOUNT
