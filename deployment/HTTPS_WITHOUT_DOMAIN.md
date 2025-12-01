# HTTPS Setup Without Domain - Quick Guide

Enable HTTPS on your EC2 using only IP address (no domain required).

**Note:** Browsers will show a security warning, but connection will be encrypted.

---

## Quick Setup (5 Minutes)

### Step 1: Generate Self-Signed Certificate

SSH to your EC2:
```bash
ssh -i your-key.pem ubuntu@your-ec2-ip
```

Create SSL certificate:
```bash
# Create directory
sudo mkdir -p /etc/nginx/ssl
cd /etc/nginx/ssl

# Generate certificate (replace YOUR_EC2_IP with actual IP)
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/selfsigned.key \
  -out /etc/nginx/ssl/selfsigned.crt \
  -subj "/C=IN/ST=Maharashtra/L=Mumbai/O=AlgoTrading/CN=YOUR_EC2_IP"

# Example:
# sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
#   -keyout /etc/nginx/ssl/selfsigned.key \
#   -out /etc/nginx/ssl/selfsigned.crt \
#   -subj "/C=IN/ST=Maharashtra/L=Mumbai/O=AlgoTrading/CN=13.232.156.78"
```

### Step 2: Configure Nginx for HTTPS

Backup existing config:
```bash
sudo cp /etc/nginx/sites-available/algo-trading /etc/nginx/sites-available/algo-trading.backup
```

Edit Nginx config:
```bash
sudo nano /etc/nginx/sites-available/algo-trading
```

Replace entire content with:
```nginx
# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name _;
    return 301 https://$host$request_uri;
}

# HTTPS Server
server {
    listen 443 ssl http2;
    server_name _;

    # SSL Certificate (Self-Signed)
    ssl_certificate /etc/nginx/ssl/selfsigned.crt;
    ssl_certificate_key /etc/nginx/ssl/selfsigned.key;

    # SSL Settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Frontend
    root /home/ubuntu/algo-trading/frontend;
    index index.html;

    # API Proxy
    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Frontend Routes
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

Save and exit (Ctrl+X, then Y, then Enter)

### Step 3: Update EC2 Security Group

Go to AWS Console:
```
EC2 → Security Groups → Your SG → Inbound Rules → Edit inbound rules

Add rule:
Type: HTTPS
Port: 443
Source: 0.0.0.0/0
Description: HTTPS access
```

### Step 4: Test and Restart Nginx

```bash
# Test configuration
sudo nginx -t

# If OK, restart
sudo systemctl restart nginx

# Check status
sudo systemctl status nginx
```

### Step 5: Access Your Application

**Browser:**
```
https://your-ec2-ip
```

**You'll see a security warning:**
- Chrome: "Your connection is not private" → Click "Advanced" → "Proceed to [IP]"
- Firefox: "Warning: Potential Security Risk" → Click "Advanced" → "Accept the Risk"
- Edge: "Your connection isn't private" → Click "Advanced" → "Continue to [IP]"

**This is normal** with self-signed certificates. Your data is still encrypted!

---

## Verification

### Test HTTPS is Working
```bash
# From local machine
curl -k https://your-ec2-ip

# Should return HTML content
```

### Check Certificate
```bash
# View certificate details
openssl s_client -connect your-ec2-ip:443 < /dev/null

# Should show:
# - Certificate details
# - Self-signed info
# - Cipher info
```

### Check Nginx Logs
```bash
# On EC2
sudo tail -f /var/log/nginx/error.log
sudo tail -f /var/log/nginx/access.log
```

---

## Accept Certificate Permanently (Optional)

### Chrome/Edge:
1. Visit `https://your-ec2-ip`
2. Click on "Not Secure" in address bar
3. Click "Certificate"
4. Go to "Details" tab → "Copy to File"
5. Install certificate in "Trusted Root Certification Authorities"

### Firefox:
1. Visit `https://your-ec2-ip`
2. Click "Advanced" → "Accept Risk and Continue"
3. Firefox will remember for this browser

### Windows (System-wide):
```powershell
# Download certificate from EC2
scp -i your-key.pem ubuntu@your-ec2-ip:/etc/nginx/ssl/selfsigned.crt ./

# Install (Run as Administrator)
certutil -addstore -enterprise -f "Root" selfsigned.crt
```

