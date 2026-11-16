# Retrieval, Narrative/XML Fidelity, System Prompt, and Inline Citation Restoration Fix

Fixed in version: **0.261.392** (Refs: [#1855](https://github.com/microsoft/simplechat/issues/1855))

## Issue Description

When Enhanced Citations was enabled (which derives `enable_mixed_source_chat_search = True`), several retrieval and answer-quality regressions occurred across both `paullizer-react-v2-ui` and earlier branches sharing the same Cosmos DB and Azure AI Search resources:

1. **Suppression of `default_system_prompt`**: `route_backend_chats.py` checked whether any `role == "system"` message did not contain `"retrieved document excerpts"` and skipped inserting `default_system_prompt` whenever `mixed_source_handoff`, chat-uploaded file/image messages, or other augmentation system messages were present.
2. **Narrative and XML Excerpt Truncation & Missing Citation Markers in Mixed-Source Chat**: `route_backend_chats.py` skipped `build_search_augmentation_system_prompt(retrieved_content)` whenever `is_mixed_source_chat_search_enabled(settings)` was `True`, leaving the model with only the JSON `evidence_envelopes` preview (where each chunk string was capped at 1,024 / 512 bytes and document metadata plus `(Source: ..., Page: ...) [#citation_id]` strings were omitted).
3. **Empty Content for Direct Chat File Uploads When Content Screening Was Off**: Workspace-backed chat file uploads (`file_content_source: "workspace"`) stored no inline `file_content` on the Cosmos message record, and `_refresh_workspace_linked_history_message` only loaded chunks when `SCREENING_FIELD` was present on the document.
4. **Bracketed Document/Chunk IDs (`[8ed56431_1]`) Rendered as Raw Text**: When models emitted bracketed chunk identifiers or shortened 8-character UUID prefixes (`[8ed56431_1]`, `[15dce0d4_2; 8ed56431_2]`) without `(Source: ...)`, neither `citations.ts` (V2 UI), `chat-citations.js` (Classic UI), nor `functions_citation_tracking.py` resolved them against `hybrid_citations`.
5. **Hard Failure When Azure AI Search Semantic Ranker Free Quota Was Exhausted**: `hybrid_search` hardcoded `query_type="semantic"` without falling back to `query_type="simple"` (vector + keyword hybrid search) after recording the service health warning, and secondary relevance tabular candidate probes could fail the entire chat turn on quota errors.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
  - Updated `has_general_system_prompt` in standard and streaming chat paths to check specifically whether `default_system_prompt` is already present in `conversation_history_for_api`.
  - Restored `build_search_augmentation_system_prompt(retrieved_content)` in `system_messages_for_augmentation` when `is_mixed_source_chat_search_enabled(settings)` is `True` so full narrative/XML chunks, metadata citations, and `(Source: ..., Page: ...) [#citation_id]` markers are always provided.
  - Guarded secondary `search_relevant_tabular_candidates` calls against `SemanticSearchQuotaExceededError` and added fallback `document_id` derivation from `id` in `_resolve_chat_mixed_source_relevance_context`.
  - Updated `_refresh_workspace_linked_history_message` to hydrate `file_content` from `get_ordered_document_chunks` for workspace-backed non-tabular chat file uploads when Content Screening is off, and removed the 50KB truncation for workspace-backed non-tabular chat uploads in `build_conversation_history_segments`.
- `application/single_app/functions_mixed_source_orchestration.py`
  - Enriched `build_narrative_evidence_envelopes` and `build_schema_summary_evidence_envelopes` citation entries with `file_name` and canonical `(Source: ..., Page: ...) [#citation_id]` strings, and added `_extract_result_document_id` fallback.
- `application/single_app/functions_search.py`
  - Kept `record_semantic_search_quota_exceeded` when Azure AI Search Semantic Ranker quota is exhausted and added automatic fallback to `query_type="simple"` vector + keyword search without clearing the persisted service health warning.
- `application/single_app/functions_citation_tracking.py`, `application/v2_ui/src/lib/citations.ts`, `application/single_app/static/js/chat/chat-citations.js`
  - Added resolution of bracketed full and 8-hex-prefix chunk citation IDs (`[8ed56431_1]`, `[15dce0d4_2; 8ed56431_2]`) against `hybrid_citations` / `documentCitations`.
- `application/single_app/config.py`
  - Bumped `VERSION` to `0.261.392`.

## Validation

- Added `functional_tests/test_retrieval_citation_system_prompt_restoration.py` and verified alongside `test_mixed_source_chat_search_consistency.py`, `test_mixed_source_manifest_contracts.py`, `test_orchestration_search_result_integrity.py`, `test_inline_citation_filename_fallback.py`, `test_v2_citations.py`, `test_chat_citation_whitespace_preservation.py`, and `test_chat_cited_source_tracking.py`.
