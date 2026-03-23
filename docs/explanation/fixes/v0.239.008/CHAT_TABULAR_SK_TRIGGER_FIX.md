# Chat-Uploaded Tabular File SK Mini-Agent Trigger Fix

## Issue Description

When a user uploads a tabular file (CSV, XLSX, XLS, XLSM) directly to a chat conversation and asks a question in model-only mode (no agent selected), the SK mini-agent (`run_tabular_sk_analysis`) did not trigger. The model would see instructions to "use plugin functions" but could not call them without an agent, resulting in the model describing what it would do instead of providing actual analysis results.

The full agent mode worked correctly because the agent has direct access to the `TabularProcessingPlugin` and can call its functions.

## Root Cause

Three gaps prevented the mini SK agent from activating for chat-uploaded tabular files:

1. **Streaming path ignored `file` role messages**: The streaming conversation history loop (`/api/chat/stream`) only processed `user` and `assistant` roles, making chat-uploaded files completely invisible to the model.

2. **Mini SK only triggered from search results**: Both streaming and non-streaming paths only invoked `run_tabular_sk_analysis()` when tabular files appeared in hybrid search results (`combined_documents`). Chat-uploaded files are stored in blob storage as `file` role messages and are not indexed in Azure AI Search, so they never appeared in search results.

3. **Model-only mode can't call plugin functions**: The non-streaming path's file handler injected "Use the tabular_processing plugin functions" as a system message, but in model-only mode the model has no function-calling capability.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py` — All code changes
- `application/single_app/config.py` — Version bump to 0.239.008

### Code Changes

#### Non-streaming path (`/api/chat`)

1. Added `chat_tabular_files = set()` tracker before the conversation history loop (~line 1896)
2. Added `chat_tabular_files.add(filename)` inside the `if is_table and file_content_source == 'blob':` block (~line 1936)
3. After the history loop, added a block that checks `chat_tabular_files` and calls `run_tabular_sk_analysis(source_hint="chat")`, injecting pre-computed results as a system message (~line 2027)

#### Streaming path (`/api/chat/stream`)

4. Replaced the simple 8-line history loop (which only handled `user`/`assistant`) with expanded logic that mirrors the non-streaming path's `file` role handling, including blob tabular file tracking (~line 3687)
5. Added the same mini SK trigger block after the expanded loop (~line 3751)

### How It Works After Fix

1. User uploads `sales.xlsx` to chat, asks "analyze sales/profit"
2. During conversation history building, the `file` role message with `is_table=True` and `file_content_source='blob'` is detected
3. The filename is collected into `chat_tabular_files`
4. After the history loop, `run_tabular_sk_analysis()` is called with `source_hint="chat"`, which resolves the file from the `personal-chat` blob container
5. The mini SK agent pre-loads the file schema, calls plugin functions (aggregate, filter, etc.), and returns computed results
6. Results are injected as a system message so the model can present accurate numbers
7. Plugin invocation citations are collected for transparency

## Testing

1. Upload a tabular file (xlsx/csv) directly to chat
2. With no agent selected, send a data analysis question
3. Verify the response contains actual computed data (not just a description of steps)
4. Check logs for `[Chat Tabular SK]` entries confirming the mini SK trigger
5. Verify agent mode still works as before

## Impact

- Enables tabular data analysis in model-only chat mode for chat-uploaded files
- No changes to existing search-result-based tabular detection
- No changes to full agent mode behavior
- Streaming and non-streaming paths both fixed

## Version

- **Version**: 0.239.008
- **Implemented in**: 0.239.008
