# Model Personas

## Overview

Model personas let an AI Connections editor attach supplemental behavioral
instructions to an exact chat model without creating an agent.

A persona is stored on the connection's model record. For eligible direct
text-generation requests, SimpleChat adds the persona as a supplemental system
message without changing saved conversation history.

- Implemented in version: **0.261.461**
- Tracking issue:
  [microsoft/simplechat#1929](https://github.com/microsoft/simplechat/issues/1929)
- No dependency or database migration is required.

## Architecture

Persona configuration uses three fields on a model:

```json
{
  "persona_enabled": false,
  "persona_markdown": "",
  "persona_text_visible": true
}
```

The backend validates, preserves, and authorizes these fields with the existing
AI Connections model record. Runtime clients resolve persona content from the
server-side scope, connection ID, and model ID; browser requests cannot inject
persona instructions.

At dispatch, a request-owned message list receives one dedicated system
message. The original conversation and agent records are not modified.

The persona uses an exact-identity cache snapshot. New requests see the latest
committed configuration, while in-flight requests retain their starting state.

## Configuration

Open the AI Connections editor for a global, personal, or authorized group
connection, then select a chat-capable model.

Each eligible model provides:

- **Enable persona** — turns runtime injection on or off.
- **Persona Markdown** — basic Markdown guidance, limited to 8,000 Unicode
  characters.
- **Preview** — sanitizes the authored Markdown without raw HTML, embedded
  media, prompt variables, or diagrams.
- **Show persona text to users** — controls whether ordinary users can read the
  text. It defaults to on.

The model row stays compact while the persona is disabled: only the enable
control is shown. Enabling it reveals the Markdown editor, preview, counter, and
visibility setting without clearing the authored draft.

Chat model pickers show a small person icon beside a model with an active
persona. Hover or focus reports that a persona is enabled and, when visibility
allows, provides a short text preview. Clicking or tapping the icon opens the
full safe Markdown in a compact panel without changing the selected model.
Models with hidden persona text show the enabled state without exposing the
authored content.

Disabling the persona retains the authored draft. Saving disabled with an empty
text field clears it. Whitespace-only content is accepted for editing but is
ignored at runtime.

Persona controls are not available for embedding-only or image-only models.

## User Workflow

1. Open or create an AI connection.
2. Locate the chat-capable model.
3. Enable **Model persona**. The additional controls expand in place.
4. Enter and preview the Markdown instructions.
5. Choose whether ordinary users may read the persona text.
6. Save the connection.

Model selectors continue to show all users that the model has an active persona.
When persona text is visible, the selector can also display the authored text.

## Runtime Boundaries

Model personas apply to exact AI Connection model references used by:

- Direct and streaming chat
- Direct workflows and orchestration calls
- Conversation and export summaries
- Metadata, vision-to-text, tabular, prompt-variable, memory, screening, and
  similar direct text-generation tasks
- Retries, fallbacks, and tool-continuation rounds

Agents do not use model personas. Local, delegated, and hosted agents continue
to use agent instructions. Agent-backed workflows are agent calls for this
purpose.

Direct embedding and image-generation operations do not receive a persona. A
chat model's text-generation step that plans or coordinates an image request
may receive it, but the image operation itself remains unchanged.

Hosted Foundry agents/applications/workflows and unbound legacy calls are not
part of model persona scope. Similar deployment names are never used to infer
persona identity.

## Context and Failure Behavior

Persona tokens participate in the existing request budget. If the persona
causes a context overflow, SimpleChat summarizes earlier conversation content
instead of silently dropping or truncating the persona. A request that still
does not fit returns the existing safe context-overflow response.

Invalid types, oversized persona text, aggregate settings-size overflow,
conflicts, and provider failures are rejected visibly. Draft text remains in
the editor for correction or retry.

## Security

- Persona text is resolved server-side.
- Existing global, personal, and group authorization remains authoritative.
- Hidden persona text is removed from ordinary read projections.
- Persona text is redacted from logs, errors, diagnostics, and telemetry.
- Client-supplied persona fields on chat requests are not trusted.
- Persona instructions cannot grant permissions or bypass authorization.
- Markdown preview sanitization prevents script, event-handler, unsafe URL, and
  embedded-media execution.

Persona text is behavioral configuration, not a secret vault. A model can still
repeat its instructions in generated output.

## Testing and Validation

Focused coverage verifies:

- Unicode length and aggregate-size boundaries
- Stable-ID merge and older-editor preservation
- Global, personal, and group authorization and visibility
- V2 and classic save/preview behavior
- XSS-safe Markdown
- Exactly-once injection for synchronous, asynchronous, Responses, Anthropic,
  streaming, retry, and tool-round paths
- Agent, embedding, and direct image exclusions
- Context-budget accounting and non-mutation of conversation history
- Cache freshness and rollback behavior

Live provider and staging acceptance remain separate deployment gates.

## Limitations

- Personas can influence summaries, screening, extraction, and structured
  generation. Use a separate persona-free model for an operational task where
  that influence is undesirable.
- Prompt ordering does not override provider behavior or application policy.
- Full persona text that is visible to users is delivered to their browser.
- An active persona increases token use and may lead to earlier conversation
  summarization.
