# Log Injection CodeQL Alerts Fix (v0.261.216)

## Issue

CodeQL's `py/log-injection` query had 19 open alerts on `paullizer-react-v2-ui`. Each one flagged
a log call that writes a value taken from the request, either Flask's `request` object or a URL
route variable such as `workflow_id`, `run_id`, `group_id`, `workspace_id` or `plugin_name`,
without a line-break sanitizer the query recognizes. All 19 are on code that predates the Chat
Orchestration Workflows roadmap, and reviews of that roadmap's pull requests kept hitting them.

| Alerts | Location at `70c255508` | What the line logs |
|---|---|---|
| 2551, 2552, 2553, 2554 | `functions_appinsights.py` L419, L515, L531, L553 | `log_event` messages, through the `sc_message` property in the `extra` dict |
| 1110, 1111 | `utils_cache.py` L215, L265 | a group or public workspace ID and the exception, when a document fingerprint query fails |
| 1113, 1114 | `utils_cache.py` L501, L571 | the cache key, document scope and partition key, on a search cache hit or write |
| 1115, 3411, 3412 | `utils_cache.py` L635, L711, L776 | the user, group or public workspace ID, after a search cache invalidation |
| 2120, 2121, 2122, 2123 | `route_backend_workflows.py` L1924, L1925, L1932, L1933 | `workflow_id` and `run_id`, when cancelling a personal workflow run fails |
| 2124, 2125, 2126 | `route_backend_workflows.py` L2318, L2325, L2332 | `workflow_id`, when cancelling a group workflow run fails |
| 1105 | `route_backend_plugins.py` L2214 | the whole admin plugin settings request body |

Fixed in version: **0.261.216**. Refs #1543.

## Root cause

The query credits one line-break sanitizer: a call to a method named `replace` whose first
argument is the string literal `"\r\n"` or `"\n"`. Anything derived from its result is treated as
clean. It does not credit `re.sub`, a `re.fullmatch` guard or a helper function, unless the value
passes through such a `replace` call inside it.

- **The 4 `functions_appinsights.py` alerts were false positives.** `log_event` runs every message
  through `sanitize_log_message`. That function masks secret assignments and authorization
  values, collapses each run of `\r`, `\n` and `\t` to one space with
  `LOG_CONTROL_CHAR_RE.sub(" ", ...)`, and truncates the text to `MAX_LOG_STRING_LENGTH` (8,192)
  characters with a `... [truncated]` suffix. No CR or LF survives, but the query could not see
  the regex remove them. All 16 reported flows pass through `sanitize_log_message` and reach the
  `extra` dict as the `sc_message` property that `_build_logger_extra` builds.
- **The 14 `utils_cache.py` and `route_backend_workflows.py` alerts were real, and low severity.**
  These lines put identifiers and exception text straight into a standard `logging` message. A
  route variable can carry an encoded line break, so a crafted ID could start what looks like a
  separate log entry.
- **The `route_backend_plugins.py` alert was also a disclosure risk.** The admin route logged the
  request body before validating it. A valid body holds only booleans, but whatever was sent was
  logged as sent, including a field the route then rejects, such as `api_key`, and a non-boolean
  value.

## Technical details

### functions_appinsights.py

`sanitize_log_message` gains one statement straight after the regex. Both of its returns, the
truncated one and the normal one, come after it:

```python
message_text = LOG_CONTROL_CHAR_RE.sub(" ", message_text)
# No-ops after the regex above; they make its line-break removal visible to static analysis.
message_text = message_text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
if len(message_text) > MAX_LOG_STRING_LENGTH:
```

- After the regex the text holds no CR or LF, so the three `replace` calls change nothing. The
  function returns exactly what it returned in 0.261.213.
- The calls must not move ahead of the regex, where they would change the output: `"a\n\nb"`
  would become `"a  b"`, with two spaces, instead of `"a b"`.
- `_build_logger_extra`, `_normalize_extra_key` and the debug `category` value are unchanged. No
  reported flow goes through the `re.fullmatch`-guarded hash and code values, the normalized keys
  or the category, so they did not need the same treatment.

### utils_cache.py

`utils_cache.py` imports `sanitize_log_message` from `functions_appinsights` and passes each value
the seven flagged lines write through it:

| Function | Sanitized values |
|---|---|
| `get_group_document_fingerprint` | `group_id`, the exception |
| `get_public_workspace_document_fingerprint` | `public_workspace_id`, the exception |
| `get_cached_search_results` (the cache hit line) | `cache_key`, `doc_scope`, `partition_key[:25]` |
| `cache_search_results` | `cache_key`, `doc_scope`, `partition_key[:25]` |
| `invalidate_personal_search_cache` | `user_id` |
| `invalidate_group_search_cache` | `group_id` |
| `invalidate_public_workspace_search_cache` | `public_workspace_id` |

- The messages and levels are unchanged. Some f-strings now span several lines.
- On the cache hit and write lines, the reported taint comes from `doc_scope` and the partition
  key. `cache_key` is a hash, but it is wrapped too, so every value on those lines is covered.
