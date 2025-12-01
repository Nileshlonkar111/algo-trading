import datetime as dt
import time
import pandas as pd
from kiteconnect import KiteConnect
from datetime import timedelta

# =========================
# 🔧 User Config / Risk
# =========================
API_KEY = "4alf9iink08mzw85"
ACCESS_TOKEN = "qxULcz0KN0SXTZR4tnPEb2mRefGVAxuc"

NIFTY_TOKEN = 256265            # Index token used for spot LTP fetch
UNDERLYING_NAME = "NIFTY"       # Name used in instruments lookup
LOT_QTY = 75
MAX_CONCURRENT_POS = 3
MIN_MINUTES_BETWEEN_ENTRIES = 10
PER_SYMBOL_COOLDOWN_MIN = 20
DAILY_MAX_LOSS = -0.02
DAILY_MAX_PROFIT = 0.04
CAPITAL_BASE = 300000
ENTRY_WINDOW_START = dt.time(9, 30)
ENTRY_WINDOW_END = dt.time(15, 20)
EOD_SQUAREOFF = dt.time(15, 20)

ATR_PERIOD = 14
TRAIL_START_PCT = 0.15
TRAIL_GIVEBACK_PCT = 0.10
LOG_FILE = "trades_log.csv"
PAPER_TRADING = False  # True -> no real orders

# VWAP distance threshold (percentage)
MIN_VWAP_DISTANCE_PCT = 0.15

# =========================
# 🔌 Kite Initialization
# =========================
kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

# =========================
# 🧾 Logging helpers
# =========================
def _log_df_row(row: dict):
    df = pd.DataFrame([row])
    import os
    header_needed = not os.path.exists(LOG_FILE)
    df.to_csv(LOG_FILE, mode="a", header=header_needed, index=False)

def log_trade(symbol, action, entry_price, exit_price=None, status="PLANNED", pnl=None, pnl_pct=None, note=None):
    row = {
        "time": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": symbol,
        "action": action,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "status": status,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "note": note
    }
    _log_df_row(row)
    print("Log:", row)

# =========================
# 📅 Instruments & expiry helpers
# =========================
_instruments_cache = None
_instruments_cache_ts = None

def load_instruments(force=False):
    global _instruments_cache, _instruments_cache_ts
    if _instruments_cache is not None and not force:
        # cache for 1 hour
        if _instruments_cache_ts and (dt.datetime.now() - _instruments_cache_ts).seconds < 3600:
            return _instruments_cache
    print("[INFO] Loading instruments (NFO)...")
    _instruments_cache = kite.instruments("NFO")
    _instruments_cache_ts = dt.datetime.now()
    return _instruments_cache

def get_next_expiry():
    """
    Return next weekly expiry (Tuesday); 
    if today is Tuesday after 15:30, jump to next week.
    """
    today = dt.date.today()
    # 0=Monday ... 1=Tuesday
    days_ahead = (1 - today.weekday()) % 7
    expiry = today + timedelta(days=days_ahead)

    if today.weekday() == 1 and dt.datetime.now().time() > dt.time(15, 30):
        expiry += timedelta(days=7)

    return expiry

def round_to_50(x):
    return int(round(x / 50.0) * 50)

def lookup_option(symbol_name, expiry_date, strike, option_type):
    """
    Return (tradingsymbol, instrument_token) for given params.
    expiry_date: date object
    option_type: "CE" or "PE"
    """
    cached = load_instruments(force=False)
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
    # forced reload if not found
    cached = load_instruments(force=True)
    return _find(cached)

# =========================
# 📈 Indicators & data fetch
# =========================
def calculate_atr(df, period=14):
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    return atr

def fetch_spot_5m(days=2):
    to_dt = dt.datetime.now()
    from_dt = to_dt - timedelta(days=days)
    data = kite.historical_data(NIFTY_TOKEN, from_dt, to_dt, "5minute")
    df = pd.DataFrame(data)
    if "date" in df.columns:
        df.rename(columns={"date": "datetime"}, inplace=True)
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"])
    return df

