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

Last updated: 24 November 2026, from the 0.261.482 run (29 conversations, 14:43 to 22:33 UTC,
in two sittings). Of 79 prompts the harness ran, 63 completed, 12 ended partial, 3 failed and 1
was cancelled by the user (97 runs counting next attempts). One more prompt was refused at
planning, and 11 were answered outside the harness (8 completed, 3 `stream_failed`). The
0.261.478 run had 50 of 61 completed, 9 partial and 2 failed, with 5 refused at planning.

How the 16 prompts that did not complete ended: 5 on a calculation (and the cancelled one was
in a calculation's second attempt), 3 on a completeness check that could not run (item 19), 3
on a partial document analysis (item 26), 2 on an action read (item 20), 1 on a composed answer
judged incomplete (item 25) and 1 on an answer that was not found after it was saved (item 29).

Most text fields added to the logs in 0.261.478 did not reach telemetry: their keys were not
on the telemetry allow-list. Fixed in 0.261.480 (`DIAGNOSTIC_RULE_FIELDS_TELEMETRY_FIX.md`).
Where an item below says a field "will show", that needs a run on 0.261.480 or later.

Changed in 0.261.490 and not yet run: items 19 (sizes logged), 20 (Word comment request) and 31
(export call). Item 33 and section 6 record the redesign that follows.

0.261.476 was written and reviewed as 0.261.474. Development used 0.261.474 and 0.261.475 for
other work before it merged, so it was renumbered.

### 5.1 Open

| # | Item | Found | State |
|---|---|---|---|
| 2 | One tabular scenario does not converge: told three times that an aggregate met a non-numeric value, the author does not correct it, on two attempts. | 0.261.473 rerun | Not investigated. Seen again on 0.261.476: the same aggregate measure met text in two conversations; one completed on its second attempt, one did not. On 0.261.477 a numeric value that is text, empty or boolean was returned 11 times and ended 2 attempts; with a comparison between incompatible types (2) and an empty date (2, item 21) these are the data-fit faults that remain. On 0.261.478 a numeric value that is text was returned 8 times; one attempt was told it three times and ended there, and the prompt ended partial after two attempts. From 0.261.481 the record of a returned finding says where it is and whether it repeats the one the author already held, so the next run shows whether that was one place or three. On 0.261.482 the finding record shows it is one place: in two runs the same aggregate measure at the same step met text, was returned, and was returned again unchanged (`correction_repeated`). A numeric value that is text was returned 13 times and one that is empty or boolean 7 times, of 72 findings; two prompts ended partial on one. |
| 4 | A join whose matches contradict its declared cardinality is not returned to the calculation's author. | 0.261.468 rerun | Changed in 0.261.477: the three cardinality checks are returned with the side that repeats (3 runs on 0.261.476 stopped here). An overlapping effective interval is still refused. Open until a rerun shows it returned and corrected. |
| 5 | An effective-date column must hold `YYYY-MM-DD`; a date written another way is not read as a date. | 0.261.476 review | Known limit. The finding is returned to the author from 0.261.476. |
| 9 | Three more calculation faults returned to the author (shared column names, datasets that are not the planned documents, a non-date effective value). | 0.261.472 and 0.261.473 reruns | Changed in 0.261.476. Shared column names was returned once and corrected (0.261.476 rerun). The other two have not occurred since. |
| 10 | Eleven functional test files have failures that predate this work, and three more stall or fail the same way on earlier commits (`test_action_credentials_chat_reconstruction.py`, `test_tabular_row_orchestration_scale.py`, `test_orchestration_research_selection.py`). | 0.261.470 to 0.261.476 test runs | Not investigated |
| 11 | Release notes for 0.261.468 to 0.261.476. | | Deferred |
| 12 | A full run of all 30 scenarios. | | Run on 0.261.477 as 28 scenarios: 51 of 62 prompts completed. The two service-now scenarios were left out and have not been run. Run again on 0.261.478: 50 of 61 completed. Run again on 0.261.482: 63 of 79 completed. |
| 14 | After a calculation's second attempt, compose stops with `result_tabular_calculation_incomplete`, twice, to the round limit. | 0.261.476 rerun (1 conversation) | Not investigated. Not seen on 0.261.477. |
| 15 | A follow-up is refused at planning with `plan_arguments_invalid` (`tabular_requirement_sources_invalid`). | 0.261.476 rerun (1) | Not investigated. On 0.261.477 one follow-up was refused at planning with `source_binding_required` (`document_sources_required`), and one prompt after three planning tries with `deliverables_invalid` (`available_deliverable_declined`; the first two tries were refused for `invalid_unavailable_reason`). A prompt refused at planning records no execution outcome. Not seen on 0.261.478. |
| 17 | A calculation's author still spends all three calls on program-shape faults (`relational_spec_invalid` for schema, transform or predicate, `relational_source_unused`, `relational_column_missing`), attempt after attempt, to the round limit. The next attempt starts without the last program or its finding. | 0.261.477 run (2 conversations to the round limit, and most second attempts; `relational_column_missing` was returned 12 times and `relational_spec_invalid` 24) | Changed in 0.261.478: the first call of a next attempt is given the previous attempt's last program and its finding. Only the last program is carried. Open until a rerun shows the carried record and fewer repeated findings. On 0.261.478 the program was carried into 11 next attempts: 5 completed and 6 failed again. `relational_spec_invalid` was returned 18 times and `relational_column_missing` 9, of 57 findings. Five prompts still ended partial on a calculation (7 on 0.261.477). On 0.261.482 the program was carried into 13 next attempts: 5 completed and 8 failed again. `relational_spec_invalid` was returned 13 times (4 of them unchanged from the finding the author already held), `relational_column_missing` 12, `relational_match_ambiguous` 9 and `relational_source_unused` 7, of 72 findings. Five prompts ended partial on a calculation. |
| 19 | The completeness check on a composed answer is unavailable (`completeness_unavailable`), on both attempts. | 0.261.477 run (1 prompt) | Open, and a product decision. Three prompts on 0.261.482, each on both attempts (none on 0.261.478, 1 on 0.261.477). The check's input does not fit the model's input budget (`WorkflowContextBudgetError`; limit known, from the model catalog; 5 or 6 pieces of evidence). Checking again fails the same way and so does the next attempt, which recomposes and meets the same limit. The sizes are still not in telemetry: the counts were logged under names containing `token`, which the telemetry filter treats as a secret and replaces with a present flag. Undecided: whether an answer whose check cannot run is delivered with a note, withheld, or checked against reduced evidence. Decided 25 November 2026: none of the three. The check is to be redesigned so that it does not need all the evidence in one call (section 6); not built. Changed in 0.261.490: the sizes are logged under names telemetry keeps, with how they were counted (`size_estimator`). When a model has no tokenizer known to the application the budget counts UTF-8 bytes as an upper bound, which is several times the token count for ordinary text; whether the three failed checks were counted that way is not known until a run on 0.261.490. |
| 20 | An action step fails (`step_failed`, `document_action_read_failed`); a next attempt needs confirmation and is not started. | 0.261.477 run (2 prompts) | Partly explained by the existing log. `document_action_read_failed`: the fourth read was refused because the document record's storage revision had changed under a paging cursor (`native_cursor_revision_changed`), with nothing to show the bytes had. Changed in 0.261.478: the cursor is bound to the document, its uploaded version and its bytes, not the record revision. See `NATIVE_INSPECTION_CURSOR_REVISION_FIX.md`. `step_failed`: stopped on the first function call, before any source was read, by a check that did not say which. From 0.261.478 every such stop names its rule (`failure_rule`). Not fixed. On 0.261.478 one action read failed again, not on a cursor: the accessibility report raised a `ValueError` on its first call, 51 ms in, with two documents bound, and logged the class name only. From 0.261.480 that log carries the application frames that raised. No `step_failed` on 0.261.478. On 0.261.482 the same failure twice in one conversation, and the 0.261.480 log names it: the accessibility report was asked for the comments of a Word file together with a non-default `native_section`, a cursor or a worksheet filter, and `get_document_accessibility_payload` refuses that combination with a plain `ValueError`. A plain error ends the step; the neighbouring refusal (comments asked of a format that has none) is typed and is returned to the action's model once for correction before any read. Both prompts failed, and a next attempt needs confirmation. Changed in 0.261.490: the Word refusal is typed, is checked before any read, and is returned to the action's model once with the names of the refused arguments (`WORD_COMMENT_REQUEST_AND_BUDGET_SIZE_TELEMETRY_FIX.md`). Open until a rerun shows it returned and corrected. Still a plain error, and not observed: PDF and PowerPoint inspection refusing a worksheet filter. |
| 21 | A calculation meets an empty date cell (`date_value_is_empty`): returned to the author once per attempt, on the last call, and not corrected, to the round limit. The first attempt of the same prompt spent its three calls on a missing join key column. | 0.261.477 run (1 prompt, 2 attempts) | Not changed directly. From 0.261.478 the next attempt starts with the program that met the empty cell and that finding (item 17). Same family as item 2. On 0.261.478 an empty date was returned twice; one prompt completed on its second attempt, from the carried program. On 0.261.482 returned 4 times; one prompt completed on its second attempt. |
| 22 | Outside the harness (direct chat), the tabular plugin refuses a selection (`TabularSelectionError`) 177 times in two conversations, 23 to 39 times within one answer, and one of those answers ends `stream_failed`. The event carried no code or operation. | 0.261.477 run | Not investigated. Not harness code. From 0.261.478 the event carries the selection rule, the plugin function and the number of choices offered back. On 0.261.478: 254 refusals in three conversations, each offering back zero choices. The code was dropped by the telemetry allow-list and the operation named a worker closure; both fixed in 0.261.480. On 0.261.482 the fields are there: 243 refusals in three conversations, 142 `table_selection_invalid` and 101 `header_selection_invalid`, across `filter_rows`, `query_tabular_data`, `count_rows`, `search_rows` and `aggregate_column`, each offering back zero choices. The three `stream_failed` answers are a different fault: item 30. |
| 23 | An offer of a next attempt is recorded two or three times for the same run, and again when the conversation is opened later. | 0.261.477 run | Not investigated. Telemetry only as far as seen. |
| 24 | A run that fails on the scheduler gets no automatic next attempt, although the server says one is offered: the next attempt is started by a hook bound to the request, which a scheduler failure never reaches. | 0.261.478 run (1 run, offered and never started) | From 0.261.482 a paused run that needs a session ends on its request's worker, so its failure reaches the hook. A run the scheduler resumes and fails is unchanged. On 0.261.482 the one marked run that failed after its pause was followed by its next attempt, as intended. No run failed on the scheduler. |
| 25 | A composed answer is judged incomplete (`completeness_incomplete`); checking again does not recover it, on two attempts. | 0.261.478 run (1 prompt) | Not investigated. One of its three inputs had a citation that could not be located. Once on 0.261.482, again on both attempts. Not investigated. |
| 26 | A document analysis finishes partial on findings the validator refused and its prompt ends `result_partial`. | 0.261.478 run (2 turns in 1 conversation; 4 partial analyses in the run) | Not investigated. The compose step accepted the partial input and the answer was delivered as partial. Three prompts on 0.261.482 (5 partial analyses in the run), each with every source read and one candidate unresolved. Not investigated. |
| 27 | An invalid date in the column a cumulative sum is ordered by ended the run with two authoring calls unused: the finding was not one returned to the author. | 0.261.478 run (1 prompt) | Changed in 0.261.481: returned to the author, like the effective-date column. Open until a rerun shows it returned. Not seen on 0.261.482. |
| 28 | A paused run that needs a session is continued only by the worker of the request that started it. If that worker is lost during the pause (a restart, a deploy, a scale event), nothing continues the run and it is closed at its deadline as `run_timeout`. The continuation also uses the identity captured when the run started, so a role removed during the pause is not seen. | 0.261.482 design (not observed in a run; how often a restart lands inside a pause is not measured) | Not built, by decision: wait for a rerun to show the 0.261.482 continuation working first. The follow-up is a signed-in continue route the browser calls for its own paused run, which continues it with the session as it is at that moment. It needs a new route (ownership check, refusal of a run already claimed, no two continuations at once) and a client change in `application/v2_ui`, which is a separate build. The waits for credentials and for the user's answer are already continued this way and are the pattern to follow. On 0.261.482 no worker was lost during a pause. |
| 29 | An answer was published and then not found when read back to confirm it (`message_not_saved`, a Cosmos not-found on the read that follows the publish in `_finalize`). The run failed with its answer composed, and no next attempt is offered for this failure. | 0.261.482 run (1 prompt) | Not explained. The storage calls of that second are not in the sampled dependency telemetry. Not seen in earlier runs. |
| 30 | Outside the harness, an agent answer ends `stream_failed` when the agent calls the ask-the-user function: it raises `UserInputError` ("could not be continued") and the stream ends with no content. | 0.261.482 run (3 answers in 2 conversations) | Not investigated. Not harness code. |
| 31 | Outside the harness, a background spreadsheet export fails on start: its caller passes `semantic_checkpoint_run` to `_generate_and_checkpoint_batch_window_entries`, which does not take it (`TypeError`). | 0.261.482 run (1 export) | Changed in 0.261.490: the keyword is removed; the function already takes the run as its first argument and uses it. Checked by reading every call an application module makes to its own functions (`test_module_call_signatures.py`), not by running an export; open until one runs. Not changed: the other branch calls `_generate_batch_window_entries` without the run that parameter was added for, so it builds its semantic checkpoint context from no run. The one existing test of the function (`test_phase_five_completion_driven_checkpointing_commits_fast_batch_before_straggler`, in a file listed under item 10) fails before and after this change: its loader lacks a helper the function calls and its stand-in generator takes fewer arguments than the function passes. Not harness code. |
| 32 | The planner's first proposal leaves out a document the user selected (`selected_documents_missing`), 17 times in the run, each corrected on the second call. | 0.261.482 run | Not investigated. It costs one planner call each time and no prompt failed on it. One prompt was refused at planning after three different corrections (`native_query_unsupported`, `relational_spec_invalid`, `document_sources_required`). |
| 33 | The answer step, its completeness check and its corrections each need all the evidence in one model call. The check is the first to fail (item 19) because it is the answer step's input plus the answer. | 0.261.482 run and code review, 25 November 2026 | Design recorded in section 6: the check judges each claim, corrections work from findings, and the answer step writes from evidence in as many calls as it needs. Not built. Follows the run on 0.261.490, which gives the sizes. |

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
| Follow-up prompts were refused at planning for naming a document the request may not read (`document_authorization_required`). | 0.261.481 | 0.261.482 run: refused 3 times, returned to the planner each time, and all 3 turns were then planned. |
| A paused run with a result from an action, agent, memory or the web failed when the scheduler resumed it without a session (`context_unavailable`, `result_unavailable`). | 0.261.482 | 0.261.482 run: 4 runs paused and none failed that way. Two were marked and continued by their own request (one completed; one ended on item 25 and got its next attempt); two were resumed by the scheduler and completed. |
| Diagnostic fields added in 0.261.478 did not reach telemetry. | 0.261.480 | 0.261.482 run: the selection rule and function of a refused spreadsheet selection, and the code location of a failed document inspection, are in the logs. Token counts are still hidden (item 19). |

## 6. Following work: the answer, its check and its corrections

Recorded 25 November 2026 from the 0.261.482 run and a reading of the code at 0.261.490. Not
built. The agreed direction is one design whose number of model calls grows with the evidence.
No single-call path is kept beside it, and size is not a way to fail.

Terms used here. A **piece** is one named item of evidence: a step's result, the saved memory,
the conversation history, the user's own message. A **claim** is one statement in the answer
that can be true or false. A **finding** is a claim or a requested item that did not pass, with
the reason. A **call** is one model request, which has an input budget.

### 6.1 What exists today

Three model calls sit at the end of a run, in `functions_orchestration_composition.py` and
`functions_task_completeness.py`.

| Call | What it is sent | What it returns |
| --- | --- | --- |
| Answer (`adapter_compose`) | Its policy, memory, history, the request and every named input in full | The answer. Refuses with `result_input_too_large` when the input does not fit. |
| Check (`check_and_correct`, stage `completeness_check`) | The request, the contract, every piece and the whole answer | A verdict per requirement. Ends `completeness_unavailable` when the input does not fit. |
| Correction (stage `completeness_correct`) | The request, the contract, every piece, the answer and the findings | A whole rewritten answer, checked again. Up to two by default, five at most. |

Each needs all the evidence in one call. The check fails first because its input is the answer
step's input plus the answer. What was found in the code:

- **The check repeats what it already holds.** Its contract carries the answer step's whole
  policy text as `generation_policy`. The request can appear three times (`approved_request`,
  `user_provided_content` and the history). The report schema is sent both as the response
  format and inside the message.
- **The check reserves the answer's response length.** The check and the correction pass the
  answer step's `output_tokens` to the budget, although a report is refused above 64 KB.
- **The verdicts are coarse.** Under the "use what is available" policy the check returns
  exactly three verdicts (`NARRATIVE_OBLIGATIONS`), and "every claim is supported" is one of
  them for the whole answer. Otherwise it writes its own list of up to 100 requirements.
- **Word lists decide a report's validity.** A passing verdict whose quote does not match the
  answer is accepted when the requirement contains words such as "no", "without", "concise" or
  "format" (`_NEGATIVE_REQUIREMENT_MARKERS`, `_GLOBAL_STYLE_REQUIREMENT_MARKERS`), and the
  answer's first line is substituted for the quote. That is a heuristic under principle 6 of
  section 3.1.
- **The size may be an over-count.** For a model with no tokenizer known to the application the
  budget counts UTF-8 bytes (`utf8_upper_bound`). Whether the failed checks were counted that
  way is not known until a run on 0.261.490. If they were, correcting the count is a separate,
  earlier fix; it does not remove the limit.
- **Three callers.** The answer step, the check of an already retained final answer (which
  cannot be corrected, `immutable_report`), and saved workflows (`functions_workflow_runner.py`).

### 6.2 Principles

1. No call needs all the evidence and the whole answer together.
2. One procedure. The evidence is packed into as many calls as it needs, and one call is the
   smallest case of the same procedure, not a different path.
3. A model answers small closed questions. The server combines the answers by fixed rules.
4. A finding is returned to whoever can act on it (principle 3 of section 3.1).
5. No word lists and no instruction in a prompt that compensates for a rule the code lacks.
6. An error in any step must produce a finding. It must never produce a pass.

### 6.3 The check, claim by claim

1. **List.** One call reads the request, the contract and the answer, with no evidence. It
   returns the items the request asks for, and every claim in the answer with its exact wording,
   its kind, and the requested items it addresses.
2. **Ask the evidence.** The pieces are packed into calls by the input budget. Every call gets
   every claim and answers, for each, whether its pieces support it, contradict it or say
   nothing about it, naming the piece. Small server facts (inputs that could not be read,
   coverage) ride in every call.
3. **Decide in code.**

   | Kind of claim | Holds when |
   | --- | --- |
   | Taken from a source | Some call supports it and no call contradicts it |
   | The sources do not contain something | No call finds it |
   | Concluded from other claims | It follows from the claims it names, judged without evidence, and those hold |
   | From the user's message, memory or history | The piece that holds it supports it |
   | General knowledge | The contract allows it; otherwise it is a finding |

   A requested item is met when a claim that holds addresses it. An item no claim addresses is
   a finding (`missing`).
4. **Return findings.** Each names the sentence, what is wrong, and for a contradiction the
   source's own wording.

Why the rules are sound where a vote across calls is not. Support needs one call, absence
needs every call, and a statement that draws on two sources is listed as one claim per source
plus a conclusion. A statement the listing fails to split is supported by no single call and is
returned as a finding, which is the safe direction. A source disagreement the answer attributes
("A says X, B says Y") is two claims that both hold; an unattributed claim that one source
supports and another contradicts is a finding, as the policy requires today.

What it removes: the word lists, the substituted quote, the repeated policy text, and the
single verdict for all claims. Format validation (`validate`) is unchanged and still runs first.

What it must keep: a saved state from which a paused run resumes without repeating a call that
finished; the report the interface shows (`public_completeness_report`, read by
`static/js/workflow/completeness.js` and the run, plan and map views in `application/v2_ui`),
where requested items take the place of today's requirement list; content-free telemetry.

Cost: two calls in the ordinary case where there is one today, and one more for each further
call the evidence needs.

### 6.4 Corrections from findings

Today a correction rewrites the whole answer from all the evidence. In the redesign the kind of
finding decides who acts and what they are given.

| Finding | Who acts | Given |
| --- | --- | --- |
| A claim no evidence supports | An edit of the answer | The answer and the finding: remove it or say it cannot be established |
| A claim a source contradicts | An edit of the answer | The answer, the finding and the source's wording |
| A conclusion that does not follow | An edit of the answer | The answer and the claims it rests on |
| A requested item no claim addresses | The answer step, as a next attempt | The finding; the evidence is read for that item |
| An invalid format | As today | As today |

- An edit never receives evidence, so it has nothing to add facts from. Anything it adds is a
  new claim and is checked like any other.
- After an edit, a claim whose wording is unchanged keeps its verdict. The evidence is the same
  by its digest, so only new or reworded claims are asked again.
- The existing limits stay: the correction allowance, and stopping when an edit changes nothing.
  A finding returned unchanged after an edit ends the corrections, as a repeated finding does
  for a calculation's author (`correction_repeated`).
- A retained final answer that cannot be corrected reports its findings and is not edited.

### 6.5 The answer step

1. The named inputs are packed as the check packs them. When they fit one call, the answer is
   written from them directly, as today.
2. When they do not, one call per group of inputs returns the statements that bear on the
   request, each naming its piece, and the answer is written from those statements. If the
   statements do not fit, the same step is applied to them.
3. The check asks the original evidence, never the gathered statements. A statement gathered
   wrongly therefore surfaces as a finding and is not passed on unchecked.
4. A next attempt that follows a finding of missing content gathers for that item.
5. Each call reserves the response length it needs, not the answer's.

Nothing is truncated and nothing is dropped without being reported. `result_input_too_large`
remains only for a single item that cannot be divided and does not fit a call.

Not examined: the document analysis capability already works through its sources in parts
(stage `window_analysis`, counted as work units). Whether that machinery can serve the
gathering step is to be read before building one.

### 6.6 Order and measures

1. **Run on 0.261.490.** Read `input_size`, `input_budget`, `output_reserve` and
   `size_estimator` for each check that could not run. If the sizes are a byte count, correct
   the count first.
2. **The check (6.3).** Until 6.4 is built, its findings go to today's correction call, which
   can still fail on size.
3. **Corrections (6.4).**
4. **The answer step (6.5).**

Each is its own version and its own run of the test set. The measures are the counts of
`completeness_unavailable`, `completeness_incomplete` (item 25) and `result_input_too_large`,
calls per check, findings by kind, and corrections per answer. Telemetry carries no content, so
whether a finding was right has to be read from the report in the conversation.

### 6.7 Open decisions

1. Who lists the claims. Recommended: the check, in its own call, so the author of the answer
   does not also say what supports it. The alternative is the answer step emitting its claims
   with the answer, which saves the call.
2. How the server confirms that every part of the answer is accounted for by a claim, for text
   and for outputs that are records or JSON.
3. A single evidence item that does not fit one call and cannot be divided.
4. A check that is saved mid-way under the present report version when the new one is deployed:
   restart it, or finish it under the old rules.
5. Whether saved workflows move to the new check in the same change.
6. A ceiling on calls per check, and what an answer becomes when it is reached.
7. Whether gathered statements are retained as a result, so a next attempt reuses them.
