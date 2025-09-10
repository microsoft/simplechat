#!/usr/bin/env python3
"""
Test script to debug the chunked image reassembly issue.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_reassembly_logic():
    """Test the reassembly logic with sample data"""
    print("🔍 Testing chunked image reassembly logic...")
    
    # Simulate the data structure from Cosmos DB
    all_items = [
        {
            'id': 'test_image_123',
            'role': 'image',
            'content': 'data:image/png;base64,CHUNK0CONTENT',
            'metadata': {
                'is_chunked': True,
                'total_chunks': 3,
                'chunk_index': 0
            }
        },
        {
            'id': 'test_image_123_chunk_1',
            'role': 'image_chunk',
            'content': 'CHUNK1CONTENT',
            'parent_message_id': 'test_image_123',
            'metadata': {
                'is_chunk': True,
                'chunk_index': 1,
                'total_chunks': 3,
                'parent_message_id': 'test_image_123'
            }
        },
        {
            'id': 'test_image_123_chunk_2',
            'role': 'image_chunk',
            'content': 'CHUNK2CONTENT',
            'parent_message_id': 'test_image_123',
            'metadata': {
                'is_chunk': True,
                'chunk_index': 2,
                'total_chunks': 3,
                'parent_message_id': 'test_image_123'
            }
        }
    ]
    
    # Simulate the reassembly logic from route_backend_conversations.py
    messages = []
    chunked_images = {}
    
    for item in all_items:
        if item.get('role') == 'image_chunk':
            # This is a chunk, store it for reassembly
            parent_id = item.get('parent_message_id')
            if parent_id not in chunked_images:
                chunked_images[parent_id] = {}
            chunk_index = item.get('metadata', {}).get('chunk_index', 0)
            chunked_images[parent_id][chunk_index] = item.get('content', '')
            print(f"Found chunk {chunk_index} for parent {parent_id}")
        else:
            # Regular message or main image document
            if item.get('role') == 'image' and item.get('metadata', {}).get('is_chunked'):
                # This is a chunked image main document
                messages.append(item)
                print(f"Found main chunked image: {item.get('id')}")
            else:
                # Regular message
                messages.append(item)
    
    print(f"Messages to process: {len(messages)}")
    print(f"Chunked images found: {list(chunked_images.keys())}")
    
    # Reassemble chunked images
    for message in messages:
        if (message.get('role') == 'image' and 
            message.get('metadata', {}).get('is_chunked')):
            
            image_id = message.get('id')
            total_chunks = message.get('metadata', {}).get('total_chunks', 1)
            
            print(f"Reassembling chunked image {image_id} with {total_chunks} chunks")
            print(f"Available chunks in chunked_images: {list(chunked_images.get(image_id, {}).keys())}")
            
            # Start with the content from the main message (chunk 0)
            complete_content = message.get('content', '')
            print(f"Main message content length: {len(complete_content)} bytes")
            
            # Add remaining chunks in order (chunks 1, 2, 3, etc.)
            if image_id in chunked_images:
                chunks = chunked_images[image_id]
                for chunk_index in range(1, total_chunks):
                    if chunk_index in chunks:
                        chunk_content = chunks[chunk_index]
                        complete_content += chunk_content
                        print(f"Added chunk {chunk_index}, length: {len(chunk_content)} bytes")
                    else:
                        print(f"WARNING: Missing chunk {chunk_index} for image {image_id}")
            else:
                print(f"WARNING: No chunks found for image {image_id} in chunked_images")
            
            # Update the message content with reassembled image
            original_content = message['content']
            message['content'] = complete_content
            print(f"BEFORE: {original_content}")
            print(f"AFTER:  {complete_content}")
            print(f"Final reassembled image total size: {len(complete_content)} bytes")
            
            return complete_content == "data:image/png;base64,CHUNK0CONTENTCHUNK1CONTENTCHUNK2CONTENT"
    
    return False

if __name__ == "__main__":
    success = test_reassembly_logic()
    if success:
        print("✅ Reassembly logic test PASSED")
    else:
        print("❌ Reassembly logic test FAILED")
