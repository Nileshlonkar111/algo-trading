#!/bin/bash

# Algo Trading Platform - Setup Script
# Run this script on fresh EC2 instance

set -e  # Exit on error

echo "========================================="
echo "Algo Trading Platform Setup"
echo "========================================="

# Check if running as root
if [ "$EUID" -eq 0 ]; then 
    echo "Please do not run as root. Run as ubuntu user."
    exit 1
fi

# Update system
echo "Updating system packages..."
sudo apt update && sudo apt upgrade -y

# Install dependencies
echo "Installing dependencies..."
sudo apt install -y python3-pip python3-venv nginx supervisor git

# Setup backend
echo "Setting up backend..."
cd /home/ubuntu/algo-trading/backend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python packages
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn

# Check if .env exists
if [ ! -f .env ]; then
    echo "Creating .env file from template..."
    cp .env.example .env
    echo ""
    echo "⚠️  IMPORTANT: Edit /home/ubuntu/algo-trading/backend/.env with your API keys!"
    echo "    nano /home/ubuntu/algo-trading/backend/.env"
    echo ""
fi

# Create log directory
sudo mkdir -p /var/log/algo-trading
sudo chown ubuntu:ubuntu /var/log/algo-trading

# Configure Supervisor
echo "Configuring Supervisor..."
sudo tee /etc/supervisor/conf.d/algo-trading.conf > /dev/null <<EOF
[program:algo-trading]
directory=/home/ubuntu/algo-trading/backend
command=/home/ubuntu/algo-trading/backend/venv/bin/gunicorn -w 2 -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:8000
user=ubuntu
autostart=true
autorestart=true
stderr_logfile=/var/log/algo-trading/error.log
stdout_logfile=/var/log/algo-trading/output.log
environment=PATH="/home/ubuntu/algo-trading/backend/venv/bin"
EOF

# Configure Nginx
echo "Configuring Nginx..."
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
    }
}
EOF

# Enable Nginx site
sudo ln -sf /etc/nginx/sites-available/algo-trading /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Test Nginx config
sudo nginx -t

# Update frontend API URL
echo "Updating frontend configuration..."
cd /home/ubuntu/algo-trading/frontend
EC2_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)
sed -i "s|http://localhost:8000|http://${EC2_IP}/api|g" app.js

# Configure firewall
echo "Configuring firewall..."
sudo ufw --force enable
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
echo "y" | sudo ufw enable

# Reload services
echo "Starting services..."
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start algo-trading
sudo systemctl restart nginx

echo ""
echo "========================================="
echo "Setup Complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo "1. Edit configuration: nano /home/ubuntu/algo-trading/backend/.env"
echo "2. Add your KITE_API_KEY and KITE_API_SECRET"
echo "3. Restart backend: sudo supervisorctl restart algo-trading"
echo "4. Access dashboard: http://${EC2_IP}"
echo ""
echo "Default login:"
echo "  Username: admin"
echo "  Password: admin123"
echo ""
echo "⚠️  IMPORTANT: Change default password in backend/auth.py"
echo ""
echo "Check status:"
echo "  sudo supervisorctl status"
echo "  sudo systemctl status nginx"
echo ""
echo "View logs:"
echo "  sudo tail -f /var/log/algo-trading/output.log"
echo "  sudo tail -f /var/log/algo-trading/error.log"
echo ""