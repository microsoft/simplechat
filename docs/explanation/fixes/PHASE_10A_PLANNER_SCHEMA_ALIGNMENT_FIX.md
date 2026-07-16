# Phase 10A Planner Schema Alignment Fix

Fixed in version: **0.250.071**

Associated issue: **[#1021](https://github.com/microsoft/simplechat/issues/1021)**

## Issue

Phase 10A deterministic fixtures passed because their model payloads already
used the validator's required aliases and inventory IDs. Initial controlled live
calls exposed a mismatch: the provider-facing JSON schema described requirement
IDs, candidate IDs, and capability IDs as generic strings, while the server
validator required `requirement_N`, `candidate_N`, and exact authorized
inventory IDs.

Live models consequently returned values such as `req1`, `plan1`, or a
candidate alias in `capability_ids`. The validator correctly rejected these
outputs, preserving deterministic fallback and preventing execution, but the
invalid-output rate blocked Phase 10B activation.

## Root Cause

The strict validator and model-facing schema expressed different constraints.
The schema embedded in the prompt was also built separately from the schema in
the Azure/OpenAI `response_format`, so an early request-specific correction did
not constrain provider structured output. Selected capabilities were exposed as
candidate members even though candidates represent additions only, inviting
selected-only proposals that the validator rejected as
`no_additional_capability`.

The original 300-token completion budget could also be consumed by a reasoning
model before visible JSON was returned.

## Technical Changes

- `application/single_app/functions_chat_capability_planner.py`
  - Builds one request-specific schema shared by the prompt and provider
    `response_format`.
  - Enumerates exact requirement and candidate aliases within server budgets.
  - Enumerates only authorized, discoverable, input-ready unselected additions
    and safe evidence types from the current planner request.
  - Removes `propose` when no additional capability can be represented.
  - Keeps selected mandates outside candidate additions and restores them only
    through existing server validation.
  - Clarifies direct behavior when selected mandates already satisfy the
    requested evidence class.
- `application/single_app/functions_settings.py`
  - Raises the default completion budget from 300 to 600 tokens.
- `scripts/run_phase10a_controlled_shadow.py`
  - Adds a repeatable non-executing live gate with Azure CLI or API-key auth,
    bounded scoring, explicit thresholds, and privacy-safe JSON evidence.
- `functional_tests/fixtures/phase10a_controlled_shadow_scenarios.json`
  - Defines 19 realistic direct, proposal, additive, selected, clarification,
    injection, and ineligible scenarios.
- `functional_tests/test_chat_capability_model_planner.py` and
  `functional_tests/test_phase10a_controlled_shadow_runner.py`
  - Cover schema alignment, policy budgets, input gating, scoring, failure
    thresholds, and report privacy.

## Impact

The planner remains strictly non-executing in `shadow` mode. Unknown,
unauthorized, unavailable, blocked, and input-not-ready capabilities still fail
closed in the existing validator. No route, browser payload, authorization
policy, capability execution path, or deterministic fallback behavior changed.

## Validation

- Focused planner and controlled-runner suites: **25 passed**.
- Controlled `gpt-5.6-terra` matrix: **57/57 end-to-end samples passed**.
- Semantic accuracy and strict JSON-schema use: **100% in every category**.
- Timeout, operational-failure, and invalid-output rates: **0%**.
- False proposals, capability leakage, and prohibited execution-surface imports: **0**.
- Planner latency: **p50 1.67 seconds**, **p95 2.65 seconds**.

The application version in `application/single_app/config.py` was updated to
`0.250.071` for this hardening change.