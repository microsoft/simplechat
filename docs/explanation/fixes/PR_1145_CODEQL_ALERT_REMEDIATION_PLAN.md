# PR 1145 CodeQL Alert Remediation Plan

Planning baseline version: **0.250.110**

Related PR: **microsoft/simplechat#1145**

Implementation status: **In progress. Phase 1 items 1 and 2 implemented in versions 0.250.111 and 0.250.112; remaining items are still pending.**

## Purpose

This plan converts the 62 CodeQL annotations from PR #1145 into an execution queue. The main execution plan follows the implementation decisions from the alert review. Optional test-file cleanup items and intentionally deferred architecture cleanup are captured in a separate deferred remediation plan at the end of this document.

## Execution Policy

- Implement all failure and warning alerts unless they are explicitly deferred below.
- Implement low-risk hygiene notices when they are mechanically scoped and do not require broad import-boundary refactoring.
- Defer optional test-file cleanup items even if they are easy, so the main remediation stays focused on security, runtime correctness, and deterministic cleanup.
- Defer cyclic-import and `import *` cleanup into separate planning work because those changes can alter import timing and route-module behavior.
- For simple Python hygiene findings, follow the CodeQL remediation example directly.
- For URL validation, regex performance, and exception disclosure, follow CodeQL's security principle but use repo-specific helpers and response patterns that fit SimpleChat logging, streaming, and mixed-source workflows.

## Main Execution Plan

### Phase 1: Security and Runtime-Failure Remediation

#### 1. Replace SharePoint substring URL checks with host-aware validation

- Alerts: 1, 2
- CodeQL rule: Incomplete URL substring sanitization
- Severity: failure
- Status: **Implemented in version 0.250.111**
- Locations:
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L8577)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L8548)
- Decision: Implement.
- Why: Substring checks allow attacker-controlled hostnames or paths that merely contain `sharepoint.com`. This is a real validation issue.
- Remediation style: Develop our own repo-specific helper while following CodeQL's host-validation guidance.
- Execution tasks:
  - Create one shared helper for tabular URL-like detection and SharePoint host validation.
  - Parse URLs with `urlparse` instead of checking arbitrary substrings.
  - Require `http` or `https` where a full URL is present.
  - Accept only `sharepoint.com` or subdomains ending in `.sharepoint.com` for SharePoint-specific detection.
  - Preserve existing `/sites/` path detection only where it is intentionally path-like content, not a trusted external URL decision.
- Validation starting point:
  - Add or update focused functional coverage for valid SharePoint URLs, subdomain SharePoint URLs, malicious lookalike domains, path-only `/sites/` values, and ordinary non-URL values.
- Validation completed:
  - `python functional_tests/test_tabular_llm_reviewer_recovery.py`
  - `python -m py_compile application/single_app/route_backend_chats.py application/single_app/config.py`
  - `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check -- application/single_app/route_backend_chats.py functional_tests/test_tabular_llm_reviewer_recovery.py application/single_app/config.py`

#### 2. Replace polynomial markdown-fence regex parsing with linear parsing

