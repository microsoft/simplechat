#!/usr/bin/env python3
"""
Debug script to see what inspect.getsource returns for chat_stream_api
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set environment to avoid missing env vars
os.environ['FLASK_ENV'] = 'development'
if not os.environ.get('SECRET_KEY'):
    os.environ['SECRET_KEY'] = 'test-key'

from config import *
from route_backend_chats import register_backend_chats_routes
import inspect
import textwrap

# Create a minimal Flask app
app = Flask(__name__)
app.config.update(CONFIG_DEFAULTS)

# Register routes to get the function
register_backend_chats_routes(app)

# Find the chat_stream_api function
for rule in app.url_map.iter_rules():
    if rule.rule == '/api/chat/stream':
        endpoint = rule.endpoint
        func = app.view_functions[endpoint]
        
        print(f"Found function: {func.__name__}")
        print(f"Endpoint: {endpoint}")
        print("\n" + "="*80)
        print("RAW SOURCE from inspect.getsource():")
        print("="*80)
        
        try:
            raw_source = inspect.getsource(func)
            print(repr(raw_source[:200]))  # First 200 chars
            print("\n")
            
            print("="*80)
            print("AFTER textwrap.dedent():")
            print("="*80)
            dedented = textwrap.dedent(raw_source)
            print(repr(dedented[:200]))
            print("\n")
            
            print("="*80)
            print("AFTER MANUAL MIN-INDENT REMOVAL:")
            print("="*80)
            lines = dedented.split('\n')
            if lines:
                min_indent = float('inf')
                for line in lines:
                    if line.strip():
                        indent = len(line) - len(line.lstrip())
                        min_indent = min(min_indent, indent)
                
                if min_indent > 0 and min_indent != float('inf'):
                    dedented = '\n'.join(line[min_indent:] if len(line) > min_indent else line for line in lines)
            
            print(repr(dedented[:200]))
            print("\n")
            
            print("="*80)
            print("AFTER lstrip():")
            print("="*80)
            final = dedented.lstrip()
            print(repr(final[:200]))
            print("\n")
            
            print("="*80)
            print("FIRST LINE:")
            print("="*80)
            first_line = final.split('\n')[0] if final else ''
            print(f"First line: {repr(first_line)}")
            print(f"Starts with whitespace: {first_line and first_line[0] in (' ', '\t')}")
            
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        
        break
