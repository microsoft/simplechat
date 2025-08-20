# PowerShell script to set up HTTPS for SimpleChat
# Run this script with Administrator privileges for best results

param(
    [Parameter(Mandatory=$false)]
    [string]$CertPath = "",
    
    [Parameter(Mandatory=$false)]
    [string]$KeyPath = "",
    
    [Parameter(Mandatory=$false)]
    [switch]$SelfSigned = $false,
    
    [Parameter(Mandatory=$false)]
    [switch]$UseAdhoc = $false
)

Write-Host "SimpleChat HTTPS Setup Script" -ForegroundColor Cyan
Write-Host "==============================" -ForegroundColor Cyan

# Function to generate self-signed certificate using PowerShell
function New-SelfSignedCertificateForSimpleChat {
    param(
        [string]$CertName = "localhost",
        [string]$OutputPath = "."
    )
    
    try {
        Write-Host "Generating self-signed certificate..." -ForegroundColor Yellow
        
        # Create self-signed certificate
        $cert = New-SelfSignedCertificate -DnsName $CertName -CertStoreLocation "cert:\LocalMachine\My" -NotAfter (Get-Date).AddYears(1)
        
        # Export certificate
        $certPath = Join-Path $OutputPath "server.crt"
        $keyPath = Join-Path $OutputPath "server.key"
        $pfxPath = Join-Path $OutputPath "server.pfx"
        
        # Generate a password for the PFX
        $password = ConvertTo-SecureString -String "simplechat123" -Force -AsPlainText
        
        # Export to PFX first
        Export-PfxCertificate -Cert $cert -FilePath $pfxPath -Password $password | Out-Null
        
        # Convert PFX to PEM format using OpenSSL (if available)
        if (Get-Command openssl -ErrorAction SilentlyContinue) {
            Write-Host "Converting certificate to PEM format..." -ForegroundColor Yellow
            
            # Extract certificate
            & openssl pkcs12 -in $pfxPath -clcerts -nokeys -out $certPath -passin pass:simplechat123
            
            # Extract private key
            & openssl pkcs12 -in $pfxPath -nocerts -nodes -out $keyPath -passin pass:simplechat123
            
            Write-Host "Certificate files generated:" -ForegroundColor Green
            Write-Host "  Certificate: $certPath" -ForegroundColor Green
            Write-Host "  Private Key: $keyPath" -ForegroundColor Green
            
            # Clean up PFX file
            Remove-Item $pfxPath -Force
            
            return @{
                CertPath = $certPath
                KeyPath = $keyPath
                Success = $true
            }
        }
        else {
            Write-Host "OpenSSL not found. Certificate created in Windows Certificate Store only." -ForegroundColor Yellow
            Write-Host "Thumbprint: $($cert.Thumbprint)" -ForegroundColor Yellow
            Write-Host "To use this certificate, you'll need to export it manually or install OpenSSL." -ForegroundColor Yellow
            
            return @{
                Thumbprint = $cert.Thumbprint
                Success = $false
                Message = "OpenSSL required for PEM export"
            }
        }
    }
    catch {
        Write-Host "Error generating certificate: $_" -ForegroundColor Red
        return @{
            Success = $false
            Message = $_.Exception.Message
        }
    }
}

# Function to update SimpleChat settings
function Update-SimpleChatSettings {
    param(
        [string]$CertPath,
        [string]$KeyPath,
        [bool]$UseAdhoc = $false
    )
    
    Write-Host "Configuration options for SimpleChat HTTPS:" -ForegroundColor Cyan
    Write-Host ""
    
    if ($UseAdhoc) {
        Write-Host "Option 1: Use adhoc SSL (self-signed, generated automatically)" -ForegroundColor Yellow
        Write-Host "Add these settings to your SimpleChat configuration:" -ForegroundColor Green
        Write-Host "'enable_https': True," -ForegroundColor Gray
        Write-Host "'use_adhoc_ssl': True," -ForegroundColor Gray
        Write-Host "'https_port': 5443" -ForegroundColor Gray
    }
    elseif ($CertPath -and $KeyPath) {
        Write-Host "Option 2: Use certificate files" -ForegroundColor Yellow
        Write-Host "Add these settings to your SimpleChat configuration:" -ForegroundColor Green
        Write-Host "'enable_https': True," -ForegroundColor Gray
        Write-Host "'ssl_cert_path': '$CertPath'," -ForegroundColor Gray
        Write-Host "'ssl_key_path': '$KeyPath'," -ForegroundColor Gray
        Write-Host "'https_port': 5443" -ForegroundColor Gray
    }
    
    Write-Host ""
    Write-Host "You can update these settings through the admin interface or directly in the database." -ForegroundColor Cyan
}

# Main script logic
try {
    if ($UseAdhoc) {
        Write-Host "Setting up adhoc SSL (Flask will generate self-signed certificates automatically)" -ForegroundColor Yellow
        Update-SimpleChatSettings -UseAdhoc $true
    }
    elseif ($CertPath -and $KeyPath) {
        Write-Host "Using provided certificate files:" -ForegroundColor Yellow
        Write-Host "  Certificate: $CertPath"
        Write-Host "  Key: $KeyPath"
        
        if ((Test-Path $CertPath) -and (Test-Path $KeyPath)) {
            Update-SimpleChatSettings -CertPath $CertPath -KeyPath $KeyPath
        }
        else {
            Write-Host "Error: One or both certificate files not found!" -ForegroundColor Red
            exit 1
        }
    }
    elseif ($SelfSigned) {
        Write-Host "Generating self-signed certificate..." -ForegroundColor Yellow
        $result = New-SelfSignedCertificateForSimpleChat -OutputPath (Get-Location)
        
        if ($result.Success) {
            Update-SimpleChatSettings -CertPath $result.CertPath -KeyPath $result.KeyPath
        }
        else {
            Write-Host "Failed to generate certificate: $($result.Message)" -ForegroundColor Red
            Write-Host "You can still use adhoc SSL by running:" -ForegroundColor Yellow
            Write-Host "  .\setup-https.ps1 -UseAdhoc" -ForegroundColor Gray
        }
    }
    else {
        Write-Host "Usage examples:" -ForegroundColor Yellow
        Write-Host "  .\setup-https.ps1 -UseAdhoc                    # Use Flask's built-in adhoc SSL"
        Write-Host "  .\setup-https.ps1 -SelfSigned                  # Generate self-signed certificate"
        Write-Host "  .\setup-https.ps1 -CertPath cert.pem -KeyPath key.pem  # Use existing certificates"
        Write-Host ""
        Write-Host "For development, the easiest option is:" -ForegroundColor Cyan
        Write-Host "  .\setup-https.ps1 -UseAdhoc" -ForegroundColor Green
    }
}
catch {
    Write-Host "Script failed with error: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Setup complete! Don't forget to:" -ForegroundColor Cyan
Write-Host "1. Update your SimpleChat settings with the HTTPS configuration" -ForegroundColor White
Write-Host "2. Restart the SimpleChat application" -ForegroundColor White
Write-Host "3. Access your app at https://localhost:5443" -ForegroundColor White
Write-Host "4. For self-signed certificates, you'll need to accept the browser security warning" -ForegroundColor Yellow
