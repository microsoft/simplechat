# functions_public_settings.py
"""Native public workspace settings: the settings read and its writes.

This backs ``GET /api/public-workspaces/<workspace_id>/settings`` and the writes under
it, in ``route_backend_public_settings``. The classic ``PATCH``/``PUT
/api/public_workspaces/<ws_id>``, ``PATCH /api/public_workspaces/<ws_id>/download-settings``,
``POST /api/public_workspaces/<ws_id>/logo`` and ``POST
/api/retention-policy/public/<ws_id>`` are separate and keep their own behavior.

Access
------
The workspace must exist (404). Every signed-in caller reads a public workspace as at
least a ``User``, and every operation is then decided by ``public_settings_decisions``,
the decision the read publishes as ``settings_management``. A refusal carries that
decision's reason as its ``error_code``. The read itself needs the owner or an admin,
as the classic settings tab does.

The read
--------
It is built from the stored workspace fields with the shared helpers, never from the
classic details payload, so it carries no owner email and no member list:

- ``profile``: the name, the description and the hero color, normalized as the classic
  pages show it;
- ``logo``: whether one is stored, its version and its URL;
- ``downloads``: present only when the administrator allows file downloads for the
  workspace, with the workspace's own switch;
- ``retention``: present only when public retention policies are on. Each value is
  what the retention job resolves it as: a number of days, ``"none"`` or ``"default"``
  (the organization default, which a missing value also means). The settings' bounds
  and organization defaults come with it.

Revisions
---------
Each section carries a ``revision``, a digest of that section's stored fields only.
Every write names the revision it was opened at and is refused with 409
``public_workspace_settings_changed`` when the stored section has moved on, so two
editors never silently overwrite each other. Membership and every other workspace field
are outside every section, so a change to them never refuses a settings write, and the
write keeps it. Classic saves carry no revision, so a classic save landing after a
native one still wins; that is recorded, not prevented.

Writes
------
The caller, the operation and the body are checked on a first read, so a refusal never
depends on the body. The write then goes through
``update_public_workspace_document_with_etag_guard``: a concurrent change is re-read and
kept, and the caller's role, the operation, the workspace status and the section
revision are checked again on the copy being written. A workspace deleted mid-write is
404 and never recreated; one that keeps changing is 409
``public_workspace_write_conflict``, with the public conflict text.

- The profile write accepts any of ``name``, ``description`` and ``hero_color``. A value
  equal to the stored one is kept as it is, so an editor can send its whole form back
  even when a stored name predates the limits below. A changed name must be text of at
  most 80 characters without control characters, and a changed description text of at
  most 500: the limits the native group settings use, since the classic public routes
  set none. The hero color is normalized as the classic write does it: text that is not
  a ``#RRGGBB`` color keeps the stored color.
- The logo write accepts a PNG or JPEG ``logo_file``, processed by the shared branding
  helper. Any image it cannot read, a decompression bomb included, is the classic
  route's reviewed 400, and a logo too large to store on the workspace document is
  refused. Removing the logo clears it, as a new workspace stores no logo, and like an
  upload it increments ``logoVersion`` so a cached image is not reused.
- The downloads write takes ``disable_file_downloads`` as a boolean only.
- The retention write merges the values it is sent into the stored policy. Each is a
  whole number of days within the configured bounds, ``"none"`` or ``"default"``.

The cache and audit effects are the classic writers': the profile and downloads writes
bump the chat bootstrap cache with ``public_workspace_updated``, the logo and retention
writes bump nothing, and none of them records an activity event or a notification.
Every response is ``no-store``, and every failure is a stable, data-free message with
an ``error_code``; an unexpected one is logged with only its error type and status code.
"""

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import quote

from flask import jsonify, request
from werkzeug.exceptions import HTTPException

