# Graph Request Boundary Fix

Fixed/Implemented in version: **0.261.456**

## Issue description and root cause

The approved Graph remediation covers CodeQL `py/partial-ssrf` alerts
[1090](https://github.com/microsoft/simplechat/security/code-scanning/1090),
[1091](https://github.com/microsoft/simplechat/security/code-scanning/1091),
[1093](https://github.com/microsoft/simplechat/security/code-scanning/1093), and
[1094](https://github.com/microsoft/simplechat/security/code-scanning/1094).
Their scanner severity does not establish demonstrated critical exploits.
Existing profile relationships and workspace membership already authorize
several reported flows.

The original Development baseline was
`4dd6d80230fe60e3cbfe8544d1d52308a14a7387`, version `0.261.422`, Python analysis
`2117078539`, analysis key `.github/workflows/codeql.yml:analyze`, category
`/language:python`. Real prepared Requests URLs reproduced these missing
boundaries without live Graph or Azure calls:

| Finding | Before |
| --- | --- |
| 1090, OneDrive metadata | Absolute pagination links could select an off-origin destination; metadata requests followed redirects. |
| 1091, directory user | `quote()` retained slashes, so `../me` selected `/v1.0/me`. |
| 1093, public-workspace member | Raw interpolation turned a valid B2B `#EXT#` identifier into a fragment, truncating the HTTP target. |
| 1094, profile user | Existing `quote(..., safe="")` still left `.` unescaped, allowing Requests to normalize that segment to `/v1.0/users/`. |

OneDrive browse-path normalization and escaping were already present. The fix
adds a destination boundary rather than replacing those protections.

## Technical details

### URI construction and metadata requests

`get_graph_endpoint()` continues to derive the destination from the existing
`get_graph_base_url()` policy. It validates URI syntax and decoded traversal or
control segments while preserving escaped identifiers, filenames, and opaque
query tokens. Absolute metadata continuations require the configured origin and
API prefix; comparisons handle IDNA and equivalent default ports.

Commercial, Government, and configured custom origins remain supported,
including custom API prefixes and explicit private origins. No second origin
allowlist, UUID-only identifier restriction, or blanket public-IP rule is added.
UPN, B2B, Unicode, and safely escaped reserved or literal percent data remain
supported.

The OneDrive `_graph_get_json()` validates destinations before obtaining headers
or calling HTTP. Pagination supplies initial selection parameters only on the
first page; subsequent pages retain their own continuation query. Directory and
profile identifiers are escaped as individual components. The selected JSON
metadata helpers disable redirects and explicitly refuse 3xx responses.

OneDrive content downloads still follow legitimate redirects. Tests exercise
Requests' redirect handling, streamed contents and checksum, and removal of the
Authorization header on a cross-host content redirect.

### Authorization, failures, and storage

Profile relationship authorization still precedes both local profile reads and
Graph fallback. Self, Admin, shared-group, shared-document, and collaboration
relationships are unchanged. Workspace membership and management checks remain
before Graph enrichment, including fresh-copy checks inside guarded writers.

Invalid profile paths follow the existing not-found contract with structured
logging. Optional public-workspace enrichment retains its blank-label failure
contract but records failures using `log_event` and the existing `[USERS]` tag,
without printing identifiers or provider exception text.

Token acquisition, OAuth callbacks, login decorators, MSAL caches, Azure endpoint
policies, storage implementations, domain validators, and shared test harnesses
are unchanged. No deployment configuration or data migration is required.

The Cosmos inventory fingerprints entire modules, so the Graph helper edits also
invalidate reviews for unchanged storage consumers. Owned entries are reviewed
against the current base without overwriting sibling reviews or claiming a
storage defect. The two touched route modules have owner-runtime coverage using
the installed SDK's `CosmosDict` responses and plain query projections; ETags and
nested data are preserved.

### Files modified

- `application/single_app/functions_authentication.py`
- `application/single_app/functions_file_sync.py`
- `application/single_app/functions_simplechat_operations.py`
- `application/single_app/route_backend_public_workspaces.py`
- `application/single_app/route_backend_users.py`
- `application/single_app/config.py`
- `functional_tests/test_graph_request_boundaries.py`
- `functional_tests/test_graph_route_cosmos_response_contracts.py`
- `functional_tests/cosmos_response_boundaries.json`
- This document and the historical [File Sync endpoint validation fix](FILE_SYNC_SSRF_ENDPOINT_VALIDATION_FIX.md).

`application/single_app/config.py` advances the live-base application patch
version from `0.261.455` to `0.261.456`. Deployer files are unchanged.

## Testing and validation

The focused suites prepare real Requests URLs through an in-memory adapter and
block network access before collection. They cover destination refusal before
HTTP, identifiers and cloud compatibility, opaque OData queries and pagination,
metadata versus content redirects, existing authorization, and real-SDK owner
behavior.

```powershell
$env:PYTHONPATH = "$PWD\application\single_app;$PWD\functional_tests"
python -m pytest -q -p no:cacheprovider -p test_support.cosmos_network_guard `
    .\functional_tests\test_graph_request_boundaries.py `
    .\functional_tests\test_graph_route_cosmos_response_contracts.py `
    .\functional_tests\test_file_sync_ssrf_validation.py `
    .\functional_tests\test_file_sync_onedrive_personal.py `
    .\functional_tests\test_user_profile_idor_authorization.py `
    .\functional_tests\test_group_membership_apis.py `
    .\functional_tests\test_public_workspace_membership_writer_safety.py `
    .\functional_tests\test_user_search_hardening.py --tb=short --disable-warnings
```

Finalization against Development `21f2b9c8`, version `0.261.455`:

| Validation | Result |
| --- | --- |
| Eight-file focused command above | 576 passed |
| All runtime selectors for the 41 owned Cosmos reviews | 69 passed |
| Route blueprint / unauthenticated / coverage suites | 15/15, 10/10, and 5/5 passed |
| Diff-scoped access-control, XSS, Swagger, compilation, whitespace | Passed |
| Documentation site quality | 6/6 passed |
| `python .\scripts\check_cosmos_response_boundaries.py --run-contracts` | Blocked before runtime execution by 26 inherited review gaps: eight in `functions_settings.py` and 18 in `route_backend_orchestration.py`. |

The unmodified live base has 31 inventory gaps. The five profile-owner contexts
that this fix touches are re-reviewed with their existing current-base runtime
evidence retained and Graph-specific SDK coverage added. The remaining 26 entries
are outside this fix and are left unchanged; the full current-base Cosmos gate
is not claimed to pass.

The original scoped implementation passed 576 focused tests, all three route
policy suites, and the then-current Cosmos contracts (2,016 tests and 431
subtests). A separate three-way integration onto Development `2968e8e5`, version
`0.261.453`, passed 205 bounded request, authorization, and SDK-owner tests without
code or fixture adaptations. Final current-base commands and results are recorded
in the pull request; historical results do not imply that inherited current-base
inventory or runtime failures are resolved.

### Local CodeQL evidence and limits

The unchanged official `py/partial-ssrf` query was run against separate complete
original-baseline and corrected snapshots. CodeQL `2.27.4`,
`codeql/python-queries` `1.9.0`, and `codeql/python-all` `7.2.9` match the
published baseline. Query SHA256:
`799f1218d22381ff7257e7cb3bc8f0cc4480208de3169ecb0cde2618031f69f6`.

All four selected baseline sinks reproduced at their exact original locations,
with four code flows each. The corrected snapshot had no `py/partial-ssrf`
result anywhere in the five owned Graph modules. The total result count changed
from six to two; the remaining two were outside the selected scope and were not
investigated or changed.

No local analyses were uploaded. This historical local comparison is not a
GitHub alert-state change: confirmation requires the final PR-ref Python analysis
with `.github/workflows/codeql.yml:analyze` and `/language:python`. No dismissal,
suppression, query/configuration change, severity change, or vendor exclusion is
included.
