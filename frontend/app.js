// API Configuration
// Auto-detect environment and set appropriate API base URL
//this is the latest change
function getApiBaseUrl() {
    const hostname = window.location.hostname;
    const protocol = window.location.protocol;
    const port = window.location.port;
    
    console.log('Detected - hostname:', hostname, 'protocol:', protocol, 'port:', port);
    
    // Local development
    if (hostname === 'localhost' || hostname === '127.0.0.1') {
        return 'http://localhost:8000';
    }
    
    // Production: construct full URL with /api prefix
    const baseUrl = `${protocol}//${hostname}${port ? ':' + port : ''}/api`;
    return baseUrl;
}

const API_BASE_URL = getApiBaseUrl();
console.log('API_BASE_URL set to:', API_BASE_URL);

let authToken = localStorage.getItem('authToken');
let wsClient = null; // WebSocket client instance
let isCheckingKiteStatus = false;
let isCheckingTradingStatus = false;

// Connection state indicator
let connectionStatusEl = null;

// Utility Functions
function showScreen(screenId) {
    document.querySelectorAll('.screen').forEach(s => s.classList.add('hidden'));
    document.getElementById(screenId).classList.remove('hidden');
}

function showError(elementId, message) {
    document.getElementById(elementId).textContent = message;
    setTimeout(() => {
        document.getElementById(elementId).textContent = '';
    }, 5000);
}

async function apiCall(endpoint, options = {}) {
    const headers = {
        'Content-Type': 'application/json',
        ...(authToken && { 'Authorization': `Bearer ${authToken}` })
    };

    try {
        const response = await fetch(`${API_BASE_URL}${endpoint}`, {
            ...options,
            headers: { ...headers, ...options.headers }
        });

        if (response.status === 401) {
            logout();
            throw new Error('Authentication expired');
        }

        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || 'API call failed');
        }
        return data;
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}

// Authentication
document.getElementById('loginForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;

    try {
        const data = await apiCall('/auth/login', {
            method: 'POST',
            body: JSON.stringify({ username, password })
        });

        authToken = data.access_token;
        localStorage.setItem('authToken', authToken);
        localStorage.setItem('username', username);
        
        document.getElementById('username-display').textContent = username;
        showScreen('dashboardScreen');
        initDashboard();
    } catch (error) {
        showError('loginError', error.message);
    }
});

document.getElementById('logoutBtn').addEventListener('click', logout);

function logout() {
    authToken = null;
    localStorage.removeItem('authToken');
    localStorage.removeItem('username');
    
    // Disconnect WebSocket
    if (wsClient) {
        wsClient.disconnect();
        wsClient = null;
    }
    
    showScreen('loginScreen');
}

// Initialize Dashboard with WebSocket
async function initDashboard() {
    // Show loading states
    document.getElementById('kiteStatus').textContent = 'Checking...';
    document.getElementById('tradingStatus').textContent = 'Checking...';
    
    // Load data with proper sequencing
    try {
        await loadConfig();
        
        // Initialize WebSocket connection for real-time updates
        initWebSocket();
        
    } catch (error) {
        console.error('Dashboard initialization error:', error);
        showError('loginError', 'Failed to initialize dashboard: ' + error.message);
    }
}

/**
 * Initialize WebSocket connection for real-time updates
 * Replaces the polling mechanism with push-based updates
 */
