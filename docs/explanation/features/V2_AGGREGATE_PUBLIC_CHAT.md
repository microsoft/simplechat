# Native V2 Aggregate Public Chat (v0.261.310)

Implemented in version: **0.261.310**, tracked in
`application/single_app/config.py`. Addresses row 3 of
[microsoft/simplechat#1722](https://github.com/microsoft/simplechat/issues/1722).

## Purpose and dependencies

Ask a question across public knowledge collections without leaving React for a
classic page. Requires `enable_public_workspaces` and the existing public
workspace, document and conversation storage. No new setting, index, migration
or browser dependency is introduced.

## Choosing a scope

| Document search scope | Retrieval set |
| --- | --- |
| Current context | Existing personal/group/public active context and selected references. |
| All public workspaces | Every existing public workspace whose status permits chat, including hidden workspaces. |
| Visible public workspaces | Chat-available public workspaces selected by your directory curation. |

Directory **Chat with visible** flushes pending visibility saves and opens a
fresh V2 conversation with Visible selected. A failed save leaves the directory
open with an explanation. Neither aggregate mode writes visibility, saved lists
or the active workspace preference. Configured public-workspace names appear
in the selector and directory.

Both aggregate modes are public-only retrieval. Existing personal/group draft
references and whole-workspace chips must be cleared, or Current context chosen,
before sending. Selecting a whole workspace is a Current context operation;
aggregate modes offer public document and tag references rather than silently
ignoring a narrower workspace choice. Documents
and `#` offer public sources only. Ordinary mixed-context chat, restricted editors
and single-workspace hand-offs keep their existing behavior.

## Continuity and refusal states

The aggregate choice survives sending and conversation-ID creation. Turn-specific
chips still clear after sending. Reopening a conversation restores the mode from
its latest saved user turn, including orchestrated questions; a later ordinary
turn clears an older aggregate choice. Unsaved mode changes are not persisted.
New chat resets to Current context.

Workspace sets are resolved afresh on each turn. `active`, `locked` and
`upload_disabled` permit chat; inactive, unknown and deleted workspaces do not.
Visible uses the existing nonempty visibility map, then the legacy visible-ID
list, then default-all visibility. All-hidden preferences produce no eligible
Visible workspace. Empty or disabled scopes are refused rather than broadened
or answered as a successful grounded search.

Conversation ownership, scope locks, action permissions, publication and content
screening remain enforced. Public retrieval does not change personal conversation
or fact-memory ownership. Direct image generation and saved-result questions
require Current context.

## Contract and implementation

`POST /api/chat`, `POST /api/chat/stream` and orchestration plan requests accept
optional `public_workspace_selection: "all" | "visible"`. The server derives
the public-only scope and workspace IDs instead of trusting browser IDs.
Requests without aggregate intent retain their previous scope contract.

`public_chat_scope.py` binds admitted IDs to request/worker context and
revalidates availability without widening an admitted turn. The resolver in
`functions_public_workspaces.py`, shared search services and source readers
retain hidden sources in All mode without bypassing access checks.
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
`ui_tests/test_v2_public_directory.py` exercises native directory navigation
at desktop/mobile widths in light/dark themes.

The directory's existing bulk-curation limit remains unchanged. This feature
does not change global React/classic routing or implement other rows of #1722.
