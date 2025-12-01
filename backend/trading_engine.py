import datetime as dt
from typing import List, Dict, Optional, Callable
from kiteconnect import KiteConnect
from trading_logic import TradingLogic
import pandas as pd

class TradeStatus:
    PLANNED = "PLANNED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"

class TradeLogEntry:
    def __init__(self, symbol, action, entry_price, exit_price=None, status=TradeStatus.PLANNED, pnl=None, pnl_pct=None, note=None):
        self.time = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.symbol = symbol
        self.action = action
        self.entry_price = entry_price
        self.exit_price = exit_price
        self.status = status
        self.pnl = pnl
        self.pnl_pct = pnl_pct
        self.note = note

    def as_dict(self):
        return self.__dict__

class TradingEngine:
    def __init__(self, kite: KiteConnect, config: dict, notify: Optional[Callable[[str, dict], None]] = None):
        self.kite = kite
        self.config = config
        self.positions: Dict[str, dict] = {}
        self.trade_logs: List[dict] = []
        self.realized_pnl = 0.0
        self.notify = notify
        self.entered_symbols_today = set()
        self.last_global_entry_time = None
        self.symbol_last_exit_time = {}
        self.logic = TradingLogic(kite, config)
        
    def log_trade(self, *args, **kwargs):
        entry = TradeLogEntry(*args, **kwargs)
        log_dict = entry.as_dict()
        self.trade_logs.append(log_dict)
        if self.notify:
            self.notify("trade_log", log_dict)
        return log_dict

    def get_trade_logs(self):
        return self.trade_logs

    def get_positions(self):
        return self.positions

    def get_pnl(self):
        return self.realized_pnl

    def update_config(self, new_config: dict):
        self.config.update(new_config)

    def add_position(self, symbol, entry_price, qty, atr=None):
        atr = atr if atr else max(0.0001, entry_price * 0.25)
        is_call = symbol.endswith("CE")
        is_put = symbol.endswith("PE")

        if is_call:
            sl_price = entry_price - atr
            target_price = entry_price + atr
        elif is_put:
            sl_price = entry_price + atr
            target_price = entry_price - atr
        else:
            sl_price = entry_price - atr
            target_price = entry_price + atr

        self.positions[symbol] = {
            "entry_price": entry_price,
            "quantity": qty,
            "sl_price": sl_price,
            "target_price": target_price,
            "trailing_active": False,
            "status": "OPEN",
            "opened_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "atr": atr,
            "is_call": is_call,
            "is_put": is_put
        }
        self.log_trade(symbol, "BUY", entry_price, status="PLANNED", note=f"signal, SL={sl_price:.2f}, TGT={target_price:.2f}")
        print(f"[OPEN] {symbol} @ {entry_price} qty={qty} SL={sl_price:.2f} TGT={target_price:.2f}")

    def exit_position(self, symbol, exit_price, reason="EXIT"):
        pos = self.positions.get(symbol)
        if not pos or pos["status"] != "OPEN":
            return
        pnl_per_unit = (exit_price - pos["entry_price"])
        pnl = pnl_per_unit * pos["quantity"]
        pnl_pct = (pnl_per_unit / pos["entry_price"]) * 100 if pos["entry_price"] else None
        self.realized_pnl += pnl
        pos["status"] = "CLOSED"
        self.symbol_last_exit_time[symbol] = dt.datetime.now()
        self.log_trade(symbol, "SELL", pos["entry_price"], exit_price, status="SUCCESS", pnl=pnl, pnl_pct=pnl_pct, note=reason)
        print(f"[CLOSE] {symbol} @ {exit_price} | PnL {pnl:.2f} ({pnl_pct:.2f}%) | Reason: {reason}")
        if self.notify:
            self.notify("position_closed", {"symbol": symbol, "pnl": pnl, "pnl_pct": pnl_pct, "reason": reason})

    def daily_pl_ratio(self):
        capital = self.config.get("capital_base", 300000)
        if capital <= 0:
            return 0.0
        return self.realized_pnl / capital

    def within_entry_window(self, t):
        start = dt.time(9, 30)
        end = dt.time(15, 20)
        return start <= t <= end

    def global_cooldown_ok(self):
        min_minutes = self.config.get("min_minutes_between_entries", 10)
        if self.last_global_entry_time is None:
            return True
        return (dt.datetime.now() - self.last_global_entry_time).total_seconds() >= min_minutes * 60

    def symbol_cooldown_ok(self, symbol):
        cooldown_min = self.config.get("per_symbol_cooldown_min", 20)
        last = self.symbol_last_exit_time.get(symbol)
        if last is None:
            return True
        return (dt.datetime.now() - last).total_seconds() >= cooldown_min * 60

    def scan_and_maybe_enter_once(self):
        """Main scanning and entry logic from v1.1.py"""
        nowt = dt.datetime.now().time()
        if not self.within_entry_window(nowt):
            return

        # Daily guards
        plr = self.daily_pl_ratio()
        daily_max_loss = self.config.get("daily_max_loss", -0.02)
        daily_max_profit = self.config.get("daily_max_profit", 0.04)
        if plr <= daily_max_loss:
            print("[GUARD] Daily loss limit reached. No more entries.")
            if self.notify:
                self.notify("risk_limit", {"type": "daily_loss", "value": plr})
            return
        if plr >= daily_max_profit:
            print("[GUARD] Daily profit cap reached. No more entries.")
            if self.notify:
                self.notify("risk_limit", {"type": "daily_profit", "value": plr})
            return
        
        max_concurrent = self.config.get("max_concurrent_pos", 3)
        if sum(1 for p in self.positions.values() if p["status"] == "OPEN") >= max_concurrent:
            print("[INFO] Max concurrent positions reached. Skipping new entries.")
            return
        if not self.global_cooldown_ok():
            print("[INFO] Global cooldown active. Skipping this scan.")
            return

        # Fetch spot data and indicators
        try:
            nifty_token = self.config.get("nifty_token", 256265)
            spot_df = self.logic.fetch_spot_5m(nifty_token, days=2)
            atr_period = self.config.get("atr_period", 14)
            spot_df = self.logic.add_spot_indicators(spot_df, atr_period)
        except Exception as e:
            print(f"[ERR] Spot fetch/indicator error: {e}")
            if self.notify:
                self.notify("error", {"error": str(e), "type": "spot_fetch"})
            return

        if spot_df is None or len(spot_df) < 15:
            print("[INFO] Not enough spot candles yet.")
            return

        last_spot = spot_df.iloc[-1]
        prev_spot = spot_df.iloc[-2]

        # EMA crossover signal
        signal_side = None
        if prev_spot["EMA5"] <= prev_spot["EMA20"] and last_spot["EMA5"] > last_spot["EMA20"]:
            signal_side = "CE"
        elif prev_spot["EMA5"] >= prev_spot["EMA20"] and last_spot["EMA5"] < last_spot["EMA20"]:
            signal_side = "PE"

        if not signal_side:
            print("[SCAN] No EMA crossover signal this candle.")
            return

        # ATR filter
        atr_median = spot_df["ATR"].rolling(20).median().iloc[-1]
        if last_spot["ATR"] < atr_median:
            print("[SKIP] Market too quiet (low ATR), skipping trade.")
            return

        # Get spot LTP and identify ATM option
        try:
            spot_ltp_data = self.kite.ltp(nifty_token)
            spot_ltp = list(spot_ltp_data.values())[0]["last_price"]
        except Exception as e:
            print(f"[ERR] Spot LTP failed: {e}")
            if self.notify:
                self.notify("error", {"error": str(e), "type": "spot_ltp"})
            return

        atm = self.logic.round_to_50(spot_ltp)
        expiry = self.logic.get_next_expiry()
        underlying = self.config.get("underlying_name", "NIFTY")
        tsym, token = self.logic.lookup_option(underlying, expiry, atm, signal_side)
        if not tsym or not token:
            print(f"[WARN] ATM option not found: {underlying} {expiry} {atm} {signal_side}")
            return

        # VWAP filter on NIFTY FUT
        try:
            fut_token, fut_symbol = self.logic.get_nifty_weekly_fut_token()
            if fut_token is None:
                print("[ERR] Cannot proceed without NIFTY FUT token.")
                return

            fut_df = self.logic.fetch_fut_5m(fut_token, days=2)
            if fut_df is None or len(fut_df) < 10:
                print("[WARN] Not enough FUT candles; skipping VWAP validation.")
                return
            fut_df = self.logic.compute_vwap(fut_df)
            fut_last = fut_df.iloc[-1]
            distance_pct = abs(fut_last["close"] - fut_last["VWAP"]) / fut_last["VWAP"] * 100
            vwap_direction_ok = (signal_side == "CE" and fut_last["close"] > fut_last["VWAP"]) or \
                                (signal_side == "PE" and fut_last["close"] < fut_last["VWAP"])
            print(f"[DEBUG] FUT VWAP distance: {distance_pct:.2f}%, direction OK: {vwap_direction_ok}")

            min_vwap_dist = self.config.get("min_vwap_distance_pct", 0.15)
            if distance_pct < min_vwap_dist or not vwap_direction_ok:
                print("[SKIP] FUT VWAP filter failed (distance or direction).")
                return
        except Exception as e:
            print(f"[ERR] FUT VWAP calc failed: {e}")
            if self.notify:
                self.notify("error", {"error": str(e), "type": "vwap_calc"})
            return

        # Check duplicates / cooldown
        if tsym in self.entered_symbols_today and (tsym in self.positions and self.positions[tsym]["status"] == "OPEN"):
            print(f"[INFO] Already in {tsym}. Skip.")
            return
        if not self.symbol_cooldown_ok(tsym):
            print(f"[INFO] Symbol cooldown active for {tsym}.")
            return

        # Get entry LTP
        try:
            ltp_info = self.kite.ltp(f"NFO:{tsym}")
            entry_ltp = list(ltp_info.values())[0]["last_price"]
        except Exception as e:
            print(f"[ERR] Option LTP failed: {e}")
            if self.notify:
                self.notify("error", {"error": str(e), "type": "option_ltp"})
            return

        self.log_trade(tsym, "BUY", entry_ltp, status="PLANNED", note="signal (spot EMA + FUT VWAP)")
        atr_value = spot_df["ATR"].iloc[-1]
        lot_qty = self.config.get("lot_qty", 75)

        # Place real market order
        try:
            order_id = self.kite.place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=self.kite.EXCHANGE_NFO,
                tradingsymbol=tsym,
                transaction_type=self.kite.TRANSACTION_TYPE_BUY,
                quantity=lot_qty,
                order_type=self.kite.ORDER_TYPE_MARKET,
                product=self.kite.PRODUCT_MIS
            )
            self.add_position(tsym, entry_ltp, lot_qty, atr=atr_value)
            self.log_trade(tsym, "BUY", entry_ltp, status="SUCCESS", note="filled")
            self.entered_symbols_today.add(tsym)
            self.last_global_entry_time = dt.datetime.now()
            if self.notify:
                self.notify("order_executed", {"symbol": tsym, "action": "BUY", "price": entry_ltp, "qty": lot_qty})
        except Exception as e:
            print(f"[ORDER-FAIL] BUY {tsym}: {e}")
            self.log_trade(tsym, "BUY", entry_ltp, status="FAILED", note=str(e))
            if self.notify:
                self.notify("order_failed", {"symbol": tsym, "action": "BUY", "error": str(e)})

    def monitor_positions_once(self):
        """Monitor and manage open positions from v1.1.py"""
        nowt = dt.datetime.now().time()
        if not self.positions:
            return

        tokens = [f"NFO:{sym}" for sym in self.positions.keys() if self.positions[sym]["status"] == "OPEN"]
        if not tokens:
            return

        ltp_data = {}
        try:
            ltp_info = self.kite.ltp(tokens)
            for sym in self.positions:
                if self.positions[sym]["status"] != "OPEN":
                    continue
                key = f"NFO:{sym}"
                entry = ltp_info.get(key)
                if entry:
                    ltp_data[sym] = list(entry.values())[0]["last_price"]
        except Exception as e:
            print(f"[ERR] LTP fetch failed: {e}")
            if self.notify:
                self.notify("error", {"error": str(e), "type": "ltp_fetch"})
            return

        trail_start_pct = self.config.get("trail_start_pct", 0.15)
        trail_giveback_pct = self.config.get("trail_giveback_pct", 0.10)
        eod_squareoff = dt.time(15, 20)

        for symbol, pos in list(self.positions.items()):
            if pos["status"] != "OPEN":
                continue
            ltp = ltp_data.get(symbol)
            if ltp is None:
                continue

            entry_price = pos["entry_price"]
            atr = pos.get("atr", 0)
            is_call = pos.get("is_call", False)
            is_put = pos.get("is_put", False)

            # Activate trailing
            if not pos["trailing_active"]:
                trigger_price = entry_price * (1 + trail_start_pct) if is_call else entry_price * (1 - trail_start_pct)
                min_sl = entry_price * 0.995 if is_call else entry_price * 1.005
                if (is_call and ltp >= trigger_price) or (is_put and ltp <= trigger_price):
                    pos["sl_price"] = max(min_sl, entry_price) if is_call else min(min_sl, entry_price)
                    pos["trailing_active"] = True
                    print(f"[TRAIL] Activated for {symbol}, SL -> {pos['sl_price']:.2f}")

            # Dynamic ATR-based SL/TGT
            if is_call:
                dynamic_sl = ltp - atr
                dynamic_target = ltp + atr
                if dynamic_sl > pos["sl_price"]:
                    old_sl = pos["sl_price"]
                    pos["sl_price"] = dynamic_sl
                    print(f"[DYNAMIC] SL updated {symbol}: {old_sl:.2f} -> {pos['sl_price']:.2f}")
                if dynamic_target > pos["target_price"]:
                    old_tgt = pos["target_price"]
                    pos["target_price"] = dynamic_target
                    print(f"[DYNAMIC] Target updated {symbol}: {old_tgt:.2f} -> {pos['target_price']:.2f}")
            elif is_put:
                dynamic_sl = ltp + atr
                dynamic_target = ltp - atr
                if dynamic_sl < pos["sl_price"] or pos["sl_price"] == entry_price + atr:
                    old_sl = pos["sl_price"]
                    pos["sl_price"] = dynamic_sl
                    print(f"[DYNAMIC] SL updated {symbol}: {old_sl:.2f} -> {pos['sl_price']:.2f}")
                if dynamic_target < pos["target_price"]:
                    old_tgt = pos["target_price"]
                    pos["target_price"] = dynamic_target
                    print(f"[DYNAMIC] Target updated {symbol}: {old_tgt:.2f} -> {pos['target_price']:.2f}")

            # Trailing giveback adjustments
            if pos["trailing_active"]:
                if is_call:
                    proposed_sl = ltp * (1 - trail_giveback_pct)
                    if proposed_sl > pos["sl_price"]:
                        old_sl = pos["sl_price"]
                        pos["sl_price"] = proposed_sl
                        print(f"[TRAIL] SL raised {symbol}: {old_sl:.2f} -> {pos['sl_price']:.2f}")
                elif is_put:
                    proposed_sl = ltp * (1 + trail_giveback_pct)
                    if proposed_sl < pos["sl_price"]:
                        old_sl = pos["sl_price"]
                        pos["sl_price"] = proposed_sl
                        print(f"[TRAIL] SL lowered {symbol}: {old_sl:.2f} -> {pos['sl_price']:.2f}")

            # Check SL/TGT/EOD
            hit_sl = (ltp <= pos["sl_price"] if is_call else ltp >= pos["sl_price"])
            hit_tgt = (ltp >= pos["target_price"] if is_call else ltp <= pos["target_price"])
            time_exit = nowt >= eod_squareoff

            if hit_sl or hit_tgt or time_exit:
                reason = "SL" if hit_sl else ("TGT" if hit_tgt else "EOD")
                try:
                    self.kite.place_order(
                        variety=self.kite.VARIETY_REGULAR,
                        exchange=self.kite.EXCHANGE_NFO,
                        tradingsymbol=symbol,
                        transaction_type=self.kite.TRANSACTION_TYPE_SELL if is_call else self.kite.TRANSACTION_TYPE_BUY,
                        quantity=pos["quantity"],
                        order_type=self.kite.ORDER_TYPE_MARKET,
                        product=self.kite.PRODUCT_MIS
                    )
                    self.exit_position(symbol, ltp, reason=reason)
                except Exception as e:
                    print(f"[ORDER-FAIL] Exit {symbol}: {e}")
                    self.log_trade(symbol, "SELL" if is_call else "BUY", pos["entry_price"], ltp, status="FAILED", note=f"{reason}: {e}")
                    if self.notify:
                        self.notify("order_failed", {"symbol": symbol, "action": "EXIT", "error": str(e)})

    def close_all_positions(self):
        """Emergency close all open positions"""
        try:
            for sym, pos in list(self.positions.items()):
                if pos["status"] == "OPEN":
                    try:
                        ltp_info = self.kite.ltp(f"NFO:{sym}")
                        ltp = list(ltp_info.values())[0]["last_price"]
                        self.kite.place_order(
                            variety=self.kite.VARIETY_REGULAR,
                            exchange=self.kite.EXCHANGE_NFO,
                            tradingsymbol=sym,
                            transaction_type=self.kite.TRANSACTION_TYPE_SELL,
                            quantity=pos["quantity"],
                            order_type=self.kite.ORDER_TYPE_MARKET,
                            product=self.kite.PRODUCT_MIS
                        )
                        self.exit_position(sym, ltp, reason="EMERGENCY_CLOSE")
                    except Exception as e:
                        self.log_trade(sym, "SELL", pos["entry_price"], status="FAILED", note=f"EMERGENCY_CLOSE: {e}")
                        if self.notify:
                            self.notify("error", {"error": str(e), "type": "emergency_close"})
        except Exception as e:
            if self.notify:
                self.notify("error", {"error": str(e), "type": "close_all_positions"})
            raise