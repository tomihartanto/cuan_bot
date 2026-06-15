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
    ZAI_API_KEY = os.getenv("ZAI_API_KEY", "")
    ZAI_API_URL = os.getenv("ZAI_API_URL", "https://api.z.ai/api/paas/v4/")

    # ── Mode ──────────────────────────────────────────────────────────
    DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

    # ── Modal & Dynamic Capital Deployment ────────────────────────────
    BASE_CURRENCY          = "IDR"  # Tokocrypto IDR-only
    INITIAL_TRADE_AMOUNT   = float(os.getenv("INITIAL_TRADE_AMOUNT", "10000"))  # Fallback / display
    MIN_ORDER_IDR          = float(os.getenv("MIN_ORDER_IDR", "10000"))  # Min notional Tokocrypto (~10k IDR)
    WORKING_CAPITAL_PCT    = float(os.getenv("WORKING_CAPITAL_PCT", "0.85"))  # 85% saldo diputar, 15% buffer
    MIN_CAPITAL_PER_POSITION = float(os.getenv("MIN_CAPITAL_PER_POSITION", "50000"))  # Modal ideal per posisi
    AUTO_COMPOUND          = os.getenv("AUTO_COMPOUND", "true").lower() == "true"

    # ── Risk & Profit ─────────────────────────────────────────────────
    TAKE_PROFIT_PERCENT  = float(os.getenv("TAKE_PROFIT_PERCENT", "2.5"))   # 2.5% TP (fee-aware)
    STOP_LOSS_PERCENT    = float(os.getenv("STOP_LOSS_PERCENT", "1.8"))     # 1.8% SL (fee-aware)
    MAX_TRADES_PER_DAY   = int(os.getenv("MAX_TRADES_PER_DAY", "10"))
    COOLDOWN_MINUTES     = int(os.getenv("COOLDOWN_MINUTES", "5"))
    MAX_OPEN_POSITIONS   = int(os.getenv("MAX_OPEN_POSITIONS", "5"))        # Cap maksimal posisi paralel
    POSITION_TIMEOUT_HOURS = float(os.getenv("POSITION_TIMEOUT_HOURS", "6"))  # Auto-sell kalau nyangkut 6 jam

    # ── Safety Nets ───────────────────────────────────────────────────
    DAILY_LOSS_LIMIT_PCT   = float(os.getenv("DAILY_LOSS_LIMIT_PCT", "3.0"))   # Stop hari itu kalau rugi >= 3% saldo awal hari
    WIN_RATE_GUARD_TRADES = int(os.getenv("WIN_RATE_GUARD_TRADES", "20"))      # Cek win rate dari N trade terakhir
    WIN_RATE_GUARD_MIN    = float(os.getenv("WIN_RATE_GUARD_MIN", "45"))       # Pause kalau win rate < 45%

    # ── Trailing Stop ─────────────────────────────────────────────────
    TRAILING_STOP_ENABLED = os.getenv("TRAILING_STOP_ENABLED", "true").lower() == "true"
    TRAILING_PERCENT      = float(os.getenv("TRAILING_PERCENT", "0.5"))     # Trailing 0.5% dari high
    TRAILING_ACTIVATION   = float(os.getenv("TRAILING_ACTIVATION", "0.8"))  # Aktif setelah profit 0.8%

    # ── Scoring ───────────────────────────────────────────────────────
    MIN_SCORE_TO_BUY  = int(os.getenv("MIN_SCORE_TO_BUY", "60"))
    MIN_SCORE_TO_HOLD = int(os.getenv("MIN_SCORE_TO_HOLD", "38"))

    # ── Liquidity Filter ──────────────────────────────────────────────
    # Hanya scan pair dengan volume 24 jam >= threshold (IDR).
    # Pair illiquid di-skip karena spread-nya gede (auto rugi).
    MIN_VOLUME_IDR = float(os.getenv("MIN_VOLUME_IDR", "50000000"))  # Rp 50 jt / 24 jam

    # ── Emergency Stop ────────────────────────────────────────────────
    EMERGENCY_STOP_LOSSES = int(os.getenv("EMERGENCY_STOP_LOSSES", "3"))
    EMERGENCY_PAUSE_HOURS = float(os.getenv("EMERGENCY_PAUSE_HOURS", "2"))

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
    NOTIFY_SCAN   = os.getenv("NOTIFY_SCAN", "false").lower() == "true"

    # ── State File ────────────────────────────────────────────────────
    STATE_FILE = os.getenv("STATE_FILE", "state.json")

    @classmethod
    def get_working_capital(cls, available_balance: float) -> float:
        """Total modal yang diputar = WORKING_CAPITAL_PCT × saldo."""
        return available_balance * cls.WORKING_CAPITAL_PCT

    @classmethod
    def get_max_positions(cls, available_balance: float) -> int:
        """Hitung jumlah posisi paralel dinamis berdasarkan saldo."""
        if available_balance < cls.MIN_ORDER_IDR:
            return 0
        working = cls.get_working_capital(available_balance)
        n = max(1, int(working / cls.MIN_CAPITAL_PER_POSITION))
        return min(n, cls.MAX_OPEN_POSITIONS)

    @classmethod
    def get_trade_amount(cls, available_balance: float = None) -> float:
        """
        Modal per posisi = working_capital / num_positions.
        Berbasis saldo riil, otomatis scale naik/turun.
        """
        if not available_balance or available_balance <= 0:
            return cls.INITIAL_TRADE_AMOUNT

        n = cls.get_max_positions(available_balance)
        if n == 0:
            return 0.0

        working   = cls.get_working_capital(available_balance)
        per_trade = working / n

        # Honor min order kalau saldo cukup
        if per_trade < cls.MIN_ORDER_IDR and available_balance >= cls.MIN_ORDER_IDR:
            per_trade = cls.MIN_ORDER_IDR

        # Buffer dust: saldo besar sisain 2%, saldo kecil boleh pakai full
        max_per_trade = available_balance * 0.98 if available_balance >= 50000 else available_balance
        return min(per_trade, max_per_trade)
