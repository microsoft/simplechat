#!/usr/bin/env python3
# test_base64_image_handling.py
"""
Functional test for base64 image data handling.
Version: 0.241.022
Implemented in: 0.241.022

This test ensures that base64 image payloads can be decoded into binary image
bytes and that external image URLs are still recognized separately from data
URLs used by chunked image storage and hydration.
"""

import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, 'application', 'single_app')
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from functions_image_messages import decode_image_content, is_external_image_url


TINY_PNG_BASE64 = (
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aF9sAAAAASUVORK5CYII='
)
TINY_PNG_DATA_URL = f'data:image/png;base64,{TINY_PNG_BASE64}'


def test_decode_base64_image_content():
    """Validate that image data URLs decode into PNG bytes."""
    mime_type, image_bytes = decode_image_content(TINY_PNG_DATA_URL)

    assert mime_type == 'image/png'
    assert image_bytes.startswith(b'\x89PNG\r\n\x1a\n')
    assert len(image_bytes) > 8


def test_external_url_detection():
    """Validate that remote image URLs stay separate from inline data URLs."""
    assert is_external_image_url('https://example.com/generated-image.png') is True
    assert is_external_image_url('http://example.com/generated-image.png') is True
    assert is_external_image_url(TINY_PNG_DATA_URL) is False


if __name__ == '__main__':
    test_decode_base64_image_content()
    test_external_url_detection()
    print('Base64 image handling checks passed.')
