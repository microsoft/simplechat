import os
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
API_ENDPOINT_URL = f"{API_BASE_URL}/api/group_bulk_documents/upload", API_BASE_URL # Your custom API endpoint for document upload
UPLOAD_DIRECTORY = os.getenv("UPLOAD_DIRECTORY")  # Local directory containing files to upload
g_ACCESS_TOKEN = None  # Placeholder for the access token function

# Configure logging for better debugging
logname = "./logfile.log"
logging.basicConfig(filename=logname,
    filemode='a',
    format='%(asctime)s,%(msecs)03d %(name)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.DEBUG)
logger = logging.getLogger(__name__)

#############################################
# --- Function Library ---
#############################################
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
            logger.info("No token in cache, acquiring new token using client credentials flow.")
            result = app.acquire_token_for_client(scopes=[API_SCOPE])

        if "access_token" in result:
            logger.info("Successfully acquired access token.")
            return result["access_token"]
        else:
            logger.error(f"Error acquiring token: {result.get('error')}")
            logger.error(f"Description: {result.get('error_description')}")
            logger.error(f"Correlation ID: {result.get('correlation_id')}")
            return None
    except Exception as e:
        logger.error(f"An unexpected error occurred during token acquisition: {e}")
        return None

def upload_document(file_path, user_id, active_group_id, access_token):
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
        'userId': user_id,
        'activeGroupOid': active_group_id
    }

    try:
        with open(file_path, 'rb') as f:
            files = {'file': (file_name, f)}
            logger.info(f"`nAttempting to upload: {file_name}")
            logger.info(f"User_ID: {user_id}, Active_Group_OID: {active_group_id}")

            response = requests.post(API_ENDPOINT_URL, headers=headers, files=files, data=data, timeout=60) # Added timeout
            response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)

            logger.info(f"Successfully uploaded {file_name}. Status Code: {response.status_code}")
            logger.debug(f"Response: {response.text}")
            return True

    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error occurred for {file_name}: {e}")
        logger.error(f"Response content: {e.response.text}")
        return False
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error occurred for {file_name}: {e}")
        return False
    except requests.exceptions.Timeout as e:
        logger.error(f"Request timed out for {file_name}: {e}")
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"An error occurred during the request for {file_name}: {e}")
        return False
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
        return False
    except Exception as e:
        logger.error(f"An unexpected error occurred while processing {file_name}: {e}")
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
                active_group_id = row[2]
                full_file_path = os.path.join(UPLOAD_DIRECTORY, directory)
                read_files_in_directory(full_file_path, user_id, active_group_id, g_ACCESS_TOKEN)
                # You can process each 'row' (which is a list of strings) here
                line_number += 1

    except FileNotFoundError:
        print(f"Error: The file '{file_path}' was not found.")
    except Exception as e:
        print(f"An error occurred while reading the CSV file: {e}")

def read_files_in_directory(directory, user_id, active_group_id, access_token=g_ACCESS_TOKEN):
    """
    Reads all files in a specified directory and returns their names.

    Args:
        directory (str): The path to the directory.

    Returns:
        list: A list of file names in the directory.
    """
    print(f"Reading files in directory: {directory}")
    if not os.path.isdir(directory):
        logger.error(f"Error: Directory '{directory}' not found.")
        return []

    files = []
    for filename in os.listdir(directory):
        file_path = os.path.join(directory, filename)
        print(f"Processing file: {file_path}")
        if (os.path.isfile(file_path)):
            files.append(filename)
            logger.debug("Uploading file")
            logger.debug(f"Uploading file: {filename}")
            upload_document(file_path, user_id, active_group_id, g_ACCESS_TOKEN)
        else:
            logger.info(f"Skipping {filename}: Not a file.")
    #return files

def main():
    """
    Main function to iterate through files and upload them.
    """
    logger.debug(f"Directory '{UPLOAD_DIRECTORY}'.")

    if not os.path.isdir(UPLOAD_DIRECTORY):
        logger.error(f"Error: Directory '{UPLOAD_DIRECTORY}' not found.")
        return

    g_ACCESS_TOKEN = get_access_token()
    if not g_ACCESS_TOKEN:
        logger.critical("Failed to obtain access token. Aborting document upload.")
        return

    logger.info("Reading map file...")
    read_csv_ignore_header('map.csv')
    logger.info("Map file processed...")

    logger.info("Bulk upload of documents is complete...")

if __name__ == "__main__":
    main()