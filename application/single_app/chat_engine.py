"""
ChatEngine - Reusable chat orchestration logic.
Extracts core chat functionality from route_backend_chats.py for Teams bot reuse.
"""

from config import *
from functions_search import hybrid_search
from functions_settings import get_settings
from functions_agents import get_agent_id_by_name
from functions_appinsights import log_event
from semantic_kernel_loader import initialize_semantic_kernel
from semantic_kernel.contents.chat_history import ChatHistory
from semantic_kernel.contents.chat_message_content import ChatMessageContent
import logging
import uuid
from datetime import datetime


class ChatEngine:
    """
    Orchestrates chat completions with RAG, agent support, and conversation management.

    This class encapsulates the core chat logic that was originally in route_backend_chats.py,
    making it reusable for both web UI and Teams bot scenarios.
    """

    def __init__(self, user_id: str):
        """
        Initialize ChatEngine for a specific user.

        Args:
            user_id: Azure AD user OID
        """
        self.user_id = user_id
        self.settings = get_settings()
        self.kernel = None
        self.kernel_agents = None

        # Initialize Semantic Kernel if available
        try:
            from flask import g
            import builtins
            self.kernel = getattr(g, 'kernel', None) or getattr(builtins, 'kernel', None)
            self.kernel_agents = getattr(g, 'kernel_agents', None) or getattr(builtins, 'kernel_agents', None)
        except:
            pass


    def get_or_create_conversation(self, conversation_id: str = None, title: str = "New Conversation") -> tuple[str, dict]:
        """
        Get existing conversation or create new one.

        Args:
            conversation_id: Optional conversation ID to load
            title: Title for new conversations

        Returns:
            (conversation_id, conversation_item)
        """
        if not conversation_id:
            conversation_id = str(uuid.uuid4())
            conversation_item = {
                'id': conversation_id,
                'user_id': self.user_id,
                'last_updated': datetime.utcnow().isoformat(),
                'title': title,
                'context': [],
                'tags': [],
                'strict': False
            }
            cosmos_conversations_container.upsert_item(conversation_item)
            log_event(f"Created new conversation: {conversation_id}", level=logging.INFO)
        else:
            try:
                conversation_item = cosmos_conversations_container.read_item(
                    item=conversation_id,
                    partition_key=conversation_id
                )
            except Exception as e:
                log_event(f"Conversation {conversation_id} not found, creating new", level=logging.WARNING)
                conversation_item = {
                    'id': conversation_id,
                    'user_id': self.user_id,
                    'last_updated': datetime.utcnow().isoformat(),
                    'title': title,
                    'context': [],
                    'tags': [],
                    'strict': False
                }
                cosmos_conversations_container.upsert_item(conversation_item)

        return conversation_id, conversation_item


    def perform_search(self, query: str, workspace_id: str = None, doc_scope: str = "personal", top_n: int = 5) -> list:
        """
        Execute hybrid search to retrieve relevant documents.

        Args:
            query: Search query
            workspace_id: Public workspace ID (for public scope)
            doc_scope: "personal", "group", or "public"
            top_n: Number of results to return

        Returns:
            List of search results with citations
        """
        try:
            results = hybrid_search(
                query=query,
                user_id=self.user_id,
                doc_scope=doc_scope,
                active_public_workspace_id=workspace_id,
                top_n=top_n
            )

            log_event(f"Search returned {len(results)} results", level=logging.INFO)
            return results

        except Exception as e:
            log_event(f"Search error: {e}", level=logging.ERROR)
            import traceback
            traceback.print_exc()
            return []


    def build_chat_history(self, conversation_item: dict, history_limit: int = 6) -> ChatHistory:
        """
        Build chat history from conversation messages.

        Args:
            conversation_item: Conversation document from Cosmos DB
            history_limit: Maximum number of historical messages

        Returns:
            ChatHistory object for Semantic Kernel
        """
        history = ChatHistory()

        # Query messages for this conversation
        try:
            query = """
            SELECT c.role, c.content, c.timestamp
            FROM c
            WHERE c.conversation_id = @conv_id
            ORDER BY c.timestamp DESC
            OFFSET 0 LIMIT @limit
            """
            params = [
                {"name": "@conv_id", "value": conversation_item['id']},
                {"name": "@limit", "value": history_limit}
            ]

            messages = list(cosmos_messages_container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True
            ))

            # Reverse to chronological order
            messages.reverse()

            # Add to chat history
            for msg in messages:
                role = msg.get('role', 'user')
                content = msg.get('content', '')

                if role == 'user':
                    history.add_user_message(content)
                elif role == 'assistant':
                    history.add_assistant_message(content)

            log_event(f"Built chat history with {len(messages)} messages", level=logging.INFO)

        except Exception as e:
            log_event(f"Error building chat history: {e}", level=logging.WARNING)

        return history


    def generate_completion(
        self,
        user_message: str,
        conversation_id: str = None,
        search_context: list = None,
        agent_name: str = None,
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> tuple[str, dict]:
        """
        Generate chat completion with optional RAG context.

        Args:
            user_message: User's input message
            conversation_id: Optional conversation ID for history
            search_context: Optional search results for RAG
            agent_name: Optional agent name to use
            temperature: Model temperature
            max_tokens: Maximum response tokens

        Returns:
            (response_text, metadata_dict)
        """
        try:
            # Get or create conversation
            conversation_id, conversation_item = self.get_or_create_conversation(conversation_id)

            # Build chat history
            history = self.build_chat_history(conversation_item)

            # Add search context to system message if provided
            system_message = "You are a helpful AI assistant."

            if search_context and len(search_context) > 0:
                context_text = self._format_search_context(search_context)
                system_message += f"\n\nUse the following context to answer the user's question:\n\n{context_text}"

            # Add system message
            history.add_system_message(system_message)

            # Add current user message
            history.add_user_message(user_message)

            # Generate completion using GPT client
            gpt_client = self._get_gpt_client()
            gpt_model = self._get_gpt_model()

            if not gpt_client or not gpt_model:
                raise ValueError("GPT client not initialized")

            # Convert history to OpenAI format
            messages = []
            for msg in history.messages:
                messages.append({
                    "role": msg.role.value if hasattr(msg.role, 'value') else str(msg.role),
                    "content": msg.content
                })

            # Call GPT
            response = gpt_client.chat.completions.create(
                model=gpt_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )

            response_text = response.choices[0].message.content

            # Save user message to Cosmos
            self._save_message(conversation_id, "user", user_message)

            # Save assistant response to Cosmos
            self._save_message(conversation_id, "assistant", response_text)

            # Update conversation timestamp
            conversation_item['last_updated'] = datetime.utcnow().isoformat()
            cosmos_conversations_container.upsert_item(conversation_item)

            # Build metadata
            metadata = {
                'conversation_id': conversation_id,
                'model': gpt_model,
                'temperature': temperature,
                'max_tokens': max_tokens,
                'search_results_count': len(search_context) if search_context else 0
            }

            return response_text, metadata

        except Exception as e:
            log_event(f"Completion error: {e}", level=logging.ERROR)
            import traceback
            traceback.print_exc()
            raise


    def _format_search_context(self, search_results: list) -> str:
        """Format search results as context text"""
        context_parts = []

        for i, result in enumerate(search_results[:5], 1):
            chunk_text = result.get('chunk_text', '')
            file_name = result.get('file_name', 'Unknown')
            page_num = result.get('page_number', '?')

            context_parts.append(f"[Source {i}: {file_name}, Page {page_num}]\n{chunk_text}\n")

        return '\n'.join(context_parts)


    def _get_gpt_client(self):
        """Get GPT client from settings"""
        # Use APIM or direct Azure OpenAI
        enable_gpt_apim = self.settings.get('enable_gpt_apim', False)

        if enable_gpt_apim:
            from openai import AzureOpenAI
            return AzureOpenAI(
                api_version=self.settings.get('azure_apim_gpt_api_version'),
                azure_endpoint=self.settings.get('azure_apim_gpt_endpoint'),
                api_key=self.settings.get('azure_apim_gpt_subscription_key')
            )
        else:
            from openai import AzureOpenAI
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider

            auth_type = self.settings.get('azure_openai_gpt_authentication_type')
            endpoint = self.settings.get('azure_openai_gpt_endpoint')
            api_version = self.settings.get('azure_openai_gpt_api_version')

            if auth_type == 'managed_identity':
                cognitive_services_scope = "https://cognitiveservices.azure.com/.default"
                token_provider = get_bearer_token_provider(
                    DefaultAzureCredential(),
                    cognitive_services_scope
                )
                return AzureOpenAI(
                    api_version=api_version,
                    azure_endpoint=endpoint,
                    azure_ad_token_provider=token_provider
                )
            else:
                api_key = self.settings.get('azure_openai_gpt_key')
                return AzureOpenAI(
                    api_version=api_version,
                    azure_endpoint=endpoint,
                    api_key=api_key
                )


    def _get_gpt_model(self) -> str:
        """Get GPT model deployment name"""
        enable_gpt_apim = self.settings.get('enable_gpt_apim', False)

        if enable_gpt_apim:
            raw = self.settings.get('azure_apim_gpt_deployment', '')
            models = [m.strip() for m in raw.split(',') if m.strip()]
            return models[0] if models else None
        else:
            gpt_model_obj = self.settings.get('gpt_model', {})
            if gpt_model_obj and gpt_model_obj.get('selected'):
                return gpt_model_obj['selected'][0]['deploymentName']
            return None


    def _save_message(self, conversation_id: str, role: str, content: str):
        """Save message to Cosmos DB"""
        import time
        import random

        message_id = f"{conversation_id}_{role}_{int(time.time())}_{random.randint(1000, 9999)}"

        message_item = {
            'id': message_id,
            'conversation_id': conversation_id,
            'user_id': self.user_id,
            'role': role,
            'content': content,
            'timestamp': datetime.utcnow().isoformat()
        }

        cosmos_messages_container.upsert_item(message_item)
