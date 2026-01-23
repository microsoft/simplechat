# ServiceNow Integration Guide

## Overview

This guide documents the integration between Simple Chat and ServiceNow, enabling AI-powered incident management, ticket analysis, and support operations through natural language prompts.

> **⚠️ Important - Work in Progress:**  
> This integration is under active development. **Check back regularly for updates** to the OpenAPI specifications and agent instructions. Unit testing of prompts is still in progress, so further changes to the spec files and agent instruction file are expected.

---

## Integration Architecture

**Approach:** Hybrid Integration
- **ServiceNow OpenAPI Actions** - Modular API integration for CRUD operations
- **ServiceNow Support Agent** - Specialized AI agent using those actions

---

## Prerequisites

### Simple Chat Requirements
- ✅ Agents enabled (`enable_semantic_kernel: True`)
- ✅ Workspace Mode enabled (`per_user_semantic_kernel: True`)
- ✅ Global Actions enabled
- ✅ Application restarted after enabling Workspace Mode

### ServiceNow Requirements
- [ ] ServiceNow Developer Instance (Zurich - Latest release recommended)
- [ ] Integration user with API access
- [ ] API credentials (Basic Auth or OAuth 2.0)

---

## Phase 1: ServiceNow Instance Setup

### Step 1: Request Developer Instance

1. Navigate to: https://developer.servicenow.com/
2. Click "Request an Instance"
3. Select **Zurich (Latest release)**
4. Click "Request"
5. Wait for instance provisioning (typically 2-5 minutes)

**You'll receive:**
```
Instance URL: https://devXXXXX.service-now.com
Admin Username: admin
Admin Password: [provided by ServiceNow]
```

### Step 2: Create Integration User

> **Note:** This step demonstrates basic authentication setup for initial testing. For production deployments using Bearer Token authentication, refer to "SERVICENOW_OAUTH_SETUP.md".

1. Log into your ServiceNow instance as admin
2. Navigate to: **User Administration** → **Users**
3. Click **New** to create integration user:
   ```
   Username: simplechat6_integration
   First Name: Simple
   Last Name: Chat Integration
   Email: [your email]
   Time Zone: [your timezone]
   ```

4. Assign Roles:
   - Navigate to **Roles** tab
   - Add roles:
     - `rest_api_explorer` - For REST API access
     - `itil` - For incident management
     - `knowledge` - For knowledge base access (optional)

5. Set Password:
   - Click **Set Password**
   - Create secure password
   - Save for later use

### Step 3: Test REST API Access

1. Navigate to: **System Web Services** → **REST** → **REST API Explorer**
2. URL: `https://devXXXXX.service-now.com/$restapi.do`
3. Select API: **Table API**
4. Select Table: **incident**
5. Click **Send** to test query
6. Verify you get JSON response with incident data

**Example successful response:**
```json
{
  "result": [
    {
      "number": "INC0000001",
      "short_description": "Test incident",
      "state": "1"
    }
  ]
}
```

---

## Phase 2: OpenAPI Specification

### ServiceNow API Endpoints

The integration uses two OpenAPI specification files that define all ServiceNow REST API operations:

#### 1. Incident Management API
**Files:** 
- **Bearer Token Auth:** `sample_servicenow_incident_api.yaml` (Recommended for production)
- **Basic Auth:** `sample_servicenow_incident_api_basicauth.yaml` (For testing only)

**Base URL:** `https://devXXXXX.service-now.com/api/now`

**Endpoints:**
- `GET /table/incident` - Query incidents with filters
- `POST /table/incident` - Create new incident
- `GET /table/incident/{sys_id}` - Get specific incident details
- `PATCH /table/incident/{sys_id}` - Update incident
- `GET /stats/incident` - Get incident statistics and aggregations

**Operations:**
- `queryIncidents` - Query incidents based on filters (state, priority, date range, etc.)
- `createIncident` - Create new incident with short_description, description, priority, etc.
- `getIncidentDetails` - Retrieve full details of specific incident by sys_id
- `updateIncident` - Update incident fields (state, work_notes, priority, assigned_to, etc.)
- `getIncidentStats` - Get aggregated statistics (count, averages, grouping by fields)

