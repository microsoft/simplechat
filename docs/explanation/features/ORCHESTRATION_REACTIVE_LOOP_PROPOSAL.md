# Orchestration Harness Review and Reactive Loop Proposal

**Version: 0.261.458** (review of the code at 0.261.446)

Versions below were renumbered after Development was merged, because Development had used
0.261.448 to 0.261.450 for other work. Deployed builds keep the number they ran under in
telemetry: Phase 2 ran as 0.261.449 and the crash fix as 0.261.450.

Phase 2 was deployed and tested overnight on 17 November 2026. A planning crash that
predates this work ended 18 of 40 requests, so the phases below are not yet measured. The
crash is fixed in 0.261.454: see `../fixes/ORCHESTRATION_PREPARED_RELATE_PLANNING_CRASH_FIX.md`.

Implemented so far:

- Phase 0 (0.261.451): crash diagnostics and the telemetry scorecard. The live-model scenario suite is not built.
- Phase 1 (0.261.452): correction feedback for the prepared tabular calculation path only. See `../fixes/ORCHESTRATION_PROGRAM_CORRECTION_FEEDBACK_FIX.md`.
- Phase 2 (0.261.453): intent patterns and scenario wording removed, prompt sections sent by capability, three plan fields derived, corrections named. Strict structured output moved to Phase 3. See `../fixes/ORCHESTRATION_PLANNER_HEURISTICS_AND_DERIVATION_FIX.md`.

- Fix (0.261.456): a multi-file calculation planned without its preparation step is rejected in planning; the prompt now matches the capability. See `../fixes/ORCHESTRATION_PREPARED_CALCULATION_BINDING_FIX.md`.
- Phase 3, first part (0.261.457, off by default): progress ledger and one typed step recovery inside a run. Model-chosen recoveries, strict structured output and server-derived bindings are not built. See `ORCHESTRATION_PROGRESS_LEDGER.md`.
- Phase 3, second part (0.261.458, same setting): a failed run is followed by its next attempt without sign-off when that attempt stays inside the approved plan. The successors are the two the server already defined; a plan the model rewrites after a failure is not built.

Second test run, 17-18 November 2026 (deployed as 0.261.450, 90 requests): no planning
crashes; 2 requests could not be planned (25 of 181 in the baseline); 1 second-round
correction (15 of 64); 50 of 86 runs completed, 58% against 59%. Failures moved from planning
to execution: 19 at the calculation step, 7 where the answer step refused a partial analysis.

Status: proposal for discussion.

## 1. Evidence

### 1.1 Live telemetry, 9-16 November 2026 (versions 0.261.424 to 0.261.444)

Source: Application Insights for the beta deployment. This is test traffic; the same scenarios repeat across versions.

| Stage | Count |
| --- | --- |
| Requests accepted for planning | 181 |
| Requests that could not be planned | 25 |
| Planner correction rounds | 64 (49 first, 15 second) |
| Runs with a recorded outcome | 138 |
| Runs completed | 82 |
| Runs failed or partial | 54 |

Plan rejections sent back to the planner, by rule:

| Rule | Count |
| --- | --- |
| `relational_spec_invalid` | 14 |
| `unknown_argument` | 13 |
| `selected_documents_missing` | 12 |
| `argument_schema_invalid` | 12 |
| `tabular_complete_policy_required` | 5 |
| `step_shape_invalid` | 4 |
| `outputs_list_required` | 2 |
| `native_query_unsupported`, `plan_step_budget` | 1 each |

Run failures, by cause:

| Cause | Count |
| --- | --- |
| `action_invoke`: `document_action_read_failed` | 22 |
| `tabular_analyze`: `result_invalid` (column missing, schema changed, ambiguous match, empty numeric, bad date, incompatible types) | 16 |
| `compose`: `completeness_incomplete` | 7 |
| Other, one or two each | 9 |

### 1.2 Code findings

