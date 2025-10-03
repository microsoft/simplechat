# config.py
import logging
import os
import requests
import uuid
import tempfile
import json
import time
import threading
import random
import base64
import markdown2
import re
import docx
import fitz # PyMuPDF
import math
import mimetypes
import openpyxl
import xlrd
import traceback
import subprocess
import ffmpeg_binaries as ffmpeg_bin
ffmpeg_bin.init()
import ffmpeg as ffmpeg_py
import glob
import jwt
import pandas

# Add dotenv import
from dotenv import load_dotenv

from flask import (
    Flask, 
    flash, 
    request, 
    jsonify, 
    render_template, 
    redirect, 
    url_for, 
    session, 
    send_from_directory, 
    send_file, 
    Markup,
    current_app
)
from werkzeug.utils import secure_filename
from datetime import datetime, timezone, timedelta
from functools import wraps
from msal import ConfidentialClientApplication, SerializableTokenCache
from flask_session import Session
from uuid import uuid4
from threading import Thread
from openai import AzureOpenAI, RateLimitError
from cryptography.fernet import Fernet, InvalidToken
from urllib.parse import quote
from flask_executor import Executor
from bs4 import BeautifulSoup
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
    MarkdownHeaderTextSplitter,
    RecursiveJsonSplitter
)
from PIL import Image
from io import BytesIO
from typing import List

from azure.cosmos import CosmosClient, PartitionKey, exceptions
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.search.documents import SearchClient, IndexDocumentsBatch
from azure.search.documents.models import VectorizedQuery
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import SearchIndex, SearchField, SearchFieldDataType
from azure.core.exceptions import AzureError, ResourceNotFoundError, HttpResponseError, ServiceRequestError
from azure.core.polling import LROPoller
from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
from azure.identity import ClientSecretCredential, DefaultAzureCredential, get_bearer_token_provider, AzureAuthorityHosts
from azure.ai.contentsafety import ContentSafetyClient
from azure.ai.contentsafety.models import AnalyzeTextOptions, TextCategory
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions

# Load environment variables from .env file
load_dotenv()

# Flask app configuration constants
EXECUTOR_TYPE = 'thread'
EXECUTOR_MAX_WORKERS = 30
SESSION_TYPE = 'filesystem'
VERSION = "0.229.063"


SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

# Security Headers Configuration
SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'X-XSS-Protection': '1; mode=block',
    'Referrer-Policy': 'strict-origin-when-cross-origin',
    'Content-Security-Policy': (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://code.jquery.com https://stackpath.bootstrapcdn.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://stackpath.bootstrapcdn.com; "
        "img-src 'self' data: https: blob:; "
        "font-src 'self' https://cdn.jsdelivr.net https://stackpath.bootstrapcdn.com; "
        "connect-src 'self' https: wss: ws:; "
        "media-src 'self' blob:; "
        "object-src 'none'; "
        "frame-ancestors 'self'; "
        "base-uri 'self';"
    )
}

# Security Configuration
ENABLE_STRICT_TRANSPORT_SECURITY = os.getenv('ENABLE_HSTS', 'false').lower() == 'true'
HSTS_MAX_AGE = int(os.getenv('HSTS_MAX_AGE', '31536000'))  # 1 year default

CLIENTS = {}
CLIENTS_LOCK = threading.Lock()

ALLOWED_EXTENSIONS = {
    'txt', 'pdf', 'docx', 'xlsx', 'xls', 'csv', 'pptx', 'html', 'jpg', 'jpeg', 'png', 'bmp', 'tiff', 'tif', 'heif', 'md', 'json', 
    'mp4', 'mov', 'avi', 'mkv', 'flv', 'mxf', 'gxf', 'ts', 'ps', '3gp', '3gpp', 'mpg', 'wmv', 'asf', 'm4a', 'm4v', 'isma', 'ismv', 
    'dvr-ms', 'wav'
}
ALLOWED_EXTENSIONS_IMG = {'png', 'jpg', 'jpeg'}
MAX_CONTENT_LENGTH = 5000 * 1024 * 1024  # 5000 MB AKA 5 GB