#### 2. Knowledge Base API
**Files:**
- **Bearer Token Auth:** `sample_now_knowledge_latest_spec.yaml` (Recommended for production)
- **Basic Auth:** `sample_now_knowledge_latest_spec_basicauth.yaml` (For testing only)

**Base URL:** `https://devXXXXX.service-now.com`

**Endpoints:**
- `GET /api/now/table/kb_knowledge` - Search knowledge base articles
- `GET /api/now/table/kb_knowledge/{sys_id}` - Get specific article details

**Operations:**
- `searchKnowledgeFacets` - Search knowledge articles with progressive fallback strategy
- `getKnowledgeArticle` - Retrieve full content of specific knowledge article

### OpenAPI Specification Files

**Locations:** `docs/how-to/agents/ServiceNow/open_api_specs/`

**Available Authentication Options:**

#### Bearer Token Authentication (Production)
- `sample_servicenow_incident_api.yaml` - Incident management with OAuth 2.0 bearer token
- `sample_now_knowledge_latest_spec.yaml` - Knowledge base search with OAuth 2.0 bearer token
- **Use these for:** Production deployments, secure enterprise environments
- **Setup guide:** See `SERVICENOW_OAUTH_SETUP.md` for OAuth configuration

#### Basic Authentication (Testing Only)
- `sample_servicenow_incident_api_basicauth.yaml` - Incident management with username:password
- `sample_now_knowledge_latest_spec_basicauth.yaml` - Knowledge base search with username:password
- **Use these for:** Initial testing, development instances, proof of concept
- **Security note:** Not recommended for production use

**Status:** ✅ Created and configured

**Key Features:**
- ✅ Both authentication methods supported (bearer token and basic auth)
- ✅ Comprehensive parameter documentation with detailed descriptions
- ✅ Critical usage patterns documented:
  - Progressive search strategy (fallback from exact phrase to broad keyword)
  - sys_id requirements and query-first patterns for updates
  - Field mapping for create/update operations
  - Work notes timing considerations (updates may take a few moments to appear)
- ✅ Query examples and common use case patterns
- ✅ Field descriptions, constraints, and validation rules
- ✅ State/priority/urgency enumerations documented
- ✅ Error handling guidance and status codes
- ✅ Pagination and filtering parameter examples
- ✅ ServiceNow-specific query syntax (encoded queries, operators)

> **⚠️ Important:** These OpenAPI specifications are continuously tested and refined based on real-world use cases, agent behavior analysis, and production feedback. Regular updates ensure optimal AI agent understanding and reliable API interactions.

---

## Phase 3: Simple Chat Configuration

### Step 1: Add ServiceNow Actions

> **Note:** This integration uses **two separate actions** because ServiceNow has distinct API endpoints for incident management and knowledge base operations, each with its own OpenAPI specification file.

1. Navigate to: **Admin Settings** → **Actions Configuration**
2. Click **"Add Action"**
3. **Select Action Type: OpenAPI**
   - ServiceNow REST APIs use OpenAPI/Swagger specifications
   - OpenAPI type supports: External API integration, HTTP/HTTPS requests, authentication, JSON payloads
   - Click **"Next"** after selecting OpenAPI

#### Action 1: Incident Management
```
Name: servicenow_manage_incident
Display Name: ServiceNow - Manage Incidents
Type: OpenAPI
Description: Complete incident management - query, create, update, retrieve details, and get statistics
OpenAPI Spec: [Upload sample_servicenow_incident_api.yaml or sample_servicenow_incident_api_basicauth.yaml]
Base URL: https://devXXXXX.service-now.com

Operations Included:
  - queryIncidents: Query/filter incidents with advanced search
  - createIncident: Create new incidents with all fields
  - getIncidentDetails: Retrieve full incident details by sys_id
  - updateIncident: Update incident state, assignments, work notes, etc.
  - getIncidentStats: Get aggregated statistics and metrics

Authentication Options:

Option A - Basic Auth (Testing Only):
  Auth Type: key
  Key: username:password (or use Key Vault reference)
  OpenAPI Spec File: sample_servicenow_incident_api_basicauth.yaml

Option B - OAuth Bearer Token (Recommended for Production):
  Auth Type: key
  Key: <oauth_access_token> (or use Key Vault reference)
  OpenAPI Spec File: sample_servicenow_incident_api.yaml
  See: SERVICENOW_OAUTH_SETUP.md for OAuth setup

Scope: Global or Group
```

