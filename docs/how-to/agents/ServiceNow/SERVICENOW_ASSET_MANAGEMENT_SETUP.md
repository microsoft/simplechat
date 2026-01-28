# ServiceNow Asset Management Agent Setup Guide

This guide walks through setting up a complete ServiceNow Asset Management agent with separate actions for querying, creating, updating, and deleting assets.

## Overview

The Asset Management agent uses **four separate actions** for different operations:
1. **Asset Query and Details** - Search and retrieve asset information
2. **Asset Creation** - Add new assets to ServiceNow
3. **Asset Update** - Modify existing asset records
4. **Asset Deletion** - Remove assets from the system

## Architecture

```
ServiceNow Asset Management Agent
├── Action 1: Query and Get Assets
├── Action 2: Create Assets
├── Action 3: Update Assets
└── Action 4: Delete Assets
```

### Scope: Core Asset Records (`alm_asset` table)

These actions manage **hardware asset records** directly in the `alm_asset` table - the core table containing actual assets (laptops, monitors, phones, servers, etc.).

**Your actions WILL handle:**
- ✅ Querying existing assets (by tag, model, location, status, assigned user)
- ✅ Creating new asset records directly
- ✅ Updating asset details (assignment, location, status, warranty)
- ✅ Deleting assets from the system

**Your actions will NOT handle (different tables/workflows):**
- ❌ Asset requests workflow (`ast_request` table) - Formal request/approval process for new assets
- ❌ Transfer orders (`alm_transfer_order` table) - Asset transfers between locations
- ❌ Stock orders/stockroom operations (`alm_stockroom_transfer` table) - Inventory replenishment

**Note:** To enable asset requests, transfer orders, or stock management capabilities, create additional actions targeting those specific ServiceNow tables. The current setup focuses on direct asset record management, which covers most asset management needs.

---

## Prerequisites: ServiceNow User and Authentication Setup

### ServiceNow Integration User

Create a dedicated ServiceNow service account for asset management operations.

**Username:** `servicenow_asset_manager`  
**Required ServiceNow Roles:**
- `itil` - Standard ITIL user access (includes basic asset read/write)
- `asset` - Asset management permissions (create, update, delete assets)
- `rest_api_explorer` - REST API access

**Optional Enhanced Permissions:**
- `admin` - Full administrative access (only if your organization requires elevated permissions for asset operations)

**Permissions:**
- Read/Write: `alm_asset` table (asset records)
- Read: `cmdb_model` table (asset models)
- Read: `cmn_location` table (locations)
- Read: `sys_user` table (user assignments)

### User Creation Steps

```
1. Log into ServiceNow as admin
2. Navigate to: User Administration > Users
3. Click "New"
4. Fill in:
   - User ID: servicenow_asset_manager
   - First name: ServiceNow Asset
   - Last name: Manager Service Account
   - Email: servicenow-assets@your-domain.com
   - Active: ✓
   - Password needs reset: ☐ UNCHECK THIS (important for API access)
5. Click "Submit"
6. Set Password:
   - Right-click the header bar > "Set Password"
   - Enter a secure password
   - Save the password for OAuth token generation
7. Open the user record
8. Go to "Roles" tab
9. Add roles: itil, asset, rest_api_explorer
10. Save
```

### Generate OAuth Bearer Token

> **📘 For complete OAuth token generation instructions, see: [SERVICENOW_OAUTH_SETUP.md](SERVICENOW_OAUTH_SETUP.md)**
>
> The OAuth setup guide provides:
> - OAuth application configuration in ServiceNow
> - Token generation using cURL, PowerShell, and Python
> - Token refresh procedures
> - Troubleshooting common OAuth issues

**Generate token for user:** `servicenow_asset_manager`

**Save the access token** - You'll need it when configuring each action in Step 1.

### Authentication Configuration for Actions

When creating each action (query, create, update, delete), use the same authentication:

**Authentication Type:** `key` (Bearer Token)  
**Key:** `Bearer YOUR_ACCESS_TOKEN`

**Important:** All four actions use the **same bearer token** from the `servicenow_asset_manager` user.

---

## Step 1: Create ServiceNow Actions

### Action 1: Query and Get Assets

**Action Name:** `servicenow_query_assets`  
**Display Name:** `ServiceNow - Query Assets`  
**Description:** `Query assets and retrieve asset details from ServiceNow`  
**Type:** `openapi`

**OpenAPI Specification:** See [servicenow_query_assets_openapi.json](servicenow_query_assets_openapi.json)

**Key Operations:**
- `queryAssets` - Search and filter assets with query parameters
- `getAssetDetails` - Retrieve full details for a specific asset by sys_id

**Endpoint:** `https://YOUR-INSTANCE.service-now.com/api/now`

**Authentication:**
- Type: `key`
- Key: `YOUR_BEARER_TOKEN`

---

### Action 2: Create Assets

**Action Name:** `servicenow_create_asset`  
**Display Name:** `ServiceNow - Create Asset`  
**Description:** `Create new assets in ServiceNow`  
**Type:** `openapi`

**OpenAPI Specification:** See [servicenow_create_asset_openapi.json](servicenow_create_asset_openapi.json)

**Key Operation:**
- `createAsset` - Create new asset with required fields (asset_tag, display_name)

