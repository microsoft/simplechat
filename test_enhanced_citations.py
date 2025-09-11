#!/usr/bin/env python3
"""
Simple test script to validate enhanced citation functionality
"""

import os
import sys
import tempfile
import requests
import json

# Add the application directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'application', 'single_app'))

def test_file_type_detection():
    """Test the frontend file type detection logic (we'll simulate this)"""
    print("Testing file type detection...")
    
    # Simulate getFileType function logic
    def get_file_type(file_name):
        if not file_name:
            return 'other'
        
        file_name_lower = file_name.lower()
        
        # Image extensions
        image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.heif']
        if any(file_name_lower.endswith(ext) for ext in image_extensions):
            return 'image'
        
        # PDF extension
        if file_name_lower.endswith('.pdf'):
            return 'pdf'
        
        # Video extensions
        video_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.flv', '.webm', '.wmv']
        if any(file_name_lower.endswith(ext) for ext in video_extensions):
            return 'video'
        
        # Audio extensions
        audio_extensions = ['.mp3', '.wav', '.ogg', '.aac', '.flac', '.m4a']
        if any(file_name_lower.endswith(ext) for ext in audio_extensions):
            return 'audio'
        
        return 'other'
    
    # Test cases
    test_cases = [
        ('document.pdf', 'pdf'),
        ('image.jpg', 'image'),
        ('image.PNG', 'image'),
        ('video.mp4', 'video'),
        ('video.MOV', 'video'),
        ('audio.mp3', 'audio'),
        ('audio.WAV', 'audio'),
        ('document.txt', 'other'),
        ('', 'other'),
        (None, 'other')
    ]
    
    for filename, expected in test_cases:
        result = get_file_type(filename)
        status = "✓" if result == expected else "✗"
        print(f"  {status} {filename or 'None'} -> {result} (expected: {expected})")
    
    print("File type detection test completed.\n")

def test_timestamp_conversion():
    """Test timestamp conversion logic"""
    print("Testing timestamp conversion...")
    
    def convert_timestamp_to_seconds(timestamp):
        if isinstance(timestamp, (int, float)):
            return timestamp
        
        if isinstance(timestamp, str):
            # Try to parse as number first
            try:
                return float(timestamp)
            except ValueError:
                pass
            
            # Try to parse as HH:MM:SS or MM:SS format
            if ':' in timestamp:
                parts = [float(part) for part in timestamp.split(':')]
                if len(parts) == 3:
                    return parts[0] * 3600 + parts[1] * 60 + parts[2]
                elif len(parts) == 2:
                    return parts[0] * 60 + parts[1]
        
        return 0
    
    # Test cases
    test_cases = [
        (120, 120),
        ('120', 120),
        ('120.5', 120.5),
        ('2:00', 120),
        ('1:30:00', 5400),
        ('0:45:30', 2730),
        ('invalid', 0),
        ('', 0),
        (None, 0)
    ]
    
    for timestamp, expected in test_cases:
        try:
            result = convert_timestamp_to_seconds(timestamp)
            status = "✓" if abs(result - expected) < 0.1 else "✗"
            print(f"  {status} {timestamp} -> {result} seconds (expected: {expected})")
        except Exception as e:
            print(f"  ✗ {timestamp} -> ERROR: {e}")
    
    print("Timestamp conversion test completed.\n")

def main():
    """Run all tests"""
    print("Enhanced Citations Test Suite")
    print("=" * 40)
    
    test_file_type_detection()
    test_timestamp_conversion()
    
    print("Test suite completed!")
    print("\nTo test the full system:")
    print("1. Start the Flask application")
    print("2. Upload different media types (images, PDFs, videos, audio)")
    print("3. Ask questions that generate citations")
    print("4. Click on citations to test the enhanced modals")

if __name__ == "__main__":
    main()
