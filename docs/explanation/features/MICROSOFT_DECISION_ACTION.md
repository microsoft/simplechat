# Microsoft Decision-1 Action

## Overview

SimpleChat version **0.261.062** adds Microsoft Decision-1 as a governed Semantic
Kernel action. It is available for global, group, and personal action scopes and
uses the existing action persistence, identity, Key Vault, loader, health-check,
and connection-test seams.

**Implemented in version: 0.261.062** in
`application/single_app/config.py`.

## Purpose and behavior

Decision-1 is deliberately an action rather than a chat-model option. It offers
three typed functions:

- `check_condition` evaluates a binary `noul` condition.
- `choose_option` selects from a bounded JSON object of option criteria.
- `score_state` evaluates state against bounded ordered score levels.

Each function returns the provider answer, any available probability, usage
metadata, and `requires_review` when confidence is below the configured
threshold. The action does not manufacture a written provider rationale.

## Endpoint and authentication

The action supports a Foundry resource URL, which appends the official Decision
API path, or an exact endpoint for APIM/custom routes. The exact mode preserves
literal APIM revision path components.

API-key authentication defaults to the Foundry `api-key` header and permits a
per-action header override for an APIM subscription key. Managed identity uses
the Azure Cognitive Services scope and is restricted to trusted Azure Foundry
and Azure API Management hostnames. This keeps workload tokens away from
arbitrary custom domains.

## Governance and safety

The action follows normal global, group, and personal action authorization.
Reusable identities are limited to API-key and managed-identity identity types.
Connection tests submit one bounded binary probe and return normalized,
browser-safe errors. Provider error bodies, keys, and identity tokens are not
returned to the browser or written to telemetry.

## Validation

Regression coverage in
`functional_tests/test_microsoft_decision_action_plugin.py` verifies endpoint
construction, APIM revision preservation, managed-identity host restrictions,
typed request construction, confidence handling, and safe provider failures.

The UI validates endpoint mode, deployment name, API-key header syntax, and
bounded timeout/confidence settings before a configuration is saved.
