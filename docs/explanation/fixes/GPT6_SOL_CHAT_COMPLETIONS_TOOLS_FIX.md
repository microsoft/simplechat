# GPT-6 Sol Chat Completions Tools Fix

Fixed in version: **0.261.221**

Related issue: #1606

## Issue

Agents with actions on `gpt-6-sol` failed unless their Reasoning Effort was set to None by hand. With no effort set, Azure rejected the request:

> Function tools with reasoning_effort are not supported for gpt-6-sol in /v1/chat/completions. To use function tools, use /v1/responses or set reasoning_effort to 'none'.

## Root Cause

`gpt-6-sol` wasn't in the model catalog. SimpleChat already enforces this rule for GPT-5.6 through the catalog's `toolReasoningEfforts` field. With no record for `gpt-6-sol`, it sent the request with no effort, and the model applied its own default.

OpenAI documents the rule on the `gpt-6-sol` model page: "Chat Completions supports function calling only with `reasoning_effort` set to `none`." Azure behaved the same on 2026-10-01: tools were rejected with the default effort and accepted with `none`.

## Technical Details

Files modified:

- `application/single_app/static/json/model_capabilities.json`
- `application/single_app/config.py`
- `functional_tests/test_model_catalog_rebase_integration.py`
- `functional_tests/test_gpt6_astra_catalog_record.py`
- `functional_tests/test_gpt6_sol_catalog_record.py` (new)

`gpt-6-sol` is now a token-evidenced record:

| Field | Value | Source |
|---|---|---|
| Shared context | 1,050,000 | OpenAI `gpt-6-sol` specification; Azure GPT-6 table for the `azure` profile |
| Maximum input | 922,000 | Same |
| Maximum output | 128,000 | Same |
| Output accounting | Total generation (reasoning plus visible output) | OpenAI and Azure reasoning guides |
| Reasoning efforts | none, low, medium, high, xhigh; fallback low | OpenAI specification |
| Chat Completions tools | `toolReasoningEfforts: ["none"]` for `openai` and `azure` | OpenAI specification; Azure behavior observed on 2026-10-01 |

The capability flags match the published feature list, which is the same as for `gpt-6-astra` and `gpt-5.6-sol`. That list includes the Responses image-generation tool. `max` isn't in the reasoning policy because SimpleChat's policy covers Chat Completions only.

There are two new sources: `openai-spec-gpt-6-sol` and `gpt-6-sol-deployed-contract`.

## Behavior After the Fix

- An agent with tools on `gpt-6-sol` that has no Reasoning Effort set sends `none`, for Azure and for direct OpenAI.
- An explicit effort other than `none` on an agent with tools fails before the request with "This model's Chat Completions tools require Reasoning Effort None." The provider's 400 no longer appears.
- Without tools, every listed effort is sent as selected.
- The Responses protocol carries no tool restriction.
- Budgets use the verified limits, so file evidence and workflow budgets don't need manual limits. Limits set in Model Endpoints still take precedence.
- `gpt-6` and `gpt-6-luna` don't inherit anything from this record.

## Validation

`functional_tests/test_gpt6_sol_catalog_record.py` checks these cases:

- The catalog passes schema validation and the cross-record integrity checks.
- The OpenAI and Azure limits each cite their exact specification.
- Both Chat Completions tool profiles require `none` and cite their evidence.
- Budgets carry the tool rule for Chat Completions only.
- Tools with no effort send `none`, and with `max_completion_tokens`.
- Tools with another explicit effort fail before the request; without tools, that effort is sent as selected.
- The reasoning policy and capability flags are correct.
- `gpt-6` and `gpt-6-luna` stay unknown.

The catalog, capability, reasoning, budget and image tests pass. `test_ai_connections_capabilities.py` has the same 9 failures before and after this change. None of them involves GPT-6.