# Add Support for Custom Azure Environments
CUSTOM_GRAPH_URL_VALUE = os.getenv("CUSTOM_GRAPH_URL_VALUE", "")
CUSTOM_IDENTITY_URL_VALUE = os.getenv("CUSTOM_IDENTITY_URL_VALUE", "")
CUSTOM_RESOURCE_MANAGER_URL_VALUE = os.getenv("CUSTOM_RESOURCE_MANAGER_URL_VALUE", "")
CUSTOM_BLOB_STORAGE_URL_VALUE = os.getenv("CUSTOM_BLOB_STORAGE_URL_VALUE", "")
CUSTOM_COGNITIVE_SERVICES_URL_VALUE = os.getenv("CUSTOM_COGNITIVE_SERVICES_URL_VALUE", "")
CUSTOM_SEARCH_RESOURCE_MANAGER_URL_VALUE = os.getenv("CUSTOM_SEARCH_RESOURCE_MANAGER_URL_VALUE", "")


# Azure AD Configuration
CLIENT_ID = os.getenv("CLIENT_ID")
APP_URI = f"api://{CLIENT_ID}"
CLIENT_SECRET = os.getenv("MICROSOFT_PROVIDER_AUTHENTICATION_SECRET")
TENANT_ID = os.getenv("TENANT_ID")
SCOPE = ["User.Read", "User.ReadBasic.All", "People.Read.All", "Group.Read.All"] # Adjust scope according to your needs
MICROSOFT_PROVIDER_AUTHENTICATION_SECRET = os.getenv("MICROSOFT_PROVIDER_AUTHENTICATION_SECRET")
LOGIN_REDIRECT_URL = os.getenv("LOGIN_REDIRECT_URL")
HOME_REDIRECT_URL = os.getenv("HOME_REDIRECT_URL")  # Front Door URL for home page

OIDC_METADATA_URL = f"https://login.microsoftonline.com/{TENANT_ID}/v2.0/.well-known/openid-configuration"
AZURE_ENVIRONMENT = os.getenv("AZURE_ENVIRONMENT", "public") # public, usgovernment, custom

if AZURE_ENVIRONMENT == "custom":
    AUTHORITY = f"{CUSTOM_IDENTITY_URL_VALUE}/{TENANT_ID}"
else:
    AUTHORITY = f"https://login.microsoftonline.us/{TENANT_ID}"

# Commercial Azure Video Indexer Endpoint
video_indexer_endpoint = "https://api.videoindexer.ai"

WORD_CHUNK_SIZE = 400

if AZURE_ENVIRONMENT == "usgovernment":
    OIDC_METADATA_URL = f"https://login.microsoftonline.us/{TENANT_ID}/v2.0/.well-known/openid-configuration"
    resource_manager = "https://management.usgovcloudapi.net"
    authority = AzureAuthorityHosts.AZURE_GOVERNMENT
    credential_scopes=[resource_manager + "/.default"]
    cognitive_services_scope = "https://cognitiveservices.azure.us/.default"
    video_indexer_endpoint = "https://api.videoindexer.ai.azure.us"
    search_resource_manager = "https://search.azure.us"

elif AZURE_ENVIRONMENT == "custom":
    resource_manager = CUSTOM_RESOURCE_MANAGER_URL_VALUE
    authority = CUSTOM_IDENTITY_URL_VALUE
    credential_scopes=[resource_manager + "/.default"]
    cognitive_services_scope = CUSTOM_COGNITIVE_SERVICES_URL_VALUE  
    search_resource_manager = CUSTOM_SEARCH_RESOURCE_MANAGER_URL_VALUE
else:
    OIDC_METADATA_URL = f"https://login.microsoftonline.com/{TENANT_ID}/v2.0/.well-known/openid-configuration"
    resource_manager = "https://management.azure.com"
    authority = AzureAuthorityHosts.AZURE_PUBLIC_CLOUD
    credential_scopes=[resource_manager + "/.default"]
    cognitive_services_scope = "https://cognitiveservices.azure.com/.default"

storage_account_user_documents_container_name = "user-documents"
storage_account_group_documents_container_name = "group-documents"
storage_account_public_documents_container_name = "public-documents"

# Initialize Azure Cosmos DB client
cosmos_endpoint = os.getenv("AZURE_COSMOS_ENDPOINT")
cosmos_key = os.getenv("AZURE_COSMOS_KEY")
cosmos_authentication_type = os.getenv("AZURE_COSMOS_AUTHENTICATION_TYPE", "key") #key or managed_identity

if cosmos_authentication_type == "managed_identity":
    cosmos_client = CosmosClient(cosmos_endpoint, credential=DefaultAzureCredential(), consistency_level="Session")
