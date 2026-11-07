# Orchestration Completeness Verification, Unfound Source Coverage, and Scoped Memory Isolation Fix (v0.261.384)

Fixed in version: **0.261.384** (`application/single_app/config.py`).

## Issue Description

Following the enablement of model-assisted task completeness checks in `0.261.382`, orchestrated `compose` runs in live UI testing and user sessions failed with:

1. `"The answer could not be verified. Review model availability, access and context limits."` (`completeness_unavailable` with `reason_code: "completeness_candidate_reference_invalid"` or `"completeness_evidence_invalid"`), even when `orchestration_compose` produced a complete, accurate response (`FED-37`, `FED-19`, `FED-35`, `FED-36`).
2. `"The answer did not satisfy the requested requirements within its correction allowance."` (`completeness_incomplete` with `reason_code: "completeness_requirements_unmet"`), or answer corruption during `completeness_correct` where user-saved memory prefixes, section headings (`## Decision`, `## Evidence`, `## Next step`), and personas (`Avery, readiness reviewer`) were flagged as unsupported additions or stripped out.
3. Linked PDF manuals in `url_fetch` were skipped with `unsupported_content_type`, and source-grounded responses explaining that a searched source did not contain a requested item were rejected as `incomplete`.

## Root Cause Analysis

1. **Brittle `answer_quote` and `evidence_refs` Normalization in `functions_task_completeness.py`**:
   - `normalize_assessment()` required every `"satisfied"` requirement to carry a single contiguous substring (`quote in candidate`). Multi-heading order requirements (`"## Decision ... ## Evidence ... ## Next step"`), negative/absence constraints (`"Do not use em dashes"`), or minor whitespace/markdown differences raised `CompletenessError("completeness_candidate_reference_invalid")`.
   - `CHECK_POLICY` asked for `"exact supplied evidence IDs"`, while `normalize_assessment()` only allowed top-level dictionary keys of `evidence`. When the checker cited nested `citation_id` (`[#...]`), `document_id`, `file_name`, or record identifiers inside `evidence`, `normalize_assessment()` raised `CompletenessError("completeness_evidence_invalid")`.

2. **Missing Saved Memory and Conversation History in `adapter_compose` Completeness Checks (`functions_orchestration_composition.py`)**:
   - `orchestration_compose` received `memory['context_messages']` (`<Instruction Memory>` and `<Fact Memory>`), `history` (`execution_conversation_messages(context)`), `CONVERSATION_POLICY`, and deliverable/visual guidance, but `adapter_compose` did not pass them into `check_and_correct()`.
   - Consequently, `completeness_check` and `completeness_correct` treated memory-derived prefixes, headings, personas, and prior-turn baseline facts as unrequested or unsupported additions.

3. **Scoped Memory Leakage in `_select_scoped_memory_candidates` (`functions_fact_memory_context.py`)**:
   - When a conversation had no identifier matching any saved scoped memory (`not has_any_matched_id`), `_select_scoped_memory_candidates()` fell back to `prefix_latest_id[prefix]` and `if not filtered: filtered = list(items)`, injecting scoped `CB-27-*` and `FED-*` memories into unrelated conversations.

4. **Unfound Source Handling and Linked PDF Extraction (`functions_source_review.py`, `functions_orchestration_adapters.py`, `functions_orchestration_result_runtime.py`)**:
   - `SAFE_CONTENT_TYPES` excluded `application/pdf`, causing linked PDF manuals to be skipped in `url_fetch`.
   - When a searched source genuinely did not contain a requested item, `CHECK_POLICY` treated an honest "not found in source" answer as `missing`/`unsupported`/`uncertain`.

## Technical Details

### Files Modified

- `application/single_app/functions_task_completeness.py`:
  - Updated `CHECK_POLICY` and `CORRECTION_POLICY` to recognize authorized `saved_memory` and `conversation_history`, require top-level `evidence` keys in `evidence_refs`, require contiguous verbatim substrings in `answer_quote`, and accept evidence-backed "not found in searched source" answers (with page/source coverage and inspected content evidence) as `"satisfied"`.
  - Updated `normalize_assessment()` with `_resolve_evidence_refs()` and `_resolve_answer_quote()` to resolve nested evidence identifiers/citations to their owning top-level `evidence` keys and validate multi-part, normalized, and negative-constraint quotes while still rejecting hallucinated references and quotes.
- `application/single_app/functions_orchestration_composition.py` and `application/single_app/functions_orchestration_deliverables.py`:
  - Passed `saved_memory`, `conversation_history`, `CONVERSATION_POLICY`, deliverable guidance, and visual guidance to `check_and_correct()` in `adapter_compose()`.
  - Updated `KNOWLEDGE_POLICIES` and `compose_deliverable_guidance()` to instruct `compose` to report searched source/page inspection counts and coverage evidence when requested information is absent from sources.
- `application/single_app/functions_fact_memory_context.py`:
  - Updated `_select_scoped_memory_candidates()` so scoped memory groups (`len(member_id_sets) > 1`, conditional prefix/markers, or conflicting query identifier stems) never leak into unmatched conversations via fallback.
- `application/single_app/functions_source_review.py`, `application/single_app/functions_orchestration_adapters.py`, and `application/single_app/functions_orchestration_result_runtime.py`:
  - Added `"application/pdf"` to `SAFE_CONTENT_TYPES` and implemented `extract_source_review_evidence_from_pdf()` using PyMuPDF with `[Page X of Y]` extraction, `pdf_page_count`, `pdf_pages_reviewed`, and a compact coverage summary.
  - Surfaced PDF page inspection counts and skipped-URL notes in `_notes_from_source_review()` and `run_url_fetch()`, and added `pages_in_returned_excerpts` to `retain_document_search_result()`.
- `application/single_app/config.py`:
  - Bumped `VERSION` to `0.261.384`.

## Validation

- Added regression tests in `functional_tests/test_task_completeness_engine.py` and `functional_tests/test_task_completeness_runtime.py`.
- Verified `test_task_completeness_engine.py`, `test_task_completeness_runtime.py`, `test_fact_memory_profile_and_mini_sk.py`, `test_orchestration_request_memory_resolution.py`, `test_source_review_security.py`, `test_orchestration_deep_research.py`, `test_orchestration_search_result_integrity.py`, and `test_orchestration_compose_output_retry.py`.
