# Chat Turn Orchestration

Implemented in version: **0.250.067**
Associated issue: **[#1021](https://github.com/microsoft/simplechat/issues/1021)**

## Overview

Chat turn orchestration coordinates the capabilities and context available when a user submits a message. Its purpose is to turn the current request, selected chat controls, relevant conversation lineage, and governed capabilities into one direct or coordinated plan before the response is finalized.

Grounded image generation is the first proving workflow. The core plan is output-neutral so later phases can reuse it for answers, reports, presentations, analyses, exports, and other agent-driven work.

## Phase 1 Behavior

Every supported chat turn receives a JSON-serializable plan:

- A simple request receives a direct plan with one response finalizer step.
- A request with selected capabilities or named evidence receives a coordinated plan.
- User-selected capabilities are represented as required attempts for that submitted turn.
- Conversation-linked documents and agent-assigned knowledge retain distinct source origins.
- The finalizer depends on the planned collection and execution steps.
- Coordinated turns receive guidance to use attempted sources, disclose skipped or failed sources, preserve conflicts, and avoid unsupported claims.
- Grounded image requests receive a prompt-level gate instructing the finalizer not to emit a `simpleimage` proposal until required evidence sources have been attempted or explicitly failed.

## Turn Snapshot

The plan records a compact snapshot of submitted controls that downstream code treats as immutable, including:

- Conversation ID.
- Selected agent and document action.
- Selected document IDs and document scope.
- Authorized group and public workspace scopes.
- Selected tags and conversation-linked task documents.
- Workspace Search, Web Search, URL Access, Deep Research, and user-workspace-context toggles.
- Selected image reference count when available.
- Model deployment, endpoint, provider, and reasoning effort.
- Selected prompt identifier without persisting the prompt payload in orchestration metadata.

Stored IDs are execution references, not authorization decisions. Existing access checks remain authoritative, and later executors must revalidate access at each data boundary.

## Plan Structure

The initial plan contains:

- `run_id`, version, mode, task type, and task profile.
- Conventionally immutable `selection_snapshot`.
- Selected capabilities and requested evidence sources.
- Inferred evidence requirements, retained separately when a selected source already satisfies them.
- Source origin, required state, and planned status.
- Collection, execution, and finalizer steps with dependencies.
- Policy defaults for selected inputs, governed read-only discovery, bounded replanning, central finalization, and approval-required operations.
- Warnings such as unavailable image generation.

Initial task profiles are:

- `direct_answer`
- `grounded_answer`
- `image_generation`
- `grounded_image_generation`

## Integration

Phase 1 is integrated with:

- Standard streaming chat turns.
- Analyze and Compare document-action chat turns.
- User message metadata.
- Successful, cancelled, and partial-error assistant message metadata on the standard streaming path.
- Existing image proposal guidance.
- Existing capability-usage metadata.

The plan is intentionally dependency-light and rules-based so direct requests do not incur an extra planning-model call.

## Phase 2 Result And Evidence Ledger

Every supported turn now initializes a versioned, output-neutral result and evidence ledger after the user message ID is assigned. Standard streaming stores the same ledger beside the immutable plan on user, successful assistant, cancelled, and partial-error metadata. Analyze/Compare stores it on user and successful assistant metadata.

The ledger is initialized from the plan and records:

- Requested output, task type, task profile, orchestration mode, and plan/run linkage.
- Evidence requirements and the source types that can satisfy them.
- Planned sources with required state, origin, permission state, and requirement linkage.
- Supported, derived, user-provided, placeholder, and unsupported fact confidence classes.
- Normalized computed results, citations, and artifact lineage.
- Explicit missing evidence, execution failures, authorization denials, and cancellations.
- Unresolved or resolved conflicts that retain all contributing source and fact IDs.

Unsupported statements are stored separately from supported facts. Provenance references must resolve to entries already present in the ledger, preventing finalizers from receiving facts with unknown source lineage.

The contract is shared by answer, image-proposal, report, table, and future artifact finalizers. `compact_evidence_ledger_for_model()` returns bounded valid JSON without dangling provenance references, and `build_evidence_ledger_guidance_message()` provides common evidence-before-claims instructions without adding output-specific fields to the core schema.

Phase 2 establishes and persists the contract. An initial planned ledger is not injected because it contains no normalized live results and must not override evidence supplied through existing context paths. Phase 3 populates the ledger from those paths before injecting it into streaming finalizer context. Phase 4 applies the same contract to selected agents and actions.

## Phase 3 Source Collectors

Phase 3 adds a generic `EvidenceCollectorResult` contract with these terminal states:

- `not_requested`
- `skipped`
- `succeeded`
- `partial`
- `not_found`
- `not_available`
- `failed`
- `unauthorized`

Collectors adapt outputs already produced by existing authorized systems; they do not replace or independently re-query those systems. Initial adapters cover:

- Relevant conversation history, with prior user statements marked `user_provided` and assistant text excluded from supported facts.
- Prior document/web citations and generated artifact lineage without promoting prior assistant claims.
- Revalidated selected documents and authorized conversation-upload workspace documents.
- Workspace search chunks, document metadata, classifications, tags, and citations.
- Web Search citations and snippets, including separate no-result and execution-failure outcomes.
- URL Access, Source Review, and Deep Research pages, excerpts, coverage, and skipped-page reasons.
- Selected workspace or conversation images, including compact image lineage and available vision descriptions, detected objects, visible text, and contextual analysis.

The standard streaming route applies collectors after existing retrieval and authorized conversation-history loading, updates the persisted user-message ledger, and injects a bounded evidence-ledger guidance message before final model or agent invocation. Analyze and Compare update the same ledger after their authorized document results become available so selected-document, upload, workspace-citation, and image lineage persist with the turn.

Collector application deduplicates facts, citations, and artifacts. Required source failures, authorization denials, skipped attempts, and empty results remain explicit and reconcile the ledger to `partial` or `failed`; unresolved future-phase sources keep it in `collecting`.

## Phase 4 Agent And Action Evidence Contract

Phase 4 adds a connector-neutral `evidence_collection` task for selected agents and actions. The task carries the original request, unresolved evidence requirements, optional executor capability metadata, delegated planned sources, a structured output schema, and policy constraints. Optional metadata can identify capability tags, supported evidence types, required permissions, current-user context support, citation support, and sensitive-data handling without teaching the orchestration core any connector-specific tool names.

The authorization descriptor identifies only the authenticated current user and the authorized scope type. It does not copy user, conversation, group, or public-workspace IDs into model-authored tool arguments. Existing plugins continue to resolve private lookups through the server-authored `g.authorized_chat_context`, and the document-action path now establishes that canonical context before its workflow executes.

Executors are instructed to:

- Attempt relevant governed tools before reporting that evidence is unavailable.
- Use authenticated request context instead of caller-supplied identity or scope values.
- Return concise facts, source attempts, citations, artifacts, results, and missing/failure states.
- Avoid retaining raw sensitive payloads.
- Leave the final response and `simpleimage` proposal to the orchestration finalizer.

The response adapter normalizes successful per-turn tool invocations and document-action outputs into the shared ledger. It preserves `not_found`, `not_available`, `failed`, and `unauthorized` outcomes; associates facts and gaps with known requirements; resolves inferred planned sources attempted through an executor; and redacts credential-bearing fields before bounded summaries enter the ledger. Agent invocation baselines ensure prior tool calls from the same conversation are not mistaken for current-turn evidence.

Grounded image generation is the first live profile using this mode. Selected-agent output is buffered as internal executor output rather than streamed as the final answer. Image-proposal guidance is withheld from the executor, its tool results are normalized after collection completes, and the route emits a deterministic evidence-status progress update before central synthesis. Analyze and Compare actions carry the same task, normalize successful results, and persist explicit action failures.

## Phase 5 Central Synthesis Contract

Phase 5 adds a versioned, output-neutral central synthesis request in `functions_central_synthesis.py`. The request binds one coordinated plan to the matching compact evidence ledger and contains:

- The original user request.
- Requested output, task type, task profile, finalizer, and run linkage.
- A bounded, model-safe evidence ledger with supported facts, normalized results, citations, artifacts, conflicts, and missing/failure states.
- A trusted output profile that supplies task-specific instructions and schema without adding image fields to the generic core.
- Shared policy requiring supported evidence, missing-evidence disclosure, conflict preservation, partial outcomes, executor isolation, and approval before artifact generation.

Synthesis is allowed only when plan and ledger run IDs match, both are coordinated, and evidence has reached `ready`, `partial`, or `failed`. A ledger still marked `collecting`, cancelled, or otherwise nonterminal cannot produce a proposal, and the route fails explicitly rather than falling back to an ungrounded response. Unsupported fact text is removed from the finalizer payload entirely; its omission count remains available while explicit missing and conflict records explain gaps safely.

The finalizer receives an isolated system/user message pair instead of executor prompt history. User and source content remains serialized as data, delimiter characters are escaped, and the system message identifies the model as the single finalizer for that run. The same contract defaults to a normal response profile for non-image answers and can accept future report, table, presentation, or artifact profiles.

### Grounded Image Proving Profile

The grounded-image output profile requires the finalizer to:

- Begin with a concise evidence summary and disclose material gaps.
- Use only supported or user-provided facts in proposal descriptions and prompts.
- Omit unsupported details or mark them as explicit placeholders.
- Use generic person icons for collaborators without verified photo references.
- Use selected-image features only when supported selected-image evidence contains them.
- Emit self-contained, provider-ready `simpleimage` proposals without claiming generation has occurred.
- Produce multiple proposals only when they serve distinct requested purposes.

Model-only grounded-image turns replace legacy augmented history with the isolated central synthesis messages before the existing GPT stream. Selected-agent grounded-image turns first buffer and normalize executor evidence, surface the deterministic handoff as progress, and then call the configured chat model as central finalizer. Synthesis lifecycle metadata records `pending`, `completed`, `failed`, or `cancelled` without retaining raw request or ledger content. Successful synthesis marks the ledger `completed`, combines executor and finalizer token usage, and persists compact central-synthesis metadata beside the plan and evidence ledger.

The `simpleimage` proposal schema now supports optional `evidenceIds`, `sourceSummary`, `missingEvidence`, and `referenceImageIds`. Python and browser normalizers bound and deduplicate these fields. At approval, evidence IDs must exist in the authorized source assistant message's ledger, and reference image IDs must identify `image_reference` artifacts in that ledger. Unbound or invented lineage IDs are removed before generation metadata is persisted. Image generation remains opt-in and starts only after user approval.

## Phase 6 Request-Scoped Orchestration Runtime

Phase 6 adds `functions_orchestration_runtime.py`, an in-process execution graph that binds one immutable plan to its matching evidence ledger for the lifetime of a chat request. Direct and coordinated turns now share the same `OrchestrationRun` contract. The runtime validates matching run IDs and modes, unique node IDs, known dependencies, acyclic graphs, a single finalizer, and bounded node and replan budgets before execution.

Runtime nodes retain the Phase 1 step fields and add lifecycle metadata for:

- `pending`
- `running`
- `succeeded`
- `partial`
- `failed`
- `skipped`
- `blocked`
- `cancelled`

The runtime supports two execution modes over the same graph:

- Injected adapters can execute dependency-light operations directly. Sequential execution is the default. Independent adapters run in bounded parallel only when they are explicitly marked read-only, parallel-safe, and independent of Flask request context.
- Existing chat-route operations continue through their established authorization and request-context boundaries, then reconcile their normalized ledger source states into the same runtime graph. This avoids duplicating retrieval or moving identity-sensitive work into worker threads.

Read-only adapters can opt into at most three cancellation-aware attempts. Write-capable or otherwise non-read-only adapters remain single-attempt even if configured otherwise. Bounded replanning accepts only collection or planning nodes, revalidates the complete graph including finalizer dependencies, enforces the run's replan and node budgets, and records rejected follow-ups as explicit partial warnings.

Required-node failures block dependent finalizers. Optional failures and partial nodes permit a clearly partial run when the finalizer can still produce a supported result. A finalizer cannot start until every dependency is terminal, and selected agents that cannot be resolved no longer silently fall back to the base model. Generic evidence discovery resolves only after authorized collectors have run; it succeeds when usable authorized evidence exists and fails closed with node-linked missing evidence otherwise.

The standard streaming and Analyze/Compare paths persist compact `orchestration_runtime` metadata beside the plan and ledger. Source metadata records the responsible runtime node, and normalized facts, results, citations, artifacts, and gaps receive `step_id` provenance where applicable. Existing thought channels display concise node progress, while Application Insights receives run and node lifecycle, attempt count, status, and compact ledger-size telemetry without raw evidence or sensitive payloads.

### Cancellation And Terminal Cleanup

Standard streaming uses `ActiveConversationStreamSession.is_cancel_requested()` as the runtime cancellation signal. Cancellation marks pending nodes and externally running nodes cancelled, prevents pending synthesis, preserves useful partial evidence, and stores a terminal runtime snapshot even when no assistant content was emitted. A final generator cleanup also fails or cancels any run left active by an early return.

Streaming document actions check cancellation before and after their existing workflow call. The underlying Analyze/Compare workflow remains non-preemptive, so a cancellation received during that call discards its result before assistant persistence and closes the runtime when control returns. Required runtime failures return an explicit conflict response rather than persisting a final document-action answer.

## Phase 7 Progress, Evidence Review, And Approval

Phase 7 keeps orchestration inside the existing chat experience. Runtime node events now retain bounded `run_id`, `node_id`, node type, capability, required state, and lifecycle status in the existing thought stream. The browser groups updates for the same node, preserves first-seen execution order, and presents capability-specific labels for planning, selected images, workspace evidence, public web, selected agents/actions, source review, finalization, and image approval. Live progress uses `role="status"` and `aria-live="polite"`; completed progress remains available behind the existing collapsed Thoughts control without exposing model reasoning, raw evidence, or debug details.

Grounded image proposal cards now derive a compact review from authorized assistant-message metadata and show:

- Canonical source badges with used, reviewed, partial, reviewing, or unavailable state.
- Concise source summaries and linked evidence-record counts.
- Explicit missing-evidence notes, including requested sources that returned no usable evidence.
- Selected reference-image previews when an authorized conversation image message can be served through the existing same-origin image route.
- Responsive evidence and approval controls for desktop and mobile layouts.

Approval has three states:

- `ready`: evidence and runtime state are terminal and the proposal can be approved normally.
- `confirmation_required`: a terminal partial outcome still contains supported evidence; the user must acknowledge that generation will use only the available evidence.
- `blocked`: evidence or orchestration is active, cancelled, failed, or lacks usable support.

The browser state is explanatory, not authoritative. The generation route reauthorizes the personal conversation, reads the exact source assistant message from that conversation, constrains proposal evidence and reference IDs to its persisted ledger, rebuilds the approval review, and validates the literal partial-confirmation boolean immediately before generation. A supplied source message that cannot be read from the authorized conversation fails instead of silently creating an unbound request. Model-authored source labels and arbitrary image URLs are not trusted.

Users can edit or dismiss a proposal before generation, explicitly acknowledge a partial proposal, or stop the active chat stream through the existing cancellation control. These interventions remain scoped to the current request and proposal; Phase 7 does not add an admin approval queue or permit automatic write, sensitive, consequential, or over-budget actions.

## Phase 8A Governed Capability Discovery And User Choice

Phase 8A gives the authenticated server a bounded inventory of built-in chat capabilities before execution. The initial inventory covers Workspace Search, Analyze, Compare, Image, Web Search, URL Access, and Deep Research. It contains only planning metadata such as category, state, governance mode, risk, latency, cost, evidence types, required inputs, and current-user scope. It does not include secrets, connection settings, raw prompt or agent instructions, inaccessible catalog entries, or browser-supplied authorization claims.

Capability states remain distinct:

- `selected` is an explicit submitted mandate and remains a required attempt.
- `unselected` is available and authorized, so policy may allow deterministic discovery or recommendation.
- `approved` and `declined` are persisted turn-scoped decisions for a proposal.
- `unavailable`, `unauthorized`, and `policy_blocked` capabilities are not offered or executed.

An inactive toolbar control is therefore not treated as a denial. Per-capability modes under `chat_capability_governance` are `manual_only`, `recommend`, `auto_read_only`, and `blocked`. Only internal, read-only capabilities can use `auto_read_only`; external retrieval still requires a user choice. Invalid governance values fail closed as blocked. `chat_capability_choice_ttl_seconds` controls the bounded pending-choice lifetime and defaults to one day.

### Deterministic Matching

Common requirements are classified without a planning-model call. Initial classes cover current public information, current official/local rules, user-supplied URLs, workspace evidence, document analysis, multi-document comparison, explicit visual output, and multi-source public research. A recommendation is created only when an eligible capability can materially improve freshness, completeness, confidence, evidence quality, or requested output.

Simple timeless questions keep their direct one-step plan. Analyze requires at least one reauthorized document target, Compare requires at least two, URL Access requires a supplied URL, and Image is proposed only for explicit visual creation intent. Current local-law and official-record requests prefer Deep Research when available and retain Web Search as a bounded alternative. Selected agents continue through canonical server resolution and the existing required-attempt contract; Phase 8B extends the same inventory and choice protocol to governed unselected agents.

### Durable Choice And Resume

When consent is needed, the server persists one normal assistant message with an `awaiting_user_choice` checkpoint and ends SSE. The proposal records its exact conversation, source user message, parent run, requirement/reason codes, allowlisted options, recommendation, creation and expiry times, decision, and resume lease. Refreshing the conversation reconstructs the same card from message metadata; no process-local waiter is required.

The decision route:

1. Reauthorizes personal conversation ownership.
2. Reads the exact proposal and source user message from the conversation partition.
3. Validates parent-run and source-turn linkage.
4. Accepts only a literal option ID present in the persisted proposal.
5. Rebuilds capability configuration, role authorization, scopes, and document targets.
6. Uses an ETag conditional replacement so duplicate clicks replay idempotently and conflicting choices cannot both win.
7. Persists approved, declined, expired, or invalidated terminal state.

Resume requests contain only the conversation and proposal IDs. The server reconstructs the original bounded request, reauthorizes scopes and linked chat-upload documents, applies approved capabilities with `discovery_approved` origin, and creates a child run linked to the parent. A decline creates no capability source and finalizes once without another recommendation loop. Selected, proposed, decided, and effective capability provenance remain separate; approved or automatic discovery is never rewritten as `selection`.

Resume execution uses a conditional lease. A duplicate live claim is rejected, a failed or cancelled claim can be retried, and completed output is replayed without another capability call. If a process stops after persisting the resumed assistant but before marking the proposal complete, the next request reconciles that exact assistant by proposal and execution IDs before considering another claim.

### External Data Minimization

Discovered external retrieval preserves the existing current-message-only boundary. Conversation history, retrieved workspace content, and unrelated context are not appended to Web Search or Deep Research requests. The server removes detected street addresses, email addresses, phone numbers, and account-like identifiers from the default external query. Parcel-specific requests receive a separate, clearly labeled option whose selection explicitly approves including the supplied address for that turn. Capability choices do not change saved toolbar defaults.

The inline choice card renders server fields through DOM text APIs, provides one recommended option, alternatives, and a continue-without-capabilities path, associates external/sensitive notices with the workflow, uses `aria-live` for status, and maintains at least 44-pixel actions on mobile.

## Phase 8B Governed Agent Discovery And Recommendation

Phase 8B extends the Phase 8A inventory, proposal, decision, and durable resume contracts to authorized unselected personal, global, and group agents. It does not add a second planner or approval route. Selected agents remain required attempts, and an inactive agent selector is not treated as a decline.

Agent discovery is explicitly opt-in through `discoverable_by_orchestrator`, which defaults to `false` for existing and new records. An opted-in record must provide an allowlisted `orchestrator_descriptor` containing nonempty capability tags and evidence types, read-only state, external-data state, risk class, data-sensitivity class, latency class, and cost class. Invalid, incomplete, write-capable, sensitive, disabled, hidden, nonlocal runtime, or action-attached records fail closed. Foundry-backed agents and local agents with attached actions remain available through normal explicit selection but are excluded from Phase 8B discovery because their hidden tools or action arguments cannot yet meet the read-only telemetry boundary.

The server builds the canonical discovery catalog only after current authorization and governance checks:

- Personal records come only from the current user's partition and require personal-agent governance access.
- Global records require current global-agent feature and per-agent item-policy access, plus availability under the active global/per-user agent mode.
- Group records come only from the user's current memberships, require group-agent governance access, and exclude groups whose current status does not allow chat.

Only a bounded safe projection enters orchestration metadata: opaque option reference, display label, scope class, capability tags, evidence types, read-only and external-data state, risk, sensitivity, latency, and cost. Raw instructions, internal IDs, group IDs/names, endpoints, keys, connector settings, action IDs/arguments, assigned-knowledge details, hidden tools, and inaccessible catalog entries remain in the server-only canonical catalog. Agent-management and invocation telemetry uses bounded summaries or the opaque reference for discovered runs rather than full canonical records.

### Deterministic Agent Matching

Initial matching recognizes explicit specialized organizational knowledge and business-system evidence requests. A safe descriptor must materially match the current message; the existence of an authorized agent alone is insufficient. At most one agent option is added to the existing Phase 8A proposal. Simple timeless questions stay direct, a selected agent suppresses all second-agent recommendations, and selected Workspace Search, Analyze, or Compare suppresses an organizational-agent recommendation when that selected capability already satisfies the requirement.

Agent option IDs are server-authored HMAC references namespaced by personal, global, or group scope. The reference binds the canonical catalog key and immutable creation timestamp, so duplicate display names remain unambiguous and a deleted/recreated record cannot inherit an old approval. Browser requests still submit only conversation/proposal and persisted option IDs.

### Agent Decision And Resume

Agent decisions use the existing ETag-protected proposal transition and resume lease. At decision, claim, and final canonicalization, the server reauthorizes the personal conversation and exact source turn, rebuilds the current governed catalog, and resolves the approved opaque reference to one canonical record. Material descriptor changes invalidate the prior choice; deletion, disablement, hidden state, policy loss, group-membership revocation, inactive group status, or runtime-type changes remove the option entirely.

After a successful claim, assigned knowledge is read from the refreshed canonical record and action constraints are checked again. Any newly attached action removes the agent from the governed catalog and invalidates the approval. The agent enters the existing selected-agent evidence/runtime node as a required `discovery_approved` source, returns evidence rather than a final answer, and hands the terminal ledger to the central response finalizer. Inherited kernel function choice is disabled at the agent, execution-setting, and service levels for that invocation; raw plugin invocation citations are not persisted. Loader and wrapper telemetry records only bounded scope/type booleans, counts, response lengths, and lifecycle state for the discovered run. Saved toolbar defaults are unchanged. Duplicate decisions, live resume claims, and process-loss reconciliation continue through the Phase 8A idempotency contract, so an approved agent is not invoked twice.

## Security And Governance

- Caller-supplied IDs are never treated as proof of authorization.
- Existing conversation, document, group, public workspace, agent, and action authorization remains in force.
- The plan stores compact metadata rather than raw tool payloads or source content.
- The ledger records authorization status but never treats that status or a stored scope ID as an access decision; collectors and executors must revalidate access at their own boundaries.
- Conversation collectors receive messages only after personal-conversation ownership is revalidated.
- Conversation and lineage collectors retain at most the 24 most recent mappings before ledger compaction.
- Selected document collectors resolve each document again through the authorized personal, group, or public workspace scope before recording it.
- Workspace, web, and source-review collectors consume the outputs of their existing permission-aware retrieval boundaries rather than caller-supplied result payloads.
- Source Review pages flagged by the existing prompt-injection detector retain citation lineage, but their excerpts are omitted from supported ledger facts and recorded as partial evidence.
- Selected-image collection retains compact IDs, MIME types, scope, and vision metadata without retaining image bytes, data URLs, blob paths, or signed URLs.
- Raw metadata parameters are not retained in the ledger. Binary values and metadata keys associated with credentials, secrets, tokens, keys, connection strings, or internal endpoints are omitted.
- HTTP citation and artifact references have query strings and fragments removed so signed URLs are not persisted or sent to a model.
- Unsupported fact text is excluded from central synthesis payloads while explicit missing and conflict records remain available to the finalizer.
- Central synthesis payload delimiters are escaped and source/user content is treated as data rather than executable instructions.
- Proposal evidence and reference-image IDs are revalidated against the authorized source assistant message's persisted ledger before approval.
- Approval state is recalculated from the authorized source ledger and runtime immediately before generation; a browser acknowledgment cannot override active, failed, cancelled, or supportless evidence.
- Evidence badges use canonical server-known source types, and reference previews use only the existing authenticated same-origin image route for message-backed references.
- Evidence summaries and missing-evidence notes are rendered as text, so source or model content cannot create executable markup.
- Prompt content is not copied into orchestration metadata.
- Selected capabilities are required attempts, but unavailable or unauthorized sources must be represented explicitly rather than bypassing access controls.
- Agent/action task payloads describe the principal as `current_user` and omit caller-provided private identity and scope IDs.
- Only tool invocations created after the current-turn baseline are eligible for executor evidence provenance.
- Credential-bearing tool result fields and authorization strings are redacted before bounded fact summaries are recorded.
- Runtime adapters receive a copied ledger snapshot and return structured results; they cannot mutate the shared ledger from parallel workers.
- Parallel execution is opt-in for read-only, request-context-independent adapters. Existing Flask-scoped collectors, agents, and actions remain inside their current authenticated request boundaries.
- Runtime metadata excludes raw adapter results, raw evidence, debug exception text, and caller-supplied authorization identifiers.
- Runtime source reconciliation consumes only evidence already normalized by the established authorization-aware collectors and executors.
- Side effects, sensitive access, and budget overflow are marked as approval-required policy classes for later runtime enforcement.
- Capability inventory availability and authorization come from current server configuration, role claims, authorized scopes, and revalidated document targets rather than toolbar state.
- Pending proposals, decisions, resume leases, parent/child linkage, and effective origins are stored in the authorized conversation partition with ETag concurrency.
- A proposal approval never substitutes for collector or executor authorization; configuration and object access are checked again immediately before resume and at execution boundaries.
- Browser decision payloads cannot add capabilities, run IDs, user IDs, document IDs, or scope IDs. Effective execution is reconstructed from the persisted allowlist.
- Discovered external queries use current-message-only minimized text. Sensitive address use requires selection of the separately labeled sensitive-input option.
- Unselected agents default to undiscoverable and enter the catalog only after ownership/membership, group-status, feature, item-policy, enabled, visibility, runtime-type, attached-action, and safe-descriptor checks.
- Agent option references are opaque, scope-namespaced, bound to immutable stored identity, and resolved only through the current authorized server catalog.
- Agent decisions revalidate the exact persisted safe descriptor; material policy changes invalidate prior consent while canonical assigned knowledge and action constraints refresh at invocation.
- Discovered-agent proposal, message, and activity metadata omit canonical IDs, group identifiers/names, ordinary tags, catalog keys, instructions, endpoints, connector settings, action IDs, and hidden tools.
- Discovered-agent execution disables inherited kernel tools, omits raw plugin invocation citations, and suppresses prompt/response previews in runtime telemetry; normal explicitly selected-agent behavior is restored after the call.

## Dependencies

- Existing chat streaming and document-action routes.
- Existing authorized chat scope resolution.
- Existing agent selection and assigned knowledge handling.
- Existing workspace, web, source-review, history, citation, and artifact systems.
- Existing image proposal finalizer guidance.
- Generic central synthesis request and output-profile contracts.
- Request-scoped `OrchestrationRun` scheduling and lifecycle helpers.
- Existing `ActiveConversationStreamSession` cancellation, replay, heartbeat, and reattach behavior.
- Cosmos message ETags for idempotent capability decisions and resume leases.
- Existing role-aware Web Search, URL Access, Deep Research, image-generation, document-action, and authorized document/scope checks.
- Existing personal/global/group agent stores, agent governance policies, group membership/status checks, assigned-knowledge reconstruction, and action-constraint validation.

## Testing And Validation

Functional coverage is in `functional_tests/test_chat_turn_orchestration_plan.py` and validates:

- Direct versus coordinated plans.
- Complete submitted-control snapshots.
- Selected agent, action, document, and search dependencies.
- Conversation and assigned-knowledge source origins.
- M365/Graph, SQL, CRM, workspace, public web, and prior-citation evidence detection.
- Grounded image classification.
- Generic image generation without false grounding.
- Selected-image Q&A without false generation.
- Standard streaming and document-action route wiring.

Ledger coverage is in `functional_tests/test_chat_evidence_ledger.py` and validates:

- Plan-based initialization for answer and artifact task profiles.
- Selected-image, public-web, selected-agent, and computed-output evidence.
- Source, citation, artifact, fact, and result lineage.
- Unsupported-fact separation, missing evidence, permission failures, and conflicts.
- Secret, signed-URL, raw-payload, and binary-data omission.
- Bounded model compaction that remains valid JSON.
- Standard streaming success, cancellation, and partial-error persistence, plus document-action user and success metadata.

Collector coverage is in `functional_tests/test_chat_evidence_collectors.py` and validates:

- User-provided conversation facts remain separate from assistant-generated text.
- Selected images produce supported vision facts or explicit partial evidence when vision metadata is absent.
- Workspace, web, Source Review, selected-document, conversation-upload, prior-citation, and artifact outputs normalize consistently.
- Web no-result, failed execution, skipped source pages, and unauthorized collection remain distinct.
- Reapplying a collector result does not duplicate facts or citations.
- A coordinated turn populates planned sources and produces bounded finalizer guidance before response generation.
- Streaming and document-action routes refresh the shared ledger through the generic collector coordinator.

Agent/action contract coverage is in `functional_tests/test_agent_action_evidence_contract.py` and validates:

- A mock profile tool produces source-supported current-user facts.
- An executor with no matching tool records explicit `not_available` evidence.
- Generic SQL/action rows become provenance-linked ledger facts without connector-specific handling.
- Action failures remain explicit without persisting raw error secrets.
- Final proposal synthesis remains gated while executor evidence sources are pending.
- Streaming and document-action routes apply the contract before synthesis or status persistence.

Central synthesis coverage is in `functional_tests/test_central_synthesis_contract.py` and validates:

- The generic response profile remains independent of `simpleimage` output rules.
- Supported profile facts and selected-image evidence reach the compact finalizer request.
- Unsupported LinkedIn claims are omitted while the missing-evidence state is disclosed.
- Collaborators without verified photos use generic icons.
- Verified image references and proposal provenance metadata are retained.
- Invented evidence and image-reference IDs are removed at the authorized ledger boundary.
- Collecting ledgers cannot produce central synthesis requests.
- Finalizer payload delimiters are escaped.
- Model-only and selected-agent grounded-image paths centralize before persistence.

The existing desktop/mobile Playwright coverage in `ui_tests/test_chat_inline_image_proposal_cards.py` also verifies that normalized provenance metadata survives card rendering, prompt editing, and the approval request.

Phase 7 proposal coverage additionally validates canonical source badges, missing-evidence disclosure, same-origin reference previews, inert markup-like evidence, normal approval, explicit partial-evidence acknowledgment, blocked approval, live accessibility state, 44px mobile actions, and responsive desktop/mobile behavior. `functional_tests/test_image_proposal_pipeline.py` validates the matching server review contract for ready, terminal-partial, active, cancelled, failed, and supportless states. `functional_tests/test_image_proposal_approval_route.py` directly validates owner access, foreign and missing conversations, cross-partition source messages, cross-turn and forged lineage removal, strict partial confirmation, and legacy no-ledger compatibility. `functional_tests/test_central_synthesis_contract.py` verifies that the authorized generation route wires the review after lineage constraints.

Runtime coverage is in `functional_tests/test_orchestration_runtime.py` and validates:

- Direct and coordinated turns share one run contract.
- Dependency ordering and bounded parallel execution for independent read-only collectors.
- Required versus optional failure behavior and finalizer isolation.
- Cancellation of pending synthesis, including the final aggregate closure checkpoint.
- Read-only retry limits and single-attempt write behavior.
- Bounded replanning, node-budget enforcement, and cycle rejection.
- Authorized evidence discovery success and fail-closed missing evidence.
- Runtime-node provenance across normalized ledger entries.
- Conversation, document, image, workspace, web, source-review, agent, action, response, and image-proposal node categories.
- Standard streaming and document-action lifecycle, structured progress, cancellation, terminal cleanup, and metadata persistence wiring.

Desktop/mobile coverage in `ui_tests/test_streaming_thought_progression.py` validates ordered node updates, capability labels, approval waiting, `aria-live` semantics, session isolation, and the existing collapsed completed-thought behavior.

The stream heartbeat, background execution, lifecycle observability, new-conversation reattach, and stop-control contracts also validate that runtime cancellation preserves the existing SSE protocol and replay behavior.

Phase 8A capability coverage is in:

- `functional_tests/test_chat_capability_discovery.py` for inventory states, deterministic matching, target gates, and unavailable/unauthorized/policy-blocked filtering.
- `functional_tests/test_chat_capability_choice_contract.py` for allowlisted decisions, expiry, decline, external-query minimization, sensitive-input options, provenance, and resume lifecycle.
- `functional_tests/test_chat_capability_choice_persistence.py` for ETag conflicts, duplicate decisions, single execution claims, and persisted expired/invalidated states.
- `functional_tests/test_chat_capability_choice_route.py` for conversation ownership, exact source-turn linkage, forged options, post-approval revocation, server request reconstruction, parent/child replay, and process-loss reconciliation.
- `ui_tests/test_chat_capability_choice_card.py` for persisted rendering, keyboard interaction, external notices, exact decision/resume payloads, `aria-live`, desktop/mobile overflow, and 44-pixel controls.

Phase 8B agent coverage is in:

- `functional_tests/test_chat_governed_agent_discovery.py` for opt-in defaults, authorization/governance filtering, inactive groups, local-runtime enforcement, duplicate names, opaque identity, deterministic matching, selected-capability suppression, safe serialization, policy changes, durable decisions, and required `discovery_approved` provenance.
- `functional_tests/test_chat_capability_choice_route.py` for forged payload rejection, exact source-turn authorization, canonical constraint refresh, policy/membership loss, duplicate decision and resume idempotency, final invocation reauthorization, safe message metadata, and process-loss reconciliation.
- `ui_tests/test_chat_capability_choice_card.py` for inert agent labels, safe scope/risk/sensitivity rendering, minimal browser payloads, pending/failed/invalidated/completed reconstruction, keyboard use, `aria-live`, 44-pixel actions, and desktop/mobile overflow.
- `ui_tests/test_agent_modal_orchestrator_discovery.py` for closed defaults, explicit opt-in, read-only validation, bounded descriptor serialization, edit reconstruction, keyboard accessibility, and responsive layout.

## Known Limitations

Phase 8A and Phase 8B add durable built-in and governed local-agent choice, with these deliberate boundaries:

- Generalized multi-agent recommendation remains out of scope. When an agent is already selected, Phase 8B does not recommend another agent.
- Foundry-backed agents and local agents with attached actions remain explicitly selectable but are not discoverable until hidden tools, action arguments, and runtime telemetry have a separately reviewed read-only governance contract.
- Active runs and evidence ledgers are not stored in a durable queue or dedicated run store. Pending capability choices survive process loss, and persisted resumed assistants reconcile safely, but an in-flight model/tool operation still relies on existing stream execution and retry behavior.
- Parallel runtime adapters must be request-context independent; the live chat route currently reconciles its existing authorized collectors sequentially.
- Cancellation of synchronous model, agent, and document-action SDK calls is best effort. Pending finalization is prevented, but an in-flight non-cooperative call may return before its result can be discarded.
- The legacy non-streaming compatibility path does not yet use Phase 3 collectors.
- Outside the grounded-image proving profile, selected agents retain their existing response-streaming behavior. The runtime records this compatibility finalizer until central synthesis is generalized.
- Analyze and Compare actions participate in runtime lifecycle and evidence normalization but retain their existing compatibility response finalizer. Grounded-image actions still return the evidence-status handoff rather than invoking central synthesis.
- Approval review currently governs the grounded-image proving profile. Automatic write, sensitive, consequential, or over-budget steps remain prohibited until a generalized approval runtime is added.
- Progress is live before response content begins and remains available through the collapsed Thoughts view after completion; it does not expose chain-of-thought or adapter debug details.
- Reference thumbnails are shown only for authorized conversation image messages. Document-backed image evidence remains labeled when no existing same-origin preview route applies.
- The live chat payload does not yet expose a dedicated selected-image-reference list; selected workspace images are represented as documents, and explicit headshot/reference intent can be detected from the message until a reference control is wired.

Generalized durable run execution, consequential/write approval, broader finalizers, and generalized artifact generation remain later roadmap phases.