# action_credential_contracts.py
"""Bootstrap-free personal action credential contracts and connector adapters."""

from copy import deepcopy
import hashlib
import json
from urllib.parse import urlsplit

from functions_action_manifest import get_action_origin, resolve_action_type
from functions_yamcs_operations import (
    normalize_yamcs_auth_method,
    normalize_yamcs_server_url,
    yamcs_basic_auth_conflicts_with_auth_method,
)


class ActionCredentialError(RuntimeError):
    """A stable, data-free credential failure."""

    def __init__(self, code="credentials_unavailable", status_code=409):
        self.code = code
        self.status_code = status_code
        super().__init__("Action credentials are unavailable. Refresh the credential request.")


class ActionCredentialsRequired(ActionCredentialError):
    """A connector has stopped before model interpretation of an authentication failure."""

    def __init__(self, request):
        super().__init__("action_credentials_required")
        self.credential_request = request

    @property
    def event(self):
        return {"type": "action_credentials_required", "credential_request": self.credential_request}


def find_credential_stop(error):
    seen = set()
    while error is not None and id(error) not in seen:
        if isinstance(error, ActionCredentialsRequired):
            return error
        seen.add(id(error))
        error = error.__cause__ or error.__context__
    return None


class YamcsCredentialAdapter:
    slots = {"service": {"username_password", "api_key", "bearer_token"}, "proxy": {"username_password"}}

    @staticmethod
    def validate(manifest, slots):
        auth = manifest.get("auth") or {}
        fields = manifest.get("additionalFields") or {}
        service = slots.get("service")
        if service and any((
            manifest.get("identity_id"), fields.get("identity_id"), auth.get("key"),
            auth.get("identity"), auth.get("tenantId"), fields.get("api_key"),
            fields.get("password"), fields.get("access_token"), fields.get("token"),
        )):
            raise ValueError("Personal service credentials cannot include a shared credential or identity.")
        if "proxy" in slots and any(fields.get(key) for key in (
            "basic_auth_identity_id", "basic_auth_username", "basic_auth_password",
        )):
            raise ValueError("Personal proxy credentials cannot include a shared credential or identity.")
        method = service["auth_type"] if service else normalize_yamcs_auth_method(fields, auth.get("type"))
        if ("proxy" in slots or fields.get("enable_basic_auth")) and yamcs_basic_auth_conflicts_with_auth_method(method):
            raise ValueError("Yamcs proxy Basic authentication requires service none or API key authentication.")

    @staticmethod
    def destination(manifest):
        fields = manifest.get("additionalFields") or {}
        endpoint = normalize_yamcs_server_url(manifest.get("endpoint") or fields.get("server_url"))
        target = urlsplit(endpoint)
        if target.scheme not in {"http", "https"} or not target.hostname or target.username or target.password:
            raise ValueError("Yamcs requires a valid server destination without URL credentials.")
        return {
            "endpoint": endpoint, "instance": fields.get("instance") or fields.get("yamcs_instance"),
            "tls_verify": fields.get("tls_verify", True),
            "service_auth": normalize_yamcs_auth_method(fields, (manifest.get("auth") or {}).get("type")),
            "proxy_enabled": bool(fields.get("enable_basic_auth")),
        }

    @staticmethod
    def inject(manifest, slot, auth):
        fields = manifest.setdefault("additionalFields", {})
        if slot == "proxy":
            fields.update(
                enable_basic_auth=True, basic_auth_username=auth["username"],
                basic_auth_password=auth["password"],
            )
        else:
            method = auth["auth_type"]
            fields["auth_method"] = method
            manifest["auth"] = {
                "type": "username_password" if method == "username_password" else "key",
                "key": auth["password"] if method == "username_password" else auth["secret"],
                "identity": auth.get("username", ""),
            }

    @staticmethod
    def rejected_slots(manifest, error):
        """Use provider response status only, never exception text."""
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
        # yamcs-client HttpError retains its numeric HTTP status on status_code.
        if status is None:
            status = getattr(error, "status_code", None)
        slots = credential_slots(manifest)
        if status == 407:
            return ["proxy"] if "proxy" in slots else []
        if status != 401:
            return []
        if len(slots) == 1:
            return list(slots)
        # An API-key service behind a Basic reverse proxy cannot disambiguate a 401.
        return list(slots)


ADAPTERS = {"yamcs": YamcsCredentialAdapter()}


def credential_slots(manifest):
    definition = manifest.get("credential_requirements")
    if definition is None:
        return {}
    if (
        type(definition) is not dict or set(definition) != {"version", "slots"}
        or type(definition["version"]) is not int or definition["version"] != 1
        or type(definition["slots"]) is not dict
    ):
        raise ValueError("Unsupported action credential requirements.")
    if not definition["slots"]:
        return {}
    adapter = ADAPTERS.get(resolve_action_type(manifest).lower())
    if adapter is None:
        raise ValueError("Personal credentials are not supported for this action type.")
    for slot, requirement in definition["slots"].items():
        if (
            slot not in adapter.slots or type(requirement) is not dict
            or set(requirement) != {"source", "auth_type"} or requirement["source"] != "personal"
            or requirement["auth_type"] not in adapter.slots[slot]
        ):
            raise ValueError("Unsupported action credential slot.")
    return deepcopy(definition["slots"])


def validate_credential_requirements(manifest):
    slots = credential_slots(manifest)
    if slots:
        adapter = ADAPTERS[resolve_action_type(manifest).lower()]
        adapter.validate(manifest, slots)
        adapter.destination(manifest)
    return slots


def credential_fingerprint(manifest):
    origin = get_action_origin(manifest)
    if origin is None or not origin.action_id:
        raise ActionCredentialError("trusted_origin_required")
    slots = validate_credential_requirements(manifest)
    payload = {
        "origin": [origin.scope_type, origin.scope_id, origin.action_id],
        "slots": slots,
        "destination": ADAPTERS[resolve_action_type(manifest).lower()].destination(manifest),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def destination_label(manifest):
    adapter = ADAPTERS[resolve_action_type(manifest).lower()]
    target = urlsplit(adapter.destination(manifest)["endpoint"])
    return f"{target.hostname}:{target.port}" if target.port else target.hostname
