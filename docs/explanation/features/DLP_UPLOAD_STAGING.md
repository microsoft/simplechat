# DLP Upload Staging

## Overview

Version: 0.242.074

Dependencies: shared DLP core, configurable regex DLP rules, optional external Presidio Analyzer-compatible endpoint, document processing pipeline, Azure AI Search, Azure OpenAI embeddings.

SimpleChat now applies DLP to extracted upload text and selected document metadata before embeddings, Azure AI Search indexing, metadata extraction prompts, Cosmos metadata updates, and file-processing logs. The feature reuses the shared DLP core introduced for web-search egress and applies it to `save_chunks()`, `save_chunks_batch()`, `save_video_chunk()`, and metadata extraction/update paths.

Regex DLP remains the lightweight default engine. The default rules detect U.S. SSNs and Luhn-valid credit card numbers, and administrators can add upload-specific regex rules through the shared `dlp_regex_rules` settings payload. Administrators can also select `presidio_endpoint` to call an external Presidio Analyzer-compatible endpoint for richer upload text and metadata detection without embedding Presidio in SimpleChat.

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
- The external Presidio Analyzer endpoint path sends extracted text and selected metadata to an administrator-managed analyzer endpoint, receives spans, and normalizes them into the same counts-only DLP result shape used by regex scanning.
- SimpleChat does not embed Presidio packages or run an in-process analyzer.
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
- Choose the default engine: regex structured identifier scan or external Presidio Analyzer endpoint.
- Configure the Presidio Analyzer endpoint, auth header, secret environment variable name, timeout, score threshold, and entities when `presidio_endpoint` is selected.
- Upload mode: `monitor`, `redact`, or `block`.
- Fail upload on match.
- Custom Regex Rules, shared with web-search DLP.

Review routing defaults to `none`. Upload review-event writing is not exposed in this release because the DLP review destination is intentionally locked to `none`.

## External Presidio Analyzer Endpoint

Administrators can select an external Presidio Analyzer-compatible endpoint as the DLP engine by setting the engine to `presidio_endpoint`. SimpleChat sends upload text and selected metadata to the endpoint from the server side, receives entity spans, and then performs monitor, redact, or block behavior locally before embeddings, Azure AI Search indexing, metadata extraction prompts, Cosmos metadata updates, and file-processing logs.

This is Option C for Presidio integration: Presidio runs outside SimpleChat. The SimpleChat application image has no embedded Presidio dependency, model package, or analyzer runtime. Regex DLP remains available as the default and fallback path.

Production deployments should keep the analyzer private and authenticated. Use a private network path plus an API key header or equivalent service boundary, and never expose a public unauthenticated Presidio Analyzer endpoint. SimpleChat stores only the configured secret environment variable name, such as `PRESIDIO_DLP_API_KEY`; the API key value belongs in App Service settings or a Key Vault reference.

The analyzer receives raw extracted text before redaction. SimpleChat, proxies, wrappers, analyzer containers, and platform diagnostics must not log raw request bodies, response bodies, chunk text, OCR text, vision text, metadata values, matched values, or analyzer explanations. Stored DLP metadata and telemetry remain counts-only.

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

Regex DLP is limited to deterministic structured identifiers and administrator-defined exact-format identifiers. It is weaker for names, addresses, contextual PII, international identifiers, and noisy document text. Use the external Presidio Analyzer endpoint when richer recognizers are needed and the production analyzer can be kept private, authenticated, and free of raw text logging.

## Testing And Validation

Functional coverage:

- `functional_tests/test_upload_dlp_redaction.py`
- `functional_tests/test_dlp_regex_rules.py`
- `functional_tests/test_upload_dlp_workspace_scopes.py`
- `functional_tests/test_upload_dlp_ingestion_integration.py`
- `functional_tests/test_dlp_admin_ui_smoke.py`
- `functional_tests/test_dlp_presidio_endpoint.py`
- `functional_tests/test_dlp_presidio_engine_integration.py`
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
