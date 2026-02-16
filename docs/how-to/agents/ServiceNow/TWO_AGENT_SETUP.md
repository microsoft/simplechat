# ServiceNow Two-Agent Setup Guide (Advanced KB Management)

**Version:** 0.237.005 
**Implemented in version:** 0.237.005

## Overview

This guide describes the **advanced two-agent architecture** for organizations that need full knowledge base management capabilities in addition to standard incident management.

**Use this approach when you need:**
- ✅ Separate permissions for KB creation and publishing
- ✅ Different ServiceNow roles for support staff vs. KB managers
- ✅ Ability to import external articles to ServiceNow KB
- ✅ Workflow-based KB article approval (draft → review → published)

**For simpler single-agent setup (incidents + KB search only), see:**
- 📘 [SERVICENOW_INTEGRATION.md](SERVICENOW_INTEGRATION.md) - Recommended for most users

---

## Architecture

This setup uses **two ServiceNow agents** with different permission levels:

1. **ServiceNow Support Agent** - Incident management + KB search (read-only)
2. **ServiceNow KB Management Agent** - Full KB operations (search, create, publish)

Each agent uses a **separate ServiceNow integration user** with appropriate role assignments and **separate OAuth bearer tokens**.

---

## Agent 1: ServiceNow Support Agent

### Purpose
Primary agent for incident management and KB article searches.

### Capabilities
- ✅ Create, update, query incidents
- ✅ Get incident statistics
- ✅ Search KB articles (read-only)
- ✅ View KB article details
- ❌ Cannot create KB articles
- ❌ Cannot publish KB articles

### ServiceNow Integration User

**Username:** `servicenow_support_service`  
**Required ServiceNow Roles:**
- `itil` - Standard ITIL user access (basic incident read/write)
- `knowledge` - KB article read access
- `rest_api_explorer` - REST API access

**Optional Role for Enhanced Permissions:**
- `incident_manager` - Adds ability to:
  - Assign incidents to any user/group
  - Close and resolve any incident
  - View all incidents across the organization
  - Escalate incidents
  - Modify incident assignments and ownership
  - Access incident analytics and reporting

**Note:** For API-based incident operations, `itil` role is usually sufficient. Add `incident_manager` only if the agent needs to manage incidents assigned to other users.

**Permissions:**
- Read/Write: `incident` table
- Read: `kb_knowledge` table (published articles only)
- Read: `kb_category` table
- Read: `kb_knowledge_base` table

### Authentication
- **Type:** Bearer Token (OAuth 2.0)
- **Token Endpoint:** `https://YOUR-INSTANCE.service-now.com/oauth_token.do`
- **Grant Type:** Resource Owner Password Credentials

### Actions Configuration

**Action 1: Manage Incidents**
- OpenAPI Spec: `sample_servicenow_incident_api.yaml`
- Operations: queryIncidents, createIncident, getIncidentDetails, updateIncident, getIncidentStats
- Uses: `servicenow_support_service` credentials

**Action 2: Search Knowledge Base**
- OpenAPI Spec: `sample_now_knowledge_search_spec.yaml`
- Operations: searchKnowledgeFacets, getKnowledgeArticle
- Uses: `servicenow_support_service` credentials

### Agent Instructions
- File: `servicenow_agent_instructions.txt`
- Location: `docs/how-to/agents/ServiceNow/`

### Available To
- All users (standard support staff)
- Primary agent for incident handling

---

## Agent 2: ServiceNow KB Management Agent

### Purpose
Specialized agent for knowledge base article management.

### Capabilities
- ✅ Search KB articles
- ✅ View KB article details
- ✅ Create new KB articles from external URLs
- ✅ Publish draft articles
- ✅ Update existing articles
- ✅ Retire outdated articles
- ❌ Cannot manage incidents (use Support Agent for that)

### ServiceNow Integration User

**Username:** `simplechat6_servicenow_kb_manager`  
**Required ServiceNow Roles:**
- `itil` - Standard ITIL user access
- `knowledge` - KB article contributor access
- `knowledge_manager` - Full KB management permissions (create, publish, retire)
- `knowledge_admin` - Elevated permissions to bypass ACL constraints for approval workflow
- `rest_api_explorer` - REST API access

