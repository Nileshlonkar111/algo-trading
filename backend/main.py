from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from kite_service import KiteService, TokenStatus
from trading_engine import TradingEngine
from auth import authenticate_user, create_access_token, require_auth
from datetime import timedelta
import os
from dotenv import load_dotenv
from typing import List, Optional
import asyncio
import logging
import sys
import datetime as dt

load_dotenv()

# Configure logging at application level
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)
logger.info("[STARTUP] Application logging configured")

app = FastAPI(title="Algo Trading Platform", version="1.0.0")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances
kite_service = KiteService()
notifications: List[dict] = []

def notification_handler(event_type: str, data: dict):
    """Handle notifications and store them"""
    notification = {
        "timestamp": data.get("time", ""),
        "type": event_type,
        "data": data
    }
    notifications.append(notification)
    print(f"[NOTIFICATION] {event_type}: {data}")

# Trading configuration from environment
trading_config = {
    "nifty_token": int(os.getenv("NIFTY_TOKEN", "256265")),
    "underlying_name": os.getenv("UNDERLYING_NAME", "NIFTY"),
    "lot_qty": int(os.getenv("LOT_QTY", "75")),
    "max_concurrent_pos": int(os.getenv("MAX_CONCURRENT_POS", "3")),
    "min_minutes_between_entries": int(os.getenv("MIN_MINUTES_BETWEEN_ENTRIES", "10")),
    "per_symbol_cooldown_min": int(os.getenv("PER_SYMBOL_COOLDOWN_MIN", "20")),
    "daily_max_loss": float(os.getenv("DAILY_MAX_LOSS", "-0.02")),
    "daily_max_profit": float(os.getenv("DAILY_MAX_PROFIT", "0.04")),
    "capital_base": float(os.getenv("CAPITAL_BASE", "300000")),
    "atr_period": int(os.getenv("ATR_PERIOD", "14")),
    "trail_start_pct": float(os.getenv("TRAIL_START_PCT", "0.15")),
    "trail_giveback_pct": float(os.getenv("TRAIL_GIVEBACK_PCT", "0.10")),
    "min_vwap_distance_pct": float(os.getenv("MIN_VWAP_DISTANCE_PCT", "0.15")),
}

trading_engine = TradingEngine(kite_service.kite, trading_config, notify=notification_handler)

TRADING_STATE_FILE = "trading_state.json"

def load_trading_active():
    try:
        import json
        with open(TRADING_STATE_FILE, "r") as f:
            state = json.load(f)
            return state.get("active", False)
    except Exception:
        return False

def save_trading_active(active):
    try:
        import json
        with open(TRADING_STATE_FILE, "w") as f:
            json.dump({"active": active}, f)
    except Exception:
        pass

trading_active = load_trading_active()

# Pydantic models
class LoginRequest(BaseModel):
    username: str
    password: str

class TokenRequest(BaseModel):
    request_token: str

class TradingConfigRequest(BaseModel):
    capital_base: Optional[float] = None
    max_concurrent_pos: Optional[int] = None
    daily_max_loss: Optional[float] = None
    daily_max_profit: Optional[float] = None
    lot_qty: Optional[int] = None
    min_minutes_between_entries: Optional[int] = None
    per_symbol_cooldown_min: Optional[int] = None

