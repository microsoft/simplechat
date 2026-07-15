# Chat Turn Orchestration

Implemented in version: **0.250.062**
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
- Prompt content is not copied into orchestration metadata.
- Selected capabilities are required attempts, but unavailable or unauthorized sources must be represented explicitly rather than bypassing access controls.
- Agent/action task payloads describe the principal as `current_user` and omit caller-provided private identity and scope IDs.
- Only tool invocations created after the current-turn baseline are eligible for executor evidence provenance.
- Credential-bearing tool result fields and authorization strings are redacted before bounded fact summaries are recorded.
- Side effects, sensitive access, and budget overflow are marked as approval-required policy classes for later runtime enforcement.

## Dependencies

- Existing chat streaming and document-action routes.
- Existing authorized chat scope resolution.
- Existing agent selection and assigned knowledge handling.
- Existing workspace, web, source-review, history, citation, and artifact systems.
- Existing image proposal finalizer guidance.
- Generic central synthesis request and output-profile contracts.

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

## Known Limitations

Phase 1 records and gates plans but does not yet provide the complete orchestration runtime.

- Planned steps are not yet scheduled through a generic execution graph.
- Arbitrary governed tools are not yet discovered automatically.
- The legacy non-streaming compatibility path does not yet use Phase 3 collectors.
- Outside the grounded-image proving profile, selected agents retain their existing response-streaming behavior until central synthesis is generalized.
- Analyze and Compare actions normalize and persist grounded-image evidence but still return the Phase 4 evidence-status handoff; using that ledger in central synthesis is a later output-profile integration.
- Central synthesis currently uses a synchronous completion after selected-agent evidence collection; resilient scheduling, retry, cancellation during that finalizer call, and durable resume belong to Phase 6.
- Plan status does not yet provide complete per-step execution reconciliation.
- The live chat payload does not yet expose a dedicated selected-image-reference list; selected workspace images are represented as documents, and explicit headshot/reference intent can be detected from the message until a reference control is wired.

These limitations are addressed by the evidence ledger, capability adapter, executor, central synthesis, and runtime phases.