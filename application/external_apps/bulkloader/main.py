import argparse
from importlib.metadata import files
import os
import sys
import csv
import requests
import time
import math
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from msal import ConfidentialClientApplication
import logging
from dotenv import load_dotenv

#############################################
# --- Configuration ---
#############################################
load_dotenv()

# From environment variables .env file for security
AUTHORITY_URL = os.getenv("AUTHORITY_URL")
TENANT_ID = os.getenv("AZURE_TENANT_ID")  # Directory (tenant) ID
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")  # Application (client) ID for your client app
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")  # Client secret for your client app (use certificates in production)
API_SCOPE = os.getenv("API_SCOPE") # Or a specific scope defined for your API, e.g., "api://<your-api-client-id>/.default" for application permissions
API_BASE_URL = os.getenv("API_BASE_URL") # Base URL for your API
GROUP_DOCUMENTS_UPLOAD_URL = f"{API_BASE_URL}/external/group_documents/upload"
PUBLIC_DOCUMENTS_UPLOAD_URL = f"{API_BASE_URL}/external/public_documents/upload"
PUBLIC_DOCUMENTS_LIST_URL = f"{API_BASE_URL}/external/public_documents"
GROUP_DOCUMENTS_LIST_URL = f"{API_BASE_URL}/external/group_documents"
BEARER_TOKEN_TEST_URL = f"{API_BASE_URL}/external/testaccesstoken"  # URL to test the access token
UPLOAD_DIRECTORY = os.getenv("UPLOAD_DIRECTORY")  # Local directory containing files to upload
g_ACCESS_TOKEN = None  # Placeholder for the access token function
MAX_RETRIES = 100
RETRY_DELAY = 60  # seconds

