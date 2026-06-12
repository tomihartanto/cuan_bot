import json, os, logging
from config import Config

logger = logging.getLogger("cuanbot")


class RiskManager:
    def __init__(self, state_file=None):
        self.state_file = state_file or Config.STATE_FILE
        self.state = self._load_state()

    def _load_state(self):
        default = {
            "trades_today": [], "positions": [], "last_trade_time": None,
            "daily_pnl": 0.0, "total_pnl": 0.0, "total_trades": 0,
            "total_wins": 0, "total_losses": 0, "last_reset": None,
            "last_run": None, "compound_profit": 0.0,
            "peak_balance": Config.INITIAL_TRADE_AMOUNT, "consecutive_losses": 0,
        }
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, "r", encoding="utf-8-sig") as f:
                    saved = json.load(f)
                    default.update(saved)
        except Exception as e:
            logger.warning(f"Could not load state: {e}")
        return default

    def save_state(self):
        try:
            self.state["last_run"] = __import__("datetime").datetime.utcnow().isoformat()
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Could not save state: {e}")

    def _reset_daily_if_needed(self):
        today = __import__("datetime").datetime.utcnow().strftime("%Y-%m-%d")
        if self.state.get("last_reset") != today:
            self.state["trades_today"] = []
            self.state["daily_pnl"] = 0.0
            self.state["last_reset"] = today

    def can_trade(self):
        self._reset_daily_if_needed()
        from datetime import datetime, timedelta

        # ── Emergency stop: terlalu banyak rugi berturut-turut ──────────
        consecutive = self.state.get("consecutive_losses", 0)
        if consecutive >= Config.EMERGENCY_STOP_LOSSES:
            # Cek apakah sudah melewati pause period
            last_loss_time = self.state.get("last_loss_time")
            if last_loss_time:
                try:
                    last_dt = datetime.fromisoformat(str(last_loss_time))
                    pause_end = last_dt + timedelta(hours=Config.EMERGENCY_PAUSE_HOURS)
                    if datetime.utcnow() < pause_end:
                        remaining_min = int((pause_end - datetime.utcnow()).seconds / 60)
                        return False, f"🛑 Emergency stop: {consecutive}x rugi berturut | Resume dalam {remaining_min} menit"
                    else:
                        # Pause sudah selesai, reset
                        logger.info("Emergency stop selesai — bot kembali aktif")
                        self.state["consecutive_losses"] = 0
                except: pass

        # ── Max trades per hari ──────────────────────────────────────────
        trades_today = len(self.state.get("trades_today", []))
        if trades_today >= Config.MAX_TRADES_PER_DAY:
            return False, f"Max trades ({trades_today}/{Config.MAX_TRADES_PER_DAY})"

        # ── Cooldown antar trade ─────────────────────────────────────────
        last_time = self.state.get("last_trade_time")
        if last_time:
            try:
                last_dt = datetime.fromisoformat(str(last_time))
                cooldown = timedelta(minutes=Config.COOLDOWN_MINUTES)
                if datetime.utcnow() - last_dt < cooldown:
                    remaining = cooldown - (datetime.utcnow() - last_dt)
                    return False, f"Cooldown ({int(remaining.seconds / 60)} min left)"
            except: pass
        return True, "OK"

    def record_trade(self, symbol, side, amount, price, order_id=None):
        self._reset_daily_if_needed()
        from datetime import datetime
        self.state["trades_today"].append({"time": datetime.utcnow().isoformat(), "symbol": symbol, "side": side, "amount": amount, "price": price, "order_id": order_id})
        self.state["last_trade_time"] = datetime.utcnow().isoformat()
        self.state["total_trades"] += 1
        self.save_state()

    def open_position(self, symbol, amount, entry_price):
        from datetime import datetime
        position = {
            "symbol": symbol, "amount": amount, "entry_price": entry_price,
            "entry_time": datetime.utcnow().isoformat(),
            "stop_loss": entry_price * (1 - Config.STOP_LOSS_PERCENT / 100),
            "take_profit": entry_price * (1 + Config.TAKE_PROFIT_PERCENT / 100),
            "highest_price": entry_price,
            "trailing_stop": entry_price * (1 - Config.TRAILING_PERCENT / 100),
            "trailing_activated": False,
        }
        self.state["positions"].append(position)
        self.save_state()
        logger.info(f"Position opened: {symbol} | Entry: {entry_price} | SL: {position['stop_loss']:.2f} | TP: {position['take_profit']:.2f}")

    def close_position(self, symbol, exit_price):
        from datetime import datetime
        for i, pos in enumerate(self.state["positions"]):
            if pos["symbol"] == symbol:
                entry = pos["entry_price"]
                pnl_percent = ((exit_price - entry) / entry) * 100
                pnl_idr = (exit_price - entry) * pos["amount"]
                self.state["daily_pnl"] += pnl_idr
                self.state["total_pnl"] += pnl_idr
                if pnl_percent > 0:
                    self.state["total_wins"] += 1
                    self.state["consecutive_losses"] = 0
                    if Config.AUTO_COMPOUND:
                        self.state["compound_profit"] += abs(pnl_idr)
                else:
                    self.state["total_losses"] += 1
                    self.state["consecutive_losses"] = self.state.get("consecutive_losses", 0) + 1
                    self.state["last_loss_time"] = datetime.utcnow().isoformat()  # ← catat waktu rugi
                    if Config.AUTO_COMPOUND:
                        self.state["compound_profit"] = max(0, self.state.get("compound_profit", 0) - abs(pnl_idr) * 0.5)
                    # Emergency stop warning
                    if self.state["consecutive_losses"] >= Config.EMERGENCY_STOP_LOSSES:
                        logger.warning(f"🛑 Emergency stop aktif! {self.state['consecutive_losses']}x rugi berturut-turut. Pause {Config.EMERGENCY_PAUSE_HOURS} jam.")
                highest = pos.get("highest_price", entry)
                self.state["positions"].pop(i)
                self.save_state()
                return {"symbol": symbol, "entry": entry, "exit": exit_price, "pnl_pct": round(pnl_percent, 2),
                        "pnl_idr": round(pnl_idr, 2), "highest": highest, "trailing_used": pos.get("trailing_activated", False),
                        "compound_total": round(self.state.get("compound_profit", 0), 2)}
        return {"error": f"No position for {symbol}"}

    def check_positions(self, current_prices):
        actions = []
        for pos in self.state["positions"][:]:
            symbol = pos["symbol"]
            if symbol not in current_prices: continue
            price = current_prices[symbol]
            entry = pos["entry_price"]
            pnl = ((price - entry) / entry) * 100
            if price > pos.get("highest_price", entry):
                pos["highest_price"] = price
                pos["trailing_activated"] = True
                if Config.TRAILING_STOP_ENABLED:
                    new_trailing = price * (1 - Config.TRAILING_PERCENT / 100)
                    if new_trailing > pos.get("trailing_stop", 0):
                        pos["trailing_stop"] = new_trailing
            if price <= pos["stop_loss"]:
                actions.append({"action": "SELL", "symbol": symbol, "reason": f"Stop loss ({pnl:+.2f}%)", "price": price, "amount": pos["amount"], "priority": "HIGH"})
            elif price >= pos["take_profit"]:
                actions.append({"action": "SELL", "symbol": symbol, "reason": f"Take profit ({pnl:+.2f}%)", "price": price, "amount": pos["amount"], "priority": "MEDIUM"})
            elif Config.TRAILING_STOP_ENABLED and pos.get("trailing_activated"):
                trailing_sl = pos.get("trailing_stop", pos["stop_loss"])
                if price <= trailing_sl and price > pos["stop_loss"]:
                    actions.append({"action": "SELL", "symbol": symbol, "reason": f"Trailing stop ({pnl:+.2f}%)", "price": price, "amount": pos["amount"], "priority": "MEDIUM"})
            self.save_state()
        return actions

    def get_status(self):
        self._reset_daily_if_needed()
        total = max(1, self.state.get("total_trades", 1))
        return {
            "trades_today": len(self.state.get("trades_today", [])),
            "max_trades": Config.MAX_TRADES_PER_DAY,
            "open_positions": len(self.state.get("positions", [])),
            "daily_pnl": round(self.state.get("daily_pnl", 0), 2),
            "total_pnl": round(self.state.get("total_pnl", 0), 2),
            "total_trades": self.state.get("total_trades", 0),
            "win_rate": round(self.state.get("total_wins", 0) / total * 100, 1),
            "positions": self.state.get("positions", []),
            "compound_profit": round(self.state.get("compound_profit", 0), 2),
            "current_trade_amount": round(Config.get_trade_amount(), 2),
            "consecutive_losses": self.state.get("consecutive_losses", 0),
        }
