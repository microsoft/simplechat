# app.py
import builtins
import bleach
import logging
import pickle
import json
import os
import sys

# Fix Windows encoding issue with Unicode characters (emojis, IPA symbols, etc.)
# Must be done before any print statements that might contain Unicode
if sys.platform == 'win32':
    try:
        # Reconfigure stdout and stderr to use UTF-8 encoding
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        # Python < 3.7 doesn't have reconfigure, try alternative
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

import app_settings_cache
from config import *
from semantic_kernel import Kernel
from semantic_kernel_loader import initialize_semantic_kernel

#from azure.monitor.opentelemetry import configure_azure_monitor

from functions_authentication import *
from functions_content import *
from functions_documents import *
from functions_latest_features_nav import should_hide_latest_features_nav
from admin_settings_nav import ADMIN_NAV, get_landing_tab_id
from functions_search import *
from functions_settings import *
from functions_mcp_server_config import is_mcp_ui_enabled
from functions_rate_limit import build_rate_limit_error_payload
from functions_appinsights import *
from functions_activity_logging import *

import threading
import time
from datetime import datetime
from flask import Blueprint, g, make_response
from urllib.parse import urlparse

from route_frontend_authentication import *
from route_frontend_profile import *
from route_frontend_admin_settings import *
from route_frontend_control_center import *
from route_frontend_workspace import *
from route_frontend_chats import *
from route_frontend_agents import *
from route_frontend_conversations import *
from route_frontend_groups import *
from route_frontend_group_workspaces import *
from route_frontend_public_workspaces import *
from route_frontend_safety import *
from route_frontend_feedback import *
from route_frontend_support import *
from route_frontend_notifications import *
from route_frontend_terms_of_use import register_route_frontend_terms_of_use
from route_frontend_v2 import register_route_frontend_v2
from route_custom_pages import register_route_custom_pages

from route_backend_chats import *
from route_backend_v2 import (
    register_route_backend_v2,
    register_route_backend_v2_admin,
)
from route_backend_search import *
from route_backend_conversations import *
from route_backend_documents import *
from route_backend_groups import *
from route_backend_users import *
from route_backend_group_documents import *
from route_backend_models import *
from route_backend_workflows import *
from route_backend_safety import *
from route_backend_feedback import *
from route_backend_settings import *
from route_backend_prompts import *
from route_backend_group_prompts import *
from route_backend_control_center import *
from route_backend_notifications import *
from route_backend_retention_policy import *
from route_backend_governance import register_route_backend_governance
from route_backend_plugins import bpap as admin_plugins_bp, bpdp as dynamic_plugins_bp
from route_backend_agents import bpa as admin_agents_bp
from route_backend_agent_templates import bp_agent_templates
from route_backend_public_workspaces import *
from route_backend_public_documents import *
from route_backend_public_prompts import *
from route_backend_file_sync import register_route_backend_file_sync
from route_backend_workspace_identities import register_route_backend_workspace_identities
from route_backend_user_agreement import register_route_backend_user_agreement
from route_backend_conversation_export import register_route_backend_conversation_export
from route_backend_thoughts import register_route_backend_thoughts
from route_backend_speech import register_route_backend_speech
from route_backend_tts import register_route_backend_tts
from route_backend_collaboration import register_route_backend_collaboration
from route_backend_data_management import register_route_backend_data_management
from route_backend_msgraph_pending_actions import register_route_backend_msgraph_pending_actions
from route_inbound_mcp import register_route_inbound_mcp
from route_enhanced_citations import register_enhanced_citations_routes
from plugin_validation_endpoint import plugin_validation_admin_bp, plugin_validation_bp
from route_openapi import register_openapi_routes
from route_migration import bp_migration
from route_plugin_logging import bpl as plugin_logging_bp
from functions_custom_pages import get_custom_pages_nav
from functions_debug import debug_print
from functions_terms_of_use import has_terms_of_use_acceptance
from functions_mcp_server_auth import inbound_mcp_required_blueprint

from opentelemetry.instrumentation.flask import FlaskInstrumentor

app = Flask(__name__, static_url_path='/static', static_folder='static')

disable_flask_instrumentation = os.environ.get("DISABLE_FLASK_INSTRUMENTATION", "0")
if not (disable_flask_instrumentation == "1" or disable_flask_instrumentation.lower() == "true"):
    FlaskInstrumentor().instrument_app(app)

app.config['EXECUTOR_TYPE'] = EXECUTOR_TYPE
app.config['EXECUTOR_MAX_WORKERS'] = EXECUTOR_MAX_WORKERS
executor = Executor()
executor.init_app(app)
app.config['SESSION_TYPE'] = SESSION_TYPE
app.config['VERSION'] = VERSION
app.config['IS_DEVELOPMENT'] = IS_DEVELOPMENT
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SESSION_COOKIE_SAMESITE'] = SESSION_COOKIE_SAMESITE
app.config['SESSION_COOKIE_HTTPONLY'] = SESSION_COOKIE_HTTPONLY
app.config['SESSION_COOKIE_SECURE'] = SESSION_COOKIE_SECURE

# Ensure filesystem session directory (when used) points to a writable path inside container.
if SESSION_TYPE == 'filesystem':
    app.config['SESSION_FILE_DIR'] = globals().get('SESSION_FILE_DIR', os.environ.get('SESSION_FILE_DIR', '/app/flask_session'))
    try:
        os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)
    except Exception as e:
        print(f"WARNING: Unable to create session directory {app.config.get('SESSION_FILE_DIR')}: {e}")
        log_event(f"Unable to create session directory {app.config.get('SESSION_FILE_DIR')}: {e}", level=logging.ERROR)

Session(app)


def register_route_blueprint(name, registrar, auth_guard=None):
    """Register a route module through a Blueprint and optional auth policy guard."""
    bp = Blueprint(name, __name__)
    if auth_guard:
        bp.before_request(auth_guard())
    registrar(bp)
    app.register_blueprint(bp)
    return bp


app.register_blueprint(admin_plugins_bp)
app.register_blueprint(dynamic_plugins_bp)
app.register_blueprint(admin_agents_bp)
app.register_blueprint(bp_agent_templates)
app.register_blueprint(plugin_validation_bp)
app.register_blueprint(plugin_validation_admin_bp)
app.register_blueprint(bp_migration)
app.register_blueprint(plugin_logging_bp)

# Register OpenAPI routes
register_route_blueprint('openapi', register_openapi_routes, user_required_blueprint)

# Register Enhanced Citations routes
register_route_blueprint('enhanced_citations', register_enhanced_citations_routes, user_required_blueprint)

# Register Speech routes
register_route_blueprint('backend_speech', register_route_backend_speech, user_required_blueprint)

