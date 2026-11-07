# GPT-6 Reasoning Model Parameters Fix

Fixed in version: **0.261.219**

## Issue

Requests to GPT-6 deployments, such as `gpt-6-astra`, failed with a 400 whenever SimpleChat set a response length:

> Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead.

Workflows were the most visible case. Once a model's token limits are configured, the workflow budget sets a response length on every model call, so each workflow run that used a GPT-6 agent failed on its first call. Chat failed the same way when a Response Length was set.

## Root Cause

`ModelEndpointBehavior.is_openai_reasoning_model` in `model_endpoint_clients.py` recognized only `gpt-5`, `o1`, `o3` and `o4` names. The policy decides two things:

- whether the response length is sent as `max_completion_tokens` or as `max_tokens`;
- whether a temperature is sent.

GPT-6 deployments fell through to the non-reasoning defaults, which they reject.

## Technical Details

Files modified:

- `application/single_app/model_endpoint_clients.py`
- `application/single_app/config.py`
- `functional_tests/test_gpt6_reasoning_model_parameters.py` (new)

`gpt-6` joins `gpt-5` in both checks: as a name prefix, and as a family name anywhere in a deployment or display name, such as `N-gpt-6-astra` or `GPT 6 Astra`. Every caller that uses the shared policy follows it, including:

- workflow budgets
- chat response length
- prompt variables
- content screening
- orchestration

## Validation

`functional_tests/test_gpt6_reasoning_model_parameters.py` runs the real policy and the workflow budget's parameter choice from source. It covers these cases:

- GPT-6 deployment, alias and display names use `max_completion_tokens`, and are treated as reasoning models.
- GPT-5, o-series and GPT-4 models keep their parameters.
- The workflow budget sets `max_completion_tokens` for a GPT-6 model.

Without the fix, the 4 GPT-6 cases and both workflow budget cases fail. `test_model_endpoint_protocol_inference.py` and `test_model_reasoning_capability_resolution.py` still pass.