**Why Both knowledge_manager AND knowledge_admin?**
- `knowledge_manager` alone allows KB management but may be blocked by ACL (separation of duties)
- `knowledge_admin` provides elevated permissions for KB operations
- **Note:** When approval workflow is enabled, publishing still requires manual portal interaction (see troubleshooting section)

**Permissions:**
- Read: `kb_knowledge` table (all states: draft, review, published, retired)
- Create: `kb_knowledge` table
- Update: `kb_knowledge` table (including workflow_state changes)
- Read: `kb_category` table
- Read: `kb_knowledge_base` table

### Authentication
- **Type:** Bearer Token (OAuth 2.0) - **SEPARATE TOKEN**
- **Token Endpoint:** `https://YOUR-INSTANCE.service-now.com/oauth_token.do`
- **Grant Type:** Resource Owner Password Credentials

### Actions Configuration

**Action 1: Search Knowledge Base**
- OpenAPI Spec: `sample_now_knowledge_search_spec.yaml`
- Operations: searchKnowledgeFacets, getKnowledgeArticle
- Uses: `simplechat6_servicenow_kb_manager` credentials

**Action 2: Create Knowledge Articles**
- OpenAPI Spec: `sample_now_knowledge_create_spec.yaml`
- Operations: createKnowledgeArticle
- Uses: `simplechat6_servicenow_kb_manager` credentials

**Action 3: Publish Knowledge Articles**
- OpenAPI Spec: `sample_now_knowledge_publish_spec.yaml`
- Operations: updateKnowledgeArticle
- Uses: `simplechat6_servicenow_kb_manager` credentials

**Plugin: SmartHttpPlugin** (globally enabled by default)
- Enabled via: Admin Settings → "Enable HTTP Action" (enabled by default)
- Operation: get_web_content
- Used to fetch content from external URLs before creating KB articles
- No separate action configuration needed - available to all agents when globally enabled

### Agent Instructions
- File: `servicenow_kb_management_agent_instructions.txt`
- Location: `docs/how-to/agents/ServiceNow/`

### Available To
- Knowledge managers only
- Users who need to create and publish KB articles

---

## Setup Steps

### Step 1: Create ServiceNow Integration Users

#### User 1: Support Agent Service Account

```
1. Log into ServiceNow as admin
2. Navigate to: User Administration > Users
3. Click "New"
4. Fill in:
   - User ID: servicenow_support_service
   - First name: ServiceNow Support
   - Last name: Service Account
   - Email: servicenow-support@your-domain.com
   - Active: ✓
5. Click "Submit"
6. Open the user record
7. Go to "Roles" tab
8. Add roles: itil, incident_manager
9. Save
```

#### User 2: KB Manager Service Account

```
1. Log into ServiceNow as admin
2. Navigate to: User Administration > Users
3. Click "New"
4. Fill in:
   - User ID: simplechat6_servicenow_kb_manager
   - First name: ServiceNow KB Manager
   - Last name: Service Account
   - Email: servicenow-kb@your-domain.com
   - Active: ✓
   - Password needs reset: ☐ UNCHECK THIS (important for API access)
5. Click "Submit"
6. Set Password:
   - Right-click the header bar > "Set Password"
   - Enter a secure password
   - Save the password for OAuth token generation
7. Open the user record
8. Go to "Roles" tab
9. Add roles: knowledge_manager, knowledge_admin, knowledge, itil, rest_api_explorer
10. Save

**Note:** The `knowledge_admin` role is required in addition to `knowledge_manager` to bypass ACL constraints and enable fully automated approval workflow.
```

---

### Step 2: Generate OAuth Tokens

> **📘 For detailed OAuth token generation instructions, see: [SERVICENOW_OAUTH_SETUP.md](SERVICENOW_OAUTH_SETUP.md)**
>
> The OAuth setup guide provides:
> - Complete OAuth application configuration in ServiceNow
> - Token generation using cURL, PowerShell, and Python
> - Token refresh procedures
> - Troubleshooting common OAuth issues

#### Token 1: Support Agent

Generate OAuth token for `servicenow_support_service` user:
- **Username:** servicenow_support_service
- **Client ID:** Your OAuth application client ID
- **Client Secret:** Your OAuth application client secret
- **Password:** Service account password

