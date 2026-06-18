# 🤖 CuanBot v4 - Smart Crypto Investment Manager

Bot trading otomatis untuk Tokocrypto. Scan 21 pair IDR aktif, analisa teknikal multi-timeframe (EMA + RSI + MACD + Bollinger), filter AI (Z.ai GLM), dan auto-trade — berjalan 24/7 **gratis di Termux Android**.

## 🏗️ Arsitektur

```
Dev PC (edit kode) → git push → GitHub (source repo)
                                        ↓
                                  Termux Android
                                        ↓
                            git pull → run_bot.sh
                                        ↓
                        Loop berjalan di tmux session:
                  ┌─────────────────────────────────┐
                  │  Quick check (TP/SL): tiap 1 mt │
                  │  Full scan & entry  : tiap 3 mt │
                  └─────────────────────────────────┘
                                        ↓
PHASE 1 — Reconcile: sync state vs exchange balance
    ↓
PHASE 2 — Exit: cek posisi terbuka → TP/SL/Trailing/Timeout
    ↓
PHASE 3 — Scan: 21 pair IDR aktif, 3 timeframe (5m, 15m, 1h)
    ↓
PHASE 4 — Entry: beli coin terbaik kalau score ≥ 55
    ↓
PHASE 5 — Save state & notif Telegram
```

**Runtime**: Termux Android (satu-satunya). GitHub hanya sebagai source repo (push dari PC, pull di Termux).

## 📁 Struktur

```
cuan-bot/
├── main.py                  # Entry point + state machine
├── config.py                # Konfigurasi (env-driven)
├── requirements.txt         # Dependencies (minimal: dotenv, requests)
├── run_bot.sh               # Runner script Termux (menu interaktif + tmux)
├── run_bot.ps1              # Runner script Windows (untuk dev PC)
├── .env                     # Secrets (lokal, gitignored)
├── .env.example             # Template .env
├── state.json               # State (auto-updated)
├── bot/
│   ├── indicators.py        # RSI, MACD, Bollinger, Volume, EMA 9/21
│   ├── scanner.py           # Scoring engine + falling knife filter
│   ├── exchange.py          # Tokocrypto API
│   ├── risk.py              # Risk management + reconciliation
│   ├── notifier.py          # Telegram notifikasi
│   └── ai.py                # Z.ai GLM filter
└── logs/                    # Log harian
```

## 🚀 Setup di Termux (Android)

### 1. Install Termux

