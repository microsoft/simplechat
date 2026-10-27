# Orchestration Unfound Source Information & Linked PDF Coverage Fix

- **Version Implemented**: **0.261.385**
- **Related Config Update**: `application/single_app/config.py` (`VERSION = "0.261.385"`)
- **Related Functional Test**: `functional_tests/test_orchestration_unfound_source_handling.py`

## Issue Description

When a user asked a question to check whether specific information existed in a document or linked URL (for example, `"Which program is 10 seconds on and 10 seconds off? https://manuals.plus/m/..._optim.pdf"`), the orchestration run failed with `completeness_incomplete` (`"The answer did not satisfy the requested requirements within its correction allowance."`) instead of completing with an answer explaining that the searched content did not contain the requested information.

### Root Cause Analysis

1. **Task Completeness Rejecting Honest "Not Found in Source" Responses**:
   - When the gathered source content did not contain the requested item or setting, `compose` honestly stated that the information was not present in the provided source.
   - However, `CHECK_POLICY` in `functions_task_completeness.py` evaluated the candidate strictly against the positive deliverable description (for example, `"The program name and a concise explanation of its 10-seconds-on/10-seconds-off setting"`) without recognizing that reporting the absence of an item in the searched sources—backed by page/source coverage and evidence of what the content actually covers—fulfills the user's lookup request.
   - Consequently, `check_and_correct` marked the requirement as unmet (`missing` / `unsupported` / `uncertain`), and `adapter_compose` failed the step with `completeness_incomplete`.

2. **Linked PDF Support & Page Coverage in `url_fetch` / `document_search`**:
   - `SAFE_CONTENT_TYPES` in `functions_source_review.py` did not include `application/pdf`, causing linked PDF manuals fetched via `url_fetch` to be skipped with `unsupported_content_type` (`"No linked pages could be read."`).
   - When all URLs in `url_fetch` were skipped and `pages` was empty, `notes` was left empty (`[]`), giving `compose` no details on which URLs were attempted or why they could not be read.
   - When `document_search` or `document_analyze` returned an empty `evidence` or `findings` list to `compose`, the producer's `coverage` metadata was not attached to the empty input entry.

## Technical Details

### Files Modified

- `application/single_app/functions_source_review.py`:
  - Added `"application/pdf"` to `SAFE_CONTENT_TYPES` (and allowed `.pdf` URLs served as `application/octet-stream` / `binary/octet-stream` when verified by `%PDF-` header bytes).
  - Added `extract_source_review_evidence_from_pdf` using PyMuPDF (`fitz`) to extract text page by page with `[Page X of Y]` labels, record `pdf_page_count`, `pdf_pages_inspected`, and `pdf_pages_with_text`, and include a `PDF coverage: Inspected X of Y total page(s)` summary alongside page excerpts.
- `application/single_app/functions_orchestration_adapters.py`:
  - Included PDF page inspection counts in `_notes_from_source_review` and `_finalize_source_review` summaries.
  - Added explanatory notes for skipped URLs when `url_fetch` returns no readable pages.
- `application/single_app/functions_orchestration_result_runtime.py`:
  - Added `returned_page_count` and `pages_in_returned_excerpts` to `retain_document_search_result` coverage.
  - Added `read_result_source_coverage` to project bounded source/page coverage from the producer's committed manifest when an input value is empty.
- `application/single_app/functions_orchestration_composition.py`:
  - Updated `KNOWLEDGE_POLICIES` (`sources` and `sources_and_general_knowledge`) to instruct the model to clearly state when the searched content does not contain the requested information, report the inspected page/source coverage, and summarize what the content covers.
  - Attached `source_coverage` on empty `compose` inputs via `read_result_source_coverage`.
- `application/single_app/functions_task_completeness.py`:
  - Updated `CHECK_POLICY` and `CORRECTION_POLICY` so that for source-grounded tasks where the supplied evidence does not contain the requested fact/item, an answer that clearly states the content does not contain it, reports the available source/page coverage, and summarizes what the inspected content covers satisfies the requirement (`status: "satisfied"`), or is marked `"missing"` (for bounded correction) if coverage/evidence details from the inputs were omitted.
- `application/single_app/config.py`:
  - Incremented `VERSION` to `"0.261.385"`.

## Validation

- Ran `pytest functional_tests/test_orchestration_unfound_source_handling.py`
- Ran `pytest functional_tests/test_task_completeness_engine.py functional_tests/test_task_completeness_runtime.py`
- Ran `pytest functional_tests/test_source_review_security.py functional_tests/test_source_review_deep_traversal.py functional_tests/test_orchestration_deep_research.py functional_tests/test_orchestration_search_result_integrity.py`
