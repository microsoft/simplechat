# Streamed tool evidence and outcome reporting fix (v0.261.365)

Fixed/Implemented in version: **0.261.365**

Related config.py update: `VERSION = "0.261.365"` in
`application/single_app/config.py`.

Current application version after merging the V2 base: **0.261.367**.
This retains the search-evidence fixes from base version **0.261.366**.

## Issue and root causes

An ordinary V2 agent reply could finish with an empty Sources panel even when
the server's terminal event contained tool citations. The client copied
document and Microsoft 365 citations onto the completed message but omitted
`agent_citations` and `web_search_citations`. Reopening history could conceal
the live-state defect.

Separately, the plugin invocation decorator classified every normal return
as successful. The OpenAPI connector intentionally returns useful error
dictionaries for HTTP, request, and JSON-parse failures, so these failures
were incorrectly recorded as successful invocations. Reasoning activities
and tool citations inherited that incorrect outcome.

## Technical changes

### Streamed evidence

`application/v2_ui/src/lib/messageDetails.ts` provides one
`completionCitations()` projection for ordinary and orchestrated completion
in `src/stores/chatStore.ts`. It retains server-supplied document, web, tool,
and Microsoft 365 evidence, including tool identity, arguments, results,
artifact references, outcome, and error fields. Missing arrays normalize to
empty arrays; blocked and safety replies have no projected evidence.

`src/lib/types.ts` explicitly types the existing citation fields on messages
and stream events, plus the recorded tool identity/outcome/error fields.
The change does not infer citations from answer text, add requests for missing
evidence, or refactor message identity and stream-recovery behavior.

### Explicit execution outcomes

`application/single_app/semantic_kernel_plugins/plugin_invocation_logger.py`
adds `report_plugin_invocation_failure(error_message)` for connector-owned
failure branches. A context-local outcome belongs to one decorated invocation
and is reset on exit. Sync, async, and sync-returning-awaitable completions
consume the same outcome contract.

`semantic_kernel_plugins/openapi_plugin.py` reports its HTTP, parse, request,
and unexpected-operation failures at their existing error-return boundaries.
The decorator records the original result and invocation identity, with a
sanitized error and `success=False`. The existing logging, completion
callbacks, reasoning formatter, and citation builder consume that invocation;
there is no separate UI-only failure classifier.

Returned values stay unchanged, including direct connector-helper returns.
Exceptions and cancellation continue to propagate. Unmarked results remain
compatible: business data containing `error`, `status_code`, or `success`
does not by itself signal execution failure. No automatic retry, model call,
or action replay is added.

### Existing Sources inspector

`application/v2_ui/src/components/chat/MessageInspector.tsx` shows
**Tool call failed**, **Tool call succeeded**, or **Outcome not recorded**
inside the existing tool disclosure. Recorded errors appear as escaped text,
beside arguments and any available result. A failed invocation with no result
remains inspectable. Safe-link handling and result preview controls are unchanged.

## Usage and impact

After a reply finishes, open **Show sources** beneath that reply, then expand
its tool disclosure to compare arguments and returned data with the answer.
Web-only replies also expose their sources immediately.

No new setting or migration is required. This repairs the evidence handoff
used by normal sends, edits/retries, reattachment, and orchestration. Existing
message merging still produces one reply when stream and collaboration
messages arrive in either order.

Before this fix, a returned connector error could appear successful and a live
reply could appear to have no tool evidence. After this fix, available evidence
is retained at completion and connector-declared failures are recorded
consistently across logging, reasoning, and citations.

## Regression coverage

| Test | Coverage |
| --- | --- |
| `functional_tests/test_v2_stream_citation_delivery.mjs` | Real store/SSE sends, all evidence families, large results/artifact metadata, failed/null results, web-only and empty replies, moderation, edit/retry, reopen reattachment, transport recovery without action replay, merge ordering, and orchestration parity. |
| `functional_tests/test_plugin_invocation_outcomes.py` | Fresh-process real-module imports with external I/O blocked; dynamic and generic OpenAPI calls; HTTP 400/429/502/503; parse, transport, and unexpected failures; unchanged business JSON; sync/async/deferred outcomes; concurrency/nesting; redaction; exceptions/cancellation; callback identity; real reasoning and citation construction. Runs normal and optimized Python. |
| `ui_tests/test_v2_stream_citation_delivery.py` | Real send/SSE/store/MessageList/Sources path in Chromium, desktop/mobile live/reopened parity, successful and failed tool data, null results, unknown historical outcomes, escaped error text, web-only/empty sources, and moderation. |

