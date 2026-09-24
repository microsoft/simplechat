# Orchestration answers that miss what the user asked for

Fixed in version: **0.261.134** (Gather / Reason / Render answer parity), **0.261.138**
(the deliverables contract and generated images in files), and **0.261.139** (Gather /
Reason / Render made the only orchestration contract).

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
  - A retry is offered when the run did not complete, for example when a required step
    failed or a requested image was not delivered. That retry runs the failed producer
    again and also runs again every step that completed without it, and everything
    computed from them. Before, `recovery_projection` reused the answer, and
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

### Retrying runs with files

Found while reviewing the stacked image layer: a whole-run retry of a plan ended failed
whenever the new attempt had to render a file that the previous attempt had already
created or admitted. React V2 offers **Retry from failed step** only for an attempt
without files, so users reached this through the retry API rather than the button. It
also blocked the retry that the image layer needs to recover a missing requested image.
The output store withdraws an attempt's files once a retry supersedes it, and never lets
another attempt adopt an output's identity. Whole-run retry accounted for neither rule:

- `prepare_retry` copied the parent's `render_output_ids` into the child. The child listed
  the parent's superseded file as its own, and finalization failed the run with
  `result_unavailable`.
- A completed render step was reused, but its file had already been superseded.
- A render run again from reused content presented the first attempt's work ID, because
  `approved_work_id` was the attempt root. It computed the first attempt's output identity
  and was refused with `output_producer_changed`.

Now each attempt owns its files:

- `_reuse_invalidated_by_rerun` never reuses a render step in a new attempt: retry
  preparation (`source_run_id`) or the attempt it created (`retry_of_run_id`). A restart
  of the same attempt still reuses its completed files.
- `prepare_retry` drops `render_output_ids` from the child.
- `bind_context` uses the attempt's own run ID as its approved work.

Rendering again calls no model, and the rule against adopting another attempt's output
identity is unchanged. The V2 recovery notice is unchanged too: an attempt with files is
still recovered per file. Offering a whole-run retry for an attempt that has files but
failed elsewhere would withdraw its available files as soon as the retry is prepared, so
it is left as a product decision rather than changed here. One upgrade edge case remains.
A retry attempt created before this change that is still waiting on a file it admitted
keeps its old identity, so that file fails when the run resumes. Retrying the run again
renders a new file.

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
| `functions_orchestration_recovery.py` | Retries run again the steps that completed without a retried producer, never reuse a render, and start without the parent's file admissions |
| `functions_orchestration_services.py` | Each run attempt is its own approved work for file identity |
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
  rewrites the answer and its file with it (this test fails with `recovery_changed`
  without the fix), a run retry that renders its own file from reused content while the
  first attempt's file reads as superseded (it fails without each of the three file
  changes), required inputs failing closed,
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

## Technical details (0.261.138): deliverables and generated images

Root causes 2 and 5 are fixed structurally. The full contract is described in
[Orchestration deliverables](../features/ORCHESTRATION_DELIVERABLES.md).

### What the user asked to receive is part of the plan

- The planner lists `deliverables` before its steps. Each is an answer, file, image,
  chart, or diagram, `explicit` or `suggested`, and `planned` or `unavailable`. Steps name
  what they produce in `delivers`.
- `plan_request` gives the planner `capability_availability.deliverables`: the kinds and
  file formats this plan can produce, closed reason codes for what it cannot, recipes, and
  facts such as "web search returns text and links only". `PLANNER_MAX_TOKENS` is 4000.
- `compile_deliverables` checks every Gather / Reason / Render plan:
  - A file comes only from a `render_file` step in the same format.
  - An explicit image comes only from `generate_image`.
  - The answer comes from the `final_response` step.
  - Every planned deliverable has a producing step.
  - Every render and image step delivers a declared deliverable.
- While planning, an unavailable deliverable's reason must equal the server's reason, and
  the planner cannot call something unavailable that the server can produce. A limitation
  therefore has to be an unavailable deliverable; the prompt forbids stating it only in
  the assumptions, and no assumption text is parsed.
- A rejected plan gets one repair call with the validation message, then fails with "The
  plan could not account for everything you asked to receive."

### Images the user asks for are generated and embedded

- The new `generate_image` capability generates each requested image as a planned step,
  reusing `generate_chat_image_message`. The image is saved as a conversation image
  message tied to the orchestrated answer's deterministic message id and retained as an
  `image-asset-v1` result.
