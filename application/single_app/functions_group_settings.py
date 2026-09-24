# functions_group_settings.py
"""Native group settings: the settings read and its writes.

This backs ``GET /api/groups/<group_id>/settings`` and the writes under it, in
``route_backend_group_settings``. The classic ``PATCH``/``PUT /api/groups/<group_id>``,
``PATCH /api/groups/<group_id>/download-settings``, ``POST /api/groups/<group_id>/logo``
and ``POST /api/retention-policy/group/<group_id>`` are separate and keep their own
behavior.

Access
------
The group must exist (404) and the caller must be one of its members (403). Every
operation is then decided by ``group_settings_decisions``, the decision the read
publishes as ``settings_management``, and a refusal carries that decision's reason
as its ``error_code``. The read itself needs the owner or an admin, as the classic
settings tab does.

The read
--------
It is built from the stored group fields with the shared helpers, never from the
classic details payload, so it carries no owner email and no member lists:

- ``profile``: the name, the description and the hero color, normalized as the
  classic pages show it;
- ``logo``: whether one is stored, its version and its URL;
- ``downloads``: present only when the administrator allows file downloads for the
  group, with the group's own switch;
- ``retention``: present only when group retention policies are on. Each value is
  what the retention job resolves it as: a number of days, ``"none"`` or
  ``"default"`` (the organization default, which a missing value also means). The
  settings' bounds and organization defaults come with it.

Revisions
---------
Each section carries a ``revision``, a digest of that section's stored fields only.
Every write names the revision it was opened at and is refused with 409
``group_settings_changed`` when the stored section has moved on, so two editors
never silently overwrite each other. Membership and every other group field are
outside every section, so a change to them never refuses a settings write, and the
write keeps it. Classic saves carry no revision, so a classic save landing after a
native one still wins; that is recorded, not prevented.

Writes
------
The caller, the operation and the body are checked on a first read, so a refusal
never depends on the body. The write then goes through
``update_group_document_with_etag_guard``: a concurrent change is re-read and kept,
and the caller's role, the operation, the group status and the section revision are
checked again on the copy being written. A group deleted mid-write is 404 and never
recreated; one that keeps changing is 409 ``group_write_conflict``.

- The profile write accepts any of ``name``, ``description`` and ``hero_color``. A
  value equal to the stored one is kept as it is, so an editor can send its whole
  form back even when a stored name predates the length and character limits. A
  changed name or description is held to the group creation limits and messages.
  The hero color is normalized as the classic write does it: text that is not a
  ``#RRGGBB`` color keeps the stored color.
- The logo write accepts a PNG or JPEG ``logo_file``, processed by the shared
  branding helper, and refuses a logo too large to store on the group document.
  Removing the logo clears it, as a new group stores no logo, and like an upload it
  increments ``logoVersion`` so a cached image is not reused.
- The downloads write takes ``disable_file_downloads`` as a boolean only.
- The retention write merges the values it is sent into the stored policy. Each is a
  whole number of days within the configured bounds, ``"none"`` or ``"default"``.

The cache and audit effects are the classic writers': the profile and downloads
writes bump the chat bootstrap cache with ``group_updated``, the logo and retention
writes bump nothing, and none of them records an activity event or a notification.
Every response is ``no-store``, and every failure is a stable, data-free message
with an ``error_code``.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from urllib.parse import quote

from flask import jsonify, request
from werkzeug.exceptions import HTTPException

from functions_appinsights import log_event
from functions_group import (
    GroupDocumentWriteConflict,
    find_group_by_id,
    get_user_role_in_group,
    update_group_document_with_etag_guard,
)
from functions_group_directory import (
    GROUP_DIRECTORY_REQUEST_MESSAGE,
    GROUP_NOT_FOUND_MESSAGE,
    GROUP_WRITE_CONFLICT_MESSAGE,
    GroupDirectoryError,
    _require_group_id,
    _require_user_id,
    current_session_roles,
    read_strict_json_object,
    reject_query_parameters,
    validate_group_description,
    validate_group_name,
)
from functions_group_directory_policy import GROUP_CREATION_ROLE_REQUIRED
from functions_group_settings_policy import (
    GROUP_DOWNLOADS_NOT_ENABLED,
    GROUP_MANAGER_REQUIRED,
    GROUP_OWNER_REQUIRED,
    GROUP_RETENTION_DISABLED,
    GROUP_SETTINGS_MANAGER_ROLES,
    GROUP_STATUS_UNAVAILABLE,
    build_group_settings_management,
    group_retention_enabled,
    group_settings_decisions,
)
from functions_settings import (
    get_settings,
    is_group_workspace_file_download_admin_enabled,
    is_group_workspace_file_download_enabled,
)
from functions_workspace_branding import (
    DEFAULT_WORKSPACE_HERO_COLOR,
    get_workspace_logo_metadata,
    is_allowed_workspace_logo_file,
    normalize_workspace_hero_color,
    prepare_workspace_logo_image_for_storage,
)


GROUP_SETTINGS_SCHEMA_VERSION = 1
GROUP_SETTINGS_SECTIONS = ("profile", "logo", "downloads", "retention")
GROUP_PROFILE_FIELDS = ("name", "description", "hero_color")
GROUP_RETENTION_FIELDS = ("conversation_retention_days", "document_retention_days")
GROUP_KNOWN_STATUSES = ("active", "locked", "upload_disabled", "inactive")
# The logo is stored inline on the group document, which also carries membership and
# every other group setting, so a stored logo is kept well under the 2 MB item limit.
GROUP_LOGO_MAX_STORED_LENGTH = 1024 * 1024
# The classic defaults for the retention bounds (functions_settings) and for the
# organization's group defaults (the retention job's own fallback).
RETENTION_BOUND_DEFAULTS = {"min_days": 1, "max_days": 3650}

GROUP_ACCESS_DENIED_MESSAGE = "You do not have access to the selected group."
GROUP_SETTINGS_CHANGED_MESSAGE = "These settings changed since you opened them. Reload them before saving."
GROUP_SETTINGS_UNAVAILABLE_MESSAGE = "The group settings request could not be completed. Try again."
NO_GROUP_LOGO_MESSAGE = "This group has no logo to remove."
REFUSAL_MESSAGES = {
    GROUP_OWNER_REQUIRED: "Only the group owner can do this.",
    GROUP_MANAGER_REQUIRED: "Only the group owner or an admin can do this.",
    GROUP_CREATION_ROLE_REQUIRED: "You need the CreateGroups role to change this group's name, description or color.",
    GROUP_STATUS_UNAVAILABLE: "This group is locked or inactive, so its name, description, color and logo can't be changed.",
    GROUP_DOWNLOADS_NOT_ENABLED: "An administrator hasn't turned on file downloads for this group.",
    GROUP_RETENTION_DISABLED: "Retention policies aren't turned on for group workspaces.",
}
RETENTION_LABELS = {"conversation_retention_days": "Conversation", "document_retention_days": "Document"}


class GroupSettingsError(GroupDirectoryError):
    """A stable, non-sensitive failure at the group settings boundary.

    It is a ``GroupDirectoryError`` so the strict request helpers shared with the
    group directory raise errors this boundary already answers.
    """


def _invalid(message):
    return GroupSettingsError(message, 400, error_code="invalid_request")


def _group_not_found():
    return GroupSettingsError(GROUP_NOT_FOUND_MESSAGE, 404, error_code="group_not_found")


def refusal(reason):
    """The 403 for a ``group_settings_decisions`` reason."""
    return GroupSettingsError(REFUSAL_MESSAGES[reason], 403, error_code=reason)


def group_settings_error_response(error):
    """Map boundary errors to stable responses; anything else is a logged, generic 500."""
    if isinstance(error, GroupDirectoryError):
        payload, status = {"error": error.description, **error.fields}, error.code
    elif isinstance(error, HTTPException) and isinstance(error.code, int) and 400 <= error.code < 500:
        payload, status = {"error": GROUP_DIRECTORY_REQUEST_MESSAGE, "error_code": "invalid_request"}, error.code
    else:
        log_event(
            "[WORKSPACE_ROUTE] Group settings request failed.",
            extra={"error_type": type(error).__name__},
            level=logging.ERROR,
        )
        payload, status = {
            "error": GROUP_SETTINGS_UNAVAILABLE_MESSAGE,
            "error_code": "group_settings_unavailable",
        }, 500
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, status


def no_store(payload, status):
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, status


def _stored_timestamp():
    """The ``modifiedDate`` format the classic group writers store."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------

