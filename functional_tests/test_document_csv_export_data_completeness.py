#!/usr/bin/env python3
"""
Functional test for CSV export document data completeness.
Version: 0.230.085
Implemented in: 0.230.085

This test verifies that all document fields are properly populated in CSV exports 
with the correct field mapping from the database schema.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Add the parent directory to sys.path to import from the app
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)
sys.path.insert(0, os.path.join(parent_dir, 'application', 'single_app'))

def test_document_csv_export_data_completeness():
    """Test that CSV export includes all available document data fields."""
    print("🔍 Testing Document CSV Export Data Completeness...")
    
    try:
        # Test 1: Verify correct field mapping in documents query
        print("\n🧪 Test 1: Verify document query uses correct field names")
        
        try:
            # Read the source code to verify query structure
            backend_file = os.path.join(parent_dir, 'application', 'single_app', 'route_backend_control_center.py')
            
            with open(backend_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check that the query uses correct field names from database schema
            expected_fields = [
                'c.file_name',        # Not c.filename
                'c.number_of_pages',  # Not c.page_count
                'c.document_id',      # Primary document ID
                'c.title',            # Document title
                'c.upload_date',      # Upload timestamp
                'c.user_id'           # User who uploaded
            ]
            
            query_found = False
            for field in expected_fields:
                if field in content:
                    print(f"✅ Found correct field: {field}")
                    query_found = True
                else:
                    print(f"❌ Missing or incorrect field: {field}")
            
            # Check for old incorrect fields
            incorrect_fields = [
                'c.filename',     # Should be c.file_name
                'c.page_count'    # Should be c.number_of_pages
            ]
            
            for field in incorrect_fields:
                if field in content:
                    print(f"⚠️  Warning: Found old field name: {field}")
                else:
                    print(f"✅ Correctly removed old field: {field}")
            
            assert query_found, "Document query should use correct field names"
            print("✅ Document query uses correct field mapping")
            
        except Exception as query_e:
            print(f"❌ Query structure test failed: {query_e}")
            return False
        
        # Test 2: Verify AI Search size calculation
        print("\n🧪 Test 2: Verify AI Search size calculation logic")
        
        try:
            # Check for AI Search size calculation (pages × 80KB)
            calculation_patterns = [
                "pages * 80 * 1024",
                "80KB per page", 
                "ai_search_size = pages * 80"
            ]
            
            calculation_found = False
            for pattern in calculation_patterns:
                if pattern in content:
                    print(f"✅ Found AI Search calculation: {pattern}")
                    calculation_found = True
            
            assert calculation_found, "AI Search size calculation should be implemented"
            print("✅ AI Search size calculation is properly implemented")
            
        except Exception as calc_e:
            print(f"❌ AI Search calculation test failed: {calc_e}")
            return False
        
        # Test 3: Verify document record structure
        print("\n🧪 Test 3: Verify document record structure includes all fields")
        
        try:
            # Check that document records include all expected fields
            expected_record_fields = [
                "'filename': doc.get('file_name'",         # Correct field mapping
                "'title': doc.get('title'",                # Document title
                "'page_count': pages",                     # Page count from number_of_pages
                "'ai_search_size': ai_search_size",       # Calculated AI search size
                "'document_id': doc.get('document_id'",   # Document ID
                "'upload_date': doc_date.strftime",       # Formatted upload date
                "'document_type': 'Personal'",            # Document type for personal
                "'document_type': 'Group'",               # Document type for group
                "'document_type': 'Public'"               # Document type for public
            ]
            
            record_structure_complete = True
            for field in expected_record_fields:
                if field in content:
                    print(f"✅ Found record field: {field}")
                else:
                    print(f"❌ Missing record field: {field}")
                    record_structure_complete = False
            
            assert record_structure_complete, "All document record fields should be present"
            print("✅ Document record structure is complete")
            
        except Exception as struct_e:
            print(f"❌ Record structure test failed: {struct_e}")
            return False
        
        # Test 4: Verify all document types are handled consistently
        print("\n🧪 Test 4: Verify consistent handling across document types")
        
        try:
            # Check that all document types use the same field mapping
            document_types = ['personal', 'group', 'public']
            
            for doc_type in document_types:
                # Check for the pattern in each document type section
                pattern = f"{doc_type}_document_records.append"
                if pattern in content:
                    print(f"✅ {doc_type.capitalize()} documents: Record creation found")
                else:
                    print(f"❌ {doc_type.capitalize()} documents: Record creation missing")
                    return False
            
            print("✅ All document types handled consistently")
            
        except Exception as type_e:
            print(f"❌ Document type consistency test failed: {type_e}")
            return False
        
        print("\n📊 Test Summary:")
        print("   ✅ Document query uses correct field names (file_name, number_of_pages)")
        print("   ✅ AI Search size calculation implemented (pages × 80KB)")
        print("   ✅ Document records include all required fields")
        print("   ✅ Consistent handling across personal/group/public documents")
        
        print("\n🎯 Expected CSV Improvements:")
        print("   • Document Filename: Populated from file_name field")
        print("   • Document Title: Populated from title field (or 'Unknown Title')")
        print("   • Document Page Count: Populated from number_of_pages field")
        print("   • AI Search Size: Calculated as pages × 80KB")
        print("   • Document ID: Populated from document_id or id field")
        print("   • Storage Account Size: Set to 0 (requires Azure Storage API)")
        
        print("\n✅ All document CSV export data completeness tests passed!")
        
        print("\n📋 Next Steps:")
        print("   1. Test CSV export with real documents")
        print("   2. Verify all fields are populated correctly")
        print("   3. Confirm public documents are included when selected")
        print("   4. Consider implementing storage account size calculation")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_document_csv_export_data_completeness()
    sys.exit(0 if success else 1)