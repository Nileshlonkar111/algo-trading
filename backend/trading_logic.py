import datetime as dt
import pandas as pd
from datetime import timedelta
from typing import Optional, Dict, List
from kiteconnect import KiteConnect

class TradingLogic:
    """Complete trading logic ported from v1.1.py"""
    
    def __init__(self, kite: KiteConnect, config: dict):
        self.kite = kite
        self.config = config
        self._instruments_cache = None
        self._instruments_cache_ts = None
        
    # Instruments & expiry helpers
    def load_instruments(self, force=False):
        if self._instruments_cache is not None and not force:
            if self._instruments_cache_ts and (dt.datetime.now() - self._instruments_cache_ts).seconds < 3600:
                return self._instruments_cache
        print("[INFO] Loading instruments (NFO)...")
        self._instruments_cache = self.kite.instruments("NFO")
        self._instruments_cache_ts = dt.datetime.now()
        return self._instruments_cache
    
    def get_next_expiry(self):
        """Return next weekly expiry (Tuesday); if today is Tuesday after 15:30, jump to next week."""
        today = dt.date.today()
        days_ahead = (1 - today.weekday()) % 7
        expiry = today + timedelta(days=days_ahead)
        if today.weekday() == 1 and dt.datetime.now().time() > dt.time(15, 30):
            expiry += timedelta(days=7)
        return expiry
    
    def round_to_50(self, x):
        return int(round(x / 50.0) * 50)
    
    def lookup_option(self, symbol_name, expiry_date, strike, option_type):
        """Return (tradingsymbol, instrument_token) for given params."""
        cached = self.load_instruments(force=False)
        def _find(cached_list):
            for inst in cached_list:
                try:
                    if inst.get("name") != symbol_name:
                        continue
                    inst_exp = inst.get("expiry")
                    if hasattr(inst_exp, "date"):
                        inst_exp = inst_exp.date()
                    if inst_exp != expiry_date:
                        continue
                    if int(inst.get("strike", 0)) != int(strike):
                        continue
                    if inst.get("instrument_type") != option_type:
                        continue
                    return inst.get("tradingsymbol"), inst.get("instrument_token")
                except Exception:
                    continue
            return None, None
        tsym, token = _find(cached)
        if tsym:
            return tsym, token
        cached = self.load_instruments(force=True)
        return _find(cached)
    
    # Indicators & data fetch
    def calculate_atr(self, df, period=14):
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        return atr
    
    def fetch_spot_5m(self, nifty_token, days=2):
        to_dt = dt.datetime.now()
        from_dt = to_dt - timedelta(days=days)
        data = self.kite.historical_data(nifty_token, from_dt, to_dt, "5minute")
        df = pd.DataFrame(data)
        if "date" in df.columns:
            df.rename(columns={"date": "datetime"}, inplace=True)
        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
        return df
    
    def fetch_fut_5m(self, fut_token, days=2):
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
            print("[ERR] fetch_fut_5m:", e)
            return None
    
    def compute_vwap(self, df):
        """Compute VWAP using typical price."""
        if df is None or df.empty:
            return df
        if not {"high", "low", "close"}.issubset(df.columns):
            return df
        typical = (df["high"] + df["low"] + df["close"]) / 3.0
        if "volume" in df.columns and df["volume"].notna().any() and (df["volume"] > 0).any():
            df["VWAP"] = (typical * df["volume"]).cumsum() / df["volume"].replace(0, pd.NA).cumsum()
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
    
    def get_nifty_weekly_fut_token(self):
        try:
            instruments = self.kite.instruments("NFO")
            today = dt.date.today()
            nearest_fut = None
            nearest_expiry = None
            for inst in instruments:
                if inst["tradingsymbol"].startswith("NIFTY") and inst["instrument_type"] == "FUT":
                    expiry_date = dt.datetime.strptime(inst["expiry"], "%Y-%m-%d").date()
                    if expiry_date >= today:
                        if nearest_expiry is None or expiry_date < nearest_expiry:
                            nearest_expiry = expiry_date
                            nearest_fut = inst
            if nearest_fut:
                return nearest_fut["instrument_token"], nearest_fut["tradingsymbol"]
            else:
                print("[ERR] No FUT contract found for NIFTY.")
                return None, None
        except Exception as e:
            print("[ERR] Fetching NIFTY FUT token failed:", e)
            return None, None