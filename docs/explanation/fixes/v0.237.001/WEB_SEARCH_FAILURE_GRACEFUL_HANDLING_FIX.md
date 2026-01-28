# Web Search Failure Graceful Handling Fix

## Overview

Fixed an issue where Azure AI Foundry web search agent failures would cause the AI model to answer questions using outdated training data instead of informing the user that the web search failed.

**Version Implemented:** v0.237.001

## Problem

When using the Azure AI Foundry web search agent (Bing grounding), if the web search operation failed for any reason (network issues, configuration errors, API failures), the conversation would continue without web search results. The AI model would then answer the user's question based on its training data, which could be outdated or incorrect.

### Example Scenario

**User asks:** "Who is the current President of the United States?"

**Before fix (incorrect behavior):**
- Web search fails silently due to agent configuration issue
- Model answers from training data: "Joe Biden is the current President"
- User receives confident but potentially outdated/incorrect information
- No indication that web search failed

**After fix (correct behavior):**
- Web search fails
- System message injected instructing model to inform user of failure
- Model responds: "I'm sorry, but the web search encountered an error and I couldn't retrieve current information. Please try again later."
- User is aware the information may be unavailable

### Error Symptoms

Users would receive:
- Answers based on outdated training data cutoff dates
- Incorrect information for time-sensitive queries
- No indication that web search was attempted but failed
- Confidently stated incorrect facts

## Root Cause

The `perform_web_search` function in `route_backend_chats.py` did not communicate failure status back to the calling code. When exceptions occurred during web search:
1. Errors were logged but not acted upon
2. The function returned `None` in all cases (success and failure)
3. No mechanism existed to inform the model about search failures
4. The conversation proceeded as if web search was not configured

## Solution

Implemented a comprehensive failure handling mechanism:

### 1. Return Value Indication

Modified `perform_web_search` to return a boolean status:
- `True` - Web search succeeded or was intentionally skipped (disabled, empty query)
- `False` - Web search failed due to an error

### 2. System Message Injection on Failure

When web search fails, a system message is added to the conversation context instructing the model to:
- Acknowledge the search failure to the user
- Not attempt to answer using training data
- Suggest the user try again later

### 3. Error-Specific Messages

Different failure scenarios receive appropriate messages:

| Failure Type | System Message |
|--------------|----------------|
| Agent ID Not Configured | "Web search agent is not configured. Please inform the user that web search is currently unavailable." |
| Foundry Invocation Error | "Web search failed: [error details]. Please inform the user that the web search encountered an error and you cannot provide real-time information for this query." |
| Unexpected Exception | "Web search failed with an unexpected error: [error]. Please inform the user that the web search encountered an error and suggest they try again later." |

### Files Modified

**route_backend_chats.py**
- Modified `perform_web_search` function to return boolean status
- Added system message injection on all failure paths
- Updated exception handlers to set appropriate failure messages

## Code Changes

### Return Value Pattern

```python
def perform_web_search(conversation_id, source, query, web_search_results_container):
    """
    Now returns:
    - True: Web search succeeded or was intentionally skipped
    - False: Web search failed due to an error
    """
    
    # Success path
    return True
    
    # Failure path - inject system message and return False
    web_search_results_container.append({
        'role': 'system',
        'content': 'Web search failed: [error]. Please inform the user...'
    })
    return False
```

### System Message Structure

When failure occurs, a message is appended to the conversation:
```python
{
    'role': 'system',
    'content': 'Web search failed with an unexpected error: [error details]. '
               'Please inform the user that the web search encountered an error '
               'and you cannot provide real-time information for this query. '
               'Suggest they try again later.'
}
```

## Testing

### Failure Scenario Validation

1. **Missing Agent Configuration**
   - Remove web search agent ID from settings
   - Send a query to web search-enabled agent
   - Verify user receives message about unavailable web search

2. **Network/API Failure**
   - Simulate network connectivity issue
   - Send a query to web search agent
   - Verify user receives error message instead of outdated answer

3. **Success Scenario (Regression)**
   - Configure valid web search agent
   - Send a query requesting current information
   - Verify web search results are returned with citations

### Test Commands

```python
# Test query for web search
"Who is the current President of the United States?"
"What is the current weather in Seattle?"
"What are today's top news headlines?"
```

## Impact

- **User Experience**: Users are now informed when web search fails instead of receiving potentially incorrect information
- **Transparency**: Clear indication when real-time information cannot be retrieved
- **Trust**: Users can make informed decisions about the reliability of responses
- **Error Visibility**: Administrators can identify web search configuration issues through user reports

## Configuration

Web search requires proper Azure AI Foundry configuration:

```python
# Required settings
FOUNDRY_WEB_SEARCH_AGENT_ID = "asst_xxxxxxxxxxxxx"  # Foundry agent with Bing grounding
AZURE_AI_PROJECT_CONNECTION_STRING = "..."  # Project connection string
```

## Debug Logging

Enhanced debug logging was also added to `perform_web_search` to aid troubleshooting:

```python
debug_print(f"🌐 Starting web search for conversation: {conversation_id}")
debug_print(f"📊 Web search query: '{query}'")
debug_print(f"✅ Web search completed successfully with {len(citations)} citations")
debug_print(f"❌ Web search failed: {error_details}")
```

Enable debug logging by setting:
```python
DEBUG_LOG_ENABLED = True
```

## Related

- [Azure AI Foundry Agent Support](../features/v0.236.011/AZURE_AI_FOUNDRY_AGENT_SUPPORT.md)
- Bing Grounding Tool Configuration
- Error Handling Best Practices

## Migration Notes

This is a behavioral change that improves user experience. No configuration changes are required. Existing web search functionality will continue to work, with improved failure handling when errors occur.
