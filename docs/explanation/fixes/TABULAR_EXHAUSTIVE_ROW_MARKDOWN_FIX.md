# TABULAR EXHAUSTIVE ROW MARKDOWN FIX

Fixed in version: **0.250.201**

## Issue Description

Durable Search and Analyze runs correctly read all 200 rows and published Markdown, but the Markdown contained only 12 row findings. The artifact still reported `Rows analyzed: 200`, which described input coverage rather than output cardinality.

For the customer prompt requesting eight individual answers for every line, the required outputs are:

- **Search:** one exhaustive Markdown file containing all 200 rows and all eight answers per row.
- **Analyze:** one concise Markdown analysis summary plus one exhaustive Markdown file containing all 200 rows and all eight answers per row.

Aggregate prompts such as analyzing all rows for themes or risks continue to produce the bounded summary artifact.

## Root Cause Analysis

The no-format row request was routed to the hierarchical summary lane. That lane intentionally:

- asks each chunk for `summary`, `findings`, `counts`, and `notable_rows`;
- caps findings at 12 and notable rows at 25;
- recursively reduces chunk summaries;
- renders only the bounded reduced fields into Markdown.

It guaranteed that all source rows were read, but never guaranteed one output entry per row. The 200-row run happened to use one chunk, and the model returned 12 findings, exactly matching the server cap.

## Technical Details

### Files Modified

- `application/single_app/functions_tabular_orchestration.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/config.py`
- Related functional and Playwright tests

### Code Changes Summary

- Added explicit per-row narrative intent detection, separate from aggregate whole-dataset analysis.
- Extracted the user's ordered, bounded question list and planned `answer_1` through `answer_N` fields.
- Routed no-format per-row Search to `structured_export(md)` and Analyze to `combined(md)`.
- Planned distinct artifact IDs so Analyze can require two same-format siblings: `analysis-summary` and `row-analysis-md`.
- Reused the durable exact-row checkpoint engine, including source tokens, exact row counts, stable schemas, source order, retries, and idempotent publication.
- Sized batches using estimated narrative output per row so a 200-row/eight-question request is split into multiple bounded model calls.
- Required every expected answer field to be non-empty and consecutive before checkpoint acceptance.
- Added an ordered Markdown stream finalizer that writes every source row and original question label, then verifies the final row count.
- Escaped source identities, user question labels, and model-generated answers as literal Markdown text.
- Added distinct UI titles for the summary and row-by-row Markdown artifacts.
- Preserved the existing hierarchical summary lane for aggregate prompts and the existing CSV/JSON/XML behavior for explicit structured formats.

## Validation

- Exact customer prompt extracts all eight questions and plans:
  - Search: `row-analysis-md`.
  - Analyze: `analysis-summary` plus `row-analysis-md`.
- A deterministic 200-row test streams four checkpoints into Markdown and asserts:
  - 200 row headings;
  - each of eight questions appears 200 times;
  - the final row and final eighth answer are present;
  - 1,600 answers are represented;
  - missing answers and malformed answer sequences fail validation.
- Adversarial row identities, questions, and answers verify active Markdown links and raw HTML are escaped.
- Queue-level testing verifies output-aware batching creates multiple batches and persists exact schemas.
- Full 70-test tabular scale coverage passes, including 100,000-row planning and idempotent publication.
- Full background-card UI suite passes, including Search's one Markdown card and Analyze's two distinct Markdown cards.

## Impact Analysis

- "All rows analyzed" now means all rows are also present in the exhaustive deliverable when the user asks for individual per-row output.
- Summary and exhaustive output remain separate concerns, preventing concise analysis from truncating row deliverables.
- Large requests remain bounded and checkpointed instead of attempting one unbounded model response or in-memory artifact.

## Related Version Updates

- `application/single_app/config.py` was updated to version **0.250.201**.
