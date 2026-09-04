# Chat Orchestration

**Implemented in version: 0.261.086**
**Knowledge phase added in version: 0.261.088**

## Overview

Chat orchestration lets a user describe what they want and have SimpleChat work out how to
answer it. Instead of choosing documents, search scope, web search, a saved prompt, an
agent and a model before asking, the user asks. SimpleChat plans the work, shows the plan,
and runs it once approved.

The plan is built by a model, but that model never performs any work. It is shown a short
list of described capabilities and returns a plan as JSON. A deterministic executor then
runs the plan's steps through adapters over the retrieval and analysis functions that
already exist. This is deliberately not Semantic Kernel function calling: with 44 plugin
classes and 27 actions available in this application, handing all of them to a model and
relying on auto-invocation is both unreliable and expensive. Semantic Kernel remains how an
*agent* runs; when a plan eventually dispatches an agent, that agent still sees only its
own configured actions.

This is a V2 interface feature. The classic interface is unchanged.

## Dependencies

- `enable_chat_orchestration` must be on.
- Each capability a plan can use must be separately enabled. Orchestration reaches only
  what a user could already reach by hand, and grants no new access.
- A chat model must be configured. A dedicated planner deployment is optional.

## Architecture

The framework has four phases.

### Inputs

`functions_orchestration_registry.py` holds the capability registry: one declarative
descriptor per capability, carrying its identifier, label, kind, a one-line summary,
guidance on when it applies, its settings gates, a JSON Schema for its arguments, what it
produces, a cost class and a per-plan cap. The registry is the only capability information
the planner ever sees, and it is also what the validator checks a plan against, so a
capability cannot be executable without also being describable and gated.

Three gate forms are supported because the real conditions are of three shapes: every named
setting must be true (`settings_gates`), at least one must be (`settings_gates_any`), or a
callable decides (`gate`). Document analysis and comparison use the third, because their
enablement lives in a nested capability record rather than a flag.

`functions_orchestration_context.py` resolves what a request could act on:

- **Candidate documents by relevance, not a catalogue.** Listing a user's workspace does
  not survive contact with a real deployment; a user with several hundred documents would
  spend the planner's whole context on file names. A cheap search probe using the user's
  own message is aggregated to distinct documents instead. When the user has already
  selected documents, no probe runs.
- **Seeds as constraints.** Anything chosen in the composer narrows the plan rather than
  suggesting to it.
- **The run ledger.** A compact, byte-bounded summary of the conversation's earlier runs,
  covering what was searched, what was produced and what the user has already been asked.
  This is a planner input rather than a display artefact: it is what lets a follow-up
  question reuse earlier findings instead of repeating them, and what stops an elicitation
  asking the same question twice.

### Plan

`functions_orchestration_planner.py` triages first. The point of triage is to stop a
conversational question costing a planning round trip, so triage itself is heuristic rather
than a model call — doing it with a model would spend exactly the round trip it saves. The
heuristics are biased towards planning: a false positive costs one cheap call, while a
false negative answers a document question without looking at the documents.

Where a plan is needed, the planner returns either a plan or an elicitation.

`functions_orchestration_schema.py` holds both contracts and the validator. **Planner
output is treated as untrusted input.** A plan naming a capability that does not exist,
using one an administrator disabled, referencing an unreadable document, or containing a
dependency cycle is within the normal range of a generative system. Each is caught before
an adapter is reached. The validator repairs where repair is honest and drops where it is
not, and records what it did in `validation.repairs` so the card can show a plan that
differs from the proposal and say why.

### Phases

Every capability declares a `phase`, and the phases are ordered:

```
knowledge  ->  reasoning  ->  output
```

| Phase | Meaning | Capabilities |
| --- | --- | --- |
| `knowledge` | Produces something the answer can be based on | `document_search`, `document_analyze`, `document_compare`, `tabular_analyze`, `web_search`, `url_fetch`, `deep_research`, `agent_invoke` |
| `reasoning` | Turns what was gathered into an answer | `respond` |
| `output` | Declared, not yet populated | — |

The boundary is drawn at *evidence*, not at effort: analysing and comparing documents are
knowledge steps because they produce something to reason over, even though they involve a
model call. Answering is the only reasoning step, because it is the only one that commits
to a claim.

`CAPABILITY_PHASES` is an ordered tuple, so a capability's phase is an index and "may this
step follow that one" is an integer comparison rather than a table of special cases. The
validator stably sorts by phase before the topological pass and drops a `depends_on` edge
that points backwards across a phase boundary, recording a repair note.

This replaced an earlier `kind` field (`retrieval` / `analysis` / `synthesis`) that was
carried all the way to the browser and read by nothing. Two overlapping taxonomies where
one is decorative is how a field comes to mean nothing, so `kind` was removed rather than
kept alongside.

**What enforcement buys.** A plan that searches after it has answered is not a plan, it is
a mistake: it would run, and produce an answer written without the evidence the later step
just found. That is a silent wrong answer rather than a visible failure, which is the worst
kind.

### Knowledge capabilities that produce text rather than evidence

