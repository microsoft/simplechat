# PowerPoint Structured Markdown Export Fix

## Header Information

Fixed in version: **0.241.031**

Enhanced in version: **0.241.032**

Issue description:

PowerPoint export could summarize an assistant message that already contained a complete slide-by-slide markdown deck. A 32-slide markdown answer could be passed back through AI slide planning and reduced to a much smaller deck.

Root cause analysis:

The export path always asked the model to create a fresh PowerPoint outline for non-empty content. That prompt limited output to a small slide range, and the fallback/sanitization path also applied a hard slide cap, so already structured slide markdown was treated like unstructured prose.

Related config update: `application/single_app/config.py` now sets `VERSION = "0.241.032"` after the follow-up rendering improvements.

## Technical Details

Files modified:

- `application/single_app/route_backend_conversation_export.py`
- `application/single_app/config.py`
- `functional_tests/test_per_message_powerpoint_export.py`

Code changes summary:

- Added deterministic detection for markdown decks that use numbered slide headings or slide separators.
- Bypassed AI slide planning for structured decks so the exported `.pptx` keeps the source slide count and slide titles.
- Suppressed generated title, appendix, and reference slides for structured decks so authored slide counts stay exact.
- Added follow-up rendering support for authored title slides, native markdown tables, authored slide-number footers, and trimming of non-slide speaker-note/caveat text.
- Changed the seven-slide cap into the default for unstructured content, with a bounded optional `slide_count` request value for future UI/API customization.
- Kept AI planning for unstructured messages while letting the caller request a larger target deck size up to the supported limit.

Testing approach:

- Updated the per-message PowerPoint functional test to generate a 32-slide markdown deck with citations and verify the exported PowerPoint contains exactly 32 slides.
- Added validation coverage for accepted and rejected optional `slide_count` values.
- Retained existing coverage for route registration, frontend hook presence, message-model selection, and appendix rendering.

## Validation

Before:

- A slide-structured assistant response could be replanned into a shorter presentation.
- The model prompt and sanitizer imposed small slide-count limits even when the source already specified each slide.

After:

- Structured markdown exports directly to PowerPoint without AI summarization.
- A 32-slide markdown deck exports as 32 PowerPoint slides.
- Unstructured message export still defaults to a concise deck, while `slide_count` can request a specific bounded target.

Related functional test:

- `functional_tests/test_per_message_powerpoint_export.py`