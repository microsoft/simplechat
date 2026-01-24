# Group Agent Loading Fix

## Header Information

**Fix Title:** Group Agents Not Loading in Per-User Semantic Kernel Mode  
**Issue Description:** Group agents and their associated actions were not being loaded when per-user semantic kernel mode was enabled, causing group agents to fall back to global agents and resulting in zero plugins/actions available.  
**Root Cause:** The `load_user_semantic_kernel()` function only loaded personal agents and global agents (when merge enabled), but completely omitted group agents from groups the user is a member of.  
**Fixed/Implemented in version:** **0.236.012** (matches `config.py` `app.config['VERSION']`)  
**Date:** January 22, 2026  

## Problem Statement

### Symptoms
When a user selected a group agent in per-user semantic kernel mode:
- The agent selection would fall back to the global "researcher" agent
- Plugin count would be zero (`plugin_count: 0, plugins: []`)
- Agent would ask clarifying questions instead of executing available actions
- No group agents appeared in the available agents list
- Group actions (plugins) were not accessible even though they existed in the database

### Impact
- **Severity:** High - Group agents completely non-functional in per-user kernel mode
- **Affected Users:** All users with per-user semantic kernel enabled who are members of groups
- **Workaround:** None - only global agents worked

### Evidence from Logs
```
[SK Loader] User settings found 1 agents for user 'f016493e-9395-4120-91b5-bac4276b6b6c'
[SK Loader] Found 2 global agents to merge
[SK Loader] After merging: 3 total agents
[DEBUG] [INFO]: [SK Loader] Merged agents: [('researcher', True), ('servicenow_test_agent', True), ('researcher', False)]
[DEBUG] [INFO]: [SK Loader] Looking for agent named 'cio6_servicenow_test_agent' with is_global=False
[DEBUG] [INFO]: [SK Loader] User NO agent found matching user-selected agent: cio6_servicenow_test_agent
[SK Loader] User f016493e-9395-4120-91b5-bac4276b6b6c No agent found matching user-selected agent: cio6_servicenow_test_agent
```

Notice: Only 3 agents loaded (2 global + 1 personal), **zero group agents** despite user being member of group "cio6".

## Root Cause Analysis

### Architectural Gap
The `load_user_semantic_kernel()` function in `semantic_kernel_loader.py` had the following loading sequence:

1. ✅ Load personal agents via `get_personal_agents(user_id)`
2. ✅ Conditionally merge global agents if `merge_global_semantic_kernel_with_workspace` enabled
3. ❌ **MISSING:** Load group agents from user's group memberships
4. ✅ Load personal actions via `get_personal_actions(user_id)`
5. ✅ Conditionally merge global actions if merge enabled
6. ❌ **MISSING:** Load group actions from user's group memberships

### Why It Was Missed
The code had logic to load a **single selected group agent** if explicitly requested, but this was:
- Only triggered when a specific group agent was pre-selected
- Required explicit group ID resolution
- Did not load **all** group agents from user's memberships
- Failed to load group agents proactively for selection

This created a chicken-and-egg problem: the agent couldn't be selected because it wasn't loaded, and it wasn't loaded unless it was selected.

## Technical Details

### Files Modified
1. **`semantic_kernel_loader.py`** (Lines ~1155-1250)
   - Added group agent loading after personal agents
   - Added group action loading after personal actions
   - Removed redundant single-agent loading logic

2. **`config.py`** (Line 91)
   - Updated VERSION from "0.235.026" to "0.235.027"

### Code Changes

#### Before (Pseudocode)
```python
agents_cfg = get_personal_agents(user_id)
# Mark personal agents
for agent in agents_cfg:
    agent['is_global'] = False

# Only try to load ONE selected group agent if explicitly requested
if selected_agent_is_group:
    # Complex logic to find and add single group agent
    
# Merge global agents if enabled
if merge_global:
    # Add global agents

# Load personal actions only
plugin_manifests = get_personal_actions(user_id)
```

#### After (Pseudocode)
```python
agents_cfg = get_personal_agents(user_id)
# Mark personal agents
for agent in agents_cfg:
    agent['is_global'] = False
    agent['is_group'] = False

# Load ALL group agents from user's group memberships
user_groups = get_user_groups(user_id)
for group in user_groups:
    group_agents = get_group_agents(group_id)
    for group_agent in group_agents:
        # Mark and add to agents_cfg
        group_agent['is_global'] = False
        group_agent['is_group'] = True
        group_agent['group_id'] = group_id
        group_agent['group_name'] = group_name
        agents_cfg.append(group_agent)

# Merge global agents if enabled (unchanged)
if merge_global:
    # Add global agents

# Load personal actions
plugin_manifests = get_personal_actions(user_id)

# Load ALL group actions from user's group memberships
for group in user_groups:
    group_actions = get_group_actions(group_id)
    plugin_manifests.extend(group_actions)
```

### Key Implementation Details

**Group Agent Loading:**
```python
from functions_group import get_user_groups
from functions_group_agents import get_group_agents

user_groups = []  # Initialize to empty list
try:
    user_groups = get_user_groups(user_id)
    print(f"[SK Loader] User '{user_id}' is a member of {len(user_groups)} groups")
    
    group_agent_count = 0
    for group in user_groups:
        group_id = group.get('id')
        group_name = group.get('name', 'Unknown')
        if group_id:
            group_agents = get_group_agents(group_id)
            for group_agent in group_agents:
                group_agent['is_global'] = False
                group_agent['is_group'] = True
                group_agent['group_id'] = group_id
                group_agent['group_name'] = group_name
                agents_cfg.append(group_agent)
                group_agent_count += 1
            print(f"[SK Loader] Loaded {len(group_agents)} agents from group '{group_name}' (id: {group_id})")
    
    if group_agent_count > 0:
        log_event(f"[SK Loader] Loaded {group_agent_count} group agents from {len(user_groups)} groups for user '{user_id}'", level=logging.INFO)
except Exception as e:
    log_event(f"[SK Loader] Error loading group agents for user '{user_id}': {e}", {"error": str(e)}, level=logging.ERROR, exceptionTraceback=True)
    user_groups = []  # Reset to empty on error
```

