# CodeQL Alert and Contract Check Fix

**Issue:** Pull request #1981 failed its model-catalog publication check and its Cosmos response contract job, and CodeQL reported new security alerts in code changed by the branch. A follow-up review also covered stale functional tests and open JavaScript alerts inherited from Development.

**Root causes:**

- The agentic workflow lock file predated the repository's `Workflow Coordinator` agent, so the pinned `gh aw` v1.2.2 compiler produced a different manifest.
- The settings writer harness executed `update_user_settings` without the conflict, copy, and managed CA reference names the writer now uses.
- The offline application double had no `patch_item`, while the no-Redis stream replay fallback now appends events and renews discovery records with conditional partial updates.
- The contract job ran at the edge of its 45-minute limit. Development-based runs already took 37–41 minutes.
- CA bundle validation used a lazy `BEGIN ... END` regular expression that rescans the upload for every unterminated `BEGIN` marker. A crafted 1 MiB upload took minutes.
- Legacy Foundry protocol inference matched `services.ai.azure.com` anywhere in the URL instead of the host.
- Cosmos cache fallback warnings interpolated request-derived cache keys into stdlib log lines, and the personal endpoint delete route returned raw exception text.
- The classic streaming client passed `{ refreshExpandedMetadata: true }` to `updateUserMessageId` as a fifth argument, so the function never received it.
- `resolve_custom_endpoint_credentials` returned the real API key as the SDK credential for non-`Authorization` key headers, so OpenAI SDK clients also sent it as `Authorization: Bearer`. The V2 merge also dropped the bearer header from bearer auth, which Custom Anthropic clients need because they send only explicit headers.
- The Custom image client passed `max_retries=0` alongside client options that already contained `max_retries`, so every Custom image client raised `TypeError` during construction (also present on Development).
- The classic table unwrapping regular expression could split a run of pipe lines between two repeated groups and a multi-line separator group in exponentially many ways. 22 crafted lines took about two seconds.
- Several classic pages reinterpreted DOM or request text as HTML: read-aloud parsed message text into a live element, export wizard IDs were interpolated into attributes, toasts supported an HTML branch, and directory user searches placed search terms in markup and directory names in inline `onclick` handlers.
- The routing preview treated an unset path order as `connection_first`, while saved connections resolve an unset order as `model_first`, so a preview could show a different URL from the one the connection calls. The classic admin modal also saved `connection_first` for an existing explicit-routing connection that had no stored order, which changed its request URL on the next save.
- Legacy group connection tests looked up the saved endpoint and resolved the request payload against the active group separately instead of pinning one group for both.
- Several functional test harnesses predated current helper, decorator, kernel function, and action recovery contracts, or held stale source and dependency snapshots, so they failed on the unmodified branch.

**Fixed in version: 0.261.485**

## Technical details

### Files modified

- `.github/workflows/refresh-model-catalog.lock.yml`
- `.github/workflows/cosmos-response-contract-check.yml`
- `application/single_app/model_endpoint_ca_bundles.py`
- `application/single_app/functions_model_endpoint_urls.py`
- `application/single_app/functions_model_endpoint_auth.py`
- `application/single_app/functions_image_generation.py`
- `application/single_app/app_settings_cache.py`
- `application/single_app/route_backend_models.py`
- `application/single_app/static/js/admin/admin_model_endpoints.js`
- `application/single_app/static/js/chat/chat-streaming.js`, `chat-messages.js`, `chat-export.js`, and `chat-tts.js`
- `application/single_app/static/js/control-center.js`, `workspace-manager.js`, and `templates/control_center.html`
- `application/single_app/config.py`, `semantic_kernel_loader.py`, `model_endpoint_clients.py`, and import-only cleanups in other application modules
- `functional_tests/test_support/cosmos_patch.py` (new), `functional_tests/test_support/offline_bootstrap.py`, and `functional_tests/test_support/app_stubs.py`
- `functional_tests/test_classic_js_codeql_xss_redos_fixes.py` (new)
- `functional_tests/test_m365_settings_ingress.py` and the focused regression and harness tests listed under Validation
- `functional_tests/cosmos_response_boundaries.json`

### Code changes

