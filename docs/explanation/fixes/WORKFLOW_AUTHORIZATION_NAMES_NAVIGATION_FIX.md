# Workflow authorization names and navigation fix (0.261.374)

Fixed in version: **0.261.374**

The application version is recorded in `application/single_app/config.py`.

## Issue and root cause

User Settings and classic Profile rendered each workflow authorization as
`Workflow <GUID>`. Users could revoke it but could not identify the workflow by
name or open it to inspect what it did. Both clients hard-coded the identifier,
and the shared bindings response contained no workflow display projection.

## Technical details

`application/single_app/route_backend_m365.py` now enriches
`GET /api/m365/bindings` with an access-checked `workflow` projection:

```json
{
  "id": "workflow-id",
  "name": "Morning mail digest",
  "scope_type": "group",
  "group_id": "team-id"
}
```

Personal workflows use `scope_type: "personal"` and `group_id: null`.
Personal reads use the signed-in user's partition and verify returned ownership.
Group reads require current group membership and the existing workflow feature
and assignment rules before fetching workflow metadata. Group scope comes from
the authorization's recorded context, not its top-level `group_id`, which is
the authorization subject's storage partition.

Names come from current storage, so older authorizations need no migration and
renames appear on refresh. Blank names use **Untitled workflow**, not a GUID.
Point responses are consumed as mappings; only a new plain dictionary of display
fields is returned. Duplicate revisions share one workflow lookup per request
but remain separate authorization rows.

Missing, deleting, or inaccessible workflows are excluded. Stored authorization
and audit history are not deleted, and reading the list does not introduce an
automatic revocation. Existing execution checks remain authoritative. Storage
outages produce the existing safe service error instead of being mistaken for
deleted workflows.

The existing record-based page size and continuation token are preserved.
Filtering can produce an empty page with more records, so both interfaces explain
that state and retain **Load more authorizations**.

## Interface behavior

`application/v2_ui/src/components/settings/M365Cards.tsx` and
`application/single_app/static/js/profile/profile-m365.js` show the workflow name
with **Open** beside **Revoke**. Open navigates to the selected personal or group
workflow's V2 overview in a new tab, retaining the settings page.

V2 uses the existing router-aware `workflowListHref` builder. Classic Profile
builds a same-origin V2 path with encoded identifiers. Both use
`noopener noreferrer`, an opening indicator, and a workflow-specific accessible
label. Names render as text, including HTML-looking names. Revoke retains its
confirmation, CSRF protection, eligibility checks, and refresh behavior.

No new routes, capabilities, dependencies, deployer changes, or changes to
approval fingerprints are required.

## Validation

Regression coverage is in:

- `functional_tests/test_m365_routes.py`: current names and renames, minimal
  projections from SDK `CosmosDict` responses, subject/tenant isolation,
  personal/group scope checks, membership removal, feature access, deletion,
  duplicate revisions, pagination, safe outage errors, and retained audit data.
- `ui_tests/test_v2_settings_m365_connections.py`: real V2 components with
  production CSS, personal/group Open links under the `/v2` router basename,
  keyboard activation in a new tab, retained original page, confirmed Revoke,
  filtered pagination, malformed responses, and visible load errors.
- `ui_tests/test_m365_lifecycle_and_approvals.py`: real classic Profile scripts,
  named rows, safe new-tab navigation, confirmed revocation, and filtered paging.

The two affected browser suites pass **123 tests**, including desktop/mobile
and light/dark V2 checks. The focused functional and existing consent/preflight checks pass **119 tests**
with **63 subtests**, excluding one unrelated existing notification test whose
group-module fixture no longer supplies the imports its production module needs.
The V2 build/typecheck and the three route-policy test scripts also pass.
The Cosmos inventory reports **zero review gaps**, and the changed-owner SDK
contracts pass with network access blocked. Documentation coverage/site checks,
XSS/access-control guardrails, and the UI mechanical scan also pass.

The repository-wide Cosmos contract run is blocked during unrelated test
collection by the installed OpenSSL dependency (`GEN_EMAIL` is unavailable).
The focused changed-owner contracts run successfully without changing shared
Python packages.

The deterministic browser fixtures do not validate live Azure authentication or
Microsoft 365 tenant permissions. Screenshots are local test artifacts under
`ui_tests/artifacts/workflow-authorizations/`, not committed media.

## Impact

Before, users had to recognize a GUID and find the workflow elsewhere.
After, they can identify it by its current name and inspect it directly, while
retaining control of each authorization and no longer seeing unavailable
workflows in this list.