else:
    cosmos_client = CosmosClient(cosmos_endpoint, cosmos_key, consistency_level="Session")

cosmos_database_name = "SimpleChat"
cosmos_database = cosmos_client.create_database_if_not_exists(cosmos_database_name)

cosmos_conversations_container_name = "conversations"
cosmos_conversations_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_conversations_container_name,
    partition_key=PartitionKey(path="/id")
)

cosmos_messages_container_name = "messages"
cosmos_messages_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_messages_container_name,
    partition_key=PartitionKey(path="/conversation_id")
)


cosmos_settings_container_name = "settings"
cosmos_settings_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_settings_container_name,
    partition_key=PartitionKey(path="/id")
)

cosmos_groups_container_name = "groups"
cosmos_groups_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_groups_container_name,
    partition_key=PartitionKey(path="/id")
)

cosmos_public_workspaces_container_name = "public_workspaces"
cosmos_public_workspaces_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_public_workspaces_container_name,
    partition_key=PartitionKey(path="/id")
)

cosmos_user_documents_container_name = "documents"
cosmos_user_documents_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_user_documents_container_name,
    partition_key=PartitionKey(path="/id")
)

cosmos_group_documents_container_name = "group_documents"
cosmos_group_documents_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_group_documents_container_name,
    partition_key=PartitionKey(path="/id")
)

cosmos_public_documents_container_name = "public_documents"
cosmos_public_documents_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_public_documents_container_name,
    partition_key=PartitionKey(path="/id")
)

cosmos_user_settings_container_name = "user_settings"
cosmos_user_settings_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_user_settings_container_name,
    partition_key=PartitionKey(path="/id")
)

cosmos_safety_container_name = "safety"
cosmos_safety_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_safety_container_name,
    partition_key=PartitionKey(path="/id")
)

cosmos_feedback_container_name = "feedback"
cosmos_feedback_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_feedback_container_name,
    partition_key=PartitionKey(path="/id")
)

cosmos_archived_conversations_container_name = "archived_conversations"
cosmos_archived_conversations_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_archived_conversations_container_name,
    partition_key=PartitionKey(path="/id")
)

cosmos_archived_messages_container_name = "archived_messages"
cosmos_archived_messages_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_archived_messages_container_name,
    partition_key=PartitionKey(path="/conversation_id")
)

cosmos_user_prompts_container_name = "prompts"
cosmos_user_prompts_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_user_prompts_container_name,
    partition_key=PartitionKey(path="/id")
)

cosmos_group_prompts_container_name = "group_prompts"
cosmos_group_prompts_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_group_prompts_container_name,
    partition_key=PartitionKey(path="/id")
)

cosmos_public_prompts_container_name = "public_prompts"
cosmos_public_prompts_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_public_prompts_container_name,
    partition_key=PartitionKey(path="/id")
)

cosmos_file_processing_container_name = "file_processing"
cosmos_file_processing_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_file_processing_container_name,
    partition_key=PartitionKey(path="/document_id")
)

cosmos_personal_agents_container_name = "personal_agents"
cosmos_personal_agents_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_personal_agents_container_name,
    partition_key=PartitionKey(path="/user_id")
)

cosmos_personal_actions_container_name = "personal_actions"
cosmos_personal_actions_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_personal_actions_container_name,
    partition_key=PartitionKey(path="/user_id")
)

cosmos_file_processing_container_name = "group_messages"
cosmos_file_processing_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_file_processing_container_name,
    partition_key=PartitionKey(path="/conversation_id")
)

cosmos_file_processing_container_name = "group_conversations"
cosmos_file_processing_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_file_processing_container_name,
    partition_key=PartitionKey(path="/id")
)

cosmos_group_agents_container_name = "group_agents"
cosmos_group_agents_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_group_agents_container_name,
    partition_key=PartitionKey(path="/group_id")
)

cosmos_group_actions_container_name = "group_actions"
cosmos_group_actions_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_group_actions_container_name,
    partition_key=PartitionKey(path="/group_id")
)

cosmos_global_agents_container_name = "global_agents"
cosmos_global_agents_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_global_agents_container_name,
    partition_key=PartitionKey(path="/id")
)

cosmos_global_actions_container_name = "global_actions"
cosmos_global_actions_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_global_actions_container_name,
    partition_key=PartitionKey(path="/id")
)