**Required Fields:**
- `asset_tag` - Unique asset identifier
- `display_name` - Display name for the asset

**Optional Fields:** model, serial_number, assigned_to, location, install_status, purchase_date, warranty_expiration, cost, department, managed_by, owned_by, comments

**Endpoint:** `https://YOUR-INSTANCE.service-now.com/api/now`

---

### Action 3: Update Assets

**Action Name:** `servicenow_update_asset`  
**Display Name:** `ServiceNow - Update Asset`  
**Description:** `Update existing assets in ServiceNow`  
**Type:** `openapi`

**OpenAPI Specification:** See [servicenow_update_asset_openapi.json](servicenow_update_asset_openapi.json)

**Key Operation:**
- `updateAsset` - Update asset fields using PATCH method

**⚠️ CRITICAL:** Always query for sys_id first using asset_tag, then update

**Updatable Fields:** display_name, assigned_to, assignment_group, location, install_status, substatus, serial_number, warranty_expiration, cost, department, managed_by, owned_by, comments

**Endpoint:** `https://YOUR-INSTANCE.service-now.com/api/now`

---

### Action 4: Delete Assets

**Action Name:** `servicenow_delete_asset`  
**Display Name:** `ServiceNow - Delete Asset`  
**Description:** `Delete assets from ServiceNow`  
**Type:** `openapi`

**OpenAPI Specification:** See [servicenow_delete_asset_openapi.json](servicenow_delete_asset_openapi.json)

**Key Operation:**
- `deleteAsset` - Permanently delete an asset from ServiceNow

**⚠️ WARNING:** This is a destructive operation. Always confirm with user before deleting. Consider retiring assets (install_status=7) instead of deletion.

**⚠️ CRITICAL:** Query for sys_id first using asset_tag, then delete

**Endpoint:** `https://YOUR-INSTANCE.service-now.com/api/now`

---

## Step 2: Create Asset Management Agent

### Agent Configuration

**Agent Name:** `servicenow_asset_management`  
**Display Name:** `ServiceNow Asset Manager`  
**Description:** `AI agent for ServiceNow asset management - query, create, update, and delete assets`  
**Model:** `gpt-4o` or `gpt-4.1`

**Actions to Load:**
- `servicenow_query_assets`
- `servicenow_create_asset`
- `servicenow_update_asset`
- `servicenow_delete_asset`

### Agent Instructions File

Upload the agent instructions file: [servicenow_asset_management_agent_instructions.txt](servicenow_asset_management_agent_instructions.txt)

**Key Instruction Highlights:**
- No-narration execution pattern (execute silently, show results only)
- Critical two-call pattern for updates/deletes (query for sys_id first, then operate)
- Install status mappings (1=In use, 6=In stock, 7=Retired)
- Progressive search for large result sets
- Delete confirmation workflow (show details, wait for confirmation, then delete)
- Required field validation for asset creation
- Formatted response templates (markdown tables, success messages)

---

## Step 3: Testing the Setup

### Test Queries

1. **Query assets:**
   ```
   Show me all active assets
   ```

2. **Get asset details:**
   ```
   Get details for asset P1000234
   ```

3. **Create asset:**
   ```
   Create a new laptop asset:
   - Tag: P1000500
   - Display Name: Jane's Laptop
   - Model: Dell Latitude 5420
   - Assigned to: Jane Smith
   - Status: In stock
   ```

4. **Update asset:**
   ```
   Update asset P1000234 to assign it to Bob Johnson
   ```

5. **Delete asset:**
   ```
   Delete asset P1000999
   ```

---

## Common Issues and Solutions

### Issue: "Asset not found" when updating

**Solution:** Always query for sys_id first:
```
1. queryAssets(sysparm_query="asset_tag=P1000234")
2. Extract sys_id from result
3. updateAsset(sys_id="...", ...)
```

### Issue: Create fails with missing fields

**Solution:** Check required fields:
- `asset_tag` (required)
- `display_name` (required)

### Issue: Agent narrates instead of executing

**Solution:** Review agent instructions - ensure "DO NOT narrate" section is prominent.

---

## Advanced Configuration

### Custom Asset Fields

If your ServiceNow instance has custom fields, add them to the OpenAPI schema:

```json
"custom_field_name": {
  "type": "string",
  "description": "Custom field description"
}
```

### Asset Statistics

Add a statistics operation similar to incident stats:

```json
"/stats/alm_asset": {
  "get": {
    "operationId": "getAssetStats",
    "description": "Get asset statistics grouped by category, status, etc."
  }
}
```

---

## Files to Create

1. ✅ Four action manifests in Admin → Actions
2. ✅ Agent manifest in Admin → Agents
3. ✅ Agent instructions file: `servicenow_asset_management_agent_instructions.txt`
4. ✅ This README for reference

---

## Next Steps

1. Create the four actions in the admin interface
2. Create the asset management agent
3. Link the four actions to the agent
4. Upload the instructions file
5. Test with sample queries
6. Expand instructions based on your specific asset management workflows

---

**Questions or Issues?**

Refer to the ServiceNow API documentation for additional field definitions and query patterns:
https://developer.servicenow.com/dev.do#!/reference/api/vancouver/rest/c_TableAPI
