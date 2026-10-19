# SQL connection diagnostics fix - v0.261.353

## Issue and root cause

FED-16 stopped at the action editor's SQL connection check. The server recorded
HTTP 400 and `InterfaceError`, but those facts did not explain why the database
connection failed. The editor discarded structured SQL diagnostics, while
classic callers and runtime plugins could expose raw provider exception text.
Adding fields at the call site alone was insufficient: the logging boundary
normally reduces unapproved string properties to their lengths.

**Fixed in version: 0.261.351**, recorded in
`application/single_app/config.py`.

The base-branch integration preserves its saved-memory diagnostics and advances
the application from **0.261.350** to **0.261.351**. SQL implementation-version
references were updated from the initial branch-only **0.261.349**.

This fixes the diagnostic gap, **not the unresolved cause of FED-16's live
connection failure**. Successful SQL access using an operator's account does not
qualify the App Service identity's connection. No deployment or live connection
retry was performed for this fix.

### Cosmos review integration - v0.261.352

PR #1787's SQL route edit changed `route_backend_plugins.py`'s module fingerprint.
The Cosmos contract check therefore invalidated its three source-only reviews:
`set_user_plugins`, `edit_plugin`, and `test_cosmos_connection`. Their function
bodies and Cosmos behavior were unchanged, but the inventory intentionally binds
reviews to the entire owning module.

**Fixed in version: 0.261.352**, recorded in `application/single_app/config.py`.
The reviewed inventory now links each owner to its own runtime regression and
removes only these three stale source-review baseline entries. No gate, baseline
assurance, or production Cosmos behavior was relaxed.

`functional_tests/test_plugin_routes_cosmos_contract.py` executes the real
handlers and legacy-update validator with installed-SDK `CosmosDict` point
responses. It covers successful personal/global updates, exact-ID and personal
partition misses, global name mismatches, ETag preservation, and lazy Cosmos
query consumption including empty results and request-charge headers. External
services are offline seams; the contract runner blocks network access before
collection.

Validation for **0.261.352**, using a repository-local Python environment with
the declared application/test pins and without changing shared Python packages:

- `python scripts/check_cosmos_response_boundaries.py --run-contracts`:
  **1,151 passed and 244 subtests passed**; **1,067 owners, 412 doubles, zero
  review gaps**. The runner automatically includes all three new owner selectors.
- New plugin-owner regressions: **8 passed** with Flask **3.1.3** and Cosmos SDK
  **4.9.0**; SQL diagnostics regressions: **106 passed**.
- Optimized new owner and SQL classifier selection: **46 passed**. Required
  operations remain outside assertions; optimized execution is not treated as
  proof of assertion coverage.
- Route policy checks: **15/15**, **10/10**, and **3/3** passed; documentation
  coverage and quality: **7/7** and **6/6** passed.

### CodeQL test-local initialization follow-up - v0.261.353

CodeQL `py/uninitialized-local-variable` flagged `stored` in the personal/global
SDK response tests (alerts 4846 and 4847). The existing success guards implied
that a record had been created, but the local bindings were conditional.
Both tests now initialize `stored` before that condition and assert the SDK
response type on successful updates before comparing ETags. Missing-record and
mismatched-owner/name cases retain all refusal assertions.

**Fixed in version: 0.261.353**, recorded in `application/single_app/config.py`.
No production handler, Cosmos review evidence, test selector, assertion policy,
or CI configuration changed.

The guarded owner/SQL regression selection passed **114 cases**; its optimized
owner/classifier selection passed **46 cases**. Cosmos inventory validation
reported **1,067 owners, 412 doubles, zero review gaps**, and documentation
coverage/quality checks passed **7/7** and **6/6**. These local results do not
replace the new commit's CodeQL analysis.

## Technical details

### Shared connection boundary

`semantic_kernel_plugins/sql_connection_diagnostics.py` is a standard-library-only
classifier. It imports no application configuration, SQL driver, or Azure client
and performs no I/O.

It normalizes Azure SQL aliases to SQL Server and reads validated SQLSTATE,
PostgreSQL `pgcode`/`sqlstate`, MySQL numeric error arguments, and SQLite error
codes when available. ODBC native numbers are accepted only from the bounded,
SQLSTATE-prefixed `SQLDriverConnect`/`SQLConnect` diagnostic format, not arbitrary
numbers found in exception messages.

