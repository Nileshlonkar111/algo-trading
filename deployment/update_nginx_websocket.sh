#!/bin/bash

# Script to update Nginx configuration with WebSocket support

echo "========================================="
echo "Updating Nginx for WebSocket Support"
echo "========================================="

# Backup existing configuration
echo "Backing up existing configuration..."
sudo cp /etc/nginx/sites-available/algo-trading /etc/nginx/sites-available/algo-trading.backup.$(date +%Y%m%d_%H%M%S)

# Update Nginx configuration
echo "Updating Nginx configuration..."
sudo tee /etc/nginx/sites-available/algo-trading > /dev/null <<'EOF'
server {
    listen 80;
    server_name _;

    # Frontend
    location / {
        root /home/ubuntu/algo-trading/frontend;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # Backend API
    location /api/ {
        rewrite ^/api/(.*) /$1 break;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # WebSocket support - CRITICAL for real-time updates
    location /api/ws/ {
        rewrite ^/api/ws/(.*) /ws/$1 break;
        proxy_pass http://127.0.0.1:8000;
        
        # WebSocket specific headers
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Standard proxy headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts for long-lived connections
        proxy_connect_timeout 7d;
        proxy_send_timeout 7d;
        proxy_read_timeout 7d;
    }
}
EOF

# Test Nginx configuration
echo "Testing Nginx configuration..."
sudo nginx -t

if [ $? -eq 0 ]; then
    echo "Configuration valid! Reloading Nginx..."
    sudo systemctl reload nginx
    echo ""
    echo "========================================="
    echo "✅ Nginx Updated Successfully!"
    echo "========================================="
    echo ""
    echo "WebSocket endpoint now available at:"
    echo "  ws://your-server/api/ws/status"
    echo ""
    echo "Test the WebSocket connection by:"
    echo "1. Refreshing your browser"
    echo "2. Check browser console for: [WEBSOCKET] Connected successfully"
    echo ""
else
    echo ""
    echo "❌ Configuration test failed!"
    echo "Restoring backup..."
    sudo cp /etc/nginx/sites-available/algo-trading.backup.* /etc/nginx/sites-available/algo-trading
    echo "Original configuration restored."
fi