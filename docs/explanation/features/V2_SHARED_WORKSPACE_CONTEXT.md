# V2 Shared Workspace Context and Group Shell

## Overview

The shared-workspace foundation gives V2 a safe way to load one selected group
and coordinate changes to the user's active group. It separates a page's explicit
resource target from the saved active preference, so the interface does not
display one group's name with another group's data.

Implemented in version: **0.261.126**, recorded in
`application/single_app/config.py`.

The shared group shell was implemented in version: **0.261.127**, also recorded
in `application/single_app/config.py`. It integrates the existing native group
workflows and Call agent tools into My Workspace's layout.
[Native group document browsing](V2_GROUP_DOCUMENT_BROWSING.md) was added in
**0.261.128**, followed by
[permission-aware document and tag management](V2_GROUP_DOCUMENT_MANAGEMENT.md)
in **0.261.129**. Sharing/approval and other unported editors remain explicit
classic handoffs. Public pages and public context endpoints are not implemented
by these slices.

### Dependencies

- Existing authenticated V2 and group APIs.
- Existing group membership, lifecycle, governance, File Sync, workflow, branding,
  and download-policy helpers.
- The V2 API client, Zustand stores, and local React/Vite build.
- `enable_group_workspaces`; no new application setting or storage migration.

## Context endpoint

`GET /api/v2/workspaces/group/<group_id>` requires a signed-in User/Admin app role,
enabled group workspaces, and current membership in the exact requested group.
An application Admin does not automatically acquire group membership.

The endpoint does not read or change the active-group preference. Bookmarks and
off-page selector entries can therefore resolve a group directly instead of
depending on the first page of a membership list.

| Response field | Purpose |
| --- | --- |
| `schema_version` | Contract version, currently `1`. |
| `enabled` | Group workspaces are enabled; successful contexts satisfy the existing workspace-availability contract. |
| `viewer_id`, `scope` | Bind the response to the current user and requested group. |
| `workspace` | Allowlisted name, description, owner display/email, normalized color, and a local versioned logo URL. |
| `role`, `status` | Effective group role and lifecycle state; unknown stored states are reported as `unknown`. |
| `can_manage_workspace` | Whether the role permits workspace-level management. |
| `sections` | Shared Knowledge/Automation/Connections grouping, availability, management eligibility, and unavailable reasons for each known section. From version **0.261.155** it also reports `members` in a group-only `manage` group: available to every member while the group can be viewed, with `can_manage` for navigation only. See [V2 Group Members](V2_GROUP_MEMBERS.md). From version **0.261.165** the `manage` group also reports `settings`, `activity` and `statistics`, open to the Owner and Admins while the group can be viewed and otherwise locked with "Only the group owner or an admin can do this."; which controls they offer comes from `settings_management`. See [V2 Group Settings, Activity and Statistics](V2_GROUP_SETTINGS.md). |
| `native_delegation` | Eligibility for the already-shipped Call agent interface, which does not depend on the personal-kernel flag required by the full legacy authoring tabs. |
| `document_permissions` | Distinct view, chat, upload, edit, delete, and download eligibility. |
| `document_queries` | Actual current query capabilities, not a promise that personal explorer features already work for groups. |
| `document_management` | Versioned support and current workspace-level operation eligibility; missing support leaves the group interface read-only. |
| `document_collaboration`, `prompt_management`, `action_management`, `agent_management`, `identity_management`, `endpoint_management`, `file_source_management` | The operations each native group surface offers the caller, built by the same policy its routes enforce. Each surface's feature documentation describes its block. |
| `settings_management` | From version **0.261.154**: `{schema_version, operations, reasons}` for the group's settings, activity, statistics and document count, built by the decision the native group settings routes enforce. See [Group Settings APIs](GROUP_SETTINGS_APIS.md). |

Responses use `Cache-Control: no-store`. Raw settings, group membership arrays,
pending requests, endpoint configurations, credentials, and logo bytes are not
included.

Invalid targets, missing groups, and non-members return explicit errors. The
existing feature-disabled decorator retains its `400` contract. An unexpected
policy/service failure returns a safe `503` and is logged server-side; it is not
converted into permissive capabilities or an empty successful workspace.

## Capability rules

Documents and tags are readable by authorized group members when lifecycle
policy permits viewing. Uploads and edits require Owner, Admin, or
DocumentManager. Downloads require those same manager roles plus the deployment
and workspace download policy; ordinary User membership is not sufficient.

Agent/action eligibility follows the existing per-user kernel, Semantic Kernel,
group feature, and governance requirements. Owner-only agent management also
restricts action/workflow management, but does not replace the separate
Owner/Admin endpoint-management rule. Workflow and File Sync availability use
their existing group-assignment and deployment helpers.

Identities and File sources are manager surfaces. Identity availability requires
File Sync or Semantic Kernel; File Sync also retains its Redis readiness,
assignment, and administrator restrictions.

