# V1 Chat Page Bootstrap Fix

Fixed in version: **0.261.327**

Cosmos review follow-up implemented in version: **0.261.328** (PR #1755).

## Issue

The classic V1 chat page could return HTTP 500 when navigating to `/chats`,
before the composer or conversation list appeared. This affected nonempty
legacy GPT, API Management (APIM), and multi-endpoint model catalogs.

## Root Cause

A model-catalog import cleanup removed the `functions_model_capabilities`
import from `route_frontend_chats.py`. The V1-specific
`_build_initial_chat_model_selection()` helper still called
`resolve_model_reasoning_policy()` when serializing the initial model.

The `/chats` route invokes that helper before rendering `chats.html`, outside
the catalog-loading exception handlers. A nonempty catalog therefore raised
`NameError: name 'resolve_model_reasoning_policy' is not defined`.
An empty catalog returned `None` before reaching the missing dependency.

Existing initial-selection tests checked source snippets but did not execute
the helper or authenticated route, so they did not detect the regression.

## Changes

- `application/single_app/route_frontend_chats.py` explicitly imports the
  reasoning resolver again. Its module uses standard-library dependencies and
  the local capability catalog; the shared model-catalog extraction remains
  intact.
- `functional_tests/test_chat_v1_page_bootstrap.py` imports the real web app in
  fresh normal and optimized Python processes with external I/O blocked.
  It executes the real selector, catalog builder, authentication decorators,
  settings sanitizer, and templates.
- `application/single_app/config.py` advances the application version from
  `0.261.326` to `0.261.327`.

The fix does not change preferred model selection, legacy/APIM configured-first
ordering, deployment aliases, reasoning policies, security requirements, or
V2 routes. It does not catch the missing dependency or hide it by emptying the
model catalog.

## Validation

Before the import was restored, the new page regressions raised the missing
resolver `NameError` through the real authenticated `/chats` route in both
normal and optimized Python.

After the fix, cold and warm bootstrap paths render HTTP 200 for legacy, APIM,
multi-endpoint, and empty catalogs. Coverage also checks selected deployments,
canonical model names, supported/unsupported/unknown reasoning metadata,
preferred model ids and selection keys, stale preferences, catalog immutability,
and JSON serialization. Anonymous requests still redirect to login, users
without the required role receive HTTP 403, and test credentials/private
endpoint URLs do not appear in rendered HTML.

The following commands ran with an isolated Python runtime for application
integration tests; the route policy scripts also passed with the default
interpreter:

| Command | Result |
| --- | --- |
| `python -m pytest -q .\functional_tests\test_chat_v1_page_bootstrap.py .\functional_tests\test_chat_model_selector_initial_multiendpoint_bootstrap.py` | 7 passed, including the final run after the version update |
| `python -m pytest -q .\functional_tests\test_model_reasoning_capability_resolution.py .\functional_tests\test_chat_retry_import_boundaries.py` | 31 passed, including 64 passing subtests |
| `python -m pytest -q .\functional_tests\test_v2_ui_spa_route.py` | 6 passed |
| `python .\functional_tests\route_tests\test_route_blueprint_policy_inventory.py` | 15 passed |
| `python .\functional_tests\route_tests\test_route_unauthenticated_policy_contract.py` | 10 passed |
| `python .\functional_tests\route_tests\test_route_policy_test_coverage.py` | 3 passed |
| `python .\functional_tests\test_docs_app_surface_coverage.py` | 7 passed; generated inventory remains current |
| `python .\functional_tests\test_docs_site_quality.py` | 6 passed |
| `python -m pytest -q .\ui_tests\test_chat_page_multi_endpoint_notice_render.py .\ui_tests\test_staging_chat_smoke.py` | 2 skipped; an authenticated deployment test environment was not configured |
| `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check` | Passed |

The default local interpreter had an unrelated PyOpenSSL/cryptography
compatibility failure during Semantic Kernel imports. Integration checks used
a session-local virtual environment with the repository's Flask, Werkzeug,
and Semantic Kernel versions and a compatible TLS dependency. No shared
interpreter packages or production dependency manifests were changed.

The investigation also found an unrelated stale expectation in
`test_chat_template_json_bootstrap_safety.py`: it still requires the removed
multi-endpoint migration notice, while the notice-removal regression requires
its absence. That baseline failure is outside this fix.

## Cosmos Contract Review Follow-up

PR #1755's `cosmos-contracts` check failed with three
`Changed owners requires review` diagnostics for `_build_new_chat_conversation`,
`_resolve_chat_upload_context`, and `register_route_frontend_chats.upload_file`,
plus `Stale source-only owner review` and
`New/changed owner needs owner-runtime SDK evidence` for the upload context owner.

The gate fingerprints the entire module as well as each storage function.
Restoring the resolver import changed that module fingerprint, although all
three function bodies remained unchanged. Their base-commit boundaries matched
the committed inventory. This is a PR-caused review requirement, not a transient
runner failure or a defect in Cosmos mapping compatibility.

The inventory is refreshed and each consumer is reviewed. Both write owners
discard point-write responses; the upload context owner reads mapping fields
and returns the mapping without sending it to a strict plain-dictionary sink.
It remains `sdk-compatible`, now with fresh real-owner runtime evidence instead
of an expanded source-only baseline.

`functional_tests/test_chat_upload_cosmos_response_contract.py` uses the existing
SDK-default offline container and actual installed SDK `CosmosDict` responses.
Fresh normal and optimized web imports exercise an owned personal conversation,
cross-user denial without writes, new/missing conversation creation, retained
fields and ETags, and discarded upsert responses. No new Cosmos double,
production normalization, relaxed assertion, or CI configuration change is needed.
The follow-up advances `application/single_app/config.py` to `0.261.328`.

Follow-up validation uses the session-local interpreter with the application
pin `azure-cosmos==4.9.0`. An initial full run exposed an inherited local SDK
version mismatch (`4.16.3` versus `4.9.0`); only the virtual environment was
corrected. Dependency assertions, production pins, and CI configuration remain
unchanged.

| Command (session-local Python where applicable) | Result |
| --- | --- |
| `python -m pytest -q -p test_support.cosmos_network_guard .\functional_tests\test_cosmos_document_boundaries.py .\functional_tests\test_chat_upload_cosmos_response_contract.py .\functional_tests\test_chat_v1_page_bootstrap.py .\functional_tests\test_chat_model_selector_initial_multiendpoint_bootstrap.py --disable-warnings --tb=short` | 59 passed |
| `python .\scripts\check_cosmos_response_boundaries.py --run-contracts` | 1,051 owners, 394 doubles, zero review gaps; 683 passed and 231 subtests passed |
| `python .\functional_tests\test_docs_app_surface_coverage.py` | 7 passed; inventory remains current |
| `python .\functional_tests\test_docs_site_quality.py` | 6 passed |

## Deployment Verification

The missing import is reproduced and fixed locally. The supplied deployed
HTTP 500 screenshot did not include a server traceback, so the deployed
exception has not been independently matched to this regression.

After deploying the fixed build, verify authenticated V1 `/chats` navigation
and a complete send/response cycle with the configured model. Offline route
coverage does not establish that the deployed model service can complete a
chat request.
