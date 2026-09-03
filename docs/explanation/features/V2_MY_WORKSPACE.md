# My Workspace in the V2 Interface

## Overview

The personal workspace in the V2 React interface. It replaces a page that listed documents
and nothing else, and it reorganises the eight capabilities the classic workspace exposes
as a flat strip of tabs.

The reorganisation is the point of the feature. The classic workspace presents Documents,
Prompts, Identities, Sync, Endpoints, Actions, Agents and Workflows as eight siblings, each
shown or hidden by a different combination of settings, app roles and governance policy. A
user sees somewhere between two and eight tabs with nothing to say why, and nothing anywhere
to say that agents use actions, that workflows use agents, or that identities exist only to
serve file sources and actions.

**Implemented in version:** 0.261.039

### Dependencies

| Dependency | Purpose |
|---|---|
| React 18 + TypeScript | Application framework |
| React Router | Section routing under `/workspace` |
| `/api/v2/bootstrap` | Reports which sections the user may see |
| `functions_workspace_sections.py` | Computes section availability for both interfaces |

## Information architecture

Sections are grouped by what they are for, rather than listed as peers.

| Group | Meaning | Sections |
|---|---|---|
| Knowledge | What your assistant can draw on | Documents, File sources, Prompts |
| Automation | What your assistant can do | Agents, Actions, Workflows |
| Connections | Shared setup the other sections reuse | Identities, Endpoints |

Two sections are renamed for clarity. **Sync** becomes **File sources**, because a user
opening it is trying to point the workspace at files they already have rather than to
configure a synchronisation mechanism. **Identities** keeps its name but is described as
saved sign-ins for other systems, since the word otherwise reads as the user's own account.

### The overview page

`/workspace` opens on an overview rather than on a section. It lists every group with its
sections, a count of what is in each, and one line on what each is for. Below that it states
the relationships explicitly:

- Identities are used by file sources and actions.
- File sources feed documents.
- Documents, actions and endpoints are used by agents.
- Agents are used by workflows.

Sections an administrator has not enabled appear here, greyed out, with the reason they are
unavailable. They do not appear in the navigation rail. This is deliberate: hiding a
capability entirely is indistinguishable from it being broken or from the user failing to
find it, and the overview is the only place with room to explain.

### Relationship to the Agents page

The **Agents** entry in the main navigation rail is a catalogue: every agent the user may
select, wherever it came from. **My Workspace → Agents** is where a user builds and manages
their own. Both are kept, and each says which it is on hover.

## Section availability

Availability is computed server-side by `functions_workspace_sections.py` and returned in
the `workspace` block of `/api/v2/bootstrap`. The classic workspace route reads the same
helper, so the two interfaces cannot disagree about what a user may see.

| Section | Requires |
|---|---|
| Documents | `enable_user_workspace` (gates the page itself) |
| Prompts | Always available |
| File sources | `is_file_sync_enabled_for_user(...)` — settings plus app roles |
| Identities | File sync available, or `enable_semantic_kernel` |
| Agents | `per_user_semantic_kernel`, `enable_semantic_kernel`, `allow_user_agents`, and governance `governance_user_agents` |
| Actions | Everything Agents requires, plus `allow_user_plugins` and governance `governance_user_actions` |
| Workflows | `is_user_workflows_enabled_for_user(...)` — settings plus app roles |
| Endpoints | `allow_user_custom_endpoints`, `enable_multi_model_endpoints`, and governance `governance_user_endpoints` |

The `features` map in the bootstrap payload cannot carry these. It forwards only `enable_*`
booleans, which excludes `per_user_semantic_kernel`, `allow_user_agents`,
`allow_user_plugins` and `allow_user_custom_endpoints`, and the file sync and governance
checks are not settings keys at all. The `workspace` block exists for exactly that reason.

A section the server does not report is treated as unavailable. Failing the other way would
render a section whose every request is refused.

