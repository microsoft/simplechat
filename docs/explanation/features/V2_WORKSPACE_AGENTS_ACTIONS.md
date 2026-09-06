# V2 Workspace Agent and Action Authoring

## Overview

My Workspace provides native V2 authoring for personal agents and actions. Agents
combine a consistent role, model, approved tools, and knowledge; actions describe
the individual tools an agent is allowed to use. Keeping their configuration
connected makes it possible to build an assistant without switching interfaces.

Implemented in version: **0.261.096**, recorded in
`application/single_app/config.py`.

The change is limited to personal workspace management. Group/global management,
the standalone agent catalogue, and the delegation execution rules are unchanged.

### Dependencies

| Dependency | Purpose |
| --- | --- |
| React 18 and TypeScript | Native editor components and typed configuration |
| React Router | Deep editor routes and unsaved-navigation protection |
| Existing Flask agent/action APIs | Authorization, schema validation, and persistence |
| Existing plugin schemas and discovery | Governed action types and configuration |
| Existing Vite/Tailwind pipeline | V2 styling and locally served runtime assets |

## Information architecture

Agents and Actions remain siblings under My Workspace's Automation group. Both
collections offer search and explicit create, edit, and delete operations.
Provided resources are distinguished from owned resources and cannot be edited
through personal management.

Call agent is an ordinary action type. It appears in the same collection and
agent action picker as other tools. Choosing that type reveals its target-agent
configuration; it does not create a separate navigation destination, list, or
binding workflow.

### Editor routes

| Route | Purpose |
| --- | --- |
| `/v2/workspace/agents` | Agent collection |
| `/v2/workspace/agents/new` | Create an agent |
| `/v2/workspace/agents/<id>` | Edit an agent or view permitted provided details |
| `/v2/workspace/actions` | Unified action collection |
| `/v2/workspace/actions/new` | Choose a type and create an action |
| `/v2/workspace/actions/<id>` | Edit an action or view permitted provided details |

Each editor uses a full page with section navigation, persistent save controls,
and one content scroll area. Sections are directly accessible instead of being
mandatory wizard steps. Advanced configuration stays available without occupying
the primary workflow.

## Agent configuration

The editor supports Local, Azure AI Foundry, New Foundry, and Foundry Workflow
agents according to the existing personal-agent and governance policies.

Local agents can configure identity, model connection, instructions, assigned
knowledge, and approved actions. Capability overrides narrow the operations an
individual agent can use. Foundry-managed agent types expose the relevant
provider configuration instead of suggesting that local actions or instructions
will change a remote agent.

Assigned knowledge retains the existing source, tag, document, and active-document
semantics. User-added context permissions and assigned URL review modes remain
subject to server policy. Instruction drafting uses the selected action and
knowledge context, including the existing `#action:` and `#knowledge:` grammar.

Examples and approved templates are starting points for a draft, not permission
grants. Applying a template does not run an action or copy another agent's
credentials.

## Action configuration

The action type catalogue comes from the governed personal plugin discovery
endpoint. A shared editor and type-specific configuration components cover the
existing connector families, authentication modes, reusable identities, and
supported discovery/connection-test commands.

OpenAPI specifications and MCP discovery use the existing server APIs. Database,
analytics, storage, search, application, and utility actions retain their
type-specific configuration. Advanced metadata/additional fields remain available
for supported custom configuration.

OpenAPI import remains upload/content-based. Download a remotely hosted
specification before importing it; the V2 editor does not restore the
[deliberately removed URL import endpoints](../fixes/v0.241.001/OPENAPI_URL_IMPORT_REMOVAL_FIX.md).

For Call agent, configuration is a stable target reference containing its ID and
scope. Authentication uses the current user's permissions and the endpoint is
internal. There is no credential or connection-test step. Saving the action
does not invoke its target.

## Connected editing

An agent's action picker can open the normal New action page. The unfinished
agent is retained in tab memory. Saving the action returns it to the agent draft
as a selection; the agent is still unsaved until its own Save command.

Ordinary navigation away from a dirty editor asks whether to discard the changes.
Cancelled or failed saves leave the draft available. Drafts and credentials are
not written to browser local/session storage and do not survive closing the tab.
Reloading a dirty editor therefore requires confirmation rather than promising
recovery that is not available.

