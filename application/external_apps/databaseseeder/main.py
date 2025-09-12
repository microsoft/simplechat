import errno
import os
import sys
import csv
import requests
import json
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
USER_ID = os.getenv("USER_ID")  # User ID for whom the groups are being fetched
g_ACCESS_TOKEN = None  # Placeholder for the access token function
AUTHORITY_FULL_URL = f"{AUTHORITY_URL}/{TENANT_ID}"

# API Urls
GROUPS_DISCOVER_URL = f"{API_BASE_URL}/external/groups/discover" # Your custom API endpoint for document upload
ADMIN_SETTINGS_GET_URL = f"{API_BASE_URL}/external/applicationsettings/get" # Your custom API endpoint for document upload
ADMIN_SETTINGS_SET_URL = f"{API_BASE_URL}/external/applicationsettings/set" # Your custom API endpoint for document upload

# Configure logging for better debugging
stdout_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
appLogname = "./logfile.log"
logging.basicConfig(filename=appLogname,
    filemode='a',
    format='%(asctime)s,%(msecs)03d %(name)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.DEBUG)
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setFormatter(stdout_formatter)
logging.getLogger().addHandler(stdout_handler)
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

def groups_get(user_id, access_token=g_ACCESS_TOKEN):
    global logger
    logger.debug(f"groups_get: {user_id}")
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    data = {
        'user_Id': user_id
    }
    params = {
        "showAll": str(True).lower()
    }

    try:
        logger.debug("`n`nAPI Endpoint: " + GROUPS_DISCOVER_URL + "`n`n")
        response = requests.get(GROUPS_DISCOVER_URL, headers=headers, data=data, params=params, timeout=60)
        response.raise_for_status()

        logger.debug(f"Response: {response.text}")

    except Exception as e:
        print(f"HTTP Error: {e}")
        logger.error(f"Response content: {e}")
        return False

def application_settings_get(access_token=g_ACCESS_TOKEN):
    global logger
    logger.debug("application_settings_get")
    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    try:
        logger.debug(f"API Endpoint: {ADMIN_SETTINGS_GET_URL}")
        response = requests.get(ADMIN_SETTINGS_GET_URL, headers=headers, timeout=60)
        response.raise_for_status()

        logger.debug(f"Response: {response.text}")
        return response.json()  # Assuming the response is in JSON format

    except Exception as e:
        print(f"HTTP Error: {e}")
        logger.error(f"Response content: {e}")
        return False

def application_settings_set(settings_json, access_token=g_ACCESS_TOKEN):
    global logger
    logger.debug("application_settings_set")
    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    try:
        logger.debug(f"API Endpoint: {ADMIN_SETTINGS_SET_URL}")
        response = requests.post(ADMIN_SETTINGS_SET_URL, json=settings_json, headers=headers, timeout=60)
        response.raise_for_status()

        logger.debug(f"Response: {response.text}")

    except Exception as e:
        print(f"HTTP Error: {e}")
        logger.error(f"Response content: {e}")
        return False

def main():
    """
    Main function to iterate through files and upload them.
    """
    global logger, g_ACCESS_TOKEN

    logger.info("Database seeder starting...")
    g_ACCESS_TOKEN = get_access_token()
    if not g_ACCESS_TOKEN:
        logger.critical("Failed to obtain access token. Aborting document upload.")
        return

    logger.info("Getting Groups...")
    groups_get(USER_ID, g_ACCESS_TOKEN)
    logger.info("Getting Groups call completed...")

    logger.info("Getting Application Settings...")
    settings_json = application_settings_get(g_ACCESS_TOKEN)
    logger.info("Application Settings call completed...")

    absolute_file_path_of_script = os.path.abspath(__file__)
    script_directory = os.path.dirname(absolute_file_path_of_script)
    print(f"Script directory: {script_directory}")

    file_path = r"artifacts\admin_settings.json"
    settings_file_path = os.path.join(script_directory, file_path)
    print(f"settings_file_path: {settings_file_path}")
    settings_json_from_file = None
    if os.path.exists(settings_file_path):
        with open(file_path, 'r') as file:
            # Use json.load() to parse the file content into a Python object
            settings_json_from_file = json.load(file)
            print("JSON file loaded successfully!")
            print(f"Type of loaded_data: {type(settings_json_from_file)}")
            print("-" * 30)
            print(f"Content of loaded_data: {settings_json_from_file}")
            print("-" * 30)
    else:
        logger.error(f"File not found: {settings_file_path}")
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), settings_file_path)

    #azure_openai_gpt_key = settings_json_from_file['azure_openai_gpt_key']
    #print(f"azure_openai_gpt_key: {azure_openai_gpt_key}")
    # Single value modification example
    #settings_json["azure_openai_gpt_key"] = f"{azure_openai_gpt_key}" # Example modification

    settings_json.update(settings_json_from_file)
    print("\nMerged JSON (using update()):", json.dumps(settings_json, indent=2))

    logger.info("Setting Application Settings...")
    application_settings_set(settings_json, g_ACCESS_TOKEN)
    logger.info("Setting Application call completed...")

    logger.warning("Database seeder complete...")

if __name__ == "__main__":
    main()