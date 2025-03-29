# config.py

import os
import requests
import uuid
import tempfile
import json
import openai
import pandas as pd
import time
import threading
import random
import base64
import markdown2
import re
import docx
import fitz # PyMuPDF
import math

from flask import Flask, flash, request, jsonify, render_template, redirect, url_for, session, send_from_directory, send_file, Markup
from werkzeug.utils import secure_filename
from datetime import datetime, timezone, timedelta
from functools import wraps
from msal import ConfidentialClientApplication
from flask_session import Session
from uuid import uuid4
from threading import Thread
from openai import AzureOpenAI, RateLimitError
from cryptography.fernet import Fernet, InvalidToken
from urllib.parse import quote
from flask_executor import Executor
from io import BytesIO


from azure.cosmos import CosmosClient, PartitionKey, exceptions
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.search.documents import SearchClient, IndexDocumentsBatch
from azure.search.documents.models import VectorizedQuery
from azure.core.exceptions import AzureError, ResourceNotFoundError, HttpResponseError
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
app.config['VERSION'] = '0.207.256'
Session(app)

CLIENTS = {}
CLIENTS_LOCK = threading.Lock()

ALLOWED_EXTENSIONS = {
    'txt', 'pdf', 'docx', 'xlsx', 'xls', 'csv', 'pptx', 'html', 'jpg', 'jpeg', 'png', 'bmp', 'tiff', 'tif', 'heif', 'md', 'json'
}
ALLOWED_EXTENSIONS_IMG = {'png', 'jpg', 'jpeg'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB

# Azure AD Configuration
CLIENT_ID = os.getenv("CLIENT_ID")
APP_URI = f"api://{CLIENT_ID}"
CLIENT_SECRET = os.getenv("MICROSOFT_PROVIDER_AUTHENTICATION_SECRET")
TENANT_ID = os.getenv("TENANT_ID")
AUTHORITY = f"https://login.microsoftonline.us/{TENANT_ID}"
SCOPE = ["User.Read"]  # Adjust scope according to your needs
MICROSOFT_PROVIDER_AUTHENTICATION_SECRET = os.getenv("MICROSOFT_PROVIDER_AUTHENTICATION_SECRET")    
AZURE_ENVIRONMENT = os.getenv("AZURE_ENVIRONMENT", "public") # public, usgovernment

if AZURE_ENVIRONMENT == "usgovernment":
    resource_manager = "https://management.usgovcloudapi.net"
    authority = AzureAuthorityHosts.AZURE_GOVERNMENT
    credential_scopes=[resource_manager + "/.default"]
else:
    resource_manager = "https://management.azure.com"
    authority = AzureAuthorityHosts.AZURE_PUBLIC_CLOUD
    credential_scopes=[resource_manager + "/.default"]

bing_search_endpoint = "https://api.bing.microsoft.com/"

user_documents_container_name = "user-documents"
group_documents_container_name = "group-documents"
user_video_files_container_name = "user-video-files"
group_video_files_container_name = "group-video-files"
user_audio_files_container_name = "user-audio-files"
group_audio_files_container_name = "group-audio-files"

# Initialize Azure Cosmos DB client
cosmos_endpoint = os.getenv("AZURE_COSMOS_ENDPOINT")
cosmos_key = os.getenv("AZURE_COSMOS_KEY")
cosmos_authentication_type = os.getenv("AZURE_COSMOS_AUTHENTICATION_TYPE", "key") #key or managed_identity
if cosmos_authentication_type == "managed_identity":
    cosmos_client = CosmosClient(cosmos_endpoint, credential=DefaultAzureCredential())
else:
    cosmos_client = CosmosClient(cosmos_endpoint, cosmos_key)

database_name = "SimpleChat"
database = cosmos_client.create_database_if_not_exists(database_name)

container_name = "conversations"
container = database.create_container_if_not_exists(
    id=container_name,
    partition_key=PartitionKey(path="/id")
)

messages_container_name = "messages"
messages_container = database.create_container_if_not_exists(
    id=messages_container_name,
    partition_key=PartitionKey(path="/conversation_id")
)

documents_container_name = "documents"
documents_container = database.create_container_if_not_exists(
    id=documents_container_name,
    partition_key=PartitionKey(path="/id")
)

settings_container_name = "settings"
settings_container = database.create_container_if_not_exists(
    id=settings_container_name,
    partition_key=PartitionKey(path="/id")
)

groups_container_name = "groups"
groups_container = database.create_container_if_not_exists(
    id=groups_container_name,
    partition_key=PartitionKey(path="/id")
)

group_documents_container_name = "group_documents"
group_documents_container = database.create_container_if_not_exists(
    id=group_documents_container_name,
    partition_key=PartitionKey(path="/id")
)

user_settings_container_name = "user_settings"
user_settings_container = database.create_container_if_not_exists(
    id=user_settings_container_name,
    partition_key=PartitionKey(path="/id")
)

safety_container_name = "safety"
safety_container = database.create_container_if_not_exists(
    id=safety_container_name,
    partition_key=PartitionKey(path="/id")
)

feedback_container_name = "feedback"
feedback_container = database.create_container_if_not_exists(
    id=feedback_container_name,
    partition_key=PartitionKey(path="/id")
)

archived_conversations_container_name = "archived_conversations"
archived_conversations_container = database.create_container_if_not_exists(
    id=archived_conversations_container_name,
    partition_key=PartitionKey(path="/id")
)

archived_messages_container_name = "archived_messages"
archived_messages_container = database.create_container_if_not_exists(
    id=archived_messages_container_name,
    partition_key=PartitionKey(path="/conversation_id")
)

prompts_container_name = "prompts"
prompts_container = database.create_container_if_not_exists(
    id=prompts_container_name,
    partition_key=PartitionKey(path="/id")
)

group_prompts_container_name = "group_prompts"
group_prompts_container = database.create_container_if_not_exists(
    id=group_prompts_container_name,
    partition_key=PartitionKey(path="/id")
)

file_processing_container_name = "file_processing"
file_processing_container = database.create_container_if_not_exists(
    id=file_processing_container_name,
    partition_key=PartitionKey(path="/document_id")
)

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
            CLIENTS["search_client_user"] = search_client_user
            CLIENTS["search_client_group"] = search_client_group
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
                office_docs_client = BlobServiceClient.from_connection_string(settings.get("office_docs_storage_account_url"))
                CLIENTS["office_docs_client"] = office_docs_client
                if enable_video_file_support:
                    video_files_client = BlobServiceClient.from_connection_string(settings.get("video_files_storage_account_url"))
                    CLIENTS["video_files_client"] = video_files_client
                if enable_audio_file_support:
                    audio_files_client = BlobServiceClient.from_connection_string(settings.get("audio_files_storage_account_url"))
                    CLIENTS["audio_files_client"] = audio_files_client
        except Exception as e:
            print(f"Failed to initialize Blob Storage clients: {e}")
