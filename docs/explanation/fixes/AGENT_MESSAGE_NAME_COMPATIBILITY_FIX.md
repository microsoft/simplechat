# Agent message-name compatibility fix

Fixed in version: **0.261.365**.

Application version: `application/single_app/config.py`.

## Issue and root cause

A saved local agent with a name longer than 64 characters could fail before
calling its assigned actions. Semantic Kernel uses the agent's name as the
author of its instruction message, but Azure OpenAI and OpenAI-compatible Chat
Completions requests accept message names of at most 64 characters.

The investigated workflow submitted a 65-character author name. Azure OpenAI
returned HTTP 400 for `messages[0].name`; this was a provider request validation
failure, not the scenario's intended upstream connector failure. Because agent
tasks can perform external actions, the durable runner conservatively stopped
at **Waiting for recovery**.

Normalizing only the initial history is insufficient: during streaming tool
invocation, Semantic Kernel can attribute newly accumulated assistant messages
to the original agent before submitting another model request.

## Changes

`application/single_app/functions_model_message_names.py` implements a
request-only author-name boundary. Names already matching `[A-Za-z0-9_-]+`
and no longer than 64 characters are preserved, including exactly 64-character
names. Other author names receive a deterministic `sc_author_` alias followed
by 54 hexadecimal characters from their SHA-256 digest. Long names sharing a
prefix therefore do not collapse through simple truncation.

`application/single_app/agent_logging_chat_completion.py` wraps the selected
chat-completion service after its existing model-budget validation. The wrapper
uses the existing service-wrapper pattern and copies history/message author
metadata immediately before each provider request. It covers streaming and
non-streaming invocation, prior conversation messages, and subsequent tool
rounds. It delegates provider settings and function-choice handling to the
original service.

Both ordinary and specialist local-agent construction paths use this shared
agent class. Chat, delegated/orchestrated agent execution, and agent workflows
therefore receive the same behavior rather than a workflow-specific exception.
Hosted Foundry agents do not use this local-agent boundary.

## Identity and safety boundaries

The alias is transport metadata, not a new agent identity or an authorization
decision. This change does not rename saved agents, display labels, IDs,
references, loader keys, or returned response attribution. It leaves caller and
thread histories unchanged by the normalization itself.

Only author names on system, developer, user, and assistant messages are
normalized. Message content, instructions, source evidence, tool/function names,
tool-call IDs, tool-result pairing, and tool-message routing remain intact.
Provider-specific instruction roles, model limits, and content-screening
boundaries continue to use the selected service.

Other provider failures are not swallowed or automatically retried. Potentially
side-effecting failures still require explicit recovery; deterministic budget
refusals keep their existing terminal-failure behavior.

## Using the fix

Existing agents need no name migration or configuration change. Their saved
names and visible labels remain available to users; only outgoing model
metadata differs when necessary.

Previously waiting runs are not rewritten, resumed, cancelled, or replayed.
Inspect the saved run and any external effects before making an authorized
recovery decision. A corrected request does not by itself prove that an
assigned connector succeeds or that a workflow meets its intended result
contract.

## Validation

`functional_tests/test_agent_message_name_compatibility.py` exercises the real
SimpleChat agent, pinned Semantic Kernel, and Azure/OpenAI clients through
in-process HTTP transports with socket/DNS access blocked. Coverage includes:

- Author lengths of 63, 64, 65, and 300 characters; deterministic aliases,
  incompatible characters, and distinct names sharing a long prefix.
- Streaming/non-streaming requests, repeated conversation use, multiple agents,
  and preservation of original history, visible identity, and content.
- Actual automatic tool-invocation rounds with unchanged function names,
  call IDs, and result pairing.
- Personal/group and ordered/structured durable workflows through
  `invoke_workflow_agent`, plus delegated execution and real scoped
  orchestration through `invoke_scoped_agent`.
- Verified model settings and developer-role instructions, unrelated provider
  refusals, source-access denial between tool rounds, and normal/optimized
  bootstrap-free import probes.

Existing context-budget, durable-policy, Microsoft 365 streaming/continuation,
and delegation tests cover the surrounding execution boundaries. Validation
uses offline fixtures; it is not a claim of a successful live provider or
connector run. No deployed workflow or Azure configuration is changed.

### Recorded results

Validation used an isolated Python 3.12 environment with the application's
Semantic Kernel `1.39.4` and OpenAI `1.109.1` pins. With `$python` pointing to
that interpreter, the following targeted run passed **171 tests and 2 subtests**:

```powershell
& $python -m pytest -q -p no:cacheprovider `
    functional_tests\test_agent_message_name_compatibility.py `
    functional_tests\test_workflow_durable_execution.py `
    functional_tests\test_workflow_policy_failures.py `
    functional_tests\test_workflow_context_budget.py `
    functional_tests\test_m365_agent_streaming.py `
    functional_tests\test_m365_agent_continuation.py `
    functional_tests\test_agent_delegation_runtime.py --tb=short
```

The new regression suite also passed **46 tests** under optimized Python:

```powershell
& $python -O -m pytest -q -p no:cacheprovider `
    functional_tests\test_agent_message_name_compatibility.py --tb=short
```

Documentation checks passed **7/7** coverage checks and **6/6** site-quality
checks:

```powershell
& $python .\functional_tests\test_docs_app_surface_coverage.py
& $python .\functional_tests\test_docs_site_quality.py
```

An additional run including the unchanged
`test_agent_delegation_entrypoints.py` encountered nine AST-fixture
`NameError` failures. Running that file with the original agent implementation
from `HEAD` reproduced the same nine failures, with ten tests passing. Those
pre-existing fixture findings were recorded separately; neither the harness nor
those fixtures were changed, and the passing targeted run above excludes that
file. This is not a claim that the entire repository test suite passes.
