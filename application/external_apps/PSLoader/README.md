# PSLoader - PowerShell Document Upload Utility

## Overview

PSLoader is a PowerShell-based bulk document upload utility for the SimpleChat system. It enables automated, programmatic upload of documents to SimpleChat workspaces using Bearer token authentication via the external API.

**Version:** 0.1.0  
**Author:** John Scott  
**License:** MIT  
**Requires:** PowerShell 7.2 or later

## Purpose

PSLoader provides a simple, scriptable way to:
- Bulk upload documents from local directories to SimpleChat
- Authenticate using Azure Entra ID (formerly Azure AD) client credentials
- Target specific workspaces (public or group)
- Classify documents during upload
- Support both Azure Commercial and Azure US Government clouds

## Key Features

✅ **Bulk Upload** - Recursively processes all supported files in a directory  
✅ **OAuth Authentication** - Uses client credentials flow with Entra ID  
✅ **Progress Tracking** - Reports success/failure counts for each file  
✅ **Multi-Cloud Support** - Works with Azure Commercial and US Government  
✅ **Document Classification** - Apply classification tags during upload  
✅ **Comprehensive File Type Support** - Handles documents, images, audio, and video files

## Prerequisites

### 1. PowerShell Requirements
- **PowerShell 7.2 or later** (PowerShell Core)
- Check your version: `$PSVersionTable.PSVersion`
- Download from: https://github.com/PowerShell/PowerShell/releases

### 2. Azure Entra ID Configuration

#### Application Registration
You need an Azure AD app registration configured for **client credentials authentication**:

1. **Create App Registration** in Azure Portal → Azure Active Directory → App registrations
2. **Note the Application (client) ID** - this is your `clientId`
3. **Note the Directory (tenant) ID** - this is your `tenantId`
4. **Create a client secret** (Certificates & secrets) - this is your `clientSecret`

#### API Permissions
The app registration must have permissions to access the SimpleChat API:

1. Navigate to **API permissions** in your app registration
2. Add permission → **APIs my organization uses** → Find your SimpleChat app registration
3. Select **Application permissions** (not Delegated)
4. Add the **ExternalApi** role
5. Click **Grant admin consent**

> **Important:** The role name must be exactly `ExternalApi` (case-sensitive)

#### Assigning the Service Principal to ExternalApi Role

**Important:** The Azure Portal only allows assigning roles to **users and groups**, not to service principals (app registrations). To assign the PSLoader service principal to the SimpleChat ExternalApi role, you must use the **Azure CLI**.

Follow these steps to assign the role:

**Step 1: Get the SimpleChat (Resource) Service Principal ID**
```bash
az ad sp list --display-name "SimpleChat" --query "[0].id" -o tsv
```
Replace `"SimpleChat"` with your SimpleChat app registration display name. Save this value as `RESOURCE_SP_ID`.

**Step 2: Get the PSLoader (Target) Service Principal ID**
```bash
az ad sp list --display-name "PSLoader" --query "[0].id" -o tsv
```
Replace `"PSLoader"` with your PSLoader app registration display name. Save this value as `TARGET_SP_ID`.

**Step 3: Get the ExternalApi App Role ID**
```bash
az ad sp show --id "RESOURCE_SP_ID" --query "appRoles[?displayName=='ExternalApi' && isEnabled==\`true\`].id | [0]" -o tsv
```
Replace `RESOURCE_SP_ID` with the value from Step 1. Save this value as `APP_ROLE_ID`.

> **Note:** If this returns empty, verify the role name. It should be `ExternalApi` (case-sensitive), not `ExternalAPI`.

**Step 4: Create the Role Assignment**
```bash
az rest --method POST \
  --url "https://graph.microsoft.com/v1.0/servicePrincipals/TARGET_SP_ID/appRoleAssignments" \
  --body '{"principalId": "TARGET_SP_ID", "resourceId": "RESOURCE_SP_ID", "appRoleId": "APP_ROLE_ID"}' \
  --headers "Content-Type=application/json"
```

Replace the placeholders:
- `TARGET_SP_ID` - PSLoader service principal ID (from Step 2)
- `RESOURCE_SP_ID` - SimpleChat service principal ID (from Step 1)
- `APP_ROLE_ID` - ExternalApi role ID (from Step 3)

