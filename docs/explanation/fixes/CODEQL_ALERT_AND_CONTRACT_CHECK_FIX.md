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
- The pull request's CodeQL check counts the results of the pull request analysis, and dismissing an alert does not remove its result from that count. Two plugin creation `print` lines the branch added (alerts 5381 and 5382) kept the check's high count at 2 after they were dismissed as false positives.
- Because the branch diff is too large to map line moves, the check also counted nine `error`-level alerts that are open on Development: seven test assertions that contained the delete request or workflow unit run they checked, `CustomAnthropicChatCompletionClient.__init__` not calling `AnthropicChatCompletionClient.__init__` (alert 3370), and an unsafe import cycle (alert 3330). `functions_settings` imports `functions_document_actions` while it loads, and `functions_document_actions` imported `normalize_search_id_list` through `functions_search`, which loads `config` and, through `functions_content`, `functions_settings`.

**Fixed in version: 0.261.485**

Follow-up CodeQL fixes in version: **0.261.486**

Pull request CodeQL check follow-up in version: **0.261.487**

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
- `application/single_app/static/js/plugin_modal_stepper.js` (0.261.486)
- `application/single_app/config.py`, `semantic_kernel_loader.py`, `model_endpoint_clients.py` (also 0.261.487), and import-only cleanups in other application modules
- `application/single_app/functions_document_actions.py`, and comments in `admin_settings_fields.py` and `functions_orchestration_registry.py` (0.261.487)
- `functional_tests/test_support/cosmos_patch.py` (new), `functional_tests/test_support/offline_bootstrap.py`, and `functional_tests/test_support/app_stubs.py`
- `functional_tests/test_classic_js_codeql_xss_redos_fixes.py` (new)
- `functional_tests/test_app_settings_import_boundaries.py`, `test_workspace_authoring_backend.py`, `test_workflow_durable_execution.py`, `test_image_description_indexing_without_ocr_text.py`, and docstrings in `test_v2_admin_actions_parity.py` (0.261.487)
- `docs/explanation/features/V2_ADMIN_AGENTS_ACTIONS.md` and `docs/explanation/fixes/IMAGE_DESCRIPTION_INDEXING_WITHOUT_OCR_TEXT_FIX.md` (0.261.487)
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
- Read-aloud never parses message text as HTML. It reads the rendered, already sanitized message when it is on the page, and otherwise reads the given text as plain text. In 0.261.485 it used `DOMParser`, which builds an inert document, but CodeQL still treats HTML parsing of DOM text as a sink (alert 5493), so 0.261.486 removes the parsing. The export wizard escapes conversation IDs, including quotes. Inline export buttons build their icon and label with DOM nodes. Control Center toasts are built with DOM nodes and `textContent`, and the two ownership toasts use line breaks instead of markup. Directory user searches escape the search term and bind each Select button to its result object instead of an inline handler. A dead duplicate `GroupManager.deleteGroup` that the later modal flow always overrode was removed.
- Message loading encodes the conversation ID as a single path segment (alert 489), and the action configuration modal skips `__proto__`, `constructor`, and `prototype` keys when it merges additional-field JSON, so parsed JSON cannot reach `Object.prototype` (alert 473). Both changes are in 0.261.486.
- In 0.261.487, `functions_document_actions` imports `normalize_search_id_list` from `search_scope_utils`, which defines it and imports nothing, instead of through `functions_search`. Nothing it loads at import time reaches `config` or `functions_settings`, so it loads correctly whether or not `functions_settings` is already loading (alert 3330). Comments in `admin_settings_fields.py`, `functions_orchestration_registry.py`, and `test_v2_admin_actions_parity.py`, and the V2 admin agents and actions feature doc, no longer say the module reaches `config.py`. The image description test's reverse import order probe relied on the removed path to load `functions_content` while `functions_content_understanding` loaded; it now requires `functions_content_understanding` to load completely first.
- `CustomAnthropicChatCompletionClient` initializes through `AnthropicChatCompletionClient` (alert 3370). It passes the URL resolved with its Custom URL mode as the operation URL, which the base class uses as given, and keeps its own transport options and header builder. The base class also trims the Anthropic version and uses the default when it is blank; callers already pass a version.
- The Yamcs and Microsoft Decision branches of plugin creation no longer print their own "Created ... plugin" line (alerts 5381 and 5382). The "Successfully loaded agent plugin" message that follows already records the action name and type.
- Seven test assertions that contained a delete request or a workflow unit run now assign the result first and assert on it (alerts 3015 and 3018–3023), so the calls still run under `python -O`. The replay assertion in the same durable execution test was changed the same way.
- Stale harnesses bind the real code they exercise instead of outdated copies. The shared stubs and model endpoint suites bind the real CA trust resolver, timeout, profile, validation, and protocol helpers. The image chat route harness binds the chat retry, chat link, and public scope decorators, the exceptions its handlers catch, and the extracted metadata helpers. The MCP authorization harness wraps kernel functions with Semantic Kernel's qualified-name metadata, gives each action fixture a distinct ID, and models a claimed continue decision for an unavailable action. The inbound MCP shell test checks the header-attaching 202 response, and the V2 dependency snapshot includes the packages that workflow Flow inspection and Theme Cards added.

