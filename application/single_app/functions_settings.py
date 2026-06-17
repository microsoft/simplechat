# functions_settings.py

from functools import wraps

from flask import g, has_request_context, jsonify, request, session

from config import *
from functions_appinsights import log_event
from functions_cosmos_throughput import get_default_cosmos_throughput_settings
from functions_document_actions import get_default_document_action_capabilities
from functions_icon_utils import normalize_icon_payload
from functions_service_health import get_default_service_health
import app_settings_cache
import inspect
import copy
import json
import uuid
from support_menu_config import (
    get_default_support_latest_features_visibility,
    has_visible_support_latest_features,
    normalize_support_latest_features_visibility,
)


USER_SETTINGS_REQUEST_CACHE_ATTR = "simplechat_user_settings_request_cache"
USER_UI_SETTINGS_KEYS = (
    "profileImage",
    "navLayout",
    "darkModeEnabled",
    "showTutorialButtons",
    "chatLayout",
    "streamingEnabled",
    "notifications_per_page",
    "sidebarToggleStyle",
    "sidebarMenuState",
)
ADMIN_SETTINGS_SECRET_REDACTED_VALUE = "***REDACTED***"
ADMIN_SETTINGS_FORM_SECRET_FIELDS = (
    "azure_openai_gpt_key",
    "azure_apim_gpt_subscription_key",
    "azure_openai_embedding_key",
    "azure_apim_embedding_subscription_key",
    "azure_openai_image_gen_key",
    "azure_apim_image_gen_subscription_key",
    "redis_key",
    "office_docs_storage_account_url",
    "office_docs_storage_account_blob_endpoint",
    "video_files_storage_account_url",
    "audio_files_storage_account_url",
    "content_safety_key",
    "azure_apim_content_safety_subscription_key",
    "azure_ai_search_key",
    "azure_apim_ai_search_subscription_key",
    "azure_document_intelligence_key",
    "azure_apim_document_intelligence_subscription_key",
    "speech_service_key",
)
ADMIN_SETTINGS_NESTED_SECRET_FIELDS = (
    "web_search_agent.other_settings.azure_ai_foundry.client_secret",
)


def is_admin_settings_redacted_secret(value):
    return str(value or '').strip() == ADMIN_SETTINGS_SECRET_REDACTED_VALUE


def _get_nested_setting_value(settings, field_path):
    current = settings if isinstance(settings, dict) else {}
    for part in str(field_path or '').split('.'):
        if not isinstance(current, dict):
            return ''
        current = current.get(part)
    return current if current is not None else ''


