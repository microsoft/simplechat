#!/usr/bin/env python3
"""
Update existing PII patterns to include regex patterns.
Version: 0.228.003
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from functions_settings import get_settings, update_settings

def update_pii_patterns_with_regex():
    """Update existing PII patterns to include regex if missing."""
    print("🔍 Updating existing PII patterns with regex...")
    
    try:
        settings = get_settings()
        
        # Regex patterns for common PII types
        regex_map = {
            'SSN': r'\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b|\b(?!000|666|9\d{2})\d{3}(?!00)\d{2}(?!0000)\d{4}\b',
            'Email': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            'Phone': r'\b(?:\+?1[-.]?)?\(?([0-9]{3})\)?[-.]?([0-9]{3})[-.]?([0-9]{4})\b|\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',
            'Credit Card': r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3[0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b',
            'Address': r'\d+\s+[A-Za-z0-9\s,.-]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Place|Pl)\b'
        }
        
        # Update existing PII patterns to include regex if missing
        if 'pii_analysis_patterns' in settings:
            updated_patterns = []
            
            for pattern in settings['pii_analysis_patterns']:
                # Add regex if missing
                if 'regex' not in pattern:
                    pattern_type = pattern.get('pattern_type', '')
                    pattern['regex'] = regex_map.get(pattern_type, '')
                    print(f"  ✅ Added regex for {pattern_type}")
                else:
                    print(f"  ⏭️ Regex already exists for {pattern.get('pattern_type', 'Unknown')}")
                
                updated_patterns.append(pattern)
            
            # Update settings
            settings['pii_analysis_patterns'] = updated_patterns
            result = update_settings(settings)
            
            print(f"\n✅ Updated PII patterns with regex. Result: {result}")
            print(f"📊 Pattern count: {len(updated_patterns)}")
            
            for pattern in updated_patterns:
                pattern_type = pattern.get('pattern_type', 'Unknown')
                has_regex = 'Yes' if pattern.get('regex') else 'No'
                print(f"  - {pattern_type}: Regex = {has_regex}")
            
            return True
            
        else:
            print("❌ No PII patterns found to update")
            return False
            
    except Exception as e:
        print(f"❌ Error updating PII patterns: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = update_pii_patterns_with_regex()
    sys.exit(0 if success else 1)