---
description: "Use when: auditing SimpleChat file upload, document ingestion, blob storage, parsing, indexing, downloads, citations, generated artifacts, MIME validation, filename handling, or document security."
name: "File Upload And Document Ingestion Security Audit"
argument-hint: "Target upload routes, document helpers, parser flow, file type, workspace scope, scan only, or fix findings"
agent: "agent"
---

# File Upload And Document Ingestion Security Audit

Audit SimpleChat file upload, document ingestion, blob storage, parsing, indexing, generated artifacts, downloads, citations, and document-derived browser rendering for security issues.

Use the repository guardrails in [.github/instructions/broken-access-control-prevention.instructions.md](../instructions/broken-access-control-prevention.instructions.md), [.github/instructions/xss-prevention.instructions.md](../instructions/xss-prevention.instructions.md), [.github/instructions/local_browser_assets.instructions.md](../instructions/local_browser_assets.instructions.md), [.github/instructions/python-lang.instructions.md](../instructions/python-lang.instructions.md), and [.github/copilot-instructions.md](../copilot-instructions.md).

## Operating Rules

- Work in the SimpleChat repository root.
- Treat filenames, file metadata, MIME types, parser output, extracted text, generated summaries, blob paths, search chunks, and citation snippets as untrusted.
- Do not revert unrelated user changes.
- If the user asks for `scan only` or `stop after plan`, do not edit files.
- If fixing findings, keep changes focused and preserve existing personal, group, and public workspace behavior.

## Baseline Discovery

1. Confirm the repo root, current branch, and concise `git status --short`.
2. Inventory upload, ingestion, storage, parsing, and download surfaces:

```powershell
rg -n "upload|download|send_file|send_from_directory|Blob|blob|container|filename|secure_filename|mimetype|content_type|content-type|parse|extract|chunk|index|citation|artifact|open\(|read\(|write\(" application/single_app
```

3. Search document and blob helpers:

```powershell
rg -n "functions_documents|functions_content|functions_search_service|functions_group|functions_public_workspaces|document_id|file_id|blob_name|blob_path|source_path|metadata_storage_path" application/single_app
```

4. Search browser rendering of document-derived values:

```powershell
rg -n "filename|document_title|document_name|citation|snippet|chunk|content|summary|metadata|innerHTML|insertAdjacentHTML|marked\.parse|\|safe" application/single_app/templates application/single_app/static application/single_app/*.py
```

5. Run relevant deterministic checkers where useful:

```powershell
python scripts/check_broken_access_control.py --full-file <target-python-files>
python scripts/check_xss_sinks.py --full-file <target-browser-files-and-routes>
```

## Manual Audit Checklist

Review these areas:

- Upload route decorators, user role checks, workspace membership checks, document ownership checks, and object-level authorization before blob, Cosmos, or search operations.
- File size limits, allowed extensions, MIME/content-type checks, parser selection, parser error handling, and rejection behavior.
- Filename normalization, path traversal prevention, blob name construction, temporary file paths, archive extraction, and generated artifact names.
- Parser safety for PDFs, Office files, images, HTML, Markdown, CSV/XLSX, PPTX/DOCX, Visio, audio/video, and any external converter such as FFmpeg.
- Whether parser output, OCR text, extracted HTML, markdown, metadata, citations, or model summaries can reach browser HTML sinks without safe rendering.
- Whether downloads, citation source links, profile images, generated artifacts, and blob fallback paths revalidate ownership or workspace membership.
- Whether document indexing, chunk retrieval, search filters, and approval/publishing flows can cross personal, group, or public workspace boundaries.
- Cleanup of temporary files and partial blobs after failed parsing or indexing.
- Malware-like risks within the app boundary: macro-enabled files, embedded scripts, remote image references, compressed bombs, oversized documents, malformed files, and parser resource exhaustion.
- Logs and activity records that may include full document text, sensitive filenames, SAS URLs, or extracted PII.

## Triage And Plan

Group findings before editing:

- `Critical`: Unauthorized users can upload, read, download, overwrite, index, delete, or render another user’s document/blob/artifact, or uploaded content can execute in a browser.
- `Important`: Parser output, filenames, citations, blob paths, or generated artifacts cross a trust boundary without validation, sanitization, or ownership checks.
- `Moderate`: File validation, size limits, cleanup, logging, or parser error handling is incomplete and could cause data leaks or denial of service.
- `Low`: False positives, static-only paths, or reviewed exceptions.

For each finding, record:

- Surface and file path.
- Untrusted file-derived source.
- Sensitive sink.
- Missing validation, sanitizer, or authorization check.
- Realistic impact.
- Remediation approach.
- Minimum regression test.

## Remediation Patterns

Use these fixes by default:

- Revalidate ownership, group membership, public workspace authorization, or admin role immediately before blob, Cosmos, search, or download operations.
- Normalize and constrain filenames and blob paths with existing helper patterns.
- Treat MIME type and extension as hints; validate parser eligibility server-side.
- Enforce file size and parser limits before expensive processing.
- Render document-derived text with `textContent` or explicit markdown sanitization before browser insertion.
- Avoid logging full document content, SAS URLs, or sensitive metadata.
- Clean up temporary files and partial blobs on failure.
- Add functional tests for the fixed upload, download, parser, or workspace authorization path.

## Verification

After fixing, run the narrowest reliable checks:

- `python -m py_compile <changed-python-files>`.
- `node --check <changed-js-files>` when JavaScript changed.
- Relevant functional tests under `functional_tests/`.
- Relevant UI tests when browser document behavior changed.
- `python scripts/check_broken_access_control.py --full-file <changed-python-files>` for authorization-sensitive changes.
- `python scripts/check_xss_sinks.py --full-file <changed browser files/routes>` for rendering changes.
- `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check`.

If a check cannot run locally, explain why and include the remaining risk.

## Output Expectations

Return findings first, ordered by severity. Include scope scanned, file types and workflows reviewed, files changed, validation commands run, skipped checks, false positives, and remaining risks.