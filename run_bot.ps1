# ============================================================
#  CuanBot - Runner Script
#  Cara pakai: klik kanan → "Run with PowerShell"
#  atau di terminal: powershell -ExecutionPolicy Bypass -File run_bot.ps1
# ============================================================

$BOT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$INTERVAL_MINUTES = 5

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
    Write-Host "  [3] Live Trading  - Trading real otomatis tiap $INTERVAL_MINUTES menit" -ForegroundColor Red
    Write-Host "  [4] Install Deps  - Install/update requirements.txt" -ForegroundColor Gray
    Write-Host "  [5] Keluar" -ForegroundColor Gray
    Write-Host ""
}

function Install-Deps {
    Write-Host "📦 Installing dependencies..." -ForegroundColor Cyan
    pip install -r "$BOT_DIR\requirements.txt"
    Write-Host "✅ Done!" -ForegroundColor Green
    Start-Sleep -Seconds 2
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
    Write-Host "─────────────────────────────────────────" -ForegroundColor DarkGray

    $run_count = 0
    while ($true) {
        $run_count++
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Write-Host ""
        Write-Host "[$timestamp] ▶ Run #$run_count" -ForegroundColor Cyan
        Write-Host "─────────────────────────────────────────" -ForegroundColor DarkGray

        Set-Location $BOT_DIR
        python main.py --live

        $next_run = (Get-Date).AddMinutes($INTERVAL_MINUTES).ToString("HH:mm:ss")
        Write-Host ""
        Write-Host "⏳ Run #$run_count selesai. Run berikutnya pukul $next_run (Ctrl+C untuk stop)" -ForegroundColor DarkGray
        Write-Host "─────────────────────────────────────────" -ForegroundColor DarkGray

        Start-Sleep -Seconds ($INTERVAL_MINUTES * 60)
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

    $choice = Read-Host "  Pilihan (1-5)"

    switch ($choice) {
        "1" { Run-ScanOnly }
        "2" { Run-DryRun }
        "3" { Run-Live }
        "4" { Install-Deps }
        "5" {
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