- The answer places images with `[[image:<step_id>]]` tokens. The chat shows them inline
  through the existing image card, viewer, and editor, and each is captioned as an
  AI-generated illustration.
- DOCX, PDF, and PPTX rendering resolve only images in the rendered source's own lineage
  and verify their bytes. Planned images therefore appear in files, which proposal images
  could never do.
- The composer's Image control now asks for explicit image deliverables instead of
  forcing proposal cards. Suggested images stay proposal cards.

### Nothing undelivered is reported as delivered

- A run in which an explicit image step did not complete is incomplete, as a missing
  required file already was.
- A deterministic, model-free **Delivery notes** list follows the answer for each explicit
  deliverable that was not delivered or is unavailable.
- The answer step is told that a later step saves its output as a file, so it writes the
  finished content and never says files cannot be created. For an unavailable deliverable
  it is told not to promise or apologize for it, because the delivery note states it once.

### Review fixes (0.261.138)

An independent review found four issues. Each is fixed and has a regression test.

- **A retry could not deliver a missing image.** With image 2 of 3 refused, the retry
  failed with `recovery_changed`, because the report that completed without the image was
  reused. The 0.261.134 retry fix now runs that report again, and this version adds the
  end-to-end regression: the retry reuses the two images, generates the missing one, writes
  the report and the Word file again, and completes with all three images in both. A retry
  is no longer offered, with reason `retry_would_repeat`, when everything it would run
  again either failed because a service declined its request (`image_content_refused`,
  `image_request_invalid`) or runs again only because of such a step. Resending the same
  prompt would only reproduce the refusal while running the report and file again. The
  rule is generic: `failure_repeats_on_retry` in the schema names the codes, and any other
  failed or unfinished step keeps the retry available.
- **The live chat could show a planned image as an approval card.** The answer rendered
  before its image messages loaded, so its cards showed **Approve**, and approving paid for
  a duplicate image. The terminal frame now carries `generated_images` at its top level as
  well as in the answer's metadata, and the controller reloads the thread from either. A
  card whose image the answer lists never offers **Approve** or **Approve all**; until the
  image loads, it says the image was generated with the answer. The approval route also
  returns the planned image instead of generating another (`find_planned_proposal_image`).
- **One large or WEBP image failed its whole file.** The asset contract admits PNG, JPEG,
  and WEBP up to 20 MB, but the Office renderers accept only PNG or JPEG up to 4 MB. A
  1536x1024 PNG of 4.7 MB failed the Word file with `output_invalid`, and a retry failed
  the same way. After the digest check, the resolver now embeds a rendition
  (`document_image_bytes`): unchanged when it already fits, otherwise re-encoded and scaled
  down only as needed. Generation admits only images this can convert, so size and format
  can no longer fail a file. The chat keeps the original image.
- **A retry moved reused images away from the earlier answer.** Finalization re-linked a
  reused image's `source_assistant_message_id` to the retry's answer, so the earlier
  answer's cards found no image and offered a paid regeneration. Images are no longer
  re-linked. Each answer owns the list of images it shows, and React V2, the classic
  client, and conversation export group images by that list as well as by their source.

### Files modified (0.261.138)

| File | Change |
| --- | --- |
| `functions_orchestration_deliverables.py` (new) | Server truth, validation, answer guidance, image placement, chat projection, delivery notes |
| `functions_orchestration_images.py` (new) | Image readiness and the `generate_image` adapter |
| `functions_orchestration_registry.py` | `generate_image` descriptor, budget, readiness gate, compose and render guidance |
| `functions_orchestration_result_contracts.py`, `functions_orchestration_results.py`, `functions_orchestration_result_runtime.py` | `image-asset-v1` kind, validation, and reads |
| `functions_orchestration_schema.py` | `delivers`, deliverables compilation, optional image inputs, image failure codes |
| `functions_orchestration_planner.py` | Deliverables prompt, server truth, Image control, one repair call, token budget |
| `functions_orchestration_composition.py` | Deliverable guidance, image tokens, missing images |
| `functions_orchestration_executor.py` | Image publication policy, explicit-image reconciliation |
| `functions_orchestration_execution.py`, `functions_orchestration_events.py` | Chat image projection, delivery notes, the answer's image list in the terminal frame |
| `functions_orchestration_rendering.py`, `functions_orchestration_services.py`, `functions_orchestration_bootstrap.py` | Per-render image resolver, verified byte reader, document renditions |
| `functions_orchestration_recovery.py` | `retry_would_repeat` when a retry could only resend declined requests |
| `functions_orchestration_checkpoints.py` | Answer message id helper, deliverables in checkpoint identity |
| `functions_orchestration_plan_revisions.py`, `functions_orchestration_plan_editing.py` | Deliverables in the editor projection and edit context |
| `functions_image_generation.py`, `route_backend_chats.py` | Image options, the stored image's digest, returning a planned image instead of generating another |
| `route_backend_conversation_export.py`, `static/js/chat/chat-messages.js` | Export and the classic client group an answer's listed images |
| `v2_ui/src/...` | You asked for section, image step prompts, image input wording, reload after generated images, planned image cards without approval |