**PowerShell Example (Windows):**
```powershell
# Step 1: Get SimpleChat service principal ID
$resourceSpId = az ad sp list --display-name "SimpleChat" --query "[0].id" -o tsv

# Step 2: Get PSLoader service principal ID
$targetSpId = az ad sp list --display-name "PSLoader" --query "[0].id" -o tsv

# Step 3: Get ExternalApi app role ID
$appRoleId = az ad sp show --id $resourceSpId --query "appRoles[?displayName=='ExternalApi' && isEnabled==``true``].id | [0]" -o tsv

# Step 4: Create the assignment
az rest --method POST `
  --url "https://graph.microsoft.com/v1.0/servicePrincipals/$targetSpId/appRoleAssignments" `
  --body "{ `"principalId`": `"$targetSpId`", `"resourceId`": `"$resourceSpId`", `"appRoleId`": `"$appRoleId`" }" `
  --headers "Content-Type=application/json"
```

**Verification:**

After assignment, verify the role was added:
```bash
az rest --method GET \
  --url "https://graph.microsoft.com/v1.0/servicePrincipals/TARGET_SP_ID/appRoleAssignments"
```

You should see an entry with the `appRoleId` matching the ExternalApi role.

#### Application ID URI (Scope)
The `scope` parameter should be in the format:
```
api://<SimpleChat-App-Registration-Client-ID>/.default
```

This is the **SimpleChat application's** App ID URI, not the PSLoader app registration.

### 3. SimpleChat Configuration

- **Feature Flags:** Ensure appropriate workspace features are enabled (public workspaces or group workspaces)
- **API Endpoint:** Know your SimpleChat API base URL (e.g., `https://your-app.azurewebsites.net`)
- **User ID:** Obtain the user GUID from Cosmos DB `users` container
- **Workspace ID:** Obtain the workspace GUID from Cosmos DB (groups or public workspaces container)

## Usage

### Basic Syntax

```powershell
.\PSLoader.ps1 `
    -uploadDirectory "C:\Documents\ToUpload" `
    -userId "12345678-1234-1234-1234-123456789abc" `
    -activeWorkspaceId "87654321-4321-4321-4321-cba987654321" `
    -classification "Confidential" `
    -tenantId "your-tenant-id" `
    -clientId "your-client-id" `
    -clientSecret "your-client-secret" `
    -scope "api://simplechat-app-id/.default"
```

### Azure US Government

For Azure US Government cloud, add the `-AzureUSGovernment` switch:

```powershell
.\PSLoader.ps1 `
    -uploadDirectory "C:\Documents\ToUpload" `
    -userId "user-guid" `
    -activeWorkspaceId "workspace-guid" `
    -tenantId "your-tenant-id" `
    -clientId "your-client-id" `
    -clientSecret "your-client-secret" `
    -scope "api://simplechat-app-id/.default" `
    -AzureUSGovernment
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `uploadDirectory` | Yes | Local directory containing files to upload (recursive) |
| `userId` | Yes | User GUID from Cosmos DB users container |
| `activeWorkspaceId` | Yes | Workspace GUID (group or public workspace) |
| `classification` | No | Document classification tag (default: "unclassified") |
| `tenantId` | Yes | Azure Entra ID tenant GUID |
| `clientId` | Yes | Application (client) ID for authentication |
| `clientSecret` | Yes | Client secret for authentication |
| `scope` | Yes | API scope: `api://<SimpleChat-App-ID>/.default` |
| `AzureUSGovernment` | No | Switch for Azure US Government cloud |

## Supported File Types

PSLoader automatically filters and uploads the following file types:

### Documents
- `.pdf`, `.docx`, `.txt`, `.md`, `.html`

### Spreadsheets
- `.xsl`, `.xslx`, `.csv`

### Images
- `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tiff`, `.tif`, `.heif`

### Audio
- `.wav`, `.m4a`

### Video
- `.mp4`, `.mov`, `.avi`, `.mkv`, `.flv`, `.mxf`, `.gxf`, `.ts`, `.ps`, `.3gp`, `.3gpp`, `.mpg`, `.wmv`, `.asf`, `.m4v`, `.isma`, `.ismv`, `.dvr-ms`

### Data
- `.json`

## How It Works

### 1. Authentication
```powershell
# Authenticates using OAuth 2.0 client credentials flow
$tokenUrl = "https://login.microsoftonline.com/$tenantId/oauth2/v2.0/token"
$body = @{
    client_id     = $clientId
    scope         = $scope
    client_secret = $clientSecret
    grant_type    = "client_credentials"
}
$response = Invoke-RestMethod -Method Post -Uri $tokenUrl -Body $body
$accessToken = $response.access_token
```

