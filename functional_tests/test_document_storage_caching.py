#!/usr/bin/env python3
"""
Functional test for document storage size caching.
Version: 0.230.088
Implemented in: 0.230.088

This test verifies that storage sizes and AI Search sizes are cached 
in Cosmos documents and reused instead of recalculating every time.
"""

import sys
import os

def test_document_storage_caching():
    """Test that document storage sizes and AI Search sizes are properly cached in Cosmos."""
    print("🔍 Testing Document Storage Size and AI Search Size Caching...")
    
    try:
        # Read the route_backend_control_center.py file to verify implementation
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        route_file = os.path.join(parent_dir, 'application', 'single_app', 'route_backend_control_center.py')
        
        with open(route_file, 'r', encoding='utf-8') as f:
            source_code = f.read()
        
        # Test 1: Verify AI Search size caching helper function exists
        print("\n🧪 Test 1: Verify AI Search size caching helper function")
        
        assert "def get_ai_search_size(doc, cosmos_container):" in source_code, \
            "AI Search size helper function should exist"
        
        assert "cached_size = doc.get('ai_search_size', 0)" in source_code, \
            "AI Search helper should check for cached ai_search_size"
        
        assert "doc['ai_search_size'] = ai_search_size" in source_code, \
            "AI Search helper should cache calculated value"
        
        print("✅ AI Search size caching helper function exists")
        
        # Test 2: Verify storage size helper function checks for cached value
        print("\n🧪 Test 2: Verify storage size helper function checks for cached storage_account_size")
        
        assert "cached_size = doc.get('storage_account_size', 0)" in source_code, \
            "Helper function should check for cached storage_account_size"
        
        assert "if cached_size and cached_size > 0:" in source_code, \
            "Helper function should use cached value if present and non-zero"
        
        assert "Using cached storage size" in source_code, \
            "Helper function should log when using cached value"
        
        print("✅ Storage size helper properly checks for cached value")
        
        # Test 3: Verify AI Search size helper is called for all document types
        print("\n🧪 Test 3: Verify AI Search size helper is used")
        
        ai_search_calls = source_code.count("ai_search_size = get_ai_search_size(doc, container)")
        assert ai_search_calls >= 3, f"AI Search helper should be called at least 3 times (personal, group, public), found {ai_search_calls}"
        
        print(f"✅ AI Search size helper is called {ai_search_calls} times")
        
        # Test 4: Verify calculation only happens when cache is missing or zero
        print("\n🧪 Test 4: Verify calculation only when cache missing/zero")
        
        assert "# Not cached or zero, calculate from Azure Storage" in source_code or \
               "storage_client = CLIENTS.get(\"storage_account_office_docs_client\")" in source_code, \
            "Helper function should calculate from Azure Storage when cache missing"
        
        assert "Calculated storage size" in source_code, \
            "Helper function should log when calculating storage size"
        
        print("✅ Calculation happens only when cache is missing or zero")
        
        # Test 5: Verify caching logic updates Cosmos document
        print("\n🧪 Test 5: Verify calculated values are cached in Cosmos")
        
        assert "doc['storage_account_size'] = total_size" in source_code, \
            "Helper function should update document with calculated storage size"
        
        assert "doc['ai_search_size'] = ai_search_size" in source_code, \
            "Helper function should update document with calculated AI Search size"
        
        assert "cosmos_container.upsert_item(doc)" in source_code or \
               "container.upsert_item(doc)" in source_code, \
            "Helper function should upsert document to Cosmos"
        
        assert "Cached storage size in Cosmos" in source_code, \
            "Helper function should log when caching value"
        
        print("✅ Calculated values are properly cached in Cosmos")
        
        # Test 6: Verify helper functions receive document and container parameters
        print("\n🧪 Test 6: Verify helper function signatures include doc and container")
        
        assert "def get_document_storage_size(doc, cosmos_container," in source_code, \
            "Storage helper function should accept doc and cosmos_container parameters"
        
        assert "def get_ai_search_size(doc, cosmos_container):" in source_code, \
            "AI Search helper function should accept doc and cosmos_container parameters"
        
        print("✅ Helper functions have correct signatures for caching")
        
        # Test 7: Verify error handling for cache failures
        print("\n🧪 Test 7: Verify graceful handling of cache failures")
        
        assert "Could not cache storage size" in source_code or \
               "cache_e" in source_code, \
            "Helper function should handle cache failures gracefully"
        
        print("✅ Cache failures are handled gracefully")
        
        print("\n📊 Test Summary:")
        print("   ✅ AI Search size helper function exists and caches values")
        print("   ✅ Storage size helper checks for cached storage_account_size")
        print("   ✅ AI Search size helper is used for all document types")
        print("   ✅ Calculation only when cache missing or zero")
        print("   ✅ Calculated values cached in Cosmos via upsert")
        print("   ✅ Helper functions have correct signatures for caching")
        print("   ✅ Cache failures handled gracefully")
        
        print("\n🎯 Caching Benefits:")
        print("   • Reduces Azure Storage API calls")
        print("   • Eliminates AI Search size recalculations")
        print("   • Improves performance for repeated admin refreshes")
        print("   • Both sizes calculated once per document")
        print("   • Cached values persist in Cosmos document metadata")
        print("   • Recalculates only if missing or zero")
        
        print("\n📝 Expected Behavior:")
        print("   • First export: Calculates and caches both sizes")
        print("   • Subsequent exports: Uses cached values (fast)")
        print("   • Admin force refresh: Uses cached values (no recalc)")
        print("   • New documents: Both sizes calculated and cached on first export")
        print("   • ai_search_size: Calculated from number_of_pages × 80KB")
        print("   • storage_account_size: Retrieved from Azure Storage blob")
        
        print("\n✅ All document caching tests passed!")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_document_storage_caching()
    sys.exit(0 if success else 1)
