#!/usr/bin/env python3
"""
Add missing Address pattern to PII analysis.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from functions_settings import get_settings, update_settings

def add_address_pattern():
    """Add Address pattern if missing."""
    print("🔍 Checking for Address pattern...")
    
    try:
        settings = get_settings()
        
        # Address pattern definition
        address_pattern = {
            'pattern_type': 'Address',
            'description': 'Physical street addresses including house numbers and street names',
            'regex': r'\d+\s+[A-Za-z0-9\s,.-]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Place|Pl)\b'
        }
        
        # Check if Address pattern already exists
        existing_types = [p.get('pattern_type') for p in settings.get('pii_analysis_patterns', [])]
        
        if 'Address' not in existing_types:
            settings['pii_analysis_patterns'].append(address_pattern)
            result = update_settings(settings)
            print(f"✅ Added Address pattern. Result: {result}")
        else:
            print("⏭️ Address pattern already exists")
        
        print("\n📊 Current patterns:")
        for pattern in settings.get('pii_analysis_patterns', []):
            pattern_type = pattern.get('pattern_type', 'Unknown')
            description = pattern.get('description', 'No description')
            has_regex = 'Yes' if pattern.get('regex') else 'No'
            print(f"  - {pattern_type}: {description[:50]}... | Regex: {has_regex}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error adding Address pattern: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = add_address_pattern()
    sys.exit(0 if success else 1)