### 2. File Discovery
```powershell
# Recursively finds all supported files in the upload directory
$files = Get-ChildItem -Path $uploadDirectory -File -Recurse -Include *.pdf, *.docx, ...
```

### 3. Upload Process
For each discovered file:
```powershell
$form = @{
    file                = Get-Item $file.FullName
    user_Id             = $userId
    active_Workspace_Id = $activeWorkspaceId
    classification      = $classification
}

$uploadResponse = Invoke-RestMethod `
    -Method Post `
    -Uri "https://your-simplechat-api-endpoint/api/external/public/documents/upload" `
    -Headers @{ Authorization = "Bearer $accessToken" } `
    -Form $form
```

### 4. Progress Reporting
- Displays progress for each file upload
- Reports success (green) or failure (red) for each file
- Provides final summary with total counts

## Configuration

### Setting the API Endpoint

**Important:** You must update the API endpoint URL in the script before using it.

On **line 119** of `PSLoader.ps1`, replace the placeholder with your actual SimpleChat API endpoint:

```powershell
# Current (line 119):
$uploadResponse = Invoke-RestMethod -Method Post -Uri "https://your-simplechat-api-endpoint/api/external/public/documents/upload" -Headers $headers -Form $form

# Change to your actual endpoint:
$uploadResponse = Invoke-RestMethod -Method Post -Uri "https://your-app.azurewebsites.net/external/public_documents/upload" -Headers $headers -Form $form
```

**Notes:**
- For public workspace uploads: `/external/public_documents/upload`
- For group workspace uploads: `/external/group_documents/upload` (requires SimpleChat v0.229.062+)

## Finding Required IDs

### User ID
```powershell
# Query Cosmos DB users container or use Azure Portal
# Example user ID: "user@contoso.com" or GUID format
```

### Workspace ID

**For Public Workspaces:**
```powershell
# Query Cosmos DB public_workspaces container
# The workspace GUID is in the 'id' field
```

**For Group Workspaces:**
```powershell
# Use Azure AD group Object ID
Connect-AzureAD
Get-AzureADGroup -SearchString "Your Group Name" | Select-Object ObjectId, DisplayName

# Or using Azure CLI
az ad group show --group "Your Group Name" --query objectId -o tsv
```

## Example Workflows

### Example 1: Upload to Public Workspace

```powershell
# Upload all documents from C:\Reports to a public workspace
.\PSLoader.ps1 `
    -uploadDirectory "C:\Reports" `
    -userId "user@contoso.com" `
    -activeWorkspaceId "public-workspace-guid" `
    -classification "Public" `
    -tenantId "tenant-guid" `
    -clientId "client-guid" `
    -clientSecret "secret-value" `
    -scope "api://simplechat-app-guid/.default"
```

### Example 2: Upload Classified Documents

```powershell
# Upload confidential documents with classification
.\PSLoader.ps1 `
    -uploadDirectory "C:\Confidential\Legal" `
    -userId "legal-team@contoso.com" `
    -activeWorkspaceId "legal-workspace-guid" `
    -classification "Confidential" `
    -tenantId "tenant-guid" `
    -clientId "client-guid" `
    -clientSecret "secret-value" `
    -scope "api://simplechat-app-guid/.default"
```

### Example 3: Azure Government Cloud

```powershell
# Upload to Azure US Government deployment
.\PSLoader.ps1 `
    -uploadDirectory "C:\Government\Documents" `
    -userId "gov-user@agency.gov" `
    -activeWorkspaceId "workspace-guid" `
    -classification "CUI" `
    -tenantId "gov-tenant-guid" `
    -clientId "gov-client-guid" `
    -clientSecret "gov-secret" `
    -scope "api://gov-simplechat-guid/.default" `
    -AzureUSGovernment
```

## Troubleshooting

### Common Issues

#### Issue: "401 Unauthorized - No access token provided"
**Cause:** Token authentication failed  
**Solution:** 
- Verify `tenantId`, `clientId`, and `clientSecret` are correct
- Check that client secret hasn't expired
- Ensure you're using the correct cloud (add `-AzureUSGovernment` if needed)

#### Issue: "401 Unauthorized - ExternalApi role required"
**Cause:** App registration missing required role  
**Solution:**
- Verify the app role is named exactly `ExternalApi` (case-sensitive)
- Ensure the service principal has been granted the role
- Check that admin consent was granted for the API permission

#### Issue: "401 Unauthorized - Invalid audience"
**Cause:** Scope parameter incorrect  
**Solution:**
- Verify scope uses format: `api://<SimpleChat-App-ID>/.default`
- Use the **SimpleChat app registration ID**, not the PSLoader app ID
- Check the Application ID URI in the SimpleChat app registration

