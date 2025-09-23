# route_frontend_workflow.py

from config import *
from functions_authentication import *
from functions_content import *
from functions_settings import *
from functions_documents import *
from functions_group import find_group_by_id
from functions_appinsights import log_event
from functions_search import hybrid_search
import json
import time
import uuid
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

def register_route_frontend_workflow(app):
    @app.route('/workflow', methods=['GET'])
    @login_required
    @user_required
    def workflow():
        user_id = get_current_user_id()
        settings = get_settings()
        user_settings = get_user_settings(user_id)
        public_settings = sanitize_settings_for_user(settings)
        
        # Check if workflow is enabled
        enable_workflow = public_settings.get("enable_workflow", False)
        enable_enhanced_citations = public_settings.get("enable_enhanced_citations", False)
        
        # Workflow requires enhanced citations
        if not enable_workflow or not enable_enhanced_citations:
            return render_template(
                'error.html',
                error_title="Workflow Not Available",
                error_message="Workflow functionality requires Enhanced Citations to be enabled by your administrator.",
                user_settings=user_settings
            )
        
        if not user_id:
            return redirect(url_for('login'))
            
        return render_template(
            'workflow.html',
            settings=public_settings,
            user_settings=user_settings,
            enable_workflow=enable_workflow,
            enable_enhanced_citations=enable_enhanced_citations,
        )
    
    @app.route('/workflow/processing-mode-selection', methods=['GET'])
    @login_required
    @user_required
    def workflow_processing_mode_selection():
        user_id = get_current_user_id()
        settings = get_settings()
        user_settings = get_user_settings(user_id)
        public_settings = sanitize_settings_for_user(settings)
        
        # Check if workflow is enabled
        enable_workflow = public_settings.get("enable_workflow", False)
        enable_enhanced_citations = public_settings.get("enable_enhanced_citations", False)
        
        if not enable_workflow or not enable_enhanced_citations:
            return redirect(url_for('workflow'))
        
        # Get scope from query parameters
        scope = request.args.get('scope')
        if not scope or scope not in ['workspace', 'group', 'public']:
            return redirect(url_for('workflow'))
        
        return render_template(
            'workflow_processing_mode_selection.html',
            settings=public_settings,
            user_settings=user_settings,
            scope=scope,
        )
    
    @app.route('/workflow/scope-selection', methods=['GET'])
    @login_required
    @user_required
    def workflow_scope_selection():
        user_id = get_current_user_id()
        settings = get_settings()
        user_settings = get_user_settings(user_id)
        public_settings = sanitize_settings_for_user(settings)
        
        # Check if workflow is enabled
        enable_workflow = public_settings.get("enable_workflow", False)
        enable_enhanced_citations = public_settings.get("enable_enhanced_citations", False)
        
        if not enable_workflow or not enable_enhanced_citations:
            return redirect(url_for('workflow'))
            
        return render_template(
            'workflow.html',
            settings=public_settings,
            user_settings=user_settings,
            enable_workflow=enable_workflow,
            enable_enhanced_citations=enable_enhanced_citations,
        )
    
    @app.route('/workflow/file-selection', methods=['GET'])
    @login_required
    @user_required
    def workflow_file_selection():
        user_id = get_current_user_id()
        settings = get_settings()
        user_settings = get_user_settings(user_id)
        public_settings = sanitize_settings_for_user(settings)
        
        # Check if workflow is enabled
        enable_workflow = public_settings.get("enable_workflow", False)
        enable_enhanced_citations = public_settings.get("enable_enhanced_citations", False)
        
        if not enable_workflow or not enable_enhanced_citations:
            return redirect(url_for('workflow'))
        
        # Get scope from query parameters
        scope = request.args.get('scope', 'workspace')  # Default to workspace
        
        return render_template(
            'workflow_file_selection.html',
            settings=public_settings,
            user_settings=user_settings,
            scope=scope,
        )
    
    @app.route('/workflow/summary-selection', methods=['GET'])
    @login_required
    @user_required
    def workflow_summary_selection():
        user_id = get_current_user_id()
        settings = get_settings()
        user_settings = get_user_settings(user_id)
        public_settings = sanitize_settings_for_user(settings)
        
        # Check if workflow is enabled
        enable_workflow = public_settings.get("enable_workflow", False)
        enable_enhanced_citations = public_settings.get("enable_enhanced_citations", False)
        
        if not enable_workflow or not enable_enhanced_citations:
            return redirect(url_for('workflow'))
        
        # Get file info from query parameters
        file_id = request.args.get('file_id')
        scope = request.args.get('scope', 'workspace')
        
        if not file_id:
            return redirect(url_for('workflow_file_selection', scope=scope))
        
        return render_template(
            'workflow_summary_selection.html',
            settings=public_settings,
            user_settings=user_settings,
            file_id=file_id,
            scope=scope,
        )
    
    @app.route('/workflow/summary-view', methods=['GET'])
    @login_required
    @user_required
    def workflow_summary_view():
        user_id = get_current_user_id()
        settings = get_settings()
        user_settings = get_user_settings(user_id)
        public_settings = sanitize_settings_for_user(settings)
        
        # Check if workflow is enabled
        enable_workflow = public_settings.get("enable_workflow", False)
        enable_enhanced_citations = public_settings.get("enable_enhanced_citations", False)
        
        if not enable_workflow or not enable_enhanced_citations:
            return redirect(url_for('workflow'))
        
        # Get parameters
        file_id = request.args.get('file_id')
        scope = request.args.get('scope', 'workspace')
        summary_type = request.args.get('summary_type', 'summary')
        
        if not file_id:
            return redirect(url_for('workflow_file_selection', scope=scope))
        
        return render_template(
            'workflow_summary_view.html',
            settings=public_settings,
            user_settings=user_settings,
            file_id=file_id,
            scope=scope,
            summary_type=summary_type,
        )
    
    @app.route('/api/workflow/generate-summary', methods=['POST'])
    @login_required
    @user_required
    def api_generate_workflow_summary():
        """Generate summary for workflow document"""
        try:
            user_id = get_current_user_id()
            if not user_id:
                return jsonify({'error': 'User not authenticated'}), 401

            data = request.get_json()
            file_id = data.get('file_id')
            scope = data.get('scope', 'workspace')
            summary_type = data.get('summary_type', 'summary')

            if not file_id:
                return jsonify({'error': 'File ID is required'}), 400

            settings = get_settings()
            public_settings = sanitize_settings_for_user(settings)
            
            # Check if workflow is enabled
            enable_workflow = public_settings.get("enable_workflow", False)
            enable_enhanced_citations = public_settings.get("enable_enhanced_citations", False)
            
            if not enable_workflow or not enable_enhanced_citations:
                return jsonify({'error': 'Workflow functionality not enabled'}), 403

            # Generate summary based on type
            if summary_type == 'summary':
                summary = generate_document_summary(file_id, scope, user_id)
            elif summary_type == 'translation':
                summary = generate_document_translation(file_id, scope, user_id)
            else:
                return jsonify({'error': f'Unsupported summary type: {summary_type}'}), 400

            return jsonify({
                'success': True,
                'summary': summary,
                'file_id': file_id,
                'scope': scope,
                'summary_type': summary_type
            })

        except Exception as e:
            debug_print(f"Error generating workflow summary: {str(e)}")
            return jsonify({'error': f'Failed to generate summary: {str(e)}'}), 500

    @app.route('/api/workflow/generate-pii-analysis', methods=['POST'])
    @login_required
    @user_required
    def api_generate_workflow_pii_analysis():
        """Generate PII analysis for workflow document"""
        try:
            user_id = get_current_user_id()
            if not user_id:
                return jsonify({'error': 'User not authenticated'}), 401

            data = request.get_json()
            file_id = data.get('file_id')
            scope = data.get('scope', 'workspace')

            if not file_id:
                return jsonify({'error': 'File ID is required'}), 400

            settings = get_settings()
            public_settings = sanitize_settings_for_user(settings)
            
            # Check if workflow and PII analysis are enabled
            enable_workflow = public_settings.get("enable_workflow", False)
            enable_enhanced_citations = public_settings.get("enable_enhanced_citations", False)
            enable_pii_analysis = public_settings.get("enable_pii_analysis", False)
            
            if not enable_workflow or not enable_enhanced_citations:
                return jsonify({'error': 'Workflow functionality not enabled'}), 403
                
            if not enable_pii_analysis:
                return jsonify({'error': 'PII Analysis functionality not enabled'}), 403

            # Generate PII analysis
            pii_analysis = generate_document_pii_analysis(file_id, scope, user_id)

            return jsonify({
                'success': True,
                'pii_analysis': pii_analysis,
                'file_id': file_id,
                'scope': scope,
                'analysis_type': 'pii_analysis'
            })

        except Exception as e:
            debug_print(f"Error generating workflow PII analysis: {str(e)}")
            return jsonify({'error': f'Failed to generate PII analysis: {str(e)}'}), 500

    @app.route('/api/get-document-info/<document_id>', methods=['GET'])
    @login_required
    @user_required
    def api_get_document_info(document_id):
        """Get document information for workflow"""
        try:
            user_id = get_current_user_id()
            if not user_id:
                return jsonify({'error': 'User not authenticated'}), 401

            # Get document from personal workspace
            doc_metadata = get_document_metadata(document_id, user_id)
            
            if not doc_metadata:
                return jsonify({'error': 'Document not found'}), 404

            return jsonify({
                'success': True,
                'document': {
                    'id': document_id,
                    'filename': doc_metadata.get('file_name', 'Unknown'),
                    'size': doc_metadata.get('size'),
                    'created_date': doc_metadata.get('created_date'),
                    'title': doc_metadata.get('title'),
                    'authors': doc_metadata.get('authors', []),
                    'abstract': doc_metadata.get('abstract')
                }
            })

        except Exception as e:
            debug_print(f"Error getting document info: {str(e)}")
            return jsonify({'error': f'Failed to get document info: {str(e)}'}), 500

    @app.route('/api/get-group-document-info/<document_id>', methods=['GET'])
    @login_required
    @user_required
    def api_get_group_document_info(document_id):
        """Get group document information for workflow"""
        try:
            user_id = get_current_user_id()
            if not user_id:
                return jsonify({'error': 'User not authenticated'}), 401

            # For group documents, we need to determine the group_id
            # This is a simplified approach - in reality you'd need proper group validation
            user_settings = get_user_settings(user_id)
            active_group_id = user_settings["settings"].get("activeGroupOid", "")
            
            if not active_group_id:
                return jsonify({'error': 'No active group selected'}), 400

            doc_metadata = get_document_metadata(document_id, user_id, group_id=active_group_id)
            
            if not doc_metadata:
                return jsonify({'error': 'Document not found'}), 404

            return jsonify({
                'success': True,
                'document': {
                    'id': document_id,
                    'filename': doc_metadata.get('file_name', 'Unknown'),
                    'size': doc_metadata.get('size'),
                    'created_date': doc_metadata.get('created_date'),
                    'title': doc_metadata.get('title'),
                    'authors': doc_metadata.get('authors', []),
                    'abstract': doc_metadata.get('abstract')
                }
            })

        except Exception as e:
            debug_print(f"Error getting group document info: {str(e)}")
            return jsonify({'error': f'Failed to get document info: {str(e)}'}), 500

    @app.route('/api/get-public-document-info/<document_id>', methods=['GET'])
    @login_required
    @user_required
    def api_get_public_document_info(document_id):
        """Get public document information for workflow"""
        try:
            user_id = get_current_user_id()
            if not user_id:
                return jsonify({'error': 'User not authenticated'}), 401

            # For public documents, we need to determine the public workspace
            # This is a simplified approach - in reality you'd need proper workspace validation
            user_settings = get_user_settings(user_id)
            # Note: This would need to be adapted based on your public workspace selection logic
            
            # For now, we'll use a basic approach
            doc_metadata = get_document_metadata(document_id, user_id, public_workspace_id="default")
            
            if not doc_metadata:
                return jsonify({'error': 'Document not found'}), 404

            return jsonify({
                'success': True,
                'document': {
                    'id': document_id,
                    'filename': doc_metadata.get('file_name', 'Unknown'),
                    'size': doc_metadata.get('size'),
                    'created_date': doc_metadata.get('created_date'),
                    'title': doc_metadata.get('title'),
                    'authors': doc_metadata.get('authors', []),
                    'abstract': doc_metadata.get('abstract')
                }
            })

        except Exception as e:
            debug_print(f"Error getting public document info: {str(e)}")
            return jsonify({'error': f'Failed to get document info: {str(e)}'}), 500

    # ========================================
    # Bulk Workflow Routes
    # ========================================
    
    @app.route('/workflow/bulk-file-selection', methods=['GET'])
    @login_required
    @user_required
    def workflow_bulk_file_selection():
        """Bulk workflow file selection page with multi-select capabilities"""
        user_id = get_current_user_id()
        settings = get_settings()
        user_settings = get_user_settings(user_id)
        public_settings = sanitize_settings_for_user(settings)
        
        # Check if workflow is enabled
        enable_workflow = public_settings.get("enable_workflow", False)
        enable_enhanced_citations = public_settings.get("enable_enhanced_citations", False)
        
        if not enable_workflow or not enable_enhanced_citations:
            return redirect(url_for('workflow'))
        
        # Get scope from query parameters
        scope = request.args.get('scope', 'workspace')  
        
        return render_template(
            'workflow_bulk_file_selection.html',
            settings=public_settings,
            user_settings=user_settings,
            scope=scope,
        )
    
    @app.route('/workflow/bulk-type-selection', methods=['GET', 'POST'])
    @login_required
    @user_required
    def workflow_bulk_type_selection():
        """Bulk workflow type selection page"""
        user_id = get_current_user_id()
        settings = get_settings()
        user_settings = get_user_settings(user_id)
        public_settings = sanitize_settings_for_user(settings)
        
        # Check if workflow is enabled
        enable_workflow = public_settings.get("enable_workflow", False)
        enable_enhanced_citations = public_settings.get("enable_enhanced_citations", False)
        
        if not enable_workflow or not enable_enhanced_citations:
            return redirect(url_for('workflow'))
        
        if request.method == 'POST':
            selected_documents = request.form.getlist('selected_documents')
            scope = request.form.get('scope')
            
            if not selected_documents:
                flash('No documents selected.', 'error')
                return redirect(url_for('workflow'))
            
            # Store selected documents in session for next step
            session['bulk_selected_documents'] = selected_documents
            session['bulk_scope'] = scope
            
            return render_template('workflow_bulk_type_selection.html', 
                                 document_count=len(selected_documents),
                                 scope=scope,
                                 settings=public_settings,
                                 user_settings=user_settings)
        
        # GET request - redirect back to workflow home
        return redirect(url_for('workflow'))
    
    @app.route('/workflow/bulk-processing', methods=['POST'])
    @login_required
    @user_required
    def workflow_bulk_processing():
        """Process bulk workflow type selection"""
        user_id = get_current_user_id()
        settings = get_settings()
        public_settings = sanitize_settings_for_user(settings)
        
        # Check if workflow is enabled
        enable_workflow = public_settings.get("enable_workflow", False)
        enable_enhanced_citations = public_settings.get("enable_enhanced_citations", False)
        
        if not enable_workflow or not enable_enhanced_citations:
            return redirect(url_for('workflow'))
        
        workflow_type = request.form.get('workflow_type')
        selected_documents = session.get('bulk_selected_documents', [])
        scope = session.get('bulk_scope')
        
        if not selected_documents or not workflow_type:
            flash('Missing required information.', 'error')
            return redirect(url_for('workflow'))
        
        # For now, redirect to placeholder routes (to be implemented)
        if workflow_type == 'summarize':
            # Process each document individually like single workflow
            flash('Bulk summarization will be implemented soon.', 'info')
            return redirect(url_for('workflow'))
        elif workflow_type == 'fraud_analysis':
            # Analyze all documents together for fraud patterns
            flash('Fraud analysis will be implemented soon.', 'info')
            return redirect(url_for('workflow'))
        elif workflow_type == 'compare':
            # Select one document to compare against others
            flash('Document comparison will be implemented soon.', 'info')
            return redirect(url_for('workflow'))
        else:
            flash('Invalid workflow type selected.', 'error')
            return redirect(url_for('workflow'))
    
    @app.route('/workflow/bulk-selection', methods=['GET'])
    @login_required
    @user_required
    def workflow_bulk_selection():
        """Bulk workflow processing options page"""
        user_id = get_current_user_id()
        settings = get_settings()
        user_settings = get_user_settings(user_id)
        public_settings = sanitize_settings_for_user(settings)
        
        # Check if workflow is enabled
        enable_workflow = public_settings.get("enable_workflow", False)
        enable_enhanced_citations = public_settings.get("enable_enhanced_citations", False)
        
        if not enable_workflow or not enable_enhanced_citations:
            return redirect(url_for('workflow'))
        
        # Get file IDs and scope from query parameters
        file_ids = request.args.getlist('file_ids')
        scope = request.args.get('scope', 'workspace')
        
        if not file_ids:
            return redirect(url_for('workflow_bulk_file_selection', scope=scope))
        
        return render_template(
            'workflow_bulk_selection.html',
            settings=public_settings,
            user_settings=user_settings,
            file_ids=file_ids,
            scope=scope,
        )
    
    @app.route('/workflow/bulk-progress', methods=['GET'])
    @login_required
    @user_required
    def workflow_bulk_progress():
        """Bulk workflow progress tracking page"""
        user_id = get_current_user_id()
        settings = get_settings()
        user_settings = get_user_settings(user_id)
        public_settings = sanitize_settings_for_user(settings)
        
        # Check if workflow is enabled
        enable_workflow = public_settings.get("enable_workflow", False)
        enable_enhanced_citations = public_settings.get("enable_enhanced_citations", False)
        
        if not enable_workflow or not enable_enhanced_citations:
            return redirect(url_for('workflow'))
        
        # Get parameters from query string
        file_ids = request.args.getlist('file_ids')
        scope = request.args.get('scope', 'workspace')
        workflow_type = request.args.get('workflow_type', 'summary')
        processing_mode = request.args.get('processing_mode', 'individual')  # 'individual' or 'combined'
        
        if not file_ids:
            return redirect(url_for('workflow_bulk_file_selection', scope=scope))
        
        return render_template(
            'workflow_bulk_progress.html',
            settings=public_settings,
            user_settings=user_settings,
            file_ids=file_ids,
            scope=scope,
            workflow_type=workflow_type,
            processing_mode=processing_mode,
        )
    
    @app.route('/api/workflow/bulk-process', methods=['POST'])
    @login_required
    @user_required
    def api_bulk_workflow_process():
        """Process multiple documents with specified workflow type"""
        try:
            user_id = get_current_user_id()
            if not user_id:
                return jsonify({'error': 'User not authenticated'}), 401

            data = request.get_json()
            file_ids = data.get('file_ids', [])
            scope = data.get('scope', 'workspace')
            workflow_type = data.get('workflow_type', 'summary')  # summary, pii_analysis, translation
            processing_mode = data.get('processing_mode', 'individual')  # individual or combined

            if not file_ids:
                return jsonify({'error': 'File IDs are required'}), 400

            settings = get_settings()
            public_settings = sanitize_settings_for_user(settings)
            
            # Check if workflow is enabled
            enable_workflow = public_settings.get("enable_workflow", False)
            enable_enhanced_citations = public_settings.get("enable_enhanced_citations", False)
            
            if not enable_workflow or not enable_enhanced_citations:
                return jsonify({'error': 'Workflow functionality not enabled'}), 403

            # Generate job ID for tracking
            job_id = str(uuid.uuid4())
            
            # Store job metadata (in production, use Redis or database)
            bulk_job_metadata = {
                'job_id': job_id,
                'user_id': user_id,
                'file_ids': file_ids,
                'scope': scope,
                'workflow_type': workflow_type,
                'processing_mode': processing_mode,
                'total_files': len(file_ids),
                'completed_files': 0,
                'failed_files': 0,
                'status': 'started',
                'start_time': time.time(),
                'results': {}
            }
            
            # For now, store in memory (in production, use persistent storage)
            if not hasattr(app, 'bulk_jobs'):
                app.bulk_jobs = {}
            app.bulk_jobs[job_id] = bulk_job_metadata

            # Process files based on mode
            if processing_mode == 'combined':
                # Combine all documents and process as one
                combined_result = process_combined_documents(file_ids, scope, workflow_type, user_id)
                bulk_job_metadata['results']['combined'] = combined_result
                bulk_job_metadata['completed_files'] = len(file_ids)
            else:
                # Process each document individually
                for file_id in file_ids:
                    try:
                        if workflow_type == 'summary':
                            result = generate_document_summary(file_id, scope, user_id)
                        elif workflow_type == 'pii_analysis':
                            result = generate_document_pii_analysis(file_id, scope, user_id)
                        elif workflow_type == 'translation':
                            result = generate_document_translation(file_id, scope, user_id)
                        else:
                            raise ValueError(f"Unsupported workflow type: {workflow_type}")
                        
                        bulk_job_metadata['results'][file_id] = {
                            'status': 'completed',
                            'result': result
                        }
                        bulk_job_metadata['completed_files'] += 1
                        
                    except Exception as e:
                        bulk_job_metadata['results'][file_id] = {
                            'status': 'failed',
                            'error': str(e)
                        }
                        bulk_job_metadata['failed_files'] += 1

            bulk_job_metadata['status'] = 'completed'
            bulk_job_metadata['end_time'] = time.time()

            return jsonify({
                'success': True,
                'job_id': job_id,
                'total_files': len(file_ids),
                'completed_files': bulk_job_metadata['completed_files'],
                'failed_files': bulk_job_metadata['failed_files'],
                'processing_mode': processing_mode,
                'workflow_type': workflow_type
            })

        except Exception as e:
            debug_print(f"Error in bulk workflow processing: {str(e)}")
            return jsonify({'error': f'Failed to process bulk workflow: {str(e)}'}), 500

    @app.route('/api/workflow/bulk-status/<job_id>', methods=['GET'])
    @login_required
    @user_required
    def api_bulk_workflow_status(job_id):
        """Get status of bulk workflow job"""
        try:
            user_id = get_current_user_id()
            if not user_id:
                return jsonify({'error': 'User not authenticated'}), 401

            # Check if job exists
            if not hasattr(app, 'bulk_jobs') or job_id not in app.bulk_jobs:
                return jsonify({'error': 'Job not found'}), 404

            job_metadata = app.bulk_jobs[job_id]
            
            # Verify user owns this job
            if job_metadata['user_id'] != user_id:
                return jsonify({'error': 'Unauthorized'}), 403

            return jsonify({
                'success': True,
                'job_id': job_id,
                'status': job_metadata['status'],
                'total_files': job_metadata['total_files'],
                'completed_files': job_metadata['completed_files'],
                'failed_files': job_metadata['failed_files'],
                'workflow_type': job_metadata['workflow_type'],
                'processing_mode': job_metadata['processing_mode'],
                'results': job_metadata['results'],
                'start_time': job_metadata.get('start_time'),
                'end_time': job_metadata.get('end_time')
            })

        except Exception as e:
            debug_print(f"Error getting bulk workflow status: {str(e)}")
            return jsonify({'error': f'Failed to get job status: {str(e)}'}), 500


