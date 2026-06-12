# 🤖 CuanBot - Smart Crypto Investment Manager

Bot trading otomatis untuk Tokocrypto. Scan 25+ coin, analisa teknikal, dan auto-trade — semua gratis, tanpa laptop nyala.

## 🏗️ Arsitektur

```
GitHub Actions (jalan tiap 5 menit, 24/7, gratis)
    ↓
Scan 25+ coin IDR di Tokocrypto
    ↓
Analisa: RSI + MACD + Bollinger Band + Volume
    ↓
Scoring 0-100 → BUY / HOLD / SELL
    ↓
Auto-trade (kalau sinyal bagus)
    ↓
Notifikasi ke Telegram
```

## 📁 Struktur

```
cuan-bot/
├── main.py                  # Entry point
├── config.py                # Konfigurasi
├── requirements.txt         # Dependencies
├── .env.example             # Template env (copy jadi .env)
├── state.json               # State (auto-updated)
├── bot/
│   ├── indicators.py        # RSI, MACD, Bollinger, Volume
│   ├── scanner.py           # Scoring engine
│   ├── exchange.py          # Tokocrypto API (CCXT)
│   ├── risk.py              # Risk management
│   └── notifier.py          # Telegram notifikasi
├── .github/workflows/
│   └── trade.yml            # GitHub Actions (auto tiap 5 menit)
└── logs/                    # Log harian
```

## 🚀 Setup

### 1. Test di PC (Langkah Pertama!)

```bash
cd D:\project\pribadi\cuan-bot
pip install -r requirements.txt

# Copy dan isi API key
copy .env.example .env
# Edit .env, isi TOKOCRYPTO_API_KEY dan TOKOCRYPTO_SECRET_KEY

# Test scan (tanpa trade)
python main.py --scan-only --dry-run

# Test dengan simulasi trade
python main.py --dry-run

# KALAU SUDAH YAKIN: live trading
python main.py --live
```

### 2. Deploy ke GitHub (Jalan 24/7 Tanpa Laptop)

```bash
# Buat repo di GitHub, lalu:
cd D:\project\pribadi\cuan-bot
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/USERNAME/cuan-bot.git
git push -u origin main

# Tambah secrets di GitHub repo:
# Settings → Secrets and variables → Actions → New repository secret
# - TOKOCRYPTO_API_KEY
# - TOKOCRYPTO_SECRET_KEY
# - TELEGRAM_BOT_TOKEN (opsional)
# - TELEGRAM_CHAT_ID (opsional)
```

### 3. Setup Telegram Notifikasi (Opsional tapi Direkomendasikan)

1. Chat dengan [@BotFather](https://t.me/BotFather) di Telegram
2. `/newbot` → kasih nama → dapat token
3. Chat dengan [@userinfobot](https://t.me/userinfobot) → dapat chat ID kamu
4. Isi `TELEGRAM_BOT_TOKEN` dan `TELEGRAM_CHAT_ID` di secrets

## ⚙️ Konfigurasi

Edit `.env` atau secrets:

| Setting | Default | Keterangan |
|---|---|---|
| DRY_RUN | true | true = simulasi, false = real trading |
| TRADE_AMOUNT_IDR | 10000 | Modal per trade (Rp) |
| MAX_TRADES_PER_DAY | 5 | Max trade per hari |
| STOP_LOSS_PERCENT | 2 | Auto sell kalau rugi 2% |
| TAKE_PROFIT_PERCENT | 3 | Auto sell kalau profit 3% |
| COOLDOWN_MINUTES | 30 | Jeda antar trade |
| MIN_SCORE_TO_BUY | 68 | Min skor untuk beli (0-100) |

## 📊 Cara Kerja Scoring

Setiap coin di-scan dan di-score 0-100:

| Indikator | Max Skor | Logika |
|---|---|---|
| RSI | 25 | < 30 = oversold = buy signal |
| MACD | 25 | Bullish crossover = buy signal |
| Bollinger | 25 | Harga di lower band = buy signal |
| Volume | 25 | Volume tinggi + oversold = strong buy |

- **Skor ≥ 68** → BUY
- **Skor 36-67** → HOLD
- **Skor ≤ 35** → SELL

## ⚠️ DISCLAIMER

Bot ini adalah ALAT BANTU. Tidak ada jaminan profit.
- Mulai dengan DRY_RUN = true dulu
- Monitor hasil minimal 1 minggu sebelum live
- Trading crypto = risiko tinggi
- Jangan pakai modal yang tidak siap hilang
