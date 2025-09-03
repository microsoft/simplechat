"""
OpenAPI Authentication Analyzer

This module analyzes OpenAPI specifications to extract and suggest authentication configurations.
"""

def analyze_openapi_authentication(spec):
    """
    Analyze an OpenAPI spec to extract authentication schemes and suggest configuration.
    
    Args:
        spec: Parsed OpenAPI specification (dict)
        
    Returns:
        dict: Authentication analysis with suggested configurations
    """
    result = {
        'has_authentication': False,
        'security_schemes': [],
        'suggested_auth': None,
        'all_auth_options': []
    }
    
    try:
        # Check for security schemes in components
        components = spec.get('components', {})
        security_schemes = components.get('securitySchemes', {})
        
        if not security_schemes:
            return result
        
        result['has_authentication'] = True
        
        # Analyze each security scheme
        for scheme_name, scheme_config in security_schemes.items():
            scheme_type = scheme_config.get('type', '').lower()
            scheme_info = {
                'name': scheme_name,
                'type': scheme_type,
                'original_config': scheme_config
            }
            
            # Map OpenAPI security schemes to our authentication types
            if scheme_type == 'apikey':
                location = scheme_config.get('in', 'header').lower()
                param_name = scheme_config.get('name', 'api-key')
                
                auth_config = {
                    'type': 'key',  # Our simplified format
                    'key': '',  # Placeholder - user will fill this
                    'location': location,
                    'name': param_name
                }
                
                scheme_info.update({
                    'mapped_type': 'key',
                    'suggested_config': auth_config,
                    'description': f"API Key in {location} parameter '{param_name}'",
                    'user_friendly_name': f"API Key ({location.title()}: {param_name})"
                })
                
                # If this is a query parameter named 'api-key', make it the primary suggestion
                if location == 'query' and 'api' in param_name.lower():
                    result['suggested_auth'] = auth_config
                    
            elif scheme_type == 'http':
                bearer_format = scheme_config.get('scheme', '').lower()
                
                if bearer_format == 'bearer':
                    auth_config = {
                        'type': 'bearer',
                        'token': ''  # Placeholder - user will fill this
                    }
                    
                    scheme_info.update({
                        'mapped_type': 'bearer',
                        'suggested_config': auth_config,
                        'description': 'Bearer token authentication',
                        'user_friendly_name': 'Bearer Token'
                    })
                    
                elif bearer_format == 'basic':
                    auth_config = {
                        'type': 'basic',
                        'username': '',  # Placeholder - user will fill this
                        'password': ''   # Placeholder - user will fill this
                    }
                    
                    scheme_info.update({
                        'mapped_type': 'basic',
                        'suggested_config': auth_config,
                        'description': 'Basic HTTP authentication',
                        'user_friendly_name': 'Basic Authentication'
                    })
                    
            elif scheme_type == 'oauth2':
                auth_config = {
                    'type': 'oauth2',
                    'token': ''  # Placeholder - user will fill this
                }
                
                scheme_info.update({
                    'mapped_type': 'oauth2',
                    'suggested_config': auth_config,
                    'description': 'OAuth2 authentication',
                    'user_friendly_name': 'OAuth2'
                })
            
            result['security_schemes'].append(scheme_info)
            
            # Add to all auth options if we have a mapped type
            if 'suggested_config' in scheme_info:
                result['all_auth_options'].append({
                    'name': scheme_info['user_friendly_name'],
                    'description': scheme_info['description'],
                    'config': scheme_info['suggested_config']
                })
        
        # If no primary suggestion was set, use the first available option
        if not result['suggested_auth'] and result['all_auth_options']:
            result['suggested_auth'] = result['all_auth_options'][0]['config']
            
        # Sort auth options by preference (API key query params first, then headers, then others)
        result['all_auth_options'].sort(key=lambda x: _get_auth_priority(x['config']))
        
    except Exception as e:
        # If analysis fails, return empty result but don't crash
        result['error'] = f"Failed to analyze authentication: {str(e)}"
    
    return result


def _get_auth_priority(auth_config):
    """
    Get priority score for authentication methods (lower = higher priority).
    """
    auth_type = auth_config.get('type', '')
    
    # Prioritize query parameter API keys (most common for simple APIs)
    if auth_type == 'key' and auth_config.get('location') == 'query':
        return 1
    
    # Then header API keys
    if auth_type == 'key' and auth_config.get('location') == 'header':
        return 2
    
    # Then bearer tokens
    if auth_type == 'bearer':
        return 3
    
    # Then basic auth
    if auth_type == 'basic':
        return 4
    
    # Everything else
    return 5


def get_authentication_help_text(auth_config):
    """
    Generate helpful instructions for the user based on the auth configuration.
    """
    auth_type = auth_config.get('type', '')
    
    if auth_type == 'key':
        location = auth_config.get('location', 'query')
        param_name = auth_config.get('name', 'api-key')
        
        if location == 'query':
            return f"Enter your API key. It will be sent as a query parameter '{param_name}' in the URL."
        else:
            return f"Enter your API key. It will be sent as a header '{param_name}' with each request."
            
    elif auth_type == 'bearer':
        return "Enter your bearer token. It will be sent in the Authorization header as 'Bearer <token>'."
        
    elif auth_type == 'basic':
        return "Enter your username and password for basic HTTP authentication."
        
    elif auth_type == 'oauth2':
        return "Enter your OAuth2 access token. It will be sent in the Authorization header."
        
    return "Authentication configuration detected. Please provide the required credentials."


def format_auth_examples():
    """
    Provide examples of common authentication patterns.
    """
    return {
        'key_query': {
            'name': 'API Key (Query Parameter)',
            'example': '?api-key=your-key-here',
            'description': 'API key sent as a URL parameter'
        },
        'key_header': {
            'name': 'API Key (Header)',
            'example': 'X-API-Key: your-key-here',
            'description': 'API key sent in request headers'
        },
        'bearer': {
            'name': 'Bearer Token',
            'example': 'Authorization: Bearer your-token-here',
            'description': 'Bearer token in Authorization header'
        },
        'basic': {
            'name': 'Basic Authentication',
            'example': 'Authorization: Basic base64(username:password)',
            'description': 'Username and password encoded in Authorization header'
        }
    }
