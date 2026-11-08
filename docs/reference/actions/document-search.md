---
layout: page
title: "Document Search"
description: "Reference for the Document Search SimpleChat action."
section: "Reference"
audience: user
version: "0.261.422"
---

<!-- action-slug: document-search -->

{% include media.html src="reference/actions-document-search-configuration.png" alt="The Document Search configuration pane noting that the action uses internal search and the current user's access, with default scope, result limit, windowing, and summary settings." title="Document Search action configuration" capture="Capture the Document Search action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Searches accessible SimpleChat documents, retrieves chunks, and summarizes documents using current user access.

## Why and when to use it

Use it when an agent should reason over workspace documents as a tool. Use the normal grounded-search panel for one-off user searches.

## Before you start

- Accessible personal, group, or public workspace content; no external credentials.
- Users also need access to the action through workspace or governance policy where applicable.


## Configuration overview

Document Search can be narrowed without granting the agent any access the user does not already have. Choose the allowed scopes:

- **My workspace** for the signed-in user's personal documents.
- **Group workspaces** for groups the signed-in user can access. Choose all accessible groups or restrict the action to selected group IDs.
- **Public workspaces** for public workspaces the signed-in user can access. Choose all accessible public workspaces or restrict the action to selected public workspace IDs.

At runtime, SimpleChat intersects those action settings with the current user's group and public workspace access. A disabled scope is rejected even if the user asks for it explicitly.

Set the default result limit with the slider or number input. The UI slider covers 5–100 results for normal setup, and the number input accepts values up to the existing backend maximum of 500 for specialized actions.

## Summary and windowing controls

The window unit controls how much source material goes into each summarization pass. Use **Automatic** when SimpleChat should choose the amount, **Fixed size** when a predictable number of pages or chunks is needed, or **Percent of document** when long documents should be sampled proportionally. Only the selected sizing value is stored; unused values are cleared to avoid conflicting instructions.

Focus instructions tell the summarizer what to prioritize, such as contract dates, safety incidents, or implementation steps. Window summary and final summary target lengths are stored as page targets from the V2 sliders. Legacy free-text values, such as word counts, are preserved as custom values and can be reset to page-based targets.

The V2 editor no longer offers ad hoc custom fields. Use **Advanced → JSON** only to review preserved legacy values.

## Reading accessibility and formatting metadata

The action includes a `get_document_accessibility_report` function for agents that review documents for accessibility or house style. For one document it returns the stored accessibility metadata (PDF tags, Office structure, comments), the style inventory (fonts, sizes, colours, outlier text, page setup), and the detected issues.

From **0.261.399**, workspace Excel files also expose native workbook properties, cell notes/threaded comments, object alternative text/decorative flags, formatting/layout and header/footer expressions. Modern `.xlsx`/`.xlsm` inspection has explicit saved-state coverage limits; legacy `.xls` is best effort. Use the report for the bounded workbook-wide inventory and document search for sheet/cell-addressed `Excel native inspection` evidence. Enhanced-citation workbooks still index a schema preview plus native evidence, not the complete worksheet data.

- Choose which stored parts to return with `sections` (`accessibility`, `style`, `issues`); all three are returned by default. Opt-in Word `comments` inspection is separate.
- Pass `page_number` to also get that page, slide or Excel indexed evidence segment's stored text. Excel segment numbers are not physical print-page numbers.
- The stored workspace report does not grant access to chat uploads. For an existing workspace Excel file, retained active source bytes can be inspected on demand without re-uploading; unavailable originals need the normal re-upload/reprocessing workflow.
- The issues list is heuristic. It is not a formal WCAG, Section 508, or PDF/UA conformance check. To apply your own rules, write them into the agent's instructions and have it compare them with the returned values.

See [Document accessibility, structure, and comment extraction](https://github.com/microsoft/simplechat/blob/13db876626a043e2c7b30f054354f07c9a1633b9/docs/explanation/features/DOCUMENT_ACCESSIBILITY_AND_STRUCTURE_EXTRACTION.md) for what is extracted for each file type.

### Native Word review comments

Fixed/Implemented in version: **0.261.422**
(`application/single_app/config.py`).

For workspace `.docx`, `.docm`, or `.dotx` files, call
`get_document_accessibility_report(document_id=..., sections="comments")`.
This uses the existing authorized original-file reader and Word parser, returning
`word_inspection` with parsed comments, supported linked replies, inventory counts,
and limitations. Normal accessibility/style/issue calls do not add this original
file read.

This is useful for checking what a reviewer actually wrote, independently of
document prose or a search summary. Anchors are limited to 300 characters;
`anchor_complete` distinguishes a complete parsed range from bounded or
unavailable text. Resolution is known only when `resolution_available` is true.
Relationships come from supported Word metadata, not guesses about author names
or reply wording.

Excel cursors, worksheet/cell filters, and non-comment native sections do not apply
to Word. A comment-only request for an unsupported format, missing original, or
malformed package fails explicitly; it does not certify that there are no comments.
Stored Word style metadata can be absent while original comment inspection is
available. A combined comments/style/accessibility/issue request still requires
the stored sections; a successful comment read does not certify missing style or
issue data as empty. This does not grant native-report access to chat-only uploads.

### Selected sources in Orchestrate

Implemented in version: **0.261.419** (`application/single_app/config.py`).
When an orchestration plan uses this action for selected workspace files, it can
declare their exact IDs as `arguments.document_ids`. Inspect the Run view's source
chips before approval; its existing narrowing controls can remove individual
files from that step.

This declaration is enforced on the server, not just added to a model instruction.
Native metadata, chunk, summary and search reads stay within the bound files and
the action's configured workspace restrictions. Omitting an ID filter on a tool
search does not broaden it to the whole workspace.

No separate Search or Analyze step is required solely to make native inspection
count as selected-source work. Supported native facts and citations travel through
the retained action result to the answer, including explicit inspection limits.
A denied or unavailable report is not a successful inspection; a missing property
inside an available report must still be distinguished from an inaccessible one.
This does not add native-report access for chat-only attachments.

### Loading failures and recovery

From **0.261.421** (`application/single_app/config.py`), shared plugin discovery
reuses the registered Python module instead of creating another copy of the
document reader. This fixes selected-document actions being rejected before their
first read even when the plan and source permissions were valid.

Run details distinguish a tool initialization or reader identity failure from a
failed document read and an action that returned no function results. For a reader
identity failure, ask an administrator to repair/update the application before
retrying; changing the model, increasing timeouts, or re-uploading the same source
does not fix that loading defect.

The source checks and native-inspection limits are unchanged. A missing report or
unavailable native property does not become evidence of absence or compliance.

### Paged Excel inspection

Implemented in version: **0.261.408** (`application/single_app/config.py`).
Use `native_section` to request `comments`, `tables`, `objects`,
`property_records`, `custom_properties`, `extended_properties`, `defined_names`,
`hyperlinks`, `validations`, or available `image_analyses`. The default is
`comments`. `native_page_size` accepts 1–200 records, with a separate response
byte bound. Follow `excel_inspection.page.next_cursor` using `native_cursor`
while `has_more` is true. Explicit long JSON record fragments require their
continuation before the record is complete.

`sheet_name` and `cell_range` read an A1 range of at most 2,000 saved cells,
including formula text/cache availability, without executing formulas.
Compatibility copies of threaded comments are not extra genuine notes.
Native evidence segment citations are not Excel print-page numbers.

See [Inspect Excel workbooks]({{ '/guides/inspect-excel-workbooks/' | relative_url }})
for table headers, saved values, and large-file workflows.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspaces/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
