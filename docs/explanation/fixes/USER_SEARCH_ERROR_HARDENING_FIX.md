# User Search Error Hardening Fix (v0.261.151)

## Issue

`GET /api/userSearch`, which the classic add-member and sharing dialogs and
V2's document sharing use, had three problems when Microsoft Graph failed:

- **It returned Graph's error body** to the browser, under `details`. That body
  can name the tenant, the application and its permissions.
- **It had no timeout**, so a slow Graph call held the request open
  indefinitely.
- **It logged with `print()`**, outside the application's logging.

Fixed in version: **0.261.151**, tracked in `application/single_app/config.py`.

## Technical details

### Files modified

`route_backend_users.py`:
- The Graph request has a 20-second timeout, the bound the SimpleChat operations
  already use for Graph.
- Failures return fixed messages, with no `details`:

  | Failure | Response |
  |---|---|
  | Graph answered with an error status | That status, with `{"error": "Graph API request failed"}` |
  | Timeout | 504, with `{"error": "Graph API request timed out"}` |
  | Transport failure, or an answer that can't be read | 502, with `{"error": "Graph API request failed"}` |

  A failure that carries a non-error status is answered with 502, never 200.
- Failures are logged with `log_event` at warning level, under `[USERS]`, with
  the status code only.

The successful response, `[{id, displayName, email}]`, the empty-query answer and
the 401 without a token are unchanged. No client reads `details`: that covers
the classic add-member, governance and sharing dialogs, and V2's document
sharing.

### Tests

`functional_tests/test_user_search_hardening.py` (26 cases):
- each failure's status and body;
- that Graph's body appears in neither the response nor the log;
- the timeout is passed to the request;
- the unchanged success, empty-query and 401 answers.

23 of the 26 fail on the code before the fix. The other three are the unchanged
answers.

## Validation

- Before: a Graph failure could expose Graph's error details to the browser, and
  a slow Graph call had no limit.
- After: failures answer with a fixed message within 20 seconds, and only the
  status code is logged.

## Related

- [Group Membership APIs](../features/GROUP_MEMBERSHIP_APIS.md)
