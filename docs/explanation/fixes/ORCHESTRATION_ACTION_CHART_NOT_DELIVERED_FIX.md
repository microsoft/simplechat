# Orchestration Action Chart Not Delivered Fix

**Version: 0.261.292**

Fixed in version: **0.261.292**, recorded in
`application/single_app/config.py`.

## Issue

With Orchestrate on, a user asked "Plot BatteryVoltage1 over the last 15 minutes, provide
high granularity". The plan had a single Gather step, **Retrieve and plot BatteryVoltage1
telemetry**, which used the Simulation action. It had no Reason step and no Render step.

The run finished as completed and the reply said only "The requested content is prepared.
No downloadable files were created." No chart appeared. The plan panel still listed the
chart under **You asked for** as **Delivered**, and Retry wasn't offered because the run
was already complete. The step also took almost four minutes.

Application Insights showed that the action itself worked. Its three Simulation calls
succeeded, and `ChartPlugin.create_chart` drew the chart about 25 seconds into the step.

## Root cause

Four problems combined.

1. **The planner was told it could skip the Reason step for a chart.** Since the
   deliverables contract (0.261.135), the planner prompt said "action_invoke can deliver a
   chart of the rows it retrieves", and `_check_producer` accepted an action as a chart's
   only producer. Since 0.261.140 `final_response` is optional, and the prompt said extra
   prose isn't needed for a structured-only request. Before 0.261.139 every plan ended
   with an Answer step that always ran, so a chart an action drew was always placed. Since
   then, a Reason step writes the answer only when the planner adds one. The planner
   followed its instructions and made one Gather step that "delivers" the chart, with no
   `final_response`. Validation accepted the plan without a correction round.
2. **Only a Reason step shows a chart drawn during Gather.** An action's chart travels in
   its tool citations, and a compose step that reads the action's output places it
   (`_input_charts`, `place_chart_blocks`). Finalization publishes the `final_response`
   answer, files and generated images, but not charts. With no compose step, the chart was
   dropped. Generated images never had this problem, because finalization always appends
   them to the answer.
3. **The failure looked like a success.** With no answer and no files, finalization used
   its "content is prepared" fallback. Delivery notes had no case for charts. The run was
   saved as completed, so recovery refused a retry. The plan panel marks a deliverable as
   delivered when the step that produces it completes.
4. **Saving the action's result was slow.** The step's 202 KB structured result was saved
   with one record per JSON encoder token. The record writer flushes a page every 100
   records, so the result took 258 pages, and each page was authorized and written on its
   own. That took about 200 of the step's 231 seconds.

## Changes

### Gather is always read by Reason

- The planner prompt says every gather step's results must be read by a reason step,
  directly or through later steps, so the work ends in the `final_response` answer, a file
  or a generated image. `workflow_run` is the only exception, because nothing reads it and
  the server reports whether it started. That exception is stated in the `workflow_run`
  instructions, which the planner sees only when it may start workflows, so a request that
  can't start one is still never told about runs. The prompt no longer says an action can
  deliver a chart on its own: the compose step that reads the action's output, and is
  `final_response`, places the chart. The chart recipe in
  `capability_availability.deliverables` says the same.
- While planning, `compile_deliverables` calls `_require_shown_work`, which follows the
  plan's named input bindings:
  - every enabled gather step except `workflow_run` must lead to the `final_response`
    step, an enabled `render_file` step or a `generate_image` step (rule
    `gather_not_used`);
  - every planned chart or diagram must come from the `final_response` step, a step that
    leads to it, or a step that leads to an enabled `render_file` step (rule
    `visual_not_published`).

  Both rules use the `deliverables_invalid` code, so the planner gets its existing single
  correction round with the server's explanation. Saved plans are revalidated without
  these rules, so plans saved before this version still open and run.

### A chart drawn during Gather is always shown

- At finalization, `gathered_charts` reads the saved result of each completed
  `action_invoke` or `agent_invoke` step whose `visuals` include `chart`, through the
  authorized result reader. `show_gathered_charts` then adds each chart the answer
  doesn't already show, once, after the answer, the way generated images are added. A
  chart the answer step placed stays where it is.
- The answer step now receives a chart drawn upstream as its `[[chart:<id>]]` token
  instead of a second copy of the chart's data. The server still places the chart from
  the exact rows. Retrieved rows and findings are sent in full, and nothing is truncated.

### Honest delivery status

- `visual_delivery` checks each explicit, planned chart and diagram meant for the answer.
  A deliverable that isn't shown gets a delivery note, for example "Not delivered: A plot
  of BatteryVoltage1. The chart could not be created from the retrieved data." The other
  reasons are "The answer did not include it." and "The step that makes it did not
  finish."
- A completed run with such a shortfall is saved as failed with outcome `partial` and the
  new failure `visual_not_delivered`.
- The run saves `deliverable_states` and `redraw_step_ids`. `public_execution_fields`
  returns the well-formed `deliverable_states`, and the V2 plan panel uses them instead of
  step status after a run.
- A retry runs the steps in `redraw_step_ids` again, with every step computed from them,
  so the new attempt can draw the chart. Running an action or agent step again repeats its
  calls, so that retry asks for confirmation first.
- A plan saved before this version that gathered without answering now replies "The
  information was gathered, but this plan had no step that writes an answer from it. Ask
  again to get an answer." instead of "The requested content is prepared."
- Delivery notes drop a trailing period from a deliverable's description, so a note never
  ends a description with two periods.

