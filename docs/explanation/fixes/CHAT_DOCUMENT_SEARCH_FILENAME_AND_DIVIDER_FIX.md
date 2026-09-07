# Chat Document Search File Name and Divider Artifact Fix

**Fixed in version: 0.250.210**

**Related issue:** [#1256](https://github.com/microsoft/simplechat/issues/1256)

## Issue Description

Two defects affected the chat page grounded-search document picker (`#search-documents-container`).

1. **File names could not be searched.** The document picker matched only on the document's
   display name, which is `title || file_name`. As soon as a document had an extracted `title`,
   its `file_name` became completely unsearchable. A user who only remembered a fragment of the
   file name — for example `200` inside `Quarterly_Report_200_final.pdf` — received
   "No Matching Documents".

2. **Filtering left orphaned separator lines behind.** When a search filtered out the leading
   workspace sections, the section separator lines belonging to those sections survived, usually
   as two stacked horizontal rules directly under the "Select All" / "Clear All" row. This
   affected the Document, Scope, and Tags dropdowns.

A third, related usability gap was addressed at the same time: matching was a single raw
substring test, so multi-word queries and separator-heavy file names did not match natural
typing (`report 200` versus `Quarterly_Report_200_final.pdf`).

## Root Cause Analysis

### File name matching

`buildDocumentDescriptor()` in `chat-documents.js` built the searchable text from the display
name and the section label only:

```javascript
searchLabel: `${getDocumentDisplayName(documentItem)} ${sectionLabel}`.trim(),
```

Because `getDocumentDisplayName()` returns `title || file_name`, the file name never reached the
matcher for any document that had a title.

### Separator artifacts

`updateDropdownStructure()` in `chat-searchable-select.js` decided divider visibility by scanning
outward for the nearest visible sibling:

```javascript
let previousVisible = null;
let previous = child.previousElementSibling;
while (previous) {
    if (!previous.classList.contains('no-matches') && isVisibleItem(previous)) {
        previousVisible = previous;
        break;
    }
    previous = previous.previousElementSibling;
}
```

`isVisibleItem()` reported dividers as "not visible", so the scan walked straight through other
dividers, and the always-visible `data-search-role="action"` row ("Select All" / "Clear All")
counted as valid content. Every orphaned divider therefore found the same action row above it and
the first surviving section header below it, so all of them stayed visible.

Reproduced against the pre-fix logic:

```
DOC: filter "beta"        TAGS: filter "confidential"
  - Select All              - Clear All
  ------------------        ------------------
  ------------------        ------------------   <- leftover artifacts
  # [Public] Beta           # Classifications
  - Beta Handbook           - Confidential
```

### Matching strictness

Both selector code paths used a raw substring test (`searchText.includes(searchTerm)` and
`optionSearchText.includes(searchTerm)`), which cannot match a query whose words are separated
differently from the source text.

## Technical Details

### Files Modified

| File | Change |
|------|--------|
| `application/single_app/static/js/chat/chat-searchable-select.js` | Added `normalizeSearchText()` and `matchesSearchTokens()`; rewrote divider visibility with section-aware rules |
| `application/single_app/static/js/chat/chat-documents.js` | Added `getDocumentFileName()`; extended the document descriptor; render a muted file-name line; read the title span for the button label |
| `application/single_app/static/js/chat/chat-onload.js` | Read the title span when restoring a deep-linked document selection |
| `application/single_app/static/css/chats.css` | Added `.chat-document-option-text` / `-title` / `-filename` rules |
| `application/single_app/config.py` | Version bumped to `0.250.210` |

### Token matching

Search text and the typed query are normalized identically: lowercased, with `_`, `-`, and `.`
treated as word breaks and whitespace collapsed. A row matches when **every** token in the query
appears somewhere in the normalized text.

```javascript
export function normalizeSearchText(value) {
    return String(value ?? '')
        .toLowerCase()
        .replace(SEARCH_SEPARATOR_PATTERN, ' ')
        .replace(SEARCH_WHITESPACE_PATTERN, ' ')
        .trim();
}

export function matchesSearchTokens(searchText, searchTerm) {
    const normalizedTerm = normalizeSearchText(searchTerm);

    if (!normalizedTerm) {
        return true;
    }

    const normalizedText = normalizeSearchText(searchText);
    return normalizedTerm.split(' ').every(token => normalizedText.includes(token));
}
```

Matching remains position-independent, so `200` still matches mid-file-name. The helper is shared,
so the scope, tags, document, prompt, model, and agent selectors all behave the same way.

### Searchable document text

```javascript
searchLabel: [displayName, fileName, sectionLabel].filter(Boolean).join(' '),
```

The file name is also surfaced visually as muted secondary text, but only when it differs from
the title, so documents without extracted metadata do not render the same string twice. Both
lines are written with `textContent` and appear in the row tooltip.

### Divider rules

Each `.dropdown-divider` in the items container is now classified:

- **Bound divider** — the next non-divider sibling is a `.dropdown-header`, so the divider
  introduces a section. Visible only when that header is visible **and** visible *section content*
  exists before it.
- **Unbound divider** — anything else, such as the static divider under "All" / "Clear All".
  Visible only when a visible non-divider element exists before it **and** visible *section
  content* exists after it.
- *Section content* is a visible `.dropdown-header`, or a visible `.dropdown-item` whose
  `data-search-role` is not `action`. Always-visible action rows never qualify, so an orphaned
  divider can no longer anchor itself to the "Select All" row.
- A final pass (`collapseRedundantDividers`) hides any leading, trailing, or adjacent visible
  divider, guaranteeing separator lines can never stack regardless of future markup.

## Before and After

| Scenario | Before | After |
|----------|--------|-------|
| Search `200` where the title is `Fiscal Overview` and the file is `Quarterly_Report_200_final.pdf` | `No Matching Documents` | The document is listed under its workspace section |
| Search `report 200` | No match | The document is listed |
| Search matching only the last workspace section | Two stacked separator lines under the action row | No separator lines |
| Tags search matching only a classification | Two stacked separator lines | One separator line above `Classifications` |
| Document row with a distinct file name | Title only | Title with the file name as a smaller muted line |

Filtered dropdown output after the fix:

```
DOC: filter "beta"        TAGS: filter "confidential"
  - Select All              - Clear All
  # [Public] Beta           ------------------
  - Beta Handbook           # Classifications
                            - Confidential
```

## Testing

### Functional test

`functional_tests/test_chat_document_search_filename_matching.py` — 8 checks covering the
descriptor wiring, safe row rendering, button-label decoupling, token matching, section-aware
divider rules, stylesheet rules, and the version bump. The divider and matching checks are
executable rather than static: the test loads the production `chat-searchable-select.js` into a
minimal DOM shim through Node and asserts the exact filtered output for the document, scope, and
tags dropdowns, including that no leading, trailing, or adjacent separator lines survive. The
executable section is skipped with a warning when Node.js is unavailable.

```
📊 Results: 8/8 tests passed
```

### UI test

`ui_tests/test_chat_document_search_filename_and_dividers.py` — 4 Playwright regression tests
that mount the real `chat-documents.js` and `chat-searchable-select.js` modules with production
CSS, stub `fetch` with personal, group, and public documents, and drive `loadAllDocs()`:

- the muted file-name line renders only when it differs from the title, stacks under the title,
  uses a smaller font, and appears in the tooltip;
- searching matches file-name fragments, multi-word queries, literal file names, and titles;
- filtering produces no orphaned separator lines and clearing the search restores the structure;
- the mobile drawer filters correctly without horizontal overflow.

```
4 passed
```

All four fail against the pre-fix source (the file-name search returns
`No Matching Documents`), confirming genuine regression coverage.

### Regression suite

`test_chat_search_panel_document_row_layout.py`, `test_chat_document_dropdown_viewport_fit.py`,
`test_chat_scope_selector_sync.py`, and `test_chat_document_action_selector_labels.py` all pass
(12 passed, 5 skipped — the skips require `SIMPLECHAT_UI_BASE_URL`).

## Impact Analysis

- Users can now locate documents by any fragment of the title **or** the file name, matching the
  behavior the backend already provides for the workspace document list.
- The Compare modal document picker inherits both fixes because `chat-messages.js` relocates the
  same `#document-dropdown` field into `#document-comparison-picker-controls`.
- The shared token matcher also improves the prompt, model, and agent selectors.
- No backend change was required — `/api/documents`, `/api/group_documents`, and
  `/api/public_workspace_documents` already return `file_name`.
- No new browser assets were introduced; all changes are in existing local static JS and CSS, so
  the local-only asset policy and CSP are unaffected.

### Known trade-off

Normalizing `.` as a word break means a query such as `a.b` matches text containing `a` and `b`
separately. This is acceptable for a filename-oriented picker and is what makes `report 200`
match `Quarterly_Report_200_final.pdf`.