Unload protection also covers an agent draft suspended while creating an action
and an action waiting to be attached on return. Save/return navigation markers
are scoped to the originating editor; an older history entry cannot bypass a
later editor's discard or saving guard.

Use in chat opens a new personal V2 conversation with the authorized saved agent.
It refreshes the permitted catalogue first; a failed refresh or revoked target is
reported instead of using an old cached selection.
It does not change the agent on an existing conversation. The selected agent
supplies its own model; the launch does not send a competing model override.

## API and persistence boundaries

The native authoring client uses an opt-in `view=editor` representation of the
existing personal resource APIs. Classic callers retain their existing contract.
Editor details separate the persisted record from revision, read-only, and
configured-secret metadata.

Updates are per-record and carry changed fields instead of replacing the whole
collection. Nested values, unresolved references, and unedited credentials are
preserved. Explicit removal and secret-clear intent are distinct from leaving a
field unchanged. Redaction markers are never credentials to be saved.

Settings-derived editor options are narrowed and sanitized. Resource secret
values are masked whether Key Vault storage is enabled or not. Scoped server-side
authorization and validation remain authoritative even when the browser already
hid a control.

Conditional writes reject stale editor revisions rather than silently replacing
another editor's configuration. The UI retains the unsaved draft when reporting
a conflict.

A lost write response can be retried by the storage SDK and then reported as a
conflict even though the first attempt committed. Once a write has started,
fresh credential references are retained conservatively rather than deleting a
secret that a committed record may use. Classic agent cleanup reads the actual
stored references, so it also works with credentials staged by the V2 editor.

## File structure

| Path | Responsibility |
| --- | --- |
| `application/v2_ui/src/pages/workspace/AgentsSection.tsx` | Personal agent collection |
| `application/v2_ui/src/pages/workspace/ActionsSection.tsx` | Unified action collection |
| `application/v2_ui/src/pages/workspace/AgentEditorPage.tsx` | Agent authoring page |
| `application/v2_ui/src/pages/workspace/ActionEditorPage.tsx` | Action authoring page |
| `application/v2_ui/src/components/workspace/WorkspaceEditorFrame.tsx` | Sections, save state, and navigation confirmation |
| `application/v2_ui/src/lib/workspaceAuthoring.ts` | Typed records and changed-field serialization |
| `application/v2_ui/src/lib/workspaceAuthoringApi.ts` | Editor API boundary |
| `application/v2_ui/src/lib/workspaceEditorDrafts.ts` | Tab-memory draft handoff |
| `application/v2_ui/src/lib/workspaceAgentLaunch.ts` | Scoped new-chat launch resolution |
| `application/single_app/route_backend_agents.py` | Agent authoring route integration |
| `application/single_app/route_backend_plugins.py` | Action authoring route integration |
| `application/single_app/functions_workspace_authoring.py` | Safe editor projections, scoped updates, and conditional persistence |
| `application/single_app/functions_personal_agents.py` | Classic reads and cleanup of actual stored credential references |

## Testing and validation

`functional_tests/test_v2_workspace_authoring_logic.mjs` executes the real
changed-field serializer, secret intent, reference preservation, scoped agent
launch, and URL-consumption helpers. Existing workspace, conversation-link,
model/agent exclusivity, schema, knowledge, and delegation tests protect the
shared behavior.

`functional_tests/test_workspace_authoring_credential_compatibility.py` covers
the installed Cosmos SDK's response-loss retry policy and V2-to-classic
credential edit/delete compatibility. `ui_tests/test_v2_workspace_draft_navigation.py`
covers historical save markers and unload protection across editor handoffs.

Python Playwright coverage under `ui_tests/` exercises the real routed V2 editor
with synthetic API fixtures and production CSS. It covers ordinary and Call agent
workflows, draft handoff, navigation, visible failures, and responsive behavior
without invoking live models or connectors. The existing Azure Playwright
connection fixture supports a configured remote workspace or a local browser.

Connector availability and successful connection tests still depend on deployment
policy and the configured remote service. Tests of the editor do not imply that
a particular deployment's connector credentials are valid.

## Related

- [My Workspace in V2](V2_MY_WORKSPACE.md)
- [Workspace agent and action guide](../../guides/workspace-agents-and-actions.md)
- [Call another agent](../../guides/call-another-agent.md)
