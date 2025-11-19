# route_frontend_chats.py

from config import *
from functions_authentication import *
from functions_content import *
from functions_settings import *
from functions_documents import *
from functions_group import find_group_by_id
from functions_appinsights import log_event
from swagger_wrapper import swagger_route, get_auth_security

def register_route_frontend_chats(app):
    @app.route('/chats', methods=['GET'])
    @swagger_route(
        security=get_auth_security()
    )
    @login_required
    @user_required
    def chats():
        user_id = get_current_user_id()
        settings = get_settings()
        user_settings = get_user_settings(user_id)
        public_settings = sanitize_settings_for_user(settings)
        enable_user_feedback = public_settings.get("enable_user_feedback", False)
        enable_enhanced_citations = public_settings.get("enable_enhanced_citations", False)
        enable_document_classification = public_settings.get("enable_document_classification", False)
        enable_extract_meta_data = public_settings.get("enable_extract_meta_data", False)
        active_group_id = user_settings["settings"].get("activeGroupOid", "")
        active_group_name = ""
        if active_group_id:
            group_doc = find_group_by_id(active_group_id)
            if group_doc:
                active_group_name = group_doc.get("name", "")
        categories_list = public_settings.get("document_classification_categories","")

        if not user_id:
            return redirect(url_for('login'))
        return render_template(
            'chats.html',
            settings=public_settings,
            enable_user_feedback=enable_user_feedback,
            active_group_id=active_group_id,
            active_group_name=active_group_name,
            enable_enhanced_citations=enable_enhanced_citations,
            enable_document_classification=enable_document_classification,
            document_classification_categories=categories_list,
            enable_extract_meta_data=enable_extract_meta_data,
        )
    
    @app.route('/upload', methods=['POST'])
    @swagger_route(
        security=get_auth_security()
    )
    @login_required
    @user_required
    @file_upload_required
    def upload_file():
        settings = get_settings()
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400

        file = request.files['file']
        conversation_id = request.form.get('conversation_id')

        if not file.filename:
            return jsonify({'error': 'No selected file'}), 400

        if not conversation_id:
            conversation_id = str(uuid.uuid4())
            conversation_item = {
                'id': conversation_id,
                'user_id': user_id,
                'last_updated': datetime.utcnow().isoformat(),
                'title': 'New Conversation',
                'context': [],
                'tags': [],
                'strict': False
            }
            cosmos_conversations_container.upsert_item(conversation_item)
        else:
            try:
                conversation_item = cosmos_conversations_container.read_item(
                    item=conversation_id,
                    partition_key=conversation_id
                )
            except CosmosResourceNotFoundError:
                conversation_id = str(uuid.uuid4())
                conversation_item = {
                    'id': conversation_id,
                    'user_id': user_id,
                    'last_updated': datetime.utcnow().isoformat(),
                    'title': 'New Conversation',
                    'context': [],
                    'tags': [],
                    'strict': False
                }
                cosmos_conversations_container.upsert_item(conversation_item)
            except Exception as e:
                return jsonify({'error': f'Error reading conversation: {str(e)}'}), 500
        
        file.seek(0, os.SEEK_END)
        file_length = file.tell()
        max_file_size_bytes = settings.get('max_file_size_mb') * 1024 * 1024
        if file_length > max_file_size_bytes:
            return jsonify({'error': 'File size exceeds maximum allowed size'}), 400
        file.seek(0)

        filename = secure_filename(file.filename)
        file_ext = os.path.splitext(filename)[1].lower()

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            file.save(tmp_file.name)
            temp_file_path = tmp_file.name

        extracted_content  = ''
        is_table = False 

        try:
            if file_ext in ['.pdf', '.docx', '.pptx', '.html', '.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.heif']:
                extracted_content  = extract_content_with_azure_di(temp_file_path)
            elif file_ext == '.txt':
                extracted_content  = extract_text_file(temp_file_path)
            elif file_ext == '.md':
                extracted_content  = extract_markdown_file(temp_file_path)
            elif file_ext == '.json':
                with open(temp_file_path, 'r', encoding='utf-8') as f:
                    parsed_json = json.load(f)
                    extracted_content  = json.dumps(parsed_json, indent=2)
            elif file_ext in ['.csv', '.xls', '.xlsx', '.xlsm']:
                extracted_content = extract_table_file(temp_file_path, file_ext)
                is_table = True
            else:
                return jsonify({'error': 'Unsupported file type'}), 400

        except Exception as e:
            return jsonify({'error': f'Error processing file: {str(e)}'}), 500
        finally:
            os.remove(temp_file_path)

        try:
            file_message_id = f"{conversation_id}_file_{int(time.time())}_{random.randint(1000,9999)}"
            file_message = {
                'id': file_message_id,
                'conversation_id': conversation_id,
                'role': 'file',
                'filename': filename,
                'file_content': extracted_content,
                'is_table': is_table,
                'timestamp': datetime.utcnow().isoformat(),
                'model_deployment_name': None
            }

            cosmos_messages_container.upsert_item(file_message)

            conversation_item['last_updated'] = datetime.utcnow().isoformat()
            cosmos_conversations_container.upsert_item(conversation_item)

        except Exception as e:
            return jsonify({
                'error': f'Error adding file to conversation: {str(e)}'
            }), 500

        return jsonify({
            'message': 'File added to the conversation successfully',
            'conversation_id': conversation_id
        }), 200
    
    # THIS IS THE OLD ROUTE, KEEPING IT FOR REFERENCE, WILL DELETE LATER
    @app.route("/view_pdf", methods=["GET"])
    @swagger_route(
        security=get_auth_security()
    )
    @login_required
    @user_required
    def view_pdf():
        """
        1) Grab 'doc_id' and 'page' from query params.
        2) Validate user and doc_id ownership.
        3) Generate SAS URL for the PDF in Azure Blob Storage.
        4) Download the file to a temp location or memory.
        5) (Optional) Use PyMuPDF to do further operations (like extracting a single page).
        6) Return the PDF file via send_file.
        """

        # 1) Get query params
        doc_id = request.args.get("doc_id")
        page_number = request.args.get("page", default=1, type=int)

        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401

        # 2) Validate doc_id -> get the blob name
        #    For example, doc_id references the DB row that includes user_id & file_name
        doc_response, status_code = get_document(user_id, doc_id)
        if status_code != 200:
            return doc_response, status_code

        raw_doc = doc_response.get_json()
        
        # Determine workspace type and appropriate container
        settings = get_settings()
        if raw_doc.get('public_workspace_id'):
            if not settings.get('enable_public_workspaces', False):
                return jsonify({"error": "Public workspaces are not enabled"}), 403
            container_name = storage_account_public_documents_container_name
            blob_name = f"{raw_doc['public_workspace_id']}/{raw_doc['file_name']}"
        elif raw_doc.get('group_id'):
            if not settings.get('enable_group_workspaces', False):
                return jsonify({"error": "Group workspaces are not enabled"}), 403
            container_name = storage_account_group_documents_container_name
            blob_name = f"{raw_doc['group_id']}/{raw_doc['file_name']}"
        else:
            if not settings.get('enable_user_workspace', False):
                return jsonify({"error": "User workspaces are not enabled"}), 403
            container_name = storage_account_user_documents_container_name
            blob_name = f"{raw_doc['user_id']}/{raw_doc['file_name']}"

        # 3) Generate the SAS URL (short-lived, read-only)
        blob_service_client = CLIENTS.get("storage_account_office_docs_client")
        container_client = blob_service_client.get_container_client(container_name)

        sas_token = generate_blob_sas(
            account_name=blob_service_client.account_name,
            container_name=container_client.container_name,
            blob_name=blob_name,
            account_key=settings.get("office_docs_key"),
            permission=BlobSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(minutes=60)  # 60-minute expiry
        )

        signed_url = (
            f"https://{blob_service_client.account_name}.blob.core.windows.net"
            f"/{container_client.container_name}/{blob_name}?{sas_token}"
        )

        if AZURE_ENVIRONMENT == "usgovernment":
            signed_url = (
                f"https://{blob_service_client.account_name}.blob.core.usgovcloudapi.net"
                f"/{container_client.container_name}/{blob_name}?{sas_token}"
            )

        if AZURE_ENVIRONMENT == "custom":
            signed_url = (
                f"https://{blob_service_client.account_name}.{CUSTOM_BLOB_STORAGE_URL_VALUE}"
                f"/{container_client.container_name}/{blob_name}?{sas_token}"
            )

        # 4) Download the PDF from Azure to a temp file (or you can use in-memory BytesIO)
        random_uuid = str(uuid.uuid4())
        temp_pdf_path = f"temp_file_{random_uuid}.pdf"

        try:
            # Download the PDF
            r = requests.get(signed_url, timeout=30)
            r.raise_for_status()
            with open(temp_pdf_path, "wb") as f:
                f.write(r.content)

            # 3) Extract up to three pages: (page-1, page, page+1)
            pdf_document = fitz.open(temp_pdf_path)
            total_pages = pdf_document.page_count
            current_idx = page_number - 1  # zero-based

            if current_idx < 0 or current_idx >= total_pages:
                pdf_document.close()
                os.remove(temp_pdf_path)
                return jsonify({"error": "Requested page out of range"}), 400

            # Default to just the current page
            start_idx = current_idx
            end_idx = current_idx

            # If a previous page exists, include it
            if current_idx > 0:
                start_idx = current_idx - 1

            # If a next page exists, include it
            if current_idx < total_pages - 1:
                end_idx = current_idx + 1

            # 4) Create new PDF with only start_idx..end_idx
            extracted_pdf = fitz.open()
            extracted_pdf.insert_pdf(pdf_document, from_page=start_idx, to_page=end_idx)
            extracted_pdf.save(temp_pdf_path, garbage=4, deflate=True)
            extracted_pdf.close()
            pdf_document.close()

            # 5) Determine new_page_number (within the sub-document)
            extracted_count = end_idx - start_idx + 1
            
            if extracted_count == 1:
                # Only current page
                new_page_number = 1
            elif extracted_count == 3:
                # current page is in the middle
                new_page_number = 2
            else:
                # Exactly 2 pages
                # If start_idx == current_idx, the user is on the first page
                # If current_idx == end_idx, the user is on the second page
                if start_idx == current_idx:
                    # e.g. pages = [current, next]
                    new_page_number = 1
                else:
                    # e.g. pages = [previous, current]
                    new_page_number = 2

            # 6) Return the sub-PDF, attaching a custom header with new_page_number
            response = send_file(temp_pdf_path, as_attachment=False)
            response.headers["X-Sub-PDF-Page"] = str(new_page_number)
            return response

        except Exception as e:
            # Clean up on error
            if os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)
            return jsonify({"error": str(e)}), 500
        finally:
            # Clean up the temp file after the request finishes
            # (You can also do this in an after_request or teardown block.)
            if os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)

    # --- Updated route ---
    @app.route('/view_document')
    @swagger_route(
        security=get_auth_security()
    )
    @login_required
    @user_required
    def view_document():
        settings = get_settings()
        download_location = tempfile.gettempdir()


        doc_id = request.args.get("doc_id")
        page_number = request.args.get("page", default=1, type=int) # Keep page, useful for PDFs

        if not doc_id:
            return jsonify({'error': 'doc_id parameter is required'}), 400

        user_id = get_current_user_id()
        if not user_id:
             return jsonify({"error": "User not authenticated"}), 401 # Should be caught by @login_required anyway

        # Fetch Document Metadata (assuming get_user_document handles user auth checks implicitly)
        doc_response, status_code = get_document(user_id, doc_id)
        if status_code != 200:
            # Pass through the error response from get_user_document
            return doc_response, status_code

        raw_doc = doc_response.get_json() # Assuming get_user_document returns jsonify response
        file_name = raw_doc.get('file_name')
        owner_user_id = raw_doc.get('user_id') # Get owner user_id from doc metadata

        if not file_name:
             return jsonify({"error": "Internal server error: Document metadata incomplete."}), 500

        # Determine workspace type and appropriate container
        if raw_doc.get('public_workspace_id'):
            if not settings.get('enable_public_workspaces', False):
                return jsonify({"error": "Public workspaces are not enabled"}), 403
            container_name = storage_account_public_documents_container_name
            blob_name = f"{raw_doc['public_workspace_id']}/{file_name}"
        elif raw_doc.get('group_id'):
            if not settings.get('enable_group_workspaces', False):
                return jsonify({"error": "Group workspaces are not enabled"}), 403
            container_name = storage_account_group_documents_container_name
            blob_name = f"{raw_doc['group_id']}/{file_name}"
        else:
            if not settings.get('enable_user_workspace', False):
                return jsonify({"error": "User workspaces are not enabled"}), 403
            container_name = storage_account_user_documents_container_name
            blob_name = f"{owner_user_id}/{file_name}"
        file_ext = os.path.splitext(file_name)[-1].lower()

        # Ensure download location exists (good practice, especially if using mount)
        try:
            os.makedirs(download_location, exist_ok=True)
        except OSError as e:
             return jsonify({"error": "Internal server error: Cannot access storage location."}), 500

        # Generate the SAS URL
        try:
            # Ensure CLIENTS dictionary and keys are correctly configured
            blob_service_client = CLIENTS.get("storage_account_office_docs_client")
            storage_account_key = settings.get("office_docs_key")
            storage_account_name = blob_service_client.account_name # Get from client

            if not all([blob_service_client, storage_account_key, container_name]):
                return jsonify({"error": "Internal server error: Storage access not configured."}), 500

            sas_token = generate_blob_sas(
                account_name=storage_account_name,
                container_name=container_name,
                blob_name=blob_name,
                account_key=storage_account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.utcnow() + timedelta(minutes=10) # Short expiry for view access
            )

            # Construct signed URL based on Azure environment
            endpoint_suffix = "blob.core.windows.net"
            if AZURE_ENVIRONMENT == "usgovernment":
                 endpoint_suffix = "blob.core.usgovcloudapi.net"
            if AZURE_ENVIRONMENT == "custom":
                endpoint_suffix = CUSTOM_BLOB_STORAGE_URL_VALUE

            signed_url = (
                f"https://{storage_account_name}.{endpoint_suffix}"
                f"/{container_name}/{blob_name}?{sas_token}"
            )

        except Exception as e:
            return jsonify({"error": "Internal server error: Could not authorize document access."}), 500

        # Define the target path within the download location
        random_uuid = str(uuid.uuid4())
        # Use a unique filename within the download location to avoid collisions
        local_file_name = f"{random_uuid}_{secure_filename(file_name)}" # Use secure_filename here too
        local_file_path = os.path.join(download_location, local_file_name)

        # Define supported types for direct viewing/handling
        is_pdf = file_ext == '.pdf'
        is_word = file_ext in ('.docx', '.doc')
        is_ppt = file_ext in ('.pptx', '.ppt')
        is_image = file_ext in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.gif', '.webp') # Added more image types
        is_text = file_ext in ('.txt', '.md', '.csv', '.json', '.log', '.xml', '.html', '.htm') # Common text-based types

        try:
            # Download the file to the specified location
            r = requests.get(signed_url, timeout=60)
            r.raise_for_status() # Raises HTTPError for bad responses (4xx or 5xx)
            with open(local_file_path, "wb") as f:
                f.write(r.content)

            # --- PDF Handling ---
            if is_pdf:
                pdf_document = None # Initialize
                extracted_pdf = None # Initialize
                try:
                    pdf_document = fitz.open(local_file_path)
                    total_pages = pdf_document.page_count
                    current_idx = page_number - 1 # PyMuPDF uses 0-based index

                    if current_idx < 0 or current_idx >= total_pages:
                        return jsonify({"error": f"Requested page ({page_number}) out of range (Total: {total_pages})"}), 400

                    # Determine pages to extract (+/- 1 page)
                    start_idx = max(0, current_idx - 1)
                    end_idx = min(total_pages - 1, current_idx + 1)

                    # Create new PDF with extracted pages
                    extracted_pdf = fitz.open() # Create a new empty PDF
                    extracted_pdf.insert_pdf(pdf_document, from_page=start_idx, to_page=end_idx)

                    # Save the extracted PDF back to the *same path*, overwriting original download
                    extracted_pdf.save(local_file_path, garbage=3, deflate=True) # garbage=3 is often sufficient

                    # Determine new page number within the sub-document (1-based for URL fragment)
                    # New index = original index - start index. Convert back to 1-based.
                    new_page_number = (current_idx - start_idx) + 1

                    # Send the processed (sub-)PDF from the download_location
                    response = send_file(local_file_path, as_attachment=False, mimetype='application/pdf')
                    response.headers["X-Sub-PDF-Page"] = str(new_page_number)
                    # File will be cleaned up in 'finally' block after response is sent
                    return response

                except Exception as pdf_error:
                     return jsonify({"error": "Failed to process PDF document"}), 500
                finally:
                    # Close PDF documents if they were opened
                    if extracted_pdf:
                        extracted_pdf.close()
                    if pdf_document:
                        pdf_document.close()
                    # Cleanup handled in the outer finally block


            # --- Image Handling (Send file directly) ---
            elif is_image:
                mimetype, _ = mimetypes.guess_type(local_file_path)
                if not mimetype:
                    mimetype = 'application/octet-stream' # Fallback generic type
                # File will be cleaned up in 'finally' block after response is sent
                return send_file(local_file_path, as_attachment=False, mimetype=mimetype)

            # --- Fallback for unsupported types, PPTX, DOCX, etc. ---
            elif is_word or is_ppt:
                # For Word/PPT, you might want to convert to PDF first or handle differently
                return jsonify({"error": f"Unsupported file type for viewing: {file_ext}"}), 415
            else:
                # Cleanup already downloaded file before returning error
                # (Cleanup is handled in finally, no need to remove here explicitly)
                return jsonify({"error": f"Unsupported file type for viewing: {file_ext}"}), 415


        except requests.exceptions.RequestException as e:
            # Handle download errors
            # No need to clean up here, 'finally' will handle it if file exists
            return jsonify({"error": "Failed to download document from storage"}), 500
        except fitz.fitz.FileNotFoundError: # More specific exception name
            # Specific error if fitz can't find the file (maybe deleted between download and open)
            return jsonify({"error": "Internal processing error: File access issue"}), 500
        except Exception as e:
            # General error handling
            # No need to clean up here, 'finally' will handle it
            return jsonify({"error": f"An internal error occurred processing the document."}), 500
        finally:
            # --- CRITICAL CLEANUP ---
            # Ensure the downloaded/processed file is removed after the request,
            # regardless of success or failure, unless send_file is streaming it
            # and handles cleanup itself (which it should for non-temporary files).
            # Double-check existence before removing.
            if os.path.exists(local_file_path):
                try:
                    os.remove(local_file_path)
                except OSError as e:
                    # Log error but don't prevent response from being sent
                    print(f"Error cleaning up file {local_file_path}: {e}")