def fetch_premium_5m(instrument_token, days=2):
    """
    Fetch 5-min candles for the option instrument token (NFO token).
    instrument_token is the numeric token returned by instruments table.
    """
    try:
        to_dt = dt.datetime.now()
        from_dt = to_dt - timedelta(days=days)
        data = kite.historical_data(instrument_token, from_dt, to_dt, "5minute")
        pdf = pd.DataFrame(data)
        if pdf.empty:
            return None
        if "date" in pdf.columns:
            pdf.rename(columns={"date": "datetime"}, inplace=True)
        if "datetime" in pdf.columns:
            pdf["datetime"] = pd.to_datetime(pdf["datetime"])
        return pdf
    except Exception as e:
        print("[ERR] fetch_premium_5m:", e)
        return None

def compute_vwap(df):
    """
    Compute VWAP using typical price; if volume missing/zero, fallback to cumulative typical average.
    """
    if df is None or df.empty:
        return df
    if not {"high", "low", "close"}.issubset(df.columns):
        return df
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    if "volume" in df.columns and df["volume"].notna().any() and (df["volume"] > 0).any():
        df["VWAP"] = (typical * df["volume"]).cumsum() / df["volume"].replace(0, pd.NA).cumsum()
    else:
        # fallback (NOT true VWAP)
        df["VWAP"] = typical.cumsum() / pd.Series(range(1, len(df) + 1))
    return df

def add_spot_indicators(df):
    if df is None or df.empty:
        return df
    close = df["close"]
    df["EMA5"] = close.ewm(span=5, adjust=False).mean()
    df["EMA20"] = close.ewm(span=20, adjust=False).mean()
    df["ATR"] = calculate_atr(df, period=ATR_PERIOD)
    return df

# =========================
# 📊 Positions & Risk
# =========================
positions = {}
entered_symbols_today = set()
last_global_entry_time = None
symbol_last_exit_time = {}
realized_pnl = 0.0

def add_position(symbol, entry_price, qty, atr=None):
    atr = atr if atr else max(0.0001, entry_price * 0.25)  # safe default
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

    positions[symbol] = {
        "entry_price": entry_price,
        "quantity": qty,
        "sl_price": sl_price,
        "target_price": target_price,
        "trailing_active": False,
        "status": "OPEN",
        "opened_at": dt.datetime.now(),
        "atr": atr,
        "is_call": is_call,
        "is_put": is_put
    }
    log_trade(symbol, "BUY", entry_price, status="PLANNED", note=f"signal, SL={sl_price:.2f}, TGT={target_price:.2f}")
    print(f"[OPEN] {symbol} @ {entry_price} qty={qty} SL={sl_price:.2f} TGT={target_price:.2f}")

def exit_position(symbol, exit_price, reason="EXIT"):
    global realized_pnl
    pos = positions.get(symbol)
    if not pos or pos["status"] != "OPEN":
        return
    pnl_per_unit = (exit_price - pos["entry_price"])
    pnl = pnl_per_unit * pos["quantity"]
    pnl_pct = (pnl_per_unit / pos["entry_price"]) * 100 if pos["entry_price"] else None
    realized_pnl += pnl
    pos["status"] = "CLOSED"
    symbol_last_exit_time[symbol] = dt.datetime.now()
    log_trade(symbol, "SELL", pos["entry_price"], exit_price, status="SUCCESS", pnl=pnl, pnl_pct=pnl_pct, note=reason)
    print(f"[CLOSE] {symbol} @ {exit_price} | PnL {pnl:.2f} ({pnl_pct:.2f}%) | Reason: {reason}")

def daily_pl_ratio():
    if CAPITAL_BASE <= 0:
        return 0.0
    return realized_pnl / CAPITAL_BASE

def within_entry_window(t):
    return ENTRY_WINDOW_START <= t <= ENTRY_WINDOW_END

def global_cooldown_ok():
    global last_global_entry_time
    if last_global_entry_time is None:
        return True
    return (dt.datetime.now() - last_global_entry_time).total_seconds() >= MIN_MINUTES_BETWEEN_ENTRIES * 60

def symbol_cooldown_ok(symbol):
    last = symbol_last_exit_time.get(symbol)
    if last is None:
        return True
    return (dt.datetime.now() - last).total_seconds() >= PER_SYMBOL_COOLDOWN_MIN * 60
    
    
