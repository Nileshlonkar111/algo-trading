# Fix Internal Server Error 500

## Quick Diagnosis

Run these commands on EC2 to identify the issue:

```bash
# SSH to EC2
ssh -i your-key.pem ubuntu@your-ec2-ip

# Check if backend is running
sudo supervisorctl status algo-trading

# View error logs
sudo tail -50 /var/log/algo-trading/error.log

# Check nginx error logs
sudo tail -50 /var/log/nginx/error.log
```

---

## Common Causes & Fixes

### Issue 1: Backend Not Running

**Check:**
```bash
sudo supervisorctl status algo-trading
```

If shows `FATAL` or `STOPPED`:

**Fix:**
```bash
# Check what's wrong
sudo supervisorctl tail -100 algo-trading

# Common issues in logs:
# - Module not found
# - .env file missing
# - Port already in use
```

**Restart backend:**
```bash
cd /home/ubuntu/algo-trading/backend
source venv/bin/activate
pip install -r requirements.txt
sudo supervisorctl restart algo-trading
```

---

### Issue 2: Missing .env File

**Check:**
```bash
ls -la /home/ubuntu/algo-trading/backend/.env
```

If file doesn't exist:

**Fix:**
```bash
# Create .env file
nano /home/ubuntu/algo-trading/backend/.env
```

Add this content (replace with your values):
```bash
KITE_API_KEY=your_api_key_here
KITE_API_SECRET=your_api_secret_here
SECRET_KEY=your-secret-key-for-jwt-min-32-chars
```

Save and restart:
```bash
sudo supervisorctl restart algo-trading
```

---

### Issue 3: Python Dependencies Missing

**Check:**
```bash
cd /home/ubuntu/algo-trading/backend
source venv/bin/activate
python -c "import fastapi; import kiteconnect; print('OK')"
```

If error:

**Fix:**
```bash
cd /home/ubuntu/algo-trading/backend
source venv/bin/activate
pip install -r requirements.txt
sudo supervisorctl restart algo-trading
```

---

### Issue 4: Port 8000 Already in Use

**Check:**
```bash
sudo lsof -i :8000
```

If shows another process using port 8000:

**Fix:**
```bash
# Kill the process
sudo kill -9 $(sudo lsof -t -i:8000)

# Restart backend
sudo supervisorctl restart algo-trading
```

---

### Issue 5: Permission Issues

**Check:**
```bash
ls -la /home/ubuntu/algo-trading/backend/
```

**Fix:**
```bash
# Fix ownership
sudo chown -R ubuntu:ubuntu /home/ubuntu/algo-trading

# Fix permissions
chmod +x /home/ubuntu/algo-trading/backend/main.py

# Restart
sudo supervisorctl restart algo-trading
```

---

### Issue 6: Nginx Misconfiguration

**Check:**
```bash
sudo nginx -t
```

If shows errors:

**Fix:**
```bash
# Restore backup config
sudo cp /etc/nginx/sites-available/algo-trading.backup /etc/nginx/sites-available/algo-trading

# Or use simple config
sudo tee /etc/nginx/sites-available/algo-trading > /dev/null <<'EOF'
server {
    listen 80;
    server_name _;

    root /home/ubuntu/algo-trading/frontend;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
EOF

# Test and restart
sudo nginx -t
sudo systemctl restart nginx
```

---

### Issue 7: Backend Code Error

**Check logs for Python errors:**
```bash
sudo tail -100 /var/log/algo-trading/output.log
sudo tail -100 /var/log/algo-trading/error.log
```

Common errors:

**a) Import Error:**
```bash
# Fix: Install missing package
cd /home/ubuntu/algo-trading/backend
source venv/bin/activate
pip install <missing-package>
sudo supervisorctl restart algo-trading
```

**b) Syntax Error:**
```bash
# Fix: Pull latest code
cd /home/ubuntu/algo-trading
git pull origin dev
sudo supervisorctl restart algo-trading
```

**c) Database/Connection Error:**
```bash
# Check .env has correct values
cat /home/ubuntu/algo-trading/backend/.env
```

