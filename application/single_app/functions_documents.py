# functions_documents.py

from config import *
from functions_content import *
from functions_settings import *
from functions_search import *
from functions_logging import *

def allowed_file(filename, allowed_extensions=None):
    if not allowed_extensions:
        allowed_extensions = ALLOWED_EXTENSIONS
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions
    
def create_document(file_name, user_id, document_id, num_file_chunks, status, group_id=None):
    current_time = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    is_group = group_id is not None

    # Choose the correct cosmos_container and query parameters
    cosmos_container = cosmos_group_documents_container if is_group else cosmos_user_documents_container

    if is_group:
        query = """
            SELECT * 
            FROM c
            WHERE c.file_name = @file_name 
                AND c.group_id = @group_id
        """
        parameters = [
            {"name": "@file_name", "value": file_name},
            {"name": "@group_id", "value": group_id}
        ]
    else:
        query = """
            SELECT * 
            FROM c
            WHERE c.file_name = @file_name 
                AND c.user_id = @user_id
        """
        parameters = [
            {"name": "@file_name", "value": file_name},
            {"name": "@user_id", "value": user_id}
        ]

    try:
        existing_document = list(
            cosmos_container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            )
        )
        version = existing_document[0]['version'] + 1 if existing_document else 1
        
        if is_group:
            document_metadata = {
                "id": document_id,
                "file_name": file_name,
                "num_chunks": 0,
                "number_of_pages": 0,
                "current_file_chunk": 0,
                "num_file_chunks": num_file_chunks,
                "upload_date": current_time,
                "last_updated": current_time,
                "version": version,
                "status": status,
                "percentage_complete": 0,
                "document_classification": "Pending",
                "type": "document_metadata",
                "group_id": group_id
            }
        else:
            document_metadata = {
                "id": document_id,
                "file_name": file_name,
                "num_chunks": 0,
                "number_of_pages": 0,
                "current_file_chunk": 0,
                "num_file_chunks": num_file_chunks,
                "upload_date": current_time,
                "last_updated": current_time,
                "version": version,
                "status": status,
                "percentage_complete": 0,
                "document_classification": "Pending",
                "type": "document_metadata",
                "user_id": user_id
            }

        cosmos_container.upsert_item(document_metadata)

        add_file_task_to_file_processing_log(
            document_id,
            user_id,
            f"Document {file_name} created."
        )

    except Exception as e:
        print(f"Error creating document: {e}")
        raise


def get_document_metadata(document_id, user_id, group_id=None):
    is_group = group_id is not None
    cosmos_container = cosmos_group_documents_container if is_group else cosmos_user_documents_container

    if is_group:
        query = """
            SELECT * 
            FROM c
            WHERE c.id = @document_id 
                AND c.group_id = @group_id
            ORDER BY c.version DESC
        """
        parameters = [
            {"name": "@document_id", "value": document_id},
            {"name": "@group_id", "value": group_id}
        ]
    else:
        query = """
            SELECT * 
            FROM c
            WHERE c.id = @document_id 
                AND c.user_id = @user_id
            ORDER BY c.version DESC
        """
        parameters = [
            {"name": "@document_id", "value": document_id},
            {"name": "@user_id", "value": user_id}
        ]

    add_file_task_to_file_processing_log(
        document_id=document_id, 
        user_id=group_id if is_group else user_id,
        content=f"Query is {query}, parameters are {parameters}."
    )
    try:
        document_items = list(
            cosmos_container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            )
        )
        add_file_task_to_file_processing_log(
            document_id=document_id, 
            user_id=group_id if is_group else user_id,
            content=f"Document metadata retrieved: {document_items}."
        )
        return document_items[0] if document_items else None

    except Exception as e:
        print(f"Error retrieving document metadata: {repr(e)}\nTraceback:\n{traceback.format_exc()}")
        return None



def calculate_processing_percentage(doc_metadata):
    """
    Calculates a simpler, step-based processing percentage based on status
    and page saving progress.

    Args:
        doc_metadata (dict): The current document metadata dictionary.

    Returns:
        int: The calculated percentage (0-100).
    """
    status = doc_metadata.get('status', '')
    if isinstance(status, str):
        status = status.lower()
    elif isinstance(status, bytes):
        status = status.decode('utf-8').lower()
    elif isinstance(status, dict):
        status = json.dumps(status).lower()
        

    current_pct = doc_metadata.get('percentage_complete', 0)
    estimated_pages = doc_metadata.get('number_of_pages', 0)
    total_chunks_saved = doc_metadata.get('current_file_chunk', 0)

    # --- Final States ---
    if "processing complete" in status or current_pct == 100:
        # Ensure it stays 100 if it ever reached it
        return 100
    if "error" in status or "failed" in status:
        # Keep the last known percentage on error/failure
        return current_pct

    # --- Calculate percentage based on phase/status ---
    calculated_pct = 0

    # Phase 1: Initial steps up to sending to DI
    if "queued" in status:
        calculated_pct = 0

    elif "sending" in status:
        # Explicitly sending data for analysis
        calculated_pct = 5

    # Phase 3: Saving Pages (The main progress happens here: 10% -> 90%)
    elif "saving page" in status or "saving chunk" in status: # Status indicating the loop saving pages is active
        if estimated_pages > 0:
            # Calculate progress ratio (0.0 to 1.0)
            # Ensure saved count doesn't exceed estimate for the ratio
            safe_chunks_saved = min(total_chunks_saved, estimated_pages)
            progress_ratio = safe_chunks_saved / estimated_pages

            # Map the ratio to the percentage range [10, 90]
            # The range covers 80 percentage points (90 - 10)
            calculated_pct = 5 + (progress_ratio * 80)
        else:
            # If page count is unknown, we can't show granular progress.
            # Stay at the beginning of this phase.
            calculated_pct = 5

    # Phase 4: Final Metadata Extraction (Optional, after page saving)
    elif "extracting final metadata" in status:
        # This phase should start after page saving is effectively done (>=90%)
        # Assign a fixed value during this step.
        calculated_pct = 95

    # Default/Fallback: If status doesn't match known phases,
    # use the current percentage. This handles intermediate statuses like
    # "Chunk X/Y saved" which might occur between "saving page" updates.
    else:
        calculated_pct = current_pct


    # --- Final Adjustments ---

    # Cap at 99% - only "Processing Complete" status should trigger 100%
    final_pct = min(int(round(calculated_pct)), 99)

    # Prevent percentage from going down, unless it's due to an error state (handled above)
    # Compare the newly calculated capped percentage with the value read at the function start
    # This ensures progress is monotonic upwards until completion or error.
    return max(final_pct, current_pct)

