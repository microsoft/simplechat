# OpenAI-Style Agent Harness

Version implemented: **0.239.202**

## Overview

This feature adds a standalone test harness at `scripts/openai_style_agent_harness.py` so Grok and Phi models can be exercised through a Semantic Kernel chat agent that uses an OpenAI-style client instead of `AzureChatCompletion`.

The harness is intended for local experiments before changing the application runtime.

## Dependencies

- `scripts/openai_style_agent_harness.py`
- `scripts/me.json`
- `scripts/agent.json`
- Python environment with `semantic-kernel`, `openai`, and `azure-identity`

## Technical Specifications

### Input Files

The harness reads both JSON files from the same directory as the script.

#### `me.json`

You can provide either a single model endpoint object or a wrapper object containing `model_endpoints`.

Example endpoint object:

```json
{
  "id": "endpoint-grok",
  "provider": "new_foundry",
  "connection": {
    "endpoint": "https://your-project.services.ai.azure.com/openai/v1/",
    "openai_api_version": "v1"
  },
  "auth": {
    "type": "api_key",
    "api_key": "replace-me"
  },
  "models": [
    {
      "id": "grok-4-fast-reasoning",
      "deploymentName": "grok-4-fast-reasoning",
      "enabled": true
    }
  ]
}
```

#### `agent.json`

Use the same general shape as a local SimpleChat agent object.

Example agent object:

```json
{
  "name": "grok-harness",
  "display_name": "Grok Harness",
  "description": "Standalone OpenAI-style agent harness",
  "instructions": "You are a helpful test agent. Use tools when they help answer the user.",
  "model_endpoint_id": "endpoint-grok",
  "model_id": "grok-4-fast-reasoning",
  "model_provider": "new_foundry",
  "max_completion_tokens": 2000,
  "temperature": 0.2,
  "top_p": 1,
  "actions_to_load": []
}
```

### Prompt Execution Settings

The harness explicitly builds prompt execution settings from the selected service and applies:

- `function_choice_behavior`
- `max_completion_tokens` / `max_tokens`
- `temperature`
- `top_p`
- `frequency_penalty`
- `presence_penalty`
- `stop`
- `reasoning_effort` when supported by the execution settings type

The command-line switch `--function-choice` supports:

- `auto`
- `required`
- `none`
- `off`

`off` sets `function_choice_behavior` to `None`, which is useful when comparing tool-enabled vs tool-disabled agent behavior.

For OpenAI-style requests, the harness uses the selected model entry's `deploymentName` as the request `model` value. The saved internal model `id` is only used to select the entry from `me.json`.

### Tooling

The harness loads a small local plugin named `harness_tools` by default so auto function choice can be tested against real callable functions.

Included functions:

- `utc_now`
- `echo_text`

Use `--no-plugin` to disable the local plugin and test a no-tools agent configuration.

## Usage Instructions

Run from the repository root with the repo virtual environment:

```powershell
& .\venv\Scripts\python.exe .\scripts\openai_style_agent_harness.py --message "What time is it in UTC? Use the tool if available."
```

Examples:

```powershell
& .\venv\Scripts\python.exe .\scripts\openai_style_agent_harness.py --function-choice auto
& .\venv\Scripts\python.exe .\scripts\openai_style_agent_harness.py --function-choice off
& .\venv\Scripts\python.exe .\scripts\openai_style_agent_harness.py --function-choice required --max-auto-invoke-attempts 3
& .\venv\Scripts\python.exe .\scripts\openai_style_agent_harness.py --model-id phi-4 --message "Use a tool if needed to answer."
```

## Testing And Validation

Validation coverage is provided by `functional_tests/test_openai_style_agent_harness.py`, which verifies that the harness:

- reads `me.json` and `agent.json`
- builds an OpenAI-style SK service using `AsyncOpenAI` and `OpenAIChatCompletion`
- includes explicit prompt execution settings
- exposes multiple function-choice modes
- invokes the agent through `invoke_stream`

## Known Limitations

- The harness does not load SimpleChat action manifests from `actions_to_load`; it uses a small local plugin instead.
- The harness is intended for local experimentation and does not use Key Vault integration.
- The harness tests one local agent invocation path and does not change the application runtime by itself.