- `validate_ca_certificates` splits PEM blocks with resumable `bytes.find` calls. Acceptance is unchanged: at least one byte between markers, the first `END` closes a block, and anything other than whitespace outside blocks is rejected. A differential fuzz of 200,000 inputs matched the former expression exactly.
- Legacy protocol inference recognizes Foundry only when the parsed hostname ends with `.services.ai.azure.com`, matching the schema-v2 validator.
- Cosmos cache fallback warnings escape carriage returns and line feeds in cache keys and exception text. The structured `log_event` properties are unchanged.
- The personal model endpoint delete route returns the same stable governance message as its sibling routes without serializing the exception.
- The classic streaming client passes the metadata refresh option as `updateUserMessageId`'s options argument.
- The offline double applies `add`, `set`, `replace`, `remove`, and `incr` patch operations atomically and evaluates the filter predicates the application sends, with Cosmos three-valued logic. Unsupported predicate syntax fails the test instead of matching.
- The settings writer harness binds the real managed CA reference fence and fails if a write without managed bundles opens the CA registry.
- The refreshed workflow lock records the coordinator agent. The contract job timeout is 60 minutes.
- CodeQL quality findings introduced by the branch were cleaned up: duplicate dictionary keys, dead locals and functions, unused imports, unexplained empty `except` blocks, and `BaseException` handlers in asyncio cleanup callbacks.
- For API keys sent in any header other than `Authorization`, the SDK credential is the `custom-header-auth` placeholder and `Authorization` is explicitly empty, so the key travels only in its configured header. Bearer auth returns its validated `Authorization: Bearer` header again; OpenAI SDK clients replace their identical default header instead of duplicating it.
- The Custom image client sets `max_retries` to 0 in its single options dictionary.
- Legacy group connection tests resolve the active group once, after preview and explicit schema-v2 tests are dispatched, and use it for both the saved-endpoint lookup and payload resolution.
- Routing previews leave an unset path order unset, so they resolve exactly as the saved connection does at runtime (`model_first`). An explicit order still applies. The classic admin modal keeps `model_first` when saving a connection that has no stored order; new connections still start `connection_first`.
- `unwrapTablesFromCodeBlocks` scans lines once with precomputed pipe-line runs, separator-line runs, and fence positions. It reproduces the former expression's fences, greedy closing choice, optional blank line before the closing fence, separator-group bridges, and resume position. The table checks are unchanged.
- Read-aloud strips markup with `DOMParser`, which builds an inert document. The export wizard escapes conversation IDs, including quotes. Inline export buttons build their icon and label with DOM nodes. Control Center toasts are built with DOM nodes and `textContent`, and the two ownership toasts use line breaks instead of markup. Directory user searches escape the search term and bind each Select button to its result object instead of an inline handler. A dead duplicate `GroupManager.deleteGroup` that the later modal flow always overrode was removed.
- Stale harnesses bind the real code they exercise instead of outdated copies. The shared stubs and model endpoint suites bind the real CA trust resolver, timeout, profile, validation, and protocol helpers. The image chat route harness binds the chat retry, chat link, and public scope decorators, the exceptions its handlers catch, and the extracted metadata helpers. The MCP authorization harness wraps kernel functions with Semantic Kernel's qualified-name metadata, gives each action fixture a distinct ID, and models a claimed continue decision for an unavailable action. The inbound MCP shell test checks the header-attaching 202 response, and the V2 dependency snapshot includes the packages that workflow Flow inspection and Theme Cards added.

### Alerts intentionally not changed

- `py/clear-text-logging-sensitive-data` in `semantic_kernel_loader.py`: the logged value is the action's `name`. The flow starts at `resolve_key_vault_secrets_in_plugins`, which only resolves `auth` credential fields and `additionalFields` secrets.
- `py/weak-sensitive-data-hashing` in `functions_shared_cache.py`: the flagged source is the `AUTH_TYPE_API_KEY` type constant, and the hash is a telemetry fingerprint for a cache key.
- `js/xss-through-dom` in `chat-messages.js` (image messages) and `MessageList.tsx`: the values only reach image `src` properties, which are never parsed as HTML. These alerts were dismissed as false positives with that justification.
- Import cycles, star imports, a re-export facade, flag-selected return shapes, and source-review-only owners are design choices or would require new owner-runtime evidence unrelated to these fixes.

## Validation

- The three failing contract tests and all seven settings ingress tests pass. The real chat transport probe passes with the stream replay fallback active.
- New regressions cover offline patch predicates and preconditions, linear CA scanning, legacy host inference, single-line fallback warnings, and the metadata refresh argument.
- A Node differential test compares the table unwrapping with the former expression on 80,000 generated inputs, including separator-bridge cases, and requires crafted inputs of 40,000 lines to finish quickly. Session fuzzing compared 700,000 inputs with no differences.
- The real MAI factory probe, Custom endpoint foundation, image runtime, image SDK, admin endpoint persistence, schema-v2 routing, content screening, image chat route, MCP authorization, inbound MCP shell, scope gate, and V2 inline image proposal suites pass. Each of the 98 test files that were updated or exercise the changed code was run in isolation on this branch and on the unmodified baseline: no test fails that passes on the baseline, and 172 tests that failed on the baseline now pass. The 32 files that still have failures fail the same way on the baseline.
- The Cosmos response-boundary inventory has no review gaps after re-reviewing the changed doubles and owners. The changed content screening settings seam is now classified as fault injection with runtime evidence.
- Swagger, XSS, broken-access-control, and whitespace checks report no new findings. Full-file XSS findings in the touched files drop by one compared with the unmodified baseline.

### Open issue exposed by the offline double fix

`test_action_runtime_recovery.py::test_actual_chat_routes_pause_before_kernel_initialization_or_user_persistence[/api/chat/stream]` used to stop at the missing `patch_item`. It now reaches its assertions and shows that, when a selected agent has an unavailable action, the streaming route saves the user's question through `ChatAttemptStore.begin` before action recovery pauses the request. Choosing **Continue** then resends the same `submission_id` with the recovery decision, and the server rejects it with `submission_conflict`. The non-streaming route is not affected. The fix needs a decision on whether streaming should check actions before saving the question or accept the resumed request for the same submission, so this change does not alter that path.

## Before and after

**Before:** publication and contract checks failed or timed out, a crafted CA upload could hold a worker for minutes, a lookalike URL could select the Foundry protocol, request-derived text could break a fallback log line, Custom header keys were also sent as bearer tokens, Custom Anthropic bearer auth and Custom image connections failed, routing previews and classic saves could disagree with the URL a connection actually calls, crafted chat tables could freeze the browser, and several classic pages reinterpreted text as HTML.

**After:** the checks reproduce the pinned compiler output and complete with headroom, CA validation and table unwrapping are linear, protocol inference reads the host, fallback warnings stay on one line, each credential is sent only where configured, Custom Anthropic and image connections work, previews and saves keep the runtime path order, and the classic pages render untrusted text as text.
