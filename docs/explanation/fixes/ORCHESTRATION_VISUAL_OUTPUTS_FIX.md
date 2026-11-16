# Orchestration charts, diagrams, and image proposals

Fixed in version: **0.261.132**

Version reference: `application/single_app/config.py`.

## Issue

An orchestrated request such as "Plot BatteryVoltage1 over the last 15 minutes, provide
high granularity" planned a Simulation (Yamcs) action step and an answer step, retrieved
900 one-second samples, and then answered that "a renderable time-series plot artifact
cannot be produced". The same request in ordinary chat draws an inline chart.

Orchestration also never produced Mermaid diagrams or image proposal cards, and the V2
composer disabled Image while Orchestrate was on ("Image unavailable in Orchestrate").

## Root cause

Orchestration had no path for any visual output. The failure was not a chart tool
erroring; no chart function was ever called.

1. **Planning.** The planner wanted a plot, and its action rationale said the Simulation
   action would "produce a plot artifact", but no capability could draw one. The v1 planner
   prompt limited actions to knowledge collection.
2. **Gathering.** `functions_orchestration_actions.invoke_action` loads only the selected
   action. Ordinary chat always loads the built-in `conversation_charts` chart plugin; this
   path did not. The step returned the model's prose summary of the 900 rows as findings, so
   the raw values never left the step.
3. **Answering.** `run_respond` is a tool-less completion. It received none of the chart,
   Mermaid, or image-proposal guidance ordinary chat attaches
   (`maybe_append_chart_tool_system_message`, `maybe_append_diagram_system_message`,
   `maybe_append_image_proposal_system_message`), and it only saw the prose summary.
4. **Finalization.** Nothing like ordinary chat's `_append_inline_chart_blocks_to_message`
   carried chart blocks into the saved answer, and action-step citations were re-sanitized to
   20,000 characters, which would cut a chart block in half.

The V2 client already renders `simplechart`, `mermaid`, and `simpleimage` blocks in
orchestrated messages, and the image-proposal approval route accepts any assistant message,
so the gap was entirely on the server plus the composer lock.

## Technical changes

### Shared helpers

- `functions_chart_operations.py` now owns `user_requested_chart_visualization` and the chart
  block collect/append helpers that previously lived in `route_backend_chats.py`. The chat
  route imports them under their existing names, so ordinary chat behaves the same.
- `build_series_chart_data()` turns exact tool rows into chart labels and datasets. It sorts
  time and numeric x values ascending (tools such as Yamcs return newest first) and, when a
  series has more points than the 200 that both chat clients render, keeps each segment's
  highest and lowest value of the first series plus the first and last point. The sampling is
  stated in the chart subtitle, for example "200 of 900 points shown".
- `functions_image_proposals.py` holds the import-light image-proposal guidance;
  `functions_image_generation.py` re-exports it.
- `functions_orchestration_visuals.py` decides which visuals a step should consider, builds
  the answer guidance, and places charts in the final answer.

### Gathering

When the user's current message explicitly asks for a chart, or the planner asks for one in
an action task, `invoke_action` runs a **chart sub-step** after the action's own loop. It is a
separate model call whose kernel holds only the built-in chart tools:

- `conversation_charts.create_chart` for a few values stated in the findings.
- `retrieved_data_charts.chart_retrieved_rows`, which charts the exact rows an earlier call in
  the step returned, read on the server, so the model never copies hundreds of values.

The action's own loop, function-call budget, manifest revalidation, and "action returned
results" check are unchanged. The chart sub-step has its own call limit, honors
cancellation, and counts toward token usage. Its failure never discards the gathered findings.
Runs that capture external acquisition (the opt-in Gather/Reason/Render harness) never add it.

When a diagram or image is requested, gathering steps are asked to keep the entities,
relationships, and visual details those need rather than only summary statistics. Agent
steps receive the same short note; agent kernels already include the chart plugin.

`run_action_invoke` keeps chart citations whole (secrets are still redacted) and reports the
chart count, for example "Used Simulation (3 function calls) and created 1 chart."

