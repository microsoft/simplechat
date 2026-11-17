# V2 Conversation Scope Lock

## Overview

The React V2 chat can now lock and unlock a conversation's workspace scope. Until now V2
only *showed* the lock: a padlock beside the title and a chip in the conversation details.
Nothing in V2 could change it, so a conversation that had locked itself to the wrong workspace
had to be abandoned, or reopened in the classic interface just to press **Unlock**.

The lock is a promise about retrieval. The first reply grounded in workspace documents locks the
conversation to the workspaces that produced them, and from then on the Documents picker offers
only those workspaces, so a follow-up question cannot quietly start drawing on a different team's
documents. This change gives V2 the classic modal's other half: reading what the lock covers and
choosing to lift or restore it.

Implemented in version **0.261.445**.

### Dependencies

None added. `PATCH /api/conversations/<conversation_id>/scope_lock` and the
`enforce_workspace_scope_lock` administrator setting already existed and are unchanged; the work
is entirely in `application/v2_ui`. It builds on the lock display from
[V2 Chat Phase 1 Parity Fixes](../fixes/V2_CHAT_PHASE1_PARITY_FIXES.md) and the original
[Enforce Workspace Scope Lock](v0.238.024/ENFORCE_WORKSPACE_SCOPE_LOCK.md).

## How the lock behaves

### Three states, not two

| `scope_locked` | Meaning | V2 control |
|---|---|---|
| absent / `null` | No workspace document has been used yet, so there is nothing to lock or unlock | Not drawn |
| `true` | Locked to the workspaces in `locked_contexts` | Closed padlock in amber; **Unlock scope…** when allowed |
| `false` | Unlocked by choice; `locked_contexts` is kept | Open padlock; **Lock scope…** when allowed |

The server writes `true` after the first grounded reply (`collect_conversation_metadata`, only
from `null`). From then on every reply that uses workspace documents adds its workspaces to
`locked_contexts`, even while the lock is off, so the list is the union of every workspace the
conversation has used.

Unlocking does not forget the workspaces. `locked_contexts` is preserved, and **Lock scope…**
offers that list again, including any workspace used while the conversation was unlocked.

### What locking limits

For a personal conversation the server reads the lock whenever the Documents picker lists
sources (`/api/v2/document-sources`, which V2 sends the conversation id to) and whenever a
message names sources (`admit_document_source_selection`). While the lock is on, only the
workspaces in `locked_contexts` — or, when that is empty, the conversation's recorded
`context` — are offered or accepted.

That is also why locking does not rewrite what you already chose. A source you picked from a
workspace outside the new lock stays in the composer, and sending is refused with "A selected
workspace is no longer available. Review your sources." until you remove it. The lock dialog says
this before you confirm.

The lock binds workspace context, not a frozen copy of its files. Documents can change and
current permissions still apply.

### Who can change it

| Conversation | Can change the lock | Otherwise |
|---|---|---|
| Personal | Its owner | A read-only dialog saying only the owner can change it |
| Shared | Anyone who can post in it (`can_post_messages`) | A read-only dialog saying only people who can post can change it |
| Either, while the administrator enforces the lock | Can **lock** but not unlock | A read-only dialog stating that the administrator enforces the lock |

The server decides; V2 only avoids offering a button that would be refused. `enforce_workspace_scope_lock`
defaults to on, and the route answers an unlock with 403 "Scope unlock is disabled by
administrator" whatever the browser believed. A shared conversation goes through the same
route, using the shared conversation's id; the server checks that the caller is an accepted
participant whose group and conversation state still allow chat.

## Where it appears

Three places open the same dialog, matching where the classic interface exposes it:

| Place | What it shows | Why it is there |
|---|---|---|
| Padlock beside the conversation title | An icon button whose label states the state and the action, such as "Workspace scope is locked. Review or unlock it." Amber when locked | The classic header icon (`header-scope-lock-btn`) |
| **Workspace scope** row in the conversation details | A **Locked** or **Unlocked** chip, the workspace names, and **Unlock scope…**, **Lock scope…** or **View details** | The one place that lists the whole conversation's recorded facts |
| Note at the top of the Documents picker | "This conversation is locked to *names*. Only those workspaces are listed here." with **Manage** or **Details** | The classic lock icon beside **Scope**; it explains why the list is short at the moment it matters |

Selecting the note's button closes the picker first, then opens the dialog.

## The dialog

The dialog reuses the classic modal's wording where it was already good.

| Intent | Title | What it says | Confirm |
|---|---|---|---|
| Unlock | Unlock workspace scope | The scope is locked to prevent accidental cross-contamination; **Currently locked to:** the workspaces; unlocking lets you choose any workspace, and you can lock again later | **Unlock scope** |
| Lock | Lock workspace scope | Keeps the conversation to the workspaces that produced its search results; **Will lock to:** the workspaces; the picker is limited to them and sources already added from other workspaces must be removed before you send | **Lock scope** |
| Read only | Workspace scope is locked / unlocked | The state, the workspaces, and the reason nothing can be changed | **Done** |

What the dialog offers is fixed when it opens. If it followed the live state it would flip from
"Unlock" to "Lock" the moment the optimistic write lands, under the reader's eyes.

A workspace is listed with a personal, group or public icon. Names come from the conversation's
recorded contexts first and from the groups and public workspaces the reader belongs to
otherwise; an id is shown only when no name is known.

**Lock scope…** is not offered when the conversation has recorded no workspace. Locking to
nothing would leave the picker with no workspace at all, so the dialog explains there is nothing
to lock to instead.

### What happens when you confirm

1. The conversation's `scope_locked` changes in the open conversation's metadata at once, so
   the header, the details and the picker answer the press.
2. `PATCH /api/conversations/<id>/scope_lock` is sent with `{ "scope_locked": true | false }`.
3. On success the server's `scope_locked` and `locked_contexts` replace the optimistic values,
   the conversation metadata is read again so every surface agrees with the server, the dialog
   closes and a toast says "Workspace scope locked." or "Workspace scope unlocked."
4. On failure the previous values are restored, the dialog stays open and shows the server's
   reason in an alert, and the button is available again. A 403 from enforcement and a server
   error read the same way.

The rollback only applies while the lock still reads as the optimistic value. If a metadata read
landed in between, it carries the server's own answer, and writing an older snapshot over it
would recreate the disagreement the rollback exists to prevent. The answer is also written only
while the same conversation is open, so changing conversations mid-request does not paint one
conversation's lock onto another. While a change is running the dialog cannot be dismissed, and a
second change is ignored.

## Architecture

Rules live in a pure module and rendering in components that ask a small store for the dialog.

```
lib/scopeLock.ts                 States, who may change them, wording, the request body and the
                                 optimistic change with its guarded rollback
stores/scopeLockStore.ts         The dialog's open and pending state, the effects that write the
                                 chat store and call the server, and useScopeLockView()
components/chat/ScopeLockControl.tsx   The three controls: badge, row and notice
components/chat/ScopeLockDialog.tsx    The dialog and the host that shows it
lib/endpoints.ts                 setConversationScopeLock()
```

### Why the dialog is hosted once

The controls only ask the store to open the dialog; none of them owns it. The Documents picker
closes itself when the reader clicks anywhere outside it, which would take a dialog it hosted
away halfway through a sentence, and two dialogs open at once would answer one press twice. The
host sits beside the padlock in the conversation badges and closes itself when the conversation
changes or the lock state disappears. The conversation details' Escape handler steps aside while
the dialog is open, because the dialog listens on the window.

### Accessibility

The padlock is a real button with `aria-haspopup="dialog"` and a label that states both the
state and the action. The details row's button names the action in full ("Unlock workspace
scope") rather than relying on the visible ellipsis. The picker note is a `note` landmark. The
dialog is a modal with focus trapped inside and returned to the control that opened it, an
alert for a refusal, and a busy confirm button while the request runs.