**Repeat Step 1 for Knowledge Base Action:**

#### Action 2: Knowledge Base Search (Optional)
```
Name: servicenow_search_knowledge_base
Display Name: ServiceNow - Search Knowledge Base
Type: OpenAPI
Description: Search knowledge articles with progressive fallback and retrieve full article content
OpenAPI Spec: [Upload sample_now_knowledge_latest_spec.yaml or sample_now_knowledge_latest_spec_basicauth.yaml]
Base URL: https://devXXXXX.service-now.com

Operations Included:
  - searchKnowledgeFacets: Search KB articles with progressive search strategy
  - getKnowledgeArticle: Retrieve complete article content by sys_id

[Same auth config as above]

Scope: Global or Group
```

> **💡 Tip:** If you only need incident management without knowledge base search, you can skip Action 2 and configure your agent with only the `servicenow_manage_incident` action.

---

## Phase 4: Configure ServiceNow Agent

### Step 1: Create Agent

1. Navigate to: **Admin Settings** → **Agents Configuration**
2. Click **"Add Agent"**
3. Configure agent:

```
Name: servicenow_support_agent
Display Name: ServiceNow Support Agent
Description: AI agent for ServiceNow incident management and knowledge base operations

Instructions: [Copy from servicenow_agent_instructions.txt]

Model: gpt-4o (or your preferred model)
Scope: Global or Group
```

> **📄 Agent Instructions File:** 
> - **Location:** `docs/how-to/agents/ServiceNow/servicenow_agent_instructions.txt`
> - **Purpose:** Comprehensive behavioral instructions for the ServiceNow support agent
> - **Usage:** Copy the entire content from this file into the "Instructions" field when creating the agent
> 
> **⚠️ Important:** These instructions are continuously refined and tuned based on real-world use cases, agent behavior analysis, and production feedback. The file serves as a living reference that should be updated as new patterns emerge or edge cases are discovered. Regular review and updates ensure optimal agent performance and reliable ServiceNow interactions.

### Step 2: Attach Actions to Agent

1. Edit the ServiceNow Support Agent
2. Navigate to **Actions** tab
3. Select and attach:
   - ✅ servicenow_manage_incident
   - ✅ servicenow_search_knowledge_base
4. Save agent configuration

---

## Testing the Integration

### Test 1: Query Incidents
```
Prompt: "Show me open critical incidents created in the last 7 days"
```

Expected: Agent queries incidents with appropriate filters and displays results in table format.

### Test 2: Create Incident
```
Prompt: "Create an incident: Email server down for Finance team, priority High, assigned to John Doe"
```

Expected: Agent creates incident and returns incident number.

### Test 3: Update Incident
```
Prompt: "Update INC0010095 - add work note: Investigating email server logs"
```

Expected: Agent queries for sys_id, then updates with work note.

### Test 4: Search Knowledge Base
```
Prompt: "Find KB articles about email troubleshooting"
```

Expected: Agent searches KB and returns relevant articles with links.

---

## Phase 5: Testing

### Test Scenarios

#### Test 1: Query Recent Tickets
**Prompt:**
```
Show me all incidents created in the last 7 days
```

**Expected Behavior:**
- Agent uses servicenow_query_incidents action
- Filters by created_date >= 7 days ago
- Returns formatted table with results

**Status:** [ ] Tested

---

#### Test 2: Create New Ticket
**Prompt:**
```
Create a new incident:
- Description: Email server not responding for Finance department
- Urgency: High
- Priority: 2
- Category: Email
```

**Expected Behavior:**
- Agent confirms parameters
- Uses servicenow_create_incident action
- Returns new incident number (e.g., INC0010001)

**Status:** [ ] Tested

---

