# V2 Admin Workflow Settings Parity Fix

**Fixed in version: 0.261.059**

## Issue

The **Workflow** group in the V2 React admin interface was empty. Selecting it in
the category rail showed no card, no controls and no explanation — the group
simply had nothing under it.

All seven workflow settings were unreachable from V2:

| Setting | Key |
| --- | --- |
| Enable Personal Workflows | `allow_user_workflows` |
| Require WorkflowUser App Role | `require_member_of_workflow_user` |
| Enable Group Workflows | `allow_group_workflows` |
| Require Group Assignment to Use Workflow | `require_group_assignment_for_group_workflows` |
| Assigned Groups | `group_workflow_allowed_group_ids` |
| Workflow Agent Action Limit | `workflow_max_auto_invoke_attempts` |
| Workflow Task Limit | `workflow_max_tasks` |

An administrator had to fall back to the classic `/admin/settings` page to enable
workflows at all.

## Root cause

One cause, not seven.

`admin_settings_nav.py` defines the group, its tab and its section
(`workflow` > `workflow` > `workflow-settings-section`), which is why the rail
entry existed. What lives *inside* a section comes from one of two sources:

1. `admin_settings_fields.py`, which declares real controls; or
2. the V2 surface's fallback, which scans the settings document for `enable_*`
   booleans and matches each key to a section by shared word stems.

The schema described the Appearance group and a handful of individual keys. It did
not describe the workflow section. So the fallback was the only source — and
**every workflow setting is named `allow_*`, `require_*`, `workflow_max_*` or
`group_workflow_*`.** Not one of them starts with `enable_`, so the scan returned
nothing.

`AdminSettingsPage.tsx` then skips any section with neither declared fields nor
fallback rows:

```ts
if (!fields.length && !capabilities.length) {
    continue;
}
```

The section was dropped, and with it the entire group.

This is a worse failure mode than the misfiled toggles fixed in
[V2_APPEARANCE_PARITY_FIX.md](V2_APPEARANCE_PARITY_FIX.md). A toggle in the wrong
tab is at least visible somewhere. A group with no `enable_*` keys at all
disappears silently, and nothing in the page hints that anything is missing.

## Fix

### Described the section

`admin_settings_fields.py` gained a `workflow-settings-section` entry declaring
all seven settings, with wording taken from the V1 pane so both interfaces
describe a setting the same way.

Dependent controls are hidden until the capability they belong to is on, matching
how the Appearance group already behaves:

```
allow_user_workflows ─────► require_member_of_workflow_user

allow_group_workflows ────► require_group_assignment_for_group_workflows
                                    └──► group_workflow_allowed_group_ids
```

The two run limits are deliberately **not** gated. They bound personal *and* group
runs, and `depends_on` names a single key, so gating either one on one capability
would hide a live limit from an administrator who only uses the other.

### Added a `group_picker` field type

`group_workflow_allowed_group_ids` stores a list of group ids, which none of the
existing control types can edit. `group_picker` was added to `FIELD_TYPES` and
routed in `_normalize_field_value` to
`normalize_group_workflow_allowed_group_ids` — the same normalizer the
server-rendered form uses, so an assignment saved from V2 is byte-for-byte what V1
would have stored, including which ids it drops.

It is deliberately **not** in `NON_PATCHABLE_TYPES`. Requiring assignment and
choosing the assigned groups is one decision; saving them through separate
requests would lock every group out of group workflows in between.

The field carries a `search_endpoint` rather than hard-coding one, so the File Sync
and file download group pickers can reuse the type.

### Added an admin-scoped group directory endpoint

`GET /api/v2/admin/groups` (`login_required` + `admin_required`, in the existing
`backend_v2_admin` blueprint) returns lightweight directory rows:

- `?search=` matches name, description or id, capped and reporting `truncated` so
  a large directory narrows the search rather than silently hiding groups;
- `?ids=` resolves a saved assignment to names. Ids that no longer exist are
  absent from the response, which is how the UI detects a stale entry.

V1's `/api/groups/discover` was not reused. It answers a different question: it is
member-facing, gated on the `User` role and on `enable_group_workspaces`, returns
every group in one unbounded response, and cannot resolve a specific set of ids.
An administrator managing an assignment may hold neither the `User` role nor
membership in the groups being assigned.

### Built the assignment control

`GroupAssignmentField.tsx` replaces V1's modal, which could only report
"3 groups assigned":

- assigned groups render as removable chips showing the group **name**;
- an id that no longer resolves is marked *Not found* and can still be removed,
  instead of rotting invisibly in the list;
