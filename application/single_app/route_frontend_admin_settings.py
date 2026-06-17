# route_frontend_admin_settings.py

import re

from config import *
from functions_documents import *
from functions_authentication import *
from functions_keyvault import keyvault_model_endpoint_cleanup_helper, keyvault_model_endpoint_delete_helper, keyvault_model_endpoint_save_helper, redact_model_endpoint_secret_values
from functions_settings import *
from functions_file_sync import FILE_SYNC_DEFAULTS, get_file_sync_config
from functions_source_review import SOURCE_REVIEW_DEFAULTS, get_source_review_config, get_source_review_runtime_capabilities, normalize_source_review_js_rendering_enabled, parse_source_review_list
from functions_control_center import (
    calculate_next_control_center_auto_refresh_run,
    get_control_center_auto_refresh_schedule,
)
from functions_cosmos_throughput import (
    get_cached_cosmos_throughput_status,
    get_cosmos_resource_config,
    get_cosmos_throughput_setting_keys,
    normalize_cosmos_throughput_settings,
    validate_cosmos_throughput_policy_settings,
)
from functions_activity_logging import log_web_search_consent_acceptance, log_general_admin_action, log_governance_change
from functions_notifications import broadcast_system_notification
from functions_logging import *
from functions_document_actions import normalize_document_action_capabilities
from swagger_wrapper import swagger_route, get_auth_security
from datetime import datetime, timedelta, timezone
from admin_settings_int_utils import safe_int_with_source
from support_menu_config import (
    get_support_latest_feature_catalog,
    get_support_latest_feature_release_groups,
    get_support_latest_feature_release_groups_for_settings,
    has_visible_support_latest_features,
    normalize_support_latest_features_visibility,
)

ALLOWED_PIL_IMAGE_UPLOAD_FORMATS = ('PNG', 'JPEG')
MAX_CUSTOM_LOGO_STORAGE_HEIGHT = 500
AGENTS_PAGE_DEFAULTS = {
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
}
HEX_COLOR_PATTERN = re.compile(r'^#[0-9a-fA-F]{6}$')

def allowed_file(filename, allowed_extensions):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions

def open_allowed_uploaded_image(file_bytes, filename):
    img = Image.open(BytesIO(file_bytes), formats=list(ALLOWED_PIL_IMAGE_UPLOAD_FORMATS))
    img.load()

    detected_format = (img.format or '').upper()
    if detected_format not in ALLOWED_PIL_IMAGE_UPLOAD_FORMATS:
        raise ValueError(
            f"Unsupported image format for {filename}. Allowed formats: {', '.join(ALLOWED_PIL_IMAGE_UPLOAD_FORMATS)}"
        )

    return img, detected_format

def prepare_logo_image_for_storage(file_bytes, filename, max_height=MAX_CUSTOM_LOGO_STORAGE_HEIGHT):
    img, detected_format = open_allowed_uploaded_image(file_bytes, filename)
    original_size = img.size

    if img.mode == 'P':
        img = img.convert('RGBA')
    elif img.mode != 'RGB' and img.mode != 'RGBA':
        img = img.convert('RGB')

    if max_height and img.height > max_height:
        aspect_ratio = img.width / img.height
        resized_width = max(1, int(round(aspect_ratio * max_height)))
        img = img.resize((resized_width, max_height), Image.Resampling.LANCZOS)

    img_bytes_io = BytesIO()
    img.save(img_bytes_io, format='PNG', optimize=True)
    png_data = img_bytes_io.getvalue()

    return {
        'detected_format': detected_format,
        'original_size': original_size,
        'stored_size': img.size,
        'png_data': png_data,
        'base64_str': base64.b64encode(png_data).decode('utf-8'),
    }

def normalize_agents_page_color(value, fallback):
    candidate = str(value or '').strip()
    fallback_value = fallback if HEX_COLOR_PATTERN.fullmatch(str(fallback or '')) else '#0f172a'
    return candidate if HEX_COLOR_PATTERN.fullmatch(candidate) else fallback_value

def normalize_agents_page_color_mode(value):
    return 'two_tone' if str(value or '').strip() == 'two_tone' else 'single'

