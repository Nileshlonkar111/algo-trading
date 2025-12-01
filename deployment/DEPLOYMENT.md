# Production Deployment Guide

Complete guide for deploying the Algo Trading Platform on AWS EC2 free tier.

## Prerequisites

- AWS account with EC2 free tier access
- SSH key pair for EC2 access
- Domain name (optional, for HTTPS)
- Zerodha Kite API credentials

## EC2 Instance Setup

### 1. Launch EC2 Instance

**Instance Configuration:**
- **AMI**: Ubuntu Server 22.04 LTS (Free tier eligible)
- **Instance Type**: t2.micro (1 vCPU, 1 GB RAM)
- **Storage**: 8-30 GB GP2
- **Security Group**: Configure as below

**Security Group Rules:**

| Type | Protocol | Port | Source | Description |
|------|----------|------|--------|-------------|
| SSH | TCP | 22 | Your IP | SSH access |
| HTTP | TCP | 80 | 0.0.0.0/0 | Web access |
| HTTPS | TCP | 443 | 0.0.0.0/0 | Secure web |
| Custom | TCP | 8000 | 0.0.0.0/0 | API (temp) |

### 2. Connect to Instance

```bash
ssh -i your-key.pem ubuntu@your-ec2-public-ip
```

### 3. System Update

```bash
sudo apt update && sudo apt upgrade -y
```

## Application Deployment

### 1. Install Dependencies

```bash
# Python and pip
sudo apt install python3-pip python3-venv -y

# Nginx
sudo apt install nginx -y

# Git
sudo apt install git -y

# Supervisor (process manager)
sudo apt install supervisor -y
```

### 2. Clone Repository

```bash
cd /home/ubuntu
git clone <your-repo-url> algo-trading
cd algo-trading
```