def get_nifty_weekly_fut_token():
    try:
        instruments = kite.instruments("NFO")
        today = dt.date.today()
        nearest_fut = None
        nearest_expiry = None

        for inst in instruments:
            if inst["tradingsymbol"].startswith("NIFTY") and inst["instrument_type"] == "FUT":
                expiry_date = dt.datetime.strptime(inst["expiry"], "%Y-%m-%d").date()
                # Only consider future contracts
                if expiry_date >= today:
                    # Pick the nearest expiry (likely the coming Tuesday)
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
        
def fetch_fut_5m(fut_token, days=2):
    try:
        to_dt = dt.datetime.now()
        from_dt = to_dt - timedelta(days=days)
        data = kite.historical_data(fut_token, from_dt, to_dt, "5minute")
        df = pd.DataFrame(data)
        if "date" in df.columns:
            df.rename(columns={"date": "datetime"}, inplace=True)
        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
        return df
    except Exception as e:
        print("[ERR] fetch_fut_5m:", e)
        return None



# =========================
# 🔁 Scan & Trade (spot EMA/ATR + premium VWAP)
# =========================
def scan_and_maybe_enter_once():
    nowt = dt.datetime.now().time()
    if not within_entry_window(nowt):
        return

    # daily guards
    plr = daily_pl_ratio()
    if plr <= DAILY_MAX_LOSS:
        print("[GUARD] Daily loss limit reached. No more entries.")
        return
    if plr >= DAILY_MAX_PROFIT:
        print("[GUARD] Daily profit cap reached. No more entries.")
        return
    if sum(1 for p in positions.values() if p["status"] == "OPEN") >= MAX_CONCURRENT_POS:
        print("[INFO] Max concurrent positions reached. Skipping new entries.")
        return
    if not global_cooldown_ok():
        print("[INFO] Global cooldown active. Skipping this scan.")
        return

    # --- Spot: fetch & indicators (for EMA/ATR) ---
    try:
        spot_df = fetch_spot_5m(days=2)
        spot_df = add_spot_indicators(spot_df)
    except Exception as e:
        print("[ERR] Spot fetch/indicator error:", e)
        return

    if spot_df is None or len(spot_df) < 15:
        print("[INFO] Not enough spot candles yet.")
        return

    last_spot = spot_df.iloc[-1]
    prev_spot = spot_df.iloc[-2]

    # EMA crossover -> decide CE/PE
    signal_side = None
    if prev_spot["EMA5"] <= prev_spot["EMA20"] and last_spot["EMA5"] > last_spot["EMA20"]:
        signal_side = "CE"
    elif prev_spot["EMA5"] >= prev_spot["EMA20"] and last_spot["EMA5"] < last_spot["EMA20"]:
        signal_side = "PE"

    if not signal_side:
        print("[SCAN] No EMA crossover signal this candle.")
        return

    # ATR filter (spot)
    atr_median = spot_df["ATR"].rolling(20).median().iloc[-1]
    if last_spot["ATR"] < atr_median:
        print("[SKIP] Market too quiet (low ATR), skipping trade.")
        return

    # --- Identify ATM option ---
    try:
        spot_ltp_data = kite.ltp(NIFTY_TOKEN)
        spot_ltp = list(spot_ltp_data.values())[0]["last_price"]
    except Exception as e:
        print("[ERR] Spot LTP failed:", e)
        return

    atm = round_to_50(spot_ltp)
    expiry = get_next_expiry()
    tsym, token = lookup_option(UNDERLYING_NAME, expiry, atm, signal_side)
    if not tsym or not token:
        print(f"[WARN] ATM option not found: {UNDERLYING_NAME} {expiry} {atm} {signal_side}")
        return

    # --- VWAP filter on NIFTY FUT ---
    try:
        NIFTY_FUT_TOKEN, NIFTY_FUT_SYMBOL = get_nifty_weekly_fut_token()
        if NIFTY_FUT_TOKEN is None:
            print("[ERR] Cannot proceed without NIFTY FUT token.")
            return

        fut_df = fetch_fut_5m(NIFTY_FUT_TOKEN, days=2)  # fetch NIFTY FUT data
        if fut_df is None or len(fut_df) < 10:
            print("[WARN] Not enough FUT candles; skipping VWAP validation.")
            return
        fut_df = compute_vwap(fut_df)
        fut_last = fut_df.iloc[-1]
        distance_pct = abs(fut_last["close"] - fut_last["VWAP"]) / fut_last["VWAP"] * 100
        vwap_direction_ok = (signal_side == "CE" and fut_last["close"] > fut_last["VWAP"]) or \
                            (signal_side == "PE" and fut_last["close"] < fut_last["VWAP"])
        print(f"[DEBUG] FUT VWAP distance: {distance_pct:.2f}%, direction OK: {vwap_direction_ok}")

        if distance_pct < MIN_VWAP_DISTANCE_PCT or not vwap_direction_ok:
            print("[SKIP] FUT VWAP filter failed (distance or direction).")
            return
    except Exception as e:
        print("[ERR] FUT VWAP calc failed:", e)
        return

    # Check duplicates / cooldown for that option symbol (tradingsymbol)
    if tsym in entered_symbols_today and (tsym in positions and positions[tsym]["status"] == "OPEN"):
        print(f"[INFO] Already in {tsym}. Skip.")
        return
    if not symbol_cooldown_ok(tsym):
        print(f"[INFO] Symbol cooldown active for {tsym}.")
        return

    # --- Get entry LTP for option ---
    try:
        ltp_info = kite.ltp(f"NFO:{tsym}")
        entry_ltp = list(ltp_info.values())[0]["last_price"]
    except Exception as e:
        print("[ERR] Option LTP failed:", e)
        return

    log_trade(tsym, "BUY", entry_ltp, status="PLANNED", note="signal (spot EMA + FUT VWAP)")
    atr_value = spot_df["ATR"].iloc[-1]

    if PAPER_TRADING:
        print(f"[PAPER-TRADE] Would BUY {tsym} @ {entry_ltp}")
        add_position(tsym, entry_ltp, LOT_QTY, atr=atr_value)
        entered_symbols_today.add(tsym)
        global last_global_entry_time
        last_global_entry_time = dt.datetime.now()
        return

    # Place real market order
    try:
        order_id = kite.place_order(
            variety=kite.VARIETY_REGULAR,
            exchange=kite.EXCHANGE_NFO,
            tradingsymbol=tsym,
            transaction_type=kite.TRANSACTION_TYPE_BUY,
            quantity=LOT_QTY,
            order_type=kite.ORDER_TYPE_MARKET,
            product=kite.PRODUCT_MIS
        )
        add_position(tsym, entry_ltp, LOT_QTY, atr=atr_value)
        log_trade(tsym, "BUY", entry_ltp, status="SUCCESS", note="filled")
        entered_symbols_today.add(tsym)
        last_global_entry_time = dt.datetime.now()
    except Exception as e:
        print(f"[ORDER-FAIL] BUY {tsym}: {e}")
        log_trade(tsym, "BUY", entry_ltp, status="FAILED", note=str(e))
