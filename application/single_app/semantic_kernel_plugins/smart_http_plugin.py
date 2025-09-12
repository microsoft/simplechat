#!/usr/bin/env python3
"""
Smart HTTP Plugin with Content Size Management and Large PDF Support.
Version: 0.228.022
Implemented in: 0.228.003
Updated in: 0.228.004 (increased content size to 75k chars ≈ 50k tokens)
Updated in: 0.228.005 (added PDF URL support with Document Intelligence integration)
Updated in: 0.228.006 (added agent citation support with function call tracking)
Updated in: 0.228.013 (integrated with plugin_function_logge                     result += f"📍 Source: {uri}\n"                result += f"📍 Source: {uri}\n"ecorator for proper citation display)
Updated in: 0.228.014 (fixed async compatibility issue - citations now show actual results, not coroutine objects)
Updated in: 0.228.015 (added large PDF support with chunked summarization for files that exceed normal size limits)
Updated in: 0.228.019 (enhanced user messaging for large PDF summarization - clear transparency about processing and reduction)
Updated in: 0.228.020 (comprehensive summarization metrics - shows original vs summarized pages, characters, words, tokens, exact limits, and per-chunk reduction details)
Updated in: 0.228.021 (improved clarity of summarization messaging - separate lines for each metric for easy parsing)
Updated in: 0.228.022 (fixed duplicate output formatting bug causing incorrect display of summarization details)

This plugin wraps the standard HttpPlugin with intelligent content size management
to prevent token limit exceeded errors when scraping large websites. Now includes
PDF processing capabilities using Azure Document Intelligence for high-quality
text extraction from PDF URLs, plus comprehensive agent citation support using
an async-compatible plugin logging system for seamless integration with agent responses.

For large PDFs that exceed normal size limits, the plugin automatically processes
the entire document with Document Intelligence, then uses chunked summarization
via Azure OpenAI to reduce the content to a manageable size while preserving
key information and context. Users receive detailed transparency about the entire
process including: original document metrics (pages/chars/words/tokens), specific
processing limits that triggered summarization, chunking details, per-section
reduction percentages, and final summarized equivalent page count.
"""

import asyncio
import logging
import tempfile
import time
import os
from typing import Optional
import aiohttp
import html2text
from bs4 import BeautifulSoup
from semantic_kernel.functions import kernel_function
from semantic_kernel.functions.kernel_function_decorator import kernel_function
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger, get_plugin_logger, log_plugin_invocation
import re
import functools

def async_plugin_logger(plugin_name: str):
    """Async-compatible plugin function logger decorator."""
    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            function_name = func.__name__
            
            # Prepare parameters (combine args and kwargs)
            parameters = {}
            if args:
                # Handle 'self' parameter for methods
                if hasattr(args[0], '__class__'):
                    parameters.update({f"arg_{i}": arg for i, arg in enumerate(args[1:])})
                else:
                    parameters.update({f"arg_{i}": arg for i, arg in enumerate(args)})
            parameters.update(kwargs)
            
            try:
                # Await the async function
                result = await func(*args, **kwargs)
                end_time = time.time()
                
                # Log the successful invocation
                log_plugin_invocation(
                    plugin_name=plugin_name,
                    function_name=function_name,
                    parameters=parameters,
                    result=result,
                    start_time=start_time,
                    end_time=end_time,
                    success=True
                )
                
                return result
                
            except Exception as e:
                end_time = time.time()
                
                # Log the failed invocation
                log_plugin_invocation(
                    plugin_name=plugin_name,
                    function_name=function_name,
                    parameters=parameters,
                    result=None,
                    start_time=start_time,
                    end_time=end_time,
                    success=False,
                    error_message=str(e)
                )
                
                raise
                
        return async_wrapper
    return decorator

