# functions_content.py

from functions_debug import debug_print
from config import *
from functions_settings import *
from functions_logging import *

def extract_text_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

def extract_markdown_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

def extract_content_with_azure_di(file_path):
    """
    Extracts text page-by-page using Azure Document Intelligence "prebuilt-read"
    and returns a list of dicts, each containing page_number and content.
    """
    try:
        document_intelligence_client = CLIENTS['document_intelligence_client'] # Ensure CLIENTS is populated
        
        # Debug logging for troubleshooting
        debug_print(f"[DEBUG] Starting Azure DI extraction for: {os.path.basename(file_path)}")
        debug_print(f"[DEBUG] AZURE_ENVIRONMENT: {AZURE_ENVIRONMENT}")

        if AZURE_ENVIRONMENT in ("usgovernment", "custom"):
            # Required format for Document Intelligence API version 2024-11-30
            debug_print("[DEBUG] Using US Government/Custom environment with base64Source")
            with open(file_path, 'rb') as f:
                file_bytes = f.read()
                base64_source = base64.b64encode(file_bytes).decode('utf-8')
            
            # For stable API 1.0.2, use the correct body parameter structure
            analyze_request = {"base64Source": base64_source}
            poller = document_intelligence_client.begin_analyze_document(
                model_id="prebuilt-read",
                body=analyze_request
            )
            debug_print("[DEBUG] Successfully started analysis with base64Source")
        else:
            debug_print("[DEBUG] Using Public cloud environment")
            with open(file_path, 'rb') as f:
                # For stable API 1.0.2, the file needs to be passed as part of the body
                file_content = f.read()
                
                # Try different approaches for the stable API
                try:
                    # Method 1: Use bytes directly in body
                    poller = document_intelligence_client.begin_analyze_document(
                        model_id="prebuilt-read",
                        body=file_content,
                        content_type="application/pdf"
                    )
                    debug_print("[DEBUG] Successfully started analysis with body as bytes")
                except Exception as e1:
                    debug_print(f"[DEBUG] Method 1 failed: {e1}")
                    
                    try:
                        # Method 2: Use base64 format for consistency
                        base64_source = base64.b64encode(file_content).decode('utf-8')
                        analyze_request = {"base64Source": base64_source}
                        poller = document_intelligence_client.begin_analyze_document(
                            model_id="prebuilt-read",
                            body=analyze_request
                        )
                        debug_print("[DEBUG] Successfully started analysis with base64Source in body")
                    except Exception as e2:
                        debug_print(f"[ERROR] Both methods failed. Method 1: {e1}, Method 2: {e2}")
                        raise e1

        max_wait_time = 600
        start_time = time.time()

        while True:
            status = poller.status()
            if status == "succeeded":
                 break
            if status in ["failed", "canceled"]:
                # Attempt to get result even on failure for potential error details
                try:
                     result = poller.result()
                     # Optionally add failed result details to the exception message
                     error_details = f"Failed DI result details: {result}"
                except Exception as res_ex:
                     error_details = f"Could not get result details after failure: {res_ex}"
                raise Exception(f"Document analysis {status} for document. {error_details}")
            if time.time() - start_time > max_wait_time:
                raise TimeoutError(f"Document analysis took too long.")

            sleep_duration = 10 # Or adjust based on expected processing time
            time.sleep(sleep_duration)


        result = poller.result()

        pages_data = []

        if result.pages:
            for page in result.pages:
                page_number = page.page_number
                page_text = "" # Initialize page_text

                # --- METHOD 1: Preferred - Use spans and result.content ---
                if page.spans and result.content:
                    try:
                        page_content_parts = []
                        for span in page.spans:
                            start = span.offset
                            end = start + span.length
                            page_content_parts.append(result.content[start:end])
                        page_text = "".join(page_content_parts)
                    except Exception as span_ex:
                         # Silently ignore span extraction error and try next method
                         page_text = "" # Reset on error

                # --- METHOD 2: Fallback - Use lines if spans failed or weren't available ---
                if not page_text and page.lines:
                    try:
                        page_text = "\n".join(line.content for line in page.lines)
                    except Exception as line_ex:
                        # Silently ignore line extraction error and try next method
                        page_text = "" # Reset on error


                # --- METHOD 3: Last Resort Fallback - Use words (less accurate formatting) ---
                if not page_text and page.words:
                     try:
                        page_text = " ".join(word.content for word in page.words)
                     except Exception as word_ex:
                         # Silently ignore word extraction error
                         page_text = "" # Reset on error

                # If page_text is still empty after all attempts, it will be added as such

                pages_data.append({
                    "page_number": page_number,
                    "content": page_text.strip() # Add strip() just in case
                })
        # --- Fallback if NO pages were found at all, but top-level content exists ---
        elif result.content:
            pages_data.append({
                "page_number": 1,
                "content": result.content.strip()
            })
        # else: # No pages and no content, pages_data remains empty


        # Log the *processed* data using your existing logging function (optional)
        # add_file_task_to_file_processing_log(
        #     document_id=document_id,
        #     user_id=user_id,
        #     content=f"DI extraction processed data: {pages_data}"
        # )

        return pages_data

    except HttpResponseError as e:
        # Consider adding to your specific log here if needed, before re-raising
        # add_file_task_to_file_processing_log(document_id, user_id, f"HTTP error during DI: {e}")
        raise e
    except TimeoutError as e:
        # add_file_task_to_file_processing_log(document_id, user_id, f"Timeout error during DI: {e}")
        raise e
    except Exception as e:
        # add_file_task_to_file_processing_log(document_id, user_id, f"General error during DI: {e}")
        raise e


