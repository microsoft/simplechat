#!/usr/bin/env python3
"""
Fix SSN regex pattern and test all patterns.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from functions_settings import get_settings, update_settings
import re

def fix_ssn_regex():
    """Fix the SSN regex pattern."""
    print("🔧 Fixing SSN regex pattern...")
    
    try:
        settings = get_settings()
        
        # Fix SSN regex pattern to handle all formats
        for pattern in settings.get('pii_analysis_patterns', []):
            if pattern.get('pattern_type') == 'SSN':
                # Updated regex that handles all common SSN formats
                pattern['regex'] = r'\b(?!000|666|9\d{2})\d{3}[-\s]?(?!00)\d{2}[-\s]?(?!0000)\d{4}\b'
                print(f"  ✅ Updated SSN regex pattern")
                break
        
        result = update_settings(settings)
        print(f"✅ Settings update result: {result}")
        
        # Test the new SSN pattern
        ssn_pattern = re.compile(r'\b(?!000|666|9\d{2})\d{3}[-\s]?(?!00)\d{2}[-\s]?(?!0000)\d{4}\b')
        test_ssns = ['123-45-6789', '987-65-4321', '555 44 3333', '123456789']
        
        print("\n🧪 Testing updated SSN pattern:")
        for test_ssn in test_ssns:
            match = ssn_pattern.search(test_ssn)
            status = "✅ Match" if match else "❌ No match"
            print(f"  {test_ssn}: {status}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error fixing SSN pattern: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = fix_ssn_regex()
    sys.exit(0 if success else 1)