### 3. Setup Python Environment

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn  # Production server
```

### 4. Configure Environment

```bash
cp .env.example .env
nano .env
```

**Required Configuration:**

```env
KITE_API_KEY=your_api_key
KITE_API_SECRET=your_api_secret
SECRET_KEY=generate-strong-random-key-here
CAPITAL_BASE=300000
DAILY_MAX_LOSS=-0.02
DAILY_MAX_PROFIT=0.04
HOST=0.0.0.0
PORT=8000
```

**Generate Secret Key:**

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 5. Test Backend

```bash
source venv/bin/activate
python main.py
```

Press `Ctrl+C` after confirming it works.

## Production Configuration

### 1. Supervisor Configuration

Create backend service config:

```bash
sudo nano /etc/supervisor/conf.d/algo-trading.conf
```

Add:

```ini
[program:algo-trading]
directory=/home/ubuntu/algo-trading/backend
command=/home/ubuntu/algo-trading/backend/venv/bin/gunicorn -w 2 -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:8000
user=ubuntu
autostart=true
autorestart=true
stderr_logfile=/var/log/algo-trading.err.log
stdout_logfile=/var/log/algo-trading.out.log
environment=PATH="/home/ubuntu/algo-trading/backend/venv/bin"
```

Update and start:

```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start algo-trading
sudo supervisorctl status
```

### 2. Nginx Configuration

```bash
sudo nano /etc/nginx/sites-available/algo-trading
```

Add:

```nginx
server {
    listen 80;
    server_name your-ec2-public-ip;  # Or your domain

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

    # WebSocket support (if needed)
    location /ws {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

Enable and restart:

```bash
sudo ln -s /etc/nginx/sites-available/algo-trading /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### 3. Update Frontend API URL

```bash
nano /home/ubuntu/algo-trading/frontend/app.js
```

Change:

```javascript
const API_BASE_URL = 'http://your-ec2-public-ip/api';
```

## SSL/HTTPS Setup (Optional but Recommended)

### Using Let's Encrypt (Free)

```bash
# Install Certbot
sudo apt install certbot python3-certbot-nginx -y

# Obtain certificate (requires domain name)
sudo certbot --nginx -d your-domain.com

# Auto-renewal
sudo certbot renew --dry-run
```

Update nginx config to redirect HTTP to HTTPS:

```nginx
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl;
    server_name your-domain.com;
    
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    
    # ... rest of config
}
```

## Firewall Configuration

```bash
# Enable UFW
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable

# Check status
sudo ufw status
```

## Monitoring & Maintenance

### Check Service Status

```bash
# Supervisor
sudo supervisorctl status algo-trading

# Nginx
sudo systemctl status nginx

# View logs
sudo tail -f /var/log/algo-trading.out.log
sudo tail -f /var/log/algo-trading.err.log
sudo tail -f /var/log/nginx/error.log
```

### Restart Services

```bash
# Backend
sudo supervisorctl restart algo-trading

# Nginx
sudo systemctl restart nginx
```

### Update Application

```bash
cd /home/ubuntu/algo-trading
git pull origin main

# Update backend
cd backend
source venv/bin/activate
pip install -r requirements.txt
sudo supervisorctl restart algo-trading

# Update frontend (already updated via git pull)
```

## Resource Optimization for Free Tier

### 1. Reduce Worker Processes

In supervisor config, use only 2 workers:

```ini
command=... gunicorn -w 2 ...
```

### 2. Enable Swap (if needed)

```bash
sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 3. Monitor Resources

```bash
# Check memory
free -h

# Check CPU
top

# Check disk
df -h
```

## Security Checklist

- [ ] Change default admin password in `backend/auth.py`
- [ ] Use strong SECRET_KEY in `.env`
- [ ] Never commit `.env` to git
- [ ] Configure firewall (UFW)
- [ ] Enable HTTPS with SSL certificate
- [ ] Restrict CORS to your domain in `backend/main.py`
- [ ] Keep API keys secure
- [ ] Regular system updates: `sudo apt update && sudo apt upgrade`
- [ ] Monitor logs for suspicious activity

## Backup Strategy

### Database/Logs Backup

```bash
# Create backup script
nano /home/ubuntu/backup.sh
```

```bash
#!/bin/bash
BACKUP_DIR="/home/ubuntu/backups"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# Backup logs
cp /var/log/algo-trading.out.log $BACKUP_DIR/trading_$DATE.log

# Backup trade logs (if CSV)
cp /home/ubuntu/algo-trading/backend/trades_log.csv $BACKUP_DIR/trades_$DATE.csv

echo "Backup completed: $DATE"
```

```bash
chmod +x /home/ubuntu/backup.sh

# Add to crontab (daily at midnight)
crontab -e
# Add: 0 0 * * * /home/ubuntu/backup.sh
```

## Troubleshooting

### Issue: Service won't start

```bash
# Check logs
sudo supervisorctl tail -f algo-trading

# Check port availability
sudo netstat -tulpn | grep 8000

# Restart service
sudo supervisorctl restart algo-trading
```

### Issue: High memory usage

```bash
# Reduce Gunicorn workers to 1
# Edit supervisor config and restart
```

### Issue: Nginx errors

```bash
# Test config
sudo nginx -t

# Check logs
sudo tail -f /var/log/nginx/error.log
```

### Issue: Can't access dashboard

```bash
# Check security group allows port 80
# Check nginx is running
sudo systemctl status nginx

# Check frontend files exist
ls /home/ubuntu/algo-trading/frontend/
```

## Post-Deployment Checklist

- [ ] Backend accessible via API
- [ ] Frontend loads in browser
- [ ] Login works with credentials
- [ ] Kite authentication flow works
- [ ] Trading configuration updates
- [ ] Notifications display correctly
- [ ] Emergency stop works
- [ ] Logs are being written
- [ ] Auto-restart on crash works
- [ ] HTTPS enabled (if applicable)

## Maintenance Schedule

**Daily:**
- Check logs for errors
- Monitor P&L and positions
- Verify Kite token status

**Weekly:**
- Review system resources
- Check for application updates
- Backup trade logs

**Monthly:**
- System security updates
- Review and rotate logs
- Test disaster recovery

## Support

For deployment issues:
1. Check logs first
2. Verify all services running
3. Test connectivity
4. Review security groups
5. Check resource usage

## Cost Estimation

**AWS Free Tier (12 months):**
- EC2 t2.micro: Free (750 hours/month)
- 30 GB storage: Free
- Data transfer: 15 GB/month free

**After Free Tier:**
- ~$8-10/month for t2.micro instance
- Consider reserved instances for savings

## Scaling Beyond Free Tier

If you need more resources:
1. **Upgrade Instance**: t2.small or t3.small
2. **Add Database**: RDS or managed database
3. **Load Balancer**: For high availability
4. **Auto Scaling**: For traffic spikes
5. **CloudWatch**: Enhanced monitoring