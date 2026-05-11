#!/usr/bin/env python3
"""
Functional test for enhanced PII Analysis with regex patterns.
Version: 0.228.003
Implemented in: 0.228.003

This test ensures that PII Analysis works correctly with enhanced regex patterns
and provides comprehensive pattern detection capabilities.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import requests
import json
import re

def test_regex_patterns():
    """Test regex patterns individually."""
    print("🔍 Testing PII regex patterns...")
    
    test_data = {
        'SSN': {
            'regex': r'\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b|\b(?!000|666|9\d{2})\d{3}(?!00)\d{2}(?!0000)\d{4}\b',
            'valid': ['123-45-6789', '987654321', '555-44-3333'],
            'invalid': ['000-45-6789', '123-00-6789', '123-45-0000', '666-45-6789']
        },
        'Email': {
            'regex': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            'valid': ['user@example.com', 'test.email+tag@domain.org', 'admin@company.co.uk'],
            'invalid': ['invalid.email', '@domain.com', 'user@']
        },
        'Phone': {
            'regex': r'\b(?:\+?1[-.]?)?\(?([0-9]{3})\)?[-.]?([0-9]{3})[-.]?([0-9]{4})\b|\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',
            'valid': ['(555) 123-4567', '555-123-4567', '5551234567', '+1-555-123-4567'],
            'invalid': ['555-12-34567', '55-123-4567']
        },
        'Credit Card': {
            'regex': r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3[0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b',
            'valid': ['4111111111111111', '5555555555554444', '378282246310005'],
            'invalid': ['1234567890123456', '411111111111111']
        },
        'Address': {
            'regex': r'\d+\s+[A-Za-z0-9\s,.-]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Place|Pl)\b',
            'valid': ['123 Main Street', '456 Oak Avenue', '789 Pine Blvd', '321 First St'],
            'invalid': ['Main Street', '123', 'Street Address']
        }
    }
    
    all_passed = True
    
    for pattern_type, data in test_data.items():
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
    
    return all_passed

def test_pii_analysis_api():
    """Test PII analysis API with sample document."""
    print("\n🔍 Testing PII Analysis API...")
    
    try:
        # Sample document with various PII types
        test_document = """
        John Doe
        Email: john.doe@company.com
        Phone: (555) 123-4567
        SSN: 123-45-6789
        Address: 123 Main Street, Anytown, ST 12345
        Credit Card: 4111-1111-1111-1111
        
        Additional contacts:
        - jane.smith@example.org, 987-654-3210
        - 321 Oak Avenue
        - SSN: 987-65-4321
        """
        
        # Test data for API call
        test_data = {
            'conversation_id': 'test-conversation-pii',
            'workflow_results': [{
                'filename': 'test_document.txt',
                'content': test_document
            }]
        }
        
        # Make API request
        response = requests.post(
            'http://localhost:8000/workflow/pii_analysis',
            json=test_data,
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status_code == 200:
            result = response.json()
            print("    ✅ API call successful")
            print(f"    📊 Response keys: {list(result.keys())}")
            
            if 'analysis' in result:
                analysis = result['analysis']
                print(f"    📝 Analysis length: {len(analysis)} characters")
                
                # Check if analysis contains expected PII mentions
                expected_pii = ['email', 'phone', 'ssn', 'address', 'credit']
                found_pii = []
                
                for pii_type in expected_pii:
                    if pii_type.lower() in analysis.lower():
                        found_pii.append(pii_type)
                        print(f"    ✅ Found {pii_type.upper()} reference in analysis")
                
                if len(found_pii) >= 3:  # Expect at least 3 PII types detected
                    print("    ✅ PII analysis appears comprehensive")
                    return True
                else:
                    print(f"    ⚠️ Only {len(found_pii)} PII types detected, expected more")
                    return False
            else:
                print("    ❌ No analysis in response")
                return False
        else:
            print(f"    ❌ API call failed: {response.status_code}")
            print(f"    📝 Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"    ❌ Error testing API: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_admin_settings_display():
    """Test that admin settings display the enhanced PII patterns correctly."""
    print("\n🔍 Testing Admin Settings display...")
    
    try:
        response = requests.get('http://localhost:8000/admin_settings')
        
        if response.status_code == 200:
            content = response.text
            print("    ✅ Admin settings page loaded")
            
            # Check for expected elements
            checks = [
                ('PII Analysis tab', 'pii-analysis-tab'),
                ('Regex pattern column', 'Regex Pattern'),
                ('Copy pattern button', 'copyPiiPattern'),
                ('Test regex button', 'testRegexPattern'),
                ('Pattern templates', 'piiPatternTemplates')
            ]
            
            all_found = True
            for description, search_text in checks:
                if search_text in content:
                    print(f"    ✅ Found {description}")
                else:
                    print(f"    ❌ Missing {description}")
                    all_found = False
            
            return all_found
        else:
            print(f"    ❌ Failed to load admin settings: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"    ❌ Error testing admin settings: {e}")
        return False

def main():
    """Run comprehensive PII analysis tests."""
    print("🧪 Testing Enhanced PII Analysis with Regex Patterns")
    print("=" * 60)
    
    tests = [
        ("Regex Pattern Validation", test_regex_patterns),
        ("Admin Settings Display", test_admin_settings_display),
        ("PII Analysis API", test_pii_analysis_api)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"\n🔍 Running {test_name}...")
        try:
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
        print("🎉 All tests passed! Enhanced PII Analysis is working correctly.")
    else:
        print("⚠️ Some tests failed. Please review the output above.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)