#### Test 3: Trend Analysis
**Prompt:**
```
What are the top 5 trending issues over the last 30 days?
Show incident counts for each category.
```

**Expected Behavior:**
- Agent queries incidents from last 30 days
- Groups by category
- Counts incidents per category
- Returns top 5 in table format

**Status:** [ ] Tested

---

#### Test 4: Support Team Analytics
**Prompt:**
```
Who is the most active support person in the last 30 days?
Show number of tickets resolved and average resolution time.
```

**Expected Behavior:**
- Agent queries incidents with resolved status
- Groups by assigned_to
- Calculates counts and averages
- Returns ranked list

**Status:** [ ] Tested

---

#### Test 5: Predictive Analysis
**Prompt:**
```
Analyze resolution entries over the last year and identify patterns.
What are the most common types of outages?
```

**Expected Behavior:**
- Agent queries historical data (1 year)
- Analyzes resolution notes and categories
- Identifies recurring patterns
- Provides recommendations

**Status:** [ ] Tested

---

## Security Best Practices

### Credential Management

**Option 1: Direct Password Entry (Quick Setup)**
- Enter ServiceNow password directly in action configuration
- Stored encrypted in Cosmos DB
- ⚠️ Less secure for production use

**Option 2: Azure Key Vault (Recommended)**
1. Store ServiceNow credentials in Azure Key Vault
2. Create secret: `servicenow-integration-password`
3. Reference in action config: `@keyvault:servicenow-integration-password`
4. Simple Chat automatically retrieves from Key Vault

**Status:** [ ] Credentials secured

### API User Permissions

**Least Privilege Principle:**
- [ ] Integration user has only required roles
- [ ] Read-only access for query actions
- [ ] Write access only for create/update actions
- [ ] No admin privileges

### Audit Logging

**Enable in ServiceNow:**
1. Navigate to **System Logs** → **System Log** → **REST Messages**
2. Enable logging for API calls
3. Monitor for unusual activity

**Status:** [ ] Audit logging configured

---

## Troubleshooting

### Common Issues

#### Issue: "Session not authenticated" or "Session expired" error

**Status:** ✅ **FIXED in version 0.235.026**

**Symptoms:**
- Agent responds: "I'm unable to access your ServiceNow incidents because your session is not authenticated"
- Direct API calls with same credentials work correctly
- Base URL is configured correctly

**Root Cause:**
This issue was caused by a mismatch between how the Simple Chat UI stores Basic Auth credentials (as `username:password` in a single field) and how the OpenAPI plugin expected them (as separate `username` and `password` fields).

**Solution:**
The fix is included in Simple Chat v0.235.026+. The OpenAPI plugin factory now automatically transforms the authentication format when loading actions, so no user action is required.

**For detailed technical information, see:** `docs/explanation/fixes/OPENAPI_BASIC_AUTH_FIX.md`

#### Issue: "Authentication failed" error
**Solution:**
- Verify username (simplechat6_integration) and password are correct
- Check integration user is active
- Confirm user has `rest_api_explorer` role
- Test credentials in REST API Explorer first
- Ensure Base URL is correct: `https://devXXXXX.service-now.com/api/now`

#### Issue: "No results returned" for queries
**Solution:**
- Check date filters are correct
- Verify table name is correct (incident, not incidents)
- Test query in ServiceNow REST API Explorer
- Check sysparm_query encoding

#### Issue: Agent not using ServiceNow actions
**Solution:**
- Verify actions are attached to agent
- Check actions are saved as "Global" scope
- Restart application after configuration changes
- Review agent instructions for clarity

#### Issue: "Rate limit exceeded" error
**Solution:**
- ServiceNow limits API calls per hour
- Developer instances: ~10,000 calls/hour
- Add delays between bulk operations
- Implement retry logic with exponential backoff

---

## Next Steps

### Completed
- [x] Understand integration approach
- [x] Choose ServiceNow instance (Zurich)

### In Progress
- [ ] Request ServiceNow developer instance
- [ ] Create integration user
- [ ] Test REST API access

### To Do
- [ ] Create OpenAPI specification
- [ ] Add ServiceNow actions in Simple Chat
- [ ] Create ServiceNow support agent
- [ ] Test all use cases
- [ ] Secure credentials with Key Vault
- [ ] Deploy to production

