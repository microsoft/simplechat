# Chat Orchestration Evaluation And Quality Gates

Implemented in version: **0.250.068**

Associated issue: **[#1021](https://github.com/microsoft/simplechat/issues/1021)**

## Overview

Phase 9 proves the chat orchestration contracts completed through Phases 8A
and 8B with deterministic scenarios, privacy-safe aggregate observability,
repaired stale tests, and repeatable automated and controlled live-smoke gates.

This phase validates existing behavior. It does not add output types,
generalized multi-agent execution, Foundry or action-attached agent discovery,
consequential or write approval, durable in-flight execution, or complex
workflow behavior. Those remain Phase 10 or later work.

## Dependencies

- Python 3.12 and the repository-local `.venv`.
- Existing turn plan, evidence ledger, collector, executor-evidence, runtime,
  central synthesis, image approval, and governed capability-choice contracts.
- Playwright only for an explicitly requested deployed-environment live smoke.
- Authenticated browser storage state or a CI access token for live smoke.
- Controlled fixture conversations, documents, selected images, agents, and
  generated-output source messages described by the live manifest.

## Automated Gate

From the repository root on Windows:

```powershell
.\.venv\Scripts\python.exe scripts\run_phase9_orchestration_quality_gates.py
```

On Linux or macOS:

```bash
./.venv/bin/python scripts/run_phase9_orchestration_quality_gates.py
```

The runner:

1. Selects the repository-local Python interpreter when available.
2. Sets `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` so unrelated globally installed
   pytest plugins cannot change collection or execution.
3. Compiles the Phase 9 evaluation module, orchestration runtime, and chat route.
4. Runs the Phase 1-9 orchestration, evidence, synthesis, choice, governed-agent,
   image approval, route-policy, UI-contract, and stale-gate regression suites.
5. Leaves cloud, model, search, agent, and image-generation calls disabled.

Useful options:

```powershell
# List every compile and pytest target.
.\.venv\Scripts\python.exe scripts\run_phase9_orchestration_quality_gates.py --list

# Retain CI-readable evidence.
.\.venv\Scripts\python.exe scripts\run_phase9_orchestration_quality_gates.py `
    --junit-xml artifacts\phase9_orchestration_quality_gates.xml
```

## Golden Scenarios

`functional_tests/test_phase9_orchestration_golden_scenarios.py` uses only
deterministic fixtures and existing production helpers.

| Scenario | Required proof |
|---|---|
| M365 work-life image | Selected image and governed profile evidence reach one image-proposal finalizer; collaborators without verified photos remain generic. |
| SQL dashboard illustration | Actual query metrics enter the ledger and unsupported metrics are absent from central synthesis. |
| Public profile not found | Missing Web evidence remains explicit, unverified profile claims are omitted, and the selected headshot remains usable. |
| Selected image Q&A | The selected image is evidence for a normal response; no image proposal profile is introduced. |
| Current Fairfax rules | One Deep Research/Web Search choice is produced; approval, decline, unavailable state, and address-minimized query behavior remain distinct. |
| Governed agent recommendation | Approval produces a required `discovery_approved` evidence source and one response finalizer without canonical agent metadata. |

The automated gate also retains dedicated required-source failure, optional
partial continuation, cancellation, retry, process-restart, duplicate decision,
duplicate resume, group/policy revocation, inherited-tool suppression, central
finalization, and output-lineage suites.

## Evaluation Events

`functions_orchestration_evaluation.py` owns fixed event builders for:

- `orchestration_run_completed`
- `orchestration_recommendation_created`
- `orchestration_recommendation_decided`
- `orchestration_recommendation_outcome`

The events provide:

- Hashed run correlation values.
- Direct or coordinated mode and allowlisted task profile.
- Aggregate required/succeeded/partial/failed/skipped/blocked/cancelled source
  counts.
- Finalizer and run status.
- Recommendation reason codes and a built-in capability or
  `governed_agent` class.
- Decision, run, and post-decision incremental latency in milliseconds.
- Citation count, citation yield per successful/partial source, missing evidence,
  unsupported fact, and replan counts.

The builders never copy prompts, evidence text, response text, canonical agent
or object IDs, display labels, private scope details, catalog counts, secrets,
endpoints, connector settings, hidden tools, action names, or action arguments.
Unknown reason codes and capability classes are dropped or bucketed instead of
being logged as arbitrary text.

## Controlled Live Smoke

Live smoke is opt-in and may call billable model, search, agent, or image
resources. Use only a controlled environment and fixture data.

Required environment variables:

- `SIMPLECHAT_UI_BASE_URL`: deployed SimpleChat origin.
- `SIMPLECHAT_PHASE9_LIVE_MANIFEST`: local JSON manifest path.
- `SIMPLECHAT_UI_ACCESS_TOKEN`, `SIMPLECHAT_UI_STORAGE_STATE`, or
  `SIMPLECHAT_UI_ADMIN_STORAGE_STATE`: authenticated state.

Optional environment variable:

- `SIMPLECHAT_PHASE9_LIVE_RESULT_PATH`: aggregate JSON result path. It defaults
  to `artifacts/phase9_orchestration_live_smoke.json`.

Run the automated gate and require live evidence with:

```powershell
.\.venv\Scripts\python.exe scripts\run_phase9_orchestration_quality_gates.py `
    --live-smoke `
    --junit-xml artifacts\phase9_orchestration_live_smoke.xml
```

The manifest must contain exactly one entry for each required scenario name:

- `selected_image_qa`
- `selected_image_reference_generation`
- `grounded_image_with_selected_agent`
- `web_and_selected_image`
- `generated_file_metadata`

Each endpoint must be a same-origin path. Keep the manifest local because its
request objects can contain controlled fixture identifiers. The result artifact
never copies those request objects.

```json
{
  "version": 1,
  "scenarios": [
    {
      "name": "selected_image_qa",
      "endpoint": "/api/chat/stream",
      "request": {
        "message": "What is this image about?",
        "conversation_id": "fixture-conversation-id",
        "selected_document_ids": ["fixture-image-document-id"]
      },
      "expect": {
        "response_type": "sse",
        "status_code": 200,
        "task_profile": "grounded_answer",
        "finalizer": "response",
        "image_proposal": false,
        "allowed_run_statuses": ["succeeded", "partial"]
      },
      "cleanup_conversation": false
    },
    {
      "name": "selected_image_reference_generation",
      "endpoint": "/api/chat/stream",
      "request": {
        "message": "Create a reference image grounded in the selected image.",
        "conversation_id": "fixture-conversation-id",
        "selected_document_ids": ["fixture-image-document-id"],
        "image_generation": true
      },
      "expect": {
        "response_type": "sse",
        "task_profile": "grounded_image_generation",
        "finalizer": "image_proposal",
        "image_proposal": true
      }
    },
    {
      "name": "grounded_image_with_selected_agent",
      "endpoint": "/api/chat/stream",
      "request": {
        "message": "Create an image grounded in the selected agent evidence.",
        "conversation_id": "fixture-conversation-id",
        "agent_info": {"id": "fixture-authorized-agent-id"},
        "image_generation": true
      },
      "expect": {
        "response_type": "sse",
        "task_profile": "grounded_image_generation",
        "image_proposal": true
      }
    },
    {
      "name": "web_and_selected_image",
      "endpoint": "/api/chat/stream",
      "request": {
        "message": "Create a current visual grounded in public sources and the selected image.",
        "conversation_id": "fixture-conversation-id",
        "selected_document_ids": ["fixture-image-document-id"],
        "web_search_enabled": true,
        "image_generation": true
      },
      "expect": {
        "response_type": "sse",
        "task_profile": "grounded_image_generation",
        "minimum_citation_count": 1,
        "image_proposal": true
      }
    },
    {
      "name": "generated_file_metadata",
      "endpoint": "/api/chat/image-proposals/generate",
      "request": {
        "conversation_id": "fixture-conversation-id",
        "assistant_message_id": "fixture-source-assistant-id",
        "proposal": {
          "prompt": "Create the approved controlled-test image.",
          "evidenceIds": ["fixture-ledger-fact-id"],
          "referenceImageIds": ["fixture-image-artifact-id"]
        }
      },
      "expect": {
        "response_type": "json",
        "status_code": 200,
        "required_paths": [
          "image_message.metadata.image_proposal.source_assistant_message_id"
        ]
      }
    }
  ]
}
```

Adjust request fields to the controlled environment's current chat payload and
fixture records. The gate validates response status, required dotted paths,
exact primitive values, task profile, finalizer, image-proposal presence,
minimum citation count, allowed runtime states, and forbidden substrings.

## Live Result Contract

The live result artifact contains only:

- Schema version and start/completion timestamps.
- A one-way environment host correlation hash.
- Total, passed, and failed scenario counts.
- Scenario name, pass/fail state, HTTP status, bounded latency, task profile,
  run status, citation count, aggregate source-status counts, and whether an
  image proposal was present.

It excludes the base URL, access token, storage state, request bodies, prompts,
conversation/message/document/agent IDs, evidence, citations, generated content,
and exception text.

## Known Limitations

- Live fixtures and authentication remain environment-owned and are not stored
  in the repository.
- The generic manifest performs one request per scenario. Multi-request setup or
  approval chains must use seeded source messages or separate controlled setup.
- The smoke gate proves the configured environment and fixtures, not every cloud
  provider or tenant policy combination.
- Phase 10 output expansion and complex workflows are intentionally absent.