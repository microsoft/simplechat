# PPTX `render_file` Layout Overflow and Pasted URL Zero-Width Character Fix (v0.261.380)

Fixed in version: **0.261.380**

## Issue Description

When requesting an orchestrated PowerPoint presentation grounded on a pasted GitHub repository URL (such as `https://github.com/paullizer/score`), the run failed during the `render_file` step (`Score_Overview_and_Evaluation_Framework.pptx: could not be created` / `This operation could not complete`) with `error_code: "output_invalid"` and `error_type: "OfficeRenderError"`.

## Root Cause Analysis

1. **Trailing Invisible Unicode Format Characters in Pasted URLs (`url_fetch` HTTP 404)**:
   - Pasting a URL from a browser or rich-text surface included a trailing Unicode Zero Width Non-Joiner (`\u200c`) after the URL path (`https://github.com/paullizer/score\u200c`).
   - `extract_urls_from_text()` and `normalize_review_url()` in `functions_source_review.py` and `_extract_urls()` in `functions_orchestration_context.py` matched `r"https?://[^\s<>'\"]+"` without stripping Unicode format (`Cf`) characters.
   - As a result, `url_fetch` requested `/paullizer/score%E2%80%8C`, received `http_404`, and returned empty repository evidence to the `compose` step.

2. **Validation Mismatch Between `compose` (`prepare_generated_slide_deck`) and `render_file` (`render_prepared_pptx`)**:
   - `prepare_generated_slide_deck()` (called by `validate_composition_profile()` during `compose`) validated JSON schema, slide count, and box bounds/overlap, **but did not validate physical text fit (`_slide_text_height`) or hyperlink safety (`_safe_link`)**.
   - Consequently, `compose` accepted and persisted a `prepared_slide_deck_v1` payload without triggering `adapter_compose`'s corrective retry (`_compose_correction`), and `render_file` failed afterward in `render_prepared_pptx` with `OfficeRenderError("layout_overflow")`.
   - Furthermore, three overly rigid text-measurement behaviors caused 7 of 8 slides in the model's `prepared_slide_deck_v1` output to fail `_slide_text_height`:
     - Slide titles were hardcoded to `30pt` in a `1.0in` (`72pt`) title box (`PREPARED_SLIDE_TITLE_HEIGHT = 1.0`), causing any single-line title over ~45 characters to wrap to 2 lines (`99pt > 72pt`) and fail.
     - `_slide_text_height()` only split tokens on whitespace (`r"\S+|[^\S\n]+"`), treating URLs and hyphenated strings (e.g. `https://github.com/paullizer/score`) as single unbreakable tokens that overflowed narrow column boxes.
     - Model-selected body `font_size` (`18`–`28pt`) and box heights slightly exceeded conservative `fitz.Font("hebo")` line-height budgets even when `14`–`18pt` or unoccupied vertical space below the box on the slide could accommodate the text cleanly.

3. **`OfficeRenderError` Misclassified as `output_invalid` in `output_failure()`**:
   - `OfficeRenderError` subclasses `ValueError`, not `GeneratedFileExportError`.
   - `output_failure()` in `functions_orchestration_rendering.py` checked `isinstance(exc, GeneratedFileExportError)` and fell through to `isinstance(exc, (ValueError, TypeError)) -> ("output_invalid", False)`, losing specific codes (`layout_overflow`, `incomplete_source`, `output_access_denied`, `output_source_changed`) and retryability (`render_io`, `source_unavailable`).

## Technical Details

### Files Modified

- `application/single_app/functions_source_review.py`:
  - Added `_strip_invisible_url_characters()` to strip Unicode `Cf` format characters (`\u200b`, `\u200c`, `\u200d`, `\u2060`, `\ufeff`, `\u00ad`) in `extract_urls_from_text()` and `normalize_review_url()`.
- `application/single_app/functions_office_file_renderers.py`:
  - Updated `_slide_text_height()` with `_SLIDE_WRAP_TOKENS` to wrap tokens at `/` and `-` in addition to whitespace.
  - Added `_slide_title_font_size()` so single-line `title_and_content` titles (without explicit `\r`/`\n` breaks) step down from `30pt` to `14pt` as needed to fit `PREPARED_SLIDE_TITLE_HEIGHT`.
- `application/single_app/functions_generated_office_adapters.py`:
  - Updated `prepare_generated_slide_deck()` to validate slide title fit, hyperlink safety (`_safe_link`), and physical text fit for `SlideTextBox` and `SlideTable`, deterministically fitting `font_size` (down to `8pt`) and expanding `box.height` into unoccupied vertical slide space when needed, without mutating the caller's input dictionary.
  - Un-fittable shapes or multi-line titles now raise `OfficeRenderError("layout_overflow")` during `prepare_generated_slide_deck()` so `validate_composition_profile()` triggers `adapter_compose`'s corrective retry before persistence.
- `application/single_app/functions_orchestration_composition.py`:
  - Updated `_OUTPUT_PROBLEMS['result_layout_invalid']` to explicitly instruct the model to keep slide titles to a single concise line and size boxes/fonts so all text fits.
- `application/single_app/functions_orchestration_rendering.py`:
  - Updated `output_failure()` to classify `OfficeRenderError` codes and preserve `retryable` for transient `render_io` and `source_unavailable` errors.
- `application/single_app/config.py`:
  - Bumped `VERSION` to `0.261.380`.

## Validation

- Added `functional_tests/test_pptx_render_file_mitigation.py` validating:
  - End-to-end preparation and PPTX rendering of the exact 8-slide Score deck payload from the failed Azure run;
  - Pre-persistence rejection of un-fittable `layout_overflow` and multi-line titles during `validate_composition_profile()`;
  - `output_failure()` classification of `OfficeRenderError` codes and retryability;
  - Stripping of trailing zero-width Unicode characters (`\u200c`, `\u200b`, `\ufeff`) in URL extraction and normalization.
- Verified existing test suites (`test_office_file_renderers.py`, `test_generated_file_office_bridge.py`, `test_orchestration_compose_output_retry.py`, `test_orchestration_dependency_runtime.py`).
