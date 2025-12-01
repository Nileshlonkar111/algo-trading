// API Configuration
// Auto-detect protocol and use relative path for API calls
const API_BASE_URL = window.location.origin.includes('localhost')
    ? 'http://localhost:8000'
    : window.location.origin;
let authToken = localStorage.getItem('authToken');
let refreshInterval = null;

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
    clearInterval(refreshInterval);
    showScreen('loginScreen');
}

// Initialize Dashboard
async function initDashboard() {
    await loadConfig();
    await checkKiteStatus();
    await checkTradingStatus();
    startAutoRefresh();
}

function startAutoRefresh() {
    refreshInterval = setInterval(async () => {
        await Promise.all([
            updatePnL(),
            updatePositions(),
            updateTradeLogs(),
            updateNotifications(),
            checkTradingStatus()
        ]);
    }, 5000); // Refresh every 5 seconds
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
    const requestToken = document.getElementById('requestToken').value;
    if (!requestToken) {
        showError('authError', 'Please enter request token');
        return;
    }

    try {
        await apiCall('/kite/generate_token', {
            method: 'POST',
            body: JSON.stringify({ request_token: requestToken })
        });
        
        document.getElementById('kiteAuthModal').classList.add('hidden');
        await checkKiteStatus();
        alert('Kite authentication successful!');
    } catch (error) {
        showError('authError', error.message);
    }
});

async function checkKiteStatus() {
    try {
        const data = await apiCall('/kite/token_status');
        const statusEl = document.getElementById('kiteStatus');
        
        if (data.status === 'authenticated') {
            statusEl.textContent = 'Connected';
            statusEl.className = 'status-indicator connected';
        } else {
            statusEl.textContent = 'Not Connected';
            statusEl.className = 'status-indicator disconnected';
        }
    } catch (error) {
        console.error('Failed to check Kite status:', error);
    }
}

// Trading Control
document.getElementById('toggleTradingBtn').addEventListener('click', async () => {
    const statusData = await apiCall('/trading/status');
    
    try {
        if (statusData.active) {
            await apiCall('/trading/stop', { method: 'POST' });
            alert('Trading stopped');
        } else {
            if (!statusData.authenticated) {
                alert('Please authenticate with Kite first');
                return;
            }
            await apiCall('/trading/start', { method: 'POST' });
            alert('Trading started');
        }
        await checkTradingStatus();
    } catch (error) {
        alert('Error: ' + error.message);
    }
});

async function checkTradingStatus() {
    try {
        const data = await apiCall('/trading/status');
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
        console.error('Failed to check trading status:', error);
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