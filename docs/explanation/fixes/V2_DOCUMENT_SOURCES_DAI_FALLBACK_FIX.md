# V2 Document Sources DAI Fallback Fix

## Version and issue

Fixed/Implemented in version: **0.261.404**.
The application version advances from `0.261.403` to `0.261.404` in
`application/single_app/config.py`. No deployer or dependency changes are required.

The beta V2 chat **Document sources** picker could not load its workspace
directory or document rows. `GET /api/v2/document-sources?query=` returned
HTTP 503 with the safe message "Could not load document sources. Please retry."

## Root cause and evidence

Application Insights and App Service console logs recorded six matching requests
between November 5, 2026, 03:44:08 and 03:45:46 UTC. Every captured exception was
`CosmosHttpResponseError`, not the previously corrected `ImportError`. The
traceback reached the document-count query in
`functions_document_source_discovery.discover_document_sources()`. Cosmos
rejected its query plan with:

```text
Query contained NonValueAggregate, which the calling client does not support.
Query contained GroupBy, which the calling client does not support.
```

The workspace-sidebar implementation in
[#1870](https://github.com/microsoft/simplechat/pull/1870) added a new discovery
path rather than reusing the existing Document Access Index (DAI). It queried
the personal, group, and public source containers directly and used grouped
counts, including a separate grouped query for shared group documents.

The [container import fix](V2_DOCUMENT_SOURCES_CONTAINER_IMPORT_FIX.md) in
[#1883](https://github.com/microsoft/simplechat/pull/1883) corrected a real wiring
error but did not change this query path. The earlier DAI-first endpoints were
still intact; the new picker had bypassed them.

The pinned `azure-cosmos==4.9.0` client cannot execute these cross-partition
grouped queries. Current upstream Python SDK documentation also lists GROUP BY
as unsupported. Replacing the DAI with raw source reads or blindly upgrading the
SDK would not restore the intended architecture.

The former test doubles returned fabricated GROUP BY results. Applying the
existing Cosmos query compatibility guard made the real registered route
reproduce HTTP 503 in both normal and optimized Python.

## Implementation

`functions_document_source_discovery.py` now uses
`query_document_access_index_documents()` for each enabled, authorized source
kind. The DAI owner retains its existing schema/backfill readiness checks,
repair-backlog gates, metrics, projection conversion, Redis read-through cache,
and scope-version invalidation.

- A successful indexed read is used even when it contains no documents.
- A readiness or query failure falls back only for the affected source kind.
  The fallback reads metadata from `documents`, `group_documents`, or
  `public_documents` using parameterized ownership/approved-share predicates.
- No discovery path uses GROUP BY, grouped COUNT, or a bounded preview catalog.
  All eligible scopes and current document candidates remain available before
  application-side filtering and pagination.
- Both paths use the same current-revision, approved-access,
  pending-publication, matching, counting, sorting, and tag-shaping pipeline.
  Duplicate share references do not duplicate a document within a workspace.
- Live authoritative metadata is read for returned page candidates, using the
  explicit personal/group/public scope. Revoked or wrong-scope candidates are
  omitted; screening-held documents retain their safe unavailable summary.
  Picker payloads remain restricted to document display fields, not source
  ownership or sharing records.
- Pagination advances over consumed candidates when live revalidation removes
  a stale item, preventing retry loops at the same offset.
- If the required source fallback also fails, the route retains its safe HTTP
  503 and server-side traceback logging. It does not pretend a failed lookup
  was a successful empty or complete result.

DAI candidate rows are not permission grants or screening clearance. In
particular, the DAI list owner includes pending share candidates for approval
interfaces and does not project the full live screening record. Discovery
therefore applies approved-source rules and authoritative page refresh rather
than serializing the indexed rows directly.

## Files and compatibility

Production changes are limited to
`application/single_app/functions_document_source_discovery.py` and the
application version. Functional coverage is extended in
`test_v2_document_source_selection.py` and
`test_v2_document_source_discovery_imports.py`.
`functional_tests/cosmos_response_boundaries.json` records the reviewed source
query boundary and real-owner evidence; the removed inline aggregate boundary
is no longer part of the inventory.

The picker layout and API contract remain unchanged. Workspace-name,
filename/title, and tag matching still narrow both columns together; matching
a workspace name includes that workspace's files. Workspace and document pages
remain independent. Conversation locks, feature gates, personal file-sharing
settings, and approved group shares continue to constrain the candidate set.

No new settings, index schema, manual backfill, cache layer, browser asset,
frontend route, or JavaScript change is introduced.

## Validation

The real-owner cold-process regression runs both import orders under normal and
optimized Python, with external network access blocked. It uses the actual
configuration, DAI readiness/cache owner, source-authority reader, public
screening projection, Flask decorators, and registered route. Source point
responses use the installed SDK's `CosmosDict` through the existing offline
bootstrap fixture.

Coverage includes ready/empty indexes; incomplete or mismatched backfill; repair
backlog; mixed per-kind readiness; index-query failure; Redis hits, outages and
scope invalidation; live share revocation; deleted candidates with same-ID
documents in another container; safe held metadata; and explicit both-path
failure. Query doubles reject unsupported SQL before returning rows.

Selection regressions cover 65 group workspaces, 1,105 documents, independent
pagination, additive scopes, pending/deleted/superseded exclusions, duplicate
shares, matching tags, and feature/conversation-lock boundaries.

With `PYTHONDONTWRITEBYTECODE=1` and the application/functional-test directories
on `PYTHONPATH`, the final focused command is:

```powershell
python -B -m pytest -p no:cacheprovider -p test_support.cosmos_network_guard functional_tests\test_v2_document_source_selection.py functional_tests\test_v2_document_source_discovery_imports.py functional_tests\test_v2_document_source_runtime.py functional_tests\test_cosmos_wave5a_document_access_read_switch.py functional_tests\test_public_chat_document_list_pending_artifacts.py functional_tests\test_content_screening_read_boundaries.py -q --disable-warnings --tb=short
```

Result: **103 passed**, plus **10 subtests passed**. This includes all four
normal/optimized, configuration/discovery import-order probes.

Additional recorded checks:

| Command | Result |
| --- | --- |
| `python -B functional_tests\route_tests\test_route_blueprint_policy_inventory.py` | 15 passed |
| `python -B functional_tests\route_tests\test_route_unauthenticated_policy_contract.py` | 10 passed |
| `python -B functional_tests\route_tests\test_route_policy_test_coverage.py` | 3 passed |
| `python -B functional_tests\test_docs_app_surface_coverage.py` | 7 checks passed; inventory current |
| `python -B functional_tests\test_docs_site_quality.py` | 6 checks passed |
| `python -B scripts\check_cosmos_response_boundaries.py` | 1,085 owners, 424 doubles, zero review gaps |
| `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check` | Passed |

The broader `python -B scripts\check_cosmos_response_boundaries.py --run-contracts`
run is **not clean**: 1,735 passed, 188 failed, 12 errors, and 431 subtests passed.
None of the document-source selection, discovery-import, or runtime regressions
failed in that run. The largest failure group is the existing orchestration
harness suite; other failures include composition/citation and workflow-policy
tests.

Two representative failures were reproduced in fresh network-blocked processes
with both `config.py` and `functions_document_source_discovery.py` loaded from
unchanged HEAD, without replacing repository files:

- `test_orchestration_analysis_citation_delivery.py::test_native_citations_reach_model_saved_answer_and_done_frame[execute-document_analyze-findings]`
- `test_orchestration_harness_execution.py::test_authority_infrastructure_never_becomes_a_headless_denial[directory_service-True-direct-finalize]`

Both retain the same `model_failed` composition outcome. This verifies those
representative failures are not introduced by this discovery fix; it is not a
claim that every broad-suite failure has been individually diagnosed. Unrelated
orchestration behavior is deliberately unchanged.

The unchanged legacy Redis cache suite has a pre-existing validation limitation:
its `_succeeded_backfill_state()` fixture hardcodes schema version 2, while the
unchanged DAI owner requires schema version 3. Nine cases therefore report
`backfill_not_ready`. A separate in-memory diagnostic changing only that fixture
to the current schema passes all 12 cache cases; this is not reported as a pass
of the unmodified suite. Discovery's own real-owner cache regression seeds the
current schema and verifies the indexed cache path directly.

## Deployment and limitations

No live Azure configuration, service restart, index rebuild, manual backfill,
or deployment is included. The automated browser reached Microsoft Entra
sign-in, so this investigation does not claim an authenticated deployed success.

After deployment, verify an authenticated initial HTTP 200 response, workspace
and document/tag filtering, browsing, and pagination. Check DAI read/cache metrics
and confirm fresh requests no longer produce GroupBy/NonValueAggregate
exceptions in Application Insights.

Directory totals describe the indexed/source candidate snapshot. A concurrent
revocation, deletion, or metadata change can reduce the returned page after
live revalidation; consumed-candidate offsets still advance. Source containers
remain authoritative for returned metadata and later document use.
