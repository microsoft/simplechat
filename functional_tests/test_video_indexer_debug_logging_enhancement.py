#!/usr/bin/env python3
"""
Functional test for Video Indexer debug logging enhancement.
Version: 0.229.041
Implemented in: 0.229.041

This test ensures that comprehensive debug logging has been added to video indexer
API calls to improve troubleshooting for customer issues.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_video_indexer_debug_logging():
    """Test that comprehensive debug logging is present in video indexer functions."""
    print("🔍 Testing Video Indexer debug logging enhancement...")
    
    try:
        # Test 1: Check functions_authentication.py for debug logging
        auth_file_path = os.path.join(
            '..', 'application', 'single_app', 'functions_authentication.py'
        )
        
        if not os.path.exists(auth_file_path):
            print("❌ functions_authentication.py not found")
            return False
            
        with open(auth_file_path, 'r', encoding='utf-8') as f:
            auth_content = f.read()
            
        # Check for debug_print imports and usage in video indexer auth function
        required_debug_patterns = [
            'from functions_debug import debug_print',
            '[VIDEO INDEXER AUTH] Starting token acquisition',
            '[VIDEO INDEXER AUTH] Azure environment',
            '[VIDEO INDEXER AUTH] Using ARM scope',
            '[VIDEO INDEXER AUTH] DefaultAzureCredential initialized',
            '[VIDEO INDEXER AUTH] ARM token acquired successfully',
            '[VIDEO INDEXER AUTH] Settings extracted',
            '[VIDEO INDEXER AUTH] ARM API URL',
            '[VIDEO INDEXER AUTH] Request body',
            '[VIDEO INDEXER AUTH] ARM API response status',
            '[VIDEO INDEXER AUTH] Account token acquired successfully'
        ]
        
        missing_patterns = []
        for pattern in required_debug_patterns:
            if pattern not in auth_content:
                missing_patterns.append(pattern)
                
        if missing_patterns:
            print(f"❌ Missing debug logging patterns in authentication: {missing_patterns}")
            return False
            
        print("✅ Video indexer authentication debug logging verified")
        
        # Test 2: Check functions_documents.py for debug logging
        docs_file_path = os.path.join(
            '..', 'application', 'single_app', 'functions_documents.py'
        )
        
        if not os.path.exists(docs_file_path):
            print("❌ functions_documents.py not found")
            return False
            
        with open(docs_file_path, 'r', encoding='utf-8') as f:
            docs_content = f.read()
            
        # Check for debug logging in video processing functions
        required_video_debug_patterns = [
            '[VIDEO INDEXER] Starting video processing',
            '[VIDEO INDEXER] Document ID',
            '[VIDEO INDEXER] Video file support is disabled',
            '[VIDEO INDEXER] Video file support is enabled',
            '[VIDEO INDEXER] Configuration - Endpoint',
            '[VIDEO INDEXER] All required settings are present',
            '[VIDEO INDEXER] Attempting to acquire authentication token',
            '[VIDEO INDEXER] Upload URL',
            '[VIDEO INDEXER] Upload response status',
            '[VIDEO INDEXER] Upload successful, video ID',
            '[VIDEO INDEXER] Index polling URL',
            '[VIDEO INDEXER] Starting processing polling',
            '[VIDEO INDEXER] Processing progress',
            '[VIDEO INDEXER] Starting insights extraction',
            '[VIDEO INDEXER] Transcript segments found',
            '[VIDEO INDEXER] OCR blocks found'
        ]
        
        missing_video_patterns = []
        for pattern in required_video_debug_patterns:
            if pattern not in docs_content:
                missing_video_patterns.append(pattern)
                
        if missing_video_patterns:
            print(f"❌ Missing debug logging patterns in video processing: {missing_video_patterns}")
            return False
            
        print("✅ Video indexer processing debug logging verified")
        
        # Test 3: Check for debug logging in video chunk processing
        required_chunk_debug_patterns = [
            '[VIDEO CHUNK] Saving video chunk',
            '[VIDEO CHUNK] Transcript length',
            '[VIDEO CHUNK] Converted start_time',
            '[VIDEO CHUNK] Generating embedding',
            '[VIDEO CHUNK] Embedding generated successfully',
            '[VIDEO CHUNK] Retrieving document metadata',
            '[VIDEO CHUNK] Generated chunk ID',
            '[VIDEO CHUNK] Built chunk document',
            '[VIDEO CHUNK] Uploading chunk to search index',
            '[VIDEO CHUNK] Upload successful'
        ]
        
        missing_chunk_patterns = []
        for pattern in required_chunk_debug_patterns:
            if pattern not in docs_content:
                missing_chunk_patterns.append(pattern)
                
        if missing_chunk_patterns:
            print(f"❌ Missing debug logging patterns in chunk processing: {missing_chunk_patterns}")
            return False
            
        print("✅ Video chunk processing debug logging verified")
        
        # Test 4: Check for debug logging in video deletion
        required_delete_debug_patterns = [
            '[VIDEO INDEXER DELETE] Video file detected',
            '[VIDEO INDEXER DELETE] Configuration - Endpoint',
            '[VIDEO INDEXER DELETE] Acquiring authentication token',
            '[VIDEO INDEXER DELETE] Video ID from document metadata',
            '[VIDEO INDEXER DELETE] Delete URL',
            '[VIDEO INDEXER DELETE] Delete response status',
            '[VIDEO INDEXER DELETE] Successfully deleted video ID'
        ]
        
        missing_delete_patterns = []
        for pattern in required_delete_debug_patterns:
            if pattern not in docs_content:
                missing_delete_patterns.append(pattern)
                
        if missing_delete_patterns:
            print(f"❌ Missing debug logging patterns in deletion: {missing_delete_patterns}")
            return False
            
        print("✅ Video indexer deletion debug logging verified")
        
        # Test 5: Verify debug_print function import patterns
        debug_import_patterns = [
            'from functions_debug import debug_print'
        ]
        
        import_count = 0
        for pattern in debug_import_patterns:
            import_count += auth_content.count(pattern)
            import_count += docs_content.count(pattern)
            
        if import_count < 3:  # Should be in at least 3 functions
            print(f"❌ Insufficient debug_print imports found: {import_count}")
            return False
            
        print("✅ Debug import statements verified")
        
        # Test 6: Check error handling with debug logging
        error_debug_patterns = [
            '[VIDEO INDEXER AUTH] ERROR acquiring ARM token',
            '[VIDEO INDEXER] Authentication failed',
            '[VIDEO INDEXER] Upload request failed',
            '[VIDEO INDEXER] Poll request failed',
            '[VIDEO INDEXER DELETE] Request error'
        ]
        
        found_error_patterns = 0
        for pattern in error_debug_patterns:
            if pattern in auth_content or pattern in docs_content:
                found_error_patterns += 1
                
        if found_error_patterns < 3:
            print(f"❌ Insufficient error debug logging patterns found: {found_error_patterns}")
            return False
            
        print("✅ Error handling debug logging verified")
        
        print("✅ All Video Indexer debug logging enhancements verified successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_debug_configuration():
    """Test that debug configuration functions are accessible."""
    print("🔍 Testing debug configuration accessibility...")
    
    try:
        # Import the debug functions
        from functions_debug import debug_print, is_debug_enabled
        
        # Test basic functionality (should not crash)
        debug_print("Test debug message")
        is_enabled = is_debug_enabled()
        
        print(f"✅ Debug functions imported successfully. Debug enabled: {is_enabled}")
        return True
        
    except ImportError as e:
        print(f"❌ Failed to import debug functions: {e}")
        return False
    except Exception as e:
        print(f"❌ Error testing debug functions: {e}")
        return False

if __name__ == "__main__":
    success = True
    
    # Run the tests
    tests = [
        test_video_indexer_debug_logging,
        test_debug_configuration
    ]
    
    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        result = test()
        results.append(result)
        if not result:
            success = False
    
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("\n🎉 All Video Indexer debug logging enhancement tests passed!")
        print("🔧 Enhanced debugging will help troubleshoot customer video indexer issues")
    else:
        print("\n❌ Some tests failed - debug logging enhancement may be incomplete")
    
    sys.exit(0 if success else 1)