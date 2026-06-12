"""
CuanBot - Telegram Notifications v2
"""

import requests
import logging
from config import Config

logger = logging.getLogger("cuanbot")


def send_telegram(message: str, parse_mode: str = "HTML") -> bool:
    if not Config.TELEGRAM_BOT_TOKEN or not Config.TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={"chat_id": Config.TELEGRAM_CHAT_ID, "text": message, "parse_mode": parse_mode}, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.warning(f"Telegram failed: {e}")
        return False


def notify_trade(side, symbol, amount, price, score, reason, dry_run=False, pnl=None, compound=None):
    emoji = "🟢" if side == "buy" else "🔴"
    mode = "SIMULASI" if dry_run else "LIVE"
    msg = f"{emoji} <b>{side.upper()}</b> {symbol}\n━━━━━━━━━━━━━━━━\nHarga: Rp {price:,.0f}\nJumlah: {amount:.8f}\nNilai: Rp {amount * price:,.0f}\nSkor: {score}/100\nAlasan: {reason}\nMode: {mode}"
    if pnl:
        msg += f"\n\n📊 PnL: {pnl.get('pnl_pct', 0):+.2f}% (Rp {pnl.get('pnl_idr', 0):+,})"
    if compound:
        msg += f"\n💰 Compound pool: Rp {compound:,.0f}"
    send_telegram(msg)


def notify_scan_results(rankings: list, top_n: int = 5):
    if not Config.NOTIFY_SCAN: return
    lines = ["🔍 <b>HASIL SCAN</b>", "━━━━━━━━━━━━━━━━"]
    for i, c in enumerate(rankings[:top_n]):
        e = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(c["action"], "⚪")
        lines.append(f"{i+1}. {e} <b>{c['symbol']}</b> — {c['score']}/100 | Rp {c['price']:,.0f} | {c['reason']}")
    send_telegram("\n".join(lines))


def notify_daily_summary(status: dict):
    pos_text = ""
    for p in status.get("positions", []):
        pos_text += f"\n   {p['symbol']} @ Rp {p['entry_price']:,.0f}"
    e = "📈" if status["daily_pnl"] >= 0 else "📉"
    trail = "ON" if Config.TRAILING_STOP_ENABLED else "OFF"
    compound_str = f"Rp {status.get('compound_profit', 0):,.0f}" if Config.AUTO_COMPOUND else "OFF"
    trade_amt = f"Rp {status.get('current_trade_amount', 0):,.0f}"
    msg = (
        f"📊 <b>DAILY SUMMARY</b>\n━━━━━━━━━━━━━━━━\n"
        f"Trade: {status['trades_today']}/{status['max_trades']}\n"
        f"Open: {status['open_positions']}{pos_text}\n"
        f"{e} PnL today: Rp {status['daily_pnl']:,.0f}\n"
        f"💰 Total PnL: Rp {status['total_pnl']:,.0f}\n"
        f"🎯 Win rate: {status['win_rate']}%\n"
        f"🔢 Total trades: {status['total_trades']}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📈 Trailing Stop: {trail}\n"
        f"🔄 Auto Compound: {compound_str}\n"
        f"💵 Trade amount: {trade_amt}"
    )
    send_telegram(msg)


def notify_error(error_msg: str):
    send_telegram(f"❌ <b>ERROR</b>\n\n{error_msg}")


def notify_startup():
    mode = "DRY RUN" if Config.DRY_RUN else "🔴 LIVE"
    trail = "ON" if Config.TRAILING_STOP_ENABLED else "OFF"
    compound = "ON" if Config.AUTO_COMPOUND else "OFF"
    send_telegram(
        f"🤖 <b>CuanBot v2 Started</b>\n━━━━━━━━━━━━━━━━\n"
        f"Mode: {mode}\n"
        f"Modal: Rp {Config.INITIAL_TRADE_AMOUNT:,.0f}\n"
        f"Coins: {len(Config.SCAN_COINS)} pairs\n"
        f"Timeframes: {', '.join(Config.TIMEFRAMES)}\n"
        f"Min buy: {Config.MIN_SCORE_TO_BUY}/100\n"
        f"TP: {Config.TAKE_PROFIT_PERCENT}% | SL: {Config.STOP_LOSS_PERCENT}%\n"
        f"📈 Trailing Stop: {trail} ({Config.TRAILING_PERCENT}%)\n"
        f"🔄 Auto Compound: {compound}"
    )
