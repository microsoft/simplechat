# Agent Streaming Support

**Version:** 0.233.280  
**Implemented in:** December 18, 2025  
**Feature Type:** Enhancement

## Overview

This feature adds real-time streaming support for Semantic Kernel agents, allowing users to see agent responses incrementally as they are generated, matching the existing chat streaming experience. Previously, streaming was only available for regular GPT models, and users had to wait for complete agent responses.

## Technical Implementation

### Backend Changes (`route_backend_chats.py`)

#### 1. Removed Agent Blocking
- **Previous:** Streaming endpoint explicitly blocked agent usage with error message
- **New:** Removed the blocking check to allow agents with streaming

```python
# REMOVED:
if user_enable_agents:
    yield f"data: {json.dumps({'error': 'Agents are not supported in streaming mode...'})}\n\n"
    return
```

#### 2. Agent Selection Logic
Added comprehensive agent selection in streaming mode:
- Supports both per-user and global agent configuration
- Selects agent based on user settings or global configuration
- Falls back to default agent or first available agent
- Extracts agent metadata (name, display_name, deployment_name)

#### 3. Semantic Kernel Streaming Integration
Implemented `invoke_stream` method for agents:
- Converts conversation history to `ChatMessageContent` format
- Creates `ChatHistoryAgentThread` for conversation context
- Uses async generator pattern to stream responses
- Properly handles async/await patterns with event loops

```python
async def stream_agent():
    async for response in selected_agent.invoke_stream(messages=agent_message_history, thread=thread):
        if hasattr(response, 'content') and response.content:
            yield response.content
```

#### 4. Agent Citation Capture
- Collects plugin invocations from `plugin_logger` after streaming completes
- Converts invocations to citation format with:
  - Tool name (plugin.function)
  - Function arguments and results
  - Duration, timestamp, success status
  - Error messages if applicable
- Makes all citation data JSON-serializable

#### 5. Dual Path Handling
Implemented branching logic for agent vs non-agent streaming:
- **Agent Path:** Uses `invoke_stream` with Semantic Kernel
- **Non-Agent Path:** Uses standard OpenAI streaming
- Both paths yield SSE-formatted chunks
- Both paths capture appropriate citations

#### 6. Error Handling
Enhanced error handling for streaming:
- Captures partial content on errors
- Saves incomplete responses with error metadata
- Displays delivered content with error banner to user
- Allows retry button usage for failed streams

### Frontend Changes

#### 1. Streaming Toggle Visibility (`chat-streaming.js`)
**Previous:** Hid streaming button when agents were active  
**New:** Always shows streaming button - agents now support streaming

```javascript
// REMOVED the hide logic for agents
function updateStreamingButtonVisibility() {
    streamingToggleBtn.style.display = 'flex'; // Always show
}
```

#### 2. Message Send Logic (`chat-messages.js`)
**Previous:** Disabled streaming when agents were enabled  
**New:** Allows streaming with agents enabled

```javascript
// REMOVED: !agentsEnabled check
if (isStreamingEnabled() && !imageGenEnabled) {
    // Stream works with agents now
}
```

#### 3. Response Finalization (`chat-streaming.js`)
Enhanced final message creation to include agent metadata:
- `agent_display_name` - Shows which agent responded
- `agent_name` - Internal agent identifier
- `agent_citations` - Plugin/tool invocations
- Proper rendering of agent citations alongside hybrid citations

## User Experience

### What Users See

1. **Streaming Toggle:** Remains available when agents are enabled
2. **Real-Time Response:** Agent responses appear token-by-token as generated
3. **Agent Attribution:** Messages show which agent responded
4. **Agent Citations:** Plugin/tool calls displayed after streaming completes
5. **Error Recovery:** Partial responses saved if stream is interrupted
6. **Retry Support:** Retry button works on partial/failed agent responses

### Streaming Indicator
During streaming, users see:
- Incremental content updates in real-time
- Streaming badge: "⚡ Streaming" 
- Proper markdown rendering as content arrives
- Citation display after completion

