# functions_documents.py

from config import *
from functions_content import *
from functions_settings import *

def allowed_file(filename, allowed_extensions=None):
    if not allowed_extensions:
        allowed_extensions = ALLOWED_EXTENSIONS
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions

def add_system_message_to_conversation(conversation_id, user_id, content):
    try:
        conversation_item = container.read_item(
            item=conversation_id,
            partition_key=conversation_id
        )

        conversation_item['messages'].append({
            "role": "system",
            "content": content,
            "timestamp": datetime.utcnow().isoformat()
        })
        conversation_item['last_updated'] = datetime.utcnow().isoformat()

        container.upsert_item(conversation_item)

    except Exception as e:
        raise e
    
def process_document_and_store_chunks(extracted_content , file_name, user_id):
    settings = get_settings()

    chunks = chunk_text(extracted_content )
    print(f"chunks: {chunks}")
    document_id = str(uuid.uuid4())
    chunks = chunk_text(extracted_content )
    num_chunks = len(chunks)

    existing_document_query = """
        SELECT c.version 
        FROM c 
        WHERE c.file_name = @file_name AND c.user_id = @user_id
    """
    parameters = [{"name": "@file_name", "value": file_name}, {"name": "@user_id", "value": user_id}]
    
    existing_document = list(documents_container.query_items(query=existing_document_query, parameters=parameters, enable_cross_partition_query=True))

    if existing_document:
        version = existing_document[0]['version'] + 1
    else:
        version = 1

    current_time = datetime.now(timezone.utc)

    formatted_time = current_time.strftime('%Y-%m-%dT%H:%M:%SZ')

    document_metadata = {
        "id": document_id,
        "num_chunks": num_chunks,
        "file_name": file_name,
        "user_id": user_id,
        "upload_date": formatted_time,
        "version": version,
        "type": "document_metadata"
    }
    documents_container.upsert_item(document_metadata)
    chunk_documents = []

    for idx, chunk_text_content in enumerate(chunks):
        chunk_id = f"{document_id}_{idx}"

        embedding = generate_embedding(chunk_text_content)

        chunk_document = {
            "id": chunk_id,
            "document_id": document_id,
            "chunk_id": str(idx),
            "chunk_text": chunk_text_content,
            "embedding": embedding,
            "file_name": file_name,
            "user_id": user_id,
            "chunk_sequence": idx,
            "upload_date": formatted_time,
            "version": version
        }
        chunk_documents.append(chunk_document)
    
    search_client_user = CLIENTS["search_client_user"]
    print(f"chunk documents before upload: {chunk_documents}")
    print(f"Search client: {search_client_user}")
    search_client_user.upload_documents(documents=chunk_documents)

def get_user_documents(user_id):
    try:
        query = """
            SELECT c.file_name, c.id, c.upload_date, c.user_id, c.num_chunks ,c.version
            FROM c
            WHERE c.user_id = @user_id
        """
        parameters = [{"name": "@user_id", "value": user_id}]
        
        documents = list(documents_container.query_items(query=query, parameters=parameters, enable_cross_partition_query=True))

        latest_documents = {}

        for doc in documents:
            file_name = doc['file_name']
            if file_name not in latest_documents or doc['version'] > latest_documents[file_name]['version']:
                latest_documents[file_name] = doc
                
        return jsonify({"documents": list(latest_documents.values())}), 200
    except Exception as e:
        return jsonify({'error': f'Error retrieving documents: {str(e)}'}), 500

def get_user_document(user_id, document_id):

    try:
        latest_version_query = """
            SELECT TOP 1 *
            FROM c 
            WHERE c.id = @document_id AND c.user_id = @user_id
            ORDER BY c.version DESC
        """
        parameters = [
            {"name": "@document_id", "value": document_id},
            {"name": "@user_id", "value": user_id}
        ]

        document_results = list(documents_container.query_items(
            query=latest_version_query, 
            parameters=parameters, 
            enable_cross_partition_query=True
        ))

        if not document_results:
            return jsonify({'error': 'Document not found or access denied'}), 404

        return jsonify(document_results[0]), 200

    except Exception as e:
        return jsonify({'error': f'Error retrieving document: {str(e)}'}), 500

