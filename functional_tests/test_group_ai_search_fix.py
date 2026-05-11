#!/usr/bin/env python3
"""
Test to verify group AI Search calculation fix.
Version: 0.230.051

Verifies that groups now use the same AI search calculation as users.
"""

import sys
import os

def test_ai_search_calculation_consistency():
    """Test that user and group AI search calculations are now identical."""
    print("🧪 Testing AI Search Calculation Consistency...")
    
    try:
        backend_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'route_backend_control_center.py'
        )
        
        if os.path.exists(backend_path):
            with open(backend_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check user AI search pattern
            print("   🔍 Checking user AI search pattern...")
            user_ai_search_elements = [
                "SELECT VALUE SUM(c.number_of_pages)",
                "WHERE c.user_id = @user_id AND c.type = 'document_metadata'"
            ]
            
            user_pattern_found = all(element in content for element in user_ai_search_elements)
            if user_pattern_found:
                print("   ✅ User AI search pattern found")
            else:
                print("   ❌ User AI search pattern not found")
                return False
            
            # Check group AI search pattern
            print("   🔍 Checking group AI search pattern...")
            group_ai_search_elements = [
                "SELECT VALUE SUM(c.number_of_pages)",
                "WHERE c.group_id = @group_id AND c.type = 'document_metadata'"
            ]
            
            group_pattern_found = all(element in content for element in group_ai_search_elements)
            if group_pattern_found:
                print("   ✅ Group AI search pattern matches user pattern")
            else:
                print("   ❌ Group AI search pattern doesn't match")
                missing = [e for e in group_ai_search_elements if e not in content]
                print(f"   Missing: {missing}")
                return False
            
            # Check that both use same calculation formula
            print("   🔍 Checking calculation formula consistency...")
            calculation_pattern = "total_pages * 80 * 1024  # 80KB per page"
            
            calculation_count = content.count(calculation_pattern)
            if calculation_count >= 2:  # Should appear for both users and groups
                print(f"   ✅ Calculation formula found {calculation_count} times (users + groups)")
            else:
                print(f"   ❌ Calculation formula found only {calculation_count} times, expected ≥2")
                return False
            
            # Check that old problematic patterns are removed
            print("   🔍 Checking for old problematic group patterns...")
            old_patterns = [
                "SELECT c.num_chunks FROM c",
                "for doc in cosmos_group_documents_container.query_items",
                "chunks = doc.get('num_chunks', 0)"
            ]
            
            old_patterns_found = any(pattern in content for pattern in old_patterns)
            if not old_patterns_found:
                print("   ✅ Old problematic patterns removed")
            else:
                found_patterns = [p for p in old_patterns if p in content]
                print(f"   ❌ Old patterns still present: {found_patterns}")
                return False
                
            return True
            
        else:
            print(f"   ❌ Backend file not found: {backend_path}")
            return False
            
    except Exception as e:
        print(f"   ❌ Error testing AI search consistency: {e}")
        return False

def test_expected_calculation():
    """Show expected calculation for the sample group."""
    print("\n📊 Expected Calculation for Sample Group...")
    
    print("   📄 Sample group document (dcb39117-1a04-44e6-ba45-bb819327056b):")
    print("     - number_of_pages: 124")
    print("     - type: 'document_metadata'")
    print("     - num_chunks: 0 (this was the wrong field!)")
    
    print("   🎯 Expected query:")
    print("     - Query: SELECT VALUE SUM(c.number_of_pages) FROM c WHERE c.group_id = @group_id AND c.type = 'document_metadata'")
    print("     - Result: 124")
    
    print("   📈 Expected calculation:")
    print("     - AI Search Size = 124 pages × 80KB = 124 × 80 × 1024 = 10,158,080 bytes")
    print("     - Display: ~9.7 MB (instead of 0 B)")

if __name__ == "__main__":
    print("🔧 Group AI Search Calculation Fix Verification")
    print("=" * 55)
    
    success = test_ai_search_calculation_consistency()
    test_expected_calculation()
    
    print("\n" + "=" * 55)
    if success:
        print("✅ PASS - Group AI search now matches user calculation")
        print("🔄 Next: Test with 'Refresh Data' to update group metrics")
        print("📄 Expected: Aaron group should show ~9.7 MB AI Search (not 0 B)")
    else:
        print("❌ FAIL - AI search calculations don't match")
    
    sys.exit(0 if success else 1)