cosmos_agent_facts_container_name = "agent_facts"
cosmos_agent_facts_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_agent_facts_container_name,
    partition_key=PartitionKey(path="/scope_id")
)

def ensure_custom_logo_file_exists(app, settings):
    """
    If custom_logo_base64 or custom_logo_dark_base64 is present in settings, ensure the appropriate
    static files exist and reflect the current base64 data. Overwrites if necessary.
    If base64 is empty/missing, removes the corresponding file.
    """
    # Handle light mode logo
    custom_logo_b64 = settings.get('custom_logo_base64', '')
    logo_filename = 'custom_logo.png'
    logo_path = os.path.join(app.root_path, 'static', 'images', logo_filename)
    images_dir = os.path.dirname(logo_path)

    # Ensure the directory exists
    os.makedirs(images_dir, exist_ok=True)

    if not custom_logo_b64:
        # No custom logo in DB; remove the static file if it exists
        if os.path.exists(logo_path):
            try:
                os.remove(logo_path)
                print(f"Removed existing {logo_filename} as custom logo is disabled/empty.")
            except OSError as ex:
                print(f"Error removing {logo_filename}: {ex}")
    else:
        # Custom logo exists in settings, write/overwrite the file
        try:
            # Decode the current base64 string
            decoded = base64.b64decode(custom_logo_b64)

            # Write the decoded data to the file, overwriting if it exists
            with open(logo_path, 'wb') as f:
                f.write(decoded)
            print(f"Ensured {logo_filename} exists and matches current settings.")

        except (base64.binascii.Error, TypeError, OSError) as ex:
            print(f"Failed to write/overwrite {logo_filename}: {ex}")
        except Exception as ex:
            print(f"Unexpected error writing {logo_filename}: {ex}")

    # Handle dark mode logo
    custom_logo_dark_b64 = settings.get('custom_logo_dark_base64', '')
    logo_dark_filename = 'custom_logo_dark.png'
    logo_dark_path = os.path.join(app.root_path, 'static', 'images', logo_dark_filename)

    if not custom_logo_dark_b64:
        # No custom dark logo in DB; remove the static file if it exists
        if os.path.exists(logo_dark_path):
            try:
                os.remove(logo_dark_path)
                print(f"Removed existing {logo_dark_filename} as custom dark logo is disabled/empty.")
            except OSError as ex:
                print(f"Error removing {logo_dark_filename}: {ex}")
    else:
        # Custom dark logo exists in settings, write/overwrite the file
        try:
            # Decode the current base64 string
            decoded = base64.b64decode(custom_logo_dark_b64)

            # Write the decoded data to the file, overwriting if it exists
            with open(logo_dark_path, 'wb') as f:
                f.write(decoded)
            print(f"Ensured {logo_dark_filename} exists and matches current settings.")

        except (base64.binascii.Error, TypeError, OSError) as ex:
            print(f"Failed to write/overwrite {logo_dark_filename}: {ex}")
        except Exception as ex:
            print(f"Unexpected error writing {logo_dark_filename}: {ex}")

def ensure_custom_favicon_file_exists(app, settings):
    """
    If custom_favicon_base64 is present in settings, ensure static/images/favicon.ico
    exists and reflects the current base64 data. Overwrites if necessary.
    If base64 is empty/missing, uses the default favicon.
    """
    custom_favicon_b64 = settings.get('custom_favicon_base64', '')
    # Ensure the filename is consistent
    favicon_filename = 'favicon.ico'
    favicon_path = os.path.join(app.root_path, 'static', 'images', favicon_filename)
    images_dir = os.path.dirname(favicon_path)

    # Ensure the directory exists
    os.makedirs(images_dir, exist_ok=True)

    if not custom_favicon_b64:
        # No custom favicon in DB; no need to remove the static file as we want to keep the default
        return

    # Custom favicon exists in settings, write/overwrite the file
    try:
        # Decode the current base64 string
        decoded = base64.b64decode(custom_favicon_b64)

        # Write the decoded data to the file, overwriting if it exists
        with open(favicon_path, 'wb') as f:
            f.write(decoded)
        print(f"Ensured {favicon_filename} exists and matches current settings.")

    except (base64.binascii.Error, TypeError, OSError) as ex: # Catch specific errors
        print(f"Failed to write/overwrite {favicon_filename}: {ex}")
    except Exception as ex: # Catch any other unexpected errors
         print(f"Unexpected error during favicon file write for {favicon_filename}: {ex}")

