import logging
from typing import Dict, Any, Optional
import httpx

logger = logging.getLogger(__name__)


class ApiClient:
    """Client for making authenticated requests to backend API"""
    
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.client = httpx.AsyncClient()
    
    async def make_request(
        self, 
        method: str, 
        endpoint: str, 
        access_token: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make authenticated request to backend API"""
        
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        try:
            if method.upper() == "GET":
                response = await self.client.get(url, headers=headers, params=params)
            elif method.upper() == "POST":
                response = await self.client.post(url, headers=headers, json=data, params=params)
            elif method.upper() == "PUT":
                response = await self.client.put(url, headers=headers, json=data, params=params)
            elif method.upper() == "DELETE":
                response = await self.client.delete(url, headers=headers, params=params)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            response.raise_for_status()
            
            # Try to parse JSON, fallback to text
            try:
                return response.json()
            except Exception:
                return {"response": response.text}
                
        except httpx.HTTPStatusError as e:
            logger.error(f"API request failed: {e.response.status_code} - {e.response.text}")
            raise Exception(f"API request failed: {e.response.status_code}")
        except Exception as e:
            logger.error(f"API request error: {e}")
            raise
    
    async def get(self, endpoint: str, access_token: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make GET request"""
        return await self.make_request("GET", endpoint, access_token, params=params)
    
    async def post(self, endpoint: str, access_token: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make POST request"""
        return await self.make_request("POST", endpoint, access_token, data=data)
    
    async def put(self, endpoint: str, access_token: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make PUT request"""
        return await self.make_request("PUT", endpoint, access_token, data=data)
    
    async def delete(self, endpoint: str, access_token: str) -> Dict[str, Any]:
        """Make DELETE request"""
        return await self.make_request("DELETE", endpoint, access_token)
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()
