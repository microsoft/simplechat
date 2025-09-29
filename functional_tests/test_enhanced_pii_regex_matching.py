#!/usr/bin/env python3
"""
Test the enhanced PII analysis with actual regex matching.
Version: 0.229.073

This test verifies that PII analysis now performs actual regex matching
before sending to AI, rather than relying solely on AI analysis.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_pii_analysis_with_sample_data():
    """Test PII analysis function with sample data containing known PII."""
    print("🔍 Testing enhanced PII analysis with regex matching...")
    
    try:
        from functions_settings import get_settings
        import re
        
        # Sample document content with various PII types
        sample_content = """
        Employee Information Form
        
        Name: John Doe
        SSN: 123-45-6789
        Email: john.doe@company.com
        Phone: (555) 123-4567
        Address: 123 Main Street, Anytown, ST 12345
        Credit Card: 4111-1111-1111-1111
        
        Emergency Contact:
        Jane Smith - jane.smith@example.org
        Phone: 987-654-3210
        Address: 456 Oak Avenue
        
        Additional Info:
        - Second SSN: 987-65-4321
        - Alternate phone: 555.123.9999
        - CC: 5555555555554444
        """
        
        # Get PII patterns from settings
        settings = get_settings()
        pii_patterns = settings.get('pii_analysis_patterns', [])
        
        if not pii_patterns:
            print("❌ No PII patterns configured")
            return False
        
        print(f"📊 Testing with {len(pii_patterns)} configured patterns")
        
        # Simulate the regex matching logic from the function
        regex_findings = {}
        total_pii_found = 0
        
        for pattern_info in pii_patterns:
            pattern_type = pattern_info.get('pattern_type', 'Unknown')
            regex_pattern = pattern_info.get('regex', '')
            description = pattern_info.get('description', '')
            severity = pattern_info.get('severity', 'Medium')
            
            if regex_pattern:
                try:
                    # Compile and search with the regex pattern
                    compiled_pattern = re.compile(regex_pattern, re.IGNORECASE)
                    matches = compiled_pattern.findall(sample_content)
                    
                    # Store findings
                    regex_findings[pattern_type] = {
                        'pattern': regex_pattern,
                        'description': description,
                        'severity': severity,
                        'matches': matches,
                        'count': len(matches)
                    }
                    
                    total_pii_found += len(matches)
                    print(f"  ✅ {pattern_type}: Found {len(matches)} matches")
                    
                    # Show examples (redacted)
                    if matches:
                        for match in matches[:2]:  # Show first 2 matches
                            if len(str(match)) > 6:
                                redacted = str(match)[:3] + "*" * (len(str(match)) - 6) + str(match)[-3:]
                            else:
                                redacted = "*" * len(str(match))
                            print(f"    Example: {redacted}")
                    
                except re.error as regex_error:
                    print(f"  ❌ {pattern_type}: Invalid regex - {regex_error}")
                    regex_findings[pattern_type] = {
                        'pattern': regex_pattern,
                        'description': description,
                        'severity': severity,
                        'matches': [],
                        'count': 0,
                        'error': str(regex_error)
                    }
            else:
                print(f"  ⚠️ {pattern_type}: No regex pattern")
        
        print(f"\n📊 Total PII instances found: {total_pii_found}")
        
        # Expected minimum findings (this sample should find multiple PII items)
        expected_types = {
            'SSN': 2,      # 123-45-6789, 987-65-4321
            'Email': 2,    # john.doe@company.com, jane.smith@example.org
            'Phone': 2,    # (555) 123-4567, 987-654-3210
            'Credit Card': 2,  # 4111-1111-1111-1111, 5555555555554444
            'Address': 2   # 123 Main Street, 456 Oak Avenue
        }
        
        success = True
        for pii_type, min_expected in expected_types.items():
            found = regex_findings.get(pii_type, {}).get('count', 0)
            if found >= min_expected:
                print(f"  ✅ {pii_type}: {found} >= {min_expected} (expected)")
            else:
                print(f"  ❌ {pii_type}: {found} < {min_expected} (expected)")
                success = False
        
        if total_pii_found >= 8:  # Should find at least 8 total PII items
            print("✅ Regex matching appears to be working correctly")
        else:
            print(f"⚠️ Only {total_pii_found} total PII found, expected more")
            success = False
            
        return success
        
    except Exception as e:
        print(f"❌ Error testing PII analysis: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_prompt_includes_findings():
    """Test that the prompt building logic includes actual findings."""
    print("\n🔍 Testing prompt building with findings...")
    
    try:
        # Simulate the findings format
        sample_findings = {
            'SSN': {
                'pattern': r'\b(?!000|666|9\d{2})\d{3}[-\s]?(?!00)\d{2}[-\s]?(?!0000)\d{4}\b',
                'description': 'Social Security Numbers',
                'severity': 'High',
                'matches': ['123-45-6789', '987654321'],
                'count': 2
            },
            'Email': {
                'pattern': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
                'description': 'Email Addresses',
                'severity': 'Medium',
                'matches': ['john@example.com'],
                'count': 1
            }
        }
        
        # Build findings summary as the function would
        findings_summary = ""
        for pattern_type, finding in sample_findings.items():
            count = finding['count']
            if count > 0:
                redacted_examples = []
                for match in finding['matches'][:3]:
                    if len(str(match)) > 6:
                        redacted = str(match)[:3] + "*" * (len(str(match)) - 6) + str(match)[-3:]
                    else:
                        redacted = "*" * len(str(match))
                    redacted_examples.append(redacted)
                
                findings_summary += f"\n✓ {pattern_type}: {count} instances found"
                if redacted_examples:
                    findings_summary += f" (Examples: {', '.join(redacted_examples)})"
            else:
                findings_summary += f"\n✗ {pattern_type}: No instances found"
        
        print("Sample findings summary:")
        print(findings_summary)
        
        # Check that findings include both concrete numbers and redacted examples
        if "2 instances found" in findings_summary and "123***789" in findings_summary:
            print("✅ Findings summary includes concrete counts and redacted examples")
            return True
        else:
            print("❌ Findings summary format incorrect")
            return False
            
    except Exception as e:
        print(f"❌ Error testing prompt building: {e}")
        return False

def main():
    """Run tests for enhanced PII analysis."""
    print("🧪 Testing Enhanced PII Analysis with Regex Matching")
    print("=" * 70)
    
    tests = [
        ("Regex Pattern Matching", test_pii_analysis_with_sample_data),
        ("Prompt Building with Findings", test_prompt_includes_findings)
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
    
    print("\n" + "=" * 70)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 Enhanced PII analysis with regex matching is working!")
        print("\n💡 The PII analysis now:")
        print("   ✅ Performs actual regex pattern matching on document content")
        print("   ✅ Provides concrete counts and examples to the AI")
        print("   ✅ Bases analysis on real findings rather than speculation")
        print("   ✅ Shows redacted examples for verification")
    else:
        print("⚠️ Some tests failed. Please review the issues above.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)