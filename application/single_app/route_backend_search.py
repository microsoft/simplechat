# route_backend_search.py

from config import *
from functions_appinsights import log_event
from functions_authentication import get_current_user_id, login_required, user_required
from functions_search_service import (
    get_document_chunks_payload,
    search_documents as run_document_search,
    summarize_document_content,
)
from swagger_wrapper import swagger_route, get_auth_security


def register_route_backend_search(app):
    @app.route('/api/search/documents', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_search_documents():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.get_json(silent=True) or {}

        try:
            payload = run_document_search(
                query=data.get('query'),
                user_id=user_id,
                top_n=data.get('top_n'),
                doc_scope=data.get('doc_scope', 'all'),
                document_id=data.get('document_id'),
                document_ids=data.get('document_ids'),
                tags_filter=data.get('tags_filter', data.get('tags')),
                active_group_ids=data.get('active_group_ids', data.get('active_group_id')),
                active_public_workspace_id=data.get('active_public_workspace_id'),
                enable_file_sharing=data.get('enable_file_sharing', True),
            )
            return jsonify(payload), 200
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            log_event(
                '[Backend Search] Document search failed.',
                extra={'user_id': user_id, 'error_message': str(e)},
                level=logging.ERROR,
            )
            return jsonify({'error': 'Document search failed'}), 500

    @app.route('/api/search/document-chunks', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_get_document_chunks():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.get_json(silent=True) or {}
        document_id = str(data.get('document_id') or '').strip()
        if not document_id:
            return jsonify({'error': 'document_id is required'}), 400

        try:
            payload = get_document_chunks_payload(
                document_id=document_id,
                user_id=user_id,
                doc_scope=data.get('doc_scope', 'all'),
                active_group_ids=data.get('active_group_ids', data.get('active_group_id')),
                active_public_workspace_id=data.get('active_public_workspace_id'),
                window_unit=data.get('window_unit', 'pages'),
                window_size=data.get('window_size'),
                window_percent=data.get('window_percent'),
                window_number=data.get('window_number'),
            )
            return jsonify(payload), 200
        except LookupError as e:
            return jsonify({'error': str(e)}), 404
        except Exception as e:
            log_event(
                '[Backend Search] Document chunk retrieval failed.',
                extra={
                    'user_id': user_id,
                    'document_id': document_id,
                    'error_message': str(e),
                },
                level=logging.ERROR,
            )
            return jsonify({'error': 'Document chunk retrieval failed'}), 500

    @app.route('/api/search/document-summary', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_summarize_document():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.get_json(silent=True) or {}
        document_id = str(data.get('document_id') or '').strip()
        if not document_id:
            return jsonify({'error': 'document_id is required'}), 400

        try:
            payload = summarize_document_content(
                document_id=document_id,
                user_id=user_id,
                doc_scope=data.get('doc_scope', 'all'),
                active_group_ids=data.get('active_group_ids', data.get('active_group_id')),
                active_public_workspace_id=data.get('active_public_workspace_id'),
                focus_instructions=data.get('focus_instructions', ''),
                final_target_length=data.get('final_target_length', data.get('target_length', '2 pages')),
                window_target_length=data.get('window_target_length', '2 pages'),
                window_unit=data.get('window_unit', 'pages'),
                window_size=data.get('window_size'),
                window_percent=data.get('window_percent'),
                reduction_batch_size=data.get('reduction_batch_size'),
                max_reduction_rounds=data.get('max_reduction_rounds'),
            )
            return jsonify(payload), 200
        except LookupError as e:
            return jsonify({'error': str(e)}), 404
        except RuntimeError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            log_event(
                '[Backend Search] Document summarization failed.',
                extra={
                    'user_id': user_id,
                    'document_id': document_id,
                    'error_message': str(e),
                },
                level=logging.ERROR,
            )
            return jsonify({'error': 'Document summarization failed'}), 500