- **The plan is compiled once and walked once.** `functions_orchestration_executor.py` states that re-planning is "surfaced, not performed". A failed required step fails the run. `chat_orchestration_max_replans` bounds hints that nothing consumes.
- **The planner must author the whole contract before any data is seen.** One JSON reply carries steps, input bindings, output kinds, deliverables, `final_response` and complete tabular relational specs. Two shared corrections are allowed.
- **Prompt size.** `PLANNER_SYSTEM_PROMPT` is about 31,700 characters. The capability registry source is about 69,000 characters across 24 capabilities. Five workflow instruction blocks and `SOURCE_PLANNING_INSTRUCTIONS` are appended on top.
- **Scenario patches in prompts.** Examples: the ride eating-and-drinking timeline, "call signs", "the first three presidents", "exercise labels and evidence rules" (planner prompt); "dated monetary determination" and "exceedance" (`CALCULATION_ANSWER_INSTRUCTIONS`); "call signs" again (`CONVERSATION_POLICY`); the `query_expression="index == index"` recipe appended inline in `plan_request`.
- **Keyword heuristics in code.** `ACKNOWLEDGMENT_PATTERN`, `TRANSFORMATION_PATTERN`, `CONVERSATION_TARGET_PATTERN` and `EXPLICIT_RETRIEVAL_PATTERN` in `functions_orchestration_planner.py` decide whether retrieval is allowed. `functions_tabular_orchestration.py` and `functions_mixed_source_orchestration.py` hold question keyword lists; whether those run on the orchestration path was not verified.
- **Crashes are not diagnosable.** The catch-all in `route_backend_orchestration.py` (`'[ORCHESTRATION] Planning failed.'`) logs only the exception type, which telemetry redacts to its length, with no traceback and no conversation hash. Conversation `d38474f4` failed this way during validation of the second proposal. The exception was not identified.
- **Tests check contracts.** 223 `test_orchestration*` functional files and 34 V2 orchestration UI files, 26 of which intercept network calls. One opt-in script evaluates a real model, for research selection only.

### 1.3 Not yet examined

- Conversation `61979ec2` (no telemetry under its ID in the 7-day window).
- The conversations as rendered in the UI.
- The Copilot worktree history and its scenario catalog.
- GitHub Copilot SDK source (search summaries only).

## 2. What other harnesses do

| Harness | How work proceeds | Failure handling | Policy |
| --- | --- | --- | --- |
| Microsoft Agent Framework, Magentic | Manager writes a task ledger (facts and plan), then a progress ledger each round: request satisfied, in a loop, progress being made, next speaker, instruction | Stall counter; exceeding it resets and replans. Defaults in the docs sample: 10 rounds, 3 stalls, 2 resets | Optional human plan review on the initial plan and on stall-triggered replans; checkpoints at each superstep, with a Cosmos store |
| OpenClaw | Serialized per-session loop: model call, tool call, result, repeat | Failed tools are reported back to the model through the transcript; bounded retry budget; one native correction for a malformed tool call | `before_tool_call` can block a call; arguments validated against each tool's schema |
| GitHub Copilot SDK | Reactive tool loop in the Copilot CLI; the plan is an editable document | Not examined in source | Pre and post tool hooks, permission handler, `ask_user` tool |

Shared shape: the model chooses one action at a time with real results in view, a tool error is an observation the model can act on, and policy is enforced when a tool is called.

SimpleChat already exceeds these in server-owned authorization, typed retained results, re-checks at run time and durable checkpoints. Those stay.

## 3. Proposal

Keep the framework. Change who decides what, and when.

### 3.1 Principles

1. **The plan is a ledger, not a contract.** The planner states intent-level steps: goal, capability, sources. The user approves that. It carries no bindings, output kinds or tool arguments.
2. **Arguments are authored when the step runs.** The model writes a capability's arguments after earlier results exist, through strict function-calling schemas generated from the registry. A tabular relational spec is written after inspection has returned the real headers.
3. **A failure is an observation.** A typed step error goes back to the model, which may correct the arguments, choose another capability, or ask the user. Bounded by per-step retries, a round limit, a stall limit and the existing time budgets.
4. **Policy is code at call time.** Capability gates, source authorization, approval floors and budgets run as one gate before each step. A revision that adds an effectful capability or a source outside the approved scope pauses for approval, using the existing plan revision store.
5. **The server derives what it can know.** Result bindings (by handle from a server-supplied list), deliverables (from render and image steps that ran), `final_response` (the last compose), and selected-source coverage (reported as an observation before finishing, not as a plan rejection).
6. **No heuristics.** No scenario wording in any prompt, no regular expressions or keyword lists that classify user intent. Capability guidance lives only in that capability's registry descriptor and is sent only when the capability is offered.

