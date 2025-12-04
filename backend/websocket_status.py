from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List
import asyncio
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"[WEBSOCKET] Client connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"[WEBSOCKET] Client disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: str):
        """Broadcast message to all connected clients"""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"[WEBSOCKET] Error sending to client: {e}")
                disconnected.append(connection)
        
        # Clean up disconnected clients
        for connection in disconnected:
            self.disconnect(connection)

manager = ConnectionManager()

# Store reference to dashboard status function (set from main.py)
_dashboard_status_fn = None

def set_dashboard_status_fn(fn):
    """Set the dashboard status function to avoid circular import"""
    global _dashboard_status_fn
    _dashboard_status_fn = fn
    logger.info("[WEBSOCKET] Dashboard status function registered")

@router.websocket("/ws/status")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    
    async def send_status():
        while True:
            try:
                if _dashboard_status_fn is None:
                    logger.warning("[WEBSOCKET] Dashboard status function not set")
                    await asyncio.sleep(2)
                    continue
                
                # Get dashboard status and broadcast to all clients
                status_data = _dashboard_status_fn()
                
                # Convert response model to JSON string
                if hasattr(status_data, 'model_dump_json'):
                    message = status_data.model_dump_json()
                elif hasattr(status_data, 'json'):
                    message = status_data.json()
                elif isinstance(status_data, dict):
                    message = json.dumps(status_data)
                else:
                    message = json.dumps({"error": "Invalid data format"})
                
                await manager.broadcast(message)
                await asyncio.sleep(2)  # Update every 2 seconds
            except Exception as e:
                logger.error(f"[WEBSOCKET] Error in send_status: {e}", exc_info=True)
                await asyncio.sleep(2)
    
    status_task = asyncio.create_task(send_status())
    
    try:
        # Keep connection alive and handle incoming messages
        while True:
            data = await websocket.receive_text()
            logger.debug(f"[WEBSOCKET] Received message: {data}")
    except WebSocketDisconnect:
        logger.info("[WEBSOCKET] Client disconnected normally")
    except Exception as e:
        logger.error(f"[WEBSOCKET] Error in websocket connection: {e}")
    finally:
        manager.disconnect(websocket)
        status_task.cancel()
        try:
            await status_task
        except asyncio.CancelledError:
            pass