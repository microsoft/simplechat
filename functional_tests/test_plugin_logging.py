# test_plugin_logging.py
"""
Test script to verify plugin logging is working correctly.
Run this to see plugin invocation logs in the terminal.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from semantic_kernel_plugins.plugin_invocation_logger import get_plugin_logger, log_plugin_invocation
import time

def test_plugin_logging():
    """Test the plugin logging system."""
    print("🔍 Testing Plugin Invocation Logging System...")
    
    # Get the plugin logger
    plugin_logger = get_plugin_logger()
    
    # Simulate some plugin invocations
    test_invocations = [
        {
            "plugin_name": "SQLSchemaPlugin",
            "function_name": "get_schema",
            "parameters": {"include_system": False},
            "result": {"tables": ["users", "orders", "products"]},
            "success": True,
            "error_message": None
        },
        {
            "plugin_name": "SQLQueryPlugin", 
            "function_name": "execute_query",
            "parameters": {"query": "SELECT * FROM users LIMIT 10"},
            "result": None,
            "success": False,
            "error_message": "Database connection failed"
        },
        {
            "plugin_name": "OpenApiPlugin",
            "function_name": "call_operation",
            "parameters": {"operation_id": "getUserById", "user_id": "123"},
            "result": {"id": "123", "name": "John Doe"},
            "success": True,
            "error_message": None
        }
    ]
    
    # Log the test invocations
    for i, inv in enumerate(test_invocations):
        start_time = time.time()
        time.sleep(0.1)  # Simulate execution time
        end_time = time.time()
        
        print(f"📝 Logging test invocation {i+1}: {inv['plugin_name']}.{inv['function_name']}")
        
        log_plugin_invocation(
            plugin_name=inv["plugin_name"],
            function_name=inv["function_name"],
            parameters=inv["parameters"],
            result=inv["result"],
            start_time=start_time,
            end_time=end_time,
            success=inv["success"],
            error_message=inv["error_message"]
        )
    
    # Display statistics
    print("\n📊 Plugin Usage Statistics:")
    stats = plugin_logger.get_plugin_stats()
    
    print(f"Total invocations: {stats.get('total_invocations', 0)}")
    print(f"Successful: {stats.get('successful_invocations', 0)}")
    print(f"Failed: {stats.get('failed_invocations', 0)}")
    print(f"Average duration: {stats.get('average_duration_ms', 0):.2f}ms")
    
    # Display per-plugin stats
    if stats.get('plugins'):
        print("\n🔌 Per-Plugin Statistics:")
        for plugin_name, plugin_stats in stats['plugins'].items():
            print(f"  {plugin_name}:")
            print(f"    Total calls: {plugin_stats['total_calls']}")
            print(f"    Success rate: {plugin_stats['successful_calls']}/{plugin_stats['total_calls']}")
            print(f"    Average duration: {plugin_stats['average_duration_ms']:.2f}ms")
    
    # Display recent invocations
    print("\n📜 Recent Invocations:")
    recent = plugin_logger.get_recent_invocations(10)
    for inv in recent:
        status = "✅" if inv.success else "❌"
        print(f"  {status} {inv.plugin_name}.{inv.function_name} ({inv.duration_ms:.2f}ms)")
        if not inv.success and inv.error_message:
            print(f"    Error: {inv.error_message}")
    
    print("\n✅ Plugin logging test completed!")
    print("🔔 Check your Application Insights for structured logs!")

if __name__ == "__main__":
    test_plugin_logging()
