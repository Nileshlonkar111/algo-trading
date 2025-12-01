# Algo Trading Platform

A production-ready algorithmic trading platform for NIFTY options trading using Zerodha Kite API.

## Features

- ✅ **Automated Trading Logic**: EMA crossover, ATR filter, VWAP validation
- ✅ **Real-time Dashboard**: Monitor positions, P&L, and trade logs
- ✅ **Secure Authentication**: JWT-based user authentication
- ✅ **Risk Management**: Daily P&L limits, position limits, cooldown periods
- ✅ **Notifications & Alerts**: Real-time trading events and error notifications
- ✅ **User-Configurable**: Adjust capital, risk parameters via UI
- ✅ **Production Ready**: Optimized for AWS EC2 free-tier deployment

## Architecture

```
├── backend/              # FastAPI backend
│   ├── main.py          # API endpoints
│   ├── trading_engine.py # Core trading logic
│   ├── trading_logic.py  # Market data & indicators
│   ├── kite_service.py   # Kite API integration
│   ├── auth.py          # Authentication
│   └── requirements.txt  # Python dependencies
├── frontend/            # Web dashboard
│   ├── index.html      # Main UI
│   ├── styles.css      # Styling
│   └── app.js          # Frontend logic
└── deployment/         # Deployment configs
```

## Prerequisites

- Python 3.8+
- Zerodha Kite API credentials (API Key & API Secret)
- AWS EC2 instance (t2.micro free tier)

## Quick Start

### 1. Clone Repository

```bash
git clone <your-repo-url>
cd algo-trading-platform
```

### 2. Backend Setup

```bash
cd backend
pip install -r requirements.txt

# Copy and configure environment variables
cp .env.example .env
nano .env  # Edit with your API keys
```

### 3. Configure Environment

Edit `.env` file:

```env
# Kite API Configuration
KITE_API_KEY=your_api_key_here
KITE_API_SECRET=your_api_secret_here

# Security (generate random string)
SECRET_KEY=your-secret-jwt-key-here

# Trading Configuration (adjust as needed)
CAPITAL_BASE=300000
DAILY_MAX_LOSS=-0.02
DAILY_MAX_PROFIT=0.04
```

### 4. Run Backend

```bash
# Development
python main.py

# Production (with Gunicorn)
gunicorn -w 2 -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:8000
```

### 5. Serve Frontend

```bash
cd ../frontend

# Simple HTTP server
python -m http.server 3000

# Or use nginx (recommended for production)
```

### 6. Access Dashboard

Open browser: `http://localhost:3000`

**Default Login:**
- Username: `admin`
- Password: `admin123`

**⚠️ Change credentials in production!**

## Kite Authentication Flow

1. Login to dashboard
2. Click "Setup Kite Auth"
3. Open Kite login URL
4. Login with Zerodha credentials
5. Copy request token from redirect URL
6. Paste token in dashboard
7. Access token generated automatically

## Deployment on AWS EC2

See detailed deployment guide: [`deployment/DEPLOYMENT.md`](deployment/DEPLOYMENT.md:1)

### Quick EC2 Setup

```bash
# 1. SSH to EC2
ssh -i your-key.pem ubuntu@your-ec2-ip

# 2. Install dependencies
sudo apt update
sudo apt install python3-pip nginx -y

# 3. Clone and setup
git clone <repo-url>
cd algo-trading-platform
./deployment/setup.sh

# 4. Start services
./deployment/start.sh
```

## Configuration

### Trading Parameters

Adjust via UI or `.env`:

- **CAPITAL_BASE**: Trading capital (₹)
- **MAX_CONCURRENT_POS**: Maximum open positions
- **DAILY_MAX_LOSS**: Daily loss limit (%)
- **DAILY_MAX_PROFIT**: Daily profit target (%)
- **LOT_QTY**: Lot size per trade
- **MIN_MINUTES_BETWEEN_ENTRIES**: Entry cooldown

### Risk Parameters

- **ATR_PERIOD**: ATR calculation period
- **TRAIL_START_PCT**: Trailing stop activation
- **TRAIL_GIVEBACK_PCT**: Trailing stop adjustment
- **MIN_VWAP_DISTANCE_PCT**: VWAP filter threshold

## API Documentation

Once running, access API docs:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Security Notes

1. **Change default admin password** in [`backend/auth.py`](backend/auth.py:1)
2. **Generate secure SECRET_KEY** for JWT
3. **Never commit** `.env` file to git
4. **Use HTTPS** in production (Let's Encrypt)
5. **Restrict CORS** to your domain
6. **Keep API keys secure** in environment variables

## Monitoring

### Dashboard Features

- Real-time P&L tracking
- Open positions monitoring
- Trade log history
- Notification alerts
- Emergency position close

### Logs

```bash
# Backend logs
tail -f backend.log

# Nginx logs (if using)
sudo tail -f /var/log/nginx/error.log
```

## Troubleshooting

### Issue: Kite authentication fails
- Verify API key and secret in `.env`
- Check redirect URL matches Kite app settings
- Ensure request token is fresh (expires quickly)

### Issue: Trading not starting
- Confirm Kite authentication is complete
- Check daily P&L limits not reached
- Verify market hours (9:30 AM - 3:20 PM)

### Issue: Backend crashes
- Check Python dependencies installed
- Review logs for error details
- Ensure sufficient EC2 resources

## Development

### Running Locally

```bash
# Terminal 1: Backend
cd backend
python main.py

# Terminal 2: Frontend
cd frontend
python -m http.server 3000
```

### Code Structure

- **Backend**: FastAPI REST API with async trading loop
- **Frontend**: Vanilla JS (no frameworks for simplicity)
- **Authentication**: JWT with Bearer tokens
- **Trading Logic**: Ported from [`v1.1.py`](v1.1.py:1) with enhancements

## Support

For issues and questions:
1. Check troubleshooting section
2. Review API documentation
3. Check logs for error details

## License

Proprietary - All rights reserved

## Disclaimer

This software is for educational purposes. Trading involves substantial risk. Use at your own discretion. The authors are not responsible for any financial losses.