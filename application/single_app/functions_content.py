# functions_content.py

import email.utils
import struct
import zipfile
from xml.etree import ElementTree

import olefile

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


def extract_docx_text(file_path):
    """Extract text from OOXML Word documents such as .docx and .docm."""
    try:
        import docx2txt
    except ImportError as exc:
        raise Exception(
            "docx2txt library is required for .docx/.docm file processing. Install with: pip install docx2txt"
        ) from exc

    return docx2txt.process(file_path)


def _normalize_legacy_doc_text(text):
    """Convert Word control characters into readable plain text."""
    if not text:
        return ""

    field_stripped_text = []
    field_stack = []

    for character in text:
        if character == "\x13":
            field_stack.append("code")
            continue
        if character == "\x14":
            if field_stack:
                field_stack[-1] = "result"
            continue
        if character == "\x15":
            if field_stack:
                field_stack.pop()
            continue

        if not field_stack or field_stack[-1] == "result":
            field_stripped_text.append(character)

    normalized_text = (
        "".join(field_stripped_text)
        .replace("\r", "\n")
        .replace("\x0b", "\n")
        .replace("\x0c", "\n\n")
        .replace("\x07", "\t")
        .replace("\x00", "")
    )
    normalized_text = re.sub(r"[\x01-\x08\x0e-\x1f]", " ", normalized_text)
    normalized_text = re.sub(r"\n{3,}", "\n\n", normalized_text)
    normalized_text = re.sub(r"[ \t]{2,}", " ", normalized_text)
    return normalized_text.strip()


def _score_legacy_doc_candidate(text):
    """Prefer longer candidates with a high ratio of readable characters."""
    if not text:
        return 0

    readable_characters = sum(
        1
        for character in text
        if character.isalnum()
        or character.isspace()
        or character in ".,;:!?()[]{}'\"-_/@#$%^&*+=<>|"
    )
    return readable_characters


def _extract_legacy_doc_text_from_piece_table(word_stream, piece_table_bytes):
    """Parse a PlcPcd piece table from the WordDocument stream."""
    if len(piece_table_bytes) < 16 or (len(piece_table_bytes) - 4) % 12 != 0:
        return ""

    piece_count = (len(piece_table_bytes) - 4) // 12
    cp_count = piece_count + 1
    cp_byte_count = cp_count * 4

    if len(piece_table_bytes) != cp_byte_count + (piece_count * 8):
        return ""

    character_positions = struct.unpack(f"<{cp_count}I", piece_table_bytes[:cp_byte_count])
    if any(character_positions[index] > character_positions[index + 1] for index in range(piece_count)):
        return ""

    text_segments = []
    piece_descriptor_offset = cp_byte_count

    for index in range(piece_count):
        start_cp = character_positions[index]
        end_cp = character_positions[index + 1]
        character_count = end_cp - start_cp
        if character_count < 0:
            return ""

        piece_descriptor_start = piece_descriptor_offset + (index * 8)
        piece_descriptor_end = piece_descriptor_start + 8
        piece_descriptor = piece_table_bytes[piece_descriptor_start:piece_descriptor_end]
        if len(piece_descriptor) != 8:
            return ""

        fc_compressed = struct.unpack("<I", piece_descriptor[2:6])[0]
        is_compressed_piece = bool(fc_compressed & 0x40000000)
        stream_offset = fc_compressed & 0x3FFFFFFF

        if is_compressed_piece:
            stream_offset //= 2
            byte_count = character_count
            encoding = "cp1252"
        else:
            byte_count = character_count * 2
            encoding = "utf-16le"

        if stream_offset < 0 or byte_count < 0 or (stream_offset + byte_count) > len(word_stream):
            return ""

        raw_text = word_stream[stream_offset:stream_offset + byte_count]
        text_segments.append(raw_text.decode(encoding, errors='ignore'))

    return _normalize_legacy_doc_text("".join(text_segments))