- Alerts: 4, 5, 6
- CodeQL rule: Polynomial regular expression used on uncontrolled data
- Severity: failure
- Status: **Implemented in version 0.250.112**
- Locations:
  - [application/single_app/functions_workflow_runner.py](../../../application/single_app/functions_workflow_runner.py#L383)
  - [application/single_app/functions_assistant_table_exports.py](../../../application/single_app/functions_assistant_table_exports.py#L389)
  - [application/single_app/functions_assistant_table_exports.py](../../../application/single_app/functions_assistant_table_exports.py#L414)
- Decision: Implement.
- Why: These helpers process model or user-influenced text. A regex with backtracking risk can create avoidable request latency or denial-of-service exposure.
- Remediation style: Develop our own linear parser rather than tuning the regex.
- Execution tasks:
  - Replace the workflow code-fence stripper with prefix/suffix checks and bounded slicing.
  - Introduce or reuse a linear fenced-block iterator for assistant table export parsing.
  - Preserve language-label behavior for CSV fences and generic fences.
  - Keep unfenced CSV parsing behavior unchanged.
- Validation starting point:
  - Add focused tests for fenced JSON, fenced CSV, generic fenced CSV-like content, unfenced CSV content, unterminated fences, and adversarial strings with many spaces or tabs after opening fences.
- Validation completed:
  - `python functional_tests/test_assistant_table_csv_artifact.py`
  - `python functional_tests/test_document_analysis_lossless_artifacts.py`
  - `python functional_tests/test_document_analysis_structured_output.py`
  - `python -m py_compile application/single_app/functions_workflow_runner.py application/single_app/functions_assistant_table_exports.py application/single_app/config.py`

#### 3. Stop exposing raw exception messages or tracebacks to browser responses

- Alerts: 7-17, 20-23, 25-27
- CodeQL rule: Information exposure through an exception
- Severity: warning
- Status: **Implemented in version 0.250.113**
- Locations:
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L14244)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L14316)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L14467)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L14469)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L14485)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L14675)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L14989)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L15005)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L15096)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L16568-L16570)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L17212)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L18405-L18433)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L18450-L18453)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L18479)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L22523)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L22539)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L22546)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L22560-L22563)
- Decision: Implement.
- Why: Raw exception strings can contain provider details, internal object names, stack traces, paths, query text, storage metadata, or authorization state. The route should log details server-side and return stable client-safe messages.
- Remediation style: Follow CodeQL's principle, but develop SimpleChat-specific response helpers for JSON and SSE paths.
- Execution tasks:
  - Keep detailed exception data in `log_event` with `exceptionTraceback=True` where appropriate.
  - Return generic client-safe messages for unexpected server failures.
  - Preserve specific 400, 401, 403, and 404 messages only when they are intentional validation or authorization outcomes.
  - For content-safety and moderation paths, use explicit allowlisted user-facing messages.
  - For streaming routes, emit sanitized SSE error events and avoid embedding raw exception text in `error` or `partial_content` metadata.
  - Remove traceback details from browser responses even when Flask debug is enabled.
- Validation starting point:
  - Add focused route or helper tests that simulate unexpected exceptions and assert that responses do not include raw exception text, traceback text, local paths, provider class names, or internal query/source descriptors.
  - Include both JSON responses and SSE error events.
- Validation completed:
  - `python functional_tests/test_chat_error_response_sanitization.py`
  - `python -m py_compile application/single_app/route_backend_chats.py application/single_app/config.py functional_tests/test_chat_error_response_sanitization.py`
  - `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check -- application/single_app/route_backend_chats.py application/single_app/config.py functional_tests/test_chat_error_response_sanitization.py docs/explanation/fixes/PR_1145_CODEQL_ALERT_REMEDIATION_PLAN.md`
- Validation notes:
  - `python functional_tests/test_foundry_delegated_user_auth.py` was attempted; 7/8 checks passed, and the remaining failure is the test's hardcoded historic `VERSION = "0.241.196"` assertion.
  - `python functional_tests/test_content_safety_error_handling.py` was attempted; it fails before checking behavior because it points at stale root-level `route_backend_chats.py` and `static/js/chat/chat-messages.js` paths.

### Phase 2: Correctness and Behavior Cleanup

#### 4. Fix unused citation loop variable

- Alert: 3
- CodeQL rule: Suspicious unused loop iteration variable
- Severity: failure
- Location: [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L17737)
- Decision: Implement.
- Why: The loop currently iterates citations without using the citation value. That can indicate repeated duplicate thoughts or missing citation-specific detail.
- Remediation style: Follow CodeQL directly if only the count matters; otherwise use the citation object meaningfully.
- Execution tasks:
  - Decide whether one thought per citation is intended.
  - If yes, include sanitized citation-specific detail in the thought payload.
  - If no, replace the loop with a single aggregate thought or use `_` only for intentional repeated emission.
