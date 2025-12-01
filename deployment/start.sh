#!/bin/bash

# Algo Trading Platform - Start Script

set -e

echo "Starting Algo Trading Platform..."

# Start backend via supervisor
echo "Starting backend service..."
sudo supervisorctl start algo-trading

# Start nginx
echo "Starting Nginx..."
sudo systemctl start nginx

# Wait a moment
sleep 2

# Check status
echo ""
echo "Service Status:"
echo "==============="
sudo supervisorctl status algo-trading
sudo systemctl status nginx --no-pager

echo ""
echo "Algo Trading Platform started successfully!"
echo ""
echo "Access dashboard at: http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)"
echo ""
echo "View logs:"
echo "  sudo tail -f /var/log/algo-trading/output.log"
echo ""