# Chat Orchestration

**Version: 0.261.105** (tracked in `application/single_app/config.py`)

**Implemented in version: 0.261.086**
**Knowledge phase added in version: 0.261.089**
**Inline composer answers implemented in version: 0.261.096**
**Research selection and multi-query execution updated in version: 0.261.099**
**Direct action access implemented in version: 0.261.098**
**Conversation continuity implemented in version: 0.261.096**
**Follow-up resolver compatibility fixed in version: 0.261.103**
**Selected/default model routing fixed in version: 0.261.103**
**Approval preference persistence fixed in version: 0.261.101**
**Conversational plan editing implemented in version: 0.261.102**
**Capability-aware planning and reasoning compatibility fixed in version: 0.261.104**
**Failure communication and checkpoint recovery implemented in version: 0.261.105**

## Overview

Chat orchestration lets a user describe what they want and have SimpleChat work out how to
answer it. Instead of choosing documents, search scope, web search, a saved prompt, an
agent and a model before asking, the user asks. SimpleChat plans the work, shows the plan,
and runs it once approved.

The plan is built by a model, but that model never performs any work. It is shown a short
list of described capabilities and returns a plan as JSON. A deterministic executor then
runs the plan's steps through adapters over the retrieval and analysis functions that
already exist. The top-level planner is deliberately not handed the entire plugin
catalogue. A configured agent still sees its own configured actions, while an optional
**Use an action** step can reach one existing integration directly, without loading an
agent. That step uses a bounded function-calling loop limited to the selected action and
its required companions.

This is a V2 interface feature. The classic interface is unchanged.

## Dependencies

- `enable_chat_orchestration` must be on.
- Each capability a plan can use must be separately enabled. Orchestration reaches only
  what a user could already reach by hand, and grants no new access.
- A chat model must be configured. A dedicated planner deployment is optional.
- Direct action access additionally requires Semantic Kernel and the default-off
  `enable_chat_orchestration_actions` switch. Existing action scope settings and
  governance continue to determine which actions the caller can use.

## Architecture

The framework has four phases.

### Inputs

`functions_orchestration_registry.py` holds the capability registry: one declarative
descriptor per capability, carrying its identifier, label, phase, a one-line summary,
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
  contextualized request is aggregated to distinct documents instead. When the user has
  already selected documents, no probe runs.
- **Positive requirements and resource filters.** Supported selected tools, documents,
  and agents must be used by the initial plan. Unchecked controls are neutral, not
  permission denials. Other enabled, authorized capabilities remain available.
  Workspace, tag, and document filters still bound source access.
- **Accessible actions by description.** Where action access is enabled, the planner
  receives safe metadata for governed actions, not credentials, connection settings or
  every action's function schemas. Scoped references distinguish actions with the same
  name. A manually selected agent keeps direct action access out of that request.
- **Conversation history.** Eligible recent user and assistant messages are loaded from
  the owned conversation on the server, not from whichever messages the browser has loaded.
  This gives a follow-up its subject and preserves relevant earlier constraints.
- **The run ledger.** A compact, byte-bounded activity summary covering earlier searches,
  produced artifacts, and answered questions. It helps avoid unnecessary repeated work,
  but does not replace message history or prove that source evidence is available.
- **Saved memory.** Since **0.261.104**, enabled Fact Memory supplies up to eight instruction
  memories and four relevant embedded facts for planning, planner edits, and answering.
  Current instructions take precedence. Private conversations use the caller's memory, or
  the first active group's authorized memory in group/all source mode. Shared conversations,
  including owner-held hidden source records, do not receive saved memory.

#### Conversational follow-ups

Before candidate retrieval, a small completion interprets substantive requests against
the recent conversation. "Which are open on Wednesdays" can therefore refer to the
wineries just discussed near Grants Pass rather than become a generic opening-hours
query. The original user message is preserved, and the resolved request is used for
retrieval, planning, and delegated tasks.

Explicit changes take precedence over earlier constraints. A new topic does not inherit
the old topic's location or subject. Reformatting an available answer can use a
respond-only plan, while new factual questions still need evidence. An earlier
recommendation is not proof that a business is open.

The history window uses **Conversation History Limit** from Chat settings, rounded up
to an even count and capped at 50 messages and 16 KiB of serialized snapshot data.
The normal setting default is 10; a missing setting falls back to six. Zero disables
history. Older content is trimmed first, and truncation is identified explicitly rather
than silently clipping every message to 300 characters.