def generate_document_summary(file_id, scope, user_id):
    """Generate a comprehensive summary of a document using AI"""
    try:
        settings = get_settings()
        
        # Determine document scope and get metadata
        if scope == 'workspace':
            doc_metadata = get_document_metadata(file_id, user_id)
            group_id = None
            public_workspace_id = None
        elif scope == 'group':
            user_settings = get_user_settings(user_id)
            group_id = user_settings["settings"].get("activeGroupOid", "")
            doc_metadata = get_document_metadata(file_id, user_id, group_id=group_id)
            public_workspace_id = None
        elif scope == 'public':
            doc_metadata = get_document_metadata(file_id, user_id, public_workspace_id="default")
            group_id = None
            public_workspace_id = "default"
        else:
            raise ValueError(f"Unsupported scope: {scope}")

        if not doc_metadata:
            raise ValueError("Document not found")

        # Get document chunks using hybrid search
        search_query = f"comprehensive summary of {doc_metadata.get('file_name', 'document')}"
        
        if scope == 'workspace':
            search_results = hybrid_search(
                search_query,
                user_id,
                document_id=file_id,
                top_n=20,  # Get more chunks for comprehensive summary
                doc_scope="personal"
            )
        elif scope == 'group':
            search_results = hybrid_search(
                search_query,
                user_id,
                document_id=file_id,
                top_n=20,
                doc_scope="group",
                group_id=group_id
            )
        elif scope == 'public':
            search_results = hybrid_search(
                search_query,
                user_id,
                document_id=file_id,
                top_n=20,
                doc_scope="public",
                public_workspace_id=public_workspace_id
            )

        if not search_results or len(search_results) == 0:
            raise ValueError("No document content found for summarization")

        # Extract content from search results
        document_content = ""
        for result in search_results:
            content = result.get('content', '')
            if content:
                document_content += content + "\n\n"

        # Limit content to avoid token limits (approximately 50,000 characters = ~12,500 tokens)
        if len(document_content) > 50000:
            document_content = document_content[:50000] + "...[Content truncated]"

        # Get GPT model for summarization (use workflow model or fallback to metadata extraction model)
        gpt_model = settings.get('workflow_default_summary_model') or settings.get('metadata_extraction_model')
        if not gpt_model:
            raise ValueError("No AI model configured for summarization")

        # Set up GPT client
        enable_gpt_apim = settings.get('enable_gpt_apim', False)
        
        if enable_gpt_apim:
            gpt_client = AzureOpenAI(
                api_version=settings.get('azure_apim_gpt_api_version'),
                azure_endpoint=settings.get('azure_apim_gpt_endpoint'),
                api_key=settings.get('azure_apim_gpt_subscription_key')
            )
        else:
            if settings.get('azure_openai_gpt_authentication_type') == 'managed_identity':
                token_provider = get_bearer_token_provider(
                    DefaultAzureCredential(), 
                    cognitive_services_scope
                )
                gpt_client = AzureOpenAI(
                    api_version=settings.get('azure_openai_gpt_api_version'),
                    azure_endpoint=settings.get('azure_openai_gpt_endpoint'),
                    azure_ad_token_provider=token_provider
                )
            else:
                gpt_client = AzureOpenAI(
                    api_version=settings.get('azure_openai_gpt_api_version'),
                    azure_endpoint=settings.get('azure_openai_gpt_endpoint'),
                    api_key=settings.get('azure_openai_gpt_key')
                )

        # Create comprehensive summary prompt
        doc_title = doc_metadata.get('title', doc_metadata.get('file_name', 'Document'))
        doc_authors = doc_metadata.get('authors', [])
        doc_abstract = doc_metadata.get('abstract', '')

        summary_prompt = f"""You are an expert document analyst. Please create a comprehensive summary of the following document.

Document Information:
- Title: {doc_title}
- Authors: {', '.join(doc_authors) if doc_authors else 'Not specified'}
- Abstract: {doc_abstract if doc_abstract else 'Not available'}

Document Content:
{document_content}

Please provide a well-structured summary that includes:

# Executive Summary
A concise overview of the main points and conclusions (2-3 paragraphs)

# Key Findings
- Main discoveries, results, or arguments presented
- Important data points or evidence

# Main Themes
- Central topics and concepts discussed
- Recurring themes throughout the document

# Methodology (if applicable)
- Approach or methods used in the research/analysis
- Data sources and analytical techniques

# Conclusions and Implications
- Primary conclusions drawn by the authors
- Significance and potential impact of the findings
- Future directions or recommendations

# Critical Analysis
- Strengths and limitations of the work
- Areas for further investigation

Please ensure the summary is:
- Comprehensive yet concise
- Well-organized with clear headings
- Written in professional language
- Captures the essence and nuance of the original document
- Approximately 800-1200 words in length

Focus on accuracy and provide specific details where relevant, including quantitative data when mentioned in the source material."""

        # Generate summary
        messages = [
            {
                "role": "system",
                "content": "You are an expert document analyst specializing in creating comprehensive, well-structured summaries of academic, business, and technical documents."
            },
            {
                "role": "user",
                "content": summary_prompt
            }
        ]

        # Prepare API parameters based on model type
        api_params = {
            "model": gpt_model,
            "messages": messages,
        }
        
        # Use correct token parameter based on model
        # o1 models use max_completion_tokens and don't support temperature
        if gpt_model and ('o1' in gpt_model.lower()):
            api_params["max_completion_tokens"] = 2500
            # o1 models don't support temperature parameter
        else:
            api_params["max_tokens"] = 2500
            api_params["temperature"] = 0.3  # Lower temperature for more consistent, factual summaries

        response = gpt_client.chat.completions.create(**api_params)

        summary = response.choices[0].message.content

        if not summary:
            raise ValueError("Failed to generate summary")

        return summary

    except Exception as e:
        debug_print(f"Error generating document summary: {str(e)}")
        raise e