def _extract_legacy_doc_text_from_table_stream(word_stream, table_stream):
    """Scan a Word table stream for the most plausible text piece table."""
    best_text = ""
    best_score = 0
    search_offset = 0

    while search_offset <= len(table_stream) - 5:
        piece_table_marker_offset = table_stream.find(b"\x02", search_offset)
        if piece_table_marker_offset == -1 or piece_table_marker_offset > len(table_stream) - 5:
            break

        piece_table_length = struct.unpack(
            "<I",
            table_stream[piece_table_marker_offset + 1:piece_table_marker_offset + 5],
        )[0]
        piece_table_end = piece_table_marker_offset + 5 + piece_table_length

        if (
            piece_table_length >= 16
            and (piece_table_length - 4) % 12 == 0
            and piece_table_end <= len(table_stream)
        ):
            candidate_text = _extract_legacy_doc_text_from_piece_table(
                word_stream,
                table_stream[piece_table_marker_offset + 5:piece_table_end],
            )
            candidate_score = _score_legacy_doc_candidate(candidate_text)
            if candidate_score > best_score:
                best_text = candidate_text
                best_score = candidate_score

        search_offset = piece_table_marker_offset + 1

    return best_text


def extract_legacy_doc_text(file_path):
    """Extract text from Word 97-2003 .doc files using OLE streams and piece tables."""
    if not olefile.isOleFile(file_path):
        raise Exception("File is not a valid OLE compound document")

    ole = olefile.OleFileIO(file_path)
    try:
        if not ole.exists("WordDocument"):
            raise Exception("Missing WordDocument stream")

        word_stream = ole.openstream("WordDocument").read()
        best_text = ""
        best_score = 0

        for table_stream_name in ("1Table", "0Table"):
            if not ole.exists(table_stream_name):
                continue

            table_stream = ole.openstream(table_stream_name).read()
            candidate_text = _extract_legacy_doc_text_from_table_stream(word_stream, table_stream)
            candidate_score = _score_legacy_doc_candidate(candidate_text)
            if candidate_score > best_score:
                best_text = candidate_text
                best_score = candidate_score

        if not best_text:
            raise Exception("Could not locate a readable text piece table in the document")

        return best_text
    finally:
        ole.close()

def extract_content_with_azure_di(file_path):
    """
    Extracts text page-by-page using Azure Document Intelligence "prebuilt-read"
    and returns a list of dicts, each containing page_number and content.
    """
    try:
        document_intelligence_client = CLIENTS['document_intelligence_client'] # Ensure CLIENTS is populated
        
        # Debug logging for troubleshooting
        debug_print(f"Starting Azure DI extraction for: {os.path.basename(file_path)}")
        debug_print(f"AZURE_ENVIRONMENT: {AZURE_ENVIRONMENT}")

        if AZURE_ENVIRONMENT in ("usgovernment", "custom"):
            # Required format for Document Intelligence API version 2024-11-30
            debug_print("Using US Government/Custom environment with base64Source")
            with open(file_path, 'rb') as f:
                file_bytes = f.read()
                base64_source = base64.b64encode(file_bytes).decode('utf-8')
            
            # For stable API 1.0.2, use the correct body parameter structure
            analyze_request = {"base64Source": base64_source}
            poller = document_intelligence_client.begin_analyze_document(
                model_id="prebuilt-read",
                body=analyze_request
            )
            debug_print("Successfully started analysis with base64Source")
        else:
            debug_print("Using Public cloud environment")
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
                    debug_print("Successfully started analysis with body as bytes")
                except Exception as e1:
                    debug_print(f"Method 1 failed: {e1}")
                    
                    try:
                        # Method 2: Use base64 format for consistency
                        base64_source = base64.b64encode(file_content).decode('utf-8')
                        analyze_request = {"base64Source": base64_source}
                        poller = document_intelligence_client.begin_analyze_document(
                            model_id="prebuilt-read",
                            body=analyze_request
                        )
                        debug_print("Successfully started analysis with base64Source in body")
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
        elif file_ext in ['.xls', '.xlsx', '.xlsm']:
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


def _normalize_legacy_doc_metadata_value(value):
    """Convert OLE metadata values into trimmed strings."""
    if value is None:
        return ''

    if isinstance(value, bytes):
        for encoding in ('utf-8', 'utf-16le', 'cp1252', 'latin1'):
            try:
                value = value.decode(encoding)
                break
            except Exception:
                continue
        else:
            value = value.decode('utf-8', errors='ignore')

    return str(value).strip().strip('\x00').strip()


