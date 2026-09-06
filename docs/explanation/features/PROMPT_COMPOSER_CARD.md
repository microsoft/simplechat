# Prompt Composer Card

Attaching a saved prompt to the message you are writing, rather than pasting it
into the box.

**Implemented in version:** 0.261.092
**Inline answers implemented in version:** 0.261.096
**Current feature version:** 0.261.099 (`application/single_app/config.py`)
**Enhanced in version:** 0.261.096 (`application/single_app/config.py`)
**Interface:** V2 only. The classic interface is unchanged.
**Dependencies:** `enable_user_workspace` for personal prompts,
`enable_group_workspaces` and `enable_public_workspaces` to reach those scopes.

## Overview

Picking a saved prompt used to paste its text into the message box. That answered
one question — what does this prompt say — and lost every other one.

The prompt stopped being a prompt the moment it arrived. It was text like any
other text: nothing marked where the standing instructions ended and your own
question began, there was no way to take it back off without finding and deleting
the right paragraphs, and correcting a variable meant editing prose in the middle
of a message box.

Variables made this worse rather than better. They were filled once, in a modal,
and then flattened into the pasted text. `{{composer}}` — documented as "what you
have already typed" — reliably resolved to nothing, because picking the prompt is
the first thing you do, not the last.

Now the prompt stays a prompt until you send. It sits in a card above the message
box, the box stays yours to type in, and the two are combined only when the
message is actually sent.

## The card

The header shows the prompt's name, available workspace label, and variable
status. Variable fields appear when a prompt is attached; their **Variables**
disclosure is independent of the scrollable preview. Collapsing a long preview
therefore does not hide the inputs needed to use it.

**Edit** turns the prompt text into an editable box and marks the card
**Edited**; **Reset** puts the saved wording back. An edit applies to the one
message and is never written back to the saved prompt, so adjusting the wording
for a particular case does not change it for everyone else using it.

**Remove** takes the prompt off. Nothing you have typed is disturbed, because the
prompt was never in the message box to begin with.

The picker includes **Tip: type / in your message to choose a prompt**, matching
the Documents picker's `#` guidance. The shortcut is forward slash, not backslash.

## Enhanced in version: **0.261.096**

This release makes variables discoverable, adds knowledge-backed filling, and
preserves prompt metadata on streaming, planned, and shared messages. The composer
and sent message use the same card presentation.

## What gets sent

The prompt goes first, then what you typed under it:

```
<the prompt, with its variables filled in>

<your message>
```

That is the order the two are actually written in. The prompt is the standing
instruction; the message underneath is the particular thing being asked.
Reversing them buries the question inside its own instructions.

Either side may be empty. A prompt that needs no further input is a complete
message on its own, so **Send** stays available with an attached prompt and an
empty box.

### The `{{composer}}` exception

A prompt that names `{{composer}}` is positioning your message itself — "summarise
the following: `{{composer}}`". Such a prompt has already consumed what you typed,
so it is not appended underneath as well. Without this it would be sent twice,
once inside the instruction and once after it.

The text typed in the composer is recorded separately for display. It remains
visible outside the sent card even when the template places it inside the
prompt; the model still receives it only once.

## Variables

Variables use the syntax the V2 prompt workbench already parses, unchanged:

- `{{name}}` is a placeholder.
- `{{name|default}}` supplies a default.
- `\{{name}}` escapes one, and anything inside a fenced code block or an inline
  code span is left alone, so a prompt that *documents* a templating language is
  not turned into a form.

Some names resolve on their own and are shown read-only: `today`, `now`, `me`,
`conversation_title`, `selected_documents`, `last_response`, `last_message` and
`composer`.

Because the prompt stays attached until you send, these are resolved against the
message as it is actually being sent rather than as it looked when the prompt was
picked. That is what makes `{{composer}}` work, and it means editing a variable
after typing changes what is sent, not merely what the preview shows.

**Insert variable** is available in both the turn-local editor and the saved-prompt
editor. It explains the built-ins and creates custom fields with optional
defaults at the cursor. An unavailable built-in shows a context hint rather
than an editable field that cannot accept changes. `selected_documents` uses
the names of the documents explicitly selected in the composer.

### Find values in knowledge

**Find in knowledge** fills an unanswered custom field. **Fill missing fields**
looks up the unanswered custom fields together, without replacing populated
fields or defaults. Lookup starts only when requested, never on every keystroke
or automatically when a prompt is selected.

By default, lookup uses the documents, tags, and workspaces selected in the
composer. **Choose knowledge** opens the existing document/context picker.
**Search all accessible knowledge for AI fill** explicitly widens the lookup,
without changing the document selection for the subsequent chat message.

A grounded value is applied immediately and marked **AI-filled**. **Sources**
shows its supporting document excerpts; **Undo** restores the previous value.
Conflicting findings offer choices. A missing result or service error leaves
the field unanswered rather than inventing an answer from general model
knowledge. Editing a field, changing the prompt or sources, cancelling, or
sending prevents late lookup results from overwriting newer work.

