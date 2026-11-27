#!/usr/bin/env python3
# test_group_document_date_fix.py
"""
Quick test to verify the group document date query fix.
Version: 0.230.050

This verifies that the group document query now matches the user document query pattern.
Implemented in: 0.230.053
"""

import sys
import os

def test_group_query_matches_user_query():
    """Test that group and user document queries are now consistent."""
    print("🧪 Testing Group vs User Document Query Consistency...")
    
    try:
        backend_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'route_backend_control_center.py'
        )
        
        if os.path.exists(backend_path):
            with open(backend_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check that both user and group queries follow same pattern
            print("   🔍 Checking user query pattern...")
            user_query_elements = [
                "SELECT TOP 1 c.last_updated",
                "WHERE c.user_id = @user_id AND c.type = 'document_metadata'",
                "ORDER BY c.last_updated DESC"
            ]
            
            user_query_found = all(element in content for element in user_query_elements)
            if user_query_found:
                print("   ✅ User query pattern found correctly")
            else:
                print("   ❌ User query pattern not found")
                return False
            
            print("   🔍 Checking group query pattern...")
            group_query_elements = [
                "SELECT TOP 1 c.last_updated",
                "WHERE c.group_id = @group_id AND c.type = 'document_metadata'", 
                "ORDER BY c.last_updated DESC"
            ]
            
            group_query_found = all(element in content for element in group_query_elements)
            if group_query_found:
                print("   ✅ Group query pattern matches user pattern")
            else:
                print("   ❌ Group query pattern doesn't match user pattern")
                missing = [e for e in group_query_elements if e not in content]
                print(f"   Missing: {missing}")
                return False
            
            # Check that both use same date parsing
            print("   🔍 Checking date parsing consistency...")
            date_parsing = [
                "datetime.fromisoformat(last_updated.replace('Z', '+00:00'))",
                "last_day_upload = date_obj.strftime('%m/%d/%Y')"
            ]
            
            # Should find this pattern twice (once for users, once for groups)
            parsing_count = sum(content.count(element) for element in date_parsing)
            if parsing_count >= 4:  # 2 elements × 2 occurrences = 4 minimum
                print("   ✅ Date parsing is consistent between users and groups")
            else:
                print(f"   ❌ Date parsing inconsistent. Found {parsing_count} occurrences, expected ≥4")
                return False
            
            # Check that old problematic query patterns are removed
            print("   🔍 Checking for old problematic patterns...")
            old_patterns = [
                "c.upload_date, c.created_at, c.modified_at",
                "ORDER BY c.upload_date DESC, c.created_at DESC"
            ]
            
            old_patterns_found = any(pattern in content for pattern in old_patterns)
            if not old_patterns_found:
                print("   ✅ Old problematic query patterns removed")
            else:
                print("   ❌ Old problematic query patterns still present")
                return False
                
            return True
            
        else:
            print(f"   ❌ Backend file not found: {backend_path}")
            return False
            
    except Exception as e:
        print(f"   ❌ Error testing query consistency: {e}")
        return False

def test_expected_results():
    """Show what results we expect from the sample data."""
    print("\n📊 Expected Results from Sample Data...")
    
    print("   📄 Sample group document:")
    print("     - group_id: dcb39117-1a04-44e6-ba45-bb819327056b")
    print("     - last_updated: 2025-09-04T13:35:34Z")
    print("     - type: document_metadata")
    
    print("   🎯 Expected query result:")
    print("     - Query: SELECT TOP 1 c.last_updated FROM c WHERE c.group_id = @group_id AND c.type = 'document_metadata' ORDER BY c.last_updated DESC")
    print("     - Result: 2025-09-04T13:35:34Z")
    print("     - Parsed: 09/04/2025")
    
    print("   📈 Expected group metrics:")
    print("     - last_day_upload: '09/04/2025' (not 'Never')")
    print("     - Frontend display: 'Last Day: 09/04/2025'")

if __name__ == "__main__":
    print("🔧 Group Document Date Query Fix Verification")
    print("=" * 50)
    
    success = test_group_query_matches_user_query()
    test_expected_results()
    
    print("\n" + "=" * 50)
    if success:
        print("✅ PASS - Group query now matches user query pattern")
        print("🔄 Next step: Test with 'Refresh Data' button to update cached metrics")
    else:
        print("❌ FAIL - Query patterns don't match")
    
    sys.exit(0 if success else 1)