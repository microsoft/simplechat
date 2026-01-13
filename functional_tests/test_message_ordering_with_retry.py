#!/usr/bin/env python3
"""
Functional test for message ordering with thread retry.
Version: 0.233.259
Implemented in: 0.233.259

This test ensures that when a message thread is retried, the retried message
maintains its original position in the conversation based on the thread chain
(thread_id and previous_thread_id), not the timestamp. This prevents retried
messages from appearing out of order due to their newer timestamps.

Test scenario:
1. Create thread 1 (previous_thread_id: None)
2. Create thread 2 (previous_thread_id: thread_1)
3. Retry thread 1 with a newer timestamp
4. Verify thread 1 still appears before thread 2 despite newer timestamp
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

from functions_chat import sort_messages_by_thread
from datetime import datetime, timedelta


def test_message_ordering_with_retry():
    """
    Test that retried messages maintain correct order based on thread chain,
    not timestamp.
    """
    print("🧪 Testing message ordering with thread retry...")
    
    try:
        # Create base timestamp
        base_time = datetime(2024, 1, 1, 12, 0, 0)
        
        # Simulate the scenario:
        # 1. User sends message (thread 1, no previous)
        # 2. Assistant responds to thread 1
        # 3. User sends another message (thread 2, previous = thread 1)
        # 4. Assistant responds to thread 2
        # 5. User retries thread 1 (same thread_id, same previous_thread_id, but newer timestamp)
        # 6. Assistant responds to retried thread 1
        
        messages = [
            # Original thread 1 - user message
            {
                'id': 'msg1',
                'role': 'user',
                'content': 'First message',
                'timestamp': (base_time + timedelta(seconds=0)).isoformat(),
                'thread_id': 'thread_1',
                'previous_thread_id': None
            },
            # Original thread 1 - assistant response
            {
                'id': 'msg2',
                'role': 'assistant',
                'content': 'Response to first',
                'timestamp': (base_time + timedelta(seconds=1)).isoformat(),
                'thread_id': 'thread_1',
                'previous_thread_id': None
            },
            # Thread 2 - user message (comes after thread 1)
            {
                'id': 'msg3',
                'role': 'user',
                'content': 'Second message',
                'timestamp': (base_time + timedelta(seconds=2)).isoformat(),
                'thread_id': 'thread_2',
                'previous_thread_id': 'thread_1'
            },
            # Thread 2 - assistant response
            {
                'id': 'msg4',
                'role': 'assistant',
                'content': 'Response to second',
                'timestamp': (base_time + timedelta(seconds=3)).isoformat(),
                'thread_id': 'thread_2',
                'previous_thread_id': 'thread_1'
            },
            # RETRY of thread 1 - user message (newer timestamp but same thread_id/previous_thread_id)
            {
                'id': 'msg5',
                'role': 'user',
                'content': 'First message (retry)',
                'timestamp': (base_time + timedelta(seconds=10)).isoformat(),  # Much newer timestamp
                'thread_id': 'thread_1',  # Same thread_id
                'previous_thread_id': None  # Same previous_thread_id
            },
            # RETRY of thread 1 - assistant response
            {
                'id': 'msg6',
                'role': 'assistant',
                'content': 'New response to first',
                'timestamp': (base_time + timedelta(seconds=11)).isoformat(),
                'thread_id': 'thread_1',
                'previous_thread_id': None
            }
        ]
        
        print(f"\n📋 Input messages (as stored, unsorted):")
        for msg in messages:
            print(f"  {msg['id']}: thread_id={msg['thread_id']}, "
                  f"prev={msg['previous_thread_id']}, "
                  f"timestamp={msg['timestamp']}")
        
        # Sort messages
        sorted_messages = sort_messages_by_thread(messages)
        
        print(f"\n✅ Sorted messages:")
        for i, msg in enumerate(sorted_messages):
            print(f"  {i+1}. {msg['id']}: thread_id={msg['thread_id']}, "
                  f"prev={msg['previous_thread_id']}, "
                  f"content='{msg['content']}'")
        
        # Verify order
        # Expected order:
        # 1. msg1 or msg5 (thread 1, first occurrence based on earliest timestamp)
        # 2. msg2 or msg6 (thread 1, response)
        # 3. msg3 (thread 2, user)
        # 4. msg4 (thread 2, assistant)
        # Then the retry messages that weren't shown yet
        
        # The key assertion: All thread_1 messages should come before all thread_2 messages
        # because thread_2 has previous_thread_id = thread_1
        
        thread_1_indices = [i for i, msg in enumerate(sorted_messages) if msg['thread_id'] == 'thread_1']
        thread_2_indices = [i for i, msg in enumerate(sorted_messages) if msg['thread_id'] == 'thread_2']
        
        print(f"\n🔍 Thread 1 positions: {thread_1_indices}")
        print(f"🔍 Thread 2 positions: {thread_2_indices}")
        
        # All thread_1 messages should come before all thread_2 messages
        max_thread_1_index = max(thread_1_indices)
        min_thread_2_index = min(thread_2_indices)
        
        if max_thread_1_index < min_thread_2_index:
            print(f"\n✅ PASS: Thread 1 (max index {max_thread_1_index}) comes before Thread 2 (min index {min_thread_2_index})")
            print("✅ Message ordering correctly preserves thread chain despite retry timestamps!")
            return True
        else:
            print(f"\n❌ FAIL: Thread ordering is incorrect!")
            print(f"   Thread 1 max index: {max_thread_1_index}")
            print(f"   Thread 2 min index: {min_thread_2_index}")
            print("   Thread 1 should come entirely before Thread 2")
            return False
            
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_legacy_messages_ordering():
    """
    Test that legacy messages (without thread_id) are sorted by timestamp
    and come before threaded messages.
    """
    print("\n🧪 Testing legacy message ordering...")
    
    try:
        base_time = datetime(2024, 1, 1, 12, 0, 0)
        
        messages = [
            # Threaded message
            {
                'id': 'msg3',
                'role': 'user',
                'content': 'Threaded message',
                'timestamp': (base_time + timedelta(seconds=1)).isoformat(),
                'thread_id': 'thread_1',
                'previous_thread_id': None
            },
            # Legacy message (earlier timestamp, no thread_id)
            {
                'id': 'msg1',
                'role': 'user',
                'content': 'Legacy message 1',
                'timestamp': (base_time + timedelta(seconds=0)).isoformat()
            },
            # Legacy message (later timestamp, no thread_id)
            {
                'id': 'msg2',
                'role': 'assistant',
                'content': 'Legacy message 2',
                'timestamp': (base_time + timedelta(seconds=0.5)).isoformat()
            }
        ]
        
        sorted_messages = sort_messages_by_thread(messages)
        
        print(f"✅ Sorted messages:")
        for i, msg in enumerate(sorted_messages):
            has_thread = 'thread_id' in msg
            print(f"  {i+1}. {msg['id']}: {'threaded' if has_thread else 'legacy'}")
        
        # Verify legacy messages come first
        if (sorted_messages[0]['id'] == 'msg1' and 
            sorted_messages[1]['id'] == 'msg2' and 
            sorted_messages[2]['id'] == 'msg3'):
            print("✅ PASS: Legacy messages come before threaded messages and are sorted by timestamp")
            return True
        else:
            print("❌ FAIL: Message ordering is incorrect")
            return False
            
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_multiple_retry_attempts():
    """
    Test that multiple retry attempts of the same thread maintain correct order.
    """
    print("\n🧪 Testing multiple retry attempts ordering...")
    
    try:
        base_time = datetime(2024, 1, 1, 12, 0, 0)
        
        messages = [
            # Thread 1 - attempt 1
            {
                'id': 'msg1',
                'role': 'user',
                'content': 'First message - attempt 1',
                'timestamp': (base_time + timedelta(seconds=0)).isoformat(),
                'thread_id': 'thread_1',
                'previous_thread_id': None
            },
            # Thread 2 - follows thread 1
            {
                'id': 'msg2',
                'role': 'user',
                'content': 'Second message',
                'timestamp': (base_time + timedelta(seconds=1)).isoformat(),
                'thread_id': 'thread_2',
                'previous_thread_id': 'thread_1'
            },
            # Thread 1 - attempt 2 (retry)
            {
                'id': 'msg3',
                'role': 'user',
                'content': 'First message - attempt 2',
                'timestamp': (base_time + timedelta(seconds=5)).isoformat(),
                'thread_id': 'thread_1',
                'previous_thread_id': None
            },
            # Thread 1 - attempt 3 (another retry)
            {
                'id': 'msg4',
                'role': 'user',
                'content': 'First message - attempt 3',
                'timestamp': (base_time + timedelta(seconds=10)).isoformat(),
                'thread_id': 'thread_1',
                'previous_thread_id': None
            }
        ]
        
        sorted_messages = sort_messages_by_thread(messages)
        
        print(f"✅ Sorted messages:")
        for i, msg in enumerate(sorted_messages):
            print(f"  {i+1}. {msg['id']}: thread_id={msg['thread_id']}, content='{msg['content']}'")
        
        # All thread_1 messages should come before thread_2
        thread_1_count = sum(1 for msg in sorted_messages if msg['thread_id'] == 'thread_1')
        thread_2_index = next(i for i, msg in enumerate(sorted_messages) if msg['thread_id'] == 'thread_2')
        
        if thread_2_index == thread_1_count:
            print(f"✅ PASS: All {thread_1_count} thread_1 messages come before thread_2")
            return True
        else:
            print(f"❌ FAIL: Thread_2 at index {thread_2_index}, but expected after {thread_1_count} thread_1 messages")
            return False
            
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 70)
    print("MESSAGE ORDERING WITH RETRY - FUNCTIONAL TEST")
    print("=" * 70)
    
    results = []
    
    # Run all tests
    results.append(("Message ordering with retry", test_message_ordering_with_retry()))
    results.append(("Legacy messages ordering", test_legacy_messages_ordering()))
    results.append(("Multiple retry attempts", test_multiple_retry_attempts()))
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\n📊 Results: {passed}/{total} tests passed")
    
    success = all(result for _, result in results)
    sys.exit(0 if success else 1)
