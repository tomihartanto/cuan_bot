"""
CuanBot v4 - Smart Crypto Investment Manager
State machine bersih: reconcile → exit positions → entry baru.
Scalping otomatis: EMA 9/21 + RSI + MACD + Bollinger.

Modes:
  python main.py --scan-only      # Scan saja, tidak ada transaksi
  python main.py --dry-run        # Simulasi (tidak ada transaksi nyata)
  python main.py --live           # Live trading otomatis
  python main.py --force-buy DOGE # Paksa beli coin tertentu (bypass scoring)
  python main.py --force-sell     # Jual semua posisi terbuka sekarang
"""

import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv()

import logging
import time
from datetime import datetime, timezone
from config import Config
from bot.exchange import (
    create_exchange, get_trade_pairs, fetch_candles,
    get_balance, place_order, fetch_ticker_price,
    check_and_allocate_funds, get_usdt_idr_rate,
)
from bot.scanner import score_coin, score_coin_multi_tf
from bot.risk import RiskManager
from bot import notifier
from bot.ai import filter_buy_signal

# ── Logging ───────────────────────────────────────────────────────────
log_dir = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(
            os.path.join(log_dir, f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.log"),
            encoding="utf-8",
        ),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("cuanbot")


# ─────────────────────────────────────────────────────────────────────
# SCAN semua coin
# ─────────────────────────────────────────────────────────────────────

def scan_all_coins(exchange) -> list:
    """Scan semua coin, return ranking dari skor tertinggi."""
    pairs   = get_trade_pairs(exchange)
    results = []
    scanned = 0

    for pair in pairs:
        try:
            candles_5m = fetch_candles(exchange, pair, timeframe="5m")
            if not candles_5m or len(candles_5m) < 30:
                time.sleep(0.2)
                continue

            quick = score_coin(candles_5m)

            if quick["score"] > 35:
                candles_by_tf = {"5m": candles_5m}
                for tf in ["15m", "1h"]:
                    c = fetch_candles(exchange, pair, timeframe=tf)
                    if c and len(c) >= 30:
                        candles_by_tf[tf] = c
                    time.sleep(0.2)

                analysis = (
                    score_coin_multi_tf(candles_by_tf)
                    if len(candles_by_tf) >= 2
                    else quick
                )
            else:
                analysis = quick

            analysis["symbol"] = pair
            results.append(analysis)
            scanned += 1
            time.sleep(0.3)

        except Exception as e:
            logger.warning(f"Scan error {pair}: {e}")
            time.sleep(0.5)

    results.sort(key=lambda x: x["score"], reverse=True)
    logger.info(f"Scan selesai: {scanned}/{len(pairs)} coin")
    return results


# ─────────────────────────────────────────────────────────────────────
# EXIT — Cek & Eksekusi Jual Posisi Terbuka
# ─────────────────────────────────────────────────────────────────────

def check_and_sell_positions(exchange, risk: RiskManager) -> bool:
    """Cek semua posisi terbuka, jual kalau TP/SL/Trailing/Timeout terpenuhi."""
    positions = risk.state.get("positions", [])
    if not positions:
        return False

    current_prices = {}
    for pos in positions:
        price = fetch_ticker_price(exchange, pos["symbol"])
        if price > 0:
            current_prices[pos["symbol"]] = price
            pnl = ((price - pos["entry_price"]) / pos["entry_price"] * 100)
            logger.info(
                f"Posisi: {pos['symbol']} | Entry: Rp {pos['entry_price']:,.0f} | "
                f"Now: Rp {price:,.0f} | PnL: {pnl:+.2f}%"
            )

    sell_actions = risk.check_positions(current_prices)
    sold_any = False
    for action in sell_actions:
        if _execute_sell(exchange, risk, action):
            sold_any = True

    return sold_any


def _execute_sell(exchange, risk: RiskManager, action: dict) -> bool:
    """Eksekusi satu sell order."""
    symbol = action["symbol"]
    amount = action["amount"]
    price  = action["price"]
    reason = action["reason"]

    logger.info(f"SELL {symbol}: {amount:.6f} @ Rp {price:,.0f} | {reason}")
    result = place_order(exchange, symbol, "sell", amount_base=amount, price=price)

    if result.get("error"):
        logger.error(f"Sell gagal {symbol}: {result['error']}")
        notifier.notify_error(f"Sell gagal: {symbol}\n{result['error']}")
        return False

    actual_price = result.get("price") or price
    pnl_data     = risk.close_position(symbol, actual_price)
    risk.record_trade(symbol, "sell", amount, actual_price, result.get("id"))

    status = risk.get_status()
    notifier.notify_trade(
        "sell", symbol, amount, actual_price, 0, reason,
        dry_run=result.get("dry_run", False),
        pnl=pnl_data,
        compound=status.get("compound_profit"),
    )
    return True


# ─────────────────────────────────────────────────────────────────────
# ENTRY — Beli Coin Terbaik dari Scan
# ─────────────────────────────────────────────────────────────────────

def try_buy_best_coin(exchange, risk: RiskManager, rankings: list) -> bool:
    """Beli coin dengan sinyal terkuat dari hasil scan."""
    can, reason = risk.can_trade()
    if not can:
        logger.info(f"Tidak bisa beli: {reason}")
        if "Emergency stop" in reason:
            notifier.notify_emergency_stop(
                risk.state.get("consecutive_losses", 0),
                Config.EMERGENCY_PAUSE_HOURS,
            )
        return False

    buy_candidates = [
        c for c in rankings
        if c.get("action") == "BUY" and not c.get("falling_knife", False)
    ]

    if not buy_candidates:
        logger.info("Tidak ada sinyal BUY yang valid")
        return False

    return _execute_buy(exchange, risk, buy_candidates[0], buy_candidates[0]["reason"])


def _execute_buy(exchange, risk: RiskManager, coin: dict, reason: str) -> bool:
    """Eksekusi satu buy order."""
    symbol    = coin["symbol"]
    price     = coin["price"]
    score     = coin.get("score", 0)
    trade_amt = Config.get_trade_amount()

    # ── AI Filter Check (Z.ai GLM-5.1) ──
    ai_ok, ai_reason = filter_buy_signal(symbol, coin)
    if not ai_ok:
        logger.info(f"BUY {symbol} dibatalkan oleh AI. Alasan: {ai_reason}")
        notifier.send_telegram(
            f"🤖 <b>AI Filter: HOLD {symbol}</b>\n"
            f"Skor Teknis: {score}/100\n"
            f"Alasan AI: {ai_reason}"
        )
        return False
    elif Config.ZAI_API_KEY:
        reason = f"{reason} | AI Approved"

    if trade_amt < Config.MIN_ORDER_IDR:
        logger.warning(f"Modal terlalu kecil: {Config.BASE_CURRENCY} {trade_amt:,.2f} < min {Config.BASE_CURRENCY} {Config.MIN_ORDER_IDR:,.2f}")
        return False

    try:
        balance   = get_balance(exchange)
        available = balance["quote"]["free"]
    except Exception as e:
        logger.error(f"Gagal mengambil saldo: {e}")
        notifier.notify_error(f"Gagal mengambil saldo Tokocrypto (Kemungkinan API key di-blok/expired):\n{e}")
        return False

    if available < trade_amt:
        logger.warning(f"{Config.BASE_CURRENCY} tidak cukup: {available:,.2f} < {trade_amt:,.2f}")
        notifier.notify_error(f"Saldo {Config.BASE_CURRENCY} tidak cukup: {available:,.2f}")
        return False

    logger.info(f"BUY {symbol} | Skor: {score}/100 | {Config.BASE_CURRENCY} {price:,.2f} | Alasan: {reason}")
    result = place_order(exchange, symbol, "buy", amount_idr=trade_amt, price=price)

    if result.get("error"):
        logger.error(f"Buy gagal {symbol}: {result['error']}")
        notifier.notify_error(f"Buy gagal: {symbol}\n{result['error']}")
        return False

    filled_qty   = result.get("amount", trade_amt / price if price > 0 else 0)
    filled_price = result.get("price") or price

    risk.record_trade(symbol, "buy", filled_qty, filled_price, result.get("id"))
    risk.open_position(symbol, filled_qty, filled_price, value_idr=trade_amt)

    logger.info(
        f"BELI BERHASIL: {symbol} | {filled_qty:.6f} crypto | "
        f"{Config.BASE_CURRENCY} {filled_price:,.2f}/unit | Total: {Config.BASE_CURRENCY} {trade_amt:,.2f}"
    )
    status = risk.get_status()
    notifier.notify_trade(
        "buy", symbol, filled_qty, filled_price, score, reason,
        dry_run=result.get("dry_run", False),
        compound=status.get("compound_profit"),
    )
    return True


# ─────────────────────────────────────────────────────────────────────
# MANUAL COMMANDS — Force Buy / Force Sell
# ─────────────────────────────────────────────────────────────────────

def run_force_buy(exchange, risk: RiskManager, symbol_input: str):
    """
    MANUAL: Paksa beli coin tertentu dari GitHub Actions.
    Bypass scoring tapi tetap cek balance dan posisi.
    """
    # Normalize: "DOGE" → "DOGE/IDR"
    sym = symbol_input.strip().upper()
    if "/" not in sym:
        sym = f"{sym}/{Config.BASE_CURRENCY}"

    logger.info(f"[FORCE BUY] Request: {sym}")
    notifier.send_telegram(f"[FORCE BUY] Request masuk untuk <b>{sym}</b>...")

    # Cek posisi dulu
    can, reason = risk.can_trade()
    if not can:
        msg = f"Force buy dibatalkan: {reason}"
        logger.warning(msg)
        notifier.notify_error(msg)
        return

    # Ambil harga terkini
    price = fetch_ticker_price(exchange, sym)
    if price <= 0:
        candles = fetch_candles(exchange, sym, timeframe="5m")
        if candles:
            price = candles[-1]["close"]

    if price <= 0:
        notifier.notify_error(f"Force buy gagal: tidak bisa dapat harga untuk {sym}")
        return

    # Ambil score untuk info (tidak sebagai filter)
    score = 0
    try:
        candles = fetch_candles(exchange, sym, timeframe="5m")
        if candles and len(candles) >= 30:
            result_score = score_coin(candles)
            score = result_score["score"]
    except Exception:
        pass

    coin = {"symbol": sym, "price": price, "score": score, "falling_knife": False}
    _execute_buy(exchange, risk, coin, f"Manual force buy dari GitHub | Score: {score}/100")


def run_force_sell(exchange, risk: RiskManager):
    """
    MANUAL: Jual semua posisi terbuka sekarang juga dari GitHub Actions.
    """
    positions = risk.state.get("positions", [])
    if not positions:
        msg = "Tidak ada posisi terbuka untuk dijual."
        logger.info(msg)
        notifier.send_telegram(f"[FORCE SELL] {msg}")
        return

    logger.info(f"[FORCE SELL] Jual {len(positions)} posisi terbuka...")
    notifier.send_telegram(f"[FORCE SELL] Menjual <b>{len(positions)} posisi</b> sekarang...")

    for pos in positions[:]:
        symbol = pos["symbol"]
        amount = pos["amount"]
        price  = fetch_ticker_price(exchange, symbol)
        if price <= 0:
            price = pos["entry_price"]

        action = {
            "symbol":   symbol,
            "amount":   amount,
            "price":    price,
            "reason":   "Manual force sell dari GitHub",
            "priority": "HIGH",
        }
        _execute_sell(exchange, risk, action)
        time.sleep(1)


# ─────────────────────────────────────────────────────────────────────
# MAIN RUN — Auto Trading
# ─────────────────────────────────────────────────────────────────────

def run(dry_run_override=None, scan_only=False, force_buy_symbol=None, force_sell=False):
    if dry_run_override is not None:
        Config.DRY_RUN = dry_run_override

    mode = "[DRY RUN]" if Config.DRY_RUN else "[LIVE]"
    logger.info(
        f"CuanBot v4 {mode} | "
        f"TP: {Config.TAKE_PROFIT_PERCENT}% | SL: {Config.STOP_LOSS_PERCENT}% | "
        f"Trailing: {'ON' if Config.TRAILING_STOP_ENABLED else 'OFF'} | "
        f"Compound: {'ON' if Config.AUTO_COMPOUND else 'OFF'}"
    )

    # Init
    try:
        exchange = create_exchange()
        
        # ── Deteksi Saldo & Alokasi Currency Dinamis ──
        try:
            active_currency, available_balance = check_and_allocate_funds(exchange)
            if active_currency == "NONE":
                logger.warning("Saldo tidak mencukupi untuk trading di IDR maupun USDT")
                notifier.send_telegram("⚠️ <b>CuanBot Saldo Tidak Cukup</b>\nSaldo Anda kurang dari Rp 10.000 IDR dan kurang dari 10 USDT. Bot tidak dapat memulai transaksi. Silakan top up.")
                return
            Config.setup_currency(active_currency)
        except Exception as e:
            logger.warning(f"Gagal mendeteksi saldo secara dinamis ({e}). Fallback ke config default.")
            Config.setup_currency(Config.BASE_CURRENCY)

        risk = RiskManager()

        # Reconcile state currency jika terdeteksi perubahan mata uang aktif
        saved_currency = risk.state.get("currency", "IDR")
        if saved_currency != Config.BASE_CURRENCY:
            logger.info(f"Mata uang di state ({saved_currency}) berbeda dengan mata uang aktif ({Config.BASE_CURRENCY}). Melakukan konversi state...")
            try:
                rate = get_usdt_idr_rate()
                if saved_currency == "IDR" and Config.BASE_CURRENCY == "USDT":
                    # Konversi IDR -> USDT
                    risk.state["daily_pnl"] = risk.state.get("daily_pnl", 0.0) / rate
                    risk.state["total_pnl"] = risk.state.get("total_pnl", 0.0) / rate
                    risk.state["compound_profit"] = risk.state.get("compound_profit", 0.0) / rate
                elif saved_currency == "USDT" and Config.BASE_CURRENCY == "IDR":
                    # Konversi USDT -> IDR
                    risk.state["daily_pnl"] = risk.state.get("daily_pnl", 0.0) * rate
                    risk.state["total_pnl"] = risk.state.get("total_pnl", 0.0) * rate
                    risk.state["compound_profit"] = risk.state.get("compound_profit", 0.0) * rate
                
                risk.state["currency"] = Config.BASE_CURRENCY
                risk.save_state()
                logger.info(f"State berhasil dikonversi ke {Config.BASE_CURRENCY}.")
            except Exception as e:
                logger.error(f"Gagal mengonversi state: {e}")

    except Exception as e:
        logger.error(f"Init gagal: {e}")
        notifier.notify_error(f"Init gagal (Cek API Key / IP Whitelist / Tokocrypto down):\n{e}")
        return

    # Startup notif (anti-spam: max 1x per jam)
    if risk.should_send_startup_notif():
        notifier.notify_startup()

    status = risk.get_status()
    logger.info(
        f"Status: {status['trades_today']}/{status['max_trades']} trades | "
        f"{status['open_positions']} posisi | "
        f"PnL hari ini: Rp {status['daily_pnl']:,.0f} | "
        f"Compound: Rp {status['compound_profit']:,.0f}"
    )

    # ── MANUAL: Force Sell ──────────────────────────────────────────
    if force_sell:
        logger.info("Mode: FORCE SELL semua posisi")
        run_force_sell(exchange, risk)
        risk.save_state()
        return

    # ── MANUAL: Force Buy ───────────────────────────────────────────
    if force_buy_symbol:
        logger.info(f"Mode: FORCE BUY {force_buy_symbol}")
        run_force_buy(exchange, risk, force_buy_symbol)
        risk.save_state()
        return

    # ── PHASE 1: Reconcile state vs exchange balance ────────────────
    if not Config.DRY_RUN and not scan_only:
        try:
            balance        = get_balance(exchange)
            current_prices = {}
            for asset in balance["holdings"]:
                pair  = f"{asset}/{Config.BASE_CURRENCY}"
                price = fetch_ticker_price(exchange, pair)
                if price > 0:
                    current_prices[pair] = price
            risk.reconcile_with_balance(balance["holdings"], current_prices)
        except Exception as e:
            logger.warning(f"Reconcile gagal (lanjut): {e}")
            notifier.notify_error(f"Reconcile saldo gagal (Koneksi bermasalah/API Key di-blok):\n{e}")

    # ── PHASE 2: EXIT — Cek posisi terbuka ─────────────────────────
    if not scan_only:
        sold = check_and_sell_positions(exchange, risk)
        if sold:
            risk.save_state()

    # ── PHASE 3: SCAN ───────────────────────────────────────────────
    rankings = scan_all_coins(exchange)
    if not rankings:
        logger.warning("Tidak ada coin yang bisa di-scan")
        notifier.notify_error(
            "Gagal melakukan scan coin (0 coin berhasil di-scan).\n"
            "Kemungkinan koneksi internet terganggu, rate limit Binance API, atau IP GitHub Actions diblok."
        )
        risk.save_state()
        return

    top  = rankings[0]
    buys = [c for c in rankings if c.get("action") == "BUY"]
    logger.info(
        f"Top: {top['symbol']} ({top['score']}/100 {top['action']}) | "
        f"BUY signals: {len(buys)}"
    )
    notifier.notify_scan_results(rankings)

    if scan_only:
        risk.save_state()
        logger.info("Scan-only selesai.")
        return

    # ── PHASE 4: ENTRY — Beli kalau belum ada posisi ───────────────
    current_positions = len(risk.state.get("positions", []))
    if current_positions < Config.MAX_OPEN_POSITIONS:
        try_buy_best_coin(exchange, risk, rankings)
    else:
        logger.info(f"Posisi penuh ({current_positions}/{Config.MAX_OPEN_POSITIONS}), skip beli")

    # ── PHASE 5: Save & Summary ─────────────────────────────────────
    risk.save_state()
    final = risk.get_status()
    notifier.notify_daily_summary(final)
    logger.info(
        f"Selesai: {final['trades_today']} trades | "
        f"PnL: Rp {final['daily_pnl']:,.0f} | "
        f"Win rate: {final['win_rate']}%"
    )


# ─────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    dry_run          = None
    scan_only        = False
    force_buy_symbol = None
    force_sell       = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--dry-run":
            dry_run = True
        elif arg == "--live":
            dry_run = False
        elif arg == "--scan-only":
            scan_only = True
        elif arg == "--force-sell":
            force_sell = True
            dry_run = False  # Force sell selalu live
        elif arg == "--force-buy":
            i += 1
            if i < len(args):
                force_buy_symbol = args[i]
                dry_run = False  # Force buy selalu live
        i += 1

    run(
        dry_run_override=dry_run,
        scan_only=scan_only,
        force_buy_symbol=force_buy_symbol,
        force_sell=force_sell,
    )