def extract_table_file(file_path, file_ext):
    try:
        if file_ext == '.csv':
            df = pandas.read_csv(file_path)
        elif file_ext in ['.xls', '.xlsx']:
            df = pandas.read_excel(file_path)
        else:
            raise ValueError("Unsupported file extension for table extraction.")
        
        # Return CSV format instead of HTML for more efficient storage and LLM processing
        # This drastically reduces token count and storage costs
        csv_content = df.to_csv(index=False)
        return csv_content
    except Exception as e:
        raise

def extract_pdf_metadata(pdf_path):
    """
    Returns a tuple (title, author, subject, keywords) from the given PDF, using PyMuPDF.
    """
    try:
        with fitz.open(pdf_path) as doc:
            meta = doc.metadata
            pdf_title = meta.get("title", "")
            pdf_author = meta.get("author", "")
            pdf_subject = meta.get("subject", "")
            pdf_keywords = meta.get("keywords", "")

            return pdf_title, pdf_author, pdf_subject, pdf_keywords

    except Exception as e:
        print(f"Error extracting PDF metadata: {e}")
        return "", "", "", ""
    
def extract_docx_metadata(docx_path):
    """
    Returns a tuple (title, author) from the given DOCX, using python-docx.
    """
    try:
        doc = docx.Document(docx_path)
        core_props = doc.core_properties
        doc_title = core_props.title or ''
        doc_author = core_props.author or ''
        return doc_title, doc_author
    except Exception as e:
        print(f"Error extracting DOCX metadata: {e}")
        return '', ''

def parse_authors(author_input):
    """
    Converts any input (None, string, list, comma-delimited, etc.)
    into a list of author strings.
    """
    if not author_input:
        # Covers None or empty string
        return []

    # If it's already a list, just return it (with stripping)
    if isinstance(author_input, list):
        return [a.strip() for a in author_input if a.strip()]

    # Otherwise, assume it's a string and parse by common delimiters (comma, semicolon)
    if isinstance(author_input, str):
        # e.g. "John Doe, Jane Smith; Bob Brown"
        authors = re.split(r'[;,]', author_input)
        authors = [a.strip() for a in authors if a.strip()]
        return authors

    # If it's some other unexpected data type, fallback to empty
    return []

def chunk_text(text, chunk_size=2000, overlap=200):
    try:
        words = text.split()
        chunks = []
        for i in range(0, len(words), chunk_size - overlap):
            chunk = ' '.join(words[i:i + chunk_size])
            chunks.append(chunk)
        return chunks
    except Exception as e:
        # Log the exception or handle it as needed
        print(f"Error in chunk_text: {e}")
        raise e  # Re-raise the exception to propagate it
    
