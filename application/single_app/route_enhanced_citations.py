# route_enhanced_citations.py
# Backend endpoints for enhanced citations supporting different media types

from flask import jsonify, request, Response
from datetime import datetime, timedelta
import os
import tempfile
import requests
import mimetypes
import io

from functions_authentication import login_required, user_required, get_current_user_id
from functions_settings import get_settings, enabled_required
from functions_documents import get_document_metadata
from functions_group import get_user_groups
from functions_public_workspaces import get_user_visible_public_workspace_ids_from_settings
from swagger_wrapper import swagger_route, get_auth_security
from config import CLIENTS, storage_account_user_documents_container_name, storage_account_group_documents_container_name, storage_account_public_documents_container_name
from functions_debug import debug_print

def register_enhanced_citations_routes(app):
    """Register enhanced citations routes"""
    
    @app.route("/api/enhanced_citations/image", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_enhanced_citations")
    def get_enhanced_citation_image():
        """
        Serve image file content directly for enhanced citations
        """
        doc_id = request.args.get("doc_id")
        if not doc_id:
            return jsonify({"error": "doc_id is required"}), 400

        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401

        try:
            # Get document metadata
            doc_response, status_code = get_document(user_id, doc_id)
            if status_code != 200:
                return doc_response, status_code

            raw_doc = doc_response.get_json()
            
            # Check if it's an image file
            file_name = raw_doc['file_name']
            ext = file_name.lower().split('.')[-1] if '.' in file_name else ''
            image_extensions = ['jpg', 'jpeg', 'png', 'bmp', 'tiff', 'tif', 'heif']
            
            if ext not in image_extensions:
                return jsonify({"error": "File is not an image"}), 400

            # Serve the image content directly
            return serve_enhanced_citation_content(raw_doc)

        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/enhanced_citations/video", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_enhanced_citations")
    def get_enhanced_citation_video():
        """
        Serve video file content directly for enhanced citations
        """
        doc_id = request.args.get("doc_id")
        if not doc_id:
            return jsonify({"error": "doc_id is required"}), 400

        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401

        try:
            # Get document metadata
            doc_response, status_code = get_document(user_id, doc_id)
            if status_code != 200:
                return doc_response, status_code

            raw_doc = doc_response.get_json()
            
            # Check if it's a video file
            file_name = raw_doc['file_name']
            ext = file_name.lower().split('.')[-1] if '.' in file_name else ''
            video_extensions = ['mp4', 'mov', 'avi', 'mkv', 'flv', 'webm', 'wmv']
            
            if ext not in video_extensions:
                return jsonify({"error": "File is not a video"}), 400

            # Serve the video content directly
            return serve_enhanced_citation_content(raw_doc, content_type='video/mp4')

        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/enhanced_citations/audio", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_enhanced_citations")
    def get_enhanced_citation_audio():
        """
        Serve audio file content directly for enhanced citations
        """
        doc_id = request.args.get("doc_id")
        if not doc_id:
            return jsonify({"error": "doc_id is required"}), 400

        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401

        try:
            # Get document metadata
            doc_response, status_code = get_document(user_id, doc_id)
            if status_code != 200:
                return doc_response, status_code

            raw_doc = doc_response.get_json()
            
            # Check if it's an audio file
            file_name = raw_doc['file_name']
            ext = file_name.lower().split('.')[-1] if '.' in file_name else ''
            audio_extensions = ['mp3', 'wav', 'ogg', 'aac', 'flac', 'm4a']
            
            if ext not in audio_extensions:
                return jsonify({"error": "File is not an audio file"}), 400

            # Serve the audio content directly
            return serve_enhanced_citation_content(raw_doc, content_type='audio/mpeg')

        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/enhanced_citations/pdf", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_enhanced_citations")
    def get_enhanced_citation_pdf():
        """
        Serve PDF file content directly for enhanced citations with page extraction
        """
        doc_id = request.args.get("doc_id")
        page_number = request.args.get("page", default=1, type=int)
        show_all = request.args.get("show_all", "false").lower() in ['true', '1', 'yes']
        download = request.args.get("download", default=False, type=bool)
        
        if not doc_id:
            return jsonify({"error": "doc_id is required"}), 400

        debug_print(f"[DEBUG]:: Enhanced citations PDF request - doc_id: {doc_id}, page: {page_number}, show_all: {show_all}")

        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401

        try:
            # Get document metadata
            doc_response, status_code = get_document(user_id, doc_id)
            if status_code != 200:
                return doc_response, status_code

            raw_doc = doc_response.get_json()
            
            # Check if it's a PDF file
            file_name = raw_doc['file_name']
            ext = file_name.lower().split('.')[-1] if '.' in file_name else ''
            
            if ext != 'pdf':
                return jsonify({"error": "File is not a PDF"}), 400

            # For download, serve the original PDF without page extraction
            if download:
                return serve_enhanced_citation_content(raw_doc, content_type='application/pdf', force_download=True)
            
            # Serve the PDF content directly with page extraction logic
            return serve_enhanced_citation_pdf_content(raw_doc, page_number, show_all)

        except Exception as e:
            return jsonify({"error": str(e)}), 500