# Register TTS routes
register_route_blueprint('backend_tts', register_route_backend_tts, user_required_blueprint)

# Register Swagger documentation routes
from swagger_wrapper import register_swagger_routes
register_swagger_routes(app)

from flask_session import Session
from redis import Redis
from functions_settings import get_settings
from functions_authentication import get_current_user_id
from functions_global_agents import ensure_default_global_agent_exists
from background_tasks import start_background_task_threads

from route_external_health import *

_app_init_lock = threading.Lock()
_app_initialized = False
_background_tasks_lock = threading.Lock()
_background_tasks_started = False


def is_running_under_gunicorn():
    """Return True when the current process is a Gunicorn worker."""
    server_software = os.environ.get('SERVER_SOFTWARE', '')
    return 'gunicorn' in server_software.lower() or bool(os.environ.get('GUNICORN_CMD_ARGS'))


def should_start_background_tasks():
    """Enable background loops unless the runtime explicitly disables them."""
    env_value = os.environ.get('SIMPLECHAT_RUN_BACKGROUND_TASKS')
    if env_value is not None:
        return env_value.strip().lower() not in ('0', 'false', 'no', 'off')

    return True

# =================== Session Configuration ===================
def configure_sessions(settings):
    """Configure session backend (Redis or filesystem) once.

    Falls back to filesystem if Redis settings are incomplete. Supports managed identity
    or key auth for Azure Redis. Uses SESSION_FILE_DIR already prepared in config/app init.
    """
    try:
        if settings.get('enable_redis_cache'):
            redis_url = settings.get('redis_url', '').strip()
            redis_auth_type = settings.get('redis_auth_type', 'key').strip().lower()

            if redis_url:
                redis_client = None
                try:
                    if redis_auth_type == 'managed_identity':
                        log_event("Redis enabled using Managed Identity", level=logging.INFO)
                        redis_client = app_settings_cache.create_redis_managed_identity_client(
                            redis_url,
                            settings=settings,
                            socket_connect_timeout=5,
                            socket_timeout=5
                        )
                    elif redis_auth_type == 'key_vault':
                        log_event("Redis enabled using Key Vault Secret", level=logging.INFO)
                        from functions_keyvault import retrieve_secret_direct
                        redis_key_secret_name = settings.get('redis_key', '').strip()
                        redis_password = retrieve_secret_direct(redis_key_secret_name)
                        if redis_password:
                            redis_password = redis_password.strip()
                        redis_client = Redis(
                            host=redis_url,
                            port=6380,
                            db=0,
                            password=redis_password,
                            ssl=True,
                            socket_connect_timeout=5,
                            socket_timeout=5
                        )
                    else:
                        redis_key = settings.get('redis_key', '').strip()
                        log_event("Redis enabled using Access Key", level=logging.INFO)
                        redis_client = Redis(
                            host=redis_url,
                            port=6380,
                            db=0,
                            password=redis_key,
                            ssl=True,
                            socket_connect_timeout=5,
                            socket_timeout=5
                        )
                    
                    # Test the connection
                    redis_client.ping()
                    log_event("✅ Redis connection successful", level=logging.INFO)
                    app.config['SESSION_TYPE'] = 'redis'
                    app.config['SESSION_REDIS'] = redis_client
                    
                except Exception as redis_error:
                    print(f"⚠️  WARNING: Redis connection failed: {redis_error}")
                    print("Falling back to filesystem sessions for reliability")
                    app.config['SESSION_TYPE'] = 'filesystem'
            else:
                print("Redis enabled but URL missing; falling back to filesystem.")
                app.config['SESSION_TYPE'] = 'filesystem'
        else:
            app.config['SESSION_TYPE'] = 'filesystem'
    except Exception as e:
        print(f"⚠️  WARNING: Session configuration error; falling back to filesystem: {e}")
        log_event(f"Session configuration error; falling back to filesystem: {e}", level=logging.ERROR)
        app.config['SESSION_TYPE'] = 'filesystem'

    # Initialize session interface
    Session(app)

# =================== Helper Functions ===================
def start_background_tasks():
    """Start background loops once per process when enabled for the current runtime."""
    global _background_tasks_started

    with _background_tasks_lock:
        if _background_tasks_started:
            return

        if not should_start_background_tasks():
            print("Background tasks disabled for this web process.")
            _background_tasks_started = True
            return
        start_background_task_threads(app=app)
        _background_tasks_started = True


def initialize_application(force=False):
    """Initialize caches, clients, sessions, and optional background services once per process."""
    global _app_initialized

    with _app_init_lock:
        if _app_initialized and not force:
            return

        print("Initializing application...")
        settings = get_settings(use_cosmos=True)
        redis_hostname = settings.get('redis_url', '').strip().split('.')[0]
        app_settings_cache.configure_app_cache(
            settings,
            get_redis_cache_infrastructure_endpoint(redis_hostname)
        )
        app_settings_cache.update_settings_cache(settings)
        sanitized_settings = sanitize_settings_for_logging(settings)
        debug_print(f"DEBUG:Application settings: {sanitized_settings}")
        sanitized_settings_cache = sanitize_settings_for_logging(app_settings_cache.get_settings_cache())
        debug_print(f"DEBUG:App settings cache initialized: {'Using Redis cache:' + str(app_settings_cache.app_cache_is_using_redis)} {sanitized_settings_cache}")

        initialize_clients(settings)
        ensure_custom_logo_file_exists(app, settings)
        print("Setting up Application Insights logging...")
        setup_appinsights_logging(settings)
        logging.basicConfig(level=logging.DEBUG)
        # basicConfig above is a no-op once Azure Monitor owns the root logger,
        # and that same root handler stops Flask attaching its stderr handler,
        # so unhandled tracebacks would otherwise never reach the container log.
        ensure_console_error_logging(app.logger)
        ensure_default_global_agent_exists()

        start_background_tasks()

        enable_semantic_kernel = settings.get('enable_semantic_kernel', False)
        per_user_semantic_kernel = settings.get('per_user_semantic_kernel', False)
        if enable_semantic_kernel and not per_user_semantic_kernel:
            print("Semantic Kernel is enabled. Initializing...")
            initialize_semantic_kernel()

        configure_sessions(settings)
        _app_initialized = True
        print("Application initialized.")


@app.before_request
def ensure_application_initialized():
    initialize_application()


