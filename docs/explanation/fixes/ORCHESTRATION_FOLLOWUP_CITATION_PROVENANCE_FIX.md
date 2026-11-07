# Citation provenance in formatting-only follow-ups

Fixed/Implemented in version: **0.261.370**.

Application version: `application/single_app/config.py`.

## Issue and root cause

A document-backed answer could have working passage citations, but a later request
to reformat that answer could lose both its inline markers and saved citation
metadata. The text and numbers could still be correct.

Selected conversation history supplied text, not a retained-result binding.
A one-step Compose plan could therefore treat the transformation as general
knowledge with no named input. Composition's citation policy and persisted
upstream lineage operate on named inputs, while final delivery deliberately does
not collect unrelated sources from conversation history.

This was independently observed in FED-34. Its recorded numeric assertion failure
was a separate external-harness problem; that harness is not changed here.
The Search `evidence` handoff reported by FED-32 was already fixed in
**0.261.365**. The investigated site still reported **0.261.363**.

## Technical changes

`route_backend_orchestration.py` resolves selected messages through the existing
ownership, visibility, content-review and fingerprint checks, including complete
text when the planning snapshot contains only a discovery preview. For a
no-retrieval follow-up, retained-run discovery uses the selected assistant
message IDs, whether selected alone or alongside their user requests. Selecting
only a user request does not admit its unselected answer or neighboring runs.

`functions_orchestration_services.py::selected_conversation_results` associates a
selected assistant answer with its already-admitted final text result only when
the retained text matches the currently visible message. A stored result never
substitutes an unedited original for an edited or partially masked answer.
Existing workflow-result exclusions and owner/conversation/producer
authorization remain unchanged.

The server stores the association in the existing request-resolution context,
so conversational plan editing preserves it. Editing a no-retrieval plan also
honors that routing contract during candidate discovery rather than performing
another document search before revising the plan.

`functions_orchestration_planner.py` exposes that association and adds the
existing-result input to an otherwise input-free Compose transformation. It
chooses a source-based answer policy instead of unrelated general knowledge,
preserving an explicitly mixed source/general-knowledge policy. Plans that
already declare named inputs retain those bindings.

`functions_orchestration_composition.py` explains that transforming an earlier
answer preserves original attribution, not fresh verification. The existing
citation-copying policy, upstream-result storage, finalization and V2 viewer
deliver the actual source markers and metadata. No new citation grammar,
frontend control, storage schema or browser runtime asset is introduced.

## Behavior and boundaries

Ask naturally to turn an existing comparison into a table, shorten a sourced
answer, or rewrite it as a briefing note. A matching selected retained answer
provides the transformation input without another document search or analysis.
Its original citation lineage remains available through saved messages and
reload.

Retained-result access continues to follow the original owner's conversation
and producer authorization. It does not reread an uploaded source merely to
reformat earlier content, nor does it certify that the underlying source is
unchanged or independently verify an earlier AI claim. Opening the cited
document remains a separately authorized operation.

Edited answers without a matching retained result remain historical text;
source-free answers and citation-looking text pasted by a user do not acquire
document authority. Hidden or changed selected messages after planning prevent
execution through the existing context checks. Missing or deleted producers
cannot authorize a retained-result read.

## Testing and validation

The backend regressions in
`functional_tests/test_orchestration_followup_citation_provenance.py` use actual
planning routes, retained storage, Search/Compose execution and publication with
external I/O isolated. Coverage includes assistant-only and paired selections,
Search `evidence` and `prepared`, multiple documents, chained transformations,
unchanged source-retrieval counts, edited and masked messages, user-pasted
citation-like content, removed producers and delivery-only refresh.

`ui_tests/test_v2_followup_citations.py` uses the real published payload with the
bundled V2 interface and local synthetic API transport. It checks table content,
the exact passage opened for each document and saved-payload reload with enhanced
citations enabled and disabled. Backend bootstrap completes in a subprocess so
its offline network guard and event loop do not interfere with Playwright.

No production conversation, source document, external qualification harness or
deployment is modified by these tests.

### Results and reproducible commands

Use the pinned application dependencies, with `application\single_app` and
`functional_tests` on `PYTHONPATH`:

```powershell
python -m pytest -q -p no:cacheprovider -p test_support.cosmos_network_guard functional_tests\test_foundry_orchestration_polling_budget.py functional_tests\test_orchestration_followup_citation_provenance.py functional_tests\test_orchestration_search_citations.py functional_tests\test_orchestration_search_citation_delivery.py functional_tests\test_orchestration_conversation_sources.py functional_tests\test_orchestration_plan_revision_planner.py --disable-warnings --tb=short --show-capture=no
python -O -m pytest -q -p no:cacheprovider -p test_support.cosmos_network_guard functional_tests\test_foundry_orchestration_polling_budget.py functional_tests\test_orchestration_followup_citation_provenance.py --disable-warnings --tb=short --show-capture=no
```

Results: **115 passed, 3 subtests passed**, and **51 passed** respectively.
The follow-up module contributes **12** passing cases to both runs. Required
setup and operations are outside assertions; optimized pytest still rewrites
test assertions.

With the repository root also on `PYTHONPATH`, the browser command is:

```powershell
python -m pytest -q -p no:cacheprovider ui_tests\test_v2_followup_citations.py ui_tests\test_v2_search_citations.py ui_tests\test_v2_analysis_compare_citations.py --disable-warnings
```

Result: **8 passed**. This includes two new follow-up cases and six existing
Search/Analyze/Compare citation cases.

The three route-policy scripts pass **15/15**, **10/10** and **3/3** checks.
Documentation coverage and site quality pass **7/7** and **6/6** checks.

### Existing test limitations

The broader test selection is not entirely green. Four unchanged
`test_orchestration_services.py` cases expect uploaded-source rechecks on retained
results. They also fail when the untouched HEAD services module is loaded in a
fresh process. The actual retained-result owner deliberately authorizes retained
text through its conversation and producer instead; this fix does not change
that contract.

The existing dependency-citation checkpoint-child regression also fails with
`result_producer_unavailable`, as already documented by the earlier Search
citation fix. Legacy `PlanRevisionRouteTests` have a separate fixture-import
failure: their fake `config` omits `cosmos_settings_container`. The same import
failure was reproduced using the untouched HEAD route module. These fixtures
were not changed to mask the failures; the new editor regression uses the real
offline application bootstrap.

The reviewed Cosmos inventory reports **1,067 owners, 413 doubles and zero review
gaps**. The full `check_cosmos_response_boundaries.py --run-contracts` selection was
attempted but not completed: early unrelated credential tests exposed a missing
optional integration dependency in the validation environment. After restoring
the pinned `yamcs-client==2.1.0`, the affected credential selection passed
**40/40** cases. No full repository-suite pass is claimed.
