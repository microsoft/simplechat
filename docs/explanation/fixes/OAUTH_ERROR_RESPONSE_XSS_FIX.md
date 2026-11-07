# OAuth callback error response fix

Implemented in version: **0.261.423**

The application version is tracked in `application/single_app/config.py`.
This change advances only its third segment from `0.261.422` to `0.261.423`.

## Issue and root cause

The ordinary provider-error branches of `/getAToken` and `/getATokenApi`
interpolated the callback's `error` and `error_description` query parameters
into a returned Python string. Flask treated that string as HTML, so hostile
provider parameters crossed directly into an HTML response. Both branches
already used HTTP 400; the problem was the response's content and media type.

This is the bounded correction for the two selected `py/reflective-xss`
instances in `route_frontend_authentication.py`. The Development baseline was
`4dd6d80230fe60e3cbfe8544d1d52308a14a7387`, version `0.261.422`; Python CodeQL
analysis `2117078539` used `.github/workflows/codeql.yml:analyze` and category
`/language:python`. No new issue or changes to scanning configuration are part
of this fix.

Historical, non-closing reference: [#1903](https://github.com/microsoft/simplechat/pull/1903),
which supplied that Development integration baseline.

## Implementation

### Response and diagnostic boundary

Both ordinary callback error branches now use `_oauth_login_error_response()`.
It returns an explicit Flask `Response` with:

| Property | Value |
| --- | --- |
| Status | HTTP 400 |
| Content-Type | `text/plain; charset=utf-8` |
| Body | `Login failed. Please try signing in again.` |

Neither provider parameter is included in the response. The existing
`[AUTH_CALLBACK]` logging tag records a warning with the callback path, a
recognized OAuth/OIDC diagnostic code, and whether a description was present.
Unrecognized codes are recorded as `unrecognized_error`; raw descriptions,
arbitrary error text, authorization codes, tokens, and query strings are not
logged by this helper. This replaces the two raw provider-error `print` calls
without losing safe failure diagnostics.

### Preserved callback behavior

The `/getAToken` Microsoft 365 chat and workflow prefix checks still precede
the ordinary login-error branch. Their existing completion helpers remain
responsible for state, session binding, nonce, account checks, popup/page
completion, and independent credentials without replacing the app principal.

A missing authorization code still redirects `/getAToken` to the public
sign-in entry point. `/getATokenApi` retains its separate missing-code HTTP 400
response. Missing or empty `error` values do not activate the new helper.
Successful application login, API token exchange, and Teams OBO session
creation retain their existing contracts.

No shared authentication/cache helper, Microsoft 365 implementation, app
security-header hook, CSP setting, browser asset, or deployer was changed.
`config.py` changes only the application version. The coordinator-assigned
release-note entry and regenerated split pages use the same `0.261.423` version;
this documentation-only addition does not advance the version again.

### Files changed

| File | Change |
| --- | --- |
| `application/single_app/route_frontend_authentication.py` | Shared fixed-text error response and safe diagnostic logging for the two selected branches. |
| `application/single_app/config.py` | Application patch version `0.261.423`. |
| `functional_tests/test_oauth_error_responses.py` | Real Flask HTTP regressions plus sign-in, Teams, and real MSAL-backed Microsoft 365 callback compatibility checks. |
| `functional_tests/test_m365_routes.py` | Minimal repair of an existing notification fixture's stale group-helper imports; current version header. |
| `docs/explanation/fixes/OAUTH_ERROR_RESPONSE_XSS_FIX.md` | Root cause, response contract, scope, and validation evidence. |
| `docs/explanation/release_notes.md` | Concise Bug Fix entry under `v0.261.423`, with the historical non-closing reference. |
| `docs/explanation/release-notes/*.md` | Regenerated split release pages derived from the release-note source. |

## Validation

### Before the fix

The new HTTP suite was run against the unchanged production callbacks. All
ten provider-error cases failed because the actual responses declared
`text/html; charset=utf-8`, rather than the required plain-text media type.
The other 23 runtime cases passed, covering missing-code behavior, successful
login/API callbacks, Teams, and Microsoft 365 prefix and guard behavior.

The original four-selector offline baseline separately reported 116 passed
and one failure. The failure was
`M365RouteTests.test_real_notification_helper_only_targets_subject_and_deduplicates`:
its scoped `functions_group` stub did not export `assert_group_role` and
`get_user_groups`, which the notification module now imports. The approved
test-only repair represents the fixture's no-group scenario with a rejecting
role check and an empty membership list, and asserts neither helper is called.
All existing notification subject, personal-scope, deduplication, status, and
fault-injection assertions are retained. Production notifications and
authorization were not modified.

### Regression coverage and execution

The HTTP suite uses the entire registered callback module, not AST-extracted
callback functions. It covers hostile markup and quotes in both provider
parameters, missing descriptions, sensitive-looking text, error precedence
over an authorization code, safe logging, and unchanged session contents.

Microsoft 365 cases reuse the existing connection fixtures and
`test_support.m365` clock and SDK-default Cosmos doubles. They execute real
MSAL state/nonce and account validation, real AES-GCM workflow storage, and
both page and popup completion through `/getAToken`. The Cosmos network-guard
plugin blocks external socket/DNS access before collection.

These are offline Flask runtime fixtures, not live Azure, Graph, full-app
bootstrap, or Azure Playwright browser validation. The response's fixed body
and declared plain-text media type are checked at the HTTP boundary. No
resources were provisioned and no authentication settings were changed.

Run the focused selection with Windows `PYTHONPATH` configured:

```powershell
$env:PYTHONPATH = "$PWD\application\single_app;$PWD\functional_tests"
python -m pytest -q -p test_support.cosmos_network_guard functional_tests\test_getatoken_missing_code_redirect.py functional_tests\test_m365_routes.py functional_tests\test_m365_connections.py functional_tests\test_m365_chat_connection_persistence.py functional_tests\test_oauth_error_responses.py
```

After the callback correction and approved fixture repair, this selection
passed: **150 tests and 119 subtests**, including all 33 new HTTP runtime
cases. The ten previously failing provider-error cases now return the fixed
body in `text/plain; charset=utf-8` with HTTP 400 and safe diagnostics.

| Additional command | Result |
| --- | --- |
| `python .\scripts\check_swagger_routes.py .\application\single_app\route_frontend_authentication.py .\application\single_app\config.py` | Passed; one changed route file validated. |
| `python .\functional_tests\route_tests\test_route_blueprint_policy_inventory.py` | 15/15 passed. |
| `python .\functional_tests\route_tests\test_route_unauthenticated_policy_contract.py` | 10/10 passed. |
| `python .\functional_tests\route_tests\test_route_policy_test_coverage.py` | 3/3 passed. |
| `python .\functional_tests\test_docs_app_surface_coverage.py` | 7/7 passed; the committed inventory remains current. |
| `python .\functional_tests\test_docs_site_quality.py` | 6/6 source-site checks passed; no built-site validation was performed. |
| `python -m py_compile .\application\single_app\route_frontend_authentication.py .\application\single_app\config.py .\functional_tests\test_oauth_error_responses.py .\functional_tests\test_m365_routes.py` | Passed. |
| `python .\scripts\build_release_notes_pages.py` | Regenerated 15 pages while preserving all 317 source release sections. |
| `python .\scripts\build_release_notes_pages.py --check` | Passed; split release pages are current. |
| `python .\scripts\build_latest_release_docs.py --check` | Passed; the independent app-driven Latest Features catalog is unchanged. |
| `python -m pytest -q -p test_support.cosmos_network_guard functional_tests\test_docs_release_notes_integrity.py functional_tests\test_docs_app_surface_coverage.py functional_tests\test_docs_site_quality.py functional_tests\test_docs_latest_release_catalog_parity.py functional_tests\test_docs_published_references.py::test_release_generation_rejects_source_relative_reader_links` | 21 passed after the assigned release-note/reference update. |

The initial PR scan also identified one redundant wrapper in the new test-only
settings seam. Using the identical `dict` callable directly removes that
`py/unnecessary-lambda` finding without changing production code or the 33
runtime cases. The full 150-test/119-subtest selection passed again after this
correction. Final exact-head CodeQL and CI evidence is recorded on the PR.

Route policy, Swagger, access-control, XSS diff guardrails, and the documentation
inventory/site checks are also required before the PR handoff. Fresh PR-ref
Python CodeQL evidence is distinct from final Development verification, which
can only occur after the user approves and merges the PR.