def load_group_for_member(user_id, group_id):
    """Return ``(group, role)`` for a member of an existing group, or raise its 404 or 403."""
    _require_group_id(group_id)
    group = find_group_by_id(group_id)
    if not group:
        raise _group_not_found()
    return group, caller_role(group, user_id)


def caller_role(group, user_id):
    role = get_user_role_in_group(group, user_id)
    if not role:
        raise GroupSettingsError(GROUP_ACCESS_DENIED_MESSAGE, 403, error_code="group_access_denied")
    return role


def require_operation(group, role, settings, roles, operation):
    """Refuse unless ``group_settings_decisions`` allows ``operation``."""
    reason = group_settings_decisions(role, group, settings, roles)[operation]
    if reason is not None:
        raise refusal(reason)


def require_manager(role):
    if role not in GROUP_SETTINGS_MANAGER_ROLES:
        raise refusal(GROUP_MANAGER_REQUIRED)


# ---------------------------------------------------------------------------
# Revisions
# ---------------------------------------------------------------------------

def _section_fields(group, section):
    if section == "profile":
        return {"name": group.get("name"), "description": group.get("description"), "heroColor": group.get("heroColor")}
    if section == "logo":
        return {"logoVersion": group.get("logoVersion"), "hasLogo": get_workspace_logo_metadata(group)["hasLogo"]}
    if section == "downloads":
        return {"disable_file_downloads": group.get("disable_file_downloads")}
    if section == "retention":
        return {"retention_policy": group.get("retention_policy")}
    raise ValueError(f"Unknown group settings section: {section}")