# =========================
# 🧭 Monitor Positions (unchanged logic, cleaned)
# =========================
def monitor_positions_once():
    nowt = dt.datetime.now().time()
    if not positions:
        return

    # Build list of NFO:<tradingsymbol> for LTP call
    tokens = [f"NFO:{sym}" for sym in positions.keys() if positions[sym]["status"] == "OPEN"]
    if not tokens:
        return

    ltp_data = {}
    try:
        ltp_info = kite.ltp(tokens)
        for sym in positions:
            if positions[sym]["status"] != "OPEN":
                continue
            key = f"NFO:{sym}"
            entry = ltp_info.get(key)
            if entry:
                # entry is dict of token->data; take first value
                ltp_data[sym] = list(entry.values())[0]["last_price"]
    except Exception as e:
        print("[ERR] LTP fetch failed:", e)
        return

    for symbol, pos in list(positions.items()):
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
            trigger_price = entry_price * (1 + TRAIL_START_PCT) if is_call else entry_price * (1 - TRAIL_START_PCT)
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
                proposed_sl = ltp * (1 - TRAIL_GIVEBACK_PCT)
                if proposed_sl > pos["sl_price"]:
                    old_sl = pos["sl_price"]
                    pos["sl_price"] = proposed_sl
                    print(f"[TRAIL] SL raised {symbol}: {old_sl:.2f} -> {pos['sl_price']:.2f}")
            elif is_put:
                proposed_sl = ltp * (1 + TRAIL_GIVEBACK_PCT)
                if proposed_sl < pos["sl_price"]:
                    old_sl = pos["sl_price"]
                    pos["sl_price"] = proposed_sl
                    print(f"[TRAIL] SL lowered {symbol}: {old_sl:.2f} -> {pos['sl_price']:.2f}")

        # Check SL/TGT/EOD
        hit_sl = (ltp <= pos["sl_price"] if is_call else ltp >= pos["sl_price"])
        hit_tgt = (ltp >= pos["target_price"] if is_call else ltp <= pos["target_price"])
        time_exit = nowt >= EOD_SQUAREOFF

        if hit_sl or hit_tgt or time_exit:
            reason = "SL" if hit_sl else ("TGT" if hit_tgt else "EOD")
            if PAPER_TRADING:
                exit_position(symbol, ltp, reason)
                continue
            try:
                kite.place_order(
                    variety=kite.VARIETY_REGULAR,
                    exchange=kite.EXCHANGE_NFO,
                    tradingsymbol=symbol,
                    transaction_type=kite.TRANSACTION_TYPE_SELL if is_call else kite.TRANSACTION_TYPE_BUY,
                    quantity=pos["quantity"],
                    order_type=kite.ORDER_TYPE_MARKET,
                    product=kite.PRODUCT_MIS
                )
                exit_position(symbol, ltp, reason=reason)
            except Exception as e:
                print(f"[ORDER-FAIL] Exit {symbol}: {e}")
                log_trade(symbol, "SELL" if is_call else "BUY", pos["entry_price"], ltp, status="FAILED", note=f"{reason}: {e}")