# Configure logging for better debugging
successFileLogger = None # File logger is to keep track of file uploads that were successfully processed.
ignoredFileLogger = None
stdout_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_formatter = logging.Formatter('%(message)s')
appLogname = "./logfile.log"
success_fileLogname = "./file_logger_success.log"
ignored_fileLogname = "./file_logger_ignored.log"
logging.basicConfig(filename=appLogname,
    filemode='a',
    format='%(asctime)s,%(msecs)03d %(name)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.DEBUG)

stdout_handler = logging.StreamHandler(sys.stdout)
#stdout_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
stdout_handler.setFormatter(stdout_formatter)
logging.getLogger().addHandler(stdout_handler)
appLogger = logging.getLogger(__name__)

#############################################
# --- Function Library ---
#############################################
def setup_FileLoggers(name, log_file, level=logging.DEBUG):
    handler = logging.FileHandler(log_file)
    handler.setFormatter(file_formatter)
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    return logger

def get_access_token():
    """
    Acquires an access token from Microsoft Entra ID using the client credentials flow.
    """
    authority = f"{AUTHORITY_URL}/{TENANT_ID}"
    app = ConfidentialClientApplication(
        client_id=CLIENT_ID,
        client_credential=CLIENT_SECRET,
        authority=authority
    )

    try:
        # Acquire a token silently from cache if available
        result = app.acquire_token_silent(scopes=[API_SCOPE], account=None)
        if not result:
            # If no token in cache, acquire a new one using client credentials flow
            appLogger.info("No token in cache, acquiring new token using client credentials flow.")
            result = app.acquire_token_for_client(scopes=[API_SCOPE])

        if "access_token" in result:
            appLogger.info("Successfully acquired access token.")
            return result["access_token"]
        else:
            appLogger.error(f"Error acquiring token: {result.get('error')}")
            appLogger.error(f"Description: {result.get('error_description')}")
            appLogger.error(f"Correlation ID: {result.get('correlation_id')}")
            return None
    except Exception as e:
        appLogger.error(f"An unexpected error occurred during token acquisition: {e}")
        return None

def upload_document(file_path, user_id, active_workspace_scope, active_workspace_id, classification, access_token=None):
    """
    Uploads a single document to the custom API.

    Args:
        file_path (str): The full path to the file to upload.
        access_token (str): The Microsoft Entra ID access token.

    Returns:
        bool: True if the upload was successful, False otherwise.
    """
    file_name = os.path.basename(file_path)
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    data = {
        "user_id": user_id.strip(),
        "active_workspace_id": active_workspace_id.strip(),
        "classification": classification.strip()
    }

    if active_workspace_scope == "public":
        upload_url = PUBLIC_DOCUMENTS_UPLOAD_URL
    else:
        upload_url = GROUP_DOCUMENTS_UPLOAD_URL

    try:
        with open(file_path, 'rb') as f:
            
            files = {'file': (file_name, f)}

            # Check if the file has already been uploaded
            if has_file_been_uploaded(file_name, user_id, active_workspace_id, access_token):
                appLogger.info(f"File {file_name} has already been uploaded.")

            else:

                attempt = 0

                for attempt in range(MAX_RETRIES):
                    try:
                        
                        appLogger.info(f"`nAttempting to upload: {file_name} to url: {upload_url} using User_ID: {user_id}, Workspace_ID: {active_workspace_id}")
                
                        #input("Press Enter to process this file...") # For debugging purposes, uncomment to pause before upload
                        response = requests.post(upload_url, headers=headers, files=files, data=data, timeout=60) # Added timeout

                        if response.status_code == 200:
                            appLogger.info(f"Successfully uploaded {file_name}. Status Code: {response.status_code}")
                            appLogger.debug(f"Response: {response.text}")
                            fullPath = os.path.abspath(file_path)
                            successFileLogger.debug(f"{fullPath}")
                            return True
                        elif response.status_code == 401:
                            appLogger.warning("Token may have expired, will refresh.")
                            access_token = g_ACCESS_TOKEN = get_access_token()
                            continue
                        elif response.status_code == 429:
                            attempt += 1
                            appLogger.warning(f"Received http 429, Too Many Requests. Retry attempt {attempt} out of {MAX_RETRIES}")
                            time.sleep(RETRY_DELAY)
                            continue                        
                        elif response.status_code == 500:
                            appLogger.error(f"Server error occurred while uploading {file_name}. Status Code: {response.status_code}")
                            appLogger.debug(f"Response: {response.text}")

                        else:
                            appLogger.warning(f"Unexpected response code: {response.status_code}")
                            appLogger.debug(f"Response: {response.text}")
                            return False
                            
                    
                        
                    except requests.HTTPError as e:
                        if e.response.status_code == 401:
                            appLogger.warning("Token may have expired, will refresh.")
                            access_token = g_ACCESS_TOKEN = get_access_token()
                            continue
                        elif e.response.status_code == 429:
                            appLogger.warning("Received 429, Too Many Requests, retrying...")
                            time.sleep(RETRY_DELAY)
                            continue
                        else:
                            appLogger.error(f"An unexpected error occurred while processing {file_name}: {e}")
                            return False      

                else:
                    appLogger.error("Max retries reached. Upload failed.")
                    return False
    
    except Exception as e:
        appLogger.error(f"An unexpected error occurred while processing {file_name}: {e}")
        return False

def test_access_token(access_token):
    """
    Tests the access token by making a request to the API.

    Args:
        access_token (str): The Microsoft Entra ID access token.

    Returns:
        bool: True if the token is valid, False otherwise.
    """
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    try:
        response = requests.post(BEARER_TOKEN_TEST_URL, headers=headers)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)
        appLogger.info("Access token is valid.")
        return True
    except requests.exceptions.HTTPError as e:
        appLogger.error(f"HTTP error occurred while testing access token: {e}")
        return False
    except requests.exceptions.RequestException as e:
        appLogger.error(f"An error occurred while testing access token: {e}")
        return False

