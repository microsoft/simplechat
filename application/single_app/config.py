# config.py

import os
import requests
import uuid
import tempfile
import json
import pandas
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

app = Flask(__name__)

app.config['EXECUTOR_TYPE'] = 'thread'
app.config['EXECUTOR_MAX_WORKERS'] = 30
executor = Executor()
executor.init_app(app)

app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")
app.config['SESSION_TYPE'] = 'filesystem'
app.config['VERSION'] = '0.215.018'

Session(app)

CLIENTS = {}
CLIENTS_LOCK = threading.Lock()

ALLOWED_EXTENSIONS = {
    'txt', 'pdf', 'docx', 'xlsx', 'xls', 'csv', 'pptx', 'html', 'jpg', 'jpeg', 'png', 'bmp', 'tiff', 'tif', 'heif', 'md', 'json', 
    'mp4', 'mov', 'avi', 'mkv', 'flv', 'mxf', 'gxf', 'ts', 'ps', '3gp', '3gpp', 'mpg', 'wmv', 'asf', 'm4a', 'm4v', 'isma', 'ismv', 
    'dvr-ms', 'wav'
}
ALLOWED_EXTENSIONS_IMG = {'png', 'jpg', 'jpeg'}
MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100 MB

# Add Support for Custom Azure Environments
CUSTOM_GRAPH_URL_VALUE = os.getenv("CUSTOM_GRAPH_URL_VALUE", "")
CUSTOM_IDENTITY_URL_VALUE = os.getenv("CUSTOM_IDENTITY_URL_VALUE", "")
CUSTOM_RESOURCE_MANAGER_URL_VALUE = os.getenv("CUSTOM_RESOURCE_MANAGER_URL_VALUE", "")
CUSTOM_BLOB_STORAGE_URL_VALUE = os.getenv("CUSTOM_BLOB_STORAGE_URL_VALUE", "")
CUSTOM_COGNITIVE_SERVICES_URL_VALUE = os.getenv("CUSTOM_COGNITIVE_SERVICES_URL_VALUE", "")

# Azure AD Configuration
CLIENT_ID = os.getenv("CLIENT_ID")
APP_URI = f"api://{CLIENT_ID}"
CLIENT_SECRET = os.getenv("MICROSOFT_PROVIDER_AUTHENTICATION_SECRET")
TENANT_ID = os.getenv("TENANT_ID")
SCOPE = ["User.Read", "User.ReadBasic.All", "People.Read.All", "Group.Read.All"] # Adjust scope according to your needs
MICROSOFT_PROVIDER_AUTHENTICATION_SECRET = os.getenv("MICROSOFT_PROVIDER_AUTHENTICATION_SECRET")    
AZURE_ENVIRONMENT = os.getenv("AZURE_ENVIRONMENT", "public") # public, usgovernment, custom

if AZURE_ENVIRONMENT == "custom":
    AUTHORITY = f"{CUSTOM_IDENTITY_URL_VALUE}/{TENANT_ID}"
else:
    AUTHORITY = f"https://login.microsoftonline.us/{TENANT_ID}"


WORD_CHUNK_SIZE = 400

if AZURE_ENVIRONMENT == "usgovernment":
    resource_manager = "https://management.usgovcloudapi.net"
    authority = AzureAuthorityHosts.AZURE_GOVERNMENT
    credential_scopes=[resource_manager + "/.default"]
    cognitive_services_scope = "https://cognitiveservices.azure.us/.default"
elif AZURE_ENVIRONMENT == "custom":
    resource_manager = CUSTOM_RESOURCE_MANAGER_URL_VALUE
    authority = CUSTOM_IDENTITY_URL_VALUE
    credential_scopes=[resource_manager + "/.default"]
    cognitive_services_scope = CUSTOM_COGNITIVE_SERVICES_URL_VALUE  
else:
    resource_manager = "https://management.azure.com"
    authority = AzureAuthorityHosts.AZURE_PUBLIC_CLOUD
    credential_scopes=[resource_manager + "/.default"]
    cognitive_services_scope = "https://cognitiveservices.azure.com/.default"

bing_search_endpoint = "https://api.bing.microsoft.com/"

