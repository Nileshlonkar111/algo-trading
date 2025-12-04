#!/bin/bash
# WebSocket Connection Diagnostic Script
# Checks all components of the WebSocket connection chain

echo "=================================================="
echo "WebSocket Connection Diagnostic"
echo "=================================================="
echo ""

# 1. Check if backend is running
echo "1. Checking backend service..."
if sudo supervisorctl status algo-trading | grep -q "RUNNING"; then
    echo "   ✅ Backend service is running"
else
    echo "   ❌ Backend service is NOT running"
    echo "   Run: sudo supervisorctl restart algo-trading"
fi
echo ""

# 2. Check if backend WebSocket endpoint responds locally
echo "2. Testing backend WebSocket endpoint (localhost:8000/ws)..."
python3 test_websocket.py
echo ""

# 3. Check nginx status
echo "3. Checking nginx service..."
if sudo systemctl is-active --quiet nginx; then
    echo "   ✅ Nginx is running"
else
    echo "   ❌ Nginx is NOT running"
    echo "   Run: sudo systemctl start nginx"
fi
echo ""

# 4. Check nginx configuration
echo "4. Checking nginx configuration..."
if sudo nginx -t 2>&1 | grep -q "syntax is ok"; then
    echo "   ✅ Nginx configuration is valid"
else
    echo "   ❌ Nginx configuration has errors"
    sudo nginx -t
fi
echo ""

# 5. Check which nginx config is active
echo "5. Checking active nginx configuration..."
if [ -L /etc/nginx/sites-enabled/algo-trading ]; then
    ACTIVE_CONFIG=$(readlink -f /etc/nginx/sites-enabled/algo-trading)
    echo "   Active config: $ACTIVE_CONFIG"
    
    # Check if it has WebSocket configuration
    if grep -q "location = /api/ws" "$ACTIVE_CONFIG"; then
        echo "   ✅ WebSocket endpoint configured in nginx"
    else
        echo "   ❌ WebSocket endpoint NOT configured in nginx"
        echo "   Expected: location = /api/ws"
    fi
else
    echo "   ❌ No active nginx configuration found"
fi
echo ""

# 6. Test nginx WebSocket proxy
echo "6. Testing nginx WebSocket proxy..."
if command -v websocat &> /dev/null; then
    echo "   Testing with websocat..."
    timeout 3 websocat ws://localhost/api/ws 2>&1 || echo "   Connection test completed"
elif command -v wscat &> /dev/null; then
    echo "   Testing with wscat..."
    timeout 3 wscat -c ws://localhost/api/ws 2>&1 || echo "   Connection test completed"
else
    echo "   ⚠️  No WebSocket client tool available (websocat/wscat)"
    echo "   Install with: sudo apt-get install -y websocat"
fi
echo ""

# 7. Check firewall/security group
echo "7. Checking network accessibility..."
echo "   Testing HTTP endpoint..."
if curl -s -o /dev/null -w "%{http_code}" http://localhost/health | grep -q "200"; then
    echo "   ✅ HTTP endpoint accessible through nginx"
else
    echo "   ❌ HTTP endpoint NOT accessible through nginx"
fi
echo ""

# 8. Check logs for errors
echo "8. Recent nginx errors (last 10 lines)..."
sudo tail -n 10 /var/log/nginx/error.log 2>/dev/null || echo "   No error log found"
echo ""

echo "9. Recent backend logs (last 20 lines)..."
sudo tail -n 20 /var/log/algo-trading.err.log 2>/dev/null || echo "   No backend error log found"
echo ""

echo "=================================================="
echo "Diagnostic Complete"
echo "=================================================="
echo ""
echo "Quick Fixes:"
echo "  - If nginx not running: sudo systemctl start nginx"
echo "  - If wrong config: sudo ln -sf ~/algo-trading/deployment/nginx_original.conf /etc/nginx/sites-available/algo-trading && sudo systemctl reload nginx"
echo "  - If backend not running: sudo supervisorctl restart algo-trading"
echo "  - View live logs: sudo tail -f /var/log/algo-trading.err.log"