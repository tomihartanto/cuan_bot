"""
CuanBot v4 - Smart Crypto Investment Manager
State machine bersih: reconcile → exit positions → entry baru.
Scalping otomatis: EMA 9/21 + RSI + MACD + Bollinger.
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
    create_exchange, get_idr_pairs, fetch_candles,
    get_balance, place_order, fetch_ticker_price,
)
from bot.scanner import score_coin, score_coin_multi_tf
from bot.risk import RiskManager
from bot import notifier

# ── Logging ───────────────────────────────────────────────────────────
log_dir = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(
            os.path.join(log_dir, f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.log")
        ),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("cuanbot")


# ─────────────────────────────────────────────────────────────────────
# PHASE 1: SCAN semua coin
# ─────────────────────────────────────────────────────────────────────

def scan_all_coins(exchange) -> list:
    """Scan semua coin, return ranking dari skor tertinggi."""
    pairs   = get_idr_pairs()
    results = []
    scanned = 0

    for pair in pairs:
        try:
            # Ambil candle 5m terlebih dahulu
            candles_5m = fetch_candles(exchange, pair, timeframe="5m")
            if not candles_5m or len(candles_5m) < 30:
                time.sleep(0.2)
                continue

            # Quick score dulu → lanjut ke multi-TF hanya kalau promising
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
# PHASE 2: EXIT — Cek & Eksekusi Jual Posisi Terbuka
# ─────────────────────────────────────────────────────────────────────

def check_and_sell_positions(exchange, risk: RiskManager) -> bool:
    """
    Cek semua posisi terbuka, jual kalau TP/SL/Trailing/Timeout terpenuhi.
    Return True kalau ada posisi yang dijual.
    """
    positions = risk.state.get("positions", [])
    if not positions:
        return False

    # Ambil harga terkini untuk semua posisi
    current_prices = {}
    for pos in positions:
        price = fetch_ticker_price(exchange, pos["symbol"])
        if price > 0:
            current_prices[pos["symbol"]] = price
            logger.info(
                f"Posisi: {pos['symbol']} | Entry: Rp {pos['entry_price']:,.2f} | "
                f"Now: Rp {price:,.2f} | "
                f"PnL: {((price - pos['entry_price']) / pos['entry_price'] * 100):+.2f}%"
            )

    # Dapatkan aksi yang perlu dilakukan
    sell_actions = risk.check_positions(current_prices)
    sold_any = False

    for action in sell_actions:
        success = _execute_sell(exchange, risk, action)
        if success:
            sold_any = True

    return sold_any


def _execute_sell(exchange, risk: RiskManager, action: dict) -> bool:
    """Eksekusi satu sell order."""
    symbol = action["symbol"]
    amount = action["amount"]
    price  = action["price"]
    reason = action["reason"]

    logger.info(f"SELL {symbol}: {amount:.6f} @ Rp {price:,.2f} | {reason}")

    result = place_order(exchange, symbol, "sell", amount_base=amount, price=price)

    if result.get("error"):
        logger.error(f"Sell gagal {symbol}: {result['error']}")
        notifier.notify_error(f"❌ Sell gagal: {symbol}\n{result['error']}")
        return False

    # Gunakan filled price dari order kalau ada
    actual_price = result.get("price") or price
    pnl_data     = risk.close_position(symbol, actual_price)
    risk.record_trade(symbol, "sell", amount, actual_price, result.get("id"))

    status = risk.get_status()
    notifier.notify_trade(
        "sell", symbol, amount, actual_price, 0,
        reason,
        dry_run=result.get("dry_run", False),
        pnl=pnl_data,
        compound=status.get("compound_profit"),
    )
    return True


# ─────────────────────────────────────────────────────────────────────
# PHASE 3: ENTRY — Beli Coin Terbaik
# ─────────────────────────────────────────────────────────────────────

def try_buy_best_coin(exchange, risk: RiskManager, rankings: list) -> bool:
    """
    Dari hasil scan, coba beli coin dengan sinyal terkuat.
    Return True kalau berhasil beli.
    """
    can, reason = risk.can_trade()
    if not can:
        logger.info(f"Tidak bisa beli: {reason}")
        if "Emergency stop" in reason:
            notifier.notify_emergency_stop(
                risk.state.get("consecutive_losses", 0),
                Config.EMERGENCY_PAUSE_HOURS,
            )
        return False

    # Filter: hanya coin dengan sinyal BUY dan tidak falling knife
    buy_candidates = [
        c for c in rankings
        if c.get("action") == "BUY" and not c.get("falling_knife", False)
    ]

    if not buy_candidates:
        logger.info("Tidak ada sinyal BUY yang valid saat ini")
        return False

    best = buy_candidates[0]
    symbol     = best["symbol"]
    price      = best["price"]
    score      = best["score"]
    reason     = best["reason"]
    trade_idr  = Config.get_trade_amount()

    if trade_idr < Config.MIN_ORDER_IDR:
        logger.warning(f"Modal terlalu kecil: Rp {trade_idr:,.0f} < min Rp {Config.MIN_ORDER_IDR:,.0f}")
        return False

    logger.info(f"BUY signal: {symbol} | Skor: {score}/100 | Rp {price:,.2f} | {reason}")

    # Cek balance IDR cukup
    balance   = get_balance(exchange)
    available = balance["idr"]["free"]
    if available < trade_idr:
        logger.warning(f"IDR tidak cukup: Rp {available:,.0f} < Rp {trade_idr:,.0f}")
        return False

    # Eksekusi BUY via quoteOrderQty (beri IDR, dapat crypto)
    result = place_order(exchange, symbol, "buy", amount_idr=trade_idr, price=price)

    if result.get("error"):
        logger.error(f"Buy gagal {symbol}: {result['error']}")
        notifier.notify_error(f"❌ Buy gagal: {symbol}\n{result['error']}")
        return False

    # Catat posisi dengan jumlah crypto yang benar-benar dapat
    filled_qty   = result.get("amount", trade_idr / price)
    filled_price = result.get("price") or price

    risk.record_trade(symbol, "buy", filled_qty, filled_price, result.get("id"))
    risk.open_position(symbol, filled_qty, filled_price, value_idr=trade_idr)

    logger.info(
        f"✅ BELI {symbol}: {filled_qty:.6f} crypto | Rp {filled_price:,.2f}/unit | "
        f"Total: Rp {trade_idr:,.0f}"
    )

    status = risk.get_status()
    notifier.notify_trade(
        "buy", symbol, filled_qty, filled_price, score, reason,
        dry_run=result.get("dry_run", False),
        compound=status.get("compound_profit"),
    )
    return True


# ─────────────────────────────────────────────────────────────────────
# MAIN RUN
# ─────────────────────────────────────────────────────────────────────

def run(dry_run_override=None, scan_only=False):
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
        risk     = RiskManager()
    except Exception as e:
        logger.error(f"Init gagal: {e}")
        notifier.notify_error(f"Init gagal: {e}")
        return

    # Startup notification (anti-spam: max 1x per jam)
    if risk.should_send_startup_notif():
        notifier.notify_startup()

    status = risk.get_status()
    logger.info(
        f"Status: {status['trades_today']}/{status['max_trades']} trades | "
        f"{status['open_positions']} posisi | "
        f"PnL hari ini: Rp {status['daily_pnl']:,.0f} | "
        f"Compound: Rp {status['compound_profit']:,.0f}"
    )

    # ── PHASE 1: Reconcile state vs exchange balance ────────────────
    if not Config.DRY_RUN and not scan_only:
        try:
            balance = get_balance(exchange)
            # Ambil harga saat ini untuk holdings
            current_prices = {}
            for asset in balance["holdings"]:
                pair  = f"{asset}/{Config.BASE_CURRENCY}"
                price = fetch_ticker_price(exchange, pair)
                if price > 0:
                    current_prices[pair] = price
            risk.reconcile_with_balance(balance["holdings"], current_prices)
        except Exception as e:
            logger.warning(f"Reconcile gagal (lanjut): {e}")

    # ── PHASE 2: EXIT — Cek posisi terbuka ─────────────────────────
    if not scan_only:
        sold = check_and_sell_positions(exchange, risk)
        if sold:
            risk.save_state()

    # ── PHASE 3: SCAN semua coin ────────────────────────────────────
    rankings = scan_all_coins(exchange)
    if not rankings:
        logger.warning("Tidak ada coin yang bisa di-scan")
        risk.save_state()
        return

    top    = rankings[0]
    buys   = [c for c in rankings if c.get("action") == "BUY"]
    logger.info(
        f"Top: {top['symbol']} ({top['score']}/100 {top['action']}) | "
        f"BUY signals: {len(buys)}"
    )
    notifier.notify_scan_results(rankings)

    if scan_only:
        risk.save_state()
        logger.info("Scan-only mode, selesai.")
        return

    # ── PHASE 4: ENTRY — Beli kalau tidak ada posisi ───────────────
    current_positions = len(risk.state.get("positions", []))
    if current_positions < Config.MAX_OPEN_POSITIONS:
        try_buy_best_coin(exchange, risk, rankings)
    else:
        logger.info(f"Posisi sudah penuh ({current_positions}/{Config.MAX_OPEN_POSITIONS}), skip beli")

    # ── PHASE 5: Save & Summary ─────────────────────────────────────
    risk.save_state()
    final = risk.get_status()
    notifier.notify_daily_summary(final)
    logger.info(
        f"Selesai: {final['trades_today']} trades | "
        f"PnL hari ini: Rp {final['daily_pnl']:,.0f} | "
        f"Win rate: {final['win_rate']}%"
    )


if __name__ == "__main__":
    dry_run   = None
    scan_only = False
    if "--dry-run" in sys.argv:   dry_run   = True
    if "--live" in sys.argv:      dry_run   = False
    if "--scan-only" in sys.argv: scan_only = True
    run(dry_run_override=dry_run, scan_only=scan_only)