Dapatkan Termux dari [F-Droid](https://f-droid.org/packages/com.termux/) (versi Play Store sudah usang & bermasalah).

### 2. Install Dependensi

```bash
# Update Termux & install toolchain
pkg update && pkg upgrade -y
pkg install python git tmux -y

# (Opsional) Termux:Boot — auto-start bot saat HP reboot
# Install dari F-Droid: https://f-droid.org/packages/com.termux.boot/
```

### 3. Kloning Repo

```bash
# Asumsi repo GitHub Anda: https://github.com/USERNAME/cuan-bot
git clone https://github.com/USERNAME/cuan-bot.git ~/cuan_bot
cd ~/cuan_bot
```

> **Catatan path**: Runner script (`run_bot.sh`) mengharapkan bot berada di
> `$HOME/cuan_bot` (underscore, bukan dash). Sesuaikan jika berbeda.

### 4. Konfigurasi Secret

```bash
cp .env.example .env
nano .env       # Isi API key Tokocrypto, Telegram, Z.ai (opsional)
chmod 600 .env  # Restriksi permission (hanya owner bisa baca)
```

Minimum wajib diisi:
- `TOKOCRYPTO_API_KEY`
- `TOKOCRYPTO_SECRET_KEY`

Opsional tapi disarankan:
- `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` (notifikasi)

> **⚠️ Keamanan device**: Secret disimpan di HP Anda. Jika HP hilang/dicuri,
> segera **revoke API key** di dashboard Tokocrypto & Telegram. Pertimbangkan
> rotasi key berkala. Jangan pernah commit file `.env` ke git.

### 5. Install Dependensi Python

```bash
pip install -r requirements.txt
```

### 6. Test Cepat

```bash
python main.py --scan-only   # Scan saja, tidak ada transaksi
```

Kalau output muncul (ranking coin + skor), bot siap dipakai.

## 🎮 Menjalankan Bot

Termux sudah menyediakan menu interaktif lewat `run_bot.sh`:

```bash
bash run_bot.sh
```

Menu yang tersedia:

| # | Menu | Fungsi |
|---|------|--------|
| 1 | Scan Only | Lihat sinyal coin (aman, tidak ada transaksi) |
| 2 | Dry Run | Simulasi trading lengkap (tidak ada uang nyata) |
| 3 | Live Trading | Trading real (quick check 1mnt, full scan 3mnt) |
| 4 | Stop Bot | Hentikan bot yang sedang jalan |
| 5 | Status Bot | Cek apakah bot sedang jalan |
| 6 | Update Bot | Pull kode terbaru dari GitHub |
| 7 | Keluar | — |

### Mode Live (Penting!)

Mode 3 (Live Trading) akan:
- Membeli/menjual crypto dengan **uang nyata**
- Meminta konfirmasi ketik `YA` sebelum mulai
- Berjalan di tmux session `bot` (tetap jalan walau layar Termux ditutup)

Perintah tmux berguna:
```bash
tmux attach -t bot     # Lihat log bot real-time
# Di dalam tmux: tekan Ctrl+B lalu D untuk lepas (bot tetap jalan)
```

### Auto-start saat HP Reboot (Opsional)

Install `Termux:Boot` dari F-Droid, lalu buat file:
```bash
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/start-bot.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
sleep 5
cd ~/cuan_bot
tmux new-session -d -s bot "bash run_bot.sh"
EOF
chmod +x ~/.termux/boot/start-bot.sh
```

## 🔄 Workflow Update Kode

```
1. Edit kode di PC (development)
2. git push ke GitHub
3. Di Termux: bash run_bot.sh → menu 6 (Update Bot)
   (atau manual: cd ~/cuan_bot && git pull)
4. Stop bot dulu (menu 4) kalau sedang jalan
5. Jalankan ulang (menu 2 atau 3)
```

> **⚠️ Penting soal `state.json`**: file ini berisi posisi terbuka & statistik.
> Saat `git pull`, kemungkinan ada konflik kalau `state.json` ikut ter-commit.
> Pastikan `state.json` ada di `.gitignore` (sudah default) supaya tidak bentrok.

## 📊 Scoring System (0-100)

| Indikator | Max Skor | Logika |
|---|---|---|
| EMA 9/21 | 25 | Bullish crossover = sinyal terkuat |
| MACD | 25 | Histogram crossover |
| RSI | 20 | Sweet spot: 35-45 (oversold) |
| Bollinger | 20 | Harga dekat lower band |
| Volume | 10 | Konfirmasi volume tinggi |

**Skor ≥ 55** → BUY | **38-54** → HOLD | **≤ 38** → SELL

### Filter Tambahan
- **Falling Knife**: Jangan beli kalau harga turun > 2% dalam 60 menit
- **Multi-TF Bonus**: +8 kalau 2 timeframe setuju, +12 kalau 3 setuju
- **AI Filter (opsional)**: Z.ai GLM menilai ulang sinyal sebelum eksekusi. Default `glm-4.7-flash` (murah & cepat)

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

## 🔧 Mode Operasi (CLI)

Bisa juga jalankan langsung tanpa menu (untuk cron/automasi):

```bash
python main.py --scan-only      # Scan saja, tidak ada transaksi
python main.py --dry-run        # Simulasi (tidak ada transaksi nyata)
python main.py --live           # Live trading (sekali jalan, lalu exit)
python main.py --quick          # Quick check TP/SL saja (skip scan)
python main.py --force-buy DOGE # Paksa beli coin tertentu
python main.py --force-sell     # Jual semua posisi sekarang
```

## ⚠️ DISCLAIMER

Bot ini adalah ALAT BANTU. Tidak ada jaminan profit.
- Mulai dengan `DRY_RUN=true` dulu
- Monitor hasil minimal 1 hari sebelum live
- Trading crypto = risiko tinggi
- Jangan pakai modal yang tidak siap hilang
- Bot berjalan di HP Anda — risiko koneksi/data/baterai/hebat doze mode Android