### 3.2 Loop

```
plan (ledger) -> approve -> repeat:
    assess   : satisfied? progressing? next step      (progress ledger)
    act      : one capability call, schema-checked    (gate, then adapter)
    observe  : typed result summary or typed error    (retained result handle)
    revise   : update ledger; pause if scope grows
until satisfied, stalled past limit, cancelled or out of budget -> render and report
```

Gather, Reason and Render remain the purposes of steps. The loop decides their order from results.

### 3.3 Phases

| Phase | Change | Targets in the baseline |
| --- | --- | --- |
| 0 | Log traceback, exception class and conversation hash on every catch-all; build a scenario suite that drives the real planner and executor against a live model and reports plan rate, completion rate, corrections and rounds per version | The undiagnosable crash; no behavioural measure today |
| 1 | Inside the current executor: author `tabular_analyze` and `action_invoke` arguments at step start, and on a typed repairable error re-author that step with the error in view, at most twice | 16 tabular run failures, 14 `relational_spec_invalid` rejections, part of the 22 action read failures |
| 2 | Server derives the plan fields that have one valid value; corrections name what was wrong; prompt sections sent by offered capability; all scenario text and intent patterns removed; a test fails the build when they return | 31 argument and shape rejections; 12 `selected_documents_missing` |
| 3 | Round-based controller with a progress ledger and mid-run plan revision, behind a setting, measured against Phase 0 numbers before becoming default. Per-step arguments through strict structured output; server-derived bindings (both moved here from Phase 2) | Remaining failed and partial runs |
| 4 | Retire validator rules and repair paths the loop made unnecessary | Churn |

Each phase is accepted on the Phase 0 suite's rates, not on contract tests alone.

### 3.4 Build or adopt

Recommendation: build the loop in the existing engine and borrow the Magentic ledger design. Magentic selects among agents; this harness selects among gated capabilities with retained results, which is where its value lies. Agent Framework workflows remain an option for the saved-workflow engine.

## 4. Open decisions

1. Decided 18 November 2026: a change inside the approved scope continues without sign-off; scope growth, external actions and anything needing confirmation wait for the user.
2. Round, stall and retry limits, and whether administrators can set them.
3. Whether Phase 1 ships before the Phase 0 suite exists.

## 5. Open items

A running list. An item is added when a rerun or a review finds it, and marked closed with
the version that closed it once a rerun confirms the fix. "Fixed" without a confirming rerun
stays open.

Last updated: 21 November 2026, at 0.261.477 (not yet deployed), from the 0.261.476 rerun
while it was still in progress (7 of 13 scenarios, 38 runs: 16 completed, 22 partial, 0
failed).

0.261.476 was written and reviewed as 0.261.474. Development used 0.261.474 and 0.261.475 for
other work before it merged, so it was renumbered.

### 5.1 Open

