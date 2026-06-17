# route_enhanced_citations.py
# Backend endpoints for enhanced citations supporting different media types

from flask import jsonify, request, Response
from datetime import datetime, timedelta, timezone
import logging
import os
import tempfile
import requests
import mimetypes
import io
import uuid
from urllib.parse import quote
import pandas
import fitz
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from werkzeug.utils import secure_filename

from functions_authentication import login_required, user_required, get_current_user_id, get_current_user_info
from functions_appinsights import log_event
from functions_settings import get_settings, enabled_required
from functions_documents import create_document, get_document_blob_storage_info, update_document
from functions_visio import render_vsdx_page_preview
from functions_group import check_group_status_allows_operation, find_group_by_id, get_user_groups, require_active_group
from functions_notifications import create_group_notification, create_notification, create_public_workspace_notification
from functions_public_workspaces import check_public_workspace_status_allows_operation, get_user_visible_public_workspace_ids_from_settings, require_active_public_workspace
from functions_simplechat_operations import download_blob_content, upload_generated_document_for_current_user
from swagger_wrapper import swagger_route, get_auth_security
from config import CLIENTS, storage_account_user_documents_container_name, storage_account_group_documents_container_name, storage_account_public_documents_container_name, storage_account_personal_chat_container_name, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, AUDIO_EXTENSIONS, TABULAR_EXTENSIONS, VISIO_EXTENSIONS, cosmos_messages_container, cosmos_conversations_container
from functions_debug import debug_print


def _get_authorized_chat_artifact_message(user_id, conversation_id, message_id):
    normalized_conversation_id = str(conversation_id or '').strip()
    normalized_message_id = str(message_id or '').strip()
    if not normalized_conversation_id or not normalized_message_id:
        raise ValueError('conversation_id and message_id are required')

    try:
        conversation_item = cosmos_conversations_container.read_item(
            item=normalized_conversation_id,
            partition_key=normalized_conversation_id,
        )
    except CosmosResourceNotFoundError as exc:
        raise LookupError('Conversation not found') from exc

    if str(conversation_item.get('user_id') or '').strip() != str(user_id or '').strip():
        raise PermissionError('Forbidden')

    try:
        message_item = cosmos_messages_container.read_item(
            item=normalized_message_id,
            partition_key=normalized_conversation_id,
        )
    except CosmosResourceNotFoundError as exc:
        raise LookupError('Chat artifact not found') from exc

    metadata = message_item.get('metadata', {}) or {}
    if message_item.get('role') != 'file' or not metadata.get('is_generated_chat_artifact', False):
        raise LookupError('Chat artifact not found')

    if str(message_item.get('file_content_source') or '').strip().lower() != 'blob':
        raise LookupError('Chat artifact content is unavailable')

    if not str(message_item.get('blob_container') or '').strip() or not str(message_item.get('blob_path') or '').strip():
        raise LookupError('Chat artifact content is unavailable')

    return message_item


def _sanitize_tabular_preview_value(value):
    """Convert pandas preview values into JSON-safe display strings."""
    if hasattr(value, 'item') and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass

    if value is None:
        return ''

    if pandas.api.types.is_scalar(value):
        try:
            if pandas.isna(value):
                return ''
        except (TypeError, ValueError):
            pass

    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')

    if hasattr(value, 'isoformat') and not isinstance(value, str):
        try:
            return value.isoformat()
        except TypeError:
            pass

    return str(value)


def _serialize_tabular_preview_table(df_preview):
    """Build JSON-safe tabular preview payload pieces for the browser."""
    columns = [
        _sanitize_tabular_preview_value(column)
        for column in df_preview.columns.tolist()
    ]
    rows = [
        [_sanitize_tabular_preview_value(cell) for cell in row]
        for row in df_preview.itertuples(index=False, name=None)
    ]
    return columns, rows


def _resolve_document_blob_reference(raw_doc):
    """Resolve the persisted blob container and path for the cited document."""
    container_name, blob_name = get_document_blob_storage_info(raw_doc)
    if not container_name or not blob_name:
        raise FileNotFoundError("Blob reference is incomplete for this document")
    return container_name, blob_name


def _normalize_generated_artifact_target_scope(raw_scope):
    normalized_scope = str(raw_scope or "personal").strip().lower()
    if normalized_scope not in {"personal", "group", "public"}:
        raise ValueError("workspace_scope must be 'personal', 'group', or 'public'")
    return normalized_scope


def _build_workspace_generated_artifact_file_name(file_name, artifact_message_id):
    normalized_file_name = str(file_name or "").replace("\\", "/").split("/")[-1].strip()
    if not normalized_file_name:
        normalized_file_name = "generated-artifact.json"

    base_name, extension = os.path.splitext(normalized_file_name)
    normalized_base_name = base_name.strip() or "generated-artifact"
    normalized_extension = extension or ".json"
    suffix = str(artifact_message_id or "").strip()[-6:] or uuid.uuid4().hex[:6]
    return f"{normalized_base_name} (artifact {suffix}){normalized_extension}"