def get_latest_version(document_id, user_id):

    query = """
        SELECT c.version
        FROM c 
        WHERE c.id = @document_id AND c.user_id = @user_id
    """
    parameters = [
        {"name": "@document_id", "value": document_id},
        {"name": "@user_id", "value": user_id}
    ]

    try:
        results = list(documents_container.query_items(query=query, parameters=parameters, enable_cross_partition_query=True))

        if results:
            max_version = max(item['version'] for item in results)
            return max_version
        else:
            return None

    except Exception as e:
        return None
    
def get_user_document_version(user_id, document_id, version):
    try:
        query = """
            SELECT *
            FROM c 
            WHERE c.id = @document_id AND c.user_id = @user_id AND c.version = @version
        """
        parameters = [
            {"name": "@document_id", "value": document_id},
            {"name": "@user_id", "value": user_id},
            {"name": "@version", "value": version}
        ]
        
        document_results = list(documents_container.query_items(query=query, parameters=parameters, enable_cross_partition_query=True))

        if not document_results:
            return jsonify({'error': 'Document version not found'}), 404

        return jsonify(document_results[0]), 200

    except Exception as e:
        return jsonify({'error': f'Error retrieving document version: {str(e)}'}), 500

def delete_user_document(user_id, document_id):
    """Delete a document from the user's documents in Cosmos DB."""
    try:
        document_item = documents_container.read_item(
            item=document_id,
            partition_key=document_id
        )

        if document_item.get('user_id') != user_id:
            raise Exception("Unauthorized access to document")

        documents_container.delete_item(
            item=document_id,
            partition_key=document_id
        )
    except CosmosResourceNotFoundError:
        raise Exception("Document not found")
    except Exception as e:
        raise

def delete_user_document_chunks(document_id):
    """Delete document chunks from Azure Cognitive Search index."""
    try:
        search_client_user = CLIENTS["search_client_user"]
        results = search_client_user.search(
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
        result = search_client_user.index_documents(batch)
    except Exception as e:
        raise

def delete_user_document_version(user_id, document_id, version):
    query = """
        SELECT c.id 
        FROM c 
        WHERE c.id = @document_id AND c.user_id = @user_id AND c.version = @version
    """
    parameters = [
        {"name": "@document_id", "value": document_id},
        {"name": "@user_id", "value": user_id},
        {"name": "@version", "value": version}
    ]
    documents = list(documents_container.query_items(query=query, parameters=parameters, enable_cross_partition_query=True))

    for doc in documents:
        documents_container.delete_item(doc['id'], partition_key=doc['user_id'])

def delete_user_document_version_chunks(document_id, version):
    search_client_user = CLIENTS["search_client_user"]
    search_client_user.delete_documents(
        actions=[
            {"@search.action": "delete", "id": chunk['id']} for chunk in 
            search_client_user.search(
                search_text="*",
                filter=f"document_id eq '{document_id}' and version eq {version}",
                select="id"
            )
        ]
    )

def get_document_versions(user_id, document_id):
    try:
        query = """
            SELECT c.id, c.file_name, c.version, c.upload_date
            FROM c 
            WHERE c.id = @document_id AND c.user_id = @user_id
            ORDER BY c.version DESC
        """
        parameters = [
            {"name": "@document_id", "value": document_id},
            {"name": "@user_id", "value": user_id}
        ]

        versions_results = list(documents_container.query_items(query=query, parameters=parameters, enable_cross_partition_query=True))

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
        doc_item = documents_container.read_item(document_id, partition_key=document_id)
        if user_id and doc_item.get('user_id') != user_id:
            pass
        else:
            return "user"
    except:
        pass

    try:
        group_doc_item = group_documents_container.read_item(document_id, partition_key=document_id)
        return "group"
    except:
        pass

    return None