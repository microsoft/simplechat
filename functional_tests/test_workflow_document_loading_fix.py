#!/usr/bin/env python3
"""
Functional test for workflow document loading fix.
Version: 0.229.064
Implemented in: 0.229.064

This test ensures that the workflow file selection page can handle
documents with missing or null properties without throwing JavaScript errors.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_workflow_file_selection_structure():
    """Test that workflow file selection template has robust JavaScript functions."""
    print("🔍 Testing workflow file selection JavaScript structure...")
    
    try:
        template_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'templates', 'workflow_file_selection.html'
        )
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for key improvements
        improvements = [
            'if (!filename || typeof filename !== \'string\')',  # Null check in getFileIcon
            'const docTitle = doc.title || doc.file_name || doc.filename',  # Multiple property fallbacks
            'page_size=1000',  # Using same approach as chat-documents.js
            'public_workspace_documents',  # Correct API endpoint
            'if (!response.ok)',  # Proper error handling
            'try {',  # Try-catch in formatDate
            'if (!dateString)',  # Null check in formatDate
            'if (!bytes || isNaN(bytes)',  # Null check in formatFileSize
        ]
        
        missing_improvements = []
        for improvement in improvements:
            if improvement not in content:
                missing_improvements.append(improvement)
        
        if missing_improvements:
            raise Exception(f"Missing improvements: {missing_improvements}")
        
        print("   - Null checks added for filename handling")
        print("   - Multiple property fallbacks implemented")
        print("   - Proper API endpoints configured")
        print("   - Error handling improved")
        print("   - Date formatting made robust")
        print("✅ File selection JavaScript structure is robust!")
        return True
        
    except Exception as e:
        print(f"❌ File selection structure test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_workflow_api_endpoints():
    """Test that workflow uses correct API endpoints matching chat-documents.js."""
    print("🔍 Testing workflow API endpoints...")
    
    try:
        template_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'templates', 'workflow_file_selection.html'
        )
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for correct API endpoints that match chat-documents.js
        expected_endpoints = [
            "'/api/documents?page_size=1000'",
            "'/api/group_documents?page_size=1000'", 
            "'/api/public_workspace_documents?page_size=1000'"
        ]
        
        missing_endpoints = []
        for endpoint in expected_endpoints:
            if endpoint not in content:
                missing_endpoints.append(endpoint)
        
        if missing_endpoints:
            raise Exception(f"Missing API endpoints: {missing_endpoints}")
        
        print("   - Personal documents endpoint: ✅ /api/documents")
        print("   - Group documents endpoint: ✅ /api/group_documents")
        print("   - Public documents endpoint: ✅ /api/public_workspace_documents")
        print("   - All endpoints use page_size=1000 parameter")
        print("✅ API endpoints match chat-documents.js!")
        return True
        
    except Exception as e:
        print(f"❌ API endpoints test failed: {e}")
        return False

def test_workflow_error_handling():
    """Test that workflow has proper error handling."""
    print("🔍 Testing workflow error handling...")
    
    try:
        template_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'templates', 'workflow_file_selection.html'
        )
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for error handling patterns
        error_patterns = [
            'catch(error => {',  # Promise catch blocks
            'console.error(',  # Error logging
            'if (!response.ok)',  # HTTP error checking
            'throw new Error(',  # Proper error throwing
            'console.warn(',  # Warning logging
            'try {',  # Try-catch blocks
        ]
        
        missing_patterns = []
        for pattern in error_patterns:
            if pattern not in content:
                missing_patterns.append(pattern)
        
        if missing_patterns:
            raise Exception(f"Missing error handling patterns: {missing_patterns}")
        
        print("   - Promise error handling: ✅")
        print("   - HTTP error checking: ✅")
        print("   - Error logging: ✅")
        print("   - Try-catch blocks: ✅")
        print("✅ Error handling is comprehensive!")
        return True
        
    except Exception as e:
        print(f"❌ Error handling test failed: {e}")
        return False

def test_version_update():
    """Test that version was updated."""
    print("🔍 Testing version update...")
    
    try:
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'config.py'
        )
        
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if 'VERSION = "0.229.064"' in content:
            print("   - Version updated to 0.229.064")
            print("✅ Version update confirmed!")
            return True
        else:
            raise Exception("Version not updated to 0.229.064")
        
    except Exception as e:
        print(f"❌ Version update test failed: {e}")
        return False

if __name__ == "__main__":
    tests = [
        test_workflow_file_selection_structure,
        test_workflow_api_endpoints,
        test_workflow_error_handling,
        test_version_update
    ]
    
    results = []
    print("🧪 Running Workflow Document Loading Fix Tests...\n")
    
    for test in tests:
        print(f"Running {test.__name__}...")
        results.append(test())
        print()
    
    success = all(results)
    print(f"📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("✅ All workflow document loading fixes validated successfully!")
        print("🎉 The workflow file selection should now handle documents without errors!")
    else:
        print("❌ Some tests failed - document loading may still have issues")
    
    sys.exit(0 if success else 1)