- `invalidate_group_search_cache` rebinds `group_id = sanitize_log_message(group_id)` on the line
  before its log call instead of wrapping the value inside the call, so the log line keeps its
  0.261.213 text. That line also carries an existing `py/clear-text-logging-sensitive-data`
  alert. CodeQL treats the group ID as a secret because of the name of a function it comes from,
  `_get_trusted_group_upload_scope_ids()` in `route_frontend_chats.py`. GitHub matches alerts
  between analyses by a fingerprint of the text at and just after the alert's line, so the first
  version of this fix, which wrapped `group_id` inline, made GitHub report that existing alert as
  a new high-severity one. The function returns straight after the log call, so the rebinding
  changes nothing else.
- The import adds no cycle. `config.py` already imports `functions_appinsights`, whose only
  application import is `app_settings_cache`, which in turn imports only the standard library,
  Azure, Redis and `app_settings_store`.

### route_backend_workflows.py

The existing `from functions_appinsights import log_event` line also imports
`sanitize_log_message`.

- In `cancel_user_workflow_run`, the `LookupError` and `WorkflowCancellationConflictError`
  handlers wrap `workflow_id` and `run_id`.
- In `cancel_active_group_workflow_run`, the `ValueError`, `LookupError` and `PermissionError`
  handlers wrap `workflow_id`.
- The calls stay `logging.exception` with the same format strings and argument order, so the level
  and the attached traceback are unchanged.
- `user_id` comes from the signed-in session, not the request. It is not flagged and not wrapped.

### route_backend_plugins.py

`update_core_plugin_settings` (`POST /api/admin/plugins/settings`) no longer logs the request
body. It logs the number of top-level fields through `log_event`, with the `[PLUGINS]` tag the
module's other events use:

```python
# Plugin settings payloads can carry secrets, so only their size is logged.
log_event(
    "[PLUGINS] Received plugin settings update request.",
    extra={"field_count": len(data) if isinstance(data, dict) else 0},
)
```

- Field names are not logged either. In a valid request they are always the same fixed set, and
  before validation they are whatever the client sent.
- The `Validated plugin settings` line after validation is unchanged. It logs only the validated
  booleans, and CodeQL does not flag it.
- Validation, the saved settings, the responses and the kernel reload request are unchanged.

### What is not changed

These lines have the same shape as the fixed ones, but CodeQL does not flag them on the base: its
taint tracking finds no request value that reaches them. They are left for follow-up work:

- In `utils_cache.py`, the personal document fingerprint error (`user_id`), the cache-expired and
  cache-miss debug lines (`cache_key`), and the cache read and write error lines.
- The `user_id` values in the workflow cancellation lines.

### Files modified

- `application/single_app/functions_appinsights.py`: the `replace` chain in
  `sanitize_log_message`.
- `application/single_app/utils_cache.py`: the import and the seven sanitized lines.
- `application/single_app/route_backend_workflows.py`: the import and the seven wrapped
  arguments.
- `application/single_app/route_backend_plugins.py`: the field-count log.
- `application/single_app/config.py`: `VERSION` 0.261.216.
- `functional_tests/test_log_injection_codeql_alerts_fix.py` (new): the tests below.
- `functional_tests/test_support/log_sanitizer.py` (new): `real_sanitize_log_message()` runs the
  real `sanitize_log_message` and the constants it reads from `functions_appinsights.py` source,
  for harnesses that run application functions in a namespace they build.
- `functional_tests/test_group_document_collaboration.py` and
  `functional_tests/test_group_workflow_fixture_parity.py`: the namespaces they run
  `invalidate_group_search_cache` and the workflow routes in gain `sanitize_log_message`.
- `docs/explanation/release_notes.md`: the 0.261.216 entry.

### Tests

`functional_tests/test_log_injection_codeql_alerts_fix.py` has 44 tests, written with plain
`assert`s that pass normally and under `python -O`. It needs no Azure resources.

- **The output is unchanged.** A frozen copy of the 0.261.213 `sanitize_log_message` is kept as
  reference data. The module and the harness helper must both match it over a 33-item corpus:
  plain text, `"a\n\nb"`, CRLF runs, a lone CR, tabs, mixed `\t\r\n`, `password=x`,
  `api_key=...`, `Bearer` and `Basic` values, strings at, over and around the 8,192-character
  limit, an exception, an int, a float, `None`, `True`, a dict, a list, bytes and unicode,
  including U+2028, U+2029 and U+0085. Spot checks pin `"a\n\nb"` to `"a b"`, the masking and the
  exact truncation suffix.
- **The replaces stay where CodeQL needs them.** An AST check requires a
  `message_text.replace("\r\n", ...)` and `.replace("\n", ...)` chain after the
  `LOG_CONTROL_CHAR_RE.sub` line and before every return. The calls change nothing at run time,
  so no behavior test would notice a refactor that drops them, and dropping them would reopen four
  alerts.