# Authentication endpoints
@app.post("/auth/login")
def login(request: LoginRequest):
    user = authenticate_user(request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    access_token_expires = timedelta(minutes=480)
    access_token = create_access_token(
        data={"sub": user["username"]}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

# Kite authentication endpoints
@app.get("/kite/login_url", dependencies=[Depends(require_auth)])
def get_login_url():
    return {"login_url": kite_service.get_login_url()}

@app.post("/kite/generate_token", dependencies=[Depends(require_auth)])
def generate_token(req: TokenRequest):
    try:
        status = kite_service.generate_access_token(req.request_token)
        trading_engine.kite = kite_service.kite  # Update engine with authenticated kite instance
        return {"status": status.value}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/kite/token_status", dependencies=[Depends(require_auth)])
def token_status():
    return {"status": kite_service.token_status().value}

@app.get("/kite/account", dependencies=[Depends(require_auth)])
def get_account():
    if not kite_service.is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        return kite_service.get_account_info()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Trading engine endpoints
@app.get("/trades/logs", dependencies=[Depends(require_auth)])
def get_trade_logs():
    return {"logs": trading_engine.get_trade_logs()}

@app.get("/trades/positions", dependencies=[Depends(require_auth)])
def get_positions():
    return {"positions": trading_engine.get_positions()}

@app.get("/trades/pnl", dependencies=[Depends(require_auth)])
def get_pnl():
    return {"realized_pnl": trading_engine.get_pnl(), "daily_pl_ratio": trading_engine.daily_pl_ratio()}

@app.get("/trades/config", dependencies=[Depends(require_auth)])
def get_trading_config():
    return {"config": trading_engine.config}

@app.post("/trades/config", dependencies=[Depends(require_auth)])
def update_trading_config(cfg: TradingConfigRequest):
    updates = {k: v for k, v in cfg.dict().items() if v is not None}
    trading_engine.update_config(updates)
    return {"status": "updated", "config": trading_engine.config}

@app.get("/notifications", dependencies=[Depends(require_auth)])
def get_notifications(limit: int = 50):
    return {"notifications": notifications[-limit:]}

@app.delete("/notifications", dependencies=[Depends(require_auth)])
def clear_notifications():
    notifications.clear()
    return {"status": "cleared"}

# Trading control endpoints
@app.post("/trading/start", dependencies=[Depends(require_auth)])
async def start_trading(background_tasks: BackgroundTasks):
    global trading_active
    
    # Validate Kite authentication before starting
    try:
        kite_service.ensure_authenticated()
    except Exception as e:
        logger.error(f"[TRADING] Cannot start - Kite auth failed: {e}")
        raise HTTPException(status_code=401, detail=str(e))
    
    if trading_active:
        raise HTTPException(status_code=400, detail="Trading already active")
    

@app.get("/dashboard/status", dependencies=[Depends(require_auth)])
def get_dashboard_status():
    """Aggregated endpoint that returns all dashboard data in a single call"""
    auth_status = kite_service.token_status()
    
    return {
        "trading": {
            "active": trading_active,
            "authenticated": auth_status.value == "authenticated",
            "token_status": auth_status.value,
            "open_positions": sum(1 for p in trading_engine.positions.values() if p["status"] == "OPEN")
        },
        "pnl": {
            "realized_pnl": trading_engine.get_pnl(),
            "daily_pl_ratio": trading_engine.daily_pl_ratio()
        },
        "positions": trading_engine.get_positions(),
        "logs": trading_engine.get_trade_logs()[-20:] if len(trading_engine.get_trade_logs()) > 0 else [],
        "notifications": notifications[-20:] if len(notifications) > 0 else []
    }
    trading_active = True
    save_trading_active(trading_active)
    background_tasks.add_task(trading_loop)
    logger.info("[TRADING] Trading started successfully")
    return {"status": "started"}

@app.post("/trading/stop", dependencies=[Depends(require_auth)])
def stop_trading():
    global trading_active
    trading_active = False
    save_trading_active(trading_active)
    logger.info("[TRADING] Trading stopped by user")
    return {"status": "stopped"}

@app.get("/trading/status", dependencies=[Depends(require_auth)])
def trading_status():
    global trading_active
    # Get current auth status with validation
    auth_status = kite_service.token_status()
    
    # Log the actual status being returned for debugging
    logger.debug(f"[TRADING_STATUS] active={trading_active}, auth={auth_status.value}")
    
    return {
        "active": trading_active,
        "authenticated": auth_status.value == "authenticated",
        "token_status": auth_status.value,
        "open_positions": sum(1 for p in trading_engine.positions.values() if p["status"] == "OPEN")
    }

@app.post("/trading/close_all", dependencies=[Depends(require_auth)])
def close_all_positions():
    try:
        trading_engine.close_all_positions()
        return {"status": "success", "message": "All positions closed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Trading loop background task
async def trading_loop():
    global trading_active
    logger.info("[TRADING_LOOP] Trading loop started")
    print("[INFO] Trading loop started")
    
    # Track last scan time to avoid duplicate scans in same 5-min window
    last_scan_minute = -1
    
    try:
        while trading_active:
            try:
                # CRITICAL: Monitor positions every 3 seconds for fast reaction
                trading_engine.monitor_positions_once()
                
                # Check if we're at a 5-minute candle close boundary
                current_time = dt.datetime.now()
                current_minute = current_time.minute
                
                # Scan only at 5-minute intervals: X:00, X:05, X:10, X:15, X:20, X:25, X:30, X:35, X:40, X:45, X:50, X:55
                # AND only if we haven't already scanned in this 5-minute window
                if (current_minute % 5 == 0) and (current_minute != last_scan_minute):
                    logger.info(f"[TRADING_LOOP] 5-minute candle close detected at {current_time.strftime('%H:%M:%S')}, initiating scan...")
                    trading_engine.scan_and_maybe_enter_once()
                    last_scan_minute = current_minute
                
                # Fast monitoring loop - check positions every 3 seconds
                await asyncio.sleep(3)
                
            except Exception as e:
                logger.error(f"[TRADING_LOOP] Error: {e}", exc_info=True)
                print(f"[ERROR] Trading loop error: {e}")
                notification_handler("error", {"error": str(e), "type": "trading_loop"})
                await asyncio.sleep(3)  # Quick retry on error
    finally:
        logger.info("[TRADING_LOOP] Trading loop stopped")
        print("[INFO] Trading loop stopped")

# Health check
@app.get("/health")
def health_check():
    return {"status": "healthy", "version": "1.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")))