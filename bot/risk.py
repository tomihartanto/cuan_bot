"""
CuanBot - Risk Manager v4
Fix: MAX_OPEN_POSITIONS check, position reconciliation, timeout handling.
"""

import json
import os
import logging
from config import Config

logger = logging.getLogger("cuanbot")


class RiskManager:
    def __init__(self, state_file: str = None):
        self.state_file = state_file or Config.STATE_FILE
        self.state = self._load_state()

    # ── State Persistence ─────────────────────────────────────────────

    def _load_state(self) -> dict:
        default = {
            "trades_today":       [],
            "positions":          [],
            "last_trade_time":    None,
            "daily_pnl":          0.0,
            "total_pnl":          0.0,
            "total_trades":       0,
            "total_wins":         0,
            "total_losses":       0,
            "last_reset":         None,
            "last_run":           None,
            "compound_profit":    0.0,   # Sekarang: statistik realized PnL (penuh, bukan untuk sizing)
            "consecutive_losses": 0,
            "last_loss_time":     None,
            "last_startup_notif": None,
            "recent_results":     [],    # History win/loss untuk win-rate guard
            "day_start_balance":  None,  # Snapshot saldo awal hari (untuk daily loss limit)
        }
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, "r", encoding="utf-8-sig") as f:
                    saved = json.load(f)
                    default.update(saved)
        except Exception as e:
            logger.warning(f"State load gagal: {e} — mulai fresh")
        return default

    def save_state(self):
        try:
            from datetime import datetime, timezone
            self.state["last_run"] = datetime.now(timezone.utc).isoformat()
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"State save gagal: {e}")

    def _reset_daily_if_needed(self):
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.state.get("last_reset") != today:
            logger.info("Reset harian: trades_today & daily_pnl direset")
            self.state["trades_today"] = []
            self.state["daily_pnl"]    = 0.0
            self.state["day_start_balance"] = None  # akan di-set oleh main.py di run pertama hari itu
            self.state["last_reset"]   = today

    # ── Trading Gate ──────────────────────────────────────────────────

    def can_trade(self, available_balance: float = None) -> tuple:
        """
        Return (bool, reason_str). False = jangan beli.
        available_balance: saldo IDR riil untuk hitung max posisi dinamis.
        """
        self._reset_daily_if_needed()
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)

        # ── 1. Emergency stop (3x rugi berturut) ──────────────────────
        consecutive = self.state.get("consecutive_losses", 0)
        if consecutive >= Config.EMERGENCY_STOP_LOSSES:
            last_loss = self.state.get("last_loss_time")
            if last_loss:
                try:
                    last_dt   = datetime.fromisoformat(str(last_loss))
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    pause_end = last_dt + timedelta(hours=Config.EMERGENCY_PAUSE_HOURS)
                    if now < pause_end:
                        rem = int((pause_end - now).seconds / 60)
                        return False, f"🛑 Emergency stop ({consecutive}x rugi) | Resume {rem} menit lagi"
                    else:
                        logger.info("Emergency stop selesai — bot aktif kembali")
                        self.state["consecutive_losses"] = 0
                except Exception as e:
                    logger.warning(f"Emergency stop check error: {e}")

        # ── 2. Daily loss limit ───────────────────────────────────────
        day_start = self.state.get("day_start_balance") or 0
        if day_start > 0:
            daily_pnl   = self.state.get("daily_pnl", 0.0)
            loss_limit  = -(day_start * Config.DAILY_LOSS_LIMIT_PCT / 100)
            if daily_pnl <= loss_limit:
                return False, (f"🛑 Daily loss limit tercapai (rugi Rp {daily_pnl:,.0f} "
                               f">= -{Config.DAILY_LOSS_LIMIT_PCT}% dari Rp {day_start:,.0f})")

        # ── 3. Win-rate guard (rolling N trade) ───────────────────────
        recent = self.state.get("recent_results", [])
        if len(recent) >= Config.WIN_RATE_GUARD_TRADES:
            wins    = recent.count("win")
            win_pct = wins / len(recent) * 100
            if win_pct < Config.WIN_RATE_GUARD_MIN:
                return False, (f"⚠️ Win rate rendah ({win_pct:.0f}% dari {len(recent)} "
                               f"trade terakhir < {Config.WIN_RATE_GUARD_MIN}%) — pause evaluasi")

        # ── 4. Max open positions (dinamis by saldo) ──────────────────
        open_pos = len(self.state.get("positions", []))
        if available_balance and available_balance > 0:
            max_pos = Config.get_max_positions(available_balance)
        else:
            max_pos = Config.MAX_OPEN_POSITIONS
        if open_pos >= max_pos:
            return False, f"Posisi penuh ({open_pos}/{max_pos})"

        # ── 5. Max trades per hari ────────────────────────────────────
        trades_today = len(self.state.get("trades_today", []))
        if trades_today >= Config.MAX_TRADES_PER_DAY:
            return False, f"Max trades hari ini ({trades_today}/{Config.MAX_TRADES_PER_DAY})"

        # ── 6. Cooldown antar trade ───────────────────────────────────
        last_time = self.state.get("last_trade_time")
        if last_time:
            try:
                last_dt = datetime.fromisoformat(str(last_time))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                cooldown = timedelta(minutes=Config.COOLDOWN_MINUTES)
                if now - last_dt < cooldown:
                    remaining = int((cooldown - (now - last_dt)).seconds / 60)
                    return False, f"Cooldown ({remaining} menit lagi)"
            except Exception:
                pass

        return True, "OK"

    # ── Trade Recording ───────────────────────────────────────────────

    def record_trade(self, symbol: str, side: str, amount: float, price: float, order_id=None):
        self._reset_daily_if_needed()
        from datetime import datetime, timezone
        self.state["trades_today"].append({
            "time": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol, "side": side,
            "amount": amount, "price": price,
            "order_id": order_id,
        })
        self.state["last_trade_time"] = datetime.now(timezone.utc).isoformat()
        self.state["total_trades"] += 1
        self.save_state()

    # ── Position Management ───────────────────────────────────────────

    def open_position(self, symbol: str, amount: float, entry_price: float, value_idr: float = None):
        from datetime import datetime, timezone
        position = {
            "symbol":             symbol,
            "amount":             amount,
            "entry_price":        entry_price,
            "value_idr":          value_idr or (amount * entry_price),
            "entry_time":         datetime.now(timezone.utc).isoformat(),
            "stop_loss":          entry_price * (1 - Config.STOP_LOSS_PERCENT / 100),
            "take_profit":        entry_price * (1 + Config.TAKE_PROFIT_PERCENT / 100),
            "highest_price":      entry_price,
            "trailing_stop":      entry_price * (1 - Config.TRAILING_PERCENT / 100),
            "trailing_activated": False,
        }
        self.state["positions"].append(position)
        self.save_state()
        logger.info(
            f"Posisi dibuka: {symbol} | Entry: Rp {entry_price:,.2f} | "
            f"SL: Rp {position['stop_loss']:,.2f} | TP: Rp {position['take_profit']:,.2f}"
        )

    def close_position(self, symbol: str, exit_price: float) -> dict:
        from datetime import datetime, timezone
        for i, pos in enumerate(self.state["positions"]):
            if pos["symbol"] != symbol:
                continue
            entry      = pos["entry_price"]
            amount     = pos["amount"]
            pnl_pct    = ((exit_price - entry) / entry) * 100
            pnl_idr    = (exit_price - entry) * amount

            self.state["daily_pnl"] += pnl_idr
            self.state["total_pnl"] += pnl_idr
            self.state["compound_profit"] = self.state.get("compound_profit", 0.0) + pnl_idr  # Realized PnL penuh

            # Track recent results untuk win-rate guard
            recent = self.state.setdefault("recent_results", [])
            recent.append("win" if pnl_pct > 0 else "loss")
            if len(recent) > Config.WIN_RATE_GUARD_TRADES:
                recent.pop(0)

            if pnl_pct > 0:
                self.state["total_wins"]         += 1
                self.state["consecutive_losses"]  = 0
            else:
                self.state["total_losses"]        += 1
                self.state["consecutive_losses"]  = self.state.get("consecutive_losses", 0) + 1
                self.state["last_loss_time"]      = datetime.now(timezone.utc).isoformat()
                if self.state["consecutive_losses"] >= Config.EMERGENCY_STOP_LOSSES:
                    logger.warning(
                        f"🛑 Emergency stop! {self.state['consecutive_losses']}x rugi berturut-turut. "
                        f"Pause {Config.EMERGENCY_PAUSE_HOURS} jam."
                    )

            result = {
                "symbol":         symbol,
                "entry":          entry,
                "exit":           exit_price,
                "amount":         amount,
                "pnl_pct":        round(pnl_pct, 2),
                "pnl_idr":        round(pnl_idr, 2),
                "highest":        pos.get("highest_price", entry),
                "trailing_used":  pos.get("trailing_activated", False),
                "compound_total": round(self.state.get("compound_profit", 0), 2),
                "hold_time":      pos.get("entry_time"),
            }
            self.state["positions"].pop(i)
            self.save_state()
            return result

        return {"error": f"Tidak ada posisi untuk {symbol}"}

    def check_positions(self, current_prices: dict) -> list:
        """
        Cek semua posisi terbuka terhadap TP/SL/Trailing/Timeout.
        Return list aksi yang harus dieksekusi.
        """
        from datetime import datetime, timedelta, timezone
        actions = []
        now = datetime.now(timezone.utc)

        for pos in self.state["positions"][:]:  # copy list karena mungkin di-modify
            symbol = pos["symbol"]
            if symbol not in current_prices:
                continue
            price = current_prices[symbol]
            if price <= 0:
                continue
            entry = pos["entry_price"]
            pnl   = ((price - entry) / entry) * 100

            # Update trailing high
            if price > pos.get("highest_price", entry):
                pos["highest_price"] = price

            # Trailing baru aktif setelah profit mencapai TRAILING_ACTIVATION%
            profit_pct = (price - entry) / entry * 100
            if (Config.TRAILING_STOP_ENABLED
                    and not pos.get("trailing_activated", False)
                    and profit_pct >= Config.TRAILING_ACTIVATION):
                pos["trailing_activated"] = True
                logger.info(f"Trailing stop aktif untuk {symbol} (profit {profit_pct:+.2f}%)")

            # Update trailing stop hanya kalau sudah aktif
            if pos.get("trailing_activated", False):
                new_trailing = price * (1 - Config.TRAILING_PERCENT / 100)
                if new_trailing > pos.get("trailing_stop", 0):
                    pos["trailing_stop"] = new_trailing

            # ── Check exits ────────────────────────────────────────
            reason = None
            priority = "MEDIUM"

            if price <= pos["stop_loss"]:
                reason   = f"Stop loss ({pnl:+.2f}%)"
                priority = "HIGH"

            elif price >= pos["take_profit"]:
                reason = f"Take profit ({pnl:+.2f}%)"

            elif (Config.TRAILING_STOP_ENABLED
                  and pos.get("trailing_activated")
                  and price <= pos.get("trailing_stop", pos["stop_loss"])
                  and price > pos["stop_loss"]):
                reason = f"Trailing stop ({pnl:+.2f}%)"

            else:
                # Position timeout: kalau nyangkut terlalu lama, cut loss kecil
                entry_time = pos.get("entry_time")
                if entry_time:
                    try:
                        entry_dt = datetime.fromisoformat(str(entry_time))
                        if entry_dt.tzinfo is None:
                            entry_dt = entry_dt.replace(tzinfo=timezone.utc)
                        hold_hours = (now - entry_dt).total_seconds() / 3600
                        if hold_hours >= Config.POSITION_TIMEOUT_HOURS:
                            reason   = f"Timeout {hold_hours:.1f} jam ({pnl:+.2f}%)"
                            priority = "MEDIUM"
                    except Exception:
                        pass

            if reason:
                actions.append({
                    "action":   "SELL",
                    "symbol":   symbol,
                    "amount":   pos["amount"],
                    "price":    price,
                    "reason":   reason,
                    "priority": priority,
                    "pnl_pct":  round(pnl, 2),
                })

        self.save_state()
        return actions

    def reconcile_with_balance(self, holdings: dict, current_prices: dict):
        """
        Sync state positions dengan exchange balance.
        Kalau ada crypto di exchange tapi tidak di state → tambah ke state.
        Kalau di state tapi tidak ada di exchange → hapus dari state.
        """
        tracked_symbols = {p["symbol"] for p in self.state.get("positions", [])}
        scan_coin_set   = {f"{c}/{Config.BASE_CURRENCY}" for c in Config.SCAN_COINS}

        for asset, amounts in holdings.items():
            pair  = f"{asset}/{Config.BASE_CURRENCY}"
            total = amounts.get("total", 0)
            if pair not in scan_coin_set:
                continue
            if total <= 0:
                continue
            if pair in tracked_symbols:
                continue
            # Ada di exchange tapi tidak di state → tambahkan dengan harga saat ini
            price = current_prices.get(pair, 0)
            if price <= 0:
                continue
            logger.warning(f"Posisi tidak tracked ditemukan: {pair} {total:.6f} @ Rp {price:,.0f} — menambahkan ke state")
            self.open_position(pair, total, price)

        # Hapus posisi dari state yang sudah tidak ada di exchange
        updated_positions = []
        for pos in self.state.get("positions", []):
            asset  = pos["symbol"].split("/")[0]
            balance = holdings.get(asset, {}).get("total", 0)
            if balance <= pos["amount"] * 0.05:  # < 5% dari amount → anggap sudah terjual
                logger.warning(f"Posisi {pos['symbol']} tidak ada di balance → hapus dari state")
                # Hitung PnL dengan harga terakhir
                price = current_prices.get(pos["symbol"], pos["entry_price"])
                self.close_position(pos["symbol"], price)
            else:
                updated_positions.append(pos)
        self.state["positions"] = updated_positions
        self.save_state()

    # ── Status & Summary ──────────────────────────────────────────────

    def get_status(self, available_balance: float = None) -> dict:
        self._reset_daily_if_needed()
        total = max(1, self.state.get("total_trades", 0))
        wins  = self.state.get("total_wins", 0)
        losses = self.state.get("total_losses", 0)
        max_pos = Config.get_max_positions(available_balance) if available_balance else Config.MAX_OPEN_POSITIONS
        return {
            "trades_today":         len(self.state.get("trades_today", [])),
            "max_trades":           Config.MAX_TRADES_PER_DAY,
            "open_positions":       len(self.state.get("positions", [])),
            "max_positions":        max_pos,
            "positions":            self.state.get("positions", []),
            "daily_pnl":            round(self.state.get("daily_pnl", 0), 2),
            "total_pnl":            round(self.state.get("total_pnl", 0), 2),
            "total_trades":         self.state.get("total_trades", 0),
            "total_wins":           wins,
            "total_losses":         losses,
            "win_rate":             round(wins / total * 100, 1),
            "realized_pnl":         round(self.state.get("compound_profit", 0), 2),
            "current_trade_amount": round(Config.get_trade_amount(available_balance), 2),
            "consecutive_losses":   self.state.get("consecutive_losses", 0),
            "day_start_balance":    self.state.get("day_start_balance"),
        }

    def should_send_startup_notif(self) -> bool:
        """Hanya kirim startup notif kalau sudah > 1 jam dari notif terakhir."""
        from datetime import datetime, timedelta, timezone
        last = self.state.get("last_startup_notif")
        now  = datetime.now(timezone.utc)
        if not last:
            self.state["last_startup_notif"] = now.isoformat()
            return True
        try:
            last_dt = datetime.fromisoformat(str(last))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            if now - last_dt > timedelta(hours=1):
                self.state["last_startup_notif"] = now.isoformat()
                return True
        except Exception:
            self.state["last_startup_notif"] = now.isoformat()
            return True
        return False
