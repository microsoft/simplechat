"""
API Client for SimpleChat Desktop Client
Handles all API interactions with the Flask backend
"""

import requests
import json
from typing import Dict, List, Optional, Any
from auth_manager import AuthenticationManager
from config import FLASK_API_BASE_URL, API_ENDPOINTS


class SimpleChat_API:
    """API client for SimpleChat backend"""
    
    def __init__(self, auth_manager: AuthenticationManager):
        self.auth_manager = auth_manager
        self.base_url = FLASK_API_BASE_URL
    
    def _get_session(self):
        """Get authenticated session"""
        if not self.auth_manager.is_authenticated():
            raise Exception("Not authenticated. Please login first.")
        return self.auth_manager.get_session()
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Make authenticated request to API"""
        session = self._get_session()
        url = f"{self.base_url}{endpoint}"
        
        # Disable SSL verification for localhost development
        kwargs['verify'] = False
        
        response = session.request(method, url, **kwargs)
        return response
    
    # Chat API Methods
    def send_message(self, message: str, conversation_id: Optional[str] = None, 
                    workspace_id: Optional[str] = None) -> Dict[str, Any]:
        """Send a chat message"""
        # Use external API since we have proper token configuration
        return self._send_message_external(message, conversation_id, workspace_id)
    
    def _send_message_regular(self, message: str, conversation_id: Optional[str] = None, 
                             workspace_id: Optional[str] = None) -> Dict[str, Any]:
        """Send message using regular API endpoint"""
        data = {
            'message': message
        }
        
        if conversation_id:
            data['conversation_id'] = conversation_id
        if workspace_id:
            data['workspace_id'] = workspace_id
        
        response = self._make_request('POST', API_ENDPOINTS['chat'], json=data)
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Chat API error: {response.status_code} - {response.text}")
    
    def _send_message_external(self, message: str, conversation_id: Optional[str] = None, 
                              workspace_id: Optional[str] = None) -> Dict[str, Any]:
        """Send message using external API endpoint"""
        user_info = self.auth_manager.get_user_info()
        user_id = user_info.get('oid') if user_info else 'unknown'
        
        data = {
            'message': message,
            'user_id': user_id
        }
        
        if conversation_id:
            data['conversation_id'] = conversation_id
        if workspace_id:
            data['workspace_id'] = workspace_id
        
        # Make sure we have the access token in the Authorization header
        session = self._get_session()
        url = f"{self.base_url}/external/chat"
        
        # Ensure Authorization header is set
        headers = {
            'Authorization': f'Bearer {self.auth_manager.access_token}',
            'Content-Type': 'application/json'
        }
        
        # Disable SSL verification for localhost development
        response = session.post(url, json=data, headers=headers, verify=False)
        
        if response.status_code == 200:
            result = response.json()
            # Convert external API response to regular API format
            return {
                'conversation_id': result.get('conversation_id'),
                'response': result.get('response'),
                'timestamp': result.get('timestamp')
            }
        else:
            raise Exception(f"External Chat API error: {response.status_code} - {response.text}")
    
    # Document API Methods
    def get_documents(self) -> List[Dict[str, Any]]:
        """Get list of documents"""
        response = self._make_request('GET', API_ENDPOINTS['documents'])
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Documents API error: {response.status_code} - {response.text}")
    
    def upload_document(self, file_path: str, title: str = None) -> Dict[str, Any]:
        """Upload a document"""
        with open(file_path, 'rb') as file:
            files = {'file': file}
            data = {}
            if title:
                data['title'] = title
            
            response = self._make_request('POST', f"{API_ENDPOINTS['documents']}/upload", 
                                        files=files, data=data)
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Document upload error: {response.status_code} - {response.text}")
    
    def delete_document(self, document_id: str) -> bool:
        """Delete a document"""
        response = self._make_request('DELETE', f"{API_ENDPOINTS['documents']}/{document_id}")
        
        if response.status_code == 200:
            return True
        else:
            raise Exception(f"Document delete error: {response.status_code} - {response.text}")
    
    # Prompt API Methods
    def get_prompts(self) -> List[Dict[str, Any]]:
        """Get list of prompts"""
        response = self._make_request('GET', API_ENDPOINTS['prompts'])
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Prompts API error: {response.status_code} - {response.text}")
    
    def create_prompt(self, title: str, content: str, description: str = None) -> Dict[str, Any]:
        """Create a new prompt"""
        data = {
            'title': title,
            'content': content
        }
        if description:
            data['description'] = description
        
        response = self._make_request('POST', API_ENDPOINTS['prompts'], json=data)
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Create prompt error: {response.status_code} - {response.text}")
    
    def update_prompt(self, prompt_id: str, title: str = None, content: str = None, 
                     description: str = None) -> Dict[str, Any]:
        """Update an existing prompt"""
        data = {}
        if title:
            data['title'] = title
        if content:
            data['content'] = content
        if description:
            data['description'] = description
        
        response = self._make_request('PATCH', f"{API_ENDPOINTS['prompts']}/{prompt_id}", json=data)
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Update prompt error: {response.status_code} - {response.text}")
    
    def delete_prompt(self, prompt_id: str) -> bool:
        """Delete a prompt"""
        response = self._make_request('DELETE', f"{API_ENDPOINTS['prompts']}/{prompt_id}")
        
        if response.status_code == 200:
            return True
        else:
            raise Exception(f"Delete prompt error: {response.status_code} - {response.text}")
    
    # Conversation API Methods
    def get_conversations(self) -> List[Dict[str, Any]]:
        """Get list of conversations"""
        response = self._make_request('GET', API_ENDPOINTS['conversations'])
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Conversations API error: {response.status_code} - {response.text}")
    
    def get_conversation(self, conversation_id: str) -> Dict[str, Any]:
        """Get specific conversation details"""
        response = self._make_request('GET', f"{API_ENDPOINTS['conversations']}/{conversation_id}")
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Conversation API error: {response.status_code} - {response.text}")
    
    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation"""
        response = self._make_request('DELETE', f"{API_ENDPOINTS['conversations']}/{conversation_id}")
        
        if response.status_code == 200:
            return True
        else:
            raise Exception(f"Delete conversation error: {response.status_code} - {response.text}")
    
    # Group API Methods  
    def get_groups(self) -> List[Dict[str, Any]]:
        """Get list of groups"""
        response = self._make_request('GET', API_ENDPOINTS['groups'])
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Groups API error: {response.status_code} - {response.text}")
    
    # Settings API Methods
    def get_settings(self) -> Dict[str, Any]:
        """Get application settings"""
        response = self._make_request('GET', API_ENDPOINTS['settings'])
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Settings API error: {response.status_code} - {response.text}")
    
    # Health Check
    def health_check(self) -> bool:
        """Check if API is accessible"""
        try:
            # First try the root endpoint which we know works
            session = self._get_session()
            response = session.get(f"{self.base_url.rstrip('/')}/", verify=False, timeout=10)
            
            if response.status_code == 200:
                print("✓ Root endpoint accessible")
                return True
            
            # If root fails, try other endpoints
            test_endpoints = ['/api/prompts', '/api/documents']
            
            for endpoint in test_endpoints:
                try:
                    response = session.get(f"{self.base_url.rstrip('/')}{endpoint}", verify=False, timeout=5)
                    # Even 401 (unauthorized) means the endpoint exists and the server is running
                    if response.status_code in [200, 401]:
                        print(f"✓ API endpoint {endpoint} is accessible")
                        return True
                except Exception:
                    continue
            
            return False
            
        except Exception as e:
            print(f"Health check failed: {e}")
            return False
    
    def test_connection(self) -> Dict[str, Any]:
        """Test API connection and return detailed status"""
        try:
            if not self.auth_manager.is_authenticated():
                return {
                    'success': False,
                    'message': 'Not authenticated',
                    'details': 'Please login first'
                }
            
            session = self._get_session()
            results = {
                'success': False,
                'message': '',
                'details': '',
                'endpoints': {}
            }
            
            # Test root endpoint
            try:
                response = session.get(f"{self.base_url.rstrip('/')}/", verify=False, timeout=10)
                results['endpoints']['/'] = {
                    'status': response.status_code,
                    'accessible': response.status_code == 200
                }
                if response.status_code == 200:
                    results['success'] = True
                    results['message'] = 'API connection successful'
            except Exception as e:
                results['endpoints']['/'] = {
                    'status': 'error',
                    'accessible': False,
                    'error': str(e)
                }
            
            # Test API endpoints
            test_endpoints = ['/api/prompts', '/api/documents']
            
            for endpoint in test_endpoints:
                try:
                    response = session.get(f"{self.base_url.rstrip('/')}{endpoint}", verify=False, timeout=5)
                    results['endpoints'][endpoint] = {
                        'status': response.status_code,
                        'accessible': response.status_code in [200, 401]  # 401 means it exists but needs auth
                    }
                    if response.status_code in [200, 401]:
                        results['success'] = True
                        if not results['message']:
                            results['message'] = 'API endpoints accessible'
                except Exception as e:
                    results['endpoints'][endpoint] = {
                        'status': 'error',
                        'accessible': False,
                        'error': str(e)
                    }
            
            if not results['success']:
                results['message'] = 'API connection failed'
                results['details'] = 'Unable to connect to any API endpoints'
            else:
                # Count accessible endpoints
                accessible_count = sum(1 for ep_data in results['endpoints'].values() if ep_data.get('accessible', False))
                results['details'] = f'Successfully connected to {accessible_count} endpoint(s)'
            
            return results
            
        except Exception as e:
            return {
                'success': False,
                'message': 'Connection test failed',
                'details': str(e),
                'endpoints': {}
            }
