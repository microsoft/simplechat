# functions_settings.py

from config import *
from functions_appinsights import log_event

def get_settings():
    import secrets
    default_settings = {
        # External health check
        'enable_external_healthcheck': True,
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
        'enable_multi_agent_orchestration': False,
        'max_rounds_per_agent': 1,
        'enable_semantic_kernel': False,
        'per_user_semantic_kernel': False,
        'orchestration_type': 'default_agent',
        'merge_global_semantic_kernel_with_workspace': False,
        'global_selected_agent': {
            'name': 'researcher',
            'is_global': True
        },
        'allow_user_agents': False,
        'allow_user_custom_agent_endpoints': False,
        'allow_user_plugins': False,
        'allow_group_agents': False,
        'allow_group_custom_agent_endpoints': False,
        'allow_group_plugins': False,
        'id': 'app_settings',
        # -- Your entire default dictionary here --
        'app_title': 'Simple Chat',
        'landing_page_text': 'You can add text here and it supports Markdown. '
                             'You agree to our [acceptable user policy](acceptable_use_policy.html) by using this service.',
        'landing_page_alignment': 'left',
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


        # Workspaces
        'enable_user_workspace': True,
        'enable_group_workspaces': True,
        'require_member_of_create_group': False,
        'enable_public_workspaces': False,
        'require_member_of_create_public_workspace': False,
        'enable_file_sharing': False,

        # Multimedia
        'enable_video_file_support': False,
        'enable_audio_file_support': False,

        # Metadata Extraction
        'enable_extract_meta_data': False,
        'metadata_extraction_model': '',
        'enable_summarize_content_history_for_search': False,
        'number_of_historical_messages_to_summarize': 10,
        'enable_summarize_content_history_beyond_conversation_history_limit': False,

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

        # Search and Extract
        'azure_ai_search_endpoint': '',
        'azure_ai_search_key': '',
        'azure_ai_search_authentication_type': 'key',
        'enable_ai_search_apim': False,
        'azure_apim_ai_search_endpoint': '',
        'azure_apim_ai_search_subscription_key': '',

        'azure_document_intelligence_endpoint': '',
        'azure_document_intelligence_key': '',
        'azure_document_intelligence_authentication_type': 'key',
        'enable_document_intelligence_apim': False,
        'azure_apim_document_intelligence_endpoint': '',
        'azure_apim_document_intelligence_subscription_key': '',

        # Authentication & Redirect Settings
        'enable_front_door': False,
        'front_door_url': '',

        # Other
        'max_file_size_mb': 150,
        'conversation_history_limit': 10,
        'default_system_prompt': '',
        'enable_file_processing_logs': True,
        'file_processing_logs_timer_enabled': False,
        'file_timer_value': 1,
        'file_timer_unit': 'hours',
        'file_processing_logs_turnoff_time': None,
        'enable_external_healthcheck': False,

        # Video file settings with Azure Video Indexer Settings
        'video_indexer_endpoint': video_indexer_endpoint,
        'video_indexer_location': '',
        'video_indexer_account_id': '',
        'video_indexer_api_key': '',
        'video_indexer_resource_group': '',
        'video_indexer_subscription_id': '',
        'video_indexer_account_name': '',
        'video_indexer_arm_api_version': '2021-11-10-preview',
        'video_index_timeout': 600,

        # Audio file settings with Azure speech service
        "speech_service_endpoint": '',
        "speech_service_location": '',
        "speech_service_locale": "en-US",
        "speech_service_key": ""
    }

    try:
        # Attempt to read the existing doc
        settings_item = cosmos_settings_container.read_item(
            item="app_settings",
            partition_key="app_settings"
        )
        #print("Successfully retrieved settings from Cosmos DB.")

        # Merge default_settings in, to fill in any missing or nested keys
        merged = deep_merge_dicts(default_settings, settings_item)

        # If merging added anything new, upsert back to Cosmos so future reads remain up to date
        if merged != settings_item:
            cosmos_settings_container.upsert_item(merged)
            print("App Settings had missing keys and was updated in Cosmos DB.")
            return merged
        else:
            # If merged is unchanged, no new keys needed
            return merged

    except CosmosResourceNotFoundError:
        cosmos_settings_container.create_item(body=default_settings)
        print("Default settings created in Cosmos and returned.")
        return default_settings

    except Exception as e:
        print(f"Error retrieving settings: {str(e)}")
        return None

