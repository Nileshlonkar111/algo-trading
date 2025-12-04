from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

import asyncio
from main import get_dashboard_status

@router.websocket("/ws/status")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    async def send_status():
        while True:
            try:
                # Get dashboard status and broadcast to all clients
                status_data = get_dashboard_status()
                await manager.broadcast(status_data.json())
                await asyncio.sleep(2)
            except Exception:
                break
    status_task = asyncio.create_task(send_status())
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        status_task.cancel()