def generate_document_pii_analysis(file_id, scope, user_id):
    """Generate a comprehensive PII analysis of a document using AI and configured patterns"""
    try:
        settings = get_settings()
        
        # Get PII analysis configuration
        pii_patterns = settings.get('pii_analysis_patterns', [])
        if not pii_patterns:
            raise ValueError("No PII analysis patterns configured")

        # Determine document scope and get metadata
        if scope == 'workspace':
            doc_metadata = get_document_metadata(file_id, user_id)
            group_id = None
            public_workspace_id = None
        elif scope == 'group':
            user_settings = get_user_settings(user_id)
            group_id = user_settings["settings"].get("activeGroupOid", "")
            doc_metadata = get_document_metadata(file_id, user_id, group_id=group_id)
            public_workspace_id = None
        elif scope == 'public':
            doc_metadata = get_document_metadata(file_id, user_id, public_workspace_id="default")
            group_id = None
            public_workspace_id = "default"
        else:
            raise ValueError(f"Unsupported scope: {scope}")

        if not doc_metadata:
            raise ValueError("Document not found")

        # Get document chunks using hybrid search
        search_query = f"content analysis privacy information {doc_metadata.get('file_name', 'document')}"
        
        debug_print(f"DEBUG: Calling hybrid_search with file_id={file_id}, scope={scope}")
        
        if scope == 'workspace':
            search_results = hybrid_search(
                search_query,
                user_id,
                document_id=file_id,
                top_n=30,  # Get more chunks for comprehensive PII analysis
                doc_scope="personal"
            )
        elif scope == 'group':
            search_results = hybrid_search(
                search_query,
                user_id,
                document_id=file_id,
                top_n=30,
                doc_scope="group",
                active_group_id=group_id
            )
        elif scope == 'public':
            search_results = hybrid_search(
                search_query,
                user_id,
                document_id=file_id,
                top_n=30,
                doc_scope="public",
                active_public_workspace_id=public_workspace_id
            )
        
        debug_print(f"DEBUG: hybrid_search returned {len(search_results) if search_results else 0} results")

        if not search_results or len(search_results) == 0:
            raise ValueError("No document content found for PII analysis")

        # Extract content from search results
        document_content = ""
        chunk_details = []
        for i, result in enumerate(search_results):
            # Search results use 'chunk_text' field, not 'content'
            content = result.get('chunk_text', result.get('content', ''))
            if content:
                document_content += content + "\n\n"
                chunk_details.append({
                    'chunk_index': i,
                    'content_length': len(content),
                    'content_preview': content[:200] + "..." if len(content) > 200 else content
                })

        debug_print(f"DEBUG: Extracted {len(document_content)} characters of content from {len(search_results)} chunks")
        debug_print(f"DEBUG: Chunk details:")
        for chunk in chunk_details:
            debug_print(f"  Chunk {chunk['chunk_index']}: {chunk['content_length']} chars - '{chunk['content_preview']}'")
        
        # Show first 1000 characters of the combined content for debugging
        debug_print(f"DEBUG: First 1000 characters of combined content:")
        debug_print(f"'{document_content[:1000]}...'" if len(document_content) > 1000 else f"'{document_content}'")

        # If no content found with specific search, try a broader search
        if not document_content.strip():
            debug_print("DEBUG: No content found with specific search, trying broader search...")
            # Try a more general search to get any content from this document
            broad_search_query = f"document {doc_metadata.get('file_name', 'content')}"
            
            if scope == 'workspace':
                search_results = hybrid_search(
                    broad_search_query,
                    user_id,
                    document_id=file_id,
                    top_n=50,  # Get more chunks
                    doc_scope="personal"
                )
            elif scope == 'group':
                search_results = hybrid_search(
                    broad_search_query,
                    user_id,
                    document_id=file_id,
                    top_n=50,
                    doc_scope="group",
                    active_group_id=group_id
                )
            elif scope == 'public':
                search_results = hybrid_search(
                    broad_search_query,
                    user_id,
                    document_id=file_id,
                    top_n=50,
                    doc_scope="public",
                    active_public_workspace_id=public_workspace_id
                )
            
            debug_print(f"DEBUG: Broad search returned {len(search_results) if search_results else 0} results")
            
            # Extract content from broad search results
            if search_results:
                broad_chunk_details = []
                for i, result in enumerate(search_results):
                    content = result.get('chunk_text', result.get('content', ''))
                    if content:
                        document_content += content + "\n\n"
                        broad_chunk_details.append({
                            'chunk_index': i,
                            'content_length': len(content),
                            'content_preview': content[:200] + "..." if len(content) > 200 else content
                        })
                        
                debug_print(f"DEBUG: After broad search, extracted {len(document_content)} characters of content")
                debug_print(f"DEBUG: Broad search chunk details:")
                for chunk in broad_chunk_details:
                    debug_print(f"  Chunk {chunk['chunk_index']}: {chunk['content_length']} chars - '{chunk['content_preview']}'")
                
                # Show first 1000 characters after broad search
                debug_print(f"DEBUG: First 1000 characters after broad search:")
                debug_print(f"'{document_content[:1000]}...'" if len(document_content) > 1000 else f"'{document_content}'")

        # Limit content to avoid token limits (approximately 60,000 characters = ~15,000 tokens)
        if len(document_content) > 60000:
            document_content = document_content[:60000] + "...[Content truncated]"

        # PERFORM ACTUAL REGEX PATTERN MATCHING FIRST
        import re
        regex_findings = {}
        total_pii_found = 0
        
        debug_print(f"Starting regex pattern matching on {len(document_content)} characters of content...")
        debug_print(f"DEBUG: Content sample for pattern matching (first 500 chars):")
        debug_print(f"'{document_content[:500]}...'" if len(document_content) > 500 else f"'{document_content}'")
        
        for pattern_info in pii_patterns:
            pattern_type = pattern_info.get('pattern_type', 'Unknown')
            regex_pattern = pattern_info.get('regex', '')
            description = pattern_info.get('description', '')
            severity = pattern_info.get('severity', 'Medium')
            
            debug_print(f"\nDEBUG: Testing {pattern_type} pattern:")
            debug_print(f"  Pattern: {regex_pattern}")
            
            if regex_pattern:
                try:
                    # Compile and search with the regex pattern
                    compiled_pattern = re.compile(regex_pattern, re.IGNORECASE)
                    matches = compiled_pattern.findall(document_content)
                    
                    debug_print(f"  Raw matches: {matches}")
                    debug_print(f"  Match count: {len(matches)}")
                    
                    # Show sample text around matches if found
                    if matches:
                        for i, match in enumerate(matches[:3]):  # Show first 3 matches
                            match_str = str(match) if not isinstance(match, tuple) else str(match[0]) if match[0] else str(match)
                            match_pos = document_content.find(match_str)
                            if match_pos >= 0:
                                start = max(0, match_pos - 50)
                                end = min(len(document_content), match_pos + len(match_str) + 50)
                                context = document_content[start:end]
                                debug_print(f"    Match {i+1} context: '...{context}...'")
                    
                    # Store findings
                    regex_findings[pattern_type] = {
                        'pattern': regex_pattern,
                        'description': description,
                        'severity': severity,
                        'matches': matches,
                        'count': len(matches)
                    }
                    
                    total_pii_found += len(matches)
                    debug_print(f"  Result: Found {len(matches)} matches for {pattern_type}")
                    
                except re.error as regex_error:
                    debug_print(f"  {pattern_type}: Invalid regex pattern - {regex_error}")
                    regex_findings[pattern_type] = {
                        'pattern': regex_pattern,
                        'description': description,
                        'severity': severity,
                        'matches': [],
                        'count': 0,
                        'error': str(regex_error)
                    }
            else:
                debug_print(f"  {pattern_type}: No regex pattern configured")
                regex_findings[pattern_type] = {
                    'pattern': '',
                    'description': description,
                    'severity': severity,
                    'matches': [],
                    'count': 0,
                    'error': 'No regex pattern configured'
                }
        
        debug_print(f"Regex matching complete. Total PII instances found: {total_pii_found}")

        # Get GPT model for PII analysis (use workflow model or fallback to metadata extraction model)
        gpt_model = settings.get('workflow_default_summary_model') or settings.get('metadata_extraction_model')
        if not gpt_model:
            raise ValueError("No AI model configured for PII analysis")

        # Set up GPT client
        enable_gpt_apim = settings.get('enable_gpt_apim', False)
        
        if enable_gpt_apim:
            gpt_client = AzureOpenAI(
                api_version=settings.get('azure_apim_gpt_api_version'),
                azure_endpoint=settings.get('azure_apim_gpt_endpoint'),
                api_key=settings.get('azure_apim_gpt_subscription_key')
            )
        else:
            if settings.get('azure_openai_gpt_authentication_type') == 'managed_identity':
                token_provider = get_bearer_token_provider(
                    DefaultAzureCredential(), 
                    cognitive_services_scope
                )
                gpt_client = AzureOpenAI(
                    api_version=settings.get('azure_openai_gpt_api_version'),
                    azure_endpoint=settings.get('azure_openai_gpt_endpoint'),
                    azure_ad_token_provider=token_provider
                )
            else:
                gpt_client = AzureOpenAI(
                    api_version=settings.get('azure_openai_gpt_api_version'),
                    azure_endpoint=settings.get('azure_openai_gpt_endpoint'),
                    api_key=settings.get('azure_openai_gpt_key')
                )

        # Build patterns description and actual findings for the AI
        patterns_desc = ""
        findings_summary = ""
        
        for pattern in pii_patterns:
            pattern_type = pattern['pattern_type']
            regex_info = f" (Pattern: {pattern.get('regex', 'N/A')})" if pattern.get('regex') else ""
            patterns_desc += f"- {pattern_type}: {pattern['description']} (Severity: {pattern['severity']}){regex_info}\n"
            
            # Add actual findings from regex matching
            if pattern_type in regex_findings:
                finding = regex_findings[pattern_type]
                count = finding['count']
                if count > 0:
                    # Redact matches for AI prompt (show first few characters only)
                    redacted_examples = []
                    for match in finding['matches'][:3]:  # Show max 3 examples
                        if len(str(match)) > 6:
                            redacted = str(match)[:3] + "*" * (len(str(match)) - 6) + str(match)[-3:]
                        else:
                            redacted = "*" * len(str(match))
                        redacted_examples.append(redacted)
                    
                    findings_summary += f"\n✓ {pattern_type}: {count} instances found"
                    if redacted_examples:
                        findings_summary += f" (Examples: {', '.join(redacted_examples)})"
                else:
                    findings_summary += f"\n✗ {pattern_type}: No instances found"

        # Create comprehensive PII analysis prompt
        doc_title = doc_metadata.get('title', doc_metadata.get('file_name', 'Document'))

        pii_prompt = f"""You are an expert privacy and data protection analyst. Please conduct a comprehensive PII (Personally Identifiable Information) analysis of the following document.

Document Information:
- Title: {doc_title}

PII Patterns Analyzed (Configured by Administrator):
{patterns_desc}

REGEX ANALYSIS RESULTS:
{findings_summary}

IMPORTANT: The above results show the actual regex pattern matches found in the document. Base your analysis primarily on these concrete findings, but also look for any additional variations that might not have been caught by the regex patterns.

Document Content:
{document_content}

Please provide a detailed PII analysis that includes:

# Executive Summary
A high-level overview of PII findings based on the regex analysis results above and overall privacy risk assessment (2-3 paragraphs)

# PII Detection Results
covnert into a table For each pattern type configured above, report the ACTUAL findings from the regex analysis:
| Account ID | Phone (Dummy)  | Email (Dummy)                          | Credit Card (Dummy) |
| ---------- | -------------- | -------------------------------------- | ------------------- |
| ACC-0001   | (000) 555-0001 | j.maple0001@training.example.com       | 4000-0000-0000-0001 |
| ACC-0002   | (000) 555-0002 | e.fictus0002@training.example.com      | 4000-0000-0000-0002 |
| ACC-0003   | (000) 555-0003 | r.imagin0003@training.example.com      | 4000-0000-0000-0003 |
| ACC-0004   | (000) 555-0004 | s.placeholder0004@training.example.com | 4000-0000-0000-0004 |

# Risk Assessment
- **Overall Risk Score**: High/Medium/Low based on actual findings from regex analysis
- **Compliance Concerns**: Potential GDPR, HIPAA, or other regulatory issues based on what was actually found
- **Data Sensitivity**: Classification based on the specific PII types detected

# Recommendations
- **Immediate Actions**: Steps to take for high-risk findings (based on what was actually detected)
- **Data Handling**: Best practices for managing the specific types of PII found
- **Compliance Steps**: Recommendations for regulatory compliance relevant to detected PII
- **Documentation**: What should be documented or reported based on actual findings

# Detailed Findings
For each specific PII instance found in the regex analysis:
- Location in document (analyze content to provide section/context)
- Type of PII (from regex findings)
- Risk assessment (based on configured severity)
- Recommended action

# Privacy Impact Assessment
- **Data Flow**: How the detected PII might be processed or shared
- **Retention**: Considerations for data retention policies for the specific PII found
- **Access Control**: Who should have access based on the sensitivity of detected PII
- **Audit Trail**: Recommended logging and monitoring for the specific PII types found

Please ensure the analysis is:
- Based primarily on the concrete regex analysis findings provided above
- Thorough and systematic about the actual PII detected
- Compliant with privacy regulations
- Actionable with specific recommendations for the detected PII
- Professional and detailed
- Focused on practical privacy protection measures for the actual findings

CRITICAL: Base your analysis on the ACTUAL regex findings provided above. Do not speculate about PII that was not detected by the regex patterns. If no PII was found, clearly state this and focus on preventive measures."""

        # Generate PII analysis
        messages = [
            {
                "role": "system",
                "content": "You are an expert privacy and data protection analyst specializing in PII detection, risk assessment, and regulatory compliance. You provide thorough, actionable privacy analyses."
            },
            {
                "role": "user",
                "content": pii_prompt
            }
        ]

        # Prepare API parameters based on model type
        api_params = {
            "model": gpt_model,
            "messages": messages,
        }
        
        # Use correct token parameter based on model
        # o1 models use max_completion_tokens and don't support temperature
        if gpt_model and ('o1' in gpt_model.lower()):
            api_params["max_completion_tokens"] = 3000
            # o1 models don't support temperature parameter
        else:
            api_params["max_tokens"] = 3000
            api_params["temperature"] = 0.1  # Very low temperature for consistent, factual PII analysis

        response = gpt_client.chat.completions.create(**api_params)

        pii_analysis = response.choices[0].message.content

        if not pii_analysis:
            raise ValueError("Failed to generate PII analysis")

        return pii_analysis

    except Exception as e:
        debug_print(f"Error generating PII analysis: {str(e)}")
        raise e