### Faster saving

- `_value_records` regroups the encoder's fragments into records of 16,384 characters
  before they're saved. The reported 202 KB result now takes 13 records instead of about
  25,800, and a few pages instead of 258. Readers already join the records and verify the
  digest, so results saved before this version still read.

## Files modified

| File | Change |
| --- | --- |
| `application/single_app/functions_orchestration_planner.py` | Gather results must be read; the chart wording. |
| `application/single_app/functions_orchestration_deliverables.py` | `_require_shown_work`, the chart recipe, `gathered_charts`, `show_gathered_charts`, `visual_delivery`, `unread_gather_steps` and chart and diagram delivery notes. |
| `application/single_app/functions_orchestration_execution.py` | Show gathered charts, check chart and diagram delivery, save their states, and the unread-gather reply. |
| `application/single_app/functions_orchestration_composition.py` | Send upstream charts to the model as their tokens. |
| `application/single_app/functions_orchestration_recovery.py` | Rerun `redraw_step_ids` in a new attempt, confirm a rerun action or agent step, and public `deliverable_states`. |
| `application/single_app/functions_orchestration_schema.py` | The `visual_not_delivered` failure message. |
| `application/single_app/functions_orchestration_results.py` | Save JSON values in 16,384-character records. |
| `application/single_app/config.py` | Version `0.261.292`. |
| `application/v2_ui/src/lib/orchestration.ts`, `orchestrationPlan.ts`, `components/chat/OrchestrationDeliverables.tsx`, `OrchestrationRunView.tsx` | The plan panel uses the server's chart and diagram checks. |
| `functional_tests/test_orchestration_action_chart_delivery.py` | New regression test. |
| `functional_tests/test_v2_orchestration_deliverables.mjs` | The server's chart check wins over step status, and `deliverable_states` normalization. |
| `functional_tests/test_support/orchestration_workflow_*_off_golden.json` | Regenerated for the planner prompt and chart recipe text. |
| `ui_tests/test_v2_orchestration_dependency_plans.py` | The plan panel shows the server's check of a chart. |
| `functional_tests/test_orchestration_workflow_results_capability.py` | The degraded-plan test's answer reads the kept workflow result, as the `workflow_results` instructions already required. |

## Validation

### Tests

`functional_tests/test_orchestration_action_chart_delivery.py` runs the real planner,
schema, executor, execution, recovery and result services in the offline harness. Only the
action's tool calls and the model are doubled. It covers:

- The prompt and chart recipe text.
- The reported plan is refused while planning, its correction is accepted, and the same
  saved plan still loads.
- Gather steps that lead nowhere, or only to a structured result nobody sees, are
  refused. Gather steps that lead to the answer, a file or nothing at all for
  `workflow_run` are accepted.
- A chart or diagram must reach the answer or a file.
- A gather-only plan gets one correction round, and planning fails if the correction
  doesn't fix it.
- The reported saved plan now shows the chart the action drew, once.
- With a Reason step, the chart is placed at its token, and the model receives the token
  instead of the chart's data.
- A chart that couldn't be drawn is reported as not delivered, the run is partial, and
  the retry reruns the action and the answer after confirmation.
- A saved plan that gathered without answering says so.
- Public fields carry only well-formed deliverable states.
- A 960-sample telemetry result is saved in at most 3 pages instead of more than 100, and
  reads back exactly.

All 15 tests fail against the code before this fix, including the reported plan, whose
reply has no chart.

`functional_tests/test_v2_orchestration_deliverables.mjs` checks that the server's chart
check wins over its step's status, that a step the user turned off still reads as turned
off, and that malformed `deliverable_states` are dropped. In
`ui_tests/test_v2_orchestration_dependency_plans.py`, the real plan panel lists a chart
whose step finished as not delivered, with the server's reason, at desktop and mobile
widths.

The four `*_off_golden` tests were regenerated. Their diffs contain only the changed
planner prompt lines and the chart recipe.

### Before and after

| Before | After |
| --- | --- |
| A chart request could be planned as one Gather step with no Reason step. | The plan is refused while planning and the planner corrects it to Gather, then Reason. |
| The chart the action drew was dropped and the reply said "The requested content is prepared." | The chart is shown, either where the answer placed it or after the answer. |
| The plan panel showed the chart as delivered and Retry wasn't offered. | A chart that isn't shown is listed as not delivered, the run is partial, and Retry draws it again. |
| The answer step was sent the chart's data a second time. | The answer step receives the chart's token. |
| Saving a 202 KB result took 258 pages and about 200 seconds. | It takes a few pages. |

## Limitations

- A chart or diagram that only goes into a file isn't checked. The orchestration file
  renderers don't draw chart or Mermaid blocks, so they show as text in the file, as
  before.
- The answer step still receives the action's full retrieved rows. A much longer time
  window can exceed the action's or the answer model's input budget. The run then fails
  with the existing message that the inputs exceed the selected model's budget, instead of
  truncating data.
- If the planner's correction still breaks the rule, planning fails with "The plan could
  not account for everything you asked to receive."

## Related

- [Chat orchestration actions](../features/CHAT_ORCHESTRATION_ACTIONS.md)
- [Orchestration deliverables](../features/ORCHESTRATION_DELIVERABLES.md)
- [Orchestration visual outputs fix](ORCHESTRATION_VISUAL_OUTPUTS_FIX.md)
- [Charts, diagrams, and images in answers](../../admin/orchestration.md#charts-diagrams-and-images-in-answers)