### Answering

`run_respond` adds, after its context policy and before saved memory:

- an orchestration visual policy;
- ordinary chat's chart guidance for explicit, planned, or proactive analytical charts;
- ordinary chat's Mermaid guidance for diagram requests;
- ordinary chat's image-proposal guidance when `enable_image_generation` is on.

Charts created during gathering are listed with placement tokens such as `[[chart:abc123]]`.
After the answer is written, each token is replaced with its chart. Charts the answer did not
place are appended once, deduplicated by `chartId`.

Image proposals keep the existing approval flow: each `simpleimage` card is generated only
when the user approves it. The model decides from the request type whether images help,
including when the user did not ask, and proposes as many as the request needs.

### Saved memory

Saved memory follows the rule the memory system already states. An explicit ask in the
current message wins. Otherwise a saved instruction about visuals overrides proactive or
suggested visuals, and style preferences apply wherever a visual is authored.

- The planner already sees memory and is told to shape planned visuals from it.
- The answer step places visual guidance before the memory messages, and the guidance defers
  to saved instructions.
- The chart sub-step receives only saved **Instruction** memories, never recalled facts, and
  never the action's integration functions. `load_orchestration_memory` now returns
  `instruction_messages` separately for this.
- Chart tools load only for an explicit current ask or a planner-directed chart, never from
  proactive keyword markers alone.

Facts are background context, and a preference saved as a Fact may not be recalled. Save
visual preferences such as "I don't like charts" as Instruction memories.

### Planner and composer

- The v1 planner prompt describes the visual outputs, asks for them to be written into the
  answer instruction and action tasks, and forbids claiming that an integration produces
  plots or images. `capability_availability.visual_outputs` reports what is available, and
  `user_selected.image_proposals` records the Image control.
- `resolve_seeds` reads `image_generation_enabled` as a strict boolean.
- The V2 composer enables Image in Orchestrate. It no longer blocks sending, shows "Orchestrate
  will include image proposals for you to approve.", and sends `image_generation_enabled`.

## Files modified

| File | Change |
| --- | --- |
| `functions_chart_operations.py` | Shared chart helpers and `build_series_chart_data` |
| `functions_image_proposals.py` | New import-light image-proposal helpers |
| `functions_image_generation.py` | Re-exports the proposal helpers |
| `functions_orchestration_visuals.py` | New visual intent, guidance, and placement helpers |
| `functions_orchestration_actions.py` | Chart sub-step and gathering addenda |
| `functions_orchestration_adapters.py` | Action, agent, and answer wiring |
| `functions_orchestration_memory.py` | `instruction_messages` in the memory context |
| `functions_orchestration_planner.py` | Visual guidance and planner context |
| `functions_orchestration_registry.py` | Answer capability description |
| `functions_orchestration_context.py` | Image seed |
| `route_backend_chats.py` | Imports the moved helpers |
| `v2_ui/src/components/chat/Composer.tsx` | Image in Orchestrate |

## Validation

- `functional_tests/test_orchestration_visual_outputs.py`: exact-row downsampling, intent
  detection, guidance and memory precedence, chart placement, answer wiring, action citation
  handling, planner context, and seeds.
- `functional_tests/test_orchestration_action_runtime.py`: the chart sub-step charts 900
  newest-first rows as at most 200 chronological points; it cannot reach the action; saved
  instructions reach only the chart sub-step and facts never do; failures keep findings;
  capturing runs never add it.
- The chart helper tests that extract route functions now read the moved helpers from
  `functions_chart_operations.py`.
- `ui_tests/test_v2_reasoning_controls.py` and `ui_tests/test_v2_orchestration_composer.py`
  cover Image in Orchestrate.

## Known limitations and follow-ups

- The Gather/Reason/Render harness (contract v2) does not produce visuals yet. Its `compose`
  steps need visual guidance and a render path.
- Charts render at most 200 points per series; longer series are reduced as described above.
- Agent steps do not receive saved memories.
- Ordinary chat's deterministic tabular auto-charts do not consult saved memory.
