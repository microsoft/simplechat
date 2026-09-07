# Agent Document Search Citation Fix

## Header information

**Issue:** Documents an agent retrieved through the document search action never became document citations. They were recorded only as agent tool citations, so the retrieved documents did not appear in the message Sources disclosure, were not clickable, never reached the enhanced citation viewer, and could not be promoted into cited references or the conversation's Used documents drawer.

**Root cause:** The route-level hybrid search built document citation records directly into `hybrid_citations`. `DocumentSearchPlugin` results took a different path: `_build_plugin_invocation_agent_citation()` wrapped the entire invocation into an `agent_citations` entry describing the tool call (`tool_name`, `function_arguments`, `function_result`). The retrieved document payload was present inside `function_result`, but nothing converted it into the document citation shape, and the plugin returned no citation markers for the model to reference. `functions_workflow_runner.py` had the same gap through `_build_agent_citations_from_plugin_invocations()`.

Fixed/Implemented in version: **0.250.219**

Related config.py update: `VERSION = "0.250.219"`

Associated issue: `microsoft/simplechat#1239`

## Technical details

### Behavior comparison

| | Standard document search | Agent document search (before) | Agent document search (after) |
|---|---|---|---|
| Retrieval | route-level `hybrid_search()` | `DocumentSearchPlugin.search_documents()` | unchanged |
| Stored as | `hybrid_citations` | `agent_citations` only | `agent_citations` **and** `hybrid_citations` |
| Sources disclosure | document buttons | raw JSON tool modal | document buttons plus the tool modal |
| Enhanced citation / PDF viewer | yes | no | yes |
| Eligible for `cited_hybrid_citations` | yes | no | yes |
| Counted in `used_documents` | yes | no | yes |
| Capability usage `workspace.search_used` | yes | no | yes |

### Sources are not cited references

Derived citations are *sources*. They are intentionally not capped or pre-filtered, so an agent that sources 500 chunks records 500 sources. `functions_citation_tracking.build_cited_source_subsets()` remains solely responsible for narrowing sources down to the subset the response actually cited.

### Derivation

`functions_agent_document_citations.py` converts document-search payloads into the same record shape the route-level search produces (`file_name`, `document_id`, `citation_id`, `page_number`, `sheet_name`, `location_label`, `location_value`, `chunk_id`, `chunk_sequence`, `score`, `group_id`, `public_workspace_id`, `version`, `classification`), using the shared `resolve_citation_location()` helper so tabular sheets and page locations match exactly.

| Plugin function | Payload shape | Derived citations |
|---|---|---|
| `search_documents` | `results[]` | one per retrieved chunk |
| `retrieve_document_chunks` | `document` + `chunks[]` | one per returned chunk |
| `summarize_document` | `document` + `citation_chunk` | one citation anchored to a real source chunk |

Each derived record is tagged with `source: "agent_document_search"`, plus `plugin_name` and `function_name`, so its provenance is auditable. Invocations from other plugins, failed invocations, and payloads containing `error` are ignored.

Merging deduplicates by `citation_id`, falling back to `document_id` + `chunk_id` + `page_number`. Existing route-level records always win, so a chunk retrieved by both the document search toggle and an agent keeps its original metadata and is listed once.

### Locator accuracy

Chunk keys are not always `<document_id>_1`. Video chunks are keyed by second and legitimately start at `<document_id>_0`, and some documents have no page 1. Three rules keep derived links resolvable:

- `summarize_document_content()` now reports a `citation_chunk` describing its first source chunk, and the summary citation uses that chunk's real id, page, and sequence. When a payload reports no source chunk, the citation falls back to the document id rather than synthesizing a `<document_id>_1` locator that may not exist.
- Page and sequence resolution uses explicit null checks instead of truthiness, so a valid sequence of `0` is preserved rather than being rewritten to `1`.
- `resolve_citation_location()` in `functions_citation_tracking.py` also preserves `0` instead of relabelling it as page 1. Every pre-existing caller already coerced `0` to `1` before calling, so this only affects the new agent-derived path and keeps the displayed location consistent with the citation id.

### Cancelled and interrupted streams

In the streaming path, plugin invocations are only folded into the agent citation list once a stream completes normally. A stream cancelled or interrupted after a document search would otherwise persist an empty citation list. Those two paths therefore also pass the raw invocation records from the plugin logger, which is cleared per chat request so it holds only the current message's invocations. Merging is deduplicated, so supplying both sources never double-counts a chunk.

