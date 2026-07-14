# Chat Turn Orchestration

Implemented in version: **0.250.060**
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
- Prompt content is not copied into orchestration metadata.
- Selected capabilities are required attempts, but unavailable or unauthorized sources must be represented explicitly rather than bypassing access controls.
- Side effects, sensitive access, and budget overflow are marked as approval-required policy classes for later runtime enforcement.

## Dependencies

- Existing chat streaming and document-action routes.
- Existing authorized chat scope resolution.
- Existing agent selection and assigned knowledge handling.
- Existing workspace, web, source-review, history, citation, and artifact systems.
- Existing image proposal finalizer guidance.

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

## Known Limitations

Phase 1 records and gates plans but does not yet provide the complete orchestration runtime.

- Planned steps are not yet scheduled through a generic execution graph.
- Arbitrary governed tools are not yet discovered automatically.
- Selected agent and action execution outputs are not normalized into the ledger until the Phase 4 executor adapters are implemented.
- The legacy non-streaming compatibility path does not yet use Phase 3 collectors.
- A selected agent can still own response streaming instead of returning structured evidence to a separate central finalizer.
- Plan status does not yet provide complete per-step execution reconciliation.
- The live chat payload does not yet expose a dedicated selected-image-reference list; selected workspace images are represented as documents, and explicit headshot/reference intent can be detected from the message until a reference control is wired.

These limitations are addressed by the evidence ledger, capability adapter, executor, central synthesis, and runtime phases.