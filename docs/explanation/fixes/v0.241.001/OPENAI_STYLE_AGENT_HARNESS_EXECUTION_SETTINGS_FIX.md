# OpenAI-Style Agent Harness Execution Settings Fix

Fixed in version: **0.239.203**

## Issue Description

The standalone harness at `scripts/openai_style_agent_harness.py` failed before any model call was made with this Semantic Kernel error:

`Argument 'execution_settings' has a value that doesn't support automatic encoding.`

## Root Cause Analysis

The harness constructed `KernelArguments` with `execution_settings=...` as a normal keyword argument.

In Semantic Kernel, prompt execution settings must be passed through the dedicated `settings` constructor parameter. Ordinary keyword arguments are treated as prompt template variables, so the agent instruction renderer tried to encode the prompt execution settings object as user content and raised `NotImplementedError`.

## Technical Details

### Files Modified

- `scripts/openai_style_agent_harness.py`
- `functional_tests/test_openai_style_agent_harness.py`
- `functional_tests/test_new_foundry_streaming_runtime.py`
- `application/single_app/config.py`

### Code Changes Summary

- Switched the harness to `KernelArguments(settings=prompt_execution_settings)` so Semantic Kernel receives execution settings through its supported path.
- Tightened the harness regression to assert the correct constructor usage and reject the old broken pattern.
- Bumped `config.py` to `0.239.203` and updated dependent functional test metadata.

### Testing Approach

- `python -m py_compile scripts/openai_style_agent_harness.py`
- `python functional_tests/test_openai_style_agent_harness.py`
- `python functional_tests/test_new_foundry_streaming_runtime.py`

## Validation

### Before

- The harness failed during prompt template rendering before the agent reached the model endpoint.

### After

- The harness passes execution settings through Semantic Kernel's dedicated execution-settings channel, which avoids the prompt-render encoding failure and allows agent invocation to proceed to the normal model call path.

## Impact

This fix is limited to the standalone OpenAI-style harness and does not change the main application runtime. It restores the harness as a reliable local test path for Grok and Phi experiments.