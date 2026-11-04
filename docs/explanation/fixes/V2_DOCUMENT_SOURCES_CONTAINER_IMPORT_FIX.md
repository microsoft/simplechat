# V2 Document Sources Container Import Fix

## Issue and root cause

The v2 chat **Document sources** picker displayed "Could not load document
sources. Please retry." instead of loading workspaces and documents. The initial
`GET /api/v2/document-sources?query=` returned HTTP 503.

The discovery function imported `cosmos_documents_container` from `config.py`.
That export does not exist: the personal-document container is configured as
`cosmos_user_documents_container`. Because the import is deferred until discovery
runs, application startup and unrelated pages could succeed while every source
directory request failed before querying documents.

On November 4, 2026, Application Insights and App Service console logs recorded
six matching 503 responses between 22:25:30 and 22:26:16 UTC on the beta App
Service. Structured error events identified `ImportError`. A fresh local process
using real configuration and network-blocked storage reproduced the missing
export exactly.

The previous selection tests did not catch this because their fake `config`
module supplied the same nonexistent export.

## Fixed in version: **0.261.400**

`application/single_app/config.py` advances the application version from
`0.261.399` to `0.261.400`. No deployment configuration or Cosmos container
definition changes are required.

## Technical details

- `application/single_app/functions_document_source_discovery.py` uses the
  existing `cosmos_user_documents_container` for personal documents. Runtime
  imports remain deferred; no compatibility alias or empty-result fallback is
  introduced.
- `application/single_app/route_backend_v2.py` requests exception tracebacks
  through the existing `log_event` failure path. The endpoint still returns its
  stable user-safe HTTP 503 message, not provider diagnostics.
- `functional_tests/test_v2_document_source_selection.py` uses the actual
  configuration export name in its fixture.
- `functional_tests/test_v2_document_source_discovery_imports.py` exercises real
  configuration, discovery, authorization decorators, public metadata projection,
  and route registration in fresh normal and optimized Python processes, with
  both configuration/discovery import orders. Only external storage I/O is
  replaced, and network access is blocked.
- `functional_tests/cosmos_response_boundaries.json` refreshes the discovery
  module's reviewed query boundaries and references the new runtime evidence.

Workspace eligibility, conversation locks, approved sharing, additive selection,
search predicates, source pagination, and screening-safe metadata projection are
unchanged. This is a backend wiring fix, not a picker redesign.

## Validation

Before the fix, the real-configuration probe reproduced the missing-container
import and the endpoint returned HTTP 503 even though all 18 existing selection
tests passed.

After the fix, the focused selection, retrieval/runtime, and cold-discovery
suites pass all 28 cases. The new probes verify initial HTTP 200 responses with
personal, group, and public documents, cross-workspace pagination, workspace
browsing and tags, and HTTP 503 with traceback logging for an injected storage
failure.

Validation commands and outcomes:

- `python -m pytest functional_tests\test_v2_document_source_selection.py functional_tests\test_v2_document_source_runtime.py functional_tests\test_v2_document_source_discovery_imports.py -q --disable-warnings --tb=short`:
  28 passed.
- The same suites with `-p test_support.cosmos_network_guard` and the application
  and functional-test directories on `PYTHONPATH`: 28 passed.
- `python functional_tests\route_tests\test_route_blueprint_policy_inventory.py`:
  15 passed.
- `python functional_tests\route_tests\test_route_unauthenticated_policy_contract.py`:
  10 passed.
- `python functional_tests\route_tests\test_route_policy_test_coverage.py`:
  3 passed.
- `python functional_tests\test_docs_site_quality.py`: 6 checks passed.
- `python scripts\check_cosmos_response_boundaries.py --run-contracts`: blocked
  before contract execution by 75 pre-existing stale owner reviews in the
  unchanged `functions_documents.py` and `route_backend_chats.py` modules.
  Discovery's three reviewed boundaries are current; unrelated inventory entries
  are deliberately not reclassified by this fix.

Production recovery requires deployment of the fixed application and a separate
authenticated check of initial loading, searching, browsing, and pagination.
The investigation and local validation do not establish that the currently
deployed beta application has recovered.
