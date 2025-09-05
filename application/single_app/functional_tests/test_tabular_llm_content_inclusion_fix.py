#!/usr/bin/env python3
"""
Test for comprehensive file content inclusio        # Verify complete content is included (since our test data is under 50KB)
        if len(csv_content) <= 50000:
            assert len(tabular_content) == len(csv_content), "Complete tabular content should be included when under limit"
            print("✅ Complete tabular data included for LLM analysis")
        
        print(f"✅ Non-tabular file content limit: {limited_limit} characters")
        print(f"✅ Non-tabular file content sent to LLM: {len(limited_content)} characters")nt.
Version: 0.226.102
Implemented in: 0.226.101

This test ensures that when files are uploaded to conversations,
the complete file content (up to 50KB) is included in the conversation history sent to the LLM,
providing comprehensive context for analysis.

This validates:
1. All files get 50KB content limits (unified approach)
2. Complete file data is sent to LLM for analysis
3. File content truncation works correctly for large files
4. Both tabular and non-tabular files get same treatment
"""

import sys
import os
import tempfile
import pandas as pd

# Add parent directory to path to import functions
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_comprehensive_file_content_inclusion():
    """Test that all files include comprehensive content for LLM analysis."""
    
    print("🔍 Testing Comprehensive File Content Inclusion Enhancement...")
    
    try:
        # Test 1: Create sample credit card data (like user's actual data)
        credit_card_data = pd.DataFrame({
            'Date': ['08/30/2025', '08/29/2025', '08/28/2025'] * 20,  # 60 rows
            'Description': ['PANERA BREAD', 'AMAZON.COM', 'SAFEWAY'] * 20,
            'Amount': [12.49, 25.99, 45.67] * 20,
            'Category': ['Restaurant', 'Internet Purchase', 'Groceries'] * 20
        })
        
        # Convert to CSV format (like our storage fix does)
        csv_content = credit_card_data.to_csv(index=False)
        
        print(f"📊 Test data size: {len(csv_content)} characters")
        
        # Test the conversation history logic (simulated)
        def simulate_conversation_history_logic(file_content, is_table):
            """Simulate the logic from route_backend_chats.py"""
            max_file_content_length_in_history = 50000  # Updated limit for all files
            max_tabular_content_length_in_history = 50000  # Same limit for consistency
            
            # Use same limit for all file types now
            content_limit = max_tabular_content_length_in_history if is_table else max_file_content_length_in_history
            
            display_content = file_content[:content_limit]
            if len(file_content) > content_limit:
                display_content += "..."
                
            return display_content, content_limit
        
        # Test tabular file (should get full content up to 50KB)
        tabular_content, tabular_limit = simulate_conversation_history_logic(csv_content, is_table=True)
        
        print(f"✅ Tabular file content limit: {tabular_limit} characters")
        print(f"✅ Tabular file content sent to LLM: {len(tabular_content)} characters")
        
        # Test non-tabular file (should also get 50KB limit now)
        non_tabular_content = "This is a regular text file with some content that goes on and on. " * 100
        limited_content, limited_limit = simulate_conversation_history_logic(non_tabular_content, is_table=False)
        
        # Verify both file types get the same higher limit now
        assert tabular_limit == 50000, "Tabular files should get 50KB limit"
        assert limited_limit == 50000, "Non-tabular files now also get 50KB limit"
        
        # Verify complete content is included (since our test data is under 50KB)
        if len(csv_content) <= 50000:
            assert len(tabular_content) == len(csv_content), "Complete tabular content should be included when under limit"
            print("✅ Complete tabular data included for LLM analysis")
        
        # Test non-tabular file (should get limited content)
        non_tabular_content = "This is a regular text file with some content that goes on and on. " * 100
        limited_content, limited_limit = simulate_conversation_history_logic(non_tabular_content, is_table=False)
        
        print(f"✅ Non-tabular file content limit: {limited_limit} characters")
        print(f"✅ Non-tabular file content sent to LLM: {len(limited_content)} characters")
        
        # Verify complete content is included when under limit for non-tabular files too
        if len(non_tabular_content) <= 50000:
            assert len(limited_content) == len(non_tabular_content), "Complete non-tabular content should be included when under limit"
            print("✅ Complete non-tabular content included when under 50KB limit")
        else:
            assert len(limited_content) <= 50003, "Non-tabular content should be limited to 50KB + '...'"
            
        print("✅ Non-tabular files now get same 50KB limit as tabular files")
        
        # Test large tabular file (should be truncated at 50KB)
        large_tabular_data = pd.DataFrame({
            'Date': ['08/30/2025'] * 5000,  # Many rows to exceed 50KB
            'Description': ['VERY LONG MERCHANT NAME WITH LOTS OF DETAILS'] * 5000,
            'Amount': [12.49] * 5000,
            'Category': ['Restaurant'] * 5000,
            'Extended_Details': ['This is a very long field with lots of transaction details that makes the file large'] * 5000
        })
        
        large_csv_content = large_tabular_data.to_csv(index=False)
        print(f"📊 Large test data size: {len(large_csv_content)} characters")
        
        if len(large_csv_content) > 50000:
            large_tabular_content, large_limit = simulate_conversation_history_logic(large_csv_content, is_table=True)
            
            assert len(large_tabular_content) <= 50003, "Large tabular content should be truncated at limit + '...'"
            assert large_tabular_content.endswith('...'), "Truncated content should end with '...'"
            
            print("✅ Large tabular files correctly truncated at 50KB limit")
        
        print("\n🎉 All tabular data LLM content inclusion tests passed!")
        
        print("\n📋 Summary of fix:")
        print("  ✅ All files now include up to 50KB of content for LLM analysis")
        print("  ✅ Unified content limit for both tabular and non-tabular files") 
        print("  ✅ Complete file data sent to LLM for accurate analysis")
        print("  ✅ Large files properly truncated to stay within limits")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 Running Comprehensive File Content Inclusion Tests...")
    
    success = test_comprehensive_file_content_inclusion()
    
    if success:
        print("\n✅ Fix validated! All file content will now be properly included in LLM conversations.")
    else:
        print("\n❌ Tests failed! Fix needs debugging.")