def _parse_metadata_keywords(value):
    """Parse metadata keywords into a normalized list of values."""
    normalized_value = _normalize_legacy_doc_metadata_value(value)
    if not normalized_value:
        return []

    return [keyword.strip() for keyword in re.split(r'[;,]', normalized_value) if keyword.strip()]


def extract_legacy_doc_metadata(doc_path):
    """Return title and author from a legacy OLE Word document when available."""
    try:
        if not olefile.isOleFile(doc_path):
            return '', ''

        ole = olefile.OleFileIO(doc_path)
        try:
            metadata = ole.get_metadata()
            doc_title = _normalize_legacy_doc_metadata_value(getattr(metadata, 'title', ''))
            doc_author = _normalize_legacy_doc_metadata_value(getattr(metadata, 'author', ''))

            if not doc_author:
                doc_author = _normalize_legacy_doc_metadata_value(getattr(metadata, 'last_saved_by', ''))

            return doc_title, doc_author
        finally:
            ole.close()
    except Exception as e:
        print(f"Error extracting DOC metadata: {e}")
        return '', ''


def extract_pptx_metadata(pptx_path):
    """Return title, author, subject, and keywords from an OOXML PowerPoint file."""
    namespaces = {
        'cp': 'http://schemas.openxmlformats.org/package/2006/metadata/core-properties',
        'dc': 'http://purl.org/dc/elements/1.1/',
    }

    try:
        with zipfile.ZipFile(pptx_path) as archive:
            try:
                core_properties = archive.read('docProps/core.xml')
            except KeyError:
                return '', '', '', []

        root = ElementTree.fromstring(core_properties)
        ppt_title = (root.findtext('dc:title', default='', namespaces=namespaces) or '').strip()
        ppt_author = (root.findtext('dc:creator', default='', namespaces=namespaces) or '').strip()
        ppt_subject = (root.findtext('dc:subject', default='', namespaces=namespaces) or '').strip()
        ppt_keywords = _parse_metadata_keywords(
            root.findtext('cp:keywords', default='', namespaces=namespaces) or ''
        )
        return ppt_title, ppt_author, ppt_subject, ppt_keywords
    except Exception as e:
        print(f"Error extracting PPTX metadata: {e}")
        return '', '', '', []


def _clean_legacy_ppt_text_fragment(text):
    """Normalize legacy PowerPoint text atoms into readable slide text."""
    if not text:
        return ''

    normalized_text = (
        text
        .replace('\r', '\n')
        .replace('\x0b', '\n')
        .replace('\x0c', '\n')
        .replace('\x00', '')
    )
    normalized_text = re.sub(r'[\x01-\x08\x0e-\x1f]', ' ', normalized_text)
    normalized_text = re.sub(r'[ \t]{2,}', ' ', normalized_text)
    normalized_text = re.sub(r'\n{3,}', '\n\n', normalized_text)
    return normalized_text.strip()


def extract_legacy_ppt_pages(file_path):
    """Extract slide text from a legacy OLE PowerPoint .ppt file."""
    if not olefile.isOleFile(file_path):
        raise Exception("File is not a valid OLE compound document")

    ole = olefile.OleFileIO(file_path)
    try:
        if not ole.exists('PowerPoint Document'):
            raise Exception("Missing PowerPoint Document stream")

        document_stream = ole.openstream('PowerPoint Document').read()
    finally:
        ole.close()

    slide_fragments = {}
    slide_counter = 0

    def walk_records(start_offset, end_offset, current_slide_number=None):
        nonlocal slide_counter

        offset = start_offset
        while offset + 8 <= end_offset:
            record_header = struct.unpack_from('<H', document_stream, offset)[0]
            record_version = record_header & 0x000F
            record_type = struct.unpack_from('<H', document_stream, offset + 2)[0]
            record_length = struct.unpack_from('<I', document_stream, offset + 4)[0]
            payload_start = offset + 8
            payload_end = payload_start + record_length

            if payload_end > end_offset:
                return

            next_slide_number = current_slide_number
            if record_type == 1006:
                slide_counter += 1
                next_slide_number = slide_counter
                slide_fragments.setdefault(next_slide_number, [])

            if record_type in {4000, 4008} and next_slide_number is not None:
                if record_type == 4000:
                    raw_text = document_stream[payload_start:payload_end].decode('utf-16le', errors='ignore')
                else:
                    raw_text = document_stream[payload_start:payload_end].decode('cp1252', errors='ignore')

                cleaned_text = _clean_legacy_ppt_text_fragment(raw_text)
                if cleaned_text:
                    fragments = slide_fragments.setdefault(next_slide_number, [])
                    if not fragments or fragments[-1] != cleaned_text:
                        fragments.append(cleaned_text)

            if record_version == 0x0F:
                walk_records(payload_start, payload_end, next_slide_number)

            offset = payload_end

    walk_records(0, len(document_stream))

    pages = []
    non_empty_slide_count = 0
    for slide_number in range(1, slide_counter + 1):
        slide_text = "\n".join(slide_fragments.get(slide_number, []))
        slide_text = re.sub(r'\n{3,}', '\n\n', slide_text).strip()
        if slide_text:
            non_empty_slide_count += 1

        pages.append({
            'page_number': slide_number,
            'content': slide_text,
        })

    if non_empty_slide_count == 0:
        raise Exception("Could not locate readable slide text in the presentation")

    return pages