#### Issue: "400 Bad Request - user_id is required"
**Cause:** Missing or invalid user ID  
**Solution:**
- Verify the user ID exists in Cosmos DB users container
- Check the user ID format (email or GUID)

#### Issue: "404 Not Found"
**Cause:** API endpoint URL incorrect  
**Solution:**
- Update line 119 with your actual SimpleChat API URL
- Verify the endpoint path matches your SimpleChat version
- Check that the route is registered in `app.py`

#### Issue: "File type not allowed"
**Cause:** File extension not in supported types list  
**Solution:**
- Check the file extension matches supported types
- If needed, add custom extensions to line 97 of the script

#### Issue: "Failed to upload file" for all files
**Cause:** Network, authentication, or API issues  
**Solution:**
- Check API endpoint is accessible
- Verify token is valid (check expiration)
- Review full error message in red text
- Test API endpoint with PowerShell separately

## Output Example

```
Retrieved access token. Beginning file upload process...
Found 25 files to upload. Beginning upload...
Uploading file: C:\Documents\report1.pdf...
Successfully uploaded file: C:\Documents\report1.pdf
{
    "message": "Processed 1 file(s). Check status periodically.",
    "document_ids": ["doc-guid-here"],
    "processed_filenames": ["report1.pdf"],
    "errors": []
}
Uploading file: C:\Documents\data.csv...
Successfully uploaded file: C:\Documents\data.csv
...
File upload process completed. Successfully uploaded 24 files. Failed to upload 1 files.
```

## Security Best Practices

### 1. Protect Client Secrets
```powershell
# Option 1: Use environment variables
$clientSecret = $env:PSLOADER_CLIENT_SECRET

# Option 2: Use Azure Key Vault
$clientSecret = Get-AzKeyVaultSecret -VaultName "YourVault" -Name "PSLoaderSecret" -AsPlainText

# Option 3: Prompt for secret
$clientSecret = Read-Host "Enter client secret" -AsSecureString
$clientSecret = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($clientSecret))
```

### 2. Token Management
- Access tokens typically expire in 1 hour
- For long-running operations, implement token refresh logic
- Never store tokens in plain text files or source control

### 3. Logging and Auditing
- Monitor upload logs for unauthorized access attempts
- Review failed uploads regularly
- Consider adding custom logging to track upload history

## Comparison with Python Bulkloader

| Feature | PSLoader | Python Bulkloader |
|---------|----------|-------------------|
| Language | PowerShell 7.2+ | Python 3.x |
| Configuration | Command-line parameters | CSV file (map.csv) |
| Multi-workspace | Single workspace per run | Multiple workspaces per CSV |
| Platform | Windows/Linux/macOS | Windows/Linux/macOS |
| Authentication | Client credentials | Client credentials (MSAL) |
| Progress Tracking | Console output | Console output |
| Use Case | Ad-hoc uploads, scripting | Scheduled bulk operations |

**When to use PSLoader:**
- Windows-native scripting environments
- Ad-hoc or one-time uploads
- Integration with existing PowerShell workflows
- Direct parameter-based configuration

**When to use Python Bulkloader:**
- Scheduled/automated bulk operations
- Multiple workspaces with different configurations
- CSV-based upload planning
- Cross-platform Python environments

## API Endpoints

### Public Workspace Documents
```
POST /external/public_documents/upload
```

### Group Workspace Documents (v0.229.062+)
```
POST /external/group_documents/upload
```

See the [External API Documentation](../../docs/features/EXTERNAL_GROUP_DOCUMENTS_API.md) for complete API specifications.

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 0.1.0 | 2025-11-05 | Initial release with bulk upload functionality |

## Related Documentation

- [Bulkloader (Python) README](../bulkloader/ReadMe.md)
- [External API Documentation](../../docs/features/EXTERNAL_GROUP_DOCUMENTS_API.md)
- [Admin Configuration Guide](../../docs/admin_configuration.md)
- [SimpleChat Features Overview](../../docs/features.md)

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review the SimpleChat documentation
3. Verify Azure AD app registration configuration
4. Check API endpoint accessibility
5. Review PowerShell error messages carefully

## License

This script is licensed under the MIT License. See the [LICENSE](../../../LICENSE) file for details.

**Copyright (c) 2025 Microsoft Corporation. All rights reserved.**