### Alerts intentionally not changed

- `py/clear-text-logging-sensitive-data` in `semantic_kernel_loader.py`: the logged value is the action's `name`. The flow starts at `resolve_key_vault_secrets_in_plugins`, which only resolves `auth` credential fields and `additionalFields` secrets. The eight remaining alerts are also open on Development; the two lines the branch added were removed in 0.261.487.
- `py/weak-sensitive-data-hashing` in `functions_shared_cache.py`: the flagged source is the `AUTH_TYPE_API_KEY` type constant, and the hash is a telemetry fingerprint for a cache key.
- `js/xss-through-dom` in `chat-messages.js` (image messages) and `MessageList.tsx`: the values only reach image `src` properties, which are never parsed as HTML. These alerts were dismissed as false positives with that justification.
- Other import cycles, star imports, a re-export facade, flag-selected return shapes, and source-review-only owners are design choices or would require new owner-runtime evidence unrelated to these fixes. The one `error`-level unsafe cycle was fixed in 0.261.487.

### CodeQL check attribution

The pull request's CodeQL check fails on any `error`-level standard alert as well as on high or critical security alerts, which are GitHub's default thresholds. For head `b5af1f916` (0.261.486) it reported 257 new alerts, including 2 high and 9 errors, with GitHub's note that the diff is too large to tell which alerts the pull request introduced. Neither group appears in a list of open high or critical alerts:

- The 2 high alerts are 5381 and 5382, the Yamcs and Microsoft Decision `print` lines this branch added to `semantic_kernel_loader.py`. They were dismissed as false positives before the last two analyses ran, and both analyses still counted them. They are the only high alerts that exist only on the pull request in files it changes. Alert 4909 also exists only on the pull request, but it is in `functions_shared_cache.py`, which the branch does not change, so it is not counted.
- The 9 errors are standard alerts that are open on Development and moved within files the branch changes: 3015, 3018–3023, 3330, and 3370. Other moved alerts in changed files, including high ones, were not counted. GitHub's attribution for an oversized diff could not be reproduced exactly.
- The check's 138 annotations are warnings and notices only.

0.261.487 removes the code behind all 11 results; see Code changes. A local port of CodeQL's line fingerprint reproduces the 269 analyzed results it was checked against, and every other result in the edited files keeps its fingerprint, so GitHub matches them to their existing alerts instead of counting them as new. Because the diff stays too large to map, a later analysis can still attribute other alerts that are open on Development. The check is not required: Development has no branch protection or rulesets.

## Validation

- The three failing contract tests and all seven settings ingress tests pass. The real chat transport probe passes with the stream replay fallback active.
- New regressions cover offline patch predicates and preconditions, linear CA scanning, legacy host inference, single-line fallback warnings, and the metadata refresh argument.
- A Node differential test compares the table unwrapping with the former expression on 80,000 generated inputs, including separator-bridge cases, and requires crafted inputs of 40,000 lines to finish quickly. Session fuzzing compared 700,000 inputs with no differences.
- The real MAI factory probe, Custom endpoint foundation, image runtime, image SDK, admin endpoint persistence, schema-v2 routing, content screening, image chat route, MCP authorization, inbound MCP shell, scope gate, and V2 inline image proposal suites pass. Each of the 98 test files that were updated or exercise the changed code was run in isolation on this branch and on the unmodified baseline: no test fails that passes on the baseline, and 172 tests that failed on the baseline now pass. The 32 files that still have failures fail the same way on the baseline. Compared with Development, 26 of those files fail the same way there. The other 6 are the streamed recovery bug below and five tests that the V2 merge or the workspace chat deep link change left stale.
- The Cosmos response-boundary inventory has no review gaps after re-reviewing the changed doubles and owners. The changed content screening settings seam is now classified as fault injection with runtime evidence.
- Swagger, XSS, broken-access-control, and whitespace checks report no new findings. Full-file XSS findings in the touched files drop by one compared with the unmodified baseline.

