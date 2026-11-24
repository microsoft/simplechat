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
| 2 | Server derives the plan fields that have one valid value; corrections name what was wrong; prompt sections sent by offered capability; all scenario text and intent patterns removed; a test fails the build when they return | Not investigated. On 0.261.477 an aggregate met text twice (`numeric_value_is_invalid`, `aggregate_measure`); both were returned to the author and neither prompt completed. A comparison between a number and text or an empty cell ended two more attempts. |
| 3 | Round-based controller with a progress ledger and mid-run plan revision, behind a setting, measured against Phase 0 numbers before becoming default. Per-step arguments through strict structured output; server-derived bindings (both moved here from Phase 2) | Remaining failed and partial runs |
| 4 | Retire validator rules and repair paths the loop made unnecessary | Changed in 0.261.477: the three cardinality checks are returned with the side that repeats. Not exercised by the 0.261.477 run: no join contradicted its cardinality. Open until one does. |

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

Last updated: 22 November 2026, from the 0.261.478 run (27 conversations, 16:37 to 17:46 UTC).
Of 61 prompts the harness ran, 50 completed, 9 ended partial and 2 failed (74 runs counting
next attempts). Five more prompts were refused at planning, and 10 were answered outside the
harness (9 completed, 1 `stream_failed`). The 0.261.477 run had 51 of 62 completed, 8 partial
and 3 failed, with 2 refused at planning.

Most text fields added to the logs in 0.261.478 did not reach telemetry: their keys were not
on the telemetry allow-list. Fixed in 0.261.480 (`DIAGNOSTIC_RULE_FIELDS_TELEMETRY_FIX.md`).
Where an item below says a field "will show", that needs a run on 0.261.480 or later.

0.261.476 was written and reviewed as 0.261.474. Development used 0.261.474 and 0.261.475 for
other work before it merged, so it was renumbered.

### 5.1 Open