### Error Scenarios
If streaming fails mid-response:
- ✅ Partial content is displayed
- ✅ Error banner shows the issue
- ✅ Retry button allows regeneration
- ✅ Content is saved to database

## Configuration

### Requirements
- `enable_semantic_kernel`: true (global or per-user)
- `per_user_semantic_kernel`: true/false (determines agent selection source)
- User setting `enable_agents`: true (when per_user mode enabled)

### Agent Selection Priority
1. Explicit user-selected agent (`selected_agent` in user settings)
2. Global selected agent (`global_selected_agent` in settings)
3. Default agent (agent with `default_agent=True`)
4. First available agent in the collection

## Technical Details

### Semantic Kernel API Used
- **Method:** `agent.invoke_stream(messages, thread)`
- **Returns:** `AsyncIterable[StreamingChatMessageContent]`
- **Content Access:** `response.content` for each streamed chunk

### SSE Format
```javascript
// Streaming chunks
data: {"content": "chunk text"}

// Final metadata
data: {
  "done": true,
  "message_id": "...",
  "agent_citations": [...],
  "agent_display_name": "...",
  "agent_name": "...",
  ...
}
```

### Database Schema
Assistant messages now include:
```python
{
    'agent_citations': [
        {
            'tool_name': 'plugin.function',
            'function_arguments': {...},
            'function_result': {...},
            'duration_ms': 123,
            'timestamp': '...',
            'success': True/False
        }
    ],
    'agent_display_name': 'Agent Name',
    'agent_name': 'agent_id'
}
```

## Benefits

### Performance
- ✅ Faster perceived response time (streaming starts immediately)
- ✅ Reduced waiting time for long agent responses
- ✅ Better user engagement during agent processing

### User Experience
- ✅ Consistent streaming experience across models and agents
- ✅ Real-time feedback on agent activities
- ✅ Clear attribution of which agent responded
- ✅ Full citation support for plugin invocations

### Reliability
- ✅ Error recovery with partial content preservation
- ✅ Timeout handling (5 minutes)
- ✅ Retry capability on failures
- ✅ Proper cleanup on cancellation

## Compatibility

### Supported Agent Types
- ✅ **ChatCompletionAgent** - Primary implementation
- ✅ **LoggingChatCompletionAgent** - Custom wrapper (used in this app)
- ✅ **Multi-agent orchestration** - Via orchestrator's streaming callbacks
- ⚠️ **Note:** Tested with Semantic Kernel Python's agent framework

### Not Supported in Streaming
- ❌ Image generation (remains non-streaming)
- ❌ File uploads (handled separately)

## Testing Recommendations

1. **Basic Streaming:** Enable streaming, enable agents, send message
2. **Citation Display:** Use agent with plugins, verify citations appear
3. **Error Handling:** Interrupt connection, verify partial content saved
4. **Agent Selection:** Test with multiple agents, verify correct selection
5. **Toggle Behavior:** Toggle streaming on/off with agents enabled
6. **Long Responses:** Test with complex queries requiring multiple plugin calls
7. **Timeout:** Test 5-minute timeout with long-running agent tasks

## Future Enhancements

- Token usage tracking for agent streaming (currently only for GPT)
- Progress indicators for multi-step agent reasoning
- Streaming support for multi-agent orchestration visualization
- Real-time display of plugin invocations during streaming (not just after)

## Known Limitations

1. **Token Usage:** Token metrics may not be available for all agent types
2. **Orchestrator Streaming:** Basic support - full visualization TBD
3. **Event Loop:** Uses new event loop for async execution (may impact performance in high-concurrency scenarios)

## Related Files

### Backend
- `route_backend_chats.py` - Main streaming implementation
- `agent_logging_chat_completion.py` - Agent wrapper (unchanged)
- `semantic_kernel_plugins/plugin_invocation_logger.py` - Citation logging

### Frontend
- `static/js/chat/chat-streaming.js` - Streaming UI logic
- `static/js/chat/chat-messages.js` - Message send logic
- `static/js/chat/chat-agents.js` - Agent enable/disable

## Version History

- **v0.233.280** - Initial agent streaming support implementation