def update_settings(new_settings):
    try:
        # always fetch the latest settings doc, which includes your merges
        settings_item = get_settings()
        settings_item.update(new_settings)
        cosmos_settings_container.upsert_item(settings_item)
        print("Settings updated successfully.")
        return True
    except Exception as e:
        print(f"Error updating settings: {str(e)}")
        return False

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
        print(f"Invalid version format encountered: '{v1_str}' or '{v2_str}'")
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
        print("HTML content is empty.")
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
                        # else:
                        #     print(f"Skipping invalid version format from href '{href}': '{version_str}'")

                except (IndexError, ValueError):
                    # Ignore links where splitting or processing fails
                    # print(f"Could not process href: {href}")
                    continue # Skip to the next link

        if not versions_found:
            print("No valid version tags found in HTML matching the pattern.")
            return None

        # Now compare the found versions to find the latest
        latest_version = None
        for current_version in versions_found:
            if latest_version is None:
                latest_version = current_version
                # print(f"Initial latest version set to: {latest_version}")
            else:
                # print(f"Comparing '{current_version}' with current latest '{latest_version}'")
                comparison_result = compare_versions(current_version, latest_version)

                if comparison_result == 1: # current_version > latest_version
                    # print(f"  -> New latest version: {current_version}")
                    latest_version = current_version
                elif comparison_result is None:
                     # Log if comparison fails, but continue trying others
                     print(f"Warning: Could not compare version '{current_version}' with '{latest_version}'. Skipping this comparison.")
                # else: comparison is -1 or 0, keep existing latest_version
                #     print(f"  -> '{latest_version}' remains latest.")


        print(f"Latest version identified from HTML: {latest_version}")
        return latest_version

    except Exception as e:
        print(f"Error parsing HTML or finding latest version: {e}")
        return None
    
def deep_merge_dicts(default_dict, existing_dict):
    for k, default_val in default_dict.items():
        if k not in existing_dict:
            existing_dict[k] = default_val
        else:
            existing_val = existing_dict[k]
            if isinstance(default_val, dict) and isinstance(existing_val, dict):
                deep_merge_dicts(default_val, existing_val)
            # For lists or other types, we skip overwriting.
    return existing_dict

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
        print("Decryption failed: Invalid token")
        return None

def get_user_settings(user_id):
    """Fetches the user settings document from Cosmos DB, ensuring email and display_name are present if possible."""
    from flask import session
    try:
        doc = cosmos_user_settings_container.read_item(item=user_id, partition_key=user_id)
        # Ensure the settings key exists for consistency downstream
        if 'settings' not in doc:
            doc['settings'] = {}
        
        # Try to update email/display_name if missing and available in session
        user = session.get("user", {})
        email = user.get("preferred_username") or user.get("email")
        display_name = user.get("name")
        updated = False
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
                print(f"Warning: Could not fetch profile image for user {user_id}: {e}")
                doc['settings']['profileImage'] = None
                updated = True
        
        if updated:
            cosmos_user_settings_container.upsert_item(body=doc)
        return doc
    except exceptions.CosmosResourceNotFoundError:
        # Return a default structure if the user has no settings saved yet
        user = session.get("user", {})
        email = user.get("preferred_username") or user.get("email")
        display_name = user.get("name")
        doc = {"id": user_id, "settings": {}}
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
            print(f"Warning: Could not fetch profile image for new user {user_id}: {e}")
            doc['settings']['profileImage'] = None
            
        cosmos_user_settings_container.upsert_item(body=doc)
        return doc
    except Exception as e:
        print(f"Error in get_user_settings for {user_id}: {e}")
        raise # Re-raise the exception to be handled by the route
    
def update_user_settings(user_id, settings_to_update):
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
    log_prefix = f"User settings update for {user_id}:"
    log_event("[UserSettings] Update Attempt", {"user_id": user_id, "settings_to_update": settings_to_update})


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
                    'name': first_user_agent['name'],
                    'is_global': False,
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
                                'name': first_global_agent['name'],
                                'is_global': True,
                            }
                        else:
                            doc['settings']['selected_agent'] = {
                                'name': 'default_agent',
                                'is_global': True,
                            }
                    except Exception:
                        # Fallback if container access fails
                        doc['settings']['selected_agent'] = {
                            'name': 'default_agent',
                            'is_global': True,
                        }
                else:
                    doc['settings']['selected_agent'] = {
                        'name': 'researcher',
                        'is_global': False,
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

        return True

    except exceptions.CosmosHttpResponseError as e:
        print(f"{log_prefix} Cosmos DB HTTP error: {e}")

        return False
    except Exception as e:
        # Catch any other unexpected errors during the update process
        print(f"{log_prefix} Unexpected error during update: {e}")

        return False

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
    # Exclude any key containing the substring "key" or specific sensitive URLs
    return {k: v for k, v in full_settings.items() if "key" not in k and k != "office_docs_storage_account_url"}