| Status | View/chat | Upload/edit | Document deletion |
| --- | --- | --- | --- |
| `active` | Available by role | Available by role | Available by role |
| `locked` | Available by role | Unavailable | Unavailable |
| `upload_disabled` | Available by role | Unavailable | Available to document managers |
| `inactive` or `unknown` | Unavailable | Unavailable | Unavailable |

The projection deliberately does not broaden legacy visible permissions where
old UI and route policies differ. For example, it does not offer ordinary Users
group prompt editing just because the legacy prompt CRUD guard admits group
membership.

These fields are UI eligibility hints, not grants. Resource endpoints must still
authorize the caller, explicit scope, actual object, operation, ownership/share
relationship, and current policy. The 0.261.128 group read contract advertises
all eight explorer sort fields, facets, and standing views. Version 0.261.129
adds immutable-target management routes and fresh per-document `document_actions`.
Group sharing/approval and additional resource adapters remain later work.

## Client activation contract

`workspaceContext.ts` supplies discriminated personal/group/public references,
viewer-and-scope keys, route helpers, and a validated group-context reader. It
rejects mismatched users/groups, malformed capability records, and nonlocal logo
URLs rather than installing them in page state.

`useGroupWorkspaceStore` coordinates the group shell and Settings activation:

| Action | Behavior |
| --- | --- |
| `load(groupId)` | Read one explicit group without changing the active preference. Superseded reads cannot overwrite a later selection. |
| `revalidate(groupId)` | Refresh the displayed group's access without changing active preferences or dropping drafts on a transient failure. A definitive access denial removes cached context. |
| `activate(groupId, confirmLeave)` | Require the caller's draft guard, preflight access, persist through the existing `setActive` API, refresh bootstrap/catalogs, and read fresh context. |
| `reconcile()` | Read the server's current active preference and context after an ambiguous or partially completed switch, without replaying the mutation. |
| `clear()` | Drop page context and supersede pending reads. It cannot cancel a server mutation already in flight. |

Selection must use `activate`, not just `load`. The shell must supply an actual
unsaved-navigation guard, render the store's error/retry state, and keep resource
controls disabled while loading, activating, or requiring reconciliation.
Availability and native/classic implementation status must remain distinct.

Cancelled confirmation makes no network request. A definitively rejected switch
retains the prior page context. A lost write response or failed post-write refresh
clears usable context and requires reconciliation instead of pretending the
server rolled back.

Activation writes are serialized. A reset does not unlock another write until
the first settles. Request generations and authenticated-user checks prevent
late responses from installing another group's or another user's context.
Identity-bound `refreshRequired(viewerId)` also prevents the selection refresh
from replacing bootstrap with a response belonging to a previous sign-in.
Existing callers that omit the optional viewer argument retain their contract.

This controller does not change an existing conversation, discard its draft,
or override its workspace lock. Subsequent section integrations must carry
explicit scope on every resource request rather than treating activation as
authorization.

## Shared shell and navigation

`WorkspaceShell` owns the rail, shared collapse preference, constrained section
measure, and full-width work-area layout. `WorkspaceOverview` is presentation
only; personal counts remain in the personal `OverviewSection`. The group
overview never calls personal resource endpoints or invents group counts.

The group page supports `/v2/groups`, `/v2/groups/<group_id>`, and scoped section
paths. It restores a valid active group or shows an explicit chooser, keeps
off-page selections while searching/paging, and validates direct links.
Existing workflow query links are routed to the Workflows section. Changing
groups clears an old workflow target rather than opening a same-ID record in
another group.

Available-but-unported sections showed a Classic label and a working handoff,
not a false disabled-by-administrator state. From version **0.261.153** every
group section is native, so no section carries the Classic label or hands off
to classic. A section URL with an item segment that the section doesn't
support, such as `/v2/groups/<group_id>/prompts/<id>`, opens the section itself.
A `/workflows/<id>` segment becomes the `?workflow_id=` link the Workflows
section already understands. From version **0.261.155** a group workspace also
has a **Manage** group holding **Members**, and the same rule covers it:
`/v2/groups/<group_id>/members/<id>` opens the section. Disabled sections explain the
server's reason. Call agent availability remains separate from full group
agent/action authoring, preserving the existing tool under its own policy.

Workflow and delegation drafts prevent group selection until saved or cancelled.
Internal navigation uses the existing discard-dialog pattern; writes in flight
cannot be discarded as if they had not happened. Refocus revalidation keeps
drafts mounted while temporarily disabling mutation controls. The existing
resource APIs still authorize each operation independently.

The Settings group tab uses the same activation and recovery controller.
Context and list state are keyed to the authenticated viewer. No new storage
preference or application capability toggle was added.

## File structure