---

## Update Frontend API URL (If Needed)

If frontend is hardcoded to use `http://`, update it:

Edit [`frontend/app.js`](frontend/app.js:1):
```javascript
// Change this:
const API_BASE_URL = 'http://your-ec2-ip:8000';

// To this:
const API_BASE_URL = window.location.protocol + '//' + window.location.host + '/api';
// This auto-detects http/https
```

Then push changes:
```bash
git add .
git commit -m "Update API URL for HTTPS"
git push origin dev
```

---

## Troubleshooting

### "Connection Refused" on Port 443
```bash
# Check if nginx is listening
sudo netstat -tlnp | grep :443

# If not, check nginx status
sudo systemctl status nginx

# Check for errors
sudo nginx -t
```

### Certificate Error
```bash
# Regenerate certificate
cd /etc/nginx/ssl
sudo rm selfsigned.*
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout selfsigned.key \
  -out selfsigned.crt \
  -subj "/C=IN/ST=State/L=City/O=Org/CN=$(curl -s ifconfig.me)"

# Restart nginx
sudo systemctl restart nginx
```

### Can't Access via HTTPS
```bash
# Check security group allows 443
# Check nginx is running
sudo systemctl status nginx

# Check logs
sudo tail -50 /var/log/nginx/error.log
```

---

## Alternative: Use HTTP with SSH Tunnel (More Secure)

If you don't want browser warnings, use SSH tunnel:

**From your local machine:**
```bash
# Create SSH tunnel
ssh -i your-key.pem -L 8080:localhost:80 ubuntu@your-ec2-ip

# Keep this terminal open
# In browser, access: http://localhost:8080
```

Benefits:
- ✅ No certificate warnings
- ✅ Traffic encrypted via SSH
- ✅ Works on any port

Downside:
- ❌ Only works from your machine
- ❌ Need to keep SSH session open

---

## Cost

**Everything is FREE:**
- ✅ Self-signed certificate: FREE
- ✅ No domain needed: FREE
- ✅ No external services: FREE

---

## Security Notes

**Self-signed certificates provide:**
- ✅ **Encryption:** Data is encrypted in transit
- ✅ **Protection from eavesdropping:** HTTPS protocol
- ⚠️ **No third-party verification:** Browser can't verify identity

**For production trading:**
Consider getting:
1. Free domain from Freenom (free .tk domain)
2. Then use Let's Encrypt SSL (free, no warnings)

**Cost:** $0 but requires domain setup

---

## Complete Setup Script

Save this as `enable-https.sh` on EC2:
```bash
#!/bin/bash

# Generate certificate
sudo mkdir -p /etc/nginx/ssl
cd /etc/nginx/ssl
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout selfsigned.key \
  -out selfsigned.crt \
  -subj "/C=IN/ST=MH/L=Mumbai/O=AlgoTrading/CN=$(curl -s ifconfig.me)"

# Backup existing config
sudo cp /etc/nginx/sites-available/algo-trading /etc/nginx/sites-available/algo-trading.backup

# Create HTTPS config
sudo tee /etc/nginx/sites-available/algo-trading > /dev/null <<'EOF'
server {
    listen 80;
    server_name _;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name _;

    ssl_certificate /etc/nginx/ssl/selfsigned.crt;
    ssl_certificate_key /etc/nginx/ssl/selfsigned.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

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
sudo nginx -t && sudo systemctl restart nginx

echo "HTTPS enabled! Access: https://$(curl -s ifconfig.me)"
echo "Note: You'll see a security warning - this is normal with self-signed certificates"
```

**Run it:**
```bash
chmod +x enable-https.sh
./enable-https.sh
```

---

## Summary

✅ **What You Have Now:**
- HTTPS enabled (encrypted connection)
- Works with IP address only
- No domain required
- Completely free

⚠️ **Browser Warning:**
- Normal for self-signed certificates
- Can be bypassed/accepted
- Data is still encrypted

🔒 **Your application is now accessible via HTTPS!**

Access: `https://your-ec2-ip` (accept browser warning)