### Inline citation markers

Every document-search payload now carries a ready-to-copy `citation` value formatted exactly as the citation tracker matches:

```
(Source: Policy.pdf, Page: 3) [#doc-1_3]
```

The payload also carries `citation_instructions`, and the three kernel function descriptions instruct the model to copy the `citation` value verbatim. When the model does, `build_cited_source_subsets()` promotes that document into `cited_hybrid_citations`, and `merge_cited_documents_into_conversation()` records it in the conversation's `used_documents`.

### Large source lists

Because sources are uncapped, the per-message Sources disclosure now renders the first 25 document sources and collapses the remainder behind a **Show N more sources** control (`citation-overflow-group` / `citation-overflow-toggle`). The control uses the Bootstrap `d-none` class and a delegated click handler; no stored data is truncated. The Used documents drawer is unaffected because it lists cited documents, not source chunks.

### Files modified

- `application/single_app/functions_agent_document_citations.py` (new)
- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/functions_search_service.py`
- `application/single_app/functions_citation_tracking.py`
- `application/single_app/semantic_kernel_plugins/document_search_plugin.py`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/static/js/chat/chat-citations.js`
- `application/single_app/config.py`

### Integration points

The merge runs before `build_cited_source_subsets()` and before `persist_agent_citation_artifacts()` in every path that writes an assistant message:

- `route_backend_chats.py` — document action path
- `route_backend_chats.py` — non-streaming chat path
- `route_backend_chats.py` — streaming completion path
- `route_backend_chats.py` — streaming cancellation path (partial content)
- `route_backend_chats.py` — streaming interruption path
- `functions_workflow_runner.py` — `_create_assistant_message()`

### Access control

No new access surface is introduced. Every derived record comes from payloads produced by `functions_search_service`, which already resolves personal, group, and public scope against the current user before returning any content. Derivation is a read of data the requesting user was already authorized to receive.

## Validation

`functional_tests/test_agent_document_search_citations.py` — 12/12 passing:

1. `config.py` VERSION is at or above the implementation version
2. `search_documents` results map to the route-level document citation shape
3. `retrieve_document_chunks` and `summarize_document` produce citations anchored to real chunks
4. Zero-indexed sequences survive and summaries never invent a `<document_id>_1` locator
5. Raw plugin invocations produce citations for cancelled and interrupted streams, deduplicated against agent citations
6. Unrelated plugins, failed invocations, and errored payloads are ignored
7. Merging dedupes against route citations, preserves them, and does not truncate a 500-result set
8. Payload markers are matched by the citation tracker and promote the correct document into `cited_hybrid_citations`
9. Tabular sheet locations and JSON-string payloads are handled
10. All chat paths, the workflow runner, and all three plugin functions are wired
11. Every function that builds cited subsets merges agent document citations first on **every branch**, verified by AST walking so a merge inside one finalization branch cannot vouch for another
12. Large source lists collapse behind a show-more control

The ordering test was confirmed to have teeth: removing the interrupted-stream merge makes it fail with the exact branch and line, and it independently caught a path that was missing a merge during development.

Regression coverage confirmed passing: `test_chat_cited_source_tracking.py`, `test_agent_citations_fix.py`, `test_agent_citations_per_message_fix.py`, `test_chat_capability_usage_metadata.py`, `test_markdown_citation_lookup_fallback.py`, `test_stored_xss_chat_workspace_rendering_fix.py`, `test_mixed_source_chat_search_consistency.py`, and the three `route_tests` policy suites.

## Known limitation

`PluginInvocationLogger` is process-global and filters only by user and conversation. If a user supersedes a request while the prior one is still finalizing, the newer request's `clear_invocations_for_conversation()` can remove invocations the older request has not yet read. This predates the change and affects existing agent tool citation capture identically; making it exact requires tagging invocations with a request or run id and filtering on it, which is a broader change to shared plugin infrastructure and is better handled separately.

### Before and after

**Before** — an agent answering from workspace documents produced a message with zero document sources. The only evidence of retrieval was an "Agent" tool citation that opened a JSON modal, and the conversation's Used documents drawer stayed empty.

**After** — the same answer lists every retrieved document chunk as a source, each source opens the document at the correct page or sheet, cited documents are separated from retrieved sources, and the Used documents drawer reflects the documents the answer actually cited.
