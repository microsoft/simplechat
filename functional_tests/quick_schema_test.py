#!/usr/bin/env python3
"""Simple test to verify schema reference system is working."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))

from flask import Flask
from swagger_wrapper import extract_route_info, swagger_route
import json

app = Flask(__name__)

@app.route('/api/chat', methods=['POST']) 
@swagger_route(summary='Chat endpoint')
def test_chat():
    return {}

with app.app_context():
    spec = extract_route_info(app)
    
# Check schema references
paths = spec.get('paths', {})
if '/api/chat' in paths:
    chat_op = paths['/api/chat'].get('post', {})
    req_body = chat_op.get('requestBody', {})
    schema = req_body.get('content', {}).get('application/json', {}).get('schema', {})
    
    print('🔍 Chat endpoint request body schema:')
    if '$ref' in schema:
        ref_value = schema['$ref']
        print(f'   ✅ Uses schema reference: {ref_value}')
    else:
        print(f'   ⚠️  Uses inline schema: {schema}')

# Check components
schemas = spec.get('components', {}).get('schemas', {})
print(f'\n📋 Available schemas: {list(schemas.keys())}')

if 'ChatRequest' in schemas:
    chat_req = schemas['ChatRequest']
    props = chat_req.get('properties', {})
    
    print('\n🔍 ChatRequest schema properties:')
    for prop, def_ in props.items():
        nullable = def_.get('nullable', False)
        type_ = def_.get('type', 'unknown')
        enum = def_.get('enum')
        
        status = '✅' if nullable or enum or prop == 'message' else '⚠️'
        extra = ''
        if nullable:
            extra += ' (nullable)'
        if enum:
            extra += f' (enum: {enum})'
            
        print(f'   {status} {prop}: {type_}{extra}')
else:
    print('   ❌ ChatRequest schema not found')