# ============================================================
#  CuanBot - Runner Script
#  Cara pakai: klik kanan → "Run with PowerShell"
#  atau di terminal: powershell -ExecutionPolicy Bypass -File run_bot.ps1
# ============================================================

$BOT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$INTERVAL_SECONDS = 60   # 1 menit per cycle (quick check tiap cycle, full scan tiap 3 cycle)

function Write-Header {
    Clear-Host
    Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║         🤖  CuanBot Runner v4            ║" -ForegroundColor Cyan
    Write-Host "║      Smart Crypto Trading Bot            ║" -ForegroundColor Cyan
    Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Menu {
    Write-Host "  Pilih mode:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  [1] Scan Only     - Lihat sinyal coin (aman, tidak ada transaksi)" -ForegroundColor Green
    Write-Host "  [2] Dry Run       - Simulasi trading (tidak ada uang nyata)" -ForegroundColor Yellow
    Write-Host "  [3] Live Trading  - Trading real (quick 1mnt, full scan 3mnt)" -ForegroundColor Red
    Write-Host "  [4] Install Deps  - Install/update requirements.txt" -ForegroundColor Gray
    Write-Host "  [5] Update Bot    - Pull kode terbaru dari GitHub" -ForegroundColor Cyan
    Write-Host "  [6] Keluar" -ForegroundColor Gray
    Write-Host ""
}

function Install-Deps {
    Write-Host "📦 Installing dependencies..." -ForegroundColor Cyan
    pip install -r "$BOT_DIR\requirements.txt"
    Write-Host "✅ Done!" -ForegroundColor Green
    Start-Sleep -Seconds 2
}

function Update-Bot {
    Write-Host ""
    Write-Host "🔄 Update CuanBot..." -ForegroundColor Cyan
    Write-Host "─────────────────────────────────────────" -ForegroundColor DarkGray
    Set-Location $BOT_DIR
    git fetch origin
    git reset --hard origin/main
    pip install -r "$BOT_DIR\requirements.txt" -q
    Write-Host ""
    Write-Host "✅ Bot sudah versi terbaru!" -ForegroundColor Green
    Write-Host "⚠️  Restart script ini supaya perubahan aktif." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Tekan Enter"
}

function Run-ScanOnly {
    Write-Host ""
    Write-Host "🔍 Mode: SCAN ONLY" -ForegroundColor Green
    Write-Host "─────────────────────────────────────────" -ForegroundColor DarkGray
    Set-Location $BOT_DIR
    python main.py --scan-only
    Write-Host ""
    Write-Host "✅ Scan selesai. Tekan Enter untuk kembali ke menu..." -ForegroundColor Gray
    Read-Host
}

function Run-DryRun {
    Write-Host ""
    Write-Host "🧪 Mode: DRY RUN (Simulasi)" -ForegroundColor Yellow
    Write-Host "─────────────────────────────────────────" -ForegroundColor DarkGray
    Set-Location $BOT_DIR
    python main.py --dry-run
    Write-Host ""
    Write-Host "✅ Selesai. Tekan Enter untuk kembali ke menu..." -ForegroundColor Gray
    Read-Host
}

function Run-Live {
    Write-Host ""
    Write-Host "🚀 Mode: LIVE TRADING" -ForegroundColor Red
    Write-Host "⚠️  Bot akan beli/jual crypto dengan uang NYATA!" -ForegroundColor Yellow
    Write-Host ""
    $confirm = Read-Host "Yakin? Ketik 'YA' untuk lanjut"
    if ($confirm -ne "YA") {
        Write-Host "Dibatalkan." -ForegroundColor Gray
        Start-Sleep -Seconds 1
        return
    }

    Write-Host ""
    Write-Host "✅ Live trading dimulai. Tekan Ctrl+C untuk berhenti." -ForegroundColor Green
    Write-Host "   • Quick check (TP/SL): tiap 1 menit" -ForegroundColor DarkGray
    Write-Host "   • Full scan & entry  : tiap 3 menit" -ForegroundColor DarkGray
    Write-Host "─────────────────────────────────────────" -ForegroundColor DarkGray

    $run_count = 0
    while ($true) {
        $run_count++
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $is_full_scan = ($run_count % 3) -eq 0

        Write-Host ""
        Write-Host "[$timestamp] ▶ Run #$run_count $(if ($is_full_scan) { '(FULL SCAN)' } else { '(quick check)' })" -ForegroundColor Cyan
        Write-Host "─────────────────────────────────────────" -ForegroundColor DarkGray

        Set-Location $BOT_DIR
        if ($is_full_scan) {
            python main.py --live
        } else {
            python main.py --quick
        }

        $next_run = (Get-Date).AddSeconds($INTERVAL_SECONDS).ToString("HH:mm:ss")
        Write-Host ""
        Write-Host "⏳ Run #$run_count selesai. Run berikutnya pukul $next_run (Ctrl+C untuk stop)" -ForegroundColor DarkGray
        Write-Host "─────────────────────────────────────────" -ForegroundColor DarkGray

        Start-Sleep -Seconds $INTERVAL_SECONDS
    }
}

# ── Main ─────────────────────────────────────────────────────
Write-Header

# Cek Python tersedia
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Python tidak ditemukan! Install Python 3.9+ dulu." -ForegroundColor Red
    Read-Host "Tekan Enter untuk keluar"
    exit
}

while ($true) {
    Write-Header
    Write-Menu

    $choice = Read-Host "  Pilihan (1-6)"

    switch ($choice) {
        "1" { Run-ScanOnly }
        "2" { Run-DryRun }
        "3" { Run-Live }
        "4" { Install-Deps }
        "5" { Update-Bot }
        "6" {
            Write-Host ""
            Write-Host "👋 Sampai jumpa!" -ForegroundColor Cyan
            exit
        }
        default {
            Write-Host "Pilihan tidak valid." -ForegroundColor Red
            Start-Sleep -Seconds 1
        }
    }
}
