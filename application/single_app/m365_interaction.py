# m365_interaction.py
"""Non-approval user interaction needed to continue delegated Microsoft 365 work."""

from functions_m365_approvals import M365PolicyError


M365_AUTH_INTERACTION_CODES = frozenset({
    "interactive_auth_required", "authentication_required", "consent_required",
    "m365_connection_required", "m365_reconnect_required", "m365_connection_scopes_required",
    "m365_consent_required",
})


class M365SignInRequired(M365PolicyError):
    approval_id = None
    request_type = "m365_sign_in"

    def __init__(self, code, details=None):
        details = details or {}
        safe = {
            key: details[key] for key in ("scopes", "auth_url", "consent_url", "profile_url")
            if key in details
        }
        super().__init__(
            code, "Sign in or reconnect Microsoft 365 to continue this request.",
            auth_required=True, **safe,
        )
