# route_openapi.py
"""
OpenAPI Plugin Routes

This module provides routes for managing OpenAPI plugin file uploads.
"""

import os
import tempfile
import uuid
from flask import request, jsonify, current_app
from functions_authentication import login_required, user_required
from openapi_security import openapi_validator
from openapi_auth_analyzer import analyze_openapi_authentication, get_authentication_help_text
from swagger_wrapper import swagger_route, get_auth_security
from functions_debug import debug_print

def register_openapi_routes(app):
    """Register OpenAPI-related routes."""
    
    @app.route('/api/openapi/upload', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def upload_openapi_spec():
        """
        Upload and validate an OpenAPI specification file.
        
        Expected form data:
        - file: The OpenAPI specification file (YAML or JSON)
        
        Returns:
        - success: Boolean indicating if upload was successful
        - filename: The secure filename used for storage
        - spec_info: Basic information about the OpenAPI spec
        - error: Error message if upload failed
        """
        try:
            # Check if file was uploaded
            if 'file' not in request.files:
                return jsonify({
                    'success': False,
                    'error': 'No file provided'
                }), 400
            
            file = request.files['file']
            if not file.filename:
                return jsonify({
                    'success': False,
                    'error': 'No file selected'
                }), 400
            
            # Validate filename
            filename_valid, filename_error = openapi_validator.validate_filename(file.filename)
            if not filename_valid:
                return jsonify({
                    'success': False,
                    'error': f'Invalid filename: {filename_error}'
                }), 400
            
            # Create safe filename
            safe_filename = openapi_validator.create_safe_filename(file.filename)
            
            # Check file size before saving
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)
            
            size_valid, size_error = openapi_validator.validate_file_size(file_size)
            if not size_valid:
                return jsonify({
                    'success': False,
                    'error': size_error
                }), 400
            
            # Save to temporary file for validation
            file_ext = os.path.splitext(safe_filename)[1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
                file.save(tmp_file.name)
                temp_path = tmp_file.name
            
            try:
                # Validate file content
                valid, spec, error = openapi_validator.validate_file_content(temp_path)
                
                if not valid:
                    return jsonify({
                        'success': False,
                        'error': f'Validation failed: {error}'
                    }), 400
                
                # Generate unique file ID for reference
                file_id = str(uuid.uuid4())
                
                # We don't permanently store the file - just use the validated content
                # The spec content will be stored in Cosmos DB user settings
                
                # Clean up the temporary file since we have the validated content
                os.unlink(temp_path)
                
                # Extract basic spec information
                info = spec.get('info', {})
                spec_info = {
                    'title': info.get('title', 'Unknown API'),
                    'description': info.get('description', ''),
                    'version': info.get('version', ''),
                    'openapi_version': spec.get('openapi', ''),
                    'servers': spec.get('servers', []),
                    'paths_count': len(spec.get('paths', {})),
                    'components_count': len(spec.get('components', {}))
                }
                
                # Analyze authentication schemes
                auth_analysis = analyze_openapi_authentication(spec)
                
                return jsonify({
                    'success': True,
                    'file_id': file_id,
                    'original_filename': file.filename,
                    'spec_content': spec,  # Return the actual spec content
                    'spec_info': spec_info,
                    'authentication': auth_analysis
                })
                
            finally:
                # Clean up temp file if it still exists
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                    
        except Exception as e:
            debug_print(f"Error uploading OpenAPI spec: {str(e)}")
            return jsonify({
                'success': False,
                'error': 'Internal server error during upload'
            }), 500
    
    @app.route('/api/openapi/list-uploaded', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def list_uploaded_specs():
        """
        List all uploaded OpenAPI specifications.
        
        Returns:
        - success: Boolean indicating if listing was successful
        - specs: List of uploaded specifications with their info
        - error: Error message if listing failed
        """
        try:
            upload_dir = os.path.join(current_app.instance_path, 'openapi_specs')
            
            if not os.path.exists(upload_dir):
                return jsonify({
                    'success': True,
                    'specs': []
                })
            
            specs = []
            for filename in os.listdir(upload_dir):
                if filename.endswith(('.yaml', '.yml', '.json')):
                    file_path = os.path.join(upload_dir, filename)
                    try:
                        # Try to read basic info from each spec
                        valid, spec, error = openapi_validator.validate_file_content(file_path)
                        if valid:
                            info = spec.get('info', {})
                            specs.append({
                                'filename': filename,
                                'title': info.get('title', 'Unknown API'),
                                'description': info.get('description', ''),
                                'version': info.get('version', ''),
                                'openapi_version': spec.get('openapi', ''),
                                'paths_count': len(spec.get('paths', {})),
                                'file_size': os.path.getsize(file_path),
                                'last_modified': os.path.getmtime(file_path)
                            })
                    except Exception as e:
                        debug_print(f"Could not read spec file {filename}: {str(e)}")
                        continue
            
            return jsonify({
                'success': True,
                'specs': specs
            })
            
        except Exception as e:
            debug_print(f"Error listing OpenAPI specs: {str(e)}")
            return jsonify({
                'success': False,
                'error': 'Internal server error while listing specifications'
            }), 500
    
    @app.route('/api/openapi/analyze-auth', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def analyze_openapi_auth():
        """
        Analyze OpenAPI specification for authentication schemes.
        
        Expected JSON data:
        - spec_content: The OpenAPI specification content (dict)
        
        Returns:
        - success: Boolean indicating if analysis was successful
        - authentication: Authentication analysis results
        - help_text: User-friendly help text for the suggested auth
        - error: Error message if analysis failed
        """
        try:
            data = request.get_json()
            if not data or 'spec_content' not in data:
                return jsonify({
                    'success': False,
                    'error': 'OpenAPI specification content is required'
                }), 400
            
            spec_content = data['spec_content']
            
            # Analyze authentication schemes
            auth_analysis = analyze_openapi_authentication(spec_content)
            
            # Generate help text for the suggested authentication
            help_text = ""
            if auth_analysis.get('suggested_auth'):
                help_text = get_authentication_help_text(auth_analysis['suggested_auth'])
            
            return jsonify({
                'success': True,
                'authentication': auth_analysis,
                'help_text': help_text
            })
            
        except Exception as e:
            debug_print(f"Error analyzing authentication: {str(e)}")
            return jsonify({
                'success': False,
                'error': 'Internal server error during authentication analysis'
            }), 500
