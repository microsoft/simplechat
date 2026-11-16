# React V2 Clipboard Paste and Drop Upload Fix

Version: **0.261.368**

Fixed/Implemented in version: **0.261.368**
(`application/single_app/config.py`).

## Issue

Pasting text into the React V2 message box worked, but pasting a screenshot or a file did
not attach it in normal chat. Dropping a file on the message box had the same limitation.
The file picker already worked.

## Root cause

The shared `ComposerEditor` paste, drop, and drag-over handlers were conditional on
`referenceUploadsOnly`. The main composer enables that flag specifically for direct Image
mode with an image model that supports references. Normal chat therefore returned before
the existing upload queue could receive any pasted or dropped files.

Classic chat had its own clipboard handling, so its existing clipboard tests did not catch
this React V2 gap.

## Technical details

### Transfer extraction

`application/v2_ui/src/lib/chatUploads.ts` now supplies the typed `chatTransferFiles`
helper. It reads file-kind transfer items first and falls back to the file list when no
usable item files are available. The two representations are not concatenated, avoiding
duplicate uploads of the same transfer.

Named files keep their names. Nameless files receive a generated name using a recognized
MIME extension, preserving their bytes, MIME type, and modification time. Unknown MIME
types remain unsupported rather than being guessed into an accepted format.

Text clipboard payloads accompanied only by unnamed auxiliary images remain ordinary text
pastes. Named files accompanied by a filename or path remain file uploads.

### Shared upload routing

`application/v2_ui/src/components/chat/ComposerEditor.tsx` now gates file transfers on
the existing upload eligibility instead of requiring Image reference mode. Pasted and
dropped files use `enqueueSelectedFiles`, the same queue as the file picker.

This preserves:

- Upload capability, disabled/restricted editor, supported-format, and file-size checks.
- Single-file inline-answer limits and Image-mode reference validation.
- Upload chips, local image previews, processing status, retry, removal, and cancellation.
- Sequential requests so a new-chat batch reuses the first upload's conversation identity.
- Native text paste, selection replacement, and text-only drops.

The change adds no backend endpoint, settings key, runtime dependency, global clipboard
listener, clipboard permission request, or visual redesign.

### Files and coverage

| File | Change |
| --- | --- |
| `application/v2_ui/src/lib/chatUploads.ts` | Transfer extraction and safe filename normalization |
| `application/v2_ui/src/components/chat/ComposerEditor.tsx` | Eligible paste/drop routing and drag-over acceptance |
| `functional_tests/test_v2_chat_context_request.ts` | Runtime transfer extraction, fallback, ordering, naming, text, and validation regressions |
| `ui_tests/test_v2_chat_clipboard_uploads.py` | Real-component browser clipboard, file/text drop, permission, limit, retry, and navigation coverage |
| `ui_tests/test_v2_image_reference_generation.py` | Shared harness response for the message list's pending-credential read |
| `docs/guides/upload-documents-in-chat.md` | V2 paste/drop workflow and browser limitations |
| `docs/reference/chat-controls.md` | Existing attachment controls and gestures |
| `application/single_app/config.py` | Application version incremented from `0.261.367` to `0.261.368` |

## Usage and impact

Focus **Message** and paste a screenshot or browser-exposed supported file, or drop a local
file onto the message box. Wait for the attachment to become **Ready**, then send your
question. **Image** can remain off for normal chat.

When the source application or browser exposes only a copied path, link, or HTML rather
than a file, use **Attach a file**. This fix does not promise arbitrary operating-system
file clipboard support beyond the files delivered by the browser.

Upload permissions, processing, workspace destinations, and retention remain unchanged.
Restricted assist inputs do not gain uploads. Removing an attachment does not delete an
already uploaded copy.

## Validation

The regression was reproduced before the fix using an actual PNG browser clipboard paste
with Image mode off: the **Attached files** list never appeared. After the fix, the same
workflow produces one upload, a ready attachment, and an image preview.

The 20-case clipboard browser suite also covers actual text insertion at a selection before
and after an image, a native text drag-and-drop, item/file fallback representations, new-chat
batches, upload eligibility, unsupported/oversized files, reference-only formats, failed-upload
retry/removal, and cancellation when changing conversations.

Focused helper/upload request checks and classic clipboard regressions pass:

```powershell
python -m pytest .\functional_tests\test_v2_chat_context_picker.py::test_the_typescript_logic_checks_pass .\functional_tests\test_chat_clipboard_paste_upload_support.py -q
```

Browser regression command:

```powershell
python -m pytest .\ui_tests\test_v2_chat_clipboard_uploads.py .\ui_tests\test_v2_chat_image_uploads.py .\ui_tests\test_v2_image_reference_generation.py -q
```

The combined browser command passed all **39** cases. The focused functional command
passed all **5** checks, including the executed TypeScript helper suite. The production V2
build, documentation coverage and site-quality checks, whitespace check, and UI detector
also passed.

The full `test_v2_chat_context_picker.py` wrapper has an unrelated pre-existing source-string
assertion expecting `setDraft(createComposerDraft())`. The unchanged main composer now creates
`emptyDraft`, calls `setDraft(emptyDraft)`, and returns that draft. Its executed TypeScript
transfer/upload contract checks pass; this fix does not change that unrelated draft-reset code.
