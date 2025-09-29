#!/usr/bin/env python3
"""
Functional test for workflow type rename and styling updates.
Version: 0.229.103
Implemented in: 0.229.103

This test ensures that:
1. "Fraud Analysis" is renamed to "Agent Analysis" in workflow types
2. highPrioritySection uses normal card styling instead of red theme
3. Content styling is handled dynamically based on fraud/clean results
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_workflow_type_rename():
    """Test that Fraud Analysis is renamed to Agent Analysis in workflow types."""
    print("🔍 Testing workflow type rename...")
    
    try:
        file_selection_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'templates', 'workflow_bulk_file_selection.html'
        )
        
        if not os.path.exists(file_selection_path):
            print(f"❌ File selection template not found: {file_selection_path}")
            return False
        
        with open(file_selection_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that "Fraud Analysis" has been replaced with "Agent Analysis"
        if 'Fraud Analysis:' in content:
            print("❌ Found 'Fraud Analysis:' text - should be replaced with 'Agent Analysis:'")
            return False
        
        if 'Agent Analysis:' not in content:
            print("❌ Missing 'Agent Analysis:' text")
            return False
        
        # Check that the description remains the same
        if 'Cross-document fraud detection' not in content:
            print("❌ Missing description 'Cross-document fraud detection'")
            return False
        
        print("✅ Workflow type rename validation passed!")
        return True
        
    except Exception as e:
        print(f"❌ Error during workflow type validation: {e}")
        return False

def test_high_priority_section_styling():
    """Test that highPrioritySection uses normal card styling."""
    print("🔍 Testing high priority section styling...")
    
    try:
        fraud_analysis_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'templates', 'workflow_bulk_fraud_analysis.html'
        )
        
        if not os.path.exists(fraud_analysis_path):
            print(f"❌ Fraud analysis template not found: {fraud_analysis_path}")
            return False
        
        with open(fraud_analysis_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that highPrioritySection no longer has fraud-result class
        if 'id="highPrioritySection" class="card mb-4 fraud-result"' in content:
            print("❌ Found 'fraud-result' class in highPrioritySection - should be removed")
            return False
        
        # Check that it has normal card styling
        if 'id="highPrioritySection" class="card mb-4"' not in content:
            print("❌ Missing normal card styling for highPrioritySection")
            return False
        
        # Check that the header doesn't have hardcoded bg-danger
        if '<div class="card-header bg-danger text-white">' in content:
            print("❌ Found hardcoded 'bg-danger text-white' in card header - should be normal")
            return False
        
        # Check that it has normal card-header
        if '<div class="card-header">' not in content:
            print("❌ Missing normal card-header styling")
            return False
        
        print("✅ High priority section styling validation passed!")
        return True
        
    except Exception as e:
        print(f"❌ Error during high priority section validation: {e}")
        return False

def test_dynamic_content_styling():
    """Test that content styling is handled dynamically in JavaScript."""
    print("🔍 Testing dynamic content styling...")
    
    try:
        fraud_analysis_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'templates', 'workflow_bulk_fraud_analysis.html'
        )
        
        with open(fraud_analysis_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for clean results styling
        clean_styling_features = [
            'header.className = \'card-header\';',
            'text-success',
            'bi-check-circle-fill',
            'Clean Financial Records - No Fraud Detected'
        ]
        
        missing_clean_features = []
        for feature in clean_styling_features:
            if feature not in content:
                missing_clean_features.append(feature)
        
        if missing_clean_features:
            print("❌ Missing clean results styling features:")
            for feature in missing_clean_features:
                print(f"   • {feature}")
            return False
        
        # Check for fraud results styling
        fraud_styling_features = [
            'text-danger',
            'bi-exclamation-triangle-fill',
            'Fictitious Revenue Detected'
        ]
        
        missing_fraud_features = []
        for feature in fraud_styling_features:
            if feature not in content:
                missing_fraud_features.append(feature)
        
        if missing_fraud_features:
            print("❌ Missing fraud results styling features:")
            for feature in missing_fraud_features:
                print(f"   • {feature}")
            return False
        
        print("✅ Dynamic content styling validation passed!")
        return True
        
    except Exception as e:
        print(f"❌ Error during dynamic styling validation: {e}")
        return False

def test_removed_hardcoded_styling():
    """Test that hardcoded red/danger styling has been removed."""
    print("🔍 Testing removal of hardcoded styling...")
    
    try:
        fraud_analysis_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'templates', 'workflow_bulk_fraud_analysis.html'
        )
        
        with open(fraud_analysis_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for removal of hardcoded danger styling in HTML (not JavaScript)
        hardcoded_html_patterns = [
            'class="card mb-4 fraud-result"',
            '<div class="card-header bg-danger text-white">',
            '<div class="card-header bg-success text-white">'  # HTML hardcoded styling, not JS
        ]
        
        found_hardcoded = []
        for pattern in hardcoded_html_patterns:
            if pattern in content:
                found_hardcoded.append(pattern)
        
        if found_hardcoded:
            print("❌ Found hardcoded styling that should be removed:")
            for pattern in found_hardcoded:
                print(f"   • {pattern}")
            return False
        
        print("✅ Hardcoded styling removal validation passed!")
        return True
        
    except Exception as e:
        print(f"❌ Error during hardcoded styling validation: {e}")
        return False

if __name__ == "__main__":
    tests = [
        test_workflow_type_rename,
        test_high_priority_section_styling,
        test_dynamic_content_styling,
        test_removed_hardcoded_styling
    ]
    results = []
    
    print("🧪 Running workflow type rename and styling update tests...\n")
    
    for test in tests:
        print(f"🧪 Running {test.__name__}...")
        results.append(test())
        print()
    
    success = all(results)
    print(f"📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All workflow type rename and styling update tests passed!")
        print("✅ 'Fraud Analysis' renamed to 'Agent Analysis' in workflow types")
        print("✅ highPrioritySection uses normal card styling")
        print("✅ Content styling is handled dynamically based on results")
        print("✅ Hardcoded red/danger styling removed")
        print("\n🎯 Expected Results:")
        print("   • Workflow selection shows 'Agent Analysis: Cross-document fraud detection'")
        print("   • Results section has normal card appearance")
        print("   • Fraud results show red text and warning icons")
        print("   • Clean results show green text and check icons")
        print("   • No hardcoded background colors on card headers")
    else:
        print("❌ Some tests failed - workflow type or styling updates may have issues")
    
    sys.exit(0 if success else 1)
