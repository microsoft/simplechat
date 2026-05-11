#!/usr/bin/env python3
"""
Enhanced PII Analysis pattern testing without server dependency.
Version: 0.229.073
Implemented in: 0.229.073

This test validates the PII regex patterns and admin functionality
without requiring a running server.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

import re
from functions_settings import get_settings

def test_improved_regex_patterns():
    """Test improved regex patterns for better accuracy."""
    print("🔍 Testing improved PII regex patterns...")
    
    improved_patterns = {
        'SSN': {
            'regex': r'\b(?!000|666|9\d{2})\d{3}[-\s]?(?!00)\d{2}[-\s]?(?!0000)\d{4}\b',
            'valid': ['123-45-6789', '987-65-4321', '555 44 3333', '123456789'],
            'invalid': ['000-45-6789', '123-00-6789', '123-45-0000', '666-45-6789']
        },
        'Email': {
            'regex': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            'valid': ['user@example.com', 'test.email+tag@domain.org', 'admin@company.co.uk'],
            'invalid': ['invalid.email', '@domain.com', 'user@']
        },
        'Phone': {
            'regex': r'\b(?:\+?1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})\b',
            'valid': ['(555) 123-4567', '555-123-4567', '5551234567', '+1-555-123-4567', '555.123.4567'],
            'invalid': ['555-12-34567', '55-123-4567', '1234']
        },
        'Credit Card': {
            'regex': r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3[0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b',
            'valid': ['4111111111111111', '5555555555554444', '378282246310005'],
            'invalid': ['1234567890123456', '411111111111111']
        },
        'Address': {
            'regex': r'\b\d+\s+[A-Za-z0-9\s,.-]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Place|Pl)\b',
            'valid': ['123 Main Street', '456 Oak Avenue', '789 Pine Blvd', '321 First St'],
            'invalid': ['Main Street', '123', 'Street Address']
        }
    }
    
    all_passed = True
    
    for pattern_type, data in improved_patterns.items():
        print(f"\n  Testing {pattern_type} patterns:")
        regex = data['regex']
        pattern = re.compile(regex, re.IGNORECASE)
        
        # Test valid matches
        for valid_text in data['valid']:
            if pattern.search(valid_text):
                print(f"    ✅ '{valid_text}' - correctly matched")
            else:
                print(f"    ❌ '{valid_text}' - should match but didn't")
                all_passed = False
        
        # Test invalid non-matches
        for invalid_text in data['invalid']:
            if not pattern.search(invalid_text):
                print(f"    ✅ '{invalid_text}' - correctly rejected")
            else:
                print(f"    ❌ '{invalid_text}' - should not match but did")
                all_passed = False
    
    return all_passed, improved_patterns

def update_patterns_with_improved_regex(improved_patterns):
    """Update the stored patterns with improved regex."""
    print("\n🔧 Updating patterns with improved regex...")
    
    try:
        from functions_settings import get_settings, update_settings
        
        settings = get_settings()
        
        if 'pii_analysis_patterns' in settings:
            updated_patterns = []
            
            for pattern in settings['pii_analysis_patterns']:
                pattern_type = pattern.get('pattern_type', '')
                
                if pattern_type in improved_patterns:
                    pattern['regex'] = improved_patterns[pattern_type]['regex']
                    print(f"    ✅ Updated {pattern_type} regex")
                
                updated_patterns.append(pattern)
            
            settings['pii_analysis_patterns'] = updated_patterns
            result = update_settings(settings)
            
            print(f"\n✅ Updated patterns. Result: {result}")
            return True
        else:
            print("❌ No PII patterns found to update")
            return False
            
    except Exception as e:
        print(f"❌ Error updating patterns: {e}")
        return False

def test_comprehensive_pii_detection():
    """Test comprehensive PII detection with sample text."""
    print("\n🔍 Testing comprehensive PII detection...")
    
    sample_text = """
    Contact Information for John Doe:
    Email: john.doe@company.com
    Phone: (555) 123-4567
    SSN: 123-45-6789
    Address: 123 Main Street, Anytown, ST 12345
    Credit Card: 4111-1111-1111-1111
    
    Additional contacts:
    - jane.smith@example.org, 987-654-3210
    - 321 Oak Avenue
    - SSN: 987-65-4321
    - Phone numbers: 555.123.4567, +1-800-555-0199
    - CC: 5555555555554444
    """
    
    try:
        settings = get_settings()
        patterns = settings.get('pii_analysis_patterns', [])
        
        detected_pii = {}
        
        for pattern_info in patterns:
            pattern_type = pattern_info.get('pattern_type', '')
            regex_pattern = pattern_info.get('regex', '')
            
            if regex_pattern:
                pattern = re.compile(regex_pattern, re.IGNORECASE)
                matches = pattern.findall(sample_text)
                
                if matches:
                    detected_pii[pattern_type] = len(matches)
                    print(f"    ✅ {pattern_type}: {len(matches)} matches found")
                else:
                    print(f"    ⚠️ {pattern_type}: No matches found")
        
        # Expected minimum detections
        expected_minimums = {
            'Email': 2,
            'Phone': 3,
            'SSN': 2,
            'Credit Card': 2,
            'Address': 1
        }
        
        success = True
        for pii_type, min_expected in expected_minimums.items():
            found = detected_pii.get(pii_type, 0)
            if found >= min_expected:
                print(f"    ✅ {pii_type}: {found} >= {min_expected} (expected minimum)")
            else:
                print(f"    ❌ {pii_type}: {found} < {min_expected} (expected minimum)")
                success = False
        
        return success
        
    except Exception as e:
        print(f"❌ Error testing PII detection: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_admin_template_structure():
    """Test that the admin template file has the correct structure."""
    print("\n🔍 Testing admin template structure...")
    
    try:
        template_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            '..', 'application', 'single_app', 'templates', 'admin_settings.html'
        )
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for expected elements
        checks = [
            ('PII Analysis tab', 'pii-analysis-tab'),
            ('Regex pattern header', 'Regex Pattern'),
            ('Copy pattern function', 'copyPiiPattern'),
            ('Test regex function', 'testRegexPattern'),
            ('Pattern templates', 'piiPatternTemplates'),
            ('Five column table structure', '<th>Pattern Type</th>'),
        ]
        
        all_found = True
        for description, search_text in checks:
            if search_text in content:
                print(f"    ✅ Found {description}")
            else:
                print(f"    ❌ Missing {description}")
                all_found = False
        
        # Check for JavaScript pattern templates
        js_checks = [
            'SSN.*regex.*\\\\b',
            'Email.*regex.*@',
            'Phone.*regex.*\\\\d{3}',
            'Credit Card.*regex.*4\\[0-9\\]',
            'Address.*regex.*Street'
        ]
        
        for pattern in js_checks:
            if re.search(pattern, content, re.IGNORECASE | re.DOTALL):
                print(f"    ✅ Found JavaScript pattern template")
            else:
                print(f"    ⚠️ Missing some JavaScript pattern templates")
                break
        
        return all_found
        
    except Exception as e:
        print(f"❌ Error testing admin template: {e}")
        return False

def main():
    """Run comprehensive PII analysis tests without server dependency."""
    print("🧪 Testing Enhanced PII Analysis (Server-Independent)")
    print("=" * 60)
    
    tests = [
        ("Improved Regex Pattern Validation", lambda: test_improved_regex_patterns()[0]),
        ("Admin Template Structure", test_admin_template_structure),
        ("Comprehensive PII Detection", test_comprehensive_pii_detection)
    ]
    
    results = []
    improved_patterns = None
    
    for test_name, test_func in tests:
        print(f"\n🔍 Running {test_name}...")
        try:
            if test_name == "Improved Regex Pattern Validation":
                result, improved_patterns = test_improved_regex_patterns()
                if result and improved_patterns:
                    print("🔧 Updating stored patterns with improved regex...")
                    update_patterns_with_improved_regex(improved_patterns)
            else:
                result = test_func()
            
            results.append(result)
            status = "✅ PASSED" if result else "❌ FAILED"
            print(f"📊 {test_name}: {status}")
        except Exception as e:
            print(f"❌ {test_name}: ERROR - {e}")
            results.append(False)
    
    # Final summary
    passed = sum(results)
    total = len(results)
    
    print("\n" + "=" * 60)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Enhanced PII Analysis is ready.")
        print("\n💡 Next steps:")
        print("   1. Start the application: python app.py")
        print("   2. Go to Admin Settings > PII Analysis tab")
        print("   3. Test the pattern management features")
        print("   4. Run a workflow with PII Analysis option")
    else:
        print("⚠️ Some tests failed. Please review the output above.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)