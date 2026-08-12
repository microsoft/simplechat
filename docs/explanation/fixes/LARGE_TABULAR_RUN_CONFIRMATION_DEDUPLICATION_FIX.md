# Large Tabular Run Confirmation Deduplication Fix

Fixed/Implemented in version: **0.250.168**

Related work: Fixes #1200

## Issue

Repeated Send clicks or Enter presses could enter the large tabular run
confirmation flow more than once before the user resolved the modal. A single
Continue action could then submit the same expensive background run multiple
times.

## Root Cause

`sendMessage()` awaited `confirmLargeTabularRunForPrompt()` without tracking
whether another send invocation was already awaiting the same modal. Each
invocation attached its own Continue listener, and the shared Continue click
resolved every waiting send path.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/config.py`
- `ui_tests/test_chat_background_generated_export_status.py`
- `docs/explanation/release_notes.md`

### Code Changes

- Added a send-level in-flight guard for prompts that require large tabular run
  confirmation.
- Ignored repeated send attempts while the first confirmation remains pending.
- Cleared the guard in `finally` so Continue, Narrow scope, modal dismissal,
  and unexpected errors cannot leave later sends blocked.
- Added browser regression coverage for repeated sends, single submission, and
  guard reuse after the confirmation settles.
- Updated the application version from `0.250.167` to `0.250.168`.

## Impact Analysis

- One large tabular confirmation can now produce at most one user submission.
- Prompts below the configured large-run thresholds retain their existing send
  behavior.
- No backend APIs, settings, schemas, or durable-run processing contracts
  changed.

## Validation

- `python -m pytest ui_tests/test_chat_background_generated_export_status.py -q -k large_tabular_run_confirmation_prompt`
- `node --check application/single_app/static/js/chat/chat-messages.js`
- `python -m py_compile ui_tests/test_chat_background_generated_export_status.py`
- `python scripts/check_xss_sinks.py --base-sha origin/Development --head-sha HEAD application/single_app/static/js/chat/chat-messages.js`

## Before and After

Before, repeated sends created multiple waiters on one modal and one Continue
click could start duplicate runs. After this fix, repeated sends are ignored
until the active confirmation settles, and later sends can confirm normally.
