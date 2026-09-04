# Chat History Summarize Settings Reset Fix

**Fixed in version: 0.261.059**

## Issue

Three conversation history settings were reset to their defaults every time an
administrator saved Admin Settings, regardless of what they had been set to:

| Setting | Reset to |
| --- | --- |
| `enable_summarize_content_history_for_search` | `False` |
| `enable_summarize_content_history_beyond_conversation_history_limit` | `False` |
| `number_of_historical_messages_to_summarize` | `10` |

An administrator who had configured these — the only way to do so was writing
them directly into the settings document in Cosmos DB — lost the values the next
time anyone opened Admin Settings and pressed Save, for any unrelated reason.
Nothing reported the change.

## Root cause

All three settings are read and acted on by `route_backend_chats.py`:

```python
enable_summarize_content_history_beyond_conversation_history_limit = settings.get(
    'enable_summarize_content_history_beyond_conversation_history_limit', True)
enable_summarize_content_history_for_search = settings.get(
    'enable_summarize_content_history_for_search', False)
number_of_historical_messages_to_summarize = settings.get(
    'number_of_historical_messages_to_summarize', 10)
```

`route_frontend_admin_settings.py` wrote all three on every save:

```python
'enable_summarize_content_history_for_search': form_data.get('enable_summarize_content_history_for_search') == 'on',
'enable_summarize_content_history_beyond_conversation_history_limit': form_data.get('enable_summarize_content_history_beyond_conversation_history_limit') == 'on',
'number_of_historical_messages_to_summarize': int(form_data.get('number_of_historical_messages_to_summarize', 10)),
```

But no template rendered an input for any of them. An unchecked checkbox is
simply absent from a form submission, and an absent checkbox is indistinguishable
from one the user deliberately unticked — so both booleans evaluated to `False`
on every save. The integer fell back to its literal default for the same reason.

The write path existed; the read path never did. The settings could be stored but
not kept.

## Fix

**Added the missing controls.** The Conversation History card in
`templates/admin/_panes/chat-experience.html` gained a "History Summarization"
group holding all three, so the form now submits what the save handler reads.

**Made the integer parse defensively.** The bare `int()` call raised a
`ValueError` on an empty submission and ignored the stored value. It now uses the
same `parse_admin_int` helper the rest of the form uses, falling back to the
stored setting rather than the literal default, and is clamped to the 1–100 range
the new input declares:

```python
'number_of_historical_messages_to_summarize': min(100, max(1, parse_admin_int(
    form_data.get('number_of_historical_messages_to_summarize'),
    settings.get('number_of_historical_messages_to_summarize', 10),
    'number_of_historical_messages_to_summarize',
    10,
))),
```

**Aligned the adjacent history limit.** `conversation_history_limit` in the same
card used the same fragile `int(form_data.get(...))` pattern, which raised on an
empty value and accepted zero or negative numbers. It now parses through
`parse_admin_int` with a floor of 1, matching the bound the V2 schema declares.

**Declared them for the V2 admin surface.** `admin_settings_fields.py` describes
all four fields under `conversation-history-section`, so both interfaces offer
the same controls with the same bounds. The message count is gated on the search
summarization switch, because it has no effect while that is off.

## Files modified

| File | Change |
| --- | --- |
| `application/single_app/templates/admin/_panes/chat-experience.html` | Added the three summarization controls to the Conversation History card |
| `application/single_app/route_frontend_admin_settings.py` | Defensive integer parsing for both history values |
| `application/single_app/admin_settings_fields.py` | Declared the four Conversation History fields |
| `application/single_app/config.py` | Version bump to 0.261.059 |

## Validation

`functional_tests/test_v2_admin_chat_parity.py` requires every field name the V1
chat panes submit to be claimed by the schema, and every schema field in the Chat
group to map back to a V1 field. Either half of this regression — a control
removed from V1, or a setting written without a control — fails that test.

`functional_tests/test_admin_settings_field_contract.py` confirms the three new
field names are registered and that no existing name was lost.

`functional_tests/test_admin_settings_absent_field_preservation.py` generalises
the bug class: it requires every settings key the save handler reads from the
form with a literal empty default to be backed by an input that actually exists.
That check found a second instance in the same handler — see
`ENHANCED_CITATIONS_STORAGE_KEY_RESET_FIX.md`.

### Before and after

| | Before | After |
| --- | --- | --- |
| Control in V1 | None | Conversation History card |
| Control in V2 | None | Conversation History section |
| Effect of an unrelated admin save | All three reset | Values preserved |
| Empty history limit submitted | `ValueError` | Falls back to the stored value |

## Related

- `docs/admin/chat.md` — Conversation History settings reference
- `docs/explanation/features/V2_ADMIN_CHAT_SETTINGS.md` — the described Chat group
