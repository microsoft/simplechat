# HTTPS Setup for SimpleChat

This guide explains how to configure SimpleChat to run with HTTPS/SSL encryption.

## Quick Start (Development)

The easiest way to enable HTTPS for development is to use Flask's built-in adhoc SSL:

1. **Update your settings** (through admin interface or database):
   ```json
   {
     "enable_https": true,
     "use_adhoc_ssl": true,
     "https_port": 5443
   }
   ```

2. **Install pyOpenSSL** (required for adhoc SSL):
   ```bash
   pip install pyOpenSSL
   ```

3. **Start the app**:
   ```bash
   python app.py
   ```

4. **Access your app** at: https://localhost:5443
   (You'll need to accept the browser security warning for self-signed certificates)

## Production Setup Options

### Option 1: Using Certificate Files

If you have SSL certificate files (from Let's Encrypt, your organization, etc.):

1. **Place your certificate files** in the application directory
2. **Update settings**:
   ```json
   {
     "enable_https": true,
     "ssl_cert_path": "/path/to/your/certificate.crt",
     "ssl_key_path": "/path/to/your/private.key",
     "https_port": 443
   }
   ```

### Option 2: Using Base64 Encoded Certificates

For cloud deployments where you can't store files:

1. **Encode your certificates**:
   ```bash
   # Encode certificate
   base64 -w 0 certificate.crt > cert.b64
   
   # Encode private key
   base64 -w 0 private.key > key.b64
   ```

2. **Update settings**:
   ```json
   {
     "enable_https": true,
     "ssl_cert_base64": "LS0tLS1CRUdJTi...",
     "ssl_key_base64": "LS0tLS1CRUdJTi...",
     "https_port": 443
   }
   ```

### Option 3: Using a Reverse Proxy (Recommended for Production)

For production environments, it's often better to use a reverse proxy like nginx:

1. **Keep SimpleChat on HTTP** (default configuration)
2. **Configure nginx** to handle SSL and proxy to SimpleChat:

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;
    
    ssl_certificate /path/to/certificate.crt;
    ssl_certificate_key /path/to/private.key;
    
    # Modern SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512;
    ssl_prefer_server_ciphers off;
    
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Generating Self-Signed Certificates

### Method 1: Using PowerShell (Windows)

Run the provided PowerShell script:

```powershell
# For adhoc SSL (easiest)
.\setup-https.ps1 -UseAdhoc

# To generate certificate files
.\setup-https.ps1 -SelfSigned

# To use existing certificates
.\setup-https.ps1 -CertPath "cert.pem" -KeyPath "key.pem"
```

### Method 2: Using Python Script

```bash
python generate_ssl_certs.py
```

### Method 3: Using OpenSSL

```bash
# Generate private key
openssl genrsa -out server.key 2048

# Generate certificate
openssl req -new -x509 -key server.key -out server.crt -days 365 \
  -subj "/C=US/ST=State/L=City/O=Organization/CN=localhost"
```

## Configuration Reference

All HTTPS-related settings that can be added to your SimpleChat configuration:

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `enable_https` | boolean | `false` | Enable HTTPS mode |
| `https_port` | integer | `5443` | Port to use for HTTPS |
| `ssl_cert_path` | string | `""` | Path to SSL certificate file |
| `ssl_key_path` | string | `""` | Path to SSL private key file |
| `ssl_cert_base64` | string | `""` | Base64 encoded SSL certificate |
| `ssl_key_base64` | string | `""` | Base64 encoded SSL private key |
| `use_adhoc_ssl` | boolean | `false` | Use Flask's adhoc SSL (development only) |

## Security Considerations

### Development vs Production

- **Development**: Use `use_adhoc_ssl: true` for quick setup
- **Production**: Use certificates from a trusted CA or a reverse proxy

### Self-Signed Certificates

Self-signed certificates provide encryption but no identity verification:
- ✅ Traffic is encrypted
- ❌ Browsers will show security warnings
- ❌ No protection against man-in-the-middle attacks

### Certificate Management

- **Renewal**: Monitor certificate expiration dates
- **Storage**: Keep private keys secure and never commit them to version control
- **Permissions**: Ensure certificate files have appropriate file permissions

## Troubleshooting

### Common Issues

1. **"SSL: CERTIFICATE_VERIFY_FAILED"**
   - This is normal for self-signed certificates
   - Accept the browser warning or add the certificate to your trusted store

2. **"Port already in use"**
   - Change the `https_port` setting
   - Check if another application is using the port

3. **"Permission denied"**
   - On Linux/Mac, ports below 1024 require root privileges
   - Use a port above 1024 or run with sudo (not recommended)

4. **"Certificate file not found"**
   - Check the file paths in your configuration
   - Ensure the application has read permissions

### Dependencies

For adhoc SSL, you need:
```bash
pip install pyOpenSSL
```

For the certificate generation script:
```bash
pip install cryptography
```

## Testing Your HTTPS Setup

1. **Start the application**
2. **Check the startup logs** for SSL confirmation
3. **Access via browser**: https://localhost:5443
4. **Verify encryption**: Look for the lock icon in your browser

### Using curl

```bash
# Test with self-signed certificate (ignore SSL errors)
curl -k https://localhost:5443

# Test with valid certificate
curl https://localhost:5443
```

## Examples

### Development Setup

```python
# In your settings or environment
settings = {
    "enable_https": True,
    "use_adhoc_ssl": True,
    "https_port": 5443
}
```

### Production with Let's Encrypt

```python
settings = {
    "enable_https": True,
    "ssl_cert_path": "/etc/letsencrypt/live/yourdomain.com/fullchain.pem",
    "ssl_key_path": "/etc/letsencrypt/live/yourdomain.com/privkey.pem",
    "https_port": 443
}
```

### Cloud Deployment with Base64

```python
settings = {
    "enable_https": True,
    "ssl_cert_base64": "LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0t...",
    "ssl_key_base64": "LS0tLS1CRUdJTiBQUklWQVRFIEtFWS0tLS0t...",
    "https_port": 443
}
```

## Support

If you encounter issues:
1. Check the application logs for SSL-related errors
2. Verify your certificate files are valid
3. Ensure all required dependencies are installed
4. Consider using the reverse proxy approach for production deployments
