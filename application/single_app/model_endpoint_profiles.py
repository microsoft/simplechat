# model_endpoint_profiles.py
"""Named Custom endpoint contracts, distinct from their wire API types."""

import math
from urllib.parse import urlsplit


GENAI_MIL_PROFILE = "genai_mil"
GENAI_MIL_API_BASE = "https://api.genai.mil/v1"
GENAI_MIL_PORTAL = "https://genai.mil/stark/"
GENAI_MIL_CAPABILITIES = {
    "processesText": True, "generatesText": True, "supportsStreaming": True,
    "toolCalling": False, "processesImages": False, "generatesImages": False,
    "processesAudio": False, "generatesAudio": False, "processesVideo": False,
    "generatesVideo": False, "processesBinaryFiles": False,
    "structuredOutput": False, "reasoning": False,
}


class ModelEndpointProfileError(ValueError):
    """A user-safe profile configuration error."""


class GenAIMilRequestError(RuntimeError):
    def __init__(self, status_code, *, retry_after=None, reference=None):
        messages = {
            401: ("genai_key_action_required", f"GenAI.mil API key requires user action. Unlock it in the approved portal ({GENAI_MIL_PORTAL}) or review the configured key."),
            403: ("genai_model_denied", "The configured GenAI.mil key is not permitted to use this model."),
            404: ("genai_model_unavailable", "The selected GenAI.mil model is unavailable or not enabled."),
            429: ("genai_rate_limited", "GenAI.mil rate limit reached. Retry later."),
            502: ("genai_upstream_failure", "GenAI.mil reported an upstream failure. Retry the request later."),
        }
        self.code, message = messages.get(status_code, ("genai_request_failed", "The GenAI.mil request could not be completed."))
        self.status_code = status_code
        self.retry_after = retry_after
        self.reference = reference
        if retry_after is not None:
            message += f" Wait at least {retry_after} seconds before retrying."
        if reference:
            message += f" (reference {reference})"
        self.public_message = message
        super().__init__(message)

    @property
    def payload(self):
        result = {"error": self.public_message, "error_code": self.code}
        if self.retry_after is not None:
            result["retry_after_seconds"] = self.retry_after
        if self.status_code == 401:
            result["portal_url"] = GENAI_MIL_PORTAL
        return result


def get_custom_endpoint_profile_options():
    return [
        {"id": "", "name": "Generic Custom", "default_endpoint": ""},
        {"id": GENAI_MIL_PROFILE, "name": "GenAI.mil", "default_endpoint": GENAI_MIL_API_BASE},
    ]


def get_custom_endpoint_profile(endpoint):
    profile = endpoint.get("profile") or ""
    if not isinstance(profile, str) or profile not in ("", GENAI_MIL_PROFILE):
        raise ModelEndpointProfileError("Choose a supported Custom endpoint profile.")
    if profile and endpoint.get("provider") != "custom":
        raise ModelEndpointProfileError("Named Custom profiles require the Custom provider.")
    return profile


def profile_origin(endpoint):
    parsed = urlsplit(str((endpoint.get("connection") or {}).get("endpoint") or ""))
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ModelEndpointProfileError("GenAI.mil requires an HTTPS API base without embedded credentials.")
    return f"https://{parsed.hostname.lower()}" + (f":{parsed.port}" if parsed.port not in (None, 443) else "")


def merge_profile_credential_approval(existing, incoming, merged):
    profile = get_custom_endpoint_profile(merged)
    merged.pop("credential_origin_approved", None)
    if profile != GENAI_MIL_PROFILE:
        if "profile" in incoming:
            merged.pop("approved_origin", None)
        return
    origin = profile_origin(merged)
    old_profile = get_custom_endpoint_profile(existing)
    old_origin = profile_origin(existing) if old_profile == GENAI_MIL_PROFILE else ""
    incoming_auth = incoming.get("auth") or {}
    fresh_key = any(
        isinstance(incoming_auth.get(field), str)
        and incoming_auth[field].strip() and set(incoming_auth[field].strip()) != {"*"}
        for field in ("api_key", "bearer_token")
    )
    default_origin = "https://api.genai.mil"
    if existing and old_profile != GENAI_MIL_PROFILE and not fresh_key:
        raise ModelEndpointProfileError("Enter the GenAI.mil key explicitly when changing an existing endpoint to this profile.")
    if origin != old_origin and (old_origin or origin != default_origin):
        if incoming.get("credential_origin_approved") is not True or not fresh_key:
            raise ModelEndpointProfileError("Changing the GenAI.mil API origin requires explicit approval and re-entry of the key.")
    merged["approved_origin"] = origin


