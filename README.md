# 🤖 CuanBot v4 - Smart Crypto Investment Manager

Bot trading otomatis untuk Tokocrypto. Scan 25+ coin, analisa teknikal multi-timeframe (EMA + RSI + MACD + Bollinger), filter AI (Z.ai GLM-5.2), dan auto-trade — jalan 24/7 di GitHub Actions, gratis.

## 🏗️ Arsitektur

```
GitHub Actions (tiap 5 menit, 24/7, gratis)
    ↓
PHASE 1 — Reconcile: sync state vs exchange balance
    ↓
PHASE 2 — Exit: cek posisi terbuka → TP/SL/Trailing/Timeout
    ↓
PHASE 3 — Scan: 25 coin, 3 timeframe (5m, 15m, 1h)
    ↓
PHASE 4 — Entry: beli coin terbaik kalau score ≥ 60
    ↓
PHASE 5 — Save state & notif Telegram
```

## 📁 Struktur

```
cuan-bot/
├── main.py                  # Entry point + state machine
├── config.py                # Konfigurasi
├── requirements.txt         # Dependencies
├── .env                     # Secrets (lokal, gitignored)
├── state.json               # State (auto-updated)
├── bot/
│   ├── indicators.py        # RSI, MACD, Bollinger, Volume, EMA 9/21
│   ├── scanner.py           # Scoring engine + falling knife filter
│   ├── exchange.py          # Tokocrypto API (CCXT + Binance data)
│   ├── risk.py              # Risk management + reconciliation
│   └── notifier.py          # Telegram notifikasi
├── .github/workflows/
│   └── trade.yml            # GitHub Actions (auto + manual control)
└── logs/                    # Log harian
```

## 🚀 Setup

### 1. Test di PC

```bash
pip install -r requirements.txt
copy .env.example .env       # Isi API key

python main.py --scan-only   # Scan tanpa transaksi
python main.py --dry-run     # Simulasi (tidak ada transaksi nyata)
python main.py --live         # Live trading
```

### 2. Deploy ke GitHub (24/7 Gratis)

```bash
git push origin main
```

Tambah secrets di GitHub: Settings → Secrets → Actions:
- `TOKOCRYPTO_API_KEY`
- `TOKOCRYPTO_SECRET_KEY`
- `TELEGRAM_BOT_TOKEN` (opsional)
- `TELEGRAM_CHAT_ID` (opsional)

### 3. Manual Control dari GitHub UI

Buka: **Actions → CuanBot v4 → Run workflow**

| Aksi | Fungsi |
|---|---|
| `auto` | Trading otomatis (default tiap 5 menit) |
| `scan-only` | Lihat kondisi market tanpa transaksi |
| `dry-run` | Simulasi lengkap |
| `force-buy` | Paksa beli coin tertentu (isi symbol) |
| `force-sell` | Jual semua posisi sekarang |

## 📊 Scoring System (0-100)

| Indikator | Max Skor | Logika |
|---|---|---|
| EMA 9/21 | 25 | Bullish crossover = sinyal terkuat |
| MACD | 25 | Histogram crossover |
| RSI | 20 | Sweet spot: 35-45 (oversold) |
| Bollinger | 20 | Harga dekat lower band |
| Volume | 10 | Konfirmasi volume tinggi |

**Skor ≥ 60** → BUY | **36-59** → HOLD | **≤ 35** → SELL

### Filter Tambahan
- **Falling Knife**: Jangan beli kalau harga turun > 2% dalam 60 menit
- **Multi-TF Bonus**: +8 kalau 2 timeframe setuju, +12 kalau 3 setuju

## 🛡️ Risk Management

| Fitur | Default | Keterangan |
|---|---|---|
| Take Profit | 2.5% | Auto-sell kalau profit 2.5% (fee-aware) |
| Stop Loss | 1.8% | Auto-sell kalau rugi 1.8% (fee-aware) |
| Trailing Stop | 0.5% | Lock profit saat harga naik (aktif di +0.8%) |
| Max Posisi | Dinamis | 1 posisi per ~Rp 50k saldo (cap 5) |
| Cooldown | 5 menit | Jeda antar trade |
| Max/Hari | 10 | Max 10 trade per hari |
| Timeout | 6 jam | Auto-sell posisi nyangkut |
| Emergency | 3x rugi | Pause 2 jam kalau 3x rugi berturut |
| Daily Loss Limit | 3% | Stop trading kalau rugi hari itu ≥ 3% saldo |
| Win-rate Guard | <45% | Pause kalau win rate 20 trade terakhir < 45% |
| Capital Deployment | 85% | 85% saldo diputar, 15% buffer fee/slippage |

**Modal sizing dinamis**: bot pakai saldo riil Tokocrypto, bukan angka fix.
`per_trade = (saldo × 85%) / jumlah_posisi`. Otomatis scale naik/turun.

## ⚠️ DISCLAIMER

Bot ini adalah ALAT BANTU. Tidak ada jaminan profit.
- Mulai dengan DRY_RUN = true dulu
- Monitor hasil minimal 1 hari sebelum live
- Trading crypto = risiko tinggi
- Jangan pakai modal yang tidak siap hilang