### Validation (0.261.138)

- `functional_tests/test_orchestration_deliverables.py`: 44 test cases in the real headless
  harness, covering validation and repair, `generate_image` gating, budget, prompt checks
  and persistence, DOCX/PDF/PPTX embedding, and the reported requests as scenarios. It
  also covers the edge cases found in review:
  - Turning off a file step at approval rebuilds the answer step's deliverable briefs, so
    a retry of that run still matches its checkpoints.
  - When every planned image fails, the answer and the file hold no leftover image tokens
    or broken image references.
  - A plan revision may drop images that were chosen with the Image control; the revised
    plan carries a review warning instead of failing.
  - A plan that repeats the implicit answer beside its real deliverables keeps the answer.
  - A retry generates the missing image and delivers all three images in the answer and
    the Word file, while the earlier answer keeps its own; no retry is offered when it
    could only resend a refused prompt, but one is when other work could still succeed.
  - A 4.7 MB PNG and WEBP images are embedded in DOCX, PDF, and PPTX as renditions, and
    the chat keeps the originals.
  - The terminal frame lists the answer's images; the approval route returns a planned
    image without calling the image service; export includes a reused image.
- `functional_tests/test_v2_orchestration_deliverables.mjs`: browser normalization,
  deliverable states, a terminal frame read through the real run stream client, and a
  reused image grouped under both answers in React V2 and the classic client.
- `ui_tests/test_v2_orchestration_dependency_plans.py`: the You asked for section in the
  plan panel and approval card.
- `ui_tests/test_v2_orchestration_generated_images.py`: the live chat loading generated
  images after the run, planned image cards that never offer approval, and a reused image
  under both answers.
- `ui_tests/test_v2_orchestration_composer.py` and `ui_tests/test_v2_reasoning_controls.py`:
  the new Image control notice.
- The full `test_orchestration*.py` suite passes apart from the same baseline failures.

With this layer, "create a csv of states and capitals" produces the CSV file itself, and
"create a word file ... images for each president" produces a Word document with a
captioned AI illustration of each president, shown inline in the chat as well. If an image
or the file cannot be produced, the answer says so once, and the run is not reported as
delivered.

## Technical details (0.261.139): Gather / Reason / Render is the only contract

Fixed in version: **0.261.139**.

Chat orchestration is still in development and only the team uses it, so the earlier
phase-based contract was deleted rather than kept as a fallback. Every new plan uses
Gather / Reason / Render whenever **Enable Chat Orchestration** is on.

### The admin toggle and new-plan admission are gone

