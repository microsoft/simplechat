---
layout: page
title: "User input"
description: "Request necessary user answers from an interactive V2 local-agent task."
section: "Reference"
audience: user
version: "0.261.411"
---

<!-- action-slug: user-input -->

## What this tool does

`UserInput.request_user_input` lets a local agent request missing facts and stop
at a retained tool boundary. It is an interactive input tool, not an integration
that reads external data or performs an approved operation.

Fixed/Implemented in version: **0.261.411**
(`application/single_app/config.py`).

## Availability

SimpleChat supplies the tool to request-owned local-agent kernels for V2
interactive chat and eligible interactive orchestration steps. It is not a new
administrator toggle, separately assigned workspace action, or scheduled workflow
input mechanism. Classic chat and Foundry-backed agents do not receive it.

The selected local model must support tool calling. Existing local-agent access
and capability settings still apply. The UI
capability marker does not authorize an actor, conversation, document, or action.

## Question contract

The `specification` argument is a JSON object with a short `message`,
`requested_schema`, and optional `ui_hints`. The schema is a flat object of
primitive fields or primitive arrays. Single-select enums are exhaustive;
string/string-array fields may instead have open suggestions in
`ui_hints.fields` with `input: "choices"` and `allow_custom: true`.

The server supplies all actor, conversation, and execution identities.
Tool arguments do not include a user ID, scope ID, or continuation ID.
Accepted results contain the validated response and separately validated
answer context. Decline/cancel do not forward drafts.

## Safe continuation

The checkpoint preserves actual SK tool results. Continuation resolves the
paused question call and retains completed calls; it does not retry the original
chat request. Changed permissions or an uncertain checkpoint stop continuation.
An answer does not replace credential, consent, or outgoing-action approval.

See [Answer an agent's follow-up questions]({{ '/guides/answer-agent-questions/' | relative_url }})
for the user workflow and [Guided user input]({{ '/explanation/features/GUIDED_USER_INPUT/' | relative_url }})
for implementation details.
