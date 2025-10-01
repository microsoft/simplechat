# Agent Citations Per-Message Isolation Fix

**Version Implemented:** 0.229.001

## Problem Description

**Issue Identified**: While the cross-conversation contamination bug was successfully fixed, a new issue was discovered where agent citations were accumulating across messages within the same conversation, rather than being specific to each user interaction.

### User's Observation
The user provided evidence showing:
- **Message 1**: 1 agent citation (from first `topNews` call)
- **Message 2**: 2 agent citations (first + second `topNews` calls) 
- **Message 3**: 3 agent citations (first + second + third `topNews` calls)

### Expected Behavior
Each message should only show citations for **tools executed during that specific user interaction**, not accumulated citations from the entire conversation history.

## Root Cause Analysis

The previous fix successfully prevented cross-conversation contamination by filtering invocations by `user_id` and `conversation_id`. However, within a single conversation, the plugin logger was accumulating ALL invocations for that conversation, causing citations to build up across messages.

### Current Flow (Problematic)
1. User sends Message 1 → Agent executes Tool A → Citation stored
2. User sends Message 2 → Agent executes Tool B → Citations: [Tool A, Tool B]
3. User sends Message 3 → Agent executes Tool C → Citations: [Tool A, Tool B, Tool C]

### Desired Flow (Fixed)
1. User sends Message 1 → Agent executes Tool A → Citations: [Tool A]
2. User sends Message 2 → Agent executes Tool B → Citations: [Tool B] only
3. User sends Message 3 → Agent executes Tool C → Citations: [Tool C] only

## Solution Implemented

### 1. Added Conversation-Specific Clear Method
```python
def clear_invocations_for_conversation(self, user_id: str, conversation_id: str):
    """Clear plugin invocations for a specific user and conversation.
    
    This ensures each message only shows citations for tools executed 
    during that specific interaction, not accumulated from the entire conversation.
    """
    self.invocations = [
        inv for inv in self.invocations 
        if not (inv.user_id == user_id and inv.conversation_id == conversation_id)
    ]
```

### 2. Clear Invocations at Start of Each Message Processing
```python
# route_backend_chats.py - Added at start of message processing
# Clear plugin invocations at start of message processing to ensure
# each message only shows citations for tools executed during that specific interaction
from semantic_kernel_plugins.plugin_invocation_logger import get_plugin_logger
plugin_logger = get_plugin_logger()
plugin_logger.clear_invocations_for_conversation(user_id, conversation_id)
```

## Implementation Details

### Files Modified

1. **`semantic_kernel_plugins/plugin_invocation_logger.py`**
   - Added `clear_invocations_for_conversation()` method

2. **`route_backend_chats.py`**
   - Added plugin logger clearing at start of message processing
   - Ensures each message starts with a clean slate for citations

3. **`config.py`**
   - Updated version from "0.226.075" to "0.226.076"

### Message Processing Flow (After Fix)

1. **Message Start**: Clear any existing invocations for this user/conversation
2. **Agent Execution**: Agent executes tools, invocations are logged
3. **Citation Extraction**: Only the current message's tool invocations are captured
4. **Message Storage**: Message stored with citations specific to this interaction
5. **Next Message**: Process repeats with fresh citation tracking

## Validation

Created comprehensive test (`test_agent_citations_per_message_fix.py`) that validates:
- ✅ Each message has exactly 1 citation (no accumulation)
- ✅ Cross-conversation isolation still works (previous fix maintained)
- ✅ Per-message isolation within conversations (new fix)
- ✅ Citations are specific to each user interaction

### Test Results
```
Message 1: 1 citation  ✅
Message 2: 1 citation  ✅ (not 2)
Message 3: 1 citation  ✅ (not 3)
```

## Impact Assessment

### Before Fix
- **User Experience**: Confusing - Users saw citations from previous messages
- **Citation Accuracy**: Misleading - Citations implied tools were used for current response when they weren't
- **Performance**: Degrading - Citation lists grew longer with each message

### After Fix  
- **User Experience**: Clear - Users only see citations relevant to their current question
- **Citation Accuracy**: Precise - Citations accurately reflect what tools were used for the current response
- **Performance**: Optimal - Citation lists remain focused and concise

## Design Philosophy

This fix aligns with the principle that **citations should be specific to each user interaction**. When a user asks a question, they want to see what tools were used to answer *that specific question*, not what tools were used throughout the entire conversation history.

### User Perspective
- "What tools did you use to answer my current question?" ✅
- "What tools have you used in our entire conversation?" ❌

### Technical Perspective
- Each message is a discrete interaction with its own context
- Tool usage should be tracked per-interaction, not per-conversation
- Citations provide transparency for the current response, not historical responses

## Deployment Notes

- **Breaking Change**: No - This improves accuracy without breaking existing functionality
- **Backward Compatibility**: Full - No database migrations or API changes required
- **Performance Impact**: Positive - Reduces citation list sizes and processing overhead
- **Rollback Plan**: Simple - Revert the 2 modified files

## Conclusion

This fix completes the agent citations system by ensuring:
1. **Cross-Conversation Isolation**: Citations don't leak between different conversations
2. **Per-Message Isolation**: Citations don't accumulate within the same conversation
3. **Interaction-Specific Accuracy**: Each message only shows citations for tools executed during that specific user interaction

The system now provides precise, accurate, and relevant citation information that enhances user understanding of how their questions were answered.
