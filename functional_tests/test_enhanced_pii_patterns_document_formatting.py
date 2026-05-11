#!/usr/bin/env python3
"""
Test enhanced PII patterns against actual document formatting.
Version: 0.229.078
Implemented in: 0.229.078

This test validates the enhanced PII regex patterns work correctly 
with the actual formatting found in the document intelligence extraction.
"""

import re
import sys

def test_enhanced_pii_patterns():
    """Test enhanced PII patterns against actual document text."""
    print("🔍 Testing Enhanced PII Patterns...")
    
    # Sample text from the actual document debug output
    test_text = """
Johnathan R. Maple
000-12- 3456
123 Fictional Rd
Chicago, IL 00001
(000) 555- 0001
j.placeholder001@training.example.com
4000-0000- 0000-0001

Eleanor K. Fictus
000-98- 7654
456 Mockingbird Ln
Metropolis, CA 00004
(000) 555- 0004
s.placeholder00 04@training.exa mple.com
4000-0000- 0000-0004
"""
    
    # Enhanced patterns from the updated code
    patterns = {
        "SSN": r"\b\d{3}[\s\-]*\d{2}[\s\-]*\d{4}\b",
        "Phone": r"\b\(?\d{3}\)?[\s\-\.]*\d{3}[\s\-\.]*\d{4}\b",
        "Credit Card": r"\b4\d{3}[\s\-]*\d{4}[\s\-]*\d{4}[\s\-]*\d{4}\b",
        "Address": r"\b\d{1,5}\s+[A-Za-z][A-Za-z\s]*(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr)\b",
        "Email": r"\b[A-Za-z0-9._%+-]+\s*@\s*[A-Za-z0-9.-]+\s*\.\s*[A-Z|a-z]{2,}\b"
    }
    
    results = {}
    all_passed = True
    
    for pattern_name, pattern in patterns.items():
        try:
            compiled_pattern = re.compile(pattern, re.IGNORECASE)
            matches = compiled_pattern.findall(test_text)
            results[pattern_name] = matches
            
            print(f"\n📋 {pattern_name} Pattern Results:")
            print(f"   Pattern: {pattern}")
            print(f"   Matches found: {len(matches)}")
            
            if matches:
                for i, match in enumerate(matches, 1):
                    print(f"     {i}. {match}")
            else:
                print("     No matches found")
                
        except Exception as e:
            print(f"❌ Error testing {pattern_name} pattern: {e}")
            all_passed = False
    
    # Expected results validation
    expected_results = {
        "SSN": 2,  # Should find both "000-12- 3456" and "000-98- 7654"
        "Phone": 2,  # Should find both "(000) 555- 0001" and "(000) 555- 0004"
        "Credit Card": 2,  # Should find both "4000-0000- 0000-0001" and "4000-0000- 0000-0004"
        "Address": 2,  # Should find "123 Fictional Rd" and "456 Mockingbird Ln"
        "Email": 2   # Should find both email addresses
    }
    
    print(f"\n📊 Validation Results:")
    for pattern_name, expected_count in expected_results.items():
        actual_count = len(results.get(pattern_name, []))
        status = "✅" if actual_count >= expected_count else "❌"
        print(f"   {status} {pattern_name}: Expected ≥{expected_count}, Found {actual_count}")
        
        if actual_count < expected_count:
            all_passed = False
    
    if all_passed:
        print("\n✅ All enhanced PII patterns working correctly!")
        return True
    else:
        print("\n❌ Some patterns need further refinement.")
        return False

if __name__ == "__main__":
    success = test_enhanced_pii_patterns()
    sys.exit(0 if success else 1)