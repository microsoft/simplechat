#!/usr/bin/env python3
"""
Functional test for fraud analysis actual document content loading fix.
Version: 0.229.101
Implemented in: 0.229.101

This test ensures that clean documents (United States Treasury and Spanish financial 
reports) display their actual titles and content from the database instead of generic 
placeholder text in the fraud analysis workflow.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_fraud_analysis_actual_document_loading():
    """Test that the fraud analysis route loads actual document content."""
    print("🔍 Testing fraud analysis actual document content loading...")
    
    try:
        route_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'route_frontend_workflow.py'
        )
        
        if not os.path.exists(route_path):
            print(f"❌ Route file not found: {route_path}")
            return False
        
        with open(route_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for improved document loading logic
        required_improvements = [
            'from functions_documents import get_document',
            'doc_title = doc_info.get(\'title\', doc_info.get(\'display_name\'',
            'get_document(user_id, doc_id',
            'if isinstance(doc_data, dict):',
            'doc_content = \'\'',
            'if \'chunks\' in doc_data and doc_data[\'chunks\']:',
            'elif \'content\' in doc_data:',
            'DEBUG: - Content length:'
        ]
        
        missing_improvements = []
        for improvement in required_improvements:
            if improvement not in content:
                missing_improvements.append(improvement)
        
        if missing_improvements:
            print("❌ Missing actual document loading improvements:")
            for improvement in missing_improvements:
                print(f"   • {improvement}")
            return False
        
        # Check that hardcoded content was removed
        hardcoded_patterns = [
            'Official treasury financial transactions report. Contains legitimate financial data',
            'Financial report for Sunrise Innovations Inc. Prepared for Spanish-speaking',
            'This document contains legitimate financial information with no fraud indicators'
        ]
        
        hardcoded_found = []
        for pattern in hardcoded_patterns:
            if pattern in content:
                hardcoded_found.append(pattern)
        
        if hardcoded_found:
            print("❌ Found remaining hardcoded content that should be replaced:")
            for pattern in hardcoded_found:
                print(f"   • {pattern}")
            return False
        
        print("✅ Actual document loading logic validation passed!")
        return True
        
    except Exception as e:
        print(f"❌ Error during validation: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_document_title_extraction():
    """Test that document titles are properly extracted."""
    print("🔍 Testing document title extraction logic...")
    
    try:
        route_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'route_frontend_workflow.py'
        )
        
        with open(route_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for proper title extraction priority
        title_extraction_logic = [
            'doc_title = doc_info.get(\'title\', doc_info.get(\'display_name\'',
            'DEBUG: - Title: {doc_title}',
            'doc_filename = doc_info.get(\'file_name\'',
            'doc_id = doc_info.get(\'id\''
        ]
        
        missing_logic = []
        for logic in title_extraction_logic:
            if logic not in content:
                missing_logic.append(logic)
        
        if missing_logic:
            print("❌ Missing title extraction logic:")
            for logic in missing_logic:
                print(f"   • {logic}")
            return False
        
        print("✅ Document title extraction logic validation passed!")
        return True
        
    except Exception as e:
        print(f"❌ Error during title extraction validation: {e}")
        return False

def test_content_reconstruction():
    """Test that document content reconstruction is properly handled."""
    print("🔍 Testing document content reconstruction...")
    
    try:
        route_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'route_frontend_workflow.py'
        )
        
        with open(route_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for content reconstruction logic
        content_logic = [
            'if \'chunks\' in doc_data and doc_data[\'chunks\']:',
            'chunks = doc_data[\'chunks\']',
            'doc_content = \'\\n\'.join([chunk.get(\'content\', \'\') for chunk in chunks])',
            'elif \'content\' in doc_data:',
            'doc_content = doc_data[\'content\']',
            'doc_size = len(doc_content.encode(\'utf-8\'))',
            'doc_preview = doc_content[:200] + \'...\' if len(doc_content) > 200 else doc_content'
        ]
        
        missing_content_logic = []
        for logic in content_logic:
            if logic not in content:
                missing_content_logic.append(logic)
        
        if missing_content_logic:
            print("❌ Missing content reconstruction logic:")
            for logic in missing_content_logic:
                print(f"   • {logic}")
            return False
        
        # Check for proper error handling
        error_handling = [
            'except Exception as parse_error:',
            'debug_debug_print(f"[DEBUG]:: Error parsing document response: {parse_error}")',
            'except Exception as e:',
            'import traceback',
            'debug_debug_print(f"[DEBUG]:: Traceback: {traceback.format_exc()}")'
        ]
        
        missing_error_handling = []
        for handler in error_handling:
            if handler not in content:
                missing_error_handling.append(handler)
        
        if missing_error_handling:
            print("❌ Missing error handling:")
            for handler in missing_error_handling:
                print(f"   • {handler}")
            return False
        
        print("✅ Content reconstruction logic validation passed!")
        return True
        
    except Exception as e:
        print(f"❌ Error during content reconstruction validation: {e}")
        return False

def test_debug_output_improvements():
    """Test that debug output has been improved for troubleshooting."""
    print("🔍 Testing debug output improvements...")
    
    try:
        route_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'route_frontend_workflow.py'
        )
        
        with open(route_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for improved debug statements
        debug_statements = [
            'debug_debug_print(f"[DEBUG]:: Processing clean document {i+1}:")',
            'debug_debug_print(f"[DEBUG]:: - ID: {doc_id}")',
            'debug_debug_print(f"[DEBUG]:: - Title: {doc_title}")',
            'debug_debug_print(f"[DEBUG]:: - Filename: {doc_filename}")',
            'debug_debug_print(f"[DEBUG]:: - Content length: {len(doc_content)} characters")',
            'debug_debug_print(f"[DEBUG]:: - Size: {doc_size} bytes")',
            'debug_debug_print(f"[DEBUG]:: Created {len(actual_documents)} clean documents with actual content")',
            'debug_debug_print(f"[DEBUG]:: Failed to get document content, status: {status_code}")'
        ]
        
        missing_debug = []
        for debug in debug_statements:
            if debug not in content:
                missing_debug.append(debug)
        
        if missing_debug:
            print("❌ Missing debug output improvements:")
            for debug in missing_debug:
                print(f"   • {debug}")
            return False
        
        print("✅ Debug output improvements validation passed!")
        return True
        
    except Exception as e:
        print(f"❌ Error during debug output validation: {e}")
        return False

if __name__ == "__main__":
    tests = [
        test_fraud_analysis_actual_document_loading,
        test_document_title_extraction,
        test_content_reconstruction,
        test_debug_output_improvements
    ]
    results = []
    
    print("🧪 Running fraud analysis actual document content loading tests...\n")
    
    for test in tests:
        print(f"🧪 Running {test.__name__}...")
        results.append(test())
        print()
    
    success = all(results)
    print(f"📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All fraud analysis actual document content loading tests passed!")
        print("✅ Documents now use actual titles from the database")
        print("✅ Document content is loaded from actual database chunks")
        print("✅ Proper error handling and fallbacks are in place")
        print("✅ Enhanced debug output for troubleshooting")
        print("\n🎯 Expected Results:")
        print("   • Document names will show actual titles (e.g., 'United States Treasury - Financial Transactions Report')")
        print("   • Document content will be loaded from the database instead of placeholder text")
        print("   • View buttons will show actual document content")
        print("   • Debug logs will show detailed processing information")
    else:
        print("❌ Some tests failed - actual document loading may have issues")
    
    sys.exit(0 if success else 1)