from functions_appinsights import log_event
from functions_public_directory import PublicDirectoryError, _require_user_id
from functions_public_settings_policy import (
    PUBLIC_DOWNLOADS_NOT_ENABLED,
    PUBLIC_MANAGER_REQUIRED,
    PUBLIC_MEMBER_REQUIRED,
    PUBLIC_OWNER_REQUIRED,
    PUBLIC_RETENTION_DISABLED,
    PUBLIC_SETTINGS_MANAGER_ROLES,
    PUBLIC_STATUS_UNAVAILABLE,
    build_public_settings_management,
    public_retention_enabled,
    public_settings_decisions,
)
from functions_public_workspaces import (
    PUBLIC_WORKSPACE_WRITE_CONFLICT_CODE,
    PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE,
    PublicWorkspaceDocumentWriteConflict,
    find_public_workspace_by_id,
    get_user_role_in_public_workspace,
    update_public_workspace_document_with_etag_guard,
)
from functions_settings import (
    get_settings,
    is_public_workspace_file_download_admin_enabled,
    is_public_workspace_file_download_enabled,
)
from functions_workspace_branding import (
    DEFAULT_WORKSPACE_HERO_COLOR,
    get_workspace_logo_metadata,
    is_allowed_workspace_logo_file,
    normalize_workspace_hero_color,
    prepare_workspace_logo_image_for_storage,
)


PUBLIC_SETTINGS_SCHEMA_VERSION = 1
PUBLIC_SETTINGS_SECTIONS = ("profile", "logo", "downloads", "retention")
PUBLIC_PROFILE_FIELDS = ("name", "description", "hero_color")
PUBLIC_RETENTION_FIELDS = ("conversation_retention_days", "document_retention_days")
PUBLIC_KNOWN_STATUSES = ("active", "locked", "upload_disabled", "inactive")
PUBLIC_NAME_MAX_LENGTH = 80
PUBLIC_DESCRIPTION_MAX_LENGTH = 500
# The logo is stored inline on the workspace document, which also carries membership
# and every other workspace setting, so a stored logo is kept well under the 2 MB item
# limit.
PUBLIC_LOGO_MAX_STORED_LENGTH = 1024 * 1024
# The classic defaults for the retention bounds (functions_settings).
RETENTION_BOUND_DEFAULTS = {"min_days": 1, "max_days": 3650}

INVALID_PUBLIC_SETTINGS_ID = re.compile(r"[/\\?#,\x00-\x1f\x7f]")
PUBLIC_NAME_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]")

PUBLIC_NOT_FOUND_MESSAGE = "The selected public workspace was not found."
PUBLIC_REQUEST_MESSAGE = "The request could not be processed."
PUBLIC_SETTINGS_CHANGED_MESSAGE = "These settings changed since you opened them. Reload them before saving."
PUBLIC_SETTINGS_UNAVAILABLE_MESSAGE = "The workspace settings request could not be completed. Try again."
# The classic logo route's reviewed text for an image it cannot read (writer-safety R5.4).
PUBLIC_LOGO_UNREADABLE_MESSAGE = "The logo image could not be read. Upload a PNG or JPEG image."
NO_PUBLIC_LOGO_MESSAGE = "This workspace has no logo to remove."
PUBLIC_STATUS_UNRECOGNIZED_MESSAGE = (
    "This workspace's status isn't recognized, so its name, description, color and logo can't be changed."
)
REFUSAL_MESSAGES = {
    PUBLIC_OWNER_REQUIRED: "Only the workspace owner can do this.",
    PUBLIC_MANAGER_REQUIRED: "Only the workspace owner or an admin can do this.",
    PUBLIC_MEMBER_REQUIRED: "Only the workspace owner, an admin or a document manager can do this.",
    PUBLIC_STATUS_UNAVAILABLE: (
        "This workspace is locked or inactive, so its name, description, color and logo can't be changed."
    ),
    PUBLIC_DOWNLOADS_NOT_ENABLED: "An administrator hasn't turned on file downloads for this workspace.",
    PUBLIC_RETENTION_DISABLED: "Retention policies aren't turned on for public workspaces.",
}
RETENTION_LABELS = {"conversation_retention_days": "Conversation", "document_retention_days": "Document"}


class PublicSettingsError(PublicDirectoryError):
    """A stable, non-sensitive failure at the public workspace settings boundary.

    It is a ``PublicDirectoryError`` so the request helpers shared with the public
    directory raise errors this boundary already answers.
    """


def _invalid(message):
    return PublicSettingsError(message, 400, error_code="invalid_request")