def update_document(**kwargs):
    document_id = kwargs.get('document_id')
    user_id = kwargs.get('user_id')
    group_id = kwargs.get('group_id')
    num_chunks_increment = kwargs.pop('num_chunks_increment', 0)

    if (not document_id or not user_id) or (not document_id and not group_id):
        # Cannot proceed without these identifiers
        print("Error: document_id and user_id or document_id and group_id are required for update_document")
        # Depending on context, you might raise an error or return failure
        raise ValueError("document_id and user_id or document_id and group_id are required")

    current_time = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    is_group = group_id is not None

    # if is_group:
    #     log_msg = f"Group document update requested for {document_id} by group {group_id}."
    # else:
    #     log_msg = f"User document update requested for {document_id} by user {user_id}."

    # add_file_task_to_file_processing_log(
    #     document_id=document_id, 
    #     user_id=group_id if group_id else user_id, 
    #     content=log_msg
    # )

    # Choose the correct cosmos_container and query parameters
    cosmos_container = cosmos_group_documents_container if is_group else cosmos_user_documents_container

    if is_group:
        query = """
            SELECT * 
            FROM c
            WHERE c.id = @document_id 
                AND c.group_id = @group_id
        """
        parameters = [
            {"name": "@document_id", "value": document_id},
            {"name": "@group_id", "value": group_id}
        ]
    else:
        query = """
            SELECT * 
            FROM c
            WHERE c.id = @document_id 
                AND c.user_id = @user_id
        """
        parameters = [
            {"name": "@document_id", "value": document_id},
            {"name": "@user_id", "value": user_id}
        ]
    
    add_file_task_to_file_processing_log(
        document_id=document_id, 
        user_id=group_id if is_group else user_id, 
        content=f"Query is {query}, parameters are {parameters}."
    )

    try:
        existing_documents = list(
            cosmos_container.query_items(
                query=query, 
                parameters=parameters, 
                enable_cross_partition_query=True
            )
        )

        status = kwargs.get('status', '')

        if status:
            add_file_task_to_file_processing_log(
                document_id=document_id,
                user_id=group_id if is_group else user_id,
                content=f"Status: {status}"
            )

        if not existing_documents:
            # Log specific error before raising
            log_msg = f"Document {document_id} not found for user {user_id} during update."
            print(log_msg)
            add_file_task_to_file_processing_log(
                document_id=document_id, 
                user_id=group_id if is_group else user_id, 
                content=log_msg
            )
            raise CosmosResourceNotFoundError(
                message=f"Document {document_id} not found",
                status=404
            )


        existing_document = existing_documents[0]
        original_percentage = existing_document.get('percentage_complete', 0) # Store for comparison

        # 2. Apply updates from kwargs
        update_occurred = False
        updated_fields_requiring_chunk_sync = set() # Track fields needing propagation

        if num_chunks_increment > 0:
            current_num_chunks = existing_document.get('num_chunks', 0)
            existing_document['num_chunks'] = current_num_chunks + num_chunks_increment
            update_occurred = True # Incrementing counts as an update
            add_file_task_to_file_processing_log(
                document_id=document_id, 
                user_id=group_id if is_group else user_id,  
                content=f"Incrementing num_chunks by {num_chunks_increment} to {existing_document['num_chunks']}"
            )

        for key, value in kwargs.items():
            if value is not None and existing_document.get(key) != value:
                # Avoid overwriting num_chunks if it was just incremented
                if key == 'num_chunks' and num_chunks_increment > 0:
                    continue # Skip direct assignment if increment was used
                existing_document[key] = value
                update_occurred = True
                if key in ['title', 'authors', 'file_name', 'document_classification']:
                    updated_fields_requiring_chunk_sync.add(key)

        # 3. If any update happened, handle timestamps and percentage
        if update_occurred:
            existing_document['last_updated'] = current_time

            # Calculate new percentage based on the *updated* existing_document state
            # This now includes the potentially incremented num_chunks
            new_percentage = calculate_processing_percentage(existing_document)
            
            # Handle final state overrides for percentage

            status_lower = existing_document.get('status', '')
            if isinstance(status_lower, str):
                status_lower = status_lower.lower()
            elif isinstance(status_lower, bytes):
                status_lower = status_lower.decode('utf-8').lower()
            elif isinstance(status_lower, dict):
                status_lower = json.dumps(status_lower).lower()

            if "processing complete" in status_lower:
                new_percentage = 100
            elif "error" in status_lower or "failed" in status_lower:
                 pass # Percentage already calculated by helper based on 'failed' status

            # Ensure percentage doesn't decrease (unless reset on failure or hitting 100)
            # Compare against original_percentage fetched *before* any updates in this call
            if new_percentage < original_percentage and new_percentage != 0 and "failed" not in status_lower and "error" not in status_lower:
                 existing_document['percentage_complete'] = original_percentage
            else:
                 existing_document['percentage_complete'] = new_percentage

        # 4. Propagate relevant changes to search index chunks
        # This happens regardless of 'update_occurred' flag because the *intent* from kwargs might trigger it,
        # even if the main doc update didn't happen (e.g., only percentage changed).
        # However, it's better to only do this if the relevant fields *actually* changed.
        if update_occurred and updated_fields_requiring_chunk_sync:
            try:
                chunks_to_update = get_all_chunks(document_id, user_id)
                for chunk in chunks_to_update:
                    chunk_updates = {}
                    if 'title' in updated_fields_requiring_chunk_sync:
                        chunk_updates['title'] = existing_document.get('title')
                    if 'authors' in updated_fields_requiring_chunk_sync:
                         # Ensure authors is a list for the chunk metadata if needed
                        chunk_updates['author'] = existing_document.get('authors')
                    if 'file_name' in updated_fields_requiring_chunk_sync:
                        chunk_updates['file_name'] = existing_document.get('file_name')
                    if 'document_classification' in updated_fields_requiring_chunk_sync:
                        chunk_updates['document_classification'] = existing_document.get('document_classification')

                    if chunk_updates: # Only call update if there's something to change
                         update_chunk_metadata(chunk['id'], user_id, document_id, **chunk_updates)
                add_file_task_to_file_processing_log(
                    document_id=document_id, 
                    user_id=group_id if is_group else user_id,
                    content=f"Propagated updates for fields {updated_fields_requiring_chunk_sync} to search chunks."
                )
            except Exception as chunk_sync_error:
                # Log error but don't necessarily fail the whole document update
                error_msg = f"Warning: Failed to sync metadata updates to search chunks for doc {document_id}: {chunk_sync_error}"
                print(error_msg)
                add_file_task_to_file_processing_log(
                    document_id=document_id, 
                    user_id=group_id if is_group else user_id, 
                    content=error_msg
                )


        # 5. Upsert the document if changes were made
        if update_occurred:
            cosmos_container.upsert_item(existing_document)

    except CosmosResourceNotFoundError as e:
        # Error already logged where it was first detected
        print(f"Document {document_id} not found or access denied: {e}")
        raise # Re-raise for the caller to handle
    except Exception as e:
        error_msg = f"Error during update_document for {document_id}: {repr(e)}\nTraceback:\n{traceback.format_exc()}"
        print(error_msg)
        add_file_task_to_file_processing_log(
            document_id=document_id, 
            user_id=group_id if is_group else user_id,
            content=error_msg
        )
        # Optionally update status to failure here if the exception is critical
        # try:
        #    existing_document['status'] = f"Update failed: {str(e)[:100]}" # Truncate error
        #    existing_document['percentage_complete'] = calculate_processing_percentage(existing_document) # Recalculate % based on failure
        #    documents_container.upsert_item(existing_document)
        # except Exception as inner_e:
        #    print(f"Failed to update status to error state for {document_id}: {inner_e}")
        raise # Re-raise the original exception

def save_chunks(page_text_content, page_number, file_name, user_id, document_id, group_id=None):
    """
    Save a single chunk (one page) at a time:
      - Generate embedding
      - Build chunk metadata
      - Upload to Search index
    """
    current_time = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    is_group = group_id is not None

    # Choose the correct cosmos_container and query parameters
    cosmos_container = cosmos_group_documents_container if is_group else cosmos_user_documents_container

    try:
        # Update document status
        #num_chunks = 1  # because we only have one chunk (page) here
        #status = f"Processing 1 chunk (page {page_number})"
        #update_document(document_id=document_id, user_id=user_id, status=status)
        
        add_file_task_to_file_processing_log(
            document_id=document_id, 
            user_id=group_id if is_group else user_id, 
            content=f"Saving chunk, cosmos_container:{cosmos_container}, page_text_content:{page_text_content}, page_number:{page_number}, file_name:{file_name}, user_id:{user_id}, document_id:{document_id}, group_id:{group_id}"
        )

        if is_group:
            metadata = get_document_metadata(
                document_id=document_id, 
                user_id=user_id, 
                group_id=group_id
            )
        else:
            metadata = get_document_metadata(
                document_id=document_id, 
                user_id=user_id
            )

        if not metadata:
            raise ValueError(f"No metadata found for document {document_id} (group: {is_group})")

        version = metadata.get("version") if metadata.get("version") else 1 
        if version is None:
            raise ValueError(f"Metadata for document {document_id} missing 'version' field")
        
    except Exception as e:
        print(f"Error updating document status or retrieving metadata for document {document_id}: {repr(e)}\nTraceback:\n{traceback.format_exc()}")
        raise

    # Generate embedding
    try:
        #status = f"Generating embedding for page {page_number}"
        #update_document(document_id=document_id, user_id=user_id, status=status)
        embedding = generate_embedding(page_text_content)
    except Exception as e:
        print(f"Error generating embedding for page {page_number} of document {document_id}: {e}")
        raise

    # Build chunk document
    try:
        chunk_id = f"{document_id}_{page_number}"
        chunk_keywords = []
        chunk_summary = ""
        author = []
        title = ""

        if is_group:
            chunk_document = {
                "id": chunk_id,
                "document_id": document_id,
                "chunk_id": str(page_number),
                "chunk_text": page_text_content,
                "embedding": embedding,
                "file_name": file_name,
                "chunk_keywords": chunk_keywords,
                "chunk_summary": chunk_summary,
                "page_number": page_number,
                "author": author,
                "title": title,
                "document_classification": "Pending",
                "chunk_sequence": page_number,  # or you can keep an incremental idx
                "upload_date": current_time,
                "version": version,
                "group_id": group_id
            }
        else:
            chunk_document = {
                "id": chunk_id,
                "document_id": document_id,
                "chunk_id": str(page_number),
                "chunk_text": page_text_content,
                "embedding": embedding,
                "file_name": file_name,
                "chunk_keywords": chunk_keywords,
                "chunk_summary": chunk_summary,
                "page_number": page_number,
                "author": author,
                "title": title,
                "document_classification": "Pending",
                "chunk_sequence": page_number,  # or you can keep an incremental idx
                "upload_date": current_time,
                "version": version,
                "user_id": user_id
            }
    except Exception as e:
        print(f"Error creating chunk document for page {page_number} of document {document_id}: {e}")
        raise

    # Upload chunk document to Search
    try:
        #status = f"Uploading page {page_number} of document {document_id} to index."
        #update_document(document_id=document_id, user_id=user_id, status=status)

        search_client = CLIENTS["search_client_group"] if is_group else CLIENTS["search_client_user"]
        # Upload as a single-document list
        search_client.upload_documents(documents=[chunk_document])

    except Exception as e:
        print(f"Error uploading chunk document for document {document_id}: {e}")
        raise

def get_all_chunks(document_id, user_id, group_id=None):
    is_group = group_id is not None

    search_client = CLIENTS["search_client_group"] if is_group else CLIENTS["search_client_user"]
    filter_expr = (
        f"document_id eq '{document_id}' and group_id eq '{group_id}'"
        if is_group else
        f"document_id eq '{document_id}' and user_id eq '{user_id}'"
    )

    select_fields = [
        "id", 
        "chunk_text", 
        "chunk_id", 
        "file_name",
        "group_id" if is_group else "user_id",
        "version", 
        "chunk_sequence", 
        "upload_date"
    ]

    try:
        results = search_client.search(
            search_text="*",
            filter=filter_expr,
            select=",".join(select_fields)
        )
        return results

    except Exception as e:
        print(f"Error retrieving chunks for document {document_id}: {e}")
        raise

def update_chunk_metadata(chunk_id, user_id, group_id, document_id, **kwargs):
    is_group = group_id is not None

    try:
        search_client = CLIENTS["search_client_group"] if is_group else CLIENTS["search_client_user"]
        chunk_item = search_client.get_document(key=chunk_id)

        if not chunk_item:
            raise Exception("Chunk not found")

        if chunk_item.get('user_id') != user_id or (is_group and chunk_item.get('group_id') != group_id):
            raise Exception("Unauthorized access to chunk")

        if chunk_item.get('document_id') != document_id:
            raise Exception("Chunk does not belong to document")

        # Update only supported fields
        updatable_fields = [
            'chunk_keywords',
            'chunk_summary',
            'author',
            'title',
            'document_classification'
        ]
        for field in updatable_fields:
            if field in kwargs:
                chunk_item[field] = kwargs[field]

        search_client.upload_documents(documents=[chunk_item])

    except Exception as e:
        print(f"Error updating chunk metadata for chunk {chunk_id}: {e}")
        raise

def get_pdf_page_count(pdf_path: str) -> int:
    """
    Returns the total number of pages in the given PDF using PyMuPDF.
    """
    try:
        with fitz.open(pdf_path) as doc:
            return doc.page_count
    except Exception as e:
        print(f"Error reading PDF page count: {e}")
        return 0

