import datetime as dt
from typing import List, Dict, Optional, Callable, Any
from kiteconnect import KiteConnect
from trading_logic import TradingLogic
from telegram_notifier import TelegramNotifier
import pandas as pd
import time
import logging
from functools import wraps
import pytz

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
        self.last_global_entry_time: Optional[dt.datetime] = None
        self.symbol_last_exit_time: Dict[str, dt.datetime] = {}
        self.logic = TradingLogic(kite, config)
        self.logger = logging.getLogger("TradingEngine")
        self.timezone = pytz.timezone('Asia/Kolkata')
        self._shutdown_requested = False
        self.telegram = TelegramNotifier()
        self.session_start_time = dt.datetime.now(self.timezone).strftime("%Y-%m-%d %H:%M:%S")
        self.session_summary_sent = False
        self.last_signal_candle_time = None  # Track last processed signal candle to prevent duplicates
        
        # Store previous cycle's EMA values for accurate crossover detection
        self.prev_ema5 = None
        self.prev_ema20 = None
        self.last_reset_date = None  # Track last daily reset
        
        # Configure logging to ensure output to stdout
        self.logger.setLevel(logging.DEBUG)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
        self.logger.propagate = True
        
        # Validate configuration on initialization
        self._validate_config()
    
    def _validate_config(self) -> None:
        """Validate configuration parameters"""
        required_keys = ["capital_base", "lot_qty", "nifty_token", "underlying_name"]
        missing_keys = [key for key in required_keys if key not in self.config]
        
        if missing_keys:
            error_msg = f"Missing required config keys: {missing_keys}"
            self.logger.error(f"[CONFIG] {error_msg}")
            raise ValueError(error_msg)
        
        # Validate numeric values
        if self.config.get("capital_base", 0) <= 0:
            raise ValueError("capital_base must be positive")
        
        if self.config.get("lot_qty", 0) <= 0:
            raise ValueError("lot_qty must be positive")
        
        # Set defaults for optional parameters
        defaults = {
            "min_minutes_between_entries": 10,
            "per_symbol_cooldown_min": 20,
            "daily_max_loss": -0.02,
            "daily_max_profit": 0.04,
            "max_concurrent_pos": 3,
            "atr_period": 14,
            "atr_filter": 0.8,  # ATR threshold multiplier (default: 0.8 = 80% of median ATR)
            "trail_start_pct": 0.20,
            "trail_giveback_pct": 0.03,  # Reduced from 0.05 to 0.03 (3% instead of 5%)
            "dynamic_atr_multiplier": 0.85  # Use 85% of ATR for tighter dynamic SL
        }
        
        for key, default_value in defaults.items():
            if key not in self.config:
                self.config[key] = default_value
                self.logger.info(f"[CONFIG] Setting default {key}={default_value}")
    
    def request_shutdown(self) -> None:
        """Request graceful shutdown"""
        self._shutdown_requested = True
        self.logger.info("[SHUTDOWN] Graceful shutdown requested")
    
    def is_shutdown_requested(self) -> bool:
        """Check if shutdown has been requested"""
        return self._shutdown_requested

    @staticmethod
    def retry_on_exception(retries: int = 3, delay: float = 1):
        """Decorator to retry function on exception"""
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs) -> Any:
                for attempt in range(retries):
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        logging.warning(f"Retry {attempt+1}/{retries} for {func.__name__} due to: {e}")
                        if attempt < retries - 1:
                            time.sleep(delay)
                        else:
                            raise
            return wrapper
        return decorator

    def log_trade(self, *args, **kwargs) -> dict:
        """Log a trade entry"""
        try:
            entry = TradeLogEntry(*args, **kwargs)
            log_dict = entry.as_dict()
            self.trade_logs.append(log_dict)
            
            if self.notify:
                try:
                    self.notify("trade_log", log_dict)
                except Exception as e:
                    self.logger.error(f"[NOTIFY] Failed to send trade_log notification: {e}")
            
            self.logger.info(f"[TRADE_LOG] {log_dict}")
            return log_dict
        except Exception as e:
            self.logger.error(f"[TRADE_LOG] Failed to log trade: {e}")
            return {}

    def get_trade_logs(self) -> List[dict]:
        """Get all trade logs"""
        return self.trade_logs.copy()

    def get_positions(self) -> Dict[str, dict]:
        """Get current positions"""
        return self.positions.copy()

    def get_pnl(self) -> float:
        """Get realized P&L"""
        return self.realized_pnl

    def update_config(self, new_config: dict) -> None:
        """Update configuration and revalidate"""
        self.config.update(new_config)
        try:
            self._validate_config()
            self.logger.info(f"[CONFIG] Configuration updated successfully")
        except ValueError as e:
            self.logger.error(f"[CONFIG] Invalid configuration: {e}")
            raise

    def add_position(self, symbol: str, entry_price: float, qty: int, atr: Optional[float] = None) -> None:
        """Add a new position with validation"""
        # Validate inputs
        if entry_price <= 0:
            self.logger.error(f"[POSITION] Invalid entry_price: {entry_price}")
            return
        
        if qty <= 0:
            self.logger.error(f"[POSITION] Invalid quantity: {qty}")
            return
        
        atr = atr if atr and atr > 0 else max(0.0001, entry_price * 0.25)
        is_call = symbol.endswith("CE")
        is_put = symbol.endswith("PE")

        # When BUYING options (both CE and PE), you profit when premium INCREASES
        # SL is below entry, Target is above entry (same for both CE and PE)
        sl_price = entry_price - atr
        target_price = entry_price + 1.5 * atr  # Changed from 2x to 1.5x ATR for better hit rate

        self.positions[symbol] = {
            "entry_price": entry_price,
            "quantity": qty,
            "sl_price": sl_price,
            "target_price": target_price,
            "trailing_active": False,
            "status": "OPEN",
            "opened_at": dt.datetime.now(self.timezone).strftime("%Y-%m-%d %H:%M:%S"),
            "atr": atr,
            "is_call": is_call,
            "is_put": is_put
        }
        self.log_trade(symbol, "BUY", entry_price, status="PLANNED", note=f"signal, SL={sl_price:.2f}, TGT={target_price:.2f}")
        self.logger.info(f"[POSITION_OPEN] {symbol} @ {entry_price} qty={qty} SL={sl_price:.2f} TGT={target_price:.2f}")

    def exit_position(self, symbol: str, exit_price: float, reason: str = "EXIT") -> None:
        """Exit a position with proper error handling"""
        pos = self.positions.get(symbol)
        
        if not pos:
            self.logger.warning(f"[POSITION_EXIT] No position found for {symbol}")
            return
        
        if pos["status"] != "OPEN":
            self.logger.warning(f"[POSITION_EXIT] Position {symbol} is not OPEN (status={pos['status']})")
            return
        
        # Calculate P&L with division by zero protection
        pnl_per_unit = exit_price - pos["entry_price"]
        pnl = pnl_per_unit * pos["quantity"]
        
        if pos["entry_price"] > 0:
            pnl_pct = (pnl_per_unit / pos["entry_price"]) * 100
        else:
            pnl_pct = 0.0
            self.logger.warning(f"[POSITION_EXIT] Entry price is zero for {symbol}, setting pnl_pct=0")
        
        self.realized_pnl += pnl
        pos["status"] = "CLOSED"
        self.symbol_last_exit_time[symbol] = dt.datetime.now(self.timezone)
        
        self.log_trade(symbol, "SELL", pos["entry_price"], exit_price, status="SUCCESS", pnl=pnl, pnl_pct=pnl_pct, note=reason)
        self.logger.info(f"[POSITION_CLOSED] {symbol} @ {exit_price} | PnL {pnl:.2f} ({pnl_pct:.2f}%) | Reason: {reason}")
        
        if self.notify:
            try:
                self.notify("position_closed", {"symbol": symbol, "pnl": pnl, "pnl_pct": pnl_pct, "reason": reason})
            except Exception as e:
                self.logger.error(f"[NOTIFY] Failed to send position_closed notification: {e}")

    def daily_pl_ratio(self) -> float:
        """Calculate daily P&L ratio with protection against division by zero"""
        capital = self.config.get("capital_base", 300000)
        
        if capital <= 0:
            self.logger.warning(f"[PNL] Invalid capital_base: {capital}, returning 0.0")
            return 0.0
        
        return self.realized_pnl / capital

    def within_entry_window(self, t: dt.time) -> bool:
        """Check if current time is within entry window"""
        start = dt.time(9, 30)
        end = dt.time(15, 20)
        return start <= t <= end

    def global_cooldown_ok(self) -> bool:
        """Check if global cooldown period has elapsed"""
        min_minutes = self.config.get("min_minutes_between_entries", 10)
        
        if self.last_global_entry_time is None:
            return True
        
        elapsed_seconds = (dt.datetime.now(self.timezone) - self.last_global_entry_time).total_seconds()
        return elapsed_seconds >= min_minutes * 60

    def symbol_cooldown_ok(self, symbol: str) -> bool:
        """Check if symbol-specific cooldown period has elapsed"""
        cooldown_min = self.config.get("per_symbol_cooldown_min", 20)
        last = self.symbol_last_exit_time.get(symbol)
        
        if last is None:
            return True
        
        elapsed_seconds = (dt.datetime.now(self.timezone) - last).total_seconds()
        return elapsed_seconds >= cooldown_min * 60

    def scan_and_maybe_enter_once(self) -> None:
        """Main scanning and entry logic - called only at 5-minute candle closes by main loop"""
        now_dt = dt.datetime.now(self.timezone)
        nowt = now_dt.time()
        
        # Reset EMA state at start of new trading day to prevent stale values from previous day
        current_date = now_dt.date()
        if self.last_reset_date != current_date:
            self.logger.info(f"[DAILY_RESET] New trading day detected ({current_date}), resetting EMA state")
            self.prev_ema5 = None
            self.prev_ema20 = None
            self.last_signal_candle_time = None
            self.last_reset_date = current_date
            self.logger.info("[DAILY_RESET] ✅ EMA state reset complete - fresh start for new day")
        
        self.logger.info(f"[SCAN_START] ========== Scan cycle at {now_dt.strftime('%H:%M:%S')} (5-min candle closed) ==========")
        
        if self._shutdown_requested:
            self.logger.info("[SCAN] Shutdown requested, skipping scan")
            return
        
        # Check if market is open (9:15 AM - 3:30 PM)
        market_open = dt.time(9, 15)
        market_close = dt.time(15, 30)
        
        self.logger.info(f"[SCAN] Current time: {nowt.strftime('%H:%M:%S')}, Market hours: 09:15-15:30, Entry window: 09:30-15:20")
        
        if nowt < market_open:
            self.logger.info(f"[SCAN] ⏰ Market not open yet (opens at 09:15), skipping scan")
            return
        
        if nowt > market_close:
            self.logger.info(f"[SCAN] ⏰ Market closed (closes at 15:30), skipping scan")
            return
        
        if not self.within_entry_window(nowt):
            self.logger.info(f"[SCAN] Outside entry window (09:30-15:20), skipping scan")
            return

        # Daily guards
        plr = self.daily_pl_ratio()
        daily_max_loss = self.config.get("daily_max_loss", -0.02)
        daily_max_profit = self.config.get("daily_max_profit", 0.04)
        self.logger.info(f"[SCAN] Daily PnL ratio: {plr:.4f} (Loss limit: {daily_max_loss}, Profit cap: {daily_max_profit})")
        
        if plr <= daily_max_loss:
            self.logger.warning(f"[RISK_GUARD] Daily loss limit reached: {plr:.4f} <= {daily_max_loss}")
            if self.notify:
                try:
                    self.notify("risk_limit", {"type": "daily_loss", "value": plr})
                except Exception as e:
                    self.logger.error(f"[NOTIFY] Failed to send risk_limit notification: {e}")
            return
        
        if plr >= daily_max_profit:
            self.logger.warning(f"[RISK_GUARD] Daily profit cap reached: {plr:.4f} >= {daily_max_profit}")
            if self.notify:
                try:
                    self.notify("risk_limit", {"type": "daily_profit", "value": plr})
                except Exception as e:
                    self.logger.error(f"[NOTIFY] Failed to send risk_limit notification: {e}")
            return
        
        max_concurrent = self.config.get("max_concurrent_pos", 3)
        open_positions = sum(1 for p in self.positions.values() if p["status"] == "OPEN")
        self.logger.info(f"[SCAN] Open positions: {open_positions}/{max_concurrent}")
        
        if open_positions >= max_concurrent:
            self.logger.info(f"[SCAN] Max concurrent positions reached ({open_positions}/{max_concurrent})")
            return
        
        if not self.global_cooldown_ok():
            elapsed = (dt.datetime.now(self.timezone) - self.last_global_entry_time).total_seconds() / 60 if self.last_global_entry_time else 0
            self.logger.info(f"[SCAN] Global cooldown active (elapsed: {elapsed:.1f} min, required: {self.config.get('min_minutes_between_entries', 10)} min)")
            return
        
        self.logger.info("[SCAN] All pre-checks passed, fetching market data...")

        # Fetch spot data and indicators
        try:
            nifty_token = self.config.get("nifty_token", 256265)
            self.logger.info(f"[SCAN_DATA] Fetching spot data for token {nifty_token}...")
            spot_df = self.logic.fetch_spot_5m(nifty_token, days=2)
            
            if spot_df is not None and not spot_df.empty:
                self.logger.info(f"[SCAN_DATA] Fetched {len(spot_df)} candles, Date range: {spot_df['datetime'].min()} to {spot_df['datetime'].max()}")
                self.logger.info(f"[SCAN_DATA] Latest candle: Time={spot_df['datetime'].iloc[-1]}, Close={spot_df['close'].iloc[-1]:.2f}")
                
                # Check data freshness - last candle should be very recent during market hours
                last_candle_time = spot_df['datetime'].iloc[-1]
                if hasattr(last_candle_time, 'tz_localize'):
                    last_candle_time = last_candle_time.tz_localize(None)
                elif hasattr(last_candle_time, 'tz_convert'):
                    last_candle_time = last_candle_time.tz_convert(None).replace(tzinfo=None)
                
                # Use IST for comparison
                now_ist = dt.datetime.now(self.timezone).replace(tzinfo=None)
                data_age_minutes = (now_ist - last_candle_time).total_seconds() / 60
                self.logger.info(f"[SCAN_DATA] Data freshness: Last candle was {data_age_minutes:.1f} minutes ago (Current IST: {now_ist.strftime('%H:%M:%S')})")
                
                # During market hours, data should be fresh (within 10 minutes to allow for slight delays)
                # The live candle injection in fetch_spot_5m should keep data current
                if data_age_minutes > 10:
                    self.logger.warning(f"[SCAN_DATA] ⚠️ STALE DATA WARNING! Last candle is {data_age_minutes:.1f} minutes old")
                    self.logger.warning(f"[SCAN_DATA] This may indicate an issue with live data injection or API delays")
                    # Don't return - allow processing with warning since we're in market hours
                
                self.logger.info(f"[SCAN_DATA] ✅ Data received, analyzing 5-min candle")
            
            atr_period = self.config.get("atr_period", 14)
            spot_df = self.logic.add_spot_indicators(spot_df, atr_period)
        except Exception as e:
            self.logger.error(f"[ERROR] Spot fetch/indicator error: {e}", exc_info=True)
            if self.notify:
                try:
                    self.notify("error", {"error": str(e), "type": "spot_fetch"})
                except Exception as notify_error:
                    self.logger.error(f"[NOTIFY] Failed to send error notification: {notify_error}")
            return

        if spot_df is None or len(spot_df) < 10:
            self.logger.info(f"[SCAN] Not enough spot candles: {len(spot_df) if spot_df is not None else 0}/10")
            return

        # Filter to only TODAY's candles for EMA crossover detection
        # EMAs are calculated on full historical data, but we only look at today's values
        today_date = now_dt.date()
        spot_df_today = spot_df[spot_df['datetime'].dt.date == today_date].copy()
        
        if len(spot_df_today) < 2:
            self.logger.info(f"[SCAN] Not enough TODAY's candles for crossover: {len(spot_df_today)}/2 (have {len(spot_df)} total including history)")
            return
        
        self.logger.info(f"[SCAN_DATA] Using {len(spot_df_today)} candles from today (out of {len(spot_df)} total with history)")
        
        last_spot = spot_df_today.iloc[-1]
        current_ema5 = last_spot['EMA5']
        current_ema20 = last_spot['EMA20']
        
        # Log last 3 candles for debugging (from today only)
        if len(spot_df_today) >= 3:
            self.logger.info(f"[SCAN_DATA] Last 3 TODAY's candles close prices: {spot_df_today['close'].iloc[-3]:.2f}, {spot_df_today['close'].iloc[-2]:.2f}, {spot_df_today['close'].iloc[-1]:.2f}")
        else:
            self.logger.info(f"[SCAN_DATA] Latest TODAY's candle close price: {spot_df_today['close'].iloc[-1]:.2f}")
        
        # Use stored previous EMA values from last cycle for accurate crossover detection
        if self.prev_ema5 is not None and self.prev_ema20 is not None:
            self.logger.info(f"[SCAN_EMA] Previous (from last cycle): EMA5={self.prev_ema5:.2f}, EMA20={self.prev_ema20:.2f}, Position={'ABOVE' if self.prev_ema5 > self.prev_ema20 else 'BELOW'}")
        else:
            # First cycle of the day - initialize with current values but don't detect crossover yet
            # We need at least 2 scan cycles to detect a crossover
            self.logger.info(f"[SCAN_EMA] FIRST SCAN CYCLE - Initializing EMA tracking (no crossover detection yet)")
            self.logger.info(f"[SCAN_EMA] Current  (this cycle):       EMA5={current_ema5:.2f}, EMA20={current_ema20:.2f}, Position={'ABOVE' if current_ema5 > current_ema20 else 'BELOW'}")
            # Store current values for next cycle
            self.prev_ema5 = current_ema5
            self.prev_ema20 = current_ema20
            self.logger.info(f"[SCAN_EMA] Stored for next cycle: EMA5={current_ema5:.2f}, EMA20={current_ema20:.2f}")
            self.logger.info("[SCAN] First cycle - skipping crossover detection, initializing baseline")
            return
        
        self.logger.info(f"[SCAN_EMA] Current  (this cycle):       EMA5={current_ema5:.2f}, EMA20={current_ema20:.2f}, Position={'ABOVE' if current_ema5 > current_ema20 else 'BELOW'}")
        
        # Show what iloc[-2] would have given (for comparison with old buggy behavior)
        prev_spot_debug = spot_df.iloc[-2]
        self.logger.info(f"[SCAN_EMA] DEBUG: iloc[-2] would show: EMA5={prev_spot_debug['EMA5']:.2f}, EMA20={prev_spot_debug['EMA20']:.2f} (OLD BUGGY METHOD)")

        # EMA crossover signal with duplicate detection
        signal_side = None
        current_candle_time = spot_df['datetime'].iloc[-1]
        
        # Convert to naive datetime for comparison if needed
        if hasattr(current_candle_time, 'tz') and current_candle_time.tz is not None:
            current_candle_time = current_candle_time.replace(tzinfo=None)
        elif hasattr(current_candle_time, 'tz_localize'):
            current_candle_time = current_candle_time.tz_localize(None)
        
        # Check if we already processed a signal for this candle timestamp
        if self.last_signal_candle_time == current_candle_time:
            self.logger.info(f"[SCAN_SIGNAL] Already processed signal for candle at {current_candle_time}, skipping duplicate")
            # Update stored EMA values even if skipping duplicate
            self.prev_ema5 = current_ema5
            self.prev_ema20 = current_ema20
            return
        
        # Detect crossover using stored previous values vs current values
        if self.prev_ema5 <= self.prev_ema20 and current_ema5 > current_ema20:
            signal_side = "CE"
            self.last_signal_candle_time = current_candle_time  # Mark this candle as processed
            self.logger.info(f"[SCAN_SIGNAL] 🔵 BULLISH EMA CROSSOVER DETECTED! EMA5 crossed above EMA20 - Signal: {signal_side}")
            
            # Send Telegram alert for bullish crossover
            try:
                spot_ltp = last_spot["close"]
                atm = self.logic.round_to_50(spot_ltp)
                self.telegram.send_ema_crossover_alert(
                    signal_side=signal_side,
                    ema5=current_ema5,
                    ema20=current_ema20,
                    spot_ltp=spot_ltp,
                    atm=atm
                )
            except Exception as e:
                self.logger.error(f"[TELEGRAM] Failed to send bullish crossover alert: {e}")
        elif self.prev_ema5 >= self.prev_ema20 and current_ema5 < current_ema20:
            signal_side = "PE"
            self.last_signal_candle_time = current_candle_time  # Mark this candle as processed
            self.logger.info(f"[SCAN_SIGNAL] 🔴 BEARISH EMA CROSSOVER DETECTED! EMA5 crossed below EMA20 - Signal: {signal_side}")
            
            # Send Telegram alert for bearish crossover
            try:
                spot_ltp = last_spot["close"]
                atm = self.logic.round_to_50(spot_ltp)
                self.telegram.send_ema_crossover_alert(
                    signal_side=signal_side,
                    ema5=current_ema5,
                    ema20=current_ema20,
                    spot_ltp=spot_ltp,
                    atm=atm
                )
            except Exception as e:
                self.logger.error(f"[TELEGRAM] Failed to send bearish crossover alert: {e}")
        else:
            self.logger.info(f"[SCAN_EMA] No crossover - EMA5 {'above' if current_ema5 > current_ema20 else 'below'} EMA20 (diff: {abs(current_ema5 - current_ema20):.2f})")

        # Store current EMA values for next cycle (CRITICAL: these will be "Previous" in next scan)
        self.logger.info(f"[SCAN_EMA] Storing for next cycle: EMA5={current_ema5:.2f}, EMA20={current_ema20:.2f}")
        self.prev_ema5 = current_ema5
        self.prev_ema20 = current_ema20
        
        if not signal_side:
            self.logger.info("[SCAN] No EMA crossover signal this candle")
            return

        # Get spot LTP and identify ATM option for trade planning
        try:
            spot_ltp_data = self.kite.ltp(nifty_token)
            spot_ltp = list(spot_ltp_data.values())[0]["last_price"]
        except Exception as e:
            self.logger.error(f"[ERROR] Spot LTP failed: {e}", exc_info=True)
            if self.notify:
                try:
                    self.notify("error", {"error": str(e), "type": "spot_ltp"})
                except Exception as notify_error:
                    self.logger.error(f"[NOTIFY] Failed to send error notification: {notify_error}")
            return

        atm = self.logic.round_to_50(spot_ltp)
        expiry = self.logic.get_next_expiry()
        underlying = self.config.get("underlying_name", "NIFTY")
        self.logger.info(f"[SCAN_OPTION] Spot LTP: {spot_ltp:.2f}, ATM Strike: {atm}, Expiry: {expiry}, Side: {signal_side}")
        
        tsym, token = self.logic.lookup_option(underlying, expiry, atm, signal_side)
        if not tsym or not token:
            self.logger.warning(f"[SCAN_OPTION] ❌ ATM option not found: {underlying} {expiry} {atm} {signal_side}")
            return
        
        self.logger.info(f"[SCAN_OPTION] ✅ Option identified: {tsym}")
        
        # Get option LTP and calculate planned SL/Target (shown even if filters fail)
        try:
            ltp_info = self.kite.ltp(f"NFO:{tsym}")
            entry_ltp = list(ltp_info.values())[0]["last_price"]
            atr_value = spot_df["ATR"].iloc[-1]
            
            # Calculate planned SL and Target
            is_call = signal_side == "CE"
            is_put = signal_side == "PE"
            # When BUYING options (both CE and PE), you profit when premium INCREASES
            # SL is below entry, Target is above entry (same for both CE and PE)
            planned_sl = entry_ltp - atr_value
            planned_target = entry_ltp + atr_value
            
            self.logger.info(f"[SCAN_PLAN] 📊 Trade Plan: {tsym} @ ₹{entry_ltp:.2f} | SL: ₹{planned_sl:.2f} | Target: ₹{planned_target:.2f} | ATR: {atr_value:.2f}")
        except Exception as e:
            self.logger.warning(f"[SCAN_PLAN] Could not fetch option LTP for planning: {e}")
            entry_ltp = None
        
        # ATR filter with configurable threshold
        # The atr_filter parameter allows trades when current ATR is at least (atr_filter * median_atr)
        # Default: 0.8 means current ATR must be at least 80% of median ATR
        atr_median = spot_df["ATR"].rolling(20).median().iloc[-1]
        atr_filter_threshold = self.config.get("atr_filter", 0.8)
        atr_threshold = atr_median * atr_filter_threshold
        
        self.logger.info(f"[SCAN_ATR] Current ATR: {last_spot['ATR']:.2f}, 20-period Median: {atr_median:.2f}, Threshold ({atr_filter_threshold*100:.0f}% of median): {atr_threshold:.2f}")
        
        if pd.isna(atr_median) or last_spot["ATR"] < atr_threshold:
            self.logger.info(f"[SCAN_ATR] ❌ Market too quiet - ATR ({last_spot['ATR']:.2f}) below threshold ({atr_threshold:.2f}), skipping entry")
            return
        
        self.logger.info(f"[SCAN_ATR] ✅ ATR filter passed - Market volatile enough (ATR {last_spot['ATR']:.2f} >= {atr_threshold:.2f})")

        # VWAP filter on NIFTY FUT
        try:
            fut_token, fut_symbol = self.logic.get_nifty_weekly_fut_token()
            if fut_token is None:
                self.logger.error("[ERROR] Cannot proceed without NIFTY FUT token")
                return

            fut_df = self.logic.fetch_fut_5m(fut_token, days=2)
            if fut_df is None or len(fut_df) < 10:
                self.logger.warning(f"[SCAN] Not enough FUT candles: {len(fut_df) if fut_df is not None else 0}/10")
                return
            
            # Note: Live candle injection removed - 3-second scan delay ensures API has processed completed candle
            fut_df = self.logic.compute_vwap(fut_df)
            fut_last = fut_df.iloc[-1]
            vwap_direction_ok = (signal_side == "CE" and fut_last["close"] > fut_last["VWAP"]) or \
                                (signal_side == "PE" and fut_last["close"] < fut_last["VWAP"])
            
            self.logger.info(f"[SCAN_VWAP] FUT Close: {fut_last['close']:.2f}, VWAP: {fut_last['VWAP']:.2f}, Diff: {(fut_last['close'] - fut_last['VWAP']):.2f}")
            self.logger.info(f"[SCAN_VWAP] Direction check: Signal={signal_side}, Close {'>' if fut_last['close'] > fut_last['VWAP'] else '<'} VWAP, Result: {'✅ PASS' if vwap_direction_ok else '❌ FAIL'}")

            if not vwap_direction_ok:
                self.logger.info(f"[SCAN_VWAP] ❌ VWAP filter failed - FUT price on wrong side of VWAP for {signal_side} signal")
                return
            
            self.logger.info(f"[SCAN_VWAP] ✅ VWAP filter passed")
        except Exception as e:
            self.logger.error(f"[ERROR] FUT VWAP calc failed: {e}", exc_info=True)
            if self.notify:
                try:
                    self.notify("error", {"error": str(e), "type": "vwap_calc"})
                except Exception as notify_error:
                    self.logger.error(f"[NOTIFY] Failed to send error notification: {notify_error}")
            return

        # Check duplicates / cooldown
        if tsym in self.entered_symbols_today and (tsym in self.positions and self.positions[tsym]["status"] == "OPEN"):
            self.logger.info(f"[SCAN_COOLDOWN] ❌ Already in position: {tsym}")
            return
        
        if not self.symbol_cooldown_ok(tsym):
            elapsed = (dt.datetime.now(self.timezone) - self.symbol_last_exit_time.get(tsym)).total_seconds() / 60 if tsym in self.symbol_last_exit_time else 0
            self.logger.info(f"[SCAN_COOLDOWN] ❌ Symbol cooldown active for {tsym} (elapsed: {elapsed:.1f} min, required: {self.config.get('per_symbol_cooldown_min', 20)} min)")
            return
        
        self.logger.info(f"[SCAN_COOLDOWN] ✅ No position conflicts or cooldowns")

        # Reconfirm entry LTP before placing order (if not already fetched)
        if entry_ltp is None:
            try:
                ltp_info = self.kite.ltp(f"NFO:{tsym}")
                entry_ltp = list(ltp_info.values())[0]["last_price"]
            except Exception as e:
                self.logger.error(f"[ERROR] Option LTP failed: {e}", exc_info=True)
                if self.notify:
                    try:
                        self.notify("error", {"error": str(e), "type": "option_ltp"})
                    except Exception as notify_error:
                        self.logger.error(f"[NOTIFY] Failed to send error notification: {notify_error}")
                return

        self.logger.info(f"[SCAN_ENTRY] 🎯 ALL FILTERS PASSED! Executing entry for {tsym} at ₹{entry_ltp:.2f}")
        self.log_trade(tsym, "BUY", entry_ltp, status="PLANNED", note="signal (spot EMA + FUT VWAP)")
        atr_value = spot_df["ATR"].iloc[-1]
        lot_qty = self.config.get("lot_qty", 75)
        
        self.logger.info(f"[SCAN_ENTRY] Order details - Symbol: {tsym}, Price: {entry_ltp:.2f}, Qty: {lot_qty}, ATR: {atr_value:.2f}")

        # Place real market order
        try:
            self.logger.info(f"[ORDER] Placing BUY order for {tsym}...")
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
            self.log_trade(tsym, "BUY", entry_ltp, status="SUCCESS", note=f"filled - Order ID: {order_id}")
            self.entered_symbols_today.add(tsym)
            self.last_global_entry_time = dt.datetime.now(self.timezone)
            
            if self.notify:
                try:
                    self.notify("order_executed", {"symbol": tsym, "action": "BUY", "price": entry_ltp, "qty": lot_qty, "order_id": order_id})
                except Exception as notify_error:
                    self.logger.error(f"[NOTIFY] Failed to send order_executed notification: {notify_error}")
        except Exception as e:
            self.logger.error(f"[ORDER_FAILED] BUY {tsym}: {e}", exc_info=True)
            self.log_trade(tsym, "BUY", entry_ltp, status="FAILED", note=str(e))
            if self.notify:
                try:
                    self.notify("order_failed", {"symbol": tsym, "action": "BUY", "error": str(e)})
                except Exception as notify_error:
                    self.logger.error(f"[NOTIFY] Failed to send order_failed notification: {notify_error}")

    def monitor_positions_once(self) -> None:
        """Monitor and manage open positions from v1.1.py"""
        if self._shutdown_requested:
            self.logger.info("[MONITOR] Shutdown requested, skipping monitoring")
            return
        
        nowt = dt.datetime.now(self.timezone).time()
        
        # Quick return if no positions
        if not self.positions:
            return

        tokens = [f"NFO:{sym}" for sym in self.positions.keys() if self.positions[sym]["status"] == "OPEN"]
        if not tokens:
            return
        
        # Log monitoring activity (info level so it's visible)
        open_count = len(tokens)
        self.logger.info(f"[MONITOR] Checking {open_count} open position(s) at {nowt.strftime('%H:%M:%S')}")

        ltp_data = {}
        try:
            ltp_info = self.kite.ltp(tokens)
            for sym in self.positions:
                if self.positions[sym]["status"] != "OPEN":
                    continue
                key = f"NFO:{sym}"
                entry = ltp_info.get(key)
                if entry:
                    # Handle both dict and direct value responses from kite.ltp()
                    if isinstance(entry, dict):
                        # If entry is a dict, extract last_price
                        if "last_price" in entry:
                            ltp_data[sym] = entry["last_price"]
                        else:
                            # Nested dict structure
                            ltp_data[sym] = list(entry.values())[0]["last_price"]
                    else:
                        # Direct numeric value
                        self.logger.warning(f"[MONITOR] Unexpected LTP response format for {sym}: {type(entry)}")
        except Exception as e:
            self.logger.error(f"[ERROR] LTP fetch failed: {e}", exc_info=True)
            if self.notify:
                try:
                    self.notify("error", {"error": str(e), "type": "ltp_fetch"})
                except Exception as notify_error:
                    self.logger.error(f"[NOTIFY] Failed to send error notification: {notify_error}")
            return

        trail_start_pct = self.config.get("trail_start_pct", 0.20)
        trail_giveback_pct = self.config.get("trail_giveback_pct", 0.03)
        eod_squareoff = dt.time(15, 10)  # Exit earlier to avoid last-minute illiquidity

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
            # When BUYING options (CE or PE), both profit when premium increases
            # FIX: Don't reset SL when trailing activates - keep the dynamic SL progress
            if not pos["trailing_active"]:
                trigger_price = entry_price * (1 + trail_start_pct)
                if ltp >= trigger_price:
                    # Don't modify SL - let dynamic ATR handle it
                    # Just activate the trailing flag to enable giveback logic
                    pos["trailing_active"] = True
                    self.logger.info(f"[TRAILING] Activated for {symbol}, keeping dynamic SL: {pos['sl_price']:.2f}")

            # Dynamic ATR-based SL (FIX: Use tighter multiplier, don't move target)
            # When BUYING options (both CE and PE), profit when premium increases
            # So SL should be below current price
            if is_call or is_put:
                atr_multiplier = self.config.get("dynamic_atr_multiplier", 0.85)
                dynamic_sl = ltp - (atr * atr_multiplier)
                
                if dynamic_sl > pos["sl_price"]:
                    old_sl = pos["sl_price"]
                    pos["sl_price"] = dynamic_sl
                    self.logger.info(f"[DYNAMIC_SL] {symbol}: {old_sl:.2f} -> {pos['sl_price']:.2f}")
                
                # REMOVED: Don't move target dynamically - creates moving goalpost
                # Keep original target from entry time

            # Trailing giveback adjustments
            # When BUYING options (CE or PE), trail SL upward as premium increases
            if pos["trailing_active"]:
                proposed_sl = ltp * (1 - trail_giveback_pct)
                if proposed_sl > pos["sl_price"]:
                    old_sl = pos["sl_price"]
                    pos["sl_price"] = proposed_sl
                    self.logger.info(f"[TRAILING_UPDATE] {symbol} SL raised: {old_sl:.2f} -> {pos['sl_price']:.2f}")

            # Check SL/TGT/EOD
            # When BUYING options (CE or PE), both profit when premium increases
            hit_sl = ltp <= pos["sl_price"]  # Exit if premium drops to SL
            hit_tgt = ltp >= pos["target_price"]  # Exit if premium rises to target
            time_exit = nowt >= eod_squareoff
            
            # Log current position status every check
            pnl_current = (ltp - entry_price) * pos["quantity"]
            pnl_pct_current = ((ltp - entry_price) / entry_price * 100) if entry_price > 0 else 0
            self.logger.info(f"[MONITOR] {symbol}: LTP={ltp:.2f}, Entry={entry_price:.2f}, SL={pos['sl_price']:.2f}, TGT={pos['target_price']:.2f}, PnL={pnl_current:.2f} ({pnl_pct_current:+.2f}%)")

            if hit_sl or hit_tgt or time_exit:
                reason = "SL" if hit_sl else ("TGT" if hit_tgt else "EOD")
                self.logger.warning(f"[MONITOR] 🚨 EXIT TRIGGER: {symbol} - Reason: {reason}, LTP: {ltp:.2f}")
                try:
                    self.kite.place_order(
                        variety=self.kite.VARIETY_REGULAR,
                        exchange=self.kite.EXCHANGE_NFO,
                        tradingsymbol=symbol,
                        transaction_type=self.kite.TRANSACTION_TYPE_SELL,  # Always SELL when closing bought options
                        quantity=pos["quantity"],
                        order_type=self.kite.ORDER_TYPE_MARKET,
                        product=self.kite.PRODUCT_MIS
                    )
                    self.exit_position(symbol, ltp, reason=reason)
                except Exception as e:
                    self.logger.error(f"[ORDER_FAILED] Exit {symbol}: {e}", exc_info=True)
                    self.log_trade(symbol, "SELL" if is_call else "BUY", pos["entry_price"], ltp, status="FAILED", note=f"{reason}: {e}")
                    if self.notify:
                        try:
                            self.notify("order_failed", {"symbol": symbol, "action": "EXIT", "error": str(e)})
                        except Exception as notify_error:
                            self.logger.error(f"[NOTIFY] Failed to send order_failed notification: {notify_error}")

    def close_all_positions(self) -> None:
        """Emergency close all open positions"""
        self.logger.warning("[EMERGENCY] Closing all open positions")
        closed_count = 0
        failed_count = 0
        
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
                        closed_count += 1
                    except Exception as e:
                        failed_count += 1
                        self.logger.error(f"[EMERGENCY] Failed to close {sym}: {e}", exc_info=True)
                        self.log_trade(sym, "SELL", pos["entry_price"], status="FAILED", note=f"EMERGENCY_CLOSE: {e}")
                        if self.notify:
                            try:
                                self.notify("error", {"error": str(e), "type": "emergency_close", "symbol": sym})
                            except Exception as notify_error:
                                self.logger.error(f"[NOTIFY] Failed to send error notification: {notify_error}")
            
            self.logger.info(f"[EMERGENCY] Closed {closed_count} positions, {failed_count} failed")
        except Exception as e:
            self.logger.error(f"[EMERGENCY] Critical error in close_all_positions: {e}", exc_info=True)
            if self.notify:
                try:
                    self.notify("error", {"error": str(e), "type": "close_all_positions"})
                except Exception as notify_error:
                    self.logger.error(f"[NOTIFY] Failed to send error notification: {notify_error}")
            raise
    
    def send_end_of_day_summary(self) -> bool:
        """Send comprehensive trading session summary to Telegram at end of day (after 3:30 PM)"""
        try:
            now = dt.datetime.now(self.timezone)
            market_close = dt.time(15, 30)
            
            # Check if market has closed
            if now.time() < market_close:
                self.logger.debug(f"[EOD_SUMMARY] Market not closed yet ({now.time().strftime('%H:%M')}), skipping summary")
                return False
            
            # Check if summary already sent today
            if self.session_summary_sent:
                self.logger.debug("[EOD_SUMMARY] Summary already sent for today")
                return False
            
            session_end_time = now.strftime("%Y-%m-%d %H:%M:%S")
            capital = self.config.get("capital_base", 300000)
            
            self.logger.info("[EOD_SUMMARY] Generating end-of-day trading session summary...")
            
            # Send summary via Telegram
            success = self.telegram.send_session_summary(
                trade_logs=self.trade_logs,
                positions=self.positions,
                realized_pnl=self.realized_pnl,
                capital_base=capital,
                session_start=self.session_start_time,
                session_end=session_end_time
            )
            
            if success:
                self.session_summary_sent = True
                self.logger.info("[EOD_SUMMARY] ✅ Session summary sent successfully to Telegram")
            else:
                self.logger.warning("[EOD_SUMMARY] ⚠️ Failed to send session summary")
            
            return success
            
        except Exception as e:
            self.logger.error(f"[EOD_SUMMARY] Error generating session summary: {e}", exc_info=True)
            return False
    
    def check_and_send_eod_summary(self) -> None:
        """Check if it's time to send EOD summary and send if appropriate"""
        now = dt.datetime.now(self.timezone)
        market_close = dt.time(15, 30)
        
        # Only attempt between 15:30 and 16:00 to avoid repeated attempts
        if market_close <= now.time() <= dt.time(16, 0) and not self.session_summary_sent:
            self.send_end_of_day_summary()