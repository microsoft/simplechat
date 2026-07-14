# Chat Turn Orchestration Foundation

Implemented in version: **0.250.058**  
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

## Security And Governance

- Caller-supplied IDs are never treated as proof of authorization.
- Existing conversation, document, group, public workspace, agent, and action authorization remains in force.
- The plan stores compact metadata rather than raw tool payloads or source content.
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

## Known Limitations

Phase 1 records and gates plans but does not yet provide the complete orchestration runtime.

- Planned steps are not yet scheduled through a generic execution graph.
- Arbitrary governed tools are not yet discovered automatically.
- Capability outputs do not yet share one normalized result/evidence ledger.
- A selected agent can still own response streaming instead of returning structured evidence to a separate central finalizer.
- Plan status does not yet provide complete per-step execution reconciliation.
- The legacy non-streaming compatibility path does not yet use the generic plan contract.
- The live chat payload does not yet expose a dedicated selected-image-reference list; selected workspace images are represented as documents, and explicit headshot/reference intent can be detected from the message until a reference control is wired.

These limitations are addressed by the evidence ledger, capability adapter, executor, central synthesis, and runtime phases.