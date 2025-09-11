#!/usr/bin/env python3
"""
Smart HTTP Plugin with Content Size Management.
Version: 0.228.004
Implemented in: 0.228.003
Updated in: 0.228.004 (increased content size to 75k chars ≈ 50k tokens)

This plugin wraps the standard HttpPlugin with intelligent content size management
to prevent token limit exceeded errors when scraping large websites.
"""

import asyncio
import logging
from typing import Optional
import aiohttp
import html2text
from bs4 import BeautifulSoup
from semantic_kernel.functions import kernel_function
from semantic_kernel.functions.kernel_function_decorator import kernel_function
import re

class SmartHttpPlugin:
    """HTTP plugin with intelligent content size management and web scraping optimization."""
    
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
        
        # HTML to text converter
        self.html_converter = html2text.HTML2Text()
        self.html_converter.ignore_links = False
        self.html_converter.ignore_images = True
        self.html_converter.body_width = 0  # Don't wrap lines
        
    @kernel_function(
        description="Makes a GET request to a URI with intelligent content size management",
        name="get_web_content"
    )
    async def get_web_content_async(self, uri: str) -> str:
        """
        Fetch web content with intelligent size management and text extraction.
        
        Args:
            uri: The URI to fetch
            
        Returns:
            Processed web content within size limits
        """
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                
                async with session.get(uri, headers=headers) as response:
                    if response.status != 200:
                        return f"Error: HTTP {response.status} - {response.reason}"
                    
                    # Check content length header
                    content_length = response.headers.get('content-length')
                    if content_length and int(content_length) > self.max_content_size * 2:
                        return f"Error: Content too large ({content_length} bytes). Try a different URL or specific page."
                    
                    # Read content with size limit
                    content = await self._read_limited_content(response)
                    
                    # Process based on content type
                    content_type = response.headers.get('content-type', '').lower()
                    
                    if 'text/html' in content_type:
                        return self._process_html_content(content, uri)
                    elif 'application/json' in content_type:
                        return self._process_json_content(content)
                    else:
                        return self._truncate_content(content, "Plain text content")
                        
        except asyncio.TimeoutError:
            return "Error: Request timed out (30 seconds). The website may be slow or unresponsive."
        except Exception as e:
            self.logger.error(f"Error fetching {uri}: {str(e)}")
            return f"Error fetching content: {str(e)}"
    
    async def _read_limited_content(self, response) -> str:
        """Read response content with size limits."""
        chunks = []
        total_size = 0
        
        async for chunk in response.content.iter_chunked(8192):
            chunk_text = chunk.decode('utf-8', errors='ignore')
            chunks.append(chunk_text)
            total_size += len(chunk_text)
            
            # Stop reading if we exceed size limit
            if total_size > self.max_content_size * 3:  # Allow 3x for HTML processing
                break
                
        return ''.join(chunks)
    
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

    @kernel_function(
        description="Makes a POST request to a URI with content size management",
        name="post_web_content"
    )
    async def post_web_content_async(self, uri: str, body: str) -> str:
        """Post data to a URI with content size management."""
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Content-Type': 'application/json'
                }
                
                async with session.post(uri, data=body, headers=headers) as response:
                    if response.status not in [200, 201, 202]:
                        return f"Error: HTTP {response.status} - {response.reason}"
                    
                    content = await self._read_limited_content(response)
                    return self._truncate_content(content, "POST response")
                    
        except Exception as e:
            self.logger.error(f"Error posting to {uri}: {str(e)}")
            return f"Error posting content: {str(e)}"
