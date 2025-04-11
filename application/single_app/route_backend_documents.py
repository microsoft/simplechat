# route_backend_documents.py

from config import *
from functions_authentication import *
from functions_documents import *
from functions_settings import *

def register_route_backend_documents(app):
    @app.route('/api/get_file_content', methods=['POST'])
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def get_file_content():
        data = request.get_json()
        user_id = get_current_user_id()
        conversation_id = data.get('conversation_id')
        file_id = data.get('file_id')

        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        if not conversation_id or not file_id:
            return jsonify({'error': 'Missing conversation_id or file_id'}), 400

        try:
            conversation_item = container.read_item(
                item=conversation_id,
                partition_key=conversation_id
            )
            messages = conversation_item.get('messages', [])
            for message in messages:
                if message.get('role') == 'file' and message.get('file_id') == file_id:
                    file_content = message.get('file_content')
                    filename = message.get('filename')
                    is_table = message.get('is_table', False)
                    if file_content:
                        return jsonify({
                            'file_content': file_content,
                            'filename': filename,
                            'is_table': is_table
                        }), 200
                    else:
                        return jsonify({'error': 'File content not found'}), 404

            return jsonify({'error': 'File not found in conversation'}), 404

        except Exception as e:
            return jsonify({'error': 'Error retrieving file content'}), 500
    
    @app.route('/api/documents/upload', methods=['POST'])
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def upload_document():
        user_id = get_current_user_id()
        settings = get_settings()

        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400

        file = request.files['file']
        if not file.filename:
            return jsonify({'error': 'No selected file'}), 400

        file.seek(0, os.SEEK_END)
        file_length = file.tell()
        max_file_size_bytes = settings.get('max_file_size_mb', 16) * 1024 * 1024
        if file_length > max_file_size_bytes:
            return jsonify({'error': 'File size exceeds maximum allowed size'}), 400
        file.seek(0)
        
        filename = secure_filename(file.filename)
        file_ext = os.path.splitext(filename)[1].lower()
        # Log the filename and file extension
        print(f"Filename: {filename}")
        print(f"File Extension: {file_ext}")
        
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            file.save(tmp_file.name)
            temp_file_path = tmp_file.name

        # Log the temporary file path
        print(f"Temporary File Path: {temp_file_path}")

        extracted_content  = ''
        try:
            if file_ext in ['.pdf', '.docx', '.xlsx', '.pptx', '.html', '.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.heif']:
                extracted_content  = extract_content_with_azure_di(temp_file_path)
            elif file_ext == '.txt':
                extracted_content  = extract_text_file(temp_file_path)
            elif file_ext == '.md':
                extracted_content  = extract_markdown_file(temp_file_path)
            elif file_ext == '.json':
                with open(temp_file_path, 'r', encoding='utf-8') as f:
                    extracted_content  = json.dumps(json.load(f))
            else:
                return jsonify({'error': 'Unsupported file type'}), 400

        except Exception as e:
            return jsonify({'error': f'Error processing file: {str(e)}'}), 500
        finally:
            os.remove(temp_file_path)

        try:
            process_document_and_store_chunks(extracted_content , filename, user_id)
        except Exception as e:
            return jsonify({'error': f'Error processing document: {str(e)}'}), 500

        return jsonify({'message': 'Document uploaded and processed successfully'}), 200

    @app.route('/api/documents', methods=['GET'])
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def api_get_user_documents():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
                
        return get_user_documents(user_id)

    @app.route('/api/documents/<document_id>', methods=['GET'])
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def api_get_user_document(document_id):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        return get_user_document(user_id, document_id)

    @app.route('/api/documents/<document_id>', methods=['DELETE'])
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def api_delete_user_document(document_id):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            delete_user_document(user_id, document_id)
            delete_user_document_chunks(document_id)
            return jsonify({'message': 'Document deleted successfully'}), 200
        except Exception as e:
            return jsonify({'error': f'Error deleting document: {str(e)}'}), 500
        
    @app.route("/api/get_citation", methods=["POST"])
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def get_citation():
        data = request.get_json()
        user_id = get_current_user_id()
        citation_id = data.get("citation_id")

        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401
                
        if not citation_id:
            return jsonify({"error": "Missing citation_id"}), 400

        try:
            search_client_user = CLIENTS['search_client_user']
            chunk = search_client_user.get_document(key=citation_id)
            if chunk.get("user_id") != user_id:
                return jsonify({"error": "Unauthorized access to citation"}), 403

            return jsonify({
                "cited_text": chunk.get("chunk_text", ""),
                "file_name": chunk.get("file_name", ""),
                "page_number": chunk.get("chunk_sequence", 0)
            }), 200

        except ResourceNotFoundError:
            pass

        try:
            search_client_group = CLIENTS['search_client_group']
            group_chunk = search_client_group.get_document(key=citation_id)

            return jsonify({
                "cited_text": group_chunk.get("chunk_text", ""),
                "file_name": group_chunk.get("file_name", ""),
                "page_number": group_chunk.get("chunk_sequence", 0)
            }), 200

        except ResourceNotFoundError:
            return jsonify({"error": "Citation not found in user or group docs"}), 404

        except Exception as e:
            return jsonify({"error": f"Unexpected error: {str(e)}"}), 500
