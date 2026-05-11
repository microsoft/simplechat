#!/usr/bin/env python3
"""
Functional test for public documents export functionality.
Version: 0.230.085
Implemented in: 0.230.085

This test verifies that public documents are properly included in CSV exports
and that the export UI includes public documents as an option.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_public_documents_export_support():
    """Test that public documents are supported in export functionality."""
    print("🔍 Testing Public Documents Export Support...")
    
    try:
        # Test 1: Check HTML template includes public documents checkbox
        print("\n🧪 Test 1: Verify HTML template includes public documents export option")
        
        try:
            template_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                       'application', 'single_app', 'templates', 'control_center.html')
            
            with open(template_path, 'r', encoding='utf-8') as f:
                template_content = f.read()
            
            # Check for public documents export checkbox
            assert 'value="public_documents"' in template_content, "Public documents checkbox value should be in template"
            assert 'exportPublicDocuments' in template_content, "Public documents checkbox ID should be in template"
            assert 'Public Documents' in template_content, "Public Documents label should be in template"
            assert 'bi-globe' in template_content, "Globe icon for public documents should be in template"
            assert '#006400' in template_content, "Dark green color for public documents should be in template"
            
            print("✅ HTML template properly includes public documents export option")
            
        except Exception as template_e:
            print(f"❌ Template test failed: {template_e}")
            return False
        
        # Test 2: Check backend raw data function supports public documents
        print("\n🧪 Test 2: Verify backend supports public documents in raw data")
        
        try:
            backend_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                      'application', 'single_app', 'route_backend_control_center.py')
            
            with open(backend_path, 'r', encoding='utf-8') as f:
                backend_content = f.read()
            
            # Check for public documents handling in raw data function
            assert "if 'public_documents' in charts:" in backend_content, "Backend should check for public_documents in charts"
            assert "'document_type': 'Public'" in backend_content, "Backend should set document_type to 'Public' for public docs"
            assert "cosmos_public_documents_container" in backend_content, "Backend should query public documents container"
            assert "'public_documents': public_document_records" in backend_content, "Backend should set public_documents result"
            
            print("✅ Backend properly supports public documents in raw data function")
            
        except Exception as backend_e:
            print(f"❌ Backend test failed: {backend_e}")
            return False
        
        # Test 3: Check CSV export logic includes public documents
        print("\n🧪 Test 3: Verify CSV export logic supports public documents")
        
        try:
            # Check document type handling in CSV export
            assert "'documents', 'personal_documents', 'group_documents', 'public_documents'" in backend_content, "CSV export should handle public_documents type"
            assert "'public_documents': 'Public Documents'" in backend_content, "CSV export should map public_documents to display name"
            
            print("✅ CSV export logic properly includes public documents")
            
        except Exception as csv_e:
            print(f"❌ CSV export test failed: {csv_e}")
            return False
        
        # Test 4: Check activity trends includes public documents
        print("\n🧪 Test 4: Verify activity trends includes public documents")
        
        try:
            # Check that combined documents logic includes public documents
            assert "if 'public_documents' in result:" in backend_content, "Combined documents should include public_documents"
            assert "combined_records.extend(result['public_documents'])" in backend_content, "Combined records should extend with public documents"
            
            print("✅ Activity trends properly includes public documents in combined logic")
            
        except Exception as trends_e:
            print(f"❌ Activity trends test failed: {trends_e}")
            return False
        
        print("\n📊 Test Summary:")
        print("   ✅ HTML template includes public documents export checkbox")
        print("   ✅ Backend raw data function supports public documents")  
        print("   ✅ CSV export logic handles public documents")
        print("   ✅ Activity trends includes public documents in combined view")
        
        print("\n🎯 Export Features:")
        print("   • Public Documents checkbox with globe icon and dark green color")
        print("   • Separate public documents data in raw export")
        print("   • Public documents marked with 'document_type': 'Public'")
        print("   • CSV export includes 'Public Documents' section")
        print("   • Activity trends combine personal, group, and public documents")
        
        print("\n✅ All public documents export support tests passed!")
        
        print("\n📋 Expected Export Behavior:")
        print("   • Export modal shows Personal, Group, and Public Documents options")
        print("   • Public documents exported with public workspace and user information")
        print("   • CSV format includes separate section for public document records")
        print("   • Raw data includes public_workspace_id and related metadata")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_public_documents_export_support()
    sys.exit(0 if success else 1)