The helper uses `POST /api/v2/prompts/fill-variables`, existing document retrieval,
and the configured default model connection, falling back to the existing
planner/default-chat client resolution. It does not use the model or agent
selected for the eventual answer. It does not start a chat turn, create
an orchestration run, invoke an agent's tools, or search the public web.
Chat orchestration does not have to be enabled.
Stored underlying-model metadata determines supported token parameters, so a
friendly deployment alias does not hide a reasoning model's requirements.

Each context chip retains its workspace identity in the request. A tag selected
from one workspace therefore does not include same-name tags elsewhere, and a
whole-workspace chip expands only its own workspace. Current access, file-sharing,
and applicable assigned-knowledge restrictions are still enforced.
Composer and assigned-knowledge predicates are intersected before the search
cutoff; unassigned hits cannot consume the result budget. Workspace unions
accept an ownership or approved-share access path without being blocked by a
pending share in a different selected group.

Known values and defaults help identify the intended subject, such as a company
whose contract date is missing. They are context, not evidence. Returned values
must be spans from supporting source quotes, allowing whitespace/case differences;
this helper does not invent or freely paraphrase a value.

Lookup is bounded. Oversized requests and context that cannot fit the search
budget produce a visible error instead of silently dropping the subject:

| Limit | Value |
| --- | --- |
| Fields per lookup | 12 |
| Request body | 64 KB |
| Prompt / draft text | 20,000 / 8,000 characters |
| Context chips | 128 |
| Retrieval | At most 12 searches, 12 hits each |
| Evidence sent for extraction | At most 18 excerpts / 20 KB |
| Search query, including known subject context | 3,000 characters |
| Model input / output budget | 48 KB / 4,096 tokens |
| Model timeout / retries | 30 seconds / zero retries |

### Sending with unanswered fields

Sending reveals a warning with **Review fields**, **Fill missing fields**, and
**Send anyway**. The last option deliberately retains unresolved placeholders
as literal text; it does not silently remove them. Permission to send unresolved
values applies only to that send. Filling variables never sends the message
automatically.

### Values are remembered in this browser only

The remembered-values cache uses `localStorage`, keyed by prompt *and* variable;
that cache is not synchronized to the server. Submitted values still travel
in the resolved prompt and message metadata, and a requested AI lookup sends
its prompt/draft context to the configured service. "Name" can mean a customer
in one prompt and a product in another, so a cache keyed on the bare name would
offer one back for the other.

Three rules protect against a pre-filled value being sent without being read:

1. Defaults, reused values, built-ins, and AI-filled values are visibly identified.
   Custom values can be cleared; AI fills can also be undone. Built-ins remain
   read-only because they describe the current chat context.
2. Values from the conversation, such as the last assistant reply, are offered as
   chips you click. Nothing takes them on its own: that reply can quote an
   uploaded document, and document text becoming part of your next instruction is
   how prompt injection gets a foothold.
3. Shared conversations do not reuse private remembered values. Defaults and
   current-chat built-ins still work, and the sender may explicitly request AI
   filling. Values included in a sent shared message are visible to participants.

Values are remembered only once the message is on its way, so a prompt you filled
in and then removed leaves nothing behind. AI-filled values are not automatically
added to this cache.

## The sent message

A message sent with a prompt shows a compact, named card above your own words,
expanding to the full text in a bounded scroll area. Your question is the thing
to read; the instructions above it are what you already knew when you sent it.

The prompt stays visible rather than being dropped so the reply can still be
understood by someone who did not pick it — in a shared conversation, that is
everybody else.

Copying or exporting a message still yields the whole thing. The split is a
display choice, not a change to what was stored or sent.

Messages sent before this existed render exactly as they did. So does a message
that has been edited since, or one whose stored content does not begin with the
prompt it claims: the split is only made when the pieces still add up, and is
abandoned rather than guessed at otherwise.

Streaming, orchestration, and collaboration preserve the same snapshot, including
the prompt's turn-local wording and composer text. Reloading does not re-resolve
dates, fetch a changed saved prompt, or flatten the card.

## Orchestration

A saved prompt says what kind of work a request is, so the planner is now given
its wording rather than only its name. "Quarterly review" says nothing about
whether the work involves reading documents, searching the web, or comparing two
things, which is exactly what a plan has to decide.

Two further consequences:

- A selected prompt counts as the user having pointed at something, alongside a
  chosen document or agent, so a request carrying one is never triaged as a
  remark to answer off the cuff.
- The stored plan names the prompt rather than quoting it. The wording is already
  in the message the plan was built from, and plan documents are kept and shown.