**Save the access token** - You'll need it for the Support Agent action configuration.

#### Token 2: KB Manager

Generate OAuth token for `simplechat6_servicenow_kb_manager` user:
- **Username:** simplechat6_servicenow_kb_manager
- **Client ID:** Your OAuth application client ID
- **Client Secret:** Your OAuth application client secret
- **Password:** Service account password

**Save the access token** - You'll need it for the KB Manager Agent action configuration.

---

### Step 3: Configure Agent 1 (ServiceNow Support Agent)

#### In Simple Chat Admin:

```
1. Navigate to: Admin > Personal Agents
2. Click "Create New Agent"
3. Fill in:
   - Name: ServiceNow Support Agent
   - Display Name: ServiceNow Support
   - Description: Incident management and KB article searches
   - Instructions: [Upload servicenow_agent_instructions.txt]
   
4. Add Action 1:
   - Name: Manage Incidents
   - Type: OpenAPI Plugin
   - Upload Spec: sample_servicenow_incident_api.yaml
   - Authentication Type: Bearer Token
   - Token: TOKEN_FOR_SUPPORT_AGENT
   
5. Add Action 2:
   - Name: Search Knowledge Base
   - Type: OpenAPI Plugin
   - Upload Spec: sample_now_knowledge_search_spec.yaml
   - Authentication Type: Bearer Token
   - Token: TOKEN_FOR_SUPPORT_AGENT
   
6. Model: gpt-4o (recommended)
7. Availability: All Users
8. Save
```

---

### Step 4: Configure Agent 2 (ServiceNow KB Management Agent)

#### In Simple Chat Admin:

```
1. Navigate to: Admin > Personal Agents
2. Click "Create New Agent"
3. Fill in:
   - Name: ServiceNow KB Management Agent
   - Display Name: ServiceNow KB Manager
   - Description: Create and publish knowledge base articles from external URLs or direct content, search KB articles, and manage article lifecycle
   - Instructions: [Upload servicenow_kb_management_agent_instructions.txt]
   
4. Add Action 1 - Search Knowledge Base:
   - Name: Search Knowledge Base
   - Description: Search and retrieve knowledge base articles
   - Type: OpenAPI Plugin
   - Upload Spec: sample_now_knowledge_search_spec.yaml
   - Authentication Type: Bearer Token
   - Token: TOKEN_FOR_KB_MANAGER

5. Add Action 2 - Create Knowledge Articles:
   - Name: Create Knowledge Articles
   - Description: Create new draft knowledge base articles from external content
   - Type: OpenAPI Plugin
   - Upload Spec: sample_now_knowledge_create_spec.yaml
   - Authentication Type: Bearer Token
   - Token: TOKEN_FOR_KB_MANAGER

6. Add Action 3 - Publish Knowledge Articles:
   - Name: Publish Knowledge Articles
   - Description: Update and publish knowledge articles to make them visible to end users
   - Type: OpenAPI Plugin
   - Upload Spec: sample_now_knowledge_publish_spec.yaml
   - Authentication Type: Bearer Token
   - Token: TOKEN_FOR_KB_MANAGER
   
7. Verify SmartHttpPlugin is enabled:
   - Navigate to: Admin Settings → Plugins
   - Ensure "Enable HTTP Action" is checked (enabled by default)
   - This provides the get_web_content() function for fetching external URLs
   
8. Model: gpt-4o (recommended)
9. Availability: Knowledge Managers Only (configure user groups)
10. Save
```

---

## Usage Examples

### Example 1: Support Agent - Search KB and Create Incident

**User to Support Agent:**
```
"Search for email configuration KB articles and create an incident 
for user John Doe who can't configure Outlook"
```

**Agent Executes:**
1. searchKnowledgeFacets(query="email configuration")
2. createIncident(description="Email configuration issue", assigned_to="John Doe")

**Agent Response:**
```
Found 3 KB articles about email configuration:

KB0011 - Configure email settings in Microsoft 365
https://YOUR-INSTANCE.service-now.com/now/knowledge-center/kb_view/kb_knowledge/abc123

✅ Incident INC0012345 created successfully.

Priority: 3 - Moderate
Assigned to: John Doe
Category: Email
Status: New

Related KB articles have been added to the incident notes.
```

