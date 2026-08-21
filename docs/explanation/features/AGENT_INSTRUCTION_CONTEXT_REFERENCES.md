# Agent Instruction Context References

## Overview

Agent instructions are now authored **after** the agent's actions and assigned knowledge have been chosen, and they can reference those selections directly with inline `#action:` and `#knowledge:` tokens.

Previously the agent modal asked for instructions at step 3 — before Actions (step 4) and Assigned Knowledge (step 5). Authors had to describe behaviour for tools and documents they had not selected yet, and the AI **Draft Instructions** helper had no idea what the agent would actually be able to do.

**Version implemented:** `0.250.214`
**Issue:** [#1257](https://github.com/microsoft/simplechat/issues/1257)

### Dependencies

- Bootstrap 5 (modal, collapse, badges)
- SimpleMDE 1.11.2, vendored locally at `static/js/simplemde/simplemde.min.js`
- Existing agent action catalog (`GET /api/user/plugins`, `GET /api/admin/plugins`)
- Existing assigned knowledge catalog (`GET /api/agents/assigned-knowledge/catalog`)

No new browser dependencies are introduced. The autocomplete is a local static ES module; nothing is loaded from a CDN.

## Technical Specifications

### New step order

| Step | Key | Pane |
|---|---|---|
| 1 | `basic` | `#agent-step-1` — Basic Info |
| 2 | `model` | `#agent-step-2` — Model & Connection |
| 3 | `actions` | `#agent-step-3` — Actions |
| 4 | `knowledge` | `#agent-step-4` — Assigned Knowledge |
| 5 | `instructions` | `#agent-step-5` — Instructions |
| 6 | `advanced` | `#agent-step-6` — Advanced |
| 7 | `summary` | `#agent-step-7` — Summary |

`AgentModalStepper` drives navigation from the ordered `AGENT_STEP_KEYS` array rather than hard-coded step numbers. `getStepKey()`, `getStepNumber()`, `getStepElement()`, and `isOnStep()` are the supported accessors, and `showStep()` / `validateCurrentStep()` branch on step keys. Reordering steps in future means reordering `AGENT_STEP_KEYS` and the matching markup — nothing else.

Because Actions and Knowledge now precede Instructions, both data sets are already loaded by the time the autocomplete needs them. Entering the Instructions step additionally loads the knowledge catalog on demand if assigned knowledge is enabled but the catalog has not been fetched yet.

### Token grammar

```
#action:<ActionDisplayName>
#action:<ActionDisplayName>:<capability_key>

#knowledge:doc:<Document Title>
#knowledge:workspace:<Workspace Name>
#knowledge:tag:<tag>
#knowledge:web:<url>
```

A value is wrapped in double quotes when it contains a space, a colon, or a quote character; otherwise it is inserted bare. Any embedded double quote is downgraded to a single quote so the token stays parseable.

| Example | Meaning |
|---|---|
| `#action:Chart` | The Chart action as a whole |
| `#action:"Simple Chat":create_group` | Only the Simple Chat "Create groups" capability |
| `#knowledge:doc:"Employee Handbook.pdf"` | One specific assigned document |
| `#knowledge:workspace:"Personal workspace"` | An assigned source workspace |
| `#knowledge:tag:policy` | An assigned tag limit |
| `#knowledge:web:"https://example.com/a"` | An assigned web source |

Tokens are stored **literally** in the agent's `instructions` field. They stay editable, round-trip unchanged when an existing agent is edited, and are read by the model as an explicit reference.

### File structure

| File | Role |
|---|---|
| `application/single_app/static/js/agent_instruction_mentions.js` | New module: token grammar, trigger parsing, and the autocomplete menu |
| `application/single_app/static/js/agent_modal_stepper.js` | Step-key map, context accessors, reference panel rendering, autocomplete wiring, draft payload |
| `application/single_app/templates/_agent_modal.html` | Reordered steps, reference panel markup, menu styles |
| `application/single_app/route_backend_agents.py` | Draft-instructions prompt context and sanitization |

### Public helpers in `agent_instruction_mentions.js`

| Export | Purpose |
|---|---|
| `AgentInstructionMentions` | Controller; attaches to a textarea or a CodeMirror instance |
| `formatMentionValue(value)` | Applies the quoting rule |
| `buildActionToken(label, capabilityKey)` | Builds an `#action:` token |
| `buildKnowledgeToken(type, value)` | Builds a `#knowledge:` token |
| `locateMentionTrigger(text)` | Linear reverse scan for the `#` under the caret |
| `splitTokenSegments(raw)` | Splits a token body on colons while treating quoted runs as opaque |

### Trigger parsing

`locateMentionTrigger()` performs a single linear reverse scan from the caret over the last 500 characters, looking for a `#` that sits at a word boundary. It stops at a newline, so a reference never spans lines.

This is deliberately **not** a regular expression. An earlier implementation used `(?:[^\s#"]|"[^"#]*"?)*` to describe optional quoted runs; the optional closing quote made each quoted span ambiguous, so ordinary prose containing several quoted phrases backtracked exponentially — 282 characters took roughly 10 seconds *per keystroke*. Since the scan runs on every keystroke, click, and cursor move, it must be linear.

Once the body is located, `splitTokenSegments()` splits it on colons while treating quoted runs as opaque. A body containing unquoted whitespace is only treated as a query when a `action` or `knowledge` namespace has already been typed — document titles and workspace names contain spaces, so `#knowledge:Employee Hand` must keep filtering. Such a space-spanning match is only honoured while it still resolves to at least one item, so ordinary prose typed after a completed token closes the menu. A token that already carries a knowledge type prefix, or an action plus capability, is treated as complete and closes the menu.

Menu events are split by intent: text edits (`input`, `changes`) may open the menu, while caret-only events (`keyup`, `click`, `cursorActivity`) only re-evaluate or close a menu that is already open. Without that split, clicking anywhere after an existing `#…` token would pop the menu open unrequested.

### `AgentModalStepper` context accessors

`getSelectedActionsWithCapabilities()` returns the selected action cards enriched with their **enabled** capabilities:

```js
[
  {
    id, name, display_name, description, type, is_global,
    capabilities: [{ key: 'create_group', label: 'Create groups', description: '...' }]
  }
]
```

Capabilities come from `SIMPLECHAT_CAPABILITY_DEFINITIONS`, `MSGRAPH_CAPABILITY_DEFINITIONS`, and `CHART_CAPABILITY_DEFINITIONS` filtered by the per-agent `additional_settings.action_capabilities` map. Action types without sub-capabilities (OpenAPI, SQL, custom) return an empty array and complete at the action level.

`getAssignedKnowledgeReference()` returns the resolved assigned knowledge:

```js
{
  enabled: true,
  sources: [{ scope, id, name }],
  documents: [{ id, title, file_name, source_name, scope, tags, is_explicit }],
  tags: ['policy'],
  web_sources: [{ url, mode, mode_label }]
}
```

Documents are the *resolved* set — the documents the agent will actually see after workspace, tag, and explicit-document limits are applied.

Both accessors return empty results for Foundry agent types.

### `POST /api/agents/draft-instructions`

Two optional fields were added to the request body:

```jsonc
{
  "agent_scope": "personal",
  "display_name": "HR Assistant",
  "description": "...",
  "brief": "...",
  "existing_instructions": "...",

  "selected_actions": [
    { "display_name": "Simple Chat", "type": "simplechat", "description": "...",
      "capabilities": [{ "key": "create_group", "label": "Create groups" }] }
  ],
  "assigned_knowledge": {
    "enabled": true,
    "sources": [{ "scope": "personal", "id": "personal", "name": "Personal workspace" }],
    "documents": [{ "title": "Employee Handbook.pdf", "source_name": "Personal workspace" }],
    "tags": ["policy"],
    "web_sources": [{ "url": "https://example.com/a", "mode_label": "Review URL" }]
  }
}
```

Both fields are optional; omitting them preserves the previous behaviour.

`_build_agent_instruction_messages()` accepts them as keyword-only arguments and renders them through `_format_agent_instruction_actions_context()` and `_format_agent_instruction_knowledge_context()`. The system prompt documents the token grammar and instructs the model to reference only listed items and to never invent a token.

#### Sanitization limits

| Constant | Value | Applies to |
|---|---|---|
| `AGENT_INSTRUCTION_CONTEXT_ITEM_LIMIT` | 40 | Actions, sources, documents, tags, and web sources per list |
| `AGENT_INSTRUCTION_CONTEXT_CAPABILITY_LIMIT` | 30 | Capabilities per action |
| `AGENT_INSTRUCTION_CONTEXT_LABEL_LIMIT` | 200 | Names, titles, tags, URLs, capability keys |
| `AGENT_INSTRUCTION_CONTEXT_DESCRIPTION_LIMIT` | 400 | Descriptions and detail suffixes |
| `AGENT_INSTRUCTION_CONTEXT_TOTAL_LIMIT` | 8000 | Combined size of both rendered context blocks |

Every value passes through `_normalize_agent_instruction_draft_input()`, which collapses whitespace (neutralizing newline-based prompt injection in labels) and truncates.

Per-item caps bound each entry but not how many entries arrive, so `_apply_agent_instruction_context_budget()` additionally enforces a shared total. Each block is guaranteed half the budget and any headroom the other block does not need rolls over, so a long action list can never starve the knowledge list. Truncation appends `- (additional items omitted)` so the model knows the list was cut.

## Usage Instructions

### Authoring instructions

1. Open the agent modal and complete Basic Info and Model & Connection.
2. Select the actions the agent needs, and configure their capabilities where the action supports them.
3. Configure assigned knowledge — source workspaces, specific documents, tag limits, and web sources.
4. On the Instructions step, expand **Selected Actions & Knowledge** to review exactly what the agent will have, including each item's reference token.
5. Write instructions. Type `#` wherever you want to name something concrete:
   - `#` → choose `action` or `knowledge`
   - `#action:` → the actions selected in step 3
   - `#action:<Action>:` → that action's enabled capabilities
   - `#knowledge:` → assigned documents, workspaces, tags, and web sources with type badges
6. Navigate with the arrow keys or the mouse, insert with `Tab` or `Enter`, dismiss with `Esc`.

### Using the AI draft

Fill in the **Instruction Brief** describing what you want the agent to do, then choose **Draft Instructions**. The draft is generated with full knowledge of the actions, capabilities, and documents you selected, and uses the token convention where it is helpful. Edit the result before saving.

### Example

```markdown
You are the HR Assistant for the People Operations team.

## Answering policy questions
Search #knowledge:doc:"Employee Handbook.pdf" first. If the handbook does not
answer the question, fall back to #knowledge:workspace:"Personal workspace" and
limit results with #knowledge:tag:policy.

## Onboarding a new hire
Use #action:"Simple Chat":create_group to create the onboarding workspace, then
#action:"Simple Chat":add_group_member to add the hire and their manager. Never
use #action:"Simple Chat":make_group_inactive unless the requester explicitly
asks to archive a workspace.
```

## Testing and Validation

### Functional tests

| Test | Coverage |
|---|---|
| `functional_tests/test_agent_modal_instructions_step_order.py` | Step indicator order, `#agent-step-N` id assignment, `AGENT_STEP_KEYS` map, absence of the old magic step numbers |
| `functional_tests/test_agent_instruction_mention_tokens.py` | Token grammar and quoting rule, trigger parsing including the spaced-query fallback, linear-scan performance, completed-token handling, cleanup and open-gating, item building and filtering, local-asset and XSS-safe rendering rules |
| `functional_tests/test_agent_draft_instructions_context.py` | Prompt context rendering, per-item and total sanitization caps, token guidance in the system prompt, backward compatibility when the new fields are omitted |
| `ui_tests/test_agent_modal_instruction_references.py` | Browser workflow: step order, reference panel, keyboard and mouse `#` autocomplete in the brief and the markdown editor, and Foundry inertness |

Run them individually:

```powershell
cd functional_tests
python test_agent_modal_instructions_step_order.py
python test_agent_instruction_mention_tokens.py
python test_agent_draft_instructions_context.py
```

No new Flask routes are added, so `functional_tests/route_tests/` is unchanged.

The UI test skips unless `SIMPLECHAT_UI_BASE_URL` and `SIMPLECHAT_UI_STORAGE_STATE` are set:

```powershell
cd ui_tests
pytest test_agent_modal_instruction_references.py
```

### Known limitations

- **Stale tokens are not flagged.** If an action or document is deselected after a token was inserted, the token stays in the instructions. This is deliberate — the author stays in control — but there is no validation or highlighting for it yet.
- **Foundry agent types are excluded.** Classic Foundry, New Foundry, and Foundry Workflow agents manage their instructions and tools in Foundry, so the reference panel, the autocomplete, and the draft button stay inert for them.
- **Colons in unquoted queries close the menu.** A manually typed query containing a colon is treated as a completed token. Selecting the item from the list instead produces a correctly quoted token.
- **Action-level capabilities are limited to Simple Chat, Microsoft Graph, and Chart.** OpenAPI, SQL, and custom actions expose no sub-capability list in the modal, so they complete at the action level.

## Cross-References

- Release notes: `docs/explanation/release_notes.md` (v0.250.214)
- Assigned knowledge catalog: `application/single_app/functions_assigned_knowledge.py`
- Agent modal stepper: `application/single_app/static/js/agent_modal_stepper.js`
