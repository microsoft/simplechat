# V2 Document Search Scope Placement Fix (v0.261.315)

## Issue and root cause

The aggregate public-search feature added for row 3 of
[microsoft/simplechat#1722](https://github.com/microsoft/simplechat/issues/1722)
rendered a permanent **Document search scope** row above the message editor.
Its generic label made a specialized public-only choice look necessary for
ordinary chat, and separated retrieval choices from the existing Documents picker.

Normal Manual chat already supports relevance search and selected document,
tag and workspace references. Orchestrate can discover relevant documents within
its supplied scope. Neither needs a separate aggregate selector to search those
sources. All and Visible public scopes remain useful for public-only retrieval
across collections, including hidden eligible collections in All mode.

## Fixed in version: **0.261.315**

The application version is recorded in `application/single_app/config.py`.
This is a V2 interface change, not a search algorithm, authorization, API or
persistence change. No migration or new dependency is required.

## Behavior and technical details

The standalone row is removed. Open **Documents -> Search in** to choose
Current context, All public workspaces or Visible public workspaces. In
Orchestrate, Documents remains under **Manual controls**, subject to the
administrator's existing policy. Closing or hiding those controls does not
change the retrieval scope.

The Documents button indicates an active aggregate choice even with no document
chips. Scope descriptions and conflict messages appear inside the picker.
Blocked sends explain recovery and open the picker when permitted. Incompatible
references are retained; disabled public workspaces still allow returning to
Current context. Image and saved-result conflicts use their existing removal
controls before changing scope.

Scope editing is explicitly enabled only by the main personal-chat composer.
Shared, restricted, inline-answer and image-reference editors do not gain
global scope controls. Scope changes cancel obsolete candidate requests and
clear their results before offering a new set.

| File | Change |
| --- | --- |
| `application/v2_ui/src/components/chat/Composer.tsx` | Remove the standalone row, pass controlled editing, indicate active scope and provide recovery guidance. |
| `application/v2_ui/src/components/chat/ComposerEditor.tsx` | Forward optional editing only to the intended picker and retain public-only candidate behavior. |
| `application/v2_ui/src/components/chat/DocumentPickerPopover.tsx` | Render Search in, descriptions and errors inside Documents; clear stale candidates. |
| `application/single_app/config.py` | Increment the application patch version. |
| `ui_tests/fixtures/orchestration/harness_entry.tsx` | Expose the real shared editor for isolation checks. |

Directory **Chat with visible**, follow-up scope persistence, latest-user-turn
restoration, New chat reset, scope locks and public publication/access checks
retain their existing behavior.

## Validation

Regression coverage uses real components, stores and request builders with
synthetic HTTP boundaries; it does not send production chats or call models.

- `functional_tests/test_v2_chat_context_picker.py` checks opt-in wiring and
  existing context-to-request behavior.
- `functional_tests/test_v2_public_chat_scope.py` checks authoritative public
  resolution, access boundaries, worker isolation and replay.
- `ui_tests/test_v2_public_chat_scope.py` checks Manual and planning dispatch,
  picker-only editing, conflicts, recovery, streaming restrictions, editor
  isolation, scope continuity, and styled desktop/mobile light/dark layouts.
- `ui_tests/test_v2_public_directory.py` checks the native directory handoff
  without visibility writes or legacy navigation.
- `ui_tests/test_v2_chat_context_selection.py` retains ordinary context and
  inline-reference workflows.
- `ui_tests/test_v2_orchestration_composer.py` checks the Manual-controls
  disclosure and administrator gating.

At implementation, the following commands passed:

| Command | Result |
| --- | --- |
| `npm --prefix .\application\v2_ui run build` | TypeScript and production build passed; existing bundle-size warning remains. |
| `python -m pytest .\functional_tests\test_v2_chat_context_picker.py .\functional_tests\test_v2_public_chat_scope.py -q --disable-warnings` | 38 passed. |
| `python -m pytest .\ui_tests\test_v2_public_chat_scope.py .\ui_tests\test_v2_public_directory.py .\ui_tests\test_v2_chat_context_selection.py -q` | 125 passed. |
| `python .\ui_tests\test_v2_orchestration_composer.py` | 7 checks passed. |
| `python .\scripts\build_docs_inventory.py` | Regenerated; no application-surface changes. |
| `python .\functional_tests\test_docs_app_surface_coverage.py` | 7 checks passed. |
| `python .\functional_tests\test_docs_site_quality.py` | 6 checks passed. |
| `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check` | Passed. |

The UI detector reported no deterministic findings. Styled screenshots were
reviewed at 1440px and 390px widths in light and dark themes, including long
configured public-workspace labels. Browser checks used local Chromium through
the existing test harness, not the production Azure application.

Before this fix the selector occupied every eligible composer. Afterward it is
available only when Documents is open; ordinary chat has no replacement banner
or additional control above the input.

See [Aggregate public chat](../features/V2_AGGREGATE_PUBLIC_CHAT.md) and
[Chat context picker](../features/CHAT_CONTEXT_PICKER.md) for scope semantics.
