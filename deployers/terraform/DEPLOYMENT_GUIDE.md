# Simple Chat - Complete Deployment Guide

**Version:** 0.229.100
**Last Updated:** December 16, 2025

This guide walks you through **every step** required to successfully deploy and configure the Simple Chat application using Terraform.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Initial Setup](#2-initial-setup)
3. [Create Azure Prerequisites](#3-create-azure-prerequisites)
4. [Configure GitHub Secrets](#4-configure-github-secrets)
5. [Build and Push Container Image](#5-build-and-push-container-image)
6. [Prepare Terraform Configuration](#6-prepare-terraform-configuration)
7. [Deploy Infrastructure with Terraform](#7-deploy-infrastructure-with-terraform)
8. [Deploy Azure AI Search Indexes](#8-deploy-azure-ai-search-indexes)
9. [Grant Entra ID Permissions](#9-grant-entra-id-permissions)
10. [Assign Users to Security Groups](#10-assign-users-to-security-groups)
11. [Configure Application Settings](#11-configure-application-settings)
12. [Test the Application](#12-test-the-application)
13. [Troubleshooting](#13-troubleshooting)
14. [Next Steps](#14-next-steps)

---

## 1. Prerequisites

### Required Tools

Install the following tools on your local machine:

| Tool | Version | Purpose | Installation Link |
|------|---------|---------|-------------------|
| **Azure CLI** | Latest | Manage Azure resources | [Install Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) |
| **Terraform** | >= 1.12.0 | Infrastructure as Code | [Install Terraform](https://developer.hashicorp.com/terraform/install) |
| **PowerShell** | 7.x+ | Run initialization script | [Install PowerShell](https://learn.microsoft.com/powershell/scripting/install/installing-powershell) |
| **Git** | Latest | Clone repository | [Install Git](https://git-scm.com/downloads) |

### Required Accounts & Permissions

- **Azure Subscription** (Azure Commercial or Azure Government)
- **Owner role** on the subscription (required for RBAC assignments)
- **Entra ID** (Azure AD) tenant access
- **GitHub account** (for container image builds)

### Knowledge Requirements

Basic familiarity with:
- Azure Portal navigation
- Command-line interfaces (Bash/PowerShell)
- JSON and HCL (Terraform) configuration files

---

## 2. Initial Setup

### Step 2.1: Clone the Repository

```bash
git clone https://github.com/lanternstudiosdev/ess-simple-chat.git
cd ess-simple-chat
```

### Step 2.2: Determine Your Azure Environment

**For Azure Commercial:**
- Cloud: `AzureCloud`
- Login endpoint: `https://login.microsoftonline.com`
- Example location: `eastus`, `westus2`, `northcentralus`

**For Azure Government:**
- Cloud: `AzureUSGovernment`
- Login endpoint: `https://login.microsoftonline.us`
- Example location: `usgovvirginia`, `usgovarizona`, `usgovtexas`

Make note of your environment - you'll need it throughout the deployment.

---

## 3. Create Azure Prerequisites

The `Initialize-AzureEnvironment.ps1` script creates **shared resources** that will be used across all environments:

### Step 3.1: Login to Azure CLI

**For Azure Commercial:**
```bash
az cloud set --name AzureCloud
az login
az account set --subscription "<YOUR_SUBSCRIPTION_ID>"
```

**For Azure Government:**
```bash
az cache purge
az account clear
az cloud set --name AzureUSGovernment
az login --scope https://management.core.usgovcloudapi.net//.default
az account set --subscription "<YOUR_SUBSCRIPTION_ID>"
```

### Step 3.2: Get Your Subscription and Tenant IDs

```bash
# Get Subscription ID
az account show --query id -o tsv

# Get Tenant ID
az account show --query tenantId -o tsv
```

**Save these values** - you'll need them multiple times.

### Step 3.3: Run the Initialization Script

```powershell
cd deployers

.\Initialize-AzureEnvironment.ps1 `
    -ResourceGroupName "sc-prereq-rg" `
    -AzureRegion "northcentralus" `
    -ACRName "lanternacr001" `
    -OpenAiName "lanternoai001"
```

**Parameters explained:**
- `ResourceGroupName`: Name for resource group containing shared resources
- `AzureRegion`: Azure region (must match your subscription's available regions)
- `ACRName`: Globally unique name for Azure Container Registry (lowercase, alphanumeric only, 5-50 chars)
- `OpenAiName`: Globally unique name for Azure OpenAI (lowercase, alphanumeric, hyphens)

### Step 3.4: Save the Outputs

The script will output critical information. **Copy and save these values:**

```
✅ ACR Login Server: lanternacr001.azurecr.io (or .azurecr.us for Gov)
✅ ACR Username: lanternacr001
✅ ACR Password: <long password string>
✅ OpenAI Name: lanternoai001
✅ OpenAI Resource Group: sc-prereq-rg
```

> **Important:** Keep the ACR password secure - you'll need it for GitHub Secrets and Terraform.

---

## 4. Configure GitHub Secrets

GitHub Actions will build your Docker image automatically. Configure repository secrets:

### Step 4.1: Navigate to Repository Settings

1. Go to your GitHub repository
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**

### Step 4.2: Add Required Secrets

Add these three secrets (using values from Step 3.4):

| Secret Name | Value | Example |
|-------------|-------|---------|
| `ACR_LOGIN_SERVER` | Your ACR login server | `lanternacr001.azurecr.io` |
| `ACR_USERNAME` | Your ACR name | `lanternacr001` |
| `ACR_PASSWORD` | Password from initialization script | `<from Step 3.4>` |

---

## 5. Build and Push Container Image

### Step 5.1: Trigger GitHub Actions Build

**Option A: Automatic (Recommended)**
1. Go to your GitHub repository
2. Navigate to **Actions** tab
3. Select **"SimpleChat Docker Image Publish"** workflow
4. Click **Run workflow** → **Run workflow** (green button)
5. Wait for the build to complete (typically 5-10 minutes)

**Option B: Manual Docker Build**
```bash
cd application/single_app

# Build the image
docker build -t <ACR_LOGIN_SERVER>/simple-chat:latest .

# Login to ACR
az acr login --name <ACR_NAME>

# Push the image
docker push <ACR_LOGIN_SERVER>/simple-chat:latest
```

### Step 5.2: Verify Image Push

```bash
az acr repository show-tags \
    --name <ACR_NAME> \
    --repository simple-chat \
    --output table
```

You should see tags like:
- `2025-12-16_42` (dated builds)
- `latest`

**Note the image tag** - you'll reference it in Terraform configuration.

---

## 6. Prepare Terraform Configuration

### Step 6.1: Navigate to Terraform Directory

```bash
cd deployers/terraform
```

### Step 6.2: Create Your Variables File

```bash
# Copy the example file
cp params/lantern-dev.tfvars.example params/lantern-dev.tfvars

# Edit with your preferred editor
nano params/lantern-dev.tfvars
```

### Step 6.3: Fill in Required Values

Edit `params/lantern-dev.tfvars` with your specific values:

```hcl
# ===================================
# Azure Environment Configuration
# ===================================
global_which_azure_platform = "AzureCloud"  # or "AzureUSGovernment"
param_tenant_id             = "YOUR_TENANT_ID"        # From Step 3.2
param_subscription_id       = "YOUR_SUBSCRIPTION_ID"  # From Step 3.2
param_location              = "northcentralus"

# ===================================
# Existing Resource Group (IMPORTANT!)
# ===================================
param_existing_resource_group_name = "rg-lantern-dev-ess-simple-chat-ncus"

# ===================================
# Azure Container Registry (ACR)
# ===================================
acr_name                = "lanternacr001"      # From Step 3.4
acr_resource_group_name = "sc-prereq-rg"       # From Step 3.3
acr_username            = "lanternacr001"      # Same as acr_name
acr_password            = "YOUR_ACR_PASSWORD"  # From Step 3.4

# ===================================
# Container Image Configuration
# ===================================
image_name = "simple-chat:latest"  # or specific tag like "simple-chat:2025-12-16_42"

# ===================================
# Application Configuration
# ===================================
param_environment = "dev"
param_base_name   = "lantern"  # Short name for resource naming

# ===================================
# Azure OpenAI Configuration
# ===================================
param_use_existing_openai_instance            = true
param_existing_azure_openai_resource_name     = "lanternoai001"  # From Step 3.4
param_existing_azure_openai_resource_group_name = "sc-prereq-rg"   # From Step 3.3

# ===================================
# Owner/Tagging Information
# ===================================
param_resource_owner_id       = "Your Name"
param_resource_owner_email_id = "your.email@yourdomain.com"

# ===================================
# Entra ID Security Groups
# ===================================
param_create_entra_security_groups = true
```

### Step 6.4: Validate Your Configuration

**Required fields checklist:**
- ✅ `param_tenant_id` - Your Azure AD tenant ID
- ✅ `param_subscription_id` - Your Azure subscription ID
- ✅ `param_location` - Azure region (must match existing RG)
- ✅ `param_existing_resource_group_name` - Your existing resource group
- ✅ `acr_name` - Container registry name
- ✅ `acr_password` - ACR admin password
- ✅ `param_resource_owner_email_id` - Valid email in your tenant

---

## 7. Deploy Infrastructure with Terraform

### Step 7.1: Initialize Terraform

```bash
cd /workspaces/ess-simple-chat/deployers/terraform

# Initialize Terraform providers
terraform init
```

Expected output:
```
Terraform has been successfully initialized!
```

### Step 7.2: Review the Deployment Plan

```bash
terraform plan -var-file="./params/lantern-dev.tfvars"
```

Review the output carefully:
- Should show **~20-30 resources** to be created
- Verify resource names follow pattern: `lantern-dev-<service>`
- Check that resources are targeting your existing resource group

### Step 7.3: Deploy the Infrastructure

```bash
terraform apply -var-file="./params/lantern-dev.tfvars" -auto-approve
```

**Deployment time:** Approximately 10-15 minutes

### Step 7.4: Save Terraform Outputs

When deployment completes, note these outputs:

```bash
# View outputs
terraform output

# Example outputs:
# web_app_url = "lantern-dev-app.azurewebsites.net"
# resource_group_name = "rg-lantern-dev-ess-simple-chat-ncus"
```

**Save the `web_app_url`** - this is your application's URL.

---

## 8. Deploy Azure AI Search Indexes

> **Important:** These indexes must be deployed manually via Azure Portal.

### Step 8.1: Navigate to Azure Portal

1. Open [Azure Portal](https://portal.azure.com) (or [Azure Government Portal](https://portal.azure.us))
2. Navigate to your resource group: `rg-lantern-dev-ess-simple-chat-ncus`
3. Find and open the **Azure AI Search** service: `lantern-dev-search`

### Step 8.2: Import User Index

1. In the search service, click **Indexes** (left menu)
2. Click **+ Add Index** → **Import from JSON**
3. Browse to: `deployers/terraform/artifacts/ai_search-index-user.json`
4. Click **Import**
5. Verify the index `ai_search-index-user` appears in the list

### Step 8.3: Import Group Index

1. Click **+ Add Index** → **Import from JSON**
2. Browse to: `deployers/terraform/artifacts/ai_search-index-group.json`
3. Click **Import**
4. Verify the index `ai_search-index-group` appears in the list

### Step 8.4: Verify Indexes

You should now see two indexes:
- ✅ `ai_search-index-user`
- ✅ `ai_search-index-group`

---

## 9. Grant Entra ID Permissions

### Step 9.1: Navigate to App Registration

1. In Azure Portal, go to **Entra ID** (or **Azure Active Directory**)
2. Click **App registrations** (left menu)
3. Find your app: `lantern-dev-ar`
4. Click on the app to open it

### Step 9.2: Review API Permissions

1. Click **API permissions** (left menu)
2. You should see:
   - Microsoft Graph
     - User.Read
     - profile
     - email
     - Group.Read.All
     - offline_access
     - openid

### Step 9.3: Grant Admin Consent

1. Click **Grant admin consent for [Your Tenant]**
2. Click **Yes** to confirm
3. Wait for green checkmarks to appear next to all permissions

> **Note:** You need **Global Administrator** or **Privileged Role Administrator** role to grant consent.

---

## 10. Assign Users to Security Groups

### Step 10.1: Navigate to Entra ID Groups

1. In Azure Portal, go to **Entra ID**
2. Click **Groups** (left menu)
3. Find the groups created (filter by `lantern-dev-sg`):
   - `lantern-dev-sg-Admins`
   - `lantern-dev-sg-Users`
   - `lantern-dev-sg-CreateGroup`
   - `lantern-dev-sg-SafetyViolationAdmin`
   - `lantern-dev-sg-FeedbackAdmin`

### Step 10.2: Add Yourself to Admin Group

1. Click **lantern-dev-sg-Admins**
2. Click **Members** (left menu)
3. Click **+ Add members**
4. Search for your user account
5. Click **Select**

### Step 10.3: Add Additional Users (Optional)

Repeat the process for other groups as needed:

| Group | Purpose |
|-------|---------|
| `Admins` | Full admin access to settings |
| `Users` | Standard chat access |
| `CreateGroup` | Can create group workspaces |
| `SafetyViolationAdmin` | View content safety violations |
| `FeedbackAdmin` | View user feedback |

---

## 11. Configure Application Settings

### Step 11.1: Access the Application

1. Open your browser
2. Navigate to: `https://lantern-dev-app.azurewebsites.net` (your web_app_url from Step 7.4)
3. Sign in with your Entra ID credentials
4. You'll be redirected after successful authentication

### Step 11.2: Open Admin Settings

1. Click **Admin** in the top navigation bar
2. Click **App Settings** tab

> **Note:** You must be in the `Admins` security group to see this section.

### Step 11.3: Configure GPT Settings

1. Scroll to **GPT Configuration** section
2. Fill in:

   **Azure OpenAI GPT Endpoint:**
   ```
   https://lanternoai001.openai.azure.com/
   ```

   **Authentication Type:**
   - Select **Key** (or **Managed Identity** if configured)

   **API Key:** (if using Key authentication)
   - Go to Azure Portal → Your OpenAI resource
   - Click **Keys and Endpoint**
   - Copy **KEY 1**
   - Paste into the field

3. Click **Test GPT Connection** - should show ✅ Success
4. Click **Fetch GPT Models**
5. Select your deployed models (e.g., `gpt-4o`, `gpt-4o-mini`)
6. Click **Save Settings**

> **Troubleshooting:** If "Fetch GPT Models" fails but "Test" succeeds, see [Troubleshooting Section](#troubleshooting).

### Step 11.4: Configure Embeddings Settings

1. Scroll to **Embeddings Configuration** section
2. Fill in (same endpoint as GPT):

   **Azure OpenAI Embeddings Endpoint:**
   ```
   https://lanternoai001.openai.azure.com/
   ```

   **Authentication Type:** Same as GPT (Key or Managed Identity)

   **API Key:** Same as GPT

3. Click **Test Embeddings Connection**
4. Click **Fetch Embedding Models**
5. Select your embedding model (e.g., `text-embedding-ada-002`)
6. Click **Save Settings**

### Step 11.5: Configure Azure AI Search

1. Scroll to **Azure AI Search Configuration** section
2. Fill in:

   **Search Service Endpoint:**
   ```
   https://lantern-dev-search.search.windows.net
   ```

   **Authentication Type:** Select **Key**

   **Admin API Key:**
   - Go to Azure Portal → Your Search service
   - Click **Keys**
   - Copy **Primary admin key**
   - Paste into the field

3. Click **Test Search Connection**
4. Click **Save Settings**

### Step 11.6: Configure Document Intelligence

1. Scroll to **Document Intelligence Configuration** section
2. Fill in:

   **Document Intelligence Endpoint:**
   ```
   https://lantern-dev-docintel.cognitiveservices.azure.com/
   ```

   **Authentication Type:** Select **Key**

   **API Key:**
   - Go to Azure Portal → Your Document Intelligence resource
   - Click **Keys and Endpoint**
   - Copy **KEY 1**
   - Paste into the field

3. Click **Test Document Intelligence Connection**
4. Click **Save Settings**

### Step 11.7: Enable Workspace Features

1. Scroll to **Workspaces** section
2. Toggle ON:
   - ✅ **Enable Your Workspace** (personal documents)
   - ✅ **Enable My Groups** (group collaboration)

3. Click **Save Settings**

### Step 11.8: Configure Optional Features (As Needed)

Configure any optional features you want to enable:

| Feature | Configuration Required |
|---------|------------------------|
| **Image Generation** | Azure OpenAI DALL-E endpoint |
| **Content Safety** | Azure Content Safety endpoint + key |
| **Video Processing** | Azure Video Indexer credentials |
| **Audio Processing** | Azure Speech Service endpoint + key |
| **Enhanced Citations** | Azure Storage connection string |
| **Metadata Extraction** | Select GPT model for metadata |

---

## 12. Test the Application

### Step 12.1: Test Basic Chat

1. Click **Home** or **Chat** in navigation
2. Type a test message: "Hello, can you help me?"
3. Verify you receive an AI response

✅ **Success:** AI responds to your message

### Step 12.2: Test Document Upload

1. Click **Your Workspace** in navigation
2. Click **Upload Document**
3. Select a test PDF or Word document
4. Wait for processing to complete
5. Verify document appears in your workspace

✅ **Success:** Document uploaded and processed

### Step 12.3: Test RAG (Retrieval-Augmented Generation)

1. Start a new chat
2. Ensure **Search Documents** toggle is ON
3. Ask a question about your uploaded document
4. Verify response includes citations referencing your document

✅ **Success:** AI responds with information from your document

### Step 12.4: Test Group Workspace (Optional)

1. Click **My Groups** in navigation
2. Click **Create Group**
3. Enter group name and description
4. Upload a document to the group
5. Verify group members can access the document

✅ **Success:** Group collaboration works

---

## 13. Troubleshooting

### Issue: "Fetch GPT Models" Fails but "Test Connection" Succeeds

**Symptom:** Test GPT Connection works, but Fetch GPT Models returns an error.

**Root Cause:** Azure AI Foundry endpoints may not work for model listing.

**Solution:**
1. Edit the GPT Endpoint URL to use the OpenAI service name:

   **Change from:**
   ```
   https://northcentralus.api.cognitive.microsoft.com/openai/...
   ```

   **Change to:**
   ```
   https://lanternoai001.openai.azure.com/
   ```

2. Click **Fetch GPT Models** (should work now)
3. Select your models
4. **Save Settings**
5. Optionally revert endpoint URL if needed for other features

### Issue: Cannot See Admin Menu

**Symptom:** "Admin" button not visible in navigation.

**Solution:**
1. Verify you're assigned to `lantern-dev-sg-Admins` security group
2. Sign out and sign back in
3. Check app roles in Entra ID → Enterprise Applications → Your app → Users and groups

### Issue: Document Upload Fails

**Possible Causes:**
- Document Intelligence not configured correctly
- Storage account permissions missing
- AI Search indexes not deployed

**Solution:**
1. Verify Document Intelligence connection in Admin Settings
2. Check Azure Portal → Storage Account → Access control (IAM)
3. Verify both search indexes exist (Step 8)
4. Check browser console for detailed errors

### Issue: Search Not Finding Documents

**Possible Causes:**
- Embeddings not configured
- AI Search not configured
- Documents not fully processed

**Solution:**
1. Verify embeddings configuration in Admin Settings
2. Check AI Search connection
3. Wait 1-2 minutes after upload for indexing to complete
4. Verify document shows "Processed" status in Your Workspace

### Issue: Authentication Redirect Loop

**Possible Causes:**
- App registration redirect URIs incorrect
- Client secret missing or incorrect

**Solution:**
1. Go to Entra ID → App registrations → Your app → Authentication
2. Verify redirect URIs match:
   ```
   https://lantern-dev-app.azurewebsites.net/.auth/login/aad/callback
   https://lantern-dev-app.azurewebsites.net/getAToken
   ```
3. Check App Service → Configuration → Application Settings
4. Verify `MICROSOFT_PROVIDER_AUTHENTICATION_SECRET` is set

### Issue: Container Fails to Start

**Symptom:** App Service shows "Application Error" or "Container didn't respond"

**Solution:**
1. Go to Azure Portal → App Service → Log stream
2. Check for errors in logs
3. Verify ACR credentials in App Service Configuration
4. Ensure container image exists in ACR
5. Check App Service → Deployment Center for deployment status

---

## 14. Next Steps

### Production Hardening

Once your application is working:

1. **Enable Managed Identity** for all Azure services (more secure than keys)
   - See: [How to use Managed Identity](../../docs/setup_instructions_special.md#how-to-use-managed-identity)

2. **Configure Private Endpoints** for enterprise networking
   - See: [Enterprise Networking](../../docs/setup_instructions_special.md#enterprise-networking)

3. **Set up Redis Cache** for scalability
   - Enables horizontal scaling across multiple App Service instances

4. **Enable Production Features:**
   - Cosmos DB backup policies
   - Key Vault purge protection
   - App Service auto-scaling rules
   - Application Insights alerts

5. **Review Security Settings:**
   - Enable Key Vault purge protection
   - Disable Storage Account public access
   - Configure network security groups
   - Review RBAC assignments

### Monitoring & Operations

1. **Application Insights:** Monitor performance, errors, and usage
2. **Log Analytics:** Query logs across all services
3. **Cosmos DB Metrics:** Monitor RU consumption and throttling
4. **AI Search Metrics:** Track query performance and index size

### Additional Documentation

- **Admin Configuration:** [docs/admin_configuration.md](../../docs/admin_configuration.md)
- **Application Scaling:** [docs/application_scaling.md](../../docs/application_scaling.md)
- **FAQs:** [docs/faqs.md](../../docs/faqs.md)
- **Features Guide:** [docs/features.md](../../docs/features.md)

---

## Support & Feedback

For issues, questions, or feature requests:
- Create an issue in the GitHub repository
- Review existing documentation in the `/docs` folder
- Check the FAQs: [docs/faqs.md](../../docs/faqs.md)

---

**Congratulations!** 🎉 Your Simple Chat application is now fully deployed and configured. You can now start using it for AI-powered conversations, document uploads, and collaborative group workspaces.
