# V2 Held Document Details Actions Fix

Fixed/Implemented in version: **0.261.159**

## Issue

In the V2 documents explorer, the Details pane for a document held by content
screening offered the ordinary document actions. In My Workspace it showed
**Chat**, **Download**, **Tag**, **Edit**, **Extract**, **Share** and
**Delete** for a held file. Chat and the operation-gated buttons were
disabled, but **Share** was live, so the owner could share a held document
from the pane.

Content screening requires the opposite: a held source can't be selected for
chat, analyzed, shared or downloaded until an authorized reviewer resolves the
hold in Content review. The React V2 branch pins this in
`ui_tests/test_v2_content_screening.py`
(`test_select_all_and_details_do_not_offer_ordinary_actions_for_held_content`),
which failed on this branch.

## Root cause

Content screening made `ActionButtons` in `DocumentDetailsPane.tsx` render only
an explanation for a held document. The group document work then changed that
block twice:

- M2A (native group document browsing) generalized the check into a selection
  reason, which still hid every button when any reason applied.
- M2B (group document management) made the buttons render beside the reason,
  so a group manager could still act on a document that is only blocked from
  chat, such as a shared document awaiting approval.

The M2B change was right for chat-only reasons, but it also applied to held
documents. The buttons then relied on the operation gate alone, and **Share**
has no operation gate: it is shown whenever personal file sharing is enabled.

The browser suites that pin held content in My Workspace weren't in the group
milestones' regression runs, so the change went unnoticed until the React V2
base merge ran them (0.261.158).

## Fix

`ActionButtons` checks for a held document first. For a held selection it
shows the hold explanation and only the cleanup the workspace authorizes for
that document:

- **Delete**, only where the operation gate allows it. For group and public
  documents the server advertises it for owned held documents whose screening
  state allows cleanup: awaiting review, scan error, incomplete, rejected or
  deleting. A personal held document never qualifies, because the personal gate
  requires the document to be available.
- **Sharing and review**, where the group collaboration adapter allows
  inspection. Its share operations already refuse held documents.

Chat, Download, Tag, Edit, Extract and Share are never shown for a held
document. Documents that are only blocked from chat keep M2B's behavior: the
reason is shown and the other permitted actions remain.

The explanation now reads "Held sources cannot be selected for chat, analyzed,
shared, or downloaded here." A group document in a cleanup state can be
selected for deletion, so "selected for chat" is the accurate wording.

## Files modified

| File | Change |
| --- | --- |
| `application/v2_ui/src/components/documents/DocumentDetailsPane.tsx` | Held documents show the explanation and only authorized cleanup. |
| `ui_tests/test_v2_group_document_management.py` | New `test_held_details_offer_only_the_advertised_cleanup`; two held-selection tests no longer expect a disabled **Edit** in the pane. |
| `application/single_app/config.py` | Version `0.261.158` -> `0.261.159`. |

## Validation

- `ui_tests/test_v2_content_screening.py`: the held-content Details test now
  passes. The one remaining failure,
  `test_admin_policy_is_discoverable_and_editable_before_citations_are_enabled`,
  also fails on the React V2 branch tip and is unrelated.
- `ui_tests/test_v2_group_document_management.py`: 34 passed, including the
  new test, which fails without the fix. It checks an owned held document keeps
  only **Delete**, and an incoming held share offers no action.
- Unchanged: group documents 29, group document collaboration 33, public
  documents 54, personal document scope 11, group workspace shell 21, content
  screening policy parity 45, and the source pins in
  `functional_tests/test_v2_documents_explorer.py` (20) and
  `test_public_document_payload_redaction.py` (48).

## Known limitation

The personal share route, `POST /api/documents/<document_id>/share`, doesn't
itself refuse a held document. Downloads and metadata extraction are refused
by the server for held content, so hiding the button closes the V2 path, but
the route is unchanged. This matches the React V2 branch and is recorded as a
follow-up.
