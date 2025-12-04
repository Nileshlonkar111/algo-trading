"""
WebSocket Manager for Real-time Trading Updates
Handles WebSocket connections, broadcasting, and connection lifecycle management
"""

from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, Set, Optional, Any
import asyncio
import json
import logging
from datetime import datetime
import time

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections with:
    - Connection pooling and tracking
    - Heartbeat/ping-pong for connection health
    - Automatic cleanup of stale connections
    - Message broadcasting with error handling
    - State reconciliation to prevent flickering
    """
    
    def __init__(self):
        # Active connections indexed by connection ID
        self.active_connections: Dict[str, WebSocket] = {}
        
        # Track last message sent to each connection for deduplication
        self.last_messages: Dict[str, Dict[str, Any]] = {}
        
        # Connection health tracking
        self.last_pong: Dict[str, float] = {}
        
        # Heartbeat configuration
        self.heartbeat_interval = 30  # seconds
        self.heartbeat_timeout = 60  # seconds
        
        # State cache to prevent unnecessary updates
        self.state_cache: Dict[str, Any] = {}
        
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()
        
        logger.info("[WS_MANAGER] ConnectionManager initialized")
    
    async def connect(self, websocket: WebSocket, client_id: str) -> None:
        """
        Accept and register a new WebSocket connection
        
        Args:
            websocket: The WebSocket connection
            client_id: Unique identifier for the client
        """
        await websocket.accept()
        
        async with self._lock:
            self.active_connections[client_id] = websocket
            self.last_pong[client_id] = time.time()
            self.last_messages[client_id] = {}
            
        logger.info(f"[WS_CONNECT] Client {client_id} connected. Total connections: {len(self.active_connections)}")
        
        # Send initial connection confirmation
        await self.send_personal_message({
            "type": "connection_established",
            "client_id": client_id,
            "timestamp": datetime.now().isoformat()
        }, client_id)
    
    async def disconnect(self, client_id: str) -> None:
        """
        Remove a client connection and cleanup resources
        
        Args:
            client_id: Unique identifier for the client
        """
        async with self._lock:
            if client_id in self.active_connections:
                del self.active_connections[client_id]
            if client_id in self.last_pong:
                del self.last_pong[client_id]
            if client_id in self.last_messages:
                del self.last_messages[client_id]
        
        logger.info(f"[WS_DISCONNECT] Client {client_id} disconnected. Remaining connections: {len(self.active_connections)}")
    
    async def send_personal_message(self, message: dict, client_id: str) -> bool:
        """
        Send message to a specific client with error handling
        
        Args:
            message: The message dictionary to send
            client_id: Target client identifier
            
        Returns:
            bool: True if sent successfully, False otherwise
        """
        websocket = self.active_connections.get(client_id)
        if not websocket:
            logger.warning(f"[WS_SEND] Client {client_id} not found")
            return False
        
        try:
            # Add timestamp if not present
            if "timestamp" not in message:
                message["timestamp"] = datetime.now().isoformat()
            
            await websocket.send_json(message)
            logger.debug(f"[WS_SEND] Message sent to {client_id}: {message.get('type', 'unknown')}")
            return True
            
        except Exception as e:
            logger.error(f"[WS_SEND_ERROR] Failed to send to {client_id}: {e}")
            # Schedule disconnection for broken connection
            asyncio.create_task(self.disconnect(client_id))
            return False
    
    def _should_send_update(self, message: dict, client_id: str) -> bool:
        """
        Determine if update should be sent based on state changes
        Prevents flickering by filtering duplicate or unchanged states
        
        Args:
            message: The message to potentially send
            client_id: Target client identifier
            
        Returns:
            bool: True if message should be sent
        """
        message_type = message.get("type")
        
        # Always send certain message types
        priority_types = {"connection_established", "error", "heartbeat", "pong"}
        if message_type in priority_types:
            return True
        
        # For status updates, check if state actually changed
        if message_type == "trading_status" or message_type == "dashboard_update":
            last_msg = self.last_messages.get(client_id, {}).get(message_type)
            
            if not last_msg:
                # First message of this type
                return True
            
            # Compare critical fields for status updates
            if message_type == "trading_status":
                critical_fields = ["active", "token_status", "open_positions"]
                for field in critical_fields:
                    if message.get("data", {}).get(field) != last_msg.get("data", {}).get(field):
                        return True
                
                # No critical fields changed
                logger.debug(f"[WS_FILTER] Filtered duplicate trading_status for {client_id}")
                return False
            
            elif message_type == "dashboard_update":
                # Check if any section changed
                sections = ["trading", "pnl", "positions", "logs", "notifications"]
                for section in sections:
                    if json.dumps(message.get("data", {}).get(section), sort_keys=True) != \
                       json.dumps(last_msg.get("data", {}).get(section), sort_keys=True):
                        return True
                
                logger.debug(f"[WS_FILTER] Filtered duplicate dashboard_update for {client_id}")
                return False
        
        return True
    
    async def broadcast(self, message: dict, exclude: Optional[Set[str]] = None) -> int:
        """
        Broadcast message to all connected clients with deduplication
        
        Args:
            message: The message dictionary to broadcast
            exclude: Set of client IDs to exclude from broadcast
            
        Returns:
            int: Number of clients that received the message
        """
        if exclude is None:
            exclude = set()
        
        sent_count = 0
        disconnected_clients = []
        
        # Get snapshot of connections to avoid modification during iteration
        async with self._lock:
            clients = list(self.active_connections.keys())
        
        for client_id in clients:
            if client_id in exclude:
                continue
            
            # Check if update should be sent (deduplication/filtering)
            if not self._should_send_update(message, client_id):
                continue
            
            success = await self.send_personal_message(message, client_id)
            
            if success:
                sent_count += 1
                # Cache this message for deduplication
                self.last_messages[client_id][message.get("type", "unknown")] = message
            else:
                disconnected_clients.append(client_id)
        
        # Cleanup disconnected clients
        for client_id in disconnected_clients:
            await self.disconnect(client_id)
        
        if sent_count > 0:
            logger.debug(f"[WS_BROADCAST] Sent '{message.get('type')}' to {sent_count} clients")
        
        return sent_count
    
    async def handle_client_message(self, message: dict, client_id: str) -> None:
        """
        Handle incoming messages from clients (e.g., pong responses)
        
        Args:
            message: The received message
            client_id: Client identifier
        """
        msg_type = message.get("type")
        
        if msg_type == "pong":
            # Update last pong time for heartbeat tracking
            self.last_pong[client_id] = time.time()
            logger.debug(f"[WS_PONG] Received pong from {client_id}")
            
        elif msg_type == "ping":
            # Client requested a ping, respond with pong
            await self.send_personal_message({"type": "pong"}, client_id)
            
        else:
            logger.debug(f"[WS_MESSAGE] Received {msg_type} from {client_id}")
    
    async def send_heartbeat(self, client_id: str) -> bool:
        """
        Send heartbeat ping to a specific client
        
        Args:
            client_id: Client identifier
            
        Returns:
            bool: True if heartbeat sent successfully
        """
        return await self.send_personal_message({
            "type": "ping",
            "timestamp": datetime.now().isoformat()
        }, client_id)
    
    async def check_connection_health(self) -> None:
        """
        Check health of all connections and remove stale ones
        Should be called periodically
        """
        current_time = time.time()
        stale_clients = []
        
        async with self._lock:
            for client_id, last_pong_time in self.last_pong.items():
                if current_time - last_pong_time > self.heartbeat_timeout:
                    stale_clients.append(client_id)
                    logger.warning(f"[WS_HEALTH] Client {client_id} connection stale (no pong for {current_time - last_pong_time:.1f}s)")
        
        # Disconnect stale clients
        for client_id in stale_clients:
            await self.disconnect(client_id)
    
    def get_connection_count(self) -> int:
        """Get the number of active connections"""
        return len(self.active_connections)
    
    def is_connected(self, client_id: str) -> bool:
        """Check if a specific client is connected"""
        return client_id in self.active_connections


# Global connection manager instance
manager = ConnectionManager()


async def heartbeat_task():
    """
    Background task to send periodic heartbeats and check connection health
    """
    logger.info("[WS_HEARTBEAT] Heartbeat task started")
    
    while True:
        try:
            await asyncio.sleep(manager.heartbeat_interval)
            
            # Check connection health
            await manager.check_connection_health()
            
            # Send heartbeat to all connections
            if manager.get_connection_count() > 0:
                await manager.broadcast({"type": "ping"})
                logger.debug(f"[WS_HEARTBEAT] Sent heartbeat to {manager.get_connection_count()} clients")
                
        except Exception as e:
            logger.error(f"[WS_HEARTBEAT_ERROR] {e}", exc_info=True)
            await asyncio.sleep(5)  # Wait before retrying