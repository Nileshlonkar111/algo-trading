from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from kite_service import KiteService, TokenStatus
from trading_engine import TradingEngine
from auth import authenticate_user, create_access_token, require_auth
from websocket_manager import manager as ws_manager, heartbeat_task
from datetime import timedelta
import os
from dotenv import load_dotenv
from typing import List, Optional
import asyncio
import logging
import sys
import datetime as dt
import uuid
import pytz

# Ensure NO websocket_status import
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

# WebSocket broadcast task
broadcast_task_handle = None

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
    
    # Trending market entry strategies (toggleable)
    "enable_crossover_entries": os.getenv("ENABLE_CROSSOVER_ENTRIES", "true").lower() == "true",
    "enable_pullback_entries": os.getenv("ENABLE_PULLBACK_ENTRIES", "true").lower() == "true",
    "enable_vwap_momentum_entries": os.getenv("ENABLE_VWAP_MOMENTUM_ENTRIES", "false").lower() == "true",
    "enable_consecutive_pattern_entries": os.getenv("ENABLE_CONSECUTIVE_PATTERN_ENTRIES", "false").lower() == "true",
    
    # Pullback strategy parameters (EMA20 only)
    "min_trend_separation_pct": float(os.getenv("MIN_TREND_SEPARATION_PCT", "0.2")),
    "pullback_cooldown_minutes": int(os.getenv("PULLBACK_COOLDOWN_MINUTES", "20")),
    
    # VWAP momentum strategy parameters
    "vwap_momentum_distance_pct": float(os.getenv("VWAP_MOMENTUM_DISTANCE_PCT", "0.3")),
    
    # Consecutive pattern strategy parameters
    "consecutive_candles_required": int(os.getenv("CONSECUTIVE_CANDLES_REQUIRED", "3")),
    "consecutive_vwap_distance_pct": float(os.getenv("CONSECUTIVE_VWAP_DISTANCE_PCT", "0.5")),
}

# Modified notification handler to also broadcast via WebSocket
def notification_handler_with_ws(event_type: str, data: dict):
    """Handle notifications, store them, and broadcast via WebSocket"""
    notification = {
        "timestamp": data.get("time", ""),
        "type": event_type,
        "data": data
    }
    notifications.append(notification)
    print(f"[NOTIFICATION] {event_type}: {data}")
    
    # Broadcast via WebSocket
    asyncio.create_task(ws_manager.broadcast({
        "type": "notification",
        "data": notification
    }))

trading_engine = TradingEngine(kite_service.kite, trading_config, notify=notification_handler_with_ws)

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

# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time updates
    Provides: trading status, positions, P&L, logs, notifications
    """
    client_id = str(uuid.uuid4())
    
    try:
        await ws_manager.connect(websocket, client_id)
        logger.info(f"[WS_ENDPOINT] Client {client_id} connected")
        
        # Send initial state immediately after connection
        try:
            auth_status = kite_service.token_status()
            initial_state = {
                "type": "dashboard_update",
                "data": {
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
            }
            await ws_manager.send_personal_message(initial_state, client_id)
        except Exception as e:
            logger.error(f"[WS_ENDPOINT] Failed to send initial state: {e}")
        
        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Receive messages from client (e.g., pong responses)
                data = await websocket.receive_json()
                await ws_manager.handle_client_message(data, client_id)
            except WebSocketDisconnect:
                logger.info(f"[WS_ENDPOINT] Client {client_id} disconnected normally")
                break
            except Exception as e:
                logger.error(f"[WS_ENDPOINT] Error receiving message from {client_id}: {e}")
                break
                
    except Exception as e:
        logger.error(f"[WS_ENDPOINT] Connection error for {client_id}: {e}", exc_info=True)
    finally:
        await ws_manager.disconnect(client_id)


async def broadcast_updates_task():
    """
    Background task to periodically broadcast dashboard updates to all WebSocket clients
    Replaces the polling mechanism with server-push updates
    """
    logger.info("[WS_BROADCAST] Broadcast task started")
    
    while True:
        try:
            # Only broadcast if there are connected clients
            if ws_manager.get_connection_count() > 0:
                auth_status = kite_service.token_status()
                
                # Get positions with current LTP data
                positions = trading_engine.get_positions()
                
                # Fetch LTPs for open positions to show real-time PNL
                position_ltps = {}
                open_positions = {sym: pos for sym, pos in positions.items() if pos["status"] == "OPEN"}
                
                if open_positions:
                    try:
                        tokens = [f"NFO:{sym}" for sym in open_positions.keys()]
                        ltp_info = trading_engine.kite.ltp(tokens)
                        
                        for sym in open_positions.keys():
                            key = f"NFO:{sym}"
                            entry = ltp_info.get(key)
                            if entry:
                                if isinstance(entry, dict):
                                    if "last_price" in entry:
                                        position_ltps[sym] = entry["last_price"]
                                    else:
                                        position_ltps[sym] = list(entry.values())[0]["last_price"]
                    except Exception as e:
                        logger.debug(f"[WS_BROADCAST] Could not fetch position LTPs: {e}")
                
                # Add LTP data to positions
                positions_with_ltp = {}
                for sym, pos in positions.items():
                    pos_copy = pos.copy()
                    if sym in position_ltps:
                        pos_copy["current_ltp"] = position_ltps[sym]
                        # Calculate unrealized PNL
                        if pos["status"] == "OPEN":
                            pos_copy["unrealized_pnl"] = (position_ltps[sym] - pos["entry_price"]) * pos["quantity"]
                            pos_copy["unrealized_pnl_pct"] = ((position_ltps[sym] - pos["entry_price"]) / pos["entry_price"] * 100) if pos["entry_price"] > 0 else 0
                    positions_with_ltp[sym] = pos_copy
                
                dashboard_data = {
                    "type": "dashboard_update",
                    "data": {
                        "trading": {
                            "active": trading_active,
                            "authenticated": auth_status.value == "authenticated",
                            "token_status": auth_status.value,
                            "open_positions": len(open_positions)
                        },
                        "pnl": {
                            "realized_pnl": trading_engine.get_pnl(),
                            "daily_pl_ratio": trading_engine.daily_pl_ratio()
                        },
                        "positions": positions_with_ltp,
                        "logs": trading_engine.get_trade_logs()[-20:] if len(trading_engine.get_trade_logs()) > 0 else [],
                        "notifications": notifications[-20:] if len(notifications) > 0 else []
                    }
                }
                
                # Broadcast will automatically filter duplicates to prevent flickering
                sent_count = await ws_manager.broadcast(dashboard_data)
                
                if sent_count > 0:
                    logger.debug(f"[WS_BROADCAST] Dashboard update sent to {sent_count} clients")
            
            # Broadcast every 2 seconds (more frequent than polling, but filtered for changes)
            await asyncio.sleep(2)
            
        except Exception as e:
            logger.error(f"[WS_BROADCAST_ERROR] {e}", exc_info=True)
            await asyncio.sleep(5)


# Auto-trading scheduler
scheduler_task_handle = None
IST = pytz.timezone('Asia/Kolkata')

async def auto_trading_scheduler():
    """
    Intelligent scheduler that:
    1. Automatically starts trading at market open (09:15 AM IST)
    2. Automatically stops trading at market close (15:30 PM IST)
    3. Resumes trading if server restarts during market hours
    4. Waits until next market open if server starts outside market hours
    """
    global trading_active
    logger.info("[SCHEDULER] Auto-trading scheduler started")
    
    while True:
        try:
            now_ist = dt.datetime.now(IST)
            current_time = now_ist.time()
            current_date = now_ist.date()
            
            # Market hours: 9:15 AM - 3:30 PM IST
            market_open = dt.time(9, 15)
            market_close = dt.time(15, 30)
            
            # Check if it's a weekday (Monday=0 to Friday=4)
            is_weekday = now_ist.weekday() < 5
            
            # Check if we're in market hours
            in_market_hours = market_open <= current_time <= market_close and is_weekday
            
            # AUTO-START: Start trading if in market hours and not active
            if in_market_hours and not trading_active:
                try:
                    # Verify Kite authentication
                    kite_service.ensure_authenticated()
                    
                    logger.info(f"[SCHEDULER] 🚀 AUTO-START: Market is open, starting trading at {current_time.strftime('%H:%M:%S')}")
                    trading_active = True
                    save_trading_active(trading_active)
                    asyncio.create_task(trading_loop())
                    
                except Exception as e:
                    logger.error(f"[SCHEDULER] Cannot auto-start trading - Kite auth failed: {e}")
                    logger.info("[SCHEDULER] Will retry authentication in 5 minutes")
                    await asyncio.sleep(300)  # Retry in 5 minutes
                    continue
            
            # AUTO-STOP: Stop trading if market closed and still active
            elif not in_market_hours and trading_active:
                logger.info(f"[SCHEDULER] 🛑 AUTO-STOP: Market closed, stopping trading at {current_time.strftime('%H:%M:%S')}")
                trading_active = False
                save_trading_active(trading_active)
            
            # WAIT FOR MARKET OPEN: Calculate time until next market open
            if not in_market_hours:
                if current_time > market_close:
                    # Market closed for today, wait until tomorrow
                    next_open = dt.datetime.combine(
                        current_date + dt.timedelta(days=1),
                        market_open
                    )
                    # Skip weekends
                    while next_open.weekday() >= 5:  # Saturday=5, Sunday=6
                        next_open += dt.timedelta(days=1)
                else:
                    # Before market open today
                    next_open = dt.datetime.combine(current_date, market_open)
                    # If today is weekend, move to Monday
                    while next_open.weekday() >= 5:
                        next_open += dt.timedelta(days=1)
                
                next_open_ist = IST.localize(next_open)
                wait_seconds = (next_open_ist - now_ist).total_seconds()
                wait_hours = wait_seconds / 3600
                
                logger.info(f"[SCHEDULER] 💤 Market closed. Next market open: {next_open_ist.strftime('%Y-%m-%d %H:%M:%S')} ({wait_hours:.1f} hours)")
                
                # Check every 5 minutes while waiting for market open
                await asyncio.sleep(min(300, max(60, wait_seconds - 60)))
            else:
                # During market hours, check every 60 seconds
                await asyncio.sleep(60)
                
        except Exception as e:
            logger.error(f"[SCHEDULER] Error in auto-trading scheduler: {e}", exc_info=True)
            await asyncio.sleep(60)


@app.on_event("startup")
async def startup_event():
    """Start background tasks on application startup"""
    global broadcast_task_handle, scheduler_task_handle
    
    logger.info("[STARTUP] Starting background tasks")
    
    # Start heartbeat task for WebSocket connection health
    asyncio.create_task(heartbeat_task())
    
    # Start broadcast task for real-time updates
    broadcast_task_handle = asyncio.create_task(broadcast_updates_task())
    
    # Start auto-trading scheduler
    scheduler_task_handle = asyncio.create_task(auto_trading_scheduler())
    
    logger.info("[STARTUP] Background tasks started successfully (including auto-trading scheduler)")


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
                # Returns LTP data for all open positions
                position_ltps = trading_engine.monitor_positions_once()
                
                # Check if we're at a 5-minute candle close boundary
                current_time = dt.datetime.now()
                current_minute = current_time.minute
                current_second = current_time.second
                
                # Scan at 5-minute intervals with 3-second delay to allow API to process completed candle
                # Duplicate detection prevents repeat signals if same candle appears in multiple scans
                if (current_minute % 5 == 0) and (current_second >= 3) and (current_minute != last_scan_minute):
                    logger.info(f"[TRADING_LOOP] 5-minute candle close detected at {current_time.strftime('%H:%M:%S')}, initiating scan...")
                    trading_engine.scan_and_maybe_enter_once()
                    last_scan_minute = current_minute
                
                # Check if it's time to send end-of-day summary (after 3:30 PM)
                trading_engine.check_and_send_eod_summary()
                
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

# No WebSocket router; pure API polling logic restored

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")))