### Pull request check follow-up (0.261.487)

- A port of the CodeQL action's line fingerprint reproduces all 269 analyzed results it was checked against. Across the 11 changed Python files, 108 results keep their fingerprints and none changes. Only the nine targeted lines and one `py/cyclic-import` note on the replaced import change. Alerts 3330 and 3370 are on unchanged lines and close because the cycle and the missing base initializer call are fixed. The next analysis confirms which alerts close.
- A static import-time trace finds no path from `functions_document_actions` to `config` or `functions_settings`. The new guarded cold import in `test_app_settings_import_boundaries.py` fails on 0.261.486 at `functions_search`'s `from config import *` and passes on 0.261.487.
- These suites pass on 0.261.487: the six edited authoring tests (41 of 42 cases), durable execution, admin actions parity, document action capability settings, workflow merge, group workflow round trip, per-document analysis mode, document source scope identity, document analysis work recovery, the orchestration dependency, native dependency, native infrastructure, native waiting, internal analysis, relational results, executor, V2 plan, conversation context, and context picker suites, the Custom Anthropic provider, protocol inference, Custom endpoint diagnostics, model endpoint normalization, Yamcs, and Microsoft Decision suites, the image description reverse import order probe, every import order in `test_workflow_goal_first_imports.py`, and all 30 `test_workflow_chat_delivery_imports.py` probes.
- The remaining failures in the affected files fail the same way on 0.261.486: `test_every_action_type_create_edit_reload_delete[microsoft_decision]`, `test_recent_target_runner_hooks`, `test_model_name_lookup_prefers_deployments_then_first_endpoint`, `test_document_actions_and_comparison_wiring`, seven `test_mixed_source_hardening.py` tests, and the stale `test_analyze_orchestration_saved_integration.py`, `test_workflow_draft_save_parity.py`, `test_model_endpoint_management_cloud_environment.py`, and `test_workflow_repeat_editor_options.py` cases. `test_orchestration_visual_outputs.py` and `test_orchestration_action_planning.py` crash with an access violation while their fixture restores `sys.modules`, at the same point on both versions; their fixture replaces `functions_document_actions` with definitions read from source, so the changed import never runs there.
- On the slow validation host, five cold-import bootstrap probes exceeded their 60-second limit and three import order probes their 240-second stall budget. Each passes when given more time.
- The Cosmos response-boundary inventory has no review gaps, and the XSS, broken-access-control, Swagger, and whitespace checks pass.

### Streamed action recovery

The offline double fix also let `test_action_runtime_recovery.py::test_actual_chat_routes_pause_before_kernel_initialization_or_user_persistence[/api/chat/stream]` reach its assertions, which exposed a streamed action recovery bug: the stream saved the question before pausing, so **Continue** failed with `submission_conflict`. It is fixed in 0.261.486; see [Streamed Chat Action Recovery Continue Fix](STREAM_ACTION_RECOVERY_CONTINUE_FIX.md).

## Before and after

**Before:** publication and contract checks failed or timed out, a crafted CA upload could hold a worker for minutes, a lookalike URL could select the Foundry protocol, request-derived text could break a fallback log line, Custom header keys were also sent as bearer tokens, Custom Anthropic bearer auth and Custom image connections failed, routing previews and classic saves could disagree with the URL a connection actually calls, crafted chat tables could freeze the browser, and several classic pages reinterpreted text as HTML.

**After:** the checks reproduce the pinned compiler output and complete with headroom, CA validation and table unwrapping are linear, protocol inference reads the host, fallback warnings stay on one line, each credential is sent only where configured, Custom Anthropic and image connections work, previews and saves keep the runtime path order, and the classic pages render untrusted text as text.
