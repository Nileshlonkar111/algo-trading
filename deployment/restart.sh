#!/bin/bash

# Algo Trading Platform - Restart Script
# This script restarts the backend service

set -e

echo "========================================="
echo "Restarting Algo Trading Platform"
echo "========================================="

# Stop the service
echo "Stopping service..."
sudo supervisorctl stop algo-trading

# Wait a moment
sleep 2

# Start the service
echo "Starting service..."
sudo supervisorctl start algo-trading

# Wait for startup
sleep 3

# Check status
echo ""
echo "Service Status:"
echo "==============="
sudo supervisorctl status algo-trading

echo ""
echo "========================================="
echo "Service restarted successfully!"
echo "========================================="
echo ""
echo "View logs in real-time:"
echo "  sudo tail -f /var/log/algo-trading/output.log"
echo ""
echo "Search for specific logs:"
echo "  sudo grep 'risk_limit' /var/log/algo-trading/output.log"
echo "  sudo grep 'ERROR' /var/log/algo-trading/output.log"
echo ""