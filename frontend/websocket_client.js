/**
 * WebSocket Client Manager
 * 
 * Provides:
 * - Automatic reconnection with exponential backoff
 * - Connection state management
 * - Message queue for offline scenarios
 * - Heartbeat/ping-pong for connection health
 * - State reconciliation to prevent flickering
 * - Debouncing for rapid state changes
 */

class WebSocketClient {
    constructor(url, options = {}) {
        this.url = url;
        this.ws = null;
        
        // Connection state
        this.connectionState = 'disconnected'; // disconnected, connecting, connected, reconnecting
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = options.maxReconnectAttempts || Infinity;
        this.reconnectDelay = options.reconnectDelay || 1000; // Initial delay in ms
        this.maxReconnectDelay = options.maxReconnectDelay || 30000; // Max delay: 30s
        this.reconnectBackoffMultiplier = options.reconnectBackoffMultiplier || 1.5;
        
        // Heartbeat configuration
        this.heartbeatInterval = options.heartbeatInterval || 30000; // 30s
        this.heartbeatTimeout = options.heartbeatTimeout || 60000; // 60s
        this.lastHeartbeat = Date.now();
        this.heartbeatTimer = null;
        this.heartbeatCheckTimer = null;
        
        // Message queue for offline scenarios
        this.messageQueue = [];
        this.maxQueueSize = options.maxQueueSize || 100;
        
        // Event handlers
        this.eventHandlers = {
            open: [],
            close: [],
            error: [],
            message: [],
            stateChange: []
        };
        
        // State management for deduplication and debouncing
        this.lastState = {};
        this.pendingStateUpdate = null;
        this.stateUpdateDebounceTime = options.stateUpdateDebounceTime || 100; // ms
        
        // Statistics
        this.stats = {
            messagesReceived: 0,
            messagesSent: 0,
            reconnectCount: 0,
            lastConnectedTime: null,
            totalUptime: 0
        };
        
        console.log('[WS_CLIENT] WebSocket client initialized', { url: this.url });
    }
    
    /**
     * Connect to WebSocket server
     */
    connect() {
        if (this.connectionState === 'connected' || this.connectionState === 'connecting') {
            console.log('[WS_CLIENT] Already connected or connecting');
            return;
        }
        
        this.setConnectionState('connecting');
        
        try {
            // Determine WebSocket URL
            let wsUrl = this.url;
            if (!wsUrl.startsWith('ws://') && !wsUrl.startsWith('wss://')) {
                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                const host = window.location.hostname;
                const port = window.location.port;
                
                // For local development
                if (host === 'localhost' || host === '127.0.0.1') {
                    wsUrl = `ws://localhost:8000/ws`;
                } else {
                    // Production: Use relative path which will work with nginx proxy
                    // The browser will automatically use the correct protocol and host
                    const baseUrl = `${protocol}//${host}${port ? ':' + port : ''}`;
                    wsUrl = `${baseUrl}/api/ws`;
                    console.log('[WS_CLIENT] Production WebSocket URL:', wsUrl);
                }
            }
            
            console.log('[WS_CLIENT] Connecting to:', wsUrl);
            this.ws = new WebSocket(wsUrl);
            
            // Set up event handlers
            this.ws.onopen = this.handleOpen.bind(this);
            this.ws.onclose = this.handleClose.bind(this);
            this.ws.onerror = this.handleError.bind(this);
            this.ws.onmessage = this.handleMessage.bind(this);
            
        } catch (error) {
            console.error('[WS_CLIENT] Connection error:', error);
            this.setConnectionState('disconnected');
            this.scheduleReconnect();
        }
    }
    
    /**
     * Disconnect from WebSocket server
     */
    disconnect() {
        console.log('[WS_CLIENT] Disconnecting...');
        this.clearHeartbeat();
        
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        
        this.setConnectionState('disconnected');
    }
    