def _workspace_not_found():
    return PublicSettingsError(PUBLIC_NOT_FOUND_MESSAGE, 404, error_code="public_workspace_not_found")


def refusal(reason, workspace=None):
    """The 403 for a ``public_settings_decisions`` reason.

    A status refusal names the status that caused it: a locked or inactive workspace, or
    one whose status isn't recognized.
    """
    message = REFUSAL_MESSAGES[reason]
    if reason == PUBLIC_STATUS_UNAVAILABLE and workspace is not None and _status(workspace) == "unknown":
        message = PUBLIC_STATUS_UNRECOGNIZED_MESSAGE
    return PublicSettingsError(message, 403, error_code=reason)


def public_settings_error_response(error):
    """Map boundary errors to stable responses; anything else is a logged, generic 500."""
    if isinstance(error, PublicDirectoryError):
        payload, status = {"error": error.description, **error.fields}, error.code
    elif isinstance(error, HTTPException) and isinstance(error.code, int) and 400 <= error.code < 500:
        payload, status = {"error": PUBLIC_REQUEST_MESSAGE, "error_code": "invalid_request"}, error.code
    else:
        extra = {"error_type": type(error).__name__}
        status_code = getattr(error, "status_code", None)
        if isinstance(status_code, int) and not isinstance(status_code, bool):
            extra["status_code"] = status_code
        log_event("[PUBLIC_SETTINGS] Public workspace settings request failed.", extra=extra, level=logging.ERROR)
        payload, status = {
            "error": PUBLIC_SETTINGS_UNAVAILABLE_MESSAGE,
            "error_code": "public_workspace_settings_unavailable",
        }, 500
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, status


def no_store(payload, status):
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, status


def _stored_timestamp():
    """The ``modifiedDate`` format the classic public workspace writers store."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


# ---------------------------------------------------------------------------
# Strict request parsing
# ---------------------------------------------------------------------------

def reject_query_parameters():
    """These routes take no query parameters; a stray one is a 400."""
    if request.args:
        raise _invalid("This request does not accept query parameters.")


def read_strict_json_object():
    """Parse a JSON object body, rejecting duplicate keys so a smuggled second value
    cannot shadow a validated one."""
    def unique_fields(pairs):
        payload = {}
        for key, value in pairs:
            if key in payload:
                raise _invalid("Duplicate fields are not supported.")
            payload[key] = value
        return payload

    if not request.is_json:
        raise _invalid("A JSON object is required for this request.")
    try:
        body = json.loads(request.get_data(), object_pairs_hook=unique_fields)
    except (ValueError, UnicodeDecodeError) as error:
        raise _invalid("Provide valid JSON with no duplicate fields.") from error
    if not isinstance(body, dict):
        raise _invalid("A JSON object is required for this request.")
    return body


def _require_workspace_id(workspace_id):
    if (
        not isinstance(workspace_id, str) or not workspace_id or len(workspace_id) > 512
        or workspace_id != workspace_id.strip() or workspace_id in (".", "..")
        or INVALID_PUBLIC_SETTINGS_ID.search(workspace_id)
    ):
        raise _invalid("Invalid public workspace identifier.")


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------

def load_public_workspace(user_id, workspace_id):
    """Return ``(workspace, role)`` for an existing public workspace, or raise its 404."""
    _require_workspace_id(workspace_id)
    workspace = find_public_workspace_by_id(workspace_id)
    if not workspace:
        raise _workspace_not_found()
    return workspace, caller_role(workspace, user_id)


def caller_role(workspace, user_id):
    """The caller's role: a stored role, or ``User`` for every other signed-in caller."""
    return get_user_role_in_public_workspace(workspace, user_id)


def require_operation(workspace, role, settings, operation):
    """Refuse unless ``public_settings_decisions`` allows ``operation``."""
    reason = public_settings_decisions(role, workspace, settings)[operation]
    if reason is not None:
        raise refusal(reason, workspace)


def require_manager(role):
    if role not in PUBLIC_SETTINGS_MANAGER_ROLES:
        raise refusal(PUBLIC_MANAGER_REQUIRED)


# ---------------------------------------------------------------------------
# Revisions
# ---------------------------------------------------------------------------

