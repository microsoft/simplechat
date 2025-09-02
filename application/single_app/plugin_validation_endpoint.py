# plugin_validation_endpoint.py
"""
Additional validation endpoints for plugin health checking and manifest validation.
"""

from flask import Blueprint, jsonify, request, current_app
from semantic_kernel_plugins.plugin_health_checker import PluginHealthChecker, PluginErrorRecovery
from semantic_kernel_plugins.plugin_loader import discover_plugins
from functions_appinsights import log_event
from functions_authentication import login_required, admin_required
import logging


plugin_validation_bp = Blueprint('plugin_validation', __name__)


@plugin_validation_bp.route('/api/admin/plugins/validate', methods=['POST'])
@login_required
@admin_required
def validate_plugin_manifest():
    """
    Validate a plugin manifest without saving it.
    Useful for frontend validation before submission.
    """
    try:
        manifest = request.json
        if not manifest:
            return jsonify({'error': 'No manifest provided'}), 400
        
        plugin_type = manifest.get('type', '')
        plugin_name = manifest.get('name', 'unnamed')
        
        # Perform health checker validation
        is_valid, validation_errors = PluginHealthChecker.validate_plugin_manifest(manifest, plugin_type)
        
        response = {
            'valid': is_valid,
            'plugin_name': plugin_name,
            'plugin_type': plugin_type,
            'errors': validation_errors,
            'warnings': []
        }
        
        # Additional checks for completeness
        if not manifest.get('description'):
            response['warnings'].append('Plugin description is empty')
        
        if plugin_type in ['azure_function', 'blob_storage', 'queue_storage']:
            if not manifest.get('endpoint'):
                response['warnings'].append('Endpoint field is recommended for this plugin type')
        
        log_event(f"[Plugin Validation] Validated manifest for {plugin_name}", 
                 extra={'plugin_name': plugin_name, 'valid': is_valid, 'errors': validation_errors})
        
        return jsonify(response)
    
    except Exception as e:
        log_event(f"[Plugin Validation] Error validating manifest: {str(e)}", level=logging.ERROR)
        return jsonify({'error': f'Validation failed: {str(e)}'}), 500


@plugin_validation_bp.route('/api/admin/plugins/test-instantiation', methods=['POST'])
def test_plugin_instantiation():
    """
    Test if a plugin can be instantiated successfully.
    This performs a dry run without adding to the kernel.
    """
    try:
        manifest = request.json
        if not manifest:
            return jsonify({'error': 'No manifest provided'}), 400
        
        plugin_type = manifest.get('type', '')
        plugin_name = manifest.get('name', 'unnamed')
        
        # Discover available plugins
        discovered_plugins = discover_plugins()
        
        # Find matching plugin class
        def normalize(s):
            return s.replace('_', '').replace('-', '').replace('plugin', '').lower() if s else ''
        
        normalized_type = normalize(plugin_type)
        matched_class = None
        
        for class_name, cls in discovered_plugins.items():
            normalized_class = normalize(class_name)
            if normalized_type == normalized_class or normalized_type in normalized_class:
                matched_class = cls
                break
        
        if not matched_class:
            return jsonify({
                'success': False,
                'error': f'No plugin class found for type: {plugin_type}',
                'available_types': list(discovered_plugins.keys())
            })
        
        # Test instantiation
        plugin_instance, instantiation_errors = PluginHealthChecker.create_plugin_safely(
            matched_class, manifest, plugin_name
        )
        
        success = plugin_instance is not None
        
        response = {
            'success': success,
            'plugin_name': plugin_name,
            'plugin_type': plugin_type,
            'class_name': matched_class.__name__,
            'errors': instantiation_errors
        }
        
        if success:
            # Run health check on the instantiated plugin
            health_report = PluginHealthChecker.check_plugin_health(plugin_instance, plugin_name)
            response['health_report'] = health_report
            response['is_healthy'] = health_report['is_healthy']
        
        log_event(f"[Plugin Test] Tested instantiation for {plugin_name}", 
                 extra={'plugin_name': plugin_name, 'success': success, 'errors': instantiation_errors})
        
        return jsonify(response)
    
    except Exception as e:
        log_event(f"[Plugin Test] Error testing instantiation: {str(e)}", level=logging.ERROR)
        return jsonify({'error': f'Test failed: {str(e)}'}), 500


@plugin_validation_bp.route('/api/admin/plugins/health-check/<plugin_name>', methods=['GET'])
def check_plugin_health(plugin_name):
    """
    Perform a health check on an existing plugin.
    """
    try:
        from functions_settings import get_settings
        
        settings = get_settings()
        plugins = settings.get('semantic_kernel_plugins', [])
        
        # Find the plugin
        plugin_manifest = None
        for plugin in plugins:
            if plugin.get('name') == plugin_name:
                plugin_manifest = plugin
                break
        
        if not plugin_manifest:
            return jsonify({'error': f'Plugin {plugin_name} not found'}), 404
        
        # Try to instantiate and check health
        plugin_type = plugin_manifest.get('type', '')
        discovered_plugins = discover_plugins()
        
        def normalize(s):
            return s.replace('_', '').replace('-', '').replace('plugin', '').lower() if s else ''
        
        normalized_type = normalize(plugin_type)
        matched_class = None
        
        for class_name, cls in discovered_plugins.items():
            normalized_class = normalize(class_name)
            if normalized_type == normalized_class or normalized_type in normalized_class:
                matched_class = cls
                break
        
        if not matched_class:
            return jsonify({
                'plugin_name': plugin_name,
                'is_healthy': False,
                'error': f'No plugin class found for type: {plugin_type}'
            })
        
        # Test instantiation and health
        plugin_instance, instantiation_errors = PluginHealthChecker.create_plugin_safely(
            matched_class, plugin_manifest, plugin_name
        )
        
        if plugin_instance is None:
            return jsonify({
                'plugin_name': plugin_name,
                'is_healthy': False,
                'errors': instantiation_errors
            })
        
        # Perform health check
        health_report = PluginHealthChecker.check_plugin_health(plugin_instance, plugin_name)
        
        log_event(f"[Plugin Health] Health check for {plugin_name}", 
                 extra={'plugin_name': plugin_name, 'is_healthy': health_report['is_healthy']})
        
        return jsonify(health_report)
    
    except Exception as e:
        log_event(f"[Plugin Health] Error checking health for {plugin_name}: {str(e)}", level=logging.ERROR)
        return jsonify({
            'plugin_name': plugin_name,
            'is_healthy': False,
            'error': f'Health check failed: {str(e)}'
        }), 500