def initialize_clients(settings):
    """
    Initialize/re-initialize all your clients based on the provided settings.
    Store them in a global dictionary so they're accessible throughout the app.
    """
    with CLIENTS_LOCK:
        form_recognizer_endpoint = settings.get("azure_document_intelligence_endpoint")
        form_recognizer_key = settings.get("azure_document_intelligence_key")
        enable_document_intelligence_apim = settings.get("enable_document_intelligence_apim")
        azure_apim_document_intelligence_endpoint = settings.get("azure_apim_document_intelligence_endpoint")
        azure_apim_document_intelligence_subscription_key = settings.get("azure_apim_document_intelligence_subscription_key")

        azure_ai_search_endpoint = settings.get("azure_ai_search_endpoint")
        azure_ai_search_key = settings.get("azure_ai_search_key")
        enable_ai_search_apim = settings.get("enable_ai_search_apim")
        azure_apim_ai_search_endpoint = settings.get("azure_apim_ai_search_endpoint")
        azure_apim_ai_search_subscription_key = settings.get("azure_apim_ai_search_subscription_key")

        enable_enhanced_citations = settings.get("enable_enhanced_citations")
        enable_video_file_support = settings.get("enable_video_file_support")
        enable_audio_file_support = settings.get("enable_audio_file_support")

        try:
            if enable_document_intelligence_apim:
                document_intelligence_client = DocumentIntelligenceClient(
                    endpoint=azure_apim_document_intelligence_endpoint,
                    credential=AzureKeyCredential(azure_apim_document_intelligence_subscription_key)
                )
            else:
                if settings.get("azure_document_intelligence_authentication_type") == "managed_identity":
                    if AZURE_ENVIRONMENT in ("usgovernment", "custom"):
                        document_intelligence_client = DocumentIntelligenceClient(
                            endpoint=form_recognizer_endpoint,
                            credential=DefaultAzureCredential(),
                            credential_scopes=[cognitive_services_scope],
                            api_version="2024-11-30"
                        )
                    else:
                        document_intelligence_client = DocumentIntelligenceClient(
                            endpoint=form_recognizer_endpoint,
                            credential=DefaultAzureCredential()
                        )
                else:
                    document_intelligence_client = DocumentIntelligenceClient(
                        endpoint=form_recognizer_endpoint,
                        credential=AzureKeyCredential(form_recognizer_key)
                    )
            CLIENTS["document_intelligence_client"] = document_intelligence_client
        except Exception as e:
            print(f"Failed to initialize Document Intelligence client: {e}")

        try:
            if enable_ai_search_apim:
                search_client_user = SearchClient(
                    endpoint=azure_apim_ai_search_endpoint,
                    index_name="simplechat-user-index",
                    credential=AzureKeyCredential(azure_apim_ai_search_subscription_key)
                )
                search_client_group = SearchClient(
                    endpoint=azure_apim_ai_search_endpoint,
                    index_name="simplechat-group-index",
                    credential=AzureKeyCredential(azure_apim_ai_search_subscription_key)
                )
                search_client_public = SearchClient(
                    endpoint=azure_apim_ai_search_endpoint,
                    index_name="simplechat-public-index",
                    credential=AzureKeyCredential(azure_apim_ai_search_subscription_key)
                )
            else:
                if settings.get("azure_ai_search_authentication_type") == "managed_identity":
                    if AZURE_ENVIRONMENT in ("usgovernment", "custom"):
                        search_client_user = SearchClient(
                            endpoint=azure_ai_search_endpoint,
                            index_name="simplechat-user-index",
                            credential=DefaultAzureCredential(),
                            audience=search_resource_manager
                        )
                        search_client_group = SearchClient(
                            endpoint=azure_ai_search_endpoint,
                            index_name="simplechat-group-index",
                            credential=DefaultAzureCredential(),
                            audience=search_resource_manager
                        )
                        search_client_public = SearchClient(
                            endpoint=azure_ai_search_endpoint,
                            index_name="simplechat-public-index",
                            credential=DefaultAzureCredential(),
                            audience=search_resource_manager
                        )
                    else:
                        search_client_user = SearchClient(
                            endpoint=azure_ai_search_endpoint,
                            index_name="simplechat-user-index",
                            credential=DefaultAzureCredential()
                        )
                        search_client_group = SearchClient(
                            endpoint=azure_ai_search_endpoint,
                            index_name="simplechat-group-index",
                            credential=DefaultAzureCredential()
                        )
                        search_client_public = SearchClient(
                            endpoint=azure_ai_search_endpoint,
                            index_name="simplechat-public-index",
                            credential=DefaultAzureCredential()
                        )
                else:
                    search_client_user = SearchClient(
                        endpoint=azure_ai_search_endpoint,
                        index_name="simplechat-user-index",
                        credential=AzureKeyCredential(azure_ai_search_key)
                    )
                    search_client_group = SearchClient(
                        endpoint=azure_ai_search_endpoint,
                        index_name="simplechat-group-index",
                        credential=AzureKeyCredential(azure_ai_search_key)
                    )
                    search_client_public = SearchClient(
                        endpoint=azure_ai_search_endpoint,
                        index_name="simplechat-public-index",
                        credential=AzureKeyCredential(azure_ai_search_key)
                    )
            CLIENTS["search_client_user"] = search_client_user
            CLIENTS["search_client_group"] = search_client_group
            CLIENTS["search_client_public"] = search_client_public
        except Exception as e:
            print(f"Failed to initialize Search clients: {e}")

        if settings.get("enable_content_safety"):
            safety_endpoint = settings.get("content_safety_endpoint", "")
            safety_key = settings.get("content_safety_key", "")
            enable_content_safety_apim = settings.get("enable_content_safety_apim")
            azure_apim_content_safety_endpoint = settings.get("azure_apim_content_safety_endpoint")
            azure_apim_content_safety_subscription_key = settings.get("azure_apim_content_safety_subscription_key")

            if safety_endpoint and safety_key:
                try:
                    if enable_content_safety_apim:
                        content_safety_client = ContentSafetyClient(
                            endpoint=azure_apim_content_safety_endpoint,
                            credential=AzureKeyCredential(azure_apim_content_safety_subscription_key)
                        )
                    else:
                        if settings.get("content_safety_authentication_type") == "managed_identity":
                            if AZURE_ENVIRONMENT in ("usgovernment", "custom"):
                                content_safety_client = ContentSafetyClient(
                                    endpoint=safety_endpoint,
                                    credential=DefaultAzureCredential(),
                                    credential_scopes=[cognitive_services_scope]
                                )
                            else:
                                content_safety_client = ContentSafetyClient(
                                    endpoint=safety_endpoint,
                                    credential=DefaultAzureCredential()
                                )
                        else:
                            content_safety_client = ContentSafetyClient(
                                endpoint=safety_endpoint,
                                credential=AzureKeyCredential(safety_key)
                            )
                    CLIENTS["content_safety_client"] = content_safety_client
                except Exception as e:
                    print(f"Failed to initialize Content Safety client: {e}")
                    CLIENTS["content_safety_client"] = None
            else:
                print("Content Safety enabled, but endpoint/key not provided.")
        else:
            if "content_safety_client" in CLIENTS:
                del CLIENTS["content_safety_client"]


        try:
            if enable_enhanced_citations:
                blob_service_client = None
                if settings.get("office_docs_authentication_type") == "key":
                    blob_service_client = BlobServiceClient.from_connection_string(settings.get("office_docs_storage_account_url"))
                    CLIENTS["storage_account_office_docs_client"] = blob_service_client
                elif settings.get("office_docs_authentication_type") == "managed_identity":
                    blob_service_client = BlobServiceClient(account_url=settings.get("office_docs_storage_account_blob_endpoint"), credential=DefaultAzureCredential())
                    CLIENTS["storage_account_office_docs_client"] = blob_service_client
                
                # Create containers if they don't exist
                # This addresses the issue where the application assumes containers exist
                if blob_service_client:
                    for container_name in [
                        storage_account_user_documents_container_name, 
                        storage_account_group_documents_container_name, 
                        storage_account_public_documents_container_name
                        ]:
                        try:
                            container_client = blob_service_client.get_container_client(container_name)
                            if not container_client.exists():
                                print(f"DEBUG: Container '{container_name}' does not exist. Creating...")
                                container_client.create_container()
                                print(f"DEBUG: Container '{container_name}' created successfully.")
                            else:
                                print(f"DEBUG: Container '{container_name}' already exists.")
                        except Exception as container_error:
                            print(f"Error creating container {container_name}: {str(container_error)}")
        except Exception as e:
            print(f"Failed to initialize Blob Storage clients: {e}")
