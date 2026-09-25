# Group Tag Vocabulary Conflict Code Fix

## Issue

When a group's tag vocabulary changed while someone was creating, recolouring
or renaming a tag, the answer depended on timing:
- if the other change landed before the request checked the group, the server
  answered 409 "The group's tags or permissions changed. Refresh and retry.";
- if it landed between that check and the write, Cosmos refused the
  conditional write (412). The generic handler then answered 409 "The resource
  changed. Refresh and retry the operation." with no `error_code`.

So the same conflict had two sentences, and a client couldn't tell a vocabulary
conflict from any other.

## Root cause

`_patch_tag_definitions` in `functions_group_document_management.py` checks the
group's etag, then writes the definitions with a conditional patch
(`filter_predicate` on `_etag`). Only the check had its own answer. A lost
patch raised the SDK's 412, which reached the generic `{409, 412}` branch of
`group_operation_error`.

Fixed in version: **0.261.167**

## Technical details

- New constants `GROUP_TAG_VOCABULARY_CONFLICT_MESSAGE` (the check's sentence)
  and `GROUP_TAG_VOCABULARY_CONFLICT_CODE` (`vocabulary_conflict`), and one error
  built from them: a 409 whose details carry the code.
- The check raises it. A 412 from the conditional patch raises it too, chained
  from the SDK error. Any other failure is re-raised unchanged.
- The generic 409/412 branch is unchanged, since other operations use it.
- The public workspace module has the same fall-through. It's recorded for the
  public writer-safety slice and not changed here.

### Answers, before and after

| Path | Before | After |
| --- | --- | --- |
| Create, recolour or rename; the write lost | 409, "The resource changed. Refresh and retry the operation.", no code | 409, "The group's tags or permissions changed. Refresh and retry.", `error_code: vocabulary_conflict` |
| Create, recolour or rename; the check caught it | 409, the vocabulary sentence, no code | The same sentence, with the code |
| Rename or delete, the final vocabulary stage (207) | `error: vocabulary_conflict`, with "The resource changed…" as the message | `error: vocabulary_conflict`, with the vocabulary sentence |
| Bulk tag, per document | The generic sentence | The vocabulary sentence and code |

The V2 client needed no change: it already shows the sentence and keeps the
draft.

### Files modified

| File | Change |
| --- | --- |
| `application/single_app/functions_group_document_management.py` | The constants, the one error, and the 412 catch around the conditional patch |
| `functional_tests/test_group_document_management.py` | 8 new tests: either path raises the coded conflict and writes nothing, a lost create, recolour or rename writes neither the group nor a document, a lost cleanup keeps its reference, and bulk tag names the conflict per document. The fake groups container raises the SDK's real 412 class |
| `functional_tests/test_group_document_fixture_parity.py` | The conflict answer checked from both paths, and `test_tag_vocabulary_refusal_parity` across create, recolour and rename |
| `ui_tests/fixtures/group_document_management.py` | `tag_vocabulary_refusal()`, the server's answer |
| `ui_tests/test_v2_group_document_management.py` | A create conflict shows the sentence, never the code, and keeps the draft |

## Validation

- Functional: 226 → 234. Fixture parity: 91 → 99. Every new test fails on the
  previous server.
- Mutations: without the 412 catch, 7 of the 8 new functional tests and all 5
  lost-patch parity cases fail. The survivor is the check path, which that
  mutation doesn't touch. Without the `error_code`, 6 of 6 and 6 of 6 fail.

### Known limitation (fixed in 0.261.168)

In this version, a metadata edit or bulk tag still saved the document before it
ensured the new tags' definitions. So a lost vocabulary write could answer this
409 after the document was already saved; a retry succeeded. From version
**0.261.168**, the definitions are written first; see
[Group Tag Definitions First Fix](GROUP_TAG_DEFINITIONS_FIRST_FIX.md).

## Related

- [Group Document Management APIs](../features/GROUP_DOCUMENT_MANAGEMENT_APIS.md)
- [V2 Group Document Management](../features/V2_GROUP_DOCUMENT_MANAGEMENT.md)
