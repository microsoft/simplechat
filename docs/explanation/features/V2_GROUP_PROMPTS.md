# V2 Group Prompts

## Overview

Implemented in version: **0.261.136**, tracked in
`application/single_app/config.py`.

Group prompts can now be read, written, and used from the native V2 group
workspace, in the same workbench as personal prompts. Previously the group
Prompts section sent users to the classic interface.

The endpoint reference is [Group Prompt APIs](GROUP_PROMPT_APIS.md).

## Who can do what

| | Owner, Admin, DocumentManager | Ordinary member |
|---|---|---|
| Read and preview | yes | yes |
| Use in chat | yes | yes |
| Reword in the chat composer for one message | yes | yes |
| Create, edit, duplicate, delete | yes, in an `active` group | no |

Ordinary members get a read-only workbench. Groups that are `upload_disabled`
or `locked` are read-only for everyone.

Rewording a prompt in chat changes only that message. Nothing is saved to the
group's prompt.

## One workbench, not two

Personal and group prompts share one workbench. Group behaviour lives in a
separate adapter, `lib/promptWorkbench.ts`, used only by the workbench.

The existing personal prompt functions in `lib/workspaceApi.ts` are
**unchanged**, and the adapter's personal path simply calls them, so the personal
prompt URLs are still defined in exactly one place. That also protects chat:
the chat composer's "Save as prompt" and the message "Save as prompt" call those
unchanged functions, so they always create a **personal** prompt and cannot be
redirected to a group.

## Gating

The workbench offers an action only when the server allows it:

- **Create** needs the workspace's `prompt_management` block to offer `create`.
- **Edit, duplicate, delete** additionally need the prompt's own
  `prompt_actions` to list the action.

There is no fallback. A missing or empty hint hides the action rather than
enabling it, so a missing server hint can never become an unchecked action. The
server checks every request regardless.

## Favorites

Group prompts have no favorite control and no favorite sorting. A favorite is
stored on the prompt itself, so in a group it would be shared by every member.
Personal favorites are unchanged.

## Conflicting edits

Each save sends the version of the prompt the editor opened. If another manager
changed it in the meantime, the save is refused, and the editor stays open with
the draft intact and an option to refresh. Nothing typed is lost.

From version **0.261.152**, refreshing merges the other manager's changes into
the fields you didn't touch and keeps your edits. A field you both changed is
named, with your value shown. Saving then writes the merge, not your stale
draft. See the [conflict rebase fix](../fixes/GROUP_EDITOR_CONFLICT_REBASE_FIX.md).

## Use in chat

"Use in chat" on a group prompt opens a link that names the prompt **and** its
group, for example `/chat?prompt=<id>&prompt_scope=group&prompt_scope_id=<group>`.
The composer attaches the prompt only if it is in the chat's prompt list with
that exact group. If it has been deleted, or the user no longer has access, the
composer says so and names the group.

Links that name only a prompt, `/chat?prompt=<id>`, keep working exactly as
before. Personal prompts still produce that form, so links already shared are
unaffected.

## Testing and validation

`ui_tests/test_v2_group_prompts.py` covers the group surface with 20 cases:
manager create, edit, duplicate, and delete; read-only for ordinary members and
for locked groups; a prompt with empty `prompt_actions` beside one with actions,
proving the gate works prompt by prompt; hidden favorites; draft retention on a
conflict; refreshing after a conflict, which merges an untouched field, names a
field both managers changed, and reports a deleted prompt without saving it
again; group and legacy chat links; a stale group link naming the group; and
layout in light and dark at 1440x900 and 390x844.

`functional_tests/test_v2_group_prompts_seam.py` pins the adapter's structure:
no personal prompt URL of its own, personal calls delegated to
`workspaceApi.ts`, encoded group URLs, and chat saves staying personal.

`functional_tests/test_group_prompt_fixture_parity.py` holds the page's
fixture, `ui_tests/fixtures/group_prompts.py`, to the real scoped prompt
routes. For each response it checks that the fixture returns only keys the
server returns, including inside each prompt, that every field the page reads
is present on both sides, and that statuses and error codes match. The routes
covered are list, create, update, delete, both conflicts, an unknown prompt and
the non-member refusal. When it was added, after version **0.261.157**, it
found two places where the fixture had drifted, and both are corrected in the
fixture:

- a delete returned `{"success": true}`, where the route returns a message;
- a conflict put `prompt_changed` in `error` and sent no `error_code`, where the
  route sends a sentence in `error` and the code in `error_code`.

The page was unaffected by either: it treats any 409 as a conflict and ignores
the delete response.

The personal prompt suites pass unchanged, as do the group and public document
browser suites.

**Running the browser suites.** Run
`ui_tests/test_v2_prompt_composer_experience.py` in its own `pytest`
invocation. It starts its own browser, which Playwright refuses while another
suite's shared browser is running, so batching it with the other V2 suites makes
every one of its cases error at setup even though it passes alone. This
predates this release.

## Related

- [Group Prompt APIs](GROUP_PROMPT_APIS.md)
- [V2 Prompts Workbench](V2_PROMPTS_WORKBENCH.md) — the personal workbench
