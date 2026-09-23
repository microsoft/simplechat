# functions_model_catalog.py
"""Reusable model profiles. No credentials, storage clients, or settings imports."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
import uuid
from urllib.parse import urlsplit

from functions_model_capabilities import (
    CAPABILITY_FIELD_NAMES,
    get_model_capability_catalog_records,
    get_model_capability_catalog_sources,
    project_model_budget_metadata,
)


CATALOG_SETTINGS_KEY = "model_catalog"
PROFILE_LINK = "catalogProfileId"
TASKS = {
    "general": "General answering",
    "summarization": "Summarization",
    "extraction": "Extraction",
    "classification": "Classification",
    "coding": "Coding",
    "reasoning": "Reasoning",
    "analysis": "Document analysis",
    "comparison": "Document comparison",
    "data_analysis": "Structured data analysis",
    "vision": "Image understanding",
    "tool_use": "Tool use",
    "planning": "Planning",
}
PRIORITIES = {"preferred": 2, "standard": 1, "lower": 0}
SUITABILITY = {"unknown": 0, "suitable": 1, "strong": 2, "unsuitable": -1}
PROFILE_FIELDS = {
    "displayName", "publisher", "summary", "strengths", "limitations",
    "tasks", "capabilities", "sources", "aliases", "archived",
}
MAX_CUSTOM_PROFILES = 200
MAX_CATALOG_BYTES = 512 * 1024
ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,159}$")


class ModelCatalogError(ValueError):
    """A stable, user-safe profile validation error."""

    def __init__(self, message, field="catalog", code="invalid_model_profile"):
        super().__init__(message)
        self.public_message = message
        self.field = field
        self.code = code


def _text(value, field, maximum=1000, *, required=False):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ModelCatalogError(f"{field} must be text of at most {maximum} characters.", field)
    return value.strip()


def _strings(value, field, maximum=12):
    if not isinstance(value, list) or len(value) > maximum:
        raise ModelCatalogError(f"{field} must contain at most {maximum} entries.", field)
    result = [_text(item, field, 500, required=True) for item in value]
    if len(set(result)) != len(result):
        raise ModelCatalogError(f"{field} contains duplicate entries.", field)
    return result


def validate_profile_link(value):
    if value in (None, ""):
        return ""
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ModelCatalogError("Choose a valid catalog profile.", PROFILE_LINK)
    return value


def normalize_custom_profile(payload):
    if not isinstance(payload, dict) or set(payload) - PROFILE_FIELDS:
        raise ModelCatalogError("The profile contains unsupported fields.")
    profile = {
        "displayName": _text(payload.get("displayName"), "displayName", 160, required=True),
        "publisher": _text(payload.get("publisher", ""), "publisher", 120),
        "summary": _text(payload.get("summary", ""), "summary", 1200),
        "strengths": _strings(payload.get("strengths", []), "strengths"),
        "limitations": _strings(payload.get("limitations", []), "limitations"),
        "aliases": _strings(payload.get("aliases", []), "aliases"),
    }
    capabilities = payload.get("capabilities", {})
    if not isinstance(capabilities, dict) or set(capabilities) - set(CAPABILITY_FIELD_NAMES):
        raise ModelCatalogError("Choose supported technical capability fields.", "capabilities")
    if any(type(value) is not bool for value in capabilities.values()):
        raise ModelCatalogError("Capabilities must be true or false; omit unknown values.", "capabilities")
    profile["capabilities"] = dict(capabilities)
    tasks = payload.get("tasks", {})
    if not isinstance(tasks, dict) or set(tasks) - set(TASKS):
        raise ModelCatalogError("Choose a supported task category.", "tasks")
    if any(not isinstance(value, str) or value not in SUITABILITY for value in tasks.values()):
        raise ModelCatalogError("Choose a valid task suitability.", "tasks")
    profile["tasks"] = dict(tasks)
    archived = payload.get("archived", False)
    if type(archived) is not bool:
        raise ModelCatalogError("Archived must be true or false.", "archived")
    profile["archived"] = archived
    sources = _strings(payload.get("sources", []), "sources")
    for source in sources:
        try:
            parsed = urlsplit(source)
            _ = parsed.port
        except ValueError as exc:
            raise ModelCatalogError("Evidence links must be valid HTTPS URLs.", "sources") from exc
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or re.search(r"[\x00-\x20]", source):
            raise ModelCatalogError("Evidence links must be HTTPS URLs without credentials.", "sources")
    profile["sources"] = sources
    return profile


def normalize_preferences(payload):
    if not isinstance(payload, dict) or set(payload) - {"favorite", "priority"}:
        raise ModelCatalogError("Choose favorite and priority preferences.", "preferences")
    favorite, priority = payload.get("favorite", False), payload.get("priority", "standard")
    if type(favorite) is not bool or not isinstance(priority, str) or priority not in PRIORITIES:
        raise ModelCatalogError("Favorite must be boolean and priority must be preferred, standard, or lower.", "preferences")
    return {"favorite": favorite, "priority": priority}


def _revision(profile):
    return hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()[:20]


def built_in_profiles():
    """Capability-derived suitability is not a comparative quality benchmark."""
    result = []
    sources = {source["id"]: source for source in get_model_capability_catalog_sources()}
    for record in get_model_capability_catalog_records():
        capabilities = record.get("capabilities") or {}
        tasks = {}
        if capabilities.get("generatesText") and capabilities.get("processesText"):
            tasks["general"] = "suitable"
        for task, capability in (
            ("coding", "optimizedForCoding"), ("reasoning", "reasoning"),
            ("vision", "processesImages"), ("tool_use", "toolCalling"),
            ("extraction", "structuredOutput"),
        ):
            if capabilities.get(capability) is True and capabilities.get("generatesText") is True:
                tasks[task] = "suitable"
        selection = record.get("selectionProfile") or {}
        profile = {
            "id": record["id"], "displayName": record.get("displayName", record["id"]),
            "publisher": record.get("provider", ""), "origin": "built_in",
            "summary": selection.get("summary") or next(iter(record.get("notes") or []), ""),
            "strengths": selection.get("strengths", []),
            "limitations": selection.get("limitations", record.get("notes", [])),
            "tasks": {**tasks, **selection.get("tasks", {})},
            "capabilities": capabilities, "aliases": record.get("aliases", []),
            "sources": selection.get("sources") or [
                sources[key]["url"] for key in record.get("sourceIds", []) if key in sources
            ],
            "evidence": "publisher_documentation" if selection else "capability_derived",
            "archived": False,
            "verifiedAt": selection.get("verifiedAt"),
            "chatCompletions": selection.get("chatCompletions"),
            "technical": {key: deepcopy(record[key]) for key in (
                "contextWindow", "inputTokenLimit", "outputTokenLimit", "tokenLimitEvidence",
                "tokenLimitProfiles", "reasoningPolicy", "embeddingPolicy", "imageProfiles",
                "lifecycle",
            ) if key in record},
        }
        profile["revision"] = _revision(profile)
        result.append(profile)
    return result


def get_effective_model_profiles(settings):
    state = (settings or {}).get(CATALOG_SETTINGS_KEY) or {}
    if not isinstance(state, dict):
        raise ModelCatalogError("Stored model catalog is invalid. Contact an administrator.")
    profiles = built_in_profiles()
    for stored in state.get("profiles", []):
        profile = normalize_custom_profile({key: value for key, value in stored.items() if key in PROFILE_FIELDS})
        profile.update(id=validate_profile_link(stored["id"]), origin="custom", evidence="admin_declared")
        profile["revision"] = _revision(profile)
        profiles.append(profile)
    preferences = state.get("preferences") or {}
    for profile in profiles:
        profile["preferences"] = normalize_preferences(preferences.get(profile["id"], {}))
    return profiles


def find_profile(model, settings, profiles=None):
    profiles = profiles if profiles is not None else get_effective_model_profiles(settings)
    link = validate_profile_link(model.get(PROFILE_LINK))
    if link:
        profile = next((entry for entry in profiles if entry["id"] == link), None)
        if profile is None:
            raise ModelCatalogError("The linked catalog profile is unavailable. Review the AI Connection.", PROFILE_LINK)
        return profile
    identity = str(model.get("modelName") or model.get("deploymentName") or "").casefold()
    # Custom profiles require explicit links. Aliases cannot take over existing models.
    return next((
        entry for entry in profiles if entry["origin"] == "built_in"
        and identity in {str(value).casefold() for value in [entry["id"], *entry["aliases"]]}
    ), None)


def apply_model_profile(model, endpoint, settings, profiles=None):
    """Return effective metadata without changing stored deployment overrides."""
    effective = deepcopy(model)
    profile = find_profile(model, settings, profiles)
    if profile is None:
        return effective
    effective["_catalog_profile"] = profile
    effective["capabilities"] = {
        **profile["capabilities"], **((endpoint or {}).get("capabilities") or {}),
        **(model.get("capabilities") or {}),
    }
    if "processesImages" not in (model.get("capabilities") or {}):
        for key in ("supportsVision", "supports_vision"):
            if type(model.get(key)) is bool:
                effective["capabilities"]["processesImages"] = model[key]
                break
    effective["_catalog_effective_revision"] = _revision({
        "profile": profile["revision"],
        "capabilities": effective["capabilities"],
        "model": project_model_budget_metadata(model),
        "endpoint": project_model_budget_metadata(endpoint),
    })
    return effective


def profile_summary(profile):
    if profile is None:
        return None
    return {key: deepcopy(profile[key]) for key in (
        "id", "displayName", "summary", "tasks", "preferences", "revision",
        "origin", "archived", "evidence",
    )}

def model_profile_projection(model, endpoint, settings, profiles=None):
    """A broken link disables Auto for that row, not every other connected model."""
    profiles = profiles if profiles is not None else get_effective_model_profiles(settings)
    try:
        effective = apply_model_profile(model, endpoint, settings, profiles)
    except ModelCatalogError as exc:
        return {"profile": None, "capabilities": {}, "profile_error": exc.public_message, "auto_routing_available": False}
    profile = effective.get("_catalog_profile")
    return {
        "profile": profile_summary(profile),
        "capabilities": effective.get("capabilities", {}),
        "auto_routing_available": supports_auto_chat(model, settings, profiles),
        "effective_revision": effective.get("_catalog_effective_revision"),
    }


def supports_auto_chat(model, settings, profiles=None):
    """A descriptive custom link cannot override a native API incompatibility."""
    profiles = profiles if profiles is not None else get_effective_model_profiles(settings)
    native = find_profile({key: value for key, value in model.items() if key != PROFILE_LINK}, {}, profiles)
    linked = find_profile(model, settings, profiles)
    return all(profile is None or profile.get("chatCompletions") is not False for profile in (native, linked))


def change_catalog(settings, *, profile_id=None, profile=None, preferences=None):
    """Pure transform suitable for the shared settings store's fenced write."""
    settings = deepcopy(settings)
    current = get_effective_model_profiles(settings)
    if profile is None and preferences is None:
        raise ModelCatalogError("No profile changes were supplied.")
    state = deepcopy(settings.get(CATALOG_SETTINGS_KEY) or {"profiles": [], "preferences": {}})
    state.setdefault("profiles", [])
    state.setdefault("preferences", {})
    if profile_id is None:
        if profile is None or preferences is not None:
            raise ModelCatalogError("A new custom profile is required.")
        profile_id = f"custom:{uuid.uuid4().hex}"
    else:
        validate_profile_link(profile_id)
        if not any(item["id"] == profile_id for item in current):
            raise ModelCatalogError("Catalog profile not found.", code="profile_not_found")
    if profile is not None:
        if not profile_id.startswith("custom:"):
            raise ModelCatalogError("Built-in profiles are read-only. Duplicate one to customize it.")
        normalized = normalize_custom_profile(profile)
        identities = {
            str(value).casefold() for item in current if item["id"] != profile_id
            for value in [item["id"], *item["aliases"]]
        }
        if any(alias.casefold() in identities for alias in normalized["aliases"]):
            raise ModelCatalogError("An alias already belongs to another profile.", "aliases")
        if len({alias.casefold() for alias in normalized["aliases"]}) != len(normalized["aliases"]):
            raise ModelCatalogError("Aliases must be unique regardless of case.", "aliases")
        state["profiles"] = [item for item in state["profiles"] if item["id"] != profile_id]
        state["profiles"].append({**normalized, "id": profile_id})
    if preferences is not None:
        state["preferences"][profile_id] = normalize_preferences(preferences)
    state["updatedAt"] = datetime.now(timezone.utc).isoformat()
    if len(state["profiles"]) > MAX_CUSTOM_PROFILES or len(json.dumps(state).encode()) > MAX_CATALOG_BYTES:
        raise ModelCatalogError("The catalog storage limit has been reached. Reduce profile content.")
    settings[CATALOG_SETTINGS_KEY] = state
    return settings