## API surface

No routes were added or changed.

| Route | Used for |
|---|---|
| `PATCH /api/conversations/<conversation_id>/scope_lock` | Lock or unlock. Body `{ "scope_locked": true \| false }`; real booleans only. Returns `{ success, scope_locked, locked_contexts }` |
| `GET /api/v2/document-sources` | The picker's list, which the server limits to the locked workspaces |

## Configuration

| Setting | Default | Effect |
|---|---|---|
| `enforce_workspace_scope_lock` | `true` | While on, unlocking is refused for everyone and V2 offers only **Lock scope…** or a read-only dialog |

The setting is edited in the administrator settings under **Workspaces**
(`workspace-scope-lock-section`) and reaches the browser inside the sanitized `settings` block of
`/api/v2/bootstrap`. It is not an `enable_*` key, so it is not in `features`. V2 treats only an
explicit `false` as "not enforced", because a missing key means the stored default, which is on.

## Usage

**Unlock a conversation that locked to the wrong workspace.** Select the padlock beside the
title, read which workspaces it names, and choose **Unlock scope**. Open **Documents** and pick
the workspace you meant.

**Lock it again.** The padlock is now open. Select it, check the workspaces under **Will lock
to:**, and choose **Lock scope**. Remove any chosen source from other workspaces before you send.

**Find out why you cannot unlock.** Open the padlock. A read-only dialog says whether your
administrator enforces the lock, you are not the owner, or you cannot post in the shared
conversation.

For the user-facing steps see [Lock workspace scope in chat](../../guides/lock-workspace-scope.md).

## Testing and validation

| Test | Covers |
|---|---|
| `functional_tests/test_v2_scope_lock_edit.py` | The route's method, decorators and strict boolean body match what the client sends; unlock is refused under enforcement and lock never is; shared conversations use the same route and V2's `can_post_messages` gate; the setting reaches the browser with the server's default; every control is wired to one dialog hosted once; nothing unsafe or remote is added |
| `functional_tests/test_v2_scope_lock_logic.ts` | 20 behavioural checks, run through the Python file with esbuild and node: states and gating, the workspace list and its fallbacks, dialog wording, the request body, the optimistic write, the guarded rollback and the error text |
| `ui_tests/test_v2_scope_lock.py` | Unlock and lock in the real components; the immediate optimistic answer; refusal and server-error rollback with the reason shown; enforcement; no control without a lock state; nothing to lock to; a shared conversation for a participant and for someone who cannot post; a conversation owned by someone else; the details row; the picker note; keyboard use with focus returned; a 390 px phone with no horizontal scroll |

The behavioural half is skipped when `application/v2_ui/node_modules` is absent.

### Known limitations

- **A source already chosen outside a new lock is not removed.** Locking narrows what the
  picker lists and the server accepts; it does not edit the composer. The dialog warns, and the
  send is refused with a message naming the problem until the source is removed.
- **A conversation with no recorded workspace cannot be locked.** The lock only has something to
  hold once a grounded reply has recorded a workspace.
- **Who may change the lock is the server's call.** V2 hides the action for a personal
  conversation owned by someone else and for a shared conversation the reader cannot post in, but
  a personal conversation whose owner is not yet known to the browser is left for the server to
  judge, and a refusal then appears in the dialog.
- **The lock is not a security boundary for external actions.** Web, Microsoft 365 and other
  configured actions have their own access and governance rules.
- **Workspace names follow what the conversation recorded.** A workspace renamed since the lock
  was written still appears under the name the conversation recorded.

## See also

- [Enforce Workspace Scope Lock](v0.238.024/ENFORCE_WORKSPACE_SCOPE_LOCK.md)
- [V2 Chat Phase 1 Parity Fixes](../fixes/V2_CHAT_PHASE1_PARITY_FIXES.md)
- [V2 Collaboration UX](V2_COLLABORATION_UX.md)
- [React V2 User Interface](REACT_V2_UI.md)
