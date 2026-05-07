# Tabular Related Document Evidence

Overview

Implemented in version: **0.241.137**

This feature extends the tabular analysis handoff so rows can carry evidence from explicitly referenced workspace documents. When a tabular row names a non-tabular file by full filename or basename, the chat route can resolve that file inside the same authorized workspace scope, retrieve a focused excerpt, and pass that evidence forward as if it were tabular-adjacent context for the same row.

Dependencies

- Tabular orchestration in `application/single_app/route_backend_chats.py`
- Search and chunk retrieval helpers in `application/single_app/functions_search_service.py`
- Workspace document metadata in `application/single_app/functions_documents.py`
- Tabular plugin invocation payloads from `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`
- Functional validation in `functional_tests/test_tabular_related_document_evidence.py`

Technical Specifications

Architecture overview

- The chat route inspects successful tabular tool results after each tabular mini-agent run.
- Each returned row is scanned for explicit references to non-tabular workspace documents using exact filename or basename matching.
- Matching documents are resolved within the same authorized personal, group, or public workspace scope as the tabular file.
- The route uses the shared search service first and falls back to the first ordered chunk when search does not return an excerpt.
- Resolved evidence is attached to each row as `referenced_documents` and summarized into the outer-model handoff message.
- Generated tabular output prompts are aware of `referenced_documents` so exported structured results can incorporate that evidence.

Scope and matching rules

- The first implementation is limited to workspace documents in personal, group, and public scopes.
- Chat-uploaded tabular files still execute normally, but related-document lookup is currently skipped for `source_hint="chat"`.
- Only explicit file references are matched. The route does not infer document relationships from comment ids, semantic similarity, or arbitrary free text.
- Tabular files are excluded from related-document resolution so this capability remains focused on non-tabular supporting evidence.

Usage Instructions

User workflow

- Ask a tabular question against a workspace CSV or workbook.
- Include or rely on rows that explicitly reference supporting files such as PDFs or DOCX files.
- When matching workspace documents exist in the same authorized scope, the response pipeline can use excerpts from those documents alongside the computed row results.
- Generated tabular artifacts can also use the attached `referenced_documents` row evidence when producing structured outputs.

Testing and Validation

Functional coverage

- `functional_tests/test_tabular_related_document_evidence.py`
- `functional_tests/test_tabular_computed_results_prompt_priority.py`
- `functional_tests/test_tabular_generated_output_exports.py`

Validation performed

- `python -m py_compile application/single_app/route_backend_chats.py`
- Focused diagnostics on `application/single_app/route_backend_chats.py`
- Focused functional regressions covering helper matching, evidence summary handoff, prompt content, and generated-output compatibility

Known limitations

- Related-document matching currently depends on exact filename or basename mentions in the tabular row data.
- The first cut does not resolve related evidence for chat-uploaded tabular files.
- The evidence summary is intentionally capped to keep prompt growth bounded on large result sets.