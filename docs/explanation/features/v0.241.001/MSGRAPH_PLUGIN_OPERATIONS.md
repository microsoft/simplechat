# Microsoft Graph Plugin Operations

Implemented in version: **0.241.027**

Related config update:
- `application/single_app/config.py` now reports version `0.241.027`.

## Overview and Purpose

The Microsoft Graph plugin now provides a stronger foundation for Graph-backed agent operations and adds practical read-heavy capabilities for profile, calendar, mail, directory, and OneDrive access, plus a focused mail-triage update for marking messages as read or unread. The goal is to make the plugin more useful for day-to-day assistant workflows while handling consent and Graph list responses more safely.

## Dependencies

- `application/single_app/semantic_kernel_plugins/msgraph_plugin.py`
- `application/single_app/functions_authentication.py`
- `application/single_app/semantic_kernel_plugins/base_plugin.py`
- `application/single_app/semantic_kernel_plugins/plugin_invocation_logger.py`
- Microsoft Graph delegated permissions for the enabled operations

## Technical Specifications

### Architecture Overview

The plugin now routes Graph calls through a shared request helper that:

- acquires access tokens through the plugin-aware authentication helper
- supports scoped overrides from the plugin manifest
- builds common OData parameters consistently
- handles pagination for Graph list responses
- returns structured error payloads for consent, throttling, and HTTP failures

### Operations Added or Enhanced

- `get_my_profile`
- `get_my_timezone`
- `get_my_events`
- `get_my_messages`
- `mark_message_as_read`
- `search_users`
- `get_user_by_email`
- `list_drive_items`
- `get_my_security_alerts`

### File Structure

- `msgraph_plugin.py`: Graph request helper, token handling, OData support, and operation methods
- `functions_authentication.py`: delegated token acquisition and consent flow support

## Usage Instructions

1. Register the plugin with a Graph endpoint manifest.
2. Ensure delegated Microsoft Graph permissions are granted for the desired operations.
3. Use read operations first to confirm token scope coverage.
4. Use `mark_message_as_read` only after `Mail.ReadWrite` has been granted for the signed-in user.
5. If consent is required, surface the returned consent URL to the user and retry after consent is granted.

## Testing and Validation

- Functional regression: `functional_tests/test_msgraph_plugin_operations.py`

## Performance Considerations

- Graph list results are capped per request to avoid oversized agent payloads.
- Pagination is followed only up to a bounded number of pages.
- OData field selection should be used to reduce response size whenever possible.

## Known Limitations

- The plugin now supports a narrow mail write operation for updating `isRead`, but it does not yet add broader write operations such as sending mail or creating events.
- Security alert access still requires elevated delegated permissions and may not be appropriate for all tenants.