- **`log_event`** writes a message and `extra` values that contain CRLF and LF as single-line
  `sc_*` properties.
- **utils_cache.** Each of the seven functions runs from source against a fake container. An
  ordinary ID logs exactly the line 0.261.213 logged. IDs, scopes, keys and exception text that
  contain `\n` or `\r\n` log on one line.
- **Workflow cancellation.** Each of the five handlers runs from source. An ordinary ID logs the
  same line as before. An injected `workflow_id` and `run_id` log on one line, at ERROR, with the
  exception and its traceback attached, and the response status is unchanged.
- **Plugin settings.** A request with an `api_key` field and one with a secret in a boolean field
  are rejected as before, and neither the logged event, the log records nor stdout contain the
  fake key. A valid request is still saved and still requests the kernel reload.
- **Fresh-process imports.** A subprocess with every socket blocked imports `functions_appinsights`
  and `utils_cache` in both orders, `config` then `utils_cache`, `route_backend_workflows`,
  `route_backend_plugins` and `app`, normally and under `-O`. It checks that each edited module's
  `sanitize_log_message` or `log_event` is the `functions_appinsights` one. The probe imports
  `functions_authentication` before `route_backend_workflows`, as `app.py` does: on the base, a
  cold import of `route_backend_workflows` on its own already fails with
  `NameError: enabled_required`, from an existing `functions_settings` and
  `functions_authentication` import cycle.

## Impact

- Apart from the plugin settings line, log output is byte-identical for ordinary values, and
  `log_event` output is byte-identical for every value.
- A wrapped value that contains a line break or tab is now logged on one line, with each run of
  them collapsed to a space. Like `log_event` messages, a wrapped value that contains a secret
  assignment or an authorization value is masked, and one longer than 8,192 characters is
  truncated.
- The plugin settings line now reads `[PLUGINS] Received plugin settings update request.` with a
  `field_count` property, through `log_event`, instead of the request body through the root
  logger.
- No setting, route, response or stored data changes.

## Validation

- **Local CodeQL.** CodeQL 2.27.1 with `codeql/python-queries` 1.8.11, the versions in the base
  analysis, ran `Security/CWE-117/LogInjection.ql` and `Security/CWE-312/CleartextLogging.ql`
  over the four edited modules, the two settings cache modules they import and a synthetic Flask
  driver. The driver registers the workflow routes on a Flask blueprint, as `app.py` does, feeds
  request values into every input of the flagged functions, passes the return value of a
  function named `_get_trusted_group_upload_scope_ids` to `invalidate_group_search_cache`, and
  logs `sanitize_log_message(value)` directly.
  - Base: 23 log-injection results. They are the 19 alerts, the driver's direct line, and the
    three `utils_cache.py` lines listed under "What is not changed" that log `user_id` or
    `cache_key`. The driver reaches those three only by passing request values where the
    application passes the signed-in user's ID or a hashed cache key.
  - Fix: 3 log-injection results, the same three lines. All 19 alerts cleared, and so did the
    driver's direct line, which shows that `sanitize_log_message` now works as a sanitizer for its
    callers.
  - Both runs report the same three clear-text results, with the same fingerprints, including the
    one on the group invalidation log line.
- **Mutation checks.** 25 mutations, each run normally and under `-O`, 50 runs in all, were each
  caught by at least one test:
  - unwrapping any one of the 20 `sanitize_log_message` calls (13 in `utils_cache.py`, one of them
    the `group_id` rebinding, and 7 in `route_backend_workflows.py`)
  - moving the replaces ahead of the regex (3 tests fail)
  - dropping the replaces (the AST check fails)
  - restoring the payload log (3 plugin tests fail)
  - removing the new import from `utils_cache.py` (6 import tests fail) or
    `route_backend_workflows.py` (2 import tests fail)

  The source files were restored byte-identical afterwards.
- **GitHub CodeQL.** The pull request's first analysis reported no new `py/log-injection` alert.
  Its one new alert was the existing clear-text alert on the group invalidation line, which that
  version had wrapped inline. The `group_id` rebinding described under utils_cache.py fixes it.
- **Alert fingerprints.** A reimplementation of the fingerprint GitHub computes reproduces all
  1,096 fingerprints in the base analysis. On the final code, 149 of the 163 base results in the
  edited files keep their fingerprints. The 14 that change are log-injection alerts on lines this
  fix edits. The other five log-injection alerts, the four in `functions_appinsights.py` and the
  group invalidation one, keep their fingerprints, so GitHub closes them only when CodeQL stops
  reporting them, which the local run shows it does.

## Related

- #1543: the Chat Orchestration Workflows roadmap, whose reviews kept hitting these alerts.
- [Log Credential Key Redaction Fix](LOG_CREDENTIAL_KEY_REDACTION_FIX.md): the
  `py/clear-text-logging-sensitive-data` alerts on the same logging sinks, a different rule that
  this fix does not change.
- `functional_tests/test_log_injection_codeql_alerts_fix.py`.