def get_idle_timeout_settings(settings=None):
    """
    Resolve and normalize idle timeout settings used for warning and logout enforcement.

    Args:
        settings (dict, optional): Settings dictionary to use. If None, uses request-scoped settings.

    Returns:
        tuple[int, int]: A tuple of (idle_timeout_minutes, idle_warning_minutes)
                         after parsing, fallback handling, and boundary normalization.

    Raises:
        None: Invalid values are handled via fallback defaults and warning logs.
    """
    if settings is None:
        settings = get_request_settings()

    timeout_raw = settings.get('idle_timeout_minutes', 30)
    warning_raw = settings.get('idle_warning_minutes', 28)

    try:
        timeout_minutes = int(timeout_raw)
    except (TypeError, ValueError):
        timeout_minutes = 30
        log_event(
            "Invalid idle timeout value detected; using default.",
            extra={
                "setting": "idle_timeout_minutes",
                "raw_value": str(timeout_raw),
                "fallback_value": 30
            },
            level=logging.WARNING
        )

    try:
        warning_minutes = int(warning_raw)
    except (TypeError, ValueError):
        warning_minutes = 28
        log_event(
            "Invalid idle warning value detected; using default.",
            extra={
                "setting": "idle_warning_minutes",
                "raw_value": str(warning_raw),
                "fallback_value": 28
            },
            level=logging.WARNING
        )

    normalized_timeout = max(10, timeout_minutes)
    if normalized_timeout != timeout_minutes:
        log_event(
            "Idle timeout value normalized to minimum allowed value.",
            extra={
                "setting": "idle_timeout_minutes",
                "original_value": timeout_minutes,
                "normalized_value": normalized_timeout
            },
            level=logging.WARNING
        )
    timeout_minutes = normalized_timeout

    normalized_warning = max(0, warning_minutes)
    if normalized_warning != warning_minutes:
        log_event(
            "Idle warning value normalized to minimum allowed value.",
            extra={
                "setting": "idle_warning_minutes",
                "original_value": warning_minutes,
                "normalized_value": normalized_warning
            },
            level=logging.WARNING
        )
    warning_minutes = normalized_warning

    if warning_minutes > timeout_minutes:
        previous_warning_minutes = warning_minutes
        warning_minutes = timeout_minutes
        log_event(
            "Idle warning value adjusted to not exceed idle timeout.",
            extra={
                "idle_timeout_minutes": timeout_minutes,
                "original_idle_warning_minutes": previous_warning_minutes,
                "adjusted_idle_warning_minutes": warning_minutes
            },
            level=logging.WARNING
        )

    return timeout_minutes, warning_minutes


def is_idle_timeout_enabled(settings=None):
    """
    Determine whether idle-timeout enforcement is enabled.

    Args:
        settings (dict, optional): Settings dictionary to use. If None, uses request-scoped settings.

    Returns:
        bool: True when idle-timeout enforcement should run; otherwise False.

    Raises:
        None: Unexpected values are coerced to boolean-compatible behavior.
    """
    if settings is None:
        settings = get_request_settings()

    enabled_raw = settings.get('enable_idle_timeout', False)

    if isinstance(enabled_raw, str):
        return enabled_raw.strip().lower() in ('1', 'true', 'yes', 'on')

    return bool(enabled_raw)


settings_source_counters = {}
settings_source_counters_lock = threading.Lock()
settings_source_last_observed = None
settings_source_last_non_cache_log_epoch = 0
settings_source_non_cache_log_interval_seconds = 60


def record_request_settings_source(source):
    """
    Record and log the source used to resolve request settings.

    Args:
        source (str): Settings source label (for example: cache, cosmos_fallback, cosmos_forced).

    Returns:
        None: Updates in-memory counters and request context diagnostics.

    Raises:
        None: Counter updates and diagnostics are handled internally.
    """
    normalized_source = source or 'unknown'
    now_epoch = int(time.time())

    global settings_source_last_observed
    global settings_source_last_non_cache_log_epoch

    with settings_source_counters_lock:
        settings_source_counters[normalized_source] = settings_source_counters.get(normalized_source, 0) + 1
        cache_hits = settings_source_counters.get('cache', 0)
        cosmos_fallback_hits = settings_source_counters.get('cosmos_fallback', 0)
        cosmos_forced_hits = settings_source_counters.get('cosmos_forced', 0)
        unknown_hits = settings_source_counters.get('unknown', 0)

        previous_source = settings_source_last_observed
        source_changed = normalized_source != previous_source
        settings_source_last_observed = normalized_source

        non_cache_log_window_elapsed = (
            now_epoch - settings_source_last_non_cache_log_epoch
        ) >= settings_source_non_cache_log_interval_seconds

        should_log_non_cache_info = (
            normalized_source != 'cache'
            and (source_changed or non_cache_log_window_elapsed)
        )

        if should_log_non_cache_info:
            settings_source_last_non_cache_log_epoch = now_epoch

    g.request_settings_source = normalized_source
    # debug_print(
    #     f"[SETTINGS SOURCE] path={request.path} source={normalized_source}",
    #     category="SETTINGS",
    #     cache_hits=cache_hits,
    #     cosmos_fallback_hits=cosmos_fallback_hits,
    #     cosmos_forced_hits=cosmos_forced_hits,
    #     unknown_hits=unknown_hits
    # )

    if should_log_non_cache_info:
        log_event(
            "Request settings source is non-cache.",
            extra={
                "path": request.path,
                "settings_source": normalized_source,
                "source_changed": source_changed,
                "non_cache_log_window_elapsed": non_cache_log_window_elapsed,
                "cache_hits": cache_hits,
                "cosmos_fallback_hits": cosmos_fallback_hits,
                "cosmos_forced_hits": cosmos_forced_hits,
                "unknown_hits": unknown_hits
            },
            level=logging.INFO
        )


def get_request_settings():
    """
    Get request-scoped settings, resolving and caching them when needed.

    Args:
        None

    Returns:
        dict: Request settings dictionary cached on Flask `g` for the current request.

    Raises:
        None: Unexpected resolver response shapes are logged and handled with safe fallbacks.
    """
    request_settings = getattr(g, 'request_settings', None)
    if request_settings is None:
        settings_result = get_settings(include_source=True)
        if isinstance(settings_result, tuple) and len(settings_result) == 2:
            request_settings, settings_source = settings_result
        else:
            request_settings = settings_result
            settings_source = 'unknown'
            log_event(
                "Unexpected settings response shape in get_request_settings.",
                extra={
                    "path": request.path,
                    "response_type": type(settings_result).__name__
                },
                level=logging.WARNING
            )

        request_settings = request_settings or {}
        g.request_settings = request_settings
        record_request_settings_source(settings_source)
    return request_settings

