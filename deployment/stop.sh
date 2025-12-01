#!/bin/bash

# Algo Trading Platform - Stop Script

echo "Stopping Algo Trading Platform..."

# Stop backend via supervisor
echo "Stopping backend service..."
sudo supervisorctl stop algo-trading

echo ""
echo "Algo Trading Platform stopped successfully!"
echo ""
echo "Note: Nginx is still running to serve static content."
echo "To stop Nginx: sudo systemctl stop nginx"
echo ""
echo "To restart: ./deployment/start.sh"
echo ""