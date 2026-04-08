# FACT MEMORY PROFILE AND MINI SK

Implemented in version: **0.240.077**

Updated in version: **0.240.079**

Updated in version: **0.240.081**

Updated in version: **0.240.082**

Updated in version: **0.240.083**

Related config.py update: `VERSION = "0.240.083"`

## Overview

This feature extends fact memory into the lightweight mini-SK tabular analysis flow, makes the admin fact-memory toggle authoritative for chat-time usage, and adds profile recall tools so users can review and control the memories saved for their account.

The profile experience was later tightened into a smaller page-level summary with a dedicated popup manager for searching, paging, and editing memories.

The chat experience now splits saved memories into instruction memories and fact memories. Instruction memories are always applied like durable user-specific prompt rules, while fact memories are recalled by embedding similarity only when they are relevant to the current request.

## Dependencies

- `application/single_app/route_backend_chats.py`
- `application/single_app/route_frontend_profile.py`
- `application/single_app/semantic_kernel_fact_memory_store.py`
- `application/single_app/semantic_kernel_plugins/fact_memory_plugin.py`
- `application/single_app/templates/profile.html`

## Technical Specifications

### Admin-Controlled Usage

- The existing `enable_fact_memory_plugin` admin toggle now gates fact-memory injection for supported chat flows instead of only controlling plugin registration.
- The mini-SK tabular analysis kernel now receives the same fact-memory context when the toggle is enabled.
- Fact memory retrieval is request-scoped so chat paths only inject relevant matches instead of the full saved-memory set.

### Memory Types

- Fact memory entries now store a `memory_type` of either `instruction` or `fact`.
- Instruction memories are injected into supported chat and mini-SK flows on every prompt as durable user-specific guidance.
- Fact memories are embedded and recalled at request time using similarity search instead of keyword heuristics.
- The fact-memory plugin now exposes `memory_type` so the model can decide whether a newly created memory should behave like an always-on instruction or a retrieved fact.

### Mini-SK Integration

- The lightweight tabular SK runner prepends both instruction-memory and relevant fact-memory system messages into its temporary chat history.
- The temporary mini-SK kernel also registers the fact-memory plugin when enabled so the lightweight runtime stays aligned with the app's SK action model.

### Profile Recall and Editing

- Added profile recall APIs at `/api/profile/fact-memory` for listing and creating user-scoped fact memories.
- Added profile recall APIs at `/api/profile/fact-memory/<fact_id>` for updating and deleting user-scoped fact memories.
- Added a new Profile page section that lets users add memories inline and open a popup manager for search, pagination, editing, deletion, and memory-type updates.
- The profile experience shows whether fact memory is currently enabled by admin while still allowing users to manage stored entries.
- The compact profile summary now shows the saved memory count, type breakdown, and last-updated date instead of showing agent or conversation metadata inline.

## Usage Instructions

1. Admins can enable or disable fact memory from Admin Settings using the existing Fact Memory action toggle.
2. Users can open Profile and add a new memory directly from the page, choosing whether it is an instruction memory or fact memory.
3. Users can open the Manage Memories popup to search, page through, filter by type, edit, reclassify, and delete saved entries.
4. When the toggle is enabled, supported chat and mini-SK flows apply instruction memories on every prompt and retrieve fact memories only when they are relevant.
5. When instruction memories are applied or fact memories are retrieved, chat thoughts and citations show dedicated memory steps so users can see how memory was used.

## Testing and Validation

- Functional regression: `functional_tests/test_fact_memory_profile_and_mini_sk.py`
- Browser workflow regression: `ui_tests/test_profile_fact_memory_editor.py`

## Known Limitations

- Profile recall currently manages user-scoped memories. Group-scoped fact memories continue to be managed through chat and agent workflows.
- Existing legacy fact-memory rows saved with the older `describer` type are normalized to `fact` automatically.