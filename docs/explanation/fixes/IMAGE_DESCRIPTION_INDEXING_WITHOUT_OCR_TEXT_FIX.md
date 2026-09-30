# Image Description Indexing Without OCR Text Fix (v0.261.047)

Fixed in version: **0.261.047** (Development) and **0.261.210** (React V2)

Issue: [#1583](https://github.com/microsoft/simplechat/issues/1583)

## React V2

The same fix ships on the React V2 branch in **0.261.210**, with these differences, because
React V2 enforces model capabilities and embedding limits that Development does not:

- The shared AI connection client helper finds the model and re-checks its chat capability
  before resolving any Key Vault secret, as React V2 metadata extraction always did. A missing
  model raises the same `LookupError`, and a disabled model is refused by the shared capability
  check with "The selected model is not available for chat. Choose a compatible model."
- Vision analysis re-checks image support against the resolved connection's model record. The
  legacy GPT path keeps its existing capability checks.
- React V2 refuses a chunk that is too large for a non-legacy embedding profile instead of
  clamping it. When the appended vision block would push a page that fits over that limit, the
  page's OCR text is embedded on its own, as before, and the stored chunk text still includes
  the block.
- V2 chat shows what was extracted from an uploaded image. See
  [V2 Chat Upload Extraction and Image Card Fix](V2_CHAT_UPLOAD_EXTRACTION_AND_IMAGE_CARD_FIX.md).

## Issue Description

A user uploaded two nearly identical grayscale photos of an empty lab floor. Neither photo has
real text, and one is more overexposed.

- The less-exposed photo was indexed and got a title.
- The overexposed photo ended with the status **Processing complete - no text found in image**,
  no title, and 0 chunks in Azure AI Search, so chat could not use it.

The AI vision model had described both photos, and the overexposed photo's vision analysis was
stored on its Cosmos DB document, but no chunk was ever written for it.

A later upload of another image failed with `404 Not Found` from
`/openai/deployments/gpt-5.6-luna/chat/completions` on the primary Azure OpenAI resource. The
selected vision model was deployed only on a different AI connection, yet the admin
**Test Vision Analysis** button reported success.

## Root Cause Analysis

Four problems combined:

1. **Only OCR text could create an image chunk.** `process_di_document()` built image chunks from
   OCR pages only. Content Understanding `prebuilt-documentSearch` returned no pages for either
   photo, so extraction fell back to Document Intelligence `prebuilt-layout`. Layout read a strip
   of floor tape on the less-exposed photo as the page number `J` (confidence 0.18), producing the
   markdown `<!-- PageNumber="J" -->`, and returned no content for the overexposed photo. The
   bogus comment became the less-exposed photo's only chunk; the overexposed photo got none.
   With `total_final_chunks_processed == 0`, final metadata extraction was skipped as well.
2. **The vector ignored the vision description.** `save_chunks()` appended the vision analysis to
   the stored chunk text only after generating the embedding from the OCR text, so the logs showed
   `embedding - 7 tokens` for the less-exposed photo's chunk.
3. **Content Understanding's image description was discarded.** The configured image analyzer,
   `prebuilt-imageSearch`, described both photos well, but it returns the markdown
   `![image](pages/1)` and puts the description in `contents[0].fields.Summary.valueString`.
   `analyze_image_with_content_understanding()` ignored `fields`, so it only ever returned the
   placeholder, and it was only used for images embedded in Office files.
4. **The vision model ignored its AI connection.** `analyze_image_with_vision_model()` always built
   its client from the legacy `azure_openai_gpt_*` (or APIM) settings, while the admin test
   resolved the model's configured connection. The setting stores only the model name
   (`multimodal_vision_model`), so nothing mapped it back to the connection that hosts it.

## Technical Details

### Files Modified

| File | Change |
| --- | --- |
| `application/single_app/functions_documents.py` | Shared vision block formatting, enhanced text embedded in `save_chunks()` and `save_chunks_batch()`, description-only image chunks, `is_image` threading, vision model routing, shared model-endpoint client builder |
| `application/single_app/functions_content.py` | `extract_content_with_extraction_engine(..., is_image=False)` image analyzer fallback |
| `application/single_app/functions_content_understanding.py` | `analyze_image_with_content_understanding()` reads string fields and ignores placeholder-only markdown |
| `application/single_app/functions_model_endpoint_types.py` | Pure `find_enabled_model_endpoint_for_model_name()` lookup |
| `application/single_app/route_backend_settings.py` | Test Vision Analysis uses the same connection as ingestion |
| `application/single_app/route_frontend_chats.py` | Chat image uploads pass `is_image=is_image_file` |
| `application/single_app/config.py` | Version `0.261.047` |
| `functional_tests/test_image_description_indexing_without_ocr_text.py` | New regression coverage |
| `docs/admin/knowledge.md`, `docs/admin/workspaces.md` | How vision analysis is indexed and which connection it uses; Image Analyzer role |
| `docs/explanation/features/CONTENT_UNDERSTANDING_ENHANCED_EXTRACTION.md` | Standalone image analyzer fallback |
| `docs/explanation/release_notes.md` | Bug Fixes entry |

### Code Changes Summary

**Index image descriptions when OCR finds no text** (`functions_documents.py`)

- `_format_vision_analysis_block(vision_analysis)` replaces the two copies of the inline
  formatting. Valid analyses produce exactly the previous `=== AI Vision Analysis ===` block. It
  returns `''` when the analysis is missing, not a dict, has an `error` key, or has no
  description, objects, text, or analysis, so a vision failure message is never indexed.
- `_append_vision_block_to_chunk_text(chunk_text, vision_text)` appends the block, dropping its
  leading blank lines when there is no OCR text.
- `save_chunks()` now builds the stored text before embedding and embeds that same text, keeping
  the last-resort clamp guard. It skips, with a warning, any chunk that has nothing to index.
  `save_chunks_batch()` uses the same helpers so both paths stay consistent.
- `process_di_document()` records whether this run produced a usable vision analysis
  (`_is_usable_vision_analysis()`). For images it keeps only OCR pages with real text, treating a
  page whose only content is Document Intelligence page-number or page-break annotations, such as
  `<!-- PageNumber="J" -->`, as having none (`_has_indexable_ocr_text()`). Header and footer
  comments, such as `<!-- PageHeader="Lab 3" -->`, still count as text because their quoted value
  is the recognized text. When no OCR text remains and a usable analysis exists, it saves one
  page-1 chunk flagged with `vision_description_only`, which `save_chunks()` fills with the stored
  vision block. Final metadata extraction then runs as usual. Images with real OCR text are
  unchanged. Vision analysis still runs only when Enhanced Citations is enabled.

**Fall back to the Content Understanding image analyzer** (`functions_content_understanding.py`,
`functions_content.py`)

- `analyze_image_with_content_understanding()` emits the `Summary` field as plain text and any
  other non-empty string field as `Name: value`, ignores markdown made up only of image
  placeholders such as `![image](pages/1)`, and keeps the existing figure-summary handling. This
  also fixes images embedded in DOCX and PPTX files, which were indexed with just the placeholder
  when Content Understanding analyzed them.
- `extract_content_with_extraction_engine()` takes `is_image`. When the document analyzer returns
  no content for an image, it calls the image analyzer and returns its description as page 1 with
  the reason *Content Understanding found no text, so its image analyzer description was indexed*.
  If the image analyzer fails or returns nothing, it logs a warning and falls back to Document
  Intelligence Layout exactly as before. PDFs and other files are unchanged. Workspace uploads
  pass the flag through `_extract_pages_with_extraction_engine()`, and chat uploads pass it from
  `route_frontend_chats.py`.

**Route the vision model through its AI connection** (`functions_model_endpoint_types.py`,
`functions_documents.py`, `route_backend_settings.py`)

- `find_enabled_model_endpoint_for_model_name(endpoints, model_name)` is a pure lookup over
  enabled endpoints and enabled models. A deployment name or resolved request model wins over a
  model name, which wins over a model id, and the first match in endpoint order wins within the
  same precedence. It returns `(endpoint, model)` or `(None, None)`.
- `resolve_vision_model_endpoint(settings, vision_model)` applies that lookup to the normalized
  `model_endpoints` when multi-endpoint models are enabled.
- `_build_model_endpoint_client_for_model(settings, endpoint_cfg, model_id, ...)` holds the
  client construction that metadata extraction used: Key Vault secret resolution, model lookup,
  request-model resolution, API version and protocol checks, the provider allowlist, and
  `_build_model_endpoint_client()`. Metadata extraction calls it with the same order and error
  messages as before.
- `analyze_image_with_vision_model()` uses the matched connection and sends
  `model=<resolved request model>`. Otherwise it builds the legacy APIM or direct client exactly as
  before. It logs which connection was used by name and id only, and still returns `None` on
  errors. Chat image uploads call the same function.
- `_test_multimodal_vision_connection()` resolves the model name the same way, so the admin test
  exercises the connection ingestion will use, including when APIM is selected for GPT.

## Testing

`functional_tests/test_image_description_indexing_without_ocr_text.py` runs the pure lookup tests
in-process and runs the real modules in fresh normal and optimized processes with external I/O
blocked. It covers:

- vision block formatting for valid, error, parse-failed, and empty analyses,
- `save_chunks()` storing and embedding the same text, the description-only chunk, skipped empty
  chunks, and the unchanged clamp guard, plus `save_chunks_batch()` parity,
- the less-exposed (`<!-- PageNumber="J" -->`), overexposed (empty page), and no-page image
  cases, real OCR text, header-only OCR text, mixed pages, and failed, empty, missing, or disabled
  vision analysis,
- the `prebuilt-imageSearch` payload, other string fields, placeholder-only markdown, and figure
  de-duplication,
- the extraction fallback for images, analyzer failure and empty results, PDFs, document analyzer
  content and failure, and Standard extraction, plus the chat upload call site,
- the vision connection lookup: match precedence, disabled endpoints and models, blank and
  malformed input, legacy fallback with multi-endpoint off or no match, and APIM,
- unchanged metadata extraction client construction and every error message,
- the admin vision test using the ingestion connection with an APIM payload.

Run it with:

```powershell
python .\functional_tests\test_image_description_indexing_without_ocr_text.py
```

Related suites re-run: `test_content_understanding_extraction_engine.py`,
`test_office_embedded_image_extraction.py`, `test_figure_chunk_association.py`,
`test_multimodal_vision_multi_endpoint_connection.py`,
`test_document_intelligence_pdf_image_extraction_mode.py`,
`test_document_intelligence_auto_reprocess_contract.py`,
`test_privacy_logging_telemetry_audit.py`, the model endpoint provider suites, and the route policy
suites.

## Impact

- Text-free images are searchable through their AI vision description and get a title from
  final metadata extraction.
- Image vectors now reflect the vision description, improving retrieval for image content.
- Existing documents are not re-indexed automatically. Re-upload an affected image to index it
  with this fix. **Change Extraction** also re-indexes an image, but it does not re-run final
  metadata extraction, so the image still has no generated title.
- A vision model name that exists on more than one enabled connection resolves by the precedence
  above, because the setting stores only the name.

## Validation

| Scenario | Before | After |
| --- | --- | --- |
| Overexposed photo, no OCR text | 0 chunks, no title, status "no text found in image" | 1 chunk holding the vision description, metadata extracted |
| Less-exposed photo, Layout reads `J` | Chunk text `<!-- PageNumber="J" -->` plus vision block, 7-token embedding | 1 chunk holding the vision description, embedded in full |
| Content Understanding image analyzer | `![image](pages/1)` | The `Summary` description |
| Vision model on another AI connection | 404 from the primary Azure OpenAI resource | Called on the connection that hosts it |
| Test Vision Analysis with APIM selected | Tested APIM while ingestion differed | Tests the connection ingestion uses |
