# V2 Public-only Chat Compatibility (v0.261.395)

Implemented in version: **0.261.310**, tracked in
`application/single_app/config.py`. Addresses row 3 of
[microsoft/simplechat#1722](https://github.com/microsoft/simplechat/issues/1722).
Scope picker placement fixed in version: **0.261.315**, tracked in the same
`application/single_app/config.py`.
Public-source visibility corrected in version: **0.261.373**.
Workspace sidebar implemented in version: **0.261.395**, tracked in
`application/single_app/config.py`.

## Purpose and dependencies

Ask a question across public knowledge collections without leaving React for a
classic page. Requires `enable_public_workspaces` and the existing public
workspace, document and conversation storage. No new setting, index, migration
or browser dependency is introduced.

## Choosing a scope

Open **Documents → Choose sources** and select individual public workspaces.
They appear alongside personal/group workspaces in the synchronized workspace
sidebar. There is no **Current context** or aggregate-public dropdown.
In Orchestrate, Documents remains under **Manual controls** when available.

Directory **Chat with all public** and saved public-only conversations resolve
the current eligible public workspace set into selected workspace chips.
These chips can be removed or combined with other sources. **Search all
documents** is a separate choice: it includes accessible personal and group
workspaces as well as public collections, rather than being public-only.

V2 does not use classic public-directory visibility preferences to hide eligible
sources. Classic curation remains unchanged. See
[Chat Context Picker](CHAT_CONTEXT_PICKER.md) for search, selection and mobile use.

## Continuity and refusal states

New chats start with document search off. Turn-specific selected chips clear
after sending; reopening a conversation restores canonical source intent from
its latest user turn. A migrated public-only selection is an explicit set, so
new workspaces are not automatically added to it. A failure to resolve the
public-only launch is visible with retry/review actions and blocks sending until
the sources have been reviewed.

`active`, `locked` and
`upload_disabled` permit chat; inactive, unknown and deleted workspaces do not.
Old V2 Visible links normalize to the eligible public set. Classic continues
applying its existing visibility map/list fallbacks.
Empty or disabled scopes are refused rather than broadened
or answered as a successful grounded search.

Conversation ownership, scope locks, action permissions, publication and content
screening remain enforced. Public retrieval does not change personal conversation
or fact-memory ownership. Restricted, shared and image-reference editors retain
their established picker behavior.

## Contract and implementation

New main-composer requests use the canonical contract documented in
[Chat Context Picker](CHAT_CONTEXT_PICKER.md), including scoped public workspace
entries. Metadata discovery uses `GET /api/v2/document-sources`.

For historical callers and retry/edit, `POST /api/chat`, `POST /api/chat/stream`
and orchestration plan requests still accept
optional `public_workspace_selection: "all"`. Legacy `visible` is accepted,
but normalizes to `all` for V2. The server derives
the public-only scope and workspace IDs instead of trusting browser IDs.
The orthogonal `public_source_policy: "all_available"` is carried through
admitted V2 execution, worker identity, checkpoints and retry metadata.
Historical aggregate retries remain dynamic public-only searches. They are not
silently changed into all-accessible searches. Requests without aggregate intent retain mixed-source scope; they do not become
public-only merely because public discovery ignores classic curation.

`public_chat_scope.py` binds admitted IDs to request/worker context and
revalidates availability without widening an admitted turn. The resolver in
`functions_public_workspaces.py`, shared search services and source readers
resolve eligible public sources without bypassing access checks.
Orchestration carries the selection in seeds and checkpoints and rebinds it
for execution and source reads, checking the conversation's live ownership and
scope lock. Delegated-agent request bridges carry the admitted retrieval limits
without inheriting personal/group workspace preferences.
Retry/edit preserve it in `workspace_search`
metadata.

Picker document/tag GETs accept the same optional mode; see
[Public Document Read APIs](PUBLIC_DOCUMENT_READ_APIS.md).
React request builders share `documentScope.ts`; `publicChatScope.ts` types the
selection and latest-turn restoration. `ChatPage.tsx` consumes the scope-only
launch once, including under StrictMode.

## Testing and limitations

`functional_tests/test_v2_public_chat_scope.py` covers authoritative resolution,
fallbacks, malformed modes, ownership, locks, dynamic availability, empty scopes,
worker/delegated-request isolation, replay, picker publication policy and
public-only request building.
`ui_tests/test_v2_public_chat_scope.py` exercises both request dispatches,
public-only migration, synchronized filtering, retained choices,
restricted-editor isolation, streaming restrictions, and desktop/mobile
light/dark layouts.
`ui_tests/test_v2_public_directory.py` exercises native directory navigation
at desktop/mobile widths in light/dark themes.

V2 no longer performs bulk curation; classic retains that functionality.
This change does not change global React/classic routing or implement other rows
of #1722.