function initWebSocket() {
    console.log('[DASHBOARD] Initializing WebSocket connection...');
    
    // Create WebSocket client with configuration
    wsClient = new WebSocketClient('/ws', {
        reconnectDelay: 1000,
        maxReconnectDelay: 30000,
        reconnectBackoffMultiplier: 1.5,
        heartbeatInterval: 30000,
        stateUpdateDebounceTime: 100 // Debounce UI updates to prevent flickering
    });
    
    // Handle connection open
    wsClient.on('open', () => {
        console.log('[DASHBOARD] ✅ WebSocket connected');
        updateConnectionStatus('connected');
    });
    
    // Handle connection close
    wsClient.on('close', () => {
        console.log('[DASHBOARD] ⚠️ WebSocket disconnected');
        updateConnectionStatus('disconnected');
    });
    
    // Handle connection errors
    wsClient.on('error', (error) => {
        console.error('[DASHBOARD] WebSocket error:', error);
        updateConnectionStatus('error');
    });
    
    // Handle state changes
    wsClient.on('stateChange', ({ oldState, newState }) => {
        console.log(`[DASHBOARD] Connection state: ${oldState} → ${newState}`);
        
        if (newState === 'reconnecting') {
            updateConnectionStatus('reconnecting');
        } else if (newState === 'connected') {
            updateConnectionStatus('connected');
        } else if (newState === 'disconnected') {
            updateConnectionStatus('disconnected');
        }
    });
    
    // Handle incoming messages
    wsClient.on('message', (message) => {
        handleWebSocketMessage(message);
    });
    
    // Connect to WebSocket
    wsClient.connect();
}

/**
 * Handle incoming WebSocket messages
 * Updates UI based on message type with built-in deduplication
 */
function handleWebSocketMessage(message) {
    const messageType = message.type;
    
    console.log('[DASHBOARD] Processing message:', messageType);
    
    switch (messageType) {
        case 'dashboard_update':
            // Complete dashboard update with all sections
            updateDashboardFromWebSocket(message.data);
            break;
            
        case 'trading_status':
            // Trading status update only
            if (message.data) {
                updateTradingStatusFromData(message.data);
            }
            break;
            
        case 'notification':
            // New notification received
            handleNotificationMessage(message.data);
            break;
            
        case 'position_closed':
            // Position closed event
            console.log('[DASHBOARD] Position closed:', message.data);
            break;
            
        case 'order_executed':
            // Order execution event
            console.log('[DASHBOARD] Order executed:', message.data);
            break;
            
        case 'connection_established':
            console.log('[DASHBOARD] Connection established with server');
            break;
            
        default:
            console.log('[DASHBOARD] Unknown message type:', messageType);
    }
}

/**
 * Update entire dashboard from WebSocket data
 * This replaces the polling-based updateDashboard function
 */
function updateDashboardFromWebSocket(data) {
    // Update all UI components from WebSocket message
    // The WebSocket manager already handles deduplication
    if (data.trading) {
        updateTradingStatusFromData(data.trading);
    }
    
    if (data.pnl) {
        updatePnLFromData(data.pnl);
    }
    
    if (data.positions) {
        updatePositionsFromData(data.positions);
    }
    
    if (data.logs) {
        updateTradeLogsFromData(data.logs);
    }
    
    if (data.notifications) {
        updateNotificationsFromData(data.notifications);
    }
}

/**
 * Handle notification messages from WebSocket
 */
function handleNotificationMessage(notification) {
    console.log('[DASHBOARD] New notification:', notification);
    // Notification will be included in next dashboard update
}

/**
 * Update connection status indicator
 */
function updateConnectionStatus(status) {
    // Create status indicator if it doesn't exist
    if (!connectionStatusEl) {
        const navbar = document.querySelector('.navbar .nav-actions');
        if (navbar) {
            connectionStatusEl = document.createElement('span');
            connectionStatusEl.id = 'ws-connection-status';
            connectionStatusEl.style.marginRight = '15px';
            navbar.insertBefore(connectionStatusEl, navbar.firstChild);
        }
    }
    
    if (!connectionStatusEl) return;
    
    // Update status display
    const statusMap = {
        connected: { text: '🟢 Live', class: 'ws-connected' },
        connecting: { text: '🟡 Connecting...', class: 'ws-connecting' },
        reconnecting: { text: '🟡 Reconnecting...', class: 'ws-reconnecting' },
        disconnected: { text: '🔴 Disconnected', class: 'ws-disconnected' },
        error: { text: '🔴 Error', class: 'ws-error' }
    };
    
    const statusInfo = statusMap[status] || statusMap.disconnected;
    connectionStatusEl.textContent = statusInfo.text;
    connectionStatusEl.className = statusInfo.class;
}

