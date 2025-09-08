#!/usr/bin/env python3
"""
Test script to call the API endpoint and see the chunked image reassembly in action.
"""

import requests
import json

def test_api_messages():
    """Test the /api/messages endpoint"""
    print("🔍 Testing /api/messages endpoint...")
    
    # Use the conversation ID from your example
    conversation_id = "fea9b98e-9185-4c2a-a428-2fe04bec643d"
    
    # Make the API request
    url = f"http://127.0.0.1:5000/api/messages"
    params = {'conversation_id': conversation_id}
    
    print(f"Making request to: {url}")
    print(f"Parameters: {params}")
    
    try:
        response = requests.get(url, params=params)
        print(f"Response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            messages = data.get('messages', [])
            print(f"Got {len(messages)} messages")
            
            for i, message in enumerate(messages):
                print(f"\nMessage {i}:")
                print(f"  ID: {message.get('id')}")
                print(f"  Role: {message.get('role')}")
                print(f"  Content length: {len(message.get('content', ''))}")
                
                if message.get('role') == 'image':
                    content = message.get('content', '')
                    if content.startswith('data:image/'):
                        print(f"  Image data URL format: YES")
                        # Check if it's a complete base64 string
                        if ',' in content:
                            header, base64_data = content.split(',', 1)
                            print(f"  Header: {header}")
                            print(f"  Base64 data length: {len(base64_data)}")
                            
                            # Check if it ends properly
                            if base64_data.endswith('==') or base64_data.endswith('='):
                                print(f"  Base64 ending: PROPER (ends with =)")
                            else:
                                print(f"  Base64 ending: SUSPICIOUS (last 10 chars: '{base64_data[-10:]}')")
                    else:
                        print(f"  Image data URL format: NO")
                    
                    # Check metadata
                    metadata = message.get('metadata', {})
                    if metadata.get('is_chunked'):
                        print(f"  Chunked image: YES (total_chunks: {metadata.get('total_chunks')})")
                        print(f"  Original size: {metadata.get('original_size')} bytes")
                    else:
                        print(f"  Chunked image: NO")
        else:
            print(f"Error response: {response.text}")
            
    except Exception as e:
        print(f"❌ Request failed: {e}")

if __name__ == "__main__":
    test_api_messages()