@app.context_processor
def inject_settings():
    settings = get_request_settings()
    public_settings = sanitize_settings_for_user(settings)
    idle_timeout_enabled = is_idle_timeout_enabled(settings)
    idle_timeout_minutes, idle_warning_minutes = get_idle_timeout_settings(settings)
    custom_pages_nav = []
    try:
        custom_pages_nav = get_custom_pages_nav(settings)
    except Exception as e:
        log_event(f"[CUSTOM_PAGES] Error injecting custom page navigation: {e}", level=logging.ERROR, exceptionTraceback=True)
    # Inject per-user settings if logged in
    user_settings = {}
    latest_features_nav_hidden = IS_DEVELOPMENT
    try:
        user_id = get_current_user_id()
        if user_id:
            from functions_settings import get_user_ui_settings
            user_settings = get_user_ui_settings(user_id) or {}
            latest_features_nav_hidden = should_hide_latest_features_nav(
                user_settings,
                VERSION,
                is_development=IS_DEVELOPMENT
            )
    except Exception as e:
        print(f"Error injecting user settings: {e}")
        log_event(f"Error injecting user settings: {e}", level=logging.ERROR)
        user_settings = {}
        latest_features_nav_hidden = IS_DEVELOPMENT
    return dict(
        app_settings=public_settings,
        user_settings=user_settings,
        custom_pages_nav=custom_pages_nav,
        admin_nav=ADMIN_NAV,
        admin_landing_tab=get_landing_tab_id(),
        latest_features_current_version=VERSION,
        latest_features_nav_hidden=latest_features_nav_hidden,
        latest_features_nav_hidden_by_development=IS_DEVELOPMENT,
        idle_timeout_enabled=idle_timeout_enabled,
        idle_timeout_minutes=idle_timeout_minutes,
        idle_warning_minutes=idle_warning_minutes,
        mcp_ui_enabled=is_mcp_ui_enabled()
    )

@app.template_filter('to_datetime')
def to_datetime_filter(value):
    return datetime.fromisoformat(value)

@app.template_filter('format_datetime')
def format_datetime_filter(value):
    return value.strftime('%Y-%m-%d %H:%M')

# =================== SK Hot Reload Handler ===================
@app.before_request
def reload_kernel_if_needed():
    if getattr(builtins, "kernel_reload_needed", False):
        debug_print(f"[SK_LOADER] Hot reload: re-initializing Semantic Kernel and agents due to settings change.")
        """Commneted out because hot reload is not fully supported yet.
        log_event(
            "[SK_LOADER] Hot reload: re-initializing Semantic Kernel and agents due to settings change.",
            level=logging.INFO
        )
        initialize_semantic_kernel()
        """
        setattr(builtins, "kernel_reload_needed", False)


UNSAFE_STATE_CHANGING_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}
GET_STATE_CHANGING_PATH_PREFIXES = (
    '/api/chat/stream/reattach/',
)
SAME_ORIGIN_FETCH_SITE_VALUES = {'same-origin', 'same-site', 'none'}


def _normalize_origin_from_url(raw_url):
    """Return the scheme/host/port origin for a URL-like value."""
    if not raw_url:
        return ''

    try:
        parsed_url = urlparse(str(raw_url).strip())
    except ValueError:
        return ''

    if not parsed_url.scheme or not parsed_url.hostname:
        return ''

    scheme = parsed_url.scheme.lower()
    hostname = parsed_url.hostname.lower()
    display_host = f'[{hostname}]' if ':' in hostname and not hostname.startswith('[') else hostname
    try:
        port = parsed_url.port
    except ValueError:
        return ''
    if port and not ((scheme == 'http' and port == 80) or (scheme == 'https' and port == 443)):
        display_host = f'{display_host}:{port}'

    return f'{scheme}://{display_host}'


def _first_forwarded_header_value(header_name):
    header_value = request.headers.get(header_name, '')
    if not header_value:
        return ''
    return header_value.split(',', 1)[0].strip()


def _add_allowed_origin(allowed_origins, raw_origin):
    normalized_origin = _normalize_origin_from_url(raw_origin)
    if normalized_origin:
        allowed_origins.add(normalized_origin)


def _origin_matches_allowed_origin(request_origin, allowed_origin):
    """Return True when an origin matches an exact or wildcard allowed origin."""
    if not request_origin or not allowed_origin:
        return False
    if request_origin == allowed_origin:
        return True

    try:
        request_parsed = urlparse(request_origin)
        allowed_parsed = urlparse(allowed_origin)
    except ValueError:
        return False

    if request_parsed.scheme != allowed_parsed.scheme:
        return False
    if request_parsed.port != allowed_parsed.port:
        return False

    allowed_host = (allowed_parsed.hostname or '').lower()
    request_host = (request_parsed.hostname or '').lower()
    if not allowed_host.startswith('*.'):
        return False

    allowed_suffix = allowed_host[1:]
    return request_host.endswith(allowed_suffix) and request_host != allowed_host[2:]


def _origin_matches_any_allowed_origin(request_origin, allowed_origins):
    return any(
        _origin_matches_allowed_origin(request_origin, allowed_origin)
        for allowed_origin in allowed_origins
    )


def _build_allowed_request_origins():
    allowed_origins = set()
    _add_allowed_origin(allowed_origins, request.host_url)
    _add_allowed_origin(allowed_origins, f'{request.scheme}://{request.host}')

    forwarded_host = (
        _first_forwarded_header_value('X-Forwarded-Host')
        or _first_forwarded_header_value('X-Original-Host')
    )
    forwarded_proto = _first_forwarded_header_value('X-Forwarded-Proto') or request.scheme
    if forwarded_host:
        _add_allowed_origin(allowed_origins, f'{forwarded_proto}://{forwarded_host}')

    _add_allowed_origin(allowed_origins, HOME_REDIRECT_URL)
    _add_allowed_origin(allowed_origins, LOGIN_REDIRECT_URL)

    for trusted_origin in CSRF_TRUSTED_ORIGINS:
        _add_allowed_origin(allowed_origins, trusted_origin)

    try:
        request_settings = get_request_settings()
        if request_settings.get('enable_front_door'):
            _add_allowed_origin(allowed_origins, request_settings.get('front_door_url'))
    except Exception as e:
        log_event(
            f"[CSRF] Failed to load Front Door trusted origin from settings: {e}",
            level=logging.WARNING,
            debug_only=True,
        )

    return allowed_origins


