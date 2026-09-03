# V2 Prompts Workbench

Saved prompts in the V2 interface, rebuilt as a two-pane workbench with a dedicated editor,
`{{variable}}` placeholders, and the ability to create a prompt from a conversation.

**Implemented in version:** 0.261.053
**Applies to:** the V2 React interface (`application/v2_ui`), My Workspace → Prompts, and the
chat composer.
**Dependencies:** `enable_user_workspace`. Group and public prompt routes were extended at the
same time for parity, but their V2 pages do not exist yet.

## The problem this replaces

The V2 prompts section rendered its editor *between the section header and the search box*.
Clicking Edit on a prompt part-way down the list moved the form to the top of the page, out of
view, with nothing tying it to the row that had been clicked — so the first thing anyone did
after pressing Edit was scroll to find the editor.

It was also thinner than the classic interface it replaced. Classic used a modal with a
markdown editor and preview, card and list views, server-side paging, and a "chat with this
prompt" link. V2 had a fixed six-row textarea, a 140-character preview and nothing else, which
meant reading a prompt required entering an editor you then had to cancel out of.

Four further defects were found and fixed alongside it:

- Switching rows with a dirty draft discarded it silently.
- Picking a prompt in the composer called `setText(prompt.content)`, **replacing whatever had
  already been typed**.
- The message menu's "Use as prompt" only copied text into the composer. It saved nothing, and
  there was no way to create a prompt from a conversation at all.
- `fetchPrompts` sent a `search_term` parameter while `list_prompts` reads `search`, so
  server-side prompt search had never once run.

## Architecture

### The workbench

`PromptsSection` is now a wrapper around `PromptWorkbench`, registered with `layout: 'full'` so
it claims the page rather than sitting inside the centred prose container.

| Component | Responsibility |
|---|---|
| `components/prompts/PromptWorkbench.tsx` | Owns the query, selection, loading and every write |
| `components/prompts/PromptList.tsx` | Rows: name, description, favourite, date, variable count |
| `components/prompts/PromptDetailsPane.tsx` | Rendered markdown, variables, and the row's actions |
| `components/prompts/PromptEditorDialog.tsx` | Writing, with source and preview side by side |
| `components/prompts/PromptVariablesDialog.tsx` | Filling placeholders in before insertion |
| `components/prompts/promptPresentation.tsx` | The variable pill, chip and favourite star |
| `components/chat/PromptSlashMenu.tsx` | The composer's `/` search |

Collection rules live in `lib/promptLibrary.ts` rather than in the components, so they can be
executed in a test instead of inferred from a rendered list — the same split the documents
explorer uses.

On a narrow screen the list and the details pane take turns, with a back control in the pane
header. Showing an 80-character-wide list beside a rendered prompt would leave neither readable.

### Two panes did not need two copies of anything

`Modal` moved from `components/documents/DocumentDialogs.tsx` to `components/ui/Modal.tsx`, and
`AdminMarkdown` moved to `components/ui/PlainMarkdown.tsx`. Both original paths re-export, so no
existing call site changed. `PlainMarkdown` does not enable `rehype-raw`, so authored markdown
cannot inject script or event handlers into a preview.

### Variables

Placeholders are written `{{name}}`, optionally `{{name|default}}`, and are derived from the
prompt body — there is no schema change and no separate list to keep in step.

Parsing is deliberately conservative. It works from a mask of the regions markdown says are
literal, so `{{ user.name }}` inside a fenced block or an inline code span is documentation
rather than a field; names must match `[A-Za-z0-9_][A-Za-z0-9_ -]{0,39}`, so
`{{ this is prose, honestly }}` is left alone; and `\{{` escapes a single occurrence. Spaces and
hyphens fold to underscores in the lookup key, so `{{customer name}}` and `{{customer-name}}`
are one field rather than two asking the same question.

A variable with no value and no default is left visible as `{{customer}}` rather than blanked,
because the braces in the middle of a paragraph are what make the omission noticed before the
message is sent.

Eight names are resolved by the application itself: `{{today}}`, `{{now}}`, `{{me}}`,
`{{conversation_title}}`, `{{selected_documents}}`, `{{last_response}}`, `{{last_message}}` and
`{{composer}}`. Dates are formatted from local components — `toISOString` would report the
previous day for anyone west of UTC in the evening, and `toLocaleDateString` could not be
asserted in a test. `resolveBuiltInPromptVariables` takes the current time as an argument, so
the tests are not time-dependent.

### Pre-filling, in tiers

1. **Built-ins** resolve with no input and are shown read-only.
2. **Remembered values** — the last value used for that variable *in that prompt* — are
   pre-filled and badged, with the previous four offered as chips.
3. **Conversation sources** are offered per field as chips: the last reply, your last message,
   and what you have already typed.

An AI "suggest values" tier was considered and deliberately left out.

## Safety properties

These are the reasons the design is shaped the way it is, and each is pinned by a test.

**A wrong pre-fill is worse than a blank one.** An empty field stops you; a plausible wrong
value gets sent. Anything filled in for you is visually distinct and clearable in one click, and
if any variable was auto-filled the dialog always appears rather than inserting silently.

