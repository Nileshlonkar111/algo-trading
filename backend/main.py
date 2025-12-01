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

load_dotenv()

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
trading_active = False

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
    if not kite_service.is_authenticated():
        raise HTTPException(status_code=401, detail="Kite not authenticated")
    if trading_active:
        raise HTTPException(status_code=400, detail="Trading already active")
    
    trading_active = True
    background_tasks.add_task(trading_loop)
    return {"status": "started"}

@app.post("/trading/stop", dependencies=[Depends(require_auth)])
def stop_trading():
    global trading_active
    trading_active = False
    return {"status": "stopped"}

@app.get("/trading/status", dependencies=[Depends(require_auth)])
def trading_status():
    return {
        "active": trading_active,
        "authenticated": kite_service.is_authenticated(),
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
    print("[INFO] Trading loop started")
    try:
        while trading_active:
            try:
                trading_engine.monitor_positions_once()
                trading_engine.scan_and_maybe_enter_once()
                await asyncio.sleep(60)  # Run every minute
            except Exception as e:
                print(f"[ERROR] Trading loop error: {e}")
                notification_handler("error", {"error": str(e), "type": "trading_loop"})
                await asyncio.sleep(60)
    finally:
        print("[INFO] Trading loop stopped")

# Health check
@app.get("/health")
def health_check():
    return {"status": "healthy", "version": "1.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")))