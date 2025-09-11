#!/usr/bin/env python3
"""
Functional test for chunked image reassembly debug.
Version: 0.226.109
Implemented in: 0.226.109

This test ensures that chunked image reassembly debugging works correctly.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the app and config
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from app import app
from config import cosmos_messages_container

def test_chunk_document_structure():
    """Test what chunk documents look like in Cosmos DB"""
    print("🔍 Testing chunk document structure in Cosmos DB...")
    
    try:
        # Use the same conversation_id from the user's example
        conversation_id = "fea9b98e-9185-4c2a-a428-2fe04bec643d"
        
        print(f"Querying for conversation: {conversation_id}")
        
        # Use the exact same query as the application
        message_query = f"SELECT * FROM c WHERE c.conversation_id = '{conversation_id}' ORDER BY c.timestamp ASC"
        
        print(f"Query: {message_query}")
        print(f"Partition key: {conversation_id}")
        
        all_items = list(cosmos_messages_container.query_items(
            query=message_query,
            partition_key=conversation_id
        ))
        
        print(f"Query returned {len(all_items)} items")
        
        for i, item in enumerate(all_items):
            print(f"\nItem {i}:")
            print(f"  id: {item.get('id')}")
            print(f"  role: {item.get('role')}")
            print(f"  partition_key: {item.get('conversation_id')}")
            print(f"  content_length: {len(item.get('content', ''))}")
            print(f"  metadata: {item.get('metadata', {})}")
            print(f"  parent_message_id: {item.get('parent_message_id', 'N/A')}")
            
            # For chunks, show more details
            if item.get('role') == 'image_chunk':
                print(f"  >>> THIS IS AN IMAGE CHUNK")
                print(f"  >>> chunk_index: {item.get('metadata', {}).get('chunk_index')}")
                print(f"  >>> parent_id: {item.get('parent_message_id')}")
            elif item.get('role') == 'image' and item.get('metadata', {}).get('is_chunked'):
                print(f"  >>> THIS IS A CHUNKED IMAGE MAIN DOCUMENT")
                print(f"  >>> total_chunks: {item.get('metadata', {}).get('total_chunks')}")
        
        # Test reassembly logic
        print("\n" + "="*60)
        print("TESTING REASSEMBLY LOGIC")
        print("="*60)
        
        messages = []
        chunked_images = {}
        
        for item in all_items:
            if item.get('role') == 'image_chunk':
                print(f"Processing chunk: {item.get('id')}")
                parent_id = item.get('parent_message_id')
                if parent_id not in chunked_images:
                    chunked_images[parent_id] = {}
                chunk_index = item.get('metadata', {}).get('chunk_index', 0)
                chunked_images[parent_id][chunk_index] = item.get('content', '')
                print(f"  Stored chunk {chunk_index} for parent {parent_id}")
            else:
                messages.append(item)
        
        print(f"\nChunked images dict: {list(chunked_images.keys())}")
        for parent_id, chunks in chunked_images.items():
            print(f"  {parent_id}: chunks {list(chunks.keys())}")
        
        # Reassemble
        for message in messages:
            if (message.get('role') == 'image' and 
                message.get('metadata', {}).get('is_chunked')):
                
                image_id = message.get('id')
                total_chunks = message.get('metadata', {}).get('total_chunks', 1)
                
                print(f"\nReassembling image {image_id}")
                print(f"  Expected chunks: {total_chunks}")
                print(f"  Available chunks: {list(chunked_images.get(image_id, {}).keys())}")
                
                # Start with main content
                complete_content = message.get('content', '')
                original_length = len(complete_content)
                
                # Add chunks
                if image_id in chunked_images:
                    chunks = chunked_images[image_id]
                    for chunk_index in range(1, total_chunks):
                        if chunk_index in chunks:
                            chunk_content = chunks[chunk_index]
                            complete_content += chunk_content
                            print(f"  Added chunk {chunk_index}: {len(chunk_content)} bytes")
                        else:
                            print(f"  MISSING chunk {chunk_index}")
                
                final_length = len(complete_content)
                print(f"  Original: {original_length} bytes")
                print(f"  Final: {final_length} bytes")
                print(f"  Gain: {final_length - original_length} bytes")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_chunk_document_structure()
    sys.exit(0 if success else 1)