def _set_nested_setting_value(settings, field_path, value):
    current = settings
    parts = str(field_path or '').split('.')
    for part in parts[:-1]:
        if not isinstance(current.get(part), dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def resolve_admin_settings_secret_value(field_name, submitted_value, existing_settings):
    submitted_text = str(submitted_value or '').strip()
    if not is_admin_settings_redacted_secret(submitted_text):
        return submitted_text
    return str(_get_nested_setting_value(existing_settings, field_name) or '').strip()


def redact_admin_settings_secrets_for_form(settings):
    redacted_settings = copy.deepcopy(settings or {})
    for field_name in ADMIN_SETTINGS_FORM_SECRET_FIELDS:
        if redacted_settings.get(field_name):
            redacted_settings[field_name] = ADMIN_SETTINGS_SECRET_REDACTED_VALUE
    for field_path in ADMIN_SETTINGS_NESTED_SECRET_FIELDS:
        if _get_nested_setting_value(redacted_settings, field_path):
            _set_nested_setting_value(redacted_settings, field_path, ADMIN_SETTINGS_SECRET_REDACTED_VALUE)
    return redacted_settings


def _clone_user_settings_doc(doc):
    return copy.deepcopy(doc or {})


def _get_user_settings_request_cache():
    if not has_request_context():
        return None

    cache = getattr(g, USER_SETTINGS_REQUEST_CACHE_ATTR, None)
    if cache is None:
        cache = {}
        setattr(g, USER_SETTINGS_REQUEST_CACHE_ATTR, cache)
    return cache


def _get_request_cached_user_settings(user_id):
    cache = _get_user_settings_request_cache()
    if cache is None or user_id not in cache:
        return None
    return _clone_user_settings_doc(cache[user_id])


def _set_request_cached_user_settings(user_id, doc):
    cache = _get_user_settings_request_cache()
    if cache is not None:
        cache[user_id] = _clone_user_settings_doc(doc)


def _delete_request_cached_user_settings(user_id):
    cache = _get_user_settings_request_cache()
    if cache is not None:
        cache.pop(user_id, None)


def _extract_user_ui_settings(doc):
    settings = (doc or {}).get('settings', {})
    if not isinstance(settings, dict):
        settings = {}
    return {
        key: copy.deepcopy(settings[key])
        for key in USER_UI_SETTINGS_KEYS
        if key in settings
    }


def _delete_user_ui_settings_cache(user_id):
    cache_deleter = getattr(app_settings_cache, "delete_user_ui_settings_cache", None)
    if callable(cache_deleter):
        try:
            cache_deleter(user_id)
        except Exception as cache_error:
            log_event(
                "[UserSettingsCache] Failed to delete user UI settings cache.",
                extra={
                    "user_id": user_id,
                    "error": str(cache_error)
                },
                level=logging.WARNING
            )


def _set_user_ui_settings_cache(user_id, doc):
    cache_setter = getattr(app_settings_cache, "set_user_ui_settings_cache", None)
    if callable(cache_setter):
        try:
            cache_setter(user_id, _extract_user_ui_settings(doc))
        except Exception as cache_error:
            log_event(
                "[UserSettingsCache] Failed to set user UI settings cache.",
                extra={
                    "user_id": user_id,
                    "error": str(cache_error)
                },
                level=logging.WARNING
            )


def invalidate_user_settings_caches(user_id):
    """Clear request and lightweight UI caches for a user settings document."""
    _delete_request_cached_user_settings(user_id)
    _delete_user_ui_settings_cache(user_id)


def is_tabular_processing_enabled(settings):
    """Tabular processing is available whenever enhanced citations is enabled."""
    return bool((settings or {}).get('enable_enhanced_citations', False))


CHAT_FILE_UPLOAD_APP_ROLE = "ChatFileUploadUser"
WORKFLOW_USER_APP_ROLE = "WorkflowUser"
DOCUMENT_INTELLIGENCE_PDF_IMAGE_EXTRACTION_MODES = {"read", "layout", "auto"}
DOCUMENT_INTELLIGENCE_MANUAL_EXTRACTION_MODES = {"read", "layout"}
DOCUMENT_INTELLIGENCE_AUTO_SAMPLE_PAGES_DEFAULT = 3
DOCUMENT_INTELLIGENCE_AUTO_SAMPLE_PAGES_MAX = 20
AGENTS_PAGE_PROMOTED_POPULAR_ORDER_OPTIONS = {"before", "after", "mixed"}
AGENTS_PAGE_PROMOTED_POPULAR_WINDOW_OPTIONS = {"all_time", "30_days", "both"}
AGENTS_PAGE_PROMOTED_POPULAR_TAG_LABEL_DEFAULT = "Promoted"


def normalize_agents_page_promoted_popular_order(value):
    """Normalize where admin-promoted popular agents appear relative to usage-ranked agents."""
    normalized_value = str(value or "before").strip().lower().replace("-", "_")
    return normalized_value if normalized_value in AGENTS_PAGE_PROMOTED_POPULAR_ORDER_OPTIONS else "before"


def normalize_agents_page_promoted_popular_window(value):
    """Normalize the Popular page time window where an admin promotion is visible."""
    normalized_value = str(value or "both").strip().lower().replace("-", "_")
    if normalized_value in {"all", "alltime"}:
        return "all_time"
    if normalized_value in {"30", "thirty_days", "last_30_days", "last30"}:
        return "30_days"
    return normalized_value if normalized_value in AGENTS_PAGE_PROMOTED_POPULAR_WINDOW_OPTIONS else "both"


def normalize_agents_page_promoted_popular_tag_label(value):
    """Normalize the optional badge label shown on admin-promoted popular agents."""
    normalized_value = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    normalized_value = " ".join(normalized_value.split())
    if not normalized_value:
        normalized_value = AGENTS_PAGE_PROMOTED_POPULAR_TAG_LABEL_DEFAULT
    return normalized_value[:40]


def normalize_agents_page_promoted_popular_tag_enabled(value):
    """Normalize persisted promoted badge toggle values into a strict boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized_value = value.strip().lower()
        if normalized_value in {"false", "0", "no", "off"}:
            return False
        if normalized_value in {"true", "1", "yes", "on"}:
            return True
    return bool(value)


def _iter_agents_page_promoted_popular_candidates(value):
    if value is None:
        return []
    if isinstance(value, str):
        stripped_value = value.strip()
        if not stripped_value:
            return []
        try:
            parsed_value = json.loads(stripped_value)
            return parsed_value if isinstance(parsed_value, list) else []
        except (TypeError, ValueError):
            return [{"catalog_key": line.strip()} for line in stripped_value.splitlines() if line.strip()]
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def normalize_agents_page_promoted_popular_agents(value):
    """Normalize admin-selected Popular page agent promotions into stable catalog-key references."""
    normalized_agents = []
    seen_catalog_keys = set()
    for candidate in _iter_agents_page_promoted_popular_candidates(value):
        if isinstance(candidate, str):
            candidate = {"catalog_key": candidate}
        if not isinstance(candidate, dict):
            continue

        catalog_key = str(candidate.get("catalog_key") or "").strip()
        if not catalog_key or len(catalog_key) > 512 or catalog_key in seen_catalog_keys:
            continue
        seen_catalog_keys.add(catalog_key)

        display_name = " ".join(str(candidate.get("display_name") or candidate.get("name") or "").split())[:160]
        scope_label = " ".join(str(candidate.get("scope_label") or candidate.get("scope_name") or "").split())[:120]
        scope_type = str(candidate.get("scope_type") or "").strip().lower()
        if scope_type == "enterprise":
            scope_type = "global"
        if scope_type not in {"personal", "group", "global"}:
            scope_type = ""

        normalized_agents.append({
            "catalog_key": catalog_key,
            "display_name": display_name,
            "scope_label": scope_label,
            "scope_type": scope_type,
            "window": normalize_agents_page_promoted_popular_window(candidate.get("window")),
        })

    return normalized_agents


def normalize_agents_page_promoted_popular_settings(settings):
    """Normalize persisted Agents page promotion settings in-place."""
    if not isinstance(settings, dict):
        return False

    changed = False
    normalized_agents = normalize_agents_page_promoted_popular_agents(
        settings.get("agents_page_promoted_popular_agents")
    )
    if settings.get("agents_page_promoted_popular_agents") != normalized_agents:
        settings["agents_page_promoted_popular_agents"] = normalized_agents
        changed = True

    normalized_order = normalize_agents_page_promoted_popular_order(
        settings.get("agents_page_promoted_popular_order")
    )
    if settings.get("agents_page_promoted_popular_order") != normalized_order:
        settings["agents_page_promoted_popular_order"] = normalized_order
        changed = True

    normalized_tag_enabled = normalize_agents_page_promoted_popular_tag_enabled(
        settings.get("agents_page_promoted_popular_tag_enabled", True)
    )
    if settings.get("agents_page_promoted_popular_tag_enabled") != normalized_tag_enabled:
        settings["agents_page_promoted_popular_tag_enabled"] = normalized_tag_enabled
        changed = True

    normalized_tag_label = normalize_agents_page_promoted_popular_tag_label(
        settings.get("agents_page_promoted_popular_tag_label")
    )
    if settings.get("agents_page_promoted_popular_tag_label") != normalized_tag_label:
        settings["agents_page_promoted_popular_tag_label"] = normalized_tag_label
        changed = True

    return changed


def normalize_document_intelligence_pdf_image_extraction_mode(value):
    """Normalize the PDF/image Document Intelligence extraction mode."""
    normalized_value = str(value or "read").strip().lower()
    if normalized_value not in DOCUMENT_INTELLIGENCE_PDF_IMAGE_EXTRACTION_MODES:
        return "read"
    return normalized_value


def get_document_intelligence_pdf_image_extraction_mode(settings):
    """Return the configured PDF/image Document Intelligence extraction mode."""
    return normalize_document_intelligence_pdf_image_extraction_mode(
        (settings or {}).get('document_intelligence_pdf_image_extraction_mode')
    )


def normalize_document_intelligence_auto_sample_pages(value):
    """Normalize how many first pages Auto mode samples before choosing a mode."""
    try:
        normalized_value = int(value)
    except (TypeError, ValueError):
        normalized_value = DOCUMENT_INTELLIGENCE_AUTO_SAMPLE_PAGES_DEFAULT

    return max(1, min(normalized_value, DOCUMENT_INTELLIGENCE_AUTO_SAMPLE_PAGES_MAX))


def get_document_intelligence_auto_sample_pages(settings):
    """Return the configured Auto-mode sample page count."""
    return normalize_document_intelligence_auto_sample_pages(
        (settings or {}).get('document_intelligence_auto_sample_pages')
    )


def normalize_document_intelligence_manual_extraction_mode(value):
    """Normalize an explicit reprocess target mode, limited to Standard/Read or Enhanced/Layout."""
    normalized_value = str(value or "read").strip().lower()
    if normalized_value not in DOCUMENT_INTELLIGENCE_MANUAL_EXTRACTION_MODES:
        return "read"
    return normalized_value


def normalize_app_role_claims(user_roles):
    """Normalize app role claims into a flat string list."""
    if not user_roles:
        return []
    if isinstance(user_roles, str):
        return [user_roles]
    if isinstance(user_roles, (list, tuple, set)):
        return [str(role).strip() for role in user_roles if str(role).strip()]
    return [str(user_roles).strip()]


def has_chat_file_upload_app_role(user_roles):
    """Return True when authenticated claims include the chat file upload app role."""
    normalized_roles = {role.lower() for role in normalize_app_role_claims(user_roles)}
    return CHAT_FILE_UPLOAD_APP_ROLE.lower() in normalized_roles


def has_workflow_user_app_role(user_roles):
    """Return True when authenticated claims include the workflow user app role."""
    normalized_roles = {role.lower() for role in normalize_app_role_claims(user_roles)}
    return WORKFLOW_USER_APP_ROLE.lower() in normalized_roles


GROUP_WORKFLOW_ALLOWED_GROUP_ID_PARSE_DEPTH_LIMIT = 5


def _iter_group_workflow_allowed_group_id_candidates(value, depth=0):
    """Yield raw assignment candidates from legacy text, JSON, and nested JSON strings."""
    if value is None or depth > GROUP_WORKFLOW_ALLOWED_GROUP_ID_PARSE_DEPTH_LIMIT:
        return

    if isinstance(value, str):
        stripped_value = value.strip()
        if not stripped_value:
            return

        if stripped_value.startswith('[') or stripped_value.startswith('"'):
            try:
                parsed_value = json.loads(stripped_value)
            except (TypeError, ValueError):
                parsed_value = None

            if isinstance(parsed_value, list):
                for candidate in parsed_value:
                    yield from _iter_group_workflow_allowed_group_id_candidates(candidate, depth + 1)
                return

            if isinstance(parsed_value, str) and parsed_value != stripped_value:
                yield from _iter_group_workflow_allowed_group_id_candidates(parsed_value, depth + 1)
                return

        for candidate in stripped_value.replace('\r', '\n').replace(',', '\n').replace(';', '\n').split('\n'):
            yield candidate
        return

    if isinstance(value, (list, tuple, set)):
        for candidate in value:
            yield from _iter_group_workflow_allowed_group_id_candidates(candidate, depth + 1)
        return

    yield value


def normalize_group_workflow_allowed_group_id(value):
    """Return a canonical SimpleChat group id or an empty string for invalid values."""
    group_id = str(value or '').strip()
    if not group_id:
        return ''

    try:
        return str(uuid.UUID(group_id))
    except (AttributeError, TypeError, ValueError):
        return ''


def normalize_group_workflow_allowed_group_ids(value):
    """Normalize group workflow assignment settings into unique group ids."""
    normalized_ids = []
    seen_ids = set()
    for candidate in _iter_group_workflow_allowed_group_id_candidates(value):
        group_id = normalize_group_workflow_allowed_group_id(candidate)
        if not group_id or group_id in seen_ids:
            continue
        normalized_ids.append(group_id)
        seen_ids.add(group_id)
    return normalized_ids


def normalize_group_workflow_assignment_settings(settings):
    """Normalize persisted group workflow assignment settings in-place."""
    if not isinstance(settings, dict):
        return False

    current_group_ids = settings.get('group_workflow_allowed_group_ids')
    normalized_group_ids = normalize_group_workflow_allowed_group_ids(current_group_ids)
    if current_group_ids == normalized_group_ids:
        return False

    settings['group_workflow_allowed_group_ids'] = normalized_group_ids
    return True


def normalize_file_sync_allowed_group_ids(value):
    """Normalize File Sync group assignment settings into unique group ids."""
    return normalize_group_workflow_allowed_group_ids(value)


def normalize_file_sync_allowed_public_workspace_ids(value):
    """Normalize File Sync public workspace assignment settings into unique workspace ids."""
    if value is None:
        return []
    if isinstance(value, str):
        stripped_value = value.strip()
        candidates = None
        if stripped_value.startswith('['):
            try:
                parsed_value = json.loads(stripped_value)
                if isinstance(parsed_value, list):
                    candidates = parsed_value
            except (TypeError, ValueError):
                candidates = None
        if candidates is None:
            candidates = value.replace('\r', '\n').replace(',', '\n').split('\n')
    elif isinstance(value, (list, tuple, set)):
        candidates = value
    else:
        candidates = [value]

    normalized_ids = []
    seen_ids = set()
    for candidate in candidates:
        workspace_id = str(candidate or '').strip()
        if not workspace_id or workspace_id in seen_ids:
            continue
        normalized_ids.append(workspace_id)
        seen_ids.add(workspace_id)
    return normalized_ids


def normalize_file_download_allowed_group_ids(value):
    """Normalize file download group assignment settings into unique group ids."""
    return normalize_group_workflow_allowed_group_ids(value)


def normalize_file_download_allowed_public_workspace_ids(value):
    """Normalize file download public workspace assignment settings into unique workspace ids."""
    return normalize_file_sync_allowed_public_workspace_ids(value)


def is_personal_workspace_file_download_enabled(settings):
    """Return True when admins allow personal workspace file downloads."""
    return bool((settings or {}).get('allow_personal_workspace_file_downloads', False))


def _get_workspace_policy_target_id(workspace_doc_or_id):
    if isinstance(workspace_doc_or_id, dict):
        return str(workspace_doc_or_id.get('id') or '').strip()
    return str(workspace_doc_or_id or '').strip()


def is_group_workspace_file_download_admin_enabled(settings, group_doc_or_id):
    """Return True when admins have enabled file downloads for a group workspace."""
    source_settings = settings or {}
    if not source_settings.get('allow_group_workspace_file_downloads', False):
        return False

    group_id = _get_workspace_policy_target_id(group_doc_or_id)
    if not group_id:
        return False
    if source_settings.get('require_group_assignment_for_file_downloads', False):
        allowed_group_ids = normalize_file_download_allowed_group_ids(
            source_settings.get('file_download_allowed_group_ids')
        )
        return group_id in allowed_group_ids
    return True


def is_group_workspace_file_download_enabled(settings, group_doc_or_id):
    """Return True when admins and group owners allow downloads for a group workspace."""
    source_settings = settings or {}
    if not is_group_workspace_file_download_admin_enabled(source_settings, group_doc_or_id):
        return False

    group_doc = {}
    if isinstance(group_doc_or_id, dict):
        group_doc = group_doc_or_id
    if bool(group_doc.get('disable_file_downloads', False)):
        return False
    return True


def is_public_workspace_file_download_admin_enabled(settings, workspace_doc_or_id):
    """Return True when admins have enabled file downloads for a public workspace."""
    source_settings = settings or {}
    if not source_settings.get('allow_public_workspace_file_downloads', False):
        return False

    workspace_id = _get_workspace_policy_target_id(workspace_doc_or_id)
    if not workspace_id:
        return False
    if source_settings.get('require_public_workspace_assignment_for_file_downloads', False):
        allowed_workspace_ids = normalize_file_download_allowed_public_workspace_ids(
            source_settings.get('file_download_allowed_public_workspace_ids')
        )
        return workspace_id in allowed_workspace_ids
    return True


def is_public_workspace_file_download_enabled(settings, workspace_doc_or_id):
    """Return True when admins and workspace owners allow downloads for a public workspace."""
    source_settings = settings or {}
    if not is_public_workspace_file_download_admin_enabled(source_settings, workspace_doc_or_id):
        return False

    workspace_doc = {}
    if isinstance(workspace_doc_or_id, dict):
        workspace_doc = workspace_doc_or_id
    if bool(workspace_doc.get('disable_file_downloads', False)):
        return False
    return True


def is_group_workflows_enabled_for_group(settings, group_id):
    """Return True when group workflows are enabled and this group is allowed."""
    source_settings = settings or {}
    normalized_group_id = str(group_id or '').strip()
    if not source_settings.get('allow_group_workflows', False):
        return False
    if not normalized_group_id:
        return False
    if source_settings.get('require_group_assignment_for_group_workflows', False):
        allowed_group_ids = normalize_group_workflow_allowed_group_ids(
            source_settings.get('group_workflow_allowed_group_ids')
        )
        return normalized_group_id in allowed_group_ids
    return True


def get_group_workflow_management_roles(settings):
    """Return group roles allowed to create, update, and delete group workflows."""
    if (settings or {}).get('require_owner_for_group_agent_management', False):
        return ("Owner",)
    return ("Owner", "Admin")


def is_chat_file_upload_enabled_for_user(settings, user_roles=None, authorization_prechecked=False):
    """Return True when app settings and optional app role policy allow chat file uploads."""
    source_settings = settings or {}
    if not source_settings.get('enable_chat_file_uploads', True):
        return False
    if (
        source_settings.get('require_member_of_chat_file_upload_user', False)
        and not authorization_prechecked
        and not has_chat_file_upload_app_role(user_roles)
    ):
        return False
    return True


def is_user_workflows_enabled_for_user(settings, user_roles=None, authorization_prechecked=False):
    """Return True when app settings and optional app role policy allow personal workflows."""
    source_settings = settings or {}
    if not source_settings.get('allow_user_workflows', False):
        return False
    if (
        source_settings.get('require_member_of_workflow_user', False)
        and not authorization_prechecked
        and not has_workflow_user_app_role(user_roles)
    ):
        return False
    return True


def _authorize_user_settings_access(user_id, operation, allow_cross_user=False):
    """Authorize user-settings access for the current request context."""
    normalized_user_id = str(user_id or '').strip()
    if allow_cross_user or not has_request_context():
        return None

    try:
        # Import locally to avoid a circular dependency during app startup.
        from functions_authentication import get_current_user_id
    except ImportError:
        from application.single_app.functions_authentication import get_current_user_id

    actor_user_id = str(get_current_user_id() or '').strip()
    if actor_user_id and normalized_user_id and actor_user_id != normalized_user_id:
        log_event(
            f"[UserSettings] Denied cross-user {operation}",
            {
                "actor_user_id": actor_user_id,
                "target_user_id": normalized_user_id,
                "operation": operation,
            },
            level=logging.WARNING,
        )
        raise PermissionError(f"Cannot {operation} settings for another user.")

    return actor_user_id or None


def _should_sync_session_profile(target_user_id, actor_user_id, allow_cross_user=False):
    """Return True when session-derived profile data should update the target settings doc."""
    if allow_cross_user or not has_request_context():
        return False
    normalized_target_user_id = str(target_user_id or '').strip()
    normalized_actor_user_id = str(actor_user_id or '').strip()
    return bool(normalized_target_user_id and normalized_actor_user_id and normalized_target_user_id == normalized_actor_user_id)


def _refresh_app_settings_cache_after_write(settings_payload, context="app_settings_write"):
    """Update shared/local settings cache around a version bump."""
    cache_updater = getattr(app_settings_cache, "update_settings_cache", None)
    version_bumper = getattr(app_settings_cache, "bump_app_settings_cache_version", None)

    def _update_cache(stage):
        if not callable(cache_updater):
            return
        try:
            cache_updater(copy.deepcopy(settings_payload))
        except Exception as cache_error:
            log_event(
                "App settings cache update failed after settings write.",
                extra={
                    "context": context,
                    "stage": stage,
                    "error": str(cache_error)
                },
                level=logging.WARNING
            )

    _update_cache("before_version_bump")

    if callable(version_bumper):
        try:
            version_bumper()
        except Exception as version_error:
            log_event(
                "App settings cache version bump failed after settings write.",
                extra={
                    "context": context,
                    "error": str(version_error)
                },
                level=logging.WARNING
            )

    _update_cache("after_version_bump")


def _refresh_app_settings_cache_after_write(settings_payload, context="app_settings_write"):
    """Update shared/local settings cache around a version bump."""
    cache_updater = getattr(app_settings_cache, "update_settings_cache", None)
    version_bumper = getattr(app_settings_cache, "bump_app_settings_cache_version", None)

    def _update_cache(stage):
        if not callable(cache_updater):
            return
        try:
            cache_updater(copy.deepcopy(settings_payload))
        except Exception as cache_error:
            log_event(
                "App settings cache update failed after settings write.",
                extra={
                    "context": context,
                    "stage": stage,
                    "error": str(cache_error)
                },
                level=logging.WARNING
            )

    _update_cache("before_version_bump")

    if callable(version_bumper):
        try:
            version_bumper()
        except Exception as version_error:
            log_event(
                "App settings cache version bump failed after settings write.",
                extra={
                    "context": context,
                    "error": str(version_error)
                },
                level=logging.WARNING
            )

    _update_cache("after_version_bump")

def get_settings(use_cosmos=False, include_source=False):
    import secrets
    default_settings = {
        # External health check
        'enable_external_healthcheck': False,
        'enable_no_auth_external_healthcheck': False,
        # Security settings
        'enable_appinsights_global_logging': False,
        'enable_debug_logging': False,
        'debug_logging_timer_enabled': False,
        'debug_timer_value': 1,
        'debug_timer_unit': 'hours',
        'debug_logging_turnoff_time': None,
        # Semantic Kernel plugin/action manifests (MCP, Databricks, RAG, etc.)
        'enable_time_plugin': True,
        'enable_http_plugin': True,
        'enable_wait_plugin': True,
        'enable_math_plugin': True,
        'enable_text_plugin': True,
        'enable_default_embedding_model_plugin': False,
        'enable_fact_memory_plugin': True,
        'enable_tabular_processing_plugin': False,
        'enable_multi_agent_orchestration': False,
        'max_rounds_per_agent': 1,
        'workflow_max_auto_invoke_attempts': 60,
        'enable_semantic_kernel': False,
        'per_user_semantic_kernel': False,
        'orchestration_type': 'default_agent',
        'merge_global_semantic_kernel_with_workspace': False,
        'global_selected_agent': {
            'name': 'researcher',
            'is_global': True
        },
        'allow_user_agents': False,
        'allow_user_custom_endpoints': False,
        'allow_user_custom_agent_endpoints': False,
        'allow_user_plugins': False,
        'allow_user_workflows': False,
        'require_member_of_workflow_user': False,
        'allow_group_workflows': False,
        'require_group_assignment_for_group_workflows': False,
        'group_workflow_allowed_group_ids': [],
        'allow_group_agents': False,
        'allow_group_custom_endpoints': False,
        'allow_group_custom_agent_endpoints': False,
        'governance_user_endpoints': False,
        'governance_group_endpoints': False,
        'governance_global_endpoints': True,
        'governance_user_agents': False,
        'governance_group_agents': False,
        'governance_global_agents_usage': False,
        'governance_user_actions': False,
        'governance_group_actions': False,
        'governance_global_actions_usage': False,
        'allow_ai_foundry_agents': False,
        'allow_group_ai_foundry_agents': False,
        'allow_personal_ai_foundry_agents': False,
        'allow_new_foundry_agents': False,
        'allow_group_new_foundry_agents': False,
        'allow_personal_new_foundry_agents': False,
        'document_action_capabilities': get_default_document_action_capabilities(),
        'enable_agent_template_gallery': True,
        'agent_templates_allow_user_submission': True,
        'agent_templates_require_approval': True,
        'agents_page_title': 'Find your next AI partner',
        'agents_page_subtitle': 'Explore specialized agents built to accelerate how you work.',
        'agents_page_hero_color_mode': 'single',
        'agents_page_hero_primary_color': '#0f172a',
        'agents_page_hero_secondary_color': '#1e293b',
        'agents_page_disclaimer_markdown': '',
        'agents_page_show_instructions_in_details': True,
        'agents_page_promoted_popular_agents': [],
        'agents_page_promoted_popular_order': 'before',
        'agents_page_promoted_popular_tag_enabled': True,
        'agents_page_promoted_popular_tag_label': AGENTS_PAGE_PROMOTED_POPULAR_TAG_LABEL_DEFAULT,
        'allow_group_plugins': False,
        'id': 'app_settings',
        # Control Center settings
        'control_center_last_refresh': None,  # Timestamp of last data refresh
        'control_center_auto_refresh_enabled': True,
        'control_center_auto_refresh_time': '06:00',
        'control_center_auto_refresh_hour': 6,
        'control_center_auto_refresh_minute': 0,
        'control_center_auto_refresh_next_run': None,
        # -- Your entire default dictionary here --
        'app_title': 'Simple Chat',
        'landing_page_text': 'You can add text here and it supports Markdown. '
                             'You agree to our [acceptable user policy](acceptable_use_policy.html) by using this service.',
        'landing_page_alignment': 'left',
        'landing_page_logo_scale_percent': 100,
        'show_logo': False,
        'hide_app_title': False,
        'custom_logo_base64': '',
        'logo_version': 1,
        'custom_logo_dark_base64': '',
        'logo_dark_version': 1,
        'custom_favicon_base64': '',
        'favicon_version': 1,
        'enable_dark_mode_default': False,
        'enable_left_nav_default': True,
        'release_notifications_registered': False,
        'release_notifications_name': '',
        'release_notifications_email': '',
        'release_notifications_org': '',
        'release_notifications_registered_at': '',
        'release_notifications_updated_at': '',

        # GPT Settings
        'enable_gpt_apim': False,
        'azure_openai_gpt_endpoint': '',
        'azure_openai_gpt_api_version': '2024-05-01-preview',
        'azure_openai_gpt_authentication_type': 'key',
        'azure_openai_gpt_subscription_id': '',
        'azure_openai_gpt_resource_group': '',
        'azure_openai_gpt_key': '',
        'gpt_model': {
            "selected": [],
            "all": []
        },
        'enable_multi_model_endpoints': False,
        'model_endpoints': [],
        'default_model_selection': {
            'endpoint_id': '',
            'model_id': '',
            'provider': ''
        },
        'multi_endpoint_migrated_at': None,
        'multi_endpoint_migration_notice': {
            'enabled': False,
                'message': '',
            'created_at': None
        },
        'azure_apim_gpt_endpoint': '',
        'azure_apim_gpt_subscription_key': '',
        'azure_apim_gpt_deployment': '',
        'azure_apim_gpt_api_version': '',

        # Embeddings Settings
        'enable_embedding_apim': False,
        'azure_openai_embedding_endpoint': '',
        'azure_openai_embedding_api_version': '2024-05-01-preview',
        'azure_openai_embedding_authentication_type': 'key',
        'azure_openai_embedding_subscription_id': '',
        'azure_openai_embedding_resource_group': '',
        'azure_openai_embedding_key': '',
        'embedding_model': {
            "selected": [],
            "all": []
        },
        'azure_apim_embedding_endpoint': '',
        'azure_apim_embedding_subscription_key': '',
        'azure_apim_embedding_deployment': '',
        'azure_apim_embedding_api_version': '',

        # Image Generation Settings
        'enable_image_generation': False,
        'enable_image_gen_apim': False,
        'azure_openai_image_gen_endpoint': '',
        'azure_openai_image_gen_api_version': '2024-12-01-preview',
        'azure_openai_image_gen_authentication_type': 'key',
        'azure_openai_image_gen_subscription_id': '',
        'azure_openai_image_gen_resource_group': '',
        'azure_openai_image_gen_key': '',
        'image_gen_model': {
            "selected": [],
            "all": []
        },
        'azure_apim_image_gen_endpoint': '',
        'azure_apim_image_gen_subscription_key': '',
        'azure_apim_image_gen_deployment': '',
        'azure_apim_image_gen_api_version': '',

        # Redis Cache Settings
        'enable_redis_cache': False,
        'redis_url': '',
        'redis_key': '',
        'redis_auth_type': '',

        # Cosmos DB Throughput Scale Settings
        **get_default_cosmos_throughput_settings(),


        # Workspaces
        'enable_user_workspace': True,
        'enable_group_workspaces': True,
        'enable_group_creation': True,
        'require_member_of_create_group': False,
        'require_owner_for_group_agent_management': False,
        'enable_public_workspaces': False,
        'require_member_of_create_public_workspace': False,
        'enable_file_sharing': False,
        'allow_personal_workspace_file_downloads': False,
        'allow_group_workspace_file_downloads': False,
        'require_group_assignment_for_file_downloads': False,
        'file_download_allowed_group_ids': [],
        'allow_public_workspace_file_downloads': False,
        'require_public_workspace_assignment_for_file_downloads': False,
        'file_download_allowed_public_workspace_ids': [],
        'enable_chat_file_uploads': True,
        'require_member_of_chat_file_upload_user': False,
        'enforce_workspace_scope_lock': True,

        # File Sync
        'enable_file_sync': False,
        'enable_file_sync_personal': True,
        'enable_file_sync_group': True,
        'enable_file_sync_public': False,
        'file_sync_personal_require_app_role': False,
        'require_group_assignment_for_file_sync': False,
        'file_sync_allowed_group_ids': [],
        'require_public_workspace_assignment_for_file_sync': False,
        'file_sync_allowed_public_workspace_ids': [],
        'file_sync_personal_admin_only': False,
        'file_sync_group_admin_only': False,
        'file_sync_public_admin_only': False,
        'file_sync_visible_source_types': ['smb', 'azure_files'],
        'file_sync_max_sources_per_scope': 10,
        'file_sync_min_schedule_interval_minutes': 15,
        'file_sync_max_files_per_run': 1000,
        'file_sync_max_bytes_per_run': 5368709120,
        'file_sync_max_concurrent_runs': 2,
        'file_sync_allow_recursive_sources': True,
        'file_sync_default_remote_delete_policy': 'ignore',
        'file_sync_debug_logging': True,

        # Multimedia
        'enable_video_file_support': False,
        'enable_audio_file_support': False,

        # Metadata Extraction
        'enable_extract_meta_data': False,
        'metadata_extraction_model': '',
        'metadata_extraction_model_selection': {
            'endpoint_id': '',
            'model_id': '',
            'provider': ''
        },
        
        # Multimodal Vision
        'enable_multimodal_vision': False,
        'multimodal_vision_model': '',
        
        'enable_summarize_content_history_for_search': False,
        'number_of_historical_messages_to_summarize': 10,
        'enable_summarize_content_history_beyond_conversation_history_limit': False,

        # Multi-Modal Vision Analysis
        'enable_multimodal_vision': False,
        'multimodal_vision_model': '',

        # Document Classification
        'enable_document_classification': False,
        'document_classification_categories': [
            {"label": "None", "color": "#808080"},
            {"label": "N/A", "color": "#808080"},
            {"label": "Pending", "color": "#0000FF"}
        ],

        # External Links
        'enable_external_links': False,
        'external_links_menu_name': 'External Links',
        'external_links_force_menu': False,
        'external_links': [
            {"label": "Acceptable Use Policy", "url": "https://example.com/policy"},
            {"label": "Prompt Ideas", "url": "https://example.com/prompts"}
        ],

        # Custom Pages
        'enable_custom_pages': False,
        'custom_pages_menu_name': 'Custom Pages',
        'custom_pages_force_menu': False,

        # Support Menu
        'enable_support_menu': False,
        'support_menu_name': 'Support',
        'enable_support_send_feedback': True,
        'support_feedback_recipient_email': '',
        'enable_support_latest_features': True,
        'enable_support_latest_feature_documentation_links': False,
        'support_latest_features_visibility': get_default_support_latest_features_visibility(),

        # Enhanced Citations
        'enable_enhanced_citations': False,
        'enable_enhanced_citations_mount': False,
        'enhanced_citations_mount': '/view_documents',
        'office_docs_storage_account_url': '',
        'office_docs_storage_account_blob_endpoint': '',
        'office_docs_authentication_type': 'key',
        'office_docs_key': '',
        'video_files_storage_account_url': '',
        'video_files_authentication_type': 'key',
        'video_files_key': '',
        'audio_files_storage_account_url': '',
        'audio_files_authentication_type': 'key',
        'audio_files_key': '',

        # Safety (Content Safety) Settings
        'enable_content_safety': False,
        'require_member_of_safety_violation_admin': False,
        'require_member_of_control_center_admin': False,
        'require_member_of_control_center_dashboard_reader': False,
        'content_safety_endpoint': '',
        'content_safety_key': '',
        'content_safety_authentication_type': 'key',
        'enable_content_safety_apim': False,
        'azure_apim_content_safety_endpoint': '',
        'azure_apim_content_safety_subscription_key': '',

        # User Feedback / Conversation Archiving
        'enable_user_feedback': True,
        'require_member_of_feedback_admin': False,
        'enable_conversation_archiving': False,

        # Processing Thoughts
        'enable_thoughts': True,

        # Collaborative Conversations
        'enable_collaborative_conversations': True,

        # Search and Extract
        'azure_ai_search_endpoint': '',
        'azure_ai_search_key': '',
        'azure_ai_search_authentication_type': 'key',
        'enable_ai_search_apim': False,
        'azure_apim_ai_search_endpoint': '',
        'azure_apim_ai_search_subscription_key': '',
        'enable_chunk_size_override': False,
        'chunk_size': {
            'txt': {'value': 400, 'unit': 'words'},
            'log': {'value': 1000, 'unit': 'words'},
            'doc': {'value': 400, 'unit': 'words'},
            'docm': {'value': 400, 'unit': 'words'},
            'docx': {'value': WORD_CHUNK_SIZE, 'unit': 'words'},
            'msg': {'value': 400, 'unit': 'words'},
            'html': {'value': 1200, 'unit': 'words'},
            'md': {'value': 1200, 'unit': 'words'},
            'xml': {'value': 4000, 'unit': 'characters'},
            'yaml': {'value': 4000, 'unit': 'characters'},
            'yml': {'value': 4000, 'unit': 'characters'},
            'json': {'value': 4000, 'unit': 'characters'},
            'csv': {'value': 800, 'unit': 'characters'},
            'excel': {'value': 800, 'unit': 'characters'},
            'transcript': {'value': 400, 'unit': 'words'},
            'pdf': {'value': 1, 'unit': 'pages'},
            'pptx': {'value': 1, 'unit': 'slides'},
            'vsdx': {'value': 1, 'unit': 'pages'}
        },
        
        # Search Result Caching
        'enable_search_result_caching': True,
        'search_cache_ttl_seconds': 300,

        # Service health warnings surfaced to admins and workspace users
        'service_health': get_default_service_health(),

        'azure_document_intelligence_endpoint': '',
        'azure_document_intelligence_key': '',
        'azure_document_intelligence_authentication_type': 'key',
        'document_intelligence_pdf_image_extraction_mode': 'read',
        'document_intelligence_auto_sample_pages': DOCUMENT_INTELLIGENCE_AUTO_SAMPLE_PAGES_DEFAULT,
        'enable_document_intelligence_apim': False,
        'azure_apim_document_intelligence_endpoint': '',
        'azure_apim_document_intelligence_subscription_key': '',

        # Web search (via Azure AI Foundry agent)
        'enable_web_search': False,
        'web_search_consent_accepted': False,
        'enable_web_search_user_notice': False,  # Show popup to users explaining their message will be sent to Bing
        'web_search_user_notice_text': 'Your current message will be sent to Microsoft Bing for web search. Conversation history is not sent for web search, but any sensitive content you paste into this message may be sent.',
        'web_search_agent': {
            'agent_type': 'aifoundry',
            'azure_openai_gpt_endpoint': '',
            'azure_openai_gpt_api_version': '',
            'azure_openai_gpt_deployment': '',
            'other_settings': {
                'azure_ai_foundry': {
                    'agent_id': '',
                    'endpoint': '',
                    'api_version': 'v1',
                    'authentication_type': 'managed_identity',
                    'managed_identity_type': 'system_assigned',
                    'managed_identity_client_id': '',
                    'tenant_id': '',
                    'client_id': '',
                    'client_secret': '',
                    'cloud': '',
                    'authority': '',
                    'notes': ''
                }
            }
        },

        # URL Access and Deep Research (bounded source-page inspection for web evidence)
        'enable_url_access': False,
        'url_access_max_chat_urls_per_turn': 10,
        'url_access_max_workflow_urls_per_run': 50,
        'url_access_allowed_domains': [],
        'url_access_blocked_domains': [],
        'require_member_of_url_access_user': False,
        'enable_source_review': False,
        'require_member_of_deep_research_user': False,
        'source_review_allow_internal_hosts': False,
        'enable_deep_source_review': True,
        'source_review_default_mode': 'manual',
        'source_review_max_pages_per_turn': 10,
        'source_review_max_seed_pages_per_turn': 10,
        'source_review_max_depth': 2,
        'source_review_timeout_seconds': 30,
        'source_review_max_redirects': 5,
        'source_review_max_bytes_per_page': 5000000,
        'deep_research_max_user_urls_per_turn': 100,
        'deep_research_max_search_queries_per_turn': 8,
        'deep_research_enable_query_planning': True,
        'deep_research_enable_ledger_artifact': True,
        'source_review_enable_llm_planning': True,
        'source_review_allow_js_rendering': True,
        'source_review_js_load_more_clicks': 12,
        'source_review_respect_robots_txt': True,
        'source_review_allowed_domains': [],
        'source_review_blocked_domains': [],
        'source_review_allowed_users': [],
        'source_review_blocked_users': [],
        'source_review_audit_logging': True,

        # Authentication & Redirect Settings
        'enable_front_door': False,
        'front_door_url': '',

        # Other
        'max_file_size_mb': 150,
        'max_generated_chat_artifact_size_mb': 500,
        'tabular_preview_max_blob_size_mb': 200,
        'conversation_history_limit': 10,
        'enable_idle_timeout': False,
        'idle_timeout_minutes': 30,
        'idle_warning_minutes': 28,
        'idle_warning_message': "You've been inactive for a while.",
        'default_system_prompt': '',
        # Access denied message shown on the home page for signed-in users who lack required roles.
        # Default is hard-coded; admins can override via Admin Settings (persisted in Cosmos DB).
        'access_denied_message': 'You are logged in but do not have the required permissions to access this application.\nPlease contact an administrator for access.',
        'access_request_button_enabled': False,
        'access_request_button_text': 'Request Access',
        'access_request_page_url': '/custom/request-access',
        'enable_file_processing_logs': True,
        'file_processing_logs_timer_enabled': False,
        'file_timer_value': 1,
        'file_timer_unit': 'hours',
        'file_processing_logs_turnoff_time': None,
        # Streaming settings
        'streamingEnabled': True,
        
        # Reasoning effort settings (per-model)
        'reasoningEffortSettings': {},

        # Video file settings with Azure Video Indexer Settings
        'video_indexer_endpoint': video_indexer_endpoint,
        'video_indexer_location': '',
        'video_indexer_account_id': '',
        'video_indexer_resource_group': '',
        'video_indexer_subscription_id': '',
        'video_indexer_account_name': '',
        'video_indexer_arm_api_version': DEFAULT_VIDEO_INDEXER_ARM_API_VERSION,
        'video_index_timeout': 600,

        # Audio file settings with Azure speech service
        "speech_service_endpoint": '',
        "speech_service_location": '',
        "speech_service_subscription_id": '',
        "speech_service_resource_group": '',
        "speech_service_resource_name": '',
        "speech_service_resource_id": '',
        "speech_service_locale": "en-US",
        "speech_service_key": "",
        "speech_service_authentication_type": "key",  # 'key' or 'managed_identity'
        
        # Speech-to-text chat input
        "enable_speech_to_text_input": False,
        
        # Text-to-speech chat output
        "enable_text_to_speech": False,
        
        #key vault settings
        'enable_key_vault_secret_storage': False,
        'key_vault_name': '',
        'key_vault_identity': '',
        
        # Retention Policy Settings
        'enable_retention_policy_personal': False,
        'enable_retention_policy_group': False,
        'enable_retention_policy_public': False,
        'retention_policy_execution_hour': 2,  # Run at 2 AM by default (0-23)
        'retention_policy_last_run': None,  # ISO timestamp of last execution
        'retention_policy_next_run': None,  # ISO timestamp of next scheduled execution
        'retention_conversation_min_days': 1,
        'retention_conversation_max_days': 3650,  # ~10 years
        'retention_document_min_days': 1,
        'retention_document_max_days': 3650,  # ~10 years
        # Default retention policies for each workspace type
        # 'none' means no automatic deletion (users can still set their own)
        # Numeric values (e.g., 30, 60, 90, 180, 365, 730) represent days
        'default_retention_conversation_personal': 'none',
        'default_retention_document_personal': 'none',
        'default_retention_conversation_group': 'none',
        'default_retention_document_group': 'none',
        'default_retention_conversation_public': 'none',
        'default_retention_document_public': 'none',
    }

    def _format_result(settings_payload, source):
        if include_source:
            return settings_payload, source
        return settings_payload

    try:
        # Attempt to read the existing doc
        if use_cosmos:
            settings_item = cosmos_settings_container.read_item(
                item="app_settings",
                partition_key="app_settings"
            )
            settings_source = "cosmos_forced"
            log_event(
                "App settings loaded from Cosmos DB (forced).",
                extra={
                    "settings_source": settings_source,
                    "use_cosmos": True
                },
                level=logging.INFO
            )
        else:
            settings_item = None
            settings_source = "cache"

            cache_accessor = getattr(app_settings_cache, "get_settings_cache", None)
            if callable(cache_accessor):
                try:
                    settings_item = cache_accessor()
                except Exception as cache_error:
                    settings_item = None
                    log_event(
                        "Error reading app settings from cache accessor.",
                        extra={
                            "error": str(cache_error)
                        },
                        level=logging.WARNING
                    )

            if not settings_item:
                settings_source = "cosmos_fallback"
                settings_item = cosmos_settings_container.read_item(
                    item="app_settings",
                    partition_key="app_settings"
                )

                frame = inspect.currentframe()
                caller = frame.f_back  # the function that called *this* code

                if caller is not None:
                    code = caller.f_code
                    caller_file = code.co_filename
                    caller_line = caller.f_lineno
                    caller_func = code.co_name

                    log_event(
                        "App settings cache miss. Falling back to Cosmos DB.",
                        extra={
                            "settings_source": settings_source,
                            "caller_file": caller_file,
                            "caller_line": caller_line,
                            "caller_func": caller_func
                        },
                        level=logging.WARNING
                    )
                else:

                    log_event(
                        "App settings cache miss. Falling back to Cosmos DB (no caller frame).",
                        extra={
                            "settings_source": settings_source
                        },
                        level=logging.WARNING
                    )

        # Merge default_settings in, to fill in any missing or nested keys
        merge_changed = deep_merge_dicts(default_settings, settings_item)
        merged = settings_item
        migration_updated = apply_custom_endpoint_setting_migration(merged)
        assignment_settings_updated = normalize_group_workflow_assignment_settings(merged)
        promoted_popular_settings_updated = normalize_agents_page_promoted_popular_settings(merged)

        merged['enable_tabular_processing_plugin'] = is_tabular_processing_enabled(merged)

        # If merging added anything new, upsert back to Cosmos so future reads remain up to date
        if merge_changed or migration_updated or assignment_settings_updated or promoted_popular_settings_updated:
            cosmos_settings_container.upsert_item(merged)
            _refresh_app_settings_cache_after_write(merged, context="merge_upsert")

            log_event(
                "App settings defaults or migrations were persisted to Cosmos DB.",
                extra={
                    "settings_source": settings_source
                },
                level=logging.INFO
            )
            return _format_result(merged, settings_source)
        else:
            # If merged is unchanged, no new keys needed
            return _format_result(merged, settings_source)

    except CosmosResourceNotFoundError:
        cosmos_settings_container.create_item(body=default_settings)
        _refresh_app_settings_cache_after_write(default_settings, context="default_create")

        log_event(
            "App settings document not found. Default settings created in Cosmos DB.",
            extra={
                "settings_source": "cosmos_default_created"
            },
            level=logging.WARNING
        )
        return _format_result(default_settings, "cosmos_default_created")

    except Exception as e:
        log_event(
            "Error retrieving app settings.",
            extra={
                "error": str(e),
                "use_cosmos": use_cosmos
            },
            level=logging.ERROR,
            exceptionTraceback=True
        )
        return _format_result(None, "error")

def update_settings(new_settings):
    try:
        # always fetch the latest settings doc, which includes your merges
        settings_item = get_settings()
        existing_multi_endpoint_enabled = settings_item.get('enable_multi_model_endpoints', False)
        settings_item.update(new_settings)
        normalize_group_workflow_assignment_settings(settings_item)
        normalize_agents_page_promoted_popular_settings(settings_item)
        settings_item['enable_multi_model_endpoints'] = coerce_multi_model_endpoint_enablement(
            existing_multi_endpoint_enabled,
            settings_item.get('enable_multi_model_endpoints', False),
        )
        settings_item['enable_tabular_processing_plugin'] = is_tabular_processing_enabled(settings_item)
        cosmos_settings_container.upsert_item(settings_item)
        _refresh_app_settings_cache_after_write(settings_item, context="update_settings")
        log_event(
            "App settings updated successfully.",
            level=logging.INFO
        )
        return True
    except Exception as e:
        log_event(
            "Error updating app settings.",
            extra={
                "error": str(e)
            },
            level=logging.ERROR,
            exceptionTraceback=True
        )
        return False


def coerce_multi_model_endpoint_enablement(existing_enabled, requested_enabled):
    """Treat multi-endpoint enablement as one-way once it has been turned on."""
    return bool(existing_enabled) or bool(requested_enabled)


def get_chunk_size_defaults():
    """Return the baseline chunk size configuration used when overrides are disabled."""
    return {
        'txt': {'value': 400, 'unit': 'words'},
        'log': {'value': 1000, 'unit': 'words'},
        'doc': {'value': 400, 'unit': 'words'},
        'docm': {'value': 400, 'unit': 'words'},
        'docx': {'value': WORD_CHUNK_SIZE, 'unit': 'words'},
        'msg': {'value': 400, 'unit': 'words'},
        'html': {'value': 1200, 'unit': 'words'},
        'md': {'value': 1200, 'unit': 'words'},
        'xml': {'value': 4000, 'unit': 'characters'},
        'yaml': {'value': 4000, 'unit': 'characters'},
        'yml': {'value': 4000, 'unit': 'characters'},
        'json': {'value': 4000, 'unit': 'characters'},
        'csv': {'value': 800, 'unit': 'characters'},
        'excel': {'value': 800, 'unit': 'characters'},
        'transcript': {'value': 400, 'unit': 'words'},
        'pdf': {'value': 1, 'unit': 'pages'},
        'pptx': {'value': 1, 'unit': 'slides'},
        'vsdx': {'value': 1, 'unit': 'pages'}
    }


def get_chunk_size_cap(settings=None):
    """Return the maximum allowed chunk size (2x embedding context window, fallback 16,384)."""
    fallback_cap = 16384
    try:
        settings = settings or get_settings()
        embedding_model = settings.get('embedding_model', {}) if isinstance(settings, dict) else {}
        selected_models = embedding_model.get('selected') or []

        base_context = None
        for model in selected_models:
            if not isinstance(model, dict):
                continue
            for key in ['context_window', 'contextWindow', 'maxContextTokens', 'context_length', 'contextLength', 'maxTokens']:
                value = model.get(key)
                if value is not None:
                    try:
                        parsed_value = int(value)
                        if parsed_value > 0:
                            base_context = parsed_value
                            break
                    except Exception:
                        continue
            if base_context:
                break

        if base_context and base_context > 0:
            return base_context * 2
    except Exception:
        pass

    return fallback_cap


def get_chunk_size_config(settings=None):
    """
    Compute the effective chunk size configuration, respecting defaults, caps, and the override toggle.
    When overrides are disabled, defaults are returned regardless of stored values.
    """
    settings = settings or get_settings()
    defaults = get_chunk_size_defaults()
    use_custom = isinstance(settings, dict) and settings.get('enable_chunk_size_override', False)
    stored = settings.get('chunk_size', {}) if isinstance(settings, dict) else {}
    cap = get_chunk_size_cap(settings)

    normalized = {}
    for key, default_meta in defaults.items():
        incoming_meta = stored.get(key, {}) if use_custom and isinstance(stored, dict) else {}
        unit = incoming_meta.get('unit', default_meta['unit']) if isinstance(incoming_meta, dict) else default_meta['unit']
        try:
            raw_value = int(incoming_meta.get('value', default_meta['value'])) if isinstance(incoming_meta, dict) else int(default_meta['value'])
        except Exception:
            raw_value = default_meta['value']

        value = max(1, raw_value)
        value = min(value, cap)

        normalized[key] = {
            'value': value,
            'unit': unit
        }

    return normalized

def compare_versions(v1_str, v2_str):
    """
    Manually compares two version strings (e.g., "1.0.0", "1.1").
    Returns:
        1 if v1 > v2
       -1 if v1 < v2
        0 if v1 == v2
       None if parsing fails or formats are invalid.
    """
    if not v1_str or not v2_str:
        return None # Cannot compare empty strings

    # Basic cleanup (remove potential 'v' prefix and whitespace)
    v1_str = v1_str.strip().lstrip('vV')
    v2_str = v2_str.strip().lstrip('vV')

    try:
        # Use regex to ensure parts are only digits before converting
        if not re.match(r'^\d+(\.\d+)*$', v1_str) or not re.match(r'^\d+(\.\d+)*$', v2_str):
             raise ValueError("Invalid characters in version string")
        v1_parts = [int(part) for part in v1_str.split('.')]
        v2_parts = [int(part) for part in v2_str.split('.')]
    except ValueError:
        # Handle cases where parts are not integers or contain invalid chars
        log_event(
            "Invalid version format encountered during comparison.",
            extra={
                "version_1": v1_str,
                "version_2": v2_str
            },
            level=logging.WARNING
        )
        return None

    # Compare parts element by element
    len_v1 = len(v1_parts)
    len_v2 = len(v2_parts)
    max_len = max(len_v1, len_v2)

    for i in range(max_len):
        part1 = v1_parts[i] if i < len_v1 else 0 # Treat missing parts as 0
        part2 = v2_parts[i] if i < len_v2 else 0

        if part1 > part2:
            return 1
        if part1 < part2:
            return -1

    # If all compared parts are equal, they are the same version
    return 0

def extract_latest_version_from_html(html_content):
    """
    Parses HTML content (expected from GitHub releases page) to find the latest version tag.

    Args:
        html_content (str): The HTML content as a string.

    Returns:
        str: The latest version string (e.g., "0.203.16") found, or None if no
             valid versions are found or an error occurs.
    """
    if not html_content:
        log_event(
            "Latest-version extraction skipped because HTML content is empty.",
            level=logging.WARNING
        )
        return None

    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        versions_found = set() # Use a set to store unique version strings

        # Find all <a> tags which are likely candidates for version tags
        # Looking for links with '/releases/tag/v' in href seems most reliable
        links = soup.find_all('a', href=True)

        for link in links:
            href = link.get('href')
            # Check if the link points to a release tag URL
            if href and '/releases/tag/v' in href:
                try:
                    # Extract the part after '/tag/' which should be like 'vX.Y.Z'
                    tag_part = href.split('/tag/')[-1]
                    # Ensure it starts with 'v' and has content after 'v'
                    if tag_part.startswith('v') and len(tag_part) > 1:
                        version_str = tag_part[1:] # Remove the leading 'v'
                        # Validate the format (digits and dots only) using regex
                        if re.match(r'^\d+(\.\d+)*$', version_str):
                            versions_found.add(version_str)

                except (IndexError, ValueError):
                    # Ignore links where splitting or processing fails
                    continue # Skip to the next link

        if not versions_found:
            log_event(
                "No valid release version tags found in HTML content.",
                level=logging.WARNING
            )
            return None

        # Now compare the found versions to find the latest
        latest_version = None
        for current_version in versions_found:
            if latest_version is None:
                latest_version = current_version
            else:
                comparison_result = compare_versions(current_version, latest_version)

                if comparison_result == 1: # current_version > latest_version
                    latest_version = current_version
                elif comparison_result is None:
                     # Log if comparison fails, but continue trying others
                     log_event(
                         "Could not compare release version values while scanning HTML.",
                         extra={
                             "current_version": current_version,
                             "latest_version": latest_version
                         },
                         level=logging.WARNING
                     )

        log_event(
            "Latest release version identified from HTML.",
            extra={
                "latest_version": latest_version
            },
            level=logging.INFO
        )
        return latest_version

    except Exception as e:
        log_event(
            "Error parsing HTML while identifying latest release version.",
            extra={
                "error": str(e)
            },
            level=logging.ERROR,
            exceptionTraceback=True
        )
        return None
    
def deep_merge_dicts(default_dict, existing_dict):
    """
    Recursively merge keys from default_dict into existing_dict in place.
    This function DOES NOT return a merged dictionary. Instead, it mutates
    existing_dict directly, adding any keys that are missing (and, for nested
    dict values, recursing to merge their contents as well). Non-dict values
    in existing_dict are left as-is and are not overwritten.

    Args:
        default_dict (dict): Source of default values.
        existing_dict (dict): Target dictionary that will be updated in place.
        
    Returns:
        bool: True if existing_dict was modified at any depth, otherwise False.
    """
    changed = False
    for k, default_val in default_dict.items():
        if k not in existing_dict:
            existing_dict[k] = default_val
            changed = True
        else:
            existing_val = existing_dict[k]
            if isinstance(default_val, dict) and isinstance(existing_val, dict):
                if deep_merge_dicts(default_val, existing_val):
                    changed = True
            # For lists or other types, we skip overwriting.
    return changed

def apply_custom_endpoint_setting_migration(settings_item):
    if not isinstance(settings_item, dict):
        return False

    updated = False
    if "allow_user_custom_endpoints" not in settings_item:
        settings_item["allow_user_custom_endpoints"] = settings_item.get("allow_user_custom_agent_endpoints", False)
        updated = True
    if "allow_group_custom_endpoints" not in settings_item:
        settings_item["allow_group_custom_endpoints"] = settings_item.get("allow_group_custom_agent_endpoints", False)
        updated = True

    if settings_item.get("allow_user_custom_agent_endpoints") != settings_item.get("allow_user_custom_endpoints"):
        settings_item["allow_user_custom_agent_endpoints"] = settings_item.get("allow_user_custom_endpoints", False)
        updated = True
    if settings_item.get("allow_group_custom_agent_endpoints") != settings_item.get("allow_group_custom_endpoints"):
        settings_item["allow_group_custom_agent_endpoints"] = settings_item.get("allow_group_custom_endpoints", False)
        updated = True

    return updated

def normalize_model_endpoints(endpoints):
    """Normalize model endpoints with stable IDs and enabled flags."""
    if not isinstance(endpoints, list):
        return [], False

    normalized = []
    changed = False

    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            continue
        endpoint_copy = json.loads(json.dumps(endpoint))
        endpoint_copy.pop("has_api_key", None)
        endpoint_copy.pop("has_client_secret", None)
        connection = endpoint_copy.get("connection") or {}

        if not endpoint_copy.get("id"):
            fallback_id = endpoint_copy.get("name") or connection.get("endpoint")
            if fallback_id:
                endpoint_copy["id"] = fallback_id
                changed = True

        if endpoint_copy.get("enabled") is None:
            endpoint_copy["enabled"] = True
            changed = True

        models = endpoint_copy.get("models") or []
        normalized_models = []
        for model in models:
            if not isinstance(model, dict):
                continue
            model_copy = json.loads(json.dumps(model))
            if not model_copy.get("id"):
                model_id = (
                    model_copy.get("deploymentName")
                    or model_copy.get("deployment")
                    or model_copy.get("modelName")
                    or model_copy.get("name")
                )
                if model_id:
                    model_copy["id"] = model_id
                    changed = True
            if model_copy.get("enabled") is None:
                model_copy["enabled"] = True
                changed = True
            try:
                normalized_icon = normalize_icon_payload(model_copy.get("icon"), field_name="model.icon")
            except ValueError:
                normalized_icon = {}
                if model_copy.get("icon"):
                    changed = True
            if model_copy.get("icon") != normalized_icon:
                model_copy["icon"] = normalized_icon
                changed = True
            normalized_models.append(model_copy)

        endpoint_copy["models"] = normalized_models
        normalized.append(endpoint_copy)

    return normalized, changed


def is_frontend_visible_model_endpoint_provider(provider):
    """Return whether the provider should be exposed in user-facing endpoint UIs."""
    normalized_provider = (provider or "aoai").lower()
    return normalized_provider in {"aoai", "aifoundry", "new_foundry"}


def merge_model_endpoint_auth(existing_auth, incoming_auth):
    """Merge endpoint auth settings while preserving stored secrets when inputs are blank."""
    if not isinstance(existing_auth, dict):
        existing_auth = {}
    if not isinstance(incoming_auth, dict):
        incoming_auth = {}

    merged = dict(existing_auth)
    for key, value in incoming_auth.items():
        if value in (None, ""):
            continue
        merged[key] = value
    return merged


def merge_model_endpoint_payload(existing_endpoint, incoming_endpoint):
    """Merge an incoming endpoint payload with an existing saved endpoint."""
    if not isinstance(existing_endpoint, dict):
        return incoming_endpoint if isinstance(incoming_endpoint, dict) else {}
    if not isinstance(incoming_endpoint, dict):
        return dict(existing_endpoint)

    merged = dict(existing_endpoint)
    for key, value in incoming_endpoint.items():
        if key == "auth":
            merged["auth"] = merge_model_endpoint_auth(existing_endpoint.get("auth"), value)
            continue
        if value in (None, ""):
            continue
        merged[key] = value
    return merged


def merge_model_endpoints_with_existing(incoming_endpoints, existing_endpoints):
    """Merge endpoint lists by endpoint ID so edits preserve stored auth values."""
    if not isinstance(incoming_endpoints, list):
        return []

    existing_by_id = {}
    if isinstance(existing_endpoints, list):
        existing_by_id = {
            endpoint.get("id"): endpoint
            for endpoint in existing_endpoints
            if isinstance(endpoint, dict) and endpoint.get("id")
        }

    merged = []
    incoming_endpoint_ids = set()
    for endpoint in incoming_endpoints:
        if not isinstance(endpoint, dict):
            continue
        endpoint_id = endpoint.get("id")
        if endpoint_id:
            incoming_endpoint_ids.add(endpoint_id)
        existing_endpoint = existing_by_id.get(endpoint_id)
        merged.append(merge_model_endpoint_payload(existing_endpoint or {}, endpoint))

    if isinstance(existing_endpoints, list):
        for endpoint in existing_endpoints:
            if not isinstance(endpoint, dict):
                continue
            endpoint_id = endpoint.get("id")
            if endpoint_id in incoming_endpoint_ids:
                continue
            if is_frontend_visible_model_endpoint_provider(endpoint.get("provider")):
                continue
            merged.append(json.loads(json.dumps(endpoint)))

    return merged


def sanitize_model_endpoints_for_frontend(endpoints):
    """Return model endpoint configs with secrets stripped for frontend use."""
    normalized, _ = normalize_model_endpoints(endpoints)
    if not isinstance(normalized, list):
        return []

    sanitized = []
    for endpoint in normalized:
        if not isinstance(endpoint, dict):
            continue
        if not is_frontend_visible_model_endpoint_provider(endpoint.get("provider")):
            continue
        endpoint_copy = json.loads(json.dumps(endpoint))
        auth = endpoint_copy.get("auth") or {}
        has_api_key = bool(auth.get("api_key"))
        has_client_secret = bool(auth.get("client_secret"))
        auth.pop("api_key", None)
        auth.pop("client_secret", None)
        endpoint_copy["auth"] = auth
        endpoint_copy["has_api_key"] = has_api_key
        endpoint_copy["has_client_secret"] = has_client_secret
        sanitized.append(endpoint_copy)

    return sanitized

def encrypt_key(key):
    cipher_suite = Fernet(app.config['SECRET_KEY'])
    encrypted_key = cipher_suite.encrypt(key.encode())
    return encrypted_key.decode()

def decrypt_key(encrypted_key):
    cipher_suite = Fernet(app.config['SECRET_KEY'])
    try:
        encrypted_key_bytes = base64.urlsafe_b64decode(encrypted_key.encode())
        decrypted_key = cipher_suite.decrypt(encrypted_key_bytes).decode()
        return decrypted_key
    except InvalidToken:
        log_event(
            "Decryption failed due to invalid token.",
            level=logging.WARNING
        )
        return None

def get_user_settings(user_id, allow_cross_user=False):
    """Fetches the user settings document from Cosmos DB, ensuring email and display_name are present if possible."""
    actor_user_id = _authorize_user_settings_access(user_id, "read", allow_cross_user=allow_cross_user)
    should_sync_session_profile = _should_sync_session_profile(
        user_id,
        actor_user_id,
        allow_cross_user=allow_cross_user,
    )

    cached_doc = _get_request_cached_user_settings(user_id)
    if cached_doc is not None:
        return cached_doc

    try:
        doc = cosmos_user_settings_container.read_item(item=user_id, partition_key=user_id)
        updated = False

        # Ensure the settings key exists for consistency downstream
        if 'settings' not in doc or not isinstance(doc.get('settings'), dict):
            previous_type = type(doc.get('settings')).__name__ if 'settings' in doc else 'missing'
            doc['settings'] = {}
            updated = True
            log_event("[UserSettings] Malformed settings repaired", {
                "user_id": user_id,
                "previous_type": previous_type,
            })

        if 'personal_model_endpoints' not in doc['settings']:
            doc['settings']['personal_model_endpoints'] = []
        if 'showTutorialButtons' not in doc['settings']:
            doc['settings']['showTutorialButtons'] = True
            updated = True
        
        if should_sync_session_profile:
            # Try to update email/display_name if missing and available in session
            user = session.get("user", {})
            email = user.get("preferred_username") or user.get("email")
            display_name = user.get("name")
            if email and doc.get("email") != email:
                doc["email"] = email
                updated = True
            if display_name and doc.get("display_name") != display_name:
                doc["display_name"] = display_name
                updated = True

            # Check if profile image needs to be fetched
            if 'profileImage' not in doc['settings']:
                from functions_authentication import get_user_profile_image
                try:
                    profile_image = get_user_profile_image()
                    doc['settings']['profileImage'] = profile_image
                    updated = True
                except Exception as e:
                    log_event(
                        "Could not fetch profile image for existing user.",
                        extra={
                            "user_id": user_id,
                            "error": str(e)
                        },
                        level=logging.WARNING
                    )
                    doc['settings']['profileImage'] = None
                    updated = True
        
        if updated:
            cosmos_user_settings_container.upsert_item(body=doc)
            _set_user_ui_settings_cache(user_id, doc)

        _set_request_cached_user_settings(user_id, doc)
        return _clone_user_settings_doc(doc)
    except exceptions.CosmosResourceNotFoundError:
        # Return a default structure if the user has no settings saved yet
        doc = {"id": user_id, "settings": {}}
        doc["settings"]["personal_model_endpoints"] = []
        doc["settings"]["showTutorialButtons"] = True
        if should_sync_session_profile:
            user = session.get("user", {})
            email = user.get("preferred_username") or user.get("email")
            display_name = user.get("name")
            if email:
                doc["email"] = email
            if display_name:
                doc["display_name"] = display_name

            # Try to fetch profile image for new user
            from functions_authentication import get_user_profile_image
            try:
                profile_image = get_user_profile_image()
                doc['settings']['profileImage'] = profile_image
            except Exception as e:
                log_event(
                    "Could not fetch profile image for new user.",
                    extra={
                        "user_id": user_id,
                        "error": str(e)
                    },
                    level=logging.WARNING
                )
                doc['settings']['profileImage'] = None
            
        cosmos_user_settings_container.upsert_item(body=doc)
        _set_user_ui_settings_cache(user_id, doc)
        _set_request_cached_user_settings(user_id, doc)
        return _clone_user_settings_doc(doc)
    except Exception as e:
        log_event(
            "Error retrieving user settings.",
            extra={
                "user_id": user_id,
                "error": str(e)
            },
            level=logging.ERROR,
            exceptionTraceback=True
        )
        raise # Re-raise the exception to be handled by the route


def get_user_ui_settings(user_id, allow_cross_user=False):
    """Return a lightweight, cacheable subset of user settings used by shared page chrome."""
    _authorize_user_settings_access(user_id, "read UI settings", allow_cross_user=allow_cross_user)

    cached_doc = _get_request_cached_user_settings(user_id)
    if cached_doc is not None:
        return {
            'id': user_id,
            'settings': _extract_user_ui_settings(cached_doc),
        }

    cache_getter = getattr(app_settings_cache, "get_user_ui_settings_cache", None)
    if callable(cache_getter):
        try:
            cached_ui_settings = cache_getter(user_id)
            if cached_ui_settings is not None:
                return {
                    'id': user_id,
                    'settings': copy.deepcopy(cached_ui_settings or {}),
                }
        except Exception as cache_error:
            log_event(
                "[UserSettingsCache] Failed to read user UI settings cache.",
                extra={
                    "user_id": user_id,
                    "error": str(cache_error)
                },
                level=logging.WARNING
            )

    doc = get_user_settings(user_id, allow_cross_user=allow_cross_user)
    _set_user_ui_settings_cache(user_id, doc)
    return {
        'id': user_id,
        'settings': _extract_user_ui_settings(doc),
    }
    
def update_user_settings(user_id, settings_to_update, allow_cross_user=False):
    """
    Updates or creates user settings in Cosmos DB, merging new settings
    into the existing 'settings' sub-dictionary and updating 'lastUpdated'.

    Args:
        user_id (str): The ID of the user.
        settings_to_update (dict): A dictionary containing the specific
                                   settings key/value pairs to update.

    Returns:
        bool: True if the update was successful, False otherwise.
    """
    actor_user_id = _authorize_user_settings_access(
        user_id,
        "update",
        allow_cross_user=allow_cross_user,
    )
    sanitized_settings_to_update = sanitize_settings_for_logging(settings_to_update)
    log_event(
        "[UserSettings] Update Attempt",
        {
            "user_id": user_id,
            "actor_user_id": actor_user_id,
            "allow_cross_user": allow_cross_user,
            "settings_to_update": sanitized_settings_to_update,
        },
    )


    try:
        # Try to read the existing document
        try:
            doc = cosmos_user_settings_container.read_item(item=user_id, partition_key=user_id)

            # Ensure the 'settings' key exists and is a dictionary
            if 'settings' not in doc or not isinstance(doc.get('settings'), dict):
                doc['settings'] = {}


        except exceptions.CosmosResourceNotFoundError:

            # Document doesn't exist, create the basic structure
            doc = {
                "id": user_id,
                "settings": {} # Initialize the settings dictionary
                # Add any other default top-level fields if needed
            }


        # --- Merge the new settings into the 'settings' sub-dictionary ---
        doc['settings'].update(settings_to_update)

        # Ensure 'agents' and 'plugins' keys exist in settings
        if 'agents' not in doc['settings'] or doc['settings']['agents'] is None:
            doc['settings']['agents'] = [
                {
                    "id": f"{user_id}_researcher",
                    "name": "researcher",
                    "display_name": "researcher",
                    "description": "This agent is detailed to provide researcher capabilities and uses a reasoning and research focused model.",
                    "azure_openai_gpt_endpoint": "",
                    "azure_openai_gpt_key": "",
                    "azure_openai_gpt_deployment": "",
                    "azure_openai_gpt_api_version": "",
                    "azure_agent_apim_gpt_endpoint": "",
                    "azure_agent_apim_gpt_subscription_key": "",
                    "azure_agent_apim_gpt_deployment": "",
                    "azure_agent_apim_gpt_api_version": "",
                    "enable_agent_gpt_apim": False,
                    "default_agent": True,
                    "is_global": False,
                    "instructions": "You are a highly capable research assistant. Your role is to help the user investigate academic, technical, and real-world topics by finding relevant information, summarizing key points, identifying knowledge gaps, and suggesting credible sources for further study.\n\nYou must always:\n- Think step-by-step and work methodically.\n- Distinguish between fact, inference, and opinion.\n- Clearly state your assumptions when making inferences.\n- Cite authoritative sources when possible (e.g., peer-reviewed journals, academic publishers, government agencies).\n- Avoid speculation unless explicitly asked for.\n- When asked to summarize, preserve the intent, nuance, and technical accuracy of the original content.\n- When generating questions, aim for depth and clarity to guide rigorous inquiry.\n- Present answers in a clear, structured format using bullet points, tables, or headings when appropriate.\n\nUse a professional, neutral tone. Do not anthropomorphize yourself or refer to yourself as an AI unless the user specifically asks you to reflect on your capabilities. Remain focused on delivering objective, actionable research insights.\n\nIf you encounter ambiguity or uncertainty, ask clarifying questions rather than assuming.",
                    "actions_to_load": [],
                    "other_settings": {},
                }
            ]
        if 'plugins' not in doc['settings'] or doc['settings']['plugins'] is None:
            doc['settings']['plugins'] = []
        if 'selected_agent' not in doc['settings'] or doc['settings']['selected_agent'] is None:
            first_user_agent = doc['settings']['agents'][0]
            if first_user_agent:
                doc['settings']['selected_agent'] = {
                    'id': first_user_agent.get('id'),
                    'name': first_user_agent['name'],
                    'display_name': first_user_agent.get('display_name', first_user_agent['name']),
                    'is_global': False,
                    'is_group': False,
                    'group_id': None,
                    'group_name': None,
                }
            else:
                settings = get_settings()
                if settings.get('merge_global_semantic_kernel_with_workspace', False):
                    # Use new container-based storage for global agents
                    from functions_global_agents import get_all_global_agents
                    try:
                        global_agents = get_all_global_agents()
                        if global_agents:
                            first_global_agent = global_agents[0]
                            doc['settings']['selected_agent'] = {
                                'id': first_global_agent.get('id'),
                                'name': first_global_agent['name'],
                                'display_name': first_global_agent.get('display_name', first_global_agent['name']),
                                'is_global': True,
                                'is_group': False,
                                'group_id': None,
                                'group_name': None,
                            }
                        else:
                            doc['settings']['selected_agent'] = {
                                'id': None,
                                'name': 'default_agent',
                                'display_name': 'default_agent',
                                'is_global': True,
                                'is_group': False,
                                'group_id': None,
                                'group_name': None,
                            }
                    except Exception:
                        # Fallback if container access fails
                        doc['settings']['selected_agent'] = {
                            'id': None,
                            'name': 'default_agent',
                            'display_name': 'default_agent',
                            'is_global': True,
                            'is_group': False,
                            'group_id': None,
                            'group_name': None,
                        }
                else:
                    doc['settings']['selected_agent'] = {
                        'id': None,
                        'name': 'researcher',
                        'display_name': 'researcher',
                        'is_global': False,
                        'is_group': False,
                        'group_id': None,
                        'group_name': None,
                    }

        if doc['settings']['agents'] is not None and len(doc['settings']['agents']) > 0:
            for agent in doc['settings']['agents']:
                if 'default_agent' in agent:
                    del agent['default_agent']

        if 'enable_agents' not in doc['settings'] or doc['settings']['enable_agents'] is None:
            doc['settings']['enable_agents'] = False

        # --- Update the timestamp ---
        # Use timezone-aware UTC time
        doc['lastUpdated'] = datetime.now(timezone.utc).isoformat()

        # Upsert the modified document
        cosmos_user_settings_container.upsert_item(body=doc) # Use body=doc for clarity
        _set_request_cached_user_settings(user_id, doc)
        _delete_user_ui_settings_cache(user_id)

        return True

    except exceptions.CosmosHttpResponseError as e:
        log_event(
            "User settings update failed with Cosmos DB HTTP error.",
            extra={
                "user_id": user_id,
                "error": str(e)
            },
            level=logging.ERROR,
            exceptionTraceback=True
        )

        return False
    except Exception as e:
        # Catch any other unexpected errors during the update process
        log_event(
            "User settings update failed with unexpected error.",
            extra={
                "user_id": user_id,
                "error": str(e)
            },
            level=logging.ERROR,
            exceptionTraceback=True
        )

        return False

def _is_api_request():
    return (
        request.accept_mimetypes.accept_json
        and not request.accept_mimetypes.accept_html
    ) or request.path.startswith('/api/')


def workflow_user_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        settings = get_settings()
        user_roles = (session.get('user') or {}).get('roles', [])
        if is_user_workflows_enabled_for_user(settings, user_roles=user_roles):
            return f(*args, **kwargs)

        if not settings.get('allow_user_workflows', False):
            message = 'Personal workflows are disabled.'
            if _is_api_request():
                return jsonify({'error': message}), 400
            return message, 400

        message = 'Personal workflows require the WorkflowUser app role.'
        if _is_api_request():
            return jsonify({'error': 'Forbidden', 'message': message}), 403
        return f'Forbidden: {message}', 403
    return wrapper


def enabled_required(setting_key):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            settings = get_settings()
            if not settings.get(setting_key, False):
                setting_key_as_statement = setting_key.replace("_", " ").title()
                return jsonify({"error": f"{setting_key_as_statement} is disabled."}), 400
            return f(*args, **kwargs)
        return wrapper
    return decorator

def sanitize_settings_for_user(full_settings: dict) -> dict:
    if not isinstance(full_settings, dict):
        return full_settings

    sensitive_terms = ("key", "secret", "password", "connection", "base64", "storage_account_url")
    sanitized = {}

    for k, v in full_settings.items():
        if k == 'support_feedback_recipient_email':
            continue
        if k == 'agents_page_promoted_popular_agents':
            continue
        if any(term in k.lower() for term in sensitive_terms):
            continue
        if k in ('model_endpoints', 'personal_model_endpoints') and isinstance(v, list):
            sanitized[k] = sanitize_model_endpoints_for_frontend(v)
            continue
        if isinstance(v, dict):
            sanitized[k] = sanitize_settings_for_user(v)
        elif isinstance(v, list):
            sanitized[k] = [
                sanitize_settings_for_user(item) if isinstance(item, dict) else item
                for item in v
            ]
        else:
            sanitized[k] = v

    # Add boolean flags for logo/favicon existence so templates can check without exposing base64 data
    # These fields are stripped by the base64 filter above, but templates need to know if logos exist
    if 'custom_logo_base64' in full_settings:
        sanitized['custom_logo_base64'] = bool(full_settings.get('custom_logo_base64'))
    if 'custom_logo_dark_base64' in full_settings:
        sanitized['custom_logo_dark_base64'] = bool(full_settings.get('custom_logo_dark_base64'))
    if 'custom_favicon_base64' in full_settings:
        sanitized['custom_favicon_base64'] = bool(full_settings.get('custom_favicon_base64'))

    if 'support_latest_features_visibility' in full_settings or 'enable_support_latest_features' in full_settings:
        sanitized['support_latest_features_visibility'] = normalize_support_latest_features_visibility(
            full_settings.get('support_latest_features_visibility', {})
        )
        sanitized['support_latest_features_has_visible_items'] = has_visible_support_latest_features(full_settings)
        sanitized['support_feedback_recipient_configured'] = bool(
            str(full_settings.get('support_feedback_recipient_email') or '').strip()
        )

    if isinstance(sanitized.get('multi_endpoint_migration_notice'), dict):
        sanitized['multi_endpoint_migration_notice'] = {
            **sanitized['multi_endpoint_migration_notice'],
            'enabled': False,
        }

    return sanitized

def sanitize_settings_for_logging(full_settings: dict) -> dict:
    """
    Recursively sanitize settings to remove sensitive data from debug logs.
    Filters out keys containing: key, base64, image, storage_account_url
    Also filters out values containing base64 data
    """
    if not isinstance(full_settings, dict):
        return full_settings
    
    sanitized = {}
    sensitive_key_terms = ["key", "base64", "image", "storage_account_url", "_secret"]
    
    for k, v in full_settings.items():
        # Skip keys with sensitive terms
        if any(term in k.lower() for term in sensitive_key_terms):
            sanitized[k] = "[REDACTED]"
            continue
        
        # Check if value is a string containing base64 data
        if isinstance(v, str) and ("base64," in v or len(v) > 500):
            sanitized[k] = "[BASE64_DATA_REDACTED]"
        # Recursively sanitize nested dicts
        elif isinstance(v, dict):
            sanitized[k] = sanitize_settings_for_logging(v)
        # Recursively sanitize lists
        elif isinstance(v, list):
            sanitized[k] = [sanitize_settings_for_logging(item) if isinstance(item, dict) else item for item in v]
        else:
            sanitized[k] = v
    
    return sanitized

# Search history management functions
def get_user_search_history(user_id):
    """Get user's search history from their settings document"""
    try:
        doc = cosmos_user_settings_container.read_item(item=user_id, partition_key=user_id)
        return doc.get('search_history', [])
    except exceptions.CosmosResourceNotFoundError:
        return []
    except Exception as e:
        log_event(
            "Error retrieving user search history.",
            extra={
                "user_id": user_id,
                "error": str(e)
            },
            level=logging.ERROR,
            exceptionTraceback=True
        )
        return []

def add_search_to_history(user_id, search_term):
    """Add a search term to user's history, maintaining max 20 items"""
    try:
        try:
            doc = cosmos_user_settings_container.read_item(item=user_id, partition_key=user_id)
        except exceptions.CosmosResourceNotFoundError:
            doc = {'id': user_id, 'settings': {}}
        
        search_history = doc.get('search_history', [])
        
        # Remove if already exists (deduplicate)
        search_history = [item for item in search_history if item.get('term') != search_term]
        
        # Add new search at beginning
        search_history.insert(0, {
            'term': search_term,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        
        # Trim to 20 items
        search_history = search_history[:20]
        
        doc['search_history'] = search_history
        cosmos_user_settings_container.upsert_item(body=doc)
        invalidate_user_settings_caches(user_id)
        
        return search_history
    except Exception as e:
        log_event(
            "Error adding search term to user history.",
            extra={
                "user_id": user_id,
                "error": str(e)
            },
            level=logging.ERROR,
            exceptionTraceback=True
        )
        return []

def clear_user_search_history(user_id):
    """Clear all search history for a user"""
    try:
        try:
            doc = cosmos_user_settings_container.read_item(item=user_id, partition_key=user_id)
        except exceptions.CosmosResourceNotFoundError:
            doc = {'id': user_id, 'settings': {}}
        
        doc['search_history'] = []
        cosmos_user_settings_container.upsert_item(body=doc)
        invalidate_user_settings_caches(user_id)
        
        return True
    except Exception as e:
        log_event(
            "Error clearing user search history.",
            extra={
                "user_id": user_id,
                "error": str(e)
            },
            level=logging.ERROR,
            exceptionTraceback=True
        )
        return False