def read_csv_ignore_header(file_path):
    """
    Opens a CSV file, skips the header, and reads it line by line.

    Args:
        file_path (str): The path to the CSV file.
    """
    if not os.path.exists(file_path):
        print(f"Error: File not found at '{file_path}'")
        return

    try:
        with open(file_path, mode='r', newline='', encoding='utf-8') as file:
            csv_reader = csv.reader(file)

            # Skip the header row
            header = next(csv_reader, None)
            if header:
                print(f"Header row skipped: {header}")
            else:
                print("Warning: CSV file is empty or has no header.")

            # Read the rest of the file line by line
            line_number = 1 # Start from 1 after header
            for row in csv_reader:
                print(f"Line {line_number}: {row}")
                directory = row[0]
                user_id = row[1]
                active_workspace_scope = row[2]
                active_workspace_id = row[3]
                classification = row[4]
                full_file_path = os.path.join(UPLOAD_DIRECTORY, directory)
                read_files_in_directory(full_file_path, user_id, active_workspace_scope, active_workspace_id, classification, g_ACCESS_TOKEN)
                # You can process each 'row' (which is a list of strings) here
                line_number += 1

    except FileNotFoundError:
        print(f"Error: The file '{file_path}' was not found.")
    except Exception as e:
        print(f"An error occurred while reading the CSV file: {e}")

def read_files_in_directory(directory, user_id, active_workspace_scope, active_workspace_id, classification, access_token=g_ACCESS_TOKEN):
    """
    Reads all files in a specified directory and returns their names.

    Args:
        directory (str): The path to the directory.

    Returns:
        list: A list of file names in the directory.
    """
    global successFileLogger, ignoredFileLogger, appLogger, g_ACCESS_TOKEN
    appLogger.info(f"Reading files in directory: {directory}")
    if not os.path.isdir(directory):
        appLogger.error(f"Error: Directory '{directory}' not found.")
        return []
    
    file_count = len([f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))])
    appLogger.info(f"Number of files: {file_count}")

    files = []
    for filename in os.listdir(directory):
        file_path = os.path.join(directory, filename)
        file_path = os.path.abspath(file_path)

        appLogger.info(f"read_files_in_directory: {file_path}")

        appLogger.info(f"Processing file: {file_path}. {len(files)} out of {file_count}")
        if (os.path.isfile(file_path)):
            files.append(filename)
            upload_document(file_path, user_id, active_workspace_scope, active_workspace_id, classification, g_ACCESS_TOKEN)
        else:
            appLogger.info(f"Skipping {filename}: Not a file.")
    #return files

def has_file_been_uploaded(file_name, user_id, workspace_id, access_token):
    """
    Checks if a file has already been uploaded to the public workspace, by looking for an existing file

    Args:
        file_name (str): Name of the file to check.
        user_id (str): User ID to check against.
        workspace_id (str): Workspace ID to check against.
        access_token (str): The Microsoft Entra ID access token.

    Returns:
        bool: True if the file has already been uploaded, False otherwise.
    """

    list_files_url = PUBLIC_DOCUMENTS_LIST_URL

    headers = {
        "Authorization": f"Bearer {access_token}"
    }    
    
    params = {
        "user_id": user_id.strip(),
        "active_workspace_id": workspace_id.strip(),
        "search": file_name
    }

    appLogger.info(f"Checking for file {file_name} in {workspace_id} for user {user_id}")

    response = requests.get(list_files_url, headers=headers, params=params, timeout=60) # Added timeout
    response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)

    appLogger.info(f"has_file_been_uploaded status code: {response.status_code}")
    #appLogger.debug(f"Response: {response.text}")

    data = response.json()
    if data.get("total_count", 0) > 0:
        return True
    return False

def get_workspace_files(user_id, workspace_id, active_workspace_scope, access_token):
    """
    Retrieves a list of files in the specified public workspace.

    Args:
        user_id (str): User ID to check against.
        workspace_id (str): Workspace ID to check against.
        access_token (str): The Microsoft Entra ID access token.

    Returns:
        list: A list of file names in the workspace, or an empty list if none found.
    """

    headers = {
        "Authorization": f"Bearer {access_token}"
    }    
    
    params = {
        "user_id": user_id.strip(),
        "active_workspace_id": workspace_id.strip(),
        "page": 1,
        "page_size": 25
    }

    if active_workspace_scope == "public":
        list_url = PUBLIC_DOCUMENTS_LIST_URL
    else:
        list_url = GROUP_DOCUMENTS_LIST_URL

    appLogger.info(f"Checking for files in {workspace_id} for user {user_id}")

    all_documents = []
    while True:

        response = None
        try:
            response = requests.get(list_url, headers=headers, params=params, timeout=60) # Added timeout

        except requests.HTTPError as e:
            if e.response.status_code == 401:
                appLogger.warning("Token may have expired, will refresh.")
                access_token = g_ACCESS_TOKEN = get_access_token()
                continue
            else:
                appLogger.error(f"An unexpected error occurred: {e}")
                return False 

        appLogger.info(f"get_workspace_files status code: {response.status_code}")
        #appLogger.debug(f"Response: {response.text}")

        data = response.json()
        documents = data.get("documents", [])
        all_documents.extend(documents)

        total_count = data.get("total_count", 0)
        current_page = data.get("page", 1)
        page_size = data.get("page_size", 10)

        total_pages = math.ceil(total_count / page_size)

        if current_page >= total_pages:
            break

        params["page"] += 1  # Move to the next page

    all_documents
    return all_documents

