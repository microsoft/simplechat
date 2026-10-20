# Inline Citation Filename Fallback Fix

Fixed in version: **0.261.355**

Application version: `application/single_app/config.py`.

## Issue and root cause

An answer could correctly cite a document but display **Untitled Document** as
its inline source label. Both chat clients used the label in the generated answer
without consulting the filename already recorded in that message's
`hybrid_citations`. The source popup could therefore show the correct filename
while the inline reference did not.

React's ordinary streaming completion also omitted `hybrid_citations` from the
final local message. Rendering changes alone would fix loaded history but leave
newly streamed answers without the metadata needed for the fallback.

A successful metadata-extraction status does not guarantee a meaningful inferred
title. This fix does not change extraction, document titles, or saved answer text.

## Resolution

For document citations only, both clients now recognize an exact **Untitled
Document** or **Untitled** label, ignoring case and surrounding whitespace. They
replace that display label with a nonblank filename from the same message's
exact matching citation ID.

Meaningful titles remain unchanged, including titles that merely contain those
words and actual filenames such as `Untitled Document.docx`. Missing, malformed,
or conflicting filename records retain the existing label rather than guessing.
One message cannot borrow a filename from another message or the document picker.

When a marker names references to different files, each reference keeps its own
filename, citation ID, and location. Filenames are rendered as inert text; a
filename resembling a URL does not become a web citation.

### Before and after

Given this answer marker:

```text
(Source: Untitled Document, Page: 1) [#document-id_1]
```

and a matching message record with `file_name: public-guide.md`, the visible
reference now names **public-guide.md**, and clicking it still requests
`document-id_1`. The stored marker remains unchanged.

### Affected implementation

| Files | Responsibility |
|---|---|
| `application/v2_ui/src/lib/citations.ts` | Exact-ID filename lookup and React placeholder-label resolution |
| `application/v2_ui/src/components/chat/AssistantMarkdown.tsx`, `MessageList.tsx` | Pass message-scoped records into rendering after masking |
| `application/v2_ui/src/stores/chatStore.ts`, `src/lib/types.ts` | Retain typed document citations when the stream completes |
| `application/v2_ui/src/lib/messageText.ts` | Use the same names in optional copied source lists |
| `application/single_app/static/js/chat/chat-citations.js` | Classic placeholder-label resolution and escaped source links |
| `application/single_app/static/js/chat/chat-messages.js` | Forward each saved or finalized message's citation records |

## Impact and limitations

The fallback requires no setting, additional network request, or metadata
reprocessing. It works for personal, group, and public document records through
the common message renderer. Previously saved messages benefit when their stored
citation records include the matching filename; no migration is performed.

Token-only provisional output may retain the placeholder until final citation
metadata arrives. References without a usable exact match keep their existing
label. Web, agent, and Microsoft 365 citations retain their existing behavior.
Authorization, passage lookup IDs, document metadata, and mask offsets are not
changed.

## Testing and validation

`functional_tests/test_inline_citation_filename_fallback.py` executes both
production parsers against the same inputs. Coverage includes exact-ID isolation,
placeholder variants, useful titles, multiple documents and locations, duplicate
and conflicting records, missing metadata, inert filenames, whitespace, and
optional source-list copying.

`ui_tests/test_inline_citation_filename_fallback.py` exercises real React
components and classic modules with synthetic HTTP data. It covers saved history,
page reload, final streaming metadata, desktop and mobile widths, keyboard
activation, inert markup, and click-through with the original citation and
document IDs. Rendering a fallback does not request citation metadata.

The existing citation, paragraph-spacing, copy, masking, enhanced-viewer, and
Microsoft 365 regressions remain applicable. Browser tests use the repository's
local/Azure Playwright connection fixture and do not mutate a live conversation.

Validation results:

| Command | Result |
|---|---|
| `python -m pytest -q functional_tests\test_inline_citation_filename_fallback.py functional_tests\test_v2_citations.py functional_tests\test_chat_citation_whitespace_preservation.py functional_tests\test_v2_message_copy.py functional_tests\test_v2_message_masking.py functional_tests\test_v2_enhanced_citations.py --tb=short --disable-warnings` | 70 passed; 35 existing return-value warnings |
| `python -m pytest -q ui_tests\test_inline_citation_filename_fallback.py ui_tests\test_v2_m365_source_citations.py --tb=short` | 21 passed using local Chromium |
| `npm --prefix application\v2_ui run typecheck` | Passed |
| `npm --prefix application\v2_ui run build` | Passed; existing large-bundle warning |
| `node --check application\single_app\static\js\chat\chat-citations.js` | Passed |
| `node --check application\single_app\static\js\chat\chat-messages.js` | Passed |
| `python functional_tests\test_docs_site_quality.py` | 6 checks passed |
| `python functional_tests\test_docs_app_surface_coverage.py` | 7 checks passed; inventory unchanged and current |

The frontend detector reported two existing bounce-animation findings and two
false positives on `<img>` mentions in comments. None is introduced by this
change; unrelated UI styling was left alone.