---

## Resources

### ServiceNow Documentation
- REST API Reference: https://developer.servicenow.com/dev.do#!/reference/api/latest/rest
- Table API Guide: https://docs.servicenow.com/bundle/latest/page/integrate/inbound-rest/concept/c_TableAPI.html
- Developer Portal: https://developer.servicenow.com/

### Simple Chat Documentation
- Actions Configuration: `docs/admin_configuration.md`
- Agent Creation: `docs/features.md`
- API Integration: `docs/explanation/features/`

---

## Appendix

### ServiceNow Query Syntax Examples

**Last 7 days:**
```
sysparm_query=sys_created_onONLast 7 days@javascript:gs.daysAgoStart(7)
```

**By priority:**
```
sysparm_query=priority=1
```

**By state (resolved):**
```
sysparm_query=state=6
```

**Combined filters:**
```
sysparm_query=priority=1^state=1^sys_created_onONLast 30 days@javascript:gs.daysAgoStart(30)
```

### Sample Prompts for ServiceNow Actions

Use these prompts with the ServiceNow Support Agent to test and demonstrate functionality:

#### Query Incidents (servicenow_query_incidents)

**Basic queries:**
- "Show me all open incidents"
- "List incidents created in the last 7 days"
- "What incidents are currently in progress?"
- "Show me all critical priority incidents"
- "Find all incidents assigned to the Finance department"

**Advanced queries:**
- "Show me high priority incidents from last month that are still unresolved"
- "List all email-related incidents created in the last 2 weeks"
- "What incidents were opened yesterday with priority 1 or 2?"
- "Find all network incidents assigned to IT Support team"
- "Show me the most recent 20 incidents sorted by creation date"

**Analytics and trends:**
- "What are the top 10 most common incident categories this month?"
- "How many incidents were created each day last week?"
- "Show me incident volume by priority for the last 30 days"
- "What's the average resolution time for critical incidents?"
- "Which category has the most unresolved incidents?"

#### Create Incident (servicenow_create_incident)

**Simple creation:**
- "Create a new incident: Email server is down for Marketing team"
- "Log a ticket: Users can't access the VPN, high urgency"
- "Open an incident for printer not working in conference room A"

**Detailed creation:**
- "Create a critical incident: Database server crashed, all users affected, need immediate attention"
- "Log a new ticket with the following details:
  - Description: Password reset portal showing error 500
  - Priority: High
  - Category: Security
  - Urgency: High
  - Impact: Medium"

**Template-based:**
- "Create an email server outage incident with high priority"
- "Open a standard network connectivity ticket for Building 2, Floor 3"
- "Log a hardware failure incident for laptop replacement"

#### Get Incident Details (servicenow_get_incident)

**By incident number:**
- "Show me details for incident INC0010001"
- "What's the status of ticket INC0010025?"
- "Get full details for incident INC0000157"
- "Show me the complete information for INC0010010"

**Follow-up queries:**
- "What's the current status of the email server incident we created earlier?"
- "Show me all the work notes for incident INC0010005"
- "Has incident INC0010015 been assigned to anyone yet?"
- "When was INC0010020 last updated?"

#### Update Incident (servicenow_update_incident)

**Status updates:**
- "Mark incident INC0010001 as resolved"
- "Update INC0010025 status to In Progress"
- "Close incident INC0010005 with resolution: Issue resolved by restarting service"
- "Put incident INC0010010 on hold"

**Assignment updates:**
- "Assign incident INC0010001 to John Smith"
- "Reassign INC0010025 to the Network Support team"
- "Change the assigned user for INC0010005"

**Work notes:**
- "Add work note to INC0010001: Investigating email server logs, found connection timeout"
- "Update INC0010025 with note: Contacted vendor for support"
- "Add comment to INC0010010: Waiting for user response"

**Priority changes:**
- "Increase priority of INC0010001 to Critical"
- "Lower the urgency of INC0010025 to Medium"
- "Change INC0010005 priority to 2"

#### Get Statistics (servicenow_get_stats)

