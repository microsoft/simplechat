# Log Credential Key Redaction Fix

Fixed/Implemented in version: **0.250.217**

## Issue Description

CodeQL reported five high-severity `py/clear-text-logging-sensitive-data` alerts against the
shared logging sinks in `application/single_app/functions_appinsights.py`, plus two
`py/import-of-mutable-attribute` warnings in helper scripts.

The logging alerts were not false positives. `log_event` sanitizes its inputs before they reach
any sink, but the redaction decision for structured properties was made by
`_is_sensitive_log_key`, which matched a fixed list of substrings. Several credential field names
used by this codebase did not contain any of those substrings and were therefore logged in
clear text.

The most significant gap was **`auth_key`**, which is the field name the plugin/action
connection-test routes use for the caller-supplied secret, and the plugin manifest's
**`auth.key`**, which `plugin.schema.json` describes as holding "the secret value for the plugin
... such as a SQL connection string, a password for a service principal."

Reproduction before the fix:

```text
log_event("credential redaction probe", extra={"auth_key": "SuperSecretCredentialValue123"})
-> [LOG] credential redaction probe -- {'auth_key': 'SuperSecretCredentialValue123'}
```

## Root Cause Analysis

`_normalize_log_key` strips non-alphanumeric characters, so `auth_key`, `authKey`, and
`auth-key` all normalize to `authkey`. The `SENSITIVE_LOG_KEY_FRAGMENTS` tuple contained
`accountkey`, `apikey`, `privatekey`, and `subscriptionkey`, but not `authkey`, and no fragment
is a substring of `authkey`. The same was true for a property named exactly `key`, and for
`pwd`, `key_pair`, `master_key`, `primary_key`, `secondary_key`, `encryption_key`,
`signing_key`, `session_key`, and `storage_key`.

A value under one of these keys was only redacted by luck, when the value itself happened to
match `SECRET_ASSIGNMENT_RE` (for example a connection string containing `Password=`). A bare
API key or token under `auth_key` was emitted verbatim.

Eighteen credential key names were affected in total.

Widening the match to "any key containing `key`" was not acceptable, because it would redact
benign configuration such as `key_encoding`, `key_prefix_hints`, and `partition_key_path`,
removing diagnostic value from logs.

## Technical Details

Files modified:

* `application/single_app/functions_appinsights.py`
* `scripts/resolve_multiendpoint_gpt.py`
* `deployers/bicep/postconfig.py`
* `deployers/version.txt`
* `functional_tests/test_privacy_logging_telemetry_audit.py`
* `functional_tests/test_log_credential_key_redaction.py` (new)

Code changes summary:

* Added the missing credential fragments to `SENSITIVE_LOG_KEY_FRAGMENTS`: `authkey`,
  `encryptionkey`, `keypair`, `masterkey`, `primarykey`, `secondarykey`, `sessionkey`,
  `signingkey`, and `storagekey`.
* Added a new `SENSITIVE_LOG_KEY_EXACT` tuple for names that carry a credential only when they
  are the entire key: `key`, `keys`, `pass`, `passphrase`, `pwd`, `sig`, and `signature`.
  `_is_sensitive_log_key` now checks the fully normalized key against this tuple before falling
  back to substring matching. Matching these as substrings would have redacted `key_encoding`
  and `partition_key_path`, so the exact-match list keeps the fix surgical.
* Replaced the direct `from azure.cosmos import CosmosClient` bindings in the two remaining
  helper scripts with `import azure.cosmos as azure_cosmos` and module-qualified
  `azure_cosmos.CosmosClient(...)` calls, matching the pattern established in
  `COSMOSCLIENT_IMPORT_BINDING_CODEQL_FIX.md` (v0.250.047). No direct `CosmosClient` imports
  remain in the repository.
* Restored `functional_tests/test_privacy_logging_telemetry_audit.py`, which had been failing
  since v0.242.072 because it asserted an exact `config.py` version. It now uses
  `assert_app_version_at_least`, per the repository's version-assertion guidance, so the privacy
  audit runs again.

## Validation

Test results:

* `functional_tests/test_log_credential_key_redaction.py` (new): 6/6 passed. Verified to fail
  before the fix, reporting all 18 unredacted credential key names and a reproduced `auth_key`
  leak, which confirms it is a real regression guard rather than a tautology.
* `functional_tests/test_privacy_logging_telemetry_audit.py`: 5/5 passed, previously erroring
  out before running any assertion.
* `functional_tests/test_log_event_call_contract.py`: passed.
* Route policy and plugin suites: passed.

Before and after:

| Property | Before | After |
|---|---|---|
| `{"auth_key": "<secret>"}` | logged in clear text | `***REDACTED***` |
| `{"auth": {"key": "<secret>"}}` | logged unless the value matched a `secret=` pattern | `***REDACTED***` |
| `{"pwd": "<secret>"}` | logged in clear text | `***REDACTED***` |
| `{"key_encoding": "utf8"}` | visible | visible (unchanged) |
| `{"partition_key_path": "/id"}` | visible | visible (unchanged) |

Impact:

* Credential values supplied to action connection tests can no longer reach stdout or
  Application Insights in clear text.
* Diagnostic value is preserved: benign configuration keys containing "key" remain readable, and
  sensitive keys still report presence through the `<key>_present` property in the structured
  log record.
* Runtime behavior is otherwise unchanged.

## Note on the remaining CodeQL alerts

The five `py/clear-text-logging-sensitive-data` alerts point at the logging sinks themselves.
CodeQL does not model `sanitize_log_message` and `sanitize_log_properties` as sanitizers, so it
may continue to report those sinks even though the data reaching them is redacted. This change
addresses the underlying gap the alerts exposed; if the alerts persist, they can be triaged in
the repository's code scanning view with this fix as the justification.