def get_document(user_id, doc_id):
    """
    Get document metadata - searches across all enabled workspace types
    """
    from functions_documents import get_document as backend_get_document
    from functions_settings import get_settings
    
    settings = get_settings()
    
    # Try to get document from different workspace types based on what's enabled
    # Start with personal workspace (most common)
    if settings.get('enable_user_workspace', False):
        try:
            doc_response, status_code = backend_get_document(user_id, doc_id)
            if status_code == 200:
                return doc_response, status_code
        except:
            pass
    
    # Try group workspaces if enabled
    if settings.get('enable_group_workspaces', False):
        # We need to find which group this document belongs to
        # This is more complex - we need to search across user's groups
        try:
            user_groups = get_user_groups(user_id)
            for group in user_groups:
                group_id = group.get('id')
                if group_id:
                    try:
                        doc_response, status_code = backend_get_document(user_id, doc_id, group_id=group_id)
                        if status_code == 200:
                            return doc_response, status_code
                    except:
                        continue
        except:
            pass
    
    # Try public workspaces if enabled
    if settings.get('enable_public_workspaces', False):
        # We need to find which public workspace this document belongs to
        # This requires checking user's accessible public workspaces
        try:
            accessible_workspace_ids = get_user_visible_public_workspace_ids_from_settings(user_id)
            for workspace_id in accessible_workspace_ids:
                try:
                    doc_response, status_code = backend_get_document(user_id, doc_id, public_workspace_id=workspace_id)
                    if status_code == 200:
                        return doc_response, status_code
                except:
                    continue
        except:
            pass
    
    # If document not found in any workspace
    return {"error": "Document not found or access denied"}, 404

def determine_workspace_type_and_container(raw_doc):
    """
    Determine workspace type and appropriate container based on document metadata
    """
    if raw_doc.get('public_workspace_id'):
        return 'public', storage_account_public_documents_container_name
    elif raw_doc.get('group_id'):
        return 'group', storage_account_group_documents_container_name
    else:
        return 'personal', storage_account_user_documents_container_name

def get_blob_name(raw_doc, workspace_type):
    """
    Determine the correct blob name based on workspace type
    """
    if workspace_type == 'public':
        return f"{raw_doc['public_workspace_id']}/{raw_doc['file_name']}"
    elif workspace_type == 'group':
        return f"{raw_doc['group_id']}/{raw_doc['file_name']}"
    else:
        return f"{raw_doc['user_id']}/{raw_doc['file_name']}"

def serve_enhanced_citation_content(raw_doc, content_type=None, force_download=False):
    """
    Server-side rendering: Serve enhanced citation file content directly
    Based on the logic from the existing view_pdf function but serves content directly
    """
    settings = get_settings()
    
    # Get blob storage client
    blob_service_client = CLIENTS.get("storage_account_office_docs_client")
    if not blob_service_client:
        raise Exception("Blob storage client not available")
    
    # Determine workspace type and container
    workspace_type, container_name = determine_workspace_type_and_container(raw_doc)
    container_client = blob_service_client.get_container_client(container_name)
    
    # Build blob name based on workspace type
    blob_name = get_blob_name(raw_doc, workspace_type)
    
    try:
        # Download blob content directly
        blob_client = container_client.get_blob_client(blob_name)
        blob_data = blob_client.download_blob()
        content = blob_data.readall()
        
        # Determine content type if not provided
        if not content_type:
            file_ext = os.path.splitext(raw_doc['file_name'])[-1].lower()
            content_type, _ = mimetypes.guess_type(raw_doc['file_name'])
            if not content_type:
                # Fallback content types
                if file_ext in ['.jpg', '.jpeg']:
                    content_type = 'image/jpeg'
                elif file_ext == '.png':
                    content_type = 'image/png'
                elif file_ext == '.pdf':
                    content_type = 'application/pdf'
                elif file_ext == '.mp4':
                    content_type = 'video/mp4'
                elif file_ext == '.mp3':
                    content_type = 'audio/mpeg'
                else:
                    content_type = 'application/octet-stream'
        
        # Set content disposition based on force_download parameter
        disposition = 'attachment' if force_download else 'inline'
        
        # Create Response with the blob content
        response = Response(
            content,
            content_type=content_type,
            headers={
                'Content-Length': str(len(content)),
                'Cache-Control': 'private, max-age=300',  # Cache for 5 minutes
                'Content-Disposition': f'{disposition}; filename="{raw_doc["file_name"]}"',
                'Accept-Ranges': 'bytes'  # Support range requests for video/audio
            }
        )
        
        return response
        
    except Exception as e:
        print(f"Error serving enhanced citation content: {e}")
        raise Exception(f"Failed to load content: {str(e)}")