def _section_fields(workspace, section):
    if section == "profile":
        return {
            "name": workspace.get("name"),
            "description": workspace.get("description"),
            "heroColor": workspace.get("heroColor"),
        }
    if section == "logo":
        return {"logoVersion": workspace.get("logoVersion"), "hasLogo": get_workspace_logo_metadata(workspace)["hasLogo"]}
    if section == "downloads":
        return {"disable_file_downloads": workspace.get("disable_file_downloads")}
    if section == "retention":
        return {"retention_policy": workspace.get("retention_policy")}
    raise ValueError(f"Unknown public workspace settings section: {section}")


def section_revision(workspace, section):
    """A digest of one section's stored fields, which changes whenever any of them does."""
    encoded = json.dumps(
        {"section": section, "fields": _section_fields(workspace, section)},
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def require_revision(workspace, section, revision):
    if section_revision(workspace, section) != revision:
        raise PublicSettingsError(
            PUBLIC_SETTINGS_CHANGED_MESSAGE, 409, error_code="public_workspace_settings_changed",
        )


# ---------------------------------------------------------------------------
# The read
# ---------------------------------------------------------------------------

def _text(value):
    return value if isinstance(value, str) else ""


def _status(workspace):
    status = workspace.get("status", "active")
    return status if status in PUBLIC_KNOWN_STATUSES else "unknown"


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


def build_public_settings(workspace, role, settings):
    """The settings read for a caller who holds ``role`` in ``workspace``."""
    workspace_id = _text(workspace.get("id"))
    logo = get_workspace_logo_metadata(workspace)
    payload = {
        "schema_version": PUBLIC_SETTINGS_SCHEMA_VERSION,
        "workspace_id": workspace_id,
        "viewer_role": role,
        "status": _status(workspace),
        "profile": {
            "name": _text(workspace.get("name")),
            "description": _text(workspace.get("description")),
            "hero_color": normalize_workspace_hero_color(workspace.get("heroColor"), DEFAULT_WORKSPACE_HERO_COLOR),
            "revision": section_revision(workspace, "profile"),
        },
        "logo": {
            "has_logo": logo["hasLogo"],
            "logo_version": logo["logoVersion"],
            "logo_url": (
                f"/api/public_workspaces/{quote(workspace_id, safe='')}/logo?v={logo['logoVersion']}"
                if logo["hasLogo"] else None
            ),
            "revision": section_revision(workspace, "logo"),
        },
        "settings_management": build_public_settings_management(role, workspace, settings),
    }
    if is_public_workspace_file_download_admin_enabled(settings, workspace):
        payload["downloads"] = {
            "disable_file_downloads": bool(workspace.get("disable_file_downloads", False)),
            "file_downloads_enabled": is_public_workspace_file_download_enabled(settings, workspace),
            "revision": section_revision(workspace, "downloads"),
        }
    if public_retention_enabled(settings):
        policy = workspace.get("retention_policy") if isinstance(workspace.get("retention_policy"), dict) else {}
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
                    settings.get("default_retention_conversation_public", "none")
                ),
                "document_retention_days": _organization_default(
                    settings.get("default_retention_document_public", "none")
                ),
            },
            "revision": section_revision(workspace, "retention"),
        }
    return payload


def read_public_settings(user_id, workspace_id):
    """Return ``({"settings": ...}, 200)`` for the owner or an admin."""
    user_id = _require_user_id(user_id)
    reject_query_parameters()
    workspace, role = load_public_workspace(user_id, workspace_id)
    require_manager(role)
    return {"settings": build_public_settings(workspace, role, get_settings())}, 200


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def _write(workspace_id, apply_changes, *, cache_reason):
    try:
        committed = update_public_workspace_document_with_etag_guard(
            workspace_id, apply_changes, cache_reason=cache_reason,
        )
    except PublicWorkspaceDocumentWriteConflict as error:
        raise PublicSettingsError(
            PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE, 409, error_code=PUBLIC_WORKSPACE_WRITE_CONFLICT_CODE,
        ) from error
    if committed is None:
        raise _workspace_not_found()
    return committed


def _written_settings(committed, user_id, settings):
    return {"settings": build_public_settings(committed, caller_role(committed, user_id), settings)}, 200


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


