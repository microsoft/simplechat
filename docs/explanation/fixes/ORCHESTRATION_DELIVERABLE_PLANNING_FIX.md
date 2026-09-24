# Orchestration answers that miss what the user asked for

Fixed in version: **0.261.134** (Gather / Reason / Render answer parity). The deliverables
contract and generated images in files follow in later layers of the same change.

Version reference: `application/single_app/config.py`.

## Issue

Orchestrated requests produced something other than what the user asked for:

| Request | What happened |
| --- | --- |
| "create a csv showing the states and their capitals" (gpt-5.4) | The planner chose to answer from general knowledge. The answer then refused: "I don't have source evidence in this conversation verifying the full state-capital list". |
| The same request routed Auto to gpt-5.6-terra | The plan said **Create state-capital CSV**, but the answer was inline text ("save as us_states_capitals.csv"). No file was created. |
| "create a word file, I'm doing a report on the 1st 3 presidents... images for each president" | The planner wrote "a DOCX file cannot be created" as an assumption and delivered a "Word-ready" report with `[Insert Image 1 here]`, "find the portraits yourself", and "I can't attach a .docx". |
| "I'm doing a report on the 1st 3 presidents... images for each president" | One run's web search failed with "This operation could not complete", so the answer was a skeleton of "Verify with a reputable source" placeholders. Another run produced no images at all and showed raw `【3:1†source】` markers with "no clickable URL". |

The plan panel also never showed which model wrote a plan.

## Root cause

1. **Every run used a legacy plan.** New plans reached the Gather / Reason / Render
   contract only when its admin toggle was on, and Auto model routing always forced the
   legacy contract (`_new_plan_contract_version`). The two contracts had split
   capabilities:
   - The legacy contract had no file capability: its output phase was empty and its
     prompt said output plans were unsupported.
   - Gather / Reason / Render had `render_file`, but no Auto routing, no charts,
     diagrams or image proposals, and no saved memory or conversation references in
     its answer step.
2. **The planner could not represent what the user asked to receive.** Nothing required
   "create a Word file" or "images for each president" to be produced or explicitly
   declined. The planner relabeled the deliverable, or buried the limitation in an
   assumption.
3. **Planner and answer step contradicted each other.** The registry told the planner
   that the answer could come from the model's own knowledge. The answer step's policy
   said "using only the evidence and context above", so the outcome depended on the model:
   gpt-5.4 refused, gpt-5.6-terra complied but still withheld well-known facts.
4. **Web search failures were opaque.** The Foundry exception was swallowed, and the
   executor replaced the unstructured failure with `step_failed`. There was no retry,
   and Foundry `url_citation` placeholders were passed to the answer unresolved.
5. **Images had no required path.** Proposal guidance was optional, intent came from
   keyword detectors, and the planner was never told that web search cannot retrieve
   images.

## Technical details (0.261.134)

### Auto model routing on Gather / Reason / Render plans

- `route_backend_orchestration._new_plan_contract_version` no longer forces legacy plans
  under Auto.
- `plan_request` binds dependency-plan steps with `assign_step_models`. `compose` is
  model-backed, `model_task` and the server-owned `model_binding` are admitted step
  fields, and the planner prompt receives `ROUTING_INSTRUCTIONS`.
- `HarnessExecution` refuses an Auto plan with a missing binding before any model
  setup, reauthorizes every binding with `validate_auto_bindings`, and resolves the
  answer model from the `final_response` producer.
- It installs `step_model_context` for each step, using a guarded planner client and
  the harness invoke prompt. Step events and records carry the executed binding.
- `validate_edited_plan` rebinds an Auto plan to the current authorized inventory. An AI
  edit or restore used to strip the server-owned bindings, which silently turned Auto
  off. If no eligible model remains, the edit is refused and the current plan is kept.
  An Ask-planner revision whose new steps cannot be bound is refused the same way, with
  `model_unavailable`, instead of surfacing as a generic service error.
- **Bound action and deep research steps pass the external-source check.** Before an
  `action_invoke` or `deep_research` result is admitted or reused, SimpleChat rebuilds
  the step's current configuration and compares it with the one the step captured. That
  rebuild used the run's own model selection, which is empty under Auto, so every bound
  step was refused. `functions_orchestration_external_metadata.py` now rebuilds a bound
  step from its approved binding:
  - Deep research uses the binding's model and model group, without the planner
    override, which is how the step's model scope resolved its research client.
  - Actions use the binding's model with the run's own groups, which is how the action
    builder authorizes its model.
  - An Auto step with a missing or malformed binding is refused.
