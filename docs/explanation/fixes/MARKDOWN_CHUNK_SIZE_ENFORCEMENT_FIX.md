# Markdown Chunk Size Enforcement Fix

**Fixed in version: 0.261.002**

## Issue

Uploading a Markdown file to any workspace could fail with:

```
Failed processing Markdown file <name>.md: Error code: 400 - ... maximum context length ...
```

The failure took down the **entire document**, not just the oversized part of it. Files that
looked ordinary, such as a long release notes page, were affected. Lowering **Markdown (words)**
in Admin Settings did not help.

## Root cause

`process_md` in `functions_documents.py` split Markdown with `MarkdownHeaderTextSplitter` on
headings `#` through `#####`, then post-processed the result. The post-processing loop **only
merged chunks that were too small**. There was no branch that split a chunk that was too large:

```python
if current_word_count >= min_chunk_words or i == len(initial_chunks_content) - 1:
    final_chunks.append(current_chunk_text)   # emit
else:
    buffer_chunk = current_chunk_text + "\n\n"  # accumulate
```

`target_chunk_words` was read from settings but used **only** to derive `min_chunk_words`:

```python
target_chunk_words = chunk_config.get('md', {}).get('value', 1200)
min_chunk_words = max(1, int(target_chunk_words * 0.5))
```

So the configured size acted purely as a *minimum*. A heading section with no nested subheading
produced a chunk as large as the text beneath it, which was then handed whole to
`generate_embedding`. That function retries only `RateLimitError` and re-raises everything else,
so a single oversized section aborted the whole upload.

Measured against the pre-fix code, a 120-paragraph section under one `####` heading produced:

| | Chunks | Largest chunk | Approx. tokens |
|---|---|---|---|
| Before | 1 | 109,927 characters | ~36,600 |
| After | 14 | 8,250 characters | ~2,750 |

The embedding limit is 8,192 tokens.

Markdown was the **only** unbounded ingestion path. `process_html` already used a
character-bounded `RecursiveCharacterTextSplitter`, and the xml, yaml, json, txt, doc, log, msg,
pdf, and pptx processors were all bounded.

### Related latent bug

`get_chunk_size_cap` returned `context_window * 2` (fallback 16,384) and `get_chunk_size_config`
applied that number **without regard to the unit**. A word field could therefore be set to 16,384
*words*, roughly 21,000–33,000 tokens, which could never embed. The same cap was used in
`_merge_embedded_images_into_chunks` to derive `16384 x 4 x 0.9` = **58,982 characters**
(~14,700 tokens) as an image merge budget.

## Fix

Three layers, so no single heuristic has to be perfect.

### 1. Word cap at the source

Each header section is now capped at `target_chunk_words` **before** the merge loop, so merge
semantics are unchanged:

```python
capped_chunks_content = []
for section_content in initial_chunks_content:
    capped_chunks_content.extend(split_text_by_word_limit(section_content, target_chunk_words))
initial_chunks_content = capped_chunks_content
```

Splitting prefers the strongest structural boundary available (blank line, then line break, then
space) and never breaks mid-word, so table rows and list items stay intact.

### 2. Character backstop

The merge loop can still carry a trailing chunk of up to `min_chunk_words` onto a following full
chunk, giving up to 1.5x the target. Word counts also cannot predict how badly tables, code
fences, and long URLs tokenize. The final list is therefore bounded by characters:

```python
final_chunks = split_oversized_chunks(final_chunks, max_chunk_characters)
```

This runs **after** merging and is the authoritative bound. The same backstop was added
defensively to `process_html`.

### 3. Last-resort guard at embed time

`save_chunks` now clamps the text passed to `generate_embedding`, and logs a warning when it does.

Splitting is not possible at this point: `chunk_id` is built as `f"{document_id}_{page_number}"`,
so emitting a second chunk for one page would overwrite the first in the search index. Instead
**only the embedding input is clamped** — `page_text_content` is still stored in full, so the
chunk stays readable and citable and only its vector is computed from the leading portion.

### 4. Unit-aware cap

`get_chunk_size_cap` now accepts a unit and returns the matching limit, derived from the embedding
context window with a conservative conversion:

| Unit | Cap (8,192-token model) |
|---|---|
| words | 3,481 |
| characters | 20,889 |
| pages, slides | 16,384 (unchanged; bounded at embed time instead) |

Every shipping default is below these limits, so **no default behavior changed**. Only custom
overrides that could never have embedded successfully are reduced.

`tiktoken` was deliberately not introduced: it is not a dependency of this project and downloads
BPE vocabulary files at runtime from a public endpoint, which does not suit the private-networking
and Azure Government deployments SimpleChat supports. The conversion ratios are instead
deliberately more conservative than English prose, because markdown tokenizes worse than prose.

## Files modified

| File | Change |
|---|---|
| `functions_settings.py` | Added embedding budget helpers and `get_chunk_size_caps_by_key`; made `get_chunk_size_cap` unit-aware and applied it per unit in `get_chunk_size_config` |
| `functions_content.py` | Added `count_words`, `split_text_by_word_limit`, `split_oversized_chunks` |
| `functions_documents.py` | Capped Markdown sections and added the character backstop in `process_md`; backstop in `process_html`; embedding clamp in `save_chunks`; repointed the image merge budget |
| `route_frontend_admin_settings.py` | Per-unit cap in save validation, render context, and admin logging |
| `templates/admin/_panes/extraction.html` | Per-input `data-cap`, corrected cap copy |
| `static/js/admin/admin_settings.js` | Per-input cap in `setupChunkSizeControls` |
| `config.py` | Version `0.261.002` |

## Validation

`functional_tests/test_markdown_chunk_size_enforcement.py` runs the **real** `process_md` against
a stubbed namespace and covers:

- an oversized single-heading section is split and every chunk stays inside both bounds
- no source content is lost while splitting
- ordinary Markdown still splits on headings rather than being reflowed
- a small document still yields exactly one chunk
- the cap is unit-aware and shipping defaults are unchanged
- `save_chunks` clamps only the embedding input and still stores the full chunk text
- `process_md` caps sections before merging and applies the backstop after

Regression coverage re-run: `test_figure_chunk_association.py` (9/9),
`test_chunked_image_storage.py`, `test_docs_app_surface_coverage.py`, `test_docs_site_quality.py`.

## Impact on existing documents

Chunking changes apply to **new uploads only**. Markdown files indexed before this fix keep the
chunks they were indexed with. A file whose upload failed part-way through remains partially
indexed, so re-upload any Markdown document that previously failed to process.
