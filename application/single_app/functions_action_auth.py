# functions_action_auth.py
"""Per-user action authentication contracts, without application initialization.

Storage, Flask and execution-context imports are deferred to operation boundaries:
schema validation must not initialize Cosmos, Key Vault, or a plugin client.
"""

import hashlib
import ipaddress
import json
import unicodedata
import uuid
from copy import deepcopy
from importlib import import_module
from urllib.parse import quote, unquote, urlsplit, urlunsplit


ACTION_AUTH_PROFILES = {
    "yamcs_login": {
        "auth_type": "username_password",
        "native_auth_type": "username_password",
        "auth_method": "username_password",
        "fields": (
            {"name": "username", "label": "Username", "type": "text", "required": True},
            {"name": "password", "label": "Password", "type": "password", "required": True},
        ),
    },
    "http_basic": {
        "auth_type": "username_password",
        "native_auth_type": "basic",
        "auth_method": "http_basic",
        "fields": (
            {"name": "username", "label": "Username", "type": "text", "required": True},
            {"name": "password", "label": "Password", "type": "password", "required": True},
        ),
    },
    "bearer_token": {
        "auth_type": "bearer_token",
        "native_auth_type": "key",
        "auth_method": "bearer_token",
        "fields": ({"name": "secret", "label": "Bearer token", "type": "password", "required": True},),
    },
    "api_key": {
        "auth_type": "api_key",
        "native_auth_type": "key",
        "auth_method": "api_key",
        "fields": ({"name": "secret", "label": "API key", "type": "password", "required": True},),
    },
}
ACTION_AUTH_SHARING_NOTICE = (
    "Your account is used for this request. Your message and returned data will be "
    "visible to everyone with access to this conversation. Your saved credentials "
    "and credential form are private."
)
_REQUIREMENT_FIELDS = frozenset({"id", "source", "identity_name", "profile"})
_INLINE_FIELDS = frozenset({
    "identity_id", "identity", "username", "password", "secret", "key", "api_key",
    "access_token", "token", "credentials", "headers", "auth_headers", "custom_headers",
    "password_secret_name", "secret_secret_name", "connection_string", "authorization",
    "authorization_header", "client_secret", "refresh_token",
})
_ACTOR_ERROR = "An authenticated action execution identity is required."
_INVALID_REQUIREMENT = "Invalid per-user action credential requirement."


class ActionAuthConflict(ValueError):
    """A safe, recoverable conflict in a private authentication workflow."""

    def __init__(self, message="Authentication changed. Check the selected action again.", *, code="action_auth_conflict"):
        super().__init__(message)
        self.code = code
        self.safe_message = message


class ActionAuthStorageError(RuntimeError):
    """A credential/metadata storage failure, not a rejected credential."""

    safe_message = "Credential storage is unavailable. Please try again."

    def __init__(self):
        super().__init__(self.safe_message)


class ActionCredentialsRequired(RuntimeError):
    """Private control signal compatible with DelegationBudget.require_authentication."""

    def __init__(self, auth_response=None, *, action_ref=None):
        super().__init__("Personal action credentials are required.")
        response = auth_response if isinstance(auth_response, dict) else {}
        self.auth_response = {
            "status": "credentials_required",
            "request_id": response.get("request_id") if isinstance(response.get("request_id"), str) else None,
            "uses_personal_credentials": True,
            "shared_conversation": bool(response.get("shared_conversation")),
            "sharing_notice": ACTION_AUTH_SHARING_NOTICE if response.get("shared_conversation") else None,
            "requirements": [],
        }
        for requirement in response.get("requirements") or []:
            if (
                not isinstance(requirement, dict) or not isinstance(requirement.get("profile"), str)
                or requirement["profile"] not in ACTION_AUTH_PROFILES
            ):
                continue
            safe = {
                key: deepcopy(requirement[key]) for key in (
                    "id", "action_id", "action_name", "identity_name", "profile",
                    "auth_type", "destination", "reason",
                ) if isinstance(requirement.get(key), str)
            }
            safe["auth_type"] = ACTION_AUTH_PROFILES[requirement["profile"]]["auth_type"]
            if "destination" in safe:
                try:
                    safe["destination"] = _canonical_destination(safe["destination"])
                except ValueError:
                    safe.pop("destination")
            if safe.get("reason") not in (
                "missing", "approval_required", "ambiguous", "incompatible", "authentication_rejected"
            ):
                safe["reason"] = "missing"
            safe["fields"] = list(deepcopy(ACTION_AUTH_PROFILES[requirement["profile"]]["fields"]))
            safe["identities"] = [
                {key: identity[key] for key in ("id", "name", "auth_type") if isinstance(identity.get(key), str)}
                for identity in requirement.get("identities") or [] if isinstance(identity, dict)
            ]
            self.auth_response["requirements"].append(safe)
        self.action_ref = action_ref

    def to_payload(self):
        return {"error_code": "action_credentials_required", **deepcopy(self.auth_response)}


