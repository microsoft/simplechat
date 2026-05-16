# PowerPoint Structured Markdown Rendering Fix

## Header Information

Fixed in version: **0.241.032**

Issue description:

Structured markdown PowerPoint exports preserved the deck shape, but still rendered too literally. A markdown title slide became a normal content slide, authored slide numbers were not visible in the generated slide footer, markdown tables were dropped from slide bodies, and trailing non-slide sections such as optional speaker notes or follow-up offers could leak into the final slide.

Root cause analysis:

The structured markdown export path only extracted slide titles and bullets. It did not promote a `Slide 1 - Title` section into the presentation title slide, did not parse markdown tables for inline rendering, and did not trim post-deck prose from the final slide section.

Related config update: `application/single_app/config.py` now sets `VERSION = "0.241.032"`.

## Technical Details

Files modified:

- `application/single_app/route_backend_conversation_export.py`
- `application/single_app/config.py`
- `functional_tests/test_per_message_powerpoint_export.py`
- `docs/explanation/fixes/v0.241.031/POWERPOINT_STRUCTURED_MARKDOWN_EXPORT_FIX.md`

Code changes summary:

- Promoted authored `Slide 1 - Title` sections into the real PowerPoint title slide.
- Preserved authored slide numbers in structured slide footers.
- Parsed markdown tables inside structured slides and rendered the first table as a native PowerPoint table on that slide.
- Trimmed post-deck speaker notes, coverage caveats, and follow-up offer text from structured slide bodies.
- Kept structured decks out of AI replanning so title/table improvements do not reintroduce summarization.

Testing approach:

- Expanded the focused PowerPoint export functional test with a representative 32-slide structured markdown deck.
- Verified the generated deck keeps exactly 32 slides, uses a true title slide, renders the Slide 3 budget table natively, includes authored slide footer text, and excludes trailing speaker-note/follow-up text.

## Validation

Before:

- `Slide 1 - Title` rendered as a basic content slide titled `Title`.
- Markdown table rows were ignored by the slide body extractor.
- The final slide could include optional speaker notes or "If you want..." follow-up text.

After:

- Structured decks retain their authored slide count while producing a more presentation-like title slide and table slide.
- Markdown tables render in-place as native PowerPoint tables.
- Non-slide tail text is excluded from the exported `.pptx`.

Related functional test:

- `functional_tests/test_per_message_powerpoint_export.py`