---

## Complete Diagnostic Script

Run this to get all info:

```bash
#!/bin/bash
echo "=== Diagnostic Report ==="
echo ""

echo "1. Supervisor Status:"
sudo supervisorctl status algo-trading
echo ""

echo "2. Backend Process:"
ps aux | grep uvicorn | grep -v grep
echo ""

echo "3. Port 8000 Status:"
sudo netstat -tlnp | grep 8000
echo ""

echo "4. .env File:"
if [ -f /home/ubuntu/algo-trading/backend/.env ]; then
    echo "EXISTS"
    echo "Keys present:"
    grep -E "^[A-Z_]+=" /home/ubuntu/algo-trading/backend/.env | cut -d= -f1
else
    echo "MISSING!"
fi
echo ""

echo "5. Nginx Status:"
sudo systemctl status nginx | grep Active
echo ""

echo "6. Nginx Config Test:"
sudo nginx -t
echo ""

echo "7. Recent Backend Errors (last 20 lines):"
sudo tail -20 /var/log/algo-trading/error.log
echo ""

echo "8. Recent Backend Output (last 20 lines):"
sudo tail -20 /var/log/algo-trading/output.log
echo ""

echo "9. Nginx Errors:"
sudo tail -20 /var/log/nginx/error.log
echo ""

echo "=== End Report ==="
```

Save as `diagnose.sh` and run:
```bash
chmod +x diagnose.sh
./diagnose.sh
```

---

## Step-by-Step Recovery

### 1. Stop Everything
```bash
sudo supervisorctl stop algo-trading
sudo systemctl stop nginx
```

### 2. Check .env File
```bash
cat /home/ubuntu/algo-trading/backend/.env
```
Ensure has: `KITE_API_KEY`, `KITE_API_SECRET`, `SECRET_KEY`

### 3. Test Backend Manually
```bash
cd /home/ubuntu/algo-trading/backend
source venv/bin/activate
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

If starts successfully, press Ctrl+C and proceed.
If errors, fix them first.

### 4. Restart Services
```bash
sudo supervisorctl start algo-trading
sleep 5
sudo supervisorctl status algo-trading
# Should show RUNNING

sudo systemctl start nginx
```

### 5. Test Endpoints
```bash
# Health check
curl http://localhost:8000/health

# Should return: {"status":"healthy"}
```

### 6. Test from Browser
```
http://your-ec2-ip
```

---

## Still Getting 500?

**Get detailed error:**
```bash
# Enable debug logging
cd /home/ubuntu/algo-trading/backend
nano main.py
```

Add at the top:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Restart and check logs:
```bash
sudo supervisorctl restart algo-trading
sleep 3
sudo tail -f /var/log/algo-trading/output.log
```

Try accessing the URL and watch logs in real-time.

---

## Emergency Rollback

If nothing works, rollback to working version:

```bash
cd /home/ubuntu/algo-trading
git log --oneline -10
# Find last working commit hash

git reset --hard <commit-hash>
sudo supervisorctl restart algo-trading
sudo systemctl restart nginx
```

---

## Get Help

If still stuck, provide these logs:

```bash
# Collect all logs
sudo supervisorctl tail -100 algo-trading > ~/debug.log
sudo tail -100 /var/log/nginx/error.log >> ~/debug.log
sudo tail -100 /var/log/algo-trading/error.log >> ~/debug.log
cat ~/debug.log
```

Share the output for further diagnosis.

---

## Prevention

Add health monitoring:

```bash
# Create health check script
cat > /home/ubuntu/health-check.sh <<'EOF'
#!/bin/bash
if ! curl -s http://localhost:8000/health > /dev/null; then
    echo "Backend down! Restarting..."
    sudo supervisorctl restart algo-trading
fi
EOF

chmod +x /home/ubuntu/health-check.sh

# Add to crontab (check every 5 minutes)
crontab -e
# Add: */5 * * * * /home/ubuntu/health-check.sh
```

Your 500 error should be resolved! 🎯