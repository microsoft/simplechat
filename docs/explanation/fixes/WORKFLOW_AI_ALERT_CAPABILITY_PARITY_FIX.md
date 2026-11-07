# Workflow AI alert capability parity fix (v0.261.315)

Fixed/Implemented in version: **0.261.315**, tracked in
`application/single_app/config.py`.

## Issue and root cause

Ask AI could incorrectly describe alert acknowledgment as unsupported even while the workflow
editor displayed it. Its draft projection omitted acknowledgment, sound and size, and its
allowlist offered no update-existing-rule operation or pop-up option fields. Chat's proposal
blueprint separately restricted alerts to quiet info/low run-status notifications. Its builder
forced notification-bell delivery, and the approval card promised alerts never popped up.
Prompt changes alone could not overcome these closed contracts.

The reported email/external-system configuration detour is consistent with missing native
capability information, but its original deployed model trace was not inspected; the exact
cause of that individual response is not proven.

## Technical changes and impact

- `functions_workflow_alert_authoring.py` provides bounded, ID-free personal rule schemas using
  the existing native alert vocabulary and limits. Both authoring paths reuse them.
- `functions_workflow_assist_operations.py` exposes pop-up options and supports targeted
  `update_alert_rule` changes, retaining IDs, order and fields not requested. Changed rules
  are checked with native validation; an untouched pre-existing invalid rule is not newly rejected.
- `functions_workflow_drafts.py` accepts explicit rules-mode blueprints, checks task references
  and option compatibility, and maps task positions to deterministic saved IDs. Legacy quiet
  proposals and one-shot hand-off defaults retain their behavior.
- `functions_workflow_assist.py`, `functions_orchestration_planner.py` and
  `functions_orchestration_registry.py` explain native alerts versus email and external alarm
  configuration. Capability selection stays model-driven, with no keyword-routing heuristics.
- `functions_orchestration_workflows.py`, `workflowProposals.ts` and `WorkflowProposalCard.tsx`
  carry and disclose native rule settings before approval, while continuing to read old summaries.

Explicit strongest-attention requests guide the model toward critical pop-ups, acknowledgment,
repeating sound and full-screen size for review. Ordinary alerts keep quiet defaults; explicit
constraints still apply. Sound preferences, ownership, proposal approval, draft-only assistance,
and personal-workflow audience limits are unchanged.

## Validation and limitations

`functional_tests/test_workflow_ai_alert_capability_parity.py` exercises rule targeting, explicit
clearing, invalid handles, incompatible options, deterministic dry-run/create, disclosure and
adverse findings after successful acquisition. Its evaluator/model replies are scripted.
`test_workflow_draft_v2_round_trip.py` exercises the production TypeScript editor and real save
path. Proposal route round-trip coverage also includes acknowledged critical rules.
`test_v2_workflow_proposal_alerts.mjs` covers old/new client contracts and malformed responses.
`ui_tests/test_v2_orchestration_workflow_proposal_card.py` checks review disclosure and inert text
in desktop/light and mobile/dark layouts.

Before: AI authors could not express these options, and a chat proposal could only create quiet
run-status alerts. After: they can propose, edit and preserve native conditional pop-up rules,
with the consequences visible before persistence.

Offline contract tests do not prove a live model will choose correctly on every paraphrase.
Provider-backed evaluation of monitoring, explicit email, negated findings and strongest-attention
requests remains necessary in a configured deployment. No private chat or telemetry is used by
the regression suite.

### Local validation results

| Check | Result |
| --- | --- |
| Targeted assistant, draft service, production editor save parity and alert runtime suites | 381 passed |
| Complete proposal-card browser suite, using the shared local/Azure Playwright connection fixture | 49 passed locally, including desktop/light and mobile/dark alert disclosures |
| Proposal alert and merge response parser tests | 6 passed |
| V2 TypeScript check and production build into UI test artifacts | Passed |
| Documentation inventory coverage and site quality | 7/7 and 6/6 passed; inventory unchanged |

The orchestration route integration suites could not complete in this environment: their fixture
hits a `functions_public_workspaces` / `functions_search` import cycle. Repeating an existing
round-trip test with the original application modules from `HEAD` reproduced that failure.
Bootstrapping authentication first then exposes an unrelated installed OpenSSL/cryptography
incompatibility (`GEN_EMAIL` missing). Neither issue was changed or suppressed. The real workflow
builder, production TypeScript editor and personal save round-trip tests do pass independently.
