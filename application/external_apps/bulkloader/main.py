import os
import sys
import csv
import requests
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
BEARER_TOKEN_TEST_URL = f"{API_BASE_URL}/external/testaccesstoken"  # URL to test the access token
UPLOAD_DIRECTORY = os.getenv("UPLOAD_DIRECTORY")  # Local directory containing files to upload
g_ACCESS_TOKEN = None  # Placeholder for the access token function

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
            appLogger.info(f"`nAttempting to upload: {file_name} to url: {upload_url}")
            appLogger.info(f"User_ID: {user_id}, Workspace_ID: {active_workspace_id}")
            input("Press Enter to process this file...") # For debugging purposes, uncomment to pause before upload
            response = requests.post(upload_url, headers=headers, files=files, data=data, timeout=60) # Added timeout
            response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)

            appLogger.info(f"Successfully uploaded {file_name}. Status Code: {response.status_code}")
            appLogger.debug(f"Response: {response.text}")
            fullPath = os.path.abspath(file_path)
            successFileLogger.debug(f"{fullPath}")
            return True

    except requests.exceptions.HTTPError as e:
        appLogger.error(f"HTTP error occurred for {file_name}: {e}")
        appLogger.error(f"Response content: {e.response.text}")
        #return False
        sys.exit(1)
    except requests.exceptions.ConnectionError as e:
        appLogger.error(f"Connection error occurred for {file_name}: {e}")
        #return False
        sys.exit(1)
    except requests.exceptions.Timeout as e:
        appLogger.error(f"Request timed out for {file_name}: {e}")
        #return False
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        appLogger.error(f"An error occurred during the request for {file_name}: {e}")
        #return False
        sys.exit(1)
    except FileNotFoundError:
        appLogger.error(f"File not found: {file_path}")
        #return False
        sys.exit(1)
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
    print(f"Reading files in directory: {directory}")
    if not os.path.isdir(directory):
        appLogger.error(f"Error: Directory '{directory}' not found.")
        return []

    files = []
    for filename in os.listdir(directory):
        file_path = os.path.join(directory, filename)
        file_path = os.path.abspath(file_path)

        appLogger.info(f"read_files_in_directory: {file_path}")
        fileProcessedAlready = has_file_been_processed(file_path)
        if (fileProcessedAlready):
            ignoredFileLogger.debug(f"{file_path}")
            appLogger.info(f"Skipping {file_path}: Already processed.")
            continue

        print(f"Processing file(s): {file_path}")
        if (os.path.isfile(file_path)):
            files.append(filename)
            appLogger.debug("Uploading file")
            appLogger.debug(f"Uploading file: {filename}")
            upload_document(file_path, user_id, active_workspace_scope, active_workspace_id, classification, g_ACCESS_TOKEN)
        else:
            appLogger.info(f"Skipping {filename}: Not a file.")
    #return files

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
    global successFileLogger, ignoredFileLogger, appLogger, g_ACCESS_TOKEN

    appLogger.debug(f"Directory '{UPLOAD_DIRECTORY}'.")
    successFileLogger = setup_FileLoggers('success_file_logger', success_fileLogname, logging.DEBUG)
    ignoredFileLogger = setup_FileLoggers('ignored_file_logger', ignored_fileLogname, logging.DEBUG)

    # You can add files to ignore here or directly in the log file.
    #successFileLogger.debug("c:\\whatever\\file.txt")

    if not os.path.isdir(UPLOAD_DIRECTORY):
        appLogger.error(f"Error: Directory '{UPLOAD_DIRECTORY}' not found.")
        return

    g_ACCESS_TOKEN = get_access_token()
    if not g_ACCESS_TOKEN:
        appLogger.critical("Failed to obtain access token. Aborting document upload.")
        return

    # Uncomment the following lines to test the access token validity
    appLogger.info("Testing access token for validity...")
    test_access_token(access_token=g_ACCESS_TOKEN)
    appLogger.info("Access token test complete...")

    appLogger.info("Reading map file...")
    read_csv_ignore_header('map.csv')
    appLogger.info("Map file processed...")

    appLogger.info("Bulk upload of documents is complete...")

if __name__ == "__main__":
    main()