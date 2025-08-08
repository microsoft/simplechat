"""
SimpleChat Desktop Client Configuration
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Flask API Configuration
FLASK_API_BASE_URL = os.getenv('FLASK_API_BASE_URL', 'https://localhost:5000')

# Azure AD Configuration  
CLIENT_ID = os.getenv('CLIENT_ID')
TENANT_ID = os.getenv('TENANT_ID')
AZURE_ENVIRONMENT = os.getenv('AZURE_ENVIRONMENT', 'public')

# Redirect URIs for desktop applications
# The first one is the preferred, but we'll let MSAL choose the best one
REDIRECT_URIS = [
    "msal://redirect",  # Standard for native/desktop apps
    "http://localhost",  # Fallback for local development
    "https://login.microsoftonline.com/common/oauth2/nativeclient"  # MSAL default
]

# MSAL Authority URL based on environment
if AZURE_ENVIRONMENT == 'usgovernment':
    AUTHORITY_URL = f"https://login.microsoftonline.us/{TENANT_ID}"
else:
    AUTHORITY_URL = f"https://login.microsoftonline.com/{TENANT_ID}"

# Scopes for API access (must match Flask backend scopes)
# Request tokens for SimpleChat application using GUID-based identifier
SCOPES = [
    f"{CLIENT_ID}/.default"  # Use GUID-based App Identifier as required by Azure AD
]

# API Endpoints
API_ENDPOINTS = {
    'login': '/login',
    'logout': '/logout',
    'chat': '/api/chat',
    'documents': '/api/documents',
    'prompts': '/api/prompts',
    'groups': '/api/groups',
    'conversations': '/api/conversations',
    'settings': '/api/settings'
}

# UI Configuration
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 800
WINDOW_TITLE = "SimpleChat Desktop Client"
WINDOW_TITLE = "SimpleChat Desktop Client"

# Session Configuration
SESSION_TIMEOUT = 3600  # 1 hour in seconds
