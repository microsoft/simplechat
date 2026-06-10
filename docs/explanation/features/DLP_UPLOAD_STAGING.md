# DLP Upload Staging

## Overview

Version: 0.241.018
Dependencies: shared DLP core, configurable regex DLP rules, document processing pipeline, Azure AI Search, Azure OpenAI embeddings.

SimpleChat now applies DLP to extracted upload text and selected document metadata before embeddings, Azure AI Search indexing, metadata extraction prompts, Cosmos metadata updates, and file-processing logs. The feature reuses the shared DLP core introduced for web-search egress and applies it to `save_chunks()`, `save_chunks_batch()`, `save_video_chunk()`, and metadata extraction/update paths.

Regex DLP is the implemented engine for this release. The default rules detect U.S. SSNs and Luhn-valid credit card numbers, and administrators can add upload-specific regex rules through the shared `dlp_regex_rules` settings payload.

## Technical Specifications

Protected processing points:

- `save_chunks()` evaluates DLP after metadata and vision text are combined, before `generate_embedding(...)`.
- `save_chunks_batch()` evaluates DLP for each enhanced chunk before `generate_embeddings_batch(...)`.
- `save_video_chunk()` evaluates transcript and OCR text before transcript embedding and AI Search indexing.
- Metadata fields `title`, `authors`, `organization`, `keywords`, and `abstract` are sanitized before metadata extraction prompts, hybrid-search queries, Cosmos updates, Azure AI Search payload metadata, activity logs, and file-processing logs.
- Safe DLP metadata is attached to chunk documents and document records as counts-only summaries.
- Document-level DLP metadata preserves the worst observed status and cumulative entity counts across chunk and metadata scans.
- Configured regex rules can target upload only, web search only, or both surfaces.
- Configured rules support keyword proximity confidence shaping, so a regex candidate can require nearby identifiers such as `document`, `employee`, `SSN`, or another admin-defined term before it redacts or blocks.
- File-processing logs replace raw chunk logging with safe DLP and text-length summaries.
- Enhanced citations are automatically disabled when upload DLP can enforce a block or redaction, including `redact` mode, `block` mode, fail-on-match, and fail-closed scanner errors, because this PR does not generate sanitized binary derivatives for raw source files.

Upload DLP states:

- `accepted`: no DLP findings.
- `accepted_with_dlp_monitoring`: findings observed in monitor mode.
- `accepted_with_redactions`: redacted text was embedded and indexed.
- `blocked`: DLP policy blocked indexing.
- `scanner_failed`: scanner failure blocked indexing in fail-closed mode.

## Admin Settings

Upload controls are available under Admin Settings > Data Loss Prevention:

- Enable Upload DLP.
- Upload mode: `monitor`, `redact`, or `block`.
- Fail upload on match.
- Custom Regex Rules, shared with web-search DLP.

Review routing defaults to `none`. Upload review-event writing is not exposed in this release because the DLP review destination is intentionally locked to `none`.

## Telemetry And Logs

Upload DLP telemetry uses `log_event(...)` with safe dimensions:

- `activity_type = dlp_decision`
- `dlp_surface = upload`
- `dlp_action`
- `dlp_engine`
- `dlp_mode`
- `workspace_scope`
- `scanner_status`
- `dlp_total_replacements`
- `dlp_entity_counts`

File-processing logs may include safe DLP summaries such as action, engine, counts, document id, workspace scope, page number, and text length. They do not include raw chunk text, raw OCR text, raw vision text, or raw matched values.

Example Azure Monitor alert concepts:

```kusto
customEvents
| where tostring(customDimensions.activity_type) == "dlp_decision"
| where tostring(customDimensions.dlp_surface) == "upload"
| where tostring(customDimensions.dlp_action) == "block"
| summarize blocked_uploads=count() by bin(timestamp, 15m)
```

```kusto
customEvents
| where tostring(customDimensions.activity_type) == "dlp_decision"
| where tostring(customDimensions.dlp_surface) == "upload"
| where toint(customDimensions.dlp_total_replacements) > 10
| summarize high_redaction_events=count() by bin(timestamp, 15m)
```

```kusto
customEvents
| where tostring(customDimensions.activity_type) == "dlp_decision"
| where tostring(customDimensions.dlp_surface) == "upload"
| where tostring(customDimensions.scanner_status) != "ok"
| summarize scanner_failures=count() by bin(timestamp, 15m)
```

## Limitations

This PR redacts extracted text and selected metadata before embeddings, search indexing, prompts, and metadata persistence. It does not claim that raw binary artifacts are format-redacted. When upload DLP can enforce a block or redaction, enhanced citations are disabled instead of storing raw source blobs. A future format-aware derivative generation or quarantine workflow is needed to produce sanitized binary copies.

Regex DLP is limited to deterministic structured identifiers and administrator-defined exact-format identifiers. It is weaker for names, addresses, contextual PII, international identifiers, and noisy document text. Presidio remains the likely next step for richer contextual PII detection, but it is not wired into runtime execution in this PR.

## Testing And Validation

Functional coverage:

- `functional_tests/test_upload_dlp_redaction.py`
- `functional_tests/test_dlp_regex_rules.py`
- `functional_tests/test_upload_dlp_workspace_scopes.py`
- `functional_tests/test_upload_dlp_ingestion_integration.py`
- `functional_tests/test_dlp_admin_ui_smoke.py`
- `functional_tests/test_dlp_review_events.py`
- `functional_tests/test_dlp_telemetry.py`
- Shared PR1 DLP tests remain green.

Validated with Docker Python 3.12:

- `python -m compileall application/single_app`
- The PR-specific functional tests above.

Additional review-readiness validation:

- `tools/local_dev/render_dlp_admin_preview.py` renders the shared DLP admin section and verifies upload controls are visible in the expanded preview.
- `tools/local_dev/run_dlp_local_stack.md` documents the local Cosmos emulator smoke flow inherited from the web-search DLP branch.
- Independent remediation review verified metadata sanitization, enhanced-citation enforcement, document-level status aggregation, and removal of the dead upload review toggle.
