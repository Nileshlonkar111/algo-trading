import datetime as dt
import pandas as pd
import time
from datetime import timedelta
from typing import Optional, Dict, List, Tuple
from kiteconnect import KiteConnect
import logging
from functools import wraps
import pytz

class TradingLogic:
    """Complete trading logic ported from v1.1.py"""
    
    # Constants
    CACHE_DURATION_SECONDS = 3600
    MARKET_CLOSE_TIME = dt.time(15, 30)
    
    logger = logging.getLogger("TradingLogic")

    def __init__(self, kite: KiteConnect, config: dict):
        self.kite = kite
        self.config = config
        self._instruments_cache = None
        self._instruments_cache_ts = None
        self._option_index = {}
        self.timezone = pytz.timezone('Asia/Kolkata')

    def retry_on_exception(retries=3, delay=1):
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                for attempt in range(retries):
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        TradingLogic.logger.warning(f"Retry {attempt+1}/{retries} for {func.__name__} due to: {e}")
                        if attempt < retries - 1:
                            time.sleep(delay)
                        else:
                            raise
            return wrapper
        return decorator

    # Instruments & expiry helpers
    @retry_on_exception(retries=3, delay=2)
    def load_instruments(self, force=False):
        if self._instruments_cache is not None and not force:
            if self._instruments_cache_ts and (dt.datetime.now(self.timezone) - self._instruments_cache_ts).total_seconds() < self.CACHE_DURATION_SECONDS:
                return self._instruments_cache
        TradingLogic.logger.info("Loading instruments (NFO)...")
        self._instruments_cache = self.kite.instruments("NFO")
        self._instruments_cache_ts = dt.datetime.now(self.timezone)
        self._build_option_index()
        return self._instruments_cache
    
    def _build_option_index(self):
        """Build indexed dictionary for fast option lookups."""
        self._option_index = {}
        if self._instruments_cache:
            for inst in self._instruments_cache:
                try:
                    key = (
                        inst.get("name"),
                        inst.get("expiry"),
                        int(inst.get("strike", 0)),
                        inst.get("instrument_type")
                    )
                    self._option_index[key] = (inst.get("tradingsymbol"), inst.get("instrument_token"))
                except Exception as e:
                    TradingLogic.logger.debug(f"Failed to index instrument: {e}")
                    continue
    
    def get_next_expiry(self) -> dt.date:
        """Find actual next NIFTY expiry from available options (handles holidays automatically)"""
        try:
            instruments = self.load_instruments()
            today = dt.datetime.now(self.timezone).date()
            
            # Find all NIFTY option expiries that are >= today
            nifty_expiries = set()
            for inst in instruments:
                if inst.get("name") == "NIFTY" and inst.get("instrument_type") in ["CE", "PE"]:
                    expiry = inst.get("expiry")
                    # Handle both datetime and date objects
                    if isinstance(expiry, dt.datetime):
                        expiry = expiry.date()
                    if expiry and isinstance(expiry, dt.date) and expiry >= today:
                        nifty_expiries.add(expiry)
            
            if nifty_expiries:
                # Return the nearest expiry (current week's expiry)
                next_expiry = min(nifty_expiries)
                
                # If we're past market close on expiry day, skip to next expiry
                if next_expiry == today and dt.datetime.now(self.timezone).time() > self.MARKET_CLOSE_TIME:
                    nifty_expiries.remove(next_expiry)
                    if nifty_expiries:
                        next_expiry = min(nifty_expiries)
                
                TradingLogic.logger.info(f"[EXPIRY] Found actual next expiry from NSE: {next_expiry} ({next_expiry.strftime('%A')})")
                return next_expiry
            else:
                # Fallback to calculated Tuesday (should rarely happen)
                TradingLogic.logger.warning("[EXPIRY] No expiries found in instruments, using calculated Tuesday (fallback)")
                days_ahead = (1 - today.weekday()) % 7
                fallback_expiry = today + timedelta(days=days_ahead) if days_ahead > 0 else today + timedelta(days=7)
                return fallback_expiry
                
        except Exception as e:
            TradingLogic.logger.error(f"[EXPIRY] Error finding expiry: {e}, using calculated Tuesday (fallback)")
            # Fallback to calculated Tuesday
            today_ist = dt.datetime.now(self.timezone).date()
            days_ahead = (1 - today_ist.weekday()) % 7
            expiry = today_ist + timedelta(days=days_ahead) if days_ahead > 0 else today_ist + timedelta(days=7)
            if today_ist.weekday() == 1 and dt.datetime.now(self.timezone).time() > self.MARKET_CLOSE_TIME:
                expiry += timedelta(days=7)
            return expiry
    
    def round_to_50(self, x: float) -> int:
        return int(round(x / 50.0) * 50)
    
    def lookup_option(self, symbol_name: str, expiry_date: dt.date, strike: int, option_type: str) -> Tuple[Optional[str], Optional[int]]:
        """Return (tradingsymbol, instrument_token) for given params using indexed lookup."""
        # Ensure instruments are loaded and indexed
        self.load_instruments(force=False)
        
        # Try indexed lookup first
        key = (symbol_name, expiry_date, int(strike), option_type)
        if key in self._option_index:
            return self._option_index[key]
        
        # If not found, reload instruments and rebuild index
        self.load_instruments(force=True)
        return self._option_index.get(key, (None, None))
    
    def find_option_in_price_range(self, symbol_name: str, expiry_date: dt.date, atm_strike: int,
                                   option_type: str, spot_ltp: float,
                                   min_price: float = 150, max_price: float = 200) -> Tuple[Optional[str], Optional[int], Optional[float], Optional[int]]:
        """
        Find an option with premium in the specified price range - OPTIMIZED for speed.
        Uses batch LTP fetching to minimize API calls and execution time.
        
        Args:
            symbol_name: Underlying name (e.g., "NIFTY")
            expiry_date: Current expiry date
            atm_strike: ATM strike price
            option_type: "CE" or "PE"
            spot_ltp: Current spot price
            min_price: Minimum acceptable premium (default: 150)
            max_price: Maximum acceptable premium (default: 200)
        
        Returns:
            Tuple of (tradingsymbol, token, premium, strike) or (None, None, None, None)
        """
        TradingLogic.logger.info(f"[OPTION_FINDER] Searching for {option_type} option in range ₹{min_price}-₹{max_price}")
        TradingLogic.logger.info(f"[OPTION_FINDER] ATM Strike: {atm_strike}, Spot: {spot_ltp:.2f}")
        
        # Prepare strikes to check: ATM + ITM options
        if option_type == "CE":
            strikes = [atm_strike] + [atm_strike - (i * 50) for i in range(1, 6)]  # ATM + 5 ITM strikes
        else:  # PE
            strikes = [atm_strike] + [atm_strike + (i * 50) for i in range(1, 6)]  # ATM + 5 ITM strikes
        
        # PHASE 1: Batch lookup and fetch for current expiry (FAST - single API call)
        instruments_to_fetch = []
        strike_map = {}  # Map NFO:symbol -> (strike, tsym, token)
        
        for strike in strikes:
            tsym, token = self.lookup_option(symbol_name, expiry_date, strike, option_type)
            if tsym and token:
                nfo_key = f"NFO:{tsym}"
                instruments_to_fetch.append(nfo_key)
                strike_map[nfo_key] = (strike, tsym, token)
        
        if instruments_to_fetch:
            try:
                # Single batch API call for all options - MUCH FASTER than individual calls
                ltp_batch = self.kite.ltp(instruments_to_fetch)
                TradingLogic.logger.info(f"[OPTION_FINDER] Batch fetched {len(ltp_batch)} option prices in single API call")
                
                # Check prices in order (ATM first, then ITM)
                for nfo_key in instruments_to_fetch:
                    if nfo_key in ltp_batch:
                        strike, tsym, token = strike_map[nfo_key]
                        price = ltp_batch[nfo_key]["last_price"]
                        
                        if min_price <= price <= max_price:
                            distance = abs(strike - atm_strike)
                            position_type = "ATM" if distance == 0 else f"ITM-{distance}"
                            TradingLogic.logger.info(f"[OPTION_FINDER] ✅ Found {position_type}: {tsym} @ ₹{price:.2f}")
                            return tsym, token, price, strike
                        
                        TradingLogic.logger.debug(f"[OPTION_FINDER] {tsym} @ ₹{price:.2f} - outside range")
            except Exception as e:
                TradingLogic.logger.warning(f"[OPTION_FINDER] Batch LTP failed, falling back: {e}")
        
        # PHASE 2: Try next expiry only if current expiry failed (rare case)
        TradingLogic.logger.info(f"[OPTION_FINDER] Current expiry unsuitable, checking next expiry...")
        next_expiry = self.get_next_next_expiry(expiry_date)
        
        # Only check ATM + 2 ITM for next expiry to save time
        next_strikes = strikes[:3]  # ATM + first 2 ITM
        instruments_to_fetch = []
        strike_map = {}
        
        for strike in next_strikes:
            tsym, token = self.lookup_option(symbol_name, next_expiry, strike, option_type)
            if tsym and token:
                nfo_key = f"NFO:{tsym}"
                instruments_to_fetch.append(nfo_key)
                strike_map[nfo_key] = (strike, tsym, token)
        
        if instruments_to_fetch:
            try:
                ltp_batch = self.kite.ltp(instruments_to_fetch)
                TradingLogic.logger.info(f"[OPTION_FINDER] Next expiry: batch fetched {len(ltp_batch)} prices")
                
                for nfo_key in instruments_to_fetch:
                    if nfo_key in ltp_batch:
                        strike, tsym, token = strike_map[nfo_key]
                        price = ltp_batch[nfo_key]["last_price"]
                        
                        if min_price <= price <= max_price:
                            distance = abs(strike - atm_strike)
                            position_type = "ATM" if distance == 0 else f"ITM-{distance}"
                            TradingLogic.logger.info(f"[OPTION_FINDER] ✅ Next expiry {position_type}: {tsym} @ ₹{price:.2f}")
                            return tsym, token, price, strike
            except Exception as e:
                TradingLogic.logger.warning(f"[OPTION_FINDER] Next expiry batch failed: {e}")
        
        TradingLogic.logger.warning(f"[OPTION_FINDER] ❌ No option found in range ₹{min_price}-₹{max_price}")
        return None, None, None, None
    
    def get_next_next_expiry(self, current_expiry: dt.date) -> dt.date:
        """Get the expiry after the current expiry (next week's expiry)"""
        # Simply add 7 days to current expiry to get next week's Tuesday
        return current_expiry + timedelta(days=7)
    
    # Indicators & data fetch
    def calculate_atr(self, df, period=14):
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        return atr
    
    @retry_on_exception(retries=3, delay=2)
    def fetch_spot_5m(self, nifty_token, days=5):
        """Fetch 5-minute historical data - 5 days handles weekends/holidays efficiently"""
        # Use IST timezone for all datetime operations
        now = dt.datetime.now(self.timezone)
        to_dt = now
        # Calculate from_dt by going back 'days' calendar days
        from_dt = now - timedelta(days=days)
        
        TradingLogic.logger.info(f"[FETCH_SPOT] Requesting {days} days of data from {from_dt.strftime('%Y-%m-%d %H:%M IST')} to {to_dt.strftime('%Y-%m-%d %H:%M IST')}")
        
        # Fetch completed historical candles - API expects naive datetime in IST
        # Convert timezone-aware datetime to naive for API compatibility
        from_dt_naive = from_dt.replace(tzinfo=None)
        to_dt_naive = to_dt.replace(tzinfo=None)
        
        data = self.kite.historical_data(nifty_token, from_dt_naive, to_dt_naive, "5minute")
        df = pd.DataFrame(data)
        
        TradingLogic.logger.info(f"[FETCH_SPOT] Received {len(data)} candles from API")
        
        if "date" in df.columns:
            df.rename(columns={"date": "datetime"}, inplace=True)
        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
        
        # Log date range for debugging
        if not df.empty and "datetime" in df.columns:
            unique_dates = df["datetime"].dt.date.unique()
            TradingLogic.logger.info(f"[FETCH_SPOT] Data spans {len(unique_dates)} trading day(s): {sorted(unique_dates)}")
        
        # Note: Live candle injection removed - 3-second scan delay ensures API has processed completed candle
        TradingLogic.logger.debug(f"[FETCH_SPOT] Using historical data from API (scan delay ensures freshness)")
        
        return df
    
    def fetch_fut_5m(self, fut_token, days=2):
        """Fetch 5-minute futures data - 2 days is enough since VWAP only uses today's data"""
        try:
            # Use IST timezone
            to_dt = dt.datetime.now(self.timezone)
            from_dt = to_dt - timedelta(days=days)
            
            # Convert timezone-aware datetime to naive for API compatibility
            from_dt_naive = from_dt.replace(tzinfo=None)
            to_dt_naive = to_dt.replace(tzinfo=None)
            
            data = self.kite.historical_data(fut_token, from_dt_naive, to_dt_naive, "5minute")
            df = pd.DataFrame(data)
            if "date" in df.columns:
                df.rename(columns={"date": "datetime"}, inplace=True)
            if "datetime" in df.columns:
                df["datetime"] = pd.to_datetime(df["datetime"])
            return df
        except Exception as e:
            TradingLogic.logger.error("[ERR] fetch_fut_5m: %s", e)
            return None
    
    
    def compute_vwap(self, df):
        """Compute VWAP using typical price - calculated ONLY on today's data (intraday indicator)."""
        if df is None or df.empty:
            return df
        if not {"high", "low", "close", "datetime"}.issubset(df.columns):
            return df
        
        # Filter to TODAY's data only - VWAP resets daily
        today = dt.datetime.now(self.timezone).date()
        today_mask = df["datetime"].dt.date == today
        
        # Initialize VWAP column with NaN
        df["VWAP"] = float('nan')
        
        if today_mask.any():
            # Calculate VWAP only on today's data
            today_df = df[today_mask].copy()
            typical = (today_df["high"] + today_df["low"] + today_df["close"]) / 3.0
            
            if "volume" in today_df.columns and today_df["volume"].notna().any() and (today_df["volume"] > 0).any():
                volume_cumsum = today_df["volume"].replace(0, pd.NA).cumsum()
                today_df["VWAP"] = (typical * today_df["volume"]).cumsum() / volume_cumsum.replace(0, pd.NA)
            else:
                today_df["VWAP"] = typical.cumsum() / pd.Series(range(1, len(today_df) + 1))
            
            # Assign back to original dataframe
            df.loc[today_mask, "VWAP"] = today_df["VWAP"].values
        
        return df
    
    def add_spot_indicators(self, df, atr_period=14):
        if df is None or df.empty:
            return df
        
        # Calculate ATR on full dataset (needs historical data)
        df["ATR"] = self.calculate_atr(df, period=atr_period)
        
        # Calculate EMAs with previous trading day seeding for accurate early morning values
        today = dt.datetime.now(self.timezone).date()
        
        # Separate today's and previous trading day's data
        today_mask = df["datetime"].dt.date == today
        today_indices = df[today_mask].index
        
        # Find the most recent previous trading day (handles weekends/holidays automatically)
        previous_dates = df[~today_mask]["datetime"].dt.date.unique()
        previous_trading_day = previous_dates.max() if len(previous_dates) > 0 else None
        
        if previous_trading_day:
            previous_mask = df["datetime"].dt.date == previous_trading_day
            previous_indices = df[previous_mask].index
            TradingLogic.logger.info(f"[INDICATORS] Previous trading day: {previous_trading_day} ({len(previous_indices)} candles)")
        else:
            previous_mask = pd.Series([False] * len(df), index=df.index)
            previous_indices = df[previous_mask].index
        
        if len(today_indices) > 0:
            # Calculate EMAs on COMBINED data (previous trading day + today) for continuity
            # This matches how professional charting platforms work
            if len(previous_indices) > 0:
                # Use last 50 candles from previous trading day (more than enough for EMA20)
                previous_tail = df[previous_mask].tail(50)
                today_data = df[today_mask]
                combined_data = pd.concat([previous_tail, today_data])
                
                # Calculate EMAs on combined dataset
                combined_data["EMA5"] = combined_data["close"].ewm(span=5, adjust=False).mean()
                combined_data["EMA20"] = combined_data["close"].ewm(span=20, adjust=False).mean()
                
                # Extract only today's EMA values
                today_ema_data = combined_data[combined_data["datetime"].dt.date == today]
                df.loc[today_indices, "EMA5"] = today_ema_data["EMA5"].values
                df.loc[today_indices, "EMA20"] = today_ema_data["EMA20"].values
                
                # Set previous day's EMAs to NaN (we don't need them)
                df.loc[previous_mask, "EMA5"] = float('nan')
                df.loc[previous_mask, "EMA20"] = float('nan')
                
                TradingLogic.logger.info(f"[INDICATORS] Calculated EMAs using {len(previous_tail)} previous day candles + {len(today_indices)} today candles")
                TradingLogic.logger.info(f"[INDICATORS] ✅ EMAs available from first candle (seeded from {previous_trading_day})")
            else:
                # No previous trading day's data - calculate on today's data only (fallback)
                today_close = df.loc[today_indices, "close"]
                df.loc[today_indices, "EMA5"] = today_close.ewm(span=5, adjust=False).mean()
                df.loc[today_indices, "EMA20"] = today_close.ewm(span=20, adjust=False).mean()
                
                TradingLogic.logger.warning(f"[INDICATORS] No previous trading day data - EMAs calculated on {len(today_indices)} today candles only")
                TradingLogic.logger.warning(f"[INDICATORS] ⚠️ First few EMAs may be less reliable without seeding")
            
            # Set EMAs to NaN for any other historical data
            if previous_trading_day:
                other_mask = ~today_mask & ~previous_mask
            else:
                other_mask = ~today_mask
            df.loc[other_mask, "EMA5"] = float('nan')
            df.loc[other_mask, "EMA20"] = float('nan')
        else:
            # No today's data, set all EMAs to NaN
            df["EMA5"] = float('nan')
            df["EMA20"] = float('nan')
            TradingLogic.logger.warning(f"[INDICATORS] No candles from today ({today}), EMAs set to NaN")
        
        return df
    
    @retry_on_exception(retries=3, delay=2)
    def get_nifty_weekly_fut_token(self) -> Tuple[Optional[int], Optional[str]]:
        """Get nearest NIFTY weekly future token and tradingsymbol.
        
        Returns:
            Tuple of (instrument_token, tradingsymbol) or (None, None) on error
        """
        try:
            instruments = self.load_instruments()
            today = dt.datetime.now(self.timezone).date()
            nearest_fut = None
            nearest_expiry = None
            for inst in instruments:
                if inst["tradingsymbol"].startswith("NIFTY") and inst["instrument_type"] == "FUT":
                    # Handle expiry field - could be date object or datetime
                    expiry_date = inst["expiry"]
                    if isinstance(expiry_date, dt.datetime):
                        expiry_date = expiry_date.date()
                    elif not isinstance(expiry_date, dt.date):
                        TradingLogic.logger.warning(f"Unexpected expiry type: {type(expiry_date)}")
                        continue
                    
                    if expiry_date >= today:
                        if nearest_expiry is None or expiry_date < nearest_expiry:
                            nearest_expiry = expiry_date
                            nearest_fut = inst
            if nearest_fut:
                return nearest_fut["instrument_token"], nearest_fut["tradingsymbol"]
            else:
                TradingLogic.logger.error("No FUT contract found for NIFTY.")
                return None, None
        except Exception as e:
            TradingLogic.logger.error(f"Fetching NIFTY FUT token failed: {e}")
            return None, None