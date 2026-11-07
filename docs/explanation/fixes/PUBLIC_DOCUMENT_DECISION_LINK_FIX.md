# Public Document Decision Link Fix (v0.261.148)

## Issue

When a public workspace manager approved or rejected a generated file that a
member had asked to publish, the member's notification linked to
`/v2/public-workspaces/<workspace_id>/documents?document_id=<document_id>`.
The V2 app has no page at that path. Its router sent the member to the V2 home
page instead of the document.

Fixed in version: **0.261.148**, tracked in `application/single_app/config.py`.

## Root cause

The V2 public workspace pages are `/v2/public/<workspace_id>/<section>`. The
decision link used the API's path segment, `public-workspaces`, instead of the
page's segment, `public`. Flask serves every `/v2/...` path with the V2 app, so
the link never returned an error. The V2 router matched it against no route and
fell through to its catch-all, which redirects home. The existing test asserted
the wrong path, and the link check added in 0.261.146 only checked Flask's route
map, which accepts every `/v2/...` path.

The group workspace equivalent, `/v2/groups/<group_id>/documents?document_id=`,
was already correct.

## Technical details

### Files modified

- `application/single_app/functions_public_document_publication.py`: the
  decision link is now `/v2/public/<workspace_id>/documents?document_id=<document_id>`,
  with both IDs URL-encoded as before. The public documents view already opens
  the document named by `document_id`.
- `functional_tests/test_public_document_publication.py`: the approve and
  reject decisions now expect the corrected link.
- `functional_tests/test_public_workspace_notification_links_fix.py`: two new
  cases.
  - Every `/v2/...` link literal in the backend must match a route in the V2
    router, read from `application/v2_ui/src/App.tsx`, other than the catch-all
    that redirects home.
  - The public decision link must open the public documents view, with the
    workspace ID, the `documents` section and the document ID.

### Testing

- Before the fix, both new link cases and the approve and reject decision cases
  fail.
- After the fix:
  - `test_public_workspace_notification_links_fix.py` passes 6, in normal and
    optimized Python;
  - `test_public_document_publication.py` passes 63;
  - `test_public_document_publication_predicate_single_source.py` passes 6.
- The broken-access-control scanner passes on the changed module.

## Impact

New approval and rejection notifications open the document in its public
workspace. **Notifications sent before this fix keep the old link,** because each
notification stores its own link. Opening one still goes to the home page; open
the workspace from **Public Workspaces** instead.

The link opens the workspace's documents and names the requested document. For
a rejected request the generated copy has already been removed, so the document
can't be opened; **Return to document list** goes back to the workspace. A
cancelled request sends no notification.

## Validation

- Before: the decision notification opened the V2 home page.
- After: it opens `/v2/public/<workspace_id>/documents` with the document
  selected. Any backend link to a V2 path that the router doesn't serve now fails
  the link test.

## Related

- [Workspace Notification Links Fix](WORKSPACE_NOTIFICATION_LINKS_FIX.md)
