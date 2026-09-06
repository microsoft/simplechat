---
layout: page
title: "Use prompts in chat"
description: "Keep reusable instructions separate from your question and fill their variables from knowledge."
section: "Guides"
audience: user
version: "0.261.096"
---

## What this does

A V2 prompt is an attachment to the message you are writing, not a wall of text
pasted into your question. Its fields help adapt reusable instructions to a
particular customer, document, or task.

The variable picker, knowledge fill, and persistent sent-message card were
implemented in version **0.261.096**, recorded in
`application/single_app/config.py`. The classic chat interface is unchanged.

## Choose a prompt and keep your question separate

1. In the V2 composer, type `/` and choose a saved prompt, or use the **Prompt** picker.
2. Complete the fields shown under **Variables**. Expand the prompt header to read
   its resolved preview; long instructions scroll inside the card.
3. Write the specifics of your request in the normal message box below the card.
4. Send. The conversation keeps the prompt in its own expandable card and shows
   your words separately.

**Edit** changes the prompt for this message only; **Reset** restores its saved
wording. **Remove** removes the attachment without deleting your message.

## Create useful variables

In either the saved-prompt editor or the attached prompt's editor, select
**Insert variable**. Give a custom field a clear name, such as `audience`, and
optionally provide a default. Built-ins include the date, your display name,
selected document names, and text from the current conversation.

For example, this prompt asks for an audience and defaults the tone to concise:

{% raw %}
```text
Summarize the selected documents for {{audience}}.
Use a {{tone|concise}} tone and list unresolved questions.
```
{% endraw %}

One field fills every occurrence of the same variable. Built-ins describe the
current chat and are read-only. If one is unavailable, add the relevant context,
give it a template default, or remove it instead of trying to type into it.

## Find values in knowledge

Use this when a field asks for a fact held in your workspace documents, such as a
customer name or agreement date.

1. Choose relevant documents, tags, or workspaces through **Choose knowledge**.
   Processed content and access to those sources are needed for retrieval.
2. Select **Find in knowledge** beside an unanswered field, or **Fill missing fields**
   to complete the unanswered custom fields together.
3. Review the values marked **AI-filled**. **Sources** shows their supporting
   document excerpts, and **Undo** restores the previous field value.

Lookup does not replace existing answers or defaults. A missing result stays
unanswered; conflicting evidence offers choices. If the selected sources are
insufficient, explicitly select **Search all accessible knowledge for AI fill**.
This widens only the lookup, not the document selection for the message itself.

Filled values are extracted from source quotes, not guesses or free-form
summaries. Existing answers help identify the correct subject. A batch can
contain up to 12 missing fields; large prompts or context receive a visible
size-limit message rather than a partially interpreted request.

Lookup starts only on your request and never sends the chat message automatically.
Changing the prompt or sources, editing a field, cancelling, or sending prevents
late results from overwriting newer work.

## Understand the send warning

If fields are still unanswered, Send offers **Review fields**, **Fill missing fields**,
or **Send anyway**. Sending anyway keeps unresolved placeholders as literal text;
it does not invent an answer or silently remove part of the instructions.

The override applies only to that send. A later message can warn again.

## Privacy and limitations

AI filling uses the configured search/model services and current access rules,
not a public web search or an agent's tools. A requested lookup sends relevant
prompt/draft context and retrieved evidence to the configured model.

Private remembered values are not reused in shared conversations. Values you
send in a shared prompt become visible to its participants. AI-filled values
are not automatically added to the browser's remembered-values cache.

Older messages without usable prompt metadata remain plain text. Copy and
export still contain the complete message, including its prompt. Masked messages
retain the existing safe rendering rather than exposing text through a separate
prompt preview.

## Related

- [Prompt composer card]({{ '/explanation/features/PROMPT_COMPOSER_CARD/' | relative_url }})
- [V2 prompts workbench]({{ '/explanation/features/V2_PROMPTS_WORKBENCH/' | relative_url }})
- [Chat controls]({{ '/reference/chat-controls/' | relative_url }})