Masked text, inactive attempts, hidden generated artifacts, system/tool records, and
binary payloads are excluded. Current block revisions are respected. The snapshot and
its source fingerprints are saved with the plan, so a reload or a delayed approval uses
the same context. Changes to the referenced messages or their visibility require a new
plan; newly appended turns do not enter an older run.

These rules apply to Auto, countdown, and manual approval. They do not introduce rolling
summaries or cross-conversation transcript lookup. Existing scoped saved memories are
separate from this history window. First turns without history and simple
acknowledgments do not require a resolution completion.

Saved memory recall is read-only: it does not autosave facts or fill missing embeddings.
Unavailable fact search is identified explicitly; query embeddings may still require a
model call. Only audience and scope markers are retained with the plan or cached
clarification, not the raw memory prompt. Current settings, membership, and audience are
checked again before final synthesis; the recalled scope is reauthorized after the model
call before publication. Questions and replays also enforce those boundaries.
Answers preserve memory citations. See the
[capability-context fix](../fixes/ORCHESTRATION_CAPABILITY_CONTEXT_FIX.md#read-only-saved-memory)
for scope and availability details.

Since **0.261.103**, an unused `clarification: null` in the resolver's JSON is
accepted as "no clarification needed", just like an empty string. It does not
discard the rest of a valid follow-up or require another model call. A request
whose relationship is `clarification` still needs a nonempty question.

Other malformed resolver output gets at most one corrective completion using
the same bounded history, original request, and clarification answers. Both
completions count toward the successful turn's token usage. Unknown message IDs,
invalid required field types, and inconsistent relationships remain invalid:
the application never drops history or starts a new topic merely to make a
response pass validation. Persistent failure produces an interpretation error,
distinct from an inaccessible or changed conversation.

Refused, filtered, absent, or incomplete completions are not retried as malformed
JSON. The resolver does not mistake provider failures for unsupported JSON formatting; only
an explicit unsupported-response-format error uses the existing no-format
compatibility fallback. The plan generator uses the same narrow format-error rule.
Model failures are surfaced, not converted into an answer-only plan. No new
model setting or API version is required.

#### Model selection

The answer model comes from **Manual controls** when one is selected, otherwise from
the administrator's default model connection. Classic single-endpoint or APIM settings
remain the fallback only when no connection-based selection or default applies.
The selected deployment, provider, endpoint ID and model ID are resolved together:
changing only the deployment on a legacy client could send it to the wrong endpoint.

The authorized answer choice is saved with the plan, including a resolved admin default.
Changing the default while approval is pending does not retarget that run. The model is
authorized again at execution, so a disabled, removed or inaccessible selection produces
an error instead of silently switching to another model.

Without a dedicated planner override, the same selection handles conversational
resolution, plan generation and research review as well as the answer. A configured
planner deployment or endpoint remains separate and does not override the answer model.
Planner endpoint selections use the existing planner model/endpoint/provider settings and
the caller's normal model access checks. A deployment-only planner override retains the
classic single-endpoint/APIM connection.

Planning resolves its client on the request thread after restoring canonical turn state,
with authenticated streaming context retained for endpoint authorization. Execution
captures bindings before starting its worker, and direct actions receive the actual
answer model identity.
GPT-5-family completions use `max_completion_tokens`, omit unsupported temperature,
and retain compatible manual reasoning effort. A positive configured model response
length governs answer calls; otherwise reasoning completions have an 8192-token budget
floor so reasoning does not consume the entire smaller visible-output allowance.
Anthropic completion flags are normalized at the protocol boundary, so successful
Claude follow-ups pass the same strict checks while truncation and refusal remain failures.

Both chat interfaces consume a canonical, per-model reasoning policy. A configured
model ID is a preference identity, not a model family. An unsupported stored effort
uses the policy's supported application default with a visible notice; Luna Minimal
becomes Low. Explicit supported None is sent unchanged. Unknown support or a narrowly
classified provider rejection uses the model-managed default and reports that honestly,
without switching deployments. See the
[reasoning compatibility fix]({{ '/explanation/fixes/ORCHESTRATION_REASONING_LEVEL_COMPATIBILITY_FIX/' | relative_url }}).

The saved assistant message and terminal stream identify the model that actually answered.
The existing V2 renderer displays that name. Empty, refused, filtered or failed answer
completions produce an error rather than a success-shaped empty turn.

#### What the context picker contributes

The composer's context picker lets a user name documents, tags and whole workspaces before
asking. Each reaches the plan differently, and the difference is the point.

| Picked | Seed | Effect on planning |
|---|---|---|
| A document | `document_ids` | Replaces the candidate probe. The user answered "which documents", so probing would only offer alternatives to a decision already made. |
| A tag | `tags` | **Scopes** the probe. A tag answers "which shelf", not "which document" — the probe still decides which documents on that shelf are worth naming. |
| A workspace | `doc_scope`, `active_group_ids`, `active_public_workspace_ids` | Bounds where the probe and every search step may look. |

Treating a tag as an explicit choice would hand the planner every document carrying it,
which is the opposite of narrowing. `seeds_are_explicit` therefore tests documents alone.

Tags are carried on `RunContext` for the whole run rather than per step, because a tag is a
standing narrowing of what the turn is about: a step is free to choose its own query, but
not to widen the shelf the user narrowed to. `document_filter_mode` travels with them —
without it a picked document beside an unrelated tag intersects to nothing.

#### Document names

`resolve_candidate_documents` used to return seeded documents with an empty `file_name`,
so a picked document reached the planner as a bare uuid. That breaks two things: the
planner cannot write "compare the Q3 and Q4 contracts" if it was never told which document
is which, and the approval card — whose entire purpose is letting someone confirm the
planner picked the right document — showed a row of identifiers.

The composer had those names on screen when the user clicked them, so it sends them as
`context_documents` rather than making the server resolve across three containers to
recover what was just discarded.

**Names are display; authorization is by id.** `_authorized_document_ids` reads
`document_ids` and nothing else, so a client that renamed a document mislabels its own plan
card and reaches nothing new. `test_orchestration_context_picker.py` asserts this directly.

#### Reading what an earlier step found

Every step's documents used to be fixed when the plan was written, which meant a plan could
not express the most natural shape of all: search for the relevant material, then analyse
what turned up. The planner had to guess document ids from the candidate probe, or the plan
simply could not say it.

A step may now set `documents_from_step` to an earlier step's `step_id` instead of naming
documents. At run time the adapter resolves it from `RunContext.step_documents`, which
records which documents each step reached.

The reference is validated where the surviving step ids are known, because ids can be
renamed during validation. It must name a step that exists, must not name the step itself,
and must name a capability that *produces evidence* — pointing at a web search or at
`respond` would resolve to nothing every time. A resolved reference is added to
`depends_on`, and the topological pass is what guarantees ordering; positions are
deliberately not checked here as well, since that would duplicate the cycle detection and
disagree with it as soon as phase ordering moved a step.

Two constraints are worth stating plainly:

- **It widens nothing.** Documents arriving this way came from a search, which only returns
  what the user can read, and the document functions resolve access again from the user id
  and scope they are given.
- **It does not dodge the administrator's ceiling.** The validator trims the documents a
  plan *names*, but it cannot trim what a search has not run yet, so the limit is applied
  again when the reference resolves.

The cost is real and is the reason this is not the default: a plan that defers its
documents cannot show the user which ones it will read. The approval card says "whatever
the earlier step finds" rather than pretending to a list, and the planner is told to name
documents directly whenever they are already known.

### Plan

Every Orchestrate request reaches `functions_orchestration_planner.py`, including short
questions and acknowledgments. The planner returns a plan or an elicitation. There is
no keyword/length shortcut that decides retrieval is unnecessary before the model sees
the available capabilities. This deliberately adds a planning call to requests that
previously bypassed it; ordinary chat is unchanged by that orchestration policy.

The context separates available capabilities, their actual unavailability reasons,
positive user requirements, and authorized resources. Descriptors include outputs and
per-plan limits, and the context carries the current UTC time. A model's claim that a
feature is unavailable is not an authorization decision. Discovery failures surface as
failures instead of silently replacing a catalog with an empty list.

Initial plans cannot silently drop selected operations or documents. A subsequent
reviewed edit can narrow them, with a visible warning. Planned Web use is kept separate
from original Web selection during restoration. Current access and feature gates are
checked again before execution.

`functions_orchestration_schema.py` holds both contracts and the validator. **Planner
output is treated as untrusted input.** A plan naming a capability that does not exist,
using one an administrator disabled, referencing an unreadable document, or containing a
dependency cycle is within the normal range of a generative system. Each is caught before
an adapter is reached. The validator repairs where repair is honest and drops where it is
not, and records what it did in `validation.repairs` so the card can show a plan that
differs from the proposal and say why.

#### Choosing research depth

The planner weighs the expected benefit of additional discovery and evidence against
its cost. Ordinary web search is appropriate for focused lookups; deep research becomes
useful when exploring different perspectives, reading detailed sources, or reconciling
evidence would materially improve the requested result. It is not necessary to prove
that a shallow search could produce no answer at all.

The choice remains model-led. There is no keyword router, fixed research-selection rate,
or automatic preference for deeper work. Prompt length, multiple preferences, and
freshness alone do not determine the choice. A short rationale in the existing plan
step explains why the selected depth fits the request.

The planner makes this choice before execution. Ordinary search results are not graded
by a new model call or automatically escalated into research.

### Phases

Every capability declares a `phase`, and the phases are ordered:

```
knowledge  ->  reasoning  ->  output
```

| Phase | Meaning | Capabilities |
| --- | --- | --- |
| `knowledge` | Produces something the answer can be based on | `document_search`, `document_analyze`, `document_compare`, `tabular_analyze`, `web_search`, `url_fetch`, `deep_research`, `agent_invoke`, `action_invoke` |
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

So `agent_invoke`, `action_invoke`, `url_fetch` and `deep_research` produce `notes` and `citations` instead.
This is not a workaround: `RunContext.merge_step_result` already accumulates notes, and the
respond adapter already folds them into its prompt. A knowledge step that gathers *text*
rather than *document evidence* reaches the answer through a path that already existed.

#### Self-contained deep research

Since version **0.261.099** (`application/single_app/config.py`), the research adapter
calls the same `perform_research_web_searches` helper as manual Deep Research before
calling `perform_source_review`. It can discover sources without a preceding web-search
step or a URL in the request. A separate search is only useful when it serves a distinct
objective rather than duplicating research's discovery.

The shared query generator retains model-planned queries and its existing supplemental
and backup variants. Queries stay within the configured limit, and source review retains
its URL, page, depth, domain, and robots policy. The capability remains high-cost and
limited to one step per plan. Feature and role permission is rechecked before discovery
starts, not only when the planner sees the capability.

Outbound query planning uses only the current user message. The orchestration objective
can reflect earlier context, but private document content, previous conversation text,
and internal search rewrites are not forwarded into this new discovery path. Current-run
web citations and the user's own URLs can still seed source review.

Query progress uses existing orchestration events. Cancellation and deadlines are checked
between internal searches and before source review; this does not add hard interruption
of an in-flight provider call.

If the optional query planner fails, research continues using the existing backup plan.
Recovery details stay in logs when useful evidence is obtained. Per-query outcomes keep
failed-query control messages out of successful evidence notes, while usable search
results and reviewed sources remain available to the answer. A run that finds nothing
usable explicitly tells synthesis not to claim research verification.

#### Direct action execution

Direct actions retain their existing function restrictions and behavior; this capability
does not classify operations as read-only or introduce another approval system. **Call
agent** actions stay on the existing **Ask an agent** path. See
[Chat Orchestration Action Access](CHAT_ORCHESTRATION_ACTIONS.md) for configuration,
scope rules and execution details.

### Two levels of gate

A capability is gated twice, and the two answer different questions.

| Gate | Question | Read by |
|---|---|---|
| `gate(settings)` | Does this deployment have the capability at all? | The admin page, the bootstrap payload, and planning |
| `request_gate(settings, context)` | May *this caller, asking this question* use it? | Planning, plus direct action execution checks |

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

An action is also resolved and authorized at execution and before subsequent function
calls. Revocation, definition changes, cancellation or a failed operation stop further
action calls instead of silently substituting an agent or another integration.

#### Failures and resumable attempts

Since **0.261.105**, measured timeouts are distinct from explicit Stop. Safe
failure facts reach the final response, and an application-generated status
message reports incomplete work if the answering model cannot finish. The
conversation does not depend on a successful model call to explain an execution
failure.

Completed steps save full reusable results in private, versioned checkpoints.
**Retry from failed step** creates a linked attempt of the same effective plan
and restores valid completed results without calling their adapters again.
Current source, context, agent/action, and model access are rechecked. Invalid
checkpoints block recovery instead of causing a silent full-plan replay.

An agent/action may have performed external effects inside its failed step.
Retrying that step requires confirmation when effects could repeat. Recovery
does not restore the agent's internal tool loop and never runs automatically.
See [Checkpoint recovery](ORCHESTRATION_CHECKPOINT_RECOVERY.md).

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

Planning and execution are deliberately separate requests. The plan is durable between
them, so a dropped connection cannot lose it. Editor operations revise that saved plan
without starting its steps or adding messages to the main conversation.

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/api/v2/orchestration/plan` | POST | Streams planning progress, then terminates with either a plan or a question set. |
| `/api/v2/orchestration/run` | POST | Executes an approved plan, streaming step progress and the answer. |
| `/api/v2/orchestration/cancel/<run_id>` | POST | Asks a running plan to stop. |
| `/api/v2/orchestration/runs` | GET | Every run in a conversation, oldest first, for the drawer's map view. |
| `/api/v2/orchestration/runs/<run_id>` | GET | One saved plan with its outcome and safe recovery eligibility. |
| `/api/v2/orchestration/runs/<run_id>/retry` | POST | Idempotently prepares a linked recovery attempt, with confirmation for uncertain external effects. |
| `/api/v2/orchestration/runs/<run_id>/editor` | GET | Current editor state and paged revision history. |
| `/api/v2/orchestration/runs/<run_id>/edit` | POST | Hold an unexecuted plan for manual approval before editing. |
| `/api/v2/orchestration/runs/<run_id>/revisions` | POST | Ask the planner for a change, answer its question, restore a version, or discard a pending change. |
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

Execution terminal events also retain the actual outcome, safe failure
information, and attempt/recovery identifiers. A final explanatory message does
not imply that every step succeeded. The same information is saved with the
assistant message and restored from history. A dropped stream is reconciled
against the saved run rather than treated as proof that the server cancelled it.

Three event types are genuinely new, because nothing existing meant the same thing:
`orchestration_plan`, `orchestration_elicitation` and `orchestration_step`.

## Editing before execution

**Review** remains the plan drawer with narrowing-only step and document controls.
**Edit** opens a full-screen preview, scoped planner conversation, and revision history.
The planner can add, remove, or revise steps, but only within current capability and
source permissions. The browser never constructs an executable plan.

Opening Edit stops a countdown and saves a manual-approval hold. Closing or reloading
does not restart the timer: the current version needs an explicit **Run**. Conditional
version checks prevent an old tab from approving a superseded plan or editing one that
has already started.

The revised task guides the actual execution and final answer, while the original user
message remains unchanged. Failed changes preserve the last valid version. See
[V2 Orchestration Plan Editing](V2_ORCHESTRATION_PLAN_EDITING.md) and the
[user guide]({{ '/guides/review-and-edit-orchestration-plans/' | relative_url }}).

## Clarifying questions

When the orchestrator cannot plan without more information it asks in an inline card rather
than asking you to start a new chat message. The card can ask for a single choice, several
choices, text, or files. It uses the same reference and saved-prompt editing layer as the
main composer, without duplicating the model, agent, web, or voice toolbar.

### Answer with context

Type `#` to choose an accessible file, tag, or workspace. Choose an actual suggestion from
the menu: typing a filename alone does not establish a file reference. Use `/` to attach a
saved prompt, fill its variables, or edit its wording for this answer only. The main
composer's draft and attached prompt are not changed.

Choice questions keep their radio buttons or checkboxes and provide an **Additional
details** editor beside that choice. You can select the intended options and add a
qualification, a reference, or a prepared prompt without having to choose between the two.

File questions offer suggested sources when the planner has suitable candidates. These
are suggestions, not the only permitted files. If they are wrong, use `#` or **Attach a
file** to supply a different source; no suggested option has to be selected. A single-file
question accepts one file across the selected suggestions, references, and uploads.
Multiple-file questions accept a set of files. A tag or workspace can narrow the task but
does not substitute for a file when the question explicitly requires one.

Uploads use the existing chat upload and processing services, including their file-type,
size, role, and workspace restrictions. Each upload shows its progress, and **Finish**
stays unavailable until selected uploads are ready. A failed upload must be retried or
removed rather than being silently omitted. Removing a reference or declining an answer
does not delete a file that has already been uploaded; its normal retention rules apply.

**Back** and **Next** retain each answer's text, choices, prompt variables, and references.
A failed submission leaves the card editable with the draft intact. Finish continues the
original request, using the supplied sources and instructions during both planning and
execution.

### Contract and persistence

That schema is deliberately shaped to the MCP elicitation specification: a flat object whose
properties are primitives or arrays of primitives, so any client can render it without a
general JSON Schema implementation. Our own paging lives in a sibling `ui_hints` field so
the schema itself stays MCP-clean. Resource hints and non-exhaustive candidate references
live in `ui_hints.fields`, not in a closed `enum`. Genuine fixed-choice fields continue to
enforce their enums.

The primitive `elicitation_response` retains `{action, content}`, with `action` one of
`accept`, `decline`, or `cancel`. Answer-local text, scoped reference identities, and
resolved prompt metadata travel in the separate `elicitation_context`, keyed by question
field. Files are identified by workspace document or conversation attachment identity,
never authorized by a display label or a browser-supplied storage URL.

The server stores the normalized pending question and binds answers to its owner,
conversation, turn, elicitation ID, and revision. Pending questions are separate from
runnable plan records and do not appear as empty runs in the map. Submission identities
protect retries from applying the same answer twice.

This also corrects the earlier client/server handoff: the route previously expected the
browser to send the original schema while the controller sent only the answer. Replies
are now validated against the stored question, rather than being ignored when that
browser-supplied schema is missing. Accepted answers are accumulated for later questions
and persisted with the eventual run.

Declining or cancelling carries neither primitive content nor draft text, reference
selections, or prompt metadata. Primitive-only questions and clients remain supported;
the added context is optional.

The controller also sends the matching elicitation as legacy metadata with an accepted or
declined response; the stored schema remains authoritative. The question and draft are
cleared only after a successful continuation. Revisions reuse the original user-message
ID, and cancelling abandons the request without starting another plan.

If another question is necessary before a runnable plan exists, the private pending-turn
state also retains the original authorized history snapshot. Version-conditional writes
prevent a delayed response from replacing newer clarification state.

The pending chain is capped at 12 answers and 32 KiB of answer data, with a 64 KiB
ceiling on the full pending record. Limits fail explicitly rather than dropping an
earlier answer. Links supplied in accepted answers can be used as user-provided URLs;
the wording of the question itself cannot authorize a link.

## Configuration

Orchestration-specific settings live under the Orchestration group in Admin Settings. The keys are prefixed
`chat_orchestration_` rather than `orchestration_`, because `orchestration_type` and
`enable_multi_agent_orchestration` already exist and mean something entirely different —
which Semantic Kernel multi-agent pattern runs a selected agent.

Recent message history also uses `conversation_history_limit` from Chat settings.
The classic chat summarization switches do not enable rolling summaries in orchestration.
The two orchestration ledger settings bound activity summaries independently of message
history; setting the ledger run count to zero does not erase conversational context.

See [the Orchestration settings page](../../admin/orchestration.md) for the full table.

## File structure

| File | Responsibility |
| --- | --- |
| `functions_orchestration_registry.py` | Capability descriptors, gating, planner and client projections |
| `functions_orchestration_schema.py` | Plan and elicitation contracts, validator, repair, step results |
| `functions_orchestration_context.py` | Candidate documents, accessible agent/action metadata, seeds, bounded history snapshots, signals, run ledger |
| `functions_action_catalog.py` | Metadata-only action discovery, scoped references and fresh authorization |
| `functions_orchestration_actions.py` | Isolated, bounded execution of one selected action |
| `functions_orchestration_planner.py` | Follow-up resolution, capability-aware plan synthesis, elicitation, re-planning |
| `functions_orchestration_plan_editing.py` | Scoped plan changes, current source checks, and revised execution requests |
| `functions_orchestration_plan_revisions.py` | Durable edit holds, conditional revision publication, history, and execution claims |
| `functions_orchestration_adapters.py` | Capability adapters over existing functions |
| `functions_orchestration_executor.py` | Step engine, budgets, cancellation, re-authorization |
| `functions_orchestration_runs.py` | Run and step persistence |
| `functions_orchestration_checkpoints.py` | Private reusable result payloads, committed manifests, and integrity checks |
| `functions_orchestration_recovery.py` | Linked retry attempts, execution ownership, and guarded recovery |
| `functions_orchestration_events.py` | Stream event builders |
| `functions_orchestration_models.py` | Authorized model selection, endpoint clients, completion parameters and safe model metadata |
| `route_backend_orchestration.py` | The V2 endpoints, conversation and message persistence |
| `application/v2_ui/src/components/chat/ComposerEditor.tsx` | Shared context-aware editing for messages and inline answers |
| `application/v2_ui/src/lib/elicitationAnswers.ts` | Primitive answer construction, required-field validation, and answer-local context |
| `application/v2_ui/src/components/chat/ElicitationCard.tsx` | Paged questions, suggestions, and recoverable answer submission |
| `route_backend_chats.py` | Shared ordinary and multi-query web-search helpers |
| `functions_source_review.py` | Shared bounded query generation, backup planning, and source review |

## Usage

1. Enable Chat Orchestration in Admin Settings, under Orchestration.
2. Choose an approval mode. Review is the default and the safest starting point.
3. Open a V2 chat. Where orchestration is enabled the composer opens in it, with the
   capability toggles and the model, agent and reasoning pickers folded behind **Manual
   controls**; file upload and voice input stay where they are. The **Orchestrate** toggle
   turns it off again for anyone who wants the classic composer.
4. Ask a question. If an inline clarification appears, answer it using choices, text, references, or uploads, then select **Finish**.
5. Review the resulting plan. Use **Edit** to discuss changes with the planner, then
   explicitly run the accepted version or cancel the plan.
6. Watch progress in the Plan panel of the right-hand drawer.

Anything selected inside the manual controls is passed as a seed and constrains the plan,
so a power user can still pin the work to a particular document or agent and let
orchestration decide the rest.

When the administrator allows approval overrides, choosing **Auto**, **After Ns**,
or **Review** saves `orchestrationApprovalMode` to your account immediately, without
sending a message. The choice follows you across chats and is restored from the
server after a reload or a later sign-in on another device. The countdown duration
still comes from administrator settings.

Users without a saved choice receive the deployment default. An enforced deployment
mode takes precedence without deleting a saved choice. If preferences cannot be
loaded, the composer keeps the draft and offers **Retry loading approval preference**
before orchestration can start. An unsuccessful save shows an error and rolls back
to the last confirmed selection unless a newer choice is still pending. Choose the
mode again to retry saving. Existing plans retain their own approval state.

See [the approval persistence fix](../fixes/V2_ORCHESTRATION_APPROVAL_PERSISTENCE_FIX.md)
for the persistence contract and failure handling.

Administrators changing these settings from the classic Admin Settings page do not need to
reload an open chat tab: the interface re-reads its configuration when the tab comes back
to the front.

## Testing and validation

| Test | Covers |
| --- | --- |
| `functional_tests/test_orchestration_registry_contract.py` | Descriptor shape, gating, administrator narrowing, and that internal fields never reach the planner |
| `functional_tests/test_orchestration_plan_schema.py` | Unknown and disabled capabilities, document authorization, argument coercion and bounds, cycles, step caps, narrowing-only edits, approval states |
| `functional_tests/test_v2_orchestration_approval_persistence.py` | Current-user approval preference round-trips, enum validation, and runtime preference resolution and save ordering |
| `ui_tests/test_v2_orchestration_approval_persistence.py` | Approval selection across navigation and fresh browser contexts, administrator precedence, loading/retry, save failures, and pending writes |
| `functional_tests/test_orchestration_plan_revision_store.py` | Durable edit holds, atomic publication, stale approvals, idempotent submissions, and revision history |
| `functional_tests/test_orchestration_plan_revision_routes.py` | Conversational add/remove/restore, clarification, error recovery, preserved original messages, and revised-task execution |
| `functional_tests/test_orchestration_elicitation_schema.py` | The MCP flat-object restriction, paging staying outside the schema, response validation |
| `functional_tests/test_orchestration_elicitation_context.py` | Authoritative pending questions, accepted context, and the real plan/answer/run handoff |
| `functional_tests/test_v2_elicitation_answers.py` | Primitive answers, single/multiple files, alternate sources, readiness, and answer-local prompt resolution |
| `ui_tests/test_v2_elicitation_composer.py` | Real editor interactions, choices with context, uploads, retries, draft isolation, and responsive rendering |
| `functional_tests/test_orchestration_run_ledger.py` | Run and byte bounds, oldest-first compaction, honest truncation, answered questions carrying forward |
| `functional_tests/test_orchestration_invoke_prompt_contract.py` | The model-call convention: the route's closure must accept what the adapters and the document functions actually pass, and must count token usage |
| `functional_tests/test_orchestration_model_selection.py` | Manual/default precedence, independent planner connections, authorization, unavailable models, legacy/APIM compatibility, protocol parameters and client ownership |
| `functional_tests/test_orchestration_executor.py` | Step ordering, dependency skipping, cancellation, budget caps, re-authorization |
| `functional_tests/test_orchestration_phase_ordering.py` | Knowledge sorts before reasoning, a plan gathering after answering is repaired, a backwards dependency is dropped with a note |
| `functional_tests/test_orchestration_adapter_contract.py` | Every capability resolves to an adapter, every adapter matches the executor's call signature, no adapter touches Flask state, and identity is captured on the request thread |
| `functional_tests/test_orchestration_citation_persistence.py` | Cited documents reach the conversation's used-document list; document, web and tool citations use their respective message channels |
| `functional_tests/test_orchestration_research_selection.py` | Balanced planning cases, preserved model choices, initial/replan guidance, and capability gates |
| `functional_tests/test_orchestration_deep_research.py` | Multi-query discovery and review, query bounds, logs-only backup recovery, cancellation, partial/empty results, resolved follow-ups, and user-URL provenance |
| `functional_tests/test_orchestration_action_catalog.py` | Scoped discovery, existing governance, exact references, secret-free projections and revocation |
| `functional_tests/test_orchestration_action_planning.py` | Default-off action gating, short requests, validated action inputs, and retained agent selections |
| `functional_tests/test_orchestration_action_runtime.py` | One-action loading, bounded function calls, model authorization, cancellation, usage and resource cleanup |
| `functional_tests/test_orchestration_context_picker.py` | Picked tags reach the seeds and both search paths under the parameter `hybrid_search` really takes; a tag scopes the probe rather than replacing it; a picked document reaches the planner and the approval card by name; a browser-supplied name cannot widen access; search citations carry the workspace a document came from; a step can read what an earlier step found, an unusable reference is repaired or dropped, and a run-time document still respects the configured ceiling |
| `functional_tests/test_orchestration_conversation_context.py` | Message eligibility, bounds, snapshot validation, nullable unused clarifications, strict response validation, bounded repair, token accounting, provider/refusal handling, contextualized adapters, synthesis roles, and URL provenance |
| `functional_tests/test_orchestration_conversation_context_routes.py` | New and existing conversations across HTTP/SSE planning and execution, all approval modes, null clarifications, bounded recovery, model selection and attribution, revocation, completion failures, stream cleanup, stale sources and legacy cutoffs |
| `ui_tests/test_v2_orchestration_conversation_context.py` | Matching clarification/model transport, cancellation, original-turn continuity, all approval modes, visible answer model names and navigation |

Research-selection evaluation distinguishes contract coverage from model behaviour. A
mocked plan proves that the application preserves an allowed choice; it does not prove
that a real planner chooses the right depth. Compare baseline and revised guidance on
the same approved deployment and synthetic cases, considering both underuse and overuse.
Ambiguous requests may legitimately use ordinary search or deep research. A higher
research-selection rate is not itself a quality improvement.

## Known limitations

- **A full page reload does not automatically restore the inline interview.** Drafts survive
  paging and navigation within the current browser session; reload recovery is a separate
  capability.
- **Recent transcript context only.** There is no orchestration rolling summary or
  cross-chat transcript lookup. A reference outside the retained window may need
  clarification. Enabled scoped fact memories are a separate, bounded source of context.
- **Automatic per-step model routing is not implemented.** Planning and research use the
  selected/default answer model unless a dedicated planner override is configured.
  Direct action execution receives the answer selection. Models are not selected
  dynamically by task capability or cost; configured agents retain their own model behavior.
- **No output-phase workflow.** Existing MCP, OpenAPI and other action types can now
  gather knowledge directly, but the `output` phase remains empty. There are no dedicated
  output scheduling, workspace placement or delivery steps. Actions retain their existing
  operations, so knowledge-phase placement is not a read-only guarantee.
- **An agent step produces no artifacts.** Charts and images an agent generates are written
  through the Flask-bound message-artifact pipeline, which the worker thread cannot reach.
  The adapter surfaces the agent's tool activity as citations instead and returns no
  artifacts.
- **One agent per plan.** Loading an agent resolves Key Vault secrets, hydrates every plugin
  it declares, and introspects SQL and Cosmos schemas. There is no working kernel cache, so
  each agent step pays that cost in full.
- **Steps run sequentially.** The executor orders steps by dependency but does not run
  independent steps in parallel.
- **Recovery is step-level.** It reuses valid completed checkpoints, not an agent's
  internal tool-loop state. An uncertain failed agent/action requires confirmation
  before retry. Older runs without checkpoints cannot be retroactively resumed.
- **Workflows do not yet execute against this engine.** The run record was shaped with that
  in mind, but the two remain separate.

## Related

- [Orchestration settings](../../admin/orchestration.md)
- [Chat Orchestration Action Access](CHAT_ORCHESTRATION_ACTIONS.md)
- [Checkpoint recovery](ORCHESTRATION_CHECKPOINT_RECOVERY.md)
- [Error communication fix](../fixes/ORCHESTRATION_ERROR_COMMUNICATION_FIX.md)
- [Conversation context fix](../fixes/ORCHESTRATION_CONVERSATION_CONTEXT_FIX.md)
- [Model selection fix](../fixes/ORCHESTRATION_MODEL_SELECTION_FIX.md)
- `docs/explanation/release_notes.md`
- [Deep research selection and execution fix](../fixes/ORCHESTRATION_DEEP_RESEARCH_SELECTION_FIX.md)