def normalize_agents_page_text(value, fallback, max_length):
    candidate = str(value or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not candidate:
        candidate = fallback
    return candidate[:max_length]

def register_route_frontend_admin_settings(app):
    @app.route('/admin/settings', methods=['GET', 'POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def admin_settings():
        settings = get_settings()
        settings['document_action_capabilities'] = normalize_document_action_capabilities(settings)
        admin_user = session.get('user', {})
        admin_email = admin_user.get('preferred_username', admin_user.get('email', 'unknown'))
        # --- Refined Default Checks (Good Practice) ---
        # Ensure models have default structure if missing/empty in DB
        if 'gpt_model' not in settings or not isinstance(settings.get('gpt_model'), dict) or 'selected' not in settings.get('gpt_model', {}):
            settings['gpt_model'] = {'selected': [], 'all': []}
        if 'embedding_model' not in settings or not isinstance(settings.get('embedding_model'), dict) or 'selected' not in settings.get('embedding_model', {}):
            settings['embedding_model'] = {'selected': [], 'all': []}
        if 'image_gen_model' not in settings or not isinstance(settings.get('image_gen_model'), dict) or 'selected' not in settings.get('image_gen_model', {}):
            settings['image_gen_model'] = {'selected': [], 'all': []}
        if 'enable_multi_model_endpoints' not in settings:
            settings['enable_multi_model_endpoints'] = False
        if 'model_endpoints' not in settings or not isinstance(settings.get('model_endpoints'), list):
            settings['model_endpoints'] = []
        if 'default_model_selection' not in settings or not isinstance(settings.get('default_model_selection'), dict):
            settings['default_model_selection'] = {
                'endpoint_id': '',
                'model_id': '',
                'provider': ''
            }
        if 'metadata_extraction_model_selection' not in settings or not isinstance(settings.get('metadata_extraction_model_selection'), dict):
            settings['metadata_extraction_model_selection'] = {
                'endpoint_id': '',
                'model_id': '',
                'provider': ''
            }
        if 'multi_endpoint_migrated_at' not in settings:
            settings['multi_endpoint_migrated_at'] = None
        if 'multi_endpoint_migration_notice' not in settings or not isinstance(settings.get('multi_endpoint_migration_notice'), dict):
            settings['multi_endpoint_migration_notice'] = {
                'enabled': False,
                'message': '',
                'created_at': None
            }

        normalized_endpoints, endpoints_changed = normalize_model_endpoints(settings.get('model_endpoints', []))
        if endpoints_changed:
            update_settings({'model_endpoints': normalized_endpoints})
        settings['model_endpoints'] = normalized_endpoints
        frontend_model_endpoints = sanitize_model_endpoints_for_frontend(normalized_endpoints)

        # (get_settings should handle this, but explicit check is safe)
        if 'require_member_of_create_group' not in settings:
            settings['require_member_of_create_group'] = False
        if 'require_member_of_create_public_workspace' not in settings:
            settings['require_member_of_create_public_workspace'] = False
        if 'enable_chat_file_uploads' not in settings:
            settings['enable_chat_file_uploads'] = True
        if 'require_member_of_chat_file_upload_user' not in settings:
            settings['require_member_of_chat_file_upload_user'] = False
        if 'require_member_of_safety_violation_admin' not in settings:
            settings['require_member_of_safety_violation_admin'] = False
        if 'require_member_of_control_center_admin' not in settings:
            settings['require_member_of_control_center_admin'] = False
        if 'require_member_of_feedback_admin' not in settings:
            settings['require_member_of_feedback_admin'] = False
        if 'control_center_auto_refresh_enabled' not in settings:
            settings['control_center_auto_refresh_enabled'] = True
        control_center_auto_refresh_schedule = get_control_center_auto_refresh_schedule(settings)
        settings['control_center_auto_refresh_time'] = control_center_auto_refresh_schedule['time']
        settings['control_center_auto_refresh_hour'] = control_center_auto_refresh_schedule['hour']
        settings['control_center_auto_refresh_minute'] = control_center_auto_refresh_schedule['minute']
        settings.update(normalize_cosmos_throughput_settings(settings))
        cosmos_resource_config = get_cosmos_resource_config(settings)
        settings['cosmos_throughput_resolved_subscription_id'] = cosmos_resource_config.get('subscription_id', '')
        settings['cosmos_throughput_resolved_resource_group'] = cosmos_resource_config.get('resource_group', '')
        settings['cosmos_throughput_resolved_account_name'] = cosmos_resource_config.get('account_name', '')
        settings['cosmos_throughput_resolved_database_name'] = cosmos_resource_config.get('database_name', '')
        settings['cosmos_throughput_cached_status'] = get_cached_cosmos_throughput_status(settings)
        # --- End NEW Default Checks ---

        # Ensure classification fields exist with defaults if missing in DB
        if 'enable_document_classification' not in settings:
            settings['enable_document_classification'] = False # Default value from get_settings
        if 'document_classification_categories' not in settings or not isinstance(settings.get('document_classification_categories'), list):
             # Default value from get_settings
            settings['document_classification_categories'] = [
                {"label": "None", "color": "#808080"},
                {"label": "N/A", "color": "#808080"},
                {"label": "Pending", "color": "#0000FF"}
            ]

        # Ensure external links fields exist with defaults if missing in DB
        if 'enable_external_links' not in settings:
            settings['enable_external_links'] = False
        if 'external_links_menu_name' not in settings:
            settings['external_links_menu_name'] = 'External Links'
        if 'external_links_force_menu' not in settings:
            settings['external_links_force_menu'] = False
        if 'external_links' not in settings or not isinstance(settings.get('external_links'), list):
            settings['external_links'] = [
                {"label": "Acceptable Use Policy", "url": "https://example.com/policy"},
                {"label": "Prompt Ideas", "url": "https://example.com/prompts"}
            ]
        if 'enable_custom_pages' not in settings:
            settings['enable_custom_pages'] = False
        if 'custom_pages_menu_name' not in settings:
            settings['custom_pages_menu_name'] = 'Custom Pages'
        if 'custom_pages_force_menu' not in settings:
            settings['custom_pages_force_menu'] = False
        if 'access_request_button_enabled' not in settings:
            settings['access_request_button_enabled'] = False
        if 'access_request_button_text' not in settings:
            settings['access_request_button_text'] = 'Request Access'
        if 'access_request_page_url' not in settings:
            settings['access_request_page_url'] = '/custom/request-access'
        if 'enable_support_menu' not in settings:
            settings['enable_support_menu'] = False
        if 'support_menu_name' not in settings:
            settings['support_menu_name'] = 'Support'
        if 'enable_support_send_feedback' not in settings:
            settings['enable_support_send_feedback'] = True
        if 'support_feedback_recipient_email' not in settings:
            settings['support_feedback_recipient_email'] = ''
        if 'enable_support_latest_features' not in settings:
            settings['enable_support_latest_features'] = True
        if 'enable_support_latest_feature_documentation_links' not in settings:
            settings['enable_support_latest_feature_documentation_links'] = False
        settings['support_latest_features_visibility'] = normalize_support_latest_features_visibility(
            settings.get('support_latest_features_visibility', {})
        )
        settings['support_latest_features_has_visible_items'] = has_visible_support_latest_features(settings)
        settings['support_feedback_recipient_configured'] = bool(
            str(settings.get('support_feedback_recipient_email') or '').strip()
        )

        # --- End Refined Default Checks ---

        if 'enable_appinsights_global_logging' not in settings:
            settings['enable_appinsights_global_logging'] = False
        if 'enable_debug_logging' not in settings:
            settings['enable_debug_logging'] = False

        # --- Add default for semantic_kernel ---
        if 'per_user_semantic_kernel' not in settings:
            settings['per_user_semantic_kernel'] = False
        if 'enable_semantic_kernel' not in settings:
            settings['enable_semantic_kernel'] = False

        if 'web_search_consent_accepted' not in settings:
            settings['web_search_consent_accepted'] = False
        for source_review_key, source_review_default in SOURCE_REVIEW_DEFAULTS.items():
            if source_review_key not in settings:
                settings[source_review_key] = list(source_review_default) if isinstance(source_review_default, list) else source_review_default

        file_sync_config = get_file_sync_config(settings)
        for file_sync_key in FILE_SYNC_DEFAULTS:
            if file_sync_key != 'enable_file_sync':
                settings[file_sync_key] = file_sync_config[file_sync_key]
        settings['requested_enable_file_sync'] = file_sync_config['requested_enable_file_sync']
        settings['file_sync_redis_ready'] = file_sync_config['redis_ready']
        settings['file_sync_effective_enabled'] = file_sync_config['enable_file_sync']
        settings['file_sync_max_gb_per_run'] = max(1, int(file_sync_config['file_sync_max_bytes_per_run'] / 1073741824))
        
        # --- Add default for swagger documentation ---
        if 'enable_swagger' not in settings:
            settings['enable_swagger'] = True  # Default enabled for development/testing
        if 'enable_external_healthcheck' not in settings:
            settings['enable_external_healthcheck'] = False
        if 'enable_no_auth_external_healthcheck' not in settings:
            settings['enable_no_auth_external_healthcheck'] = False
        if 'release_notifications_registered' not in settings:
            settings['release_notifications_registered'] = False
        if 'release_notifications_name' not in settings:
            settings['release_notifications_name'] = ''
        if 'release_notifications_email' not in settings:
            settings['release_notifications_email'] = ''
        if 'release_notifications_org' not in settings:
            settings['release_notifications_org'] = ''
        if 'release_notifications_registered_at' not in settings:
            settings['release_notifications_registered_at'] = ''
        if 'release_notifications_updated_at' not in settings:
            settings['release_notifications_updated_at'] = ''
        if 'enable_time_plugin' not in settings:
            settings['enable_time_plugin'] = False
        if 'enable_http_plugin' not in settings:
            settings['enable_http_plugin'] = False
        if 'enable_wait_plugin' not in settings:
            settings['enable_wait_plugin'] = False
        if 'enable_math_plugin' not in settings:
            settings['enable_math_plugin'] = False
        if 'enable_text_plugin' not in settings:
            settings['enable_text_plugin'] = False
        if 'enable_fact_memory_plugin' not in settings:
            settings['enable_fact_memory_plugin'] = False
        settings['enable_tabular_processing_plugin'] = is_tabular_processing_enabled(settings)
        if 'enable_default_embedding_model_plugin' not in settings:
            settings['enable_default_embedding_model_plugin'] = False
        if 'enable_multi_agent_orchestration' not in settings:
            settings['enable_multi_agent_orchestration'] = False
        if 'max_rounds_per_agent' not in settings:
            settings['max_rounds_per_agent'] = 1
        if 'orchestration_type' not in settings:
            settings['orchestration_type'] = 'default_agent'
        # NOTE: semantic_kernel_plugins are now stored in containers, not settings
        if 'merge_global_semantic_kernel_with_workspace' not in settings:
            settings['merge_global_semantic_kernel_with_workspace'] = False
        # NOTE: semantic_kernel_agents are now stored in containers, not settings
        if 'global_selected_agent' not in settings:
            # Use container-based storage for global agents instead of legacy settings
            from functions_global_agents import get_all_global_agents
            try:
                global_agents = get_all_global_agents()
                default_agent = next((a for a in global_agents if a.get('default_agent')), None)
                if default_agent:
                    settings['global_selected_agent'] = {
                        'name': default_agent['name'],
                        'is_global': True
                    }
                else:
                    # Fallback to first agent if no default found
                    if global_agents:
                        settings['global_selected_agent'] = {
                            'name': global_agents[0]['name'],
                            'is_global': True
                        }
                    else: 
                        settings['global_selected_agent'] = {
                            'name': 'default_agent',
                            'is_global': True
                        }
            except Exception:
                # Fallback if container access fails
                settings['global_selected_agent'] = {
                    'name': 'default_agent',
                    'is_global': True
                }
                log_event("Error retrieving global agents for default selection.", level=logging.ERROR)
                debug_print("Error retrieving global agents for default selection.")
                
        if 'allow_user_agents' not in settings:
            settings['allow_user_agents'] = False
        if 'allow_user_custom_endpoints' not in settings:
            settings['allow_user_custom_endpoints'] = settings.get('allow_user_custom_agent_endpoints', False)
        if 'allow_user_plugins' not in settings:
            settings['allow_user_plugins'] = False
        if 'allow_user_workflows' not in settings:
            settings['allow_user_workflows'] = False
        if 'require_member_of_workflow_user' not in settings:
            settings['require_member_of_workflow_user'] = False
        if 'allow_group_workflows' not in settings:
            settings['allow_group_workflows'] = False
        if 'require_group_assignment_for_group_workflows' not in settings:
            settings['require_group_assignment_for_group_workflows'] = False
        settings['group_workflow_allowed_group_ids'] = normalize_group_workflow_allowed_group_ids(
            settings.get('group_workflow_allowed_group_ids', [])
        )
        if 'allow_personal_workspace_file_downloads' not in settings:
            settings['allow_personal_workspace_file_downloads'] = False
        if 'allow_group_workspace_file_downloads' not in settings:
            settings['allow_group_workspace_file_downloads'] = False
        if 'require_group_assignment_for_file_downloads' not in settings:
            settings['require_group_assignment_for_file_downloads'] = False
        settings['file_download_allowed_group_ids'] = normalize_file_download_allowed_group_ids(
            settings.get('file_download_allowed_group_ids', [])
        )
        if 'allow_public_workspace_file_downloads' not in settings:
            settings['allow_public_workspace_file_downloads'] = False
        if 'require_public_workspace_assignment_for_file_downloads' not in settings:
            settings['require_public_workspace_assignment_for_file_downloads'] = False
        settings['file_download_allowed_public_workspace_ids'] = normalize_file_download_allowed_public_workspace_ids(
            settings.get('file_download_allowed_public_workspace_ids', [])
        )
        if 'allow_group_agents' not in settings:
            settings['allow_group_agents'] = False
        if 'allow_group_custom_endpoints' not in settings:
            settings['allow_group_custom_endpoints'] = settings.get('allow_group_custom_agent_endpoints', False)
        if 'allow_group_plugins' not in settings:
            settings['allow_group_plugins'] = False
        if 'enable_agent_template_gallery' not in settings:
            settings['enable_agent_template_gallery'] = True
        if 'agent_templates_allow_user_submission' not in settings:
            settings['agent_templates_allow_user_submission'] = True
        if 'agent_templates_require_approval' not in settings:
            settings['agent_templates_require_approval'] = True
        for agents_page_key, agents_page_default in AGENTS_PAGE_DEFAULTS.items():
            if agents_page_key not in settings:
                settings[agents_page_key] = agents_page_default
        settings['agents_page_hero_color_mode'] = normalize_agents_page_color_mode(
            settings.get('agents_page_hero_color_mode')
        )
        settings['agents_page_hero_primary_color'] = normalize_agents_page_color(
            settings.get('agents_page_hero_primary_color'),
            AGENTS_PAGE_DEFAULTS['agents_page_hero_primary_color'],
        )
        settings['agents_page_hero_secondary_color'] = normalize_agents_page_color(
            settings.get('agents_page_hero_secondary_color'),
            AGENTS_PAGE_DEFAULTS['agents_page_hero_secondary_color'],
        )

        # --- Add defaults for classification banner ---
        if 'classification_banner_enabled' not in settings:
            settings['classification_banner_enabled'] = False
        if 'classification_banner_text' not in settings:
            settings['classification_banner_text'] = ''
        if 'classification_banner_color' not in settings:
            settings['classification_banner_color'] = '#ffc107'  # Bootstrap warning color
        if 'classification_banner_text_color' not in settings:
            settings['classification_banner_text_color'] = '#ffffff'  # White text by default
        
        # --- Add defaults for user agreement ---
        if 'enable_user_agreement' not in settings:
            settings['enable_user_agreement'] = False
        if 'user_agreement_text' not in settings:
            settings['user_agreement_text'] = ''
        if 'user_agreement_apply_to' not in settings:
            settings['user_agreement_apply_to'] = []
        if 'enable_user_agreement_daily' not in settings:
            settings['enable_user_agreement_daily'] = False
        
        # --- Add defaults for key vault
        if 'enable_key_vault_secret_storage' not in settings:
            settings['enable_key_vault_secret_storage'] = False
        if 'key_vault_name' not in settings:
            settings['key_vault_name'] = ''
        if 'key_vault_identity' not in settings:
            settings['key_vault_identity'] = ''

            # --- Add defaults for left nav ---
        if 'enable_left_nav_default' not in settings:
            settings['enable_left_nav_default'] = True
        
        # --- Add defaults for workspace scope lock ---
        if 'enforce_workspace_scope_lock' not in settings:
            settings['enforce_workspace_scope_lock'] = True

        # --- Add defaults for multimodal vision ---
        if 'enable_multimodal_vision' not in settings:
            settings['enable_multimodal_vision'] = False
        if 'multimodal_vision_model' not in settings:
            settings['multimodal_vision_model'] = ''

        # --- Add defaults for user idle timeout ---
        if 'enable_idle_timeout' not in settings:
            settings['enable_idle_timeout'] = False
        if 'idle_timeout_minutes' not in settings:
            settings['idle_timeout_minutes'] = 30
        if 'idle_warning_minutes' not in settings:
            settings['idle_warning_minutes'] = 28
        if 'idle_warning_message' not in settings:
            settings['idle_warning_message'] = "You've been inactive for a while."
            
        if request.method == 'GET':
            # --- Model fetching logic remains the same ---
            gpt_deployments = []
            embedding_deployments = []
            image_deployments = []
            # (Keep your existing try...except blocks for fetching models)
            # Example (simplified):
            try:
                 gpt_endpoint = settings.get("azure_openai_gpt_endpoint", "").strip()
                 if gpt_endpoint and settings.get("azure_openai_gpt_key") and settings.get("azure_openai_gpt_authentication_type") == 'key':
                     # Your logic to list deployments
                     pass # Replace with actual logic
            except Exception as e:
                 print(f"Error retrieving GPT deployments: {e}")
                 log_event(f"Error retrieving GPT deployments: {e}", level=logging.ERROR)

            # Check for application updates
            current_version = app.config['VERSION']
            update_available = False
            latest_version = None
            download_url = "https://github.com/microsoft/simplechat/releases"
            
            # Only check for updates every 24 hours at most
            last_check_time = settings.get('last_update_check_time')
            check_needed = last_check_time is None or (
                datetime.now(timezone.utc) - 
                datetime.fromisoformat(last_check_time)
            ).total_seconds() > 86400  # 24 hours in seconds
            
            if check_needed:
                try:
                    # Fetch latest release from GitHub
                    response = requests.get(
                        "https://github.com/microsoft/simplechat/releases", 
                        timeout=3
                    )
                    if response.status_code == 200:
                        # Extract the latest version
                        latest_version = extract_latest_version_from_html(response.text)
                        
                        # Store the results in settings for persistence
                        new_settings = {
                            'last_update_check_time': datetime.now(timezone.utc).isoformat(),
                            'latest_version_available': latest_version
                        }
                        
                        # Compare with current version
                        if latest_version and compare_versions(latest_version, current_version) == 1:
                            new_settings['update_available'] = True
                        else:
                            new_settings['update_available'] = False
                        
                        # Update settings to persist these values
                        update_settings(new_settings)
                        settings.update(new_settings)
                except Exception as e:
                    print(f"Error checking for updates: {e}")
                    log_event(f"Error checking for updates: {e}", level=logging.ERROR)
            
            # Get the persisted values for template rendering
            update_available = settings.get('update_available', False)
            latest_version = settings.get('latest_version_available')
            
            # Get user settings for profile and navigation
            user_id = get_current_user_id()
            user_settings = get_user_settings(user_id)
            settings_for_template = dict(settings)
            settings_for_template['model_endpoints'] = frontend_model_endpoints
            source_review_runtime_capabilities = get_source_review_runtime_capabilities()
            settings_for_template['source_review_allow_js_rendering'] = normalize_source_review_js_rendering_enabled(
                settings_for_template.get('source_review_allow_js_rendering'),
                source_review_runtime_capabilities,
            )
            settings_for_template = redact_admin_settings_secrets_for_form(settings_for_template)

            return render_template(
                'admin_settings.html',
                app_settings=settings_for_template,
                settings=settings_for_template,
                azure_environment=AZURE_ENVIRONMENT,
                default_video_indexer_endpoint=video_indexer_endpoint,
                default_video_indexer_arm_api_version=DEFAULT_VIDEO_INDEXER_ARM_API_VERSION,
                user_settings=user_settings,
                update_available=update_available,
                latest_version=latest_version,
                download_url=download_url,
                support_latest_feature_catalog=get_support_latest_feature_catalog(),
                support_latest_feature_release_groups=get_support_latest_feature_release_groups(),
                support_latest_feature_release_groups_preview=get_support_latest_feature_release_groups_for_settings(settings),
                chunk_size_defaults=get_chunk_size_defaults(),
                chunk_size_settings=settings.get('chunk_size', {}),
                chunk_size_cap=get_chunk_size_cap(settings),
                chunk_size_effective=get_chunk_size_config(settings),
                source_review_runtime_capabilities=source_review_runtime_capabilities
                # You don't need to pass deployments separately if they are added to settings['..._model']['all']
                # gpt_deployments=gpt_deployments,
                # embedding_deployments=embedding_deployments,
                # image_deployments=image_deployments
            )

        if request.method == 'POST':
            form_data = request.form # Use a variable for easier access
            user_id = get_current_user_id()

            def admin_secret(field_name, form_field_name=None):
                submitted_value = form_data.get(form_field_name or field_name, '').strip()
                return resolve_admin_settings_secret_value(field_name, submitted_value, settings)

            def parse_admin_int(raw_value, fallback_value, field_name="unknown", hard_default=0):
                """
                Parse an admin form value to an integer with structured fallback diagnostics.

                Args:
                    raw_value (object): The submitted form value to parse.
                    fallback_value (object): The fallback value to parse when input conversion fails.
                    field_name (str): The admin settings field name being parsed.
                    hard_default (int): Final integer default when both input and fallback are invalid.

                Returns:
                    int: A valid integer derived from input, fallback, or hard default.
                Raises:
                    None.
                """
                parsed_value, parse_source = safe_int_with_source(raw_value, fallback_value, hard_default)

                if parse_source == "hard_default":
                    log_event(
                        "Invalid admin settings integer input and fallback detected; using hard default value.",
                        extra={
                            "field": field_name,
                            "raw_value": str(raw_value),
                            "fallback_value": str(fallback_value),
                            "hard_default": hard_default,
                            "user_id": user_id
                        },
                        level=logging.WARNING
                    )
                elif parse_source == "fallback":
                    log_event(
                        "Invalid admin settings integer input detected; using fallback value.",
                        extra={
                            "field": field_name,
                            "raw_value": str(raw_value),
                            "fallback_value": str(fallback_value),
                            "user_id": user_id
                        },
                        level=logging.WARNING
                    )

                return parsed_value

            # --- Fetch all other form data as before ---
            app_title = form_data.get('app_title', 'AI Chat Application')
            landing_page_logo_scale_percent = min(
                500,
                max(
                    50,
                    parse_admin_int(
                        form_data.get('landing_page_logo_scale_percent'),
                        settings.get('landing_page_logo_scale_percent', 100),
                        'landing_page_logo_scale_percent',
                        100
                    )
                )
            )
            max_file_size_mb = int(form_data.get('max_file_size_mb', 16))
            conversation_history_limit = int(form_data.get('conversation_history_limit', 10))
            enable_idle_timeout = form_data.get('enable_idle_timeout') == 'on'
            idle_timeout_minutes = max(10, parse_admin_int(form_data.get('idle_timeout_minutes'), settings.get('idle_timeout_minutes', 30), 'idle_timeout_minutes', 30))
            idle_warning_minutes = max(0, parse_admin_int(form_data.get('idle_warning_minutes'), settings.get('idle_warning_minutes', 28), 'idle_warning_minutes', 28))
            idle_warning_message = form_data.get(
                'idle_warning_message',
                settings.get('idle_warning_message', "You've been inactive for a while.")
            ).strip()
            if idle_warning_minutes > idle_timeout_minutes:
                idle_warning_minutes = idle_timeout_minutes
            if not idle_warning_message:
                idle_warning_message = "You've been inactive for a while."
            # ... (fetch all other fields using form_data.get) ...
            enable_video_file_support = form_data.get('enable_video_file_support') == 'on'
            enable_audio_file_support = form_data.get('enable_audio_file_support') == 'on'
            enable_extract_meta_data = form_data.get('enable_extract_meta_data') == 'on'
            
            # Vision settings
            enable_multimodal_vision = form_data.get('enable_multimodal_vision') == 'on'
            multimodal_vision_model = form_data.get('multimodal_vision_model', '')

            require_member_of_create_group = form_data.get('require_member_of_create_group') == 'on'
            require_owner_for_group_agent_management = form_data.get('require_owner_for_group_agent_management') == 'on'
            require_member_of_create_public_workspace = form_data.get('require_member_of_create_public_workspace') == 'on'
            require_member_of_chat_file_upload_user = form_data.get('require_member_of_chat_file_upload_user') == 'on'
            require_member_of_workflow_user = form_data.get('require_member_of_workflow_user') == 'on'
            group_workflow_allowed_group_ids = normalize_group_workflow_allowed_group_ids(
                form_data.get('group_workflow_allowed_group_ids', '')
            )
            workflow_max_auto_invoke_attempts = min(
                500,
                max(
                    1,
                    parse_admin_int(
                        form_data.get('workflow_max_auto_invoke_attempts'),
                        settings.get('workflow_max_auto_invoke_attempts', 60),
                        'workflow_max_auto_invoke_attempts',
                        60
                    )
                )
            )
            file_sync_allowed_group_ids = normalize_file_sync_allowed_group_ids(
                form_data.get('file_sync_allowed_group_ids', '')
            )
            file_sync_allowed_public_workspace_ids = normalize_file_sync_allowed_public_workspace_ids(
                form_data.get('file_sync_allowed_public_workspace_ids', '')
            )
            file_download_allowed_group_ids = normalize_file_download_allowed_group_ids(
                form_data.get('file_download_allowed_group_ids', '')
            )
            file_download_allowed_public_workspace_ids = normalize_file_download_allowed_public_workspace_ids(
                form_data.get('file_download_allowed_public_workspace_ids', '')
            )
            require_member_of_safety_violation_admin = form_data.get('require_member_of_safety_violation_admin') == 'on'
            require_member_of_control_center_admin = form_data.get('require_member_of_control_center_admin') == 'on'
            require_member_of_control_center_dashboard_reader = form_data.get('require_member_of_control_center_dashboard_reader') == 'on'
            require_member_of_feedback_admin = form_data.get('require_member_of_feedback_admin') == 'on'

            control_center_auto_refresh_enabled = form_data.get('control_center_auto_refresh_enabled') == 'on'
            incoming_control_center_auto_refresh_time = form_data.get(
                'control_center_auto_refresh_time',
                settings.get('control_center_auto_refresh_time', '06:00')
            )
            control_center_auto_refresh_schedule = get_control_center_auto_refresh_schedule({
                'control_center_auto_refresh_time': incoming_control_center_auto_refresh_time,
                'control_center_auto_refresh_hour': settings.get('control_center_auto_refresh_hour', 6),
                'control_center_auto_refresh_minute': settings.get('control_center_auto_refresh_minute', 0),
            })
            existing_control_center_auto_refresh_schedule = get_control_center_auto_refresh_schedule(settings)
            existing_control_center_auto_refresh_enabled = settings.get('control_center_auto_refresh_enabled', True)
            existing_control_center_auto_refresh_next_run = settings.get('control_center_auto_refresh_next_run')
            control_center_auto_refresh_schedule_changed = (
                control_center_auto_refresh_enabled != existing_control_center_auto_refresh_enabled or
                control_center_auto_refresh_schedule['time'] != existing_control_center_auto_refresh_schedule['time']
            )
            if control_center_auto_refresh_enabled:
                if control_center_auto_refresh_schedule_changed or not existing_control_center_auto_refresh_next_run:
                    control_center_auto_refresh_next_run = calculate_next_control_center_auto_refresh_run(
                        {
                            'control_center_auto_refresh_time': control_center_auto_refresh_schedule['time'],
                            'control_center_auto_refresh_hour': control_center_auto_refresh_schedule['hour'],
                            'control_center_auto_refresh_minute': control_center_auto_refresh_schedule['minute'],
                        },
                        current_time=datetime.now(timezone.utc),
                    ).isoformat()
                else:
                    control_center_auto_refresh_next_run = existing_control_center_auto_refresh_next_run
            else:
                control_center_auto_refresh_next_run = None

            web_search_consent_message = (
                "When you use Grounding with Bing Search, your customer data is transferred "
                "outside of the Azure compliance boundary to the Grounding with Bing Search service. "
                "Grounding with Bing Search is not subject to the same data processing terms "
                "(including location of processing) and does not have the same compliance standards "
                "and certifications as the Azure AI Agent Service, as described in the "
                "Grounding with Bing Search TOU (https://www.microsoft.com/en-us/bing/apis/grounding-legal). "
                "It is your responsibility to assess whether use of Grounding with Bing Search in your agent "
                "meets your needs and requirements."
            )
            web_search_consent_accepted = form_data.get('web_search_consent_accepted') == 'true'
            requested_enable_web_search = form_data.get('enable_web_search') == 'on'
            enable_web_search = requested_enable_web_search and web_search_consent_accepted

            if requested_enable_web_search and not web_search_consent_accepted:
                flash('Web search requires consent before it can be enabled.', 'warning')

            if enable_web_search and web_search_consent_accepted and not settings.get('web_search_consent_accepted'):
                log_web_search_consent_acceptance(
                    user_id=user_id,
                    admin_email=admin_email,
                    consent_text=web_search_consent_message,
                    source='admin_settings'
                )

            existing_source_review_max_bytes = parse_admin_int(
                settings.get('source_review_max_bytes_per_page'),
                5000000,
                'source_review_max_bytes_per_page',
                5000000
            )
            source_review_max_bytes_mb = max(
                1,
                parse_admin_int(
                    form_data.get('source_review_max_bytes_per_page_mb'),
                    max(1, int(existing_source_review_max_bytes / 1000000)),
                    'source_review_max_bytes_per_page_mb',
                    5
                )
            )
            source_review_runtime_capabilities = get_source_review_runtime_capabilities()
            source_review_settings = get_source_review_config({
                'enable_url_access': form_data.get('enable_url_access') == 'on',
                'url_access_max_chat_urls_per_turn': parse_admin_int(
                    form_data.get('url_access_max_chat_urls_per_turn'),
                    settings.get('url_access_max_chat_urls_per_turn', 10),
                    'url_access_max_chat_urls_per_turn',
                    10
                ),
                'url_access_max_workflow_urls_per_run': parse_admin_int(
                    form_data.get('url_access_max_workflow_urls_per_run'),
                    settings.get('url_access_max_workflow_urls_per_run', 50),
                    'url_access_max_workflow_urls_per_run',
                    50
                ),
                'url_access_allowed_domains': parse_source_review_list(
                    form_data.get('url_access_allowed_domains') or form_data.get('source_review_allowed_domains')
                ),
                'url_access_blocked_domains': parse_source_review_list(
                    form_data.get('url_access_blocked_domains') or form_data.get('source_review_blocked_domains')
                ),
                'require_member_of_url_access_user': form_data.get('require_member_of_url_access_user') == 'on',
                'enable_source_review': form_data.get('enable_source_review') == 'on',
                'require_member_of_deep_research_user': form_data.get('require_member_of_deep_research_user') == 'on',
                'source_review_allow_internal_hosts': form_data.get('source_review_allow_internal_hosts') == 'on',
                'enable_deep_source_review': form_data.get('enable_deep_source_review') == 'on',
                'source_review_default_mode': form_data.get('source_review_default_mode', 'manual'),
                'source_review_max_pages_per_turn': parse_admin_int(
                    form_data.get('source_review_max_pages_per_turn'),
                    settings.get('source_review_max_pages_per_turn', 10),
                    'source_review_max_pages_per_turn',
                    10
                ),
                'source_review_max_seed_pages_per_turn': parse_admin_int(
                    form_data.get('source_review_max_seed_pages_per_turn'),
                    settings.get('source_review_max_seed_pages_per_turn', 10),
                    'source_review_max_seed_pages_per_turn',
                    10
                ),
                'source_review_max_depth': parse_admin_int(
                    form_data.get('source_review_max_depth'),
                    settings.get('source_review_max_depth', 2),
                    'source_review_max_depth',
                    2
                ),
                'source_review_timeout_seconds': parse_admin_int(
                    form_data.get('source_review_timeout_seconds'),
                    settings.get('source_review_timeout_seconds', 30),
                    'source_review_timeout_seconds',
                    30
                ),
                'source_review_max_redirects': parse_admin_int(
                    form_data.get('source_review_max_redirects'),
                    settings.get('source_review_max_redirects', 5),
                    'source_review_max_redirects',
                    5
                ),
                'source_review_max_bytes_per_page': source_review_max_bytes_mb * 1000000,
                'deep_research_max_user_urls_per_turn': parse_admin_int(
                    form_data.get('deep_research_max_user_urls_per_turn'),
                    settings.get('deep_research_max_user_urls_per_turn', 100),
                    'deep_research_max_user_urls_per_turn',
                    100
                ),
                'deep_research_max_search_queries_per_turn': parse_admin_int(
                    form_data.get('deep_research_max_search_queries_per_turn'),
                    settings.get('deep_research_max_search_queries_per_turn', 8),
                    'deep_research_max_search_queries_per_turn',
                    8
                ),
                'deep_research_enable_query_planning': form_data.get('deep_research_enable_query_planning') == 'on',
                'deep_research_enable_ledger_artifact': form_data.get('deep_research_enable_ledger_artifact') == 'on',
                'source_review_enable_llm_planning': form_data.get('source_review_enable_llm_planning') == 'on',
                'source_review_allow_js_rendering': normalize_source_review_js_rendering_enabled(
                    form_data.get('source_review_allow_js_rendering') == 'on',
                    source_review_runtime_capabilities,
                ),
                'source_review_js_load_more_clicks': parse_admin_int(
                    form_data.get('source_review_js_load_more_clicks'),
                    settings.get('source_review_js_load_more_clicks', 12),
                    'source_review_js_load_more_clicks',
                    12
                ),
                'source_review_respect_robots_txt': form_data.get('source_review_respect_robots_txt') == 'on',
                'source_review_allowed_domains': parse_source_review_list(
                    form_data.get('url_access_allowed_domains') or form_data.get('source_review_allowed_domains')
                ),
                'source_review_blocked_domains': parse_source_review_list(
                    form_data.get('url_access_blocked_domains') or form_data.get('source_review_blocked_domains')
                ),
                'source_review_allowed_users': [],
                'source_review_blocked_users': [],
                'source_review_audit_logging': form_data.get('source_review_audit_logging') == 'on',
            })

            requested_enable_file_sync = form_data.get('enable_file_sync') == 'on'
            file_sync_submitted_settings = dict(settings)
            file_sync_submitted_settings.update({
                'enable_redis_cache': form_data.get('enable_redis_cache') == 'on',
                'redis_url': form_data.get('redis_url', '').strip(),
                'redis_key': admin_secret('redis_key'),
                'redis_auth_type': form_data.get('redis_auth_type', '').strip(),
                'enable_file_sync': requested_enable_file_sync,
                'enable_file_sync_personal': form_data.get('enable_file_sync_personal') == 'on',
                'enable_file_sync_group': form_data.get('enable_file_sync_group') == 'on',
                'enable_file_sync_public': form_data.get('enable_file_sync_public') == 'on',
                'file_sync_personal_require_app_role': form_data.get('file_sync_personal_require_app_role') == 'on',
                'require_group_assignment_for_file_sync': form_data.get('require_group_assignment_for_file_sync') == 'on',
                'file_sync_allowed_group_ids': file_sync_allowed_group_ids,
                'require_public_workspace_assignment_for_file_sync': form_data.get('require_public_workspace_assignment_for_file_sync') == 'on',
                'file_sync_allowed_public_workspace_ids': file_sync_allowed_public_workspace_ids,
                'file_sync_personal_admin_only': form_data.get('file_sync_personal_admin_only') == 'on',
                'file_sync_group_admin_only': form_data.get('file_sync_group_admin_only') == 'on',
                'file_sync_public_admin_only': form_data.get('file_sync_public_admin_only') == 'on',
                'file_sync_visible_source_types': form_data.getlist('file_sync_visible_source_types'),
                'file_sync_max_sources_per_scope': parse_admin_int(
                    form_data.get('file_sync_max_sources_per_scope'),
                    settings.get('file_sync_max_sources_per_scope', FILE_SYNC_DEFAULTS['file_sync_max_sources_per_scope']),
                    'file_sync_max_sources_per_scope',
                    FILE_SYNC_DEFAULTS['file_sync_max_sources_per_scope']
                ),
                'file_sync_min_schedule_interval_minutes': parse_admin_int(
                    form_data.get('file_sync_min_schedule_interval_minutes'),
                    settings.get('file_sync_min_schedule_interval_minutes', FILE_SYNC_DEFAULTS['file_sync_min_schedule_interval_minutes']),
                    'file_sync_min_schedule_interval_minutes',
                    FILE_SYNC_DEFAULTS['file_sync_min_schedule_interval_minutes']
                ),
                'file_sync_max_files_per_run': parse_admin_int(
                    form_data.get('file_sync_max_files_per_run'),
                    settings.get('file_sync_max_files_per_run', FILE_SYNC_DEFAULTS['file_sync_max_files_per_run']),
                    'file_sync_max_files_per_run',
                    FILE_SYNC_DEFAULTS['file_sync_max_files_per_run']
                ),
                'file_sync_max_bytes_per_run': parse_admin_int(
                    form_data.get('file_sync_max_gb_per_run'),
                    max(1, int(settings.get('file_sync_max_bytes_per_run', FILE_SYNC_DEFAULTS['file_sync_max_bytes_per_run']) / 1073741824)),
                    'file_sync_max_gb_per_run',
                    5
                ) * 1073741824,
                'file_sync_max_concurrent_runs': parse_admin_int(
                    form_data.get('file_sync_max_concurrent_runs'),
                    settings.get('file_sync_max_concurrent_runs', FILE_SYNC_DEFAULTS['file_sync_max_concurrent_runs']),
                    'file_sync_max_concurrent_runs',
                    FILE_SYNC_DEFAULTS['file_sync_max_concurrent_runs']
                ),
                'file_sync_allow_recursive_sources': form_data.get('file_sync_allow_recursive_sources') == 'on',
                'file_sync_default_remote_delete_policy': FILE_SYNC_DEFAULTS['file_sync_default_remote_delete_policy'],
            })
            file_sync_settings = get_file_sync_config(file_sync_submitted_settings)

            if requested_enable_file_sync and not file_sync_settings['redis_ready']:
                flash('File Sync was saved as requested, but it will remain inactive until Redis Cache is enabled and configured.', 'warning')

            # --- Handle Document Classification Toggle ---
            enable_document_classification = form_data.get('enable_document_classification') == 'on'

            # --- Handle Document Classification Categories JSON ---
            document_classification_categories_json = form_data.get("document_classification_categories_json", "[]") # Default to empty list string
            parsed_categories = [] # Initialize
            try:
                parsed_categories_raw = json.loads(document_classification_categories_json)
                # Validation
                if isinstance(parsed_categories_raw, list) and all(
                    isinstance(item, dict) and
                    'label' in item and isinstance(item['label'], str) and item['label'].strip() and # Ensure label is non-empty string
                    'color' in item and isinstance(item['color'], str) and item['color'].startswith('#') # Basic color format check
                    for item in parsed_categories_raw
                ):
                    # Sanitize/clean data slightly
                    parsed_categories = [
                        {'label': item['label'].strip(), 'color': item['color']}
                        for item in parsed_categories_raw
                    ]
                    print(f"Successfully parsed {len(parsed_categories)} classification categories.")
                else:
                     raise ValueError("Invalid format: Expected a list of objects with 'label' and 'color' keys.")

            except (json.JSONDecodeError, ValueError) as e:
                print(f"Error processing document_classification_categories_json: {e}")
                flash(f'Error processing classification categories: {e}. Changes for categories not saved.', 'danger')
                # Keep existing categories from the database instead of overwriting with bad data
                parsed_categories = settings.get('document_classification_categories', []) # Fallback to existing

            # --- Handle External Links Toggle ---
            enable_external_links = form_data.get('enable_external_links') == 'on'

            # --- Handle External Links Menu Name ---
            external_links_menu_name = form_data.get('external_links_menu_name', 'External Links').strip()
            if not external_links_menu_name:  # If empty, set to default
                external_links_menu_name = 'External Links'

            # --- Handle External Links Force Menu ---
            external_links_force_menu = form_data.get('external_links_force_menu') == 'on'

            # --- Handle External Links JSON ---
            external_links_json = form_data.get("external_links_json", "[]") # Default to empty list string
            parsed_external_links = [] # Initialize
            try:
                parsed_external_links_raw = json.loads(external_links_json)
                # Validation
                if isinstance(parsed_external_links_raw, list) and all(
                    isinstance(item, dict) and
                    'label' in item and isinstance(item['label'], str) and item['label'].strip() and # Ensure label is non-empty string
                    'url' in item and isinstance(item['url'], str) and item['url'].strip() # Ensure URL is non-empty string
                    for item in parsed_external_links_raw
                ):
                    # Sanitize/clean data slightly
                    parsed_external_links = [
                        {'label': item['label'].strip(), 'url': item['url'].strip()}
                        for item in parsed_external_links_raw
                    ]
                    print(f"Successfully parsed {len(parsed_external_links)} external links.")
                else:
                     raise ValueError("Invalid format: Expected a list of objects with 'label' and 'url' keys.")

            except (json.JSONDecodeError, ValueError) as e:
                print(f"Error processing external_links_json: {e}")
                flash(f'Error processing external links: {e}. Changes for external links not saved.', 'danger')
                # Keep existing external links from the database instead of overwriting with bad data
                parsed_external_links = settings.get('external_links', []) # Fallback to existing

            enable_custom_pages = form_data.get('enable_custom_pages') == 'on'
            custom_pages_was_enabled = bool(settings.get('enable_custom_pages', False))
            custom_pages_restart_acknowledged = form_data.get('custom_pages_restart_acknowledged') == 'on'
            if enable_custom_pages and not custom_pages_was_enabled and not custom_pages_restart_acknowledged:
                flash(
                    'Custom Pages requires acknowledgement that the App Service must be restarted before it is fully enabled. The feature was not enabled.',
                    'danger'
                )
                enable_custom_pages = False
            custom_pages_menu_name = form_data.get('custom_pages_menu_name', 'Custom Pages').strip()
            if not custom_pages_menu_name:
                custom_pages_menu_name = 'Custom Pages'
            custom_pages_force_menu = form_data.get('custom_pages_force_menu') == 'on'

            enable_support_menu = form_data.get('enable_support_menu') == 'on'
            support_menu_name = form_data.get('support_menu_name', 'Support').strip()
            if not support_menu_name:
                support_menu_name = 'Support'

            enable_support_send_feedback = form_data.get('enable_support_send_feedback') == 'on'
            support_feedback_recipient_email = form_data.get('support_feedback_recipient_email', '').strip()
            if enable_support_send_feedback and not support_feedback_recipient_email:
                flash('Support Send Feedback requires a recipient email. The Send Feedback entry was disabled.', 'warning')
                enable_support_send_feedback = False
            elif support_feedback_recipient_email and '@' not in support_feedback_recipient_email:
                flash('Support feedback recipient email must be a valid email address. The Send Feedback entry was disabled.', 'warning')
                support_feedback_recipient_email = ''
                enable_support_send_feedback = False

            enable_support_latest_features = form_data.get('enable_support_latest_features') == 'on'
            enable_support_latest_feature_documentation_links = (
                form_data.get('enable_support_latest_feature_documentation_links') == 'on'
            )
            support_latest_features_visibility = {}
            for feature in get_support_latest_feature_catalog():
                field_name = f"support_latest_feature_{feature['id']}"
                support_latest_features_visibility[feature['id']] = form_data.get(field_name) == 'on'
            support_latest_features_visibility = normalize_support_latest_features_visibility(
                support_latest_features_visibility
            )

            current_document_action_capabilities = normalize_document_action_capabilities(settings)
            document_action_capabilities = normalize_document_action_capabilities({
                'document_action_capabilities': {
                    'analyze': {
                        'enabled': form_data.get('document_action_analyze_enabled') == 'on',
                        'chat_max_documents': parse_admin_int(
                            form_data.get('document_action_analyze_chat_max_documents'),
                            current_document_action_capabilities.get('analyze', {}).get('chat_max_documents', 3),
                            'document_action_analyze_chat_max_documents',
                            3,
                        ),
                        'workflow_max_documents': parse_admin_int(
                            form_data.get('document_action_analyze_workflow_max_documents'),
                            current_document_action_capabilities.get('analyze', {}).get('workflow_max_documents', 10),
                            'document_action_analyze_workflow_max_documents',
                            10,
                        ),
                    },
                    'comparison': {
                        'enabled': form_data.get('document_action_comparison_enabled') == 'on',
                        'chat_max_documents': parse_admin_int(
                            form_data.get('document_action_comparison_chat_max_documents'),
                            current_document_action_capabilities.get('comparison', {}).get('chat_max_documents', 3),
                            'document_action_comparison_chat_max_documents',
                            3,
                        ),
                        'workflow_max_documents': parse_admin_int(
                            form_data.get('document_action_comparison_workflow_max_documents'),
                            current_document_action_capabilities.get('comparison', {}).get('workflow_max_documents', 10),
                            'document_action_comparison_workflow_max_documents',
                            10,
                        ),
                    },
                }
            })

            # Enhanced Citations...
            enable_enhanced_citations = form_data.get('enable_enhanced_citations') == 'on'
            office_docs_storage_account_blob_endpoint = form_data.get('office_docs_storage_account_blob_endpoint', '').strip()
            office_docs_storage_account_url = form_data.get('office_docs_storage_account_url', '').strip()

            
            # Validate that if enhanced citations are enabled, a connection string is provided
            if enable_enhanced_citations and not (office_docs_storage_account_blob_endpoint or office_docs_storage_account_url):
                flash("Enhanced Citations cannot be enabled without providing a connection string or blob service endpoint. Feature has been disabled.", "danger")
                enable_enhanced_citations = False

            # Model JSON Parsing (Your existing logic is fine)
            gpt_model_json = form_data.get('gpt_model_json', '')
            embedding_model_json = form_data.get('embedding_model_json', '')
            image_gen_model_json = form_data.get('image_gen_model_json', '')
            try:
                gpt_model_obj = json.loads(gpt_model_json) if gpt_model_json else {'selected': [], 'all': []}
            except Exception as e:
                print(f"Error parsing gpt_model_json: {e}")
                flash('Error parsing GPT model data. Changes may not be saved.', 'warning')
                log_event(f"Error parsing GPT model data: {e}", level=logging.ERROR)
                gpt_model_obj = settings.get('gpt_model', {'selected': [], 'all': []}) # Fallback
                
            try:
                embedding_model_obj = json.loads(embedding_model_json) if embedding_model_json else {'selected': [], 'all': []}
            except Exception as e:
                print(f"Error parsing embedding_model_json: {e}")
                flash('Error parsing Embedding model data. Changes may not be saved.', 'warning')
                log_event(f"Error parsing Embedding model data: {e}", level=logging.ERROR)
                embedding_model_obj = settings.get('embedding_model', {'selected': [], 'all': []}) # Fallback
            try:
                image_gen_model_obj = json.loads(image_gen_model_json) if image_gen_model_json else {'selected': [], 'all': []}
            except Exception as e:
                print(f"Error parsing image_gen_model_json: {e}")
                flash('Error parsing Image Gen model data. Changes may not be saved.', 'warning')
                log_event(f"Error parsing Image Gen model data: {e}", level=logging.ERROR)
                image_gen_model_obj = settings.get('image_gen_model', {'selected': [], 'all': []}) # Fallback

            requested_enable_multi_model_endpoints = form_data.get('enable_multi_model_endpoints') == 'on'
            model_endpoints_json = form_data.get('model_endpoints_json', '[]')
            existing_model_endpoints = settings.get('model_endpoints', []) or []
            parsed_model_endpoints = []
            try:
                parsed_model_endpoints_raw = json.loads(model_endpoints_json) if model_endpoints_json else []
                if isinstance(parsed_model_endpoints_raw, list):
                    parsed_model_endpoints = parsed_model_endpoints_raw
                else:
                    raise ValueError("Invalid format: model_endpoints must be a list.")
            except (json.JSONDecodeError, ValueError) as e:
                print(f"Error processing model_endpoints_json: {e}")
                flash(f"Error processing model endpoints: {e}. Changes for endpoints not saved.", 'danger')
                parsed_model_endpoints = settings.get('model_endpoints', [])

            existing_multi_endpoints_enabled = settings.get('enable_multi_model_endpoints', False)
            enable_multi_model_endpoints = coerce_multi_model_endpoint_enablement(
                existing_multi_endpoints_enabled,
                requested_enable_multi_model_endpoints,
            )
            should_migrate_endpoints = enable_multi_model_endpoints and not existing_multi_endpoints_enabled
            migration_notice = settings.get('multi_endpoint_migration_notice', {
                'enabled': False,
                'message': '',
                'created_at': None
            })
            migration_notice['enabled'] = False
            migration_notice['message'] = ''
            migrated_at = settings.get('multi_endpoint_migrated_at')

            if should_migrate_endpoints and not parsed_model_endpoints:
                default_endpoint_id = str(uuid.uuid4())
                migrated_models = []
                for model in gpt_model_obj.get('selected', []):
                    deployment_name = model.get('deploymentName') or model.get('deployment') or ''
                    model_name = model.get('modelName') or model.get('name') or ''
                    if not deployment_name:
                        continue
                    migrated_models.append({
                        'id': str(uuid.uuid4()),
                        'deploymentName': deployment_name,
                        'modelName': model_name,
                        'displayName': deployment_name,
                        'description': '',
                        'enabled': True
                    })

                legacy_auth_type = settings.get('azure_openai_gpt_authentication_type', 'key')
                migrated_auth_type = 'api_key' if legacy_auth_type == 'key' else legacy_auth_type

                parsed_model_endpoints = [{
                    'id': default_endpoint_id,
                    'name': 'Migrated Azure OpenAI Endpoint',
                    'provider': 'aoai',
                    'enabled': True,
                    'auth': {
                        'type': migrated_auth_type,
                        'managed_identity_type': 'system_assigned',
                        'managed_identity_client_id': '',
                        'tenant_id': '',
                        'client_id': '',
                        'client_secret': '',
                        'api_key': settings.get('azure_openai_gpt_key', '')
                    },
                    'connection': {
                        'endpoint': settings.get('azure_openai_gpt_endpoint', ''),
                        'api_version': settings.get('azure_openai_gpt_api_version', '')
                    },
                    'management': {
                        'subscription_id': settings.get('azure_openai_gpt_subscription_id', ''),
                        'resource_group': settings.get('azure_openai_gpt_resource_group', ''),
                        'location': ''
                    },
                    'models': migrated_models
                }]
                debug_print(f"Migrated {len(migrated_models)} models to new multi-endpoint configuration.")
                debug_print(
                    f"Migrated Model Endpoints: {json.dumps([redact_model_endpoint_secret_values(endpoint) for endpoint in parsed_model_endpoints], indent=2)}"
                )
                log_event(f"Migrated {len(migrated_models)} models to new multi-endpoint configuration.", level=logging.INFO)
                log_event(
                    f"Migrated Model Endpoints: {json.dumps([redact_model_endpoint_secret_values(endpoint) for endpoint in parsed_model_endpoints], indent=2)}",
                    level=logging.INFO,
                )
                log_general_admin_action(
                    admin_user_id=user_id,
                    admin_email=admin_email,
                    action='Enabled and migrated multi-model endpoints',
                    description=f'Migrated {len(migrated_models)} models to multi-endpoint configuration.'
                )


                migrated_at = datetime.now(timezone.utc).isoformat()
                migration_notice['created_at'] = migrated_at

            parsed_model_endpoints = merge_model_endpoints_with_existing(parsed_model_endpoints, existing_model_endpoints)
            parsed_model_endpoints, _ = normalize_model_endpoints(parsed_model_endpoints)

            existing_endpoints_by_id = {
                endpoint.get('id'): endpoint
                for endpoint in existing_model_endpoints
                if isinstance(endpoint, dict) and endpoint.get('id')
            }
            parsed_model_endpoints = [
                keyvault_model_endpoint_save_helper(
                    endpoint,
                    endpoint.get('id'),
                    scope='global',
                    existing_endpoint=existing_endpoints_by_id.get(endpoint.get('id')),
                )
                for endpoint in parsed_model_endpoints
            ]

            for endpoint in parsed_model_endpoints:
                if not isinstance(endpoint, dict):
                    continue
                endpoint_id = endpoint.get('id')
                if not endpoint_id:
                    continue
                keyvault_model_endpoint_cleanup_helper(
                    existing_endpoints_by_id.get(endpoint_id),
                    endpoint,
                    endpoint_id,
                    scope='global',
                )

            saved_endpoint_ids = {
                endpoint.get('id')
                for endpoint in parsed_model_endpoints
                if isinstance(endpoint, dict) and endpoint.get('id')
            }
            for endpoint in existing_model_endpoints:
                if not isinstance(endpoint, dict):
                    continue
                endpoint_id = endpoint.get('id')
                if endpoint_id and endpoint_id not in saved_endpoint_ids:
                    keyvault_model_endpoint_delete_helper(endpoint, endpoint_id, scope='global')

            default_model_selection_json = form_data.get('default_model_selection_json', '{}')
            parsed_default_model_selection = {}
            try:
                parsed_default_model_selection_raw = (
                    json.loads(default_model_selection_json) if default_model_selection_json else {}
                )
                if isinstance(parsed_default_model_selection_raw, dict):
                    parsed_default_model_selection = parsed_default_model_selection_raw
                else:
                    raise ValueError("Invalid format: default_model_selection must be an object.")
            except (json.JSONDecodeError, ValueError) as e:
                print(f"Error processing default_model_selection_json: {e}")
                flash(f"Error processing default model selection: {e}. Changes not saved.", 'danger')
                parsed_default_model_selection = settings.get('default_model_selection', {})

            normalized_default_model_selection = {
                'endpoint_id': str(parsed_default_model_selection.get('endpoint_id') or '').strip(),
                'model_id': str(parsed_default_model_selection.get('model_id') or '').strip(),
                'provider': str(parsed_default_model_selection.get('provider') or '').strip().lower()
            }

            if not enable_multi_model_endpoints:
                normalized_default_model_selection = {
                    'endpoint_id': '',
                    'model_id': '',
                    'provider': ''
                }
            elif normalized_default_model_selection['endpoint_id'] and normalized_default_model_selection['model_id']:
                endpoint_cfg = next(
                    (e for e in parsed_model_endpoints if e.get('id') == normalized_default_model_selection['endpoint_id']),
                    None
                )
                if not endpoint_cfg or not endpoint_cfg.get('enabled', True):
                    flash('Default model endpoint is not available. Please select a valid endpoint.', 'warning')
                    normalized_default_model_selection = {
                        'endpoint_id': '',
                        'model_id': '',
                        'provider': ''
                    }
                else:
                    models = endpoint_cfg.get('models', []) or []
                    model_cfg = next(
                        (m for m in models if m.get('id') == normalized_default_model_selection['model_id']),
                        None
                    )
                    if not model_cfg or not model_cfg.get('enabled', True):
                        flash('Default model is not available. Please select a valid model.', 'warning')
                        normalized_default_model_selection = {
                            'endpoint_id': '',
                            'model_id': '',
                            'provider': ''
                        }
                    else:
                        endpoint_provider = (endpoint_cfg.get('provider') or '').strip().lower()
                        if endpoint_provider:
                            normalized_default_model_selection['provider'] = endpoint_provider
            else:
                normalized_default_model_selection = {
                    'endpoint_id': '',
                    'model_id': '',
                    'provider': ''
                }

            metadata_selection_json = form_data.get('metadata_extraction_model_selection_json', '{}')
            parsed_metadata_model_selection = {}
            try:
                parsed_metadata_model_selection_raw = (
                    json.loads(metadata_selection_json) if metadata_selection_json else {}
                )
                if isinstance(parsed_metadata_model_selection_raw, dict):
                    parsed_metadata_model_selection = parsed_metadata_model_selection_raw
                else:
                    raise ValueError("Invalid format: metadata_extraction_model_selection must be an object.")
            except (json.JSONDecodeError, ValueError) as e:
                print(f"Error processing metadata_extraction_model_selection_json: {e}")
                flash(f"Error processing metadata extraction model selection: {e}. Changes not saved.", 'danger')
                parsed_metadata_model_selection = settings.get('metadata_extraction_model_selection', {})

            normalized_metadata_model_selection = {
                'endpoint_id': str(parsed_metadata_model_selection.get('endpoint_id') or '').strip(),
                'model_id': str(parsed_metadata_model_selection.get('model_id') or '').strip(),
                'provider': str(parsed_metadata_model_selection.get('provider') or '').strip().lower()
            }
            metadata_extraction_model_deployment = form_data.get('metadata_extraction_model', '').strip()

            if not enable_multi_model_endpoints:
                normalized_metadata_model_selection = {
                    'endpoint_id': '',
                    'model_id': '',
                    'provider': ''
                }
            elif normalized_metadata_model_selection['endpoint_id'] and normalized_metadata_model_selection['model_id']:
                endpoint_cfg = next(
                    (e for e in parsed_model_endpoints if e.get('id') == normalized_metadata_model_selection['endpoint_id']),
                    None
                )
                if not endpoint_cfg or not endpoint_cfg.get('enabled', True):
                    flash('Metadata extraction model endpoint is not available. Please select a valid endpoint.', 'warning')
                    normalized_metadata_model_selection = {
                        'endpoint_id': '',
                        'model_id': '',
                        'provider': ''
                    }
                else:
                    models = endpoint_cfg.get('models', []) or []
                    model_cfg = next(
                        (m for m in models if m.get('id') == normalized_metadata_model_selection['model_id']),
                        None
                    )
                    if not model_cfg or not model_cfg.get('enabled', True):
                        flash('Metadata extraction model is not available. Please select a valid model.', 'warning')
                        normalized_metadata_model_selection = {
                            'endpoint_id': '',
                            'model_id': '',
                            'provider': ''
                        }
                    else:
                        endpoint_provider = (endpoint_cfg.get('provider') or '').strip().lower()
                        if endpoint_provider:
                            normalized_metadata_model_selection['provider'] = endpoint_provider
                        metadata_extraction_model_deployment = str(
                            model_cfg.get('deploymentName')
                            or model_cfg.get('deployment')
                            or ''
                        ).strip()
            else:
                normalized_metadata_model_selection = {
                    'endpoint_id': '',
                    'model_id': '',
                    'provider': ''
                }

            # --- Extract banner fields from form_data ---
            classification_banner_enabled = form_data.get('classification_banner_enabled') == 'on'
            classification_banner_text = form_data.get('classification_banner_text', '').strip()
            classification_banner_color = form_data.get('classification_banner_color', '#ffc107').strip()
            classification_banner_text_color = form_data.get('classification_banner_text_color', '#ffffff').strip()

            agents_page_title = normalize_agents_page_text(
                form_data.get('agents_page_title'),
                AGENTS_PAGE_DEFAULTS['agents_page_title'],
                120,
            )
            agents_page_subtitle = normalize_agents_page_text(
                form_data.get('agents_page_subtitle'),
                AGENTS_PAGE_DEFAULTS['agents_page_subtitle'],
                240,
            )
            agents_page_hero_color_mode = normalize_agents_page_color_mode(
                form_data.get('agents_page_hero_color_mode')
            )
            agents_page_hero_primary_color = normalize_agents_page_color(
                form_data.get('agents_page_hero_primary_color'),
                AGENTS_PAGE_DEFAULTS['agents_page_hero_primary_color'],
            )
            agents_page_hero_secondary_color = normalize_agents_page_color(
                form_data.get('agents_page_hero_secondary_color'),
                AGENTS_PAGE_DEFAULTS['agents_page_hero_secondary_color'],
            )
            agents_page_disclaimer_markdown = normalize_agents_page_text(
                form_data.get('agents_page_disclaimer_markdown'),
                '',
                3000,
            )
            agents_page_show_instructions_in_details = form_data.get(
                'agents_page_show_instructions_in_details'
            ) == 'on'
            agents_page_promoted_popular_agents = normalize_agents_page_promoted_popular_agents(
                form_data.get('agents_page_promoted_popular_agents_json')
            )
            agents_page_promoted_popular_order = normalize_agents_page_promoted_popular_order(
                form_data.get('agents_page_promoted_popular_order')
            )
            agents_page_promoted_popular_tag_enabled = form_data.get(
                'agents_page_promoted_popular_tag_enabled'
            ) == 'on'
            agents_page_promoted_popular_tag_label = normalize_agents_page_promoted_popular_tag_label(
                form_data.get('agents_page_promoted_popular_tag_label')
            )

            # --- Application Insights Logging Toggle ---
            enable_appinsights_global_logging = form_data.get('enable_appinsights_global_logging') == 'on'
            
            # --- Debug Logging Toggle ---
            enable_debug_logging = form_data.get('enable_debug_logging') == 'on'
            
            # --- Debug Logging Timer Settings ---
            debug_logging_timer_enabled = form_data.get('enable_debug_logging_timer') == 'on'
            debug_timer_value = int(form_data.get('debug_timer_value', 1))
            debug_timer_unit = form_data.get('debug_timer_unit', 'hours')
            debug_logging_turnoff_time = None
            
            # Validate debug timer values
            timer_limits = {
                'minutes': (1, 120),
                'hours': (1, 24),
                'days': (1, 7),
                'weeks': (1, 52)
            }
            
            if debug_timer_unit in timer_limits:
                min_val, max_val = timer_limits[debug_timer_unit]
                if debug_timer_value < min_val or debug_timer_value > max_val:
                    debug_timer_value = min(max(debug_timer_value, min_val), max_val)
            
            # Get existing timer settings to check if they've changed
            existing_debug_timer_enabled = settings.get('debug_logging_timer_enabled', False)
            existing_debug_timer_value = settings.get('debug_timer_value', 1)
            existing_debug_timer_unit = settings.get('debug_timer_unit', 'hours')
            existing_debug_logging_enabled = settings.get('enable_debug_logging', False)
            existing_debug_turnoff_time = settings.get('debug_logging_turnoff_time')
            
            # Determine if timer settings have changed
            timer_settings_changed = (
                debug_logging_timer_enabled != existing_debug_timer_enabled or
                debug_timer_value != existing_debug_timer_value or
                debug_timer_unit != existing_debug_timer_unit
            )
            debug_logging_newly_enabled = enable_debug_logging and not existing_debug_logging_enabled
            
            # Calculate debug logging turnoff time if timer is enabled and debug logging is on
            if enable_debug_logging and debug_logging_timer_enabled:
                # Only recalculate turnoff time if:
                # 1. Timer settings have changed (value, unit, or enabled state), OR
                # 2. Debug logging was just enabled, OR
                # 3. No existing turnoff time exists
                if timer_settings_changed or debug_logging_newly_enabled or not existing_debug_turnoff_time:
                    now = datetime.now()
                    
                    if debug_timer_unit == 'minutes':
                        delta = timedelta(minutes=debug_timer_value)
                    elif debug_timer_unit == 'hours':
                        delta = timedelta(hours=debug_timer_value)
                    elif debug_timer_unit == 'days':
                        delta = timedelta(days=debug_timer_value)
                    elif debug_timer_unit == 'weeks':
                        delta = timedelta(weeks=debug_timer_value)
                    else:
                        delta = timedelta(hours=1)  # default fallback
                    
                    debug_logging_turnoff_time = now + delta
                    # Convert to ISO string for JSON serialization
                    debug_logging_turnoff_time_str = debug_logging_turnoff_time.isoformat()
                else:
                    # Preserve existing turnoff time
                    debug_logging_turnoff_time_str = existing_debug_turnoff_time
            else:
                debug_logging_turnoff_time_str = None

            # --- File Processing Logs Timer Settings ---
            file_processing_logs_timer_enabled = form_data.get('enable_file_processing_logs_timer') == 'on'
            file_timer_value = int(form_data.get('file_timer_value', 1))
            file_timer_unit = form_data.get('file_timer_unit', 'hours')
            file_processing_logs_turnoff_time = None
            enable_file_processing_logs = form_data.get('enable_file_processing_logs') == 'on'
            
            # Validate file timer values
            if file_timer_unit in timer_limits:
                min_val, max_val = timer_limits[file_timer_unit]
                if file_timer_value < min_val or file_timer_value > max_val:
                    file_timer_value = min(max(file_timer_value, min_val), max_val)
            
            # Get existing file timer settings to check if they've changed
            existing_file_timer_enabled = settings.get('file_processing_logs_timer_enabled', False)
            existing_file_timer_value = settings.get('file_timer_value', 1)
            existing_file_timer_unit = settings.get('file_timer_unit', 'hours')
            existing_file_processing_logs_enabled = settings.get('enable_file_processing_logs', False)
            existing_file_turnoff_time = settings.get('file_processing_logs_turnoff_time')
            
            # Determine if timer settings have changed
            file_timer_settings_changed = (
                file_processing_logs_timer_enabled != existing_file_timer_enabled or
                file_timer_value != existing_file_timer_value or
                file_timer_unit != existing_file_timer_unit
            )
            file_processing_logs_newly_enabled = enable_file_processing_logs and not existing_file_processing_logs_enabled
            
            # Calculate file processing logs turnoff time if timer is enabled and file processing logs are on
            if enable_file_processing_logs and file_processing_logs_timer_enabled:
                # Only recalculate turnoff time if:
                # 1. Timer settings have changed (value, unit, or enabled state), OR
                # 2. File processing logs was just enabled, OR
                # 3. No existing turnoff time exists
                if file_timer_settings_changed or file_processing_logs_newly_enabled or not existing_file_turnoff_time:
                    now = datetime.now()
                    
                    if file_timer_unit == 'minutes':
                        delta = timedelta(minutes=file_timer_value)
                    elif file_timer_unit == 'hours':
                        delta = timedelta(hours=file_timer_value)
                    elif file_timer_unit == 'days':
                        delta = timedelta(days=file_timer_value)
                    elif file_timer_unit == 'weeks':
                        delta = timedelta(weeks=file_timer_value)
                    else:
                        delta = timedelta(hours=1)  # default fallback
                    
                    file_processing_logs_turnoff_time = now + delta
                    # Convert to ISO string for JSON serialization
                    file_processing_logs_turnoff_time_str = file_processing_logs_turnoff_time.isoformat()
                else:
                    # Preserve existing turnoff time
                    file_processing_logs_turnoff_time_str = existing_file_turnoff_time
            else:
                file_processing_logs_turnoff_time_str = None

            # --- Retention Policy Settings ---
            enable_retention_policy_personal = form_data.get('enable_retention_policy_personal') == 'on'
            enable_retention_policy_group = form_data.get('enable_retention_policy_group') == 'on'
            enable_retention_policy_public = form_data.get('enable_retention_policy_public') == 'on'
            retention_policy_execution_hour = int(form_data.get('retention_policy_execution_hour', 2))
            
            # Default retention policy values for each workspace type
            default_retention_conversation_personal = form_data.get('default_retention_conversation_personal', 'none')
            default_retention_document_personal = form_data.get('default_retention_document_personal', 'none')
            default_retention_conversation_group = form_data.get('default_retention_conversation_group', 'none')
            default_retention_document_group = form_data.get('default_retention_document_group', 'none')
            default_retention_conversation_public = form_data.get('default_retention_conversation_public', 'none')
            default_retention_document_public = form_data.get('default_retention_document_public', 'none')
            
            # Validate execution hour (0-23)
            if retention_policy_execution_hour < 0 or retention_policy_execution_hour > 23:
                retention_policy_execution_hour = 2  # Default to 2 AM
            
            # Calculate next scheduled execution time if any retention policy is enabled
            retention_policy_next_run = None
            if enable_retention_policy_personal or enable_retention_policy_group or enable_retention_policy_public:
                now = datetime.now(timezone.utc)
                # Create next run datetime with the specified hour
                next_run = now.replace(hour=retention_policy_execution_hour, minute=0, second=0, microsecond=0)
                
                # If the scheduled time has already passed today, schedule for tomorrow
                if next_run <= now:
                    next_run = next_run + timedelta(days=1)
                
                retention_policy_next_run = next_run.isoformat()

            # --- User Agreement Settings ---
            enable_user_agreement = form_data.get('enable_user_agreement') == 'on'
            user_agreement_text = form_data.get('user_agreement_text', '').strip()
            enable_user_agreement_daily = form_data.get('enable_user_agreement_daily') == 'on'
            
            # Build apply_to list from checkboxes
            user_agreement_apply_to = []
            if form_data.get('user_agreement_apply_personal') == 'on':
                user_agreement_apply_to.append('personal')
            if form_data.get('user_agreement_apply_group') == 'on':
                user_agreement_apply_to.append('group')
            if form_data.get('user_agreement_apply_public') == 'on':
                user_agreement_apply_to.append('public')
            if form_data.get('user_agreement_apply_chat') == 'on':
                user_agreement_apply_to.append('chat')
            
            # Validate word count (max 200 words)
            if enable_user_agreement and user_agreement_text:
                word_count = len(user_agreement_text.split())
                if word_count > 200:
                    flash('User Agreement text exceeds 200 word limit. Please shorten the text.', 'warning')

            # --- Authentication & Redirect Settings ---
            enable_front_door = form_data.get('enable_front_door') == 'on'
            front_door_url = form_data.get('front_door_url', '').strip()
            
            # Validate Front Door URL if provided
            def is_valid_url(url):
                if not url:
                    return True  # Empty URL is valid (no redirect)
                import re
                url_pattern = re.compile(
                    r'^https?://'  # http:// or https://
                    r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
                    r'localhost|'  # localhost...
                    r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
                    r'(?::\d+)?'  # optional port
                    r'(?:/?|[/?]\S+)$', re.IGNORECASE)
                return url_pattern.match(url) is not None
            
            if front_door_url and not is_valid_url(front_door_url):
                flash('Invalid Front Door URL format. Please provide a valid HTTP/HTTPS URL.', 'danger')
                front_door_url = ''

            try:
                cosmos_throughput_container_policies = json.loads(
                    form_data.get('cosmos_throughput_container_policies_json') or '{}'
                )
                if not isinstance(cosmos_throughput_container_policies, dict):
                    cosmos_throughput_container_policies = {}
            except Exception:
                flash('Container throughput policies could not be parsed and were not updated.', 'warning')
                cosmos_throughput_container_policies = settings.get('cosmos_throughput_container_policies', {})

            cosmos_throughput_candidate_settings = {
                **settings,
                'cosmos_throughput_autoscale_enabled': form_data.get('cosmos_throughput_autoscale_enabled') == 'on',
                'cosmos_throughput_auto_scale_up_enabled': form_data.get('cosmos_throughput_auto_scale_up_enabled') == 'on',
                'cosmos_throughput_auto_scale_down_enabled': form_data.get('cosmos_throughput_auto_scale_down_enabled') == 'on',
                'cosmos_throughput_subscription_id': form_data.get('cosmos_throughput_subscription_id', '').strip(),
                'cosmos_throughput_resource_group': form_data.get('cosmos_throughput_resource_group', '').strip(),
                'cosmos_throughput_account_name': form_data.get('cosmos_throughput_account_name', '').strip(),
                'cosmos_throughput_database_name': form_data.get('cosmos_throughput_database_name', '').strip(),
                'cosmos_throughput_metrics_window_minutes': form_data.get('cosmos_throughput_metrics_window_minutes'),
                'cosmos_throughput_scale_up_threshold_percent': form_data.get('cosmos_throughput_scale_up_threshold_percent'),
                'cosmos_throughput_scale_down_threshold_percent': form_data.get('cosmos_throughput_scale_down_threshold_percent'),
                'cosmos_throughput_scale_up_step_ru': form_data.get('cosmos_throughput_scale_up_step_ru'),
                'cosmos_throughput_scale_down_step_ru': form_data.get('cosmos_throughput_scale_down_step_ru'),
                'cosmos_throughput_scale_up_cooldown_minutes': form_data.get('cosmos_throughput_scale_up_cooldown_minutes'),
                'cosmos_throughput_scale_down_cooldown_minutes': form_data.get('cosmos_throughput_scale_down_cooldown_minutes'),
                'cosmos_throughput_min_ru': form_data.get('cosmos_throughput_min_ru'),
                'cosmos_throughput_max_ru': form_data.get('cosmos_throughput_max_ru'),
                'cosmos_throughput_ignore_min_limit': form_data.get('cosmos_throughput_ignore_min_limit') == 'on',
                'cosmos_throughput_ignore_max_limit': form_data.get('cosmos_throughput_ignore_max_limit') == 'on',
                'cosmos_throughput_convert_manual_to_autoscale_enabled': form_data.get('cosmos_throughput_convert_manual_to_autoscale_enabled') == 'on',
                'cosmos_throughput_enforce_container_defaults': form_data.get('cosmos_throughput_enforce_container_defaults') == 'on',
                'cosmos_throughput_container_policies': cosmos_throughput_container_policies,
            }
            cosmos_throughput_validation_errors = validate_cosmos_throughput_policy_settings(
                cosmos_throughput_candidate_settings,
            )
            if cosmos_throughput_validation_errors:
                for validation_error in cosmos_throughput_validation_errors:
                    flash(validation_error, 'danger')
                return redirect(url_for('admin_settings'))

            cosmos_throughput_settings = normalize_cosmos_throughput_settings(cosmos_throughput_candidate_settings)

            # --- Chunk Size Overrides ---
            chunk_size_defaults = get_chunk_size_defaults()
            existing_chunk_sizes = settings.get('chunk_size', {}) if isinstance(settings, dict) else {}
            chunk_size_cap = get_chunk_size_cap(settings)
            enable_chunk_size_override = form_data.get('enable_chunk_size_override') == 'on'
            normalized_chunk_sizes = {}
            chunk_size_warning_keys = []

            for key, meta in chunk_size_defaults.items():
                field_name = f"chunk_size_{key}"
                incoming_raw = form_data.get(field_name, '')
                stored_meta = existing_chunk_sizes.get(key, {}) if isinstance(existing_chunk_sizes, dict) else {}

                try:
                    parsed_value = int(incoming_raw) if incoming_raw not in [None, ''] else int(stored_meta.get('value', meta.get('value', 1)))
                except Exception:
                    parsed_value = meta.get('value', 1)

                sanitized_value = max(1, parsed_value)
                if sanitized_value > chunk_size_cap:
                    chunk_size_warning_keys.append(key.upper())
                sanitized_value = min(sanitized_value, chunk_size_cap)

                normalized_chunk_sizes[key] = {
                    'value': sanitized_value,
                    'unit': stored_meta.get('unit', meta.get('unit', 'words'))
                }

            chunk_size_changed = (
                enable_chunk_size_override != settings.get('enable_chunk_size_override', False)
                or normalized_chunk_sizes != existing_chunk_sizes
            )

            if chunk_size_warning_keys:
                flash(
                    f"Chunk sizes capped at {chunk_size_cap} for: {', '.join(chunk_size_warning_keys)}.",
                    'warning'
                )

            document_intelligence_pdf_image_extraction_mode = normalize_document_intelligence_pdf_image_extraction_mode(
                form_data.get('document_intelligence_pdf_image_extraction_mode')
            )
            document_intelligence_auto_sample_pages = normalize_document_intelligence_auto_sample_pages(
                form_data.get('document_intelligence_auto_sample_pages')
            )

            # --- Construct new_settings Dictionary ---
            new_settings = {
                # Logging
                'enable_appinsights_global_logging': enable_appinsights_global_logging,
                'enable_debug_logging': enable_debug_logging,
                'debug_logging_timer_enabled': debug_logging_timer_enabled,
                'debug_timer_value': debug_timer_value,
                'debug_timer_unit': debug_timer_unit,
                'debug_logging_turnoff_time': debug_logging_turnoff_time_str,
                # General
                'app_title': app_title,
                'show_logo': form_data.get('show_logo') == 'on',
                'hide_app_title': form_data.get('hide_app_title') == 'on',
                'custom_logo_base64': settings.get('custom_logo_base64', ''),
                'logo_version': settings.get('logo_version', 1),
                'custom_logo_dark_base64': settings.get('custom_logo_dark_base64', ''),
                'logo_dark_version': settings.get('logo_dark_version', 1),
                'custom_favicon_base64': settings.get('custom_favicon_base64', ''),
                'favicon_version': settings.get('favicon_version', 1),
                'landing_page_text': form_data.get('landing_page_text', ''),
                'landing_page_alignment': form_data.get('landing_page_alignment', 'left'),
                'landing_page_logo_scale_percent': landing_page_logo_scale_percent,
                'enable_dark_mode_default': form_data.get('enable_dark_mode_default') == 'on',
                'enable_left_nav_default': form_data.get('enable_left_nav_default') == 'on',
                'release_notifications_registered': form_data.get('release_notifications_registered', 'false').lower() == 'true',
                'release_notifications_name': form_data.get('release_notifications_name', settings.get('release_notifications_name', '')).strip(),
                'release_notifications_email': form_data.get('release_notifications_email', settings.get('release_notifications_email', '')).strip(),
                'release_notifications_org': form_data.get('release_notifications_org', settings.get('release_notifications_org', '')).strip(),
                'release_notifications_registered_at': form_data.get('release_notifications_registered_at', settings.get('release_notifications_registered_at', '')).strip(),
                'release_notifications_updated_at': form_data.get('release_notifications_updated_at', settings.get('release_notifications_updated_at', '')).strip(),
                'enable_external_healthcheck': form_data.get('enable_external_healthcheck') == 'on',
                'enable_no_auth_external_healthcheck': form_data.get('enable_no_auth_external_healthcheck') == 'on',
                'enable_swagger': form_data.get('enable_swagger') == 'on',
                'enable_semantic_kernel': form_data.get('enable_semantic_kernel') == 'on',
                'per_user_semantic_kernel': form_data.get('per_user_semantic_kernel') == 'on',
                'enable_agent_template_gallery': form_data.get('enable_agent_template_gallery') == 'on',
                'agent_templates_allow_user_submission': form_data.get('agent_templates_allow_user_submission') == 'on',
                'agent_templates_require_approval': form_data.get('agent_templates_require_approval') == 'on',
                'agents_page_title': agents_page_title,
                'agents_page_subtitle': agents_page_subtitle,
                'agents_page_hero_color_mode': agents_page_hero_color_mode,
                'agents_page_hero_primary_color': agents_page_hero_primary_color,
                'agents_page_hero_secondary_color': agents_page_hero_secondary_color,
                'agents_page_disclaimer_markdown': agents_page_disclaimer_markdown,
                'agents_page_show_instructions_in_details': agents_page_show_instructions_in_details,
                'agents_page_promoted_popular_agents': agents_page_promoted_popular_agents,
                'agents_page_promoted_popular_order': agents_page_promoted_popular_order,
                'agents_page_promoted_popular_tag_enabled': agents_page_promoted_popular_tag_enabled,
                'agents_page_promoted_popular_tag_label': agents_page_promoted_popular_tag_label,
                'governance_user_endpoints': form_data.get('governance_user_endpoints') == 'on' and form_data.get('allow_user_custom_endpoints') == 'on',
                'governance_group_endpoints': form_data.get('governance_group_endpoints') == 'on' and form_data.get('allow_group_custom_endpoints') == 'on',
                'governance_global_endpoints': True,
                'governance_user_agents': form_data.get('governance_user_agents') == 'on' and form_data.get('allow_user_agents') == 'on',
                'governance_group_agents': form_data.get('governance_group_agents') == 'on' and form_data.get('allow_group_agents') == 'on',
                'governance_global_agents_usage': form_data.get('governance_global_agents_usage') == 'on' and form_data.get('enable_semantic_kernel') == 'on',
                'governance_user_actions': form_data.get('governance_user_actions') == 'on' and form_data.get('allow_user_plugins') == 'on',
                'governance_group_actions': form_data.get('governance_group_actions') == 'on' and form_data.get('allow_group_plugins') == 'on',
                'governance_global_actions_usage': form_data.get('governance_global_actions_usage') == 'on' and form_data.get('enable_semantic_kernel') == 'on',

                # GPT (Direct & APIM)
                'enable_gpt_apim': form_data.get('enable_gpt_apim') == 'on',
                'azure_openai_gpt_endpoint': form_data.get('azure_openai_gpt_endpoint', '').strip(),
                'azure_openai_gpt_api_version': form_data.get('azure_openai_gpt_api_version', '').strip(),
                'azure_openai_gpt_authentication_type': form_data.get('azure_openai_gpt_authentication_type', 'key'),
                'azure_openai_gpt_subscription_id': form_data.get('azure_openai_gpt_subscription_id', '').strip(),
                'azure_openai_gpt_resource_group': form_data.get('azure_openai_gpt_resource_group', '').strip(),
                'azure_openai_gpt_key': admin_secret('azure_openai_gpt_key'),
                'gpt_model': gpt_model_obj,
                'enable_multi_model_endpoints': enable_multi_model_endpoints,
                'model_endpoints': parsed_model_endpoints,
                'default_model_selection': normalized_default_model_selection,
                'multi_endpoint_migrated_at': migrated_at,
                'multi_endpoint_migration_notice': migration_notice,
                'azure_apim_gpt_endpoint': form_data.get('azure_apim_gpt_endpoint', '').strip(),
                'azure_apim_gpt_subscription_key': admin_secret('azure_apim_gpt_subscription_key'),
                'azure_apim_gpt_deployment': form_data.get('azure_apim_gpt_deployment', '').strip(),
                'azure_apim_gpt_api_version': form_data.get('azure_apim_gpt_api_version', '').strip(),

                # Embeddings (Direct & APIM)
                'enable_embedding_apim': form_data.get('enable_embedding_apim') == 'on',
                'azure_openai_embedding_endpoint': form_data.get('azure_openai_embedding_endpoint', '').strip(),
                'azure_openai_embedding_api_version': form_data.get('azure_openai_embedding_api_version', '').strip(),
                'azure_openai_embedding_authentication_type': form_data.get('azure_openai_embedding_authentication_type', 'key'),
                'azure_openai_embedding_subscription_id': form_data.get('azure_openai_embedding_subscription_id', '').strip(),
                'azure_openai_embedding_resource_group': form_data.get('azure_openai_embedding_resource_group', '').strip(),
                'azure_openai_embedding_key': admin_secret('azure_openai_embedding_key'),
                'embedding_model': embedding_model_obj,
                'azure_apim_embedding_endpoint': form_data.get('azure_apim_embedding_endpoint', '').strip(),
                'azure_apim_embedding_subscription_key': admin_secret('azure_apim_embedding_subscription_key'),
                'azure_apim_embedding_deployment': form_data.get('azure_apim_embedding_deployment', '').strip(),
                'azure_apim_embedding_api_version': form_data.get('azure_apim_embedding_api_version', '').strip(),

                # Image Gen (Direct & APIM)
                'enable_image_generation': form_data.get('enable_image_generation') == 'on',
                'enable_image_gen_apim': form_data.get('enable_image_gen_apim') == 'on',
                'azure_openai_image_gen_endpoint': form_data.get('azure_openai_image_gen_endpoint', '').strip(),
                'azure_openai_image_gen_api_version': form_data.get('azure_openai_image_gen_api_version', '').strip(),
                'azure_openai_image_gen_authentication_type': form_data.get('azure_openai_image_gen_authentication_type', 'key'),
                'azure_openai_image_gen_subscription_id': form_data.get('azure_openai_image_gen_subscription_id', '').strip(),
                'azure_openai_image_gen_resource_group': form_data.get('azure_openai_image_gen_resource_group', '').strip(),
                'azure_openai_image_gen_key': admin_secret('azure_openai_image_gen_key'),
                'image_gen_model': image_gen_model_obj,
                'azure_apim_image_gen_endpoint': form_data.get('azure_apim_image_gen_endpoint', '').strip(),
                'azure_apim_image_gen_subscription_key': admin_secret('azure_apim_image_gen_subscription_key'),
                'azure_apim_image_gen_deployment': form_data.get('azure_apim_image_gen_deployment', '').strip(),
                'azure_apim_image_gen_api_version': form_data.get('azure_apim_image_gen_api_version', '').strip(),

                # Redis Cache
                'enable_redis_cache': form_data.get('enable_redis_cache') == 'on',
                'redis_url': form_data.get('redis_url', '').strip(),
                'redis_key': admin_secret('redis_key'),
                'redis_auth_type': form_data.get('redis_auth_type', '').strip(),

                # Workspaces
                'enable_user_workspace': form_data.get('enable_user_workspace') == 'on',
                'enable_group_workspaces': form_data.get('enable_group_workspaces') == 'on',
                # disable_group_creation is inverted: when checked (on), enable_group_creation = False
                'enable_group_creation': form_data.get('disable_group_creation') != 'on',
                'enable_public_workspaces': form_data.get('enable_public_workspaces') == 'on',
                'enable_file_sharing': form_data.get('enable_file_sharing') == 'on',
                'enable_chat_file_uploads': form_data.get('enable_chat_file_uploads') == 'on',
                'require_member_of_chat_file_upload_user': require_member_of_chat_file_upload_user,
                'allow_user_workflows': form_data.get('allow_user_workflows') == 'on',
                'require_member_of_workflow_user': require_member_of_workflow_user,
                'allow_group_workflows': form_data.get('allow_group_workflows') == 'on',
                'require_group_assignment_for_group_workflows': form_data.get('require_group_assignment_for_group_workflows') == 'on',
                'group_workflow_allowed_group_ids': group_workflow_allowed_group_ids,
                'workflow_max_auto_invoke_attempts': workflow_max_auto_invoke_attempts,
                'allow_personal_workspace_file_downloads': form_data.get('allow_personal_workspace_file_downloads') == 'on',
                'allow_group_workspace_file_downloads': form_data.get('allow_group_workspace_file_downloads') == 'on',
                'require_group_assignment_for_file_downloads': form_data.get('require_group_assignment_for_file_downloads') == 'on',
                'file_download_allowed_group_ids': file_download_allowed_group_ids,
                'allow_public_workspace_file_downloads': form_data.get('allow_public_workspace_file_downloads') == 'on',
                'require_public_workspace_assignment_for_file_downloads': form_data.get('require_public_workspace_assignment_for_file_downloads') == 'on',
                'file_download_allowed_public_workspace_ids': file_download_allowed_public_workspace_ids,
                'enforce_workspace_scope_lock': form_data.get('enforce_workspace_scope_lock') == 'on',
                'enable_file_sync': requested_enable_file_sync,
                'enable_file_sync_personal': file_sync_settings['enable_file_sync_personal'],
                'enable_file_sync_group': file_sync_settings['enable_file_sync_group'],
                'enable_file_sync_public': file_sync_settings['enable_file_sync_public'],
                'file_sync_personal_require_app_role': file_sync_settings['file_sync_personal_require_app_role'],
                'require_group_assignment_for_file_sync': file_sync_settings['require_group_assignment_for_file_sync'],
                'file_sync_allowed_group_ids': file_sync_settings['file_sync_allowed_group_ids'],
                'require_public_workspace_assignment_for_file_sync': file_sync_settings['require_public_workspace_assignment_for_file_sync'],
                'file_sync_allowed_public_workspace_ids': file_sync_settings['file_sync_allowed_public_workspace_ids'],
                'file_sync_personal_admin_only': file_sync_settings['file_sync_personal_admin_only'],
                'file_sync_group_admin_only': file_sync_settings['file_sync_group_admin_only'],
                'file_sync_public_admin_only': file_sync_settings['file_sync_public_admin_only'],
                'file_sync_visible_source_types': file_sync_settings['file_sync_visible_source_types'],
                'file_sync_max_sources_per_scope': file_sync_settings['file_sync_max_sources_per_scope'],
                'file_sync_min_schedule_interval_minutes': file_sync_settings['file_sync_min_schedule_interval_minutes'],
                'file_sync_max_files_per_run': file_sync_settings['file_sync_max_files_per_run'],
                'file_sync_max_bytes_per_run': file_sync_settings['file_sync_max_bytes_per_run'],
                'file_sync_max_concurrent_runs': file_sync_settings['file_sync_max_concurrent_runs'],
                'file_sync_allow_recursive_sources': file_sync_settings['file_sync_allow_recursive_sources'],
                'file_sync_default_remote_delete_policy': file_sync_settings['file_sync_default_remote_delete_policy'],
                'enable_file_processing_logs': enable_file_processing_logs,
                'file_processing_logs_timer_enabled': file_processing_logs_timer_enabled,
                'file_timer_value': file_timer_value,
                'file_timer_unit': file_timer_unit,
                'file_processing_logs_turnoff_time': file_processing_logs_turnoff_time_str,
                'require_member_of_create_group': require_member_of_create_group,
                'require_owner_for_group_agent_management': require_owner_for_group_agent_management,
                'require_member_of_create_public_workspace': require_member_of_create_public_workspace,
                
                # Retention Policy
                'enable_retention_policy_personal': enable_retention_policy_personal,
                'enable_retention_policy_group': enable_retention_policy_group,
                'enable_retention_policy_public': enable_retention_policy_public,
                'retention_policy_execution_hour': retention_policy_execution_hour,
                'retention_policy_next_run': retention_policy_next_run,
                'default_retention_conversation_personal': default_retention_conversation_personal,
                'default_retention_document_personal': default_retention_document_personal,
                'default_retention_conversation_group': default_retention_conversation_group,
                'default_retention_document_group': default_retention_document_group,
                'default_retention_conversation_public': default_retention_conversation_public,
                'default_retention_document_public': default_retention_document_public,

                # User Agreement
                'enable_user_agreement': enable_user_agreement,
                'user_agreement_text': user_agreement_text,
                'user_agreement_apply_to': user_agreement_apply_to,
                'enable_user_agreement_daily': enable_user_agreement_daily,

                # Multimedia & Metadata
                'enable_video_file_support': enable_video_file_support,
                'enable_audio_file_support': enable_audio_file_support,
                'enable_extract_meta_data': enable_extract_meta_data,
                'enable_summarize_content_history_for_search': form_data.get('enable_summarize_content_history_for_search') == 'on',
                'enable_summarize_content_history_beyond_conversation_history_limit': form_data.get('enable_summarize_content_history_beyond_conversation_history_limit') == 'on',
                'number_of_historical_messages_to_summarize': int(form_data.get('number_of_historical_messages_to_summarize', 10)),
                
                # *** Document Classification ***
                'enable_document_classification': enable_document_classification,
                'document_classification_categories': parsed_categories, # Store the PARSED LIST

                # *** External Links ***
                'enable_external_links': enable_external_links,
                'external_links_menu_name': external_links_menu_name,
                'external_links_force_menu': external_links_force_menu,
                'external_links': parsed_external_links, # Store the PARSED LIST

                # *** Custom Pages ***
                'enable_custom_pages': enable_custom_pages,
                'custom_pages_menu_name': custom_pages_menu_name,
                'custom_pages_force_menu': custom_pages_force_menu,
                'access_request_button_enabled': bool(settings.get('access_request_button_enabled', False)),
                'access_request_button_text': settings.get('access_request_button_text', 'Request Access'),
                'access_request_page_url': settings.get('access_request_page_url', '/custom/request-access'),

                # *** Support Menu ***
                'enable_support_menu': enable_support_menu,
                'support_menu_name': support_menu_name,
                'enable_support_send_feedback': enable_support_send_feedback,
                'support_feedback_recipient_email': support_feedback_recipient_email,
                'enable_support_latest_features': enable_support_latest_features,
                'enable_support_latest_feature_documentation_links': enable_support_latest_feature_documentation_links,
                'support_latest_features_visibility': support_latest_features_visibility,
                'document_action_capabilities': document_action_capabilities,

                # Enhanced Citations
                'enable_enhanced_citations': enable_enhanced_citations,
                'enable_enhanced_citations_mount': form_data.get('enable_enhanced_citations_mount') == 'on' and enable_enhanced_citations,
                'enhanced_citations_mount': form_data.get('enhanced_citations_mount', '/view_documents').strip(),
                'tabular_preview_max_blob_size_mb': int(form_data.get('tabular_preview_max_blob_size_mb', 200)),
                'office_docs_storage_account_blob_endpoint': admin_secret('office_docs_storage_account_blob_endpoint'),
                'office_docs_storage_account_url': admin_secret('office_docs_storage_account_url'),
                'office_docs_authentication_type': form_data.get('office_docs_authentication_type', 'key'),
                'office_docs_key': form_data.get('office_docs_key', '').strip(),
                'video_files_storage_account_url': admin_secret('video_files_storage_account_url'),
                'video_files_authentication_type': form_data.get('video_files_authentication_type', 'key'),
                'video_files_key': form_data.get('video_files_key', '').strip(),
                'audio_files_storage_account_url': admin_secret('audio_files_storage_account_url'),
                'audio_files_authentication_type': form_data.get('audio_files_authentication_type', 'key'),
                'audio_files_key': form_data.get('audio_files_key', '').strip(),

                # Safety (Content Safety Direct & APIM)
                'enable_content_safety': form_data.get('enable_content_safety') == 'on',
                'content_safety_endpoint': form_data.get('content_safety_endpoint', '').strip(),
                'content_safety_key': admin_secret('content_safety_key'),
                'content_safety_authentication_type': form_data.get('content_safety_authentication_type', 'key'),
                'enable_content_safety_apim': form_data.get('enable_content_safety_apim') == 'on',
                'azure_apim_content_safety_endpoint': form_data.get('azure_apim_content_safety_endpoint', '').strip(),
                'azure_apim_content_safety_subscription_key': admin_secret('azure_apim_content_safety_subscription_key'),
                'require_member_of_safety_violation_admin': require_member_of_safety_violation_admin, # ADDED
                'require_member_of_feedback_admin': require_member_of_feedback_admin, # ADDED

                # Feedback, Archiving & Thoughts
                'enable_user_feedback': form_data.get('enable_user_feedback') == 'on',
                'enable_conversation_archiving': form_data.get('enable_conversation_archiving') == 'on',
                'enable_thoughts': form_data.get('enable_thoughts') == 'on',

                # Search (Web Search via Azure AI Foundry agent)
                'enable_web_search': enable_web_search,
                'web_search_consent_accepted': web_search_consent_accepted,
                'enable_web_search_user_notice': form_data.get('enable_web_search_user_notice') == 'on',
                'web_search_user_notice_text': form_data.get('web_search_user_notice_text', 'Your current message will be sent to Microsoft Bing for web search. Conversation history is not sent for web search, but any sensitive content you paste into this message may be sent.').strip(),
                'web_search_agent': {
                    'agent_type': 'aifoundry',
                    'azure_openai_gpt_endpoint': form_data.get('web_search_foundry_endpoint', '').strip(),
                    'azure_openai_gpt_api_version': form_data.get('web_search_foundry_api_version', '').strip(),
                    'azure_openai_gpt_deployment': '',
                    'other_settings': {
                        'azure_ai_foundry': {
                            'agent_id': form_data.get('web_search_foundry_agent_id', '').strip(),
                            'endpoint': form_data.get('web_search_foundry_endpoint', '').strip(),
                            'api_version': form_data.get('web_search_foundry_api_version', '').strip(),
                            'authentication_type': form_data.get('web_search_foundry_auth_type', 'managed_identity').strip(),
                            'managed_identity_type': form_data.get('web_search_foundry_managed_identity_type', 'system_assigned').strip(),
                            'managed_identity_client_id': form_data.get('web_search_foundry_managed_identity_client_id', '').strip(),
                            'tenant_id': form_data.get('web_search_foundry_tenant_id', '').strip(),
                            'client_id': form_data.get('web_search_foundry_client_id', '').strip(),
                            'client_secret': admin_secret(
                                'web_search_agent.other_settings.azure_ai_foundry.client_secret',
                                'web_search_foundry_client_secret'
                            ),
                            'cloud': form_data.get('web_search_foundry_cloud', '').strip(),
                            'authority': form_data.get('web_search_foundry_authority', '').strip(),
                            'notes': form_data.get('web_search_foundry_notes', '').strip()
                        }
                    }
                },

                # Search (URL Access and Source Review)
                'enable_url_access': source_review_settings['enable_url_access'],
                'url_access_max_chat_urls_per_turn': source_review_settings['url_access_max_chat_urls_per_turn'],
                'url_access_max_workflow_urls_per_run': source_review_settings['url_access_max_workflow_urls_per_run'],
                'url_access_allowed_domains': source_review_settings['url_access_allowed_domains'],
                'url_access_blocked_domains': source_review_settings['url_access_blocked_domains'],
                'require_member_of_url_access_user': source_review_settings['require_member_of_url_access_user'],
                'enable_source_review': source_review_settings['enable_source_review'],
                'require_member_of_deep_research_user': source_review_settings['require_member_of_deep_research_user'],
                'source_review_allow_internal_hosts': source_review_settings['source_review_allow_internal_hosts'],
                'enable_deep_source_review': source_review_settings['enable_deep_source_review'],
                'source_review_default_mode': source_review_settings['source_review_default_mode'],
                'source_review_max_pages_per_turn': source_review_settings['source_review_max_pages_per_turn'],
                'source_review_max_seed_pages_per_turn': source_review_settings['source_review_max_seed_pages_per_turn'],
                'source_review_max_depth': source_review_settings['source_review_max_depth'],
                'source_review_timeout_seconds': source_review_settings['source_review_timeout_seconds'],
                'source_review_max_redirects': source_review_settings['source_review_max_redirects'],
                'source_review_max_bytes_per_page': source_review_settings['source_review_max_bytes_per_page'],
                'deep_research_max_user_urls_per_turn': source_review_settings['deep_research_max_user_urls_per_turn'],
                'deep_research_max_search_queries_per_turn': source_review_settings['deep_research_max_search_queries_per_turn'],
                'deep_research_enable_query_planning': source_review_settings['deep_research_enable_query_planning'],
                'deep_research_enable_ledger_artifact': source_review_settings['deep_research_enable_ledger_artifact'],
                'source_review_enable_llm_planning': source_review_settings['source_review_enable_llm_planning'],
                'source_review_allow_js_rendering': source_review_settings['source_review_allow_js_rendering'],
                'source_review_js_load_more_clicks': source_review_settings['source_review_js_load_more_clicks'],
                'source_review_respect_robots_txt': source_review_settings['source_review_respect_robots_txt'],
                'source_review_allowed_domains': source_review_settings['source_review_allowed_domains'],
                'source_review_blocked_domains': source_review_settings['source_review_blocked_domains'],
                'source_review_allowed_users': source_review_settings['source_review_allowed_users'],
                'source_review_blocked_users': source_review_settings['source_review_blocked_users'],
                'source_review_audit_logging': source_review_settings['source_review_audit_logging'],

                # Search (AI Search Direct & APIM)
                'azure_ai_search_endpoint': form_data.get('azure_ai_search_endpoint', '').strip(),
                'azure_ai_search_key': admin_secret('azure_ai_search_key'),
                'azure_ai_search_authentication_type': form_data.get('azure_ai_search_authentication_type', 'key'),
                'enable_ai_search_apim': form_data.get('enable_ai_search_apim') == 'on',
                'azure_apim_ai_search_endpoint': form_data.get('azure_apim_ai_search_endpoint', '').strip(),
                'azure_apim_ai_search_subscription_key': admin_secret('azure_apim_ai_search_subscription_key'),
                'enable_chunk_size_override': enable_chunk_size_override,
                'chunk_size': normalized_chunk_sizes,

                # Extract (Doc Intelligence Direct & APIM)
                'azure_document_intelligence_endpoint': form_data.get('azure_document_intelligence_endpoint', '').strip(),
                'azure_document_intelligence_key': admin_secret('azure_document_intelligence_key'),
                'azure_document_intelligence_authentication_type': form_data.get('azure_document_intelligence_authentication_type', 'key'),
                'document_intelligence_pdf_image_extraction_mode': document_intelligence_pdf_image_extraction_mode,
                'document_intelligence_auto_sample_pages': document_intelligence_auto_sample_pages,
                'enable_document_intelligence_apim': form_data.get('enable_document_intelligence_apim') == 'on',
                'azure_apim_document_intelligence_endpoint': form_data.get('azure_apim_document_intelligence_endpoint', '').strip(),
                'azure_apim_document_intelligence_subscription_key': admin_secret('azure_apim_document_intelligence_subscription_key'),

                'enable_key_vault_secret_storage': form_data.get('enable_key_vault_secret_storage') == 'on',
                'key_vault_name': form_data.get('key_vault_name', '').strip(),
                'key_vault_identity': form_data.get('key_vault_identity', ''),

                # Authentication & Redirect Settings
                'enable_front_door': enable_front_door,
                'front_door_url': front_door_url,

                # Other
                'max_file_size_mb': max_file_size_mb,
                'conversation_history_limit': conversation_history_limit,
                'enable_idle_timeout': enable_idle_timeout,
                'idle_timeout_minutes': idle_timeout_minutes,
                'idle_warning_minutes': idle_warning_minutes,
                'idle_warning_message': idle_warning_message,
                'default_system_prompt': form_data.get('default_system_prompt', '').strip(),
                'access_denied_message': form_data.get('access_denied_message', settings.get('access_denied_message', '')).strip(),

                # Video file settings with Azure Video Indexer Settings
                'video_indexer_endpoint': form_data.get('video_indexer_endpoint', video_indexer_endpoint).strip(),
                'video_indexer_location': form_data.get('video_indexer_location', '').strip(),
                'video_indexer_account_id': form_data.get('video_indexer_account_id', '').strip(),
                'video_indexer_resource_group': form_data.get('video_indexer_resource_group', '').strip(),
                'video_indexer_subscription_id': form_data.get('video_indexer_subscription_id', '').strip(),
                'video_indexer_account_name': form_data.get('video_indexer_account_name', '').strip(),
                'video_indexer_arm_api_version': form_data.get('video_indexer_arm_api_version', DEFAULT_VIDEO_INDEXER_ARM_API_VERSION).strip(),
                'video_index_timeout': int(form_data.get('video_index_timeout', 600)),

                # Audio file settings with Azure speech service
                'speech_service_endpoint': form_data.get('speech_service_endpoint', '').strip(),
                'speech_service_location': form_data.get('speech_service_location', '').strip(),
                'speech_service_subscription_id': form_data.get('speech_service_subscription_id', '').strip(),
                'speech_service_resource_group': form_data.get('speech_service_resource_group', '').strip(),
                'speech_service_resource_name': form_data.get('speech_service_resource_name', '').strip(),
                'speech_service_resource_id': form_data.get('speech_service_resource_id', '').strip(),
                'speech_service_locale': form_data.get('speech_service_locale', '').strip(),
                'speech_service_authentication_type': form_data.get('speech_service_authentication_type', 'key'),
                'speech_service_key': admin_secret('speech_service_key'),
                
                # Speech-to-text chat input
                'enable_speech_to_text_input': form_data.get('enable_speech_to_text_input') == 'on',
                
                # Text-to-speech chat output
                'enable_text_to_speech': form_data.get('enable_text_to_speech') == 'on',

                'metadata_extraction_model': metadata_extraction_model_deployment,
                'metadata_extraction_model_selection': normalized_metadata_model_selection,

                # Multi-modal vision settings
                'enable_multimodal_vision': form_data.get('enable_multimodal_vision') == 'on',
                'multimodal_vision_model': form_data.get('multimodal_vision_model', '').strip(),

                # --- Banner fields ---
                'classification_banner_enabled': classification_banner_enabled,
                'classification_banner_text': classification_banner_text,
                'classification_banner_color': classification_banner_color,
                'classification_banner_text_color': classification_banner_text_color,

                'require_member_of_control_center_admin': require_member_of_control_center_admin,
                'require_member_of_control_center_dashboard_reader': require_member_of_control_center_dashboard_reader,
                'control_center_auto_refresh_enabled': control_center_auto_refresh_enabled,
                'control_center_auto_refresh_time': control_center_auto_refresh_schedule['time'],
                'control_center_auto_refresh_hour': control_center_auto_refresh_schedule['hour'],
                'control_center_auto_refresh_minute': control_center_auto_refresh_schedule['minute'],
                'control_center_auto_refresh_next_run': control_center_auto_refresh_next_run,
            }
            
            # --- Prevent Legacy Fields from Being Created/Updated ---
            # Remove semantic_kernel_agents and semantic_kernel_plugins if they somehow got added
            if 'semantic_kernel_agents' in new_settings:
                del new_settings['semantic_kernel_agents']
            if 'semantic_kernel_plugins' in new_settings:
                del new_settings['semantic_kernel_plugins']

            new_settings.update({
                key: cosmos_throughput_settings[key]
                for key in get_cosmos_throughput_setting_keys()
            })

            # Remove legacy web search keys if present
            for legacy_key in [
                'bing_search_key',
                'enable_web_search_apim',
                'azure_apim_web_search_endpoint',
                'azure_apim_web_search_subscription_key'
            ]:
                if legacy_key in new_settings:
                    del new_settings[legacy_key]
            
            logo_file = request.files.get('logo_file')
            if logo_file and allowed_file(logo_file.filename, ALLOWED_EXTENSIONS_IMG):
                try:
                    # 1) Read file fully into memory:
                    file_bytes = logo_file.read()
                    add_file_task_to_file_processing_log(
                        document_id='Image_Upload', # Placeholder if needed
                        user_id='New_image',
                        content=f"Logo file uploaded: {logo_file.filename}"
                    )

                    processed_logo = prepare_logo_image_for_storage(file_bytes, logo_file.filename)

                    add_file_task_to_file_processing_log(
                        document_id='Image_Upload', # Placeholder if needed
                        user_id='New_image',
                        content=(
                            f"Prepared logo asset: {logo_file.filename} "
                            f"(format: {processed_logo['detected_format']}, "
                            f"original size: {processed_logo['original_size']}, "
                            f"stored size: {processed_logo['stored_size']}, "
                            f"png bytes: {len(processed_logo['png_data'])})"
                        )
                    )

                    # ****** CHANGE HERE: Update only on success *****
                    new_settings['custom_logo_base64'] = processed_logo['base64_str']

                    current_version = settings.get('logo_version', 1) # Get version from settings loaded at start
                    new_settings['logo_version'] = current_version + 1 # Increment
                    new_logo_processed = True


                except Exception as e:
                    print(f"Error processing logo file: {e}") # Log the error for debugging
                    flash(f"Error processing logo file: {e}. Existing logo preserved.", "danger")
                    log_event(f"Error processing logo file: {e}", level=logging.ERROR)

            # Process dark mode logo file upload
            logo_dark_file = request.files.get('logo_dark_file')
            new_dark_logo_processed = False
            if logo_dark_file and allowed_file(logo_dark_file.filename, ALLOWED_EXTENSIONS_IMG):
                try:
                    # 1) Read file fully into memory:
                    file_bytes = logo_dark_file.read()
                    add_file_task_to_file_processing_log(
                        document_id='Image_Upload', # Placeholder if needed
                        user_id='New_image',
                        content=f"Dark mode logo file uploaded: {logo_dark_file.filename}"
                    )

                    processed_dark_logo = prepare_logo_image_for_storage(file_bytes, logo_dark_file.filename)

                    add_file_task_to_file_processing_log(
                        document_id='Image_Upload', # Placeholder if needed
                        user_id='New_image',
                        content=(
                            f"Prepared dark mode logo asset: {logo_dark_file.filename} "
                            f"(format: {processed_dark_logo['detected_format']}, "
                            f"original size: {processed_dark_logo['original_size']}, "
                            f"stored size: {processed_dark_logo['stored_size']}, "
                            f"png bytes: {len(processed_dark_logo['png_data'])})"
                        )
                    )

                    # ****** CHANGE HERE: Update only on success *****
                    new_settings['custom_logo_dark_base64'] = processed_dark_logo['base64_str']

                    current_version = settings.get('logo_dark_version', 1) # Get version from settings loaded at start
                    new_settings['logo_dark_version'] = current_version + 1 # Increment
                    new_dark_logo_processed = True


                except Exception as e:
                    print(f"Error processing dark mode logo file: {e}") # Log the error for debugging
                    flash(f"Error processing dark mode logo file: {e}. Existing dark mode logo preserved.", "danger")
                    log_event(f"Error processing dark mode logo file: {e}", level=logging.ERROR)

            # Process favicon file upload
            favicon_file = request.files.get('favicon_file')
            if favicon_file and allowed_file(favicon_file.filename, ALLOWED_EXTENSIONS_IMG):
                try:
                    # 1) Read file fully into memory:
                    file_bytes = favicon_file.read()
                    add_file_task_to_file_processing_log(
                        document_id='Image_Upload', # Placeholder if needed
                        user_id='New_image',
                        content=f"Favicon file uploaded: {favicon_file.filename}"
                    )

                    # 2) Load into Pillow from the original bytes for processing
                    img, detected_format = open_allowed_uploaded_image(file_bytes, favicon_file.filename)
                    
                    add_file_task_to_file_processing_log(
                        document_id='Image_Upload', # Placeholder if needed
                        user_id='New_image',
                        content=f"Loaded favicon image for processing: {favicon_file.filename} (format: {detected_format})"
                    )

                    # 3) Ensure image mode is compatible (e.g., convert palette modes)
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    elif img.mode != 'RGB' and img.mode != 'RGBA':
                         img = img.convert('RGB')

                    add_file_task_to_file_processing_log(
                        document_id='Image_Upload', # Placeholder if needed
                        user_id='New_image',
                        content=f"Converted favicon image mode for processing: {favicon_file.filename} (mode: {img.mode})"
                    )

                    # 4) Resize to appropriate favicon size (16x16 or 32x32)
                    img = img.resize((32, 32), Image.Resampling.LANCZOS)

                    add_file_task_to_file_processing_log(
                        document_id='Image_Upload', # Placeholder if needed
                        user_id='New_image',
                        content=f"Resized favicon image for processing: {favicon_file.filename} (new size: {img.size})"
                    )

                    # 5) Convert to ICO in-memory
                    img_bytes_io = BytesIO()
                    img.save(img_bytes_io, format='ICO')
                    ico_data = img_bytes_io.getvalue()

                    add_file_task_to_file_processing_log(
                        document_id='Image_Upload', # Placeholder if needed
                        user_id='New_image',
                        content=f"Converted favicon image to ICO for processing: {favicon_file.filename}"
                    )

                    # 6) Turn to base64
                    base64_str = base64.b64encode(ico_data).decode('utf-8')

                    add_file_task_to_file_processing_log(
                        document_id='Image_Upload', # Placeholder if needed
                        user_id='New_image',
                        content=f"Converted favicon image to base64 for processing: {base64_str}"
                    )

                    # Update only on success
                    new_settings['custom_favicon_base64'] = base64_str

                    current_version = settings.get('favicon_version', 1) # Get version from settings loaded at start
                    new_settings['favicon_version'] = current_version + 1 # Increment

                except Exception as e:
                    print(f"Error processing favicon file: {e}") # Log the error for debugging
                    flash(f"Error processing favicon file: {e}. Existing favicon preserved.", "danger")
                    log_event(f"Error processing favicon file: {e}", level=logging.ERROR)

            governance_toggle_keys = [
                'governance_user_endpoints',
                'governance_group_endpoints',
                'governance_global_endpoints',
                'governance_user_agents',
                'governance_group_agents',
                'governance_global_agents_usage',
                'governance_user_actions',
                'governance_group_actions',
                'governance_global_actions_usage',
            ]
            governance_toggle_changes = {}
            for toggle_key in governance_toggle_keys:
                before_value = bool(settings.get(toggle_key, False))
                after_value = bool(new_settings.get(toggle_key, False))
                if before_value != after_value:
                    governance_toggle_changes[toggle_key] = {
                        'before': before_value,
                        'after': after_value,
                    }

            # --- Update settings in DB ---
            # new_settings now contains either the new logo/favicon base64 or the original ones
            if update_settings(new_settings):
                flash("Admin settings updated successfully.", "success")
                if enable_custom_pages and not custom_pages_was_enabled and custom_pages_restart_acknowledged:
                    log_general_admin_action(
                        admin_user_id=user_id,
                        admin_email=admin_email,
                        action='custom_pages_enabled_acknowledged',
                        description='Custom Pages enabled after restart acknowledgement.',
                        additional_context={
                            'feature': 'custom_pages',
                            'enabled': True,
                            'restart_required': True,
                            'acknowledgement': 'Admin acknowledged that the App Service must be restarted before Custom Pages is fully enabled.',
                            'custom_pages_menu_name': custom_pages_menu_name,
                            'custom_pages_force_menu': custom_pages_force_menu,
                        }
                    )
                # Reconfigure Application Insights logging immediately if the setting changed
                from functions_appinsights import setup_appinsights_logging
                setup_appinsights_logging(get_settings())
                # Ensure static file is created/updated *after* successful DB save
                # Pass the *just saved* data (or fetch fresh) to ensure consistency
                updated_settings_for_file = get_settings() # Fetch fresh to be safe
                if updated_settings_for_file:
                    ensure_custom_logo_file_exists(app, updated_settings_for_file)
                    ensure_custom_favicon_file_exists(app, updated_settings_for_file)
                    initialize_clients(updated_settings_for_file) # Important - reinitialize clients with new settings
                else:
                    print("ERROR: Could not fetch settings after update to ensure logo/favicon files.")

                if governance_toggle_changes:
                    try:
                        log_governance_change(
                            admin_user_id=user_id,
                            admin_email=admin_email,
                            action='governance_feature_toggles_updated',
                            scope='feature_policy',
                            target_id='governance_feature_toggles',
                            before_state={
                                key: bool(settings.get(key, False))
                                for key in governance_toggle_keys
                            },
                            after_state={
                                key: bool(new_settings.get(key, False))
                                for key in governance_toggle_keys
                            },
                            change_details={
                                'changed_toggles': governance_toggle_changes
                            },
                        )
                    except Exception as governance_log_error:
                        log_event(
                            f"Failed to log governance toggle change: {governance_log_error}",
                            level=logging.ERROR,
                        )

                if chunk_size_changed:
                    try:
                        log_general_admin_action(
                            admin_user_id=user_id,
                            admin_email=admin_email,
                            action='chunk_size_settings_updated',
                            description='Updated chunk size overrides for document processing.',
                            additional_context={
                                'override_enabled': enable_chunk_size_override,
                                'chunk_size_cap': chunk_size_cap,
                                'chunk_sizes': normalized_chunk_sizes
                            }
                        )
                    except Exception as e:
                        print(f"Warning logging chunk size admin action: {e}")

                    try:
                        broadcast_system_notification(
                            title="Document chunk sizes updated",
                            message="Admins updated chunk size defaults. New uploads will use the latest limits.",
                            metadata={
                                'override_enabled': enable_chunk_size_override,
                                'chunk_size_cap': chunk_size_cap
                            }
                        )
                    except Exception as e:
                        print(f"Warning sending chunk size notification: {e}")

            else:
                flash("Failed to update admin settings.", "danger")


            # Redirect back to settings page
            return redirect(url_for('admin_settings'))

        # Fallback if not GET or POST (shouldn't happen with standard routing)
        return redirect(url_for('admin_settings'))