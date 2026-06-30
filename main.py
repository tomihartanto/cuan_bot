"""
CuanBot v4 - Smart Crypto Investment Manager
State machine bersih: reconcile -> exit positions -> entry baru.
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
from datetime import datetime, timedelta, timezone
from config import Config
from bot.exchange import (
    get_trade_pairs, fetch_candles,
    get_balance, place_order, fetch_ticker_price,
    check_idr_balance, check_market_active,
    cancel_all_orders, get_open_orders, get_clock_drift_ms,
)
from bot.scanner import score_coin, score_coin_multi_tf
from bot.risk import RiskManager
from bot import notifier
from bot.websocket import start as ws_start, stop as ws_stop, get_latest_price, is_running as ws_running
from bot.ai import filter_buy_signal
from bot.market_intel import get_intel_bonus, get_market_summary, get_market_sentiment

# -- Logging ---------------------------------------------------------
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


# ------------------------------------------------------------
# SCAN semua coin
# ------------------------------------------------------------

def scan_all_coins() -> list:
    """Scan semua coin, return ranking dari skor tertinggi."""
    pairs   = get_trade_pairs()
    results = []
    scanned = 0

    for pair in pairs:
        try:
            candles_5m = fetch_candles(pair, timeframe="5m")
            if not candles_5m or len(candles_5m) < 30:
                time.sleep(0.2)
                continue

            quick = score_coin(candles_5m)

            if quick["score"] > 35:
                candles_by_tf = {"5m": candles_5m}
                for tf in ["15m", "1h"]:
                    c = fetch_candles(pair, timeframe=tf)
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

            # ── Market Intel bonus/penalty (Binance.vision + CoinGecko) ──
            try:
                coin_base = pair.split("/")[0]
                intel = get_intel_bonus(coin_base)
                intel_bonus = intel["bonus"]
                if intel_bonus != 0:
                    old_score = analysis["score"]
                    analysis["score"] = max(0, min(100, old_score + intel_bonus))
                    intel_reason = f"[Intel {intel_bonus:+d}] {intel['reason']}"
                    analysis["reason"] = f"{analysis.get('reason', '')} | {intel_reason}"
                    logger.debug(
                        f"Intel {pair}: {old_score} → {analysis['score']} ({intel_bonus:+d}) | {intel['reason']}"
                    )
            except Exception as e:
                logger.debug(f"Intel bonus error for {pair}: {e}")

            results.append(analysis)
            scanned += 1
            time.sleep(0.3)

        except Exception as e:
            logger.warning(f"Scan error {pair}: {e}")
            time.sleep(0.5)

    results.sort(key=lambda x: x["score"], reverse=True)
    logger.info(f"Scan selesai: {scanned}/{len(pairs)} coin")
    return results


# ------------------------------------------------------------
# EXIT -- Cek & Eksekusi Jual Posisi Terbuka
# ------------------------------------------------------------

def check_and_sell_positions(risk: RiskManager) -> bool:
    """Cek semua posisi terbuka, jual kalau TP/SL/Trailing/Timeout/Bearish terpenuhi."""
    positions = risk.state.get("positions", [])
    if not positions:
        return False

    current_prices = {}
    for pos in positions:
        price = fetch_ticker_price(pos["symbol"])
        if price > 0:
            current_prices[pos["symbol"]] = price
            pnl = ((price - pos["entry_price"]) / pos["entry_price"] * 100)
            logger.info(
                f"Posisi: {pos['symbol']} | Entry: Rp {pos['entry_price']:,.0f} | "
                f"Now: Rp {price:,.0f} | PnL: {pnl:+.2f}%"
            )

    # check_positions() update trailing high/stop in-place → selalu save
    sell_actions = risk.check_positions(current_prices)

    # ── Bearish market exit: jual kalau market global lagi crash ────
    # Cek sentiment global, kalau bearish dan posisi profit tipis/rugi → jual
    try:
        sentiment = get_market_sentiment()
        if sentiment["direction"] == "bearish" and sentiment["btc_change"] < -4.0:
            for pos in risk.state.get("positions", []):
                sym = pos["symbol"]
                price = current_prices.get(sym, 0)
                if price <= 0:
                    continue
                pnl = ((price - pos["entry_price"]) / pos["entry_price"] * 100)
                # Kalau rugi atau profit tipis (< +0.5%), exit untuk amankan
                if pnl < 0.5 and sym not in [a["symbol"] for a in sell_actions]:
                    sell_actions.append({
                        "symbol": sym,
                        "amount": pos["amount"],
                        "price":  price,
                        "reason": f"🛡️ Bearish exit (BTC {sentiment['btc_change']:+.1f}%, PnL {pnl:+.1f}%)",
                    })
                    logger.warning(f"BEARISH EXIT {sym}: BTC {sentiment['btc_change']:+.1f}%")
    except Exception as e:
        logger.debug(f"Bearish exit check error: {e}")

    # ── Momentum reversal: auto-sell saat sinyal teknikal berubah bearish ──
    # Cek indikator teknikal coin yang sedang dipegang. Kalau EMA cross ke bawah
    # atau RSI overbought lalu turun, jual sebelum hancur.
    try:
        for pos in risk.state.get("positions", []):
            sym = pos["symbol"]
            if sym in [a["symbol"] for a in sell_actions]:
                continue  # sudah ada action, skip

            candles = fetch_candles(sym, timeframe="5m", limit=50)
            if not candles or len(candles) < 30:
                continue

            analysis = score_coin(candles)
            price = current_prices.get(sym, 0)
            pnl = ((price - pos["entry_price"]) / pos["entry_price"] * 100) if price > 0 else 0

            # Jual kalau:
            # 1. Sinyal teknikal = SELL (score <= 38), ATAU
            # 2. EMA bearish cross + MACD bearish (momentum berbalik arah)
            signals = analysis.get("signals", {})
            ema_sig = signals.get("ema", {})
            macd_sig = signals.get("macd", {})

            technical_sell = (
                analysis.get("action") == "SELL" or
                (ema_sig.get("gap", 0) < -0.3 and not ema_sig.get("above", True))  # EMA turun
            )

            if technical_sell and pnl > -Config.STOP_LOSS_PERCENT:
                sell_actions.append({
                    "symbol": sym,
                    "amount": pos["amount"],
                    "price":  price if price > 0 else analysis.get("price", 0),
                    "reason": f"📉 Momentum reversal (score {analysis['score']}, PnL {pnl:+.1f}%)",
                })
                logger.info(f"MOMENTUM SELL {sym}: score={analysis['score']} action={analysis['action']}")
    except Exception as e:
        logger.debug(f"Momentum reversal check error: {e}")

    sold_any = False
    for action in sell_actions:
        if _execute_sell(risk, action):
            sold_any = True

    # Selalu persist trailing stop updates walau tidak ada sell
    risk.save_state()
    return sold_any


def _execute_sell(risk: RiskManager, action: dict) -> bool:
    """Eksekusi satu sell order. Diam-diam kalau min notional (no Telegram spam)."""
    symbol = action["symbol"]
    amount = action["amount"]
    price  = action["price"]
    reason = action["reason"]

    value_idr = amount * price if price > 0 else 0

    # ── Cek minimum: kalau di bawah minimum, coba quoteOrderQty ──────
    # Jangan kirim notifikasi Telegram (anti-spam). Cukup log.
    if value_idr < Config.MIN_ORDER_IDR:
        # Coba jual via quoteOrderQty (fitur penukaran kecil Tokocrypto)
        logger.info(
            f"[DUST-SELL] {symbol}: nilai Rp {value_idr:,.0f} < min Rp {Config.MIN_ORDER_IDR:,.0f}. "
            f"Coba quoteOrderQty..."
        )
        try:
            result = place_order(symbol, "sell", amount_base=amount, price=price,
                                skip_validation=True)
            if not result.get("error"):
                actual = result.get("price") or price
                logger.info(f"Dust-sell {symbol} OK: {result.get('amount', amount):.8f} @ Rp {actual:,.0f}")
                risk.close_position(symbol, actual)
                risk.record_trade(symbol, "sell", result.get("amount", amount), actual)
                return True
            else:
                logger.debug(f"Dust-sell {symbol} gagal: {result['error']}")
        except Exception as e:
            logger.debug(f"Dust-sell {symbol} error: {e}")
        return False

    logger.info(f"SELL {symbol}: {amount:.6f} @ Rp {price:,.0f} | {reason}")
    result = place_order(symbol, "sell", amount_base=amount, price=price)

    if result.get("error"):
        logger.warning(f"Sell gagal {symbol}: {result['error']}")
        return False

    actual_price = result.get("price") or price
    pnl_data     = risk.close_position(symbol, actual_price)
    risk.record_trade(symbol, "sell", amount, actual_price, result.get("id"))

    status = risk.get_status()
    notifier.notify_trade(
        "sell", symbol, amount, actual_price, 0, reason,
        dry_run=result.get("dry_run", False),
        pnl=pnl_data,
        compound=status.get("realized_pnl"),
    )
    return True


# ------------------------------------------------------------
# SWEEP WALLET -- Kelola SEMUA coin di dompet Tokocrypto
# Investment manager: evaluasi setiap aset, jual yang tidak prospektif
# ------------------------------------------------------------
def sweep_wallet(risk: RiskManager) -> bool:
    """
    Evaluasi SEMUA coin di dompet Tokocrypto (bukan cuma posisi ter-track).
    Jual coin yang:
    1. Nilainya < min notional → coba quoteOrderQty (dust sell)
    2. Tidak punya pair IDR (tidak bisa diperdagangkan) → skip
    3. Sinyal teknikal bearish & tidak sedang di-tracking → jual ke IDR
    """
    try:
        balance = get_balance()
        holdings = balance.get("holdings", {})
        if not holdings:
            return False

        traded_symbols = set()
        available_balance = check_idr_balance()
        sold_any = False

        for asset, amounts in holdings.items():
            free = amounts.get("free", 0)
            if free <= 0:
                continue

            pair = f"{asset}/{Config.BASE_CURRENCY}"
            price = fetch_ticker_price(pair)
            if price <= 0:
                logger.debug(f"[SWEEP] {asset}: tidak ada harga IDR, skip")
                continue

            value_idr = free * price

            # Sudah di-track sebagai posisi aktif? Lewati, biar risk manager yang handle
            tracked = any(p["symbol"] == pair for p in risk.state.get("positions", []))
            if tracked:
                traded_symbols.add(pair)
                continue

            # Nilai kecil → dust sell via quoteOrderQty (skip min notional check)
            if value_idr < Config.MIN_ORDER_IDR:
                logger.info(
                    f"[SWEEP-DUST] {pair}: {free:.8f} = Rp {value_idr:,.0f}. Coba dust-sell..."
                )
                result = place_order(pair, "sell", amount_base=free, price=price,
                                    skip_validation=True)
                if not result.get("error"):
                    actual = result.get("price") or price
                    amt = result.get("amount", free)
                    logger.info(f"[SWEEP-DUST] ✅ {pair} → IDR Rp {actual * amt:,.0f}")
                    sold_any = True
                else:
                    logger.debug(f"[SWEEP-DUST] {pair} gagal: {result['error']}")
                continue

            # Nilai cukup besar → cek teknikal, jual kalau bearish
            logger.info(f"[SWEEP] {pair}: Rp {value_idr:,.0f} (free {free:.8f}) — evaluasi teknikal...")
            try:
                candles = fetch_candles(pair, timeframe="5m", limit=50)
                if not candles or len(candles) < 30:
                    continue
                analysis = score_coin(candles)
                # Jual kalau sinyal bearish (score <= 40) atau falling knife
                if analysis.get("action") == "SELL" or analysis.get("falling_knife", False):
                    logger.info(f"[SWEEP-SELL] {pair}: score={analysis['score']} bearish, jual semua → IDR")
                    result = place_order(pair, "sell", amount_base=free, price=price)
                    if not result.get("error"):
                        actual = result.get("price") or price
                        amt = result.get("amount", free)
                        pnl_pct = ((actual - price) / price * 100) if price > 0 else 0
                        risk.record_trade(pair, "sell", amt, actual)
                        notifier.notify_trade(
                            "sell", pair, amt, actual, pnl_pct,
                            "🧹 Wallet sweep (bearish)",
                            dry_run=False,
                        )
                        logger.info(f"[SWEEP-SELL] ✅ {pair} → IDR Rp {actual * amt:,.0f}")
                        sold_any = True
                    else:
                        logger.warning(f"[SWEEP-SELL] {pair} gagal: {result['error']}")
                else:
                    logger.debug(f"[SWEEP] {pair}: score={analysis['score']} {analysis['action']}, keep")
            except Exception as e:
                logger.debug(f"[SWEEP] Error evaluasi {pair}: {e}")

        if sold_any:
            # Refresh balance setelah jual
            new_bal = check_idr_balance()
            logger.info(f"[SWEEP] Saldo IDR setelah sweep: Rp {new_bal:,.0f}")

        return sold_any

    except Exception as e:
        logger.warning(f"Sweep wallet error: {e}")
        return False


# ------------------------------------------------------------
# ENTRY -- Beli Coin Terbaik dari Scan
# ------------------------------------------------------------

def try_buy_best_coin(risk: RiskManager, rankings: list, available_balance: float) -> bool:
    """Beli coin dengan sinyal terkuat dari hasil scan."""
    can, reason = risk.can_trade(available_balance)
    if not can:
        logger.info(f"Tidak bisa beli: {reason}")
        if "Emergency stop" in reason or "Daily loss limit" in reason or "Win rate rendah" in reason:
            # Status bot normal (pause proteksi), bukan error sistem. Pakai INFO.
            notifier.notify_info(f"Bot pause otomatis:\n{reason}")
        return False

    buy_candidates = [
        c for c in rankings
        if c.get("action") == "BUY" and not c.get("falling_knife", False)
    ]

    if not buy_candidates:
        logger.info("Tidak ada sinyal BUY yang valid")
        return False

    return _execute_buy(risk, buy_candidates[0], buy_candidates[0]["reason"])


def _execute_buy(risk: RiskManager, coin: dict, reason: str, bypass_ai: bool = False) -> bool:
    """Eksekusi satu buy order."""
    symbol = coin["symbol"]
    price  = coin["price"]
    score  = coin.get("score", 0)

    # -- AI Filter Check (Z.ai GLM-4.7-flash) --
    if not bypass_ai:
        ai_ok, ai_reason = filter_buy_signal(symbol, coin)
        if not ai_ok:
            logger.info(f"BUY {symbol} dibatalkan oleh AI. Alasan: {ai_reason}")
            # Anti-spam: rate limit AI HOLD notif per coin (4 jam)
            notifier._send_categorized(
                "AI_HOLD",
                f"🤖 <b>AI Filter: HOLD {symbol}</b>\n"
                f"Skor Teknis: {score}/100\n"
                f"Alasan: {ai_reason}",
                dedup_key_override=f"ai_hold:{symbol}",
            )
            return False
        elif Config.ZAI_API_KEY:
            reason = f"{reason} | AI Approved"
    else:
        logger.info(f"AI filter dilewati untuk {symbol} (force-buy/manual override)")
        reason = f"{reason} | AI Bypassed"

    # Ambil saldo riil untuk dynamic sizing
    try:
        balance   = get_balance()
        available = balance["quote"]["free"]
    except Exception as e:
        logger.error(f"Gagal mengambil saldo: {e}")
        notifier.notify_error(
            f"Gagal mengambil saldo Tokocrypto:\n{e}",
            context=f"_execute_buy({symbol}) get_balance()",
            force_send=True  # error kritis: API down / auth / IP
        )
        return False

    # Dynamic position sizing: persentase dari saldo riil
    trade_amt = Config.get_trade_amount(available)
    if trade_amt < Config.MIN_ORDER_IDR:
        logger.info(
            f"[SKIP-BUY] {symbol}: modal Rp {trade_amt:,.0f} < min Rp {Config.MIN_ORDER_IDR:,.0f} "
            f"(saldo Rp {available:,.0f}). Dilewati diam-diam."
        )
        return False

    if available < trade_amt:
        logger.info(f"Saldo IDR tidak cukup: Rp {available:,.0f} < Rp {trade_amt:,.0f}. Skip buy {symbol}.")
        return False

    # Validasi pair IDR aktif di Tokocrypto (defense-in-depth)
    if not check_market_active(symbol):
        logger.warning(f"Pair {symbol} tidak tersedia/aktif di Tokocrypto! Skip buy.")
        return False

    logger.info(f"BUY {symbol} | Skor: {score}/100 | Rp {price:,.2f} | Modal: Rp {trade_amt:,.0f} (dari saldo Rp {available:,.0f}) | Alasan: {reason}")
    result = place_order(symbol, "buy", amount_idr=trade_amt, price=price)

    if result.get("error"):
        err = result["error"]
        # Anti-spam: min notional error cukup di-log, jangan kirim Telegram
        if "min" in err.lower() or "notional" in err.lower() or "20" in err:
            logger.info(f"Buy {symbol} diblokir min notional: {err}")
        else:
            logger.warning(f"Buy gagal {symbol}: {err}")
        return False

    filled_qty   = result.get("amount", trade_amt / price if price > 0 else 0)
    filled_price = result.get("price") or price

    risk.record_trade(symbol, "buy", filled_qty, filled_price, result.get("id"))

    # ── TP Adaptif: naikkan TP kalau momentum kuat (profil Moderat) ──
    tp_pct = Config.TAKE_PROFIT_PERCENT
    if Config.TP_ADAPTIVE_ENABLED:
        ema_gap = abs(coin.get("ema_gap_pct", 0))
        if ema_gap >= Config.TP_ADAPTIVE_EMA_GAP_TRIGGER:
            # Scale: baseline → max_TP secara linear dengan EMA gap
            # Mis. gap 1% → baseline + 0%, gap 3% → ~max_TP
            scale = min(1.0, (ema_gap - Config.TP_ADAPTIVE_EMA_GAP_TRIGGER) / 2.0)
            tp_pct = Config.TAKE_PROFIT_PERCENT + (
                Config.TP_ADAPTIVE_MAX_PERCENT - Config.TAKE_PROFIT_PERCENT
            ) * scale
            logger.info(
                f"TP adaptif aktif: {tp_pct:.2f}% (EMA gap {ema_gap:.2f}%, baseline {Config.TAKE_PROFIT_PERCENT}%)"
            )

    risk.open_position(symbol, filled_qty, filled_price, value_idr=trade_amt, take_profit_pct=tp_pct)

    logger.info(
        f"BELI BERHASIL: {symbol} | {filled_qty:.6f} crypto | "
        f"Rp {filled_price:,.2f}/unit | Total: Rp {trade_amt:,.2f}"
    )
    status = risk.get_status(available)
    notifier.notify_trade(
        "buy", symbol, filled_qty, filled_price, score, reason,
        dry_run=result.get("dry_run", False),
        compound=status.get("realized_pnl"),
    )
    return True


# ------------------------------------------------------------
# MANUAL COMMANDS -- Force Buy / Force Sell
# ------------------------------------------------------------

def run_force_buy(risk: RiskManager, symbol_input: str):
    """MANUAL: Paksa beli coin tertentu dari GitHub Actions."""
    sym = symbol_input.strip().upper()
    if "/" not in sym:
        sym = f"{sym}/{Config.BASE_CURRENCY}"

    logger.info(f"[FORCE BUY] Request: {sym}")
    notifier.send_telegram(f"[FORCE BUY] Request masuk untuk <b>{sym}</b>...")

    try:
        bal = get_balance()
        available_balance = bal["quote"]["free"]
    except Exception as e:
        notifier.notify_error(
            f"Force buy gagal ambil saldo: {e}",
            context=f"force_buy({sym}) get_balance()",
            force_send=True  # error kritis: API down
        )
        return

    can, reason = risk.can_trade(available_balance)
    if not can:
        msg = f"Force buy dibatalkan: {reason}"
        logger.warning(msg)
        # Bisa jadi INFO (pause proteksi) atau WARNING (cooldown). Cek keyword.
        if "Emergency stop" in reason or "Daily loss" in reason or "Win rate" in reason:
            notifier.notify_info(f"Force buy tidak bisa diproses:\n{reason}")
        else:
            notifier.notify_warning(f"Force buy dibatalkan:\n{reason}")
        return

    # Ambil harga terkini
    price = fetch_ticker_price(sym)
    if price <= 0:
        candles = fetch_candles(sym, timeframe="5m")
        if candles:
            price = candles[-1]["close"]

    if price <= 0:
        notifier.notify_warning(
            f"Force buy gagal: tidak bisa dapat harga untuk {sym}.\n"
            f"Possibly pair delisted atau API error."
        )
        return

    # Ambil score untuk info
    score = 0
    try:
        candles = fetch_candles(sym, timeframe="5m")
        if candles and len(candles) >= 30:
            result_score = score_coin(candles)
            score = result_score["score"]
    except Exception:
        pass

    coin = {"symbol": sym, "price": price, "score": score, "falling_knife": False}
    _execute_buy(risk, coin, f"Manual force buy dari GitHub | Score: {score}/100", bypass_ai=True)


def run_force_sell(risk: RiskManager):
    """MANUAL: Jual semua posisi terbuka sekarang juga."""
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
        price  = fetch_ticker_price(symbol)
        if price <= 0:
            price = pos["entry_price"]

        action = {
            "symbol": symbol,
            "amount": amount,
            "price":  price,
            "reason": "Manual force sell dari GitHub",
        }
        _execute_sell(risk, action)
        time.sleep(1)


# ------------------------------------------------------------
# MAIN RUN -- Auto Trading
# ------------------------------------------------------------

def run(dry_run_override=None, scan_only=False, force_buy_symbol=None, force_sell=False, quick_check=False):
    if dry_run_override is not None:
        Config.DRY_RUN = dry_run_override

    mode = "[DRY RUN]" if Config.DRY_RUN else "[LIVE]"
    if quick_check:
        mode += " [QUICK]"
    logger.info(
        f"CuanBot v4 {mode} | "
        f"TP: {Config.TAKE_PROFIT_PERCENT}% | SL: {Config.STOP_LOSS_PERCENT}% | "
        f"Trailing: {'ON' if Config.TRAILING_STOP_ENABLED else 'OFF'} | "
        f"Compound: {'ON' if Config.AUTO_COMPOUND else 'OFF'}"
    )

    # Init
    try:
        # -- Cek Saldo IDR --
        available_balance = check_idr_balance()
        if available_balance < Config.MIN_ORDER_IDR:
            logger.warning(
                f"Saldo IDR tidak cukup: Rp {available_balance:,.0f} < min Rp {Config.MIN_ORDER_IDR:,.0f}"
            )
            # Kondisi normal (perlu top up), bukan error sistem. Pakai INFO.
            notifier.notify_info(
                f"Saldo IDR Anda (Rp {available_balance:,.0f}) kurang dari minimum "
                f"(Rp {Config.MIN_ORDER_IDR:,.0f}).\n"
                f"💡 Silakan top up saldo Tokocrypto untuk mulai trading."
            )
            return

        risk = RiskManager()

        # -- Snapshot saldo awal hari --
        if risk.state.get("day_start_balance") is None:
            risk.state["day_start_balance"] = available_balance
            risk.save_state()
            logger.info(f"Day start balance diset: Rp {available_balance:,.0f}")

    except Exception as e:
        logger.error(f"Init gagal: {e}")
        notifier.notify_error(f"Init gagal: {e}", context="startup", force_send=True)
        return

    # ── Start WebSocket real-time ────────────────────────────────────
    if not scan_only:
        try:
            ws_start()
            logger.info(f"[WSS] WebSocket started (market + account). Fallback ke polling jika tidak ada data.")
        except Exception as e:
            logger.warning(f"[WSS] Gagal start WebSocket: {e}. Fallback ke polling.")

    # ── Clock sync check ────────────────────────────────────────────
    drift = get_clock_drift_ms()
    if abs(drift) > 1000:
        logger.warning(f"[CLOCK] Drift {drift}ms — bisa menyebabkan signature error")
    else:
        logger.debug(f"[CLOCK] Drift OK: {drift}ms")

    # ── Startup notif (skip di quick mode, anti-spam) ──────────────
    if not quick_check and risk.should_send_startup_notif():
        valid_pairs = len(get_trade_pairs())
        notifier.notify_startup(num_pairs=valid_pairs, market_info=get_market_summary())

    status = risk.get_status(available_balance)
    logger.info(
        f"Status: {status['trades_today']}/{status['max_trades']} trades | "
        f"{status['open_positions']}/{status['max_positions']} posisi | "
        f"Modal/trade: Rp {status['current_trade_amount']:,.0f} | "
        f"PnL hari ini: Rp {status['daily_pnl']:,.0f} | "
        f"Realized PnL: Rp {status['realized_pnl']:,.0f}"
    )

    # -- MANUAL: Force Sell ------------------------------------------------
    if force_sell:
        logger.info("Mode: FORCE SELL semua posisi")
        run_force_sell(risk)
        risk.save_state()
        return

    # -- MANUAL: Force Buy -------------------------------------------------
    if force_buy_symbol:
        logger.info(f"Mode: FORCE BUY {force_buy_symbol}")
        run_force_buy(risk, force_buy_symbol)
        risk.save_state()
        return

    # -- PHASE 1: Reconcile state vs exchange balance ----------------------
    if not Config.DRY_RUN and not scan_only:
        try:
            balance        = get_balance()
            current_prices = {}
            for asset in balance["holdings"]:
                pair  = f"{asset}/{Config.BASE_CURRENCY}"
                price = fetch_ticker_price(pair)
                if price > 0:
                    current_prices[pair] = price

            risk.reconcile_with_balance(balance["holdings"], current_prices)

        except Exception as e:
            logger.warning(f"Reconcile gagal (lanjut): {e}")

    # -- PHASE 2: SWEEP WALLET -- Kelola semua aset di dompet ----------------
    if not scan_only:
        sweep_wallet(risk)

    # -- PHASE 3: EXIT -- Cek posisi terbuka --------------------------------
    sold = False
    if not scan_only:
        sold = check_and_sell_positions(risk)

    # -- QUICK MODE: skip scan & entry, langsung selesai -------------------
    if quick_check:
        risk.save_state()
        logger.info("Quick check selesai (skip scan & entry)")
        return

    # -- PHASE 4: SCAN ------------------------------------------------------
    rankings = scan_all_coins()
    if not rankings:
        logger.warning("Tidak ada coin yang bisa di-scan")
        notifier.notify_error(
            "Gagal melakukan scan coin (0 coin berhasil di-scan).\n"
            "Kemungkinan koneksi internet terganggu, rate limit Tokocrypto API, atau IP diblok.",
            context="run() Phase 3 — scan_all_coins returned empty"
        )
        risk.save_state()
        return

    # -- PHASE 5: ENTRY -- Beli koin terbaik dari hasil scan --------------
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

    # -- PHASE 4: ENTRY -- Beli beberapa kandidat hingga posisi terisi -----
    # Diversifikasi: isi slot yang kosong dengan top kandidat BUY (bukan hanya top 1)
    bought = False
    current_positions = len(risk.state.get("positions", []))
    max_positions     = Config.get_max_positions(available_balance)
    slots_available   = max_positions - current_positions

    if slots_available > 0:
        buy_candidates = [
            c for c in rankings
            if c.get("action") == "BUY" and not c.get("falling_knife", False)
        ]
        # Ambil sebanyak slot yang tersedia, tapi tetap hormati cooldown & risk gate
        for i, coin in enumerate(buy_candidates[:slots_available]):
            # Cek ulang risk gate tiap iterasi (cooldown berlaku setelah buy sukses)
            can, reason = risk.can_trade(available_balance)
            if not can:
                logger.info(f"Stop diversifikasi: {reason}")
                break
            slot_label = f"[slot {i+1}/{slots_available}] " if slots_available > 1 else ""
            logger.info(f"{slot_label}Coba beli {coin['symbol']} (skor {coin.get('score', 0)})")
            if _execute_buy(risk, coin, coin.get("reason", "Diversifikasi entry")):
                bought = True
                # Setelah buy sukses, cooldown aktif. Stop loop karena iterasi
                # berikutnya pasti diblok cooldown.
                break
    else:
        logger.info(f"Posisi penuh ({current_positions}/{max_positions}), skip beli")

    # -- PHASE 5: Save & Summary --------------------------------------------
    risk.save_state()
    final = risk.get_status(available_balance)

    # Throttle summary: kirim max 1x/jam, KECUALI ada trade baru di run ini
    last_summary = risk.state.get("last_summary_time")
    now_utc = datetime.now(timezone.utc)
    summary_cooldown = True
    if last_summary:
        try:
            last_dt = datetime.fromisoformat(str(last_summary))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            if now_utc - last_dt >= timedelta(hours=1):
                summary_cooldown = False
        except Exception:
            summary_cooldown = False
    else:
        summary_cooldown = False

    # Kirim summary kalau: (1) ada trade baru, atau (2) sudah > 1 jam
    had_activity = sold or bought
    if had_activity or not summary_cooldown:
        notifier.notify_daily_summary(final)
        risk.state["last_summary_time"] = now_utc.isoformat()
        risk.save_state()

    logger.info(
        f"Selesai: {final['trades_today']} trades | "
        f"PnL: Rp {final['daily_pnl']:,.0f} | "
        f"Win rate: {final['win_rate']}%"
    )


# ------------------------------------------------------------
# Entry Point
# ------------------------------------------------------------

if __name__ == "__main__":
    dry_run          = None
    scan_only        = False
    force_buy_symbol = None
    force_sell       = False
    quick_check      = False

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
        elif arg == "--quick":
            quick_check = True
            dry_run = False
        elif arg == "--force-sell":
            force_sell = True
            dry_run = False
        elif arg == "--force-buy":
            i += 1
            if i < len(args):
                force_buy_symbol = args[i]
                dry_run = False
        i += 1

    run(
        dry_run_override=dry_run,
        scan_only=scan_only,
        force_buy_symbol=force_buy_symbol,
        force_sell=force_sell,
        quick_check=quick_check,
    )