def extract_legacy_ppt_metadata(ppt_path):
    """Return title, author, subject, and keywords from a legacy OLE PowerPoint file."""
    try:
        if not olefile.isOleFile(ppt_path):
            return '', '', '', []

        ole = olefile.OleFileIO(ppt_path)
        try:
            metadata = ole.get_metadata()
            ppt_title = _normalize_legacy_doc_metadata_value(getattr(metadata, 'title', ''))
            ppt_author = _normalize_legacy_doc_metadata_value(getattr(metadata, 'author', ''))
            ppt_subject = _normalize_legacy_doc_metadata_value(getattr(metadata, 'subject', ''))
            ppt_keywords = _parse_metadata_keywords(getattr(metadata, 'keywords', ''))

            if not ppt_author:
                ppt_author = _normalize_legacy_doc_metadata_value(getattr(metadata, 'last_saved_by', ''))

            return ppt_title, ppt_author, ppt_subject, ppt_keywords
        finally:
            ole.close()
    except Exception as e:
        print(f"Error extracting PPT metadata: {e}")
        return '', '', '', []


def extract_presentation_metadata(file_path, file_extension=None):
    """Extract metadata from supported PowerPoint presentation formats."""
    resolved_extension = (file_extension or os.path.splitext(file_path)[1]).lower()

    if resolved_extension == '.ppt':
        return extract_legacy_ppt_metadata(file_path)

    if resolved_extension == '.pptx':
        return extract_pptx_metadata(file_path)

    return '', '', '', []


def extract_word_text(file_path, file_extension=None):
    """Extract text from supported Word document formats."""
    resolved_extension = (file_extension or os.path.splitext(file_path)[1]).lower()

    if resolved_extension == '.doc':
        if olefile.isOleFile(file_path):
            return extract_legacy_doc_text(file_path)
        return extract_docx_text(file_path)

    if resolved_extension in {'.docx', '.docm'}:
        return extract_docx_text(file_path)

    raise ValueError(f"Unsupported Word document extension: {resolved_extension}")


def extract_word_metadata(file_path, file_extension=None):
    """Extract title and author metadata from supported Word document formats."""
    resolved_extension = (file_extension or os.path.splitext(file_path)[1]).lower()

    if resolved_extension == '.doc':
        if olefile.isOleFile(file_path):
            return extract_legacy_doc_metadata(file_path)
        return extract_docx_metadata(file_path)

    if resolved_extension in {'.docx', '.docm'}:
        return extract_docx_metadata(file_path)

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
    