storage_account_user_documents_container_name = "user-documents"
storage_account_group_documents_container_name = "group-documents"
storage_account_public_documents_container_name = "public-documents"

# Initialize Azure Cosmos DB client
cosmos_endpoint = os.getenv("AZURE_COSMOS_ENDPOINT")
cosmos_key = os.getenv("AZURE_COSMOS_KEY")
cosmos_authentication_type = os.getenv("AZURE_COSMOS_AUTHENTICATION_TYPE", "key") #key or managed_identity
if cosmos_authentication_type == "managed_identity":
    cosmos_client = CosmosClient(cosmos_endpoint, credential=DefaultAzureCredential())
else:
    cosmos_client = CosmosClient(cosmos_endpoint, cosmos_key)

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

cosmos_user_documents_container_name = "documents"
cosmos_user_documents_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_user_documents_container_name,
    partition_key=PartitionKey(path="/id")
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

cosmos_group_documents_container_name = "group_documents"
cosmos_group_documents_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_group_documents_container_name,
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

cosmos_public_workspaces_container_name = "public_workspaces"
cosmos_public_workspaces_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_public_workspaces_container_name,
    partition_key=PartitionKey(path="/id")
)

cosmos_public_documents_container_name = "public_documents"
cosmos_public_documents_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_public_documents_container_name,
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

def ensure_custom_logo_file_exists(app, settings):
    """
    If custom_logo_base64 is present in settings, ensure static/images/custom_logo.png
    exists and reflects the current base64 data. Overwrites if necessary.
    If base64 is empty/missing, removes the file.
    """
    custom_logo_b64 = settings.get('custom_logo_base64', '')
    # Ensure the filename is consistent
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
            except OSError as ex: # Use OSError for file operations
                print(f"Error removing {logo_filename}: {ex}")
        return

    # Custom logo exists in settings, write/overwrite the file
    try:
        # Decode the current base64 string
        decoded = base64.b64decode(custom_logo_b64)

        # Write the decoded data to the file, overwriting if it exists
        with open(logo_path, 'wb') as f:
            f.write(decoded)
        print(f"Ensured {logo_filename} exists and matches current settings.")

    except (base64.binascii.Error, TypeError, OSError) as ex: # Catch specific errors
        print(f"Failed to write/overwrite {logo_filename}: {ex}")
    except Exception as ex: # Catch any other unexpected errors
         print(f"Unexpected error during logo file write for {logo_filename}: {ex}")

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
                    document_intelligence_client = DocumentIntelligenceClient(
                        endpoint=form_recognizer_endpoint,
                        credential=DefaultAzureCredential()
                    )
                else:
                    document_intelligence_client = DocumentAnalysisClient(
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
                blob_service_client = BlobServiceClient.from_connection_string(settings.get("office_docs_storage_account_url"))
                CLIENTS["storage_account_office_docs_client"] = blob_service_client
                
                # Create containers if they don't exist
                # This addresses the issue where the application assumes containers exist
                for container_name in [
                    storage_account_user_documents_container_name, 
                    storage_account_group_documents_container_name,
                    storage_account_public_documents_container_name
                    ]:
                    try:
                        container_client = blob_service_client.get_container_client(container_name)
                        if not container_client.exists():
                            print(f"Container '{container_name}' does not exist. Creating...")
                            container_client.create_container()
                            print(f"Container '{container_name}' created successfully.")
                        else:
                            print(f"Container '{container_name}' already exists.")
                    except Exception as container_error:
                        print(f"Error creating container {container_name}: {str(container_error)}")
                
                # Handle video and audio support when enabled
                # if enable_video_file_support:
                #     video_client = BlobServiceClient.from_connection_string(settings.get("video_files_storage_account_url"))
                #     CLIENTS["storage_account_video_files_client"] = video_client
                #     # Create video containers if needed
                #
                # if enable_audio_file_support:
                #     audio_client = BlobServiceClient.from_connection_string(settings.get("audio_files_storage_account_url"))
                #     CLIENTS["storage_account_audio_files_client"] = audio_client
                #     # Create audio containers if needed
        except Exception as e:
            print(f"Failed to initialize Blob Storage clients: {e}")