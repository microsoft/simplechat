# V2 Sent Prompt Attachment Fix

## Fixed in version: **0.261.096**

The application version is recorded in `application/single_app/config.py`.

## Issue and root cause

A saved prompt could look correct in the V2 composer but become a single large
user-message block after sending or reloading. The user's additional words were
buried inside the instructions.

The frontend already had a prompt-card reader, but the backend only recorded
the necessary selection metadata in non-streaming chat. The V2 streaming path,
orchestration user-message creation, and visible collaborative message creation
did not consistently preserve it. Optimistic orchestration messages also lacked
the prompt snapshot.

Templates using the `composer` built-in exposed another distinction: the user's
text was intentionally not appended twice to model input, but the display layer
also lost the separate copy of those words.

## Technical changes

The request and stored metadata retain an attachment snapshot while message
`content` remains the complete text sent to the model. Actual composer text is
separate from the appended-text composition rule, so embedded input can still
be displayed outside the card.

The chat, orchestration, and collaboration routes share a metadata builder.
Frontend optimistic messages carry the same snapshot as persisted messages.
`readMessagePrompt` reconciles the snapshot with stored content before splitting
the display; an arbitrary prefix match must not remove unrelated user text.

The shared `PromptCard` presentation keeps instructions scrollable and the user's
words outside the card. It does not re-read the saved prompt or resolve historical
variables against the current conversation.

Relevant components are `promptRequest.ts`, `messagePrompt.ts`, `chatStore.ts`,
`orchestrationController.ts`, `Composer.tsx`, `MessageList.tsx`, and the three
backend chat/orchestration/collaboration route modules. The shared backend builder
is `functions_prompt_metadata.build_prompt_selection_metadata`.

## Validation and compatibility

`functional_tests/test_v2_prompt_attachment_persistence.py` executes the six
user-message persistence boundaries with controlled storage. The accompanying
composer functional/TypeScript coverage exercises metadata construction and composition, including
prompt-only turns, appended text, embedded composer input, and legacy/mismatched
metadata. Browser coverage in `ui_tests/test_v2_prompt_composer_experience.py`
exercises the real composer, card rendering, and send workflow.

Before the fix, missing metadata left the renderer no trustworthy way to separate
instructions from the user's question. With the snapshot preserved, sending and
reopening the conversation retain the same named card and separately readable text.

Older messages without sufficient metadata are not guessed at or migrated.
Masked messages keep the existing safe rendering. Copy/export and the complete
model-message body are unchanged.

## Related documentation

- [Prompt composer card]({{ '/explanation/features/PROMPT_COMPOSER_CARD/' | relative_url }})
- [Use prompts in chat]({{ '/guides/use-prompts-in-chat/' | relative_url }})