## API changes

Personal agents, actions and model endpoints previously had no per-item write path: saving
or removing one meant POSTing the entire collection. That is lossy in two ways that never
surface as an error — a client that omits a row deletes it, and a client holding a stale
copy silently reverts another tab's edit.

Each now supports full per-item REST.

| Collection | Added |
|---|---|
| Agents | `GET`, `PATCH`, `DELETE` on `/api/user/agents/<agent_id>` |
| Actions | `GET`, `PATCH` on `/api/user/plugins/<action_id>` |
| Model endpoints | `GET`, `PATCH`, `DELETE` on `/api/user/model-endpoints/<endpoint_id>` |

`POST` to each collection now creates a single record when the body is an object. An array
body — or, for endpoints, a body carrying an `endpoints` list — still performs the original
whole-collection replace. That form is **deprecated** and retained only because the classic
interface saves that way. The V2 client never uses it.

Per-item routes resolve by id first and fall back to name. Ids are what the V2 client sends:
`GET /api/user/plugins` can merge personal and global actions, which explicitly permits
duplicate names, and a name is editable in any case.

`PATCH` on a model endpoint merges onto the stored record server-side. The copies the
browser holds have their secrets stripped, so sending one back wholesale would blank the
stored credentials.

## File structure

```
application/single_app/
    functions_workspace_sections.py     Section availability, shared by both interfaces

application/v2_ui/src/
    lib/workspaceApi.ts                 Typed client for all eight sections
    lib/workspaceSections.ts            Grouping and gating, free of React
    components/workspace/
        primitives.tsx                  Rows, pills, search, confirm actions
        useSectionResource.ts           Load, refresh and error state
    pages/workspace/
        WorkspacePage.tsx               Shell: header, grouped rail, active section
        sections.tsx                    Section registry
        OverviewSection.tsx
        DocumentsSection.tsx
        FileSourcesSection.tsx
        PromptsSection.tsx
        AgentsSection.tsx
        ActionsSection.tsx
        WorkflowsSection.tsx
        IdentitiesSection.tsx
        EndpointsSection.tsx
```

## Using it

Open **My Workspace** in the left rail. The overview lists what is available; selecting a
group heading's entry opens that section. Sections are real paths — `/workspace/agents`,
`/workspace/prompts` — so a link to one can be shared or bookmarked.

What each section supports in this release:

| Section | Available now |
|---|---|
| Documents | Upload, search, filter by tag, delete |
| File sources | List, sync now, run history, delete |
| Prompts | Full create, edit and delete |
| Agents | List, create, edit name, description and instructions, delete |
| Actions | List, delete |
| Workflows | List, run, cancel, run history, delete |
| Identities | List, delete |
| Endpoints | List, enable or disable, delete |

## Known limitations

Authoring surfaces that are specific to a connector or a schedule are not rebuilt yet and
remain in the classic workspace. Each section links to it rather than offering a control
that does nothing.

- Action configuration, which differs across more than twenty connector types.
- The workflow designer: tasks, document actions and scheduling.
- Model endpoint connection details: provider, API versions, authentication, model list.
- File source configuration, and identity creation with its auth-type-specific fields.
- Agent model binding, action attachment and assigned knowledge.

## Testing and validation

| Test | Covers |
|---|---|
| `functional_tests/test_v2_workspace_sections.py` | Collection key contracts, per-item route registration, bootstrap workspace block, gating parity between the two interfaces, section registry completeness |
| `functional_tests/test_v2_workspace_sections_logic.mjs` | Section resolution, rail versus overview visibility, grouping order, default selection |
| `functional_tests/test_personal_resource_per_item_rest.py` | Per-item routes, bulk compatibility, secret cleanup, route decorators |
| `functional_tests/route_tests/` | Route policy classification for the new routes |

Related fix documentation: `docs/explanation/fixes/PERSONAL_AGENT_DELETE_FIX.md`.
