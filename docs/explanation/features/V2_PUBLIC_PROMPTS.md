# V2 Public Prompts

## Overview

Implemented in version: **0.261.177**, tracked in
`application/single_app/config.py`.

Public workspace prompts can now be read, written and used from the native V2
public workspace page, in the same workbench as personal and group prompts.
Before this, the public workspace page had no Prompts section, and public
prompts were managed on the classic page.

The endpoint reference is [Public Prompt APIs](PUBLIC_PROMPT_APIS.md).

## Who can do what

| | Owner, Admin, DocumentManager | Any other signed-in user |
|---|---|---|
| Read and preview | yes | yes |
| Use in chat | yes | yes |
| Create, edit, duplicate, delete | yes, in an `active` workspace | no |

Readers get a read-only workbench. `upload_disabled` and `locked` workspaces
are read-only for everyone, and an `inactive` one has no Prompts section.

## One workbench

The public scope is a third branch of the same adapter, `lib/promptWorkbench.ts`,
that serves personal and group prompts. The personal and group paths are
unchanged. Chat's "Save as prompt" still creates a personal prompt, never a
public one.

The controls follow the server's hints, never a client role check:
- `prompt_management` in the public workspace context decides whether **New
  prompt** is offered;
- each prompt's own `prompt_actions` decides whether it can be edited or
  deleted.

## Conflicting edits

Saves and deletes send the prompt's `etag`. If another manager changed the
prompt meanwhile, the save is refused (409 `prompt_changed`), the editor and its
draft stay open, and a reload merges the other person's changes into the fields
you didn't touch, as group prompts do.

## Use in chat

"Use in chat" opens chat with the prompt, named by its id and its workspace.
- When the workspace is visible for chat, the composer takes the prompt from
  its chat catalog, with no extra request.
- When you've hidden the workspace from chat, the composer fetches that one
  prompt from the workspace's own route and attaches it. It changes nothing: no
  visibility setting is written and the catalog isn't refreshed. A response
  that doesn't name the requested workspace is refused.
- A prompt that no longer exists shows "That prompt is no longer available."
  and attaches nothing.
- Links without a workspace, the older `?prompt=<id>` form, work as before.

## Testing and validation

- `ui_tests/test_v2_public_prompts.py` (20):
  - the workbench: read, filter, create, edit, delete, a conflict with its
    merge, the read-only reader, and the inline `prompt_actions` gate;
  - layouts in light and dark at 1440 and 390 pixels;
  - the four chat links: from the catalog, the older form, a workspace hidden
    from chat, and a missing prompt.
- `functional_tests/test_public_prompt_fixture_parity.py` holds the browser
  fixture to the real routes.
- The group prompts (20), prompt composer (56) and personal document scope (12)
  suites pass unchanged.

## Related

- [Public Prompt APIs](PUBLIC_PROMPT_APIS.md)
- [V2 Group Prompts](V2_GROUP_PROMPTS.md)
- [V2 Prompts Workbench](V2_PROMPTS_WORKBENCH.md)