def validate_genai_profile(endpoint, *, require_approval=True):
    if get_custom_endpoint_profile(endpoint) != GENAI_MIL_PROFILE:
        return
    if endpoint.get("routing_schema_version") != 2:
        raise ModelEndpointProfileError("GenAI.mil requires explicit model routing.")
    origin = profile_origin(endpoint)
    if require_approval and endpoint.get("approved_origin") != origin:
        raise ModelEndpointProfileError("Save and approve the GenAI.mil API origin before using its stored credential.")
    auth = endpoint.get("auth") or {}
    if auth.get("type") not in ("api_key", "key", "bearer"):
        raise ModelEndpointProfileError("GenAI.mil uses a scoped API key or bearer key, not Azure identity or OAuth2.")
    if auth.get("api_key_header") not in (None, "", "Authorization") or auth.get("api_key_prefix") not in (None, "Bearer"):
        raise ModelEndpointProfileError("GenAI.mil keys must use Authorization with the Bearer prefix.")
    for model in endpoint.get("models") or []:
        if model.get("api_type") != "openai":
            raise ModelEndpointProfileError("GenAI.mil supports OpenAI-compatible Chat Completions only.")


def prepare_genai_request(request):
    """Project SDK defaults; reject unsupported semantic operations, never drop them."""
    extra = request.get("extra_body") or {}
    if not isinstance(extra, dict):
        raise ModelEndpointProfileError("Invalid GenAI.mil request extensions.")
    if set(extra) - {"model", "messages", "temperature", "max_tokens", "stream"}:
        raise ModelEndpointProfileError("GenAI.mil request extensions must use documented fields only.")
    payload = {**request, **extra}
    if payload.get("tools") or payload.get("functions") or payload.get("tool_choice") not in (None, "", "none"):
        raise ModelEndpointProfileError("GenAI.mil tools and function calling are not supported by the documented contract.")
    if payload.get("response_format") not in (None, {"type": "text"}) or payload.get("audio") or payload.get("modalities"):
        raise ModelEndpointProfileError("GenAI.mil structured, image, and audio output are not supported by the documented contract.")
    messages = payload.get("messages")
    if not isinstance(messages, (list, tuple)) or not messages:
        raise ModelEndpointProfileError("GenAI.mil requires text chat messages.")
    projected_messages = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in ("system", "user", "assistant"):
            raise ModelEndpointProfileError("GenAI.mil supports system, user, and assistant text messages only.")
        content = message.get("content")
        if isinstance(content, (list, tuple)):
            if any(not isinstance(part, dict) or part.get("type") != "text" or not isinstance(part.get("text"), str) for part in content):
                raise ModelEndpointProfileError("GenAI.mil vision and non-text content are not supported by the documented contract.")
            content = "\n".join(part["text"] for part in content)
        if not isinstance(content, str) or message.get("tool_calls") or message.get("function_call"):
            raise ModelEndpointProfileError("GenAI.mil requires text messages without tool calls.")
        projected_messages.append({"role": message["role"], "content": content})
    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        raise ModelEndpointProfileError("GenAI.mil requires the selected model identifier.")
    stream = payload.get("stream", False)
    if type(stream) is not bool:
        raise ModelEndpointProfileError("GenAI.mil stream must be a Boolean.")
    result = {"model": model, "messages": projected_messages, "stream": stream}
    temperature = payload.get("temperature")
    if temperature is not None:
        if type(temperature) not in (int, float) or not math.isfinite(temperature) or not 0 <= temperature <= 2:
            raise ModelEndpointProfileError("GenAI.mil temperature must be a finite number between 0 and 2.")
        result["temperature"] = temperature
    ceiling = payload.get("max_tokens", payload.get("max_completion_tokens"))
    if payload.get("max_tokens") is not None and payload.get("max_completion_tokens") not in (None, payload["max_tokens"]):
        raise ModelEndpointProfileError("GenAI.mil generation limits must not conflict.")
    if ceiling is not None:
        if type(ceiling) is not int or ceiling <= 0:
            raise ModelEndpointProfileError("GenAI.mil max_tokens must be a positive whole number.")
        result["max_tokens"] = ceiling
    return result