def generate_document_translation(file_id, scope, user_id):
    """Generate translation for a document"""
    try:
        debug_print(f"DEBUG: Starting document translation for file_id={file_id}, scope={scope}, user_id={user_id}")
        
        # Get document content using hybrid search
        search_query = "translate document content"
        group_id = session.get('active_group_id')
        public_workspace_id = session.get('active_public_workspace_id')
        
        debug_print(f"DEBUG: Calling hybrid_search with file_id={file_id}, scope={scope}")
        
        if scope == 'workspace':
            search_results = hybrid_search(
                search_query,
                user_id,
                document_id=file_id,
                top_n=30,
                doc_scope="personal",
                active_group_id=group_id
            )
        elif scope == 'group':
            search_results = hybrid_search(
                search_query,
                user_id,
                document_id=file_id,
                top_n=30,
                doc_scope="group",
                active_group_id=group_id
            )
        elif scope == 'public':
            search_results = hybrid_search(
                search_query,
                user_id,
                document_id=file_id,
                top_n=30,
                doc_scope="public",
                active_public_workspace_id=public_workspace_id
            )
        
        debug_print(f"DEBUG: hybrid_search returned {len(search_results) if search_results else 0} results")
        
        if not search_results or len(search_results) == 0:
            raise ValueError("No document content found for translation")

        # Extract content from search results using same logic as PII analysis
        document_content = ""
        chunk_details = []
        for i, result in enumerate(search_results):
            # Search results use 'chunk_text' field, not 'content'
            content = result.get('chunk_text', result.get('content', ''))
            if content:
                document_content += content + "\n\n"
                chunk_details.append({
                    'chunk_index': i,
                    'content_length': len(content),
                    'content_preview': content[:200] + "..." if len(content) > 200 else content
                })

        debug_print(f"DEBUG: Extracted {len(document_content)} characters of content from {len(search_results)} chunks")
        debug_print(f"DEBUG: Chunk details:")
        for detail in chunk_details:
            debug_print(f"DEBUG:   Chunk {detail['chunk_index']}: {detail['content_length']} chars - '{detail['content_preview']}'")

        if not document_content.strip():
            raise ValueError("No readable content found for translation")

        # Limit content to avoid token limits (approximately 30,000 characters = ~7,500 tokens for translation)
        if len(document_content) > 30000:
            document_content = document_content[:30000] + "...[Content truncated for translation]"

        # Get settings for OpenAI configuration
        settings = get_settings()
        
        # Get GPT model for translation (use workflow model or fallback to metadata extraction model)
        gpt_model = settings.get('workflow_default_summary_model') or settings.get('metadata_extraction_model')
        if not gpt_model:
            raise ValueError("No AI model configured for translation")

        # Set up GPT client
        enable_gpt_apim = settings.get('enable_gpt_apim', False)
        
        if enable_gpt_apim:
            gpt_client = AzureOpenAI(
                api_version=settings.get('azure_apim_gpt_api_version'),
                azure_endpoint=settings.get('azure_apim_gpt_endpoint'),
                api_key=settings.get('azure_apim_gpt_subscription_key')
            )
        else:
            if settings.get('azure_openai_gpt_authentication_type') == 'managed_identity':
                token_provider = get_bearer_token_provider(
                    DefaultAzureCredential(), 
                    cognitive_services_scope
                )
                gpt_client = AzureOpenAI(
                    api_version=settings.get('azure_openai_gpt_api_version'),
                    azure_endpoint=settings.get('azure_openai_gpt_endpoint'),
                    azure_ad_token_provider=token_provider
                )
            else:
                gpt_client = AzureOpenAI(
                    api_version=settings.get('azure_openai_gpt_api_version'),
                    azure_endpoint=settings.get('azure_openai_gpt_endpoint'),
                    api_key=settings.get('azure_openai_gpt_key')
                )

        # Create translation prompt
        system_prompt = """You are a professional document translator. Your task is to:

1. **Detect the source language** of the provided document content
2. **Translate the entire document** to English (if source is not English) or provide translation options
3. **Preserve document structure** including headings, lists, tables, and formatting
4. **Maintain professional terminology** and context
5. **Provide accurate, fluent translations** that preserve the original meaning

For English documents, offer translation to:
- Spanish (Español)
- Russian (Русский) 
- Chinese (中文)

Format your response as:
**Source Language Detected:** [Language]

**Translation:**
[Full translated content preserving structure]

**Alternative Language Options:** (if source is English)
- Spanish: [Brief sample]
- Russian: [Brief sample] 
- Chinese: [Brief sample]"""

        user_prompt = f"""Please translate this document content:

{document_content}"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        # Prepare API parameters based on model type
        api_params = {
            "model": gpt_model,
            "messages": messages,
        }
        
        # Use correct token parameter based on model
        # o1 models use max_completion_tokens and don't support temperature
        if gpt_model and ('o1' in gpt_model.lower()):
            api_params["max_completion_tokens"] = 4000
            # o1 models don't support temperature parameter
        else:
            api_params["max_tokens"] = 4000
            api_params["temperature"] = 0.3  # Moderate temperature for natural translation

        response = gpt_client.chat.completions.create(**api_params)

        translation = response.choices[0].message.content

        if not translation:
            raise ValueError("Failed to generate translation")

        return translation

    except Exception as e:
        debug_print(f"Error generating document translation: {str(e)}")
        raise e


def process_combined_documents(file_ids, scope, workflow_type, user_id):
    """Process multiple documents as a combined unit"""
    try:
        # Get all document content and combine it
        combined_content = ""
        document_titles = []
        
        for file_id in file_ids:
            # Get document metadata and content
            if scope == 'workspace':
                doc_metadata = get_document_metadata(file_id, user_id)
            elif scope == 'group':
                user_settings = get_user_settings(user_id)
                group_id = user_settings["settings"].get("activeGroupOid", "")
                doc_metadata = get_document_metadata(file_id, user_id, group_id=group_id)
            elif scope == 'public':
                user_settings = get_user_settings(user_id)
                public_workspace_id = user_settings["settings"].get("activePublicWorkspaceOid", "")
                doc_metadata = get_document_metadata(file_id, user_id, public_workspace_id=public_workspace_id)
            else:
                raise ValueError(f"Invalid scope: {scope}")
            
            if not doc_metadata:
                continue
                
            # Get document content via search
            if scope == 'workspace':
                search_results = hybrid_search(
                    "",  # Empty query to get all chunks
                    user_id,
                    document_id=file_id,
                    top_n=50,  # Get more chunks for combined processing
                    doc_scope="personal"
                )
            elif scope == 'group':
                search_results = hybrid_search(
                    "",
                    user_id,
                    document_id=file_id,
                    top_n=50,
                    doc_scope="group",
                    active_group_id=group_id
                )
            elif scope == 'public':
                search_results = hybrid_search(
                    "",
                    user_id,
                    document_id=file_id,
                    top_n=50,
                    doc_scope="public",
                    active_public_workspace_id=public_workspace_id
                )
            
            # Extract and combine content
            doc_title = doc_metadata.get('title') or doc_metadata.get('file_name', f'Document {file_id}')
            document_titles.append(doc_title)
            
            combined_content += f"\n\n=== {doc_title} ===\n\n"
            
            if search_results and hasattr(search_results, 'results'):
                chunks = search_results.results[:50]  # Limit to 50 chunks per document
                total_chars = 0
                for chunk in chunks:
                    chunk_text = chunk.get('chunk_text', '')
                    if total_chars + len(chunk_text) > 20000:  # Limit total content
                        break
                    combined_content += chunk_text + "\n\n"
                    total_chars += len(chunk_text)
        
        if not combined_content.strip():
            raise ValueError("No content found in selected documents")
        
        # Process based on workflow type
        if workflow_type == 'summary':
            return generate_combined_summary(combined_content, document_titles)
        elif workflow_type == 'pii_analysis':
            return generate_combined_pii_analysis(combined_content, document_titles)
        elif workflow_type == 'translation':
            return generate_combined_translation(combined_content, document_titles)
        else:
            raise ValueError(f"Unsupported workflow type: {workflow_type}")
            
    except Exception as e:
        debug_print(f"Error processing combined documents: {str(e)}")
        raise e


def generate_combined_summary(combined_content, document_titles):
    """Generate a summary for multiple combined documents"""
    try:
        settings = get_settings()
        azure_openai_gpt_key = settings.get('azure_openai_gpt_key')
        azure_openai_gpt_endpoint = settings.get('azure_openai_gpt_endpoint')
        azure_openai_gpt_deployment = settings.get('azure_openai_gpt_deployment')
        
        if not all([azure_openai_gpt_key, azure_openai_gpt_endpoint, azure_openai_gpt_deployment]):
            raise ValueError("Azure OpenAI configuration incomplete")

        # Setup Azure OpenAI client
        if azure_openai_gpt_key.startswith('managed_identity'):
            token_provider = get_bearer_token_provider(
                DefaultAzureCredential(),
                settings.get('cognitive_services_scope')
            )
            gpt_client = AzureOpenAI(
                azure_endpoint=azure_openai_gpt_endpoint,
                azure_ad_token_provider=token_provider,
                api_version="2024-11-30"
            )
        else:
            gpt_client = AzureOpenAI(
                api_key=azure_openai_gpt_key,
                azure_endpoint=azure_openai_gpt_endpoint,
                api_version="2024-11-30"
            )

        # Create combined summary prompt
        doc_list = "\n".join([f"- {title}" for title in document_titles])
        
        system_prompt = f"""You are an expert document analyst. You have been provided with content from multiple documents that need to be summarized collectively.

