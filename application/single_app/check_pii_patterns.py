#!/usr/bin/env python3
"""
Check and fix PII patterns JSON serialization issue.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from functions_settings import get_settings, update_settings
import json
import re

def check_and_fix_patterns():
    """Check PII patterns and fix JSON serialization issues."""
    print("🔍 Checking PII patterns JSON serialization...")
    
    try:
        settings = get_settings()
        patterns = settings.get('pii_analysis_patterns', [])
        
        print(f"📊 Found {len(patterns)} patterns")
        
        # Check each pattern
        for i, pattern in enumerate(patterns):
            pattern_type = pattern.get('pattern_type', 'Unknown')
            regex = pattern.get('regex', '')
            print(f"\n{i+1}. {pattern_type}")
            print(f"   Regex: {regex}")
            
            # Test if regex is valid
            try:
                re.compile(regex)
                print(f"   ✅ Regex is valid")
            except re.error as e:
                print(f"   ❌ Invalid regex: {e}")
        
        print("\n🧪 Testing JSON serialization...")
        try:
            json_str = json.dumps(patterns, indent=2)
            print("✅ JSON serialization successful")
            print(f"📝 JSON length: {len(json_str)} characters")
            
            # Test parsing back
            parsed = json.loads(json_str)
            print("✅ JSON parsing successful")
            
        except Exception as e:
            print(f"❌ JSON serialization error: {e}")
            
            # Fix the patterns by properly escaping regex
            print("\n🔧 Fixing regex escaping...")
            fixed_patterns = []
            
            for pattern in patterns:
                fixed_pattern = pattern.copy()
                regex = pattern.get('regex', '')
                
                if regex:
                    # Properly escape backslashes for JSON
                    fixed_regex = regex.replace('\\', '\\\\')
                    fixed_pattern['regex'] = fixed_regex
                    print(f"   Fixed {pattern.get('pattern_type')}: {regex} -> {fixed_regex}")
                
                fixed_patterns.append(fixed_pattern)
            
            # Test fixed patterns
            try:
                fixed_json = json.dumps(fixed_patterns, indent=2)
                print("✅ Fixed JSON serialization successful")
                
                # Update settings with fixed patterns
                settings['pii_analysis_patterns'] = fixed_patterns
                result = update_settings(settings)
                print(f"✅ Updated settings: {result}")
                
            except Exception as fix_error:
                print(f"❌ Still having issues: {fix_error}")
                return False
        
        return True
        
    except Exception as e:
        print(f"❌ Error checking patterns: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = check_and_fix_patterns()
    sys.exit(0 if success else 1)