def _state_changing_request_has_same_origin_boundary():
    fetch_site = request.headers.get('Sec-Fetch-Site', '').strip().lower()
    origin_header = request.headers.get('Origin', '').strip()
    referer_header = request.headers.get('Referer', '').strip()

    if fetch_site == 'cross-site':
        # A genuinely cross-site request is rejected unless its Origin is explicitly
        # trusted. This is what allows a deliberately separate front-end origin (the
        # standalone V2 UI app service, declared via V2_UI_ALLOWED_ORIGIN) to mutate
        # state, while an arbitrary attacker origin still cannot: the browser sets
        # Origin itself and it must match the configured allowlist exactly.
        if origin_header:
            request_origin = _normalize_origin_from_url(origin_header)
            if request_origin and _origin_matches_any_allowed_origin(
                request_origin, _build_allowed_request_origins()
            ):
                return True, 'cross-site origin explicitly trusted'
        return False, 'cross-site fetch metadata'
    if fetch_site == 'same-origin':
        return True, 'same-origin fetch metadata'
    if fetch_site == 'same-site' and not origin_header and not referer_header:
        return False, 'same-site fetch metadata without origin headers'
    if fetch_site and fetch_site not in SAME_ORIGIN_FETCH_SITE_VALUES:
        return False, f'unexpected fetch metadata: {fetch_site}'

    allowed_origins = _build_allowed_request_origins()
    if origin_header:
        request_origin = _normalize_origin_from_url(origin_header)
        if request_origin and _origin_matches_any_allowed_origin(request_origin, allowed_origins):
            return True, 'origin matched'
        return False, 'origin mismatch'

    if referer_header:
        request_origin = _normalize_origin_from_url(referer_header)
        if request_origin and _origin_matches_any_allowed_origin(request_origin, allowed_origins):
            return True, 'referer matched'
        return False, 'referer mismatch'

    return True, 'no browser origin headers present'


def _requires_same_origin_state_change_boundary():
    if request.method in UNSAFE_STATE_CHANGING_METHODS:
        return True
    if request.method == 'GET':
        return any(request.path.startswith(prefix) for prefix in GET_STATE_CHANGING_PATH_PREFIXES)
    return False


@app.before_request
def answer_cors_preflight_for_allowed_origins():
    """Answer CORS preflight requests before the authentication guards run.

    A cross-origin JSON request triggers an OPTIONS preflight, and preflights deliberately
    carry no cookies. Blueprint auth guards run after app-level before_request handlers, so
    without this a preflight would be rejected with 401 and every state-changing call from
    a separately hosted V2 UI would fail before it was ever sent.

    This is inert unless V2_UI_ALLOWED_ORIGIN is configured, and it only ever answers for an
    Origin that exactly matches the allowlist.
    """
    if not V2_UI_ALLOWED_ORIGINS or request.method != 'OPTIONS':
        return None

    # Access-Control-Request-Method is only present on a real preflight, which keeps this
    # from intercepting an ordinary OPTIONS request.
    if not request.headers.get('Access-Control-Request-Method'):
        return None

    request_origin = request.headers.get('Origin', '').strip()
    if not request_origin or request_origin not in V2_UI_ALLOWED_ORIGINS:
        return None

    response = make_response('', 204)
    response.headers['Access-Control-Allow-Origin'] = request_origin
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Accept'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
    response.headers['Access-Control-Max-Age'] = '600'
    response.headers['Vary'] = 'Origin'
    return response


@app.before_request
def enforce_same_origin_for_state_changing_requests():
    """Reject authenticated browser mutations that originate off-site."""
    if not CSRF_ENFORCE_ORIGIN_FOR_UNSAFE_METHODS:
        return None
    if not _requires_same_origin_state_change_boundary():
        return None
    is_teams_token_exchange = request.path == '/auth/teams/token-exchange' and ENABLE_TEAMS_SSO
    if 'user' not in session and not is_teams_token_exchange:
        return None

    has_boundary, reason = _state_changing_request_has_same_origin_boundary()
    if has_boundary:
        return None

    log_event(
        "[CSRF] Blocked state-changing request with invalid same-origin boundary.",
        extra={
            'path': request.path,
            'method': request.method,
            'reason': reason,
            'origin_present': bool(request.headers.get('Origin')),
            'referer_present': bool(request.headers.get('Referer')),
            'sec_fetch_site': request.headers.get('Sec-Fetch-Site', ''),
        },
        level=logging.WARNING,
    )
    return jsonify({
        'error': 'Forbidden',
        'message': 'State-changing requests must originate from SimpleChat.',
    }), 403


def _is_idle_timeout_exempt(path):
    """
    Check whether a request path is exempt from idle-timeout processing.

    Args:
        path (str): Request path to evaluate.

    Returns:
        bool: True if the path is exempt from idle-timeout checks; otherwise False.

    Raises:
        None
    """
    if path in IDLE_TIMEOUT_EXEMPT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in IDLE_TIMEOUT_EXEMPT_PREFIXES)


TERMS_OF_USE_EXEMPT_PATHS = {
    '/login',
    '/logout',
    '/logout/local',
    '/getAToken',
    '/getATokenApi',
    '/ci-auth/session',
    '/auth/teams/token-exchange',
    '/terms-of-use',
    '/terms-of-use/accept',
    '/terms-of-use/decline',
    '/robots933456.txt',
    '/favicon.ico',
    '/acceptable_use_policy.html',
    '/external/healthcheck',
    '/external/healthcheckz',
}

TERMS_OF_USE_EXEMPT_PREFIXES = (
    '/static/',
    '/health',
    '/api/health',
)


def _is_terms_of_use_exempt(path):
    if path in TERMS_OF_USE_EXEMPT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in TERMS_OF_USE_EXEMPT_PREFIXES)


@app.before_request
def enforce_terms_of_use():
    """Block authenticated app usage until the current terms of use is accepted."""
    if 'user' not in session:
        return None
    if request.method == 'OPTIONS' or _is_terms_of_use_exempt(request.path):
        return None

    request_settings = get_request_settings()
    user_id = session.get('user', {}).get('oid') or session.get('user', {}).get('sub')
    if has_terms_of_use_acceptance(request_settings, user_id=user_id):
        return None

    terms_url = url_for(
        'frontend_terms_of_use.terms_of_use',
        next=normalize_path_with_query(request.path, request.query_string),
    )
    is_api_request = (
        request.accept_mimetypes.accept_json
        and not request.accept_mimetypes.accept_html
    ) or request.path.startswith('/api/')
    if is_api_request:
        return jsonify({
            'error': 'terms_of_use_required',
            'message': 'Terms of Use acceptance is required before using SimpleChat.',
            'terms_url': terms_url,
        }), 403
    return redirect(terms_url)


def normalize_path_with_query(path, query_string):
    query_text = query_string.decode('utf-8', errors='ignore') if isinstance(query_string, bytes) else str(query_string or '')
    if not query_text:
        return path
    return f"{path}?{query_text}"


def maybe_log_authenticated_browser_request():
    """Record throttled login activity for authenticated browser page requests."""
    if request.method != 'GET' or request.path.startswith('/api/'):
        return

    user_id = session.get('user', {}).get('oid') or session.get('user', {}).get('sub')
    if not user_id:
        return

    maybe_log_authenticated_request_login(
        user_id=user_id,
        session_state=session,
        request_path=request.path,
        request_method=request.method
    )