- **Steps with no rated model use general answering.** Few built-in profiles rate
  specialist tasks: only one rates structured data analysis, and many rate no
  reasoning. So Auto refused whole plans that needed `tabular_analyze` or
  `deep_research` on common deployments such as gpt-4o and gpt-4.1. When no capable
  connected model is rated for a step's task, `assign_step_models` now ranks the
  capable models by their general-answering rating, and the step's reason reads
  "General answering, because no connected model is rated for ...". Rated models still
  win. A model rated `unsuitable` for the task, an archived profile, and a missing
  required capability are never bypassed. This applies to standard plans as well.
- **The answer is credited to the model that wrote it.** The reply is attributed to the
  binding of the step that `final_response` names. When the reply reuses an earlier
  turn's result, or the plan only delivers files, the default selection is kept rather
  than crediting the last compose step or any other bound step.
- The dependency planner prompt names the steps that take a `model_task` (`compose`,
  `tabular_analyze`, `document_analyze`, `document_compare`, `deep_research`,
  `action_invoke`) and says every other step takes none. The list is derived from
  the routing table, so it stays in step with what the server binds.

### The answer step (`compose`)

- It receives saved instruction and fact memory, the resolver-selected conversation
  references, and a policy stating that earlier answers are not evidence.
- `knowledge_basis` is one of `general_knowledge`, `sources`, or
  `sources_and_general_knowledge`, and the step's policy is built from it. When the
  planner omits it, a step with inputs defaults to `sources` and a step without inputs
  defaults to `general_knowledge`.
- **Optional named inputs.**
  - Only compose can declare one, and only with a basis that includes general knowledge.
  - A producer that feeds nothing but optional inputs is compiled as optional.
  - If that producer fails, compose still runs and receives `unavailable_inputs` with the
    application-owned reason, and it must disclose the gap. The run completes with the
    failed step shown.
  - The run is offered a retry only when another step also failed. That retry runs the
    failed producer again and also runs again every step that completed without it, and
    everything computed from them. Before, `recovery_projection` reused the answer, and
    the new attempt failed with `recovery_changed` ("Saved step inputs changed") as soon
    as the producer succeeded. `_reuse_invalidated_by_rerun` applies the same rule to
    what a retry offers and what the new attempt restores. A continuation of a waiting
    run is unaffected, because it never runs failed steps again.
  - Required inputs still fail closed.
- **Visuals are named by the planner** in `visuals` (`chart`, `diagram`, `image_proposal`)
  rather than detected from keywords. Markdown outputs receive the ordinary chat chart,
  Mermaid, and proposal guidance. Charts a gathering step drew are listed with their
  `[[chart:id]]` tokens and placed after the reply.
- The action chart sub-step also runs under invocation capture. It holds only the
  built-in chart tools and the rows already returned, and adds no captured acquisition.

### Web search

- `functions_web_search_results.py` replaces Foundry citation placeholders with numbered
  links, lists the sources, and describes provider failures by type and HTTP status only.
  Ordinary chat and orchestration both use it.
- The orchestration adapter maps failures to `provider_http_error` (with the status),
  `provider_timeout`, `connection_failed`, `provider_not_configured`, or
  `provider_failed`.
  - `perform_web_search` records these facts before checking the invocation capture.
  - A Foundry failure before anything was acquired, such as the agent definition read, is
    reported as that provider failure rather than an attestation failure, so it is
    classified and can be retried.
- Read-only gather capabilities (`document_search`, `web_search`, `url_fetch`,
  `deep_research`) retry once after a transient failure, within the step deadline, and
  emit a "Retrying after a temporary service error." progress event.

### Planner model visibility

`plan.planner` records the planning model's display label, how it was chosen
(`selected`, `planner_setting`, or `default`), and its effective reasoning effort. The
plan panel and approval card show "Planned by ...". No connection details are exposed.

## Files modified

