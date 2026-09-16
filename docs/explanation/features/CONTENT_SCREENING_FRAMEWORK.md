# Content Screening Framework

## Overview

Content screening creates an admission checkpoint between document extraction and usable workspace knowledge. It combines deterministic rules with optional model-based inspection and keeps a document unavailable while a required scan or review is outstanding.

**Implemented in version: 0.261.106.** The application version is managed in `application\single_app\config.py`.

**Dependencies:** Enhanced Citations and its configured storage account, the existing Cosmos DB and workspace knowledge services, and an approved model connection when a policy includes model evaluation.

**Related issue:** [#1476](https://github.com/microsoft/simplechat/issues/1476). Related work includes document/chat PII (#341), message alerts (#375), outbound preflight (#992), and formatting-aware extraction (#1142).

The motivating case is text that is easy to miss in a visual document, such as white text that tells an AI to value that document more highly than other sources. Screening inspects extracted text regardless of its original appearance. It does not infer font color or prove that every hidden layer was extracted.

## Architecture and data flow

The reusable `application\single_app\content_screening\` package separates policy/evaluation from the workspace-document adapter. Its contracts describe a subject, source revision, canonical content units, effective policy, grounded findings, and coverage.

New enrolled documents are held before ordinary processing is queued. Their source and extracted content are retained privately. The existing processors supply canonical pages, text, table cells, and transcript segments without embedding or publishing early chunks. Publication happens only after the complete verdict and any required human decision.

The document record contains a small screening marker. Detailed evidence and canonical content live in private artifacts in the Enhanced Citations storage account; policy, scan, job, and audit metadata live in the screening repository. Normal application settings do not contain the detailed finding payload.

Cosmos state is authoritative. Search projections, cached results, native table reads, source previews, historical citations, and repeated source-context use must honor the current document decision. A stale index entry or cached snippet is not permission to use the document.

Release also records the exact approved Blob and content-derived metadata fingerprints. Restoring a document marker without its completed scan, or changing an abstract or tag after inspection, does not create a valid clearance. Ordinary lists return status-only metadata when that proof is unavailable.

## Policies and evaluators

Administrators define a required baseline. Authorized workspace managers can add rules and instructions, but a workspace pass cannot cancel a baseline finding.

| Evaluator | Intended use | Important limit |
| --- | --- | --- |
| Structured PII patterns | Identify common structured identifiers, email/phone patterns, and similar recognizable values. | Patterns are not a universal detector of names, addresses, or all regulated data. |
| Literal values and phrases | Flag known project identifiers, restricted phrases, or organization-specific values. | Match configuration and normalization matter; inspect representative samples. |
| Custom regex | Express organization-specific structured patterns. | Invalid expressions and execution-budget failures do not count as a clean scan. |
| Configured model | Inspect context-dependent instructions, source-ranking manipulation, secrets, or custom sensitivity criteria. | Model findings are risk signals, not proof of malicious intent or guaranteed detection. |

Model checks use configured model connections rather than an implicit classic GPT deployment. The evaluation scaffold treats source material as data and provides no tool or URL-execution capability. Responses must identify valid source units and satisfy the result schema.

Policies can inspect pages, chunks, or bounded groups. Oversized units and the final tail still require coverage. A timeout, refusal, malformed result, unsupported configuration, or incomplete window does not silently become a pass.

## Availability and review

| State | What users can do |
| --- | --- |
| Pending/scanning | See safe processing status, but cannot use the content in ordinary knowledge operations. |
| Error/incomplete | Correct the prerequisite or retry; the document stays held. |
| Pending review | Authorized reviewers can inspect evidence and decide how to proceed. |
| Remediating/publishing | Wait for the candidate to complete inspection and publication. |
| Cleared | Use the document subject to its normal access and revision rules. |
| Approved with flags | Use the document with a retained warning and recorded acceptance. |
| Rejected/deleting/deleted | The document is not available as knowledge. |

Personal owners and group/public workspace Owners, Admins, and DocumentManagers can review within their scope, including their own uploads. Permission to launch an all-workspace scan is not unrestricted permission to inspect private evidence.

Reviewers can accept findings with a reason, remove a page or segment, remove an exact span, change or clear structured data, keep the document held, or delete it. Edits are checked against the content hash, source location, and review revision; stale decisions require a refresh.

A clean-looking retry does not silently erase an unresolved finding. Review expiry, a disabled feature, or a changed rule is not an approval.

## Clean derivatives

Remediation changes canonical knowledge and produces a clean text or structured-data derivative. It does not draw a box over text and call the original file redacted.

Removed material must not remain in released chunk overlap, abstracts, metadata, native table inputs, previews, or citation copies. Retained originals remain reviewer-only after remediation. Ordinary tools must not fall back to those originals.

For text documents, the clean download is a text representation with available source-page references. Spreadsheet derivatives preserve reviewed cell data without retaining macros, active formulas, or original formatting. Cached spreadsheet formula values can be absent if the source workbook was not recalculated and saved; screening does not execute formulas to fill them in.

Page removal is offered only for a genuine page mapping. A synthetic chunk or a legacy indexed segment is identified as such rather than being presented as a physical page.

## Existing workspaces and recovery

Administrators can inspect selected documents/workspaces or run an all-workspace job. Workspace managers can inspect their own authorized documents.

Queued documents retain their previous availability until their individual scan starts. Once started, a document stays held on findings, incomplete coverage, or errors. Jobs persist their selection, progress, leases, and work-item state so a worker restart does not imply approval.

Where necessary, an existing source is extracted again to obtain canonical content. If a retained original is unavailable, an indexed-text snapshot must be labeled with its limited provenance. A tabular schema summary is not a substitute for inspecting the native table's cell data.

Cancellation does not release a document already being inspected. Concurrent source changes, a new required policy, or a stale reviewer decision invalidate the old release attempt.

Source-bound conversation history and exports withhold unavailable attachments and tool evidence. Remediated workspace attachments are refreshed from the current clean representation. Legacy native tool results that have no matching revision proof must be regenerated rather than borrowing a later approval.

Automatic metadata generation uses admitted source content. New metadata changes are held and inspected before they replace the knowledge projection.

## Configuration and usage

`enable_content_screening` is disabled by default. Enhanced Citations and its working storage configuration are required before activation. Review the selected model's data routing and the expected workload before adding model checks to a broad workspace scan.

Use the [content-review guide]({{ '/guides/review-screened-documents/' | relative_url }}) for baseline selection, existing-workspace scans, and remediation. The capability is distinct from the existing Azure AI Content Safety chat-category feature.

The shared API family is `/api/content-screening/...`; its policy, job, and review operations use authenticated Blueprints and object-level scope authorization. Detailed evidence is separate from ordinary document-list responses.

## Coverage and limitations

Functional coverage lives in `functional_tests\test_content_screening_*.py`, with route-policy coverage under `functional_tests\route_tests\` and classic/V2 browser workflows under `ui_tests\`.

The core cases include a last-page finding, complete window coverage, regex deadlines, strict model responses, sticky review holds, authorization, revision conflicts, safe derivatives, and recovery from partial publication.

This release covers workspace knowledge, including chat files handed off to a workspace. It does not add ordinary message screening, chat-only attachment screening, outbound web-search preflight, or agent-to-agent message inspection.

Formatting-based hidden-text detection and layout-preserving PDF/Office redaction remain separate work. Neither regex nor a model guarantees that all sensitive information or prompt injection will be found. Previously downloaded content and requests already sent to a provider cannot be recalled.
