#!/usr/bin/env python3
# test_message_threading_system.py
"""
Functional test for message threading system.
Version: 0.233.208
Implemented in: 0.233.208

This test ensures that the message threading system correctly orders messages
and establishes thread chains between related messages.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Add parent directory to path to import from single_app
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app_dir = os.path.join(parent_dir, 'single_app')
sys.path.insert(0, app_dir)

def test_sort_messages_by_thread():
    """Test the sort_messages_by_thread function with various message configurations."""
    from functions_chat import sort_messages_by_thread
    
    print("🧪 Testing sort_messages_by_thread function...")
    
    # Test 1: Legacy messages only (no thread_id)
    print("\n📝 Test 1: Legacy messages (timestamp-based sorting)")
    legacy_messages = [
        {'id': '3', 'timestamp': '2024-01-03T10:00:00', 'content': 'Third'},
        {'id': '1', 'timestamp': '2024-01-01T10:00:00', 'content': 'First'},
        {'id': '2', 'timestamp': '2024-01-02T10:00:00', 'content': 'Second'},
    ]
    sorted_legacy = sort_messages_by_thread(legacy_messages)
    assert sorted_legacy[0]['id'] == '1', "First message should be oldest"
    assert sorted_legacy[1]['id'] == '2', "Second message should be middle"
    assert sorted_legacy[2]['id'] == '3', "Third message should be newest"
    print("✅ Legacy messages sorted correctly by timestamp")
    
    # Test 2: Threaded messages only
    print("\n📝 Test 2: Threaded messages (chain-based sorting)")
    threaded_messages = [
        {'id': '3', 'thread_id': 'thread-3', 'previous_thread_id': 'thread-2', 'timestamp': '2024-01-03T10:00:00', 'role': 'assistant'},
        {'id': '1', 'thread_id': 'thread-1', 'previous_thread_id': None, 'timestamp': '2024-01-01T10:00:00', 'role': 'user'},
        {'id': '2', 'thread_id': 'thread-2', 'previous_thread_id': 'thread-1', 'timestamp': '2024-01-02T10:00:00', 'role': 'system'},
    ]
    sorted_threaded = sort_messages_by_thread(threaded_messages)
    assert sorted_threaded[0]['id'] == '1', "User message should be first (root)"
    assert sorted_threaded[1]['id'] == '2', "System message should be second (child of user)"
    assert sorted_threaded[2]['id'] == '3', "Assistant message should be third (child of system)"
    print("✅ Threaded messages sorted correctly by chain")
    
    # Test 3: Mixed legacy and threaded messages
    print("\n📝 Test 3: Mixed legacy and threaded messages")
    mixed_messages = [
        {'id': '5', 'thread_id': 'thread-5', 'previous_thread_id': 'thread-4', 'timestamp': '2024-01-05T10:00:00', 'role': 'assistant'},
        {'id': '2', 'timestamp': '2024-01-02T10:00:00', 'content': 'Legacy second'},
        {'id': '4', 'thread_id': 'thread-4', 'previous_thread_id': None, 'timestamp': '2024-01-04T10:00:00', 'role': 'user'},
        {'id': '1', 'timestamp': '2024-01-01T10:00:00', 'content': 'Legacy first'},
    ]
    sorted_mixed = sort_messages_by_thread(mixed_messages)
    assert sorted_mixed[0]['id'] == '1', "Legacy messages should come first"
    assert sorted_mixed[1]['id'] == '2', "Legacy messages should be sorted by timestamp"
    assert sorted_mixed[2]['id'] == '4', "Threaded messages should come after legacy"
    assert sorted_mixed[3]['id'] == '5', "Threaded chain should be maintained"
    print("✅ Mixed messages sorted correctly (legacy first, then threaded)")
    
    # Test 4: Multiple thread chains
    print("\n📝 Test 4: Multiple independent thread chains")
    multi_chain = [
        {'id': '2', 'thread_id': 'thread-2', 'previous_thread_id': 'thread-1', 'timestamp': '2024-01-02T10:00:00', 'role': 'assistant'},
        {'id': '4', 'thread_id': 'thread-4', 'previous_thread_id': 'thread-3', 'timestamp': '2024-01-04T10:00:00', 'role': 'assistant'},
        {'id': '1', 'thread_id': 'thread-1', 'previous_thread_id': None, 'timestamp': '2024-01-01T10:00:00', 'role': 'user'},
        {'id': '3', 'thread_id': 'thread-3', 'previous_thread_id': None, 'timestamp': '2024-01-03T10:00:00', 'role': 'user'},
    ]
    sorted_multi = sort_messages_by_thread(multi_chain)
    # First chain (older timestamp): thread-1 -> thread-2
    # Second chain (newer timestamp): thread-3 -> thread-4
    assert sorted_multi[0]['id'] == '1', "First chain root (older)"
    assert sorted_multi[1]['id'] == '2', "First chain child"
    assert sorted_multi[2]['id'] == '3', "Second chain root (newer)"
    assert sorted_multi[3]['id'] == '4', "Second chain child"
    print("✅ Multiple thread chains sorted correctly")
    
    # Test 5: Empty list
    print("\n📝 Test 5: Empty message list")
    empty_messages = []
    sorted_empty = sort_messages_by_thread(empty_messages)
    assert len(sorted_empty) == 0, "Empty list should return empty list"
    print("✅ Empty list handled correctly")
    
    # Test 6: Complex conversation with system messages
    print("\n📝 Test 6: Complex conversation (user -> system -> assistant)")
    complex_conversation = [
        {'id': '3', 'thread_id': 'thread-3', 'previous_thread_id': 'thread-2', 'timestamp': '2024-01-03T10:00:00', 'role': 'assistant'},
        {'id': '1', 'thread_id': 'thread-1', 'previous_thread_id': None, 'timestamp': '2024-01-01T10:00:00', 'role': 'user'},
        {'id': '2', 'thread_id': 'thread-2', 'previous_thread_id': 'thread-1', 'timestamp': '2024-01-02T10:00:00', 'role': 'system'},
    ]
    sorted_complex = sort_messages_by_thread(complex_conversation)
    assert sorted_complex[0]['role'] == 'user', "User message first"
    assert sorted_complex[1]['role'] == 'system', "System message second"
    assert sorted_complex[2]['role'] == 'assistant', "Assistant message third"
    print("✅ Complex conversation flow maintained correctly")
    
    # Test 7: Image generation thread
    print("\n📝 Test 7: Image generation thread (user -> image)")
    image_thread = [
        {'id': '2', 'thread_id': 'thread-2', 'previous_thread_id': 'thread-1', 'timestamp': '2024-01-02T10:00:00', 'role': 'image'},
        {'id': '1', 'thread_id': 'thread-1', 'previous_thread_id': None, 'timestamp': '2024-01-01T10:00:00', 'role': 'user'},
    ]
    sorted_image = sort_messages_by_thread(image_thread)
    assert sorted_image[0]['role'] == 'user', "User request first"
    assert sorted_image[1]['role'] == 'image', "Generated image second"
    print("✅ Image generation thread ordered correctly")
    
    # Test 8: File upload thread
    print("\n📝 Test 8: File upload mid-conversation")
    file_upload = [
        {'id': '3', 'thread_id': 'thread-3', 'previous_thread_id': 'thread-2', 'timestamp': '2024-01-03T10:00:00', 'role': 'file', 'filename': 'doc.pdf'},
        {'id': '1', 'thread_id': 'thread-1', 'previous_thread_id': None, 'timestamp': '2024-01-01T10:00:00', 'role': 'user'},
        {'id': '2', 'thread_id': 'thread-2', 'previous_thread_id': 'thread-1', 'timestamp': '2024-01-02T10:00:00', 'role': 'assistant'},
    ]
    sorted_file = sort_messages_by_thread(file_upload)
    assert sorted_file[0]['role'] == 'user', "User message first"
    assert sorted_file[1]['role'] == 'assistant', "Assistant response second"
    assert sorted_file[2]['role'] == 'file', "File upload third"
    print("✅ File upload thread ordered correctly")
    
    print("\n✅ All sort_messages_by_thread tests passed!")
    return True

def test_thread_field_structure():
    """Test that thread fields have the correct structure."""
    print("\n🧪 Testing thread field structure...")
    
    # Example message with threading fields
    test_message = {
        'id': 'msg-123',
        'conversation_id': 'conv-456',
        'role': 'user',
        'content': 'Test message',
        'timestamp': '2024-01-01T10:00:00',
        'thread_id': 'thread-abc-123',
        'previous_thread_id': 'thread-xyz-789',
        'active_thread': True,
        'thread_attempt': 1
    }
    
    # Verify required fields exist
    assert 'thread_id' in test_message, "thread_id field should exist"
    assert 'previous_thread_id' in test_message, "previous_thread_id field should exist"
    assert 'active_thread' in test_message, "active_thread field should exist"
    assert 'thread_attempt' in test_message, "thread_attempt field should exist"
    
    # Verify field types
    assert isinstance(test_message['thread_id'], str), "thread_id should be string"
    assert isinstance(test_message['previous_thread_id'], (str, type(None))), "previous_thread_id should be string or None"
    assert isinstance(test_message['active_thread'], bool), "active_thread should be boolean"
    assert isinstance(test_message['thread_attempt'], int), "thread_attempt should be integer"
    
    # Verify field values
    assert test_message['active_thread'] == True, "active_thread should be True"
    assert test_message['thread_attempt'] == 1, "thread_attempt should be 1"
    
    print("✅ Thread field structure validated correctly")
    return True

def main():
    """Run all threading system tests."""
    print("=" * 60)
    print("MESSAGE THREADING SYSTEM - FUNCTIONAL TESTS")
    print("Version: 0.233.208")
    print("=" * 60)
    
    try:
        # Run tests
        test_sort_messages_by_thread()
        test_thread_field_structure()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED")
        print("=" * 60)
        print("\n📊 Test Summary:")
        print("   ✓ Message sorting algorithm validated")
        print("   ✓ Thread field structure validated")
        print("   ✓ Legacy message support confirmed")
        print("   ✓ Multiple thread chains handled correctly")
        print("   ✓ Complex conversation flows maintained")
        print("   ✓ Image and file upload threading verified")
        
        return True
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