@app.before_request
def enforce_idle_session_timeout():
    """
    Enforce server-side idle session timeout for authenticated requests.

    Args:
        None

    Returns:
        Response | None: A redirect/401 response when timeout is exceeded; otherwise None.

    Raises:
        None: Runtime issues in timeout evaluation are logged and request processing continues safely.
    """
    if 'user' not in session:
        return None

    if request.method == 'OPTIONS' or _is_idle_timeout_exempt(request.path):
        return None

    now_epoch = int(time.time())
    request_settings = get_request_settings()
    if not is_idle_timeout_enabled(request_settings):
        disabled_refresh_interval_seconds = 60
        last_activity_epoch = session.get('last_activity_epoch')
        should_refresh_last_activity = False

        if last_activity_epoch is None:
            should_refresh_last_activity = True
        else:
            try:
                parsed_last_activity_epoch = int(float(last_activity_epoch))
                if (
                    parsed_last_activity_epoch > now_epoch
                    or (now_epoch - parsed_last_activity_epoch) >= disabled_refresh_interval_seconds
                ):
                    should_refresh_last_activity = True
            except (TypeError, ValueError):
                should_refresh_last_activity = True

        if should_refresh_last_activity:
            session['last_activity_epoch'] = now_epoch
            session.modified = True
        maybe_log_authenticated_browser_request()
        return None

    idle_timeout_minutes, _ = get_idle_timeout_settings(request_settings)
    last_activity_epoch = session.get('last_activity_epoch')
    has_valid_last_activity_epoch = False
    max_allowed_future_skew_seconds = 60

    if last_activity_epoch is not None:
        try:
            parsed_last_activity_epoch = int(float(last_activity_epoch))
            if parsed_last_activity_epoch <= (now_epoch + max_allowed_future_skew_seconds):
                has_valid_last_activity_epoch = True
            else:
                log_event(
                    "Idle timeout last_activity_epoch is in the future; resetting timestamp.",
                    extra={
                        "path": request.path,
                        "parsed_last_activity_epoch": parsed_last_activity_epoch,
                        "now_epoch": now_epoch,
                        "max_allowed_future_skew_seconds": max_allowed_future_skew_seconds
                    },
                    level=logging.WARNING
                )
            idle_seconds = now_epoch - parsed_last_activity_epoch
            if idle_seconds >= (idle_timeout_minutes * 60):
                user_id = session.get('user', {}).get('oid') or session.get('user', {}).get('sub')
                session.clear()

                log_event(
                    f"Session expired due to {idle_timeout_minutes} minute inactivity timeout for user {user_id or 'unknown'}.",
                    level=logging.INFO
                )

                if request.path.startswith('/api/'):
                    return jsonify({
                        'error': 'Session expired',
                        'message': 'Your session expired due to inactivity. Please sign in again.',
                        'requires_reauth': True
                    }), 401

                return redirect(url_for('frontend_authentication.local_logout'))
        except Exception as e:
            log_event(f"Idle timeout evaluation failed: {e}", level=logging.WARNING)

    if request.path.startswith('/api/'):
        if not has_valid_last_activity_epoch:
            session['last_activity_epoch'] = now_epoch
            session.modified = True
        return None

    session['last_activity_epoch'] = now_epoch
    session.modified = True
    maybe_log_authenticated_browser_request()
    return None

@app.after_request
def add_security_headers(response):
    """
    Add comprehensive security headers to all responses to protect against
    various web vulnerabilities including MIME sniffing attacks.
    """
    from config import SECURITY_HEADERS, ENABLE_STRICT_TRANSPORT_SECURITY, HSTS_MAX_AGE, V2_UI_ALLOWED_ORIGINS
    
    # Apply all configured security headers
    for header_name, header_value in SECURITY_HEADERS.items():
        response.headers[header_name] = header_value
    
    # Add HSTS header only if HTTPS is enabled and configured
    if ENABLE_STRICT_TRANSPORT_SECURITY and request.is_secure:
        response.headers['Strict-Transport-Security'] = f'max-age={HSTS_MAX_AGE}; includeSubDomains; preload'
    
    # Ensure X-Content-Type-Options is always present for specific content types
    # This provides extra protection against MIME sniffing attacks
    if response.content_type and any(ct in response.content_type.lower() for ct in ['text/', 'application/json', 'application/javascript', 'application/octet-stream']):
        response.headers['X-Content-Type-Options'] = 'nosniff'

    # Cross-origin support for a separately hosted V2 UI.
    #
    # Only the exact configured origin is ever echoed back, never a wildcard, because
    # Allow-Credentials is required to carry the session cookie and the two are mutually
    # exclusive with '*'. This block does nothing unless V2_UI_ALLOWED_ORIGIN is set, so
    # the default same-origin deployment emits no CORS headers at all.
    if V2_UI_ALLOWED_ORIGINS:
        request_origin = request.headers.get('Origin')
        if request_origin and request_origin in V2_UI_ALLOWED_ORIGINS:
            response.headers['Access-Control-Allow-Origin'] = request_origin
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Accept'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
            response.headers['Access-Control-Max-Age'] = '600'
            # Responses vary by Origin, so caches must not serve one origin's response
            # to another.
            existing_vary = response.headers.get('Vary')
            response.headers['Vary'] = f'{existing_vary}, Origin' if existing_vary else 'Origin'

    return response

# Register a custom Jinja filter for Markdown
def markdown_filter(text):
    if not text:
        text = ""

    # Convert Markdown to HTML
    html = markdown2.markdown(text)

    # Add target="_blank" to all <a> links
    html = re.sub(r'(<a\s+href=["\'](https?://.*?)["\'])', r'\1 target="_blank" rel="noopener noreferrer"', html)
    allowed_tags = set(bleach.sanitizer.ALLOWED_TAGS).union({
        'p',
        'pre',
        'span',
        'h1',
        'h2',
        'h3',
        'h4',
        'h5',
        'h6',
        'br',
        'table',
        'thead',
        'tbody',
        'tr',
        'th',
        'td',
    })
    allowed_attributes = dict(bleach.sanitizer.ALLOWED_ATTRIBUTES)
    allowed_attributes['a'] = ['href', 'title', 'target', 'rel']
    allowed_attributes['*'] = ['class']
    html = bleach.clean(
        html,
        tags=allowed_tags,
        attributes=allowed_attributes,
        protocols={'http', 'https', 'mailto'},
        strip=True,
    )

    return Markup(html)  # xss-check: ignore - sanitized with bleach.clean before Markup.

# Add the filter to the Jinja environment
app.jinja_env.filters['markdown'] = markdown_filter

# Register a custom Jinja filter for nl2br (newline to <br>)
def nl2br_filter(value):
    """Escape HTML then convert newline characters to <br> tags."""
    from markupsafe import escape, Markup
    if not value:
        return Markup('')  # xss-check: ignore - static empty safe markup.
    return Markup(str(escape(value)).replace('\n', '<br>\n'))  # xss-check: ignore - value is escaped before adding static br tags.

