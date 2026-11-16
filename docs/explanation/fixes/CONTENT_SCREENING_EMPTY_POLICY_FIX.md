# Content Screening Empty Policy Fix

**Fixed in version: 0.261.114**, recorded in `application\single_app\config.py`.

## Issue and root cause

Content Screening could not be enabled until an administrator separately saved
an enabled policy with at least one active check. Classic rejected the new-scan
switch immediately, while V2 accepted the draft switch and rejected the later
Admin Settings save. Visible policy edits were not the persisted policy used by
either activation request.

The policy schema conflated an enabled feature with an executable inspection.
Upload admission also used the feature flag alone, so simply removing the
settings error would have held new uploads against an empty policy.

## Behavior

Enabling Content Screening creates an enabled empty global baseline if no
policy exists. Existing policies are preserved, including deliberately disabled
baselines. An enabled policy can be saved with no rules, all rules disabled, or
AI checks off. No starter rules or models are selected automatically.

New uploads whose effective policy has no checks use ordinary processing.
An enabled workspace addition can supply checks under an empty enabled
baseline. Adding checks later applies them to subsequent uploads; existing
knowledge requires an explicit scan.

Persisted holds, evidence, review decisions, and publication requirements do not
change. A policy becoming empty does not clear an earlier finding or create a
passing inspection. Enhanced Citations, its private storage, configured model
validation, scope authorization, and conditional writes remain enforced.

## Interface and settings comparison

| Operation | Classic V1 | React V2 |
| --- | --- | --- |
| Enable new scanning | Switch saves immediately | Switch is saved with Admin Settings **Save changes** |
| Save policy rules and model criteria | **Save screening policy** | **Save screening policy** |
| Save an enabled policy without checks | Allowed | Allowed |
| First activation with no saved policy | Creates an enabled empty baseline | Creates an enabled empty baseline |
| Unsaved policy edits during activation | Retained; initialization revision refreshed safely | Retained; initialization revision refreshed safely |
| Concurrent policy changes | Draft retained; reload required rather than overwriting | Draft retained; reload required rather than overwriting |
| Test an empty policy | Explains that testing needs a check; saving remains available | Same |

Both editors retain custom literal, regex, and PII rules; per-rule severity,
category, and enabled controls; optional AI scanner criteria and window limits;
independent workspace model permissions; and execution limits. The
**No active checks configured** summary distinguishes an empty policy from
actual screening coverage.

The shared starter packs are unchanged:

| Pack | Checks |
| --- | --- |
| `structured_pii_v1` | Email addresses, phone numbers, US Social Security numbers, payment cards |
| `sensitive_text_v1` | Confidentiality markings |
| `credentials_v1` | Private-key markers and GitHub-token indicators |
| `prompt_manipulation_v1` | Instruction overrides and source-ranking manipulation |

Both editors also retain the prompt-manipulation and sensitive-information AI
criteria. Starter-pack and custom-rule parity was already implemented in
0.261.108; this fix changes activation and empty-policy behavior rather than
adding another rule catalog.

## Implementation and validation

The backend changes policy normalization, shared settings activation, and
checks-aware document admission in `content_screening`, `functions_settings.py`,
and `functions_documents.py`. Empty configuration is distinguished from the
active policy required to inspect or release previously enrolled content.

The classic `content-screening-policy.js` and V2 `ScreeningPolicyEditor` retain
drafts across activation and refresh the newly created policy revision. They
do not advance a dirty draft onto a different administrator's saved policy.
Help text in the admin pane and field schema describes the empty state.

`ui_tests\test_content_screening_policy_parity.py` covers the same activation,
empty-save, later-rule, and conflict workflows in both interfaces using their
real local assets and synthetic API boundaries. The existing Azure/local
Playwright fixture is reused. `functional_tests\test_v2_content_screening_logic.mjs`
checks empty-policy validation, summary text, and safe initialization matching.
Backend functional coverage exercises policy composition, settings persistence,
new uploads, and retained holds without live Azure services.

At 0.261.114, the content-screening functional suite passed 643 tests and
688 subtests. The V2 production build, 30 logic checks, 8 rendering checks,
route-policy coverage, documentation inventory/quality checks, and targeted
browser/XSS/access guardrails also passed. Shared policy browser coverage
includes first activation, blank saves, later checks, draft preservation,
creation-revision updates, and explicit failure feedback.

Before this fix, first-time activation required preconfigured checks and failed
at different points in each interface. Afterward, administrators can enable
the capability first and deliberately configure inspection later, without
treating unscreened uploads as screened or releasing existing holds.