def section_revision(group, section):
    """A digest of one section's stored fields, which changes whenever any of them does."""
    encoded = json.dumps(
        {"section": section, "fields": _section_fields(group, section)},
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def require_revision(group, section, revision):
    if section_revision(group, section) != revision:
        raise GroupSettingsError(GROUP_SETTINGS_CHANGED_MESSAGE, 409, error_code="group_settings_changed")


# ---------------------------------------------------------------------------
# The read
# ---------------------------------------------------------------------------

def _text(value):
    return value if isinstance(value, str) else ""


def _status(group):
    status = group.get("status", "active")
    return status if status in GROUP_KNOWN_STATUSES else "unknown"


def resolved_retention_value(value):
    """A stored retention value as the retention job resolves it (``resolve_retention_value``)."""
    if value is None or value == "" or value == "default":
        return "default"
    if value == "none":
        return "none"
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return "none"


def _organization_default(value):
    """An organization default as the retention job reads it: days, or ``"none"``."""
    if value is None or value == "none":
        return "none"
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return "none"


def retention_bounds(settings, kind):
    """``(min_days, max_days)`` for ``conversation`` or ``document`` retention."""
    bounds = []
    for bound in ("min_days", "max_days"):
        value = settings.get(f"retention_{kind}_{bound}", RETENTION_BOUND_DEFAULTS[bound])
        if isinstance(value, bool):
            value = RETENTION_BOUND_DEFAULTS[bound]
        try:
            bounds.append(int(value))
        except (TypeError, ValueError, OverflowError):
            bounds.append(RETENTION_BOUND_DEFAULTS[bound])
    return bounds[0], bounds[1]


def build_group_settings(group, role, settings, session_roles):
    """The settings read for a caller who holds ``role`` in ``group``."""
    group_id = _text(group.get("id"))
    logo = get_workspace_logo_metadata(group)
    payload = {
        "schema_version": GROUP_SETTINGS_SCHEMA_VERSION,
        "group_id": group_id,
        "viewer_role": role,
        "status": _status(group),
        "profile": {
            "name": _text(group.get("name")),
            "description": _text(group.get("description")),
            "hero_color": normalize_workspace_hero_color(group.get("heroColor"), DEFAULT_WORKSPACE_HERO_COLOR),
            "revision": section_revision(group, "profile"),
        },
        "logo": {
            "has_logo": logo["hasLogo"],
            "logo_version": logo["logoVersion"],
            "logo_url": (
                f"/api/groups/{quote(group_id, safe='')}/logo?v={logo['logoVersion']}" if logo["hasLogo"] else None
            ),
            "revision": section_revision(group, "logo"),
        },
        "settings_management": build_group_settings_management(role, group, settings, session_roles),
    }
    if is_group_workspace_file_download_admin_enabled(settings, group):
        payload["downloads"] = {
            "disable_file_downloads": bool(group.get("disable_file_downloads", False)),
            "file_downloads_enabled": is_group_workspace_file_download_enabled(settings, group),
            "revision": section_revision(group, "downloads"),
        }
    if group_retention_enabled(settings):
        policy = group.get("retention_policy") if isinstance(group.get("retention_policy"), dict) else {}
        conversation_bounds = retention_bounds(settings, "conversation")
        document_bounds = retention_bounds(settings, "document")
        payload["retention"] = {
            "conversation_retention_days": resolved_retention_value(policy.get("conversation_retention_days")),
            "document_retention_days": resolved_retention_value(policy.get("document_retention_days")),
            "bounds": {
                "conversation": {"min_days": conversation_bounds[0], "max_days": conversation_bounds[1]},
                "document": {"min_days": document_bounds[0], "max_days": document_bounds[1]},
            },
            "organization_defaults": {
                "conversation_retention_days": _organization_default(
                    settings.get("default_retention_conversation_group", "none")
                ),
                "document_retention_days": _organization_default(
                    settings.get("default_retention_document_group", "none")
                ),
            },
            "revision": section_revision(group, "retention"),
        }
    return payload


def read_group_settings(user_id, group_id):
    """Return ``({"settings": ...}, 200)`` for the owner or an admin."""
    user_id = _require_user_id(user_id)
    reject_query_parameters()
    group, role = load_group_for_member(user_id, group_id)
    require_manager(role)
    return {"settings": build_group_settings(group, role, get_settings(), current_session_roles())}, 200


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def _write(group_id, apply_changes, *, cache_reason):
    try:
        committed = update_group_document_with_etag_guard(group_id, apply_changes, cache_reason=cache_reason)
    except GroupDocumentWriteConflict as error:
        raise GroupSettingsError(GROUP_WRITE_CONFLICT_MESSAGE, 409, error_code="group_write_conflict") from error
    if committed is None:
        raise _group_not_found()
    return committed


def _written_settings(committed, user_id, settings, roles):
    return {"settings": build_group_settings(committed, caller_role(committed, user_id), settings, roles)}, 200


def _read_revision(body):
    revision = body.get("revision")
    if not isinstance(revision, str) or not revision:
        raise _invalid("Include the revision of the settings you loaded.")
    return revision


def _read_body(allowed_fields, unknown_message):
    body = read_strict_json_object()
    if any(key not in ("revision", *allowed_fields) for key in body):
        raise _invalid(unknown_message)
    return body, _read_revision(body)


def _profile_changes(group, body):
    """The profile fields the body changes, validated against ``group``'s stored values."""
    changes = {}
    if "name" in body:
        name = body["name"]
        changes["name"] = name if name == group.get("name") else validate_group_name(name)
    if "description" in body:
        description = body["description"]
        changes["description"] = (
            description if description == group.get("description") else validate_group_description(description)
        )
    if "hero_color" in body:
        hero_color = body["hero_color"]
        if not isinstance(hero_color, str):
            raise _invalid("The hero color must be text, such as #0078d4.")
        changes["heroColor"] = normalize_workspace_hero_color(
            hero_color, group.get("heroColor", DEFAULT_WORKSPACE_HERO_COLOR),
        )
    return changes


PROFILE_OPERATIONS_BY_FIELD = {"name": "edit_name", "description": "edit_description", "hero_color": "edit_color"}


def update_group_profile(user_id, group_id):
    """Change the name, description or hero color and return ``({"settings": ...}, 200)``."""
    user_id = _require_user_id(user_id)
    reject_query_parameters()
    settings, roles = get_settings(), current_session_roles()
    group, role = load_group_for_member(user_id, group_id)
    for operation in PROFILE_OPERATIONS_BY_FIELD.values():
        require_operation(group, role, settings, roles, operation)
    body, revision = _read_body(
        GROUP_PROFILE_FIELDS, "Only the name, description and hero_color can be changed here.",
    )
    if not any(field in body for field in GROUP_PROFILE_FIELDS):
        raise _invalid("Include a name, description or hero_color to change.")
    _profile_changes(group, body)

    def apply(fresh):
        fresh_role = caller_role(fresh, user_id)
        for field, operation in PROFILE_OPERATIONS_BY_FIELD.items():
            if field in body:
                require_operation(fresh, fresh_role, settings, roles, operation)
        require_revision(fresh, "profile", revision)
        fresh.update(_profile_changes(fresh, body))
        fresh["modifiedDate"] = _stored_timestamp()
        return fresh

    return _written_settings(_write(group_id, apply, cache_reason="group_updated"), user_id, settings, roles)


def _read_logo_upload():
    if request.mimetype != "multipart/form-data":
        raise _invalid("Upload the logo as multipart form data with a logo_file and the logo revision.")
    if set(request.form.keys()) - {"revision"} or set(request.files.keys()) - {"logo_file"}:
        raise _invalid("Only a logo_file and the logo revision can be sent.")
    if len(request.form.getlist("revision")) > 1 or len(request.files.getlist("logo_file")) > 1:
        raise _invalid("Send one logo_file and one revision.")
    revision = _read_revision({"revision": request.form.get("revision")})
    logo_file = request.files.get("logo_file")
    if logo_file is None or not logo_file.filename:
        raise _invalid("Choose a PNG or JPEG image for the logo.")
    if not is_allowed_workspace_logo_file(logo_file.filename):
        raise _invalid("The logo must be a PNG or JPEG image.")
    return logo_file, revision


def _prepared_logo(logo_file):
    """The stored form of an uploaded logo, or a data-free 400 when it can't be used."""
    try:
        processed = prepare_workspace_logo_image_for_storage(logo_file.read(), logo_file.filename)
    except Exception as error:  # noqa: BLE001 - any decoding failure of an untrusted image is the same 400
        raise _invalid("The logo image could not be read. Upload a PNG or JPEG image.") from error
    stored = processed.get("base64_str") if isinstance(processed, dict) else None
    if not isinstance(stored, str) or not stored:
        raise _invalid("The logo image could not be read. Upload a PNG or JPEG image.")
    if len(stored) > GROUP_LOGO_MAX_STORED_LENGTH:
        raise _invalid("This logo is too large to store. Use a smaller image.")
    return stored


def replace_group_logo(user_id, group_id):
    """Store a new logo and return ``({"settings": ...}, 200)``."""
    user_id = _require_user_id(user_id)
    reject_query_parameters()
    settings, roles = get_settings(), current_session_roles()
    group, role = load_group_for_member(user_id, group_id)
    require_operation(group, role, settings, roles, "edit_logo")
    logo_file, revision = _read_logo_upload()
    stored_logo = _prepared_logo(logo_file)

    def apply(fresh):
        require_operation(fresh, caller_role(fresh, user_id), settings, roles, "edit_logo")
        require_revision(fresh, "logo", revision)
        fresh["logoBase64"] = stored_logo
        fresh["logoVersion"] = get_workspace_logo_metadata(fresh)["logoVersion"] + 1
        fresh["modifiedDate"] = _stored_timestamp()
        return fresh

    return _written_settings(_write(group_id, apply, cache_reason=None), user_id, settings, roles)


def remove_group_logo(user_id, group_id):
    """Clear the logo and return ``({"settings": ...}, 200)``."""
    user_id = _require_user_id(user_id)
    reject_query_parameters()
    settings, roles = get_settings(), current_session_roles()
    group, role = load_group_for_member(user_id, group_id)
    require_operation(group, role, settings, roles, "edit_logo")
    _body, revision = _read_body((), "Only the logo revision can be sent to remove the logo.")

    def apply(fresh):
        require_operation(fresh, caller_role(fresh, user_id), settings, roles, "edit_logo")
        require_revision(fresh, "logo", revision)
        if not get_workspace_logo_metadata(fresh)["hasLogo"]:
            raise GroupSettingsError(NO_GROUP_LOGO_MESSAGE, 409, error_code="no_group_logo")
        fresh["logoBase64"] = ""
        fresh["logoVersion"] = get_workspace_logo_metadata(fresh)["logoVersion"] + 1
        fresh["modifiedDate"] = _stored_timestamp()
        return fresh

    return _written_settings(_write(group_id, apply, cache_reason=None), user_id, settings, roles)


def update_group_downloads(user_id, group_id):
    """Set the group's ``disable_file_downloads`` switch and return ``({"settings": ...}, 200)``."""
    user_id = _require_user_id(user_id)
    reject_query_parameters()
    settings, roles = get_settings(), current_session_roles()
    group, role = load_group_for_member(user_id, group_id)
    require_operation(group, role, settings, roles, "edit_downloads")
    body, revision = _read_body(
        ("disable_file_downloads",), "Only disable_file_downloads can be changed here.",
    )
    disabled = body.get("disable_file_downloads")
    if not isinstance(disabled, bool):
        raise _invalid("Set disable_file_downloads to true or false.")

    def apply(fresh):
        require_operation(fresh, caller_role(fresh, user_id), settings, roles, "edit_downloads")
        require_revision(fresh, "downloads", revision)
        fresh["disable_file_downloads"] = disabled
        fresh["modifiedDate"] = _stored_timestamp()
        return fresh

    return _written_settings(_write(group_id, apply, cache_reason="group_updated"), user_id, settings, roles)


def _retention_value(field, value, settings):
    label = RETENTION_LABELS[field]
    if isinstance(value, str) and value in ("none", "default"):
        return value
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(f'{label} retention must be a whole number of days, "none" or "default".')
    minimum, maximum = retention_bounds(settings, "conversation" if field.startswith("conversation") else "document")
    if value < minimum or value > maximum:
        raise _invalid(f"{label} retention must be between {minimum} and {maximum} days.")
    return value


def update_group_retention(user_id, group_id):
    """Merge retention values into the stored policy and return ``({"settings": ...}, 200)``."""
    user_id = _require_user_id(user_id)
    reject_query_parameters()
    settings, roles = get_settings(), current_session_roles()
    group, role = load_group_for_member(user_id, group_id)
    require_operation(group, role, settings, roles, "edit_retention")
    body, revision = _read_body(
        GROUP_RETENTION_FIELDS,
        "Only conversation_retention_days and document_retention_days can be changed here.",
    )
    values = {field: _retention_value(field, body[field], settings) for field in GROUP_RETENTION_FIELDS if field in body}
    if not values:
        raise _invalid("Include conversation_retention_days or document_retention_days to change.")

    def apply(fresh):
        require_operation(fresh, caller_role(fresh, user_id), settings, roles, "edit_retention")
        require_revision(fresh, "retention", revision)
        stored = fresh.get("retention_policy")
        policy = dict(stored) if isinstance(stored, dict) else {}
        policy.update(values)
        fresh["retention_policy"] = policy
        fresh["modifiedDate"] = _stored_timestamp()
        return fresh

    return _written_settings(_write(group_id, apply, cache_reason=None), user_id, settings, roles)