---

### Example 2: KB Manager - Create and Publish Article

**User to KB Manager:**
```
"Add this Microsoft article to ServiceNow KB:
https://support.microsoft.com/en-us/office/configure-email-settings"
```

**Agent Executes:**
1. SmartHttpPlugin.get_web_content(url="https://support.microsoft.com...")
2. createKnowledgeArticle(content=extracted, workflow_state="draft")

**Agent Response:**
```
✅ Knowledge article KB0001234 created successfully in draft state.

**Article Details:**
- Title: Configure email settings in Microsoft 365
- Knowledge Base: IT
- Category: Operating Systems
- Type: How-to guide
- Source: https://support.microsoft.com/en-us/office/configure-email-settings
- Content: 5,247 characters

**Review & Publish:**
https://YOUR-INSTANCE.service-now.com/now/knowledge-center/kb_view/kb_knowledge/abc123xyz789

📝 The article is in draft state. To publish:
1. Click the link above to open the article
2. Click the "Publish" button in ServiceNow portal
3. An approval request will be created for the designated approver
4. Once approved, the article will be published automatically
```

---

### Example 3: KB Manager - Publish Existing Draft

**User to KB Manager:**
```
"Publish KB article KB0001234"
```

**Agent Executes:**
1. searchKnowledgeFacets(query="number=KB0001234")
2. getKnowledgeArticle(sys_id="abc123") - verify current state

**Agent Response:**
```
KB article KB0001234 is ready for publication, but requires manual submission via the ServiceNow portal.

**Why Manual Submission Required:**
Your ServiceNow instance has the 'Knowledge - Approval Publish' workflow enabled, which requires using the portal's Publish button to trigger the approval process. The API cannot initiate this workflow directly.

**To Submit for Approval:**
1. Go to the article: https://YOUR-INSTANCE.service-now.com/now/knowledge-center/kb_view/kb_knowledge/abc123xyz789
2. Click the "Publish" button (top right of the page)
3. The article will move from Draft → Review and create an approval request

**What Happens Next:**
- Workflow state changes to "Review"
- An approval request is created for a designated approver
- The article waits for manual approval before publication

Once you've clicked Publish, let me know and I can verify the article is in review state.
```

---

## Security Model

### Permission Separation

| Operation | Support Agent | KB Manager |
|-----------|---------------|------------|
| Search KB articles | ✅ Yes | ✅ Yes |
| View KB article details | ✅ Yes | ✅ Yes |
| Create incidents | ✅ Yes | ❌ No |
| Update incidents | ✅ Yes | ❌ No |
| Create KB articles | ❌ No | ✅ Yes |
| Publish KB articles | ❌ No | ✅ Yes |
| Update KB articles | ❌ No | ✅ Yes |
| Retire KB articles | ❌ No | ✅ Yes |

### Why Two Separate Integration Users?

1. **Least Privilege:** Each agent has only the permissions it needs
2. **Audit Trail:** Different service accounts show who did what in ServiceNow audit logs
3. **Security:** Support Agent cannot accidentally publish unapproved KB articles
4. **Compliance:** Enforces approval workflow (create draft → manager publishes)
5. **Token Isolation:** If one token is compromised, other agent remains secure

---

## Troubleshooting

### Problem: Support Agent Cannot Search KB Articles

**Symptoms:** 401 Unauthorized or 403 Forbidden when searching KB

**Solution:**
1. Verify `servicenow_support_service` has `itil` role in ServiceNow
2. Check bearer token is valid and not expired
3. Verify `sample_now_knowledge_search_spec.yaml` base URL matches your instance

---

### Problem: KB Manager Cannot Publish Articles

**Symptoms:** 403 Forbidden when calling updateKnowledgeArticle

**Solution:**
1. Verify `simplechat6_servicenow_kb_manager` has `knowledge_manager` role
2. Check that separate bearer token is configured (not using same token as Support Agent)
3. Verify article exists and is in valid state for publishing

---

### Problem: KB Article Shows Draft After Agent Reports Published

**Symptoms:** 
- Agent reports "✅ Knowledge article KB0010004 published successfully"
- ServiceNow portal still shows workflow_state = "Draft"
- Article not visible to end users

