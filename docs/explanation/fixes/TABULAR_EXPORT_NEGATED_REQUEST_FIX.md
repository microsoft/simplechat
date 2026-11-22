# Tabular Export Started Despite "Do Not Generate" Fix

## Issue Description

A user sent a prompt, with a spreadsheet attached, that ended "Do not generate JSON, create files, or initiate background processing." The reply was "Understood. I am generating the complete JSON for all 826 rows. Processing continues in the background…" and a background export started. Correcting the assistant led to an apology and a request for permission instead of the answer. This happened five times in 24 hours.

## Root Cause

- The reply was a fixed server message, not model output. The chat route replaces the model's answer with it whenever a background tabular run is accepted.
- Keyword matching on the user's message decided whether to start that run. Before v0.250.154 it matched the substring `generate json`, which appears inside "Do not generate JSON".
- v0.250.154 added a negation pattern for "do not / don't / never". Other phrasings still started an export: "must not generate JSON", "rather than as a JSON file", "JSON output is not permitted", "Step 5D will generate the JSON".
- The fixed message was saved as the assistant's reply in the first person. Later turns read it as a promise the model had made.

**Fixed in version:** 0.261.479

## Technical Details

### Files modified

- `application/single_app/functions_request_intent.py` (new)
- `application/single_app/functions_generated_file_exports.py`
- `application/single_app/functions_tabular_orchestration.py`
- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_settings.py`
- `application/single_app/static/js/chat/chat-messages.js`
- `ui_tests/test_chat_background_generated_export_status.py`
- Test harness namespaces in four functional tests that execute the changed functions in isolation

### Code changes

- Keywords now only nominate a file export or background run. A per-action decision for the turn determines whether it starts. See `docs/explanation/features/REQUEST_INTENT_CHECK.md`.
- Explicit statements such as "do not create files" and "do not initiate background processing" withhold the matching action without a model call.
- A short model check decides the remaining nominated actions. If it fails or is unsure, the action is withheld and the reply says so.
- Background run submission and file publication check the decision themselves.
- The handoff message is worded as application status.
- The background export card has an **Answer in chat instead** button.

### Testing

`functional_tests/test_request_intent_side_effect_gate.py`, 12 checks, all passing. The model is stubbed.

### Impact

- Prompts that forbid a file or background processing no longer start one.
- Genuine export requests cost one additional short model call before the run starts.
- A wanted export can be withheld if the check fails or is unsure. The reply states this and how to request it.

## Validation

### Before and after

| Prompt | Before | After |
|---|---|---|
| "Do not generate JSON, create files, or initiate background processing." (pre-0.250.154) | Background JSON export | Answer in chat |
| "You must not generate JSON. Analyze every row in chat." | Background JSON export | Answer in chat |
| "Respond in chat rather than as a JSON file for all rows." | Background JSON export | Answer in chat |
| "Step 5D will generate the JSON. For now, analyze all rows in chat." | Background JSON export | Answer in chat |
| "Convert all rows to a JSON file" | Background JSON export | Background JSON export |

The "after" column for the middle three rows depends on the model check answering correctly. That was verified with a stubbed model only, not against a live model.

### Not verified

- No run in the live application: the chat routes, the streaming path, agent chat and the new button have not been exercised end to end.
- The follow-up turn after a real handoff ("Proceed") has not been tested against a live model.
