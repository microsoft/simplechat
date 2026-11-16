# Group Document Count Fix (v0.261.154)

## Issue

Before an owner deletes a group, the classic manage page asks for the group's
document count, and if there are any, tells the owner to remove them first.
The count always came back as 0, so the page never asked. An owner could delete
a group that still had documents, and those documents were left behind with no
group.

Fixed in version: **0.261.154**, tracked in `application/single_app/config.py`.

## Root cause

`GET /api/groups/<group_id>/fileCount` counted documents whose `groupId` named
the group. Group documents store the group as `group_id`, so no document ever
matched.

## Technical details

### The change

The route now answers with `count_current_group_documents(group_id)`, in
`functions_group_document_reads.py`. It counts the group's own documents exactly
as the group document list shows them:
- each document family's current revision, chosen by the same
  `current_group_document_records` the list now uses;
- never a revision marked `is_current_version: false`;
- not documents shared into the group, which belong to the group that shared
  them.

The native `GET /api/groups/<group_id>/insights/file-count` uses the same
function, so the two counts always agree. The route's access is unchanged: the
owner only, and 404 for a missing group.

### Files modified

- `route_backend_groups.py`: `get_group_file_count`.
- `functions_group_document_reads.py`: `current_group_document_records` is
  factored out of `load_group_document_browser_documents`, with no change to
  the list, and `count_current_group_documents` is added.

### Tests

- `functional_tests/test_group_document_count_predicate.py` (9 cases): the
  count against the real document list, over superseded revisions, a legacy
  family without revision fields, a document still processing, a family whose
  only revision isn't current, shared documents and another group's document.
- `functional_tests/test_group_settings_legacy_fixes.py`: the classic route
  answers the group's current documents, only for the owner, and agrees with
  the native count.

## Impact

An owner whose group has documents now sees "This group has N document(s). You
must remove or delete these documents before the group can be deleted." on the
classic manage page, and can delete the group once they're gone.

The server's `DELETE /api/groups/<group_id>` doesn't check the count, and
deleting a group doesn't remove its other records. Both are recorded as a group
lifecycle follow-up.

## Validation

- Before: the count was always 0, and the page let the owner delete a group
  with documents.
- After: the count is the documents the owner sees in the group's document
  list, and the page asks for them to be removed first.

## Related

- [Group Settings APIs](../features/GROUP_SETTINGS_APIS.md)
- [Group Document Read APIs](../features/GROUP_DOCUMENT_READ_APIS.md)
