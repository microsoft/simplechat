# Orchestration planner: heuristics removed, fields derived, corrections named

Version: **0.261.453**

Fixed/Implemented in version: **0.261.453** (`application/single_app/config.py`).

This is Phase 2 of the [reactive loop proposal](../features/ORCHESTRATION_REACTIVE_LOOP_PROPOSAL.md).

## Issue description

1. Request wording decided routing. Four regular expressions in the planner module classified
   a message as an acknowledgment, a transformation, a reference to earlier content or an
   explicit retrieval request, and overrode the resolver model's structured answer.
2. Prompts carried wording written for individual test scenarios.
3. Every request received the whole planner prompt, including guidance for capabilities the
   request did not offer.
4. The planner was rejected for omitting fields that have exactly one valid value.
5. A rejected plan was reported one step at a time, and the correction request named no
   argument: the diagnostics are content-free because they are logged.

In the 9-16 November baseline these accounted for 13 `unknown_argument`, 12
`argument_schema_invalid`, 12 `selected_documents_missing`, 5
`tabular_complete_policy_required`, 4 `step_shape_invalid` and 2 `outputs_list_required`
rejections, and 15 second-round corrections.

## Root cause

- The intent patterns predate the resolver's `requires_retrieval` and `source_requirement`
  fields and were kept as an override.
- Scenario failures were fixed by adding sentences to prompts.
- `PlanValidationError` had one detail channel, used for both telemetry and the planner.

## Technical details

Files modified:

- `application/single_app/functions_orchestration_planner.py`
  - Removed `ACKNOWLEDGMENT_PATTERN`, `TRANSFORMATION_PATTERN`, `CONVERSATION_TARGET_PATTERN`,
    `EXPLICIT_RETRIEVAL_PATTERN`, `_explicit_retrieval` and `_conversation_transformation`.
    `conversation_retrieval_allowed` reads the resolver's `requires_retrieval` and the user's
    control selections only. The resolver's answer is no longer overridden after the fact.
  - The planner prompt is `PLANNER_PROMPT_SECTIONS`, 14 ordered sections. Nine are sent only
    when the request offers one of their capabilities (document templates, agents and actions,
    document-bound actions, accessibility reads, tabular work, Word comment export, mixed
    narrative and tabular work, research depth, images). `PLANNER_SYSTEM_PROMPT` is still the
    full text; `planner_system_prompt(offered_ids)` builds the per-request prompt.
  - Scenario wording removed from the planner and resolver prompts. The original-row export
    note that was appended inline in `plan_request` moved into the tabular section.
  - `plan_repair_message` appends the error's model-only `feedback`.
  - New proposals pass through `derive_plan_defaults` before validation.
- `application/single_app/functions_orchestration_schema.py`
  - `PlanValidationError.feedback`: names the planner wrote or was shown. Returned to the
    planner only; never part of `diagnostics`, so never logged.
  - `plan_argument_feedback`: argument problems for every step in one report, with the
    unknown and allowed argument names.
  - `step_shape_invalid` names the unknown step fields; `selected_requirements_missing` names
    the unused selected document IDs and capabilities.
  - `derive_plan_defaults`: a compose step without outputs prepares one Markdown answer;
    complete tabular composition drops a declared available-information policy; when no answer
    is selected and exactly one enabled compose step leaves one unread text output, that
    output is the answer. Nothing is derived when more than one value would be valid.
- `application/single_app/functions_orchestration_composition.py`,
  `application/single_app/functions_orchestration_native_results.py`
  - Scenario wording removed from the calculation, mixed-knowledge and conversation policies
    and from the prepared-program prompt.
- `functional_tests/test_orchestration_plan_derivation_and_feedback.py` (new), including a
  check that fails when scenario wording or an intent pattern returns to the three prompt
  modules.

## Behaviour changes to expect

- A short acknowledgment in a conversation with history now reaches the resolver model
  instead of being answered by a pattern. That is one more model call for such a message.
- The resolver runs when there is something a request could refer to: earlier messages, a
  truncated history, or saved memory supplied for the request. On a first turn with none of
  these, the request goes straight to the planner whatever its wording, and the planner asks
  when the content it refers to is missing. Before, wording such as "the above" or "rewrite"
  sent a first turn to the resolver.
- A plan with one compose step and no selected answer is accepted with that step's output as
  the answer instead of being sent back.
- When the resolver says no retrieval is needed, wording such as "search" no longer reverses
  it. A selected document, tag, workspace or the Web control still does.

## Not done

- **Strict structured output.** The plan document cannot be expressed in strict mode: named
  inputs are maps with free keys, and several capability argument schemas are conditional or
  free-form (`tabular_analyze`, `render_file`, workflow blueprints). It fits Phase 3, where
  arguments are authored per step.
- **Bindings and deliverables** are derived only where they already were (unambiguous
  deliverable links) plus the answer selection above. The planner still writes input bindings.
- **Keyword classifiers in the shared tabular engine.**
  `functions_tabular_orchestration.plan_tabular_request` calls
  `question_requests_tabular_generated_output`, `..._hierarchical_analysis` and
  `..._exhaustive_row_output`, and orchestration reaches it through
  `functions_orchestration_native_results`. Classic chat uses the same functions, so they
  were not changed here.
- The planner prompt was scoped and cleaned, not rewritten. Its general sections are still
  long.
- Not deployed and not measured with the scorecard.

## Validation

Scope: the 223 `functional_tests/test_orchestration*.py` files plus four related files, run on
the unmodified commit `316bcf67f` and on this change with the same eight-shard assignment.

| Tree | Failed or errored |
| --- | --- |
| Unmodified `316bcf67f` | 410 |
| This change | 411 |

- The suite already fails about 410 tests before this change. Those failures are not
  addressed here.
- Eleven tests differed between the two runs: six failed only with this change, five only on
  the unmodified commit. All eleven are cold-import, fresh-process or scheduler bootstrap
  tests. The four files holding the six were rerun alone in both trees and gave identical
  results: `test_orchestration_operation_imports.py` 11 passed,
  `test_orchestration_dependency_imports.py` 11 passed,
  `test_orchestration_harness_execution.py` 719 passed,
  `test_orchestration_harness_scheduler.py` 12 failed and 201 passed in both.
- Phase 2 changed the outcome of 37 tests in nine files. Their expectations were updated to
  the behaviour listed above. Run alone, each file now matches the unmodified commit:
  request memory resolution 22 passed, conversation context 28 passed, conversation sources
  25 passed, failure telemetry 58 passed, mixed-mode history 3 passed, task completeness
  runtime 44 passed; workflow hand-off planner (25 failed), plan revision references
  (18 failed) and visual outputs (2 failed) fail identically in both trees.
- New: `test_orchestration_plan_derivation_and_feedback.py` 8 passed,
  `test_orchestration_crash_diagnostics.py` 5 passed.

Before and after:

| Case | Before | After |
| --- | --- | --- |
| "Search ..." after the resolver said no retrieval | Retrieval re-enabled by a pattern | Resolver's decision stands |
| First message, nothing to refer to, worded "rewrite the above" | Resolver model called | Planner called directly; it asks for the content |
| First message with saved memory | Resolver called only for matching wording | Resolver called |
| One compose step, no `final_response` | Rejected, correction round | Accepted, answer derived |
| Unknown argument on two steps | Two rounds, argument not named | One report naming both |

Not validated: behaviour against a live model, and the UI. Nothing is deployed.
