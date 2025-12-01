# Quick Start Guide

Get the Algo Trading Platform running in 15 minutes.

## Prerequisites

- Python 3.8+
- Zerodha Kite API credentials (API Key & Secret)

## Local Development Setup

### 1. Clone Repository

```bash
git clone <repository-url>
cd algo-trading-platform
```

### 2. Backend Setup

```bash
cd backend
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit with your API credentials
nano .env  # or use any text editor
```

**Required Configuration:**

```env
KITE_API_KEY=your_api_key_here
KITE_API_SECRET=your_api_secret_here
SECRET_KEY=generate-random-string-here
```

**Generate Secret Key (optional but recommended):**

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 4. Start Backend

```bash
python main.py
```

Backend will start at: `http://localhost:8000`

### 5. Start Frontend

Open a new terminal:

```bash
cd frontend
python -m http.server 3000
```

Frontend will be available at: `http://localhost:3000`

### 6. Access Dashboard

Open browser: `http://localhost:3000`

**Default Login Credentials:**
- Username: `admin`
- Password: `admin123`

⚠️ **Change these credentials in `backend/auth.py` before production use!**

### 7. Setup Kite Authentication

1. Click **"Setup Kite Auth"** button
2. Click **"Open Kite Login"**
3. Login with your Zerodha credentials
4. Copy the **request_token** from redirect URL
5. Paste token in dashboard and submit

Example redirect URL:
```
https://127.0.0.1/?request_token=ABCD1234&action=login&status=success
```
Copy only: `ABCD1234`

### 8. Configure Trading Parameters

Update in the dashboard:
- Capital Base: ₹300,000 (default)
- Max Concurrent Positions: 3
- Daily Max Loss: -2%
- Daily Max Profit: 4%
- Lot Quantity: 75

Click **"Update Configuration"**

### 9. Start Trading

1. Ensure Kite authentication is complete (Status: Connected)
2. Click **"Start Trading"** button
3. Monitor positions and logs in real-time

### 10. Monitor Trading

Dashboard displays:
- ✅ Real-time P&L
- ✅ Open positions
- ✅ Trade history
- ✅ Notifications & alerts

## Production Deployment (AWS EC2)

### One-Command Setup

```bash
# SSH to EC2
ssh -i your-key.pem ubuntu@your-ec2-ip

# Clone repo
git clone <repository-url> algo-trading
cd algo-trading

# Run setup script
./deployment/setup.sh

# Edit configuration
nano backend/.env

# Restart backend
sudo supervisorctl restart algo-trading
```

Access: `http://your-ec2-ip`

**Full deployment guide:** [`deployment/DEPLOYMENT.md`](deployment/DEPLOYMENT.md:1)

## Common Commands

### Backend

```bash
# Start
python main.py

# With auto-reload (development)
uvicorn main:app --reload

# Production (Gunicorn)
gunicorn -w 2 -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:8000
```

### Check Logs

```bash
# Local
tail -f backend.log

# EC2
sudo tail -f /var/log/algo-trading/output.log
```

### Service Management (EC2)

```bash
# Status
sudo supervisorctl status algo-trading

# Restart
sudo supervisorctl restart algo-trading

# Stop
sudo supervisorctl stop algo-trading

# Logs
sudo supervisorctl tail -f algo-trading
```

## Testing the Setup

### 1. Health Check

```bash
curl http://localhost:8000/health
```

Expected: `{"status":"healthy","version":"1.0.0"}`

### 2. API Documentation

Visit: `http://localhost:8000/docs`

### 3. Test Login

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
```

### 4. Test Kite Login URL

```bash
# Get auth token from login response
TOKEN="your-jwt-token-here"

curl http://localhost:8000/kite/login_url \
  -H "Authorization: Bearer $TOKEN"
```

## Troubleshooting

### Issue: Backend won't start

**Check:**
1. Python dependencies installed: `pip list`
2. Port 8000 available: `lsof -i :8000` (Linux/Mac)
3. `.env` file exists with API keys
4. Logs for errors: `tail -f backend.log`

### Issue: Kite authentication fails

**Verify:**
1. API Key and Secret are correct in `.env`
2. Request token is fresh (expires quickly)
3. Redirect URL matches Kite app settings

### Issue: Frontend can't connect to backend

**Check:**
1. Backend is running: `curl http://localhost:8000/health`
2. API URL in `frontend/app.js` is correct
3. CORS is enabled in `backend/main.py`

### Issue: Trading not starting

**Verify:**
1. Kite authentication is complete
2. Market hours (9:30 AM - 3:20 PM IST)
3. Daily P&L limits not reached
4. Check logs for specific errors

## Security Checklist

Before production:
- [ ] Change default admin password in [`backend/auth.py`](backend/auth.py:1)
- [ ] Generate strong SECRET_KEY in `.env`
- [ ] Never commit `.env` to version control
- [ ] Enable HTTPS/SSL certificate
- [ ] Restrict CORS to your domain
- [ ] Configure firewall rules
- [ ] Regular security updates

## Next Steps

1. **Read full documentation:** [`README.md`](README.md:1)
2. **Review user stories:** [`userStory.md`](userStory.md:1)
3. **Deployment guide:** [`deployment/DEPLOYMENT.md`](deployment/DEPLOYMENT.md:1)
4. **Customize trading logic:** Review [`backend/trading_engine.py`](backend/trading_engine.py:1)

## Support

- Check logs for error details
- Review API documentation at `/docs`
- Verify all prerequisites are met
- Test individual components

## Disclaimer

This software is for educational purposes. Trading involves substantial risk. Use at your own discretion.