    /**
     * Handle WebSocket open event
     */
    handleOpen(event) {
        console.log('[WS_CLIENT] ✅ Connected successfully');
        this.setConnectionState('connected');
        this.reconnectAttempts = 0;
        this.stats.lastConnectedTime = Date.now();
        this.stats.reconnectCount++;
        
        // Start heartbeat
        this.startHeartbeat();
        
        // Process queued messages
        this.processMessageQueue();
        
        // Trigger open event handlers
        this.emit('open', event);
    }
    
    /**
     * Handle WebSocket close event
     */
    handleClose(event) {
        console.log('[WS_CLIENT] Connection closed', { code: event.code, reason: event.reason });
        
        this.clearHeartbeat();
        
        // Update uptime stats
        if (this.stats.lastConnectedTime) {
            this.stats.totalUptime += Date.now() - this.stats.lastConnectedTime;
        }
        
        const previousState = this.connectionState;
        this.setConnectionState('disconnected');
        
        // Trigger close event handlers
        this.emit('close', event);
        
        // Attempt reconnection if not manually disconnected
        if (previousState !== 'disconnected') {
            this.scheduleReconnect();
        }
    }
    
    /**
     * Handle WebSocket error event
     */
    handleError(event) {
        console.error('[WS_CLIENT] ❌ WebSocket error:', event);
        this.emit('error', event);
    }
    
    /**
     * Handle incoming WebSocket message
     */
    handleMessage(event) {
        this.stats.messagesReceived++;
        
        try {
            const message = JSON.parse(event.data);
            const messageType = message.type;
            
            // Handle heartbeat messages
            if (messageType === 'ping') {
                this.lastHeartbeat = Date.now();
                this.send({ type: 'pong', timestamp: new Date().toISOString() });
                return;
            }
            
            if (messageType === 'pong') {
                this.lastHeartbeat = Date.now();
                return;
            }
            
            // Log received message (debug)
            console.log('[WS_CLIENT] 📨 Message received:', messageType);
            
            // Handle state updates with debouncing
            if (messageType === 'dashboard_update' || messageType === 'trading_status') {
                this.handleStateUpdate(message);
            } else {
                // Immediate processing for other message types
                this.emit('message', message);
            }
            
        } catch (error) {
            console.error('[WS_CLIENT] Failed to parse message:', error, event.data);
        }
    }
    
    /**
     * Handle state updates with debouncing and deduplication
     */
    handleStateUpdate(message) {
        // Check if state actually changed (prevent flickering)
        const messageType = message.type;
        const currentData = JSON.stringify(message.data);
        const lastData = this.lastState[messageType];
        
        if (lastData === currentData) {
            console.log('[WS_CLIENT] ⏭️ Skipping duplicate state update:', messageType);
            return;
        }
        
        // Cancel pending update if exists
        if (this.pendingStateUpdate) {
            clearTimeout(this.pendingStateUpdate);
        }
        
        // Debounce state updates to prevent rapid flickering
        this.pendingStateUpdate = setTimeout(() => {
            this.lastState[messageType] = currentData;
            this.emit('message', message);
            this.pendingStateUpdate = null;
        }, this.stateUpdateDebounceTime);
    }
    
    /**
     * Send message to server
     */
    send(data) {
        if (this.connectionState !== 'connected') {
            console.warn('[WS_CLIENT] Not connected, queueing message');
            this.queueMessage(data);
            return false;
        }
        
        try {
            const message = typeof data === 'string' ? data : JSON.stringify(data);
            this.ws.send(message);
            this.stats.messagesSent++;
            return true;
        } catch (error) {
            console.error('[WS_CLIENT] Failed to send message:', error);
            this.queueMessage(data);
            return false;
        }
    }
    
    /**
     * Queue message for later delivery
     */
    queueMessage(data) {
        if (this.messageQueue.length >= this.maxQueueSize) {
            console.warn('[WS_CLIENT] Message queue full, dropping oldest message');
            this.messageQueue.shift();
        }
        
        this.messageQueue.push(data);
    }
    