def chunk_word_file_into_pages(di_pages, chunk_size=WORD_CHUNK_SIZE):
    """
    Chunk Azure DI Word pages into smaller word-based segments.

    Args:
        di_pages (list): Pages returned from DI with page_number/content keys.
        chunk_size (int): Target number of words per chunk (defaults to config).

    Returns:
        list: A list of dicts with chunked content and sequence numbers.
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
            if current_word_count >= chunk_size:
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


def _parse_retry_after_seconds(response_headers):
    """Return retry delay in seconds from rate-limit headers when available."""
    if response_headers is None:
        return None

    for header_name in ('retry-after-ms', 'x-ms-retry-after-ms'):
        try:
            retry_ms = response_headers.get(header_name)
            if retry_ms is None:
                continue

            retry_after = float(retry_ms) / 1000
            if retry_after > 0:
                return retry_after
        except (TypeError, ValueError):
            continue

    retry_header = response_headers.get('retry-after')
    try:
        retry_after = float(retry_header)
        if retry_after > 0:
            return retry_after
    except (TypeError, ValueError):
        pass

    if not retry_header:
        return None

    retry_date_tuple = email.utils.parsedate_tz(retry_header)
    if retry_date_tuple is None:
        return None

    retry_after = float(email.utils.mktime_tz(retry_date_tuple) - time.time())
    if retry_after <= 0:
        return None

    return retry_after


def _get_rate_limit_wait_time(rate_limit_error, fallback_delay):
    """Prefer service-provided retry timing and fall back to jittered backoff."""
    response = getattr(rate_limit_error, 'response', None)
    response_headers = getattr(response, 'headers', None)
    retry_after = _parse_retry_after_seconds(response_headers)

    if retry_after is not None and retry_after <= 60:
        return retry_after

    return fallback_delay * random.uniform(1.0, 1.5)

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
        random_delay = random.uniform(0.05, 0.2)
        time.sleep(random_delay)

        try:
            response = embedding_client.embeddings.create(
                model=embedding_model,
                input=text
            )

            embedding = response.data[0].embedding
            
            # Capture token usage for embedding tracking
            token_usage = None
            if hasattr(response, 'usage') and response.usage:
                token_usage = {
                    'prompt_tokens': response.usage.prompt_tokens,
                    'total_tokens': response.usage.total_tokens,
                    'model_deployment_name': embedding_model
                }
            
            return embedding, token_usage

        except RateLimitError as e:
            retries += 1
            if retries > max_retries:
                return None

            wait_time = _get_rate_limit_wait_time(e, current_delay)
            debug_print(
                f"[EMBEDDING] Rate limited, retrying in {wait_time:.2f}s "
                f"(attempt {retries}/{max_retries})"
            )
            time.sleep(wait_time)
            current_delay *= delay_multiplier

        except Exception as e:
            raise

def generate_embeddings_batch(
    texts,
    batch_size=16,
    max_retries=5,
    initial_delay=1.0,
    delay_multiplier=2.0
):
    """Generate embeddings for multiple texts in batches.

    Azure OpenAI embeddings API accepts a list of strings as input.
    This reduces per-call overhead and delay significantly.

    Args:
        texts: List of text strings to embed.
        batch_size: Number of texts per API call (default 16).
        max_retries: Max retries on rate limit errors.
        initial_delay: Initial retry delay in seconds.
        delay_multiplier: Multiplier for exponential backoff.

    Returns:
        list of (embedding, token_usage) tuples, one per input text.
    """
    settings = get_settings()

    enable_embedding_apim = settings.get('enable_embedding_apim', False)

    if enable_embedding_apim:
        embedding_model = settings.get('azure_apim_embedding_deployment')
        embedding_client = AzureOpenAI(
            api_version=settings.get('azure_apim_embedding_api_version'),
            azure_endpoint=settings.get('azure_apim_embedding_endpoint'),
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

    results = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        retries = 0
        current_delay = initial_delay

        while True:
            random_delay = random.uniform(0.05, 0.2)
            time.sleep(random_delay)

            try:
                response = embedding_client.embeddings.create(
                    model=embedding_model,
                    input=batch
                )

                for item in response.data:
                    token_usage = None
                    if hasattr(response, 'usage') and response.usage:
                        token_usage = {
                            'prompt_tokens': response.usage.prompt_tokens // len(batch),
                            'total_tokens': response.usage.total_tokens // len(batch),
                            'model_deployment_name': embedding_model
                        }
                    results.append((item.embedding, token_usage))
                break

            except RateLimitError as e:
                retries += 1
                if retries > max_retries:
                    raise

                wait_time = _get_rate_limit_wait_time(e, current_delay)
                debug_print(
                    f"[EMBEDDING_BATCH] Rate limited, retrying in {wait_time:.2f}s "
                    f"(attempt {retries}/{max_retries})"
                )
                time.sleep(wait_time)
                current_delay *= delay_multiplier

            except Exception as e:
                raise

    return results
