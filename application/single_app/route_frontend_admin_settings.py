# route_frontend_admin_settings.py

from config import *
from functions_documents import *
from functions_authentication import *
from functions_settings import *
from functions_logging import *

def allowed_file(filename, allowed_extensions):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions

def register_route_frontend_admin_settings(app):
    @app.route('/admin/settings', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def admin_settings():
        settings = get_settings()

        # --- Refined Default Checks (Good Practice) ---
        # Ensure models have default structure if missing/empty in DB
        if 'gpt_model' not in settings or not isinstance(settings.get('gpt_model'), dict) or 'selected' not in settings.get('gpt_model', {}):
            settings['gpt_model'] = {'selected': [], 'all': []}
        if 'embedding_model' not in settings or not isinstance(settings.get('embedding_model'), dict) or 'selected' not in settings.get('embedding_model', {}):
            settings['embedding_model'] = {'selected': [], 'all': []}
        if 'image_gen_model' not in settings or not isinstance(settings.get('image_gen_model'), dict) or 'selected' not in settings.get('image_gen_model', {}):
            settings['image_gen_model'] = {'selected': [], 'all': []}

        # (get_settings should handle this, but explicit check is safe)
        if 'require_member_of_create_group' not in settings:
            settings['require_member_of_create_group'] = False
        if 'require_member_of_safety_violation_admin' not in settings:
            settings['require_member_of_safety_violation_admin'] = False
        if 'require_member_of_feedback_admin' not in settings:
            settings['require_member_of_feedback_admin'] = False
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
        # --- End Refined Default Checks ---


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
            # ... similar try/except for embedding and image models ...


            # !!! REMOVE THIS LINE FROM GET HANDLER !!!
            # update_settings(settings) # <--- Remove this

            return render_template(
                'admin_settings.html',
                settings=settings
                # You don't need to pass deployments separately if they are added to settings['..._model']['all']
                # gpt_deployments=gpt_deployments,
                # embedding_deployments=embedding_deployments,
                # image_deployments=image_deployments
            )

        if request.method == 'POST':
            form_data = request.form # Use a variable for easier access

            # --- Fetch all other form data as before ---
            app_title = form_data.get('app_title', 'AI Chat Application')
            max_file_size_mb = int(form_data.get('max_file_size_mb', 16))
            conversation_history_limit = int(form_data.get('conversation_history_limit', 10))
            # ... (fetch all other fields using form_data.get) ...
            enable_video_file_support = form_data.get('enable_video_file_support') == 'on'
            enable_audio_file_support = form_data.get('enable_audio_file_support') == 'on'
            enable_extract_meta_data = form_data.get('enable_extract_meta_data') == 'on'

            require_member_of_create_group = form_data.get('require_member_of_create_group') == 'on'
            require_member_of_safety_violation_admin = form_data.get('require_member_of_safety_violation_admin') == 'on'
            require_member_of_feedback_admin = form_data.get('require_member_of_feedback_admin') == 'on'

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

            # Enhanced Citations...
            enable_enhanced_citations = form_data.get('enable_enhanced_citations') == 'on'
            # ... (fetch enhanced citation fields) ...

            # Model JSON Parsing (Your existing logic is fine)
            gpt_model_json = form_data.get('gpt_model_json', '')
            embedding_model_json = form_data.get('embedding_model_json', '')
            image_gen_model_json = form_data.get('image_gen_model_json', '')
            try:
                gpt_model_obj = json.loads(gpt_model_json) if gpt_model_json else {'selected': [], 'all': []}
            except Exception as e:
                print(f"Error parsing gpt_model_json: {e}")
                flash('Error parsing GPT model data. Changes may not be saved.', 'warning')
                gpt_model_obj = settings.get('gpt_model', {'selected': [], 'all': []}) # Fallback
            # ... similar try/except for embedding and image models ...
            try:
                embedding_model_obj = json.loads(embedding_model_json) if embedding_model_json else {'selected': [], 'all': []}
            except Exception as e:
                print(f"Error parsing embedding_model_json: {e}")
                flash('Error parsing Embedding model data. Changes may not be saved.', 'warning')
                embedding_model_obj = settings.get('embedding_model', {'selected': [], 'all': []}) # Fallback
            try:
                image_gen_model_obj = json.loads(image_gen_model_json) if image_gen_model_json else {'selected': [], 'all': []}
            except Exception as e:
                print(f"Error parsing image_gen_model_json: {e}")
                flash('Error parsing Image Gen model data. Changes may not be saved.', 'warning')
                image_gen_model_obj = settings.get('image_gen_model', {'selected': [], 'all': []}) # Fallback

            # --- Construct new_settings Dictionary ---
            new_settings = {
                # General
                'app_title': app_title,
                'show_logo': form_data.get('show_logo') == 'on',
                'custom_logo_base64': settings.get('custom_logo_base64', ''),
                'landing_page_text': form_data.get('landing_page_text', ''),

                # GPT (Direct & APIM)
                'enable_gpt_apim': form_data.get('enable_gpt_apim') == 'on',
                'azure_openai_gpt_endpoint': form_data.get('azure_openai_gpt_endpoint', '').strip(),
                'azure_openai_gpt_api_version': form_data.get('azure_openai_gpt_api_version', '').strip(),
                'azure_openai_gpt_authentication_type': form_data.get('azure_openai_gpt_authentication_type', 'key'),
                'azure_openai_gpt_subscription_id': form_data.get('azure_openai_gpt_subscription_id', '').strip(),
                'azure_openai_gpt_resource_group': form_data.get('azure_openai_gpt_resource_group', '').strip(),
                'azure_openai_gpt_key': form_data.get('azure_openai_gpt_key', '').strip(), # Consider encryption/decryption here if needed
                'gpt_model': gpt_model_obj,
                'azure_apim_gpt_endpoint': form_data.get('azure_apim_gpt_endpoint', '').strip(),
                'azure_apim_gpt_subscription_key': form_data.get('azure_apim_gpt_subscription_key', '').strip(),
                'azure_apim_gpt_deployment': form_data.get('azure_apim_gpt_deployment', '').strip(),
                'azure_apim_gpt_api_version': form_data.get('azure_apim_gpt_api_version', '').strip(),

                # Embeddings (Direct & APIM)
                'enable_embedding_apim': form_data.get('enable_embedding_apim') == 'on',
                'azure_openai_embedding_endpoint': form_data.get('azure_openai_embedding_endpoint', '').strip(),
                'azure_openai_embedding_api_version': form_data.get('azure_openai_embedding_api_version', '').strip(),
                'azure_openai_embedding_authentication_type': form_data.get('azure_openai_embedding_authentication_type', 'key'),
                'azure_openai_embedding_subscription_id': form_data.get('azure_openai_embedding_subscription_id', '').strip(),
                'azure_openai_embedding_resource_group': form_data.get('azure_openai_embedding_resource_group', '').strip(),
                'azure_openai_embedding_key': form_data.get('azure_openai_embedding_key', '').strip(),
                'embedding_model': embedding_model_obj,
                'azure_apim_embedding_endpoint': form_data.get('azure_apim_embedding_endpoint', '').strip(),
                'azure_apim_embedding_subscription_key': form_data.get('azure_apim_embedding_subscription_key', '').strip(),
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
                'azure_openai_image_gen_key': form_data.get('azure_openai_image_gen_key', '').strip(),
                'image_gen_model': image_gen_model_obj,
                'azure_apim_image_gen_endpoint': form_data.get('azure_apim_image_gen_endpoint', '').strip(),
                'azure_apim_image_gen_subscription_key': form_data.get('azure_apim_image_gen_subscription_key', '').strip(),
                'azure_apim_image_gen_deployment': form_data.get('azure_apim_image_gen_deployment', '').strip(),
                'azure_apim_image_gen_api_version': form_data.get('azure_apim_image_gen_api_version', '').strip(),

                # Workspaces
                'enable_user_workspace': form_data.get('enable_user_workspace') == 'on',
                'enable_group_workspaces': form_data.get('enable_group_workspaces') == 'on',
                'enable_file_processing_logs': form_data.get('enable_file_processing_logs') == 'on',
                'require_member_of_create_group': require_member_of_create_group, # ADDE

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

                # Enhanced Citations
                'enable_enhanced_citations': enable_enhanced_citations,
                'enable_enhanced_citations_mount': form_data.get('enable_enhanced_citations_mount') == 'on',
                'enhanced_citations_mount': form_data.get('enhanced_citations_mount', '/view_documents').strip(),
                'office_docs_storage_account_url': form_data.get('office_docs_storage_account_url', '').strip(),
                'office_docs_authentication_type': form_data.get('office_docs_authentication_type', 'key'),
                'office_docs_key': form_data.get('office_docs_key', '').strip(),
                'video_files_storage_account_url': form_data.get('video_files_storage_account_url', '').strip(),
                'video_files_authentication_type': form_data.get('video_files_authentication_type', 'key'),
                'video_files_key': form_data.get('video_files_key', '').strip(),
                'audio_files_storage_account_url': form_data.get('audio_files_storage_account_url', '').strip(),
                'audio_files_authentication_type': form_data.get('audio_files_authentication_type', 'key'),
                'audio_files_key': form_data.get('audio_files_key', '').strip(),

                # Safety (Content Safety Direct & APIM)
                'enable_content_safety': form_data.get('enable_content_safety') == 'on',
                'content_safety_endpoint': form_data.get('content_safety_endpoint', '').strip(),
                'content_safety_key': form_data.get('content_safety_key', '').strip(),
                'content_safety_authentication_type': form_data.get('content_safety_authentication_type', 'key'),
                'enable_content_safety_apim': form_data.get('enable_content_safety_apim') == 'on',
                'azure_apim_content_safety_endpoint': form_data.get('azure_apim_content_safety_endpoint', '').strip(),
                'azure_apim_content_safety_subscription_key': form_data.get('azure_apim_content_safety_subscription_key', '').strip(),
                'require_member_of_safety_violation_admin': require_member_of_safety_violation_admin, # ADDED
                'require_member_of_feedback_admin': require_member_of_feedback_admin, # ADDED

                # Feedback & Archiving
                'enable_user_feedback': form_data.get('enable_user_feedback') == 'on',
                'enable_conversation_archiving': form_data.get('enable_conversation_archiving') == 'on',

                # Search (Web Search Direct & APIM)
                'enable_web_search': form_data.get('enable_web_search') == 'on',
                'bing_search_key': form_data.get('bing_search_key', '').strip(),
                'enable_web_search_apim': form_data.get('enable_web_search_apim') == 'on',
                'azure_apim_web_search_endpoint': form_data.get('azure_apim_web_search_endpoint', '').strip(),
                'azure_apim_web_search_subscription_key': form_data.get('azure_apim_web_search_subscription_key', '').strip(),

                # Search (AI Search Direct & APIM)
                'azure_ai_search_endpoint': form_data.get('azure_ai_search_endpoint', '').strip(),
                'azure_ai_search_key': form_data.get('azure_ai_search_key', '').strip(),
                'azure_ai_search_authentication_type': form_data.get('azure_ai_search_authentication_type', 'key'),
                'enable_ai_search_apim': form_data.get('enable_ai_search_apim') == 'on',
                'azure_apim_ai_search_endpoint': form_data.get('azure_apim_ai_search_endpoint', '').strip(),
                'azure_apim_ai_search_subscription_key': form_data.get('azure_apim_ai_search_subscription_key', '').strip(),

                # Extract (Doc Intelligence Direct & APIM)
                'azure_document_intelligence_endpoint': form_data.get('azure_document_intelligence_endpoint', '').strip(),
                'azure_document_intelligence_key': form_data.get('azure_document_intelligence_key', '').strip(),
                'azure_document_intelligence_authentication_type': form_data.get('azure_document_intelligence_authentication_type', 'key'),
                'enable_document_intelligence_apim': form_data.get('enable_document_intelligence_apim') == 'on',
                'azure_apim_document_intelligence_endpoint': form_data.get('azure_apim_document_intelligence_endpoint', '').strip(),
                'azure_apim_document_intelligence_subscription_key': form_data.get('azure_apim_document_intelligence_subscription_key', '').strip(),

                # Other
                'max_file_size_mb': max_file_size_mb,
                'conversation_history_limit': conversation_history_limit,
                'default_system_prompt': form_data.get('default_system_prompt', '').strip(),
            }
            
            logo_file = request.files.get('logo_file')
            if logo_file and allowed_file(logo_file.filename, ALLOWED_EXTENSIONS_IMG):
                try:
                    # 1) Read file fully into memory:
                    file_bytes = logo_file.read()
                    add_file_task_to_file_processing_log(
                        document_id=None, # Placeholder if needed
                        user_id='test',
                        content=f"Logo file uploaded: {logo_file.filename}"
                    )

                    # 3) Load into Pillow from the original bytes for processing
                    in_memory_for_process = BytesIO(file_bytes) # Use original bytes
                    img = Image.open(in_memory_for_process)
                    
                    add_file_task_to_file_processing_log(
                        document_id=None, # Placeholder if needed
                        user_id='test',
                        content=f"Loaded image for processing: {logo_file.filename}"
                    )

                    # Ensure image mode is compatible (e.g., convert palette modes)
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    elif img.mode != 'RGB' and img.mode != 'RGBA':
                         img = img.convert('RGB')

                    add_file_task_to_file_processing_log(
                        document_id=None, # Placeholder if needed
                        user_id='test',
                        content=f"Converted image mode for processing: {logo_file.filename} (mode: {img.mode})"
                    )

                    # 4) Resize to height=100
                    w, h = img.size
                    if h > 100:
                        aspect = w / h
                        new_height = 100
                        new_width = int(aspect * new_height)
                        # Use LANCZOS (previously ANTIALIAS) for resizing
                        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

                    add_file_task_to_file_processing_log(
                        document_id=None, # Placeholder if needed
                        user_id='test',
                        content=f"Resized image for processing: {logo_file.filename} (new size: {img.size})"
                    )

                    # 5) Convert to PNG in-memory
                    img_bytes_io = BytesIO()
                    img.save(img_bytes_io, format='PNG')
                    png_data = img_bytes_io.getvalue()

                    add_file_task_to_file_processing_log(
                        document_id=None, # Placeholder if needed
                        user_id='test',
                        content=f"Converted image to PNG for processing: {logo_file.filename}"
                    )

                    # 6) Turn to base64
                    base64_str = base64.b64encode(png_data).decode('utf-8')

                    add_file_task_to_file_processing_log(
                        document_id=None, # Placeholder if needed
                        user_id='test',
                        content=f"Converted image to base64 for processing: {base64_str}"
                    )

                    # ****** CHANGE HERE: Update only on success *****
                    new_settings['custom_logo_base64'] = base64_str
                    test_settings = get_settings()
                    base64_str_test = test_settings.get('custom_logo_base64')

                    print("Successfully processed new logo and updated base64 string.")

                    add_file_task_to_file_processing_log(
                        document_id=None, # Placeholder if needed
                        user_id='test',
                        content=f"Updated logo base64 in settings: {base64_str_test}"
                    )

                    # ****** END CHANGE *****

                    # 7) (Optional) update logo_path_relative if you still use it elsewhere
                    # logo_path_relative = f'images/{custom_logo_filename}'
                    # new_settings['logo_path_relative'] = logo_path_relative # Example if needed

                except Exception as e:
                    print(f"Error processing logo file: {e}") # Log the error for debugging
                    flash(f"Error processing logo file: {e}. Existing logo preserved.", "danger")
                    # On error, new_settings['custom_logo_base64'] keeps its initial value (the old logo)

            # --- Update settings in DB ---
            # new_settings now contains either the new logo base64 or the original one
            if update_settings(new_settings):
                flash("Admin settings updated successfully.", "success")
                # Update local settings variable ONLY after successful DB update
                # This ensures the 'settings' variable used in GET requests reflects the saved state
                # Note: get_settings() called at the start of the *next* request will fetch the true latest state anyway.
                # So, this immediate update is mainly for consistency within this *single* request/response cycle if needed.
                settings.update(new_settings)
                # Re-initialize clients or services if critical settings changed
                # initialize_clients(settings) # Uncomment if needed and defined
                # Ensure the static file is updated/created from the new base64
                ensure_custom_logo_file_exists(app, new_settings) # Call after successful update
            else:
                flash("Failed to update admin settings.", "danger")


            # Redirect back to settings page
            return redirect(url_for('admin_settings'))

        # Fallback if not GET or POST (shouldn't happen with standard routing)
        return redirect(url_for('admin_settings'))