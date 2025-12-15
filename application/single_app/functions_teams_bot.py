"""
Teams Bot business logic and helper functions.
Handles query processing, response formatting, and token validation.
"""

from config import *
from functions_public_workspaces import find_public_workspace_by_id
from functions_settings import get_setting
from functions_appinsights import log_event
from chat_engine import ChatEngine
import jwt
from jwt import PyJWKClient
import logging
import requests
from datetime import datetime
import re

# Bot Framework OpenID configuration
BOT_FRAMEWORK_OPENID_URL = "https://login.botframework.com/v1/.well-known/openidconfiguration"
JWKS_CACHE = {}
JWKS_CACHE_EXPIRY = None

def validate_bot_framework_token(token: str) -> tuple[bool, dict | str]:
    """
    Validate Bot Framework JWT token.

    Args:
        token: JWT token from Bot Service

    Returns:
        (True, claims_dict) if valid
        (False, error_message) if invalid
    """
    try:
        # Get JWKS from Bot Framework
        global JWKS_CACHE, JWKS_CACHE_EXPIRY
        now = datetime.utcnow().timestamp()

        if not JWKS_CACHE or not JWKS_CACHE_EXPIRY or now > JWKS_CACHE_EXPIRY:
            # Fetch OpenID configuration
            openid_config = requests.get(BOT_FRAMEWORK_OPENID_URL, timeout=10).json()
            jwks_uri = openid_config['jwks_uri']

            # Create JWK client
            jwks_client = PyJWKClient(jwks_uri)
            JWKS_CACHE = jwks_client
            JWKS_CACHE_EXPIRY = now + 3600  # Cache for 1 hour

        # Get signing key
        signing_key = JWKS_CACHE.get_signing_key_from_jwt(token)

        # Decode and validate token
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=TEAMS_BOT_APP_ID,  # Your bot's app ID
            options={"verify_exp": True}
        )

        # Additional validation: check service URL
        service_url = claims.get('serviceurl', '')
        if not service_url:
            return False, "Missing service URL in token"

        return True, claims

    except jwt.ExpiredSignatureError:
        return False, "Token expired"
    except jwt.InvalidTokenError as e:
        return False, f"Invalid token: {str(e)}"
    except Exception as e:
        log_event(f"Token validation error: {str(e)}", level=logging.ERROR)
        return False, f"Token validation failed: {str(e)}"


def handle_bot_query(user_id: str, workspace_id: str, query: str, conversation_id: str = None) -> dict:
    """
    Process Teams bot query and return formatted response.

    Args:
        user_id: Azure AD user OID
        workspace_id: Public workspace ID to query (HR knowledge base)
        query: User's question
        conversation_id: Teams conversation ID (optional)

    Returns:
        Bot Framework response activity
    """
    try:
        # Validate workspace exists
        workspace = find_public_workspace_by_id(workspace_id)
        if not workspace:
            return {
                'type': 'message',
                'text': f'⚠️ HR Knowledge Base not found. Please contact your administrator.'
            }

        # Check if workspace has documents
        doc_count = count_public_workspace_documents(workspace_id)
        if doc_count == 0:
            return {
                'type': 'message',
                'text': f'📚 The HR knowledge base is currently empty. Please contact your administrator.'
            }

        # Initialize ChatEngine for this user
        chat_engine = ChatEngine(user_id)

        # Perform search for RAG context
        search_results = chat_engine.perform_search(
            query=query,
            workspace_id=workspace_id,
            doc_scope="public",
            top_n=get_setting('teams_bot_max_results', 5)
        )

        if not search_results:
            return {
                'type': 'message',
                'text': format_no_results_response(query)
            }

        # Generate completion with RAG context
        response_text, metadata = chat_engine.generate_completion(
            user_message=query,
            conversation_id=conversation_id,
            search_context=search_results,
            temperature=0.7,
            max_tokens=1000
        )

        # Format response with citations
        return format_response_with_citations(
            response_text=response_text,
            search_results=search_results,
            workspace_name=workspace['name']
        )

    except Exception as e:
        log_event(f"Bot query error: {str(e)}", level=logging.ERROR)
        import traceback
        traceback.print_exc()
        return {
            'type': 'message',
            'text': 'Sorry, I encountered an error processing your query. Please try again later.'
        }