def validate_public_workspace_name(name):
    """Return a workspace name stripped, or raise its reviewed 400."""
    if name is None or (isinstance(name, str) and not name.strip()):
        raise _invalid("Enter a workspace name.")
    if not isinstance(name, str):
        raise _invalid("The workspace name must be text.")
    name = name.strip()
    if len(name) > PUBLIC_NAME_MAX_LENGTH:
        raise _invalid(f"Workspace names can be at most {PUBLIC_NAME_MAX_LENGTH} characters.")
    if PUBLIC_NAME_CONTROL_CHARACTERS.search(name):
        raise _invalid("Workspace names cannot contain control characters.")
    return name


def validate_public_workspace_description(description):
    """Return a workspace description stripped, or raise its reviewed 400."""
    if not isinstance(description, str):
        raise _invalid("The workspace description must be text.")
    description = description.strip()
    if len(description) > PUBLIC_DESCRIPTION_MAX_LENGTH:
        raise _invalid(f"Workspace descriptions can be at most {PUBLIC_DESCRIPTION_MAX_LENGTH} characters.")
    return description


def _profile_changes(workspace, body):
    """The profile fields the body changes, validated against ``workspace``'s stored values."""
    changes = {}
    if "name" in body:
        name = body["name"]
        changes["name"] = name if name == workspace.get("name") else validate_public_workspace_name(name)
    if "description" in body:
        description = body["description"]
        changes["description"] = (
            description if description == workspace.get("description")
            else validate_public_workspace_description(description)
        )
    if "hero_color" in body:
        hero_color = body["hero_color"]
        if not isinstance(hero_color, str):
            raise _invalid("The hero color must be text, such as #0078d4.")
        changes["heroColor"] = normalize_workspace_hero_color(
            hero_color, workspace.get("heroColor", DEFAULT_WORKSPACE_HERO_COLOR),
        )
    return changes


PROFILE_OPERATIONS_BY_FIELD = {"name": "edit_name", "description": "edit_description", "hero_color": "edit_color"}


def update_public_profile(user_id, workspace_id):
    """Change the name, description or hero color and return ``({"settings": ...}, 200)``."""
    user_id = _require_user_id(user_id)
    reject_query_parameters()
    settings = get_settings()
    workspace, role = load_public_workspace(user_id, workspace_id)
    for operation in PROFILE_OPERATIONS_BY_FIELD.values():
        require_operation(workspace, role, settings, operation)
    body, revision = _read_body(
        PUBLIC_PROFILE_FIELDS, "Only the name, description and hero_color can be changed here.",
    )
    if not any(field in body for field in PUBLIC_PROFILE_FIELDS):
        raise _invalid("Include a name, description or hero_color to change.")
    _profile_changes(workspace, body)

    def apply(fresh):
        fresh_role = caller_role(fresh, user_id)
        for field, operation in PROFILE_OPERATIONS_BY_FIELD.items():
            if field in body:
                require_operation(fresh, fresh_role, settings, operation)
        require_revision(fresh, "profile", revision)
        fresh.update(_profile_changes(fresh, body))
        fresh["modifiedDate"] = _stored_timestamp()
        return fresh

    committed = _write(workspace_id, apply, cache_reason="public_workspace_updated")
    return _written_settings(committed, user_id, settings)


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
    """The stored form of an uploaded logo, or the reviewed, data-free 400 when it can't be used."""
    try:
        processed = prepare_workspace_logo_image_for_storage(logo_file.read(), logo_file.filename)
    except Exception as error:  # noqa: BLE001 - any decoding failure of an untrusted image is the same 400
        raise _invalid(PUBLIC_LOGO_UNREADABLE_MESSAGE) from error
    stored = processed.get("base64_str") if isinstance(processed, dict) else None
    if not isinstance(stored, str) or not stored:
        raise _invalid(PUBLIC_LOGO_UNREADABLE_MESSAGE)
    if len(stored) > PUBLIC_LOGO_MAX_STORED_LENGTH:
        raise _invalid("This logo is too large to store. Use a smaller image.")
    return stored


