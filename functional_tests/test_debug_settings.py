#!/usr/bin/env python3
# test_debug_settings.py
"""
Check if debug logging is enabled in settings.
Version: 0.261.474
Implemented in: 0.230.034
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from functions_settings import get_settings

def check_debug_settings():
    """Check if debug logging is enabled."""
    print("🔍 Checking debug logging settings...")
    
    try:
        settings = get_settings()
        
        if settings:
            debug_enabled = settings.get('enable_debug_logging', False)
            print(f"📊 Debug logging enabled: {debug_enabled}")
            
            if debug_enabled:
                print("✅ Debug logging is enabled - debug_print() statements will show")
            else:
                print("❌ Debug logging is disabled - debug_print() statements will be silent")
                
            # Show some other relevant settings
            print(f"📋 Enhanced citations enabled: {settings.get('enable_enhanced_citations', False)}")
            print(f"📋 Office docs auth type: {settings.get('office_docs_authentication_type', 'Not set')}")
            
            return debug_enabled
        else:
            print("❌ Could not retrieve settings")
            return False
            
    except Exception as e:
        print(f"❌ Error checking settings: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    debug_enabled = check_debug_settings()
    sys.exit(0 if debug_enabled else 1)