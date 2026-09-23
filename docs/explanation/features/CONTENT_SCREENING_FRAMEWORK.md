# Content Screening Framework

## Overview

Content screening creates an admission checkpoint between document extraction and usable workspace knowledge. It combines deterministic rules with optional model-based inspection and keeps a document unavailable while a required scan or review is outstanding.

**Implemented in version: 0.261.106.** The application version is managed in `application\single_app\config.py`.

**Current documentation version: 0.261.131.** Orchestration harness integration with chat checkpoints was implemented in 0.261.131. Chat checkpoints and strict retained-result source-authority errors were implemented in 0.261.127; enabled-empty policy configuration was implemented in 0.261.114; classic/V2 policy-editor alignment was implemented in 0.261.108; the original framework implementation remains 0.261.106.

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

An enabled policy may contain no checks. Enabling Content Screening creates an enabled empty baseline only when no policy exists, without selecting detectors or a scanner. New uploads with no effective checks follow ordinary processing without a screening marker, evidence, or a fabricated passing result. Enabled workspace additions may supply checks under an empty enabled baseline. A disabled baseline still disables additions, and persisted document holds retain their release requirements.

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

### Retained-result authority failures

**Implemented in version: 0.261.127** for [#1509](https://github.com/microsoft/simplechat/issues/1509); version tracking remains in `application\single_app\config.py`.

A temporary Cosmos or authority-service outage is not evidence that a previously authorized source was revoked or placed under review. Retained orchestration results use a strict server-owned access path so discovery and output retries fail explicitly instead of silently omitting those results. The path still reads current document metadata, permissions and screening release proof; it never uses a saved manifest or cached positive decision as authority.

| Outcome | Strict service behavior |
| --- | --- |
| Transport timeout, connection failure, HTTP 408/429 or 5xx | `SourceAuthorityUnavailableError`, code `source_authority_unavailable`, `retryable=True`. |
| Malformed authority response or a nontransient backend/configuration failure | `SourceAuthorityUnverifiedError`, code `source_authority_unverified`, `retryable=False`. |
| Existing typed screening error | Preserve its type and stable code; configuration/validation/conflict errors are not retryable. |
| Current denial, missing document, known hold, invalid release proof or snapshot conflict | Continue to refuse access; no fallback to retained content or a model. |

Bootstrap owners bind `resolve_orchestration_source_manifest(requested_sources, user_id, ...)` and `read_orchestration_source_metadata(document_id, user_id, group_id=None, public_workspace_id=None)` from `functions_orchestration_source_access.py`. The resolver accepts the existing mixed-source selection, conversation, active-scope and cancellation arguments. `OrchestrationResultAccess.authorize_sources` uses the strict helper for fresh manifest and metadata checks, including injected runtime readers. Strict search resolution bypasses the legacy document reader's `None`-on-error fallback without changing ordinary search or workflow defaults.

The additive `assert_document_available(..., strict_errors=True)` and `assert_evidence_available(..., strict_errors=True)` APIs are server-only choices, not request settings. A headless owner that catches source errors must wrap its entire source decision/model phase in `with strict_source_authority():`; nested checks retain the first failure until that operation ends. Flask requests additionally retain the existing request-local model fence. Independent operations do not share a global failure flag.

Only `public_message`, `code`, `retryable` and `status_code` are suitable for public error responses. Do not serialize exception strings, causes or SDK diagnostics. Legacy screening/search callers outside this explicit path keep their existing fail-closed behavior.

Importing the source-access contracts does not import telemetry, settings or configuration owners. Runtime failure reporting resolves `log_event` only after recording the model fence; import-order checks cover both normal and optimized Python without provider access.

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

`enable_content_screening` is disabled by default. Enhanced Citations and working storage are required for workspace upload screening and explicit document scans. In **0.261.127**, chat-only use can leave `enable_content_screening_workspace_uploads` off and does not require Blob storage. Review the selected model's data routing and workload before enabling model checks.

Since **0.261.107**, both interfaces expose **Admin Settings > Security > Content Screening** independently of Content Safety. The V2 policy editor loads and saves the protected policy through its dedicated API, supports sample inspection and configured-model selection, and remains visible before Enhanced Citations is enabled. Main settings saves no longer report success when persistence fails.

Since **0.261.108**, both editors offer explicit custom literal/regex/PII creation and the same server-defined starter packs. Re-adding a pack preserves existing rule IDs, edits, and disabled rules. Deterministic rules do not call a model.

The optional **Enable AI checks** switch precedes the policy's single scanner and criteria. Turning it off disables those inputs without clearing the configuration. **Models workspaces may use** is a separate administrative allowlist, not a list of model checks to execute. The baseline scanner's implicit permission is displayed without copying it into the explicit allowlist.

Configured-check summaries count enabled local and mandatory baseline rules/model checks. Disabling workspace additions does not hide required administrator AI checks; a disabled baseline makes additions inactive. Summaries describe the draft rather than the separate enrollment capability.

Since **0.261.114**, enabling and saving the feature no longer requires selecting checks first. Enabled empty policies can be saved, and the summary explains that new uploads are not screened until applicable checks are added. The classic toggle persists immediately; V2 uses **Save changes**. Both editors refresh an automatically created baseline without discarding policy drafts or silently overwriting a concurrent administrator's edits. Detailed policy changes still use **Save screening policy**. Sample testing requires checks to evaluate and never describes an empty policy as a clean inspection.

The **0.261.113** React V2 integration retains these controls alongside unified embedding/image connections and durable Analyze results. Sequential and isolated concurrent Analyze model calls recheck source availability, final coverage retains screening provenance, and completed checkpoints cannot bypass a later hold. Saved-result responses and exports retain both their source-access rules and screening checks.

Use the [content-review guide]({{ '/guides/review-screened-documents/' | relative_url }}) for baseline selection, existing-workspace scans, and remediation. The capability is distinct from the existing Azure AI Content Safety chat-category feature.

The shared API family is `/api/content-screening/...`; its policy, job, and review operations use authenticated Blueprints and object-level scope authorization. Detailed evidence is separate from ordinary document-list responses.

## Coverage and limitations

Functional coverage lives in `functional_tests\test_content_screening_*.py`, with route-policy coverage under `functional_tests\route_tests\` and classic/V2 browser workflows under `ui_tests\`.

`ui_tests\test_content_screening_policy_parity.py` runs the same custom-rule, starter-pack, AI-toggle, permission, and inherited-summary workflows against both real interfaces, including narrow and desktop layouts. Logic/rendering regressions cover the V2 helpers, and the engine tests prove that saved scanner references and permission lists do not invoke disabled AI checks.

Enabled-empty policy coverage also exercises first activation, save/reload without checks, later starter-pack insertion, clearing the last check, draft preservation, and concurrency. Backend coverage distinguishes unmarked new uploads with no applicable checks from previously enrolled or held documents; empty policies do not bypass review or publication proof.

The core cases include a last-page finding, complete window coverage, regex deadlines, strict model responses, sticky review holds, authorization, revision conflicts, safe derivatives, and recovery from partial publication.

`functional_tests\test_orchestration_source_access.py` exercises strict metadata and scope-service failures, the real mixed-source/search resolver, retained-result discovery and reopen, unchanged legacy defaults, caught-error model fences, concurrent scope isolation and network-blocked cold imports in normal and optimized Python. `test_content_screening_access.py` continues to cover the original default-mode sanitization and model-fallback fence.

The document adapter covers workspace knowledge, including chat files handed off to a workspace. **0.261.127** adds [chat text checkpoints]({{ '/explanation/features/CHAT_CONTENT_CHECKS/' | relative_url }}) that reuse its global baseline without changing document holds or workspace review. Since **0.261.131**, Gather / Reason / Render orchestration replies use the same output checkpoint before publication, including model-free delivery. Chat-only attachment screening, outbound web-search preflight, and agent-to-agent message inspection remain outside these checkpoints.

Formatting-based hidden-text detection and layout-preserving PDF/Office redaction remain separate work. Neither regex nor a model guarantees that all sensitive information or prompt injection will be found. Previously downloaded content and requests already sent to a provider cannot be recalled.
