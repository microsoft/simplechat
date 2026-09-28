# Group Tag Definitions First Fix

## Issue

A metadata edit or a bulk tag in a group saved the document first and wrote the
new tags' definitions afterwards. If the group's tags changed in between, the
vocabulary write lost, and the request answered 409 "The group's tags or
permissions changed. Refresh and retry." But the document had already been saved
with its new tags, so the refusal wasn't true. In a batch, each document already
saved was also listed as an error.

## Root cause

`update_group_document_metadata` in `functions_group_document_management.py`
called `_ensure_document_tag_definitions` after the document write. Bulk tagging
(`tag_group_documents`) went through the same function for each document, so
every document was written before its tags' definitions were checked.

Fixed in version: **0.261.168**

## Technical details

- **Metadata edits:** once the document is authorized, the tags' definitions
  are written first, then the document. A definition that no document uses yet
  is already a valid state, since creating a tag makes one. So a vocabulary
  conflict leaves the document untouched, and a document write that fails
  afterwards leaves at most an unused definition.
- **Bulk tagging:** one vocabulary write for the batch's tags, after the
  batch's permission check and before any document. A conflict refuses the
  whole batch with 409 "The group's tags or permissions changed. Refresh and
  retry." and `error_code: "vocabulary_conflict"`, and writes no document.
  Removing tags writes no definitions.
- **Behaviour note:** bulk tagging used to write a definition for every tag
  each document ended up with, which gave older tags without one a definition
  in passing. It now defines only the batch's own tags. Such tags keep showing
  with the default colour, as before.
- A metadata edit whose own document write loses its etag check now leaves the
  new tag's unused definition behind. This is the accepted residue, pinned by
  `test_failed_source_cas_never_changes_projections_or_resurrects`.

### The classic routes (unchanged)

The classic `PATCH /api/group_documents/<id>` and
`POST /api/group_documents/bulk-tag` already write definitions first, through
`get_or_create_tag_definition`. That helper is etag-guarded; if the group keeps
changing it logs and skips the definition, and the document is still written, so
the tag shows its default colour. The classic PATCH also writes each field with
its own call before validating the tags, so a request with a new title and
invalid tags saves the title and then answers 400. Both are recorded, not
changed here.

### Files modified

| File | Change |
| --- | --- |
| `application/single_app/functions_group_document_management.py` | Definitions before the document write, in both paths |
| `functional_tests/test_group_document_management.py` | A lost vocabulary write refuses a metadata save and a two-document batch with the coded 409 and no document, chunk or blob write. New tags are defined before the first document write, in both paths |
| `functional_tests/test_group_document_fixture_parity.py` | The refusal parity adds bulk tagging and metadata saves, from the check and from a lost write |
| `ui_tests/fixtures/group_document_management.py` | The refusal can name the document |

## Validation

- Functional: 234 → 237 in the management suite, and parity 99 → 103. Every new
  pin fails on the previous server.
- Mutations: moving either path's definitions back after the document write
  fails the new pins and the parity cases.

## Related

- [Group Tag Vocabulary Conflict Code Fix](GROUP_TAG_VOCABULARY_CONFLICT_CODE_FIX.md)
- [Group Document Management APIs](../features/GROUP_DOCUMENT_MANAGEMENT_APIS.md)