| File | Responsibility |
| --- | --- |
| `application/single_app/functions_workspace_context.py` | Authorized group projection and capability policy composition. |
| `application/single_app/route_backend_v2.py` | Authenticated, no-store selected-group endpoint and safe errors. |
| `application/v2_ui/src/lib/workspaceContext.ts` | Scope identity, routes, response validation, and context fetch. |
| `application/v2_ui/src/stores/groupWorkspaceStore.ts` | Selection ordering, mandatory refresh, isolation, and recovery. |
| `application/v2_ui/src/stores/bootstrapStore.ts` | Optional viewer binding for mandatory refresh. |
| `application/v2_ui/src/pages/GroupWorkspacePage.tsx` | Group selection, metadata, scoped sections, recovery, and navigation guards. |
| `application/v2_ui/src/components/workspace/WorkspaceShell.tsx` | Shared personal/group section rail and layout. |
| `application/v2_ui/src/components/workspace/WorkspaceOverview.tsx` | Shared overview without resource-loading side effects. |
| `application/v2_ui/src/components/workspace/GroupWorkspacePicker.tsx` | Server-side membership search and paging. |
| `application/v2_ui/src/lib/groupWorkspaceNavigation.ts` | Scoped routes, section copy, and native/classic navigation eligibility. |

## Testing and limitations

`functional_tests/test_v2_group_workspace_context.py` exercises the actual
projection and Flask route definitions with isolated service seams, including
real group-role/status and authentication helper definitions. It covers role and
lifecycle combinations, feature/governance gates, revocation, explicit IDs,
sanitization, failure handling, and the frontend companion.

`functional_tests/test_v2_group_workspace_context_logic.mjs` executes the real
API client and stores against controlled HTTP responses. It covers ordered and
reversed responses, draft cancellation, concurrent switching, lost
acknowledgements, mandatory-refresh failures, revoked access, account changes,
and read-only recovery.

`ui_tests/test_v2_group_workspace_shell.py` runs the production SPA with closed
synthetic HTTP fixtures. It covers selection, metadata, off-page membership,
scope-specific requests, dirty navigation, failed and partial activation,
classic handoff, Settings activation, refocus recovery, role denial, escaped
labels, and desktop/mobile light/dark layouts. Existing workflow suites use a
real selector-and-navigation helper, preserving their authoring, read-only
inspection, and runtime assertions.

`functional_tests/test_group_context_fixture_parity.py` holds the browser
fixture's context to the real one, field by field. Every group browser suite
builds its context with `group_context` in `ui_tests/fixtures/group_workspace.py`.
The test runs the real context builder for:
- every role and status, including an unrecognized status;
- the deployment variants the suites model;
- the fixture's per-section seeds and the setters that recompute a context.

It compares the union of keys at every level, so a section the server adds is
compared as soon as the server sends it. It was added after version
**0.261.157**. Before it, the fixture had drifted from the server in these ways:
- reason texts;
- how an unrecognized status was treated;
- four missing management blocks;
- some capabilities.

Those were corrected, and so were the browser tests that relied on them.

`functional_tests/test_public_context_fixture_parity.py` does the same for the
public workspace context, from version **0.261.168**. Every public browser suite
builds its context with `public_context` in `ui_tests/fixtures/public_workspace.py`.
The test runs the real public context builder and route through the same
harness for:
- every role and status, including an unrecognized status;
- every seeded context;
- the per-suite setters that recompute a context.

Before it, the public fixture had drifted from the server:
- it opened every section to readers and let managers manage them, where the
  server opens only Documents;
- `can_manage_workspace` was given to any manager, where the server gives it
  to the Owner and Admins;
- chat was refused in locked workspaces, where the server allows it;
- editing was allowed in `upload_disabled` and downloading was allowed for
  readers, where the server allows neither;
- the collaboration hint was missing or approximated;
- the unrecognized-status handling, the inactive reason and the not-found text
  differed.

It also pins one server inconsistency as a strict expected failure. The public
builder opens Documents with a section whose `can_manage` is false even for an
active manager, whose `document_management` hint grants every operation. The
group builder doesn't do this. No V2 client reads that flag today; the public
directory work will correct it.

`ui_tests/test_v2_personal_document_scope.py` provides the personal-document
integration baseline added in version **0.261.128**. It checks that an unrelated
active group does not retarget personal reads, search/tag filters, action
availability, or metadata updates.
The **0.261.129** management baseline also covers personal uploads, tagging,
version/sync deletion confirmation, and downloads.
The **0.261.130** collaboration baseline additionally protects personal
share/unshare targeting and failed-share state when a different group is active.

Route-policy tests include the new endpoint. Existing personal bootstrap,
workspace, and browser journeys protect compatibility. These isolated tests do
not claim connectivity to a live Azure tenant or prove all future native
document operations.

The projection loads one group's metadata and policy, not its collections,
statistics, or all membership pages. Native group reads use separate explicit
document adapters. Public UI, group sharing/approval, broader native management,
and additional resource adapters remain separate milestones.
