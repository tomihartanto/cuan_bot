"""
CuanBot v4 - Telegram Notifications
Notifikasi dengan rate limiting, klasifikasi severity, dan logging debug.

Klasifikasi notifikasi:
- ERROR    : Kegagalan sistem (API down, exception tak terduga). Kirim + rate limit.
- WARNING  : Kondisi perlu perhatian (min notional, pair tidak aktif). Rate limit agresif.
- INFO     : Status bot normal (pause, cooldown, saldo). Kirim sekali, rate limit ketat.
- TRADE    : Eksekusi trade (buy/sell). Selalu kirim (tidak di-rate limit).
- SUMMARY  : Ringkasan sesi. Throttled di main.py.
"""

import hashlib
import requests
import logging
import time as _time
from collections import defaultdict
from config import Config

logger = logging.getLogger("cuanbot")


# ── Rate Limiter ────────────────────────────────────────────────────
# Key = hash(message); Value = last_sent_timestamp
_notification_history = defaultdict(list)

# Cooldown per kategori (detik). Pesanan identik tidak dikirim ulang dalam window ini.
RATE_LIMIT_SECONDS = {
    "ERROR":   1800,   # 30 menit — error sistem yang sama
    "WARNING": 3600,   # 1 jam    — warning kondisi market
    "INFO":    7200,   # 2 jam    — status info (saldo, pause)
    # TRADE & SUMMARY: tidak di-rate limit (handled by caller)
}


def _is_rate_limited(category: str, dedup_key: str) -> bool:
    """
    Cek apakah pesan dengan kategori+key tertentu masih dalam cooldown.
    Return True jika pesan harus DITAHAN (rate limited).
    """
    if category not in RATE_LIMIT_SECONDS:
        return False
    cooldown = RATE_LIMIT_SECONDS[category]
    now = _time.time()
    key = f"{category}:{dedup_key}"
    last_sent = _notification_history[key]
    # Buang history yang sudah过期 (> 2x cooldown)
    cutoff = now - (cooldown * 2)
    _notification_history[key] = [t for t in last_sent if t > cutoff]
    if _notification_history[key]:
        last = _notification_history[key][-1]
        if (now - last) < cooldown:
            return True
    return False


def _mark_sent(category: str, dedup_key: str):
    """Catat bahwa pesan sudah dikirim untuk rate limiting."""
    key = f"{category}:{dedup_key}"
    _notification_history[key].append(_time.time())


def _make_dedup_key(message: str) -> str:
    """
    Buat key dedup dari pesan. Abaikan angka & simbol agar "Saldo IDR Rp 9,000"
    dan "Saldo IDR Rp 8,500" dianggap pesan yang sama (sama penyebabnya).
    """
    import re
    # Hapus angka & format mata uang
    normalized = re.sub(r"[\d,.\-+/]+", "", message)
    return hashlib.md5(normalized.encode()).hexdigest()[:12]


# ── Core Sender ─────────────────────────────────────────────────────

