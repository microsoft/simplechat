# Chat Citation Whitespace Collapse Fix

Fixed in version: **0.250.229**

Related issue: [#1289](https://github.com/microsoft/simplechat/issues/1289)

## Issue Description

Inline document citations in assistant chat messages deleted the whitespace that followed them. The citation link itself rendered correctly, but the text after the citation was jammed onto the end of the closing parenthesis instead of starting a new paragraph, list item, or sentence.

In the reported message the model produced normal, well-formed markdown, but the browser rendered:

- `... used to support cited answers in chat. (Source: application_workflows.md, Page: 1)Admins can configure the extraction approach ...`
- `... warrants it (Source: document-intelligence.md, Page: 1)For best results, upload clear, readable images.`
- `... (Source: uploading_documents.md, Page: 1)Thank you, Paul.`

Because the first citation was inside a numbered list, the paragraph that followed it was also absorbed into list item 5 rather than closing the list.

## Root Cause Analysis

`parseCitations()` in `application/single_app/static/js/chat/chat-citations.js` matched inline citations with:

```js
const citationRegex = /\(Source:\s*(...),\s*(Page(?:s)?|Sheet(?:s)?|Location):\s*(...)\)\s*((?:\[#.*?\]\s*)+)/gi;
```

The trailing `\s*` inside the repeated bracket group `((?:\[#.*?\]\s*)+)` is greedy and matches newlines, so it consumed the whitespace that followed the last `[#citation-id]` marker. The replacement callback returned only the rebuilt `(Source: ...)` string and never re-emitted that whitespace, so the blank line separating the citation from the next block was silently deleted.

`parseCitations()` runs on raw markdown **before** `marked.parse()` in `renderAiMessageContent()` (`chat-messages.js`). Losing a `\n\n` therefore did not merely remove a space — it changed how markdown parsed the remainder of the block, which is why the following paragraph became a continuation of the preceding list item.

Reproduced in isolation against the production regex:

```text
Input : "... in chat. (Source: application_workflows.md, Page: 1) [#181b54f7-..._1]\n\nAdmins can configure ..."
Output: "... in chat. (Source: application_workflows.md, Page: 1)Admins can configure ..."
```

### Secondary instance of the same defect

The cleanup pass that strips leftover `[#guid]` brackets (used when the model emits a non-standard citation format) had the same class of bug in the opposite direction:

```js
const guidBracketRegex = /\s*\[#?[0-9a-f]{8}-...[^\]]*\]/gi;
```

Its leading `\s*` also matched newlines, so a stray bracket that opened a paragraph took the preceding blank line with it (`text.\n\n[#guid] More` became `text. More`).

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-citations.js`
- `application/single_app/config.py`
- `functional_tests/test_chat_citation_whitespace_preservation.py`
- `ui_tests/test_chat_citation_paragraph_spacing.py`

### Code Changes Summary

- `parseCitations()` now captures the trailing whitespace from the matched bracket group and appends it to the rebuilt citation string. Whitespace is restored exactly as the model emitted it, so no spacing is invented and a citation followed immediately by punctuation renders byte-identically to before.
- The leftover `[#guid]` cleanup pass was split into three ordered passes so line structure survives:
  1. A bracket run that occupies a whole line is removed together with its line.
  2. A bracket run that opens a line is removed along with the spacing that follows it, so the paragraph it introduces starts cleanly.
  3. Any remaining inline bracket run consumes only the spaces or tabs in front of it, never newlines.
- Both passes now also handle consecutive bracket runs such as `[#id-a] [#id-b]` as a unit.
- Updated `config.py` to version `0.250.229` for this fix.

The emitted citation HTML is unchanged. These are whitespace-only changes, so there is no change to escaping, sanitization, or the XSS surface.

## Validation

### Test Results

`functional_tests/test_chat_citation_whitespace_preservation.py` executes the real `parseCitations()` in a Node sandbox and then renders the result with the vendored `marked` bundle, so it asserts the user-visible block structure rather than just the regex output.

| Check | Result |
| --- | --- |
| Reported message keeps its paragraph breaks | Pass |
| Inline citation spacing preserved (same-line text, trailing punctuation, back-to-back citations, citation id on the next line) | Pass |
| Stray `[#guid]` cleanup keeps line structure | Pass |
| Source guards for the whitespace restoration mechanism | Pass |

All four checks fail against the pre-fix source and pass after it, so the test is a genuine regression guard.

`ui_tests/test_chat_citation_paragraph_spacing.py` seeds the reported assistant message into the chat page and asserts the rendered DOM: the numbered list item ends at its citation, the following text renders as its own `<p>`, and no sentence collides with a citation's closing parenthesis.

### Before / After

Rendered HTML for the reported message, before:

```html
<ol start="5">
<li><strong>Grounded chat:</strong> ... in chat. (Source: application_workflows.md, Page: <a ...>1</a>)Admins can configure the extraction approach ... The available modes are:</li>
</ol>
```

After:

```html
<ol start="5">
<li><strong>Grounded chat:</strong> ... in chat. (Source: application_workflows.md, Page: <a ...>1</a>)</li>
</ol>
<p>Admins can configure the extraction approach for images and PDFs under <strong>Admin Settings &gt; Search &amp; Extract</strong>. The available modes are:</p>
```

### User Experience Improvements

- Paragraphs, bullets, and numbered lists after a citation render in the structure the model actually produced.
- A citation followed by more text on the same line keeps its separating space.
- Back-to-back citations no longer collide.
- Copied and exported message markdown is built from the same parsed output, so it keeps its line breaks too.

## Cross-References

- Functional test: `functional_tests/test_chat_citation_whitespace_preservation.py`
- UI test: `ui_tests/test_chat_citation_paragraph_spacing.py`
- Related: [Citation Improvements](../features/v0.238.024/CITATION_IMPROVEMENTS.md)
