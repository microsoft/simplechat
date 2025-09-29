# route_plugin_logging.py
"""
API endpoints for accessing plugin invocation logs and statistics.
"""

from flask import Blueprint, jsonify, request
from functions_authentication import login_required, get_current_user_id
from functions_appinsights import log_event
from semantic_kernel_plugins.plugin_invocation_logger import get_plugin_logger
from swagger_wrapper import swagger_route, get_auth_security
import logging

bpl = Blueprint('plugin_logging', __name__)


@bpl.route('/api/plugins/invocations', methods=['GET'])
@swagger_route(
    security=get_auth_security()
)
@login_required
def get_plugin_invocations():
    """Get recent plugin invocations for the current user."""
    try:
        user_id = get_current_user_id()
        plugin_logger = get_plugin_logger()
        
        # Get query parameters
        limit = request.args.get('limit', 50, type=int)
        limit = min(limit, 500)  # Cap at 500 for performance
        
        # Get user-specific invocations
        invocations = plugin_logger.get_invocations_for_user(user_id, limit)
        
        # Convert to dictionaries for JSON response
        response_data = {
            "invocations": [inv.to_dict() for inv in invocations],
            "total_count": len(invocations),
            "user_id": user_id
        }
        
        log_event(
            "[Plugin Logging API] Retrieved plugin invocations",
            extra={
                "user_id": user_id,
                "invocation_count": len(invocations),
                "limit": limit
            },
            level=logging.INFO
        )
        
        return jsonify(response_data), 200
        
    except Exception as e:
        log_event(
            "[Plugin Logging API] Error retrieving plugin invocations",
            extra={"error": str(e), "user_id": get_current_user_id()},
            level=logging.ERROR,
            exceptionTraceback=True
        )
        return jsonify({"error": "Failed to retrieve plugin invocations"}), 500


@bpl.route('/api/plugins/stats', methods=['GET'])
@swagger_route(
    security=get_auth_security()
)
@login_required
def get_plugin_stats():
    """Get plugin usage statistics."""
    try:
        user_id = get_current_user_id()
        plugin_logger = get_plugin_logger()
        
        # Get overall statistics
        stats = plugin_logger.get_plugin_stats()
        
        # Get user-specific invocations for user stats
        user_invocations = plugin_logger.get_invocations_for_user(user_id, 1000)
        
        # Calculate user-specific stats
        user_stats = {
            "total_invocations": len(user_invocations),
            "successful_invocations": sum(1 for inv in user_invocations if inv.success),
            "failed_invocations": sum(1 for inv in user_invocations if not inv.success),
            "plugins_used": len(set(inv.plugin_name for inv in user_invocations)),
            "average_duration_ms": (
                sum(inv.duration_ms for inv in user_invocations) / len(user_invocations)
                if user_invocations else 0
            )
        }
        
        response_data = {
            "overall_stats": stats,
            "user_stats": user_stats,
            "user_id": user_id
        }
        
        log_event(
            "[Plugin Logging API] Retrieved plugin statistics",
            extra={
                "user_id": user_id,
                "user_invocations": len(user_invocations),
                "total_plugins": stats.get("plugins", {}).keys() if stats else []
            },
            level=logging.INFO
        )
        
        return jsonify(response_data), 200
        
    except Exception as e:
        log_event(
            "[Plugin Logging API] Error retrieving plugin statistics",
            extra={"error": str(e), "user_id": get_current_user_id()},
            level=logging.ERROR,
            exceptionTraceback=True
        )
        return jsonify({"error": "Failed to retrieve plugin statistics"}), 500


@bpl.route('/api/plugins/invocations/recent', methods=['GET'])
@swagger_route(
    security=get_auth_security()
)
@login_required
def get_recent_invocations():
    """Get the most recent plugin invocations across all users (admin only)."""
    try:
        # Note: You might want to add admin role checking here
        plugin_logger = get_plugin_logger()
        
        limit = request.args.get('limit', 20, type=int)
        limit = min(limit, 100)  # Cap at 100 for performance
        
        recent_invocations = plugin_logger.get_recent_invocations(limit)
        
        response_data = {
            "invocations": [inv.to_dict() for inv in recent_invocations],
            "total_count": len(recent_invocations)
        }
        
        log_event(
            "[Plugin Logging API] Retrieved recent plugin invocations",
            extra={
                "requester_user_id": get_current_user_id(),
                "invocation_count": len(recent_invocations),
                "limit": limit
            },
            level=logging.INFO
        )
        
        return jsonify(response_data), 200
        
    except Exception as e:
        log_event(
            "[Plugin Logging API] Error retrieving recent plugin invocations",
            extra={"error": str(e), "requester_user_id": get_current_user_id()},
            level=logging.ERROR,
            exceptionTraceback=True
        )
        return jsonify({"error": "Failed to retrieve recent plugin invocations"}), 500


