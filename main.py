"""
CuanBot - Smart Crypto Investment Manager
Main entry point

Usage:
    python main.py              # Full run: scan + trade (uses DRY_RUN from .env)
    python main.py --dry-run    # Simulation mode
    python main.py --live       # Live trading (real money!)
    python main.py --scan-only  # Only scan, no trading
"""

import sys
import os

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

# Load env
from dotenv import load_dotenv
load_dotenv()

import logging
import time
from datetime import datetime
from config import Config
from bot.exchange import create_exchange, get_idr_pairs, fetch_candles, get_balance, place_order
from bot.scanner import score_coin
from bot.risk import RiskManager
from bot import notifier

# === Setup Logging ===
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
        logger.info(f"Scanning {pair}...")
        candles = fetch_candles(exchange, pair)
        if not candles or len(candles) < 30:
            logger.warning(f"Skipping {pair} - insufficient data")
            continue

        analysis = score_coin(candles)
        analysis["symbol"] = pair
        results.append(analysis)
        time.sleep(0.3)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def execute_buy(exchange, risk: RiskManager, coin: dict) -> bool:
    symbol = coin["symbol"]
    price = coin["price"]
    amount_in_idr = Config.TRADE_AMOUNT_IDR

    if price <= 0:
        logger.error(f"Invalid price for {symbol}")
        return False

    amount = amount_in_idr / price

    balance = get_balance(exchange)
    available = balance["base"]["free"]
    if available < amount_in_idr:
        logger.warning(f"Insufficient balance: {available} < {amount_in_idr}")
        return False

    result = place_order(exchange, symbol, "buy", amount, price)

    if result.get("error"):
        logger.error(f"Buy failed: {result['error']}")
        notifier.notify_error(f"Buy gagal: {symbol}\n{result['error']}")
        return False

    risk.record_trade(symbol, "buy", amount, price, result.get("id"))
    risk.open_position(symbol, amount, price)

    logger.info(f"BUY {symbol}: {amount:.8f} @ Rp {price:,.0f}")
    notifier.notify_trade("buy", symbol, amount, price, coin["score"], coin["reason"], dry_run=result.get("dry_run", False))
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
    notifier.notify_trade("sell", symbol, amount, price, 0, f"{reason} | PnL: {pnl.get('pnl_pct', 0):+.2f}%", dry_run=result.get("dry_run", False))
    return True


def run(dry_run_override=None, scan_only=False):
    logger.info("=" * 50)
    logger.info("CuanBot Starting...")
    logger.info(f"Mode: {'DRY RUN' if (dry_run_override is True or (dry_run_override is None and Config.DRY_RUN)) else 'LIVE'}")
    logger.info(f"Time: {datetime.utcnow().isoformat()} UTC")
    logger.info("=" * 50)

    if dry_run_override is not None:
        Config.DRY_RUN = dry_run_override
    elif not Config.DRY_RUN:
        pass  # Use .env setting

    try:
        exchange = create_exchange()
        risk = RiskManager()
    except Exception as e:
        logger.error(f"Initialization failed: {e}")
        notifier.notify_error(f"Init gagal: {e}")
        return

    # Send startup notification
    notifier.notify_startup()

    # Step 1: Check existing positions
    status = risk.get_status()
    logger.info(f"Status: {status['trades_today']}/{status['max_trades']} trades | {status['open_positions']} positions | PnL: Rp {status['total_pnl']:,.0f}")

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
            can, reason = risk.can_trade()
            if can or action["priority"] == "HIGH":
                execute_sell(exchange, risk, action["symbol"], action["amount"], action["price"], action["reason"])

    # Step 2: Scan all coins
    rankings = scan_all_coins(exchange)

    if not rankings:
        logger.warning("No coins scanned successfully")
        return

    logger.info("\n" + "=" * 50)
    logger.info("TOP COINS:")
    for i, coin in enumerate(rankings[:5]):
        logger.info(f"  {i+1}. {coin['symbol']:15s} | Score: {coin['score']:3d}/100 | {coin['action']:4s} | Rp {coin['price']:>15,.0f} | {coin['reason']}")
    logger.info("=" * 50)

    # Send scan results
    notifier.notify_scan_results(rankings)

    if scan_only:
        logger.info("Scan-only mode, skipping trades")
        risk.save_state()
        return

    # Step 3: Execute trades
    best = rankings[0]
    if best["action"] == "BUY" and best["score"] >= Config.MIN_SCORE_TO_BUY:
        can, reason = risk.can_trade()
        if can:
            logger.info(f"Best candidate: {best['symbol']} (Score: {best['score']})")
            execute_buy(exchange, risk, best)
        else:
            logger.info(f"Cannot trade: {reason}")

    # Check if we should sell holdings based on score
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

    # Step 4: Save state & summary
    risk.save_state()
    final_status = risk.get_status()
    notifier.notify_daily_summary(final_status)
    logger.info(f"Final: {final_status['trades_today']} trades | PnL: Rp {final_status['daily_pnl']:,.0f} today | Rp {final_status['total_pnl']:,.0f} total")
    logger.info("CuanBot run complete.")


if __name__ == "__main__":
    dry_run = None
    scan_only = False

    if "--dry-run" in sys.argv:
        dry_run = True
    if "--live" in sys.argv:
        dry_run = False
    if "--scan-only" in sys.argv:
        scan_only = True

    run(dry_run_override=dry_run, scan_only=scan_only)