@plugin_validation_bp.route('/api/admin/plugins/repair/<plugin_name>', methods=['POST'])
def repair_plugin(plugin_name):
    """
    Attempt to repair a plugin that has issues.
    """
    try:
        from functions_settings import get_settings, update_settings
        
        settings = get_settings()
        plugins = settings.get('semantic_kernel_plugins', [])
        
        # Find the plugin
        plugin_index = None
        plugin_manifest = None
        for i, plugin in enumerate(plugins):
            if plugin.get('name') == plugin_name:
                plugin_index = i
                plugin_manifest = plugin
                break
        
        if plugin_manifest is None:
            return jsonify({'error': f'Plugin {plugin_name} not found'}), 404
        
        # Try to instantiate the plugin
        plugin_type = plugin_manifest.get('type', '')
        discovered_plugins = discover_plugins()
        
        def normalize(s):
            return s.replace('_', '').replace('-', '').replace('plugin', '').lower() if s else ''
        
        normalized_type = normalize(plugin_type)
        matched_class = None
        
        for class_name, cls in discovered_plugins.items():
            normalized_class = normalize(class_name)
            if normalized_type == normalized_class or normalized_type in normalized_class:
                matched_class = cls
                break
        
        if not matched_class:
            return jsonify({
                'success': False,
                'error': f'No plugin class found for type: {plugin_type}'
            })
        
        # Attempt instantiation and repair
        plugin_instance, instantiation_errors = PluginHealthChecker.create_plugin_safely(
            matched_class, plugin_manifest, plugin_name
        )
        
        if plugin_instance is None:
            # Try creating a fallback plugin
            fallback_plugin = PluginErrorRecovery.create_fallback_plugin(plugin_name, plugin_type)
            if fallback_plugin is None:
                return jsonify({
                    'success': False,
                    'error': 'Both main plugin and fallback creation failed',
                    'details': instantiation_errors
                })
            
            # Update the manifest to reflect fallback status
            plugin_manifest['metadata'] = plugin_manifest.get('metadata', {})
            plugin_manifest['metadata']['status'] = 'fallback'
            plugin_manifest['metadata']['original_errors'] = instantiation_errors
            
            plugins[plugin_index] = plugin_manifest
            # NOTE: Update container-based storage instead of legacy settings
            from functions_global_actions import save_global_action
            try:
                # Save to container instead of settings
                save_global_action(plugin_manifest)
                # Remove from legacy settings if present
                if 'semantic_kernel_plugins' in settings:
                    del settings['semantic_kernel_plugins']
                    update_settings(settings)
            except Exception as e:
                print(f"Error updating plugin in container storage: {e}")
                # Fallback to settings update if container fails
                settings['semantic_kernel_plugins'] = plugins
                update_settings(settings)
            
            return jsonify({
                'success': True,
                'repaired': True,
                'fallback_used': True,
                'original_errors': instantiation_errors
            })
        
        # Try to repair the plugin instance
        health_report = PluginHealthChecker.check_plugin_health(plugin_instance, plugin_name)
        
        if not health_report['is_healthy']:
            repaired_plugin, was_repaired = PluginErrorRecovery.attempt_plugin_repair(
                plugin_instance, health_report['errors']
            )
            
            if was_repaired:
                # Update manifest with repair information
                plugin_manifest['metadata'] = plugin_manifest.get('metadata', {})
                plugin_manifest['metadata']['status'] = 'repaired'
                plugin_manifest['metadata']['repair_timestamp'] = health_report.get('timestamp')
                
                plugins[plugin_index] = plugin_manifest
                # NOTE: Update container-based storage instead of legacy settings
                from functions_global_actions import save_global_action
                try:
                    # Save to container instead of settings
                    save_global_action(plugin_manifest)
                    # Remove from legacy settings if present
                    if 'semantic_kernel_plugins' in settings:
                        del settings['semantic_kernel_plugins']
                        update_settings(settings)
                except Exception as e:
                    print(f"Error updating plugin in container storage: {e}")
                    # Fallback to settings update if container fails
                    settings['semantic_kernel_plugins'] = plugins
                    update_settings(settings)
                
                return jsonify({
                    'success': True,
                    'repaired': True,
                    'original_errors': health_report['errors']
                })
        
        return jsonify({
            'success': True,
            'repaired': False,
            'message': 'Plugin is already healthy'
        })
    
    except Exception as e:
        log_event(f"[Plugin Repair] Error repairing {plugin_name}: {str(e)}", level=logging.ERROR)
        return jsonify({
            'success': False,
            'error': f'Repair failed: {str(e)}'
        }), 500
