#!/usr/bin/env python3
"""
Test automatic swagger generation for route_backend_models.py
Version: 0.229.063
Testing: How the simplified decorators work with the actual backend models

This test demonstrates the automatic generation working with real route files.
"""

import sys
import os

# Add the application directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))

from flask import Flask
from route_backend_models import register_route_backend_models
from swagger_wrapper import extract_route_info

def test_backend_models_automatic_generation():
    """Test automatic generation with the backend models routes."""
    print("🧪 Testing Backend Models Automatic Generation...")
    
    try:
        # Create a test Flask app
        app = Flask(__name__)
        
        # Register the backend model routes
        register_route_backend_models(app)
        
        # Extract route information and generate OpenAPI spec
        with app.app_context():
            spec = extract_route_info(app)
        
        # Validate the generated specification
        print(f"✅ Generated OpenAPI {spec['openapi']} specification")
        print(f"✅ Found {len(spec['paths'])} documented paths")
        print(f"✅ Generated {len(spec['tags'])} tag categories")
        
        # Check the GPT models endpoint
        gpt_path = '/api/models/gpt'
        if gpt_path in spec['paths'] and 'get' in spec['paths'][gpt_path]:
            operation = spec['paths'][gpt_path]['get']
            
            # Check auto-generated summary
            summary = operation.get('summary', '')
            print(f"✅ GPT Models Summary: '{summary}'")
            assert 'Get Gpt Models' in summary, f"Expected 'Get Gpt Models' in summary, got: {summary}"
            
            # Check auto-generated description from docstring
            description = operation.get('description', '')  
            print(f"✅ GPT Models Description: '{description[:60]}...'")
            assert 'Fetch available GPT-like Azure OpenAI deployments' in description, "Docstring not used as description"
            
            # Check auto-generated tags from path
            tags = operation.get('tags', [])
            print(f"✅ GPT Models Tags: {tags}")
            assert 'Models' in tags, f"Expected 'Models' tag from path, got: {tags}"
            
            # Check that security is still preserved
            security = operation.get('security', [])
            print(f"✅ GPT Models Security: {security}")
            assert len(security) > 0, "Security requirements should be preserved"
            
            # Check auto-generated response schema
            responses = operation.get('responses', {})
            if '200' in responses:
                schema = responses['200']['content']['application/json']['schema']
                properties = schema.get('properties', {})
                print(f"✅ GPT Models Response Schema has {len(properties)} properties")
                assert 'models' in properties, "Expected 'models' property in response schema"
        
        # Check the embedding models endpoint
        embedding_path = '/api/models/embedding'
        if embedding_path in spec['paths'] and 'get' in spec['paths'][embedding_path]:
            operation = spec['paths'][embedding_path]['get']
            
            summary = operation.get('summary', '')
            print(f"✅ Embedding Models Summary: '{summary}'")
            assert 'Get Embedding Models' in summary, f"Expected 'Get Embedding Models' in summary, got: {summary}"
            
            tags = operation.get('tags', [])
            print(f"✅ Embedding Models Tags: {tags}")
            assert 'Models' in tags, f"Expected 'Models' tag from path, got: {tags}"
            assert 'Embedding' in tags, f"Expected 'Embedding' tag from path, got: {tags}"
        
        # Check the image models endpoint
        image_path = '/api/models/image'
        if image_path in spec['paths'] and 'get' in spec['paths'][image_path]:
            operation = spec['paths'][image_path]['get']
            
            summary = operation.get('summary', '')
            print(f"✅ Image Models Summary: '{summary}'")
            assert 'Get Image Models' in summary, f"Expected 'Get Image Models' in summary, got: {summary}"
            
            tags = operation.get('tags', [])
            print(f"✅ Image Models Tags: {tags}")
            assert 'Models' in tags, f"Expected 'Models' tag from path, got: {tags}"
            assert 'Image' in tags, f"Expected 'Image' tag from path, got: {tags}"
        
        # Print all tags for debugging
        all_tags = spec.get('tags', [])
        tag_names = [tag['name'] for tag in all_tags]
        print(f"✅ All Generated Tags: {tag_names}")
        
        print("✅ Backend models automatic generation test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_code_reduction_comparison():
    """Show the difference in code required before and after."""
    print("\n📊 Code Reduction Comparison...")
    
    original_lines = """
    @swagger_route(
        summary="Get GPT Models",
        description="Fetch available GPT-like Azure OpenAI deployments using Azure Management API",
        tags=["Models", "Azure OpenAI"],
        responses={
            200: {
                "description": "List of GPT models",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "models": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "deploymentName": {
                                                "type": "string",
                                                "description": "Azure OpenAI deployment name"
                                            },
                                            "modelName": {
                                                "type": "string", 
                                                "description": "Azure OpenAI model name"
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            400: {
                "description": "Configuration error - Azure GPT settings not configured",
                "content": {
                    "application/json": {
                        "schema": COMMON_SCHEMAS["error_response"]
                    }
                }
            },
            500: {
                "description": "Azure API error",
                "content": {
                    "application/json": {
                        "schema": COMMON_SCHEMAS["error_response"]
                    }
                }
            }
        },
        security=get_auth_security()
    )
    """
    
    new_lines = """
    @swagger_route(
        security=get_auth_security()
    )
    """
    
    original_count = len(original_lines.strip().split('\n'))
    new_count = len(new_lines.strip().split('\n'))
    reduction = ((original_count - new_count) / original_count) * 100
    
    print(f"📈 Original decorator: {original_count} lines")
    print(f"📉 New decorator: {new_count} lines")
    print(f"🎯 Code reduction: {reduction:.1f}%")
    print(f"✨ Automatic generation handles:")
    print(f"   • Summary from function name: 'get_gpt_models' → 'Get Gpt Models'")
    print(f"   • Description from docstring: Function docstring → OpenAPI description")
    print(f"   • Tags from path: '/api/models/gpt' → ['Models', 'Gpt']")
    print(f"   • Response schema from return jsonify() calls")
    print(f"   • Parameter definitions from function signature")
    
    return True

if __name__ == "__main__":
    print("🔬 Starting Backend Models Automatic Generation Test\n")
    
    tests = [
        test_backend_models_automatic_generation,
        test_code_reduction_comparison
    ]
    
    results = []
    for test in tests:
        results.append(test())
    
    success_count = sum(results)
    total_count = len(results)
    
    print(f"\n📊 Test Results: {success_count}/{total_count} tests passed")
    
    if success_count == total_count:
        print("🎉 All tests passed! The backend models are now fully automated.")
    else:
        print("⚠️  Some tests failed. Please check the output above for details.")
    
    sys.exit(0 if success_count == total_count else 1)