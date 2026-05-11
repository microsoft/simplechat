# Local Agent Cognitive Services Scope Fix

Fixed/Implemented in version: **0.241.007**

## Issue Description

Local agents using Azure OpenAI managed identity or service principal authentication always requested the commercial Cognitive Services audience from the shared Semantic Kernel loader.

That behavior ignored the configured `cognitive_services_scope` in `config.py`, so non-public environments such as Azure Government and custom cloud deployments could fail to acquire tokens for local agent execution.

## Root Cause Analysis

`resolve_agent_config()` in `application/single_app/semantic_kernel_loader.py` builds token providers for local and Foundry agents through a nested `build_token_provider()` helper.

The Foundry branch already resolved provider-specific `ai.azure*` scopes, but the Azure OpenAI branch hardcoded `https://cognitiveservices.azure.com/.default` instead of reading `cognitive_services_scope` from `application/single_app/config.py`.

Because personal, group, and global local agents all resolve through the same shared loader helper, the hardcoded commercial audience affected every local-agent scope.

## Technical Details

Files modified: `application/single_app/semantic_kernel_loader.py`, `application/single_app/config.py`, `functional_tests/test_local_agent_cognitive_services_scope.py`

Code changes summary:

- Imported `cognitive_services_scope` from `config.py` into the shared Semantic Kernel loader.
- Added a shared Azure OpenAI scope helper inside `resolve_agent_config()` so local token providers consistently use the configured Cognitive Services scope.
- Preserved `resolve_foundry_scope()` for `aifoundry` and `new_foundry` providers so Foundry runtime behavior remains provider-specific.
- Left personal, group, and global agent storage code unchanged because all three local agent scopes already converge on the same loader path.

Impact analysis:

- Local agents now honor the configured Cognitive Services audience in public, government, and custom Azure environments.
- Foundry agent scope resolution remains unchanged and isolated from the local Azure OpenAI fix.

## Validation

Test coverage: `functional_tests/test_local_agent_cognitive_services_scope.py`

Test results:

- Validates that the loader imports and uses `cognitive_services_scope` from `config.py` for Azure OpenAI token providers.
- Validates that the local agent path no longer hardcodes the commercial Cognitive Services scope.
- Validates that Foundry providers still use `resolve_foundry_scope()`.
- Validates that personal, group, and global local agents all resolve through the same shared loader helper.

Before/after comparison:

- Before: Local agents always requested the commercial Cognitive Services audience regardless of environment configuration.
- After: Local agents use the configured `cognitive_services_scope`, while Foundry agents keep their provider-specific scope behavior.

Related config.py version update: `VERSION = "0.241.007"`