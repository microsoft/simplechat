#!/usr/bin/env python3
"""
Test script for the new large image URL reference approach.
"""

import requests
import json

def test_large_image_api():
    """Test the new large image API approach"""
    print("🔍 Testing large image API with URL references...")
    
    conversation_id = "fea9b98e-9185-4c2a-a428-2fe04bec643d"
    url = f"http://127.0.0.1:5000/api/messages"
    params = {'conversation_id': conversation_id}
    
    print(f"Making request to: {url}")
    
    try:
        # Test the messages endpoint
        response = requests.get(url, params=params, timeout=30)
        print(f"Messages response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            messages = data.get('messages', [])
            print(f"Got {len(messages)} messages")
            
            for i, message in enumerate(messages):
                print(f"\nMessage {i}:")
                print(f"  ID: {message.get('id')}")
                print(f"  Role: {message.get('role')}")
                print(f"  Content: {message.get('content', '')[:100]}...")
                
                if message.get('role') == 'image':
                    metadata = message.get('metadata', {})
                    if metadata.get('is_large_image'):
                        print(f"  ✅ Large image detected!")
                        print(f"  Size: {metadata.get('image_size')} bytes")
                        print(f"  URL: {message.get('content')}")
                        
                        # Test the image endpoint
                        image_url = f"http://127.0.0.1:5000{message.get('content')}"
                        print(f"  Testing image endpoint: {image_url}")
                        
                        try:
                            img_response = requests.get(image_url, timeout=30)
                            print(f"  Image response status: {img_response.status_code}")
                            print(f"  Image response headers: {dict(img_response.headers)}")
                            print(f"  Image content length: {len(img_response.content)} bytes")
                            
                            if img_response.status_code == 200:
                                print(f"  ✅ Image successfully retrieved!")
                                
                                # Check if it's a valid image
                                content_type = img_response.headers.get('content-type', '')
                                if content_type.startswith('image/'):
                                    print(f"  Content-Type: {content_type}")
                                    print(f"  ✅ Valid image format!")
                                else:
                                    print(f"  ⚠️  Unexpected content type: {content_type}")
                            else:
                                print(f"  ❌ Image request failed: {img_response.text}")
                                
                        except Exception as img_error:
                            print(f"  ❌ Image request error: {img_error}")
                    else:
                        content_len = len(message.get('content', ''))
                        print(f"  Small image (embedded): {content_len} bytes")
        else:
            print(f"❌ Messages request failed: {response.text}")
            
    except Exception as e:
        print(f"❌ Request failed: {e}")

if __name__ == "__main__":
    test_large_image_api()