def chunk_word_file_into_pages(di_pages):
    """
    Chunks the content extracted from a Word document by Azure DI into smaller
    chunks based on a target word count.

    Args:
        di_pages (list): A list of dictionaries, where each dictionary represents
                         a page extracted by Azure DI and contains at least a
                         'page_number' and 'content' key.

    Returns:
        list: A new list of dictionaries, where each dictionary represents a
              smaller chunk with 'page_number' (representing the chunk sequence)
              and 'content' (the chunked text).
    """
    new_pages = []
    current_chunk_content = []
    current_word_count = 0
    new_page_number = 1 # This will represent the chunk number

    for page in di_pages:
        page_content = page.get("content", "")
        # Split content into words (handling various whitespace)
        words = re.findall(r'\S+', page_content)

        for word in words:
            current_chunk_content.append(word)
            current_word_count += 1

            # If the chunk reaches the desired size, finalize it
            if current_word_count >= WORD_CHUNK_SIZE:
                chunk_text = " ".join(current_chunk_content)
                new_pages.append({
                    "page_number": new_page_number,
                    "content": chunk_text
                })
                # Reset for the next chunk
                current_chunk_content = []
                current_word_count = 0
                new_page_number += 1

    # Add any remaining words as the last chunk, if any exist
    if current_chunk_content:
        chunk_text = " ".join(current_chunk_content)
        new_pages.append({
            "page_number": new_page_number,
            "content": chunk_text
        })

    # If the input was empty or contained no words, return an empty list
    # or a single empty chunk depending on desired behavior.
    # Current logic returns empty list if no words.
    return new_pages

def generate_embedding(
    text,
    max_retries=5,
    initial_delay=1.0,
    delay_multiplier=2.0
):
    settings = get_settings()

    retries = 0
    current_delay = initial_delay

    enable_embedding_apim = settings.get('enable_embedding_apim', False)

    if enable_embedding_apim:
        embedding_model = settings.get('azure_apim_embedding_deployment')
        embedding_client = AzureOpenAI(
            api_version = settings.get('azure_apim_embedding_api_version'),
            azure_endpoint = settings.get('azure_apim_embedding_endpoint'),
            api_key=settings.get('azure_apim_embedding_subscription_key'))
    else:
        if (settings.get('azure_openai_embedding_authentication_type') == 'managed_identity'):
            token_provider = get_bearer_token_provider(DefaultAzureCredential(), cognitive_services_scope)
            
            embedding_client = AzureOpenAI(
                api_version=settings.get('azure_openai_embedding_api_version'),
                azure_endpoint=settings.get('azure_openai_embedding_endpoint'),
                azure_ad_token_provider=token_provider
            )
        
            embedding_model_obj = settings.get('embedding_model', {})
            if embedding_model_obj and embedding_model_obj.get('selected'):
                selected_embedding_model = embedding_model_obj['selected'][0]
                embedding_model = selected_embedding_model['deploymentName']
        else:
            embedding_client = AzureOpenAI(
                api_version=settings.get('azure_openai_embedding_api_version'),
                azure_endpoint=settings.get('azure_openai_embedding_endpoint'),
                api_key=settings.get('azure_openai_embedding_key')
            )
            
            embedding_model_obj = settings.get('embedding_model', {})
            if embedding_model_obj and embedding_model_obj.get('selected'):
                selected_embedding_model = embedding_model_obj['selected'][0]
                embedding_model = selected_embedding_model['deploymentName']

    while True:
        random_delay = random.uniform(0.5, 2.0)
        time.sleep(random_delay)

        try:
            response = embedding_client.embeddings.create(
                model=embedding_model,
                input=text
            )

            embedding = response.data[0].embedding
            return embedding

        except RateLimitError as e:
            retries += 1
            if retries > max_retries:
                return None

            wait_time = current_delay * random.uniform(1.0, 1.5)
            time.sleep(wait_time)
            current_delay *= delay_multiplier

        except Exception as e:
            raise
