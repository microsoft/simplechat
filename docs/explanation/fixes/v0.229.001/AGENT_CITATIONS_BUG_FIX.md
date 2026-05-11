# Agent Citations Cross-Conversation Contamination Bug Fix

**Version Implemented:** 0.229.001

## Problem Description

**Critical Bug**: Agent citations from one conversation were appearing in completely different conversations, causing serious data contamination. 

### User Evidence
The user provided concrete evidence showing:
- Conversation 1: Used "World News Agent" with tool invocations for news searches
- Conversation 2: Started a new conversation, but the message data contained `agent_citations` from the World News Agent tools from Conversation 1

### Root Cause
The bug was in the plugin invocation logger system:
1. `PluginInvocationLogger` is a global singleton shared across all users and conversations
2. `get_recent_invocations()` method returns ALL recent invocations from ALL users and conversations
3. In `route_backend_chats.py` line 1352-1353, the code was using `get_recent_invocations()` without any filtering
4. This caused agent citations to leak across conversation boundaries

## Technical Analysis

### Problematic Code Path
```python
# route_backend_chats.py (lines 1352-1353) - BEFORE FIX
plugin_logger = get_plugin_logger()
plugin_invocations = plugin_logger.get_recent_invocations()  # ❌ Returns ALL invocations
```

### Data Flow Issue
1. User A, Conversation 1: World News Agent executes tools → logged to global plugin_logger
2. User A, Conversation 2: Weather Agent executes tools → logged to global plugin_logger  
3. When rendering Conversation 2: `get_recent_invocations()` returns tools from BOTH conversations
4. Agent citations from Conversation 1 appear in Conversation 2 message data

## Solution Implemented

### 1. Enhanced PluginInvocation Data Structure
```python
@dataclass
class PluginInvocation:
    # ... existing fields ...
    conversation_id: Optional[str] = None  # ✅ Added conversation tracking
```

### 2. Added Conversation-Specific Filtering Method
```python
def get_invocations_for_conversation(self, user_id: str, conversation_id: str, limit: int = 50) -> List[PluginInvocation]:
    """Get recent plugin invocations for a specific user and conversation."""
    conversation_invocations = [
        inv for inv in self.invocations 
        if inv.user_id == user_id and inv.conversation_id == conversation_id
    ]
    return conversation_invocations[-limit:] if conversation_invocations else []
```

### 3. Updated Plugin Logging to Track Conversation Context
```python
def log_plugin_invocation(..., conversation_id: Optional[str] = None):
    # Try to get conversation_id from Flask context if not provided
    if conversation_id is None:
        try:
            from flask import g
            conversation_id = getattr(g, 'conversation_id', None)
        except Exception:
            conversation_id = None
```

### 4. Fixed Route Backend to Use Conversation-Specific Filtering
```python
# route_backend_chats.py - AFTER FIX
# Store conversation_id in Flask context for plugin logger access
g.conversation_id = conversation_id

# CRITICAL FIX: Filter by user_id and conversation_id to prevent cross-conversation contamination
plugin_invocations = plugin_logger.get_invocations_for_conversation(user_id, conversation_id)
```

## Files Modified

1. **`semantic_kernel_plugins/plugin_invocation_logger.py`**
   - Added `conversation_id` field to `PluginInvocation` dataclass
   - Added `get_invocations_for_conversation()` method
   - Updated `log_plugin_invocation()` to capture conversation context

2. **`route_backend_chats.py`**
   - Added `g.conversation_id = conversation_id` to store context
   - Changed `get_recent_invocations()` to `get_invocations_for_conversation(user_id, conversation_id)`

3. **`config.py`**
   - Updated version from "0.226.074" to "0.226.075"

## Validation

Created comprehensive test script (`test_agent_citations_fix.py`) that validates:
- ✅ Cross-conversation isolation works correctly
- ✅ No contamination between different conversations  
- ✅ Each conversation only shows its own agent citations
- ✅ Original behavior vs fixed behavior comparison

## Impact Assessment

### Before Fix
- **Security Risk**: High - User data contamination across conversations
- **Privacy Risk**: High - Users could see tool execution details from other conversations
- **Data Integrity**: Compromised - Citations appeared in wrong conversations

### After Fix  
- **Security Risk**: Resolved - Complete conversation isolation
- **Privacy Risk**: Resolved - No cross-conversation data leakage
- **Data Integrity**: Restored - Citations only appear in correct conversations

## Testing Recommendations

1. **Regression Testing**: Verify existing agent functionality still works
2. **Isolation Testing**: Test multiple concurrent users with different conversations
3. **Edge Case Testing**: Test conversation switching, agent switching, etc.
4. **Performance Testing**: Verify filtering doesn't impact performance significantly

## Deployment Notes

- **Breaking Change**: No - Backward compatible
- **Database Migration**: None required
- **Restart Required**: Yes - Application restart needed to load new code
- **Rollback Plan**: Simple - revert the 3 modified files

This fix resolves a critical data contamination bug that could have serious privacy and security implications in production environments.
