# GitHub Secrets Setup - Exact Format

## Where to Add Secrets

1. Go to your GitHub repository
2. Click **Settings** (top menu)
3. In left sidebar, click **Secrets and variables** → **Actions**
4. Click **New repository secret** button

---

## Secret 1: EC2_HOST

**Name:** `EC2_HOST`

**Value Format:** Just the IP address (no protocol, no port)
```
54.123.45.67
```

**Example:**
```
13.232.156.78
```

**Where to find:** AWS EC2 Console → Instances → Your instance → Public IPv4 address

---

## Secret 2: EC2_USERNAME

**Name:** `EC2_USERNAME`

**Value Format:** Just the username
```
ubuntu
```

**Common values:**
- Ubuntu AMI: `ubuntu`
- Amazon Linux: `ec2-user`
- CentOS: `centos`

**For this project:** Always use `ubuntu`

---

## Secret 3: EC2_SSH_KEY

**Name:** `EC2_SSH_KEY`

**Value Format:** Complete private key content including headers

### How to Get Your Key Content

**If you have .pem file:**

Windows:
```powershell
Get-Content "C:\path\to\your-key.pem" -Raw
```

Linux/Mac:
```bash
cat /path/to/your-key.pem
```

**If you have .ppk file (PuTTY format):**

You need to convert PPK to PEM format first:

**Method 1: Using PuTTYgen (Windows)**
1. Open **PuTTYgen** (comes with PuTTY)
2. Click **Load** and select your `.ppk` file
3. Go to **Conversions** menu → **Export OpenSSH key**
4. Save as `your-key.pem` (without passphrase)
5. Open the saved `.pem` file in Notepad
6. Copy entire content

**Method 2: Using Command Line**
```bash
# Install puttygen if not already installed
# Ubuntu/Debian:
sudo apt-get install putty-tools

# Convert PPK to PEM
puttygen your-key.ppk -O private-openssh -o your-key.pem

# View the PEM content
cat your-key.pem
```

**Method 3: Using Online Tool (Not Recommended for Production)**
- Use https://www.puttygen.com/ (client-side conversion)
- Upload PPK → Download as OpenSSH format

### Exact Format to Copy-Paste

Copy **EVERYTHING** from the .pem file, including:

```
-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEAyourprivatekeycontenthere...
(multiple lines of base64 encoded key)
...endswithaverylongstringofcharacters
-----END RSA PRIVATE KEY-----
```

