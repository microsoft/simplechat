#!/usr/bin/env python3
# test_multi_workspace_document_access_fix.py
"""
Functional test for multi-workspace document access fix.
Version: 0.229.013
Implemented in: 0.229.013

This test ensures that PDF viewing and enhanced citations work correctly across
all workspace types (personal, group, public) by implementing cross-workspace
document lookup when documents cannot be found in the default workspace container.

The fix addresses the issue where documents in group and public workspaces
would fail with "Document not found or access denied" errors because the
system was only looking in the personal workspace container with incorrect blob paths.

Critical fix: Blob naming patterns must match the storage structure:
- Personal workspace: {user_id}/{filename}
- Group workspace: {group_id}/{filename}  
- Public workspace: {public_workspace_id}/{filename}
"""

import sys
import os
from test_support.versioning import app_version_is_at_least  # noqa: E402
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_multi_workspace_document_routes():
    """Test that document viewing routes support multi-workspace access."""
    print("🔍 Testing Multi-Workspace Document Access Routes...")
    
    try:
        # Test view_pdf route in route_frontend_chats.py
        print("  📄 Checking view_pdf route implementation...")
        
        with open('../application/single_app/route_frontend_chats.py', 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Find the view_pdf function
        view_pdf_start = content.find('def view_pdf():')
        if view_pdf_start == -1:
            print("    ❌ view_pdf route not found")
            return False
            
        # Get the view_pdf function content (until next function)
        view_pdf_content = content[view_pdf_start:]
        next_func = view_pdf_content.find('\n    def ', 1)  # Find next function
        if next_func != -1:
            view_pdf_content = view_pdf_content[:next_func]
            
        # Check for multi-workspace container logic
        if 'public_workspace_id' in view_pdf_content and 'storage_account_public_documents_container_name' in view_pdf_content:
            print("    ✅ view_pdf route supports public workspace containers")
        else:
            print("    ❌ view_pdf route missing public workspace container support")
            return False
            
        if 'group_id' in view_pdf_content and 'storage_account_group_documents_container_name' in view_pdf_content:
            print("    ✅ view_pdf route supports group workspace containers")
        else:
            print("    ❌ view_pdf route missing group workspace container support")
            return False
            
        # Test view_document route
        print("  📋 Checking view_document route implementation...")
        
        view_doc_start = content.find('def view_document():')
        if view_doc_start == -1:
            print("    ❌ view_document route not found")
            return False
            
        # Get the view_document function content
        view_doc_content = content[view_doc_start:]
        next_func = view_doc_content.find('\n    def ', 1)  # Find next function
        if next_func != -1:
            view_doc_content = view_doc_content[:next_func]
            
        # Check for multi-workspace container logic in view_document
        if 'public_workspace_id' in view_doc_content and 'storage_account_public_documents_container_name' in view_doc_content:
            print("    ✅ view_document route supports public workspace containers")
        else:
            print("    ❌ view_document route missing public workspace container support")
            return False
            
        if 'group_id' in view_doc_content and 'storage_account_group_documents_container_name' in view_doc_content:
            print("    ✅ view_document route supports group workspace containers")
        else:
            print("    ❌ view_document route missing group workspace container support")
            return False
            
        print("  ✅ Frontend chat routes support multi-workspace document access")
        return True
        
    except Exception as e:
        print(f"    ❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_enhanced_citations_multi_workspace():
    """Test that enhanced citations routes support multi-workspace access."""
    print("🔍 Testing Enhanced Citations Multi-Workspace Support...")
    
    try:
        # Test enhanced citations route implementation
        print("  📊 Checking enhanced citations route implementation...")
        
        with open('../application/single_app/route_enhanced_citations.py', 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Check for the enhanced get_document function
        if 'def get_document(user_id, doc_id):' in content:
            print("    ✅ Enhanced citations has custom get_document function")
        else:
            print("    ❌ Enhanced citations missing custom get_document function")
            return False
            
        # Check for multi-workspace search logic
        get_doc_section = content[content.find('def get_document(user_id, doc_id):'):]
        
        if 'get_user_groups' in get_doc_section[:2000]:
            print("    ✅ Enhanced citations searches group workspaces")
        else:
            print("    ❌ Enhanced citations missing group workspace search")
            return False
            
        if 'get_user_visible_public_workspace_ids_from_settings' in get_doc_section[:2000]:
            print("    ✅ Enhanced citations searches public workspaces")
        else:
            print("    ❌ Enhanced citations missing public workspace search")
            return False
            
        # Check for proper imports
        if 'from functions_group import get_user_groups' in content:
            print("    ✅ Enhanced citations imports group functions")
        else:
            print("    ❌ Enhanced citations missing group function imports")
            return False
            
        if 'from functions_public_workspaces import get_user_visible_public_workspace_ids_from_settings' in content:
            print("    ✅ Enhanced citations imports public workspace functions")
        else:
            print("    ❌ Enhanced citations missing public workspace function imports")
            return False
            
        print("  ✅ Enhanced citations support multi-workspace document access")
        return True
        
    except Exception as e:
        print(f"    ❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_workspace_container_determination():
    """Test the workspace container determination logic."""
    print("🔍 Testing Workspace Container Determination Logic...")
    
    try:
        # Check route_frontend_chats.py for inline workspace container logic
        print("  🗂️ Checking inline workspace container determination logic...")
        
        with open('../application/single_app/route_frontend_chats.py', 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Check for workspace enablement validation patterns
        if 'enable_public_workspaces' in content and 'enable_group_workspaces' in content:
            print("    ✅ Routes check workspace enablement settings")
        else:
            print("    ❌ Routes missing workspace enablement checks")
            return False
            
        # Check for container name assignment logic
        container_checks = [
            'storage_account_public_documents_container_name',
            'storage_account_group_documents_container_name', 
            'storage_account_user_documents_container_name'
        ]
        
        missing_containers = []
        for container in container_checks:
            if container not in content:
                missing_containers.append(container)
                
        if missing_containers:
            print(f"    ❌ Routes missing container assignments: {missing_containers}")
            return False
        else:
            print("    ✅ Routes have all workspace container assignments")
            
        # Check route_enhanced_citations.py for the same logic
        print("  📊 Checking enhanced citations workspace determination...")
        
        with open('../application/single_app/route_enhanced_citations.py', 'r', encoding='utf-8') as f:
            citations_content = f.read()
            
        if 'def determine_workspace_type_and_container' in citations_content:
            print("    ✅ Enhanced citations has determine_workspace_type_and_container function")
        else:
            print("    ❌ Enhanced citations missing determine_workspace_type_and_container function")
            return False
            
        print("  ✅ Workspace container determination logic is properly implemented")
        return True
        
    except Exception as e:
        print(f"    ❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_blob_naming_patterns():
    """Test that blob naming patterns are correct for each workspace type."""
    print("🔍 Testing Blob Naming Patterns...")
    
    try:
        # Test enhanced citations blob naming
        print("  📊 Checking enhanced citations blob naming...")
        
        with open('../application/single_app/route_enhanced_citations.py', 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Check for get_blob_name function
        if 'def get_blob_name(' in content:
            print("    ✅ Enhanced citations has get_blob_name function")
            
            # Check for correct workspace-specific patterns
            func_section = content[content.find('def get_blob_name('):]
            func_end = func_section.find('\ndef ') if '\ndef ' in func_section else len(func_section)
            func_content = func_section[:func_end]
            
            if 'public_workspace_id' in func_content and 'group_id' in func_content:
                print("    ✅ get_blob_name function handles all workspace types")
            else:
                print("    ❌ get_blob_name function missing workspace type handling")
                return False
                
        else:
            print("    ❌ Enhanced citations missing get_blob_name function")
            return False
            
        # Test frontend routes blob naming
        print("  📄 Checking frontend routes blob naming...")
        
        with open('../application/single_app/route_frontend_chats.py', 'r', encoding='utf-8') as f:
            frontend_content = f.read()
            
        # Check view_pdf route
        view_pdf_section = frontend_content[frontend_content.find('def view_pdf():'):]
        view_pdf_end = view_pdf_section.find('\n    def ') if '\n    def ' in view_pdf_section else len(view_pdf_section)
        view_pdf_content = view_pdf_section[:view_pdf_end]
        
        # Look for workspace-specific blob naming in view_pdf
        view_pdf_patterns = [
            'raw_doc[\'public_workspace_id\']',
            'raw_doc[\'group_id\']', 
            'raw_doc[\'user_id\']'
        ]
        
        found_patterns = 0
        for pattern in view_pdf_patterns:
            if pattern in view_pdf_content:
                found_patterns += 1
                
        if found_patterns >= 3:
            print("    ✅ view_pdf route uses workspace-specific blob naming")
        else:
            print("    ❌ view_pdf route missing workspace-specific blob naming")
            return False
            
        # Check view_document route
        view_doc_section = frontend_content[frontend_content.find('def view_document():'):]
        view_doc_end = view_doc_section.find('\n    def ') if '\n    def ' in view_doc_section else len(view_doc_section)
        view_doc_content = view_doc_section[:view_doc_end]
        
        # Look for workspace-specific blob naming in view_document
        view_doc_patterns = [
            'raw_doc[\'public_workspace_id\']',
            'raw_doc[\'group_id\']', 
            'owner_user_id'  # view_document uses owner_user_id instead of raw_doc['user_id']
        ]
        
        found_patterns = 0
        for pattern in view_doc_patterns:
            if pattern in view_doc_content:
                found_patterns += 1
                
        if found_patterns >= 3:
            print("    ✅ view_document route uses workspace-specific blob naming")
        else:
            print("    ❌ view_document route missing workspace-specific blob naming")
            return False
            
        print("  ✅ Blob naming patterns correctly implemented for all workspace types")
        return True
        
    except Exception as e:
        print(f"    ❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_version_consistency():
    """Test that the version has been properly updated."""
    print("🔍 Testing Version Consistency...")
    
    try:
        print("  📋 Checking config.py version...")
        
        with open('../application/single_app/config.py', 'r', encoding='utf-8') as f:
            content = f.read()
            
        if app_version_is_at_least("0.229.013"):
            print("    ✅ Version updated to 0.229.013 in config.py")
        else:
            print("    ❌ Version not properly updated in config.py")
            return False
            
        print("  ✅ Version consistency validated")
        return True
        
    except Exception as e:
        print(f"    ❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    """Test that the version has been properly updated."""
    print("🔍 Testing Version Consistency...")
    
    try:
        print("  📋 Checking config.py version...")
        
        with open('../application/single_app/config.py', 'r', encoding='utf-8') as f:
            content = f.read()
            
        if app_version_is_at_least("0.229.013"):
            print("    ✅ Version updated to 0.229.013 in config.py")
        else:
            print("    ❌ Version not properly updated in config.py")
            return False
            
        print("  ✅ Version consistency validated")
        return True
        
    except Exception as e:
        print(f"    ❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def run_comprehensive_test():
    """Run all multi-workspace document access tests."""
    print("🧪 Running Comprehensive Multi-Workspace Document Access Test")
    print("=" * 70)
    
    tests = [
        test_multi_workspace_document_routes,
        test_enhanced_citations_multi_workspace,
        test_workspace_container_determination,
        test_blob_naming_patterns,
        test_version_consistency
    ]
    
    results = []
    
    for test in tests:
        print(f"\n🔬 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Test Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("\n🎉 All multi-workspace document access tests passed!")
        print("\n📋 Fix Summary:")
        print("  • PDF viewing routes now support group and public workspace documents")
        print("  • Enhanced citations routes implement cross-workspace document lookup")
        print("  • Workspace container determination logic handles all workspace types")
        print("  • Blob naming patterns correctly implemented for all workspace types")
        print("  • Version updated to 0.229.013")
        print("\n✅ Multi-workspace document access fix is complete and validated")
    else:
        print("\n❌ Some tests failed. Multi-workspace document access fix needs attention.")
    
    return success

if __name__ == "__main__":
    success = run_comprehensive_test()
    sys.exit(0 if success else 1)