def get_action_credential_requirement(action):
    """Return a copy of the non-secret requirement; malformed presence never falls back."""
    if not isinstance(action, dict) or "credential_requirement" not in action:
        return None
    requirement = action["credential_requirement"]
    if not isinstance(requirement, dict):
        raise ValueError(_INVALID_REQUIREMENT)
    return deepcopy(requirement)


def normalize_action_identity_name(value):
    """One consistent, case-insensitive comparison for suggested identity labels."""
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


def _requirement_uuid(value):
    if not isinstance(value, str):
        raise ValueError(_INVALID_REQUIREMENT)
    try:
        result = str(uuid.UUID(value))
    except (ValueError, AttributeError):
        raise ValueError(_INVALID_REQUIREMENT) from None
    if value != result:
        raise ValueError(_INVALID_REQUIREMENT)
    return result


def _canonical_destination(value):
    if (
        not isinstance(value, str) or not value or len(value) > 2048
        or "\\" in value or any(ord(character) <= 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("Per-user actions require a valid HTTPS destination.")
    try:
        parsed = urlsplit(value)
        port = parsed.port if parsed.port is not None else 443
        host = parsed.hostname
        if (
            parsed.scheme.lower() != "https" or not host or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or "?" in value or "#" in value or not 1 <= port <= 65535
        ):
            raise ValueError()
        try:
            host = ipaddress.ip_address(host).compressed
        except ValueError:
            host = host.rstrip(".").encode("idna").decode("ascii").lower()
            if not host or any(not part or part.startswith("-") or part.endswith("-") for part in host.split(".")):
                raise ValueError()
            if any(not (character.isalnum() or character in ".-") for character in host):
                raise ValueError()
        if ":" in host:
            host = f"[{host}]"
        authority = host if port == 443 else f"{host}:{port}"
        path = parsed.path
        segments = []
        for segment in path.split("/"):
            decoded = unquote(segment, errors="strict")
            for _ in range(4):
                nested = unquote(decoded, errors="strict")
                if nested == decoded:
                    break
                decoded = nested
            else:
                raise ValueError()
            if decoded in {".", ".."} or any(character in decoded for character in "/\\?#"):
                raise ValueError()
            if any(ord(character) < 32 or ord(character) == 127 for character in decoded):
                raise ValueError()
            segments.append(quote(decoded, safe="-._~!$&'()*+,;=:@"))
        path = "/".join(segments).rstrip("/")
        if "//" in path:
            raise ValueError()
        return urlunsplit(("https", authority, path, "", ""))
    except (ValueError, UnicodeError):
        raise ValueError("Per-user actions require a valid HTTPS destination.") from None


def get_action_auth_destination(action):
    """Canonical credential recipient used for approval and the client transport."""
    fields = action.get("additionalFields") or {}
    if not isinstance(fields, dict):
        raise ValueError(_INVALID_REQUIREMENT)
    urls = [value for value in (fields.get("server_url"), fields.get("serverUrl"), action.get("endpoint")) if value]
    if not urls:
        raise ValueError("Per-user actions require a valid HTTPS destination.")
    destinations = {_canonical_destination(value) for value in urls}
    if len(destinations) != 1:
        raise ValueError("Per-user action destinations must agree.")
    if fields.get("tls_verify", True) not in (True, "true", "True", 1):
        raise ValueError("Per-user actions require TLS certificate verification.")
    return destinations.pop()


def _has_inline_credentials(values, *, root=False):
    for key, value in values.items():
        normalized = str(key).casefold()
        if root and normalized in {"auth", "credential_requirement"}:
            continue
        if (normalized in _INLINE_FIELDS or normalized == "auth") and value not in (None, ""):
            return True
        if isinstance(value, dict) and _has_inline_credentials(value):
            return True
    return False


def validate_action_credential_requirement(action, *, scope_type=None):
    """Validate a draft requirement without reading settings, identities or storage."""
    requirement = get_action_credential_requirement(action)
    if requirement is None:
        return
    if (
        action.get("type") != "yamcs"
        or set(requirement) - _REQUIREMENT_FIELDS
        or requirement.get("source") != "current_user"
        or not isinstance(requirement.get("profile"), str)
        or requirement.get("profile") not in ACTION_AUTH_PROFILES
    ):
        raise ValueError(_INVALID_REQUIREMENT)
    if scope_type not in (None, "global"):
        raise ValueError("Per-user credentials are supported only by global Yamcs actions.")
    if (
        action.get("is_group") or action.get("user_id") or action.get("group_id")
        or action.get("scope_type") not in (None, "", "global")
        or action.get("scope") not in (None, "", "global")
    ):
        raise ValueError("Per-user credentials are supported only by global Yamcs actions.")
    label = requirement.get("identity_name")
    if (
        not isinstance(label, str) or not label.strip() or len(label) > 120
        or any(ord(character) < 32 or ord(character) == 127 for character in label)
    ):
        raise ValueError("Provide an identity name of at most 120 characters.")
    if "id" in requirement:
        _requirement_uuid(requirement["id"])
    auth = action.get("auth", {})
    fields = action.get("additionalFields", {})
    if not isinstance(auth, dict) or not isinstance(fields, dict):
        raise ValueError(_INVALID_REQUIREMENT)
    if (
        any(value not in (None, "") for key, value in auth.items() if key != "type")
        or _has_inline_credentials(action, root=True)
    ):
        raise ValueError("Per-user actions cannot contain inline credentials or an identity reference.")
    get_action_auth_destination(action)


def normalize_action_credential_requirement(action, existing_action=None, *, assign_id=False):
    """Copy and derive native authentication while preserving server-owned IDs."""
    result = deepcopy(action)
    requirement = get_action_credential_requirement(result)
    if requirement is None:
        return result
    validate_action_credential_requirement(result)
    previous = get_action_credential_requirement(existing_action)
    if previous and previous.get("id"):
        previous_id = _requirement_uuid(previous["id"])
        if requirement.get("id", previous_id) != previous_id:
            raise ValueError("The credential requirement ID cannot be changed.")
        requirement["id"] = previous_id
    elif assign_id:
        if requirement.get("id"):
            raise ValueError("Credential requirement IDs are assigned by the server.")
        requirement["id"] = str(uuid.uuid4())
    requirement["identity_name"] = requirement["identity_name"].strip()
    profile = ACTION_AUTH_PROFILES[requirement["profile"]]
    result["credential_requirement"] = requirement
    result["auth"] = {"type": profile["native_auth_type"]}
    result["additionalFields"] = {**result.get("additionalFields", {}), "auth_method": profile["auth_method"], "tls_verify": True}
    result.pop("identity_id", None)
    return result


def action_auth_fingerprint(action):
    """Hash only the canonical recipient and registered credential-delivery profile."""
    validate_action_credential_requirement(action)
    requirement = get_action_credential_requirement(action)
    if requirement is None:
        raise ValueError(_INVALID_REQUIREMENT)
    descriptor = {
        "destination": get_action_auth_destination(action),
        "profile": requirement["profile"],
        "header": "x-api-key" if requirement["profile"] == "api_key" else None,
        "tls_verify": True,
    }
    return hashlib.sha256(json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _action_auth_actor(user_id=None, *, require_context=False):
    """Prefer task-local actor, verify authenticated request/explicit actor consistency."""
    # Context modules are light but not required for pure manifest validation.
    frame = import_module("agent_execution_context").current_agent_execution()
    flask = import_module("flask")
    request_actor = None
    if flask.has_request_context():
        request_actor = (flask.session.get("user") or {}).get("oid")
        if not request_actor:
            raise PermissionError(_ACTOR_ERROR)
    execution_actor = frame.identity.user_id if frame else None
    actors = [actor for actor in (execution_actor, request_actor, user_id) if actor is not None]
    if require_context and not (execution_actor or request_actor):
        raise PermissionError(_ACTOR_ERROR)
    if not actors or any(
        not isinstance(actor, str) or not actor or actor != actor.strip()
        or actor.casefold() == "system" or len(actor) > 128
        or any(ord(character) < 32 or character in "/\\?#" for character in actor)
        for actor in actors
    ) or len(set(actors)) != 1:
        raise PermissionError(_ACTOR_ERROR)
    return actors[0]


def resolve_action_auth_credentials(action):
    """Resolve a fresh owned identity at invocation, never on a shared plugin."""
    user_id = _action_auth_actor(require_context=True)
    # The state service reauthorizes the stored action and validates the binding
    # immediately before private identity/Key Vault access. No mutation or cache.
    return import_module("functions_action_auth_state")._resolve_action_credentials(user_id, action)


def invalidate_action_auth_credentials(action):
    """Mark only this invocation's actor-owned credential revision as rejected."""
    user_id = _action_auth_actor(require_context=True)
    return import_module("functions_action_auth_state")._invalidate_action_credentials(user_id, action)