| # | Item | Found | State |
|---|---|---|---|
| 1 | Document analysis finishes partial on every run seen, with full coverage and the same number of limitations. A partial analysis has no `records` output and its consumers refuse it, so this is behind the compose refusals (the largest group of partial runs) and `result_output_missing`. | 0.261.472 and 0.261.473 reruns | Changed in 0.261.477. Cause: the analysis model reports what it could not conclude, and the validator made the analysis partial for any such report (a slice-level statement in 8 of 9 partial analyses on 0.261.476, a finding-level one in 6 of 9). Now, when every source was read, a gap the model states is reported and the analysis is complete; a finding it did not conclude is still not a record. Unread sources and findings the validator refuses (3 of 9) are still partial. A finding the model supports with one thing it could not settle is kept, with that statement on it. Every step that reads the analysis is given the statements as limitations, not only one that reads the report. Not guarded: a calculation over record values is not stopped by a statement on a record. See `DOCUMENT_ANALYSIS_STATED_GAP_FIX.md`. Open until a rerun shows analyses complete with `stated_gap_count` set. |
| 2 | One tabular scenario does not converge: told three times that an aggregate met a non-numeric value, the author does not correct it, on two attempts. | 0.261.473 rerun | Not investigated. Seen again on 0.261.476: the same aggregate measure met text in two conversations; one completed on its second attempt, one did not. |
| 3 | Follow-up prompts are refused the tabular source at planning (`source_unavailable`, `document_authorization_required`). | 0.261.472 and 0.261.473 reruns | Not investigated. Once on 0.261.476. |
| 4 | A join whose matches contradict its declared cardinality is not returned to the calculation's author. | 0.261.468 rerun | Changed in 0.261.477: the three cardinality checks are returned with the side that repeats (3 runs on 0.261.476 stopped here). An overlapping effective interval is still refused. Open until a rerun shows it returned and corrected. |
| 5 | An effective-date column must hold `YYYY-MM-DD`; a date written another way is not read as a date. | 0.261.476 review | Known limit. The finding is returned to the author from 0.261.476. |
| 7 | `context_unavailable` after waiting. | 0.261.472 rerun (2 runs); not seen on 0.261.473 or 0.261.476 | Unexplained |
| 8 | The model call itself failed in a calculation (`model_failed`). | 0.261.468 rerun (4 runs); once on 0.261.476, where the second attempt completed | Unexplained |
| 9 | Three more calculation faults returned to the author (shared column names, datasets that are not the planned documents, a non-date effective value). | 0.261.472 and 0.261.473 reruns | Changed in 0.261.476. Shared column names was returned once and corrected (0.261.476 rerun). The other two have not occurred since. |
| 10 | Eleven functional test files have failures that predate this work, and three more stall or fail the same way on earlier commits (`test_action_credentials_chat_reconstruction.py`, `test_tabular_row_orchestration_scale.py`, `test_orchestration_research_selection.py`). | 0.261.470 to 0.261.476 test runs | Not investigated |
| 11 | Release notes for 0.261.468 to 0.261.476. | | Deferred |
| 12 | A full run of all 30 scenarios. | | Due after items 1 to 3 have fixes |
| 13 | A calculation's author spends all three calls on faults in the shape of the program (`relational_spec_invalid` for schema or transform, `relational_source_unused`), and the run ends `calculation_program_invalid` with no next attempt offered. | 0.261.476 rerun (6 runs) | Changed in 0.261.477: such an attempt may have a next attempt, within the round limit and the stall check. The next attempt does not carry the last program or its finding forward. Open until a rerun shows a next attempt start and complete. |
| 14 | After a calculation's second attempt, compose stops with `result_tabular_calculation_incomplete`, twice, to the round limit. | 0.261.476 rerun (1 conversation) | Not investigated |
| 15 | A follow-up is refused at planning with `plan_arguments_invalid` (`tabular_requirement_sources_invalid`). | 0.261.476 rerun (1) | Not investigated |

### 5.2 Closed

| Item | Closed in | Confirmed by |
|---|---|---|
| The server could not start a next attempt for a run that recalled saved memory (`execution_binding_changed`). | 0.261.468 | 0.261.468 rerun: 10 next attempts prepared, 1 refused |
| A calculation that failed on the data was not told why, and formatted numbers were not numbers. | 0.261.470, 0.261.471 | 0.261.472 and 0.261.473 reruns: findings returned 10 times each, second attempts completing |
| A waiting run could not be resumed for a caller holding an app role (`recovery_changed`). | 0.261.476 | 0.261.476 rerun: 3 runs waited and all 3 resumed; 38 bindings saved, none changed, each with `role_gated_action_count` 1, which confirms the inferred cause |
| New diagnostic fields reached the log as lengths only. | 0.261.473 | 0.261.473 rerun: binding parts, correction categories and output lists readable |
