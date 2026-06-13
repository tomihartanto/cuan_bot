"""
CuanBot - Configuration v4
Dikurasi untuk scalping IDR di Tokocrypto dengan modal kecil.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── Credentials ──────────────────────────────────────────────────
    API_KEY    = os.getenv("TOKOCRYPTO_API_KEY", "")
    SECRET_KEY = os.getenv("TOKOCRYPTO_SECRET_KEY", "")

    # ── Mode ──────────────────────────────────────────────────────────
    DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

    # ── Modal & Compound ──────────────────────────────────────────────
    BASE_CURRENCY        = os.getenv("BASE_CURRENCY", "IDR")
    INITIAL_TRADE_AMOUNT = float(os.getenv("INITIAL_TRADE_AMOUNT", "11000"))  # Min order Tokocrypto ~11k
    MAX_TRADE_AMOUNT     = float(os.getenv("MAX_TRADE_AMOUNT", "50000"))
    AUTO_COMPOUND        = os.getenv("AUTO_COMPOUND", "true").lower() == "true"
    MIN_ORDER_IDR        = float(os.getenv("MIN_ORDER_IDR", "11000"))  # Minimum notional Tokocrypto

    # ── Risk & Profit ─────────────────────────────────────────────────
    TAKE_PROFIT_PERCENT  = float(os.getenv("TAKE_PROFIT_PERCENT", "1.8"))   # 1.8% TP
    STOP_LOSS_PERCENT    = float(os.getenv("STOP_LOSS_PERCENT", "1.2"))     # 1.2% SL → R:R = 1:1.5
    MAX_TRADES_PER_DAY   = int(os.getenv("MAX_TRADES_PER_DAY", "10"))
    COOLDOWN_MINUTES     = int(os.getenv("COOLDOWN_MINUTES", "10"))
    MAX_OPEN_POSITIONS   = int(os.getenv("MAX_OPEN_POSITIONS", "1"))        # 1 posisi saja (modal kecil)
    POSITION_TIMEOUT_HOURS = float(os.getenv("POSITION_TIMEOUT_HOURS", "6"))  # Auto-sell kalau nyangkut 6 jam

    # ── Trailing Stop ─────────────────────────────────────────────────
    TRAILING_STOP_ENABLED = os.getenv("TRAILING_STOP_ENABLED", "true").lower() == "true"
    TRAILING_PERCENT      = float(os.getenv("TRAILING_PERCENT", "0.5"))     # Trailing 0.5% dari high
    TRAILING_ACTIVATION   = float(os.getenv("TRAILING_ACTIVATION", "0.8"))  # Aktif setelah profit 0.8%

    # ── Scoring ───────────────────────────────────────────────────────
    MIN_SCORE_TO_BUY  = int(os.getenv("MIN_SCORE_TO_BUY", "60"))
    MIN_SCORE_TO_HOLD = int(os.getenv("MIN_SCORE_TO_HOLD", "38"))

    # ── Emergency Stop ────────────────────────────────────────────────
    EMERGENCY_STOP_LOSSES = int(os.getenv("EMERGENCY_STOP_LOSSES", "3"))
    EMERGENCY_PAUSE_HOURS = float(os.getenv("EMERGENCY_PAUSE_HOURS", "2"))

    # ── Coin List (dikurasi: hanya pair IDR yang ada di Tokocrypto) ───
    # Diprioritaskan: volatile, likuid, harga tidak terlalu tinggi
    SCAN_COINS = [
        # Tier 1: Pasti ada, sangat likuid
        "BTC", "ETH", "BNB", "XRP", "SOL",
        # Tier 2: Harga murah, cocok untuk modal kecil
        "ADA", "DOGE", "SHIB", "TRX", "NEAR",
        # Tier 3: Volatile, potensi profit cepat
        "AVAX", "DOT", "LINK", "UNI", "ATOM",
        # Tier 4: Altcoin likuid di Tokocrypto
        "LTC", "MATIC", "OP", "ARB", "HBAR",
        # Tier 5: Meme & volatile (high risk high reward)
        "FLOKI", "PEPE", "SUI", "TON", "SAND",
    ]

    # ── Technical Indicators ──────────────────────────────────────────
    RSI_PERIOD      = 14
    BB_PERIOD       = 20
    BB_STD          = 2.0
    MACD_FAST       = 12
    MACD_SLOW       = 26
    MACD_SIGNAL     = 9
    VOLUME_MA_PERIOD = 20
    TIMEFRAME       = "5m"
    CANDLE_LIMIT    = 100
    TIMEFRAMES      = ["5m", "15m", "1h"]
    TIMEFRAME_WEIGHTS = {"5m": 0.5, "15m": 0.3, "1h": 0.2}

    # ── Telegram ──────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
    NOTIFY_TRADES = os.getenv("NOTIFY_TRADES", "true").lower() == "true"
    NOTIFY_SCAN   = os.getenv("NOTIFY_SCAN", "false").lower() == "true"

    # ── State File ────────────────────────────────────────────────────
    STATE_FILE = os.getenv("STATE_FILE", "state.json")

    @classmethod
    def get_trade_amount(cls) -> float:
        """Hitung trade amount dengan compound profit."""
        try:
            import json
            if os.path.exists(cls.STATE_FILE):
                with open(cls.STATE_FILE, "r", encoding="utf-8-sig") as f:
                    state = json.load(f)
                    if cls.AUTO_COMPOUND:
                        amount = cls.INITIAL_TRADE_AMOUNT + state.get("compound_profit", 0)
                        return min(amount, cls.MAX_TRADE_AMOUNT)
        except Exception:
            pass
        return cls.INITIAL_TRADE_AMOUNT
