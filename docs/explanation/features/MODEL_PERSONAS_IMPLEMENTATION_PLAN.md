# Model Personas Implementation Plan

## Header Information

- Status: **Planned; implementation not started**
- Tracking issue: [microsoft/simplechat#1929](https://github.com/microsoft/simplechat/issues/1929)
- Planning baseline: `feature/modelpersonas` at
  `7ba976b49cd92875f5d584055ff40403a2d654ec`
- Baseline application version: **0.261.460**
- Expected initial implementation version: **0.261.461**, if no intervening
  version change occurs
- Planned: **2026-11-19**
- Owner: **TBD**
- Approval scope: implementation-ready product, backend, UI, validation, and
  rollback specification

This document is the durable implementation plan for adding optional personas
to models configured through AI Connections. It does not authorize a release
or deployment. Implementation must recheck the branch and repository
instructions before editing source.

## Overview and Purpose

SimpleChat users can currently supply instructions through agents, but they
cannot give a connection model a persistent role or behavioral style that
applies outside an agent.

Model personas add a user-authored Markdown instruction to an exact
connection/model record. When enabled, the backend injects the persona as one
supplemental system message for eligible direct text-generation requests.

The model persona is not a replacement for platform safety, application,
grounding, task, or agent instructions. It is not saved into conversation
history.

## Product Decisions

The following decisions are authoritative for this implementation.

### Scope

- Apply the persona to every eligible text-generation request bound to the
  exact scope, connection ID, and model ID.
- Apply it to direct chat, streaming chat, and direct non-agent helper calls.
- Do not apply it to agent execution. Agents use their own instructions instead
  of model personas.
- Do not provide persona controls for embedding-only or image-only models.
- Do not apply personas to direct embedding or image-generation operations.
- A chat model's text-generation step that plans or orchestrates an image
  request may receive the persona; the image-generation operation itself does
  not receive it.
- Exclude hosted Foundry agents, hosted applications, and hosted workflows.
- Exclude legacy requests that do not carry exact connection/model identity.
- Never infer a persona by matching deployment names.

### Ownership and Visibility

- Administrators control personas on global connections.
- A user controls personas on their own personal connections.
- Existing group endpoint authorization controls group persona editing.
- Ordinary users can always see whether an eligible model has a configured,
  enabled persona.
- The connection editor controls whether ordinary users can read the persona
  text.
- Persona-text visibility defaults to on for newly configured personas.
- Full persona text is exposed only to connection editors or to an ordinary
  reader when the visibility control is enabled.
- Persona text is excluded from logs, diagnostics, errors, and telemetry.

### Prompt Precedence

For eligible direct model calls, the effective instruction order is:

1. Supplemental model persona
2. Application and platform safety instructions
3. Default system instructions
4. Task-specific instructions
5. Grounding and retrieval instructions
6. User and conversation content

Agent calls are excluded, so model personas and agent instructions are not
combined.

The ordering is a composition policy, not an authorization or security
guarantee. Persona content cannot grant tool permissions or bypass application
authorization.

## Goals

1. Persist a persona on each eligible connection model without a database
   migration.
2. Provide consistent V2 and classic editing experiences.
3. Apply the persona exactly once to eligible outbound text-generation
   requests.
4. Preserve existing requests when the persona is absent, disabled, or
   whitespace-only.
5. Exclude all agent paths from model-persona injection.
6. Preserve persona metadata across saves, discovery, older records, and
   schema/routing versions.
7. Prevent persona XSS, leakage, and client-forged instruction injection.
8. Include persona tokens in existing context-budget accounting.
9. Make disablement an immediate operational rollback.
10. Add focused backend, UI, transport, authorization, and regression coverage.

## Non-Goals

- Per-user overrides of another user's, group's, or administrator's model
- A replacement for agent instructions
- Automatic persona generation or recommendation
- Persona support for embeddings, direct image generation, speech, or
  transcription
- Hosted Foundry agent/application/workflow instruction management
- Migrating legacy deployment-only consumers into AI Connections
- Routing-schema conversion or endpoint redesign
- A generic prompt-middleware framework
- New third-party Markdown or prompt-management dependencies
- Deployment, release, or live-provider enablement as part of this plan

## Configuration Contract

Use one representation on each model record:

```json
{
  "persona_enabled": false,
  "persona_markdown": "",
  "persona_text_visible": true
}
```

### Validation Rules

- `persona_enabled` must be an actual boolean.
- `persona_markdown` must be a string.
- `persona_text_visible` must be an actual boolean when supplied.
- Maximum `persona_markdown` length is **8,000 Unicode characters**.
- Do not measure only UTF-16 code units; frontend and backend limits must use
  the same Unicode-character definition.
- Reject structural invalidity and oversized text. Do not silently coerce,
  truncate, or sanitize persisted Markdown.
- Whitespace-only text is valid to save, retained for editing, and ignored at
  runtime.
- Disabling retains the draft text.
- Explicitly saving disabled with an empty string clears the text.
- Missing `persona_text_visible` defaults to `true`.
- Store Markdown source, not rendered HTML.

### Stable Identity and Merge Rules

Persona identity is:

```text
scope + connection ID + model ID
```

For an incoming model with the same model ID on the same connection:

- Omitted persona fields preserve the saved values.
- Explicit fields replace their corresponding values, including `false` and
  an empty string.
- A removed model remains removed.
- A new or replaced model ID does not inherit another model's persona.
- Discovery preserves existing persona metadata and cannot populate persona
  fields from provider-discovery metadata.
- Older editors that submit a model without persona fields must not erase
  existing persona state.

Do not turn this preservation into a general deep-merge refactor.

## UI Specification

Implement equivalent controls in the V2 and classic AI Connections editors.

### Eligible Model Row Controls

For each text-chat-capable model, show:

- **Enable model persona** switch
- Labeled multiline Markdown editor
- Write/Preview control
- Character counter using the 8,000-character limit
- **Show persona text to users** switch or checkbox
- Inline explanation that personas affect direct model use but not agents
- Accessible validation and disabled/read-only states

Do not show persona controls for embedding-only or image-only models.

### Draft Behavior

- Retain persona text when the enable switch is off.
- Preserve draft input across rerenders and discovery refreshes.
- Preserve the draft after validation, conflict, or persistence errors.
- Synchronize editor state before save and before any model-list rerender.
- Follow existing modal cancellation, dirty-state, focus, and conflict behavior.
- Keep ordinary workspace and group read-only users ineligible to edit.

### Safe Markdown Preview

- Reuse the existing V2 authored-Markdown component.
- Reuse Marked plus DOMPurify in the classic UI.
- Do not render assistant diagrams, Mermaid, executable widgets, or prompt
  variables.
- Do not fetch linked content or embedded media during preview.
- Do not interpolate persona text into generated HTML.
- Raw HTML, event attributes, script tags, and unsafe URLs must remain inert.

## Backend Specification

### Add a Narrow Persona Helper

Add a small, import-safe module for:

- Persona field interpretation and validation
- Creation of the supplemental system message
- Pure request-message composition
- Character-count and whitespace-only checks

The helper must not import application settings, logging initialization, cloud
clients, caches, or request-global state. It must not mutate stored
configuration or input message lists.

The chosen module and symbol names may follow repository conventions. No
generic prompt framework is required.

### Persistence and Projections

Update the shared model-endpoint normalization, merge, and frontend
projection paths to:

- Apply the persona defaults and validation rules.
- Preserve omitted persona fields by stable model identity.
- Default to withholding full persona text.
- Include text only for an authorized editor or when the model explicitly
  allows ordinary users to see it.
- Always expose a non-sensitive `persona_enabled`/configured indicator to
  ordinary users for eligible models.
- Redact persona text from settings logs regardless of length.
- Preserve revision, ETag, concurrency, credential-staging, and Key Vault
  semantics.
- Reject a failed or oversized save before any partial persona/secret commit.

Audit the V2 global CRUD paths, personal/group endpoint routes, classic admin
save path, group-access projections, chat model catalog, agent selectors, and
workspace page projections. Do not apply ordinary-user sanitization to
authorized admin editors.

### Aggregate Settings Size

AI Connections may contain multiple model personas in one settings document.
Before persistence:

1. Construct the complete prospective settings payload.
2. Serialize and measure the actual payload using the repository's storage
   boundary.
3. Apply the configured or supported settings-document limit.
4. Reject the save before any partial commit if it is too large.
5. Preserve the UI draft and return a non-sensitive validation response.

No per-persona storage container or schema migration is required.

## Runtime Specification

### Exact-Identity Resolution

Runtime code must resolve persona configuration from:

```text
request scope + connection ID + exact model ID
```

Do not accept a persona from the browser request and do not infer it from:

- Display name
- Deployment name
- Model name alone
- A hosted agent's eventual model

### Injection

For an eligible request:

1. Resolve the committed model and persona server-side.
2. Create request-owned copies of messages.
3. Prepend one supplemental system message containing the source Markdown.
4. Mark the content as supplemental in the message text without sending
   private/internal wrapper tokens.
5. Preserve all existing roles, multimodal parts, tools, structured-output
   options, default prompts, task instructions, and request metadata.
6. Dispatch through the existing provider adapter.
7. Do not persist the injected message in conversation history or agent data.

Use one owned injection boundary per runtime path. Wrapping an existing wrapped
client/service must remain exactly-once.

### Provider Behavior

Support the repository's existing text-generation contracts:

- Chat Completions: dedicated system message
- Responses: equivalent system input through the existing conversion
- Anthropic: existing top-level `system` conversion
- Semantic Kernel: streaming, non-streaming, and tool-continuation rounds

Do not silently remove the persona, demote it to a user message, or retry
without it when a provider rejects the request. Return the existing sanitized
failure shape.

### Agent Exclusion

All agent runtime paths must explicitly avoid persona binding, including:

- Direct local agents
- Agents using a default model
- Delegated and specialist agents
- Agent-backed workflows
- Agent tool rounds

Agent instructions remain unchanged. Add regression assertions that an agent
using a persona-enabled connection model produces the same outbound
instructions as it did before this feature.

### Request Freshness and Cache Behavior

Newly acquired requests use the latest committed persona. An in-flight request
retains the persona snapshot with which it started.

Reuse an existing connection/settings revision in cache keys where one already
exists. If a cache key can represent the bound model without an authoritative
revision, include a deterministic digest of the relevant persona state in the
client/service cache key. Never place raw persona text in cache keys, reprs,
diagnostics, or telemetry.

Do not add a new application-wide cache. Change a cache key only when a stale
binding is demonstrated or otherwise required by the affected existing cache.

## Consumer Inventory

Implementation must cover each eligible direct model consumer or explicitly
document that it is genuinely unbound/legacy:

| Consumer family | Required outcome |
|---|---|
| Direct and streaming chat | Persona applied through the shared text request boundary |
| Retry, replay, edit, and fallback | Persona applied exactly once for each actual request |
| History assessment and summary calls | Selected exact model identity preserved |
| Conversation and export summaries | Bound branches receive the persona; legacy branches remain unchanged |
| Direct workflows | Direct model calls receive the persona |
| Agent-backed workflows | No model persona |
| Orchestration planner, answer, and action calls | Each selected direct model receives its own persona |
| Metadata and vision-to-text calls | Direct bound text generation receives the persona |
| Tabular and generated-artifact text calls | Direct bound text generation receives the persona |
| Prompt-variable and memory calls | Selected model identity preserved through direct generation |
| Screening and classification | Persona applies unless that consumer is agent-managed or unbound |
| Test chat/model inference | Saved or explicitly previewed persona behavior is deterministic |
| Discovery/connectivity checks | No persona inference dispatch |

## Context Budget and Overflow

Use the same composed persona system message for budget calculation and final
dispatch.

Update existing budget paths to:

- Include persona tokens before request dispatch
- Include the persona in accumulated tool rounds
- Never count it twice
- Never silently drop or truncate it
- Preserve existing response/output reserves

When the persona causes overflow, apply the repository's existing prior-turn
summarization behavior and retry the budget calculation. If the request still
cannot fit, return the established context-overflow response with no
conversation corruption.

## Security Requirements

- Resolve persona instructions server-side from committed configuration.
- Ignore persona fields supplied in ordinary model-selection or chat payloads.
- Apply existing global, personal, and group authorization checks.
- Preserve connection secret sanitization.
- Keep full persona text out of non-editor projections by default.
- Redact persona content from logs, errors, diagnostics, and telemetry.
- Do not treat prompt ordering as an access-control boundary.
- Never interpolate persona content into HTML or JavaScript.
- Sanitize Markdown preview output before rendering.
- Do not execute or fetch previewed raw HTML, unsafe URLs, Mermaid, or embedded
  media.

## Ordered Implementation Steps

### Phase 1 — Rebaseline and Contract Tests

1. Confirm `feature/modelpersonas` is the intended integration branch.
2. Recheck the actual version, uncommitted state, and affected runtime contracts.
3. Create the persona helper and its pure behavioral tests.
4. Capture disabled, enabled, whitespace-only, invalid, Unicode, and
   non-mutation behavior.

### Phase 2 — Persistence and Projection

1. Extend shared model normalization and validation.
2. Add stable-ID merge preservation for omitted persona fields.
3. Add authorized editor projections and ordinary-user visibility behavior.
4. Add persona redaction to logging/settings sanitization.
5. Add aggregate serialized settings-size validation before writes.
6. Verify all global, personal, and group writers return validation and
   concurrency failures without partial success.

### Phase 3 — Runtime Integration

1. Bind persona state in the existing sync and async model client/service
   factories.
2. Preserve exact model IDs through wrappers and callers that currently discard
   them.
3. Cover Chat Completions, Responses, Anthropic, and Semantic Kernel requests.
4. Close conditional direct-agent, summary, and legacy-runtime bypasses with an
   explicit agent exclusion.
5. Verify exactly-once behavior across retries, streaming, tools, and fallbacks.
6. Update budget accounting and cache freshness only at demonstrated seams.

### Phase 4 — V2 and Classic Editors

1. Extend V2 model types and payload/discovery helpers.
2. Add per-model persona controls to the shared V2 connection manager.
3. Mirror controls in classic admin and workspace model renderers.
4. Add safe Markdown preview and accessible validation.
5. Preserve drafts, disabled text, visibility, and discovery state across
   rerenders.
6. Hide controls for ineligible operation types.

### Phase 5 — Coverage and Documentation

1. Extend the nearest backend, route, runtime, consumer, and UI test suites.
2. Add exact model-isolation and agent-exclusion tests.
3. Add XSS, visibility, authorization, draft-retention, conflict, and
   aggregate-size tests.
4. Add provider-adapter outbound-payload tests using mocks.
5. Run V2 typecheck/build, focused Python tests, browser tests, route-policy
   coverage, and the full repository Python suite required by repository
   instructions.
6. Update the AI Connections guide and feature documentation.
7. Increment only the third segment of the application version during code
   implementation. If the baseline remains `0.261.460`, use `0.261.461`.
8. Offer a release-notes update after implementation validation.

## Acceptance Criteria

- [ ] Eligible models expose persona controls in V2 and classic editors.
- [ ] Embedding-only and image-only models do not expose persona controls.
- [ ] Global, personal, and group saves reopen with the expected persona state.
- [ ] Persona visibility defaults to on and is enforced.
- [ ] Same-named models on different connections do not share personas.
- [ ] Existing models normalize safely without eager migration.
- [ ] Older editor payloads and discovery preserve saved persona fields.
- [ ] Missing, disabled, or whitespace-only personas produce unchanged outbound
      requests.
- [ ] An enabled persona appears exactly once in every eligible direct
      text-generation request.
- [ ] Agent requests receive no model persona.
- [ ] Direct embedding and image-generation payloads receive no model persona.
- [ ] Chat text that plans an image request may receive the persona without
      changing the image operation.
- [ ] Existing system, task, multimodal, tool, and structured-output content is
      preserved.
- [ ] Retries, streaming, fallbacks, and tool rounds do not duplicate the
      persona.
- [ ] Persona tokens are included in context and output-budget calculations.
- [ ] Context overflow summarizes prior history rather than dropping or
      truncating the persona.
- [ ] Scripts, event handlers, unsafe URLs, Mermaid, and embedded media cannot
      execute or fetch during preview.
- [ ] Unauthorized users cannot edit or forge runtime persona content.
- [ ] Ordinary settings, logs, errors, diagnostics, and telemetry do not leak
      hidden persona text.
- [ ] New requests receive edited personas while in-flight requests retain
      their bound snapshot.
- [ ] Validation, conflict, storage-size, and provider failures retain drafts
      and do not report partial success.
- [ ] Disabling a persona restores previous outbound request behavior.
- [ ] Downgrade behavior does not silently erase saved persona fields.

## Validation Plan

### Unit and Functional Coverage

Add or extend the nearest tests for:

- 8,000 versus 8,001 Unicode characters
- Supplementary Unicode code points
- Missing, disabled, empty, and whitespace-only behavior
- Invalid field types and oversized values
- Message-list non-mutation
- Exactly-once injection
- Stable-ID merge preservation
- Discovery preservation
- Authorized editor projections and visibility
- Aggregate settings-document limits
- Cache freshness and request-local snapshots
- Agent exclusion
- Direct image/embedding exclusion
- Provider conversions
- Retry, streaming, fallback, and tool continuation
- Context-overflow summarization

### Browser Coverage

Extend existing V2 and classic browser tests to cover:

- Toggle, editor, preview, counter, and visibility control
- Save/reopen for global, personal, and group scopes
- Same-named models on separate connections
- Disabled text retention
- Keyboard and focus behavior
- Mobile layout
- Validation and conflict draft retention
- Read-only user visibility
- Unsafe Markdown rendering

### Baseline Caution

The earlier planning investigation found baseline failures in several
extracted text-consumer test harnesses, including missing or stale helper
names. These are pre-feature evidence and must be reproduced on the current
implementation baseline. Repair only directly affected harness contracts and
report unrelated baseline failures separately.

Live provider checks require explicit test-environment authorization and are
not part of local plan completion.

## Rollback

- Disabling a persona is the immediate operational kill switch.
- No conversation-history or agent-data rewrite is required.
- Previous runtime versions may ignore the additive fields.
- Persisted persona fields can remain when implementation code is reverted.
- Downgrade behavior must be tested so older editors do not silently erase
  saved personas.
- No destructive migration or cleanup is required for rollback.

## Performance Considerations

- Personas increase prompt length and token consumption.
- Every persona message participates in existing context budgets.
- Large persona configurations contribute to settings-document size even when
  personas are disabled.
- Request snapshots and cache digests must not create cross-user or cross-model
  leakage.
- Markdown preview rendering remains local and bounded by the 8,000-character
  source limit.

## Known Limitations and Risks

- Personas can influence screening, summaries, extraction, and structured
  generation. Administrators should use a separate persona-free model for roles
  where that influence is undesirable.
- Persona text hidden from ordinary users is not a guaranteed secret because
  a model can reproduce instructions in generated output.
- Prompt ordering does not override provider behavior, safety policies, or
  application authorization.
- Hosted Foundry agents and legacy unbound calls remain outside this feature.
- Multiple personas can cause the aggregate settings document to grow beyond
  its supported size.
- Context use may increase, causing earlier summarization or explicit overflow.
- The active branch and test baseline must be revalidated before implementation.

## Dependencies

- Existing V2 Markdown renderer
- Existing classic Marked and DOMPurify assets
- Existing AI Connections model identity, normalization, and scope authorization
- Existing sync/async model client and Semantic Kernel factories
- Existing workflow/tabular context-budget infrastructure
- Existing V2 and Playwright test harnesses

No new package or service dependency is planned.

## Implementation Handoff

The implementation owner should:

1. Recheck this plan against `feature/modelpersonas`.
2. Preserve unrelated work and existing authorization boundaries.
3. Implement only the approved scope.
4. Stop for review if evidence requires agent persona composition, hosted
   Foundry integration, a new dependency, or a public configuration contract
   outside this plan.
5. Update the checklist and tracking issue with focused validation results.
