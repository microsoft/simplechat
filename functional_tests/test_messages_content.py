#!/usr/bin/env python3
"""
Test to see exactly what the messages API returns.
"""

import requests
import json

def test_messages_content():
    """Test what the messages endpoint actually returns"""
    print("🔍 Testing messages API content...")
    
    conversation_id = "fea9b98e-9185-4c2a-a428-2fe04bec643d"
    url = f"http://127.0.0.1:5000/api/messages"
    params = {'conversation_id': conversation_id}
    
    try:
        response = requests.get(url, params=params, timeout=30)
        print(f"Response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            messages = data.get('messages', [])
            print(f"Got {len(messages)} messages")
            
            for i, message in enumerate(messages):
                print(f"\n=== Message {i} ===")
                print(f"ID: {message.get('id')}")
                print(f"Role: {message.get('role')}")
                
                if message.get('role') == 'image':
                    content = message.get('content', '')
                    metadata = message.get('metadata', {})
                    
                    print(f"Content: {content}")
                    print(f"Metadata: {metadata}")
                    
                    if metadata.get('is_large_image'):
                        print("✅ This is marked as a large image!")
                        print(f"Expected size: {metadata.get('image_size')} bytes")
                        print(f"URL reference: {content}")
                        
                        # The content should be a URL like /api/image/xxx
                        if content.startswith('/api/image/'):
                            print("✅ URL format is correct")
                        else:
                            print("❌ URL format is incorrect")
                    else:
                        print("❌ This is not marked as a large image")
                        if content.startswith('data:image/'):
                            print(f"Data URL length: {len(content)} bytes")
                        else:
                            print(f"Unexpected content format: {content[:100]}...")
                else:
                    print(f"Content: {message.get('content', '')[:100]}...")
        else:
            print(f"❌ Request failed: {response.status_code}")
            print(f"Response: {response.text}")
            
    except Exception as e:
        print(f"❌ Request failed: {e}")

if __name__ == "__main__":
    test_messages_content()
