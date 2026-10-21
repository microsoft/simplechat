# Native V2 Aggregate Public Chat (v0.261.371)

Implemented in version: **0.261.310**, tracked in
`application/single_app/config.py`. Addresses row 3 of
[microsoft/simplechat#1722](https://github.com/microsoft/simplechat/issues/1722).
Scope picker placement fixed in version: **0.261.315**, tracked in the same
`application/single_app/config.py`.
Public-source visibility corrected in version: **0.261.371**.

## Purpose and dependencies

Ask a question across public knowledge collections without leaving React for a
classic page. Requires `enable_public_workspaces` and the existing public
workspace, document and conversation storage. No new setting, index, migration
or browser dependency is introduced.

## Choosing a scope

Open **Documents**, then use **Search in**. In Orchestrate, Documents stays
under **Manual controls** when the administrator allows those controls.
There is no separate scope row above the message editor. The Documents button
shows an active All scope when its toolbar is visible.

| Search in | Retrieval set |
| --- | --- |
| Current context | Mixed personal/group/public context and selected references; all eligible public sources are discoverable. |
| All public workspaces | Public-only retrieval across every existing public workspace whose status permits chat. |

Directory **Chat with all public** opens a fresh V2 conversation with All selected.
V2 has no public visibility switches or saved visibility lists. Existing classic
preferences are unchanged and do not filter V2 sources. Configured public-workspace names appear
in the selector and directory.

All is public-only retrieval. Existing personal/group draft
references and whole-workspace chips must be cleared, or Current context chosen,
before sending. Selecting a whole workspace is a Current context operation;
aggregate mode offers public document and tag references rather than silently
ignoring a narrower workspace choice. Documents
and `#` offer public sources only. Ordinary mixed-context chat, restricted editors
and single-workspace hand-offs keep their existing behavior.

Normal Manual chat uses Documents relevance search or selected document, tag
and workspace references; it does not need an aggregate public scope.
Orchestrate can find relevant documents within the supplied context without
that selector. Explicit document references replace its candidate probe;
tags constrain the probe. All is useful specifically when a
question should retrieve across public collections, not personal or group sources.

## Continuity and refusal states

The aggregate choice survives sending and conversation-ID creation. Turn-specific
chips still clear after sending. Reopening a conversation restores the mode from
its latest saved user turn, including orchestrated questions; a later ordinary
turn clears an older aggregate choice. Unsaved mode changes are not persisted.
New chat resets to Current context.

Workspace sets are resolved afresh on each turn. `active`, `locked` and
`upload_disabled` permit chat; inactive, unknown and deleted workspaces do not.
Old V2 Visible links and saved aggregate metadata normalize to All. Classic
continues applying its existing visibility map/list fallbacks.
Empty or disabled scopes are refused rather than broadened
or answered as a successful grounded search.

Conversation ownership, scope locks, action permissions, publication and content
screening remain enforced. Public retrieval does not change personal conversation
or fact-memory ownership. Direct image generation and saved-result questions
require Current context.
Conflict explanations live inside Documents and blocked sends explain how to
recover without discarding references. Even if public workspaces are disabled,
an existing aggregate selection can be changed back to Current context.
If manual controls are unavailable in Orchestrate, switch to Manual mode to
open Documents, or start a new chat. Turn off direct Image mode or remove a
saved-result context before changing an incompatible scope.

## Contract and implementation

`POST /api/chat`, `POST /api/chat/stream` and orchestration plan requests accept
optional `public_workspace_selection: "all"`. Legacy `visible` is accepted,
but normalizes to `all` for V2. The server derives
the public-only scope and workspace IDs instead of trusting browser IDs.
The orthogonal `public_source_policy: "all_available"` is carried through
admitted V2 execution, worker identity, checkpoints and retry metadata.
Requests without aggregate intent retain mixed-source scope; they do not become
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
public-only candidates, conflicting drafts, continuity and restoration.
It also covers picker-only scope editing, restricted-editor isolation,
streaming restrictions, recovery paths, and desktop/mobile light/dark layouts.
`ui_tests/test_v2_public_directory.py` exercises native directory navigation
at desktop/mobile widths in light/dark themes.

V2 no longer performs bulk curation; classic retains that functionality.
This change does not change global React/classic routing or implement other rows
of #1722.