- Validation starting point:
  - Add or update a focused Foundry citation test to assert the expected number and content of citation thoughts.

#### 5. Remove duplicate keys in token usage aggregation test fixture

- Alerts: 18, 24
- CodeQL rule: Duplicate key in dict literal
- Severity: warning
- Location: [functional_tests/test_document_action_token_usage_aggregation.py](../../../functional_tests/test_document_action_token_usage_aggregation.py#L225-L226)
- Decision: Implement.
- Why: Duplicate keys hide fixture intent and can make a test pass with the wrong mocked behavior.
- Remediation style: Follow CodeQL directly.
- Execution tasks:
  - Remove the overwritten duplicate entries.
  - Keep one canonical fixture value for each helper.
  - Confirm the test still exercises cross-format compare behavior intentionally.
- Validation starting point:
  - Run `python functional_tests/test_document_action_token_usage_aggregation.py`.

#### 6. Resolve unreachable code in chat route

- Alert: 19
- CodeQL rule: Unreachable code
- Severity: warning
- Location: [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L18404)
- Decision: Implement.
- Why: Unreachable code in a large route can hide a missing branch or stale error handling.
- Remediation style: Follow CodeQL directly after local inspection.
- Execution tasks:
  - Inspect the surrounding control flow.
  - Remove the statement if it is stale.
  - Move it before the terminal return if it was intended to run.
- Validation starting point:
  - Compile the route module and run the focused chat route tests that cover the edited path.

#### 7. Resolve no-effect statement in tabular lifecycle thought helper

- Alert: 47
- CodeQL rule: Statement has no effect
- Severity: notice
- Location: [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L9773)
- Decision: Implement after inspection.
- Why: A no-effect statement is usually leftover code or a missed assignment/call.
- Remediation style: Follow CodeQL directly once intent is known.
- Execution tasks:
  - Inspect the helper around the flagged line.
  - Remove the statement if it is leftover.
  - Convert it into the intended assignment or function call only if nearby logic proves that was the intent.
- Validation starting point:
  - Compile the route module and run tabular chat/thought tests that cover lifecycle thought emission.

#### 8. Make mixed explicit and implicit returns explicit

- Alert: 58
- CodeQL rule: Explicit returns mixed with implicit fall-through returns
- Severity: notice
- Location: [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L17310)
- Decision: Implement after inspection.
- Why: A silent `None` fall-through can turn into confusing model-call behavior or skipped error handling.
- Remediation style: Develop the smallest local fix after inspecting the nested function's contract.
- Execution tasks:
  - Identify the nested function and expected return shape.
  - Add an explicit terminal return if `None` is valid.
  - Otherwise add the missing return path that matches the function contract.
- Validation starting point:
  - Run focused tests around the Semantic Kernel call path or add a small unit-style functional test for the function contract.

### Phase 3: Low-Risk Hygiene Cleanup

#### 9. Remove unused imports in route and workflow modules

- Alerts: 29, 31, 36, 37, 38, 49, 50, 52, 57, 60, 62
- CodeQL rule: Unused import
- Severity: notice
- Locations:
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L2)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L21)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L22-L33)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L74)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L77)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L118)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L154)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L172)
  - [application/single_app/functions_workflow_runner.py](../../../application/single_app/functions_workflow_runner.py#L39-L49)
  - [application/single_app/functions_workflow_runner.py](../../../application/single_app/functions_workflow_runner.py#L158-L162)
  - [application/single_app/functions_tabular_generated_exports.py](../../../application/single_app/functions_tabular_generated_exports.py#L38-L41)
- Decision: Implement.
- Why: These are mechanically scoped and reduce noise for future CodeQL runs.
- Remediation style: Follow CodeQL directly.
- Execution tasks:
  - Remove imports only after confirming there are no dynamic references.
  - Avoid changing `import *` lines as part of this cleanup.
  - Keep import grouping consistent with the local file style.
- Validation starting point:
  - Run `python -m py_compile` for each touched Python file.
  - Run the focused functional tests for chat, workflow runner, and tabular generated exports.

#### 10. Remove duplicate local `json` import

- Alert: 30
- CodeQL rule: Module is imported more than once
- Severity: notice
- Location: [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L18465)
- Decision: Implement.
- Why: The module already imports `json` at top level. The local import is redundant.
- Remediation style: Follow CodeQL directly.
- Execution tasks:
  - Remove the nested duplicate import.
  - Confirm the function still resolves the top-level module import.
- Validation starting point:
  - Compile [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py).

#### 11. Replace empty except blocks with intentional handling

- Alerts: 32, 33, 34
- CodeQL rule: Empty except
- Severity: notice
- Locations:
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L22142)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L22170)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L22234)
- Decision: Implement.
- Why: Silent exception swallowing makes rollback or cleanup failures difficult to diagnose.
- Remediation style: Use repo-specific logging, not generic print statements.
- Execution tasks:
  - Narrow the caught exception type if possible.
  - Log cleanup failures with `log_event` or `debug_print`, depending on expected frequency and severity.
  - Add a short explanatory comment only if the exception is intentionally ignored.
