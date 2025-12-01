# HTTPS Setup Guide - Free SSL Certificate

Enable HTTPS for your algo trading application using free SSL from Let's Encrypt.

## Prerequisites

- Domain name pointing to your EC2 IP (e.g., `algotrading.yourdomain.com`)
- EC2 security group allowing HTTPS (port 443)

---

## Option 1: With Domain Name (Recommended)

### Step 1: Point Domain to EC2

Add an **A record** in your domain DNS:
```
Type: A
Name: algotrading (or @ for root domain)
Value: your-ec2-ip-address
TTL: 300
```

Wait 5-10 minutes for DNS propagation.

**Verify DNS:**
```bash
nslookup algotrading.yourdomain.com
# Should return your EC2 IP
```

### Step 2: Install Certbot

SSH to EC2 and run:
```bash
# Update system
sudo apt update

# Install Certbot
sudo apt install certbot python3-certbot-nginx -y
```

### Step 3: Get SSL Certificate

```bash
# Stop nginx temporarily
sudo systemctl stop nginx

# Get certificate (replace with your domain)
sudo certbot certonly --standalone -d algotrading.yourdomain.com

# Follow prompts:
# - Enter email address
# - Agree to terms (Y)
# - Share email (N is fine)
```

**Certificate Location:**
```
Certificate: /etc/letsencrypt/live/algotrading.yourdomain.com/fullchain.pem
Private Key: /etc/letsencrypt/live/algotrading.yourdomain.com/privkey.pem
```

### Step 4: Configure Nginx for HTTPS

Create SSL Nginx config:
```bash
sudo nano /etc/nginx/sites-available/algo-trading-ssl
```

Paste this configuration:
```nginx
# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name algotrading.yourdomain.com;
    return 301 https://$server_name$request_uri;
}

# HTTPS Server
server {
    listen 443 ssl http2;
    server_name algotrading.yourdomain.com;

    # SSL Configuration
    ssl_certificate /etc/letsencrypt/live/algotrading.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/algotrading.yourdomain.com/privkey.pem;
    
    # SSL Settings (Mozilla Intermediate Configuration)
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;

    # Frontend (Static Files)
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

**Enable the config:**
```bash
# Remove old config
sudo rm /etc/nginx/sites-enabled/default

# Enable SSL config
sudo ln -s /etc/nginx/sites-available/algo-trading-ssl /etc/nginx/sites-enabled/

# Test configuration
sudo nginx -t

# Restart nginx
sudo systemctl restart nginx
```

### Step 5: Update EC2 Security Group

Add HTTPS rule in AWS Console:
```
EC2 → Security Groups → Your SG → Inbound Rules → Add Rule

Type: HTTPS
Port: 443
Source: 0.0.0.0/0
Description: HTTPS access
```

### Step 6: Test HTTPS

```bash
# Test from local machine
curl https://algotrading.yourdomain.com

# Should load without SSL errors
```

Visit: `https://algotrading.yourdomain.com`

### Step 7: Auto-Renewal Setup

Certbot auto-renewal is already configured. Test it:
```bash
# Test renewal (dry run)
sudo certbot renew --dry-run

# Should show: Congratulations, all renewals succeeded
```

Certificates auto-renew every 60 days.

---

## Option 2: Without Domain (Self-Signed Certificate)

⚠️ **Warning:** Browsers will show "Not Secure" warning. Only for testing!

### Generate Self-Signed Certificate

```bash
# Create SSL directory
sudo mkdir -p /etc/nginx/ssl

# Generate certificate (valid 365 days)
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/nginx-selfsigned.key \
  -out /etc/nginx/ssl/nginx-selfsigned.crt \
  -subj "/C=IN/ST=State/L=City/O=Organization/CN=your-ec2-ip"
```

### Configure Nginx

```bash
sudo nano /etc/nginx/sites-available/algo-trading-ssl
```

```nginx
server {
    listen 443 ssl http2;
    server_name _;

    ssl_certificate /etc/nginx/ssl/nginx-selfsigned.crt;
    ssl_certificate_key /etc/nginx/ssl/nginx-selfsigned.key;

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

server {
    listen 80;
    return 301 https://$host$request_uri;
}
```

Enable and restart:
```bash
sudo ln -s /etc/nginx/sites-available/algo-trading-ssl /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

Access: `https://your-ec2-ip` (accept browser warning)

---

## Option 3: Using Cloudflare (Free & Easy)

1. **Add domain to Cloudflare** (free account)
2. **Update nameservers** at your domain registrar
3. **Enable "Full" SSL mode** in Cloudflare SSL/TLS settings
4. **Create A record** pointing to EC2 IP
5. **Enable "Always Use HTTPS"** in Cloudflare SSL/TLS → Edge Certificates

Cloudflare handles SSL automatically. Your EC2 can use HTTP internally.

**Nginx config for Cloudflare:**
```nginx
server {
    listen 80;
    server_name algotrading.yourdomain.com;

    root /home/ubuntu/algo-trading/frontend;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

---

## Verification Checklist

✅ **HTTPS Working:**
- Visit `https://yourdomain.com` - Shows padlock icon
- No SSL errors or warnings
- HTTP redirects to HTTPS
- API calls work through HTTPS

✅ **SSL Certificate Valid:**
```bash
# Check certificate
openssl s_client -connect yourdomain.com:443 -servername yourdomain.com < /dev/null

# Should show:
# - Valid certificate
# - No errors
# - Verification: OK
```

✅ **Security Headers:**
```bash
curl -I https://yourdomain.com

# Should include:
# Strict-Transport-Security: max-age=31536000
# X-Frame-Options: SAMEORIGIN
# X-Content-Type-Options: nosniff
```

---

## Troubleshooting

### Certificate Not Found
```bash
# List certificates
sudo certbot certificates

# Reinstall if missing
sudo certbot certonly --standalone -d yourdomain.com
```

### Nginx Won't Start
```bash
# Check config
sudo nginx -t

# Check certificate paths
sudo ls -la /etc/letsencrypt/live/yourdomain.com/
```

### Port 443 Blocked
```bash
# Check if nginx is listening
sudo netstat -tlnp | grep :443

# Check firewall
sudo ufw status

# If active, allow HTTPS
sudo ufw allow 443/tcp
```

### Auto-Renewal Not Working
```bash
# Check renewal timer
sudo systemctl status certbot.timer

# Enable if disabled
sudo systemctl enable certbot.timer
sudo systemctl start certbot.timer
```

---

## Best Practices

1. ✅ **Always use HTTPS in production**
2. ✅ **Enable HSTS** (Strict-Transport-Security header)
3. ✅ **Use Let's Encrypt** for free certificates
4. ✅ **Set up auto-renewal** (done by default)
5. ✅ **Keep certificates updated** (certbot handles this)
6. ✅ **Use strong SSL ciphers** (configured above)

---

## Cost

**Option 1 (Let's Encrypt):** FREE ✅
**Option 2 (Self-Signed):** FREE (but shows warnings)
**Option 3 (Cloudflare):** FREE ✅

---

## Summary

### Recommended for Production:
1. Get a domain name ($10-15/year)
2. Use Let's Encrypt (FREE SSL)
3. Auto-renewal configured
4. Full HTTPS security

### Quick Setup (5 minutes):
Use Cloudflare - handles everything automatically!

Your application will be secure with HTTPS! 🔒