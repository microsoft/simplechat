# GPT-6 Astra Model Catalog Fix

Fixed in version: **0.261.220**

Related issue: #1606

## Issue

The model catalog described `gpt-6-astra` only through its image-generation tool. It had no token limits, reasoning policy or note about how the model handles function tools. That caused three problems:

- **Token limits had to be entered by hand.** Every deployment needed limits set in Model Endpoints before it could use file evidence or a workflow token budget. Without them, workflows fell back to a small compatibility budget.
- **No reasoning policy.** With no policy, chat sent no reasoning effort for this model, so the model always used its default. Agents send their saved effort as is, so an agent saved with `none` was rejected: "Supported values are: 'low', 'medium', 'high', and 'xhigh'."
- **Nothing warned about function tools.** Azure Chat Completions rejects function tools for `gpt-6-astra` unless `reasoning_effort` is `none`, which the model also rejects. The catalog gave no sign of this, so agents with actions on `gpt-6-astra` failed only when they ran.

## Root Cause

`gpt-6-astra` was added as an operation-only record. Operation-only records can't carry token limits, and this one had no reasoning policy.

The tool restriction isn't in the documentation either:

- Azure's model table lists Chat Completions and "Functions, tools, and parallel tool calling" for GPT-6. It doesn't have the GPT-5.6 note that Chat Completions tools require `reasoning_effort: none`.
- OpenAI lists reasoning efforts low, medium, high, xhigh and max for `gpt-6-astra`. `none` isn't among them.

## Technical Details

Files modified:

- `application/single_app/static/json/model_capabilities.json`
- `application/single_app/config.py`
- `functional_tests/test_model_catalog_rebase_integration.py`
- `functional_tests/test_gpt6_astra_catalog_record.py` (new)

`gpt-6-astra` is now a token-evidenced record, reviewed on 2026-10-01 and kept separate from the 2026-09-19 audit of the original 75 records. It records:

| Field | Value | Source |
|---|---|---|
| Shared context | 1,050,000 | OpenAI `gpt-6-astra` specification; Azure GPT-6 table for the `azure` profile |
| Maximum input | 922,000 | Same |
| Maximum output | 128,000 | Same |
| Output accounting | Total generation (reasoning plus visible output) | OpenAI and Azure reasoning guides |
| Reasoning efforts | low, medium, high, xhigh; fallback low | OpenAI specification and the observed Azure rejection |

The capability flags match the documented features: text and image input with text output, streaming, structured outputs, function calling and reasoning. These flags are identical to the published feature list for `gpt-5.6-sol`. `max` isn't in the reasoning policy because SimpleChat's policy covers Chat Completions only.

There are three new sources: `openai-spec-gpt-6-astra`, `azure-spec-gpt-6` and `gpt-6-astra-deployed-contract`. The last one records the Azure rejections observed on 2026-10-01 against model version 2026-09-03:

| Reasoning effort | With function tools on Chat Completions |
|---|---|
| Not set (model default) | Rejected: "Function tools with reasoning_effort are not supported for gpt-6-astra in /v1/chat/completions. To use function tools, use /v1/responses or set reasoning_effort to 'none'." |
| `low` | Rejected with the same error |
| `none` | Rejected: "'reasoning_effort' does not support 'none' with this model" |

`toolReasoningEfforts` lists the efforts that may be used with tools. It can't express a model where no effort works, so the record doesn't declare one. The restriction is recorded in the model notes, the `azure` profile note and a coverage note.

## Behavior After the Fix

- Budgets for `gpt-6-astra` resolve to the verified limits for Azure and OpenAI, so file evidence and workflow budgets no longer need manual limits. Limits set in Model Endpoints still take precedence.
- Chat now sends the selected reasoning effort. If `none` or another unsupported effort is selected, chat sends `low` instead. Agents still send their saved effort as is, so don't save a `gpt-6-astra` agent with None.
- `gpt-6`, `gpt-6-sol` and `gpt-6-luna` don't inherit anything from this record. Suffixed deployment names such as `gpt-6-astra-eastus` get the reasoning policy, which matches by prefix, but not the token limits, which need the exact model name.
- Agents with actions on `gpt-6-astra` still fail on Azure Chat Completions. Local agents can't use the Responses API yet, and the runtime doesn't yet fail early with a clear message. #1606 tracks both. For agents with actions, use `gpt-6-sol`. From 0.261.221, SimpleChat sends Reasoning Effort None for it when tools are present; see [GPT6_SOL_CHAT_COMPLETIONS_TOOLS_FIX.md](GPT6_SOL_CHAT_COMPLETIONS_TOOLS_FIX.md).

## Validation

`functional_tests/test_gpt6_astra_catalog_record.py` checks these cases:

- The catalog passes schema validation and the cross-record integrity checks.
- The OpenAI and Azure limits each cite their exact specification.
- No tool-effort constraint is invented.
- Budgets resolve for both providers and both protocols.
- The reasoning policy excludes `none` and corrects it to `low`.
- The capability flags keep the Responses image-generation tool.
- Sibling GPT-6 names don't inherit the record, and suffixed names get the reasoning policy but no token limits.

`test_model_catalog_rebase_integration.py` now treats `gpt-6-astra` as a token-evidenced record with a reasoning policy, and registers the 2026-10-01 source review. The catalog, capability, reasoning, budget, image-generation and AI connection test files all pass. Four files that need `tiktoken` or live Azure credentials to import were skipped.