The wording sent to the planner is capped at 2000 characters
(`SELECTED_PROMPT_LENGTH` in `functions_orchestration_context.py`). A saved prompt
has no length limit and the planner's budget does; a prompt long enough to be cut
has said what kind of work it is well before that point.

## What the server records

### Prompts in inline clarification answers

An inline follow-up question accepts `/` saved prompts through the same attached card.
Use its variable fields or edit its wording for that answer. `{{composer}}` means the
text in that answer editor, not whatever is waiting in the main composer.

Each answer has its own prompt and variable values, so moving between questions does not
replace another answer or the original request's prompt. Selecting a suggested option and
adding an attached prompt are compatible: the option remains the primary choice, and the
filled prompt travels as supplemental answer context.

On acceptance, `elicitation_context` carries the resolved text and prompt metadata for the
appropriate field. It does not replace the original turn's `prompt_info`. Decline and
Cancel send neither the prompt nor the draft answer. These boundaries are covered by
`functional_tests/test_v2_elicitation_answers.py` and
`ui_tests/test_v2_elicitation_composer.py`.

### Prompts on ordinary messages

`prompt_info` travels with the send request. A shared validator builds the
compatible `metadata.prompt_selection` snapshot on the stored user message:

| Field | What it holds |
| --- | --- |
| `selected_prompt_text` | The prompt as sent, variables filled in |
| `original_prompt_text` | The prompt as saved |
| `prompt_variables` | The values supplied, excluding empty ones |
| `prompt_edited` | Whether the wording was changed for this message |
| `user_text` | The appended tail, empty when the template consumes the composer text |
| `template_content` | The active template, including edits for this turn |
| `composer_text` | The actual words typed in the message box |
| `composer_embedded` | Whether the active template places those words itself |
| `scope_type`, `scope_name` | Available prompt workspace descriptors |

`composer_text` and `composer_embedded` distinguish the display from the model
composition without appending an embedded message twice. The renderer checks
that the snapshot matches stored content before separating the two.

A client that does not send these fields reads back exactly as it always did.

## File structure

| File | Role |
| --- | --- |
| `components/chat/AttachedPromptCard.tsx` | The card |
| `components/prompts/PromptVariableField.tsx` | One variable, shared |
| `lib/usePromptVariableValues.ts` | Values, pre-fill rules and resolution |
| `lib/promptRequest.ts` | Composition and the `prompt_info` contract |
| `lib/messagePrompt.ts` | Splitting a sent message back apart |
| `lib/promptVariables.ts` | The parser, unchanged |
| `lib/promptVariableMemory.ts` | Browser-local remembered values, treating prompt and variable names as data keys |
| `components/chat/PromptCard.tsx` | Shared draft and sent-message presentation |
| `components/prompts/PromptVariablePicker.tsx` | Built-in discovery and custom variable insertion |
| `lib/usePromptKnowledgeFill.ts` | Lookup lifecycle, cancellation, and stale-result protection |
| `lib/promptKnowledge.ts` | Typed knowledge-fill request and response |
| `functions_prompt_variables.py` | Scoped, grounded variable extraction |
| `functions_prompt_metadata.py` | Shared template-key parsing and side-effect-free snapshot validation |

`PromptVariablesDialog.tsx` was retired. Its rules did not go with it: they live
in `usePromptVariableValues.ts` and `PromptVariableField.tsx`, which the card
uses. Two surfaces filling one prompt is how a safety badge ends up on one of them
and not the other.

## Testing

| Test | Covers |
| --- | --- |
| `functional_tests/test_v2_prompt_composer_card.py` | Wiring: attachment, turn-local editing, send gating, both request paths, stored metadata, dialog retirement |
| `functional_tests/test_v2_prompt_composer_card_logic.ts` | Behaviour: composition order, the `{{composer}}` exception, and every `readMessagePrompt` fallback |
| `functional_tests/test_orchestration_prompt_instruction.py` | The planner sees capped wording, triage counts a prompt, plan inputs name it |
| `functional_tests/test_v2_prompts_workbench.py` | The workbench, the slash menu, and the shared pre-fill rules |
| `functional_tests/test_prompt_variable_knowledge_fill.py` | Grounding, authorization, scope, bounded requests, and failure behavior |
| `functional_tests/test_v2_prompt_attachment_persistence.py` | Executed snapshot/persistence coverage across chat, streaming, document actions, orchestration, and collaboration |
| `ui_tests/test_v2_prompt_composer_experience.py` | Real composer, editor, send, and AI-fill browser workflows |

For a task-oriented walkthrough, see [Use prompts in chat]({{ '/guides/use-prompts-in-chat/' | relative_url }}).

## Known limitations

- One prompt per message. Attaching a second replaces the first.
- A masked message is not split. Mask ranges are offsets into the whole content,
  so splitting it would leave them pointing at the wrong characters.
- Plan inputs are carried but not yet rendered, so the prompt a plan was built
  with is recorded rather than displayed on the plan card.