def _resolve_generated_artifact_file_name(message_item):
    """Resolve the best workspace/download filename for a generated chat artifact."""
    message_item = message_item if isinstance(message_item, dict) else {}
    raw_file_name = str(message_item.get("filename") or "generated-artifact.json").strip() or "generated-artifact.json"
    normalized_file_name = raw_file_name.replace("\\", "/").split("/")[-1].strip() or "generated-artifact.json"
    metadata = message_item.get("metadata", {}) if isinstance(message_item.get("metadata", {}), dict) else {}
    output_format = str(metadata.get("generated_artifact_output_format") or "").strip().lower().lstrip(".")
    output_extension = {
        "csv": ".csv",
        "json": ".json",
        "markdown": ".md",
        "md": ".md",
    }.get(output_format)

    if not output_extension:
        return normalized_file_name

    base_name, current_extension = os.path.splitext(normalized_file_name)
    normalized_current_extension = current_extension.lower()
    if normalized_current_extension == output_extension:
        return normalized_file_name

    if normalized_current_extension in {"", ".json"} and output_extension != ".json":
        normalized_base_name = base_name.strip() or "generated-artifact"
        return f"{normalized_base_name}{output_extension}"

    return normalized_file_name


def _normalize_response_file_name(file_name, fallback='download'):
    normalized_file_name = str(file_name or fallback).replace('\\', '/').split('/')[-1].strip()
    normalized_file_name = normalized_file_name.replace('\r', '').replace('\n', '')
    if not normalized_file_name:
        normalized_file_name = fallback

    ascii_file_name = secure_filename(normalized_file_name) or secure_filename(str(fallback)) or 'download'
    return normalized_file_name, ascii_file_name


def _build_content_disposition(disposition, file_name, fallback='download'):
    normalized_disposition = 'attachment' if disposition == 'attachment' else 'inline'
    normalized_file_name, ascii_file_name = _normalize_response_file_name(file_name, fallback=fallback)
    encoded_file_name = quote(normalized_file_name, safe='')
    return f'{normalized_disposition}; filename="{ascii_file_name}"; filename*=UTF-8\'\'{encoded_file_name}'


def _log_enhanced_citations_debug(message, **details):
    """Write debug-gated enhanced citations diagnostics."""
    log_event(
        f"[EnhancedCitations] {message}",
        extra=details or None,
        debug_only=True,
        category="EnhancedCitations",
    )


def _log_enhanced_citations_error(message, error, **details):
    """Write structured error diagnostics for enhanced citations failures."""
    error_details = dict(details)
    error_details["error"] = str(error)
    log_event(
        f"[EnhancedCitations] {message}",
        extra=error_details,
        level=logging.ERROR,
        exceptionTraceback=True,
    )