# =========================
# ⏱️ Timing & Main Loop
# =========================
def align_to_next_5m():
    now = dt.datetime.now()
    mins = now.minute
    next_min = (mins // 5 + 1) * 5
    next_tick = now.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=next_min)
    if next_tick <= now:
        next_tick += timedelta(minutes=5)
    sleep_s = (next_tick - now).total_seconds()
    if sleep_s > 0:
        time.sleep(min(120, sleep_s))
        rem = (next_tick - dt.datetime.now()).total_seconds()
        if rem > 0:
            time.sleep(rem)

def main():
    print("=== Intraday Scanner (Spot EMA/ATR + ATM Option Premium VWAP) ===")
    load_instruments(force=True)
    while dt.datetime.now().time() < ENTRY_WINDOW_START:
        print("[WAIT] Market open warm-up. Entries start at 09:30.")
        time.sleep(20)
    try:
        while True:
            now = dt.datetime.now()
            if now.time() >= EOD_SQUAREOFF:
                monitor_positions_once()
                if all(p["status"] != "OPEN" for p in positions.values()):
                    print("[DONE] EOD complete. No open positions. Stopping.")
                    break
                time.sleep(15)
                continue
            monitor_positions_once()
            scan_and_maybe_enter_once()
            align_to_next_5m()
    except KeyboardInterrupt:
        print("[INTERRUPT] Exiting… attempting to close positions")
        for sym, pos in list(positions.items()):
            if pos["status"] == "OPEN":
                try:
                    ltp_info = kite.ltp(f"NFO:{sym}")
                    ltp = list(ltp_info.values())[0]["last_price"]
                    if not PAPER_TRADING:
                        kite.place_order(
                            variety=kite.VARIETY_REGULAR,
                            exchange=kite.EXCHANGE_NFO,
                            tradingsymbol=sym,
                            transaction_type=kite.TRANSACTION_TYPE_SELL,
                            quantity=pos["quantity"],
                            order_type=kite.ORDER_TYPE_MARKET,
                            product=kite.PRODUCT_MIS
                        )
                    exit_position(sym, ltp, reason="INTERRUPT")
                except Exception as e:
                    log_trade(sym, "SELL", pos["entry_price"], status="FAILED", note=f"INTERRUPT: {e}")
        print("[STOPPED]")

if __name__ == "__main__":
    main()