| File | Change |
| --- | --- |
| `functions_orchestration_schema.py` | Optional inputs, step model fields, producer optionality, failure codes, transient classification |
| `functions_orchestration_result_contracts.py` | `InputSpec.optional` |
| `functions_orchestration_registry.py` | Knowledge bases, visual kinds, compose/gather arguments, retry flags |
| `functions_orchestration_model_routing.py` | Compose task, general-answering fallback, dependency routing note, final-response answer credit, guarded planner clients |
| `functions_orchestration_external_metadata.py` | Bound Auto steps rebuilt from their approved binding |
| `functions_orchestration_planner.py` | Auto routing and visuals for dependency plans, answer/visual/file guidance, planner descriptor |
| `functions_orchestration_execution.py` | Auto binding validation and per-step model scope in the harness |
| `functions_orchestration_executor.py` | Step model scope, optional-input dependencies, one transient retry |
| `functions_orchestration_result_runtime.py`, `functions_orchestration_checkpoints.py` | Missing optional inputs |
| `functions_orchestration_recovery.py` | Retries run again the steps that completed without a retried producer |
| `functions_orchestration_composition.py` | Memory, conversation, knowledge basis, missing inputs, visuals, chart placement |
| `functions_orchestration_adapters.py`, `functions_orchestration_actions.py` | Structured visuals, web search failures, chart sub-step under capture |
| `functions_web_search_results.py`, `route_backend_chats.py` | Citation links and structured failure facts |
| `functions_orchestration_plan_revisions.py` | Planner descriptor in the editor projection |
| `functions_orchestration_plan_editing.py` | Auto rebinding for edited and restored plans; unroutable revisions refused with `model_unavailable` |
| `v2_ui/src/...` | Planner line, answer basis and visual labels, optional-input wording |

## Validation

- `functional_tests/test_orchestration_single_contract_parity.py` exercises the real
  headless harness. It covers Auto planning and execution on the bound model,
  fail-closed stale bindings, Auto rebinding after plan edits, final-response answer
  selection, knowledge-basis policies and defaults, memory and conversation references,
  the optional-input retry and disclosure, a run retry that fetches the missing input and
  rewrites the answer with it (this test fails with `recovery_changed` without the fix),
  required inputs failing closed,
  optional-input validation, planner-named visuals, chart placement, the planner
  descriptor, web search classification, and citation links.
- `functional_tests/test_orchestration_external_configuration_capture.py` drives the real
  v2 web search through its invocation capture when the Foundry definition read fails, and
  checks that the failure is classified as a transient provider failure.
- `functional_tests/test_orchestration_external_metadata.py` rebuilds bound Auto action
  and deep research steps from their bindings, checks that research ignores the planner
  override and that actions keep the run's groups, and refuses missing or malformed
  bindings.
- `functional_tests/test_model_catalog_profiles.py` covers the general-answering fallback:
  rated models still win, and `unsuitable`, archived and missing-capability models are
  never used.
- `functional_tests/test_orchestration_plan_revision_routes.py` checks that an Ask-planner
  revision that cannot be bound reports `model_unavailable`, keeps the plan, and closes
  its planner client. The test fails if the new handling is removed.
- `functional_tests/test_v2_orchestration_planner_display.mjs` covers the browser
  normalization and labels.
- `ui_tests/test_v2_orchestration_dependency_plans.py` checks the planner line, answer
  basis, visuals, and optional-input wording at desktop and mobile widths.
- Four updated regressions:
  - `test_orchestration_action_runtime.py`: charts under capture.
  - `test_orchestration_harness_chat_checks.py`: Auto planning candidates.
  - `test_orchestration_harness_routes.py`: contract selection under Auto.
  - `test_orchestration_visual_outputs.py`: visuals in both planner prompts.
- The full `test_orchestration*.py` suite passes, apart from failures that also occur on
  the unchanged baseline (`elicitation_context`, `memory_context`,
  `conversation_context`, `conversation_context_routes`). Those failures come from
  outdated local stubs, not from this change.

Before this change, the three requests above landed on legacy plans. With Gather / Reason /
Render enabled, the same requests now plan that contract's work even under Auto routing:
compose writes from general knowledge when appropriate, a failed search is disclosed
rather than turned into placeholders, and web sources arrive as links. A later layer of
this change makes Gather / Reason / Render the only contract and removes its admin toggle.