    /**
     * Process queued messages
     */
    processMessageQueue() {
        if (this.messageQueue.length === 0) {
            return;
        }
        
        console.log(`[WS_CLIENT] Processing ${this.messageQueue.length} queued messages`);
        
        while (this.messageQueue.length > 0) {
            const message = this.messageQueue.shift();
            this.send(message);
        }
    }
    
    /**
     * Schedule reconnection with exponential backoff
     */
    scheduleReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error('[WS_CLIENT] Max reconnection attempts reached');
            return;
        }
        
        this.reconnectAttempts++;
        
        // Calculate delay with exponential backoff
        const delay = Math.min(
            this.reconnectDelay * Math.pow(this.reconnectBackoffMultiplier, this.reconnectAttempts - 1),
            this.maxReconnectDelay
        );
        
        console.log(`[WS_CLIENT] 🔄 Reconnecting in ${(delay / 1000).toFixed(1)}s (attempt ${this.reconnectAttempts})`);
        this.setConnectionState('reconnecting');
        
        setTimeout(() => {
            if (this.connectionState === 'reconnecting') {
                this.connect();
            }
        }, delay);
    }
    
    /**
     * Start heartbeat mechanism
     */
    startHeartbeat() {
        this.clearHeartbeat();
        this.lastHeartbeat = Date.now();
        
        // Send periodic pings
        this.heartbeatTimer = setInterval(() => {
            if (this.connectionState === 'connected') {
                this.send({ type: 'ping', timestamp: new Date().toISOString() });
            }
        }, this.heartbeatInterval);
        
        // Check for missed heartbeats
        this.heartbeatCheckTimer = setInterval(() => {
            const timeSinceLastHeartbeat = Date.now() - this.lastHeartbeat;
            
            if (timeSinceLastHeartbeat > this.heartbeatTimeout) {
                console.warn('[WS_CLIENT] ⚠️ Heartbeat timeout, reconnecting...');
                this.disconnect();
                this.scheduleReconnect();
            }
        }, this.heartbeatInterval);
    }
    
    /**
     * Clear heartbeat timers
     */
    clearHeartbeat() {
        if (this.heartbeatTimer) {
            clearInterval(this.heartbeatTimer);
            this.heartbeatTimer = null;
        }
        
        if (this.heartbeatCheckTimer) {
            clearInterval(this.heartbeatCheckTimer);
            this.heartbeatCheckTimer = null;
        }
    }
    
    /**
     * Set connection state and emit state change event
     */
    setConnectionState(state) {
        const oldState = this.connectionState;
        this.connectionState = state;
        
        if (oldState !== state) {
            console.log(`[WS_CLIENT] State change: ${oldState} → ${state}`);
            this.emit('stateChange', { oldState, newState: state });
        }
    }
    
    /**
     * Register event handler
     */
    on(event, handler) {
        if (this.eventHandlers[event]) {
            this.eventHandlers[event].push(handler);
        }
    }
    
    /**
     * Unregister event handler
     */
    off(event, handler) {
        if (this.eventHandlers[event]) {
            this.eventHandlers[event] = this.eventHandlers[event].filter(h => h !== handler);
        }
    }
    
    /**
     * Emit event to all registered handlers
     */
    emit(event, data) {
        if (this.eventHandlers[event]) {
            this.eventHandlers[event].forEach(handler => {
                try {
                    handler(data);
                } catch (error) {
                    console.error(`[WS_CLIENT] Error in ${event} handler:`, error);
                }
            });
        }
    }
    
    /**
     * Get current connection state
     */
    getState() {
        return this.connectionState;
    }
    
    /**
     * Check if connected
     */
    isConnected() {
        return this.connectionState === 'connected';
    }
    
    /**
     * Get connection statistics
     */
    getStats() {
        return {
            ...this.stats,
            currentState: this.connectionState,
            reconnectAttempts: this.reconnectAttempts,
            queuedMessages: this.messageQueue.length
        };
    }
}

// Export for use in app.js
window.WebSocketClient = WebSocketClient;