app.jinja_env.filters['nl2br'] = nl2br_filter


# =================== Rate Limiting (429) Responses =====================
def rate_limited_caller_wants_json():
    """Return True when a rate limited caller expects JSON over a rendered page."""
    path = request.path or ''
    if path.startswith('/api/') or path.startswith('/external/'):
        return True

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True

    accept = request.accept_mimetypes
    return accept.accept_json and not accept.accept_html


@app.errorhandler(429)
def handle_rate_limited_request(error):
    """Return the admin-configured message whenever a request is rate limited.

    Views that build their own 429 body resolve the message themselves, so this
    handler covers ``abort(429)`` and any 429 raised from within the stack.
    """
    settings = get_settings()
    retry_after = getattr(error, 'retry_after', None)

    if rate_limited_caller_wants_json():
        response = jsonify(build_rate_limit_error_payload(settings, retry_after=retry_after))
    else:
        message = get_rate_limit_message(settings)
        try:
            response = make_response(render_template(
                'errors/429.html',
                rate_limit_message_html=markdown_filter(message),
            ))
        except Exception as render_error:
            # The message still has to reach the user even if the shell fails
            # to render, so fall back to the raw Markdown as plain text.
            log_event(
                f"[RATE_LIMIT] Failed to render the 429 page: {render_error}",
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            response = make_response(message)
            response.mimetype = 'text/plain'

    response.status_code = 429
    if retry_after:
        response.headers['Retry-After'] = str(retry_after)

    return response


public_app_bp = Blueprint('public_app', __name__)


# =================== Default Routes =====================
@public_app_bp.route('/')
@swagger_route(security=get_auth_security())
def index():
    if ENABLE_AUTO_LOGIN_ON_INDEX and "user" not in session:
        return redirect(url_for('frontend_authentication.login'))

    settings = get_settings()
    public_settings = sanitize_settings_for_user(settings)

    # Ensure landing_page_text is always a valid string
    landing_text = settings.get("landing_page_text", "Click the button below to start chatting with the AI assistant. You agree to our [acceptable user policy by using this service](acceptable_use_policy.html).")

    # Convert Markdown to HTML safely
    landing_html = markdown_filter(landing_text)

    return render_template('index.html', app_settings=public_settings, landing_html=landing_html)

@public_app_bp.route('/robots933456.txt')
@swagger_route(security=get_auth_security())
def robots():
    return send_from_directory('static', 'robots.txt')

@public_app_bp.route('/favicon.ico')
@swagger_route(security=get_auth_security())
def favicon():
    return send_from_directory('static', 'favicon.ico')

@public_app_bp.route('/static/js/<path:filename>')
@swagger_route(security=get_auth_security())
def serve_js_modules(filename):
    """Serve JavaScript modules with correct MIME type."""
    from flask import send_from_directory, Response
    if filename.endswith('.mjs'):
        # Serve .mjs files with correct MIME type for ES modules
        response = send_from_directory('static/js', filename)
        response.headers['Content-Type'] = 'application/javascript'
        return response
    else:
        return send_from_directory('static/js', filename)

@public_app_bp.route('/acceptable_use_policy.html')
@swagger_route(security=get_auth_security())
def acceptable_use_policy():
    return render_template('acceptable_use_policy.html')

session_api_bp = Blueprint('session_api', __name__)
session_api_bp.before_request(login_required_blueprint())


@session_api_bp.route('/api/session/heartbeat', methods=['POST'])
@swagger_route(security=get_auth_security())
@login_required
def session_heartbeat():
    """
    Refresh the authenticated session activity timestamp used by idle-timeout enforcement.

    Args:
        None

    Returns:
        tuple[Response, int]: JSON response containing refresh confirmation and timeout metadata.

    Raises:
        None
    """
    session['last_activity_epoch'] = int(time.time())
    session.modified = True
    idle_timeout_minutes, _ = get_idle_timeout_settings(get_request_settings())
    return jsonify({
        'message': 'Session refreshed',
        'idle_timeout_minutes': idle_timeout_minutes
    }), 200

debug_admin_bp = Blueprint('debug_admin', __name__)
debug_admin_bp.before_request(admin_required_blueprint())


@debug_admin_bp.route('/api/semantic-kernel/plugins')
@swagger_route(security=get_auth_security())
@login_required
@admin_required
def list_semantic_kernel_plugins():
    """Test endpoint: List loaded Semantic Kernel plugins and their functions."""
    global kernel
    if not kernel:
        return {"error": "Kernel not initialized"}, 500
    plugins = {}
    for plugin_name, plugin in kernel.plugins.items():
        plugins[plugin_name] = [func.name for func in plugin.functions.values()]
    return {"plugins": plugins}


app.register_blueprint(public_app_bp)
app.register_blueprint(session_api_bp)
app.register_blueprint(debug_admin_bp)


# =================== Front End Routes ===================
# ------------------- User Authentication Routes ---------
register_route_blueprint('frontend_authentication', register_route_frontend_authentication)

# ------------------- Terms of Use Routes --
register_route_blueprint('frontend_terms_of_use', register_route_frontend_terms_of_use)

# ------------------- User Profile Routes ----------------
register_route_blueprint('frontend_profile', register_route_frontend_profile, login_required_blueprint)

# ------------------- Admin Settings Routes --------------
register_route_blueprint('frontend_admin_settings', register_route_frontend_admin_settings, admin_required_blueprint)

# ------------------- Control Center Routes --------------
register_route_blueprint('frontend_control_center', register_route_frontend_control_center, login_required_blueprint)

# ------------------- Chats Routes -----------------------
register_route_blueprint('frontend_chats', register_route_frontend_chats, user_required_blueprint)

# ------------------- Agents Catalog Routes --------------
register_route_blueprint('frontend_agents', register_route_frontend_agents, user_required_blueprint)

# ------------------- Conversations Routes ---------------
register_route_blueprint('frontend_conversations', register_route_frontend_conversations, user_required_blueprint)

# ------------------- Documents Routes -------------------
register_route_blueprint('frontend_workspace', register_route_frontend_workspace, user_required_blueprint)

# ------------------- Groups Routes ----------------------
register_route_blueprint('frontend_groups', register_route_frontend_groups, user_required_blueprint)

# ------------------- Group Documents Routes -------------
register_route_blueprint('frontend_group_workspaces', register_route_frontend_group_workspaces, user_required_blueprint)
register_route_blueprint('frontend_public_workspaces', register_route_frontend_public_workspaces, user_required_blueprint)

# ------------------- Safety Routes ----------------------
register_route_blueprint('frontend_safety', register_route_frontend_safety, login_required_blueprint)

# ------------------- Feedback Routes -------------------
register_route_blueprint('frontend_feedback', register_route_frontend_feedback, login_required_blueprint)

# ------------------- Support Routes --------------------
register_route_blueprint('frontend_support', register_route_frontend_support, user_required_blueprint)

# ------------------- Notifications Routes --------------
register_route_blueprint('frontend_notifications', register_route_frontend_notifications, user_required_blueprint)

# ------------------- Custom Pages Routes ---------------
register_route_blueprint('custom_pages', register_route_custom_pages, login_required_blueprint)

# ------------------- V2 React UI Routes ----------------
register_route_blueprint('frontend_v2', register_route_frontend_v2, user_required_blueprint)

# ------------------- API Chat Routes --------------------
register_route_blueprint('backend_chats', register_route_backend_chats, user_required_blueprint)

# ------------------- API V2 UI Routes -------------------
register_route_blueprint('backend_v2', register_route_backend_v2, user_required_blueprint)
register_route_blueprint('backend_v2_admin', register_route_backend_v2_admin, admin_required_blueprint)

# ------------------- API Search Routes ------------------
register_route_blueprint('backend_search', register_route_backend_search, user_required_blueprint)

# ------------------- API Conversation Routes ------------
register_route_blueprint('backend_conversations', register_route_backend_conversations, user_required_blueprint)

# ------------------- API Collaboration Routes -----------
register_route_blueprint('backend_collaboration', register_route_backend_collaboration, user_required_blueprint)

# ------------------- API MS Graph Pending Action Routes -
register_route_blueprint('backend_msgraph_pending_actions', register_route_backend_msgraph_pending_actions, user_required_blueprint)

# ------------------- API Documents Routes ---------------
register_route_blueprint('backend_documents', register_route_backend_documents, user_required_blueprint)

# ------------------- API Groups Routes ------------------
register_route_blueprint('backend_groups', register_route_backend_groups, user_required_blueprint)

# ------------------- API User Routes --------------------
register_route_blueprint('backend_users', register_route_backend_users, user_required_blueprint)

# ------------------- API Group Documents Routes ---------
register_route_blueprint('backend_group_documents', register_route_backend_group_documents, user_required_blueprint)

# ------------------- API Model Routes -------------------
register_route_blueprint('backend_models', register_route_backend_models, user_required_blueprint)

# ------------------- API Workflow Routes ----------------
register_route_blueprint('backend_workflows', register_route_backend_workflows, user_required_blueprint)

# ------------------- API Safety Logs Routes -------------
register_route_blueprint('backend_safety', register_route_backend_safety, user_required_blueprint)

# ------------------- API Feedback Routes ---------------
register_route_blueprint('backend_feedback', register_route_backend_feedback, user_required_blueprint)

# ------------------- API Settings Routes ---------------
register_route_blueprint('backend_settings', register_route_backend_settings, login_required_blueprint)

# ------------------- API Data Management Routes ---------
register_route_blueprint('backend_data_management', register_route_backend_data_management, admin_required_blueprint)

# ------------------- API Prompts Routes ----------------
register_route_blueprint('backend_prompts', register_route_backend_prompts, user_required_blueprint)

# ------------------- API Group Prompts Routes ----------
register_route_blueprint('backend_group_prompts', register_route_backend_group_prompts, user_required_blueprint)

# ------------------- API Control Center Routes ---------
register_route_blueprint('backend_control_center', register_route_backend_control_center, login_required_blueprint)

# ------------------- API Notifications Routes ----------
register_route_blueprint('backend_notifications', register_route_backend_notifications, user_required_blueprint)

# ------------------- API Retention Policy Routes --------
register_route_blueprint('backend_retention_policy', register_route_backend_retention_policy, login_required_blueprint)

# ------------------- API Governance Routes --------------
register_route_blueprint('backend_governance', register_route_backend_governance, admin_required_blueprint)

# ------------------- API Public Workspaces Routes -------
register_route_blueprint('backend_public_workspaces', register_route_backend_public_workspaces, user_required_blueprint)

# ------------------- API Conversation Export Routes -----
register_route_blueprint('backend_conversation_export', register_route_backend_conversation_export, user_required_blueprint)

# ------------------- API Public Documents Routes --------
register_route_blueprint('backend_public_documents', register_route_backend_public_documents, user_required_blueprint)

# ------------------- API Public Prompts Routes ----------
register_route_blueprint('backend_public_prompts', register_route_backend_public_prompts, user_required_blueprint)

# ------------------- API File Sync Routes ---------------
register_route_blueprint('backend_file_sync', register_route_backend_file_sync, login_required_blueprint)

# ------------------- API Workspace Identity Routes ------
register_route_blueprint('backend_workspace_identities', register_route_backend_workspace_identities, login_required_blueprint)

# ------------------- API User Agreement Routes ----------
register_route_blueprint('backend_user_agreement', register_route_backend_user_agreement, user_required_blueprint)

# ------------------- API Thoughts Routes ----------------
register_route_blueprint('backend_thoughts', register_route_backend_thoughts, user_required_blueprint)

# ------------------- Inbound MCP Routes -----------------
register_route_blueprint('inbound_mcp', register_route_inbound_mcp, inbound_mcp_required_blueprint)

# ------------------- External Health Routes ----------
register_route_blueprint('external_health', register_route_external_health)
register_route_blueprint('external_no_auth_health', register_no_auth_health)

if __name__ == '__main__':
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    use_gunicorn = os.environ.get("SIMPLECHAT_USE_GUNICORN", "0").strip().lower() in ('1', 'true', 'yes', 'on')

    if use_gunicorn and not debug_mode:
        gunicorn_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gunicorn.conf.py')
        print(f"Starting Gunicorn using {gunicorn_config_path}")
        os.execvp(sys.executable, [sys.executable, '-m', 'gunicorn', '-c', gunicorn_config_path, 'app:app'])

    if use_gunicorn and debug_mode:
        print("⚠️  WARNING: Both Gunicorn and Flask debug mode are enabled, which is not supported. Please disable one of them, app will not run until resolved.")
        log_event("WARNING: Running with both Gunicorn and Flask debug mode is not supported. Please disable one of them, app will not run until resolved.", level=logging.WARNING)
        exit(1)

    initialize_application(force=True)

    if debug_mode:
        # Local development with HTTPS
        # use_reloader=False prevents too_many_retries errors with static files
        # Disable excessive logging for static file requests in development
        werkzeug_logger = logging.getLogger('werkzeug')
        werkzeug_logger.setLevel(logging.ERROR)
        app.run(host="0.0.0.0", port=5000, debug=True, ssl_context='adhoc', threaded=True, use_reloader=False)
    else:
        # Production
        port = int(os.environ.get("PORT", 5000))
        app.run(host="0.0.0.0", port=port, debug=False)
