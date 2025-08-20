#!/usr/bin/env python3
"""
SSL Certificate Generation Script for SimpleChat

This script generates self-signed SSL certificates for development use.
For production, you should use certificates from a trusted Certificate Authority.
"""

import ssl
import socket
import subprocess
import sys
import os
from pathlib import Path

def generate_self_signed_cert(cert_file="server.crt", key_file="server.key", days=365):
    """
    Generate a self-signed SSL certificate using OpenSSL
    """
    try:
        # Check if OpenSSL is available
        subprocess.run(["openssl", "version"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("ERROR: OpenSSL is not installed or not in PATH")
        print("Please install OpenSSL first:")
        print("- Windows: Download from https://slproweb.com/products/Win32OpenSSL.html")
        print("- Or use Windows Subsystem for Linux (WSL)")
        print("- Or use Chocolatey: choco install openssl")
        return False
    
    # Get the current directory
    current_dir = Path(__file__).parent
    cert_path = current_dir / cert_file
    key_path = current_dir / key_file
    
    # Generate private key
    print(f"Generating private key: {key_path}")
    subprocess.run([
        "openssl", "genrsa", 
        "-out", str(key_path), 
        "2048"
    ], check=True)
    
    # Generate certificate
    print(f"Generating certificate: {cert_path}")
    subprocess.run([
        "openssl", "req", 
        "-new", "-x509", 
        "-key", str(key_path),
        "-out", str(cert_path),
        "-days", str(days),
        "-subj", "/C=US/ST=State/L=City/O=Organization/CN=localhost"
    ], check=True)
    
    print(f"\nSSL certificate generated successfully!")
    print(f"Certificate: {cert_path}")
    print(f"Private Key: {key_path}")
    print(f"Valid for: {days} days")
    print("\nTo use these certificates, update your settings:")
    print(f"  'enable_https': True,")
    print(f"  'ssl_cert_path': '{cert_path}',")
    print(f"  'ssl_key_path': '{key_path}',")
    
    return True

def generate_with_python_only(cert_file="server.crt", key_file="server.key"):
    """
    Generate a self-signed certificate using Python's cryptography library
    This method doesn't require OpenSSL to be installed separately
    """
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime
    except ImportError:
        print("ERROR: cryptography library not installed")
        print("Install it with: pip install cryptography")
        return False
    
    # Get the current directory
    current_dir = Path(__file__).parent
    cert_path = current_dir / cert_file
    key_path = current_dir / key_file
    
    # Generate private key
    print("Generating private key...")
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    
    # Generate certificate
    print("Generating certificate...")
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "State"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "City"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SimpleChat"),
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])
    
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow()
    ).not_valid_after(
        datetime.datetime.utcnow() + datetime.timedelta(days=365)
    ).add_extension(
        x509.SubjectAlternativeName([
            x509.DNSName("localhost"),
            x509.DNSName("127.0.0.1"),
            x509.IPAddress(socket.inet_aton("127.0.0.1")),
        ]),
        critical=False,
    ).sign(private_key, hashes.SHA256())
    
    # Write private key
    print(f"Writing private key: {key_path}")
    with open(key_path, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ))
    
    # Write certificate
    print(f"Writing certificate: {cert_path}")
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    
    print(f"\nSSL certificate generated successfully!")
    print(f"Certificate: {cert_path}")
    print(f"Private Key: {key_path}")
    print(f"Valid for: 365 days")
    print("\nTo use these certificates, update your settings:")
    print(f"  'enable_https': True,")
    print(f"  'ssl_cert_path': '{cert_path}',")
    print(f"  'ssl_key_path': '{key_path}',")
    
    return True

def main():
    print("SimpleChat SSL Certificate Generator")
    print("=" * 40)
    
    # Try Python method first (doesn't require OpenSSL installation)
    if generate_with_python_only():
        return
    
    # Fall back to OpenSSL method
    print("\nFalling back to OpenSSL method...")
    if not generate_self_signed_cert():
        print("\nFailed to generate certificates with both methods")
        sys.exit(1)

if __name__ == "__main__":
    main()
