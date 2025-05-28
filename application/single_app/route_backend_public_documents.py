# route_backend_public_documents.py

from config import *
from functions_authentication import *
from functions_settings import *
from functions_public_workspace import *
from functions_documents import *

def register_route_backend_public_documents(app):
    @app.route('/api/public_documents', methods=['GET'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_list_public_documents():
        """
        Return a list of documents for the active public workspace.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_public_workspace_id = user_settings["settings"].get("activePublicWorkspaceOid")

        if not active_public_workspace_id:
            return jsonify({'error': 'No active public workspace selected'}), 400

        return get_documents(user_id, active_public_workspace_id)


    @app.route('/api/public_documents/<document_id>', methods=['GET'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_get_public_document(document_id):
        """
        Return metadata for a specific public document.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_public_workspace_id = user_settings["settings"].get("activePublicWorkspaceOid")

        if not active_public_workspace_id:
            return jsonify({'error': 'No active public workspace selected'}), 400

        return get_document(user_id, document_id, active_public_workspace_id)


    @app.route('/api/public_documents/<document_id>/chunks', methods=['GET'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_get_public_document_chunks(document_id):
        """
        Return chunks for a specific public document.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_public_workspace_id = user_settings["settings"].get("activePublicWorkspaceOid")

        if not active_public_workspace_id:
            return jsonify({'error': 'No active public workspace selected'}), 400

        return get_all_chunks(document_id, user_id, active_public_workspace_id)


    @app.route('/api/public_documents/<document_id>', methods=['PATCH'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_patch_public_document(document_id):
        """
        Update metadata fields for a public document.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_public_workspace_id = user_settings["settings"].get("activePublicWorkspaceOid")

        if not active_public_workspace_id:
            return jsonify({'error': 'No active public workspace selected'}), 400

        workspace_doc = find_public_workspace_by_id(active_public_workspace_id)
        if not workspace_doc:
            return jsonify({'error': 'Active public workspace not found'}), 404

        role = get_user_role_in_public_workspace(workspace_doc, user_id)
        if role not in ['Owner', 'Admin', 'DocumentManager']:
            return jsonify({'error': 'You do not have permission to update documents in this public workspace'}), 403

        data = request.get_json()

        try:
            if 'title' in data:
                update_document(
                    document_id=document_id,
                    group_id=active_public_workspace_id,
                    user_id=user_id,
                    title=data['title']
                )
            if 'abstract' in data:
                update_document(
                    document_id=document_id,
                    group_id=active_public_workspace_id,
                    user_id=user_id,
                    abstract=data['abstract']
                )
            if 'keywords' in data:
                if isinstance(data['keywords'], list):
                    update_document(
                        document_id=document_id,
                        group_id=active_public_workspace_id,
                        user_id=user_id,
                        keywords=data['keywords']
                    )
            if 'authors' in data:
                if isinstance(data['authors'], list):
                    update_document(
                        document_id=document_id,
                        group_id=active_public_workspace_id,
                        user_id=user_id,
                        authors=data['authors']
                    )
            if 'document_classification' in data:
                update_document(
                    document_id=document_id,
                    group_id=active_public_workspace_id,
                    user_id=user_id,
                    document_classification=data['document_classification']
                )
            return jsonify({"updated": True}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500


    @app.route('/api/public_documents/<document_id>', methods=['DELETE'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_delete_public_document(document_id):
        """
        Delete a document from a public workspace.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_public_workspace_id = user_settings["settings"].get("activePublicWorkspaceOid")

        if not active_public_workspace_id:
            return jsonify({'error': 'No active public workspace selected'}), 400

        workspace_doc = find_public_workspace_by_id(active_public_workspace_id)
        if not workspace_doc:
            return jsonify({'error': 'Active public workspace not found'}), 404

        role = get_user_role_in_public_workspace(workspace_doc, user_id)
        if role not in ['Owner', 'Admin', 'DocumentManager']:
            return jsonify({'error': 'You do not have permission to delete documents in this public workspace'}), 403

        try:
            delete_document(user_id, document_id, active_public_workspace_id)
            return jsonify({"deleted": True}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500


    @app.route('/api/public_documents/<document_id>/extract_metadata', methods=['POST'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_extract_public_metadata(document_id):
        """
        Extract metadata for a document in a public workspace.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_public_workspace_id = user_settings["settings"].get("activePublicWorkspaceOid")

        if not active_public_workspace_id:
            return jsonify({'error': 'No active public workspace selected'}), 400

        workspace_doc = find_public_workspace_by_id(active_public_workspace_id)
        if not workspace_doc:
            return jsonify({'error': 'Active public workspace not found'}), 404

        role = get_user_role_in_public_workspace(workspace_doc, user_id)
        if role not in ['Owner', 'Admin', 'DocumentManager']:
            return jsonify({'error': 'You do not have permission to extract metadata in this public workspace'}), 403

        try:
            meta_data = extract_document_metadata(document_id, user_id, active_public_workspace_id)
            return jsonify(meta_data), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500