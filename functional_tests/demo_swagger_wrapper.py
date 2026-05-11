#!/usr/bin/env python3
"""
Demo script for Swagger Route Wrapper System
Version: 0.229.061

This script demonstrates the swagger wrapper system by starting a minimal Flask app
with documented routes that you can interact with.
"""

import sys
import os
from flask import Flask, jsonify, request

# Add the application directory to the path
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

from swagger_wrapper import (
    swagger_route, 
    register_swagger_routes, 
    create_parameter,
    get_auth_security,
    COMMON_SCHEMAS
)

def create_demo_app():
    """Create a demo Flask app with documented routes."""
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'demo-secret-key'
    
    # Register swagger routes
    register_swagger_routes(app)
    
    # Demo route 1: Simple GET endpoint
    @app.route('/api/demo/hello', methods=['GET'])
    @swagger_route(
        summary="Hello World Demo",
        description="Returns a simple greeting message",
        tags=["Demo", "Simple"],
        responses={
            200: {
                "description": "Greeting message",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "message": {"type": "string"},
                                "timestamp": {"type": "string", "format": "date-time"}
                            }
                        }
                    }
                }
            }
        }
    )
    def hello_demo():
        from datetime import datetime
        return jsonify({
            "message": "Hello from Swagger-documented API!",
            "timestamp": datetime.now().isoformat()
        })
    
    # Demo route 2: GET with parameters
    @app.route('/api/demo/greet/<name>', methods=['GET'])
    @swagger_route(
        summary="Personalized Greeting",
        description="Returns a personalized greeting with optional formatting",
        tags=["Demo", "Personalization"],
        parameters=[
            create_parameter("name", "path", "string", True, "Name to greet"),
            create_parameter("format", "query", "string", False, "Greeting format (formal, casual)"),
            create_parameter("lang", "query", "string", False, "Language code (en, es, fr)")
        ],
        responses={
            200: {
                "description": "Personalized greeting",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "greeting": {"type": "string"},
                                "name": {"type": "string"},
                                "format": {"type": "string"},
                                "language": {"type": "string"}
                            }
                        }
                    }
                }
            },
            400: {
                "description": "Invalid parameters",
                "content": {
                    "application/json": {
                        "schema": COMMON_SCHEMAS["error_response"]
                    }
                }
            }
        }
    )
    def greet_demo(name):
        format_type = request.args.get('format', 'casual')
        lang = request.args.get('lang', 'en')
        
        if not name or len(name.strip()) == 0:
            return jsonify({"error": "Name cannot be empty"}), 400
        
        greetings = {
            'en': {
                'formal': f"Good day, {name}",
                'casual': f"Hey there, {name}!"
            },
            'es': {
                'formal': f"Buenos días, {name}",
                'casual': f"¡Hola, {name}!"
            },
            'fr': {
                'formal': f"Bonjour, {name}",
                'casual': f"Salut, {name}!"
            }
        }
        
        greeting = greetings.get(lang, greetings['en']).get(format_type, greetings['en']['casual'])
        
        return jsonify({
            "greeting": greeting,
            "name": name,
            "format": format_type,
            "language": lang
        })
    
    # Demo route 3: POST with request body
    @app.route('/api/demo/calculate', methods=['POST'])
    @swagger_route(
        summary="Simple Calculator",
        description="Performs basic arithmetic operations on two numbers",
        tags=["Demo", "Calculator"],
        request_body={
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "First number"},
                "b": {"type": "number", "description": "Second number"},
                "operation": {
                    "type": "string", 
                    "enum": ["add", "subtract", "multiply", "divide"],
                    "description": "Arithmetic operation to perform"
                }
            },
            "required": ["a", "b", "operation"]
        },
        responses={
            200: {
                "description": "Calculation result",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "result": {"type": "number"},
                                "operation": {"type": "string"},
                                "operands": {
                                    "type": "object",
                                    "properties": {
                                        "a": {"type": "number"},
                                        "b": {"type": "number"}
                                    }
                                }
                            }
                        }
                    }
                }
            },
            400: {
                "description": "Invalid input or division by zero",
                "content": {
                    "application/json": {
                        "schema": COMMON_SCHEMAS["error_response"]
                    }
                }
            }
        }
    )
    def calculate_demo():
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "JSON body required"}), 400
        
        try:
            a = float(data.get('a'))
            b = float(data.get('b'))
            operation = data.get('operation')
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid number format"}), 400
        
        if operation not in ['add', 'subtract', 'multiply', 'divide']:
            return jsonify({"error": "Invalid operation. Use: add, subtract, multiply, divide"}), 400
        
        if operation == 'divide' and b == 0:
            return jsonify({"error": "Division by zero not allowed"}), 400
        
        operations = {
            'add': a + b,
            'subtract': a - b,
            'multiply': a * b,
            'divide': a / b
        }
        
        result = operations[operation]
        
        return jsonify({
            "result": result,
            "operation": operation,
            "operands": {"a": a, "b": b}
        })
    
    # Demo route 4: Undocumented route (for comparison)
    @app.route('/api/demo/undocumented', methods=['GET'])
    def undocumented_demo():
        """This route intentionally has no swagger documentation."""
        return jsonify({"message": "This route is not documented in Swagger"})
    
    return app

def main():
    """Run the demo application."""
    print("🚀 Starting Swagger Route Wrapper Demo...")
    print("=" * 60)
    
    app = create_demo_app()
    
    print("📋 Demo endpoints available:")
    print("  • GET  /api/demo/hello")
    print("  • GET  /api/demo/greet/<name>?format=casual&lang=en")
    print("  • POST /api/demo/calculate")
    print("  • GET  /api/demo/undocumented")
    print()
    print("📖 Swagger documentation:")
    print("  • Interactive UI: http://localhost:5001/swagger")  
    print("  • JSON spec:     http://localhost:5001/swagger.json")
    print("  • Route status:  http://localhost:5001/api/swagger/routes")
    print()
    print("🧪 Try these examples:")
    print("  curl http://localhost:5001/api/demo/hello")
    print("  curl http://localhost:5001/api/demo/greet/Alice?format=formal&lang=es")
    print("  curl -X POST http://localhost:5001/api/demo/calculate \\")
    print("       -H 'Content-Type: application/json' \\")
    print("       -d '{\"a\": 10, \"b\": 5, \"operation\": \"multiply\"}'")
    print()
    print("Press Ctrl+C to stop the server")
    print("=" * 60)
    
    try:
        app.run(host='0.0.0.0', port=5001, debug=True)
    except KeyboardInterrupt:
        print("\n👋 Demo stopped. Thanks for trying the Swagger Route Wrapper!")

if __name__ == '__main__':
    main()