Documents included in this analysis:
{doc_list}

Please provide a comprehensive summary that:
1. **Executive Overview**: High-level overview of all documents combined
2. **Key Themes**: Common themes and topics across all documents
3. **Important Findings**: Critical information and insights from the collection
4. **Document-Specific Highlights**: Brief highlights from each individual document
5. **Relationships**: How the documents relate to each other (if applicable)
6. **Conclusions**: Overall conclusions from the complete document set

Format your response with clear headings and bullet points for easy reading."""

        user_prompt = f"Please analyze and summarize this collection of {len(document_titles)} documents:\n\n{combined_content}"

        # Prepare API parameters
        api_params = {
            "model": azure_openai_gpt_deployment,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt[:30000]}  # Limit content length
            ]
        }

        # Handle different model types
        if azure_openai_gpt_deployment.startswith('o1'):
            api_params["max_completion_tokens"] = 4000
        else:
            api_params["max_tokens"] = 4000
            api_params["temperature"] = 0.3

        response = gpt_client.chat.completions.create(**api_params)
        summary = response.choices[0].message.content

        if not summary:
            raise ValueError("Failed to generate combined summary")

        return summary

    except Exception as e:
        debug_print(f"Error generating combined summary: {str(e)}")
        raise e


def generate_combined_pii_analysis(combined_content, document_titles):
    """Generate PII analysis for multiple combined documents"""
    try:
        # Use existing PII analysis logic but for combined content
        settings = get_settings()
        pii_patterns = settings.get('pii_patterns', {})
        
        # Create combined analysis
        doc_list = "\n".join([f"- {title}" for title in document_titles])
        
        combined_analysis = f"""# PII Analysis Report - Multiple Documents

