#!/usr/bin/env python3
"""
Demo script showing the debug logging toggle feature in action.
Run this to see how the debug toggle controls output.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def demo_debug_feature():
    """Demonstrate the debug logging feature."""
    print("🎯 Debug Logging Toggle Feature Demo")
    print("=" * 40)
    
    try:
        from functions_debug import debug_print, is_debug_enabled
        
        print(f"📊 Current debug status: {is_debug_enabled()}")
        print("\n🔍 Testing debug output...")
        
        # Test debug prints
        debug_print("This is a debug message")
        debug_print("This will only show if debug logging is enabled")
        debug_print("Check your admin settings to toggle this feature")
        
        print("\n📋 Instructions:")
        print("1. Go to Admin Settings")
        print("2. Click on the 'Logging' tab")
        print("3. Toggle 'Enable Debug Logging' on/off")
        print("4. Re-run this demo to see the difference")
        
        print("\n✅ Demo completed!")
        
    except Exception as e:
        print(f"❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    demo_debug_feature()