| # | Item | Found | State |
|---|---|---|---|
| 2 | One tabular scenario does not converge: told three times that an aggregate met a non-numeric value, the author does not correct it, on two attempts. | 0.261.473 rerun | Not investigated. Seen again on 0.261.476: the same aggregate measure met text in two conversations; one completed on its second attempt, one did not. On 0.261.477 a numeric value that is text, empty or boolean was returned 11 times and ended 2 attempts; with a comparison between incompatible types (2) and an empty date (2, item 21) these are the data-fit faults that remain. On 0.261.478 a numeric value that is text was returned 8 times; one attempt was told it three times and ended there, and the prompt ended partial after two attempts. From 0.261.481 the record of a returned finding says where it is and whether it repeats the one the author already held, so the next run shows whether that was one place or three. |
| 3 | Follow-up prompts are refused the tabular source at planning (`source_unavailable`, `document_authorization_required`). | 0.261.472 and 0.261.473 reruns | Changed in 0.261.481. Five times on 0.261.478. Cause: the plan named a document ID outside the documents the request may read, and that refusal was not one the planner is asked to correct, so planning ended on the first proposal with two corrections unused. In the two turns traced, one had three documents selected and named a fourth ID, and one had no selection and named nine documents with fifteen candidates. The refusal is now returned to the planner with the IDs it named; the set a plan may name is unchanged. See `PLAN_DOCUMENT_UNAVAILABLE_CORRECTION_FIX.md`. Open until a rerun shows it corrected. |
| 4 | A join whose matches contradict its declared cardinality is not returned to the calculation's author. | 0.261.468 rerun | Changed in 0.261.477: the three cardinality checks are returned with the side that repeats (3 runs on 0.261.476 stopped here). An overlapping effective interval is still refused. Open until a rerun shows it returned and corrected. |
| 5 | An effective-date column must hold `YYYY-MM-DD`; a date written another way is not read as a date. | 0.261.476 review | Known limit. The finding is returned to the author from 0.261.476. |
| 7 | `context_unavailable` after waiting. | 0.261.472 rerun (2 runs); not seen on 0.261.473 or 0.261.476 | Changed in 0.261.482. Twice on 0.261.478 (one reported as `result_unavailable`), of 5 runs that waited. Every run that waited had paused on a pending spreadsheet computation and was resumed by the scheduler, which has no session; a result that names an external source is authorized against the session on every read, so that resume could only fail. A paused run now records whether its results need a session; the scheduler leaves such a run alone and the request that started it continues it on its own worker. The session requirement is unchanged. If that worker is lost the run is closed at its deadline; a signed-in continue route for the browser is not built. See `PAUSED_RUN_SESSION_CONTINUATION_FIX.md`. Open until a rerun shows a marked run continued. |
| 9 | Three more calculation faults returned to the author (shared column names, datasets that are not the planned documents, a non-date effective value). | 0.261.472 and 0.261.473 reruns | Changed in 0.261.476. Shared column names was returned once and corrected (0.261.476 rerun). The other two have not occurred since. |
| 10 | Eleven functional test files have failures that predate this work, and three more stall or fail the same way on earlier commits (`test_action_credentials_chat_reconstruction.py`, `test_tabular_row_orchestration_scale.py`, `test_orchestration_research_selection.py`). | 0.261.470 to 0.261.476 test runs | Not investigated |
| 11 | Release notes for 0.261.468 to 0.261.476. | | Deferred |
| 12 | A full run of all 30 scenarios. | | Run on 0.261.477 as 28 scenarios: 51 of 62 prompts completed. The two service-now scenarios were left out and have not been run. Run again on 0.261.478: 50 of 61 completed. |
| 14 | After a calculation's second attempt, compose stops with `result_tabular_calculation_incomplete`, twice, to the round limit. | 0.261.476 rerun (1 conversation) | Not investigated. Not seen on 0.261.477. |
| 15 | A follow-up is refused at planning with `plan_arguments_invalid` (`tabular_requirement_sources_invalid`). | 0.261.476 rerun (1) | Not investigated. On 0.261.477 one follow-up was refused at planning with `source_binding_required` (`document_sources_required`), and one prompt after three planning tries with `deliverables_invalid` (`available_deliverable_declined`; the first two tries were refused for `invalid_unavailable_reason`). A prompt refused at planning records no execution outcome. Not seen on 0.261.478. |
| 17 | A calculation's author still spends all three calls on program-shape faults (`relational_spec_invalid` for schema, transform or predicate, `relational_source_unused`, `relational_column_missing`), attempt after attempt, to the round limit. The next attempt starts without the last program or its finding. | 0.261.477 run (2 conversations to the round limit, and most second attempts; `relational_column_missing` was returned 12 times and `relational_spec_invalid` 24) | Changed in 0.261.478: the first call of a next attempt is given the previous attempt's last program and its finding. Only the last program is carried. Open until a rerun shows the carried record and fewer repeated findings. On 0.261.478 the program was carried into 11 next attempts: 5 completed and 6 failed again. `relational_spec_invalid` was returned 18 times and `relational_column_missing` 9, of 57 findings. Five prompts still ended partial on a calculation (7 on 0.261.477). |
| 19 | The completeness check on a composed answer is unavailable (`completeness_unavailable`), on both attempts. | 0.261.477 run (1 prompt) | Explained by the existing log: the check's input does not fit the model's input budget (`WorkflowContextBudgetError`), so checking again fails the same way, on every attempt. Not fixed: whether an answer whose check cannot run is delivered with a note or withheld is a product decision, and the size of the overrun and the source of the limit are not known until the next run logs them. From 0.261.478 the log carries the token counts and where the limit came from. Not seen on 0.261.478 (one check was unavailable for an invalid candidate reference, and its run completed). On 0.261.478 a different compose failure appeared: item 25. |
| 20 | An action step fails (`step_failed`, `document_action_read_failed`); a next attempt needs confirmation and is not started. | 0.261.477 run (2 prompts) | Partly explained by the existing log. `document_action_read_failed`: the fourth read was refused because the document record's storage revision had changed under a paging cursor (`native_cursor_revision_changed`), with nothing to show the bytes had. Changed in 0.261.478: the cursor is bound to the document, its uploaded version and its bytes, not the record revision. See `NATIVE_INSPECTION_CURSOR_REVISION_FIX.md`. `step_failed`: stopped on the first function call, before any source was read, by a check that did not say which. From 0.261.478 every such stop names its rule (`failure_rule`). Not fixed. On 0.261.478 one action read failed again, not on a cursor: the accessibility report raised a `ValueError` on its first call, 51 ms in, with two documents bound, and logged the class name only. From 0.261.480 that log carries the application frames that raised. No `step_failed` on 0.261.478. |
| 21 | A calculation meets an empty date cell (`date_value_is_empty`): returned to the author once per attempt, on the last call, and not corrected, to the round limit. The first attempt of the same prompt spent its three calls on a missing join key column. | 0.261.477 run (1 prompt, 2 attempts) | Not changed directly. From 0.261.478 the next attempt starts with the program that met the empty cell and that finding (item 17). Same family as item 2. On 0.261.478 an empty date was returned twice; one prompt completed on its second attempt, from the carried program. |
| 22 | Outside the harness (direct chat), the tabular plugin refuses a selection (`TabularSelectionError`) 177 times in two conversations, 23 to 39 times within one answer, and one of those answers ends `stream_failed`. The event carried no code or operation. | 0.261.477 run | Not investigated. Not harness code. From 0.261.478 the event carries the selection rule, the plugin function and the number of choices offered back. On 0.261.478: 254 refusals in three conversations, each offering back zero choices. The code was dropped by the telemetry allow-list and the operation named a worker closure; both fixed in 0.261.480. |
| 23 | An offer of a next attempt is recorded two or three times for the same run, and again when the conversation is opened later. | 0.261.477 run | Not investigated. Telemetry only as far as seen. |
| 24 | A run that fails on the scheduler gets no automatic next attempt, although the server says one is offered: the next attempt is started by a hook bound to the request, which a scheduler failure never reaches. | 0.261.478 run (1 run, offered and never started) | From 0.261.482 a paused run that needs a session ends on its request's worker, so its failure reaches the hook. A run the scheduler resumes and fails is unchanged. |
| 25 | A composed answer is judged incomplete (`completeness_incomplete`); checking again does not recover it, on two attempts. | 0.261.478 run (1 prompt) | Not investigated. One of its three inputs had a citation that could not be located. |
| 26 | A document analysis finishes partial on findings the validator refused and its prompt ends `result_partial`. | 0.261.478 run (2 turns in 1 conversation; 4 partial analyses in the run) | Not investigated. The compose step accepted the partial input and the answer was delivered as partial. |
| 27 | An invalid date in the column a cumulative sum is ordered by ended the run with two authoring calls unused: the finding was not one returned to the author. | 0.261.478 run (1 prompt) | Changed in 0.261.481: returned to the author, like the effective-date column. Open until a rerun shows it returned. |
| 28 | A paused run that needs a session is continued only by the worker of the request that started it. If that worker is lost during the pause (a restart, a deploy, a scale event), nothing continues the run and it is closed at its deadline as `run_timeout`. The continuation also uses the identity captured when the run started, so a role removed during the pause is not seen. | 0.261.482 design (not observed in a run; how often a restart lands inside a pause is not measured) | Not built, by decision: wait for a rerun to show the 0.261.482 continuation working first. The follow-up is a signed-in continue route the browser calls for its own paused run, which continues it with the session as it is at that moment. It needs a new route (ownership check, refusal of a run already claimed, no two continuations at once) and a client change in `application/v2_ui`, which is a separate build. The waits for credentials and for the user's answer are already continued this way and are the pattern to follow. |

