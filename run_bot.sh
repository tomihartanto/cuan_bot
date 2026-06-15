#!/bin/bash
# ============================================================
#  CuanBot - Runner Script untuk Termux (Android)
#  Cara pakai: bash run_bot.sh
# ============================================================

BOT_DIR="$HOME/cuan_bot"
INTERVAL=60  # 1 menit (quick check tiap cycle, full scan tiap 5 cycle)

show_header() {
    clear
    echo "╔══════════════════════════════════════════╗"
    echo "║         🤖  CuanBot Runner v4            ║"
    echo "║      Smart Crypto Trading Bot            ║"
    echo "╚══════════════════════════════════════════╝"
    echo ""
}

show_menu() {
    echo "  Pilih mode:"
    echo ""
    echo "  [1] Scan Only     - Lihat sinyal coin (aman)"
    echo "  [2] Dry Run       - Simulasi trading"
    echo "  [3] Live Trading  - Trading real (quick check 1mnt, full scan 5mnt)"
    echo "  [4] Stop Bot      - Hentikan bot yang sedang jalan"
    echo "  [5] Status Bot    - Cek apakah bot sedang jalan"
    echo "  [6] Keluar"
    echo ""
}

run_scan() {
    echo ""
    echo "🔍 Mode: SCAN ONLY"
    echo "─────────────────────────────────────────"
    cd "$BOT_DIR"
    python main.py --scan-only
    echo ""
    echo "✅ Selesai. Tekan Enter..."
    read
}

run_dryrun() {
    echo ""
    echo "🧪 Mode: DRY RUN (Simulasi)"
    echo "─────────────────────────────────────────"
    cd "$BOT_DIR"
    python main.py --dry-run
    echo ""
    echo "✅ Selesai. Tekan Enter..."
    read
}

run_live() {
    echo ""
    echo "🚀 Mode: LIVE TRADING"
    echo "⚠️  Bot akan beli/jual crypto dengan uang NYATA!"
    echo ""
    read -p "Yakin? Ketik 'YA' untuk lanjut: " confirm
    if [ "$confirm" != "YA" ]; then
        echo "Dibatalkan."
        sleep 1
        return
    fi

    # Jalankan di tmux session baru
    if tmux has-session -t bot 2>/dev/null; then
        echo "⚠️  Session 'bot' sudah ada. Stop dulu? (y/n)"
        read ans
        if [ "$ans" = "y" ]; then
            tmux kill-session -t bot
        else
            tmux attach -t bot
            return
        fi
    fi

    echo ""
    echo "✅ Menjalankan bot di background (tmux session: bot)..."
    echo "   • Quick check (TP/SL): tiap 1 menit"
    echo "   • Full scan & entry  : tiap 5 menit"
    tmux new-session -d -s bot -x 200 -y 50
    tmux send-keys -t bot "cd $BOT_DIR && CYCLE=0; while true; do CYCLE=\$((CYCLE + 1)); if [ \$((CYCLE % 5)) -eq 0 ]; then echo '=== FULL SCAN ==='; python main.py --live; else python main.py --quick; fi; sleep $INTERVAL; done" Enter
    echo ""
    echo "Bot jalan di background! Gunakan:"
    echo "  tmux attach -t bot   → lihat log bot"
    echo "  Ctrl+B lalu D        → lepas (bot tetap jalan)"
    echo ""
    echo "Mau langsung lihat log? (y/n)"
    read ans
    if [ "$ans" = "y" ]; then
        tmux attach -t bot
    fi
}

stop_bot() {
    if tmux has-session -t bot 2>/dev/null; then
        tmux kill-session -t bot
        echo "✅ Bot berhasil dihentikan."
    else
        echo "ℹ️  Bot tidak sedang jalan."
    fi
    sleep 2
}

status_bot() {
    echo ""
    if tmux has-session -t bot 2>/dev/null; then
        echo "✅ Bot sedang JALAN (tmux session: bot)"
        echo ""
        echo "Mau lihat log? (y/n)"
        read ans
        if [ "$ans" = "y" ]; then
            tmux attach -t bot
        fi
    else
        echo "⛔ Bot TIDAK jalan."
    fi
    echo ""
    echo "Tekan Enter..."
    read
}

# ── Main ──────────────────────────────────────────────────
while true; do
    show_header
    show_menu
    read -p "  Pilihan (1-6): " choice

    case $choice in
        1) run_scan ;;
        2) run_dryrun ;;
        3) run_live ;;
        4) stop_bot ;;
        5) status_bot ;;
        6)
            echo ""
            echo "👋 Sampai jumpa!"
            exit 0
            ;;
        *)
            echo "Pilihan tidak valid."
            sleep 1
            ;;
    esac
done