def delete_workspace_file(file_id, user_id, workspace_id, active_workspace_scope, access_token):
    """
    Deletes a file from the specified public workspace.

    Args:
        file_id (str): ID of the file to delete.
        user_id (str): User ID to check against.
        workspace_id (str): Workspace ID to check against.
        active_workspace_scope (str): Scope of the workspace (public or private).
        access_token (str): The Microsoft Entra ID access token.

    Returns:
        bool: True if the file was successfully deleted, False otherwise.
    """

    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    params = {
        "user_id": user_id.strip(),
        "active_workspace_id": workspace_id.strip()
    }

    if active_workspace_scope == "public":
        delete_url = f"{PUBLIC_DOCUMENTS_LIST_URL}/{file_id}"
    else:
        delete_url = f"{GROUP_DOCUMENTS_LIST_URL}/{file_id}"

    appLogger.info(f"Deleting file {file_id} from {workspace_id} for user {user_id} by calling {delete_url}")

    response = requests.delete(delete_url, headers=headers, params=params, timeout=60)  # Added timeout
    response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)

    appLogger.info(f"delete_workspace_file status code: {response.status_code}")
    appLogger.debug(f"Response: {response.text}")

    return response.status_code == 204

def get_uploading_workspace_files(files):
    """
    Retrieves a list of files that are in a uploading state

    Args:
        files (list): A list of files to check.

    Returns:
        list: A list of files that are in an uploading state.
    """
    uploading_files = []

    for file in files:
        if file["percentage_complete"] < 100:
            uploading_files.append(file)

    appLogger.info(f"Found {len(uploading_files)} files that are currently uploading.")

    return uploading_files