## Documents Analyzed:
{doc_list}

## Combined PII Scan Results:

"""
        
        # Run PII detection on combined content
        for pattern_name, pattern_config in pii_patterns.items():
            if not pattern_config.get('enabled', True):
                continue
                
            pattern = pattern_config.get('pattern', '')
            if pattern:
                import re
                matches = re.findall(pattern, combined_content, re.IGNORECASE | re.MULTILINE)
                if matches:
                    combined_analysis += f"### {pattern_name}\n"
                    combined_analysis += f"**Instances Found:** {len(matches)}\n"
                    # Show first few matches as examples
                    examples = list(set(matches))[:5]  # Unique examples, max 5
                    for example in examples:
                        combined_analysis += f"- `{example}`\n"
                    combined_analysis += "\n"
        
        combined_analysis += """
## Recommendations:
- Review all identified PII instances across the document collection
- Ensure proper data handling procedures are followed
- Consider anonymization or redaction where appropriate
- Implement access controls for sensitive documents
"""
        
        return combined_analysis

    except Exception as e:
        debug_print(f"Error generating combined PII analysis: {str(e)}")
        raise e


def generate_combined_translation(combined_content, document_titles):
    """Generate translation for multiple combined documents"""
    try:
        settings = get_settings()
        azure_openai_gpt_key = settings.get('azure_openai_gpt_key')
        azure_openai_gpt_endpoint = settings.get('azure_openai_gpt_endpoint')
        azure_openai_gpt_deployment = settings.get('azure_openai_gpt_deployment')
        
        if not all([azure_openai_gpt_key, azure_openai_gpt_endpoint, azure_openai_gpt_deployment]):
            raise ValueError("Azure OpenAI configuration incomplete")

        # Setup Azure OpenAI client (same as individual translation)
        if azure_openai_gpt_key.startswith('managed_identity'):
            token_provider = get_bearer_token_provider(
                DefaultAzureCredential(),
                settings.get('cognitive_services_scope')
            )
            gpt_client = AzureOpenAI(
                azure_endpoint=azure_openai_gpt_endpoint,
                azure_ad_token_provider=token_provider,
                api_version="2024-11-30"
            )
        else:
            gpt_client = AzureOpenAI(
                api_key=azure_openai_gpt_key,
                azure_endpoint=azure_openai_gpt_endpoint,
                api_version="2024-11-30"
            )

        # Create combined translation prompt
        doc_list = "\n".join([f"- {title}" for title in document_titles])
        
        system_prompt = f"""You are a professional translator. You have been provided with content from multiple documents that need to be translated collectively to English.

Documents included:
{doc_list}

Please:
1. **Auto-detect** the source language(s) in the content
2. **Translate** all content to English while preserving:
   - Document structure and formatting
   - Technical terminology
   - Table structures (use markdown tables)
   - Section headings
3. **Indicate** the source language(s) detected
4. **Maintain** clear separation between different documents

Start your response with "Source Language Detected: [language]" followed by "---Translation:" and then the translated content."""

        user_prompt = f"Please translate this collection of {len(document_titles)} documents to English:\n\n{combined_content[:25000]}"  # Limit for translation

        # Prepare API parameters
        api_params = {
            "model": azure_openai_gpt_deployment,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        }

        # Handle different model types
        if azure_openai_gpt_deployment.startswith('o1'):
            api_params["max_completion_tokens"] = 4000
        else:
            api_params["max_tokens"] = 4000
            api_params["temperature"] = 0.3

        response = gpt_client.chat.completions.create(**api_params)
        translation = response.choices[0].message.content

        if not translation:
            raise ValueError("Failed to generate combined translation")

        return translation

    except Exception as e:
        debug_print(f"Error generating combined translation: {str(e)}")
        raise e