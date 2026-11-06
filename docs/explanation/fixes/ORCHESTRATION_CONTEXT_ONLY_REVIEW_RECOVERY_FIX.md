# Context-only orchestration review recovery (v0.261.417)

Fixed/Implemented in version: **0.261.417**
(`application/single_app/config.py`).

## Issue and root cause

A self-contained rewrite prepared its answer and passed output-format validation,
but orchestration withheld the draft with `completeness_requirements_changed`.
There were zero answer adjustments. The reviewer had returned a checklist whose
identities did not match the application's three narrative obligations.

Version 0.261.416 allowed paraphrased requirement descriptions, but still relied
on the model reproducing obligation IDs in a list. Generic JSON mode did not close
those identities, and report repair supplied only a failure code. This was an
assessment-protocol failure, not evidence that the draft was wrong.

The original request was already included in the final checker's instructions.
It was not explicitly labeled as user-supplied source content in the evidence
object, leaving an avoidable distinction between the user's account and gathered
inputs.

## Shared assessment contract

`functions_task_completeness.py` supplies known obligations as a closed keyed
assessment schema and attaches canonical descriptions server-side. The reviewer
assesses requested facts within those obligations instead of inventing new IDs.
Legacy list reports remain readable, but cannot add/drop identities or use
paraphrased descriptions to relax application-owned quote checks.

`model_endpoint_clients.py` owns bounded response-format compatibility. Explicit
strict-schema rejection can fall back to JSON mode, then prompt-only mode; other
provider rejections are not format negotiation. Both orchestration and workflow
invocation owners use the same helper. Local report validation remains strict.

## Grounding and bounded recovery

`functions_orchestration_composition.py` identifies the complete authorized
original message as `user_provided_content` for review and correction. The checker
may preserve the user's stated account in a rewrite without demanding outside
verification. A question asking for an unknown fact does not establish that fact,
and the prepared candidate is not its own evidence.

The compose capability declares a validated content intent, independently of
model routing. The executor computes eligible context-only steps from the actual
enabled plan. Auto recovery is limited to a single, explicitly classified,
prose-only draft/transformation with no gathered or named inputs, analysis,
calculation, visuals, structured datasets, or effectful steps. Missing intent
retains strict review.

On an eligible checker error, the existing draft can complete required checks
without another draft generation or blind reviewer retry. The full existing
conversation-context validator rechecks message fingerprints, masks, ownership,
memory audience and capability access before that result is committed.

The saved semantic outcome is skipped-on-error, with its safe reason, not a passed
assessment. Genuine content findings, prior unresolved findings, refusals/content
filtering, source changes, lost access, cancellation, budget failures and
interrupted corrections cannot use this recovery. Explicit On, gathered-data
tasks and workflows keep their strict gates. Administrative disablement and zero
correction limits retain their existing meaning.

Checkpoint identity upgrades only accept the explicit source text when it was
already bound in the original approved request. They preserve the original
candidate and consumed allowances rather than resetting work.

## Plan and conversation behavior

The chat delivers the draft without a skipped-review warning or technical
appendix. Plan inspection retains the actual skipped stage and diagnostic.

Completed checks show their actual value: reviewed against supplied text,
gathered information, both, or the request. A format-only result says **Required
output format validated**, not that content was reviewed. Older reports do not
gain invented attribution, and late/older candidate stages cannot certify the
current answer.

The V2 helpers and existing run/plan components use inert text and existing theme
tokens. The positive validation statement uses the stronger success foreground
to preserve at least 4.5:1 measured contrast in tested light/dark views. No new
browser dependency, remote asset, administrator toggle, route or connector was
introduced. Normal non-orchestrated chat and deployer versions are unchanged.

## Validation and impact

The functional engine, runtime and available-information suites cover closed
checklists, precise repair feedback, real composition/model-call wiring,
original-message evidence, retained draft delivery, provider compatibility,
strict negative controls, legacy checkpoints and checking-only retry.

Runtime fault injection includes connection/rate-limit failures, empty/malformed
reports, unrelated provider rejections, refusals/content filtering, lost
conversation ownership and original-message edits/masking during an outage.
Required structured-output checks remain blocking even with a misleading content
intent.

The Python Playwright suites cover quiet activity, saved recovery, historical
reports, source-specific completion statements, plan-only skipped-review details,
stale candidate events, desktop light/mobile dark layouts, and text contrast.
Production V2 assets are typechecked and built from the changed sources.

| Verification | Result |
| --- | --- |
| Review engine, real runtime, available-information, plan schema, invocation, model selection and retry functional selection | 165 passed; 51 subtests passed |
| Quiet activity, completeness and saved-recovery Python Playwright suites | 93 passed, including desktop/mobile and measured light/dark contrast |
| Local browser assets and real model reasoning-capability resolution | 22 passed; 64 subtests passed |
| `python .\scripts\check_cosmos_response_boundaries.py --run-contracts` | 2,005 passed; 431 subtests passed, with external network calls blocked |
| Documentation inventory coverage and site quality | 7/7 and 6/6 checks passed |
| V2 TypeScript check and production/component-test builds | Passed |
| Changed browser-sink scan and deterministic UI design scan | Passed; no design findings |
| Whitespace/diff check | Passed |

The Cosmos inventory renews module-level reviews for unchanged storage-owner
ASTs and SDK consumers. Classifications and all existing runtime evidence remain
in place; no storage or domain validator was relaxed.

An additional GPT-6 AST-only parameter selection has two pre-existing fixture
failures: its extracted `ModelEndpointBehavior` namespace omits
`model_uses_mai_chat_api` for non-reasoning models. The production class AST is
unchanged from the base revision, and real-module model selection/capability
coverage passes. That unrelated fixture was not changed by this fix.

Before this change, a broken optional review could turn an already prepared
self-contained draft into a failed request. Afterward, eligible Auto work can
deliver that draft with truthful required-check-only metadata, while strict
tasks continue to fail closed. Scripted provider replies establish control flow
and contracts, not an empirical guarantee of semantic accuracy. This change does
not deploy the application or replay the investigated production conversation.

See [model-assisted completeness](../features/MODEL_ASSISTED_COMPLETENESS.md),
[orchestration settings](../../admin/orchestration.md), and
[reviewing plans](../../guides/review-and-edit-orchestration-plans.md).