**Volume metrics:**
- "How many incidents were created last month?"
- "What's the total incident count by category for this year?"
- "Show me incident volume trends for the last 6 months"
- "How many critical incidents were opened this week?"

**Performance metrics:**
- "What's the average resolution time for incidents last month?"
- "Show me the mean time to resolve by category"
- "What percentage of incidents are resolved within SLA?"
- "Calculate the average time to first response"

**Team analytics:**
- "Show me incident counts by assigned user for last 30 days"
- "Which support team resolved the most incidents this quarter?"
- "What's the workload distribution across support groups?"
- "Who has the fastest average resolution time?"

**Categorical analysis:**
- "Break down incident counts by priority for last month"
- "Show me the distribution of incidents by state"
- "What categories have the highest incident volume?"
- "Compare email vs network incident counts for Q4"

#### Search Knowledge Base (servicenow_search_kb)

**Solution searches:**
- "Search the knowledge base for email configuration guides"
- "Find articles about VPN connection troubleshooting"
- "Look up password reset procedures in the KB"
- "Search for solutions to 'server not responding' errors"

**Category searches:**
- "Show me all knowledge articles in the Email category"
- "Find network troubleshooting guides"
- "List all hardware setup articles"
- "Show me security-related KB articles"

**Problem-specific:**
- "Find KB articles about printer connectivity issues"
- "Search for documentation on how to reset user passwords"
- "Look up articles about 'Error 500' messages"
- "Find guides for setting up mobile email access"

**Recent/popular:**
- "What are the most viewed knowledge articles this month?"
- "Show me recently updated KB articles"
- "Find the top 10 most helpful articles"
- "List new knowledge articles from the last 30 days"

#### Complex Multi-Action Workflows

**Incident creation with KB lookup:**
- "Users are reporting email server issues. Search the knowledge base for solutions and if none exist, create a new incident."

**Trend analysis with knowledge suggestions:**
- "What are the top 5 recurring issues this month? For each, suggest relevant knowledge articles."

**Incident lifecycle:**
- "Show me all unresolved incidents from last week. For those older than 5 days, add a work note asking for status update."

**Support quality check:**
- "Find all incidents closed yesterday. Check if resolution notes reference knowledge articles. Report which ones are missing KB references."

**Proactive support:**
- "Analyze incidents from the last 90 days. Identify the top 3 issues that don't have knowledge articles, and suggest creating documentation for them."

#### Natural Language Queries (Advanced Agent Capabilities)

- "I need help with the laptop that won't connect to WiFi"
  - Agent creates incident with user's details
  - Searches KB for WiFi troubleshooting
  - Provides step-by-step guide
  - Tracks incident until resolved

- "Show me everything related to the email outage last Tuesday"
  - Agent queries incidents from that date
  - Filters by email category
  - Shows timeline of events
  - Provides resolution summary

- "Create a monthly support report for my manager"
  - Agent gathers statistics for last month
  - Calculates key metrics (volume, resolution time, SLA)
  - Identifies trends and patterns
  - Formats professional summary

- "What's our biggest support challenge right now?"
  - Agent analyzes recent incident data
  - Identifies high-volume categories
  - Calculates resolution times
  - Highlights recurring problems
  - Suggests improvements

---

**Tip:** Start with simple queries to verify actions are working, then progress to more complex multi-action workflows. The ServiceNow Support Agent can combine multiple actions intelligently based on your natural language requests.

### Useful ServiceNow Fields

**Incident Table Fields:**
- `number` - Incident number (INC0000001)
- `short_description` - Brief title
- `description` - Detailed description
- `priority` - 1-5 (1=Critical, 5=Planning)
- `urgency` - 1-3 (1=High, 3=Low)
- `state` - 1=New, 2=In Progress, 6=Resolved, 7=Closed
- `assigned_to` - Assigned user
- `category` - Incident category
- `sys_created_on` - Created timestamp
- `sys_updated_on` - Updated timestamp
- `resolved_at` - Resolution timestamp
- `sys_id` - Unique identifier

---

**Last Updated:** January 21, 2026
**Status:** Initial Draft - In Progress
