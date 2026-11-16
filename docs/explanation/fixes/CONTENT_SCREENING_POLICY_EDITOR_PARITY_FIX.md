# Content Screening Policy Editor Parity Fix

## Issue

Classic and V2 exposed the same screening policies through different controls. V2 offered individual starter rules instead of packs and lacked explicit custom-rule buttons. An administrative model-permission list appeared before the optional AI switch, and model configuration stayed editable when AI checks were off.

This made it unclear whether deterministic rules called a model or whether selecting several permitted models ran several scanners.

**Fixed in version: 0.261.108**, recorded in `application\single_app\config.py`.

**Related issue:** [#1476](https://github.com/microsoft/simplechat/issues/1476).

## Root cause

The editors presented three separate backend concepts as one model-configuration flow: deterministic `rules`, the policy's optional `ai` check, and the global `allowed_models` permission list. Their starter controls also used different presentations of the same server catalog.

The baseline's saved scanner is implicitly permitted for workspace additions. Treating that visible permission as an explicit allowlist edit would retain unintended permissions when the selected scanner later changed.

## Changes

Both interfaces now provide custom literal, regex, and PII rule buttons and the same four starter packs. Custom match fields start blank and reuse server-defined severity/category defaults. Pack insertion preserves stable IDs and existing edits, including disabled rules.

**Enable AI checks** appears before scanner, criteria, and window settings. Those controls are disabled when AI checks are off, without discarding their saved values. The classic editor also retains an unavailable saved scanner reference when saving a deterministic-only policy instead of silently clearing it. No fallback model is selected.

**Models workspaces may use** is a separate permission section, editable independently of baseline AI execution. The selected baseline scanner is marked as implicitly permitted without promoting it into the explicit allowlist. Regex and literal matching controls are available consistently in both editors.

A live **Configured screening checks** summary includes enabled deterministic and AI checks, required administrator inheritance, and disabled-baseline states. It describes the draft, not the separate new-scan capability. Classic policy preparation is available before Enhanced Citations is configured, while enrollment remains gated.

The implementation changes `content-screening-policy.js`, its template adapter in `content-screening-api.js`, and the V2 `ScreeningPolicyFields`, `ScreeningPolicyEditor`, and `contentScreeningPolicy` helpers. Backend evaluation, reviewer authorization, ETags, held-document enforcement, and publication rules remain unchanged.

## Validation and impact

`ui_tests\test_content_screening_policy_parity.py` exercises the same browser workflows against the real classic assets and production V2 SPA. Coverage includes custom-rule save/reload, matching starter packs at narrow and desktop widths, pack deduplication without resets, disabled AI configuration, independent permissions, implicit-versus-explicit permissions, unavailable saved scanners, and inherited summaries.

`functional_tests\test_v2_content_screening_logic.mjs` and `functional_tests\test_v2_content_screening_rendering.mjs` cover policy construction, summary counts, and control placement/disabled states. `functional_tests\test_content_screening_engine.py` proves that deterministic-only policies with saved scanner references and workspace permissions do not import or invoke a model evaluator.

Validation at 0.261.108 passed: 108 classic/V2 browser scenarios, 117 targeted Python tests with 206 subtests, 28 V2 logic checks, and 8 rendering checks. The V2 production build and standalone documentation coverage/quality checks also passed. No deployment is required to run these closed-fixture checks.

Before this change, model permissions and execution looked related and custom-rule creation differed by interface. After the change, both editors expose the same rule-building choices and distinguish model permission from actual AI checks. Existing saved policies need no migration, and disabling checks or future scans does not release held documents.
