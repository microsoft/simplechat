#!/usr/bin/env python3
"""
Test script using actual Cosmos DB data structure to debug reassembly.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_real_cosmos_data():
    """Test with the actual Cosmos DB data structure"""
    print("🔍 Testing with real Cosmos DB data structure...")
    
    # Actual data from user's Cosmos DB (simplified)
    all_items = [
        {
            "id": "fea9b98e-9185-4c2a-a428-2fe04bec643d_user_1757366351_4210",
            "conversation_id": "fea9b98e-9185-4c2a-a428-2fe04bec643d",
            "role": "user",
            "content": "window shopping a candy shop with the name \"Candy Shoppe\"",
            "timestamp": "2025-09-08T21:19:11.389609"
        },
        {
            "id": "fea9b98e-9185-4c2a-a428-2fe04bec643d_image_1757366402_4665",
            "conversation_id": "fea9b98e-9185-4c2a-a428-2fe04bec643d",
            "role": "image",
            "content": "data:image/png;base64,FIRSTCHUNK_CONTENT_ENDS_WITH_9k",
            "prompt": "window shopping a candy shop with the name \"Candy Shoppe\"",
            "metadata": {
                "is_chunked": True,
                "total_chunks": 2,
                "chunk_index": 0,
                "original_size": 2780414
            }
        },
        {
            "id": "fea9b98e-9185-4c2a-a428-2fe04bec643d_image_1757366402_4665_chunk_1",
            "conversation_id": "fea9b98e-9185-4c2a-a428-2fe04bec643d",
            "role": "image_chunk",
            "content": "SECONDCHUNK_CONTENT_ENDS_WITH_gg==",
            "parent_message_id": "fea9b98e-9185-4c2a-a428-2fe04bec643d_image_1757366402_4665",
            "metadata": {
                "is_chunk": True,
                "chunk_index": 1,
                "total_chunks": 2,
                "parent_message_id": "fea9b98e-9185-4c2a-a428-2fe04bec643d_image_1757366402_4665"
            }
        }
    ]
    
    # Follow the exact logic from route_backend_conversations.py
    messages = []
    chunked_images = {}
    
    print("Processing all items...")
    for item in all_items:
        print(f"Processing item: {item.get('id')}, role: {item.get('role')}")
        
        if item.get('role') == 'image_chunk':
            print(f"  → This is a chunk")
            # This is a chunk, store it for reassembly
            parent_id = item.get('parent_message_id')
            if parent_id not in chunked_images:
                chunked_images[parent_id] = {}
            chunk_index = item.get('metadata', {}).get('chunk_index', 0)
            chunked_images[parent_id][chunk_index] = item.get('content', '')
            print(f"  → Stored chunk {chunk_index} for parent {parent_id}")
        else:
            print(f"  → This is a regular message")
            # Regular message or main image document
            if item.get('role') == 'image' and item.get('metadata', {}).get('is_chunked'):
                print(f"  → This is a chunked image main document")
                # This is a chunked image main document
                messages.append(item)
            else:
                print(f"  → This is a regular message")
                # Regular message
                messages.append(item)
    
    print(f"\nAfter processing:")
    print(f"Messages: {len(messages)}")
    print(f"Chunked images: {chunked_images}")
    
    # Reassemble chunked images
    print(f"\nReassembling chunked images...")
    for message in messages:
        print(f"Checking message: {message.get('id')}, role: {message.get('role')}")
        
        if (message.get('role') == 'image' and 
            message.get('metadata', {}).get('is_chunked')):
            
            image_id = message.get('id')
            total_chunks = message.get('metadata', {}).get('total_chunks', 1)
            
            print(f"  → Reassembling chunked image {image_id} with {total_chunks} chunks")
            print(f"  → Available chunks: {list(chunked_images.get(image_id, {}).keys())}")
            
            # Start with the content from the main message (chunk 0)
            complete_content = message.get('content', '')
            print(f"  → Main message content: {complete_content}")
            
            # Add remaining chunks in order
            if image_id in chunked_images:
                chunks = chunked_images[image_id]
                for chunk_index in range(1, total_chunks):
                    if chunk_index in chunks:
                        chunk_content = chunks[chunk_index]
                        complete_content += chunk_content
                        print(f"  → Added chunk {chunk_index}: {chunk_content}")
                    else:
                        print(f"  → WARNING: Missing chunk {chunk_index}")
            else:
                print(f"  → WARNING: No chunks found for {image_id}")
            
            # Show final result
            print(f"  → FINAL CONTENT: {complete_content}")
            message['content'] = complete_content
    
    # Show what would be returned
    print(f"\nFinal messages that would be returned:")
    for msg in messages:
        if msg.get('role') == 'image':
            print(f"Image message content: {msg.get('content')}")
    
    return True

if __name__ == "__main__":
    test_real_cosmos_data()