**Prompt injection is contained.** Nothing pulls from message content automatically. The last
assistant reply can be quoting an uploaded document, and document text becoming part of your
next instruction is how prompt injection gets a foothold — so tier 3 stays a chip you click, per
field.

**Shared conversations do not leak.** Auto-fill is suppressed entirely when the conversation is
collaborative. A value remembered from a private chat would otherwise become visible to every
participant the moment the message is sent; it is offered as a chip instead.

**Variable values never reach the server.** People paste customer names, case numbers and API
keys into these. `lib/promptVariableMemory.ts` uses `localStorage` only, references no API
client and claims no user-settings key. It skips persisting anything matching an obvious secret
shape (bearer tokens, `sk-`/`ghp_`/`xox` keys, JWTs, PEM blocks, `api_key:` assignments), caps
values at 2,000 characters, and offers "Forget saved values" per prompt.

**Memory is keyed per prompt.** "Name" means a customer in one prompt and a product in another.
Keys are `(promptId, variable)`, never the bare variable name.

## Chat integration

**Insertion, not replacement.** `insertPromptText` splices at the caret or over the selection,
adding a blank line before a multi-line prompt and a space before a single-line one, and neither
when the neighbouring text already provides whitespace.

**`/` search.** Typing a slash that opens a word offers matching prompts, favourites first. A
slash mid-word does not trigger — `and/or` and `https://` are left alone — a slash followed by a
space is treated as prose rather than a command, and the menu closes by having nothing to show,
which is what makes a query containing spaces safe.

**Save from chat.** A message's overflow menu offers **Save as prompt**, and the composer offers
the same for text you have drafted. Both open the editor prefilled, with a name suggested from
the first meaningful line, so the specifics can be turned into `{{variables}}` before saving.
The old **Use as prompt** entry was renamed **Copy to composer**, which is what it has always
done.

**The catalog stays fresh.** The picker reads a server-built, cached catalog.
`bootstrapStore.upsertPromptInCatalog()` applies the new prompt locally so it is selectable
immediately, and a background `refresh()` replaces that with the server's record.

**Use in chat.** The details pane links to `/chat?prompt=<id>`. The composer captures the id in a
lazy state initialiser during its first render, and `syncedConversationParams` — the single
writer of the chat query string — strips the parameter, so reloading afterwards does not insert
the prompt again. The composer deliberately does not remove it itself: `setSearchParams`
replaces the whole query from the caller's render snapshot, so two writers means the parameter
one deletes is restored by the other in the same commit.

## Server changes

`build_prompt_updates()` in `functions_prompts.py` is now the single validator for
`name`, `content`, `description` and `is_favorite`, used by all three prompt blueprints. They
previously carried three copies of the same checks, which is how a field accepted on a personal
prompt ends up silently dropped on a group one — a difference that reads to a user as a save
that did not work.

`serialize_prompt_summary()` gives creates and updates one response shape, because the client
applies both optimistically to the same list.

Two new stored fields:

| Field | Type | Notes |
|---|---|---|
| `description` | string | Trimmed, capped at 200 characters. `null` clears it. |
| `is_favorite` | boolean | Strictly boolean; `1` and `"yes"` are rejected. |

Both are read defensively everywhere, because prompts created before they existed do not carry
them — and neither does a prompt last saved by the classic interface, which sends only `name`
and `content`. `update_prompt_doc` merges rather than replaces, so a classic save does not wipe
them.

Favourites float to the top of the list **in the client**. `list_prompts` pages with
`ORDER BY c.updated_at DESC OFFSET/LIMIT`, so a second sort key would need a composite index,
and older documents have no `is_favorite` property for such an index to cover.

Prompt search now covers the description as well as the name, guarded with `IS_DEFINED` so
documents predating the field are unaffected.

## Testing

| File | Covers |
|---|---|
| `functional_tests/test_v2_prompts_workbench.py` | Wiring: shared validation across all three blueprints, route guards, response shape, the search-parameter fix, full-bleed registration, the shared-conversation rule, client-only storage, catalog freshness, single URL writer, modal portalling, selection after create, no duplicated UI, no remote assets |
| `functional_tests/test_v2_prompts_workbench_logic.ts` | Behaviour: 63 checks over parsing, substitution, built-in resolution against a fixed clock, memory caps and secret detection, slash queries, insertion, naming, sorting and the chat handoff |

The TypeScript half is bundled with the esbuild Vite already provides and run under node by the
Python test, which skips it when `application/v2_ui/node_modules` is absent.

The Python helpers are executed rather than asserted about: `functions_prompts` imports `config`,
which builds Azure clients at import time, so the module is parsed and only the pure helpers are
run.

## Known limitations

- **Personal workspace only.** `/groups` and `/public` are still placeholder pages in V2. Their
  backend routes accept the new fields so the three cannot drift, but there is no V2 surface for
  them yet.
- **No AI-suggested values.** Deliberately deferred; see the safety notes above.
- **Remembered values do not follow you between browsers.** That is the point of keeping them
  out of the server.
- **The classic prompt interface is unchanged.** It keeps working and will not damage the new
  fields, but it does not show or set them.
