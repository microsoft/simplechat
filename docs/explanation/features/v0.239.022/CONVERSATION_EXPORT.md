# Conversation Export

## Overview
Snapshot of the Conversation Export feature as implemented in version **0.239.022**.

This version updates export generation so JSON includes modern citation buckets, normalized citation summaries, and processing thoughts, while Markdown becomes a transcript-first report with appendix sections and optional AI-generated intro summaries.

**Version Implemented:** 0.239.022
**Dependencies:** Flask export route, Azure Cosmos DB conversations/messages/thoughts, Bootstrap modal workflow, chat-export.js, Azure OpenAI/APIM chat models

## Technical Summary

### Backend
- Filters out deleted messages and inactive-thread retries
- Reapplies thread-aware ordering to align with the live chat view
- Includes both normalized and raw citations per message
- Joins persisted processing thoughts by `message_id`
- Supports optional per-conversation `summary_intro` generation using a selected model

### Frontend
- Adds a summary step to the export wizard
- Lets users enable or disable intro summaries
- Reuses the existing chat model selector options for summary model choice

## Export Shape

### JSON
Each conversation entry contains:
- `conversation`
- `summary_intro`
- `messages`

Each message can include:
- `content`
- `content_text`
- `details`
- `citations`
- `legacy_citations`
- `hybrid_citations`
- `web_search_citations`
- `agent_citations`
- `thoughts`

### Markdown
Markdown exports contain:
- metadata header
- optional abstract
- transcript body
- appendices for metadata, message details, references, thoughts, and supplemental messages

## Files Updated
- `application/single_app/route_backend_conversation_export.py`
- `application/single_app/static/js/chat/chat-export.js`
- `application/single_app/config.py`
- `functional_tests/test_conversation_export.py`

## Testing
Validated by `functional_tests/test_conversation_export.py`.
