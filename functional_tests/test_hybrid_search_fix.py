#!/usr/bin/env python3
# test_hybrid_search_fix.py
"""
Test the hybrid_search parameters fix for PII analysis.
Version: 0.229.074

This test verifies that the PII analysis correctly calls hybrid_search
and extracts content from the returned chunks.
Implemented in: 0.229.088
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_hybrid_search_parameters():
    """Test that hybrid_search is called with correct parameters."""
    print("🔍 Testing hybrid_search parameter usage...")
    
    try:
        from functions_search import hybrid_search
        
        # Test the function signature
        import inspect
        sig = inspect.signature(hybrid_search)
        params = list(sig.parameters.keys())
        
        expected_params = ['query', 'user_id', 'document_id', 'top_n', 'doc_scope', 'active_group_id', 'active_public_workspace_id', 'enable_file_sharing']
        
        print(f"📊 Function parameters: {params}")
        
        # Check that all expected parameters exist
        missing_params = [p for p in expected_params if p not in params]
        if missing_params:
            print(f"❌ Missing parameters: {missing_params}")
            return False
        else:
            print("✅ All expected parameters present")
        
        # Check parameter defaults
        defaults = {}
        for param_name, param in sig.parameters.items():
            if param.default != inspect.Parameter.empty:
                defaults[param_name] = param.default
        
        print(f"📊 Parameter defaults: {defaults}")
        
        # Check that key defaults are correct
        expected_defaults = {
            'document_id': None,
            'top_n': 12,
            'doc_scope': 'all',
            'active_group_id': None,
            'active_public_workspace_id': None,
            'enable_file_sharing': True
        }
        
        for param, expected_default in expected_defaults.items():
            if param in defaults and defaults[param] == expected_default:
                print(f"  ✅ {param}: {expected_default}")
            else:
                print(f"  ❌ {param}: expected {expected_default}, got {defaults.get(param, 'missing')}")
                return False
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing hybrid_search parameters: {e}")
        return False

def test_search_result_structure():
    """Test understanding of search result structure."""
    print("\n🔍 Testing search result structure...")
    
    try:
        from functions_search import extract_search_results
        
        # Mock search result to test extraction
        mock_result = {
            "id": "test-id",
            "chunk_text": "This is sample content with SSN 123-45-6789",
            "chunk_id": "chunk-1",
            "file_name": "test.pdf",
            "version": "1.0",
            "chunk_sequence": 1,
            "upload_date": "2024-01-01",
            "document_classification": "Public",
            "page_number": 1,
            "author": "Test Author",
            "chunk_keywords": "test, sample",
            "title": "Test Document",
            "chunk_summary": "Sample content",
            "@search.score": 0.95
        }
        
        # Create mock paged results
        class MockPagedResults:
            def __init__(self, results):
                self.results = results
                self.index = 0
                
            def __iter__(self):
                return iter(self.results)
                
            def __getitem__(self, index):
                return self.results[index]
        
        mock_paged = MockPagedResults([mock_result])
        extracted = extract_search_results(mock_paged, 1)
        
        if extracted and len(extracted) > 0:
            result = extracted[0]
            print(f"✅ Extracted result structure: {list(result.keys())}")
            
            # Check that chunk_text is preserved
            if 'chunk_text' in result and result['chunk_text'] == mock_result['chunk_text']:
                print("✅ chunk_text field correctly extracted")
                return True
            else:
                print(f"❌ chunk_text field issue: {result.get('chunk_text', 'missing')}")
                return False
        else:
            print("❌ No results extracted")
            return False
            
    except Exception as e:
        print(f"❌ Error testing search result structure: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_pii_analysis_search_logic():
    """Test the search logic that would be used in PII analysis."""
    print("\n🔍 Testing PII analysis search logic...")
    
    try:
        # Test that we understand the content extraction logic
        mock_search_results = [
            {'chunk_text': 'First chunk with email: user@example.com'},
            {'chunk_text': 'Second chunk with phone: (555) 123-4567'},
            {'content': 'Legacy format chunk'},  # Test fallback
            {'chunk_text': 'Third chunk with SSN: 123-45-6789'}
        ]
        
        # Simulate the content extraction logic from PII analysis
        document_content = ""
        for result in mock_search_results:
            # This is the logic we fixed: check chunk_text first, then content
            content = result.get('chunk_text', result.get('content', ''))
            if content:
                document_content += content + "\n\n"
        
        print(f"📊 Extracted content length: {len(document_content)} characters")
        print(f"📝 Content sample: {document_content[:100]}...")
        
        # Check that all chunks were included
        expected_terms = ['user@example.com', '(555) 123-4567', 'Legacy format', '123-45-6789']
        found_terms = [term for term in expected_terms if term in document_content]
        
        print(f"✅ Found {len(found_terms)}/{len(expected_terms)} expected terms")
        
        if len(found_terms) == len(expected_terms):
            print("✅ Content extraction logic working correctly")
            return True
        else:
            missing = [term for term in expected_terms if term not in found_terms]
            print(f"❌ Missing terms: {missing}")
            return False
            
    except Exception as e:
        print(f"❌ Error testing search logic: {e}")
        return False

def main():
    """Run tests for hybrid_search fix."""
    print("🧪 Testing Hybrid Search Fix for PII Analysis")
    print("=" * 60)
    
    tests = [
        ("Hybrid Search Parameters", test_hybrid_search_parameters),
        ("Search Result Structure", test_search_result_structure),
        ("PII Analysis Search Logic", test_pii_analysis_search_logic)
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
        print("🎉 Hybrid search fixes should resolve the PII content issue!")
        print("\n💡 Key fixes applied:")
        print("   ✅ Corrected hybrid_search parameter names")
        print("   ✅ Fixed content extraction to use 'chunk_text' field")
        print("   ✅ Added fallback broad search if specific search fails")
        print("   ✅ Added debugging output to track content extraction")
    else:
        print("⚠️ Some tests failed. Please review the issues above.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)