- Validation starting point:
  - Compile the route module and run streaming cancellation or rollback tests that cover these cleanup paths.

#### 12. Remove unused local variables and dead debug comments

- Alerts: 28, 46, 59
- CodeQL rules: Unused local variable; commented-out code
- Severity: notice
- Locations:
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L11239)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L12820)
  - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L17655-L17659)
- Decision: Implement.
- Why: These findings add noise in a large route module and can obscure meaningful analysis.
- Remediation style: Follow CodeQL directly unless local inspection shows the variable should be wired into behavior.
- Execution tasks:
  - Remove `previous_execution_gap_messages` assignment only if it is not needed for retry telemetry.
  - Remove or wire `get_facts_for_context` based on whether fact-memory context still expects the helper.
  - Delete the commented debug block for enhanced agent citations.
- Validation starting point:
  - Compile the route module.
  - Run focused tabular retry and fact-memory/chat context tests if those paths are edited.

#### 13. Fix explicit `None` comparison in non-optional test cleanup

- Alert: 44
- CodeQL rule: Testing equality to None
- Severity: notice
- Location: [functional_tests/test_tabular_document_actions_workflow.py](../../../functional_tests/test_tabular_document_actions_workflow.py#L238)
- Decision: Implement.
- Why: This is a low-risk standards cleanup and was not classified as optional lambda-only test cleanup.
- Remediation style: Follow CodeQL directly.
- Execution tasks:
  - Replace equality comparison with identity comparison.
- Validation starting point:
  - Run `python functional_tests/test_tabular_document_actions_workflow.py`.

## Suggested Validation Sequence for Main Plan

1. Run Python compile checks for touched backend files:
   - [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py)
   - [application/single_app/functions_workflow_runner.py](../../../application/single_app/functions_workflow_runner.py)
   - [application/single_app/functions_assistant_table_exports.py](../../../application/single_app/functions_assistant_table_exports.py)
   - [application/single_app/functions_tabular_generated_exports.py](../../../application/single_app/functions_tabular_generated_exports.py)
2. Run focused functional tests for each touched behavior:
   - token usage aggregation
   - tabular document actions workflow
   - assistant table export parsing
   - tabular generated export routing
   - mixed-source or document-action chat flows affected by exception sanitization
3. Run route policy coverage only if route decorators or route registrations are touched.
4. Rerun the CodeQL check or PR checks after implementation to verify all targeted alerts are cleared.

## Deferred Remediation Plan

These items are intentionally deferred from the main execution plan. Each deferred item includes the reason and a starting point for a future remediation plan.

### Deferred Group A: Optional Test-File Lambda Cleanup

#### A1. Remove unnecessary lambda in mixed-source chat search fixture

- Alert: 41
- CodeQL rule: Unnecessary lambda
- Location: [functional_tests/test_mixed_source_chat_search_consistency.py](../../../functional_tests/test_mixed_source_chat_search_consistency.py#L149)
- Deferred because: This is optional test hygiene and does not affect runtime security, production correctness, or PR #1145 behavior.
- Starting point for future plan:
  - Inspect whether the lambda simply forwards to an existing callable with identical arguments.
  - Replace only if the direct callable preserves test readability and fixture behavior.
  - Run `python functional_tests/test_mixed_source_chat_search_consistency.py`.

#### A2. Remove unnecessary lambda in workflow search helper fixture

- Alert: 42
- CodeQL rule: Unnecessary lambda
- Location: [functional_tests/test_mixed_source_chat_search_consistency.py](../../../functional_tests/test_mixed_source_chat_search_consistency.py#L390)
- Deferred because: This is optional test hygiene and can be handled with other fixture simplification work.
- Starting point for future plan:
  - Confirm the lambda is only adapting an already compatible callable.
  - Replace with the callable object directly if there is no argument transformation.
  - Run the mixed-source chat search consistency test.

#### A3. Remove unnecessary lambda in Foundry context fixture

- Alert: 43
- CodeQL rule: Unnecessary lambda
- Location: [functional_tests/test_mixed_source_chat_search_consistency.py](../../../functional_tests/test_mixed_source_chat_search_consistency.py#L816)
- Deferred because: This is optional test cleanup in a Foundry-context fixture and should not distract from CodeQL failures and warnings.
- Starting point for future plan:
  - Verify whether `str` or another direct callable exactly matches the fixture's intended behavior.
  - Replace only if the fixture remains clear.
  - Run the mixed-source chat search consistency test.

#### A4. Remove unnecessary lambda in tabular row orchestration scale migration fixture

- Alert: 45
- CodeQL rule: Unnecessary lambda
- Location: [functional_tests/test_tabular_row_orchestration_scale.py](../../../functional_tests/test_tabular_row_orchestration_scale.py#L467)
- Deferred because: This is optional test hygiene and the scale test is already a sensitive regression harness for the PR's core behavior.
- Starting point for future plan:
  - Confirm the lambda does not intentionally adapt arguments or return values.
  - Replace with the callable object directly if behavior is identical.
  - Run `python functional_tests/test_tabular_row_orchestration_scale.py`.

### Deferred Group B: Import-Cycle Remediation

#### B1. Resolve workflow runner to tabular analysis import cycle

- Alert: 35
- CodeQL rule: Cyclic import
- Location: [application/single_app/functions_workflow_runner.py](../../../application/single_app/functions_workflow_runner.py#L5592)
- Deferred because: The import is local and appears intentionally placed to avoid top-level cycle failures. Moving it mechanically could break application startup or workflow execution order.
- Starting point for future plan:
  - Draw the dependency path among workflow runner, tabular analysis, mixed-source orchestration, and document analysis.
  - Identify a neutral module for shared contracts or helper functions.
  - Move only pure types/constants/helpers first, then retest workflow imports and document-action workflows.

#### B2. Resolve mixed-source orchestration logging import cycle

- Alert: 39
- CodeQL rule: Cyclic import
- Location: [application/single_app/functions_mixed_source_orchestration.py](../../../application/single_app/functions_mixed_source_orchestration.py#L11)
- Deferred because: This is a module-boundary issue involving shared telemetry. It should be fixed with an import architecture plan, not while touching chat-route security findings.
- Starting point for future plan:
  - Check whether `log_event` can be imported lazily or moved behind a lightweight telemetry adapter.
  - Confirm no import-time side effects depend on `functions_appinsights`.
  - Compile affected modules and run mixed-source orchestration tests.

#### B3. Resolve document analysis to mixed-source orchestration import cycle

- Alert: 40
- CodeQL rule: Cyclic import
- Location: [application/single_app/functions_document_analysis.py](../../../application/single_app/functions_document_analysis.py#L11-L14)
- Deferred because: Document analysis and mixed-source cancellation share contracts. Refactoring the boundary needs targeted regression coverage.
- Starting point for future plan:
  - Extract cancellation exceptions and cancellation guard helpers into a small neutral module.
  - Update both document analysis and mixed-source orchestration to import from that module.
  - Run document analysis, mixed-source chat, and workflow document-action tests.

#### B4. Resolve chat route to workflow runner import cycle

- Alert: 48
- CodeQL rule: Cyclic import
- Location: [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L199)
- Deferred because: [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py) is a large route module with many import-time dependencies. A mechanical import move could affect app startup.
- Starting point for future plan:
  - Identify which chat route functions require `_execute_document_action_workflow`.
  - Consider moving workflow invocation behind a small service adapter or local import at the use site.
  - Validate Flask app startup, chat document-action routes, and workflow execution.

#### B5. Resolve chat route to tabular analysis import cycle

- Alert: 61
- CodeQL rule: Cyclic import
- Location: [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L57-L59)
- Deferred because: The chat route uses tabular analysis callbacks and shared invocation helpers. Refactoring this safely requires understanding both synchronous and streaming paths.
- Starting point for future plan:
  - Inventory all tabular analysis symbols used by the chat route.
  - Move shared callback or invocation-inspection helpers into a neutral module if possible.
  - Validate tabular chat analysis, generated exports, and streaming progress.

### Deferred Group C: Star Import Remediation

#### C1. Replace `functions_chat` star import with explicit imports

- Alert: 51
- CodeQL rule: `import *` may pollute namespace
- Location: [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L120)
- Deferred because: Converting star imports in a large route module can expose many implicit dependencies and create a broad regression surface.
- Starting point for future plan:
  - Use static analysis to list actually used symbols from `functions_chat`.
  - Replace the star import in one commit with explicit imports only.
  - Compile the module and run chat route tests before touching other star imports.

#### C2. Replace `functions_settings` star import with explicit imports

- Alert: 53
- CodeQL rule: `import *` may pollute namespace
- Location: [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L88)
- Deferred because: Settings helpers are widely used in the route and include security-sensitive feature gates. A dedicated import cleanup needs careful validation.
- Starting point for future plan:
  - Inventory settings symbols used by the chat route.
  - Replace with explicit imports in isolation.
  - Run chat settings, model selection, source review, and generated export tests.

#### C3. Replace `functions_search` star import with explicit imports

- Alert: 54
- CodeQL rule: `import *` may pollute namespace
- Location: [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L81)
- Deferred because: Search helpers interact with hybrid search, tabular candidate search, and assigned knowledge paths.
- Starting point for future plan:
  - Inventory search symbols used by the chat route.
  - Replace with explicit imports and avoid mixing this with behavior changes.
  - Run hybrid search, assigned knowledge, and mixed-source search tests.

#### C4. Replace `functions_authentication` star import with explicit imports

- Alert: 55
- CodeQL rule: `import *` may pollute namespace
- Location: [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L80)
- Deferred because: Authentication symbols affect route access and user context. This cleanup should be isolated and covered by route policy tests.
- Starting point for future plan:
  - Inventory authentication decorators and helpers used by the route.
  - Replace with explicit imports.
  - Run route policy and chat authorization tests.

#### C5. Replace `config` star import with explicit imports

- Alert: 56
- CodeQL rule: `import *` may pollute namespace
- Location: [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py#L78)
- Deferred because: Config star imports often hide many container and app constants. Replacing it is valuable but high-churn.
- Starting point for future plan:
  - Inventory config symbols used by the route, especially Cosmos containers and feature constants.
  - Replace with explicit imports in a standalone cleanup PR.
  - Run Flask startup, chat, route policy, and import smoke tests.

## Deferred Validation Strategy

When the deferred work is planned, split it into at least three separate changes:

1. Optional test-file lambda cleanup.
2. Import-cycle boundary refactoring.
3. Star-import conversion in [application/single_app/route_backend_chats.py](../../../application/single_app/route_backend_chats.py).

Each deferred change should include focused compile checks, route startup validation when route imports change, and the smallest functional test set that covers the affected import boundary.