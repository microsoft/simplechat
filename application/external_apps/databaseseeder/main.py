import os
import msal
import requests
from msal import ConfidentialClientApplication
import logging
from dotenv import load_dotenv
import webbrowser

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
API_ENDPOINT_URL = f"{API_BASE_URL}/api/groups/discover" # Your custom API endpoint for document upload
USER_ID = os.getenv("USER_ID")  # User ID for whom the groups are being fetched
g_ACCESS_TOKEN = None  # Placeholder for the access token function
authority = f"{AUTHORITY_URL}/{TENANT_ID}"
#authority = "https://julie1-sbx-app-ui7wiq4j5sqf4.azurewebsites.us/getAToken"
#authority = "https://julie1-sbx-app-ui7wiq4j5sqf4.azurewebsites.us/getAToken/v2.0/.well-known/openid-configuration"
TOKEN_CACHE_FILE = "msal_token_cache.bin"

# Configure logging for better debugging
logname = "./logfile.log"
logging.basicConfig(level = logging.INFO) # DEBUG, INFO, WARNING, ERROR, and CRITICAL
logger = logging.getLogger(__name__)


#############################################
# --- Function Library ---
#############################################
def get_token_interactive():
    result = None

    app = ConfidentialClientApplication(
        CLIENT_ID,
        authority=authority,
        client_credential=CLIENT_SECRET,
        instance_discovery=False,
        token_cache=msal.TokenCache() # Optional: For persistent token caching
    )

    #accounts = app.get_accounts()
    accounts = app.get_accounts(username="greg@gregungergov.onmicrosoft.us")
    print(accounts)

    SCOPE = ["User.Read", "User.ReadBasic.All", "People.Read.All", "Group.Read.All"] # Adjust scope according to your needs

    authorization_url = app.get_authorization_request_url(
        scopes=SCOPE,
        #redirect_uri="https://julie1-sbx-app-ui7wiq4j5sqf4.azurewebsites.us/getAToken"
        #redirect_uri="https://julie1-sbx-app-ui7wiq4j5sqf4.azurewebsites.us/.auth/login/aad/callback"
        redirect_uri="https://localhost"
    )
    
    print(authorization_url)

    #result = app.acquire_token_silent(scopes=SCOPE, account=accounts)

    #if result and "access_token" in result:
    #    return result['access_token']
  
    #auth_code = input("Enter the authorization code from the browser redirect URL: ")
    #auth_code = "0.CwMAPrPFawW8PEmwdo-M4TMVFeL4rKkdRMpKhPaoOz6CB3IDAPc.AgABBAIAAgBR8dQFmz9bTrhReQfPAnzpBQDs_wUA8P_sx4AuAWjpWtps1y_nKzAJYajArFS24PNwTm64boIpnrpC2b_tgZ6ULbxdM6xAuIlDFYxfkRBBNzlEp7WVTxiO7pTLNjMFqPt1MW8XgnecJKu5-yOCgNpryCuq7vXotrVdZzLo-82FlsFoBDqoM0pCzocjV60yj5HhCIzXqb-ygOorrEUnHmRhbjM-DpuufnF1iObcww4fHz8_tYUUKTvJlF7BOCyxLFMPhHul92bG7qyoWItRI8kaELNjjmGgDKVLRxNUZ5fxphaZVvVXBTsz3iFWDxY4qy86jMyPkqodylVz29k6nXIShRBZzGjzQNSFPyXsO3XlDVOwHDFGh95vIFoJaHpDoA651BBrIzeKuaoFQVO89aS_EJDt3JfH3heX7zyyYUZlqyBQSjrhYB4ANG1g0qtyto6z6kQ1L_mHKJ8jT3JgPYFUsPCaEsQaxJ35wffqpwtFm3FKsjWckZ095wQNg7376XE7lNnDpNM4eLbrspKwPPTTGzXMNYvqRUPGHMVe8f_WITJwsyubogGK2d4BiAhjOeRkvr68vK1fsdIkQ8Avalz2LLkQS6Z1QXcZzWjF9ZnoXwW6VrO7COGRPl244UysdNXhxcGl_6F9EvHdoNYc6kWVJ9KN8UXFGRYtc2Az314Ha1Ymx7ZIp8hyLxJrxV7DzHkzampO0zroUbuQZMamxfzZo5dpKdpZ5ITNyBPEuwuFELHzoADxhLyYq8n4HbAxj3X-8d-3vxiLRHbaEjPSF2ql5Rza_DiS4frZglXeuBncHdGGSw2y1bvWoY0xLpIsgL9Gmr8K1okQFJtQR81bGqEPHRSECqZXIsEnhN9VPfR6QxWkhh3UtQ"

def groups_get(user_id, access_token):
    logger.debug(f"groups_get: {user_id}")
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    data = {
        'userId': user_id
    }
    params = {
        "showAll": str(True).lower()
    }

    try:
        logger.debug("`n`nAPI Endpoint: " + API_ENDPOINT_URL + "`n`n")
        response = requests.post(API_ENDPOINT_URL, headers=headers, data=data, params=params, timeout=60)
        response.raise_for_status()

        logger.debug(f"Response: {response.text}")

    except Exception as e:
        print(f"HTTP Error: {e}")
        logger.error(f"Response content: {e}")
        return False

    def greg():
        myUrl="https://julie1-sbx-app-ui7wiq4j5sqf4.azurewebsites.us/getAToken"
        access_token = ""
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        data = {
            'userId': USER_ID
        }
        params = {
            "showAll": str(True).lower()
        }
        try:
            logger.debug("`n`nAPI Endpoint: " + API_ENDPOINT_URL + "`n`n")
            response = requests.post(API_ENDPOINT_URL, headers=headers, data=data, timeout=60)
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
    logger.warning("Database seeder starting...")
    g_ACCESS_TOKEN = get_token_interactive()
    if not g_ACCESS_TOKEN:
        logger.critical("Failed to obtain access token. Aborting document upload.")
        return

    logger.warning("Getting Groups from CosmosDb...")
    groups_get(USER_ID, access_token=g_ACCESS_TOKEN)

    logger.warning("Database seeder complete...")

if __name__ == "__main__":
    main()