All browser HTTP boundaries use synthetic fixtures; these tests do not
create live agents, actions, conversations, model calls, or connector requests.
The UI suite reuses the repository's Azure Playwright-compatible connection
fixture and ran locally without a remote service configured.

## Validation

| Command | Result |
| --- | --- |
| `node --test .\functional_tests\test_v2_stream_citation_delivery.mjs .\functional_tests\test_v2_m365_pending_actions_stream.mjs` | Passed: 60 tests, including 17 new evidence regressions. |
| `python -m pytest .\functional_tests\test_plugin_invocation_outcomes.py -q` | Passed: 4 normal/optimized subprocess cases, using an isolated compatible Python environment. |
| `python -m pytest .\ui_tests\test_v2_stream_citation_delivery.py .\ui_tests\test_v2_m365_source_citations.py .\ui_tests\test_v2_analysis_compare_citations.py -q` | Passed: 26 tests. |
| `npm --prefix .\application\v2_ui run typecheck` | Passed. |
| `npm --prefix .\application\v2_ui run build` | Passed; existing large-chunk warning remains. |
| `python .\scripts\build_docs_inventory.py` | Passed; generated inventory unchanged. |
| `python .\functional_tests\test_docs_app_surface_coverage.py` | Passed: 7 checks. |
| `python .\functional_tests\test_docs_site_quality.py` | Passed: 6 checks. |
| `node --test .\functional_tests\test_v2_stream_citation_delivery.mjs .\functional_tests\test_v2_m365_pending_actions_stream.mjs .\functional_tests\test_v2_orchestration_streaming_surface.mjs` | 65 passed; 1 pre-existing source-contract failure. |
| `python -m pytest .\functional_tests\test_plugin_invocation_outcomes.py .\functional_tests\test_v2_message_inspector.py .\functional_tests\test_privacy_logging_telemetry_audit.py::test_plugin_function_logger_uses_parameter_shapes -q` | 11 passed; 2 pre-existing source-contract failures. |

The existing OpenAPI allowed-operation tests also passed with outbound network
blocked. The changed product files passed the repository XSS-sink check,
and the UI detector reported no findings.

Broader pre-existing source-contract checks are not all green. Two assertions
in `test_v2_message_inspector.py` expect obsolete raw `jsonify(metadata)` and
`gap-3` source strings. One assertion in
`test_v2_orchestration_streaming_surface.mjs` expects streaming-ownership
fields in a specific source order. Each failing expression also fails against
the unchanged `HEAD` source; none is repaired or waived by the new behavior
tests.

The shared machine's `pyOpenSSL 25.3.0` / `cryptography 50.0.0` combination
prevented importing the full chat route. Real citation-builder integration
was validated in a session-local environment with compatible cryptography,
without changing application dependencies or the shared Python installation.

### Base synchronization in 0.261.367

The V2 base at `ef8da7beb` merged with only a `config.py` version conflict.
The combined version is **0.261.367**; both citation fixes are retained.
Post-merge validation passed the frontend production build, 60 stream tests,
30 Chromium tests covering tool/Search/Microsoft 365/Analyze citations,
7 documentation-coverage checks, and 6 site-quality checks.

The backend outcome, Search citation/delivery, dependency-citation, and
Search-result-integrity suites produced **75 passed, 1 failed** with external
network access blocked. The failure is the base's already documented
`test_checkpoint_child_keeps_original_grounded_citations_without_replaying_source`
checkpoint-recovery limitation (`result_producer_unavailable`), not a merge
conflict or a newly introduced behavior change. Backend and browser validation
used a temporary compatible Python environment without changing shared packages.

## Limitations

This change has not been deployed or verified against a new live UI acceptance
run. Live investigation was read-only. Historical incorrectly recorded
success values are not relabeled, and absent historical status remains unknown.
Other connectors must explicitly report returned execution failures to use
the new outcome contract; arbitrary result dictionaries are not classified.

External harness findings are retained separately as a session artifact, not
implemented here. There are no harness, retry-policy, deployment, authorization,
storage-schema, or historical-data changes in this fix.