**Important:**
- ✅ Include `-----BEGIN RSA PRIVATE KEY-----`
- ✅ Include all middle lines (don't skip any)
- ✅ Include `-----END RSA PRIVATE KEY-----`
- ✅ Maintain line breaks exactly as they are
- ❌ Don't add extra spaces or lines
- ❌ Don't remove line breaks

### Alternative Key Formats

If your key starts differently, copy that format:

**For newer EC2 keys:**
```
-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAA...
-----END OPENSSH PRIVATE KEY-----
```

**For EC2 keys (another format):**
```
-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKc...
-----END PRIVATE KEY-----
```

---

## Complete Example

Here's what it looks like when properly configured:

### Secret #1
```
Name: EC2_HOST
Value: 13.232.156.78
```

### Secret #2
```
Name: EC2_USERNAME
Value: ubuntu
```

### Secret #3
```
Name: EC2_SSH_KEY
Value: 
-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEAwXYZ9TpkKq3VJxR5VvYL7fG2MpQWK6hT9rYnC3eD4fE5gH6i
J7kL8mN9oP0qR1sT2uV3wX4yZ5aB6cD7eF8gH9iJ0kL1mN2oP3qR4sT5uV6wX7y
... (many more lines) ...
Z8aB9cD0eF1gH2iJ3kL4mN5oP6qR7sT8uV9wX0yZ1aB2cD3eF4gH5iJ6kL7mN8o
-----END RSA PRIVATE KEY-----
```

---

## Verification

After adding all three secrets, you should see:

```
Repository secrets (3)

EC2_HOST                Updated 2 minutes ago
EC2_SSH_KEY            Updated 1 minute ago  
EC2_USERNAME           Updated 3 minutes ago
```

**Note:** GitHub will never show the secret values after saving (for security).

---

## Common Mistakes to Avoid

❌ **Wrong EC2_HOST format:**
```
http://54.123.45.67        ← NO (has protocol)
54.123.45.67:22           ← NO (has port)
ubuntu@54.123.45.67       ← NO (has username)
ec2-54-123-45-67.compute.amazonaws.com  ← Use IP instead
```

✅ **Correct EC2_HOST:**
```
54.123.45.67              ← YES (just IP)
```

---

❌ **Wrong EC2_SSH_KEY format:**
```
MIIEpAIBAAKCAQEAwXYZ...  ← NO (missing headers)
```
```
-----BEGIN RSA PRIVATE KEY-----MIIEpA...  ← NO (no line breaks)
```

✅ **Correct EC2_SSH_KEY:**
```
-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEAwXYZ...
(proper line breaks)
-----END RSA PRIVATE KEY-----
```

---

## Testing Your Secrets

After adding secrets, push any change to trigger the pipeline:

```bash
git add .
git commit -m "Test CI/CD"
git push origin main
```

Go to GitHub → Actions tab → Watch the deployment

If it fails:
1. Check the error message in Actions logs
2. Verify secret names match exactly (case-sensitive)
3. Verify SSH key includes headers and line breaks
4. Verify EC2 security group allows SSH from anywhere (0.0.0.0/0)

---

## Security Notes

✅ **Good practices:**
- Secrets are encrypted by GitHub
- Never log or print secrets
- Rotate SSH keys regularly
- Use branch protection rules

❌ **Don't:**
- Share secrets in commits
- Store secrets in `.env` files in git
- Use same SSH key for multiple projects

---

## Quick Copy Template

Use this template when adding secrets:

**Secret 1:**
- Name: `EC2_HOST`
- Value: `[paste your EC2 IP here]`

**Secret 2:**
- Name: `EC2_USERNAME`
- Value: `ubuntu`

**Secret 3:**
- Name: `EC2_SSH_KEY`
- Value: `[paste entire .pem file content here - convert .ppk to .pem first if needed]`

Done! Your CI/CD pipeline is ready.

---

## PPK to PEM Conversion - Step by Step

If you only have a `.ppk` file, follow these steps:

### Windows Users (Easiest Method):

1. **Download PuTTYgen** (if not installed):
   - Go to https://www.chiark.greenend.org.uk/~sgtatham/putty/latest.html
   - Download `puttygen.exe`

2. **Convert PPK to PEM**:
   ```
   a. Run PuTTYgen.exe
   b. Click "Load" button
   c. Select your .ppk file (change file filter to "All Files" if needed)
   d. Click "Conversions" menu → "Export OpenSSH key"
   e. Save as "your-key.pem" (without passphrase)
   f. Click "Yes" when asked about saving without passphrase
   ```

3. **Get the content**:
   ```powershell
   # Open in Notepad
   notepad your-key.pem
   
   # Or get content via PowerShell
   Get-Content your-key.pem -Raw
   ```

4. **Copy everything** from the file and paste into EC2_SSH_KEY secret

### Linux/Mac Users:

```bash
# Install putty-tools
sudo apt-get install putty-tools  # Ubuntu/Debian
brew install putty               # macOS

# Convert PPK to PEM
puttygen your-key.ppk -O private-openssh -o your-key.pem

# View content
cat your-key.pem

# Copy output and paste into EC2_SSH_KEY secret
```

### Verify Conversion:

After conversion, your `.pem` file should look like:
```
-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAABlwAAAAdzc2gtcn
... (many lines)
AAAAC3VidW50dUBob21lAQIDBA==
-----END OPENSSH PRIVATE KEY-----
```

**Important**: Make sure there's NO passphrase on the exported key!