### 5.2 Closed

| Item | Closed in | Confirmed by |
|---|---|---|
| The server could not start a next attempt for a run that recalled saved memory (`execution_binding_changed`). | 0.261.468 | 0.261.468 rerun: 10 next attempts prepared, 1 refused |
| A calculation that failed on the data was not told why, and formatted numbers were not numbers. | 0.261.470, 0.261.471 | 0.261.472 and 0.261.473 reruns: findings returned 10 times each, second attempts completing |
| A waiting run could not be resumed for a caller holding an app role (`recovery_changed`). | 0.261.476 | 0.261.476 rerun: 3 runs waited and all 3 resumed; 38 bindings saved, none changed, each with `role_gated_action_count` 1, which confirms the inferred cause |
| Document analysis finished partial on nearly every run, although every source was read, because any gap the model stated made it partial. | 0.261.477 | 0.261.477 run: 1 analysis finished partial (9 on 0.261.476), on a finding the validator refused, and its run completed. No run ended partial on an analysis. Not confirmed directly: a complete analysis does not log its stated-gap count. |
| An attempt that used all its authoring calls on returnable findings had no next attempt (`calculation_program_invalid`). | 0.261.477 | 0.261.477 run: 6 next attempts started after `calculation_program_invalid`; 3 prompts completed on a second or third attempt (a fourth completed on a second attempt after `result_invalid`). |
| New diagnostic fields reached the log as lengths only. | 0.261.473 | 0.261.473 rerun: binding parts, correction categories and output lists readable |
| The model call itself failed in a calculation (`model_failed`), 4 times on 0.261.477. | 0.261.478 | 0.261.478 run: no `model_failed`. Three replies that ended before a whole program were asked again inside the loop. The rule field itself did not reach telemetry until 0.261.480. |
| A finished calculation was refused by the result contract (`result_schema_invalid`). | 0.261.478 | 0.261.478 run: none. |
| An invalid key cell in an allocation ended the run without being returned to the author. | 0.261.478 | 0.261.478 run: `relational_key_invalid` (`event_key`) returned once, and the attempt had a next one. |
| Whether a complete document analysis stated gaps was not logged. | 0.261.478 | 0.261.478 run: 13 complete analyses logged between 1 and 20 stated gaps each. |