def chunk_pdf(input_pdf_path: str, max_pages: int = 500) -> list:
    """
    Splits a PDF into multiple PDFs, each with up to `max_pages` pages,
    using PyMuPDF. Returns a list of file paths for the newly created chunks.
    """
    chunks = []
    try:
        with fitz.open(input_pdf_path) as doc:
            total_pages = doc.page_count
            current_page = 0
            chunk_index = 1
            
            base_name, ext = os.path.splitext(input_pdf_path)
            
            # Loop through the PDF in increments of `max_pages`
            while current_page < total_pages:
                end_page = min(current_page + max_pages, total_pages)
                
                # Create a new, empty document for this chunk
                chunk_doc = fitz.open()
                
                # Insert the range of pages in one go
                chunk_doc.insert_pdf(doc, from_page=current_page, to_page=end_page - 1)
                
                chunk_pdf_path = f"{base_name}_chunk_{chunk_index}{ext}"
                chunk_doc.save(chunk_pdf_path)
                chunk_doc.close()
                
                chunks.append(chunk_pdf_path)
                
                current_page = end_page
                chunk_index += 1

    except Exception as e:
        print(f"Error chunking PDF: {e}")

    return chunks

def get_documents(user_id, group_id=None):
    is_group = group_id is not None

    # Choose the correct cosmos_container and query parameters
    cosmos_container = cosmos_group_documents_container if is_group else cosmos_user_documents_container

    if is_group:
        query = """
            SELECT * 
            FROM c
            WHERE c.group_id = @group_id
        """
        parameters = [
            {"name": "@group_id", "value": group_id}
        ]
    else:
        query = """
            SELECT * 
            FROM c
            WHERE c.user_id = @user_id
        """
        parameters = [
            {"name": "@user_id", "value": user_id}
        ]
    
    try:       
        documents = list(
            cosmos_container.query_items(
                query=query,
                parameters=parameters, 
                enable_cross_partition_query=True
            )
        )

        latest_documents = {}

        for doc in documents:
            file_name = doc['file_name']
            if file_name not in latest_documents or doc['version'] > latest_documents[file_name]['version']:
                latest_documents[file_name] = doc
                
        return jsonify({"documents": list(latest_documents.values())}), 200
    except Exception as e:
        return jsonify({'error': f'Error retrieving documents: {str(e)}'}), 500

def get_document(user_id, document_id, group_id=None):
    is_group = group_id is not None

    # Choose the correct cosmos_container and query parameters
    cosmos_container = cosmos_group_documents_container if is_group else cosmos_user_documents_container

    if is_group:
        query = """
            SELECT TOP 1 * 
            FROM c
            WHERE c.id = @document_id 
                AND c.group_id = @group_id
            ORDER BY c.version DESC
        """
        parameters = [
            {"name": "@document_id", "value": document_id},
            {"name": "@group_id", "value": group_id}
        ]
    else:
        query = """
            SELECT TOP 1 * 
            FROM c
            WHERE c.id = @document_id 
                AND c.user_id = @user_id
            ORDER BY c.version DESC
        """
        parameters = [
            {"name": "@document_id", "value": document_id},
            {"name": "@user_id", "value": user_id}
        ]

    try:
        document_results = list(
            cosmos_container.query_items(
                query=query, 
                parameters=parameters, 
                enable_cross_partition_query=True
            )
        )

        if not document_results:
            return jsonify({'error': 'Document not found or access denied'}), 404

        return jsonify(document_results[0]), 200

    except Exception as e:
        return jsonify({'error': f'Error retrieving document: {str(e)}'}), 500

def get_latest_version(document_id, user_id, group_id=None):
    is_group = group_id is not None
    cosmos_container = cosmos_group_documents_container if is_group else cosmos_user_documents_container

    if is_group:
        query = """
            SELECT c.version 
            FROM c
            WHERE c.id = @document_id 
                AND c.group_id = @group_id
            ORDER BY c.version DESC
        """
        parameters = [
            {"name": "@document_id", "value": document_id},
            {"name": "@group_id", "value": group_id}
        ]
    else:
        query = """
            SELECT c.version
            FROM c
            WHERE c.id = @document_id 
                AND c.user_id = @user_id
            ORDER BY c.version DESC
        """
        parameters = [
            {"name": "@document_id", "value": document_id},
            {"name": "@user_id", "value": user_id}
        ]

    try:
        results = list(
            cosmos_container.query_items(
                query=query, 
                parameters=parameters, 
                enable_cross_partition_query=True
            )
        )

        if results:
            return results[0]['version']
        else:
            return None

    except Exception as e:
        return None
    
def get_document_version(user_id, document_id, version, group_id=None):
    is_group = group_id is not None
    cosmos_container = cosmos_group_documents_container if is_group else cosmos_user_documents_container

    if is_group:
        query = """
            SELECT * 
            FROM c
            WHERE c.id = @document_id
                AND c.version = @version
                AND c.group_id = @group_id
            ORDER BY c.version DESC
        """
        parameters = [
            {"name": "@document_id", "value": document_id},
            {"name": "@version", "value": version},
            {"name": "@group_id", "value": group_id}
        ]
    else:
        query = """
            SELECT *
            FROM c
            WHERE c.id = @document_id 
                AND c.version = @version
                AND c.user_id = @user_id
            ORDER BY c.version DESC
        """
        parameters = [
            {"name": "@document_id", "value": document_id},
            {"name": "@version", "value": version},
            {"name": "@user_id", "value": user_id}
        ]

    try:
        document_results = list(
            cosmos_container.query_items(
                query=query, 
                parameters=parameters, 
                enable_cross_partition_query=True
            )
        )

        if not document_results:
            return jsonify({'error': 'Document version not found'}), 404

        return jsonify(document_results[0]), 200

    except Exception as e:
        return jsonify({'error': f'Error retrieving document version: {str(e)}'}), 500

# def delete_document(user_id, document_id, group_id=None):
#     """Delete a document from the user's documents in Cosmos DB."""
#     is_group = group_id is not None
#     cosmos_container = cosmos_group_documents_container if is_group else cosmos_user_documents_container

#     try:
#         document_item = cosmos_container.read_item(
#             item=document_id,
#             partition_key=document_id
#         )

#         if (document_item.get('user_id') != user_id) or (is_group and document_item.get('group_id') != group_id):
#             raise Exception("Unauthorized access to document")

#         cosmos_container.delete_item(
#             item=document_id,
#             partition_key=document_id
#         )

#     except CosmosResourceNotFoundError:
#         raise Exception("Document not found")
#     except Exception as e:
#         raise

def delete_document_chunks(document_id, group_id=None):
    """Delete document chunks from Azure Cognitive Search index."""

    is_group = group_id is not None

    try:
        search_client = CLIENTS["search_client_group"] if is_group else CLIENTS["search_client_user"]
        results = search_client.search(
            search_text="*",
            filter=f"document_id eq '{document_id}'",
            select=["id"]
        )

        ids_to_delete = [doc['id'] for doc in results]

        if not ids_to_delete:
            return

        documents_to_delete = [{"id": doc_id} for doc_id in ids_to_delete]
        batch = IndexDocumentsBatch()
        batch.add_delete_actions(documents_to_delete)
        result = search_client.index_documents(batch)
    except Exception as e:
        raise

def delete_document(user_id, document_id, group_id=None):
    """
    Delete a document from the user's documents in Cosmos DB
    and remove any associated blobs in storage whose metadata
    matches the user_id and document_id.
    """
    is_group = group_id is not None
    cosmos_container = cosmos_group_documents_container if is_group else cosmos_user_documents_container
    storage_account_container_name = (
        storage_account_group_documents_container_name
        if is_group else
        storage_account_user_documents_container_name
    )

    try:
        # 1. Verify the document is owned by this user
        document_item = cosmos_container.read_item(
            item=document_id,
            partition_key=document_id
        )
        if (document_item.get('user_id') != user_id) or (is_group and document_item.get('group_id') != group_id):
            raise Exception("Unauthorized access to document")

        # 2. Delete from Cosmos DB
        cosmos_container.delete_item(
            item=document_id,
            partition_key=document_id
        )

        # 3. Delete matching blobs from Azure Storage
        blob_service_client = CLIENTS.get("storage_account_office_docs_client")
        container_client = blob_service_client.get_container_client(
            storage_account_container_name
        )

        # List only blobs in "user_id/" prefix:
        prefix = f"{group_id}/" if is_group else f"{user_id}/"
        blob_list = container_client.list_blobs(name_starts_with=prefix)

        for blob_item in blob_list:
            # We need to retrieve the blob’s metadata to check document_id
            blob_client = container_client.get_blob_client(blob_item.name)
            properties = blob_client.get_blob_properties()
            blob_metadata = properties.metadata or {}

            # Compare metadata for user_id and document_id
            if not is_group:
                # User document - match only user_id and document_id
                if (
                    blob_metadata.get('user_id') == str(user_id) and
                    blob_metadata.get('document_id') == str(document_id)
                ):
                    container_client.delete_blob(blob_item.name)

            elif is_group:
                # Group document - match only group_id and document_id
                if (
                    blob_metadata.get('group_id') == str(group_id) and
                    blob_metadata.get('document_id') == str(document_id)
                ):
                    container_client.delete_blob(blob_item.name)

        return {"message": "Document and associated blobs deleted successfully."}

    except CosmosResourceNotFoundError:
        raise Exception("Document not found")
    except Exception as e:
        # You can raise or return a custom JSON error
        raise Exception(f"Error during delete: {str(e)}")



def delete_document_version_chunks(document_id, version, group_id=None):
    """Delete document chunks from Azure Cognitive Search index for a specific version."""
    is_group = group_id is not None
    search_client = CLIENTS["search_client_group"] if is_group else CLIENTS["search_client_user"]

    search_client.delete_documents(
        actions=[
            {"@search.action": "delete", "id": chunk['id']} for chunk in 
            search_client.search(
                search_text="*",
                filter=f"document_id eq '{document_id}' and version eq {version}",
                select="id"
            )
        ]
    )

def get_document_versions(user_id, document_id, group_id=None):
    """ Get all versions of a document for a user."""
    is_group = group_id is not None
    cosmos_container = cosmos_group_documents_container if is_group else cosmos_user_documents_container

    if is_group:
        query = """
            SELECT c.id, c.file_name, c.version, c.upload_date
            FROM c
            WHERE c.id = @document_id
                AND c.group_id = @group_id
            ORDER BY c.version DESC
        """
        parameters = [
            {"name": "@document_id", "value": document_id},
            {"name": "@group_id", "value": group_id}
        ]
    else:
        query = """
            SELECT c.id, c.file_name, c.version, c.upload_date
            FROM c
            WHERE c.id = @document_id 
                AND c.user_id = @user_id
            ORDER BY c.version DESC
        """
        parameters = [
            {"name": "@document_id", "value": document_id},
            {"name": "@user_id", "value": user_id}
        ]

    try:
        versions_results = list(
            cosmos_container.query_items(
                query=query, 
                parameters=parameters, 
                enable_cross_partition_query=True
            )
        )

        if not versions_results:
            return []
        return versions_results

    except Exception as e:
        return []
    