class SmartHttpPlugin:
    """HTTP plugin with intelligent content size management, web scraping optimization, and PDF processing via Document Intelligence."""
    
    def __init__(self, max_content_size: int = 75000, extract_text_only: bool = True):
        """
        Initialize the Smart HTTP Plugin.
        
        Args:
            max_content_size: Maximum content size in characters (default: 75k chars ≈ 50k tokens)
            extract_text_only: If True, extract only text content from HTML
        """
        self.max_content_size = max_content_size
        self.extract_text_only = extract_text_only
        self.logger = logging.getLogger(__name__)
        
        # Track function calls for citations
        self.function_calls = []
        
        # HTML to text converter
        self.html_converter = html2text.HTML2Text()
        self.html_converter.ignore_links = False
        self.html_converter.ignore_images = True
        self.html_converter.body_width = 0  # Don't wrap lines
        
    def _is_pdf_url(self, url: str) -> bool:
        """Check if URL likely points to a PDF file."""
        url_lower = url.lower()
        return (
            url_lower.endswith('.pdf') or 
            'filetype=pdf' in url_lower or
            'content-type=application/pdf' in url_lower or
            '/pdf/' in url_lower
        )
        
    def _track_function_call(self, function_name: str, parameters: dict, result: str, call_start: float, url: str, content_type: str = "unknown"):
        """Track function call for citation purposes with enhanced details."""
        duration = time.time() - call_start
        
        # Extract key information from the result for better citation display
        result_summary = str(result)
        if isinstance(result, str):
            if "Error:" in result:
                result_summary = f"Error: {result[:100]}..."
            elif "PDF Content from:" in result:
                # Extract PDF-specific info
                lines = result.split('\n')
                pdf_info = [line for line in lines[:3] if line.strip()]
                result_summary = " | ".join(pdf_info)
            elif "Content from:" in result:
                # Extract web content info
                content_length = len(result)
                if content_length > 200:
                    result_summary = f"Web content ({content_length} chars): {result[:100]}..."
                else:
                    result_summary = f"Web content: {result[:100]}..."
            else:
                # General content truncation
                if len(result) > 100:
                    result_summary = f"Content ({len(result)} chars): {result[:100]}..."
                else:
                    result_summary = result[:100]
        
        # Format parameters for better display
        params_summary = ""
        if parameters:
            param_parts = []
            for key, value in parameters.items():
                if isinstance(value, str) and len(value) > 50:
                    param_parts.append(f"{key}: {value[:50]}...")
                else:
                    param_parts.append(f"{key}: {value}")
            params_summary = ", ".join(param_parts[:3])  # Limit to first 3 params
            if len(parameters) > 3:
                params_summary += f" (and {len(parameters) - 3} more)"
        
        call_data = {
            "name": f"SmartHttp.{function_name}",
            "arguments": parameters,
            "result": result,
            "start_time": call_start,
            "end_time": time.time(),
            "url": url,
            # Enhanced display information
            "function_name": function_name,
            "duration_ms": round(duration * 1000, 2),
            "result_summary": result_summary[:300],  # Truncate for display
            "params_summary": params_summary,
            "content_type": content_type,
            "content_length": len(result) if isinstance(result, str) else 0,
            "plugin_type": "SmartHttpPlugin"
        }
        self.function_calls.append(call_data)
        self.logger.info(f"[Smart HTTP Plugin] Tracked function call: {function_name} ({duration:.3f}s) -> {url}")
        
    @async_plugin_logger("SmartHttpPlugin")
    @kernel_function(
        description="Makes a GET request to a URI with intelligent content size management. Supports HTML, JSON, and PDF content with automatic text extraction from PDFs using Document Intelligence.",
        name="get_web_content"
    )
    async def get_web_content_async(self, uri: str) -> str:
        """
        Fetch web content with intelligent size management and text extraction.
        Supports HTML, JSON, and PDF content. PDFs are processed using Document Intelligence
        for high-quality text extraction.
        
        Args:
            uri: The URI to fetch
            
        Returns:
            Processed web content within size limits
        """
        call_start = time.time()
        parameters = {"uri": uri}
        content_type = "unknown"
        
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                
                async with session.get(uri, headers=headers) as response:
                    if response.status != 200:
                        error_result = f"Error: HTTP {response.status} - {response.reason}"
                        self._track_function_call("get_web_content", parameters, error_result, call_start, uri, "error")
                        return error_result
                    
                    # Check content length header - allow larger PDFs for summarization
                    content_length = response.headers.get('content-length')
                    content_type = response.headers.get('content-type', '').lower()
                    is_pdf = self._is_pdf_url(uri) or 'application/pdf' in content_type
                    
                    # Use Azure Document Intelligence limits for PDFs vs conservative limits for other content
                    # Azure DI supports 500MB for S0 tier, 4MB for F0 tier - we'll use a conservative 100MB
                    size_limit = 100 * 1024 * 1024 if is_pdf else self.max_content_size * 2  # 100MB for PDFs
                    
                    if content_length and int(content_length) > size_limit:
                        if is_pdf:
                            self.logger.info(f"Large PDF detected ({content_length} bytes), will attempt processing with summarization")
                        else:
                            error_result = f"Error: Content too large ({content_length} bytes). Try a different URL or specific page."
                            self._track_function_call("get_web_content", parameters, error_result, call_start, uri, "error")
                            return error_result
                    
                    # Read content with size limit
                    raw_content = await self._read_limited_content(response)
                    
                    # Process based on content type
                    content_type = response.headers.get('content-type', '').lower()
                    
                    # Check for PDF content
                    if (self._is_pdf_url(uri) or 'application/pdf' in content_type):
                        result = await self._process_pdf_content(raw_content, uri, response)
                        self._track_function_call("get_web_content", parameters, result, call_start, uri, "application/pdf")
                        return result
                    else:
                        # Convert bytes to string for non-PDF content
                        if isinstance(raw_content, bytes):
                            content = raw_content.decode('utf-8', errors='ignore')
                        else:
                            content = raw_content
                            
                        if 'text/html' in content_type:
                            result = self._process_html_content(content, uri)
                            self._track_function_call("get_web_content", parameters, result, call_start, uri, "text/html")
                            return result
                        elif 'application/json' in content_type:
                            result = self._process_json_content(content)
                            self._track_function_call("get_web_content", parameters, result, call_start, uri, "application/json")
                            return result
                        else:
                            result = self._truncate_content(content, "Plain text content")
                            self._track_function_call("get_web_content", parameters, result, call_start, uri, "text/plain")
                            return result
                        
        except asyncio.TimeoutError:
            error_result = "Error: Request timed out (30 seconds). The website may be slow or unresponsive."
            self._track_function_call("get_web_content", parameters, error_result, call_start, uri, "timeout")
            return error_result
        except Exception as e:
            self.logger.error(f"Error fetching {uri}: {str(e)}")
            error_result = f"Error fetching content: {str(e)}"
            self._track_function_call("get_web_content", parameters, error_result, call_start, uri, "error")
            return error_result
    
    def _process_html_content(self, html_content: str, uri: str) -> str:
        """Process HTML content to extract meaningful text."""
        try:
            if not self.extract_text_only:
                return self._truncate_content(html_content, "Raw HTML content")
            
            # Parse HTML
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove script, style, and other non-content elements
            for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                element.decompose()
            
            # Extract main content areas first
            main_content = ""
            
            # Try to find main content containers
            content_selectors = [
                'main', '[role="main"]', '.content', '.main-content', 
                '.post-content', '.article-content', '.entry-content',
                'article', '.article'
            ]
            
            for selector in content_selectors:
                elements = soup.select(selector)
                if elements:
                    main_content = ' '.join([elem.get_text() for elem in elements])
                    break
            
            # If no main content found, use body
            if not main_content:
                body = soup.find('body')
                if body:
                    main_content = body.get_text()
                else:
                    main_content = soup.get_text()
            
            # Clean up text
            text = self._clean_text(main_content)
            
            # Add URL context
            result = f"Content from: {uri}\n\n{text}"
            
            return self._truncate_content(result, "Extracted text content")
            
        except Exception as e:
            self.logger.error(f"Error processing HTML: {str(e)}")
            return self._truncate_content(html_content, "Raw content (HTML processing failed)")
    
    def _process_json_content(self, json_content: str) -> str:
        """Process JSON content."""
        try:
            # Pretty format JSON if possible
            import json
            parsed = json.loads(json_content)
            formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
            return self._truncate_content(formatted, "JSON content")
        except:
            return self._truncate_content(json_content, "Raw JSON content")
    
    def _clean_text(self, text: str) -> str:
        """Clean extracted text."""
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        # Remove multiple newlines
        text = re.sub(r'\n\s*\n', '\n\n', text)
        # Trim
        return text.strip()
    
    def _truncate_content(self, content: str, content_type: str) -> str:
        """Truncate content to size limits with informative message."""
        if len(content) <= self.max_content_size:
            return content
        
        truncated = content[:self.max_content_size]
        
        # Try to cut at a sentence boundary
        last_period = truncated.rfind('. ')
        last_newline = truncated.rfind('\n')
        
        cut_point = max(last_period, last_newline)
        if cut_point > self.max_content_size * 0.8:  # Only cut if we don't lose too much
            truncated = truncated[:cut_point + 1]
        
        original_size = len(content)
        truncated_size = len(truncated)
        
        truncation_info = f"\n\n--- CONTENT TRUNCATED ---\n"
        truncation_info += f"Original size: {original_size:,} characters\n"
        truncation_info += f"Truncated to: {truncated_size:,} characters\n"
        truncation_info += f"Content type: {content_type}\n"
        truncation_info += f"Tip: For full content, try requesting specific sections or ask for a summary."
        
        return truncated + truncation_info

    async def _process_pdf_content(self, pdf_bytes: bytes, uri: str, response) -> str:
        """Process PDF content using Document Intelligence with large PDF support."""
        try:
            # Import here to avoid circular imports
            from functions_content import extract_content_with_azure_di
            from functions_settings import get_settings
            from config import initialize_clients, CLIENTS
            
            # Check if pdf_bytes is actually string content (error case)
            if isinstance(pdf_bytes, str):
                return f"Error: Expected PDF binary data but received text content from {uri}"
            
            # Validate PDF header to ensure we have valid PDF data
            if not pdf_bytes.startswith(b'%PDF-'):
                self.logger.error(f"Invalid PDF header for {uri}: {pdf_bytes[:20]}")
                return f"📄 **INVALID PDF FORMAT**\n📍 Source: {uri}\n❌ Error: File does not appear to be a valid PDF document\n\n⚠️  The downloaded file does not have a valid PDF header. This could be due to:\n• Server returning HTML error page instead of PDF\n• Corrupted download\n• URL redirecting to non-PDF content\n• Access restrictions requiring authentication"
            
            # Debug: Log PDF header and size info
            self.logger.debug(f"PDF validation for {uri}: Header: {pdf_bytes[:10]}, Size: {len(pdf_bytes)} bytes")
            
            # Ensure Document Intelligence client is initialized
            if 'document_intelligence_client' not in CLIENTS or CLIENTS['document_intelligence_client'] is None:
                self.logger.info("Initializing Document Intelligence client for PDF processing")
                settings = get_settings()
                initialize_clients(settings)
            
            # Create temporary file for PDF processing with better handling
            temp_file_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
                    # Write binary PDF content directly (no string conversion)
                    temp_file.write(pdf_bytes)
                    temp_file.flush()  # Ensure all data is written
                    temp_file_path = temp_file.name
                
                # Get file size for diagnostics
                pdf_size = len(pdf_bytes)
                self.logger.info(f"Processing PDF from {uri} with Document Intelligence (size: {pdf_size:,} bytes)")
                
                # Check if file size exceeds reasonable limits for Document Intelligence
                max_di_size = 500 * 1024 * 1024  # 500MB - typical Azure DI limit
                if pdf_size > max_di_size:
                    return f"📄 **PDF TOO LARGE FOR PROCESSING**\n📍 Source: {uri}\n📊 File size: {pdf_size:,} bytes (exceeds {max_di_size:,} byte limit for Document Intelligence)\n\n⚠️  This PDF is too large for automated text extraction. Please try:\n• A smaller PDF document\n• Specific sections of the document\n• Contact the document provider for a text version"
                
                pages_data = extract_content_with_azure_di(temp_file_path)
                
                if not pages_data:
                    return f"📄 **PDF PROCESSING COMPLETED BUT NO TEXT FOUND**\n📍 Source: {uri}\n📊 File size: {pdf_size:,} bytes\n🔄 Processing: Document Intelligence completed successfully\n\n⚠️  The PDF was processed but contained no extractable text. This could be due to:\n• Image-only PDF (scanned document)\n• Encrypted or secured PDF\n• Unsupported PDF format\n• Empty or corrupted file"
                
                # Combine all pages into a single text
                combined_text = []
                for page_data in pages_data:
                    page_num = page_data.get('page_number', 'Unknown')
                    page_content = page_data.get('content', '').strip()
                    if page_content:
                        combined_text.append(f"=== Page {page_num} ===\n{page_content}")
                
                if not combined_text:
                    return f"PDF processed from {uri} but no readable text was found."
                
                full_text = "\n\n".join(combined_text)
                
                # Check if the content needs summarization based on token limits
                # Most models have context limits around 128k tokens, so we'll use 100k tokens as our limit
                max_tokens_for_processing = 100000  # ~400k characters
                max_chars_for_processing = max_tokens_for_processing * 4  # Rough estimate: 1 token ≈ 4 chars
                
                if len(full_text) > max_chars_for_processing:
                    original_char_count = len(full_text)
                    original_word_count = len(full_text.split())
                    # Rough token estimate (1 token ≈ 4 characters for English text)
                    estimated_token_count = original_char_count // 4
                    
                    # Our processing limits based on model token limits
                    char_limit = max_chars_for_processing  # 400,000 characters
                    token_limit = max_tokens_for_processing  # 100,000 tokens
                    
                    self.logger.info(f"PDF from {uri} is very large ({original_char_count} chars), attempting summarization")
                    summarized_text = await self._summarize_large_content(full_text, uri, len(pages_data))
                    
                    # Calculate final metrics
                    final_char_count = len(summarized_text) if summarized_text else 0
                    final_word_count = len(summarized_text.split()) if summarized_text else 0
                    final_token_estimate = final_char_count // 4
                    
                    # Calculate reduction percentages
                    char_reduction_pct = round((1 - final_char_count / original_char_count) * 100, 1) if original_char_count > 0 else 0
                    
                    # Estimate "virtual pages" after summarization (assuming ~2500 chars per page typical for dense text)
                    chars_per_page = 2500
                    estimated_summarized_pages = max(1, round(final_char_count / chars_per_page))
                    
                    # Add comprehensive header with detailed summarization explanation
                    result = f"📄 **LARGE PDF PROCESSED WITH AI SUMMARIZATION**\n"
                    result += f"📍 Source: {uri}\n"
                    result += f"📊 Original Document: {len(pages_data)} pages • {original_char_count:,} characters • ~{original_word_count:,} words • ~{estimated_token_count:,} tokens\n"
                    result += f"� Processing Limits: {char_limit:,} characters • ~{token_limit:,} tokens (content exceeded limits by {round((original_char_count/char_limit - 1) * 100, 1)}%)\n"
                    result += f"🔄 Processing Method: Full text extracted using Azure Document Intelligence, then AI summarization\n\n"
                    result += f"📏 Processing limits: {char_limit:,} characters (~{token_limit:,} tokens)\n"
                    result += f"⚠️  Original content exceeded limits by {round((original_char_count/char_limit - 1) * 100, 1)}% so we summarized the document\n"
                    result += f"📉 Summarization reduced document size: ~{char_reduction_pct}%\n"
                    result += f"📊 Character counts: {original_char_count:,} characters → {final_char_count:,} characters\n"
                    result += f"📄 Page counts: {len(pages_data)} pages summarized to ~{estimated_summarized_pages} pages\n"
                    result += f"🔢 Token estimates: ~{estimated_token_count:,} tokens → ~{final_token_estimate:,} tokens\n\n"
                    result += f"⚠️  Important: This is an AI-summarized version preserving key information. For complete details, access the original PDF.\n\n"
                    result += f"{'='*80}\n"
                    result += f"SUMMARIZED CONTENT ({estimated_summarized_pages} EQUIVALENT PAGES)\n"
                    result += f"{'='*80}\n\n"
                    result += summarized_text
                    
                    return result
                else:
                    # Add URL context for normal-sized PDFs
                    char_count = len(full_text)
                    word_count = len(full_text.split())
                    token_estimate = char_count // 4
                    
                    result = f"📄 **PDF CONTENT**\n"
                    result += f"📍 Source: {uri}\n"
                    result += f"📊 Document: {len(pages_data)} pages • {char_count:,} characters • ~{word_count:,} words • ~{token_estimate:,} tokens\n"
                    result += f"🔄 Processing: Extracted using Azure Document Intelligence\n"
                    result += f"✅ Status: Complete content included (within {max_chars_for_processing:,} character processing limit)\n\n"
                    result += f"{'='*60}\n"
                    result += f"FULL CONTENT\n"
                    result += f"{'='*60}\n\n"
                    result += full_text
                    
                    return self._truncate_content(result, "PDF content")
                
            finally:
                # Clean up temporary file
                if temp_file_path:
                    try:
                        os.unlink(temp_file_path)
                    except Exception as cleanup_error:
                        self.logger.warning(f"Failed to cleanup temp PDF file: {cleanup_error}")
                    
        except ImportError:
            return f"📄 **CONFIGURATION ERROR**\n📍 Source: {uri}\n\n❌ Document Intelligence not available for PDF processing. Please ensure the system is properly configured with Azure Document Intelligence credentials."
        except Exception as e:
            error_msg = str(e)
            pdf_size = len(pdf_bytes) if pdf_bytes else 0
            
            # Check for specific Document Intelligence errors
            if "InvalidContent" in error_msg or "corrupted or format is unsupported" in error_msg:
                return f"📄 **PDF FORMAT NOT SUPPORTED**\n📍 Source: {uri}\n📊 File size: {pdf_size:,} bytes\n❌ Error: Document Intelligence cannot process this PDF format\n\n⚠️  This could be due to:\n• Unsupported PDF version or format\n• Password-protected or encrypted PDF\n• Corrupted file during download\n• PDF contains only images/scans without OCR\n• File exceeds Document Intelligence size/complexity limits\n\n💡 Suggestions:\n• Try a different PDF document\n• Ensure the PDF is not password-protected\n• Check if the PDF opens correctly in a PDF viewer\n• For scanned documents, try a PDF with OCR text layer"
            elif "InvalidRequest" in error_msg:
                return f"📄 **PROCESSING REQUEST FAILED**\n📍 Source: {uri}\n📊 File size: {pdf_size:,} bytes\n❌ Error: Document Intelligence rejected the processing request\n\n⚠️  This could be due to:\n• File size exceeds service limits\n• PDF format not supported by Document Intelligence\n• Temporary service availability issues\n• Authentication or configuration problems\n\n💡 Try again with a smaller or different PDF document."
            else:
                self.logger.error(f"Error processing PDF from {uri}: {error_msg}")
                return f"📄 **PDF PROCESSING ERROR**\n📍 Source: {uri}\n📊 File size: {pdf_size:,} bytes\n❌ Error: {error_msg}\n\n⚠️  Unable to extract text from this PDF. Please try a different document or contact support if the issue persists."

    async def _read_limited_content(self, response) -> bytes:
        """Read response content with size limits, returning bytes for PDFs. Allow larger sizes for PDFs that will be summarized."""
        chunks = []
        total_size = 0
        content_type = response.headers.get('content-type', '').lower()
        is_pdf = 'application/pdf' in content_type
        
        # Use Azure Document Intelligence limits - 100MB conservative limit for downloads
        size_limit = 100 * 1024 * 1024 if is_pdf else self.max_content_size * 3  # 100MB for PDFs
        
        async for chunk in response.content.iter_chunked(8192):
            chunks.append(chunk)
            total_size += len(chunk)
            
            # Stop reading if we exceed size limit
            if total_size > size_limit:
                break
                
        return b''.join(chunks)

    async def _summarize_large_content(self, content: str, uri: str, page_count: int = None) -> str:
        """Summarize large content by chunking and summarizing each piece."""
        try:
            # Import settings and AzureOpenAI here to avoid circular imports
            from functions_settings import get_settings
            from openai import AzureOpenAI
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            
            settings = get_settings()
            
            # Set up Azure OpenAI client (similar to functions_documents.py)
            enable_gpt_apim = settings.get('enable_gpt_apim', False)
            gpt_model = settings.get('gpt_model', {}).get('selected', [{}])[0].get('deploymentName') or settings.get('azure_openai_gpt_deployment')
            
            if not gpt_model:
                self.logger.error("No GPT model available for summarization")
                return self._truncate_content(content, "Large PDF content (summarization unavailable)")
            
            # Create Azure OpenAI client
            if enable_gpt_apim:
                gpt_client = AzureOpenAI(
                    api_version=settings.get('azure_apim_gpt_api_version'),
                    azure_endpoint=settings.get('azure_apim_gpt_endpoint'),
                    api_key=settings.get('azure_apim_gpt_subscription_key')
                )
            else:
                if settings.get('azure_openai_gpt_authentication_type') == 'managed_identity':
                    cognitive_services_scope = "https://cognitiveservices.azure.com/.default"
                    token_provider = get_bearer_token_provider(
                        DefaultAzureCredential(), 
                        cognitive_services_scope
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
            
            # Chunk the content into manageable pieces (about 100k chars each)
            chunk_size = 100000
            chunks = []
            
            for i in range(0, len(content), chunk_size):
                chunk = content[i:i + chunk_size]
                chunks.append(chunk)
            
            page_info = f" from {page_count}-page PDF" if page_count else ""
            self.logger.info(f"Summarizing content{page_info} from {uri} in {len(chunks)} chunks of ~{chunk_size:,} characters each")
            
            # Summarize each chunk
            summaries = []
            for i, chunk in enumerate(chunks):
                try:
                    # More specific instructions for document summarization
                    chunk_char_count = len(chunk)
                    chunk_word_count = len(chunk.split())
                    chunk_token_estimate = chunk_char_count // 4
                    
                    messages = [
                        {
                            "role": "system",
                            "content": f"You are an expert at summarizing documents. Create a comprehensive summary that preserves all key information, main points, important details, data, and actionable insights from this document{page_info}. Maintain structure and context while being concise. This is part {i+1} of {len(chunks)} from a larger document that exceeded normal processing limits. This chunk contains {chunk_char_count:,} characters (~{chunk_word_count:,} words, ~{chunk_token_estimate:,} tokens)."
                        },
                        {
                            "role": "user",
                            "content": f"Please provide a detailed and comprehensive summary of this document section (chunk {i+1} of {len(chunks)}, {chunk_char_count:,} characters). Preserve all important information, data points, conclusions, and actionable insights:\n\n{chunk}"
                        }
                    ]
                    
                    response = gpt_client.chat.completions.create(
                        model=gpt_model,
                        messages=messages,
                        max_tokens=2500,  # Increased for more comprehensive summaries
                        temperature=0.3   # Low temperature for consistent summarization
                    )
                    
                    chunk_summary = response.choices[0].message.content.strip()
                    summary_char_count = len(chunk_summary)
                    chunk_reduction = round((1 - summary_char_count / chunk_char_count) * 100, 1) if chunk_char_count > 0 else 0
                    
                    summaries.append(f"📄 **SECTION {i+1} OF {len(chunks)}** (Original: {chunk_char_count:,} chars → Summary: {summary_char_count:,} chars, {chunk_reduction}% reduction)\n{chunk_summary}")
                    
                except Exception as e:
                    self.logger.error(f"Error summarizing chunk {i+1}: {str(e)}")
                    # Fallback to truncation for this chunk
                    truncated_chunk = chunk[:4000] + "... [Content truncated due to summarization error]"
                    summaries.append(f"📄 **SECTION {i+1} OF {len(chunks)} (AI Summarization Failed - Partial Original Content)**\n{truncated_chunk}")
            
            # Combine all summaries
            summary_header = f"🔄 **AI-GENERATED SUMMARY SECTIONS**\n"
            summary_header += f"The original content was divided into {len(chunks)} chunks of ~{chunk_size:,} characters each for processing.\n"
            summary_header += f"Each section below represents an intelligent summary preserving key information:\n\n"
            
            final_summary = summary_header + "\n\n".join(summaries)
            
            # If the combined summary is still too large, create a final executive summary
            if len(final_summary) > self.max_content_size:
                try:
                    messages = [
                        {
                            "role": "system",
                            "content": f"You are an expert at creating executive summaries. Create a comprehensive overview that captures the most important information, key findings, main conclusions, and actionable insights from this {page_count}-page document{page_info if page_count else ''}. The content was too large for normal processing and was intelligently summarized in sections."
                        },
                        {
                            "role": "user",
                            "content": f"Please create a comprehensive executive summary of these section summaries from a large document{page_info}. Focus on key findings, main points, important data, and actionable insights:\n\n{final_summary}"
                        }
                    ]
                    
                    response = gpt_client.chat.completions.create(
                        model=gpt_model,
                        messages=messages,
                        max_tokens=4000,  # More space for executive summary
                        temperature=0.3
                    )
                    
                    executive_summary = response.choices[0].message.content.strip()
                    
                    # Create layered summary structure
                    layered_summary = f"📋 **EXECUTIVE SUMMARY**\n{executive_summary}\n\n"
                    layered_summary += f"📑 **DETAILED SECTION SUMMARIES**\n"
                    layered_summary += f"The following sections provide more detailed summaries of each part:\n\n"
                    
                    # Add truncated section summaries if space allows
                    remaining_space = self.max_content_size - len(layered_summary)
                    if remaining_space > 1000:
                        truncated_sections = final_summary[:remaining_space-100] + "... [Additional sections truncated]"
                        layered_summary += truncated_sections
                    
                    final_summary = layered_summary
                    
                except Exception as e:
                    self.logger.error(f"Error creating executive summary: {str(e)}")
                    # Fallback to truncation with clear messaging
                    final_summary = f"⚠️  **CONTENT SIZE NOTICE**\nThe document was too large even after initial summarization. Here's the available content:\n\n" + final_summary[:self.max_content_size-200]
            
            return final_summary
            
        except ImportError as e:
            self.logger.error(f"Missing dependencies for summarization: {str(e)}")
            return self._truncate_content(content, "Large PDF content (summarization dependencies unavailable)")
        except Exception as e:
            self.logger.error(f"Error in content summarization: {str(e)}")
            return self._truncate_content(content, "Large PDF content (summarization failed)")

    @async_plugin_logger("SmartHttpPlugin")
    @kernel_function(
        description="Makes a POST request to a URI with content size management",
        name="post_web_content"
    )
    async def post_web_content_async(self, uri: str, body: str) -> str:
        """Post data to a URI with content size management."""
        call_start = time.time()
        parameters = {"uri": uri, "body": body[:100] + "..." if len(body) > 100 else body}  # Truncate body for display
        
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Content-Type': 'application/json'
                }
                
                async with session.post(uri, data=body, headers=headers) as response:
                    if response.status not in [200, 201, 202]:
                        error_result = f"Error: HTTP {response.status} - {response.reason}"
                        self._track_function_call("post_web_content", parameters, error_result, call_start, uri, "error")
                        return error_result
                    
                    raw_content = await self._read_limited_content(response)
                    # Convert bytes to string for POST responses
                    if isinstance(raw_content, bytes):
                        content = raw_content.decode('utf-8', errors='ignore')
                    else:
                        content = raw_content
                    result = self._truncate_content(content, "POST response")
                    self._track_function_call("post_web_content", parameters, result, call_start, uri, "application/json")
                    return result
                    
        except Exception as e:
            self.logger.error(f"Error posting to {uri}: {str(e)}")
            error_result = f"Error posting content: {str(e)}"
            self._track_function_call("post_web_content", parameters, error_result, call_start, uri, "error")
            return error_result
