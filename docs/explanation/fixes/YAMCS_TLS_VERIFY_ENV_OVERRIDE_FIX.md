# Yamcs TLS Verification Setting Fix (v0.261.062)

Fixed/Implemented in version: **0.261.062**

Related configuration update: `application\single_app\config.py` increments
`VERSION` from `0.261.061` to `0.261.062`.

Related issue: [#1934](https://github.com/microsoft/simplechat/issues/1934).

## Issue

The Yamcs action could still verify server certificates when **Verify TLS** was
explicitly disabled. Both **Test Yamcs Connection** and agent action requests
were affected when the process specified an environment CA bundle.

This fix makes the existing action setting behave consistently. It does not add
certificate-management features or change the deployment's trusted certificates.

## Root cause

The Yamcs SDK sets `requests.Session.verify`, but normally omits `verify` on
individual requests. Requests merges `REQUESTS_CA_BUNDLE`, or fallback
`CURL_CA_BUNDLE`, into an unspecified request-level setting. That request-level
bundle then takes precedence over `session.verify=False`.

The standard SimpleChat container already specifies `REQUESTS_CA_BUNDLE`, making
the interaction relevant to normal deployments. This Requests behavior predates
2.33.1; the dependency version is not changed.

SimpleChat's existing wrappers supplied only a timeout, and were installed after
`YamcsClient` construction. Username/password login happens during construction,
so changing only those post-construction wrappers would still miss initial login.

## Technical details

The plugin and connection-test route now supply the configured `verify` as a
request default alongside the timeout. `setdefault` preserves an explicit
request-level verification value or timeout.

The shared `wrap_yamcs_login_credentials()` adapter installs the caller's request
wrapper before delegating SDK login. It returns the SDK's real credentials, so
token state, authentication headers, and renewal continue to use the same
configured session. A failed login closes that session and re-raises the error.
Clients without credentials receive the wrapper immediately after construction.

### Files modified

- `application\single_app\functions_yamcs_operations.py`: shared pre-login adapter.
- `application\single_app\semantic_kernel_plugins\yamcs_plugin.py`: runtime TLS
  default and early session configuration.
- `application\single_app\route_backend_plugins.py`: matching connection-test policy.
- `functional_tests\test_yamcs_tls_verify.py`: real SDK/Requests regression coverage
  with intercepted transport.
- Existing Yamcs functional tests: SDK-faithful credential-login doubles and
  current-version headers.
- Yamcs action reference and feature documentation, release notes, and `config.py`.

### Behavior and impact

| Configuration | Before | After |
| --- | --- | --- |
| Verification disabled; environment CA bundle present | Bundle could override the session setting | Requests receive explicit `verify=False` |
| Verification enabled or omitted | Certificates verified using the configured/default trust | Same secure default and environment CA resolution |
| Username/password login | Occurred before SimpleChat's request wrapper | Uses the configured TLS default and timeout |
| Token renewal | Used the client's existing session settings | Retains the same configured request policy |
| Explicit per-request verification/timeout | Caller override accepted | Caller override still accepted |

No Flask route, authorization policy, credential storage, read-only operation, or
retrieval limit is added or changed. Verification errors are not retried with
verification disabled.

## Validation

The new suite produced **27 failing subcases on unpatched main**, identifying
ignored TLS defaults, unbounded constructor-time login, and failed-login session
cleanup. After the fix:

- `python .\functional_tests\test_yamcs_tls_verify.py`: **6 tests passed**.
- `python -O .\functional_tests\test_yamcs_tls_verify.py`: **6 tests passed**.
- `python .\functional_tests\test_yamcs_action_plugin.py`: **14 tests passed**.
- `python .\functional_tests\test_yamcs_basic_auth.py`: **12 tests passed**.
- Route Blueprint inventory, unauthenticated-policy, and policy-coverage suites:
  **6, 4, and 2 tests passed**, respectively.
- `python .\functional_tests\test_docs_app_surface_coverage.py`: **7 checks passed**;
  the generated application-surface inventory remains current.
- `python .\functional_tests\test_docs_site_quality.py`: **6 checks passed**.
- Python compilation of the changed application/test modules and Git whitespace
  validation passed.

Coverage includes both CA environment variables, their precedence and absence,
secure defaults, runtime and Flask connection-test requests, constructor-time
login, token renewal, API key/bearer/proxy Basic authentication, explicit
request overrides, environment proxy behavior, and failed-login cleanup.

Tests execute the real plugin/route bodies and pinned SDK request behavior with
HTTP transport intercepted. Route policy is checked separately; the isolated
behavior harness is not an application import-lifecycle test.

## Existing certificate support

The [existing container CA workflow](../../guides/docker-customization.md#custom-certificate-authorities)
remains unchanged. Production can keep verification enabled with approved
organization certificates in its deployed trust bundle. Disabling verification
weakens server identity checks and should only be an explicit diagnostic choice.

No organization certificate installation or live telemetry-server access was
performed for this fix. A deployed retest can confirm the action setting; repair
of a deployment's certificate trust chain is separate work.

## Related documentation

- [Yamcs action reference](../../reference/actions/yamcs.md)
- [Yamcs action feature](../features/YAMCS_ACTION.md)
