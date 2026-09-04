# Prompt Composer Card

Attaching a saved prompt to the message you are writing, rather than pasting it
into the box.

**Implemented in version:** 0.261.092
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

Collapsed, the card is one line: the prompt's name, the workspace it came from,
and how many of its variables still need a value. That last part is what is worth
knowing at a glance — an unfilled placeholder is the thing that would otherwise
reach the model as a literal `{{customer}}`.

Expanded, it shows a field for each variable and the prompt exactly as it will be
sent. **Edit** turns the prompt text into an editable box and marks the card
**Edited**; **Reset** puts the saved wording back. An edit applies to the one
message and is never written back to the saved prompt, so adjusting the wording
for a particular case does not change it for everyone else using it.

**Remove** takes the prompt off. Nothing you have typed is disturbed, because the
prompt was never in the message box to begin with.

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

### Values are remembered in this browser only

Values you supply are stored in `localStorage`, keyed by prompt *and* variable, and
are never sent to the server. "Name" means a customer in one prompt and a product
in another, and a store keyed on the bare name would offer one back for the other.

Three rules protect against a pre-filled value being sent without being read:

1. Anything filled in for you is badged — **Reused** or **From this chat** — and
   clearable in one click, so it never reads as something you typed.
2. Values from the conversation, such as the last assistant reply, are offered as
   chips you click. Nothing takes them on its own: that reply can quote an
   uploaded document, and document text becoming part of your next instruction is
   how prompt injection gets a foothold.
3. In a shared conversation nothing is pre-filled at all, because a value
   remembered from a private chat would become visible to every participant the
   moment the message is sent.

Values are remembered only once the message is on its way, so a prompt you filled
in and then removed leaves nothing behind.

## The sent message

A message sent with a prompt shows the prompt as a collapsed **Prompt: <name>**
row above your own words, expanding to the full text. Your question is the thing
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

`prompt_selection` on the user message keeps its original four fields and gains
four more:

| Field | What it holds |
| --- | --- |
| `selected_prompt_text` | The prompt as sent, variables filled in |
| `original_prompt_text` | The prompt as saved |
| `prompt_variables` | The values supplied, excluding empty ones |
| `prompt_edited` | Whether the wording was changed for this message |
| `user_text` | What was typed under the prompt |

`user_text` is what allows a sent message to be drawn as a prompt plus your own
words: the stored content is the two concatenated, and nothing else can tell them
apart.

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
| `lib/promptVariableMemory.ts` | Remembered values, unchanged |

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

## Known limitations

- One prompt per message. Attaching a second replaces the first.
- A masked message is not split. Mask ranges are offsets into the whole content,
  so splitting it would leave them pointing at the wrong characters.
- Plan inputs are carried but not yet rendered, so the prompt a plan was built
  with is recorded rather than displayed on the plan card.
