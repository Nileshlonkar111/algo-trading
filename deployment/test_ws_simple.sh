#!/bin/bash
# Simple WebSocket test without Python dependencies

echo "Testing WebSocket endpoint..."
echo ""

# Test direct backend
echo "1. Testing backend directly (localhost:8000/ws):"
timeout 2 curl --include --no-buffer \
  --header "Connection: Upgrade" \
  --header "Upgrade: websocket" \
  --header "Host: localhost:8000" \
  --header "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  --header "Sec-WebSocket-Version: 13" \
  http://localhost:8000/ws 2>&1 | head -5

echo ""
echo "2. Testing through nginx (localhost/api/ws):"
timeout 2 curl --include --no-buffer \
  --header "Connection: Upgrade" \
  --header "Upgrade: websocket" \
  --header "Host: localhost" \
  --header "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  --header "Sec-WebSocket-Version: 13" \
  http://localhost/api/ws 2>&1 | head -5

echo ""
echo "3. Checking services:"
echo -n "Nginx: "
systemctl is-active nginx
echo -n "Backend: "
sudo supervisorctl status algo-trading | awk '{print $2}'

echo ""
echo "If you see 'HTTP/1.1 101 Switching Protocols' above, WebSocket is working!"
echo "If you see '400 Bad Request' mentioning WebSocket, the endpoint exists but needs proper client."