def send_telegram(message: str, parse_mode: str = "HTML") -> bool:
    if not Config.TELEGRAM_BOT_TOKEN or not Config.TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"
        resp = requests.post(
            url,
            json={"chat_id": Config.TELEGRAM_CHAT_ID, "text": message, "parse_mode": parse_mode},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        logger.warning(f"Telegram send failed: {e}")
        return False


def _send_categorized(category: str, message: str, force_send: bool = False,
                      dedup_key_override: str = None) -> bool:
    """
    Kirim pesan dengan klasifikasi severity & rate limiting.

    category: "ERROR" | "WARNING" | "INFO"
    force_send: True = bypass rate limit (untuk error kritis yang harus dikirim)
    dedup_key_override: key custom untuk dedup (mis. "min_notional:sell:DOGE/IDR")
                        agar pesan yang beda tapi semantik sama tetap di-rate limit.
    """
    dedup_key = dedup_key_override or _make_dedup_key(message)

    if not force_send and _is_rate_limited(category, dedup_key):
        logger.debug(
            f"[NOTIF-SUPPRESSED] category={category} key={dedup_key} "
            f"(rate limited, tidak dikirim ulang)"
        )
        return False

    ok = send_telegram(message)
    if ok:
        _mark_sent(category, dedup_key)
        logger.info(
            f"[NOTIF-SENT] category={category} key={dedup_key} "
            f"| length={len(message)} chars"
        )
    else:
        logger.warning(f"[NOTIF-FAILED] category={category} key={dedup_key} — Telegram reject/error")
    return ok


# ── Public API ──────────────────────────────────────────────────────

def notify_trade(side, symbol, amount, price, score, reason, dry_run=False, pnl=None, compound=None):
    """Notifikasi trade. Tidak di-rate limit (setiap trade penting)."""
    emoji = "🟢" if side == "buy" else "🔴"
    mode  = "🧪 SIMULASI" if dry_run else "🔴 LIVE"
    value = amount * price

    msg = (
        f"{emoji} <b>{side.upper()}</b> {symbol}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Harga  : Rp {price:,.0f}\n"
        f"Jumlah : {amount:.6f}\n"
        f"Nilai  : Rp {value:,.0f}\n"
        f"Skor   : {score}/100\n"
        f"Sinyal : {reason}\n"
        f"Mode   : {mode}"
    )
    if pnl:
        pnl_pct = pnl.get("pnl_pct", 0)
        pnl_idr = pnl.get("pnl_idr", 0)
        icon    = "✅" if pnl_pct >= 0 else "❌"
        msg += f"\n\n{icon} PnL: <b>{pnl_pct:+.2f}%</b> (Rp {pnl_idr:+,.0f})"
        if pnl.get("trailing_used"):
            msg += " | 📈 Trailing stop"
    if compound is not None:
        msg += f"\n💰 Pool compound: Rp {compound:,.0f}"
    # Trade selalu dikirim (penting untuk user)
    logger.info(f"[NOTIF-TRADE] {side} {symbol} amt={amount:.6f} @ Rp {price:,.0f}")
    send_telegram(msg)


def notify_scan_results(rankings: list, top_n: int = 5):
    if not Config.NOTIFY_SCAN:
        return
    lines = ["🔍 <b>TOP COIN SCAN</b>", "━━━━━━━━━━━━━━━━"]
    for i, c in enumerate(rankings[:top_n]):
        e = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(c["action"], "⚪")
        lines.append(
            f"{i+1}. {e} <b>{c['symbol']}</b> — {c['score']}/100\n"
            f"   Rp {c['price']:,.0f} | {c['reason']}"
        )
    send_telegram("\n".join(lines))


def notify_daily_summary(status: dict):
    pos_lines = ""
    for p in status.get("positions", []):
        pos_lines += f"\n   • {p['symbol']} entry Rp {p['entry_price']:,.0f}"

    pnl_today   = status["daily_pnl"]
    pnl_total   = status["total_pnl"]
    e_today     = "📈" if pnl_today >= 0 else "📉"
    e_total     = "📈" if pnl_total >= 0 else "📉"
    win_rate    = status["win_rate"]
    cons_loss   = status.get("consecutive_losses", 0)
    stop_warn   = f"\n🛑 <b>WARNING:</b> {cons_loss}x rugi berturut-turut!" if cons_loss >= 2 else ""

    compound_str = f"Rp {status.get('realized_pnl', 0):,.0f}" if Config.AUTO_COMPOUND else "OFF"
    trade_amt    = f"Rp {status.get('current_trade_amount', 0):,.0f}"
    max_pos      = status.get("max_positions", "-")

    msg = (
        f"📊 <b>RINGKASAN SESI</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🔢 Trade: {status['trades_today']}/{status['max_trades']}\n"
        f"📂 Posisi: {status['open_positions']}/{max_pos}{pos_lines}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{e_today} PnL hari ini : <b>Rp {pnl_today:,.0f}</b>\n"
        f"{e_total} PnL total    : <b>Rp {pnl_total:,.0f}</b>\n"
        f"🎯 Win rate   : {win_rate}% ({status.get('total_wins',0)}W/{status.get('total_losses',0)}L)\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🔄 Realized PnL  : {compound_str}\n"
        f"💵 Modal per trade: {trade_amt}\n"
        f"📈 Trailing Stop : {'ON' if Config.TRAILING_STOP_ENABLED else 'OFF'}"
        f"{stop_warn}"
    )
    send_telegram(msg)


def notify_error(error_msg: str, context: str = None, force_send: bool = False):
    """
    Notifikasi ERROR (kegagalan sistem). Di-rate limit 30 menit untuk pesan serupa.

    Args:
        error_msg: Pesan error utama
        context: Info tambahan (function/symbol/operation) untuk debugging
        force_send: True = bypass rate limit (untuk error kritis)
    """
    context_line = f"\n🔍 Context: <code>{context}</code>" if context else ""
    msg = (
        f"❌ <b>ERROR SISTEM</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{error_msg}"
        f"{context_line}"
    )
    _send_categorized("ERROR", msg, force_send=force_send)


def notify_warning(warning_msg: str, context: str = None):
    """
    Notifikasi WARNING (kondisi market yang perlu perhatian tapi bukan error sistem).
    Di-rate limit 1 jam. Contoh: min notional, pair tidak aktif.

    GUNAKAN INI alih-alih notify_error untuk kondisi yang BUKAN error sistem.
    """
    context_line = f"\n🔍 Context: <code>{context}</code>" if context else ""
    msg = (
        f"⚠️ <b>PERHATIAN</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{warning_msg}"
        f"{context_line}"
    )
    _send_categorized("WARNING", msg)


def notify_info(info_msg: str, context: str = None):
    """
    Notifikasi INFO (status bot normal). Di-rate limit 2 jam.
    Contoh: bot pause karena emergency stop, cooldown aktif, saldo tidak cukup.

    GUNAKAN INI alih-alih notify_error untuk status bot yang normal/diharapkan.
    """
    context_line = f"\n🔍 Context: <code>{context}</code>" if context else ""
    msg = (
        f"ℹ️ <b>INFO BOT</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{info_msg}"
        f"{context_line}"
    )
    _send_categorized("INFO", msg)


def notify_min_notional(side: str, symbol: str, value_idr: float,
                        min_idr: float, extra: str = None):
    """
    Notifikasi WARNING bahwa transaksi ditolak karena nominal di bawah minimum.

    Di-rate limit 1 jam per kombinasi symbol+side (dedup).
    """
    side_label = "PENJUALAN" if side == "sell" else "PEMBELIAN"
    emoji_side = "🔴" if side == "sell" else "🟢"

    msg = (
        f"⚠️ {emoji_side} <b>{side_label} DIBLOKIR — NOMINAL MINIMUM</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Coin   : {symbol}\n"
        f"Nominal saat ini : <b>Rp {value_idr:,.0f}</b>\n"
        f"Minimum {side_label} : <b>Rp {min_idr:,.0f}</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"ℹ️ Persyaratan nominal minimum Tokocrypto:\n"
        f"   • Pembelian  : &gt;= Rp {min_idr:,.0f}\n"
        f"   • Penjualan  : &gt;= Rp {min_idr:,.0f}\n"
        f"     (jumlah crypto × harga)"
    )
    if extra:
        msg += f"\n📋 {extra}"
    msg += (
        f"\n💡 Tips: Akumulasi crypto hingga nilainya mencapai minimum, "
        f"atau tingkatkan modal pembelian."
    )
    # Pakai WARNING category dengan dedup key spesifik (symbol+side)
    # agar tidak spam per cycle meskipun nominal/extra berbeda
    _send_categorized(
        "WARNING", msg,
        dedup_key_override=f"min_notional:{side}:{symbol}"
    )


def notify_startup(num_pairs: int = None):
    mode     = "🧪 DRY RUN" if Config.DRY_RUN else "🔴 LIVE TRADING"
    trail    = f"ON ({Config.TRAILING_PERCENT}%, aktif di +{Config.TRAILING_ACTIVATION}%)"  if Config.TRAILING_STOP_ENABLED else "OFF"
    compound = "ON" if Config.AUTO_COMPOUND else "OFF"
    scan_info = f"{num_pairs} pair IDR likuid" if num_pairs else "0 pair"

    send_telegram(
        f"🤖 <b>CuanBot v4 — Siap Trading!</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Mode     : {mode}\n"
        f"Modal    : Rp {Config.INITIAL_TRADE_AMOUNT:,.0f}\n"
        f"Target   : TP {Config.TAKE_PROFIT_PERCENT}% | SL {Config.STOP_LOSS_PERCENT}%\n"
        f"Cooldown : {Config.COOLDOWN_MINUTES} menit\n"
        f"Max/hari : {Config.MAX_TRADES_PER_DAY} trades\n"
        f"Scan     : {scan_info} | {', '.join(Config.TIMEFRAMES)}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📈 Trailing: {trail}\n"
        f"🔄 Compound: {compound}\n"
        f"🛡️ Emergency stop: setelah {Config.EMERGENCY_STOP_LOSSES}x rugi berturut"
    )


# ── Utility untuk debugging ─────────────────────────────────────────

def get_notification_stats() -> dict:
    """Return statistik notifikasi untuk debugging (berapa yang ditahan vs dikirim)."""
    return {
        "tracked_keys": len(_notification_history),
        "categories_cooldown_seconds": RATE_LIMIT_SECONDS.copy(),
    }
