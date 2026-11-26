# Model Endpoint Baseline Test Fix (0.261.040)

## Version and Scope

Fixed in version: **0.261.040**.

The patch version in [config.py](../../../application/single_app/config.py) was
incremented from **0.261.039** to **0.261.040** for these test repairs. Both modified
functional-test headers identify this repair version and retain their original
implementation versions. No endpoint routing, authentication, UI, or database
behavior changed.

This closes the baseline gate in the
[Custom endpoint routing specification](../features/CUSTOM_ENDPOINTS_PER_MODEL_ROUTING_SPEC.md).
It does not implement the planned per-model routing feature.

## Root Causes

The summary test extracted production route helpers into an isolated namespace
without their `build_model_endpoint_identity_headers` dependency. The production
route imported that helper correctly, but three test cases raised `NameError`.

The editor payload-order test searched the whole JavaScript file for obsolete
Foundry validation text. It also located an auth declaration outside the payload
builder, which could conceal incorrect ordering inside the function under test.
The production builder already used `isFoundryProvider(provider)` and a conditional
Custom-provider auth assignment.

## Changes

- [Summary protocol test](../../../functional_tests/test_conversation_summary_model_endpoint_protocol.py):
  imports the real identity-header helper and supplies it to the extracted namespace.
  It does not replace identity behavior with a no-op stub.
- [Payload auth-order test](../../../functional_tests/test_model_endpoint_payload_auth_type_order.py):
  scopes the assertion to `buildEndpointPayload`, recognizes the current auth
  declaration and Foundry helper, and checks declaration order before both
  Foundry and Azure OpenAI validation.
- [config.py](../../../application/single_app/config.py): version metadata only.

The payload-order repair adapts the narrow test hunk from
[source commit 3f896d7b](https://github.com/microsoft/simplechat/blob/3f896d7b6c45800c593599f3100b9aa7c7251159/functional_tests/test_model_endpoint_payload_auth_type_order.py).
No unrelated source-branch imports or runtime changes were copied.

## Validation

On 2026-09-22, the selected virtual environment ran Python **3.13.15**. Each of the
21 Phase 0 baseline scripts ran in a fresh process through its standalone runner,
with external connections, external DNS, subprocess launches, and dotenv-file
reads blocked. The on-prem test used deterministic offline DNS fixtures. The
specification records the complete script list and execution details.

| Check | Before | After |
|---|---|---|
| Summary protocol script | 1/4 cases passed | 4/4 cases passed |
| Payload auth-order script | Failed on obsolete source text | Passed |
| Phase 0 baseline | 19/21 scripts passed | 21/21 scripts passed |
| Separate identity-header suite | Passed | 5/5 cases passed |

Two in-memory negative probes confirmed the repaired payload test rejects a
missing local auth declaration and a declaration moved after validation, even
when earlier declarations exist outside the builder. These probes did not edit
the JavaScript file.

The token-budget suite reported an existing `anyio` assertion-rewrite warning;
all 51 cases passed. Editor diagnostics were clean for the modified Python files.

## Impact and Limits

The fixes restore useful baseline coverage and remove false failures without
changing user-facing behavior. No dependencies were installed or upgraded, no
secrets or endpoint settings were changed, and no live inference was performed.

The full repository suite, browser suite, and live authorization/provider checks
were not run. Source-string and extracted-function tests are not end-to-end
browser or bootstrap coverage. Those broader gates remain in the implementation
plan for the later routing changes.