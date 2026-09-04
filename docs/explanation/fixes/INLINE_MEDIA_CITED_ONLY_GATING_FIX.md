# Inline Media Cited-Only Gating Fix

Fixed/Implemented in version: **0.260.024**

GitHub issue: [#1329](https://github.com/microsoft/simplechat/issues/1329) (follow-up to [#1249](https://github.com/microsoft/simplechat/issues/1249))

## Issue Description

Assistant messages rendered inline image and video galleries for every media document returned by retrieval, not just the media the response actually cited. A workspace search that surfaced five image files produced five inline gallery tiles even when the answer referenced only one of them, or none at all.

Because the galleries sit directly inside the message bubble, unrelated media was presented as though it supported the answer. The five-item gallery cap could also be consumed entirely by retrieval noise, pushing genuinely cited media out of view, and each unreferenced workspace file triggered an additional enhanced-citation fetch.

## Root Cause Analysis

Issue #1249 introduced the separation between retrieved sources and exact references. Every assistant message now persists `cited_hybrid_citations` and `cited_web_search_citations` alongside the complete `hybrid_citations` and `web_search_citations` arrays, and those cited subsets already reach the browser on all four delivery paths: history load, the streaming terminal event, the legacy non-streaming bridge, and collaboration message serialization.

The inline gallery renderers were never switched over. `appendMessage` passed the full retrieved arrays into `renderInlineImageGalleries` and `renderInlineVideoGalleries`, and those renderers select workspace media purely by file extension through `extractWorkspaceCitationImageItems` and `extractWorkspaceCitationVideoItems`. Any retrieved `.png` or `.mp4` therefore became a gallery tile regardless of whether it was cited. No frontend module read the cited subsets at all.

## Technical Details

Files modified:

- `application/single_app/static/js/chat/chat-citation-tracking.js` (new)
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/static/js/chat/chat-inline-images.js`
- `application/single_app/static/js/chat/chat-inline-videos.js`
- `application/single_app/config.py`
- `functional_tests/test_inline_media_cited_only_gating.py` (new)
- `functional_tests/test_inline_image_gallery_visualization.py`
- `functional_tests/test_inline_video_gallery_visualization.py`
- `functional_tests/test_chat_cited_source_tracking.py`
- `ui_tests/test_chat_inline_image_gallery_rendering.py`
- `ui_tests/test_chat_inline_video_gallery_rendering.py`

Code changes summary:

- Added `chat-citation-tracking.js`, the browser mirror of `functions_citation_tracking._message_has_citation_tracking()`. It exports `messageHasCitationTracking`, `getCitedHybridCitations`, and `getCitedWebCitations`. A message counts as tracked when `citation_tracking_version` is at least `1` or either `cited_*` key is present, and each getter normalizes non-array values to an empty list.
- `appendMessage` now derives `citedHybridCitations` and `citedWebCitations` from the assistant message object and passes those to both gallery renderers. The Sources disclosure, its count badges, and the metadata drawer continue to receive the complete retrieved arrays.
- Renamed the gallery entry-point and extraction helper parameters to `citedHybridCitations` and `citedWebCitations` so the narrowed contract is explicit at the call boundary.
- Corrected the "Linked images" and "Linked videos" card summaries, which described the links as merely returned with the response rather than cited by it.

No backend change was required. `functions_citation_tracking.build_cited_source_subsets()` already produces the subsets, and conversation and per-message exports already select them through `get_message_reference_citation_buckets()`.

### Scope boundaries

- **Agent and tool galleries still render.** An action that returns an image or video gallery is an executed tool result, not an unused retrieval candidate. This matches how #1249 treats agent records.
- **Legacy messages keep prior behavior.** Messages saved before citation tracking existed carry no cited arrays and fall back to the full retrieved set, matching the no-migration legacy fallback in `get_message_reference_citation_buckets()` and #1249's decision to avoid read-time history parsing.
- **A tracked response that cited nothing renders no workspace or linked gallery.** `renderInlineImageGalleries` and `renderInlineVideoGalleries` already collapse `.inline-visualizations-container` with `d-none` when it has no children, so an empty result leaves no visual gap.

## Validation

Test coverage added or updated:

- `functional_tests/test_inline_media_cited_only_gating.py` executes the real `chat-citation-tracking.js` helper under Node across tracked, untracked, empty-cited, key-presence-only, missing-message, and malformed-value inputs, then asserts the wiring in `chat-messages.js`, that the Sources panel still receives full arrays, and that both renderers declare cited inputs.
- `functional_tests/test_chat_cited_source_tracking.py` gained `test_inline_media_galleries_render_cited_subsets_only`, keeping the inline galleries inside the citation-tracking contract suite (17/17 passing).
- `functional_tests/test_inline_image_gallery_visualization.py` and `functional_tests/test_inline_video_gallery_visualization.py` had their wiring assertions updated from the retrieved-set call shape to the cited-subset call shape.
- `ui_tests/test_chat_inline_image_gallery_rendering.py` and `ui_tests/test_chat_inline_video_gallery_rendering.py` gained a gating regression test covering three messages in one page: a tracked response that cited one of two retrieved media files, a tracked response that cited nothing but ran a media action, and a legacy untracked response.

Before and after:

| Scenario | Before | After |
| --- | --- | --- |
| Tracked response, 1 of 5 retrieved images cited | 5 inline tiles | 1 inline tile |
| Tracked response, no documents cited | Every retrieved image tiled | No workspace gallery |
| Tracked response, no documents cited, media action ran | Retrieved images plus action gallery | Action gallery only |
| Legacy untracked response | Every retrieved image tiled | Unchanged |
| Sources disclosure | Complete retrieved set | Unchanged |
