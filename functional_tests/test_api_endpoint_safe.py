#!/usr/bin/env python3
"""
Test script to check image size without downloading full content.
"""

import requests
import json

def test_api_messages_with_limit():
    """Test the /api/messages endpoint with response size check"""
    print("🔍 Testing /api/messages endpoint with size limits...")
    
    conversation_id = "fea9b98e-9185-4c2a-a428-2fe04bec643d"
    url = f"http://127.0.0.1:5000/api/messages"
    params = {'conversation_id': conversation_id}
    
    print(f"Making request to: {url}")
    print(f"Parameters: {params}")
    
    try:
        # Use stream=True to check response size before downloading
        response = requests.get(url, params=params, stream=True, timeout=10)
        print(f"Response status: {response.status_code}")
        print(f"Response headers: {dict(response.headers)}")
        
        # Check content length
        content_length = response.headers.get('content-length')
        if content_length:
            print(f"Content-Length: {content_length} bytes ({int(content_length)/1024/1024:.2f} MB)")
            
            if int(content_length) > 10 * 1024 * 1024:  # 10MB
                print("⚠️  Response is very large (>10MB) - this might cause connection issues")
        
        # Try to read just the first part
        print("Attempting to read response...")
        try:
            content = response.content
            print(f"Successfully read {len(content)} bytes")
            
            # Try to parse JSON
            data = json.loads(content)
            messages = data.get('messages', [])
            print(f"Got {len(messages)} messages")
            
            for i, message in enumerate(messages):
                if message.get('role') == 'image':
                    content_len = len(message.get('content', ''))
                    print(f"Image {i} content length: {content_len} bytes ({content_len/1024/1024:.2f} MB)")
                    
                    # Check if it's properly formatted
                    content_str = message.get('content', '')
                    if content_str.startswith('data:image/'):
                        if ',' in content_str:
                            header, base64_data = content_str.split(',', 1)
                            print(f"  Header: {header}")
                            print(f"  Base64 length: {len(base64_data)}")
                            print(f"  Ends with: '{base64_data[-10:] if len(base64_data) > 10 else base64_data}'")
                            
                            # Check if complete
                            if base64_data.endswith('==') or base64_data.endswith('='):
                                print(f"  ✅ Base64 appears complete")
                            else:
                                print(f"  ⚠️  Base64 might be truncated")
                        
        except Exception as read_error:
            print(f"❌ Error reading response: {read_error}")
            
    except requests.exceptions.Timeout:
        print("❌ Request timed out")
    except requests.exceptions.ConnectionError as e:
        print(f"❌ Connection error: {e}")
    except Exception as e:
        print(f"❌ Request failed: {e}")

if __name__ == "__main__":
    test_api_messages_with_limit()
