# V2 Chat Picker Search (0.261.395)

## Overview

Large catalogs should not force users to scroll through every model, agent, or
saved prompt before writing a message. The V2 chat pickers include an
always-visible search field styled like the compact Documents search retained
in restricted and inline editors. The main composer's Documents panel uses the
[workspace-sidebar picker](CHAT_CONTEXT_PICKER.md#the-documents-picker).

Implemented in version: **0.261.395**, recorded in
`application/single_app/config.py`.

The change uses the existing React, TypeScript, Lucide, and V2 theme dependencies.
It requires no new package, administrator setting, or cloud resource.

## Technical specifications

### Architecture and data boundaries

The chat bootstrap already supplies the caller's authorized models, agents, and
prompts. Search filters these loaded lists in the browser; typing does not send
another lookup request or write an account preference.

`Dropdown` opts into search through `searchPlaceholder`. Non-searchable callers,
including reasoning and approval mode, retain their previous behavior.
`DropdownOption.searchText` allows a picker to provide additional public metadata
without changing its display label or selection value.

The existing `GET /api/v2/bootstrap` response includes each model's safe profile
summary. That summary now includes `profile.publisher` through the same explicit
allowlist as the other summary fields. It does not expose full profiles, raw
settings, credentials, or endpoint configuration. There is no new API route.
The shared projection remains compatible with classic consumers.

| Search surface | Fields used |
| --- | --- |
| Model and orchestration model | Display name, underlying model/deployment/request names, profile model name, and available publisher/provider labels. |
| Agent | Display name, description, and displayed scope label. |
| Prompt | Name, description, and displayed scope label. Full prompt bodies are not indexed. |

Matching is a case-insensitive substring comparison after trimming surrounding
whitespace. Results retain catalog order and scope grouping. A blank query
restores all loaded options, without a new result limit or fuzzy ranking.

### Selection and interaction

Each opening begins with an empty query and focuses the search field. Search
remains above the scrollable results, and clear-selection controls and the prompt
shortcut hint remain available. No matching entries produces **Nothing matches
that.**; an empty catalog remains **Nothing available**.

Filtering cannot change a selected value, its toolbar label, or a remembered
model choice, even when the selected row is filtered out. A result must be
activated before selection changes. Ordinary and orchestration model preferences
remain separate, and orchestration's Auto option participates in text filtering
without changing how Auto routes requests.

Native text editing, including Home and End, works inside search. Arrow keys
move into visible results; Enter on a result chooses it, while Enter in the
search field cannot send the message. Escape closes the picker and returns focus
to its trigger. Existing outside-click and Tab dismissal remain intact. Query
state is cleared when a picker closes or another picker replaces it.

### Main files

| File | Responsibility |
| --- | --- |
| `application/v2_ui/src/components/ui/Dropdown.tsx` | Opt-in search, stable filtering, focus, keyboard behavior, and scroll layout. |
| `application/v2_ui/src/components/chat/Composer.tsx` | Enables search for ordinary models, orchestration models, agents, and prompts. |
| `application/v2_ui/src/lib/models.ts` | Builds model search text from public names and publisher/provider metadata. |
| `application/single_app/functions_model_catalog.py` | Adds publisher to the safe profile-summary projection. |
| `application/v2_ui/src/components/chat/DocumentPickerPopover.tsx` | Existing visual reference; its document search behavior is unchanged. |

## Usage

When choosing between vendors, open **Model** and search `OpenAI` or `Anthropic`.
The search also recognizes underlying model-family names such as `Grok` and
`Llama`, so a deployment named for its job can still be found by its real model
metadata. In Orchestrate, use the model picker under **Manual controls** when
that control is available.

For task-specific agents or saved prompts, search the work described rather than
memorizing a catalog name: `forecast` can find an agent described as analyzing
financial forecasts, and `triage` can find a prompt described as an incident
checklist. Choose the result to use the agent or attach the saved prompt.
The existing `/` prompt shortcut still searches from the message editor.

On phones, the same pickers are available through **Chat tools**. Search appears
even when only one entry is available. Existing feature and permission gates
still determine which pickers and catalog entries are offered.

## Testing and validation

`functional_tests/test_model_catalog_profiles.py` verifies publisher projection,
the public-field allowlist, copy isolation, and missing/broken-profile behavior.
`functional_tests/test_v2_chat_picker_search.py` executes the production matching
helpers for names, descriptions, scope text, vendor labels, model families,
whitespace, stable identities, and missing optional metadata.

`ui_tests/test_v2_chat_picker_search.py` drives the real Composer and stores with
synthetic authorized catalogs. It covers both model modes, one-item and long
lists, description-only matches, empty matches, selection and query lifecycle,
keyboard behavior, no search-triggered preference writes, and parity with
legacy Documents styling in desktop/mobile and light/dark layouts. Existing overlay,
orchestration persistence, and prompt-composer suites cover the surrounding
workflows. The shared browser fixture supports local Chromium or configured Azure
Playwright without provisioning resources.

### Performance and limitations

Filtering scans the catalog already in memory and does not add network latency,
debounce delays, new dependencies, or remote runtime assets.

Vendor search depends on the public metadata actually available for a model.
Unprofiled models remain searchable by known names and meaningful provider
labels. An OpenAI-compatible custom API is not assumed to be operated by OpenAI.
Search does not add unavailable models, expand permissions, or inspect agent
instructions, saved prompt bodies, or configuration secrets.
