"""
CuanBot v2 - Smart Crypto Investment Manager
"""

import sys, os
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv()

import logging, time
from datetime import datetime
from config import Config
from bot.exchange import create_exchange, get_idr_pairs, fetch_candles, get_balance, place_order
from bot.scanner import score_coin, score_coin_multi_tf
from bot.risk import RiskManager
from bot import notifier

log_dir = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, f"{datetime.utcnow().strftime('%Y-%m-%d')}.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("cuanbot")


def scan_all_coins(exchange) -> list:
    pairs = get_idr_pairs()
    if not pairs:
        return []

    results = []
    scanned = 0
    for pair in pairs:
        try:
            # Primary timeframe first
            candles_5m = fetch_candles(exchange, pair, timeframe="5m")
            if not candles_5m or len(candles_5m) < 30:
                time.sleep(0.3)
                continue

            # Quick score on primary TF
            quick = score_coin(candles_5m)
            
            # Only fetch additional timeframes if promising (score > 40)
            if quick["score"] > 40:
                candles_by_tf = {"5m": candles_5m}
                for tf in ["15m", "1h"]:
                    c = fetch_candles(exchange, pair, timeframe=tf)
                    if c and len(c) >= 30:
                        candles_by_tf[tf] = c
                    time.sleep(0.3)

                if len(candles_by_tf) >= 2:
                    analysis = score_coin_multi_tf(candles_by_tf)
                else:
                    analysis = quick
            else:
                analysis = quick

            analysis["symbol"] = pair
            results.append(analysis)
            scanned += 1
            
            # Rate limit: sleep between coins
            time.sleep(0.5)

        except Exception as e:
            logger.warning(f"Scan error {pair}: {e}")
            time.sleep(1)

    results.sort(key=lambda x: x["score"], reverse=True)
    logger.info(f"Scanned {scanned}/{len(pairs)} coins successfully")
    return results


def execute_buy(exchange, risk, coin) -> bool:
    symbol = coin["symbol"]
    price = coin["price"]
    trade_amount = Config.get_trade_amount()
    if price <= 0: return False
    amount = trade_amount / price
    balance = get_balance(exchange)
    available = balance["base"]["free"]
    if available < trade_amount:
        logger.warning(f"Insufficient balance: {available} < {trade_amount}")
        return False
    result = place_order(exchange, symbol, "buy", amount, price)
    if result.get("error"):
        logger.error(f"Buy failed: {result['error']}")
        notifier.notify_error(f"Buy gagal: {symbol}\n{result['error']}")
        return False
    risk.record_trade(symbol, "buy", amount, price, result.get("id"))
    risk.open_position(symbol, amount, price)
    logger.info(f"BUY {symbol}: {amount:.8f} @ Rp {price:,.0f}")
    status = risk.get_status()
    notifier.notify_trade("buy", symbol, amount, price, coin["score"], coin["reason"],
                          dry_run=result.get("dry_run", False), compound=status.get("compound_profit"))
    return True


def execute_sell(exchange, risk, symbol, amount, price, reason) -> bool:
    result = place_order(exchange, symbol, "sell", amount, price)
    if result.get("error"):
        logger.error(f"Sell failed: {result['error']}")
        notifier.notify_error(f"Sell gagal: {symbol}\n{result['error']}")
        return False
    pnl = risk.close_position(symbol, price)
    risk.record_trade(symbol, "sell", amount, price, result.get("id"))
    logger.info(f"SELL {symbol}: {amount:.8f} @ Rp {price:,.0f} | {reason} | PnL: {pnl.get('pnl_pct', 0):+.2f}%")
    status = risk.get_status()
    notifier.notify_trade("sell", symbol, amount, price, 0, f"{reason} | PnL: {pnl.get('pnl_pct', 0):+.2f}%",
                          dry_run=result.get("dry_run", False), pnl=pnl, compound=status.get("compound_profit"))
    return True


def run(dry_run_override=None, scan_only=False):
    mode_str = "DRY RUN" if (dry_run_override is True or (dry_run_override is None and Config.DRY_RUN)) else "LIVE"
    logger.info(f"CuanBot v2 [{mode_str}] | Trailing: {'ON' if Config.TRAILING_STOP_ENABLED else 'OFF'} | Compound: {'ON' if Config.AUTO_COMPOUND else 'OFF'}")

    if dry_run_override is not None:
        Config.DRY_RUN = dry_run_override

    try:
        exchange = create_exchange()
        risk = RiskManager()
    except Exception as e:
        logger.error(f"Init failed: {e}")
        notifier.notify_error(f"Init gagal: {e}")
        return

    notifier.notify_startup()
    status = risk.get_status()
    logger.info(f"Trades: {status['trades_today']}/{status['max_trades']} | Positions: {status['open_positions']} | PnL: Rp {status['total_pnl']:,.0f} | Compound: Rp {status.get('compound_profit', 0):,.0f}")

    # Check existing positions
    if status["open_positions"] > 0 and not scan_only:
        positions = risk.state.get("positions", [])
        current_prices = {}
        for pos in positions:
            try:
                ticker = exchange.fetch_ticker(pos["symbol"])
                current_prices[pos["symbol"]] = ticker.get("last", 0)
            except: pass
        for action in risk.check_positions(current_prices):
            can, _ = risk.can_trade()
            if can or action["priority"] == "HIGH":
                execute_sell(exchange, risk, action["symbol"], action["amount"], action["price"], action["reason"])

    # Scan
    rankings = scan_all_coins(exchange)
    if not rankings:
        logger.warning("No coins scanned")
        risk.save_state()
        return

    buy_signals = [c for c in rankings if c["action"] == "BUY"]
    logger.info(f"Top: {rankings[0]['symbol']} ({rankings[0]['score']}/100) | BUY signals: {len(buy_signals)}")
    notifier.notify_scan_results(rankings)

    if scan_only:
        risk.save_state()
        return

    # Execute
    if buy_signals:
        can, reason = risk.can_trade()
        if can:
            logger.info(f"Buying: {buy_signals[0]['symbol']} (Score: {buy_signals[0]['score']})")
            execute_buy(exchange, risk, buy_signals[0])

    # Check sell for holdings
    balance = get_balance(exchange)
    for asset, amounts in balance.get("holdings", {}).items():
        if asset == Config.BASE_CURRENCY: continue
        pair = f"{asset}/{Config.BASE_CURRENCY}"
        for coin in rankings:
            if coin["symbol"] == pair and coin["action"] == "SELL" and coin["score"] <= Config.MIN_SCORE_TO_HOLD:
                amt = amounts.get("free", 0)
                if amt > 0:
                    execute_sell(exchange, risk, pair, amt, coin["price"], coin["reason"])

    risk.save_state()
    final = risk.get_status()
    notifier.notify_daily_summary(final)
    logger.info(f"Done: {final['trades_today']} trades | PnL: Rp {final['daily_pnl']:,.0f}")


if __name__ == "__main__":
    dry_run = None
    scan_only = False
    if "--dry-run" in sys.argv: dry_run = True
    if "--live" in sys.argv: dry_run = False
    if "--scan-only" in sys.argv: scan_only = True
    run(dry_run_override=dry_run, scan_only=scan_only)