function updateTradingStatusFromData(trading) {
    const statusEl = document.getElementById('tradingStatus');
    const btnEl = document.getElementById('toggleTradingBtn');
    
    if (trading.active) {
        statusEl.textContent = 'Active';
        statusEl.className = 'status-indicator active';
        btnEl.textContent = 'Stop Trading';
        btnEl.className = 'btn-danger';
    } else {
        statusEl.textContent = 'Stopped';
        statusEl.className = 'status-indicator disconnected';
        btnEl.textContent = 'Start Trading';
        btnEl.className = 'btn-primary';
    }
    
    document.getElementById('openPositions').textContent = trading.open_positions || 0;
    
    // Update Kite status as well
    const kiteStatusEl = document.getElementById('kiteStatus');
    if (trading.token_status === 'authenticated') {
        kiteStatusEl.textContent = 'Connected';
        kiteStatusEl.className = 'status-indicator connected';
    } else if (trading.token_status === 'expired') {
        kiteStatusEl.textContent = 'Expired - Re-auth Required';
        kiteStatusEl.className = 'status-indicator disconnected';
    } else {
        kiteStatusEl.textContent = 'Not Connected';
        kiteStatusEl.className = 'status-indicator disconnected';
    }
}

function updatePnLFromData(pnl) {
    const pnlEl = document.getElementById('pnlDisplay');
    const pctEl = document.getElementById('pnlPercent');
    
    const pnlValue = pnl.realized_pnl || 0;
    const pnlPct = (pnl.daily_pl_ratio || 0) * 100;
    
    pnlEl.textContent = `₹${pnlValue.toFixed(2)}`;
    pnlEl.className = 'pnl-value ' + (pnlValue >= 0 ? 'positive' : 'negative');
    pctEl.textContent = `${pnlPct.toFixed(2)}%`;
}

function updatePositionsFromData(positionsData) {
    const container = document.getElementById('positionsTable');
    const positions = Object.entries(positionsData || {}).filter(([_, pos]) => pos.status === 'OPEN');
    
    if (positions.length === 0) {
        container.innerHTML = '<p class="no-data">No open positions</p>';
        return;
    }
    
    let html = '<table><thead><tr><th>Symbol</th><th>Entry Price</th><th>Current LTP</th><th>Qty</th><th>SL</th><th>Target</th><th>Status</th></tr></thead><tbody>';
    
    for (const [symbol, pos] of positions) {
        html += `<tr>
            <td>${symbol}</td>
            <td>₹${pos.entry_price?.toFixed(2) || 0}</td>
            <td>-</td>
            <td>${pos.quantity || 0}</td>
            <td>₹${pos.sl_price?.toFixed(2) || 0}</td>
            <td>₹${pos.target_price?.toFixed(2) || 0}</td>
            <td><span class="status-indicator active">${pos.status}</span></td>
        </tr>`;
    }
    
    html += '</tbody></table>';
    container.innerHTML = html;
}

function updateTradeLogsFromData(logs) {
    const container = document.getElementById('tradeLogsTable');
    
    if (logs.length === 0) {
        container.innerHTML = '<p class="no-data">No trades yet</p>';
        return;
    }
    
    let html = '<table><thead><tr><th>Time</th><th>Symbol</th><th>Action</th><th>Price</th><th>P&L</th><th>Status</th><th>Note</th></tr></thead><tbody>';
    
    const recentLogs = logs.slice(-20).reverse();
    
    for (const log of recentLogs) {
        const pnlClass = log.pnl > 0 ? 'positive' : (log.pnl < 0 ? 'negative' : '');
        html += `<tr>
            <td>${log.time}</td>
            <td>${log.symbol}</td>
            <td>${log.action}</td>
            <td>₹${log.entry_price?.toFixed(2) || 0}</td>
            <td class="${pnlClass}">${log.pnl ? '₹' + log.pnl.toFixed(2) : '-'}</td>
            <td>${log.status}</td>
            <td>${log.note || '-'}</td>
        </tr>`;
    }
    
    html += '</tbody></table>';
    container.innerHTML = html;
}

