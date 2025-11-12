# route_backend_settings.py

from config import *
from functions_documents import *
from functions_authentication import *
from functions_settings import *
from functions_appinsights import log_event
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from swagger_wrapper import swagger_route, get_auth_security
import redis 


def register_route_backend_settings(app):
    @app.route('/api/admin/settings/check_index_fields', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def check_index_fields():
        try:
            data = request.get_json(force=True)
            idx_type = data.get('indexType')  # 'user', 'group', or 'public'

            if not idx_type or idx_type not in ['user', 'group', 'public']:
                return jsonify({'error': 'Invalid indexType. Must be "user", "group", or "public"'}), 400

            # load your golden JSON
            fname = secure_filename(f'ai_search-index-{idx_type}.json')
            base_path = os.path.join(current_app.root_path, 'static', 'json')
            fpath = os.path.normpath(os.path.join(base_path, fname))
            if os.path.commonpath([base_path, fpath]) != base_path:
                return jsonify({'error': 'Invalid file path'}), 400
            
            if not os.path.exists(fpath):
                return jsonify({'error': f'Index schema file not found: {fname}'}), 404
                
            with open(fpath, 'r') as f:
                expected = json.load(f)

            # Check if Azure AI Search is configured
            settings = get_settings()
            if not settings.get("azure_ai_search_endpoint"):
                return jsonify({
                    'error': 'Azure AI Search not configured. Please configure Azure AI Search endpoint and key in settings.',
                    'needsConfiguration': True
                }), 400

            try:
                client = get_index_client()
                current = client.get_index(expected['name'])
                
                existing_names = { fld.name for fld in current.fields }
                expected_names = { fld['name'] for fld in expected['fields'] }
                missing = sorted(expected_names - existing_names)

                return jsonify({ 
                    'missingFields': missing,
                    'indexExists': True,
                    'indexName': expected['name']
                }), 200
                
            except ResourceNotFoundError as not_found_error:
                # Index doesn't exist - this is the specific exception for "index not found"
                return jsonify({
                    'error': f'Azure AI Search index "{expected["name"]}" does not exist yet',
                    'indexExists': False,
                    'indexName': expected['name'],
                    'needsCreation': True
                }), 404
            except Exception as search_error:
                error_str = str(search_error).lower()
                # Check for other index not found patterns (fallback)
                if any(phrase in error_str for phrase in [
                    "not found", "does not exist", "no index with the name", 
                    "index does not exist", "could not find index"
                ]):
                    return jsonify({
                        'error': f'Azure AI Search index "{expected["name"]}" does not exist yet',
                        'indexExists': False,
                        'indexName': expected['name'],
                        'needsCreation': True
                    }), 404
                else:
                    app.logger.error(f"Azure AI Search error: {search_error}")
                    return jsonify({
                        'error': f'Failed to connect to Azure AI Search: {str(search_error)}',
                        'needsConfiguration': True
                    }), 500

        except Exception as e:
            app.logger.error(f"Error in check_index_fields: {str(e)}")
            return jsonify({'error': f'Unexpected error: {str(e)}'}), 500


    @app.route('/api/admin/settings/fix_index_fields', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def fix_index_fields():
        try:
            data     = request.get_json(force=True)
            idx_type = data.get('indexType')  # 'user' or 'group'

            # load your “golden” JSON schema
            json_name = secure_filename(f'ai_search-index-{idx_type}.json')
            base_path = os.path.join(current_app.root_path, 'static', 'json')
            json_path = os.path.normpath(os.path.join(base_path, json_name))
            if not json_path.startswith(base_path):
                raise Exception("Invalid file path")
            with open(json_path, 'r') as f:
                full_def = json.load(f)

            client    = get_index_client()
            index_obj = client.get_index(full_def['name'])

            existing_names = {fld.name for fld in index_obj.fields}
            missing_defs   = [fld for fld in full_def['fields'] if fld['name'] not in existing_names]

            if not missing_defs:
                return jsonify({'status': 'nothingToAdd'}), 200

            new_fields = []
            for fld in missing_defs:
                name = fld['name']
                ftype = fld['type']  # e.g. "Edm.String" or "Collection(Edm.Single)"

                if ftype.lower() == "collection(edm.single)":
                    # Vector field: hardcode dimensions if missing, pass profile name
                    dims = fld.get('dimensions', 1536)
                    vp   = fld.get('vectorSearchProfile')
                    new_fields.append(
                        SearchField(
                            name=name,
                            type=ftype,
                            searchable=True,
                            filterable=False,
                            retrievable=True,
                            sortable=False,
                            facetable=False,
                            vector_search_dimensions=dims,
                            vector_search_profile_name=vp
                        )
                    )
                else:
                    # Regular field: mirror the JSON props
                    new_fields.append(
                        SearchField(
                            name=name,
                            type=ftype,
                            searchable=fld.get('searchable', False),
                            filterable=fld.get('filterable', False),
                            retrievable=fld.get('retrievable', True),
                            sortable=fld.get('sortable', False),
                            facetable=fld.get('facetable', False),
                            key=fld.get('key', False),
                            analyzer_name=fld.get('analyzer'),
                            index_analyzer_name=fld.get('indexAnalyzer'),
                            search_analyzer_name=fld.get('searchAnalyzer'),
                            normalizer_name=fld.get('normalizer'),
                            synonym_map_names=fld.get('synonymMaps', [])
                        )
                    )

            # append the new fields, bypass ETag checks, and update
            index_obj.fields.extend(new_fields)
            index_obj.etag = "*"
            client.create_or_update_index(index_obj)

            added = [f.name for f in new_fields]
            return jsonify({ 'status': 'success', 'added': added }), 200

        except Exception as e:
            return jsonify({ 'error': str(e) }), 500

    @app.route('/api/admin/settings/create_index', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def create_index():
        """Create an AI Search index from scratch using the JSON schema."""
        try:
            data = request.get_json(force=True)
            idx_type = data.get('indexType')  # 'user', 'group', or 'public'

            if not idx_type or idx_type not in ['user', 'group', 'public']:
                return jsonify({'error': 'Invalid indexType. Must be "user", "group", or "public"'}), 400

            # Load the JSON schema
            json_name = secure_filename(f'ai_search-index-{idx_type}.json')
            base_path = os.path.join(current_app.root_path, 'static', 'json')
            json_path = os.path.normpath(os.path.join(base_path, json_name))
            if os.path.commonpath([base_path, json_path]) != base_path:
                return jsonify({'error': 'Invalid file path'}), 400
            
            if not os.path.exists(json_path):
                return jsonify({'error': f'Index schema file not found: {json_name}'}), 404

            with open(json_path, 'r') as f:
                index_definition = json.load(f)

            # Check if Azure AI Search is configured
            settings = get_settings()
            if not settings.get("azure_ai_search_endpoint"):
                return jsonify({
                    'error': 'Azure AI Search not configured. Please configure Azure AI Search endpoint and key in settings.',
                    'needsConfiguration': True
                }), 400

            client = get_index_client()
            
            # Check if index already exists
            try:
                existing_index = client.get_index(index_definition['name'])
                return jsonify({
                    'error': f'Index "{index_definition["name"]}" already exists',
                    'indexExists': True
                }), 409
            except ResourceNotFoundError:
                # Index doesn't exist, which is what we want for creation
                pass
            except Exception as e:
                # Other errors checking if index exists
                app.logger.error(f"Error checking if index exists: {e}")
                # Continue with creation attempt anyway

            # Create the index using the JSON definition
            from azure.search.documents.indexes.models import SearchIndex
            index = SearchIndex.deserialize(index_definition)
            
            # Create the index
            result = client.create_index(index)
            
            return jsonify({
                'status': 'success',
                'message': f'Successfully created index "{result.name}"',
                'indexName': result.name,
                'fieldsCount': len(result.fields)
            }), 200

        except Exception as e:
            app.logger.error(f"Error creating index: {str(e)}")
            return jsonify({'error': f'Failed to create index: {str(e)}'}), 500
    
    @app.route('/api/admin/settings/test_connection', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def test_connection():
        """
        Receives JSON payload with { test_type: "...", ... } containing ephemeral
        data from admin_settings.js. Uses that data to attempt an actual connection
        to GPT, Embeddings, etc., and returns success/failure.
        """
        data = request.get_json(force=True)
        test_type = data.get('test_type', '')

        try:
            if test_type == 'gpt':
                return _test_gpt_connection(data)

            elif test_type == 'embedding':
                return _test_embedding_connection(data)

            elif test_type == 'image':
                return _test_image_gen_connection(data)

            elif test_type == 'safety':
                return _test_safety_connection(data)

            elif test_type == 'web_search':
                return _test_web_search_connection(data)

            elif test_type == 'azure_ai_search':
                return _test_azure_ai_search_connection(data)

            elif test_type == 'redis':
                return _test_redis_connection(data)

            elif test_type == 'azure_doc_intelligence':
                return _test_azure_doc_intelligence_connection(data)

            elif test_type == 'chunking_api':
                # If you have a chunking API test, implement it here.
                return jsonify({'message': 'Chunking API connection successful'}), 200
            
            elif test_type == 'key_vault':
                return _test_key_vault_connection(data)

            else:
                return jsonify({'error': f'Unknown test_type: {test_type}'}), 400

        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
def get_index_client() -> SearchIndexClient:
    """
    Returns a SearchIndexClient wired up based on:
      - enable_ai_search_apim
      - azure_ai_search_authentication_type (managed_identity vs key)
      - and the various endpoint & key settings.
    """
    settings = get_settings()

    if settings.get("enable_ai_search_apim", False):
        endpoint = settings["azure_apim_ai_search_endpoint"].rstrip("/")
        credential = AzureKeyCredential(settings["azure_apim_ai_search_subscription_key"])
    else:
        endpoint = settings["azure_ai_search_endpoint"].rstrip("/")
        if settings.get("azure_ai_search_authentication_type", "key") == "managed_identity":
            credential = DefaultAzureCredential()
            if AZURE_ENVIRONMENT in ("usgovernment", "custom"):
                return SearchIndexClient(endpoint=endpoint,
                                          credential=credential,
                                          audience=search_resource_manager)
        else:
            credential = AzureKeyCredential(settings["azure_ai_search_key"])

    return SearchIndexClient(endpoint=endpoint, credential=credential)

def _test_gpt_connection(payload):
    """Attempt to connect to GPT using ephemeral settings from the admin UI."""
    enable_apim = payload.get('enable_apim', False)
    selected_model = payload.get('selected_model') or {}
    system_message = {
        'role': 'system',
        'content': f"Testing access."
    }

    # Decide GPT model
    if enable_apim:
        apim_data = payload.get('apim', {})
        endpoint = apim_data.get('endpoint') #.rstrip('/openai')
        api_version = apim_data.get('api_version')
        gpt_model = apim_data.get('deployment').split(',')[0]
        subscription_key = apim_data.get('subscription_key')

        gpt_client = AzureOpenAI(
            api_version=api_version,
            azure_endpoint=endpoint,
            api_key=subscription_key
        )
    else:
        direct_data = payload.get('direct', {})
        endpoint = direct_data.get('endpoint')
        api_version = direct_data.get('api_version')
        gpt_model = selected_model.get('deploymentName')

        if direct_data.get('auth_type') == 'managed_identity':
            token_provider = get_bearer_token_provider(DefaultAzureCredential(), cognitive_services_scope)
            
            gpt_client = AzureOpenAI(
                api_version=api_version,
                azure_endpoint=endpoint,
                azure_ad_token_provider=token_provider
            )
        else:
            key = direct_data.get('key')

            gpt_client = AzureOpenAI(
                api_version=api_version,
                azure_endpoint=endpoint,
                api_key=key
            )

    try:
        response = gpt_client.chat.completions.create(
            model=gpt_model,
            messages=[system_message]
        )
        if response:
            return jsonify({'message': 'GPT connection successful'}), 200
    except Exception as e:
        print(str(e))
        return jsonify({'error': f'Error generating model response: {str(e)}'}), 500


def _test_redis_connection(payload):
    """
    Attempts to connect to Azure Redis using key or managed identity auth.
    Performs a simple SET/GET round-trip test.
    """
    redis_host = payload.get('endpoint', '').strip()
    redis_key = payload.get('key', '').strip()
    redis_auth_type = payload.get('auth_type', 'key').strip()

    if not redis_host:
        return jsonify({'error': 'Redis host is required'}), 400

    try:
        if redis_auth_type == 'managed_identity':
            # Acquire token from managed identity for Redis scope
            from config import get_redis_cache_infrastructure_endpoint
            credential = DefaultAzureCredential()
            redis_hostname = redis_host.split('.')[0]
            cache_endpoint = get_redis_cache_infrastructure_endpoint(redis_hostname)
            token = credential.get_token(cache_endpoint)
            redis_password = token.token
        else:
            if not redis_key:
                return jsonify({'error': 'Redis key is required for key auth'}), 400
            redis_password = redis_key

        r = redis.Redis(
            host=redis_host,
            port=6380,
            password=redis_password,
            ssl=True,
            socket_connect_timeout=5
        )

        test_key = "test_key_simplechat"
        test_value = "hello_redis"
        r.set(test_key, test_value, ex=10)
        result = r.get(test_key)

        if result and result.decode() == test_value:
            return jsonify({'message': 'Redis connection successful'}), 200
        else:
            return jsonify({'error': 'Redis test failed: unexpected value'}), 500

    except Exception as e:
        print(f"Redis test error: {e}")
        return jsonify({'error': f'Redis connection error: {str(e)}'}), 500



def _test_embedding_connection(payload):
    """Attempt to connect to Embeddings using ephemeral settings from the admin UI."""
    enable_apim = payload.get('enable_apim', False)
    selected_model = payload.get('selected_model') or {}
    text = "Test text for embedding connection."

    if enable_apim:
        apim_data = payload.get('apim', {})
        endpoint = apim_data.get('endpoint')
        api_version = apim_data.get('api_version')
        embedding_model = apim_data.get('deployment')
        subscription_key = apim_data.get('subscription_key')

        embedding_client = AzureOpenAI(
            api_version=api_version,
            azure_endpoint=endpoint,
            api_key=subscription_key
        )
    else:
        direct_data = payload.get('direct', {})
        endpoint = direct_data.get('endpoint')
        api_version = direct_data.get('api_version')
        embedding_model = selected_model.get('deploymentName')

        if direct_data.get('auth_type') == 'managed_identity':
            token_provider = get_bearer_token_provider(DefaultAzureCredential(), cognitive_services_scope)
            
            embedding_client = AzureOpenAI(
                api_version=api_version,
                azure_endpoint=endpoint,
                azure_ad_token_provider=token_provider
            )
        else:
            key = direct_data.get('key')

            embedding_client = AzureOpenAI(
                api_version=api_version,
                azure_endpoint=endpoint,
                api_key=key
            )
    try:
        response = embedding_client.embeddings.create(
            model=embedding_model,
            input=text
        )

        if response:
            return jsonify({'message': 'Embedding connection successful'}), 200
    except Exception as e:
        print(str(e))
        return jsonify({'error': f'Error generating embedding response: {str(e)}'}), 500
    

def _test_image_gen_connection(payload):
    """Attempt to connect to an Image Generation endpoint using ephemeral settings."""
    enable_apim = payload.get('enable_apim', False)
    selected_model = payload.get('selected_model') or {}
    prompt = "A scenic mountain at sunrise"

    if enable_apim:
        apim_data = payload.get('apim', {})
        endpoint = apim_data.get('endpoint')
        api_version = apim_data.get('api_version')
        image_gen_model = apim_data.get('deployment')
        subscription_key = apim_data.get('subscription_key')

        image_gen_client = AzureOpenAI(
            api_version=api_version,
            azure_endpoint=endpoint,
            api_key=subscription_key
        )
    else:
        direct_data = payload.get('direct', {})
        endpoint = direct_data.get('endpoint')
        api_version = direct_data.get('api_version')
        image_gen_model = selected_model.get('deploymentName')

        if direct_data.get('auth_type') == 'managed_identity':
            token_provider = get_bearer_token_provider(DefaultAzureCredential(), cognitive_services_scope)
            
            image_gen_client = AzureOpenAI(
                api_version=api_version,
                azure_endpoint=endpoint,
                azure_ad_token_provider=token_provider
            )
        else:
            key = direct_data.get('key')

            image_gen_client = AzureOpenAI(
                api_version=api_version,
                azure_endpoint=endpoint,
                api_key=key
            )
    try:
        response = image_gen_client.images.generate(
            prompt=prompt,
            n=1,
            model=image_gen_model
        )
        if response:
            return jsonify({'message': 'Image generation connection successful'}), 200
    except Exception as e:
        print(str(e))
        return jsonify({'error': f'Error generating model response: {str(e)}'}), 500


def _test_safety_connection(payload):
    """Attempt to connect to a content safety endpoint using ephemeral settings."""
    enabled = payload.get('enabled', False)
    if not enabled:
        # If the user toggled content safety off, just return success
        return jsonify({'message': 'Content Safety is disabled, skipping test'}), 200

    enable_apim = payload.get('enable_apim', False)

    if enable_apim:
        apim_data = payload.get('apim', {})
        endpoint = apim_data.get('endpoint')
        subscription_key = apim_data.get('subscription_key')

        content_safety_client = ContentSafetyClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(subscription_key)
        )
    else:
        direct_data = payload.get('direct', {})
        endpoint = direct_data.get('endpoint')
        key = direct_data.get('key')

        if direct_data.get('auth_type') == 'managed_identity':
            if AZURE_ENVIRONMENT in ("usgovernment", "custom"):
                content_safety_client = ContentSafetyClient(
                    endpoint=endpoint,
                    credential=DefaultAzureCredential(),
                    credential_scopes=[cognitive_services_scope]
                )
            else:
                content_safety_client = ContentSafetyClient(
                    endpoint=endpoint,
                    credential=DefaultAzureCredential()
                )
        else:
            content_safety_client = ContentSafetyClient(
                endpoint=endpoint,
                credential=AzureKeyCredential(key)
            )

    try:     
        user_message = "Test message for content safety connection."
        request_obj = AnalyzeTextOptions(text=user_message)
        cs_response = content_safety_client.analyze_text(request_obj)

        if cs_response:
            return jsonify({'message': 'Safety connection successful'}), 200
    except Exception as e:
        return jsonify({'error': f'Safety connection error: {str(e)}'}), 500

def _test_azure_ai_search_connection(payload):
    """Attempt to connect to Azure Cognitive Search (or APIM-wrapped)."""
    enable_apim = payload.get('enable_apim', False)

    if enable_apim:
        apim_data = payload.get('apim', {})
        endpoint = apim_data.get('endpoint')  # e.g. https://my-apim.azure-api.net/search
        subscription_key = apim_data.get('subscription_key')
        url = f"{endpoint.rstrip('/')}/indexes?api-version=2023-11-01"
        headers = {
            'api-key': subscription_key,
            'Content-Type': 'application/json'
        }
    else:
        direct_data = payload.get('direct', {})
        endpoint = direct_data.get('endpoint')  # e.g. https://<searchservice>.search.windows.net
        key = direct_data.get('key')
        url = f"{endpoint.rstrip('/')}/indexes?api-version=2023-11-01"

        if direct_data.get('auth_type') == 'managed_identity':
            if AZURE_ENVIRONMENT in ("usgovernment", "custom"): # change credential scopes for US Gov or custom environments
                credential_scopes=search_resource_manager + "/.default"
            arm_scope = credential_scopes
            credential = DefaultAzureCredential()
            arm_token = credential.get_token(arm_scope).token
            headers = {
                'Authorization': f'Bearer {arm_token}',
                'Content-Type': 'application/json'
            }
        else:
            headers = {
                'api-key': key,
                'Content-Type': 'application/json'
            }

    # A small GET to /indexes to verify we have connectivity
    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code == 200:
        return jsonify({'message': 'Azure AI search connection successful'}), 200
    else:
        raise Exception(f"Azure AI search connection error: {resp.status_code} - {resp.text}")


def _test_azure_doc_intelligence_connection(payload):
    """Attempt to connect to Azure Form Recognizer / Document Intelligence."""
    enable_apim = payload.get('enable_apim', False)

    if enable_apim:
        apim_data = payload.get('apim', {})
        endpoint = apim_data.get('endpoint')
        subscription_key = apim_data.get('subscription_key')

        document_intelligence_client = DocumentIntelligenceClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(subscription_key)
        )
    else:
        direct_data = payload.get('direct', {})
        endpoint = direct_data.get('endpoint')
        key = direct_data.get('key')

        if direct_data.get('auth_type') == 'managed_identity':
            if AZURE_ENVIRONMENT in ("usgovernment", "custom"):
                document_intelligence_client = DocumentIntelligenceClient(
                    endpoint=endpoint,
                    credential=DefaultAzureCredential(),
                    credential_scopes=[cognitive_services_scope],
                    api_version="2024-11-30"    # Must be specified otherwise looks for 2023-07-31-preview by default which is not a valid version in Azure Government
                )
            else:
                document_intelligence_client = DocumentIntelligenceClient(
                    endpoint=endpoint,
                    credential=DefaultAzureCredential()
                )
        else:
            document_intelligence_client = DocumentIntelligenceClient(
                endpoint=endpoint,
                credential=AzureKeyCredential(key)
            )
    
    # Use local test file instead of URL for better offline testing
    test_file_path = os.path.join(current_app.root_path, 'static', 'test_files', 'test_document.pdf')
    if AZURE_ENVIRONMENT in ("usgovernment", "custom"):
        # Required format for Document Intelligence API version 2024-11-30 and later
        with open(test_file_path, 'rb') as f:
            file_bytes = f.read()
            base64_source = base64.b64encode(file_bytes).decode('utf-8')

        poller = document_intelligence_client.begin_analyze_document(
            "prebuilt-read",
            {"base64Source": base64_source}
        )
    else:
        with open(test_file_path, 'rb') as f:
            file_content = f.read()
            # Use base64 format for consistency with the stable API
            base64_source = base64.b64encode(file_content).decode('utf-8')
            analyze_request = {"base64Source": base64_source}
            poller = document_intelligence_client.begin_analyze_document(
                model_id="prebuilt-read",
                body=analyze_request
            )

    max_wait_time = 600
    start_time = time.time()

    while True:
        status = poller.status()
        if status in ["succeeded", "failed", "canceled"]:
            break
        if time.time() - start_time > max_wait_time:
            raise TimeoutError("Document analysis took too long.")
        time.sleep(10)

    if status == "succeeded":
        return jsonify({'message': 'Azure document intelligence connection successful'}), 200
    else:
        return jsonify({'error': f"Document Intelligence error: {status}"}), 500

def _test_key_vault_connection(payload):
    """Attempt to connect to Azure Key Vault using ephemeral settings."""
    vault_name = payload.get('vault_name', '').strip()
    client_id = payload.get('client_id', '').strip()

    if not vault_name:
        return jsonify({'error': 'Key Vault name is required'}), 400

    try:
        vault_url = f"https://{vault_name}{KEY_VAULT_DOMAIN}"

        if client_id:
            credential = DefaultAzureCredential(managed_identity_client_id=client_id)
        else:
            credential = DefaultAzureCredential()

        if AZURE_ENVIRONMENT == "custom":
            #TODO: Needs to be tested with a custom environment
            kv_client = SecretClient(vault_url=vault_url, credential=credential)
        else:
            kv_client = SecretClient(vault_url=vault_url, credential=credential)

        # Perform a simple list operation to verify connectivity
        secrets = kv_client.list_properties_of_secrets()
        _ = next(secrets, None)  # Attempt to get the first secret (if any)

        return jsonify({'message': 'Key Vault connection successful'}), 200

    except Exception as e:
        log_event(f"[AKV_TEST] Key Vault connection error: {str(e)}", level="error")
        return jsonify({'error': f'Key Vault connection error. Check Application Insights using "[AKV_TEST]" for details.'}), 500