def detect_doc_type(document_id, user_id=None):
    """
    Check Cosmos to see if this doc belongs to the user's docs (has user_id)
    or the group's docs (has group_id).
    Returns one of: "user", "group", or None if not found.
    Optionally checks if user_id matches (for user docs).
    """

    try:
        doc_item = cosmos_user_documents_container.read_item(
            document_id, 
            partition_key=document_id
        )
        if user_id and doc_item.get('user_id') != user_id:
            pass
        else:
            return "personal", doc_item['user_id']
    except:
        pass

    try:
        group_doc_item = cosmos_group_documents_container.read_item(
            document_id, 
            partition_key=document_id
        )
        return "group", group_doc_item['group_id']
    except:
        pass

    return None

def process_metadata_extraction_background(document_id, user_id, group_id=None):
    """
    Background function that calls extract_document_metadata(...)
    and updates Cosmos DB accordingly.
    """
    is_group = group_id is not None

    try:
        # Log status: starting
        args = {
            "document_id": document_id,
            "user_id": user_id,
            "percentage_complete": 5,
            "status": "Metadata extraction started..."
        }

        if is_group:
            args["group_id"] = group_id

        update_document(**args)

        # Call your existing extraction function
        args = {
            "document_id": document_id,
            "user_id": user_id
        }

        if is_group:
            args["group_id"] = group_id

        metadata = extract_document_metadata(**args)


        if not metadata:
            # If it fails or returns nothing, log an error status and quit
            args = {
                "document_id": document_id,
                "user_id": user_id,
                "status": "Metadata extraction returned empty or failed"
            }

            if is_group:
                args["group_id"] = group_id

            update_document(**args)

            return

        # Persist the returned metadata fields back into Cosmos
        args_metadata = {
            "document_id": document_id,
            "user_id": user_id,
            "title": metadata.get('title'),
            "authors": metadata.get('authors'),
            "abstract": metadata.get('abstract'),
            "keywords": metadata.get('keywords'),
            "publication_date": metadata.get('publication_date'),
            "organization": metadata.get('organization')
        }

        if is_group:
            args_metadata["group_id"] = group_id

        update_document(**args_metadata)

        args_status = {
            "document_id": document_id,
            "user_id": user_id,
            "status": "Metadata extraction complete",
            "percentage_complete": 100
        }

        if is_group:
            args_status["group_id"] = group_id

        update_document(**args_status)

    except Exception as e:
        # Log any exceptions
        args = {
            "document_id": document_id,
            "user_id": user_id,
            "status": f"Metadata extraction failed: {str(e)}"
        }

        if is_group:
            args["group_id"] = group_id

        update_document(**args)

        
def extract_document_metadata(document_id, user_id, group_id=None):
    """
    Extract metadata from a document stored in Cosmos DB.
    This function is called in the background after the document is uploaded.
    It retrieves the document from Cosmos DB, extracts metadata, and performs
    content safety checks.
    """

    settings = get_settings()
    enable_gpt_apim = settings.get('enable_gpt_apim', False)
    enable_user_workspace = settings.get('enable_user_workspace', False)
    enable_group_workspaces = settings.get('enable_group_workspaces', False)

    is_group = group_id is not None
    cosmos_container = cosmos_group_documents_container if is_group else cosmos_user_documents_container
    id_key = "group_id" if is_group else "user_id"
    id_value = group_id if is_group else user_id

    add_file_task_to_file_processing_log(
        document_id=document_id, 
        user_id=group_id if is_group else user_id,
        content=f"Querying metadata for document {document_id} and user {user_id}"
    )
    
    # Example structure for reference
    meta_data_example = {
        "title": "Title here",
        "authors": ["Author 1", "Author 2"],
        "organization": "Organization or Unknown",
        "publication_date": "MM/YYYY or N/A",
        "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
        "abstract": "two sentence abstract"
    }
    
    # Pre-initialize metadata dictionary
    meta_data = {
        "title": "",
        "authors": [],
        "organization": "",
        "publication_date": "",
        "keywords": [],
        "abstract": ""
    }

    if is_group:
        query = """
            SELECT *
            FROM c
            WHERE c.id = @document_id
                AND c.group_id = @group_id
        """
        parameters = [
            {"name": "@document_id", "value": document_id},
            {"name": "@group_id", "value": group_id}
        ]
    else:
        query = """
            SELECT *
            FROM c
            WHERE c.id = @document_id 
                AND c.user_id = @user_id
        """
        parameters = [
            {"name": "@document_id", "value": document_id},
            {"name": "@user_id", "value": user_id}
        ]

    # --- Step 1: Retrieve document from Cosmos ---
    try:
        document_items = list(
            cosmos_container.query_items(
                query=query, 
                parameters=parameters, 
                enable_cross_partition_query=True
            )
        )

        args = {
            "document_id": document_id,
            "user_id": user_id,
            "status": f"Retrieved document items for document {document_id}"
        }

        if is_group:
            args["group_id"] = group_id

        update_document(**args)


        add_file_task_to_file_processing_log(
            document_id=document_id, 
            user_id=group_id if is_group else user_id,
            content=f"Retrieved document items for document {document_id}: {document_items}"
        )
    except Exception as e:
        add_file_task_to_file_processing_log(
            document_id=document_id, 
            user_id=group_id if is_group else user_id,
            content=f"Error querying document items for document {document_id}: {e}"
        )
        print(f"Error querying document items for document {document_id}: {e}")

    if not document_items:
        return None

    document_metadata = document_items[0]
    
    # --- Step 2: Populate meta_data from DB ---
    # Convert the DB fields to the correct structure
    if "title" in document_metadata:
        meta_data["title"] = document_metadata["title"]
    if "authors" in document_metadata:
        meta_data["authors"] = ensure_list(document_metadata["authors"])
    if "organization" in document_metadata:
        meta_data["organization"] = document_metadata["organization"]
    if "publication_date" in document_metadata:
        meta_data["publication_date"] = document_metadata["publication_date"]
    if "keywords" in document_metadata:
        meta_data["keywords"] = ensure_list(document_metadata["keywords"])
    if "abstract" in document_metadata:
        meta_data["abstract"] = document_metadata["abstract"]

    add_file_task_to_file_processing_log(
        document_id=document_id, 
        user_id=group_id if is_group else user_id,
        content=f"Extracted metadata for document {document_id}, metadata: {meta_data}"
    )

    args = {
        "document_id": document_id,
        "user_id": user_id,
        "status": f"Extracted metadata for document {document_id}"
    }

    if is_group:
        args["group_id"] = group_id

    update_document(**args)


    # --- Step 3: Content Safety Check (if enabled) ---
    if settings.get('enable_content_safety') and "content_safety_client" in CLIENTS:
        content_safety_client = CLIENTS["content_safety_client"]
        blocked = False
        block_reasons = []
        triggered_categories = []
        blocklist_matches = []

        try:
            request_obj = AnalyzeTextOptions(text=json.dumps(meta_data))
            cs_response = content_safety_client.analyze_text(request_obj)

            max_severity = 0
            for cat_result in cs_response.categories_analysis:
                triggered_categories.append({
                    "category": cat_result.category,
                    "severity": cat_result.severity
                })
                if cat_result.severity > max_severity:
                    max_severity = cat_result.severity

            if cs_response.blocklists_match:
                for match in cs_response.blocklists_match:
                    blocklist_matches.append({
                        "blocklistName": match.blocklist_name,
                        "blocklistItemId": match.blocklist_item_id,
                        "blocklistItemText": match.blocklist_item_text
                    })

            if max_severity >= 4:
                blocked = True
                block_reasons.append("Max severity >= 4")
            if blocklist_matches:
                blocked = True
                block_reasons.append("Blocklist match")
            
            if blocked:
                add_file_task_to_file_processing_log(
                    document_id=document_id, 
                    user_id=group_id if is_group else user_id,
                    content=f"Blocked document metadata: {document_metadata}, reasons: {block_reasons}"
                )
                print(f"Blocked document metadata: {document_metadata}\nReasons: {block_reasons}")
                return None

        except Exception as e:
            add_file_task_to_file_processing_log(
                document_id=document_id, 
                user_id=group_id if is_group else user_id,
                content=f"Error checking content safety for document metadata: {e}"
            )
            print(f"Error checking content safety for document metadata: {e}")

    # --- Step 4: Hybrid Search ---
    try:
        if enable_user_workspace or enable_group_workspaces:
            add_file_task_to_file_processing_log(
                document_id=document_id, 
                user_id=group_id if is_group else user_id,
                content=f"Processing Hybrid search for document {document_id} using json dump of metadata {json.dumps(meta_data)}"
            )

            args = {
                "document_id": document_id,
                "user_id": user_id,
                "status": f"Collecting document data to generate metadata from document: {document_id}"
            }

            if is_group:
                args["group_id"] = group_id

            update_document(**args)


            document_scope, scope_id = detect_doc_type(
                document_id, 
                user_id
            )

            if document_scope == "personal":
                search_results = hybrid_search(
                    json.dumps(meta_data), 
                    user_id, 
                    document_id=document_id, 
                    top_n=10, 
                    doc_scope=document_scope
                )
            elif document_scope == "group":
                search_results = hybrid_search(
                    json.dumps(meta_data), 
                    user_id, 
                    document_id=document_id,
                    top_n=10, 
                    doc_scope=document_scope, 
                    active_group_id=scope_id
                )

        else:
            search_results = "No Hybrid results"
    except Exception as e:
        add_file_task_to_file_processing_log(
            document_id=document_id, 
            user_id=group_id if is_group else user_id,
            content=f"Error processing Hybrid search for document {document_id}: {e}"
        )
        print(f"Error processing Hybrid search for document {document_id}: {e}")
        search_results = "No Hybrid results"

    # --- Step 5: Prepare GPT Client ---
    if enable_gpt_apim:
        # APIM-based GPT client
        gpt_model = settings.get('azure_apim_gpt_deployment')
        gpt_client = AzureOpenAI(
            api_version=settings.get('azure_apim_gpt_api_version'),
            azure_endpoint=settings.get('azure_apim_gpt_endpoint'),
            api_key=settings.get('azure_apim_gpt_subscription_key')
        )
    else:
        # Standard Azure OpenAI approach
        if settings.get('azure_openai_gpt_authentication_type') == 'managed_identity':
            token_provider = get_bearer_token_provider(
                DefaultAzureCredential(), 
                "https://cognitiveservices.azure.com/.default"
            )
            gpt_client = AzureOpenAI(
                api_version=settings.get('azure_openai_gpt_api_version'),
                azure_endpoint=settings.get('azure_openai_gpt_endpoint'),
                azure_ad_token_provider=token_provider
            )
        else:
            gpt_client = AzureOpenAI(
                api_version=settings.get('azure_openai_gpt_api_version'),
                azure_endpoint=settings.get('azure_openai_gpt_endpoint'),
                api_key=settings.get('azure_openai_gpt_key')
            )

        # Retrieve the selected deployment name if provided
        gpt_model_obj = settings.get('gpt_model', {})
        if gpt_model_obj and gpt_model_obj.get('selected'):
            selected_gpt_model = gpt_model_obj['selected'][0]
            gpt_model = selected_gpt_model['deploymentName']

    # --- Step 6: GPT Prompt and JSON Parsing ---
    try:
        add_file_task_to_file_processing_log(
            document_id=document_id, 
            user_id=group_id if is_group else user_id,
            content=f"Sending search results to AI to generate metadata {document_id}"
        )
        messages = [
            {
                "role": "system", 
                "content": "You are an AI assistant that extracts metadata. Return valid JSON."
            },
            {
                "role": "user", 
                "content": (
                    f"Search results from AI search index:\n{search_results}\n\n"
                    f"Current known metadata:\n{json.dumps(meta_data, indent=2)}\n\n"
                    f"Desired metadata structure:\n{json.dumps(meta_data_example, indent=2)}\n\n"
                    f"Please attempt to fill in any missing, or empty values."
                    f"If generating keywords, please create 5-10 keywords."
                    f"Return only JSON."
                )
            }
        ]

        response = gpt_client.chat.completions.create(
            model=gpt_model, 
            messages=messages
        )
        
    except Exception as e:
        add_file_task_to_file_processing_log(
            document_id=document_id, 
            user_id=group_id if is_group else user_id,
            content=f"Error processing GPT request for document {document_id}: {e}"
        )
        print(f"Error processing GPT request for document {document_id}: {e}")
        return meta_data  # Return what we have so far
    
    if not response:
        return meta_data  # or None, depending on your logic

    response_content = response.choices[0].message.content
    add_file_task_to_file_processing_log(
        document_id=document_id, 
        user_id=group_id if is_group else user_id,
        content=f"GPT response for document {document_id}: {response_content}"
    )

    # --- Step 7: Clean and parse the GPT JSON output ---
    try:
        add_file_task_to_file_processing_log(
            document_id=document_id, 
            user_id=group_id if is_group else user_id,
            content=f"Decoding JSON from GPT response for document {document_id}"
        )

        cleaned_str = clean_json_codeFence(response_content)

        add_file_task_to_file_processing_log(
            document_id=document_id, 
            user_id=group_id if is_group else user_id, 
            content=f"Cleaned JSON from GPT response for document {document_id}: {cleaned_str}"
        )

        gpt_output = json.loads(cleaned_str)

        add_file_task_to_file_processing_log(
            document_id=document_id, 
            user_id=group_id if is_group else user_id,
            content=f"Decoded JSON from GPT response for document {document_id}: {gpt_output}"
        )

        # Ensure authors and keywords are always lists
        gpt_output["authors"] = ensure_list(gpt_output.get("authors", []))
        gpt_output["keywords"] = ensure_list(gpt_output.get("keywords", []))

    except (json.JSONDecodeError, TypeError) as e:
        add_file_task_to_file_processing_log(
            document_id=document_id, 
            user_id=group_id if is_group else user_id,
            content=f"Error decoding JSON from GPT response for document {document_id}: {e}"
        )
        print(f"Error decoding JSON from response: {e}")
        return meta_data  # or None

    # --- Step 8: Merge GPT Output with Existing Metadata ---
    #
    # If the DB’s version is effectively empty/worthless, then overwrite 
    # with the GPT’s version if GPT has something non-empty.
    # Otherwise keep the DB’s version.
    #

    # Title
    if is_effectively_empty(meta_data["title"]):
        meta_data["title"] = gpt_output.get("title", meta_data["title"])

    # Authors
    if is_effectively_empty(meta_data["authors"]):
        # If GPT has no authors either, fallback to ["Unknown"]
        meta_data["authors"] = gpt_output["authors"] or ["Unknown"]

    # Organization
    if is_effectively_empty(meta_data["organization"]):
        meta_data["organization"] = gpt_output.get("organization", meta_data["organization"])

    # Publication Date
    if is_effectively_empty(meta_data["publication_date"]):
        meta_data["publication_date"] = gpt_output.get("publication_date", meta_data["publication_date"])

    # Keywords
    if is_effectively_empty(meta_data["keywords"]):
        meta_data["keywords"] = gpt_output["keywords"]

    # Abstract
    if is_effectively_empty(meta_data["abstract"]):
        meta_data["abstract"] = gpt_output.get("abstract", meta_data["abstract"])

    add_file_task_to_file_processing_log(
        document_id=document_id, 
        user_id=group_id if is_group else user_id,
        content=f"Final metadata for document {document_id}: {meta_data}"
    )

    args = {
        "document_id": document_id,
        "user_id": user_id,
        "status": f"Metadata generated for document {document_id}"
    }

    if is_group:
        args["group_id"] = group_id

    update_document(**args)


    return meta_data


