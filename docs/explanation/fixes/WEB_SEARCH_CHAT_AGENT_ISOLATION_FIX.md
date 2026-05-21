# Web Search Chat Agent Isolation Fix

Fixed/Implemented in version: **0.241.073**

## Issue Description

Fresh installs could interrupt a Web Search streaming response when no chat agent was selected. Web Search uses its configured Azure AI Foundry agent only to retrieve current web evidence, but the chat response path could still fall back to a loaded Semantic Kernel default or first agent afterward.

## Root Cause Analysis

The streaming and non-streaming chat paths treated the presence of loaded agents as enough reason to select a default or first chat agent. On environments where the Web Search Foundry agent was present in the loaded agent set, an otherwise model-only Web Search request could accidentally enter chat-agent and Assigned Knowledge related paths.

## Version Implemented

- Application version updated in `application/single_app/config.py` from `0.241.072` to `0.241.073`.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_web_search_without_agent_assigned_knowledge.py`

### Code Changes Summary

- Added explicit chat-agent selection helpers so empty or unrelated `agent_info` payloads do not enable agent mode.
- Removed default-agent and first-agent fallbacks from chat response selection when no chat agent is selected.
- Kept Web Search Foundry execution isolated through the existing `perform_research_web_searches()` and `execute_foundry_agent()` path.
- Prevented unresolved chat-agent selections from writing misleading selected-agent metadata.

### Testing Approach

- Added a static functional regression test that verifies the undefined `agent_knowledge_binding` name is absent and default/first chat-agent fallbacks remain removed.
- Validated that Web Search still retains its dedicated Foundry execution path.

## Impact Analysis

Web Search remains available through the configured Foundry search agent, while the final answer generation stays model-only unless the user or saved settings explicitly select a chat agent. This prevents Assigned Knowledge policy from applying to Web Search-only requests.

## Validation

Run:

```bash
python functional_tests/test_web_search_without_agent_assigned_knowledge.py
python -m py_compile application/single_app/route_backend_chats.py functional_tests/test_web_search_without_agent_assigned_knowledge.py
```