**Group Action Loading:**
```python
# Load group actions from all groups the user is a member of
try:
    group_action_count = 0
    for group in user_groups:
        group_id = group.get('id')
        group_name = group.get('name', 'Unknown')
        if group_id:
            group_actions = get_group_actions(group_id, return_type=SecretReturnType.NAME)
            plugin_manifests.extend(group_actions)
            group_action_count += len(group_actions)
            print(f"[SK Loader] Loaded {len(group_actions)} actions from group '{group_name}' (id: {group_id})")
    
    if group_action_count > 0:
        log_event(f"[SK Loader] Loaded {group_action_count} group actions from {len(user_groups)} groups for user '{user_id}'", level=logging.INFO)
except Exception as e:
    log_event(f"[SK Loader] Error loading group actions for user '{user_id}': {e}", {"error": str(e)}, level=logging.ERROR, exceptionTraceback=True)
```

### Functions Used
- **`get_user_groups(user_id)`** - Returns all groups where user is a member (from `functions_group.py`)
- **`get_group_agents(group_id)`** - Returns all agents for a specific group (from `functions_group_agents.py`)
- **`get_group_actions(group_id, return_type)`** - Returns all actions/plugins for a specific group (from `functions_group_actions.py`)

### Error Handling
- Both group agent and group action loading are wrapped in try-except blocks
- Errors are logged with full exception tracebacks
- On error, `user_groups` is reset to empty list to prevent downstream issues
- System gracefully degrades to personal + global agents if group loading fails

## Validation

### Test Scenario
1. **Setup:**
   - User `f016493e-9395-4120-91b5-bac4276b6b6c` is member of group `cio6` (ID: `72254e24-4bc6-4680-bc2e-c56d5214d8e8`)
   - Group has agent `cio6_servicenow_test_agent` with action `cio6_servicenow_query_incidents`
   - Per-user semantic kernel mode enabled
   - Global agent merging enabled

2. **User Action:**
   - User selects group agent `cio6_servicenow_test_agent`
   - User submits message: "Show me all ServiceNow incidents"

### Before Fix - Failure Behavior
```
[SK Loader] User settings found 1 agents for user 'f016493e-9395-4120-91b5-bac4276b6b6c'
[SK Loader] After merging: 3 total agents  # Only personal + global
[SK Loader] Looking for agent named 'cio6_servicenow_test_agent' with is_global=False
[SK Loader] User NO agent found matching user-selected agent: cio6_servicenow_test_agent
[SK Loader] selected_agent fallback to first agent: researcher  # ❌ Wrong agent
[Enhanced Agent Citations] Extracted 0 detailed plugin invocations  # ❌ No actions
{'agent': 'researcher', 'plugin_count': 0}  # ❌ Zero plugins
```

**Result:** Agent asks clarifying questions instead of querying ServiceNow.

### After Fix - Success Behavior
```
[SK Loader] User settings found 1 personal agents for user 'f016493e-9395-4120-91b5-bac4276b6b6c'
[SK Loader] User 'f016493e-9395-4120-91b5-bac4276b6b6c' is a member of 1 groups  # ✅ Groups detected
[SK Loader] Loaded 1 agents from group 'cio6' (id: 72254e24-4bc6-4680-bc2e-c56d5214d8e8)  # ✅ Group agent loaded
[SK Loader] Loaded 1 group agents from 1 groups for user 'f016493e-9395-4120-91b5-bac4276b6b6c'  # ✅ Success
[SK Loader] Total agents loaded: 2 (personal + group) for user 'f016493e-9395-4120-91b5-bac4276b6b6c'
[SK Loader] After merging: 4 total agents  # ✅ Includes group agent
[SK Loader] Merged agents: [('researcher', True), ('servicenow_test_agent', True), ('researcher', False), ('cio6_servicenow_test_agent', False)]  # ✅ Group agent present
[SK Loader] Loaded 1 actions from group 'cio6' (id: 72254e24-4bc6-4680-bc2e-c56d5214d8e8)  # ✅ Group action loaded
[SK Loader] Loaded 1 group actions from 1 groups for user 'f016493e-9395-4120-91b5-bac4276b6b6c'  # ✅ Success
[SK Loader] User f016493e-9395-4120-91b5-bac4276b6b6c Found EXACT match for agent: cio6_servicenow_test_agent (is_global=False)  # ✅ Agent found
[SK Loader] Plugin cio6_servicenow_query_incidents: SUCCESS  # ✅ Plugin loaded
```

**Result:** Correct group agent selected with its action available for execution.

### Verification Checklist
- [x] Personal agents still load correctly
- [x] Global agents still merge correctly when enabled
- [x] Group agents load for all user's group memberships
- [x] Group actions load for all user's group memberships
- [x] Agents properly marked with `is_group` and `group_id` flags
- [x] Agent selection finds group agents by name
- [x] Error handling prevents crashes if group loading fails
- [x] Logging provides visibility into group loading process