`build_evidence_envelope` requires a non-empty `document_id`, a `source_kind` of `tabular`
or `narrative`, and an `engine` from three values. An agent returns free text plus tool-call
citations tied to no document, and source review returns a JSON blob plus citations.
Neither can honestly produce evidence.

So `agent_invoke`, `url_fetch` and `deep_research` produce `notes` and `citations` instead.
This is not a workaround: `RunContext.merge_step_result` already accumulates notes, and the
respond adapter already folds them into its prompt. A knowledge step that gathers *text*
rather than *document evidence* reaches the answer through a path that already existed.

### Two levels of gate

A capability is gated twice, and the two answer different questions.

| Gate | Question | Read by |
|---|---|---|
| `gate(settings)` | Does this deployment have the capability at all? | The admin page, the bootstrap payload, and planning |
| `request_gate(settings, context)` | May *this caller, asking this question* use it? | Planning only |

`resolve_available_capabilities` applies request gates **only when a request context is
given**. That is deliberate: the admin page and the bootstrap payload describe a
deployment, not a caller, and would be wrong to hide a capability because the administrator
viewing the page happens to have no agents.

But it means a caller that forgets to pass a context silently gets the deployment answer.
`plan_request` takes `request_context` and forwards it, so one resolution narrows three
things at once: what the planner is offered, what the validator accepts, and therefore what
can reach an adapter. `test_orchestration_adapter_contract.py` asserts that the parameter
exists, that it is forwarded, and that the route supplies one.

Every request gate **fails closed** — a gate that raises withholds the capability. These
read app roles, and an error resolving a role is not a reason to assume the caller holds it.

### Execute

`functions_orchestration_executor.py` orders steps topologically over `depends_on` and runs
them through `functions_orchestration_adapters.py`. The shared run context is built on the
existing mixed-source evidence envelope contract rather than a new one, so byte bounds,
cancellation and telemetry come with it.

Authorization is checked twice: when the plan is validated, and again before the answer is
composed. Those are not the same moment, and access can be revoked between them.

#### The worker-thread boundary

`execute_plan` runs in a `threading.Thread` so progress can stream while work happens. That
thread has no Flask request context: no `g`, no `session`, no `current_app`. **An adapter
must never read Flask state.** Every request-scoped value an adapter needs is captured on
the request thread by `_request_identity()` in `route_backend_orchestration.py` and carried
explicitly on `RunContext`.

This matters most for `user_roles`, which gates the `UrlAccessUser` and `DeepResearchUser`
app roles. Guessing it would either deny a permitted user or, far worse, admit one who
holds no role. Absent roles normalise to "no roles" and the gate denies — the failure mode
is a feature that does not appear, never one that appears when it should not.

The capture happens outside the streamed generator, because a generator body runs *after*
the view returns, when the session is already gone. `test_orchestration_adapter_contract.py`
asserts all of this statically.

### Outputs

The answer is an ordinary assistant message, so the existing renderer, citation and export
pipeline all apply unchanged. Alongside it, a run record is written to the
`orchestration_runs` and `orchestration_run_steps` containers, and a plan summary is
recorded on the assistant message so reopening a conversation shows what produced the
answer.

## API