- search is inline and debounced, with Assign/Remove per row;
- a failed lookup falls back to showing raw ids and says so, rather than losing
  the assignment.

Edits flow into the page's draft, so the picker saves with the same save bar and
dirty count as every other field.

### Added a generic `notice` property

V1 renders a warning block under the agent action limit about capacity. Rather
than hard-code that text in React, fields may now carry `notice` and
`notice_level`, rendered as a callout by `FieldShell` and `SwitchControl`. This is
distinct from `help` (what the setting does) and from the server's per-save
`warnings` (a reaction to a submitted value).

### Moved the id normalizers to a leaf module

`admin_settings_fields.py` must delegate to the same normalizer V1 uses, but it
cannot import `functions_settings` — that module builds a Cosmos client at import
time through `config.py`, and the functional-test harness replaces it with a stub.

`GROUP_WORKFLOW_ALLOWED_GROUP_ID_PARSE_DEPTH_LIMIT`,
`_iter_group_workflow_allowed_group_id_candidates`,
`normalize_group_workflow_allowed_group_id` and
`normalize_group_workflow_allowed_group_ids` moved verbatim into
`functions_group_assignment_ids.py`. `functions_settings.py` re-exports all four,
so every existing caller is unaffected.

## Files modified

| File | Change |
| --- | --- |
| `application/single_app/functions_group_assignment_ids.py` | New. The four pure group-id normalizers. |
| `application/single_app/functions_settings.py` | Re-exports them from the leaf module. |
| `application/single_app/admin_settings_fields.py` | Declares the workflow section; adds the `group_picker` type and its normalization. |
| `application/single_app/functions_group.py` | Adds `find_groups_by_ids` and `list_groups_for_admin_directory`. |
| `application/single_app/route_backend_v2.py` | Adds `GET /api/v2/admin/groups`. |
| `application/v2_ui/src/lib/adminFields.ts` | Adds `group_picker`, `notice`, `notice_level`, `search_endpoint`. |
| `application/v2_ui/src/lib/adminGroups.ts` | New. Directory search and id resolution. |
| `application/v2_ui/src/components/admin/GroupAssignmentField.tsx` | New. The assignment control. |
| `application/v2_ui/src/components/admin/fields.tsx` | Adds `FieldNotice`, wired into `FieldShell` and `SwitchControl`. |
| `application/v2_ui/src/pages/AdminSettingsPage.tsx` | Adds the `group_picker` branch. |
| `application/single_app/config.py` | Version bumped to `0.261.059`. |

## Validation

`functional_tests/test_v2_admin_workflow_parity.py` is new and holds the
invariants that would have caught this:

| Check | Guards against |
| --- | --- |
| The section declares at least one field | The original bug: an empty group |
| Every V1 pane field name is claimed by the schema | A setting reachable in only one interface |
| No schema field lacks a V1 counterpart | V2 writing a setting nothing reads |
| Number `min`/`max`/`step` match the V1 markup | V2 saving a value V1 refuses to show |
| The gating chain matches its capability | A control hidden while its feature is live |
| The assignment is a patchable `group_picker` | The list saving apart from its gate |
| Normalization matches V1 for duplicates, non-UUIDs and JSON strings | Storage-shape drift between interfaces |

Also run and passing:

- `test_v2_admin_settings_schema.py` (extended with `group_picker`)
- `test_v2_admin_settings_normalization.py`
- `test_v2_admin_field_renderer_coverage.py`
- `test_v2_admin_capability_placement.py`
- `test_v2_admin_appearance_parity.py`
- `test_v2_bootstrap_branding_and_navigation.py`
- `test_docs_app_surface_coverage.py`, `test_docs_site_quality.py`
- `route_tests/` (all three; the new route needed no policy entry, since the
  `backend_v2_admin` blueprint already carries `login_required` + `admin_required`)
- `npm run build` in `application/v2_ui`

## Before and after

| | Before | After |
| --- | --- | --- |
| Workflow group in V2 | Empty | Seven settings in one card |
| Reaching a workflow setting | Only via the classic admin page | Either interface |
| Assigned groups | "3 groups assigned" | Named chips |
| A deleted assigned group | Invisible | Marked *Not found*, removable |
| Searching for a group | Modal, explicit Search button | Inline, debounced |

## Out of scope

Two workflow-adjacent settings live in other V1 panes and stay where V1 puts them:
`url_access_max_workflow_urls_per_run` (Web Research) and
`require_owner_for_group_agent_management` (Workspace Types).
