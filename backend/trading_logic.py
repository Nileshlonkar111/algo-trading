import datetime as dt
import pandas as pd
import time
from datetime import timedelta
from typing import Optional, Dict, List, Tuple
from kiteconnect import KiteConnect
import logging
from functools import wraps

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
            if self._instruments_cache_ts and (dt.datetime.now() - self._instruments_cache_ts).total_seconds() < self.CACHE_DURATION_SECONDS:
                return self._instruments_cache
        TradingLogic.logger.info("Loading instruments (NFO)...")
        self._instruments_cache = self.kite.instruments("NFO")
        self._instruments_cache_ts = dt.datetime.now()
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
        """Return next weekly expiry (Tuesday); if today is Tuesday after 15:30, jump to next week."""
        today = dt.date.today()
        days_ahead = (1 - today.weekday()) % 7
        expiry = today + timedelta(days=days_ahead)
        if today.weekday() == 1 and dt.datetime.now().time() > self.MARKET_CLOSE_TIME:
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
    
    # Indicators & data fetch
    def calculate_atr(self, df, period=14):
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        return atr
    
    @retry_on_exception(retries=3, delay=2)
    def fetch_spot_5m(self, nifty_token, days=2):
        """Fetch 5-minute historical data with live candle injection during market hours"""
        to_dt = dt.datetime.now()
        from_dt = to_dt - timedelta(days=days)
        
        # Fetch completed historical candles
        data = self.kite.historical_data(nifty_token, from_dt, to_dt, "5minute")
        df = pd.DataFrame(data)
        
        if "date" in df.columns:
            df.rename(columns={"date": "datetime"}, inplace=True)
        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
        
        # During market hours (9:15-15:30), inject current live candle
        now = dt.datetime.now()
        market_start = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_end = now.replace(hour=15, minute=30, second=0, microsecond=0)
        
        if market_start <= now <= market_end and not df.empty:
            try:
                TradingLogic.logger.info(f"[LIVE_DATA] Market hours detected, fetching live quote for token {nifty_token}...")
                
                # Get live quote - use proper format for Kite API
                # For NSE:NIFTY 50, token is 256265
                quote = self.kite.quote([f"NSE:NIFTY 50"])
                
                if quote:
                    # Extract data - handle both token and symbol key formats
                    quote_data = None
                    if f"NSE:NIFTY 50" in quote:
                        quote_data = quote[f"NSE:NIFTY 50"]
                    elif nifty_token in quote:
                        quote_data = quote[nifty_token]
                    
                    if quote_data:
                        ohlc = quote_data['ohlc']
                        last_price = quote_data['last_price']
                        
                        TradingLogic.logger.info(f"[LIVE_DATA] Got quote - Open:{ohlc['open']:.2f}, High:{ohlc['high']:.2f}, Low:{ohlc['low']:.2f}, Last:{last_price:.2f}")
                        
                        # Calculate current 5-min candle start time
                        minutes_since_market_open = (now - market_start).total_seconds() / 60
                        candle_number = int(minutes_since_market_open // 5)
                        current_candle_start = market_start + timedelta(minutes=candle_number * 5)
                        
                        # Create live candle row
                        live_candle = {
                            'datetime': current_candle_start,
                            'open': ohlc['open'],
                            'high': ohlc['high'],
                            'low': ohlc['low'],
                            'close': last_price,
                            'volume': quote_data.get('volume', 0)
                        }
                        
                        # Check if this candle already exists in historical data
                        last_hist_time = df['datetime'].iloc[-1]
                        if hasattr(last_hist_time, 'tz_localize'):
                            last_hist_time = last_hist_time.tz_localize(None)
                        
                        if last_hist_time >= current_candle_start:
                            # Update existing candle with live data
                            df.iloc[-1] = live_candle
                            TradingLogic.logger.info(f"[LIVE_DATA] ✅ Updated incomplete candle at {current_candle_start.strftime('%H:%M')} with live price {last_price:.2f}")
                        else:
                            # Append new live candle
                            df = pd.concat([df, pd.DataFrame([live_candle])], ignore_index=True)
                            TradingLogic.logger.info(f"[LIVE_DATA] ✅ Injected new live candle at {current_candle_start.strftime('%H:%M')} with price {last_price:.2f}")
                    else:
                        TradingLogic.logger.warning(f"[LIVE_DATA] Quote data not found in response keys: {list(quote.keys())}")
                        
            except Exception as e:
                TradingLogic.logger.warning(f"[LIVE_DATA] ⚠️ Failed to inject live candle: {e}")
                import traceback
                TradingLogic.logger.debug(f"[LIVE_DATA] Traceback: {traceback.format_exc()}")
                # Continue with historical data only
        elif market_start <= now <= market_end and df.empty:
            TradingLogic.logger.warning(f"[LIVE_DATA] Market hours but no historical data available")
        
        return df
    
    def fetch_fut_5m(self, fut_token, days=2):
        """Fetch 5-minute futures data - live injection handled separately via tradingsymbol"""
        try:
            to_dt = dt.datetime.now()
            from_dt = to_dt - timedelta(days=days)
            data = self.kite.historical_data(fut_token, from_dt, to_dt, "5minute")
            df = pd.DataFrame(data)
            if "date" in df.columns:
                df.rename(columns={"date": "datetime"}, inplace=True)
            if "datetime" in df.columns:
                df["datetime"] = pd.to_datetime(df["datetime"])
            return df
        except Exception as e:
            TradingLogic.logger.error("[ERR] fetch_fut_5m: %s", e)
            return None
    
    def inject_live_candle(self, df, trading_symbol):
        """Inject live candle data during market hours for any instrument"""
        if df is None or df.empty:
            return df
        
        now = dt.datetime.now()
        market_start = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_end = now.replace(hour=15, minute=30, second=0, microsecond=0)
        
        if not (market_start <= now <= market_end):
            return df
        
        try:
            TradingLogic.logger.info(f"[LIVE_DATA] Market hours detected, fetching live quote for {trading_symbol}...")
            
            # Get live quote
            quote = self.kite.quote([trading_symbol])
            
            if quote and trading_symbol in quote:
                quote_data = quote[trading_symbol]
                ohlc = quote_data['ohlc']
                last_price = quote_data['last_price']
                
                TradingLogic.logger.info(f"[LIVE_DATA] Got quote for {trading_symbol} - Open:{ohlc['open']:.2f}, High:{ohlc['high']:.2f}, Low:{ohlc['low']:.2f}, Last:{last_price:.2f}")
                
                # Calculate current 5-min candle start time
                minutes_since_market_open = (now - market_start).total_seconds() / 60
                candle_number = int(minutes_since_market_open // 5)
                current_candle_start = market_start + timedelta(minutes=candle_number * 5)
                
                # Create live candle row
                live_candle = {
                    'datetime': current_candle_start,
                    'open': ohlc['open'],
                    'high': ohlc['high'],
                    'low': ohlc['low'],
                    'close': last_price,
                    'volume': quote_data.get('volume', 0)
                }
                
                # Check if this candle already exists in historical data
                last_hist_time = df['datetime'].iloc[-1]
                if hasattr(last_hist_time, 'tz_localize'):
                    last_hist_time = last_hist_time.tz_localize(None)
                
                if last_hist_time >= current_candle_start:
                    # Update existing candle with live data
                    df.iloc[-1] = live_candle
                    TradingLogic.logger.info(f"[LIVE_DATA] ✅ Updated incomplete candle at {current_candle_start.strftime('%H:%M')} with live price {last_price:.2f}")
                else:
                    # Append new live candle
                    df = pd.concat([df, pd.DataFrame([live_candle])], ignore_index=True)
                    TradingLogic.logger.info(f"[LIVE_DATA] ✅ Injected new live candle at {current_candle_start.strftime('%H:%M')} with price {last_price:.2f}")
            else:
                TradingLogic.logger.warning(f"[LIVE_DATA] Quote data not found for {trading_symbol} in response keys: {list(quote.keys()) if quote else 'None'}")
                
        except Exception as e:
            TradingLogic.logger.warning(f"[LIVE_DATA] ⚠️ Failed to inject live candle for {trading_symbol}: {e}")
            import traceback
            TradingLogic.logger.debug(f"[LIVE_DATA] Traceback: {traceback.format_exc()}")
        
        return df
    
    def compute_vwap(self, df):
        """Compute VWAP using typical price."""
        if df is None or df.empty:
            return df
        if not {"high", "low", "close"}.issubset(df.columns):
            return df
        typical = (df["high"] + df["low"] + df["close"]) / 3.0
        if "volume" in df.columns and df["volume"].notna().any() and (df["volume"] > 0).any():
            volume_cumsum = df["volume"].replace(0, pd.NA).cumsum()
            df["VWAP"] = (typical * df["volume"]).cumsum() / volume_cumsum.replace(0, pd.NA)
        else:
            df["VWAP"] = typical.cumsum() / pd.Series(range(1, len(df) + 1))
        return df
    
    def add_spot_indicators(self, df, atr_period=14):
        if df is None or df.empty:
            return df
        close = df["close"]
        df["EMA5"] = close.ewm(span=5, adjust=False).mean()
        df["EMA20"] = close.ewm(span=20, adjust=False).mean()
        df["ATR"] = self.calculate_atr(df, period=atr_period)
        return df
    
    @retry_on_exception(retries=3, delay=2)
    def get_nifty_weekly_fut_token(self) -> Tuple[Optional[int], Optional[str]]:
        """Get nearest NIFTY weekly future token and tradingsymbol.
        
        Returns:
            Tuple of (instrument_token, tradingsymbol) or (None, None) on error
        """
        try:
            instruments = self.load_instruments()
            today = dt.date.today()
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