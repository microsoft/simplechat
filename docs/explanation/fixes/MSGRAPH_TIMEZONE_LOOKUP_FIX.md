# MSGRAPH_TIMEZONE_LOOKUP_FIX.md

## Microsoft Graph Timezone Lookup Fix (v0.239.174)

Fixed/Implemented in version: **0.239.174**

### Issue Description

Timezone-sensitive responses could be wrong because the core Semantic Kernel time plugin does not
know the signed-in user's mailbox timezone and often defaults to UTC-oriented behavior.

### Root Cause Analysis

The application exposed Microsoft Graph calendar and mail operations but did not expose mailbox
timezone settings. That left the agent without a user-specific timezone source when it needed to
answer questions such as current local time, date boundaries, or time-relative interpretations.

### Technical Details

Files modified:
- `application/single_app/semantic_kernel_plugins/msgraph_plugin.py`
- `application/single_app/config.py`
- `functional_tests/test_msgraph_plugin_operations.py`

Code changes summary:
- Added `get_my_timezone` to the Microsoft Graph plugin.
- Wired the new operation to `GET /v1.0/me/mailboxSettings` with the `MailboxSettings.Read` scope.
- Updated plugin metadata so agents can discover the timezone operation.
- Extended functional coverage for the new timezone lookup.

Testing approach:
- Updated `functional_tests/test_msgraph_plugin_operations.py` to verify metadata exposure,
  required scope usage, request path, and shaped timezone result payload.

Impact analysis:
- Agents now have an explicit per-user timezone source from Microsoft Graph.
- Timezone-sensitive responses can prefer the user's mailbox timezone instead of assuming UTC.

### Validation

Before:
- The agent had no dedicated Microsoft Graph timezone lookup.
- TimePlugin-based answers could drift to UTC assumptions.

After:
- The agent can call `msgraph.get_my_timezone` to retrieve the mailbox timezone and formatting.
- Time-sensitive answers can use mailbox timezone context before relying on generic time helpers.