@bpl.route('/api/plugins/invocations/<string:plugin_name>', methods=['GET'])
@swagger_route(
    security=get_auth_security()
)
@login_required
def get_plugin_specific_invocations(plugin_name):
    """Get invocations for a specific plugin."""
    try:
        user_id = get_current_user_id()
        plugin_logger = get_plugin_logger()
        
        limit = request.args.get('limit', 50, type=int)
        limit = min(limit, 200)  # Cap for performance
        
        # Get all user invocations and filter by plugin name
        all_invocations = plugin_logger.get_invocations_for_user(user_id, 1000)
        plugin_invocations = [
            inv for inv in all_invocations 
            if inv.plugin_name.lower() == plugin_name.lower()
        ][-limit:]  # Get the most recent ones
        
        response_data = {
            "plugin_name": plugin_name,
            "invocations": [inv.to_dict() for inv in plugin_invocations],
            "total_count": len(plugin_invocations),
            "user_id": user_id
        }
        
        log_event(
            "[Plugin Logging API] Retrieved plugin-specific invocations",
            extra={
                "user_id": user_id,
                "plugin_name": plugin_name,
                "invocation_count": len(plugin_invocations),
                "limit": limit
            },
            level=logging.INFO
        )
        
        return jsonify(response_data), 200
        
    except Exception as e:
        log_event(
            "[Plugin Logging API] Error retrieving plugin-specific invocations",
            extra={
                "error": str(e), 
                "user_id": get_current_user_id(),
                "plugin_name": plugin_name
            },
            level=logging.ERROR,
            exceptionTraceback=True
        )
        return jsonify({"error": f"Failed to retrieve invocations for plugin {plugin_name}"}), 500


@bpl.route('/api/plugins/clear-logs', methods=['POST'])
@swagger_route(
    security=get_auth_security()
)
@login_required
def clear_plugin_logs():
    """Clear plugin invocation logs (admin only or for testing)."""
    try:
        # Note: You might want to add admin role checking here
        plugin_logger = get_plugin_logger()
        
        # Get count before clearing
        previous_count = len(plugin_logger.invocations)
        
        # Clear the logs
        plugin_logger.clear_history()
        
        log_event(
            "[Plugin Logging API] Cleared plugin invocation logs",
            extra={
                "requester_user_id": get_current_user_id(),
                "previous_log_count": previous_count
            },
            level=logging.WARNING  # Use WARNING since this is a destructive action
        )
        
        return jsonify({
            "message": "Plugin invocation logs cleared successfully",
            "previous_count": previous_count
        }), 200
        
    except Exception as e:
        log_event(
            "[Plugin Logging API] Error clearing plugin logs",
            extra={"error": str(e), "requester_user_id": get_current_user_id()},
            level=logging.ERROR,
            exceptionTraceback=True
        )
        return jsonify({"error": "Failed to clear plugin logs"}), 500


@bpl.route('/api/plugins/export-logs', methods=['GET'])
@swagger_route(
    security=get_auth_security()
)
@login_required
def export_plugin_logs():
    """Export plugin invocation logs for the current user."""
    try:
        user_id = get_current_user_id()
        plugin_logger = get_plugin_logger()
        
        # Get all user invocations
        user_invocations = plugin_logger.get_invocations_for_user(user_id, 10000)  # Large limit for export
        
        # Format for export
        export_data = {
            "export_timestamp": plugin_logger.invocations[-1].timestamp if plugin_logger.invocations else None,
            "user_id": user_id,
            "total_invocations": len(user_invocations),
            "invocations": [inv.to_dict() for inv in user_invocations]
        }
        
        log_event(
            "[Plugin Logging API] Exported plugin invocation logs",
            extra={
                "user_id": user_id,
                "exported_count": len(user_invocations)
            },
            level=logging.INFO
        )
        
        return jsonify(export_data), 200
        
    except Exception as e:
        log_event(
            "[Plugin Logging API] Error exporting plugin logs",
            extra={"error": str(e), "user_id": get_current_user_id()},
            level=logging.ERROR,
            exceptionTraceback=True
        )
        return jsonify({"error": "Failed to export plugin logs"}), 500
