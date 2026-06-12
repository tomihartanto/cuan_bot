"""
CuanBot - Risk Management
"""

import json
import os
from datetime import datetime, timedelta
from config import Config
import logging

logger = logging.getLogger("cuanbot")


class RiskManager:
    def __init__(self, state_file: str = None):
        self.state_file = state_file or Config.STATE_FILE
        self.state = self._load_state()

    def _load_state(self) -> dict:
        default = {
            "trades_today": [], "positions": [], "last_trade_time": None,
            "daily_pnl": 0.0, "total_pnl": 0.0, "total_trades": 0,
            "total_wins": 0, "total_losses": 0, "last_reset": None, "last_run": None,
        }
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, "r") as f:
                    saved = json.load(f)
                    default.update(saved)
        except Exception as e:
            logger.warning(f"Could not load state: {e}")
        return default

    def save_state(self):
        try:
            self.state["last_run"] = datetime.utcnow().isoformat()
            with open(self.state_file, "w") as f:
                json.dump(self.state, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Could not save state: {e}")

    def _reset_daily_if_needed(self):
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if self.state.get("last_reset") != today:
            self.state["trades_today"] = []
            self.state["daily_pnl"] = 0.0
            self.state["last_reset"] = today

    def can_trade(self) -> tuple:
        self._reset_daily_if_needed()
        trades_today = len(self.state.get("trades_today", []))
        if trades_today >= Config.MAX_TRADES_PER_DAY:
            return False, f"Max trades ({trades_today}/{Config.MAX_TRADES_PER_DAY})"
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

    def record_trade(self, symbol: str, side: str, amount: float, price: float, order_id: str = None):
        self._reset_daily_if_needed()
        trade = {"time": datetime.utcnow().isoformat(), "symbol": symbol, "side": side, "amount": amount, "price": price, "order_id": order_id}
        self.state["trades_today"].append(trade)
        self.state["last_trade_time"] = datetime.utcnow().isoformat()
        self.state["total_trades"] += 1
        self.save_state()

    def open_position(self, symbol: str, amount: float, entry_price: float):
        position = {
            "symbol": symbol, "amount": amount, "entry_price": entry_price,
            "entry_time": datetime.utcnow().isoformat(),
            "stop_loss": entry_price * (1 - Config.STOP_LOSS_PERCENT / 100),
            "take_profit": entry_price * (1 + Config.TAKE_PROFIT_PERCENT / 100),
        }
        self.state["positions"].append(position)
        self.save_state()

    def close_position(self, symbol: str, exit_price: float) -> dict:
        for i, pos in enumerate(self.state["positions"]):
            if pos["symbol"] == symbol:
                entry = pos["entry_price"]
                pnl_percent = ((exit_price - entry) / entry) * 100
                pnl_idr = (exit_price - entry) * pos["amount"]
                self.state["daily_pnl"] += pnl_idr
                self.state["total_pnl"] += pnl_idr
                if pnl_percent > 0: self.state["total_wins"] += 1
                else: self.state["total_losses"] += 1
                self.state["positions"].pop(i)
                self.save_state()
                return {"symbol": symbol, "entry": entry, "exit": exit_price, "pnl_pct": round(pnl_percent, 2), "pnl_idr": round(pnl_idr, 2)}
        return {"error": f"No position for {symbol}"}

    def check_positions(self, current_prices: dict) -> list:
        actions = []
        for pos in self.state["positions"][:]:
            symbol = pos["symbol"]
            if symbol not in current_prices: continue
            price = current_prices[symbol]
            entry = pos["entry_price"]
            pnl = ((price - entry) / entry) * 100
            if price <= pos["stop_loss"]:
                actions.append({"action": "SELL", "symbol": symbol, "reason": f"Stop loss ({pnl:+.2f}%)", "price": price, "amount": pos["amount"], "priority": "HIGH"})
            elif price >= pos["take_profit"]:
                actions.append({"action": "SELL", "symbol": symbol, "reason": f"Take profit ({pnl:+.2f}%)", "price": price, "amount": pos["amount"], "priority": "MEDIUM"})
        return actions

    def get_status(self) -> dict:
        self._reset_daily_if_needed()
        total = max(1, self.state.get("total_trades", 0))
        return {
            "trades_today": len(self.state.get("trades_today", [])),
            "max_trades": Config.MAX_TRADES_PER_DAY,
            "open_positions": len(self.state.get("positions", [])),
            "daily_pnl": round(self.state.get("daily_pnl", 0), 2),
            "total_pnl": round(self.state.get("total_pnl", 0), 2),
            "total_trades": self.state.get("total_trades", 0),
            "win_rate": round(self.state.get("total_wins", 0) / total * 100, 1),
            "positions": self.state.get("positions", []),
        }
