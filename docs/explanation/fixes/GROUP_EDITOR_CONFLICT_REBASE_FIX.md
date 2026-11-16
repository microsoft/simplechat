# Group Editor Conflict Rebase Fix (v0.261.152)

## Issue

The group prompt, identity, endpoint and file source editors detect a conflicting
save properly. Each save carries a revision or etag, and when someone else has
changed the item meanwhile, the save is refused and the editor keeps your draft.

But the reload that followed only fetched the new revision. Your draft still held
every field as it was before the conflict. So saving again re-sent all of them,
including fields you never touched, and silently undid the other person's
changes to those fields. That is exactly the lost update the revision exists to
prevent, and you had no way to see it, because the draft didn't show the other
person's changes.

Fixed in version: **0.261.152**, tracked in `application/single_app/config.py`.

## Root cause

Each editor kept one copy of the item: the draft. The reload replaced the list
row, and with it the write token, but not the draft. Nothing remembered the item
as the editor first loaded it, so the editor couldn't tell which fields you had
changed and which the other person had.

## Technical details

### The shared helper

`application/v2_ui/src/lib/rebaseDraft.ts` exports one pure function:

```ts
rebaseDraft(baseline, fresh, draft, fields) => { draft, conflicts }
```

- `baseline` is the item as the editor loaded it, `fresh` is the reloaded item,
  and `draft` is your current copy.
- For each field in the editor's list:
  - a field you didn't touch (the draft equals the baseline) takes the fresh
    value, so the other person's change is kept and shown;
  - a field you changed keeps your value;
  - when you and the other person both changed it, to different values, it's a
    **conflict**. Your value is kept and the field is reported by its label.
- **Secrets are never compared or copied into a notice.** A secret you typed is
  kept. A blank secret input takes the reloaded stored state, meaning whether a
  secret is stored.
- Fields not in the list are left as the draft holds them.

### Each editor's reload

1. Fetch the fresh item.
2. Rebase the draft onto it.
3. Make the fresh item the new baseline and token.
4. Show a notice:
   - with no conflicts: "Someone else changed this while you were editing.
     Their changes are loaded; your edits are kept. Review, then save.";
   - with conflicts, it adds the fields by label, never their values: "You and
     someone else both changed: Name, Description. Your values are shown."
5. If the item was deleted: "This item was deleted. Copy anything you need, then
   close." The draft stays open, and nothing is saved.

| Editor | Where | Fields |
|---|---|---|
| Group prompts | `PromptWorkbench.tsx`, `PromptEditorDialog.tsx` | Name, description, content |
| Group identities | `GroupIdentitiesSection.tsx`, `identityFields.ts` | Name, description, uses, and each credential field, with the secret marked |
| Group endpoints | `ModelConnectionsManager.tsx`, `modelConnections.ts` | Name, provider, API type and enabled. The connection, management, identity header and models are compared as whole blocks. Each authentication field is listed separately, with the three secrets marked |
| Group file sources | `GroupFileSourcesSection.tsx`, `fileSourceFields.ts` | Every draft field: name, type, connection fields, filters, schedule, credential source, identity, and credentials, with the secret marked |

File sources rebase only after a `config_conflict`. A `write_conflict` means
nothing your draft depends on changed, so it stays a plain retry. The admin
connection editor never conflicts, and its behaviour is unchanged.

## Testing

- `functional_tests/test_v2_rebase_draft_logic.mjs` (16 checks):
  - untouched, edited, edited alike, and edited differently;
  - secrets, typed and blank;
  - the stored-secret flag;
  - fields outside the list;
  - no mutation of the inputs;
  - each notice.
- The four editor suites each gain three browser cases:
  - someone else changes field A while you edit field B: after the conflict
    and reload, the saved body carries their A and your B;
  - both of you change the same field: the notice names it, and your value is
    saved;
  - the item was deleted: the notice appears and nothing is saved.

  They are `ui_tests/test_v2_group_prompts.py`, `test_v2_group_identities.py`,
  `test_v2_group_endpoints.py` and `test_v2_group_file_sources.py`.
- The fixture shape parity tests for endpoints and file sources pass unchanged.

## Validation

- Before: saving after a conflict reload could undo the other person's changes
  to fields you never touched.
- After: their changes are kept, your edits win where you made them, and a field
  you both changed is named so you can check it.

## Related

- [V2 Group Endpoints](../features/V2_GROUP_ENDPOINTS.md)
- [V2 Group File Sources](../features/V2_GROUP_FILE_SOURCES.md)
- [V2 Group Identities](../features/V2_GROUP_IDENTITIES.md)
- [V2 Group Prompts](../features/V2_GROUP_PROMPTS.md)
