# Chat Template JSON Bootstrap Fix

Fixed/Implemented in version: **0.240.008**

## Issue Description

The chats page could fail during initial load with a browser error similar to `Bad control character in string literal in JSON` when bootstrapped template data included escaped control characters such as newlines.

## Root Cause Analysis

- The template was serializing several server-side objects with `tojson`, wrapping that JSON in a JavaScript string literal, and then calling `JSON.parse(...)` on the client.
- JavaScript unescaped sequences like `\n` while building the string literal, which turned valid JSON text into invalid JSON content before `JSON.parse(...)` ran.
- The same bootstrap block also interpolated several string globals directly into JavaScript string literals, which left them vulnerable to the same class of quoting and control-character failures.

## Technical Details

### Files Modified

- `application/single_app/templates/chats.html`
- `application/single_app/config.py`
- `functional_tests/test_chat_multi_endpoint_notice_template_fallback.py`
- `functional_tests/test_chat_template_json_bootstrap_safety.py`
- `ui_tests/test_chat_page_multi_endpoint_notice_render.py`

### Code Changes Summary

- Replaced `JSON.parse('...{{ value|tojson }}...')` bootstrapping in `chats.html` with direct JavaScript literal assignment using `tojson`.
- Converted adjacent inline string and boolean globals in the same script block to `tojson` output so user-controlled values cannot break the page bootstrap.
- Updated the existing multi-endpoint notice regression test to assert the new safe bootstrap pattern.
- Added a dedicated functional regression test to prevent reintroduction of `JSON.parse`-wrapped Jinja payloads in the chat template.
- Extended the chat page UI smoke test to fail on browser-side syntax and JSON bootstrap errors.

### Testing Approach

- Functional regression: `functional_tests/test_chat_multi_endpoint_notice_template_fallback.py`
- Functional regression: `functional_tests/test_chat_template_json_bootstrap_safety.py`
- UI regression: `ui_tests/test_chat_page_multi_endpoint_notice_render.py`

## Validation

### Before

- Selecting workspace/chat context that introduced escaped control characters into bootstrapped template data could stop the chats page from finishing its JavaScript initialization.

### After

- The chats page bootstraps server-side data as direct JavaScript literals.
- Escaped control characters remain safely encoded within the serialized objects instead of being reinterpreted by a JavaScript string literal.
- The page can load without the `Bad control character in string literal in JSON` console failure.