The four application-owned categories are `sql_connection_failed`,
`sql_driver_unavailable`, `sql_connection_timeout`, and
`sql_authentication_failed`. See the
[SQL action troubleshooting reference](../../reference/actions/sql-query.md#connection-failure-categories)
for their meaning. An `InterfaceError` alone stays general; SQLSTATE class `08`
does not establish a firewall, TLS, or identity cause.

`route_backend_plugins.py::test_sql_connection` returns static error guidance and
an additive `error_code`, preserving HTTP 400, `success: false`, and `error`.
Classic and editor requests use the same provider-error boundary.

`sql_query_plugin.py` and `sql_schema_plugin.py` log the same diagnostic at
connection creation and raise a safe `SqlConnectionError` with raw exception
context suppressed in formatted tracebacks. Existing outer handlers therefore
receive static text rather than raw connection errors. Query, scalar,
question/query, and complete-schema failure results add `error_code`; the other
schema methods propagate the safe exception.

### Operator telemetry and privacy

`functions_appinsights.py` validates the new SQL fields before retaining them in
log records. `[SQL_CONNECTION]` warnings do not require debug logging; exporting
them still requires Application Insights to be configured.

| Property on the log record | Content |
| --- | --- |
| `sc_failure_code` | Static application-owned failure category |
| `sc_sql_engine` | Allowlisted, normalized engine |
| `sc_error_type` | Known exception class name, or `Exception` |
| `sc_operation` | Connection test, query connection, or schema connection |
| `sc_sqlstate` | Validated five-character provider SQLSTATE, if available |
| `sc_sql_native_error` | Bounded integer native error number, if available |

Raw provider messages, credentials, connection strings, SQL, server/database
names, and identity/workspace identifiers are not added to this diagnostic.
Malformed or unsupported structured fields are omitted. Provider codes stay out
of browser JSON and plugin connection-failure results. The existing telemetry
operation correlation is retained; see the
[logging reference](../../reference/logging-tags.md#sql-connection-diagnostics)
for a request-correlated Log Analytics query.

### Compatibility and files

Authentication selection, reusable-identity authorization/hydration, driver
inputs, connection timeouts, successful connection caching, and successful
response shapes remain unchanged. The existing bounded Driver 17-to-18
missing-driver fallback is unchanged; no new retries, permissions, TLS changes,
or connection/authentication repairs were introduced.

The SQL action references and logging-tag inventory document the new behavior.
`scripts/build_docs_inventory.py` excludes the diagnostic helper as plugin
infrastructure, alongside the existing ODBC helper. Regenerating the inventory
leaves the user-facing action count unchanged.

The existing `test_workspace_authoring_backend.py` fixture loads the new
production dependency for its extracted routes. No federal harness source,
workflow, selector, acceptance rule, or unrelated fixture defect was repaired.
Harness findings are retained separately in session artifacts.

## Testing and validation

`functional_tests/test_sql_connection_diagnostics.py` covers evidence-based
classification, malformed/oversized/nested inputs, conservative unknown errors,
inventory exclusion, and fresh-process imports with external dependencies and
network access blocked. Its subprocess probe explicitly checks required
operations in normal and optimized Python.

`functional_tests/test_sql_connection_diagnostics_runtime.py` runs actual plugin
classes, ODBC helpers, extracted Flask handlers, and the real logging boundary
against isolated external I/O seams. Coverage includes provider failure privacy,
debug on/off, classic/editor and new/saved requests, scoped identities and
denials, success responses, authentication inputs, timeout caps, connection
caching, and unchanged fallback bounds.

Validation results:

- Combined focused diagnostics and existing SQL compatibility run: **114 passed**
  (106 diagnostic tests and eight existing compatibility cases).
- Optimized classifier run: **38 passed**, including the explicit subprocess
  probe; optimized execution alone is not treated as proof of assertion coverage.
- Driver/logging compatibility selection: **16 passed**, with one confirmed
  pre-existing debug-log expectation failure. Loading the unchanged `HEAD`
  logger reproduced that failure.
- Route-policy scripts: **15/15**, **10/10**, and **3/3** passed.
- Regenerated documentation inventory/coverage: **7/7** passed; documentation
  site source-quality checks: **6/6** passed.
- The repository-wide logging-tag check remains failing on unrelated existing
  mixed-case tags and inventory drift. All tags in modified product files are
  normalized, and `[SQL_CONNECTION]` is documented.

After integrating base version **0.261.350**, the 114 focused SQL cases, 38
optimized cases, and 13 documentation checks passed again. Additional inherited
saved-memory validation reached ten passing cases and five passing subtests, but
47 cases could not set up because the shared Python installation's OpenSSL dependency lacks
`lib.GEN_EMAIL`, the environment limitation already noted in the base fix.
No shared packages, inherited memory code, or assertions were changed to bypass it.

The original live FED-16 acceptance outcome remains unqualified. A separately
approved deployment and observed connection check are needed to obtain the
missing provider evidence before selecting a connection fix.
