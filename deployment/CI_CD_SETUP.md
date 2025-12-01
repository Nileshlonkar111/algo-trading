# CI/CD Pipeline Setup Guide

Automated deployment pipeline using GitHub Actions to deploy to EC2 on every push.

## Overview

When you push code to GitHub, it automatically:
1. Pulls latest code on EC2
2. Installs dependencies
3. Restarts services
4. Verifies deployment

## Setup Steps

### 1. Initial EC2 Setup (One-time)

First, set up your EC2 instance manually once:

```bash
# SSH to EC2
ssh -i your-key.pem ubuntu@your-ec2-ip

# Clone repository
cd /home/ubuntu
git clone https://github.com/your-username/algo-trading.git
cd algo-trading

# Run initial setup
./deployment/setup.sh

# Configure .env
nano backend/.env
# Add your KITE_API_KEY, KITE_API_SECRET, SECRET_KEY

# Restart
sudo supervisorctl restart algo-trading
```

### 2. Setup GitHub Secrets

Go to your GitHub repository → Settings → Secrets and variables → Actions → New repository secret

Add these secrets:

**EC2_HOST**
```
your-ec2-public-ip
# Example: 54.123.45.67
```

**EC2_USERNAME**
```
ubuntu
```

**EC2_SSH_KEY**
```
Paste your private key (.pem) content here
```

To get your SSH key content:
```bash
cat path/to/your-key.pem
```

Copy the entire content including:
```
-----BEGIN RSA PRIVATE KEY-----
...
-----END RSA PRIVATE KEY-----
```

### 3. Configure Git on EC2

On your EC2 instance:

```bash
cd /home/ubuntu/algo-trading

# Configure git
git config --global user.email "you@example.com"
git config --global user.name "Your Name"

# Set up SSH key for GitHub (if using private repo)
ssh-keygen -t rsa -b 4096 -C "your_email@example.com"
cat ~/.ssh/id_rsa.pub
# Add this to GitHub → Settings → SSH keys
```

### 4. Test Pipeline

Push a change to trigger deployment:

```bash
# Make a small change
echo "# Test" >> README.md

# Commit and push
git add .
git commit -m "Test CI/CD pipeline"
git push origin main
```

Go to GitHub → Actions tab → Watch deployment in real-time

### 5. Verify Deployment

After pipeline completes:

```bash
# SSH to EC2
ssh -i your-key.pem ubuntu@your-ec2-ip

# Check service status
sudo supervisorctl status algo-trading

# View logs
sudo tail -f /var/log/algo-trading/output.log
```

Visit your application: `http://your-ec2-ip`

## Pipeline Features

### Automatic Deployment
- Triggers on push to `main` or `master` branch
- Can also trigger manually from GitHub Actions tab

### What It Does
1. ✅ Pulls latest code from GitHub
2. ✅ Installs/updates Python dependencies
3. ✅ Restarts backend service
4. ✅ Reloads Nginx
5. ✅ Verifies service is running

### Deployment Time
~30-60 seconds per deployment

## Advanced: Environment Variables

To update environment variables:

**Option 1: Manually on EC2** (Recommended for secrets)
```bash
ssh -i your-key.pem ubuntu@your-ec2-ip
nano /home/ubuntu/algo-trading/backend/.env
sudo supervisorctl restart algo-trading
```

**Option 2: Add to GitHub Actions** (For non-sensitive configs)

Edit `.github/workflows/deploy.yml`:

```yaml
- name: Update environment
  run: |
    echo "CAPITAL_BASE=500000" >> backend/.env
```

## Monitoring Deployments

### GitHub Actions
- View deployment history: GitHub → Actions
- See logs and errors for each deployment
- Re-run failed deployments

### EC2 Logs
```bash
# Application logs
sudo tail -f /var/log/algo-trading/output.log
sudo tail -f /var/log/algo-trading/error.log

# Supervisor logs
sudo supervisorctl tail -f algo-trading

# Nginx logs
sudo tail -f /var/log/nginx/error.log
```

## Rollback Strategy

If deployment breaks:

### Option 1: Revert Git Commit
```bash
git revert HEAD
git push origin main
# Pipeline will auto-deploy previous version
```

### Option 2: Manual Rollback on EC2
```bash
ssh -i your-key.pem ubuntu@your-ec2-ip
cd /home/ubuntu/algo-trading
git log --oneline
git reset --hard <previous-commit-hash>
sudo supervisorctl restart algo-trading
```

## Troubleshooting

### Pipeline Fails
1. Check GitHub Actions logs for error details
2. Verify GitHub secrets are correct
3. Ensure EC2 is accessible (security groups)
4. Check SSH key permissions

### Service Won't Start After Deployment
```bash
# SSH to EC2
ssh -i your-key.pem ubuntu@your-ec2-ip

# Check logs
sudo supervisorctl tail -100 algo-trading

# Check configuration
cat backend/.env

# Restart manually
sudo supervisorctl restart algo-trading
```

### GitHub Can't Connect to EC2
- Verify EC2_HOST is the public IP
- Check EC2 security group allows SSH (port 22) from GitHub IPs
- Verify SSH key in secrets matches EC2 key pair

## Security Best Practices

1. **Never commit `.env` files** - Use GitHub Secrets
2. **Rotate SSH keys** regularly
3. **Use GitHub branch protection** - Require PR reviews before merge
4. **Monitor deployments** - Set up Slack/email notifications
5. **Backup before deploy** - Keep previous versions accessible

## Multi-Environment Setup (Optional)

For staging + production:

```yaml
# .github/workflows/deploy-staging.yml
on:
  push:
    branches: [develop]
# Deploy to staging EC2

# .github/workflows/deploy-production.yml
on:
  push:
    branches: [main]
# Deploy to production EC2
```

Add separate secrets:
- `STAGING_EC2_HOST`, `STAGING_EC2_SSH_KEY`
- `PROD_EC2_HOST`, `PROD_EC2_SSH_KEY`

## Cost Optimization

GitHub Actions free tier:
- 2,000 minutes/month for private repos
- Unlimited for public repos

Each deployment takes ~1 minute, so:
- Private repo: Up to 2,000 deployments/month
- Public repo: Unlimited deployments

## Next Steps

1. ✅ Set up GitHub secrets
2. ✅ Do initial EC2 setup
3. ✅ Test pipeline with dummy commit
4. ✅ Monitor first deployment
5. ✅ Document your specific setup notes

Your deployment pipeline is now ready! 🚀

Push to GitHub → Automatic deployment to EC2 → Application updated