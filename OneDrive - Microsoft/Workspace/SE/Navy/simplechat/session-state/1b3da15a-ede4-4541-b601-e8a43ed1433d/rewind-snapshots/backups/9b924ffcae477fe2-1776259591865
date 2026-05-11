# BookStack Integration Setup Guide

## Overview
This document provides instructions for configuring the BookStack integration with Azure resources. All hardcoded endpoints and resource-specific values have been parameterized to support deployment across different Azure environments.

## Prerequisites
- Azure subscription
- Azure Cosmos DB account
- Azure Storage Account with blob container
- Azure CLI installed
- Appropriate permissions to create role assignments

## Environment Variables

Ensure the following environment variables are set in your `.env` file:

```bash
# Azure Cosmos DB Configuration
AZURE_COSMOS_ENDPOINT="https://<your-cosmos-account>.documents.azure.com:443/"
AZURE_COSMOS_AUTHENTICATION_TYPE="managed_identity"  # or "key" or "connection_string"
AZURE_COSMOS_KEY="<your-cosmos-key-if-using-key-auth>"

# Azure Storage Configuration
STORAGE_ACCOUNT_URL="https://<your-storage-account>.blob.core.windows.net"
AZURE_STORAGE_CONNECTION_STRING="<your-connection-string-if-needed>"
AZURE_BLOB_CONTAINER="bookstack-documents"

# BookStack Configuration
BOOKSTACK_URL="http://<your-bookstack-instance>"
BOOKSTACK_TOKEN_ID="<your-bookstack-token-id>"
BOOKSTACK_TOKEN_SECRET="<your-bookstack-token-secret>"

# Database Name
COSMOS_DB="<your-cosmos-db-name>"
```

## Azure Role Assignments

### Step 1: Update JSON Role Definition Files

Before running the Azure CLI commands, update the placeholder values in the JSON role definition files:

#### `cosmosdb-data-writer-role.json`
Replace:
- `<SUBSCRIPTION_ID>` with your Azure subscription ID
- `<RESOURCE_GROUP>` with your resource group name
- `<COSMOS_ACCOUNT_NAME>` with your Cosmos DB account name

#### `cosmosdb-readmetadata-role.json`
Replace the same placeholders as above.

### Step 2: Run Azure CLI Commands

Open `application/single_app/commands.txt` and replace the following placeholders in each command:

- `<SUBSCRIPTION_ID>`: Your Azure subscription ID (e.g., `57ddfff2-1477-479b-8e05-9a5f170fe5db`)
- `<RESOURCE_GROUP>`: Your resource group name (e.g., `SimpleChatWestRG`)
- `<COSMOS_ACCOUNT_NAME>`: Your Cosmos DB account name (e.g., `simplechatwest-cosmos2`)
- `<STORAGE_ACCOUNT_NAME>`: Your storage account name (e.g., `simplechatweststorage`)
- `<PRINCIPAL_ID>`: The managed identity or service principal object ID for basic access
- `<APP_PRINCIPAL_ID>`: The application's managed identity or service principal object ID

Then execute the commands in sequence:

