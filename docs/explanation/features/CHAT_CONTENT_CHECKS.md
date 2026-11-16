# Chat Content Checks

## Overview

**Implemented in version: 0.261.127.** Application version tracking remains in `application/single_app/config.py`.

Content Screening and Azure AI Content Safety have separate administrator-controlled input and output checkpoints for chat. This extends the existing scanners instead of introducing another PII detector or policy editor.

**Dependencies:** the saved global Content Screening baseline for PII/regex/literal/optional model checks; the configured Content Safety connection for Azure category checks; existing chat, Cosmos, cache, and reviewer-role infrastructure. Chat-only text screening does not require Enhanced Citations. Workspace document admission still does.

## Configuration and defaults

Each child switch is effective only beneath its enabled master. Turning a master off retains child selections.

| Scanner | Master | Checkpoint | Default beneath the master |
| --- | --- | --- | --- |
| Content Screening | `enable_content_screening` | `enable_content_screening_workspace_uploads` | On, preserving upload enrollment |
| Content Screening | `enable_content_screening` | `enable_content_screening_chat_input` | Off |
| Content Screening | `enable_content_screening` | `enable_content_screening_chat_output` | Off |
| Content Safety | `enable_content_safety` | `enable_content_safety_chat_input` | On, preserving input coverage |
| Content Safety | `enable_content_safety` | `enable_content_safety_chat_output` | Off |

Chat uses the saved **global** screening baseline. Workspace additions still apply to documents, not arbitrary chat messages. PII patterns are indicators rather than universal detection of every name, address, identifier, or secret. Optional model checks send inspected text to the approved scanner model without enabling agent tools for that scanner.

An empty baseline is valid configuration, but cannot produce a passed chat inspection. Such attempts follow the failure action and are recorded as not checked. Explicitly disabled checkpoints do not fill the unchecked queue.

### Response presentation

`chat_content_output_mode` has two values:

- `stream_then_check` is the default. Text streams normally, then the complete reply is checked. A finding replaces provisional text with a content-check notice.
- `check_before_display` withholds answer-bearing stream events until the decision is available. Processing-note polling follows the hold; authentication and approval handoffs remain usable.

Streaming first is not prevention of initial exposure. A person may read or copy text before it is removed. A held response still follows the failure setting if checking cannot finish.

### Checker failures

`chat_content_scan_failure_action` defaults to `allow_unchecked`: unavailable clients, invalid/missing policies, timeouts, incomplete model coverage, and execution limits allow content through with private **not checked** metadata. The end user sees no outage warning or not-checked badge.

The alternative, `block`, stops input or withholds/replaces output when a required check cannot complete. A known finding always blocks regardless of the failure setting. Permission, source-availability, persistence, and retraction failures are not scanner outages and do not gain an allow-through bypass.

Document admission retains its separate fail-closed hold-and-review behavior.

## Architecture

`functions_chat_content_checks.py` owns shared decisions, safe notices, private metadata, and the terminal replacement contract. It reuses `content_screening.engine.inspect_text_units()` and the Azure adapter in `functions_content_safety.py`.

Submitted text is checked before ordinary message publication and answering/planning work. Normal, agent, retry/edit, saved-analysis, document-action, collaboration, and orchestration chat paths use the shared checkpoints. Reply checks inspect complete assembled text, including patterns split across stream chunks. Retained partial replies also require a decision.

Since **0.261.131**, Gather / Reason / Render replies use the output checkpoint inside the headless publisher, so web streams and scheduler continuations are covered, including model-free file-status republication. A removed reply publishes only the safety notice, without citations or file cards, and later publication never overwrites an administrator's retraction. Run history hides that run's files while a check-before-display reply is pending or after removal; the private file records are not deleted.

Azure analysis uses windows of at most **10,000 Unicode code points**, 500-code-point overlap, a 32-window cap, and an inspection deadline. Every tail is included. Incomplete coverage is not a pass. See the [Azure Analyze Text contract](https://learn.microsoft.com/en-us/rest/api/contentsafety/text-operations/analyze-text?view=rest-contentsafety-2024-09-01).

`functions_chat_content_review.py` binds later rechecks to the stored content fingerprint and Cosmos revision. A retracted reply retains its identity and safe thread information, but ordinary history contains a replacement notice rather than the rejected body. Stale writers, replay sessions, shared mirrors, message inspectors, processing notes, and transcript exports respect that authoritative decision.

The classic stream reader and V2 SSE/store handling use `replace_content` and authoritative `full_content`, including an explicitly empty replacement. A safety notice is not appended to the rejected answer, and a delayed old frame cannot override a known shared-message retraction.

### Private audit metadata

`metadata.chat_content_checks` records checkpoint, origin, scanner results, completeness, safe failure codes, content/policy fingerprints, and attempt information. It is removed from ordinary browser responses and user exports. The public moderation revision does not say whether a check failed.

New incident records contain safe summaries rather than matched PII or raw rejected replies. AI-output incidents are distinguished from user submissions and cannot trigger user warning, suspension, or blocking actions.

## Administrator rechecks

The existing protected safety report includes **Unchecked chat content**, linked from both admin interfaces.

| API | Purpose |
| --- | --- |
| `GET /api/safety/chat-checks` | Bounded metadata-only listing with source, checkpoint, scanner, and continuation filters |
| `POST /api/safety/chat-checks/recheck` | Recheck an identified stored message revision using current applicable rules |

Both endpoints require the safety-review administrative policy, including `SafetyViolationAdmin` when configured. The server resolves the content; it does not accept a browser-supplied message body as the subject.

A later AI-output finding automatically removes the reply. An unsuccessful check leaves previously allowed content available and retryable, even if the stricter failure option is now selected for new chat attempts. User-submission findings are recorded for review; earlier model calls and external actions cannot be reversed.

See [Recheck chat content]({{ '/guides/recheck-chat-content/' | relative_url }}) for the operator workflow.

## Coverage and limits

The new checkpoints cover submitted chat text and final reply text across supported chat modes. They do not add scanning of chat-only attachments, retrieved document/web/tool content, outbound search/tool arguments, standalone workflow/model calls, image pixels, or downloadable-file contents. Existing upload screening and document-metadata Content Safety behavior remain separate.

Removing a reply withdraws its displayed answer and associated cards/links from ordinary chat. It is not secure erasure of prior downloads, separately retained files, external effects, provider-side state, historical backups, or text copied into another conversation.

Rechecks are per record, not scheduled corpus-wide rescans. Correct failing scanner configuration or choose appropriate rules before retrying.

## Validation

Functional coverage includes `test_chat_content_checks.py`, `test_chat_content_review.py`, `test_chat_content_streaming.py`, `test_chat_content_orchestration.py`, `test_orchestration_harness_chat_checks.py`, existing screening/model/settings suites, and `test_v2_chat_content_checks.mjs`. Browser coverage in `ui_tests/test_chat_content_checks.py` exercises real classic and V2 controls, stream readers and the React store, and the admin recheck workflow with synthetic data.

The main cases cover master/child combinations, deterministic findings, long/Unicode text, quiet allow-unchecked behavior, held versus provisional replies, stale revisions, authoritative replacements, shared mirrors, and preservation of document holds.