def replace_public_logo(user_id, workspace_id):
    """Store a new logo and return ``({"settings": ...}, 200)``."""
    user_id = _require_user_id(user_id)
    reject_query_parameters()
    settings = get_settings()
    workspace, role = load_public_workspace(user_id, workspace_id)
    require_operation(workspace, role, settings, "edit_logo")
    logo_file, revision = _read_logo_upload()
    stored_logo = _prepared_logo(logo_file)

    def apply(fresh):
        require_operation(fresh, caller_role(fresh, user_id), settings, "edit_logo")
        require_revision(fresh, "logo", revision)
        fresh["logoBase64"] = stored_logo
        fresh["logoVersion"] = get_workspace_logo_metadata(fresh)["logoVersion"] + 1
        fresh["modifiedDate"] = _stored_timestamp()
        return fresh

    return _written_settings(_write(workspace_id, apply, cache_reason=None), user_id, settings)


def remove_public_logo(user_id, workspace_id):
    """Clear the logo and return ``({"settings": ...}, 200)``."""
    user_id = _require_user_id(user_id)
    reject_query_parameters()
    settings = get_settings()
    workspace, role = load_public_workspace(user_id, workspace_id)
    require_operation(workspace, role, settings, "edit_logo")
    _body, revision = _read_body((), "Only the logo revision can be sent to remove the logo.")

    def apply(fresh):
        require_operation(fresh, caller_role(fresh, user_id), settings, "edit_logo")
        require_revision(fresh, "logo", revision)
        if not get_workspace_logo_metadata(fresh)["hasLogo"]:
            raise PublicSettingsError(NO_PUBLIC_LOGO_MESSAGE, 409, error_code="no_public_workspace_logo")
        fresh["logoBase64"] = ""
        fresh["logoVersion"] = get_workspace_logo_metadata(fresh)["logoVersion"] + 1
        fresh["modifiedDate"] = _stored_timestamp()
        return fresh

    return _written_settings(_write(workspace_id, apply, cache_reason=None), user_id, settings)


def update_public_downloads(user_id, workspace_id):
    """Set the workspace's ``disable_file_downloads`` switch and return ``({"settings": ...}, 200)``."""
    user_id = _require_user_id(user_id)
    reject_query_parameters()
    settings = get_settings()
    workspace, role = load_public_workspace(user_id, workspace_id)
    require_operation(workspace, role, settings, "edit_downloads")
    body, revision = _read_body(
        ("disable_file_downloads",), "Only disable_file_downloads can be changed here.",
    )
    disabled = body.get("disable_file_downloads")
    if not isinstance(disabled, bool):
        raise _invalid("Set disable_file_downloads to true or false.")

    def apply(fresh):
        require_operation(fresh, caller_role(fresh, user_id), settings, "edit_downloads")
        require_revision(fresh, "downloads", revision)
        fresh["disable_file_downloads"] = disabled
        fresh["modifiedDate"] = _stored_timestamp()
        return fresh

    committed = _write(workspace_id, apply, cache_reason="public_workspace_updated")
    return _written_settings(committed, user_id, settings)


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


def update_public_retention(user_id, workspace_id):
    """Merge retention values into the stored policy and return ``({"settings": ...}, 200)``."""
    user_id = _require_user_id(user_id)
    reject_query_parameters()
    settings = get_settings()
    workspace, role = load_public_workspace(user_id, workspace_id)
    require_operation(workspace, role, settings, "edit_retention")
    body, revision = _read_body(
        PUBLIC_RETENTION_FIELDS,
        "Only conversation_retention_days and document_retention_days can be changed here.",
    )
    values = {field: _retention_value(field, body[field], settings) for field in PUBLIC_RETENTION_FIELDS if field in body}
    if not values:
        raise _invalid("Include conversation_retention_days or document_retention_days to change.")

    def apply(fresh):
        require_operation(fresh, caller_role(fresh, user_id), settings, "edit_retention")
        require_revision(fresh, "retention", revision)
        stored = fresh.get("retention_policy")
        policy = dict(stored) if isinstance(stored, dict) else {}
        policy.update(values)
        fresh["retention_policy"] = policy
        fresh["modifiedDate"] = _stored_timestamp()
        return fresh

    return _written_settings(_write(workspace_id, apply, cache_reason=None), user_id, settings)