- `functions_orchestration_admission.py`, `_new_plan_contract_version` in the route, and
  the `enable_chat_orchestration_harness` setting ("Gather / Reason / Render harness
  (preview)") were removed from the defaults, sanitization, admin fields, admin form
  handling, the admin template, the checkpoint settings fingerprint and
  `docs/_data/features.yml`.
- `functions_settings.normalize_retired_orchestration_settings` drops a stored toggle value when settings
  load or save. A stored capability list that named the removed `respond` capability now
  names `compose` (Prepare content) instead, so a narrowed list keeps producing answers.
  The migration never adds Create a file or Generate images to a narrowed list.
- New turns always record `planner_contract_version: 2`. The marker stays in saved data
  for compatibility; the UI never shows it.

### Saved runs from the earlier contract fail closed

A saved plan with no `planner_contract_version`, or with the earlier marker `1`, is never
interpreted. Every entry point refuses it with one stable message, HTTP 409 and code
`legacy_plan`:

> This plan was created by an earlier orchestration version and can't be opened or rerun.
> Start a new request.

This covers run detail and steps, the editor, edit, Ask planner and restore, retry, file
retry, run, cancel, the export catalog, checkpoint restore, continuation, the headless
executor, and a pending clarification or turn from the earlier contract. Unknown markers
are refused as a changed plan, never as legacy. The run list and the planner's earlier-run
context **omit** legacy runs rather than listing them as unavailable. Conversation deletion
still reads them (`read_revision_run(..., allow_legacy=True)`) so their saved data is
removed.

### Removed from the backend

- Planner: the phase-based prompt, `triage_request`, `build_trivial_plan`, and the
  contract branches of `build_planner_messages` and `plan_request`. The one
  `PLANNER_SYSTEM_PROMPT` keeps the earlier prompt's useful guidance: capability authority,
  agents and actions, choosing search versus Analyze and binding Analyze `sources` to a
  search step's `sources` output (replacing `documents_from_step`), web_search versus
  deep_research depth and cost, conversation, memory and ledger use, self-contained step
  tasks, visuals, and clarification and file-answer rules.
- Registry: phases, the `respond` capability, `TERMINAL_CAPABILITY_ID`, `phase_index` and
  `documents_from_step`. One registry holds every descriptor with its role. Discovery that
  only asks whether settings permit a capability passes `include_runtime_bindings=False`;
  planning and execution still require the request-time services.
- Schema: the phase validator, its repairs and the terminal-answer repair.
  `validate_plan` delegates to the dependency validator and refuses invalid plans without
  repairing them.
- Executor and adapters: the phase executor and `_run_single_step`, `run_respond`,
  `RESPONSE_CONTEXT_POLICY`, the uncaptured agent kernel path, the source-review planner
  fallback, and every `plan_contract_version` branch. The transient-retry helpers stay.
- Visuals: `requested_visual_outputs` and its keyword detectors. Ordinary chat's
  `IMAGE_PROPOSAL_REQUEST_MARKERS` and `user_request_supports_image_proposals` stay.
- Checkpoints, recovery, plan revisions, plan editing, runs, continuation and model
  routing: the contract branches, `STEP_TASKS['respond']` and the `respond` branch of
  `answer_selection`. Checkpoint storage failures now always report
  `checkpoint_storage_unavailable`.
- Route: the earlier execution path after the Gather / Reason / Render stream, with
  `_build_invoke_prompt`, `_finalize_execution`, `_record_cited_documents`,
  `_partition_citations` and `_combined_token_usage`. Helpers were renamed without
  "harness", for example `_orchestration_services` and `_prepare_execution_stream`.
- Plan editing: the step that the plan's `final_response` binds, the step that writes the
  chat answer, cannot be disabled. This replaces the earlier "respond cannot be disabled"
  rule.

### Removed from the V2 interface

The phase groups, `TERMINAL_CAPABILITY_ID` and the **Always runs** step, the
`documents_from_step` chip, and every contract fork in the run view, plan card, result
bindings, planned file, map view, stores and controllers. Read-only run records show each
step's real status instead of **Will run**. Opening an old run shows the server's
legacy-record message and stops loading.

### Deliberate behavior removals

| Earlier behavior | Now |
| --- | --- |
| A final `respond` step wrote every answer, and phase ordering | `compose` writes the answer the plan's `final_response` selects; steps run in dependency order. |
| The planner's plan was repaired (unauthorized documents dropped, steps trimmed or reordered, an answer appended) | An invalid plan is refused and the planner is asked again or the request fails. |
| `documents_from_step` passed one step's documents to the next | Analyze binds its `sources` input to a search step's `sources` output. |
| Keyword detection added charts, diagrams or image proposals | Visuals come from the planner's flags on a compose step. |
| Triage produced trivial one-step plans without the planner | The planner plans every request; a one-step compose plan is still valid. |
| The answer step explained or formatted saved Analyze results with `explain_saved_analysis` and keyword-selected `format_saved_analysis` | Compose explains Analyze results bound as inputs, and `render_file` formats them as files (`test_orchestration_reason_render_pipeline.py`). Ordinary chat keeps both functions. |
| Deep research fell back to resolving its own source-review planner | Research uses only the captured planner binding. |
| Agent steps ran through the uncaptured Semantic Kernel path | Agent steps run only under the acquisition capture, which admits Azure AI Foundry (classic) agents without local actions, workspace knowledge or web sources. Local Semantic Kernel agents are refused safely. |
| When the answer message could not be saved, the earlier path still streamed the unsaved explanation with the step's failure | The run records `message_not_saved`, never streams an answer it could not save, and the browser shows the could-not-save notice. |
| The admin could turn Gather / Reason / Render off for new plans | There is no switch; Chat Orchestration on means Gather / Reason / Render. |

### Files modified (0.261.139)

- `application/single_app/config.py` (version), `functions_settings.py`,
  `admin_settings_fields.py`, `route_frontend_admin_settings.py`,
  `templates/admin/_panes/chat-orchestration.html`; `functions_orchestration_admission.py`
  deleted.
- `functions_orchestration_registry.py`, `_schema.py`, `_planner.py`, `_executor.py`,
  `_adapters.py`, `_visuals.py`, `_composition.py`, `_checkpoints.py`, `_recovery.py`,
  `_plan_revisions.py`, `_plan_editing.py`, `_runs.py`, `_model_routing.py`,
  `_continuation.py`, `_execution.py`, `_services.py`, `_scheduler.py`, `_actions.py`,
  `_context.py`, `_external_sources.py`, `route_backend_orchestration.py`,
  `route_backend_v2.py`.
- V2 UI: `components/chat/Orchestration*.tsx`, `lib/orchestration*.ts`, `lib/types.ts`,
  `stores/orchestrationStore.ts`, new `lib/orchestrationErrors.ts`.
- Tests: new `functional_tests/test_orchestration_single_contract.py`,
  `test_orchestration_route_recovery.py` and `test_orchestration_elicitation_routes.py`;
  deleted the admission, phase-ordering, v1-only checkpoint and admin toggle tests;
  migrated the remaining suites and UI tests to Gather / Reason / Render.
- Docs: `docs/admin/orchestration.md`, `CHAT_ORCHESTRATION.md`, the renamed
  `ORCHESTRATION_GATHER_REASON_RENDER.md` (was `ORCHESTRATION_RENDERING_HARNESS.md`), the
  external source, checkpoint recovery, output lifecycle, deliverables and actions feature
  docs, the orchestration guides and `docs/reference/chat-controls.md`.

### Validation (0.261.139)

- `functional_tests/test_orchestration_single_contract.py` (new, 53 tests): the toggle is gone
  from the settings defaults, sanitization, admin fields, admin route, template and docs
  inventories; a stored toggle and `respond` capability are retired on load and save; one
  registry has no phases or `respond`; discovery and planning treat runtime services
  correctly; the one planner prompt keeps each piece of ported guidance; new plans always use
  the single contract; legacy plans are detected, while unknown markers are refused as changed
  plans; the executor, headless runtime, checkpoints, recovery, plan revisions and
  continuation refuse legacy runs; listings omit them; and every by-id route answers
  `409 legacy_plan` without binding services or changing the saved record.
- `functional_tests/test_orchestration_route_recovery.py` and
  `test_orchestration_elicitation_routes.py` (new), plus the migrated conversation context,
  plan revision, memory, elicitation, research selection, deep research, planner
  diagnostics, schema, registry, executor, adapter, citation, context picker, visual output
  and catalog execution suites, re-express the earlier behavior that still matters.
- The full `functional_tests/test_orchestration*.py` suite passes: 115 files.
  `test_orchestration_harness_execution.py` (649 tests) can time out only under the parallel
  runner. The earlier baseline failures in the conversation context, conversation context
  routes, elicitation and memory suites no longer occur, because those suites now run on the
  current contract.
- The three route policy tests and both docs checks pass.
- V2 UI: `npm run typecheck`, the six `functional_tests/test_v2_orchestration*.mjs` files and
  all 20 `ui_tests/test_v2_orchestration_*.py` files pass. That includes the browser-to-Flask
  recovery suite, which now runs against real Gather / Reason / Render execution. The admin
  actions, planner model, reasoning controls, model catalog, context selection, elicitation
  composer and prompt composer UI suites pass too.
- Baselines are unchanged: `test_*image*.py` 22/31 and `test_*admin*.py` 58/74.
  `ui_tests/test_v2_orchestration_auto_open.py` run as a script and
  `ui_tests/test_chat_three_document_smoke.py` fail as they do on the base.
- Key suites also pass under `python -O`, and the XSS and broken access control guardrails
  pass on the changed files.

Before this layer, new plans used Gather / Reason / Render only when an administrator turned
on a preview setting, and other plans used the phase-based contract with its separate
answer step. Now every plan uses Gather / Reason / Render, a plan saved by the earlier
contract shows one clear message instead of opening, and no code path interprets it.
