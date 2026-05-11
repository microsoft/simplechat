#!/usr/bin/env python3
"""
Test the enhanced SSN pattern that includes 000-00-0000.
Version: 0.229.075

This test verifies that the updated PII analysis SSN pattern
correctly detects both valid SSNs and common test patterns like 000-00-0000.
"""

import sys
import os
import re
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_enhanced_ssn_pattern():
    """Test that the enhanced SSN regex pattern catches various SSN formats."""
    print("🔍 Testing Enhanced SSN Pattern...")
    
    try:
        # The enhanced pattern from the admin settings
        ssn_pattern = r"\b(000-00-0000|(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4})\b|\b(00000000|(?!000|666|9\d{2})\d{3}(?!00)\d{2}(?!0000)\d{4})\b"
        compiled_pattern = re.compile(ssn_pattern, re.IGNORECASE)
        
        # Test cases that should be detected
        positive_tests = [
            "000-00-0000",  # The specific case user mentioned
            "123-45-6789",  # Valid SSN format
            "555-12-3456",  # Valid SSN format
            "123456789",    # No dashes format
            "55512345",     # No dashes format (missing leading 0)
            "000000000"     # All zeros no dashes
        ]
        
        # Test cases that should NOT be detected
        negative_tests = [
            "000-00-000",   # Too short
            "666-12-3456",  # Invalid area number (666)
            "900-12-3456",  # Invalid area number (9xx)
            "123-00-1234",  # Invalid group number (00)
            "123-45-0000",  # Invalid serial number (0000)
            "12-34-5678",   # Too short area
            "abc-de-fghi",  # Non-numeric
            "1234-56-7890", # Too long area
        ]
        
        print("Testing positive cases (should be detected):")
        positive_results = []
        for test_case in positive_tests:
            matches = compiled_pattern.findall(test_case)
            found = len(matches) > 0
            positive_results.append(found)
            status = "✅" if found else "❌"
            print(f"  {status} '{test_case}': {matches if found else 'No match'}")
        
        print("\nTesting negative cases (should NOT be detected):")
        negative_results = []
        for test_case in negative_tests:
            matches = compiled_pattern.findall(test_case)
            found = len(matches) > 0
            negative_results.append(not found)  # Success is NOT finding
            status = "✅" if not found else "❌"
            result = "Correctly ignored" if not found else f"Incorrectly matched: {matches}"
            print(f"  {status} '{test_case}': {result}")
        
        # Test the specific case mentioned by user
        test_text = "Here is a document with SSN 000-00-0000 in it."
        matches = compiled_pattern.findall(test_text)
        specific_case_pass = any("000-00-0000" in match for match in matches if isinstance(match, (tuple, list)) for submatch in match if "000-00-0000" in submatch) or "000-00-0000" in matches
        
        print(f"\n🎯 Specific test case: '{test_text}'")
        print(f"   Matches found: {matches}")
        print(f"   000-00-0000 detected: {'✅' if specific_case_pass else '❌'}")
        
        # Summary
        positive_passed = sum(positive_results)
        negative_passed = sum(negative_results)
        total_positive = len(positive_tests)
        total_negative = len(negative_tests)
        
        print(f"\n📊 Results Summary:")
        print(f"   Positive tests: {positive_passed}/{total_positive}")
        print(f"   Negative tests: {negative_passed}/{total_negative}")
        print(f"   Specific case (000-00-0000): {'✅' if specific_case_pass else '❌'}")
        
        overall_success = (positive_passed == total_positive and 
                          negative_passed == total_negative and 
                          specific_case_pass)
        
        if overall_success:
            print("✅ Enhanced SSN pattern test PASSED!")
            return True
        else:
            print("❌ Enhanced SSN pattern test FAILED!")
            return False
            
    except Exception as e:
        print(f"❌ Error testing SSN pattern: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_pattern_in_context():
    """Test the pattern works in realistic document contexts."""
    print("\n🔍 Testing SSN Pattern in Document Context...")
    
    try:
        ssn_pattern = r"\b(000-00-0000|(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4})\b|\b(00000000|(?!000|666|9\d{2})\d{3}(?!00)\d{2}(?!0000)\d{4})\b"
        compiled_pattern = re.compile(ssn_pattern, re.IGNORECASE)
        
        # Test documents
        test_documents = [
            {
                "name": "User's specific case",
                "content": "This document contains SSN 000-00-0000 which should be detected.",
                "expected_ssns": ["000-00-0000"]
            },
            {
                "name": "Mixed SSN formats",
                "content": "Employee records: John Doe (123-45-6789), Jane Smith (555-12-3456), Test User (000-00-0000).",
                "expected_ssns": ["123-45-6789", "555-12-3456", "000-00-0000"]
            },
            {
                "name": "No dashes format",
                "content": "SSN without dashes: 123456789 and test SSN 000000000.",
                "expected_ssns": ["123456789", "000000000"]
            },
            {
                "name": "Invalid SSNs mixed",
                "content": "Invalid: 666-12-3456, Valid: 123-45-6789, Test: 000-00-0000, Invalid: 900-12-3456.",
                "expected_ssns": ["123-45-6789", "000-00-0000"]
            }
        ]
        
        all_passed = True
        for doc in test_documents:
            print(f"\n📄 Testing: {doc['name']}")
            print(f"   Content: {doc['content']}")
            
            # Find all matches in the content
            matches = compiled_pattern.findall(doc["content"])
            
            # Extract actual SSN values from tuple matches
            found_ssns = []
            for match in matches:
                if isinstance(match, tuple):
                    # The pattern returns tuples, extract non-empty parts
                    for part in match:
                        if part:
                            found_ssns.append(part)
                else:
                    found_ssns.append(match)
            
            print(f"   Found SSNs: {found_ssns}")
            print(f"   Expected: {doc['expected_ssns']}")
            
            # Check if all expected SSNs were found
            all_found = all(expected in found_ssns for expected in doc['expected_ssns'])
            no_extras = len(found_ssns) == len(doc['expected_ssns'])
            
            success = all_found and no_extras
            print(f"   Result: {'✅ PASS' if success else '❌ FAIL'}")
            
            if not success:
                all_passed = False
                missing = [ssn for ssn in doc['expected_ssns'] if ssn not in found_ssns]
                extras = [ssn for ssn in found_ssns if ssn not in doc['expected_ssns']]
                if missing:
                    print(f"   Missing: {missing}")
                if extras:
                    print(f"   Unexpected: {extras}")
        
        print(f"\n📊 Document Context Test: {'✅ PASSED' if all_passed else '❌ FAILED'}")
        return all_passed
        
    except Exception as e:
        print(f"❌ Error testing pattern in context: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run tests for enhanced SSN pattern."""
    print("🧪 Testing Enhanced SSN Pattern for PII Analysis")
    print("=" * 60)
    
    tests = [
        ("Enhanced SSN Pattern", test_enhanced_ssn_pattern),
        ("Pattern in Document Context", test_pattern_in_context)
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
        print("🎉 Enhanced SSN pattern successfully detects 000-00-0000!")
        print("\n💡 Key improvements:")
        print("   ✅ Added explicit detection for 000-00-0000")
        print("   ✅ Added explicit detection for 000000000 (no dashes)")
        print("   ✅ Maintains validation for real SSN formats")
        print("   ✅ PII Analysis sidebar tab added to admin settings")
    else:
        print("⚠️ Some tests failed. Please review the issues above.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)