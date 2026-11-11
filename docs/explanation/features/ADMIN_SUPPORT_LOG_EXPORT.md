# Admin diagnostic support ZIP exports (v0.261.428)

## Overview

Administrators can collect retained diagnostic evidence by user, conversation,
and time without asking a developer to operate Azure tooling. The download is a
private support ZIP containing structured logs, a readable timeline, source
coverage, privacy-check results, and optionally approved personal transcripts.
Nothing is emailed or uploaded to the development team automatically.

Implemented in version: **0.261.428**, tracked by `VERSION` in
`application/single_app/config.py`. Related issue: [#1916](https://github.com/microsoft/simplechat/issues/1916).

## Dependencies and access

- The regular SimpleChat **Admin** role opens the export tool. A
  `ControlCenterAdmin` or dashboard-reader role alone does not grant access.
  Control Center delegation settings govern that surface, not this separate
  Admin Settings capability.
- Azure telemetry uses the existing pinned Azure Monitor Query SDK and the
  application's `DefaultAzureCredential` identity. No ingestion key or
  browser-held credential grants query permission.
- Configure the Application Insights resource ID and, for optional console
  logs, the App Service resource ID. Queries use **resource context**, not an
  unrestricted workspace query. Commercial and US Government clouds are
  supported.
- Grant resource-scoped monitoring read access to the application identity.
  The connected Log Analytics workspace must use **Use resource or workspace
  permissions** for resource-only RBAC. A workspace configured to **Require
  workspace permissions** also requires workspace/table read permission;
  SimpleChat does not grant it or change the workspace access mode.
- Export staging uses the existing application Blob storage configuration,
  even if Enhanced Citations itself is disabled, with a separate private
  `support-exports` container. The identity needs Blob data access and, when
  initializing a missing container, container-creation permission.
- Cosmos metadata lives in the `support_exports` container. The normal web
  background runner or the dedicated scheduler must be running to process
  queued jobs and cleanup. No new package, log collector, or deployment-time
  permission change is required.

## Collection behavior

The tool is under **Admin Settings > Operations > Logging & Health > Support
Log Export** in both interfaces. Exports are immediate operations separate
from the page's Save Settings action.

| Selection | Behavior |
| --- | --- |
| One user | Reads a registered user's diagnostic events, not arbitrary directory profiles. |
| All users | Explicitly includes deployment-wide activity; conversation selection and transcripts are unavailable. |
| Time-based | Uses a half-open UTC range; the initial range is the last hour. |
| Conversation windows | Select one or more metadata-only conversation entries or search by ID. Activity bounds are expanded by editable before/after margins, initially 15 minutes each. |
| Multiple conversations | Overlapping windows are merged; unrelated gaps are not collected. The effective earliest-to-latest span still cannot exceed seven days. |
| Nearby system context | Optional unscoped events are separated from correlated records. Positively attributed other-user events are excluded from a one-user export, but historical untagged events can still contain unrelated activity. |

Conversation lists expose IDs, timestamps, kind, and recorded counts, not
private titles or message bodies. Shared/group conversations can supply log
filters but cannot supply transcripts in this version. Inaccessible stale
shared entries are filtered without hiding later pagination results.

Sources are Application Insights traces, exceptions, requests/dependencies and
application events; Cosmos activity/audit records; optional file-processing
records; and optional App Service console logs already collected in Azure
Monitor. Console collection is not a download of arbitrary host files or Kudu
credentials. An unavailable source must be explicitly excluded. Permission
failures, SDK partial results, timeouts, and limits fail collection instead of
becoming successful empty data.

Future structured events carry hashed user/conversation context where it is
known, with native operation links joining related telemetry.
`log_event(debug_only=True)` now follows the existing tagged debug-forwarding
path while debug logging and the exporter are active. It remains silent when
debug logging is off. This cannot reconstruct older console-only output,
missing correlation, expired records, sampling losses, or uncollected data.

## Privacy processing

Recognizable credentials are always removed. The deterministic pass inspects
complete exportable text using the existing deadline-bound content-screening
detector, including email, common phone patterns, US SSNs and Luhn-validated
card numbers. Known structured personal fields, identifier fields, and IP
addresses receive additional handling. Per-bundle pseudonyms preserve useful
relationships without shipping a reverse mapping or the private salt.

An optional isolated AI pass uses the configured default text model from AI
Connections. It receives only deterministically scrubbed content, has no
tools/actions, and returns validated exact spans; it cannot rewrite logs or
approve a release. The approved destination is fingerprint-bound to the
request and checked against the fresh registry and the model evaluator's
actual binding. A settings cache cannot authorize a different destination.

Every required field/window must complete. Model refusal, invalid spans,
missing configuration, or incomplete coverage blocks the AI-reviewed ZIP.
The administrator can explicitly create a narrower or deterministic-only
request; there is no silent fallback or sampling.

Privacy checking is **best effort**, not a guarantee of anonymity or regulatory
compliance. Logs may contain free-form request text, unusual encodings, names,
or confidential business content that a detector misses. Review the scrubbed
preview and the complete ZIP before sharing through the organization's
approved support process.

## Optional transcript consent

Transcripts are off by default. An administrator can request whole selected
personal conversations; the owner receives a personal notification and reviews
the request under **Approval Requests > Support data** in V2 or **Support data
requests** on the classic page.

The release covers user-visible text messages timestamped through the review
cutoff, with the versions confirmed at approval. It is not limited to the log
time window or the small preview. The owner sees the purpose, requesting
administrator, conversations, cutoff, expiry, privacy mode and default model
when AI inspection is selected.

Approval requires a current snapshot preview and matching fingerprint. A
changed revision requires another review. The approved snapshot is privately
staged and immutable. New messages, changed disclosure, another export, or an
admin role cannot reuse the grant. Download checks also revalidate current
ownership, personal-conversation kind, revisions/availability, grant state and
expiry. The requester alone may access the resulting ZIP.

Only user/assistant text is exported as JSON and Markdown. Hidden prompts,
internal reasoning, attached binaries, source-document bodies and unrestricted
blob downloads are excluded. Inline binary data is omitted from the text.
Decline, revocation, withdrawal, and expiry block release. Downloaded copies
and AI inputs already submitted cannot be recalled.

## Limits and lifecycle

| Limit | Value |
| --- | --- |
| Effective log span, including margins | 7 days |
| Selected conversations | 20 |
| Total records | 100,000 |
| Total uncompressed archive contents | 50 MiB, including readable/structured copies and metadata |
| Complete AI inspection budget | 200,000 input tokens, conservatively reserved with request/output overhead |
| Scope review | Expires after 15 minutes; confirmation binds that exact review |
| Pending consent | Expires after 24 hours |
| ZIP availability | At most 24 hours; an earlier consent expiry also limits downloads |
| Concurrency | One active build per admin, two executing builds per deployment |

The model's smaller context limit still applies. Regex deadlines, source
shape/size guards and model inspection limits can require a narrower request
before the archive-size cap is reached. Oversize requests are rejected rather
than truncated.

Jobs use conditional Cosmos writes and fenced leases, with cancellation and
stale-worker protection. Only sanitized staging and approved snapshots reach
private Blob storage. Downloads are authenticated, checksum-verified,
attachment responses with `Cache-Control: no-store`; there are no public or
SAS download links. Expiry is enforced before physical cleanup. The scheduler
retries cleanup and scans expired orphan blobs even after job metadata TTL,
using a durable bounded cursor. When a deployment has never used exports, it
does not probe missing storage or create background audit noise.

## Bundle structure

`manifest.json` records app/schema version, UTC windows/cutoff, redacted scope,
source exclusions/counts, privacy coverage, consent references, expiry and
checksums. `logs/` contains JSONL records plus `diagnostics.txt`; unscoped system
context stays separate. `privacy-report.json` contains counts and coverage,
not original matched values. `conversations/` exists only for approved text
snapshots. `README.md` explains interpretation and manual sharing.

Preview output is deliberately bounded and marked when truncated; that does
not truncate the archive or privacy inspection.

## APIs and implementation

Admin-protected routes use `/api/admin/support-exports`:

- `GET /readiness`, `POST /configuration`, `POST /initialize-storage`, and
  `POST /test-sources`.
- `GET /users`, `GET /conversations?user_id=...`, and paginated `GET` of the root.
- `POST /review` prepares an immutable short-lived scope. Root `POST` takes
  `request`, `review_id` and `retry_key`; clients reuse the key when retrying
  the same create.
- `GET /<id>` for status; `POST /<id>/cancel`; `GET /<id>/preview`; and
  `GET /<id>/download`.

Subject-protected routes use `/api/support-export-consents`: list/detail,
`GET /<id>/preview`, and `POST /<id>/decision` with `approve`, `decline` or
`revoke`. Approval also requires the fingerprint returned by the preview.
Caller-supplied owner IDs and administrative reviewer roles are not accepted
as consent authority.

Implementation modules are `support_export_contracts.py`,
`support_export_sources.py`, `support_export_privacy.py`,
`support_export_store.py`, `support_export_service.py`,
`functions_support_exports.py`, and `route_backend_support_exports.py`.
Classic assets are local templates and `static/js/support-exports.js`; V2 uses
`SupportExportPanel.tsx`, `SupportExportConsentPanel.tsx`, and the
transport-free `lib/supportExports.ts` contracts.

## Testing and validation

Targeted `functional_tests/test_admin_support_export_*.py` cover real SDK
response shapes/ETags, scoped collectors and sovereign token audiences,
privacy/ZIP contents, consent and tampering, concurrency/expiry, route
authorization, debug correlation and current-model bindings. The startup
regressions import real web/scheduler modules in fresh normal/optimized Python
with external I/O blocked.

`ui_tests/test_admin_support_export.py`,
`ui_tests/test_v2_admin_support_export.py`, and
`ui_tests/test_support_export_consent.py` exercise real support APIs behind
isolated SDK/identity fixtures, including browser downloads, owner decisions,
responsive widths and themes. Existing Azure Playwright connection fixtures
can run them in an authorized configured workspace without provisioning one.
Fixture success does not prove a deployment's Azure permissions, collection
settings or retention; use **Test source access** and an authorized staging
export for that proof.
