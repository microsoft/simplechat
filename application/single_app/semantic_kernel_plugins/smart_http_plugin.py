#!/usr/bin/env python3
"""
Smart HTTP Plugin with Content Size Management.
Version: 0.228.014
Implemented in: 0.228.003
Updated in: 0.228.004 (increased content size to 75k chars ≈ 50k tokens)
Updated in: 0.228.005 (added PDF URL support with Document Intelligence integration)
Updated in: 0.228.006 (added agent citation support with function call tracking)
Updated in: 0.228.013 (integrated with plugin_function_logger decorator for proper citation display)
Updated in: 0.228.014 (fixed async compatibility issue - citations now show actual results, not coroutine objects)

This plugin wraps the standard HttpPlugin with intelligent content size management
to prevent token limit exceeded errors when scraping large websites. Now includes
PDF processing capabilities using Azure Document Intelligence for high-quality
text extraction from PDF URLs, plus comprehensive agent citation support using
an async-compatible plugin logging system for seamless integration with agent responses.
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
                    
                    # Check content length header
                    content_length = response.headers.get('content-length')
                    if content_length and int(content_length) > self.max_content_size * 2:
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
        """Process PDF content using Document Intelligence."""
        try:
            # Import here to avoid circular imports
            from functions_content import extract_content_with_azure_di
            
            # Check if pdf_bytes is actually string content (error case)
            if isinstance(pdf_bytes, str):
                return f"Error: Expected PDF binary data but received text content from {uri}"
            
            # Create temporary file for PDF processing
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
                if isinstance(pdf_bytes, str):
                    # If we somehow got string content, convert to bytes
                    temp_file.write(pdf_bytes.encode('utf-8'))
                else:
                    # Write binary PDF content
                    temp_file.write(pdf_bytes)
                temp_file_path = temp_file.name
            
            try:
                # Use Document Intelligence to extract content
                self.logger.info(f"Processing PDF from {uri} with Document Intelligence")
                pages_data = extract_content_with_azure_di(temp_file_path)
                
                if not pages_data:
                    return f"PDF processed from {uri} but no text content was extracted."
                
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
                
                # Add URL context
                result = f"PDF Content from: {uri}\n"
                result += f"Pages processed: {len(pages_data)}\n"
                result += f"Extracted via Document Intelligence\n\n{full_text}"
                
                return self._truncate_content(result, "PDF content")
                
            finally:
                # Clean up temporary file
                try:
                    os.unlink(temp_file_path)
                except Exception as cleanup_error:
                    self.logger.warning(f"Failed to cleanup temp PDF file: {cleanup_error}")
                    
        except ImportError:
            return f"Error: Document Intelligence not available for PDF processing from {uri}. Please ensure the system is properly configured."
        except Exception as e:
            self.logger.error(f"Error processing PDF from {uri}: {str(e)}")
            return f"Error processing PDF content from {uri}: {str(e)}"

    async def _read_limited_content(self, response) -> bytes:
        """Read response content with size limits, returning bytes for PDFs."""
        chunks = []
        total_size = 0
        
        async for chunk in response.content.iter_chunked(8192):
            chunks.append(chunk)
            total_size += len(chunk)
            
            # Stop reading if we exceed size limit
            if total_size > self.max_content_size * 3:  # Allow 3x for processing
                break
                
        return b''.join(chunks)

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