Two endpoints, deliberately separate. The plan is durable between them, so a dropped
connection cannot lose it, editing is straightforward, and the existing 24,600-line chat
route is untouched.

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/api/v2/orchestration/plan` | POST | Streams planning progress, then terminates with either a plan or a question set. |
| `/api/v2/orchestration/run` | POST | Executes an approved plan, streaming step progress and the answer. |
| `/api/v2/orchestration/cancel/<run_id>` | POST | Asks a running plan to stop. |
| `/api/v2/orchestration/runs` | GET | Every run in a conversation, oldest first, for the drawer's map view. |
| `/api/v2/orchestration/runs/<run_id>/steps` | GET | One run's steps, for expanding a row in the map view. |

Cancellation is recorded on the run rather than signalled in process memory. The run is a
blocking POST held by one worker while the cancel request lands wherever the load balancer
sends it, so the record is the only place both can see. The executor polls it between
steps. This is the same approach the workflow runner takes.

Progress on the run endpoint is produced by a worker thread feeding a queue that the
response drains. The executor is synchronous and calls its progress callback from inside
its own loop, and a generator cannot yield from a callback — collecting frames and flushing
them at the end would have delivered every step event at once, after the answer, which is
precisely the "looks hung" experience the progress exists to prevent.

### Stream events

Progress rides the existing `thought` event, byte-for-byte the shape the chat stream already
emits, so `ThoughtTracker` persistence and the client's activity-lane rendering work
unchanged and a live run draws identically to a reloaded one. Orchestration adds the
`step_type` values `orchestration_triage`, `orchestration_planning`, `orchestration_step`
and `orchestration_synthesis`, each carrying `activity.lane_key = "orchestration"`.

Three event types are genuinely new, because nothing existing meant the same thing:
`orchestration_plan`, `orchestration_elicitation` and `orchestration_step`.

## Clarifying questions

When the orchestrator cannot plan without more information it asks in an inline card rather
than in the chat thread, and the card is driven by a JSON Schema.

That schema is deliberately shaped to the MCP elicitation specification: a flat object whose
properties are primitives or arrays of primitives, so any client can render it without a
general JSON Schema implementation. Our own paging lives in a sibling `ui_hints` field so
the schema itself stays MCP-clean, and the response is MCP's shape verbatim,
`{action, content}` with `action` one of `accept`, `decline` or `cancel`. A future MCP
server asking a question therefore renders through the identical card.

Declining or cancelling carries no content, so a refusal cannot be used to smuggle answers
past the user.

## Configuration

All settings live under the Orchestration group in Admin Settings. The keys are prefixed
`chat_orchestration_` rather than `orchestration_`, because `orchestration_type` and
`enable_multi_agent_orchestration` already exist and mean something entirely different —
which Semantic Kernel multi-agent pattern runs a selected agent.

See [the Orchestration settings page](../../admin/orchestration.md) for the full table.

## File structure

| File | Responsibility |
| --- | --- |
| `functions_orchestration_registry.py` | Capability descriptors, gating, planner and client projections |
| `functions_orchestration_schema.py` | Plan and elicitation contracts, validator, repair, step results |
| `functions_orchestration_context.py` | Candidate documents, seeds, signals, run ledger |
| `functions_orchestration_planner.py` | Triage, plan synthesis, elicitation, re-planning |
| `functions_orchestration_adapters.py` | Capability adapters over existing functions |
| `functions_orchestration_executor.py` | Step engine, budgets, cancellation, re-authorization |
| `functions_orchestration_runs.py` | Run and step persistence |
| `functions_orchestration_events.py` | Stream event builders |
| `route_backend_orchestration.py` | The V2 endpoints, conversation and message persistence |

## Usage

1. Enable Chat Orchestration in Admin Settings, under Orchestration.
2. Choose an approval mode. Review is the default and the safest starting point.
3. Open a V2 chat. Where orchestration is enabled the composer opens in it, with the
   capability toggles and the model, agent and reasoning pickers folded behind **Manual
   controls**; file upload and voice input stay where they are. The **Orchestrate** toggle
   turns it off again for anyone who wants the classic composer.
4. Ask a question. A plan appears; approve, adjust or cancel it.
5. Watch progress in the Plan panel of the right-hand drawer.

Anything selected inside the manual controls is passed as a seed and constrains the plan,
so a power user can still pin the work to a particular document or agent and let
orchestration decide the rest.

Administrators changing these settings from the classic Admin Settings page do not need to
reload an open chat tab: the interface re-reads its configuration when the tab comes back
to the front.

## Testing and validation

| Test | Covers |
| --- | --- |
| `functional_tests/test_orchestration_registry_contract.py` | Descriptor shape, gating, administrator narrowing, and that internal fields never reach the planner |
| `functional_tests/test_orchestration_plan_schema.py` | Unknown and disabled capabilities, document authorization, argument coercion and bounds, cycles, step caps, narrowing-only edits, approval states |
| `functional_tests/test_orchestration_elicitation_schema.py` | The MCP flat-object restriction, paging staying outside the schema, response validation |
| `functional_tests/test_orchestration_run_ledger.py` | Run and byte bounds, oldest-first compaction, honest truncation, answered questions carrying forward |
| `functional_tests/test_orchestration_invoke_prompt_contract.py` | The model-call convention: the route's closure must accept what the adapters and the document functions actually pass, and must count token usage |
| `functional_tests/test_orchestration_executor.py` | Step ordering, dependency skipping, cancellation, budget caps, re-authorization |
| `functional_tests/test_orchestration_phase_ordering.py` | Knowledge sorts before reasoning, a plan gathering after answering is repaired, a backwards dependency is dropped with a note |
| `functional_tests/test_orchestration_adapter_contract.py` | Every capability resolves to an adapter, every adapter matches the executor's call signature, no adapter touches Flask state, and identity is captured on the request thread |
| `functional_tests/test_orchestration_citation_persistence.py` | Cited documents reach the conversation's used-document list, and document and web citations are separated |

## Known limitations

- **Model routing is not implemented.** The model catalogue currently records almost no
  capability metadata, so plans use one configured planner model and the default chat model
  for execution. Each step records which model it used, so per-step routing can be added
  without changing the plan contract.
- **Retrieval and reasoning only.** Image generation, file exports, workspace placement,
  sharing, mail and MCP or OpenAPI actions are not yet capabilities a plan can contain. The
  `output` phase is declared for them but empty.
- **An agent step produces no artifacts.** Charts and images an agent generates are written
  through the Flask-bound message-artifact pipeline, which the worker thread cannot reach.
  The adapter surfaces the agent's tool activity as citations instead and returns no
  artifacts.
- **One agent per plan.** Loading an agent resolves Key Vault secrets, hydrates every plugin
  it declares, and introspects SQL and Cosmos schemas. There is no working kernel cache, so
  each agent step pays that cost in full.
- **Steps run sequentially.** The executor orders steps by dependency but does not run
  independent steps in parallel.
- **Workflows do not yet execute against this engine.** The run record was shaped with that
  in mind, but the two remain separate.

## Related

- [Orchestration settings](../../admin/orchestration.md)
- `docs/explanation/release_notes.md`
