#!/bin/bash

echo "========================================="
echo "Diagnosing and Fixing Backend Issues"
echo "========================================="

# Check if backend is running
echo "1. Checking backend status..."
sudo supervisorctl status algo-trading

# Check for errors in logs
echo ""
echo "2. Recent error logs (last 50 lines):"
echo "----------------------------------------"
sudo tail -50 /var/log/algo-trading/error.log

echo ""
echo "3. Recent output logs (last 30 lines):"
echo "----------------------------------------"
sudo tail -30 /var/log/algo-trading/output.log

# Try to identify the issue
echo ""
echo "4. Testing Python syntax..."
cd /home/ubuntu/algo-trading/backend
source venv/bin/activate
python3 -m py_compile main.py websocket_status.py

if [ $? -eq 0 ]; then
    echo "✅ Python syntax is valid"
else
    echo "❌ Python syntax error detected"
    exit 1
fi

# Check if websocket_status.py can be imported
echo ""
echo "5. Testing imports..."
python3 -c "import sys; sys.path.insert(0, '.'); import websocket_status; print('✅ websocket_status imports successfully')" 2>&1

# Restart backend
echo ""
echo "6. Restarting backend service..."
sudo supervisorctl restart algo-trading
sleep 3

# Check status again
echo ""
echo "7. Final status check..."
sudo supervisorctl status algo-trading

# Check if port 8000 is listening
echo ""
echo "8. Checking if backend is listening on port 8000..."
if sudo netstat -tulpn | grep :8000 > /dev/null; then
    echo "✅ Backend is listening on port 8000"
else
    echo "❌ Backend is NOT listening on port 8000"
    echo ""
    echo "Most recent error:"
    sudo tail -20 /var/log/algo-trading/error.log
fi

echo ""
echo "========================================="
echo "Diagnostic Complete"
echo "========================================="