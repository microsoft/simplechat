# CHAT FACT MEMORY WITHOUT AGENTS

Implemented in version: **0.261.001**

Related config.py update: `VERSION = "0.261.001"`

Related issue: [#1352](https://github.com/microsoft/simplechat/issues/1352). Partially advances [#1153](https://github.com/microsoft/simplechat/issues/1153).

## Overview

Fact memory is now a chat capability rather than an agent action. Administrators enable it
from **Chat > Chat Experience > Fact Memory**, and standard chat then recalls a user's saved
memories, lets users manage their own entries from Profile, and lets the assistant save,
change, or remove memories when a user asks it to in conversation. None of this requires
agents or actions to be enabled.

Two problems motivated the change.

The first was discoverability. The only control was `enable_fact_memory_plugin` in
**Agents & Actions > Actions**, labeled "Enable Fact Memory Action". An administrator running
plain chat had no reason to open that tab, so they never found the switch, even though memory
recall already worked without agents.

The second was a real functional gap. Memory recall was agent-free, but creating, updating,
and deleting memories was not. `FactMemoryPlugin` was only attached to a kernel with automatic
function calling on the Semantic Kernel agent path, so a request like "remember that I prefer
bullet points" or "stop calling me Paul" silently did nothing unless agents were enabled.

## Dependencies

- `application/single_app/functions_fact_memory_autosave.py`
- `application/single_app/functions_settings.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/route_backend_plugins.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/admin_settings_nav.py`
- `application/single_app/semantic_kernel_plugins/fact_memory_plugin.py`
- `application/single_app/templates/admin/_panes/chat-experience.html`
- `application/single_app/templates/admin/_panes/actions.html`
- `application/single_app/static/js/admin/admin_settings.js`

## Technical Specifications

### Settings ownership

`enable_fact_memory_plugin` remains the single settings key, so existing deployments keep the
value they already had and no migration is required. What changed is which surface owns it.

- The live toggle moved to the `fact-memory-section` card in the Chat Experience pane and is
  saved by the main admin settings form.
- The Actions pane shows a read-only `fact-memory-dependency-note` pointing at Chat, following
  the pattern already used by Tabular Processing, which points at Enhanced Citations.
- `POST /api/admin/plugins/settings` moved the key from `expected_keys` to
  `deprecated_optional_keys`. An older client that still posts the key gets a normal response
  and the value is ignored; a current client that omits it no longer gets a 400.
- `is_fact_memory_enabled()` in `functions_settings.py` records the intent in one place.

The endpoint change is load-bearing rather than cosmetic. The Actions toggle previously saved
through the plugins endpoint where the key was required, so removing the input without
relaxing that contract would have made the browser post `enable_fact_memory_plugin: false`.
Toggling any unrelated core action would then have silently disabled fact memory.

### Agent-free memory writes

`functions_fact_memory_autosave.py` adds a small kernel that carries only the fact-memory
plugin, modeled on the existing lightweight tabular analysis runner.

- `user_requested_memory_update()` is a pure intent pre-filter in the same style as
  `user_requested_chart_visualization()`. It matches explicit save, change, and forget
  language, and screens out recall questions such as "do you remember" so the broad
  `remember` pattern does not fire a write pass on every such turn.
- `should_run_fact_memory_autosave()` combines that filter with the admin toggle and skips the
  pass when an agent ran, because an agent run already had the tool attached inline.
- `run_fact_memory_autosave()` builds a `Kernel` with only `FactMemoryPlugin`, creates a chat
  service under the `fact-memory-autosave` service id reusing the resolved chat model endpoint
  context, and executes with `FunctionChoiceBehavior.Auto` filtered to the `fact_memory`
  plugin.
- Changes are read back from the plugin invocation logger and returned as chat thoughts.
- Every failure is contained inside the runner and logged. A memory problem never breaks or
  delays a chat response.

The pass runs after the assistant response is already finalized, in both the standard and
streaming chat paths, so it cannot alter the answer the user sees. It must run inside the
originating request: `FactMemoryPlugin` resolves its authorization boundary from
`g.authorized_chat_context`, which is what prevents a tool call from writing outside the
caller's own user or group scope.

Because the pre-filter gates the pass, ordinary chat turns pay no extra model call.

## Usage Instructions

1. In Admin Settings, open **Chat > Chat Experience > Fact Memory** and enable it. Agents and
   actions can stay off.
2. Users review, add, edit, and delete their own entries from **Profile > Fact Memory**.
3. In chat, users can ask the assistant to remember something, to change how it responds going
   forward, or to forget a saved detail, and the assistant updates their memories.
4. Instruction memories are applied to every prompt. Fact memories are recalled by relevance to
   the current request.
5. Memory activity appears as chat thoughts so users can see what was recalled or changed.
6. Assigning the Fact Memory action to an agent still lets that agent read and write memories
   through its own tool calls.

## Testing and Validation

- `functional_tests/test_chat_fact_memory_admin_placement.py` covers the Chat pane card, the
  Actions read-only note, single form-field ownership across all admin panes, navigation
  registration, admin form persistence, the plugins endpoint contract, and the JavaScript
  payload regression.
- `functional_tests/test_chat_fact_memory_autosave.py` covers intent detection, pass gating,
  mini kernel composition and tool filtering, change reporting, graceful degradation, and
  route wiring across both chat paths.
- `functional_tests/test_fact_memory_profile_and_mini_sk.py` continues to cover typed recall
  and profile CRUD.

## Known Limitations

- The assistant acts on explicit memory requests. It does not propose inferred memories for
  review; that experience is tracked separately in issue #1153.
- Group-scoped memories are still managed through chat and agent workflows rather than a
  dedicated Profile view.
- Memories persist across conversations and are not an appropriate place for secrets or
  regulated data.