def format_response_with_citations(response_text: str, search_results: list, workspace_name: str) -> dict:
    """
    Format GPT response with citations as plain text.

    Args:
        response_text: GPT-generated response text
        search_results: List of search result dictionaries used for context
        workspace_name: Name of the workspace

    Returns:
        Bot Framework message activity with text response
    """
    # Build response text
    response_lines = []

    # Add GPT response
    response_lines.append(response_text)
    response_lines.append("")

    # Add citations
    response_lines.append("**📄 Sources:**")
    seen_files = set()
    for i, result in enumerate(search_results[:3], 1):
        file_name = result.get('file_name', 'Unknown')
        page_num = result.get('page_number', '?')

        # Avoid duplicate citations from same file
        file_key = f"{file_name}_{page_num}"
        if file_key not in seen_files:
            response_lines.append(f"{i}. {file_name}, Page {page_num}")
            seen_files.add(file_key)

    response_lines.append("")
    response_lines.append("_Need more help? Contact HR at hr@company.com_")

    final_text = '\n'.join(response_lines)

    return {
        'type': 'message',
        'text': final_text
    }


def format_no_results_response(query: str) -> str:
    """Format response when no relevant documents found"""
    return f"""I couldn't find any relevant information about "{query}" in the HR knowledge base.

**For assistance, please:**
• Contact HR at hr@company.com
• Visit the HR portal at https://hr.company.com
• Call HR at 555-0123

Or try rephrasing your question - for example:
• "What is the PTO policy?"
• "How do I submit an expense report?"
• "What are the benefits options?"
"""


def get_help_response() -> dict:
    """Return help message"""
    help_text = """**HR Knowledge Base Assistant**

I can help you find information about:
• HR policies and procedures
• Benefits and compensation
• Time off and leave policies
• Expense reporting
• Onboarding and training
• Company guidelines

**How to use:**
Just ask me a question! For example:
• "What's the PTO policy?"
• "How do I request time off?"
• "What health insurance options are available?"
• "How do I submit expenses?"

**Commands:**
• `/help` - Show this help message
• `/status` - Check bot status

**Important:**
• I answer based on company HR documents only
• For personal HR matters, contact HR directly
• I cannot provide legal or financial advice

**Need more help?**
Contact HR at hr@company.com or call 555-0123
"""

    return {
        'type': 'message',
        'text': help_text.strip()
    }


def get_status_response() -> dict:
    """Return bot status"""
    workspace_id = HR_WORKSPACE_ID
    workspace = find_public_workspace_by_id(workspace_id) if workspace_id else None

    if workspace:
        doc_count = count_public_workspace_documents(workspace_id)
        status_text = f"""**Bot Status: ✅ Active**

**Knowledge Base:** {workspace['name']}
**Documents Indexed:** {doc_count}
**Last Updated:** {workspace.get('modifiedDate', 'Unknown')}

Ready to answer your HR questions!

_For HR support: hr@company.com | 555-0123_
"""
    else:
        status_text = "⚠️ Bot is active but HR knowledge base is not configured. Please contact your administrator."

    return {
        'type': 'message',
        'text': status_text.strip()
    }


def get_welcome_response() -> dict:
    """Return welcome message when bot is added"""
    welcome_text = """👋 **Welcome to the HR Knowledge Base Assistant!**

I'm here to help you find information about company HR policies, benefits, and procedures.

**Get started:**
Just ask me a question like:
• "What's the vacation policy?"
• "How do I submit an expense report?"
• "What are the health insurance options?"

Type `/help` for more information or `/status` to check my status.

**Note:** For personal HR matters or sensitive issues, please contact HR directly at hr@company.com

_Ready to help! 🚀_
"""

    return {
        'type': 'message',
        'text': welcome_text.strip()
    }


def remove_bot_mention(text: str, activity: dict) -> str:
    """
    Remove bot mention from message text.
    Teams includes @BotName in the message text which needs to be stripped.

    Args:
        text: Original message text
        activity: Bot Framework activity

    Returns:
        Cleaned message text
    """
    # Get bot mention from activity
    entities = activity.get('entities', [])
    for entity in entities:
        if entity.get('type') == 'mention':
            mentioned = entity.get('mentioned', {})
            if mentioned.get('id') == activity.get('recipient', {}).get('id'):
                # This is a mention of the bot
                mention_text = entity.get('text', '')
                if mention_text:
                    # Remove the mention from text
                    text = text.replace(mention_text, '').strip()

    # Also try to remove common patterns like "@BotName" at start
    text = re.sub(r'^@\w+\s+', '', text)

    return text.strip()


def count_public_workspace_documents(workspace_id: str) -> int:
    """Count documents in public workspace"""
    try:
        query = "SELECT VALUE COUNT(1) FROM c WHERE c.public_workspace_id = @workspace_id AND c.status = 'Complete'"
        params = [{"name": "@workspace_id", "value": workspace_id}]

        result = list(cosmos_public_documents_container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True
        ))

        return result[0] if result else 0
    except Exception as e:
        log_event(f"Error counting workspace documents: {e}", level=logging.ERROR)
        return 0