function updateNotificationsFromData(notificationsData) {
    const container = document.getElementById('notificationsList');
    
    if (notificationsData.length === 0) {
        container.innerHTML = '<p class="no-data">No notifications</p>';
        return;
    }
    
    let html = '';
    const recentNotifications = notificationsData.slice(-20).reverse();
    
    for (const notif of recentNotifications) {
        const typeClass = notif.type === 'error' ? 'error' :
                        notif.type === 'order_executed' ? 'success' : '';
        
        html += `<div class="notification-item ${typeClass}">
            <div class="timestamp">${notif.timestamp || new Date().toLocaleString()}</div>
            <div class="message"><strong>${notif.type}</strong>: ${JSON.stringify(notif.data)}</div>
        </div>`;
    }
    
    container.innerHTML = html;
}

// Kite Authentication
document.getElementById('kiteLoginBtn').addEventListener('click', () => {
    document.getElementById('kiteAuthModal').classList.remove('hidden');
});

document.getElementById('closeModalBtn').addEventListener('click', () => {
    document.getElementById('kiteAuthModal').classList.add('hidden');
});

document.getElementById('openKiteLoginBtn').addEventListener('click', async () => {
    try {
        const data = await apiCall('/kite/login_url');
        window.open(data.login_url, '_blank');
    } catch (error) {
        showError('authError', error.message);
    }
});