**Root Cause:** ServiceNow Knowledge Base has approval workflows enabled

**Solution:**

Your ServiceNow instance requires approval workflow: **Draft → Review → Published**

**Check if Approval Workflow is Enabled:**
1. Go to: Knowledge → Administration → Knowledge Bases
2. Open your KB (e.g., "IT")
3. Check fields:
   - **Publish flow** (e.g., "Knowledge - Approval Publish")
   - **Retire flow** (e.g., "Knowledge - Approval Retire")
4. If these are populated, approval workflow is required

**Fix Options:**

**Option 1: Use Portal-Based Publishing (Required when workflow is enabled)**
- The agent instructions (v0.237.005+) detect approval workflow and guide users accordingly
- Agent creates article in draft state via API ✓
- User clicks "Publish" button in ServiceNow portal (workflow requirement)
- Article moves to "Review" state and creates approval request
- Designated approver approves in portal
- Article automatically published once approved
- This is the ONLY workflow that works when "Knowledge - Approval Publish" workflow is enabled

**Option 2: Disable approval workflow (Non-production only)**
- Go to: Knowledge → Administration → Knowledge Bases
- Clear the "Publish flow" and "Retire flow" fields
- Allows direct API publishing (draft → published)
- Only recommended for development/testing environments

**Related Files:**
- Fix documentation: `docs/explanation/fixes/SERVICENOW_KB_APPROVAL_WORKFLOW_FIX.md`
- Agent instructions: `servicenow_kb_management_agent_instructions.txt`

---

### Problem: External URL Content Not Fetching

**Symptoms:** "Unable to fetch content from URL" error

**Solution:**
1. Verify SmartHttpPlugin action is configured for KB Manager agent
2. Check URL is accessible from Simple Chat server
3. Try simpler URL first (e.g., public Microsoft docs)
4. Check for firewall or proxy blocking external requests

---

## Maintenance

### Token Refresh

Bearer tokens expire after a period (typically 1 hour). 

> **📘 For token refresh procedures, see: [SERVICENOW_OAUTH_SETUP.md](SERVICENOW_OAUTH_SETUP.md)**

After obtaining a new token, update it in the agent action configuration in Simple Chat.

### Role Updates

If ServiceNow roles change:
1. Update integration user roles in ServiceNow
2. Regenerate OAuth token
3. Update token in Simple Chat agent configuration
4. Test agent operations

---

## Files Reference

### Agent Instructions
- `servicenow_agent_instructions.txt` - Support Agent (incidents + KB search)
- `servicenow_kb_management_agent_instructions.txt` - KB Manager (full KB operations)

### OpenAPI Specs
- `sample_servicenow_incident_api.yaml` - Incident management operations
- `sample_now_knowledge_search_spec.yaml` - KB search (read-only)
- `sample_now_knowledge_search_spec.yaml` - KB search operations
- `sample_now_knowledge_create_spec.yaml` - KB creation operations
- `sample_now_knowledge_publish_spec.yaml` - KB publish/update operations

### Documentation
- `KB_MULTI_ACTION_SETUP.md` - Original multi-action approach (reference)
- `TWO_AGENT_SETUP.md` - This file (recommended approach)

---

## Benefits of Two-Agent Approach

1. ✅ **Clear Separation:** Each agent has distinct purpose
2. ✅ **Better UX:** Users choose appropriate agent for their task
3. ✅ **Security:** Permission enforcement at ServiceNow API level
4. ✅ **Audit Trail:** Different service accounts for different operations
5. ✅ **Flexibility:** Easy to add more agents with different permission levels
6. ✅ **Scalability:** Can create specialized agents for other ServiceNow tables
7. ✅ **Token Security:** Separate tokens limit blast radius if one is compromised

---

## Next Steps

1. ✅ Create two ServiceNow integration users
2. ✅ Generate separate OAuth tokens
3. ✅ Configure Support Agent with incident + KB search actions
4. ✅ Configure KB Manager Agent with full KB management actions
5. ✅ Test both agents with sample scenarios
6. ✅ Train users on which agent to use for which tasks
7. ✅ Monitor ServiceNow audit logs for service account activity
