# Bitbucket error-boundary exception ordering fix

Fixed/Implemented in version: **0.261.451**.
The application version is recorded in `application/single_app/config.py`.
Related pull request: [#1949](https://github.com/microsoft/simplechat/pull/1949).

## Issue and root cause

CodeQL reported `py/unreachable-except` in the new Bitbucket route boundary.
Python's `KeyError` inherits from `LookupError`, so the earlier unavailable-action
handler intercepted missing configuration keys before their intended invalid
configuration handler. Those errors returned HTTP 404 instead of HTTP 400.

## Technical details

`application/single_app/route_backend_bitbucket.py` now handles
`ValueError`, `TypeError` and `KeyError` before the broader `LookupError`
handler. The earlier `BitbucketError` handler still preserves domain-specific
status codes and safe messages. Other lookup failures and permission failures
still return HTTP 404; response privacy headers remain unchanged.

`functional_tests/test_bitbucket_routes.py` exercises six exception types
through the real Flask connection-status endpoint, checking status codes, safe
response bodies, `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.
The new missing-key case failed against the original handler order.

## Validation and separate follow-up

The network-blocked pytest selection passed **62 tests**, covering all three
Bitbucket backend suites and the Blueprint inventory, unauthenticated policy
and route-policy coverage suites. This includes the six error-mapping cases.

`python functional_tests\test_docs_app_surface_coverage.py` passed all seven
checks; `python functional_tests\test_docs_site_quality.py` passed all six.
`python scripts\check_swagger_routes.py application\single_app\route_backend_bitbucket.py`
passed for the changed route module. Python compilation and whitespace
validation also passed.

The original CI Cosmos failure is independent of this fix: the boundary
inventory reports 18 mismatches only in unchanged
`application/single_app/route_backend_orchestration.py`. Comparing the
implementation and its reviewed entries against PR base commit
`74d3bd035bdefb2f0dd51f361a075badcc3aaa0d` reproduces the same 18 mismatches.
Those entries require a separate owner review; this PR does not refresh or
approve unrelated fingerprint drift. A rerun alone will not repair it.