document.getElementById('submitTokenBtn').addEventListener('click', async () => {
    const requestToken = document.getElementById('requestToken').value.trim();
    if (!requestToken) {
        showError('authError', 'Please enter request token');
        return;
    }

    const btn = document.getElementById('submitTokenBtn');
    const originalText = btn.textContent;
    
    try {
        btn.disabled = true;
        btn.textContent = 'Authenticating...';
        
        await apiCall('/kite/generate_token', {
            method: 'POST',
            body: JSON.stringify({ request_token: requestToken })
        });
        
        // Clear input field
        document.getElementById('requestToken').value = '';
        
        // Close modal and refresh status
        document.getElementById('kiteAuthModal').classList.add('hidden');
        await checkKiteStatus();
        alert('Kite authentication successful!');
    } catch (error) {
        showError('authError', 'Authentication failed: ' + error.message);
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
});

async function checkKiteStatus() {
    if (isCheckingKiteStatus) return; // Prevent concurrent calls
    
    isCheckingKiteStatus = true;
    const statusEl = document.getElementById('kiteStatus');
    
    try {
        const data = await apiCall('/kite/token_status');
        
        if (data.status === 'authenticated') {
            statusEl.textContent = 'Connected';
            statusEl.className = 'status-indicator connected';
        } else if (data.status === 'expired') {
            statusEl.textContent = 'Expired - Re-auth Required';
            statusEl.className = 'status-indicator disconnected';
        } else {
            statusEl.textContent = 'Not Connected';
            statusEl.className = 'status-indicator disconnected';
        }
    } catch (error) {
        console.error('Failed to check Kite status:', error);
        statusEl.textContent = 'Error Checking Status';
        statusEl.className = 'status-indicator disconnected';
    } finally {
        isCheckingKiteStatus = false;
    }
}

// Trading Control
document.getElementById('toggleTradingBtn').addEventListener('click', async () => {
    const btn = document.getElementById('toggleTradingBtn');
    const originalText = btn.textContent;
    
    try {
        // Show loading state
        btn.disabled = true;
        btn.textContent = 'Processing...';
        
        const statusData = await apiCall('/trading/status');
        
        if (statusData.active) {
            await apiCall('/trading/stop', { method: 'POST' });
            alert('Trading stopped successfully');
        } else {
            // Check authentication status
            if (!statusData.authenticated) {
                const tokenStatus = statusData.token_status || 'not_authenticated';
                if (tokenStatus === 'expired') {
                    alert('Kite authentication expired. Please re-authenticate.');
                } else {
                    alert('Please authenticate with Kite first');
                }
                document.getElementById('kiteAuthModal').classList.remove('hidden');
                return;
            }
            
            await apiCall('/trading/start', { method: 'POST' });
            alert('Trading started successfully');
        }
        
        // WebSocket will automatically push the updated status
        // No need to manually refresh
    } catch (error) {
        console.error('Trading toggle error:', error);
        
        // Show user-friendly error messages
        if (error.message.includes('expired') || error.message.includes('authentication')) {
            alert('Authentication issue: ' + error.message + '\nPlease re-authenticate with Kite.');
            document.getElementById('kiteAuthModal').classList.remove('hidden');
        } else {
            alert('Error: ' + error.message);
        }
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
});

let latestTradingStatusTimestamp = 0;
async function checkTradingStatus() {
    if (isCheckingTradingStatus) return; // Prevent concurrent calls
    
    isCheckingTradingStatus = true;
    const requestTimestamp = Date.now();

    try {
        const data = await apiCall('/trading/status');
        // Only update UI if this is the latest request
        if (requestTimestamp < latestTradingStatusTimestamp) return;
        latestTradingStatusTimestamp = requestTimestamp;

        const statusEl = document.getElementById('tradingStatus');
        const btnEl = document.getElementById('toggleTradingBtn');

        if (data.active) {
            statusEl.textContent = 'Active';
            statusEl.className = 'status-indicator active';
            btnEl.textContent = 'Stop Trading';
            btnEl.className = 'btn-danger';
        } else {
            statusEl.textContent = 'Stopped';
            statusEl.className = 'status-indicator disconnected';
            btnEl.textContent = 'Start Trading';
            btnEl.className = 'btn-primary';
        }

        document.getElementById('openPositions').textContent = data.open_positions || 0;
    } catch (error) {
        if (requestTimestamp < latestTradingStatusTimestamp) return;
        latestTradingStatusTimestamp = requestTimestamp;
        console.error('Failed to check trading status:', error);
        const statusEl = document.getElementById('tradingStatus');
        statusEl.textContent = 'Error';
        statusEl.className = 'status-indicator disconnected';
    } finally {
        isCheckingTradingStatus = false;
    }
}

// Configuration
async function loadConfig() {
    try {
        const data = await apiCall('/trades/config');
        const config = data.config;
        
        document.getElementById('capitalBase').value = config.capital_base || 300000;
        document.getElementById('maxPositions').value = config.max_concurrent_pos || 3;
        document.getElementById('maxLoss').value = (config.daily_max_loss || -0.02) * 100;
        document.getElementById('maxProfit').value = (config.daily_max_profit || 0.04) * 100;
        document.getElementById('lotQty').value = config.lot_qty || 75;
    } catch (error) {
        console.error('Failed to load config:', error);
    }
}

document.getElementById('updateConfigBtn').addEventListener('click', async () => {
    const config = {
        capital_base: parseFloat(document.getElementById('capitalBase').value),
        max_concurrent_pos: parseInt(document.getElementById('maxPositions').value),
        daily_max_loss: parseFloat(document.getElementById('maxLoss').value) / 100,
        daily_max_profit: parseFloat(document.getElementById('maxProfit').value) / 100,
        lot_qty: parseInt(document.getElementById('lotQty').value)
    };

    try {
        await apiCall('/trades/config', {
            method: 'POST',
            body: JSON.stringify(config)
        });
        alert('Configuration updated successfully');
    } catch (error) {
        alert('Failed to update config: ' + error.message);
    }
});

// P&L Display
async function updatePnL() {
    try {
        const data = await apiCall('/trades/pnl');
        const pnlEl = document.getElementById('pnlDisplay');
        const pctEl = document.getElementById('pnlPercent');
        
        const pnl = data.realized_pnl || 0;
        const pnlPct = (data.daily_pl_ratio || 0) * 100;
        
        pnlEl.textContent = `₹${pnl.toFixed(2)}`;
        pnlEl.className = 'pnl-value ' + (pnl >= 0 ? 'positive' : 'negative');
        
        pctEl.textContent = `${pnlPct.toFixed(2)}%`;
    } catch (error) {
        console.error('Failed to update P&L:', error);
    }
}

// Positions
async function updatePositions() {
    try {
        const data = await apiCall('/trades/positions');
        const container = document.getElementById('positionsTable');
        const positions = Object.entries(data.positions || {}).filter(([_, pos]) => pos.status === 'OPEN');
        
        if (positions.length === 0) {
            container.innerHTML = '<p class="no-data">No open positions</p>';
            return;
        }
        
        let html = '<table><thead><tr><th>Symbol</th><th>Entry Price</th><th>Current LTP</th><th>Qty</th><th>SL</th><th>Target</th><th>Status</th></tr></thead><tbody>';
        
        for (const [symbol, pos] of positions) {
            html += `<tr>
                <td>${symbol}</td>
                <td>₹${pos.entry_price?.toFixed(2) || 0}</td>
                <td>-</td>
                <td>${pos.quantity || 0}</td>
                <td>₹${pos.sl_price?.toFixed(2) || 0}</td>
                <td>₹${pos.target_price?.toFixed(2) || 0}</td>
                <td><span class="status-indicator active">${pos.status}</span></td>
            </tr>`;
        }
        
        html += '</tbody></table>';
        container.innerHTML = html;
    } catch (error) {
        console.error('Failed to update positions:', error);
    }
}

// Trade Logs
async function updateTradeLogs() {
    try {
        const data = await apiCall('/trades/logs');
        const container = document.getElementById('tradeLogsTable');
        const logs = data.logs || [];
        
        if (logs.length === 0) {
            container.innerHTML = '<p class="no-data">No trades yet</p>';
            return;
        }
        
        let html = '<table><thead><tr><th>Time</th><th>Symbol</th><th>Action</th><th>Price</th><th>P&L</th><th>Status</th><th>Note</th></tr></thead><tbody>';
        
        // Show last 20 trades
        const recentLogs = logs.slice(-20).reverse();
        
        for (const log of recentLogs) {
            const pnlClass = log.pnl > 0 ? 'positive' : (log.pnl < 0 ? 'negative' : '');
            html += `<tr>
                <td>${log.time}</td>
                <td>${log.symbol}</td>
                <td>${log.action}</td>
                <td>₹${log.entry_price?.toFixed(2) || 0}</td>
                <td class="${pnlClass}">${log.pnl ? '₹' + log.pnl.toFixed(2) : '-'}</td>
                <td>${log.status}</td>
                <td>${log.note || '-'}</td>
            </tr>`;
        }
        
        html += '</tbody></table>';
        container.innerHTML = html;
    } catch (error) {
        console.error('Failed to update trade logs:', error);
    }
}

// Notifications
async function updateNotifications() {
    try {
        const data = await apiCall('/notifications?limit=50');
        const container = document.getElementById('notificationsList');
        const notifications = data.notifications || [];
        
        if (notifications.length === 0) {
            container.innerHTML = '<p class="no-data">No notifications</p>';
            return;
        }
        
        let html = '';
        const recentNotifications = notifications.slice(-20).reverse();
        
        for (const notif of recentNotifications) {
            const typeClass = notif.type === 'error' ? 'error' : 
                            notif.type === 'order_executed' ? 'success' : '';
            
            html += `<div class="notification-item ${typeClass}">
                <div class="timestamp">${notif.timestamp || new Date().toLocaleString()}</div>
                <div class="message"><strong>${notif.type}</strong>: ${JSON.stringify(notif.data)}</div>
            </div>`;
        }
        
        container.innerHTML = html;
    } catch (error) {
        console.error('Failed to update notifications:', error);
    }
}

document.getElementById('clearNotificationsBtn').addEventListener('click', async () => {
    try {
        await apiCall('/notifications', { method: 'DELETE' });
        document.getElementById('notificationsList').innerHTML = '<p class="no-data">No notifications</p>';
    } catch (error) {
        alert('Failed to clear notifications: ' + error.message);
    }
});

// Emergency Controls
document.getElementById('closeAllBtn').addEventListener('click', async () => {
    if (!confirm('Are you sure you want to close all open positions? This action cannot be undone.')) {
        return;
    }

    try {
        await apiCall('/trading/close_all', { method: 'POST' });
        alert('All positions closed successfully');
        await updatePositions();
        await updatePnL();
    } catch (error) {
        alert('Failed to close positions: ' + error.message);
    }
});

// Initialize on page load
if (authToken) {
    const username = localStorage.getItem('username');
    document.getElementById('username-display').textContent = username;
    showScreen('dashboardScreen');
    initDashboard();
} else {
    showScreen('loginScreen');
}

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    if (wsClient) {
        wsClient.disconnect();
    }
});