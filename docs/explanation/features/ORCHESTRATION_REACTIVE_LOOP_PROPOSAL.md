# Orchestration Harness Review and Reactive Loop Proposal

**Version: 0.261.450** (review of the code at 0.261.446)

0.261.449 was deployed and tested overnight on 17 November 2026. A planning crash that
predates this work ended 18 of 40 requests, so the phases below are not yet measured. The
crash is fixed in 0.261.450: see `../fixes/ORCHESTRATION_PREPARED_RELATE_PLANNING_CRASH_FIX.md`.

Implemented so far:

- Phase 0 (0.261.447): crash diagnostics and the telemetry scorecard. The live-model scenario suite is not built.
- Phase 1 (0.261.448): correction feedback for the prepared tabular calculation path only. See `../fixes/ORCHESTRATION_PROGRAM_CORRECTION_FEEDBACK_FIX.md`.
- Phase 2 (0.261.449): intent patterns and scenario wording removed, prompt sections sent by capability, three plan fields derived, corrections named. Strict structured output moved to Phase 3. See `../fixes/ORCHESTRATION_PLANNER_HEURISTICS_AND_DERIVATION_FIX.md`.

Status: proposal for discussion.

## 1. Evidence

### 1.1 Live telemetry, 9-16 November 2026 (versions 0.261.424 to 0.261.444)

Source: Application Insights `simplechat-2026beta-ai`. This is test traffic; the same scenarios repeat across versions.

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

1. Whether mid-run plan changes within the approved scope need user sign-off, or only scope growth does.
2. Round, stall and retry limits, and whether administrators can set them.
3. Whether Phase 1 ships before the Phase 0 suite exists.