def clean_json_codeFence(response_content: str) -> str:
    """
    Removes leading and trailing triple-backticks (```) or ```json
    from a string so that it can be parsed as JSON.
    """
    # Remove any ```json or ``` (with optional whitespace/newlines) at the start
    cleaned = re.sub(r"(?s)^```(?:json)?\s*", "", response_content.strip())
    # Remove trailing ``` on its own line or at the end
    cleaned = re.sub(r"```$", "", cleaned.strip())
    return cleaned.strip()

def ensure_list(value, delimiters=r"[;,]"):
    """
    Ensures the provided value is returned as a list of strings.
    - If `value` is already a list, it is returned as-is.
    - If `value` is a string, it is split on the given delimiters
      (default: commas and semicolons).
    - Otherwise, return an empty list.
    """
    if isinstance(value, list):
        return value
    elif isinstance(value, str):
        # Split on the given delimiters (commas, semicolons, etc.)
        items = re.split(delimiters, value)
        # Strip whitespace and remove empty strings
        items = [item.strip() for item in items if item.strip()]
        return items
    else:
        return []

def is_effectively_empty(value):
    """
    Returns True if the value is 'worthless' or empty.
    - For a string: empty or just whitespace
    - For a list: empty OR all empty strings
    - For None: obviously empty
    - For other types: not considered here, but you can extend as needed
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()  # '' or whitespace is empty
    if isinstance(value, list):
        # Example: [] or [''] or [' ', ''] is empty
        # If *every* item is effectively empty as a string, treat as empty
        if len(value) == 0:
            return True
        return all(not item.strip() for item in value if isinstance(item, str))
    return False

# --- Helper function to estimate word count ---
def estimate_word_count(text):
    """Estimates the number of words in a string."""
    if not text:
        return 0
    return len(text.split())

# --- Helper function for uploading to blob storage ---
def upload_to_blob(temp_file_path, user_id, document_id, blob_filename, update_callback, group_id=None):
    """Uploads the file to Azure Blob Storage."""

    is_group = group_id is not None
    storage_account_container_name = (
        storage_account_group_documents_container_name
        if is_group else
        storage_account_user_documents_container_name
    )

    try:
        blob_path = f"{group_id}/{blob_filename}" if is_group else f"{user_id}/{blob_filename}"

        blob_service_client = CLIENTS.get("storage_account_office_docs_client")
        if not blob_service_client:
            raise Exception("Blob service client not available or not configured.")

        blob_client = blob_service_client.get_blob_client(
            container=storage_account_container_name,
            blob=blob_path
        )

        metadata = {
            "document_id": str(document_id),
            "group_id": str(group_id) if is_group else None,
            "user_id": str(user_id) if not is_group else None
        }

        metadata = {k: v for k, v in metadata.items() if v is not None}

        update_callback(status=f"Uploading {blob_filename} to Blob Storage...")

        with open(temp_file_path, "rb") as f:
            blob_client.upload_blob(f, overwrite=True, metadata=metadata)

        print(f"Successfully uploaded {blob_filename} to blob storage at {blob_path}")
        return blob_path

    except Exception as e:
        print(f"Error uploading {blob_filename} to Blob Storage: {str(e)}")
        raise Exception(f"Error uploading {blob_filename} to Blob Storage: {str(e)}")


# --- Helper function to process TXT files ---
def process_txt(document_id, user_id, temp_file_path, original_filename, enable_enhanced_citations, update_callback, group_id=None):
    """Processes plain text files."""
    is_group = group_id is not None

    update_callback(status="Processing TXT file...")
    total_chunks_saved = 0
    target_words_per_chunk = 400

    if enable_enhanced_citations:
        args = {
            "temp_file_path": temp_file_path,
            "user_id": user_id,
            "document_id": document_id,
            "blob_filename": original_filename,
            "update_callback": update_callback
        }

        if is_group:
            args["group_id"] = group_id

        upload_to_blob(**args)

    try:
        with open(temp_file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        words = content.split()
        num_words = len(words)
        num_chunks_estimated = math.ceil(num_words / target_words_per_chunk)
        update_callback(number_of_pages=num_chunks_estimated) # Use number_of_pages for chunk count

        for i in range(0, num_words, target_words_per_chunk):
            chunk_words = words[i : i + target_words_per_chunk]
            chunk_content = " ".join(chunk_words)
            chunk_index = (i // target_words_per_chunk) + 1

            if chunk_content.strip():
                update_callback(
                    current_file_chunk=chunk_index,
                    status=f"Saving chunk {chunk_index}/{num_chunks_estimated}..."
                )
                args = {
                    "page_text_content": chunk_content,
                    "page_number": chunk_index,
                    "file_name": original_filename,
                    "user_id": user_id,
                    "document_id": document_id
                }

                if is_group:
                    args["group_id"] = group_id

                save_chunks(**args)
                total_chunks_saved += 1

    except Exception as e:
        raise Exception(f"Failed processing TXT file {original_filename}: {e}")

    return total_chunks_saved

# --- Helper function to process HTML files ---
def process_html(document_id, user_id, temp_file_path, original_filename, enable_enhanced_citations, update_callback, group_id=None):
    """Processes HTML files."""
    is_group = group_id is not None

    update_callback(status="Processing HTML file...")
    total_chunks_saved = 0
    target_chunk_words = 1200 # Target size based on requirement
    min_chunk_words = 600 # Minimum size based on requirement

    if enable_enhanced_citations:
        args = {
            "temp_file_path": temp_file_path,
            "user_id": user_id,
            "document_id": document_id,
            "blob_filename": original_filename,
            "update_callback": update_callback
        }

        if is_group:
            args["group_id"] = group_id

        upload_to_blob(**args)

    try:
        # --- CHANGE HERE: Open in binary mode ('rb') ---
        # Let BeautifulSoup handle the decoding based on meta tags or detection
        with open(temp_file_path, 'rb') as f:
            # --- CHANGE HERE: Pass the file object directly to BeautifulSoup ---
            soup = BeautifulSoup(f, 'lxml') # or 'html.parser' if lxml not installed

        # TODO: Advanced Table Handling - (Comment remains valid)
        # ...

        # Now process the soup object as before
        text_content = soup.get_text(separator=" ", strip=True)

        # Remainder of the chunking logic stays the same...
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=target_chunk_words * 6, # Approximation
            chunk_overlap=target_chunk_words * 0.1 * 6, # 10% overlap approx
            length_function=len,
            is_separator_regex=False,
        )

        initial_chunks = text_splitter.split_text(text_content)

        # Post-processing: Merge small chunks
        final_chunks = []
        buffer_chunk = ""
        for i, chunk in enumerate(initial_chunks):
            current_chunk_text = buffer_chunk + chunk
            current_word_count = estimate_word_count(current_chunk_text)

            if current_word_count >= min_chunk_words or i == len(initial_chunks) - 1:
                if current_chunk_text.strip():
                    final_chunks.append(current_chunk_text)
                buffer_chunk = "" # Reset buffer
            else:
                # Chunk is too small, add to buffer and continue to next chunk
                buffer_chunk = current_chunk_text + " " # Add space between merged chunks

        num_chunks_final = len(final_chunks)
        update_callback(number_of_pages=num_chunks_final) # Use number_of_pages for chunk count

        for idx, chunk_content in enumerate(final_chunks, start=1):
            update_callback(
                current_file_chunk=idx,
                status=f"Saving chunk {idx}/{num_chunks_final}..."
            )
            args = {
                "page_text_content": chunk_content,
                "page_number": idx,
                "file_name": original_filename,
                "user_id": user_id,
                "document_id": document_id
            }

            if is_group:
                args["group_id"] = group_id

            save_chunks(**args)
            total_chunks_saved += 1

    except Exception as e:
        # Catch potential BeautifulSoup errors too
        raise Exception(f"Failed processing HTML file {original_filename}: {e}")

    return total_chunks_saved


# --- Helper function to process Markdown files ---
def process_md(document_id, user_id, temp_file_path, original_filename, enable_enhanced_citations, update_callback, group_id=None):
    """Processes Markdown files."""
    is_group = group_id is not None

    update_callback(status="Processing Markdown file...")
    total_chunks_saved = 0
    target_chunk_words = 1200 # Target size based on requirement
    min_chunk_words = 600 # Minimum size based on requirement

    if enable_enhanced_citations:
        args = {
            "temp_file_path": temp_file_path,
            "user_id": user_id,
            "document_id": document_id,
            "blob_filename": original_filename,
            "update_callback": update_callback
        }

        if is_group:
            args["group_id"] = group_id

        upload_to_blob(**args)

    try:
        with open(temp_file_path, 'r', encoding='utf-8') as f:
            md_content = f.read()

        headers_to_split_on = [
            ("#", "Header 1"),
            ("##", "Header 2"),
            ("###", "Header 3"),
            ("####", "Header 4"),
            ("#####", "Header 5"),
        ]

        # Use MarkdownHeaderTextSplitter first
        md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on, return_each_line=False)
        md_header_splits = md_splitter.split_text(md_content)

        initial_chunks_content = [doc.page_content for doc in md_header_splits]

        # TODO: Advanced Table/Code Block Handling:
        # - Table header replication requires identifying markdown tables (`|---|`),
        #   detecting splits, and injecting headers.
        # - Code block wrapping requires detecting ``` blocks split across chunks and
        #   adding start/end fences.
        # This requires complex regex or stateful parsing during/after splitting.
        # For now, we focus on the text splitting and minimum size merging.

        # Post-processing: Merge small chunks based on word count
        final_chunks = []
        buffer_chunk = ""
        for i, chunk_text in enumerate(initial_chunks_content):
            current_chunk_text = buffer_chunk + chunk_text # Combine with buffer first
            current_word_count = estimate_word_count(current_chunk_text)

            # Merge if current chunk alone (without buffer) is too small, UNLESS it's the last one
            # Or, more simply, accumulate until the buffer meets the minimum size
            if current_word_count >= min_chunk_words or i == len(initial_chunks_content) - 1:
                 # If the combined chunk meets min size OR it's the last chunk, save it
                if current_chunk_text.strip():
                     final_chunks.append(current_chunk_text)
                buffer_chunk = "" # Reset buffer
            else:
                # Accumulate in buffer if below min size and not the last chunk
                buffer_chunk = current_chunk_text + "\n\n" # Add separator when buffering

        num_chunks_final = len(final_chunks)
        update_callback(number_of_pages=num_chunks_final)

        for idx, chunk_content in enumerate(final_chunks, start=1):
            update_callback(
                current_file_chunk=idx,
                status=f"Saving chunk {idx}/{num_chunks_final}..."
            )
            args = {
                "page_text_content": chunk_content,
                "page_number": idx,
                "file_name": original_filename,
                "user_id": user_id,
                "document_id": document_id
            }

            if is_group:
                args["group_id"] = group_id

            save_chunks(**args)
            total_chunks_saved += 1

    except Exception as e:
        raise Exception(f"Failed processing Markdown file {original_filename}: {e}")

    return total_chunks_saved


# --- Helper function to process JSON files ---
def process_json(document_id, user_id, temp_file_path, original_filename, enable_enhanced_citations, update_callback, group_id=None):
    """Processes JSON files using RecursiveJsonSplitter."""
    is_group = group_id is not None

    update_callback(status="Processing JSON file...")
    total_chunks_saved = 0
    # Reflects character count limit for the splitter
    max_chunk_size_chars = 600 # As per original requirement

    if enable_enhanced_citations:
        args = {
            "temp_file_path": temp_file_path,
            "user_id": user_id,
            "document_id": document_id,
            "blob_filename": original_filename,
            "update_callback": update_callback
        }

        if is_group:
            args["group_id"] = group_id

        upload_to_blob(**args)


    try:
        # Load the JSON data first to ensure it's valid
        try:
            with open(temp_file_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
        except json.JSONDecodeError as e:
             raise Exception(f"Invalid JSON structure in {original_filename}: {e}")
        except Exception as e: # Catch other file reading errors
             raise Exception(f"Error reading JSON file {original_filename}: {e}")

        # Initialize the splitter - convert_lists does NOT go here
        json_splitter = RecursiveJsonSplitter(max_chunk_size=max_chunk_size_chars)

        # Perform the splitting using split_json
        # --- CHANGE HERE: Add convert_lists=True to the splitting method call ---
        # This tells the splitter to handle lists by converting them internally during splitting
        final_json_chunks_structured = json_splitter.split_json(
            json_data=json_data,
            convert_lists=True # Use the feature here as per documentation
        )

        # Convert each structured chunk (which are dicts/lists) back into a JSON string for saving
        # Using ensure_ascii=False is safer for preserving original characters if any non-ASCII exist
        final_chunks_text = [json.dumps(chunk, ensure_ascii=False) for chunk in final_json_chunks_structured]

        initial_chunk_count = len(final_chunks_text)
        update_callback(number_of_pages=initial_chunk_count) # Initial estimate

        for idx, chunk_content in enumerate(final_chunks_text, start=1):
            # Skip potentially empty or trivial chunks (e.g., "{}" or "[]" or just "")
            # Stripping allows checking for empty strings potentially generated
            if not chunk_content or chunk_content == '""' or chunk_content == '{}' or chunk_content == '[]' or not chunk_content.strip('{}[]" '):
                print(f"Skipping empty or trivial JSON chunk {idx}/{initial_chunk_count}")
                continue # Skip saving this chunk

            update_callback(
                current_file_chunk=idx, # Use original index for progress display
                # Keep number_of_pages as initial estimate during saving loop
                status=f"Saving chunk {idx}/{initial_chunk_count}..."
            )
            args = {
                "page_text_content": chunk_content,
                "page_number": total_chunks_saved + 1,
                "file_name": original_filename,
                "user_id": user_id,
                "document_id": document_id
            }

            if is_group:
                args["group_id"] = group_id

            save_chunks(**args)
            total_chunks_saved += 1 # Increment only when a chunk is actually saved

        # Final update with the actual number of chunks saved
        if total_chunks_saved != initial_chunk_count:
            update_callback(number_of_pages=total_chunks_saved)
            print(f"Adjusted final chunk count from {initial_chunk_count} to {total_chunks_saved} after skipping empty chunks.")


    except Exception as e:
        # Catch errors during loading, splitting, or saving
        # Avoid catching the specific JSONDecodeError again if already handled
        if not isinstance(e, json.JSONDecodeError):
             print(f"Error during JSON processing for {original_filename}: {type(e).__name__}: {e}")
        # Re-raise wrapped exception for the main handler
        raise Exception(f"Failed processing JSON file {original_filename}: {e}")

    # Return the count of chunks actually saved
    return total_chunks_saved


# --- Helper function to process a single Tabular sheet (CSV or Excel tab) ---
def process_single_tabular_sheet(df, document_id, user_id, effective_filename, update_callback, group_id=None):
    """Chunks a pandas DataFrame from a CSV or Excel sheet."""
    is_group = group_id is not None

    total_chunks_saved = 0
    target_chunk_size_chars = 800 # Requirement: "800 size chunk" (assuming characters)

    if df.empty:
        print(f"Skipping empty sheet/file: {effective_filename}")
        return 0

    # Get header
    header = df.columns.tolist()
    header_string = ",".join(map(str, header)) + "\n" # CSV representation of header

    # Prepare rows as strings (e.g., CSV format)
    rows_as_strings = []
    for _, row in df.iterrows():
        # Convert row to string, handling potential NaNs and types
        row_string = ",".join(map(lambda x: str(x) if pd.notna(x) else "", row.tolist())) + "\n"
        rows_as_strings.append(row_string)

    # Chunk rows based on character count
    final_chunks_content = []
    current_chunk_rows = []
    current_chunk_char_count = 0

    for row_str in rows_as_strings:
        row_len = len(row_str)
        # If adding the current row exceeds the limit AND the chunk already has content
        if current_chunk_char_count + row_len > target_chunk_size_chars and current_chunk_rows:
            # Finalize the current chunk
            final_chunks_content.append("".join(current_chunk_rows))
            # Start a new chunk with the current row
            current_chunk_rows = [row_str]
            current_chunk_char_count = row_len
        else:
            # Add row to the current chunk
            current_chunk_rows.append(row_str)
            current_chunk_char_count += row_len

    # Add the last remaining chunk if it has content
    if current_chunk_rows:
        final_chunks_content.append("".join(current_chunk_rows))

    num_chunks_final = len(final_chunks_content)
    # Update total pages estimate once at the start of processing this sheet
    # Note: This might overwrite previous updates if called multiple times for excel sheets.
    # Consider accumulating page count in the caller if needed.
    update_callback(number_of_pages=num_chunks_final)

    # Save chunks, prepending the header to each
    for idx, chunk_rows_content in enumerate(final_chunks_content, start=1):
        # Prepend header - header length does not count towards chunk size limit
        chunk_with_header = header_string + chunk_rows_content

        update_callback(
            current_file_chunk=idx,
            status=f"Saving chunk {idx}/{num_chunks_final} from {effective_filename}..."
        )

        args = {
            "page_text_content": chunk_with_header,
            "page_number": idx,
            "file_name": effective_filename,
            "user_id": user_id,
            "document_id": document_id
        }

        if is_group:
            args["group_id"] = group_id

        save_chunks(**args)
        total_chunks_saved += 1

    return total_chunks_saved


# --- Helper function to process Tabular files (CSV, XLSX, XLS) ---
def process_tabular(document_id, user_id, temp_file_path, original_filename, file_ext, enable_enhanced_citations, update_callback, group_id=None):
    """Processes CSV, XLSX, or XLS files using pandas."""
    is_group = group_id is not None

    update_callback(status=f"Processing Tabular file ({file_ext})...")
    total_chunks_saved = 0

    # Upload the original file once if enhanced citations are enabled
    if enable_enhanced_citations:
        args = {
            "temp_file_path": temp_file_path,
            "user_id": user_id,
            "document_id": document_id,
            "blob_filename": original_filename,
            "update_callback": update_callback
        }

        if is_group:
            args["group_id"] = group_id

        upload_to_blob(**args)

    try:
        if file_ext == '.csv':
            # Process CSV
             # Read CSV, attempt to infer header, keep data as string initially
            df = pd.read_csv(
                temp_file_path, 
                keep_default_na=False, 
                dtype=str
            )
            args = {
                "df": df,
                "document_id": document_id,
                "user_id": user_id,
                "file_name": original_filename,
                "update_callback": update_callback
            }

            if is_group:
                args["group_id"] = group_id

            total_chunks_saved = process_single_tabular_sheet(**args)

        elif file_ext in ('.xlsx', '.xls'):
            # Process Excel (potentially multiple sheets)
            excel_file = pd.ExcelFile(
                temp_file_path, 
                engine='openpyxl' if file_ext == '.xlsx' else 'xlrd'
            )
            sheet_names = excel_file.sheet_names
            base_name, ext = os.path.splitext(original_filename)

            accumulated_total_chunks = 0
            for sheet_name in sheet_names:
                update_callback(status=f"Processing sheet '{sheet_name}'...")
                # Read specific sheet, get values (not formulas), keep data as string
                # Note: pandas typically reads values, not formulas by default.
                df = excel_file.parse(sheet_name, keep_default_na=False, dtype=str)

                # Create effective filename for this sheet
                effective_filename = f"{base_name}-{sheet_name}{ext}" if len(sheet_names) > 1 else original_filename

                args = {
                    "df": df,
                    "document_id": document_id,
                    "user_id": user_id,
                    "file_name": effective_filename,
                    "update_callback": update_callback
                }

                if is_group:
                    args["group_id"] = group_id

                chunks_from_sheet = process_single_tabular_sheet(**args)

                accumulated_total_chunks += chunks_from_sheet

            total_chunks_saved = accumulated_total_chunks # Total across all sheets


    except pd.errors.EmptyDataError:
        print(f"Warning: Tabular file or sheet is empty: {original_filename}")
        update_callback(status=f"Warning: File/sheet is empty - {original_filename}", number_of_pages=0)
    except Exception as e:
        raise Exception(f"Failed processing Tabular file {original_filename}: {e}")

    return total_chunks_saved


# --- Helper function for DI-supported types (PDF, DOCX, PPT, Image) ---
# This function encapsulates the original logic for these file types
def process_di_document(document_id, user_id, temp_file_path, original_filename, file_ext, enable_enhanced_citations, update_callback, group_id=None):
    """Processes documents supported by Azure Document Intelligence (PDF, Word, PPT, Image)."""
    is_group = group_id is not None
    
    # --- Extracted Metadata logic ---
    doc_title, doc_author, doc_subject, doc_keywords = '', '', None, None
    doc_authors_list = []
    page_count = 0 # For PDF pre-check

    is_pdf = file_ext == '.pdf'
    is_word = file_ext in ('.docx', '.doc')
    is_ppt = file_ext in ('.pptx', '.ppt')
    is_image = file_ext in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.heif')

    try:
        if is_pdf:
            doc_title, doc_author, doc_subject, doc_keywords = extract_pdf_metadata(temp_file_path)
            doc_authors_list = parse_authors(doc_author)
            page_count = get_pdf_page_count(temp_file_path)
        elif is_word:
            doc_title, doc_author = extract_docx_metadata(temp_file_path)
            doc_authors_list = parse_authors(doc_author)
        # PPT and Image metadata extraction might be added here if needed/possible

        update_fields = {'status': "Extracted initial metadata"}
        if doc_title: update_fields['title'] = doc_title
        if doc_authors_list: update_fields['authors'] = doc_authors_list
        elif doc_author: update_fields['authors'] = [doc_author]
        if doc_subject: update_fields['abstract'] = doc_subject
        if doc_keywords: update_fields['keywords'] = doc_keywords
        update_callback(**update_fields)

    except Exception as e:
        print(f"Warning: Failed to extract initial metadata for {original_filename}: {e}")
        # Continue processing even if metadata fails

    # --- DI Processing Logic ---
    settings = get_settings() # Assuming get_settings is accessible
    di_limit_bytes = 500 * 1024 * 1024
    di_page_limit = 2000
    file_size = os.path.getsize(temp_file_path)

    file_paths_to_process = [temp_file_path]
    needs_pdf_file_chunking = False
    use_enhanced_citations_di = False # Specific flag for DI types

    if enable_enhanced_citations:
        # Enhanced citations involve blob link for PDF, PPT, Word, Image in this flow
        use_enhanced_citations_di = True
        update_callback(enhanced_citations=True, status=f"Enhanced citations enabled for {file_ext}")
        # Check if PDF needs *file-level* chunking before DI/Upload
        if is_pdf and (file_size > di_limit_bytes or (page_count > 0 and page_count > di_page_limit)):
            needs_pdf_file_chunking = True
    else:
        update_callback(enhanced_citations=False, status="Enhanced citations disabled")

    if needs_pdf_file_chunking:
        try:
            update_callback(status="Chunking large PDF file...")
            pdf_chunk_max_pages = di_page_limit // 4 if di_page_limit > 4 else 500
            file_paths_to_process = chunk_pdf(temp_file_path, max_pages=pdf_chunk_max_pages)
            if not file_paths_to_process:
                raise Exception("PDF chunking failed to produce output files.")
            if os.path.exists(temp_file_path): os.remove(temp_file_path) # Remove original large PDF
            print(f"Successfully chunked large PDF into {len(file_paths_to_process)} files.")
        except Exception as e:
            raise Exception(f"Failed to chunk PDF file: {str(e)}")

    num_file_chunks = len(file_paths_to_process)
    update_callback(num_file_chunks=num_file_chunks, status=f"Processing {original_filename} in {num_file_chunks} file chunk(s)")

    total_final_chunks_processed = 0
    for idx, chunk_path in enumerate(file_paths_to_process, start=1):
        chunk_base_name, chunk_ext_loop = os.path.splitext(original_filename)
        chunk_effective_filename = original_filename
        if num_file_chunks > 1:
            chunk_effective_filename = f"{chunk_base_name}_chunk_{idx}{chunk_ext_loop}"
        print(f"Processing DI file chunk {idx}/{num_file_chunks}: {chunk_effective_filename}")

        update_callback(status=f"Processing file chunk {idx}/{num_file_chunks}: {chunk_effective_filename}")

        # Upload to Blob (if enhanced citations enabled for these types)
        if use_enhanced_citations_di:
            args = {
                "temp_file_path": temp_file_path,
                "user_id": user_id,
                "document_id": document_id,
                "blob_filename": chunk_effective_filename,
                "update_callback": update_callback
            }

            if is_group:
                args["group_id"] = group_id

            upload_to_blob(**args)

        # Send chunk to Azure DI
        update_callback(status=f"Sending {chunk_effective_filename} to Azure Document Intelligence...")
        di_extracted_pages = []
        try:
            di_extracted_pages = extract_content_with_azure_di(chunk_path)
            num_di_pages = len(di_extracted_pages)
            conceptual_pages = num_di_pages if not is_image else 1 # Image is one conceptual item

            if not di_extracted_pages and not is_image:
                print(f"Warning: Azure DI returned no content pages for {chunk_effective_filename}.")
                status_msg = f"Azure DI found no content in {chunk_effective_filename}."
                # Update page count to 0 if nothing found, otherwise keep previous estimate or conceptual count
                update_callback(number_of_pages=0 if idx == num_file_chunks else conceptual_pages, status=status_msg)
            elif not di_extracted_pages and is_image:
                print(f"Info: Azure DI processed image {chunk_effective_filename}, but extracted no text.")
                update_callback(number_of_pages=conceptual_pages, status=f"Processed image {chunk_effective_filename} (no text found).")
            else:
                 update_callback(number_of_pages=conceptual_pages, status=f"Received {num_di_pages} content page(s)/slide(s) from Azure DI for {chunk_effective_filename}.")

        except Exception as e:
            raise Exception(f"Error extracting content from {chunk_effective_filename} with Azure DI: {str(e)}")

        # Content Chunking Strategy (Word needs specific handling)
        final_chunks_to_save = []
        if is_word:
            update_callback(status=f"Chunking Word content from {chunk_effective_filename}...")
            try:
                final_chunks_to_save = chunk_word_file_into_pages(di_pages=di_extracted_pages)
                num_final_chunks = len(final_chunks_to_save)
                # Update number_of_pages again for Word to reflect final chunk count
                update_callback(number_of_pages=num_final_chunks, status=f"Created {num_final_chunks} content chunks for {chunk_effective_filename}.")
            except Exception as e:
                 raise Exception(f"Error chunking Word content for {chunk_effective_filename}: {str(e)}")
        elif is_pdf or is_ppt:
            final_chunks_to_save = di_extracted_pages # Use DI pages/slides directly
        elif is_image:
            if di_extracted_pages:
                 if 'page_number' not in di_extracted_pages[0]: di_extracted_pages[0]['page_number'] = 1
                 final_chunks_to_save = di_extracted_pages
            else: final_chunks_to_save = [] # No text extracted

        # Save Final Chunks to Search Index
        num_final_chunks = len(final_chunks_to_save)
        if not final_chunks_to_save:
            print(f"Info: No final content chunks to save for {chunk_effective_filename}.")
        else:
            update_callback(status=f"Saving {num_final_chunks} content chunk(s) for {chunk_effective_filename}...")
            args = {
                "document_id": document_id,
                "user_id": user_id
            }

            if is_group:
                args["group_id"] = group_id

            doc_metadata_temp = get_document_metadata(**args)

            estimated_total_items = doc_metadata_temp.get('number_of_pages', num_final_chunks) if doc_metadata_temp else num_final_chunks

            try:
                for i, chunk_data in enumerate(final_chunks_to_save):
                    chunk_index = chunk_data.get("page_number", i + 1) # Ensure page number exists
                    chunk_content = chunk_data.get("content", "")

                    if not chunk_content.strip():
                        print(f"Skipping empty chunk index {chunk_index} for {chunk_effective_filename}.")
                        continue

                    update_callback(
                        current_file_chunk=int(chunk_index),
                        number_of_pages=estimated_total_items,
                        status=f"Saving page/chunk {chunk_index}/{estimated_total_items} of {chunk_effective_filename}..."
                    )
                    
                    args = {
                        "page_text_content": chunk_content,
                        "page_number": chunk_index,
                        "file_name": chunk_effective_filename,
                        "user_id": user_id,
                        "document_id": document_id
                    }

                    if is_group:
                        args["group_id"] = group_id

                    save_chunks(**args)

                    total_final_chunks_processed += 1
                print(f"Saved {num_final_chunks} content chunk(s) from {chunk_effective_filename}.")
            except Exception as e:
                raise Exception(f"Error saving extracted content chunk index {chunk_index} for {chunk_effective_filename}: {repr(e)}\nTraceback:\n{traceback.format_exc()}")

        # Clean up local file chunk (if it's not the original temp file)
        if chunk_path != temp_file_path and os.path.exists(chunk_path):
            try:
                os.remove(chunk_path)
                print(f"Cleaned up temporary chunk file: {chunk_path}")
            except Exception as cleanup_e:
                print(f"Warning: Failed to clean up temp chunk file {chunk_path}: {cleanup_e}")

    # --- Final Metadata Extraction (Optional, moved outside loop) ---
    settings = get_settings() # Re-get in case it changed? Or pass it down.
    enable_extract_meta_data = settings.get('enable_extract_meta_data')
    if enable_extract_meta_data and total_final_chunks_processed > 0:
        try:
            update_callback(status="Extracting final metadata...")
            args = {
                "document_id": document_id,
                "user_id": user_id
            }

            if is_group:
                args["group_id"] = group_id

            document_metadata = extract_document_metadata(**args)

            update_fields = {k: v for k, v in document_metadata.items() if v is not None and v != ""}
            if update_fields:
                 update_fields['status'] = "Final metadata extracted"
                 update_callback(**update_fields)
            else:
                 update_callback(status="Final metadata extraction yielded no new info")
        except Exception as e:
            print(f"Warning: Error extracting final metadata for {document_id}: {str(e)}")
            # Don't fail the whole process, just update status
            update_callback(status=f"Processing complete (metadata extraction warning)")

    return total_final_chunks_processed

def process_document_upload_background(document_id, user_id, temp_file_path, original_filename, group_id=None):
    """
    Main background task dispatcher for document processing.
    Handles various file types with specific chunking and processing logic.
    Integrates enhanced citations (blob upload) for all supported types.
    """
    is_group = group_id is not None
    settings = get_settings()
    enable_enhanced_citations = settings.get('enable_enhanced_citations', False) # Default to False if missing
    enable_extract_meta_data = settings.get('enable_extract_meta_data', False) # Used by DI flow
    max_file_size_bytes = settings.get('max_file_size_mb', 16) * 1024 * 1024

    # --- Define update_document callback wrapper ---
    # This makes it easier to pass the update function to helpers without repeating args
    def update_doc_callback(**kwargs):
        args = {
            "document_id": document_id,
            "user_id": user_id,
            **kwargs  # includes any dynamic update fields
        }

        if is_group:
            args["group_id"] = group_id

        update_document(**args)


    total_chunks_saved = 0
    file_ext = '' # Initialize

    try:
        # --- 0. Initial Setup & Validation ---
        if not temp_file_path or not os.path.exists(temp_file_path):
             raise FileNotFoundError(f"Temporary file path not found or invalid: {temp_file_path}")

        file_ext = os.path.splitext(original_filename)[-1].lower()
        if not file_ext:
            raise ValueError("Could not determine file extension from original filename.")

        if not allowed_file(original_filename): # Assuming allowed_file checks the extension
             raise ValueError(f"File type {file_ext} is not allowed.")

        file_size = os.path.getsize(temp_file_path)
        if file_size > max_file_size_bytes:
            raise ValueError(f"File exceeds maximum allowed size ({max_file_size_bytes / (1024*1024):.1f} MB).")

        update_doc_callback(status=f"Processing file {original_filename}, type: {file_ext}")

        # --- 1. Dispatch to appropriate handler based on file type ---
        di_supported_extensions = ('.pdf', '.docx', '.doc', '.pptx', '.ppt', '.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.heif')
        tabular_extensions = ('.csv', '.xlsx', '.xls')

        is_group = group_id is not None

        args = {
            "document_id": document_id,
            "user_id": user_id,
            "temp_file_path": temp_file_path,
            "original_filename": original_filename,
            "file_ext": file_ext if file_ext in tabular_extensions or file_ext in di_supported_extensions else None,
            "enable_enhanced_citations": enable_enhanced_citations,
            "update_callback": update_doc_callback
        }

        if is_group:
            args["group_id"] = group_id

        if file_ext == '.txt':
            total_chunks_saved = process_txt(**{k: v for k, v in args.items() if k != "file_ext"})
        elif file_ext == '.html':
            total_chunks_saved = process_html(**{k: v for k, v in args.items() if k != "file_ext"})
        elif file_ext == '.md':
            total_chunks_saved = process_md(**{k: v for k, v in args.items() if k != "file_ext"})
        elif file_ext == '.json':
            total_chunks_saved = process_json(**{k: v for k, v in args.items() if k != "file_ext"})
        elif file_ext in tabular_extensions:
            total_chunks_saved = process_tabular(**args)
        elif file_ext in di_supported_extensions:
            total_chunks_saved = process_di_document(**args)
        else:
            raise ValueError(f"Unsupported file type for processing: {file_ext}")


        # --- 2. Final Status Update ---
        final_status = "Processing complete"
        if total_chunks_saved == 0:
             # Provide more specific status if no chunks were saved
             if file_ext in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.heif'):
                 final_status = "Processing complete - no text found in image"
             elif file_ext in tabular_extensions:
                 final_status = "Processing complete - no data rows found or file empty"
             else:
                 final_status = "Processing complete - no content indexed"

        # Final update uses the total chunks saved across all steps/sheets
        # For DI types, number_of_pages might have been updated during DI processing,
        # but let's ensure the final update reflects the *saved* chunk count accurately.
        update_doc_callback(
             number_of_pages=total_chunks_saved, # Final count of SAVED chunks
             status=final_status,
             percentage_complete=100,
             current_file_chunk=None # Clear current chunk tracking
         )

        print(f"Document {document_id} ({original_filename}) processed successfully with {total_chunks_saved} chunks saved.")

    except Exception as e:
        error_msg = f"Processing failed: {str(e)}"
        print(f"Error processing {document_id} ({original_filename}): {error_msg}")
        # Attempt to update status to Error
        try:
            update_doc_callback(
                status=f"Error: {error_msg[:250]}", # Limit error message length
                percentage_complete=0 # Indicate failure
            )
        except Exception as update_e:
            print(f"Critical Error: Failed to update document status to error for {document_id}: {update_e}")

    finally:
        # --- 3. Cleanup ---
        # Clean up the original temporary file path regardless of success or failure
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                print(f"Cleaned up original temporary file: {temp_file_path}")
            except Exception as cleanup_e:
                 print(f"Warning: Failed to clean up original temp file {temp_file_path}: {cleanup_e}")

    # Return value is typically not used by Flask-Executor, but can be helpful for direct calls/testing
    # return total_chunks_saved # Or None/True/False depending on convention