def register_enhanced_citations_routes(app):
    """Register enhanced citations routes"""

    @app.route("/api/enhanced_citations/document_metadata", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_enhanced_citations")
    def get_enhanced_citation_document_metadata():
        """
        Return minimal document metadata for an exact historical or current doc_id.
        This lets the chat UI render enhanced citations even when the cited
        document revision is not part of the currently loaded workspace list.
        """
        doc_id = request.args.get("doc_id")
        if not doc_id:
            return jsonify({"error": "doc_id is required"}), 400

        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401

        try:
            doc_response, status_code = get_document(user_id, doc_id)
            if status_code != 200:
                return doc_response, status_code

            raw_doc = doc_response.get_json()
            return jsonify({
                "id": raw_doc.get("id"),
                "document_id": raw_doc.get("id"),
                "file_name": raw_doc.get("file_name"),
                "version": raw_doc.get("version"),
                "is_current_version": raw_doc.get("is_current_version"),
                "enhanced_citations": bool(raw_doc.get("enhanced_citations", False)),
            }), 200

        except Exception as e:
            debug_print(f"Error getting enhanced citation document metadata: {e}")
            return jsonify({"error": str(e)}), 500
    
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
            
            if ext not in IMAGE_EXTENSIONS:
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
            
            if ext not in VIDEO_EXTENSIONS:
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
            
            if ext not in AUDIO_EXTENSIONS:
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

        _log_enhanced_citations_debug(
            "PDF request received",
            doc_id=doc_id,
            page=page_number,
            show_all=show_all,
            download=download,
        )

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
            _log_enhanced_citations_error(
                "PDF request failed",
                e,
                doc_id=doc_id,
                page=page_number,
                show_all=show_all,
                download=download,
            )
            return jsonify({"error": str(e)}), 500

    @app.route("/api/enhanced_citations/tabular", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_enhanced_citations")
    def get_enhanced_citation_tabular():
        """
        Serve original tabular file (CSV, XLSX, etc.) from blob storage for download.
        Used for chat-uploaded tabular files stored in blob storage.
        """
        conversation_id = request.args.get("conversation_id")
        file_id = request.args.get("file_id")

        if not conversation_id or not file_id:
            return jsonify({"error": "conversation_id and file_id are required"}), 400

        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401

        try:
            # Verify the current user owns the conversation
            try:
                conversation = cosmos_conversations_container.read_item(
                    item=conversation_id,
                    partition_key=conversation_id
                )
            except Exception:
                return jsonify({"error": "Conversation not found"}), 404

            if conversation.get('user_id') != user_id:
                return jsonify({"error": "Forbidden"}), 403

            # Look up the file message in Cosmos to get blob reference
            query_str = """
                SELECT * FROM c
                WHERE c.conversation_id = @conversation_id
                AND c.id = @file_id
            """
            items = list(cosmos_messages_container.query_items(
                query=query_str,
                parameters=[
                    {'name': '@conversation_id', 'value': conversation_id},
                    {'name': '@file_id', 'value': file_id}
                ],
                partition_key=conversation_id
            ))

            if not items:
                return jsonify({"error": "File not found"}), 404

            file_msg = items[0]
            file_content_source = file_msg.get('file_content_source', '')

            if file_content_source != 'blob':
                return jsonify({"error": "File is not stored in blob storage"}), 400

            blob_container = file_msg.get('blob_container', '')
            blob_path = file_msg.get('blob_path', '')
            filename = file_msg.get('filename', 'download')

            if not blob_container or not blob_path:
                return jsonify({"error": "Blob reference is incomplete"}), 500

            blob_service_client = CLIENTS.get("storage_account_office_docs_client")
            if not blob_service_client:
                return jsonify({"error": "Storage not available"}), 500

            blob_client = blob_service_client.get_blob_client(
                container=blob_container,
                blob=blob_path
            )
            stream = blob_client.download_blob()
            content = stream.readall()

            # Determine content type
            content_type, _ = mimetypes.guess_type(filename)
            if not content_type:
                content_type = 'application/octet-stream'

            return Response(
                content,
                content_type=content_type,
                headers={
                    'Content-Length': str(len(content)),
                    'Content-Disposition': _build_content_disposition('attachment', filename),
                    'Cache-Control': 'private, max-age=300',
                }
            )

        except Exception as e:
            debug_print(f"Error serving tabular citation: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/enhanced_citations/tabular_workspace", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_enhanced_citations")
    def get_enhanced_citation_tabular_workspace():
        """
        Serve tabular file (CSV, XLSX, etc.) from blob storage for workspace documents.
        Uses doc_id to look up the document across personal, group, and public workspaces.
        """
        doc_id = request.args.get("doc_id")
        if not doc_id:
            return jsonify({"error": "doc_id is required"}), 400

        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401

        try:
            doc_response, status_code = get_document(user_id, doc_id)
            if status_code != 200:
                return doc_response, status_code

            raw_doc = doc_response.get_json()
            file_name = raw_doc.get('file_name', '')
            ext = file_name.lower().split('.')[-1] if '.' in file_name else ''

            if ext not in ('csv', 'xlsx', 'xls', 'xlsm'):
                return jsonify({"error": "File is not a tabular file"}), 400

            return serve_enhanced_citation_content(raw_doc, force_download=True)

        except Exception as e:
            debug_print(f"Error serving tabular workspace citation: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/workspace_documents/download", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def download_workspace_document():
        """Serve an authorized workspace document blob as a direct download."""
        doc_id = request.args.get("doc_id")
        if not doc_id:
            return jsonify({"error": "doc_id is required"}), 400

        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401

        try:
            doc_response, status_code = get_document(user_id, doc_id)
            if status_code != 200:
                return doc_response, status_code

            raw_doc = doc_response.get_json()
            return serve_enhanced_citation_content(raw_doc, force_download=True)
        except Exception as e:
            debug_print(f"Error serving workspace document download: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/chat_artifacts/download", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def download_chat_artifact():
        """Serve an authorized generated chat artifact as a direct download."""
        conversation_id = request.args.get("conversation_id")
        message_id = request.args.get("message_id")
        if not conversation_id or not message_id:
            return jsonify({"error": "conversation_id and message_id are required"}), 400

        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401

        try:
            message_item = _get_authorized_chat_artifact_message(user_id, conversation_id, message_id)
            return serve_enhanced_citation_content(
                {
                    'file_name': _resolve_generated_artifact_file_name(message_item),
                    'blob_container': message_item.get('blob_container'),
                    'blob_path': message_item.get('blob_path'),
                },
                force_download=True,
            )
        except PermissionError:
            return jsonify({"error": "Forbidden"}), 403
        except LookupError as exc:
            return jsonify({"error": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as e:
            debug_print(f"Error serving chat artifact download: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/chat_artifacts/promote", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def promote_chat_artifact_to_workspace():
        """Promote a generated chat artifact into a workspace document."""
        payload = request.get_json(silent=True) or {}
        conversation_id = str(payload.get("conversation_id") or "").strip()
        message_id = str(payload.get("message_id") or "").strip()

        if not conversation_id or not message_id:
            return jsonify({"error": "conversation_id and message_id are required"}), 400

        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401

        current_user_info = get_current_user_info() or {}

        try:
            workspace_scope = _normalize_generated_artifact_target_scope(payload.get("workspace_scope"))
            message_item = _get_authorized_chat_artifact_message(user_id, conversation_id, message_id)

            file_name = _resolve_generated_artifact_file_name(message_item)
            artifact_metadata = message_item.get("metadata", {}) or {}
            source_blob_container = str(message_item.get("blob_container") or "").strip()
            source_blob_path = str(message_item.get("blob_path") or "").strip()

            if workspace_scope == "personal":
                artifact_bytes = download_blob_content(source_blob_container, source_blob_path)
                upload_result = upload_generated_document_for_current_user(
                    file_name=file_name,
                    file_content=artifact_bytes,
                    workspace_scope="personal",
                )
                return jsonify({
                    "message": "Generated artifact added to your personal workspace.",
                    "workspace_scope": "personal",
                    "approval_required": False,
                    "document": upload_result.get("document"),
                }), 200

            requester_display_name = (
                str(current_user_info.get("displayName") or "").strip()
                or str(current_user_info.get("email") or "").strip()
                or "A workspace member"
            )
            request_timestamp = datetime.now(timezone.utc).isoformat()
            pending_file_name = _build_workspace_generated_artifact_file_name(file_name, message_id)
            document_id = str(uuid.uuid4())

            if workspace_scope == "group":
                requested_group_id = str(payload.get("group_id") or "").strip()
                resolved_group_id = require_active_group(
                    user_id,
                    allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
                )
                if requested_group_id and requested_group_id != resolved_group_id:
                    raise PermissionError("Target group does not match your authorized active group")

                group_doc = find_group_by_id(resolved_group_id)
                if not group_doc:
                    raise LookupError("Group not found")

                allowed, reason = check_group_status_allows_operation(group_doc, "upload")
                if not allowed:
                    raise PermissionError(reason)

                group_name = str(group_doc.get("name") or "group workspace").strip() or "group workspace"

                create_document(
                    file_name=pending_file_name,
                    group_id=resolved_group_id,
                    user_id=user_id,
                    document_id=document_id,
                    num_file_chunks=0,
                    status="Pending approval",
                )
                update_document(
                    document_id=document_id,
                    user_id=user_id,
                    group_id=resolved_group_id,
                    percentage_complete=0,
                    generated_artifact_promotion_status="pending_approval",
                    generated_artifact_original_file_name=file_name,
                    generated_artifact_source_conversation_id=conversation_id,
                    generated_artifact_source_message_id=message_id,
                    generated_artifact_source_blob_container=source_blob_container,
                    generated_artifact_source_blob_path=source_blob_path,
                    generated_artifact_requested_by_user_id=user_id,
                    generated_artifact_requested_by_display_name=requester_display_name,
                    generated_artifact_requested_at=request_timestamp,
                    generated_artifact_capability=str(artifact_metadata.get("generated_artifact_capability") or "").strip(),
                    generated_artifact_output_format=str(artifact_metadata.get("generated_artifact_output_format") or "").strip(),
                    generated_artifact_summary=str(artifact_metadata.get("generated_artifact_summary") or "").strip(),
                )

                create_group_notification(
                    resolved_group_id,
                    "approval_request_pending",
                    "Approval required: generated artifact",
                    f"{requester_display_name} requested approval for {pending_file_name} in {group_name}.",
                    link_url="/group_workspaces",
                    link_context={
                        "workspace_type": "group",
                        "group_id": resolved_group_id,
                        "document_id": document_id,
                    },
                    metadata={
                        "document_id": document_id,
                        "group_id": resolved_group_id,
                        "request_type": "generated_artifact_promotion",
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                    },
                )
                create_notification(
                    user_id=user_id,
                    notification_type="approval_request_pending_submitter",
                    title="Generated artifact submitted for approval",
                    message=f"{pending_file_name} is waiting for approval in {group_name}.",
                    link_url="/group_workspaces",
                    link_context={
                        "workspace_type": "group",
                        "group_id": resolved_group_id,
                        "document_id": document_id,
                    },
                    metadata={
                        "document_id": document_id,
                        "group_id": resolved_group_id,
                        "request_type": "generated_artifact_promotion",
                    },
                )

                return jsonify({
                    "message": f"Generated artifact submitted to {group_name} for approval.",
                    "workspace_scope": "group",
                    "approval_required": True,
                    "group_id": resolved_group_id,
                    "document": {
                        "id": document_id,
                        "file_name": pending_file_name,
                        "status": "Pending approval",
                    },
                }), 202

            requested_public_workspace_id = str(payload.get("public_workspace_id") or "").strip()
            resolved_public_workspace_id, workspace_doc, _ = require_active_public_workspace(user_id)
            if requested_public_workspace_id and requested_public_workspace_id != resolved_public_workspace_id:
                raise PermissionError("Target public workspace does not match your authorized active workspace")

            allowed, reason = check_public_workspace_status_allows_operation(workspace_doc, "upload")
            if not allowed:
                raise PermissionError(reason)

            workspace_name = str(workspace_doc.get("name") or "public workspace").strip() or "public workspace"

            create_document(
                file_name=pending_file_name,
                public_workspace_id=resolved_public_workspace_id,
                user_id=user_id,
                document_id=document_id,
                num_file_chunks=0,
                status="Pending approval",
            )
            update_document(
                document_id=document_id,
                user_id=user_id,
                public_workspace_id=resolved_public_workspace_id,
                percentage_complete=0,
                generated_artifact_promotion_status="pending_approval",
                generated_artifact_original_file_name=file_name,
                generated_artifact_source_conversation_id=conversation_id,
                generated_artifact_source_message_id=message_id,
                generated_artifact_source_blob_container=source_blob_container,
                generated_artifact_source_blob_path=source_blob_path,
                generated_artifact_requested_by_user_id=user_id,
                generated_artifact_requested_by_display_name=requester_display_name,
                generated_artifact_requested_at=request_timestamp,
                generated_artifact_capability=str(artifact_metadata.get("generated_artifact_capability") or "").strip(),
                generated_artifact_output_format=str(artifact_metadata.get("generated_artifact_output_format") or "").strip(),
                generated_artifact_summary=str(artifact_metadata.get("generated_artifact_summary") or "").strip(),
            )

            create_public_workspace_notification(
                resolved_public_workspace_id,
                "approval_request_pending",
                "Approval required: generated artifact",
                f"{requester_display_name} requested approval for {pending_file_name} in {workspace_name}.",
                link_url="/public_workspaces",
                link_context={
                    "workspace_type": "public",
                    "public_workspace_id": resolved_public_workspace_id,
                    "document_id": document_id,
                },
                metadata={
                    "document_id": document_id,
                    "public_workspace_id": resolved_public_workspace_id,
                    "request_type": "generated_artifact_promotion",
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                },
            )
            create_notification(
                user_id=user_id,
                notification_type="approval_request_pending_submitter",
                title="Generated artifact submitted for approval",
                message=f"{pending_file_name} is waiting for approval in {workspace_name}.",
                link_url="/public_workspaces",
                link_context={
                    "workspace_type": "public",
                    "public_workspace_id": resolved_public_workspace_id,
                    "document_id": document_id,
                },
                metadata={
                    "document_id": document_id,
                    "public_workspace_id": resolved_public_workspace_id,
                    "request_type": "generated_artifact_promotion",
                },
            )

            return jsonify({
                "message": f"Generated artifact submitted to {workspace_name} for approval.",
                "workspace_scope": "public",
                "approval_required": True,
                "public_workspace_id": resolved_public_workspace_id,
                "document": {
                    "id": document_id,
                    "file_name": pending_file_name,
                    "status": "Pending approval",
                },
            }), 202
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403
        except LookupError as exc:
            return jsonify({"error": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as e:
            debug_print(f"Error promoting chat artifact: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/enhanced_citations/tabular_preview", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_enhanced_citations")
    def get_enhanced_citation_tabular_preview():
        """
        Return JSON preview of a tabular file for rendering as an HTML table.
        Reads the file into a pandas DataFrame and returns columns + rows as JSON.
        """
        doc_id = request.args.get("doc_id")
        sheet_name = request.args.get("sheet_name")
        sheet_index = request.args.get("sheet_index")
        max_rows = min(request.args.get("max_rows", 200, type=int), 500)
        if not doc_id:
            return jsonify({"error": "doc_id is required"}), 400

        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401

        try:
            doc_response, status_code = get_document(user_id, doc_id)
            if status_code != 200:
                return doc_response, status_code

            raw_doc = doc_response.get_json()
            file_name = raw_doc.get('file_name', '')
            ext = file_name.lower().rsplit('.', 1)[-1] if '.' in file_name else ''
            if ext not in ('csv', 'xlsx', 'xls', 'xlsm'):
                return jsonify({"error": "File is not a tabular file"}), 400

            # Download blob with size cap to protect memory
            settings = get_settings()
            max_blob_size = int(settings.get('tabular_preview_max_blob_size_mb', 200)) * 1024 * 1024
            blob_service_client = CLIENTS.get("storage_account_office_docs_client")
            if not blob_service_client:
                return jsonify({"error": "Blob storage client not available"}), 500
            container_name, blob_name = _resolve_document_blob_reference(raw_doc)
            blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)
            blob_props = blob_client.get_blob_properties()
            if blob_props.size > max_blob_size:
                return jsonify({"error": "File is too large to preview"}), 400
            data = blob_client.download_blob().readall()

            # Read into DataFrame, limiting rows for preview efficiency
            # Read max_rows + 1 so we can detect truncation without loading the full file
            nrows_limit = max_rows + 1
            selected_sheet = None
            sheet_names = []
            if ext == 'csv':
                df = pandas.read_csv(io.BytesIO(data), keep_default_na=False, dtype=str, nrows=nrows_limit)
            elif ext in ('xlsx', 'xlsm'):
                excel_file = pandas.ExcelFile(io.BytesIO(data), engine='openpyxl')
                sheet_names = list(excel_file.sheet_names)
                if not sheet_names:
                    return jsonify({"error": "Workbook does not contain any readable sheets"}), 400

                if sheet_name:
                    requested_sheet_name = sheet_name.strip()
                    matching_sheet_name = next(
                        (candidate for candidate in sheet_names if candidate.lower() == requested_sheet_name.lower()),
                        None,
                    )
                    if not matching_sheet_name:
                        return jsonify({
                            "error": f"Sheet '{requested_sheet_name}' was not found. Available sheets: {sheet_names}"
                        }), 400
                    selected_sheet = matching_sheet_name
                elif sheet_index not in (None, ''):
                    try:
                        resolved_sheet_index = int(sheet_index)
                    except ValueError:
                        return jsonify({"error": "sheet_index must be an integer"}), 400
                    if resolved_sheet_index < 0 or resolved_sheet_index >= len(sheet_names):
                        return jsonify({
                            "error": f"sheet_index {resolved_sheet_index} is out of range. Available sheets: {sheet_names}"
                        }), 400
                    selected_sheet = sheet_names[resolved_sheet_index]
                else:
                    selected_sheet = sheet_names[0]

                df = excel_file.parse(selected_sheet, keep_default_na=False, dtype=str, nrows=nrows_limit)
            elif ext == 'xls':
                excel_file = pandas.ExcelFile(io.BytesIO(data), engine='xlrd')
                sheet_names = list(excel_file.sheet_names)
                if not sheet_names:
                    return jsonify({"error": "Workbook does not contain any readable sheets"}), 400

                if sheet_name:
                    requested_sheet_name = sheet_name.strip()
                    matching_sheet_name = next(
                        (candidate for candidate in sheet_names if candidate.lower() == requested_sheet_name.lower()),
                        None,
                    )
                    if not matching_sheet_name:
                        return jsonify({
                            "error": f"Sheet '{requested_sheet_name}' was not found. Available sheets: {sheet_names}"
                        }), 400
                    selected_sheet = matching_sheet_name
                elif sheet_index not in (None, ''):
                    try:
                        resolved_sheet_index = int(sheet_index)
                    except ValueError:
                        return jsonify({"error": "sheet_index must be an integer"}), 400
                    if resolved_sheet_index < 0 or resolved_sheet_index >= len(sheet_names):
                        return jsonify({
                            "error": f"sheet_index {resolved_sheet_index} is out of range. Available sheets: {sheet_names}"
                        }), 400
                    selected_sheet = sheet_names[resolved_sheet_index]
                else:
                    selected_sheet = sheet_names[0]

                df = excel_file.parse(selected_sheet, keep_default_na=False, dtype=str, nrows=nrows_limit)
            else:
                return jsonify({"error": f"Unsupported file type: {ext}"}), 400

            total_rows = len(df)
            truncated = total_rows > max_rows
            preview = df.head(max_rows)
            columns, rows = _serialize_tabular_preview_table(preview)

            return jsonify({
                "filename": file_name,
                "selected_sheet": selected_sheet,
                "sheet_names": sheet_names,
                "sheet_count": len(sheet_names),
                "total_rows": total_rows if not truncated else None,
                "total_columns": len(df.columns),
                "columns": columns,
                "rows": rows,
                "truncated": truncated
            })

        except Exception as e:
            debug_print(f"Error generating tabular preview: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/enhanced_citations/visio", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_enhanced_citations")
    def get_enhanced_citation_visio_preview():
        """Return a PNG preview for a Visio page or download the original VSDX."""
        doc_id = request.args.get("doc_id")
        page_number = request.args.get("page", 1, type=int)
        force_download = str(request.args.get("download", "")).lower() == "true"

        if not doc_id:
            return jsonify({"error": "doc_id is required"}), 400

        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401

        if not page_number or page_number < 1:
            return jsonify({"error": "page must be a positive integer"}), 400

        try:
            doc_response, status_code = get_document(user_id, doc_id)
            if status_code != 200:
                return doc_response, status_code

            raw_doc = doc_response.get_json()
            file_name = raw_doc.get('file_name', '')
            ext = file_name.lower().rsplit('.', 1)[-1] if '.' in file_name else ''
            if ext not in VISIO_EXTENSIONS:
                return jsonify({"error": "File is not a Visio VSDX document"}), 400

            if force_download:
                return serve_enhanced_citation_content(raw_doc, force_download=True)

            settings = get_settings()
            max_blob_size = int(settings.get('visio_preview_max_blob_size_mb', settings.get('max_file_size_mb', 16))) * 1024 * 1024
            max_edge_px = int(settings.get('visio_preview_max_edge_px', 3200))
            blob_service_client = CLIENTS.get("storage_account_office_docs_client")
            if not blob_service_client:
                return jsonify({"error": "Blob storage client not available"}), 500

            container_name, blob_name = _resolve_document_blob_reference(raw_doc)
            blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)
            blob_props = blob_client.get_blob_properties()
            if blob_props.size > max_blob_size:
                return jsonify({"error": "File is too large to preview"}), 400

            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".vsdx", delete=False) as temp_file:
                    temp_path = temp_file.name
                    blob_client.download_blob().readinto(temp_file)

                png_bytes = render_vsdx_page_preview(
                    temp_path,
                    page_number=page_number,
                    max_edge_px=max_edge_px,
                )
            finally:
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)

            response = Response(png_bytes, mimetype="image/png")
            response.headers["Content-Disposition"] = f"inline; filename=visio-page-{page_number}.png"
            response.headers["Cache-Control"] = "private, max-age=300"
            return response

        except ValueError as value_error:
            return jsonify({"error": str(value_error)}), 400
        except FileNotFoundError as file_error:
            return jsonify({"error": str(file_error)}), 404
        except Exception as error:
            debug_print(f"Error generating Visio preview: {error}")
            return jsonify({"error": str(error)}), 500

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
        except Exception as ex:
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
                    except Exception as ex:
                        continue
        except Exception as ex:
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
                except Exception as ex:
                    continue
        except Exception as ex:
            pass
    
    # If document not found in any workspace
    return {"error": "Document not found or access denied"}, 404


def determine_workspace_type_and_container(raw_doc):
    """
    Determine workspace type and appropriate container based on document metadata
    """
    if raw_doc.get('public_workspace_id'):
        return 'public', raw_doc.get('blob_container') or storage_account_public_documents_container_name
    elif raw_doc.get('group_id'):
        return 'group', raw_doc.get('blob_container') or storage_account_group_documents_container_name
    else:
        return 'personal', raw_doc.get('blob_container') or storage_account_user_documents_container_name

def get_blob_name(raw_doc, workspace_type):
    """
    Determine the correct blob name based on workspace type
    """
    _, blob_name = get_document_blob_storage_info(raw_doc)
    if blob_name:
        _log_enhanced_citations_debug(
            "Using stored blob path for citation content",
            doc_id=raw_doc.get('id'),
            workspace_type=workspace_type,
            blob_name=blob_name,
        )
        return blob_name

    if workspace_type == 'public':
        fallback_blob_name = f"{raw_doc['public_workspace_id']}/{raw_doc['file_name']}"
    elif workspace_type == 'group':
        fallback_blob_name = f"{raw_doc['group_id']}/{raw_doc['file_name']}"
    else:
        fallback_blob_name = f"{raw_doc['user_id']}/{raw_doc['file_name']}"

    _log_enhanced_citations_debug(
        "Using legacy blob path fallback for citation content",
        doc_id=raw_doc.get('id'),
        workspace_type=workspace_type,
        blob_name=fallback_blob_name,
    )
    return fallback_blob_name


def serve_enhanced_citation_content(raw_doc, content_type=None, force_download=False):
    """
    Server-side rendering: Serve enhanced citation file content directly
    Based on the logic from the existing view_pdf function but serves content directly
    """
    # Get blob storage client
    blob_service_client = CLIENTS.get("storage_account_office_docs_client")
    if not blob_service_client:
        raise Exception("Blob storage client not available")

    doc_id = raw_doc.get('id')
    file_name = raw_doc.get('file_name')
    workspace_type = None
    container_name = None
    blob_name = None

    try:
        workspace_type, container_name = determine_workspace_type_and_container(raw_doc)
        blob_name = get_blob_name(raw_doc, workspace_type)
        container_client = blob_service_client.get_container_client(container_name)

        _log_enhanced_citations_debug(
            "Downloading citation content from blob storage",
            doc_id=doc_id,
            file_name=file_name,
            workspace_type=workspace_type,
            container_name=container_name,
            blob_name=blob_name,
            force_download=force_download,
        )

        # Download blob content directly
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)
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

        _log_enhanced_citations_debug(
            "Citation content downloaded successfully",
            doc_id=doc_id,
            file_name=file_name,
            workspace_type=workspace_type,
            container_name=container_name,
            blob_name=blob_name,
            content_type=content_type,
            content_length=len(content),
            force_download=force_download,
        )
        
        # Set content disposition based on force_download parameter
        disposition = 'attachment' if force_download else 'inline'
        
        # Create Response with the blob content
        response = Response(
            content,
            content_type=content_type,
            headers={
                'Content-Length': str(len(content)),
                'Cache-Control': 'private, max-age=300',  # Cache for 5 minutes
                'Content-Disposition': _build_content_disposition(disposition, raw_doc.get('file_name')),
                'Accept-Ranges': 'bytes'  # Support range requests for video/audio
            }
        )
        
        return response
        
    except Exception as e:
        _log_enhanced_citations_error(
            "Failed to serve citation content",
            e,
            doc_id=doc_id,
            file_name=file_name,
            workspace_type=workspace_type,
            container_name=container_name,
            blob_name=blob_name,
            force_download=force_download,
        )
        raise Exception(f"Failed to load content: {str(e)}") from e

def serve_enhanced_citation_pdf_content(raw_doc, page_number, show_all=False):
    """
    Serve PDF content with page extraction (±1 page logic from original view_pdf)
    Based on the logic from the existing view_pdf function but serves content directly
    
    Args:
        raw_doc: Document metadata
        page_number: Current page number
        show_all: If True, show all pages instead of just ±1 pages around current
    """
    _log_enhanced_citations_debug(
        "Preparing PDF citation content",
        doc_id=raw_doc.get('id'),
        file_name=raw_doc.get('file_name'),
        page=page_number,
        show_all=show_all,
    )
    
    blob_service_client = CLIENTS.get("storage_account_office_docs_client")
    if not blob_service_client:
        raise Exception("Blob storage client not available")

    doc_id = raw_doc.get('id')
    file_name = raw_doc.get('file_name')
    workspace_type = None
    container_name = None
    blob_name = None

    try:
        workspace_type, container_name = determine_workspace_type_and_container(raw_doc)
        blob_name = get_blob_name(raw_doc, workspace_type)
        container_client = blob_service_client.get_container_client(container_name)

        _log_enhanced_citations_debug(
            "Downloading PDF citation blob",
            doc_id=doc_id,
            file_name=file_name,
            workspace_type=workspace_type,
            container_name=container_name,
            blob_name=blob_name,
            page=page_number,
            show_all=show_all,
        )

        # Download blob content directly
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)
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
                _log_enhanced_citations_debug(
                    "Requested PDF page was out of range",
                    doc_id=doc_id,
                    file_name=file_name,
                    page=page_number,
                    total_pages=total_pages,
                )
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

            _log_enhanced_citations_debug(
                "Built PDF citation sub-document",
                doc_id=doc_id,
                file_name=file_name,
                page=page_number,
                show_all=show_all,
                total_pages=total_pages,
                start_idx=start_idx,
                end_idx=end_idx,
                viewer_page=new_page_number,
                content_length=len(extracted_content),
            )

            # Return the extracted PDF
            headers = {
                'Content-Length': str(len(extracted_content)),
                'Cache-Control': 'private, max-age=300',  # Cache for 5 minutes
                'Content-Disposition': _build_content_disposition('inline', raw_doc.get('file_name')),
                'X-Sub-PDF-Page': str(new_page_number),  # Custom header with page info
                'Accept-Ranges': 'bytes'
            }
            
            # When show_all is True, allow iframe embedding
            if show_all:
                _log_enhanced_citations_debug(
                    "Setting CSP headers for iframe embedding",
                    doc_id=doc_id,
                    file_name=file_name,
                    show_all=show_all,
                )
                headers['Content-Security-Policy'] = (
                    "default-src 'self'; "
                    "frame-ancestors 'self'; "  # Allow embedding in same origin
                    "object-src 'none';"
                )
                headers['X-Frame-Options'] = 'SAMEORIGIN'  # Allow same-origin framing
            else:
                _log_enhanced_citations_debug(
                    "Skipping iframe embedding headers for sub-document response",
                    doc_id=doc_id,
                    file_name=file_name,
                    show_all=show_all,
                )
            
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
        _log_enhanced_citations_error(
            "Failed to serve PDF citation content",
            e,
            doc_id=doc_id,
            file_name=file_name,
            workspace_type=workspace_type,
            container_name=container_name,
            blob_name=blob_name,
            page=page_number,
            show_all=show_all,
        )
        raise Exception(f"Failed to load PDF content: {str(e)}") from e