```bash
# 1. Assign Cosmos DB Account Reader Role
az role assignment create --assignee <PRINCIPAL_ID> --role "Cosmos DB Account Reader Role" --scope /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/<RESOURCE_GROUP>/providers/Microsoft.DocumentDB/databaseAccounts/<COSMOS_ACCOUNT_NAME>

# 2. Assign Cosmos DB Built-in Data Contributor
az role assignment create --assignee <PRINCIPAL_ID> --role "Cosmos DB Built-in Data Contributor" --scope /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/<RESOURCE_GROUP>/providers/Microsoft.DocumentDB/databaseAccounts/<COSMOS_ACCOUNT_NAME>/databases/

# 3. Disable local auth (if needed for enhanced security)
az resource update --ids /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/<RESOURCE_GROUP>/providers/Microsoft.DocumentDB/databaseAccounts/<COSMOS_ACCOUNT_NAME> --set properties.disableLocalAuth=false

# 4. Create custom role definitions
az cosmosdb sql role definition create --account-name <COSMOS_ACCOUNT_NAME> --resource-group <RESOURCE_GROUP> --body @cosmosdb-readmetadata-role.json

az cosmosdb sql role definition create --account-name <COSMOS_ACCOUNT_NAME> --resource-group <RESOURCE_GROUP> --body @cosmosdb-data-writer-role.json

# 5. Assign custom roles
az cosmosdb sql role assignment create --account-name <COSMOS_ACCOUNT_NAME> --resource-group <RESOURCE_GROUP> --role-definition-name "CosmosDBCustomDataContributor" --scope "/" --principal-id <APP_PRINCIPAL_ID>

az cosmosdb sql role assignment create --account-name <COSMOS_ACCOUNT_NAME> --resource-group <RESOURCE_GROUP> --role-definition-name "CosmosDBCustomDataWriter" --scope "/" --principal-id <PRINCIPAL_ID>

# 6. Assign Storage Account roles
az role assignment create --role "Storage Blob Data Contributor" --assignee <APP_PRINCIPAL_ID> --scope /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/<RESOURCE_GROUP>/providers/Microsoft.Storage/storageAccounts/<STORAGE_ACCOUNT_NAME>

# 7. Verify role assignments
az role assignment list --assignee <APP_PRINCIPAL_ID> --scope /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/<RESOURCE_GROUP>/providers/Microsoft.Storage/storageAccounts/<STORAGE_ACCOUNT_NAME> --output table
```

## Code Changes Summary

### Files Modified

1. **`application/single_app/commands.txt`**
   - Replaced all hardcoded subscription IDs, resource groups, account names, and principal IDs with placeholders

2. **`cosmosdb-data-writer-role.json`**
   - Parameterized the `AssignableScopes` array with placeholders

3. **`cosmosdb-readmetadata-role.json`**
   - Parameterized the `AssignableScopes` array with placeholders

4. **`application/single_app/functions_documents.py`**
   - Changed hardcoded `STORAGE_ACCOUNT_URL` to use `os.environ.get("STORAGE_ACCOUNT_URL")`
   - Added validation to ensure the environment variable is set

5. **`application/single_app/route_backend_group_documents.py`**
   - Changed hardcoded `STORAGE_ACCOUNT_URL` (2 occurrences) to use `os.environ.get("STORAGE_ACCOUNT_URL")`
   - Added validation and error handling

6. **`application/external_apps/databaseseeder/artifacts/admin_settings.json`**
   - Replaced hardcoded endpoint URLs with placeholder text for sample configuration

## Verification

After deployment, verify the configuration:

1. Check environment variables are loaded:
   ```python
   import os
   print(os.environ.get("STORAGE_ACCOUNT_URL"))
   print(os.environ.get("AZURE_COSMOS_ENDPOINT"))
   ```

2. Verify role assignments:
   ```bash
   az cosmosdb sql role definition list --account-name <COSMOS_ACCOUNT_NAME> --resource-group <RESOURCE_GROUP>
   ```

3. Test BookStack document synchronization

## Troubleshooting

### Common Issues

1. **Missing environment variable errors**
   - Ensure all required environment variables are set in `.env`
   - Restart the application after updating `.env`

2. **Permission denied errors**
   - Verify role assignments are correctly configured
   - Check that managed identity is enabled and assigned

3. **Storage account connection failures**
   - Verify `STORAGE_ACCOUNT_URL` format is correct: `https://<account>.blob.core.windows.net`
   - Ensure network connectivity to Azure Storage

## Security Notes

- Never commit actual credentials, subscription IDs, or resource names to version control
- Use managed identities where possible instead of connection strings or keys
- Regularly rotate keys and secrets
- Follow the principle of least privilege when assigning roles

## Support

For issues or questions, please refer to the main project documentation or create an issue in the repository.
