#!/usr/bin/env python3
"""
Enable debug logging in settings.
Version: 0.230.034

This enables debug_print() statements to show up in console output.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def enable_debug_logging():
    """Enable debug logging in app settings."""
    print("🔧 Enabling debug logging...")
    
    try:
        from functions_settings import get_settings, update_settings
        
        settings = get_settings()
        if not settings:
            print("❌ Could not retrieve settings")
            return False
            
        # Enable debug logging
        settings['enable_debug_logging'] = True
        
        # Update settings
        success = update_settings(settings)
        
        if success:
            print("✅ Debug logging enabled successfully!")
            print("🔍 debug_print() statements will now appear in console output")
            return True
        else:
            print("❌ Failed to update settings")
            return False
            
    except Exception as e:
        print(f"❌ Error enabling debug logging: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = enable_debug_logging()
    sys.exit(0 if success else 1)