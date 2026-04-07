# FACT MEMORY PROFILE AND MINI SK

Implemented in version: **0.240.077**

Related config.py update: `VERSION = "0.240.077"`

## Overview

This feature extends fact memory into the lightweight mini-SK tabular analysis flow, makes the admin fact-memory toggle authoritative for chat-time usage, and adds profile recall tools so users can review and control the memories saved for their account.

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

### Mini-SK Integration

- The lightweight tabular SK runner prepends fact-memory system messages into its temporary chat history.
- The temporary mini-SK kernel also registers the fact-memory plugin when enabled so the lightweight runtime stays aligned with the app's SK action model.

### Profile Recall and Editing

- Added profile recall APIs at `/api/profile/fact-memory` for listing and creating user-scoped fact memories.
- Added profile recall APIs at `/api/profile/fact-memory/<fact_id>` for updating and deleting user-scoped fact memories.
- Added a new Profile page section that lets users add, edit, refresh, and delete saved memories.
- The profile experience shows whether fact memory is currently enabled by admin while still allowing users to manage stored entries.

## Usage Instructions

1. Admins can enable or disable fact memory from Admin Settings using the existing Fact Memory action toggle.
2. Users can open Profile and use the Fact Memory section to create or revise saved memory entries.
3. When the toggle is enabled, supported chat and mini-SK flows can read those memories during execution.

## Testing and Validation

- Functional regression: `functional_tests/test_fact_memory_profile_and_mini_sk.py`
- Browser workflow regression: `ui_tests/test_profile_fact_memory_editor.py`

## Known Limitations

- Profile recall currently manages user-scoped memories. Group-scoped fact memories continue to be managed through chat and agent workflows.