# sync-bookstack-to-storage.py

import requests
from azure.storage.blob import BlobServiceClient
import os
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
# --------------------------
# Configuration
# --------------------------

load_dotenv()
BOOKSTACK_URL = os.environ.get("BOOKSTACK_URL")
BOOKSTACK_TOKEN_ID = os.environ.get("BOOKSTACK_TOKEN_ID")
BOOKSTACK_TOKEN_SECRET = os.environ.get("BOOKSTACK_TOKEN_SECRET")
STORAGE_CONNECTION_STRING = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
CONTAINER_NAME = os.environ.get("AZURE_BLOB_CONTAINER")
STORAGE_ACCOUNT_URL = os.environ.get("STORAGE_ACCOUNT_URL")
# --------------------------
# Initialize Azure Blob Storage
# --------------------------

from azure.identity import AzureCliCredential
from azure.storage.blob import BlobServiceClient

credential = AzureCliCredential()
blob_service_client = BlobServiceClient(
    account_url=STORAGE_ACCOUNT_URL,
    credential=credential
)


container_client = blob_service_client.get_container_client(CONTAINER_NAME)

# Create container if needed
try:
    container_client.create_container()
except Exception:
    pass  # already exists

# --------------------------
# Helper: Auth Header
# --------------------------
headers = {
    "Authorization": f"Token {BOOKSTACK_TOKEN_ID}:{BOOKSTACK_TOKEN_SECRET}"
}

# --------------------------
# Helper: Fetch List of Items
# --------------------------
def list_all(endpoint):
    """Return all paginated results from a BookStack list endpoint."""
    items = []
    offset = 0
    while True:
        resp = requests.get(f"{BOOKSTACK_URL}/{endpoint}?count=100&offset={offset}", headers=headers)
        resp.raise_for_status()
        data = resp.json()
        chunk = data.get("data", [])
        if not chunk:
            break
        items.extend(chunk)
        if len(chunk) < 100:
            break
        offset += 100
    return items

# --------------------------
# Step 1: Get all books, chapters, pages
# --------------------------
books = list_all("books")
chapters = list_all("chapters")
pages = list_all("pages")

print(f"Found {len(books)} books, {len(chapters)} chapters, {len(pages)} pages.")

# --------------------------
# Helper: Download PDF
# --------------------------
def download_pdf(item_type, item_id, item_name):
    """Download a BookStack item as PDF."""
    pdf_url = f"{BOOKSTACK_URL}/{item_type}/{item_id}/export/pdf"
    resp = requests.get(pdf_url, headers=headers)
    if resp.status_code == 200:
        filename = f"{item_type}_{item_id}_{item_name.replace(' ', '_')}.pdf"
        return filename, resp.content
    else:
        print(f"⚠️ Skipped {item_type} {item_name} ({resp.status_code})")
        return None, None

# --------------------------
# Step 2: Export & Upload PDFs
# --------------------------
for item_type, items in [
    ("books", books),
    ("chapters", chapters),
    ("pages", pages)
]:
    for item in items:
        name = item["name"]
        id_ = item["id"]

        filename, pdf_data = download_pdf(item_type, id_, name)
        if not pdf_data:
            continue

        blob_client = container_client.get_blob_client(filename)
        if blob_client.exists():
            print(f"Skipping {filename} (already uploaded)")
            continue

        print(f"Uploading {filename}...")
        blob_client.upload_blob(pdf_data, overwrite=True)

print("✅ All new PDFs uploaded successfully to Azure Blob Storage")