def serve_enhanced_citation_pdf_content(raw_doc, page_number, show_all=False):
    """
    Serve PDF content with page extraction (±1 page logic from original view_pdf)
    Based on the logic from the existing view_pdf function but serves content directly
    
    Args:
        raw_doc: Document metadata
        page_number: Current page number
        show_all: If True, show all pages instead of just ±1 pages around current
    """
    debug_print(f"[DEBUG]:: serve_enhanced_citation_pdf_content called with show_all: {show_all}")
    
    import io
    import uuid
    import tempfile
    import fitz  # PyMuPDF
    
    blob_service_client = CLIENTS.get("storage_account_office_docs_client")
    if not blob_service_client:
        raise Exception("Blob storage client not available")
    
    # Determine workspace type and container
    workspace_type, container_name = determine_workspace_type_and_container(raw_doc)
    container_client = blob_service_client.get_container_client(container_name)
    
    # Build blob name based on workspace type
    blob_name = get_blob_name(raw_doc, workspace_type)
    
    try:
        # Download blob content directly
        blob_client = container_client.get_blob_client(blob_name)
        blob_data = blob_client.download_blob()
        content = blob_data.readall()
        
        # Create temporary file for PDF processing
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
            temp_file.write(content)
            temp_pdf_path = temp_file.name
        
        try:
            # Process PDF with page extraction logic (from original view_pdf)
            pdf_document = fitz.open(temp_pdf_path)
            total_pages = pdf_document.page_count
            current_idx = page_number - 1  # zero-based

            if current_idx < 0 or current_idx >= total_pages:
                pdf_document.close()
                os.remove(temp_pdf_path)
                return jsonify({"error": "Requested page out of range"}), 400

            if show_all:
                # Show all pages
                start_idx = 0
                end_idx = total_pages - 1
                new_page_number = page_number  # Keep original page number
            else:
                # Default to just the current page
                start_idx = current_idx
                end_idx = current_idx

                # If a previous page exists, include it
                if current_idx > 0:
                    start_idx = current_idx - 1

                # If a next page exists, include it
                if current_idx < total_pages - 1:
                    end_idx = current_idx + 1

                # Determine new_page_number (within the sub-document)
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

            # Create new PDF with only start_idx..end_idx
            extracted_pdf = fitz.open()
            extracted_pdf.insert_pdf(pdf_document, from_page=start_idx, to_page=end_idx)
            
            # Save extracted PDF to memory
            extracted_content = extracted_pdf.tobytes()
            extracted_pdf.close()
            pdf_document.close()

            # Return the extracted PDF
            headers = {
                'Content-Length': str(len(extracted_content)),
                'Cache-Control': 'private, max-age=300',  # Cache for 5 minutes
                'Content-Disposition': f'inline; filename="{raw_doc["file_name"]}"',
                'X-Sub-PDF-Page': str(new_page_number),  # Custom header with page info
                'Accept-Ranges': 'bytes'
            }
            
            # When show_all is True, allow iframe embedding
            if show_all:
                debug_print(f"[DEBUG]:: Setting CSP headers for iframe embedding (show_all={show_all})")
                headers['Content-Security-Policy'] = (
                    "default-src 'self'; "
                    "frame-ancestors 'self'; "  # Allow embedding in same origin
                    "object-src 'none';"
                )
                headers['X-Frame-Options'] = 'SAMEORIGIN'  # Allow same-origin framing
            else:
                debug_print(f"[DEBUG]:: NOT setting CSP headers for iframe embedding (show_all={show_all})")
            
            response = Response(
                extracted_content,
                content_type='application/pdf',
                headers=headers
            )
            return response
            
        finally:
            # Clean up temporary file
            if os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)
        
    except Exception as e:
        print(f"Error serving PDF citation content: {e}")
        raise Exception(f"Failed to load PDF content: {str(e)}")
