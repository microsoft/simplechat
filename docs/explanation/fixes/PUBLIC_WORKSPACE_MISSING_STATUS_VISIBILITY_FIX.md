# Public workspace missing-status visibility fix

Fixed in version: **0.261.355**, tracked in
`application/single_app/config.py`.

## Issue and root cause

New public workspaces did not persist `status`. Chat and workspace settings
already treated an absent status as active, but the native public directory
reported it as unknown. Its existing availability guard correctly prevented a
hidden unknown-status workspace from being made visible for chat. A processed
document could therefore be readable inside its workspace while absent from
the ordinary document picker, with no usable directory control to include it.

Both directory projections needed correction: the list query's row projector
and the full-document projector used by membership mutation responses.
Correcting only the list would let a request or cancellation replace an active
row with an unknown one again.

## Generalized change

`functions_public_workspaces.py::create_public_workspace` now saves active
status explicitly. In `functions_public_directory.py`, `_directory_row` and
`build_public_directory_row` apply the existing active compatibility default
only when the field is absent.

| Stored status | Directory before | Directory after | Chat eligibility |
| --- | --- | --- | --- |
| Absent | unknown | active | Allowed |
| active | active | active | Allowed |
| locked | locked | locked | Allowed |
| upload_disabled | upload_disabled | upload_disabled | Allowed |
| inactive | inactive | inactive | Denied |
| null, empty, or unrecognized | unknown | unknown | Denied |

No migration or write-on-read repair is needed. The fix does not alter roles,
membership, publication or screening rules, or saved visibility preferences.
The React availability guard remains unchanged. A user still explicitly enables
visibility for a hidden eligible workspace; Current context is not silently
broadened to All public workspaces.

See [Public Directory APIs](../features/PUBLIC_DIRECTORY_APIS.md) and
[Use public workspaces](../../guides/use-public-workspaces.md).

## Regression coverage and validation

`functional_tests/test_public_workspace_status_compatibility.py` exercises the
real creator with SDK-shaped point responses, missing-versus-invalid statuses
for owners and ordinary readers, both directory projections, membership
request/cancel responses, safe response fields, and absence of writes on reads.
It also renews runtime evidence for the storage module's response consumers;
the reviewed contracts are in
`functional_tests/cosmos_response_boundaries.json`.

The new backend regression initially reproduced four failures against the old
code. After the fix all 19 cases pass. Existing directory, membership, public
scope, and hidden-document regressions also pass: **150 tests** across the
five focused backend files.

`ui_tests/test_v2_public_workspace_status_compatibility.py` passes six Azure
Playwright browser cases, using real backend-produced rows and scope resolution.
It covers desktop/mobile layouts in light/dark themes, keyboard visibility
changes and reload persistence, membership row replacement, explicit status
restrictions, preservation of unrelated choices, and source selection in
Current context versus an explicit All choice.

The existing directory visibility and membership browser selectors pass another
17 cases, for **23 browser cases** overall.
`python scripts/check_cosmos_response_boundaries.py --run-contracts` passes
**1,216 tests and 244 subtests** with external networking blocked and no storage
review gaps. Validation used the repository's pinned dependencies in an isolated
session environment, with tokenizer assets cached before network blocking.
Route-policy checks, documentation coverage and site-quality checks, and the
13 public-directory JavaScript visibility checks also pass.

## Live investigation limits

The reported source-picker failure occurred before any prompt was submitted.
Relevant source requests returned HTTP 200; the public document request took
316 ms. Telemetry did not contain its response body. Read-only inspection
confirmed a missing-status workspace and a processed current document revision.
Current visibility settings were modified after the failure and are not treated
as an exact historical snapshot.

This change is not a deployment or a claim that the original live journey's
model answer and citation passed. Harness findings are kept separately from
the product implementation; no harness or production data changes are required
by this fix.
