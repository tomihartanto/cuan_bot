"""
CuanBot v2 - Smart Crypto Investment Manager
Features: Trailing Stop, Auto Compound, Multi-Timeframe

Usage:
    python main.py              # Default mode (from .env)
    python main.py --dry-run    # Simulation
    python main.py --live       # Live trading
    python main.py --scan-only  # Scan only
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
    pairs = get_idr_pairs(exchange)
    if not pairs:
        logger.error("No tradeable pairs found!")
        return []

    results = []
    for pair in pairs:
        try:
            # Multi-timeframe scan
            candles_by_tf = {}
            for tf in Config.TIMEFRAMES:
                candles = fetch_candles(exchange, pair, timeframe=tf)
                if candles and len(candles) >= 30:
                    candles_by_tf[tf] = candles
                time.sleep(0.1)

            if not candles_by_tf:
                continue

            # Score with multi-TF
            if len(candles_by_tf) >= 2:
                analysis = score_coin_multi_tf(candles_by_tf)
            else:
                tf = list(candles_by_tf.keys())[0]
                analysis = score_coin(candles_by_tf[tf])

            analysis["symbol"] = pair
            results.append(analysis)
            time.sleep(0.2)

        except Exception as e:
            logger.warning(f"Error scanning {pair}: {e}")

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def execute_buy(exchange, risk: RiskManager, coin: dict) -> bool:
    symbol = coin["symbol"]
    price = coin["price"]
    trade_amount = Config.get_trade_amount()

    if price <= 0:
        return False

    amount = trade_amount / price

    balance = get_balance(exchange)
    available = balance["base"]["free"]
    if available < trade_amount:
        logger.warning(f"Insufficient balance: {available} < {trade_amount}")
        return False

    # Use actual available if less than target
    if available < trade_amount:
        trade_amount = available
        amount = trade_amount / price

    result = place_order(exchange, symbol, "buy", amount, price)

    if result.get("error"):
        logger.error(f"Buy failed: {result['error']}")
        notifier.notify_error(f"Buy gagal: {symbol}\n{result['error']}")
        return False

    risk.record_trade(symbol, "buy", amount, price, result.get("id"))
    risk.open_position(symbol, amount, price)

    logger.info(f"BUY {symbol}: {amount:.8f} @ Rp {price:,.0f} (Rp {trade_amount:,.0f})")
    status = risk.get_status()
    notifier.notify_trade("buy", symbol, amount, price, coin["score"], coin["reason"],
                          dry_run=result.get("dry_run", False), compound=status.get("compound_profit"))
    return True


def execute_sell(exchange, risk: RiskManager, symbol: str, amount: float, price: float, reason: str) -> bool:
    result = place_order(exchange, symbol, "sell", amount, price)

    if result.get("error"):
        logger.error(f"Sell failed: {result['error']}")
        notifier.notify_error(f"Sell gagal: {symbol}\n{result['error']}")
        return False

    pnl = risk.close_position(symbol, price)
    risk.record_trade(symbol, "sell", amount, price, result.get("id"))

    logger.info(f"SELL {symbol}: {amount:.8f} @ Rp {price:,.0f} | {reason} | PnL: {pnl.get('pnl_pct', 0):+.2f}%")
    status = risk.get_status()
    notifier.notify_trade("sell", symbol, amount, price, 0,
                          f"{reason} | PnL: {pnl.get('pnl_pct', 0):+.2f}%",
                          dry_run=result.get("dry_run", False),
                          pnl=pnl, compound=status.get("compound_profit"))
    return True


def run(dry_run_override=None, scan_only=False):
    logger.info("=" * 50)
    mode_str = "DRY RUN" if (dry_run_override is True or (dry_run_override is None and Config.DRY_RUN)) else "LIVE"
    logger.info(f"CuanBot v2 Starting... [{mode_str}]")
    logger.info(f"Trailing: {'ON' if Config.TRAILING_STOP_ENABLED else 'OFF'} | Compound: {'ON' if Config.AUTO_COMPOUND else 'OFF'}")
    logger.info(f"Timeframes: {Config.TIMEFRAMES}")
    logger.info("=" * 50)

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
    logger.info(f"Status: {status['trades_today']}/{status['max_trades']} trades | {status['open_positions']} positions | PnL: Rp {status['total_pnl']:,.0f} | Compound: Rp {status.get('compound_profit', 0):,.0f} | Trade amt: Rp {status.get('current_trade_amount', 0):,.0f}")

    # === Step 1: Check existing positions (with trailing stop) ===
    if status["open_positions"] > 0 and not scan_only:
        positions = risk.state.get("positions", [])
        current_prices = {}
        for pos in positions:
            symbol = pos["symbol"]
            try:
                ticker = exchange.fetch_ticker(symbol)
                current_prices[symbol] = ticker.get("last", 0)
            except:
                pass

        actions = risk.check_positions(current_prices)
        for action in actions:
            can, _ = risk.can_trade()
            if can or action["priority"] == "HIGH":
                execute_sell(exchange, risk, action["symbol"], action["amount"], action["price"], action["reason"])

    # === Step 2: Multi-TF scan ===
    rankings = scan_all_coins(exchange)

    if not rankings:
        logger.warning("No coins scanned")
        risk.save_state()
        return

    buy_signals = [c for c in rankings if c["action"] == "BUY"]
    logger.info(f"Top 3: {[(c['symbol'], c['score'], c['action']) for c in rankings[:3]]} | BUY signals: {len(buy_signals)}")

    notifier.notify_scan_results(rankings)

    if scan_only:
        risk.save_state()
        return

    # === Step 3: Execute trades ===
    if buy_signals:
        best = buy_signals[0]
        can, reason = risk.can_trade()
        if can:
            logger.info(f"Best: {best['symbol']} (Score: {best['score']}, Reason: {best['reason']})")
            execute_buy(exchange, risk, best)
        else:
            logger.info(f"Cannot trade: {reason}")

    # Check sell signals for holdings
    balance = get_balance(exchange)
    holdings = balance.get("holdings", {})
    for asset, amounts in holdings.items():
        if asset == Config.BASE_CURRENCY:
            continue
        pair = f"{asset}/{Config.BASE_CURRENCY}"
        for coin in rankings:
            if coin["symbol"] == pair and coin["action"] == "SELL" and coin["score"] <= Config.MIN_SCORE_TO_HOLD:
                holding_amount = amounts.get("free", 0)
                if holding_amount > 0:
                    execute_sell(exchange, risk, pair, holding_amount, coin["price"], coin["reason"])

    # === Step 4: Save & summary ===
    risk.save_state()
    final = risk.get_status()
    notifier.notify_daily_summary(final)
    logger.info(f"Done: {final['trades_today']} trades | PnL: Rp {final['daily_pnl']:,.0f} today | Compound: Rp {final.get('compound_profit', 0):,.0f} | Trade amt: Rp {final.get('current_trade_amount', 0):,.0f}")


if __name__ == "__main__":
    dry_run = None
    scan_only = False
    if "--dry-run" in sys.argv: dry_run = True
    if "--live" in sys.argv: dry_run = False
    if "--scan-only" in sys.argv: scan_only = True
    run(dry_run_override=dry_run, scan_only=scan_only)
