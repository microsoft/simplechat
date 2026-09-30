# functions_orchestration_directory_access.py
"""Stable codes for Microsoft Entra directory reads that the application itself cannot make.

Version: 0.261.204
Implemented in: 0.261.204

Before orchestration uses or reuses web, linked-page, deep-research, agent or action
results, it rereads the requesting user's current account and app-role assignments with
the application's own Microsoft Graph identity. When Microsoft Graph or Microsoft Entra ID
refuses the application, no decision about the user was made: the deployment is missing
the Microsoft Graph application permission, or its client credentials cannot sign in.
Those refusals carry one of the reasons below, so users see an actionable message and
administrators are told which fix applies. Denials about the user keep their own codes.

This module has no imports. The directory reader, invocation capture, executor and
failure schema all read it without widening their dependency graphs.
"""

GRAPH_RESOURCE_APP_ID = "00000003-0000-0000-c000-000000000000"
GRAPH_DIRECTORY_PERMISSION = "Directory.Read.All"
GRAPH_DIRECTORY_PERMISSION_ID = "7ab1d382-f21e-4acd-a863-ba3e13f7da61"

# Microsoft Graph refused the application's token (HTTP 403): the application
# permission is missing or has not been granted administrator consent.
DIRECTORY_PERMISSION_MISSING = "external_identity_directory_permission_missing"
# Microsoft Entra ID refused the client-credential sign-in, or Microsoft Graph
# rejected the resulting token (HTTP 401).
DIRECTORY_SIGN_IN_FAILED = "external_identity_directory_sign_in_failed"
DIRECTORY_ACCESS_REASONS = frozenset({DIRECTORY_PERMISSION_MISSING, DIRECTORY_SIGN_IN_FAILED})

# The step failure code shown to users when a directory reason stopped their work.
DIRECTORY_ACCESS_FAILURE_CODE = "directory_access_unavailable"

# Capabilities whose steps reread the requesting user's directory state, in registry order.
DIRECTORY_GATED_CAPABILITIES = ("web_search", "url_fetch", "deep_research", "agent_invoke", "action_invoke")


def directory_access_reason(error):
    """Return the directory-access reason a refused identity read carries, or None.

    Invocation capture reports the reason as ``authority_reason``; the directory reader
    raises it as the refusal ``code``. Any other denial returns None.
    """
    if not isinstance(error, PermissionError):
        return None
    for name in ("authority_reason", "code"):
        value = getattr(error, name, None)
        if type(value) is str and value in DIRECTORY_ACCESS_REASONS:
            return value
    return None