def delete_failed_workspace_files(files, user_id, workspace_id, active_workspace_scope, access_token):
    """
    Processes a list of files deleting failed workspace files.

    Args:
        files (list): A list of files to check.

    Returns:
        list: A list of failed files.
    """
    failed_files = []
    now = datetime.now(timezone.utc)
    twelve_hours_ago = now - timedelta(hours=12)
    
    for file in files:

        last_updated = None

        try:
            last_updated = datetime.strptime(file["last_updated"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue  # Skip if date format is invalid

        if file["percentage_complete"] < 100 and (last_updated < twelve_hours_ago or file["status"].startswith("Error:")):
            failed_files.append(file)            
            
    appLogger.info(f"Found {len(failed_files)} failed files.")

    for file in failed_files:
        appLogger.info(f"Deleting failed file: {file['file_name']} with ID: {file['id']}")
        delete_workspace_file(file["id"], user_id, workspace_id, active_workspace_scope, access_token)  

    return failed_files

def delete_duplicate_workspace_files(files, user_id, workspace_id, active_workspace_scope, access_token):
    """
    Processes a list of files deleting duplicate workspace files.

    Args:
        files (list): A list of files to check.

    Returns:
        list: A list of duplicate files.
    """
    duplicate_files = []

    file_name_map = defaultdict(list)

    # Populate the map with indices of each file_name
    for index, file in enumerate(files):
        file_name = file.get('file_name')
        if file_name:
            file_name_map[file_name].append(index)  

    # Collect full file objects that are duplicates (excluding one per group)
    duplicate_files = []
    for indices in file_name_map.values():
        if len(indices) > 1:
            # Keep one file and add the rest to duplicate_files
            for i in indices[1:]:
                duplicate_files.append(files[i])

    # Output the number of duplicates found
    appLogger.info(f"Total duplicate file entries (excluding one per group): {len(duplicate_files)}")   

    for file in duplicate_files:
        appLogger.info(f"Deleting duplicate file: {file['file_name']} with ID: {file['id']}")
        delete_workspace_file(file["id"], user_id, workspace_id, active_workspace_scope, access_token)  

    return duplicate_files


def has_file_been_processed(file_path):
    """
    Checks if a file has already been processed by looking for its path in the file logger.

    Args:
        file_path (str): The full path to the file to check.

    Returns:
        bool: True if the file has been processed, False otherwise.
    """
    if not successFileLogger:
        appLogger.error("File logger is not initialized.")
        return False

    fullPath = os.path.abspath(file_path)
    appLogger.debug(f"Checking if file has been processed: {fullPath}")
    with open(success_fileLogname, 'r') as f:
        for line in f:
            if fullPath in line:
                return True
    return False

def main():
    """
    Main function to iterate through files and upload them.
    """

    global successFileLogger, ignoredFileLogger, appLogger, g_ACCESS_TOKEN, bUpload, bDelete

    parser = argparse.ArgumentParser()
    parser.add_argument("-a", "--action", choices=["upload", "delete", "clean"], required=True, help="Action to perform")
    parser.add_argument("-w", "--workspaceid", required=False, help="Workspace ID")
    parser.add_argument("-u", "--userid", required=False, help="User ID")
    parser.add_argument("-s", "--scope", choices=["public", "group"], required=False, help="Scope or workspace visibility")
    parser.add_argument("-dupes", "--removeduplicates", action="store_true", help="Removes duplicate documents")

    args = parser.parse_args()

    if args.action in ["delete", "clean"]:
        if not args.workspaceid or not args.userid or not args.scope:
            parser.error("workspaceid, userid, and scope are required for delete and clean actions.")

    action = args.action
    workspaceid = args.workspaceid
    userid = args.userid
    scope = args.scope
    removeduplicates = args.removeduplicates

    successFileLogger = setup_FileLoggers('success_file_logger', success_fileLogname, logging.DEBUG)
    ignoredFileLogger = setup_FileLoggers('ignored_file_logger', ignored_fileLogname, logging.DEBUG)

    g_ACCESS_TOKEN = get_access_token()
    if not g_ACCESS_TOKEN:
        appLogger.critical("Failed to obtain access token. Aborting document upload.")
        return

    # Uncomment the following lines to test the access token validity
    appLogger.info("Testing access token for validity...")
    test_access_token(access_token=g_ACCESS_TOKEN)
    appLogger.info("Access token test complete...")

    if action == "upload":
        appLogger.info("Bulk upload of documents is starting...")

        appLogger.debug(f"Directory '{UPLOAD_DIRECTORY}'.")

        # You can add files to ignore here or directly in the log file.
        #successFileLogger.debug("c:\\whatever\\file.txt")

        if not os.path.isdir(UPLOAD_DIRECTORY):
            appLogger.error(f"Error: Directory '{UPLOAD_DIRECTORY}' not found.")
            return

        appLogger.info("Reading map file...")
        read_csv_ignore_header('map.csv')
        appLogger.info("Map file processed...")

        appLogger.info("Bulk upload of documents is complete...")

    elif action == "delete":
        appLogger.info("Bulk delete of documents is starting...")
        get_workspace_files(userid, workspaceid, scope, g_ACCESS_TOKEN)

    elif action == "clean":
        appLogger.info("Bulk clean of documents is starting...")

        all_files = get_workspace_files(userid, workspaceid, scope, g_ACCESS_TOKEN)

        delete_failed_workspace_files(all_files, userid, workspaceid, scope, g_ACCESS_TOKEN)

        if removeduplicates:
            appLogger.info("Will remove duplicate documents...")
            delete_duplicate_workspace_files(all_files, userid, workspaceid, scope, g_ACCESS_TOKEN)

if __name__ == "__main__":
    main()