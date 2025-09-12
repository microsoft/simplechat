# semantic_kernel_loader.py
"""
Loader for Semantic Kernel plugins/actions from app settings.
- Loads plugin/action manifests from settings (CosmosDB)
- Registers plugins with the Semantic Kernel instance
"""

from agent_orchestrator_groupchat import OrchestratorAgent, SCGroupChatManager
from semantic_kernel import Kernel
from semantic_kernel.agents import Agent
from semantic_kernel.connectors.ai.prompt_execution_settings import PromptExecutionSettings
from semantic_kernel.core_plugins import TimePlugin, HttpPlugin
from semantic_kernel.core_plugins.wait_plugin import WaitPlugin
from semantic_kernel_plugins.math_plugin import MathPlugin
from semantic_kernel_plugins.text_plugin import TextPlugin
from semantic_kernel.functions.kernel_plugin import KernelPlugin
from semantic_kernel_plugins.embedding_model_plugin import EmbeddingModelPlugin
from semantic_kernel_plugins.fact_memory_plugin import FactMemoryPlugin
from functions_settings import get_settings, get_user_settings
from functions_appinsights import log_event, get_appinsights_logger
from functions_authentication import get_current_user_id
from semantic_kernel_plugins.plugin_health_checker import PluginHealthChecker, PluginErrorRecovery
from semantic_kernel_plugins.logged_plugin_loader import create_logged_plugin_loader
from semantic_kernel_plugins.plugin_invocation_logger import get_plugin_logger
from functions_debug import debug_print
from flask import g
import logging
import importlib
import os
import importlib.util
import inspect
import builtins

# Agent and Azure OpenAI chat service imports
log_event("[SK Loader] Starting loader imports")
try:
    from semantic_kernel.agents import ChatCompletionAgent
    from agent_logging_chat_completion import LoggingChatCompletionAgent
    from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
except ImportError:
    ChatCompletionAgent = None
    AzureChatCompletion = None
    log_event(
        "[SK Loader] ChatCompletionAgent or AzureChatCompletion not available. Ensure you have the correct Semantic Kernel version.",
        level=logging.ERROR,
        exceptionTraceback=True
    )
log_event("[SK Loader] Completed imports")


# Define supported chat types in a single place
orchestration_types = [
    {
        "value": "default_agent",
        "label": "Selected Agent",
        "agent_mode": "single",
        "description": "Single-agent chat with the selected agent."
    }
]
"""
    {
        "value": "group_chat",
        "label": "Group Chat",
        "agent_mode": "multi",
        "description": "Multi-agent group chat orchestration."
    },
    {
        "value": "magnetic",
        "label": "Magnetic",
        "agent_mode": "multi",
        "description": "Multi-agent magnetic orchestration."
    }
"""
def get_agent_orchestration_types():
    """Returns the supported chat orchestration types (full metadata)."""
    return orchestration_types

def get_agent_orchestration_type_values():
    """Returns just the allowed values for validation/settings."""
    return [t["value"] for t in orchestration_types]

def get_agent_orchestration_types_by_mode(mode):
    """Filter orchestration types by agent_mode ('single' or 'multi')."""
    return [t for t in orchestration_types if t["agent_mode"] == mode]

def first_if_comma(val):
        if isinstance(val, str) and "," in val:
            return val.split(",")[0].strip()
        return val

def resolve_agent_config(agent, settings):
    debug_print(f"[SK Loader] resolve_agent_config called for agent: {agent.get('name')}")
    debug_print(f"[SK Loader] Agent config: {agent}")
    debug_print(f"[SK Loader] Agent is_global flag: {agent.get('is_global')}")

    gpt_model_obj = settings.get('gpt_model', {})
    selected_model = gpt_model_obj.get('selected', [{}])[0] if gpt_model_obj.get('selected') else {}
    debug_print(f"[SK Loader] Global selected_model: {selected_model}")
    debug_print(f"[SK Loader] Global selected_model deploymentName: {selected_model.get('deploymentName')}")

    # User APIM enabled if agent has enable_agent_gpt_apim True (or 1, or 'true')
    user_apim_enabled = agent.get("enable_agent_gpt_apim") in [True, 1, "true", "True"]
    global_apim_enabled = settings.get("enable_gpt_apim", False)
    per_user_enabled = settings.get('per_user_semantic_kernel', False)
    allow_user_custom_agent_endpoints = settings.get('allow_user_custom_agent_endpoints', False)
    allow_group_custom_agent_endpoints = settings.get('allow_group_custom_agent_endpoints', False)

    debug_print(f"[SK Loader] user_apim_enabled: {user_apim_enabled}, global_apim_enabled: {global_apim_enabled}, per_user_enabled: {per_user_enabled}")

    def any_filled(*fields):
        return any(bool(f) for f in fields)

    def all_filled(*fields):
        return all(bool(f) for f in fields)

    def get_user_apim():
        return (
            agent.get("azure_apim_gpt_endpoint"),
            agent.get("azure_apim_gpt_subscription_key"),
            agent.get("azure_apim_gpt_deployment"),
            agent.get("azure_apim_gpt_api_version")
        )

    def get_global_apim():
        return (
            settings.get("azure_apim_gpt_endpoint"),
            settings.get("azure_apim_gpt_subscription_key"),
            first_if_comma(settings.get("azure_apim_gpt_deployment")),
            settings.get("azure_apim_gpt_api_version")
        )

    def get_user_gpt():
        return (
            agent.get("azure_openai_gpt_endpoint"),
            agent.get("azure_openai_gpt_key"),
            agent.get("azure_openai_gpt_deployment"),
            agent.get("azure_openai_gpt_api_version")
        )

    def get_global_gpt():
        return (
            settings.get("azure_openai_gpt_endpoint") or selected_model.get("endpoint"),
            settings.get("azure_openai_gpt_key") or selected_model.get("key"),
            settings.get("azure_openai_gpt_deployment") or selected_model.get("deploymentName"),
            settings.get("azure_openai_gpt_api_version") or selected_model.get("api_version")
        )

    def merge_fields(primary, fallback):
        return tuple(p if p not in [None, ""] else f for p, f in zip(primary, fallback))

    # If per-user mode is not enabled, ignore all user/agent-specific config fields
    if not per_user_enabled:
        try:
            if global_apim_enabled:
                g_apim = get_global_apim()
                endpoint, key, deployment, api_version = g_apim
            else:
                g_gpt = get_global_gpt()
                endpoint, key, deployment, api_version = g_gpt
            return {
                "endpoint": endpoint,
                "key": key,
                "deployment": deployment,
                "api_version": api_version,
                "instructions": agent.get("instructions", ""),
                "actions_to_load": agent.get("actions_to_load", []),
                "additional_settings": agent.get("additional_settings", {}),
                "name": agent.get("name"),
                "display_name": agent.get("display_name", agent.get("name")),
                "description": agent.get("description", ""),
                "id": agent.get("id", ""),
                "default_agent": agent.get("default_agent", False),
                "is_global": agent.get("is_global", False),
                "enable_agent_gpt_apim": agent.get("enable_agent_gpt_apim", False)
            }
        except Exception as e:
            log_event(f"[SK Loader] Error resolving agent config: {e}", level=logging.ERROR, exceptionTraceback=True)

    # --- PATCHED DECISION TREE ---
    u_apim = get_user_apim()
    g_apim = get_global_apim()
    u_gpt = get_user_gpt()
    g_gpt = get_global_gpt()

    # 1. User APIM enabled and any user APIM values set: use user APIM (merge with global APIM if needed)
    if user_apim_enabled and any_filled(*u_apim) and allow_user_custom_agent_endpoints:
        debug_print(f"[SK Loader] Using user APIM with global fallback")
        merged = merge_fields(u_apim, g_apim if global_apim_enabled and any_filled(*g_apim) else (None, None, None, None))
        endpoint, key, deployment, api_version = merged
    # 2. User APIM enabled but no user APIM values, and global APIM enabled and present: use global APIM
    elif user_apim_enabled and global_apim_enabled and any_filled(*g_apim) and allow_group_custom_agent_endpoints:
        debug_print(f"[SK Loader] Using global APIM (user APIM enabled but not present)")
        endpoint, key, deployment, api_version = g_apim
    # 3. User GPT config is FULLY filled: use user GPT (all fields filled)
    elif all_filled(*u_gpt) and allow_user_custom_agent_endpoints:
        debug_print(f"[SK Loader] Using agent GPT config (all fields filled)")
        endpoint, key, deployment, api_version = u_gpt
    # 4. User GPT config is PARTIALLY filled, global APIM is NOT enabled: merge user GPT with global GPT
    elif any_filled(*u_gpt) and not global_apim_enabled and allow_user_custom_agent_endpoints:
        debug_print(f"[SK Loader] Using agent GPT config (partially filled, merging with global GPT, global APIM not enabled)")
        endpoint, key, deployment, api_version = merge_fields(u_gpt, g_gpt)
    # 5. Global APIM enabled and present: use global APIM
    elif global_apim_enabled and any_filled(*g_apim):
        debug_print(f"[SK Loader] Using global APIM (fallback)")
        endpoint, key, deployment, api_version = g_apim
    # 6. Fallback to global GPT config
    else:
        debug_print(f"[SK Loader] Using global GPT config (fallback)")
        endpoint, key, deployment, api_version = g_gpt

    result = {
        "endpoint": endpoint,
        "key": key,
        "deployment": deployment,
        "api_version": api_version,
        "instructions": agent.get("instructions", ""),
        "actions_to_load": agent.get("actions_to_load", []),
        "additional_settings": agent.get("additional_settings", {}),
        "name": agent.get("name"),
        "display_name": agent.get("display_name", agent.get("name")),
        "description": agent.get("description", ""),
        "id": agent.get("id", ""),
        "default_agent": agent.get("default_agent", False),  # [Deprecated, use 'selected_agent' or 'global_selected_agent' in agent config]
        "is_global": agent.get("is_global", False),  # Ensure we have this field
        "enable_agent_gpt_apim": agent.get("enable_agent_gpt_apim", False)  # Use this to check if APIM is enabled for the agent
    }

    print(f"[SK Loader] Final resolved config for {agent.get('name')}: endpoint={bool(endpoint)}, key={bool(key)}, deployment={deployment}")
    return result

def load_time_plugin(kernel: Kernel):
    kernel.add_plugin(
        TimePlugin(),
        plugin_name="time",
        description="Provides time-related functions."
    )

def load_http_plugin(kernel: Kernel):
    # Import the smart HTTP plugin for better content size management
    try:
        from semantic_kernel_plugins.smart_http_plugin import SmartHttpPlugin
        # Use smart HTTP plugin with 75k character limit (≈50k tokens)
        smart_plugin = SmartHttpPlugin(max_content_size=75000, extract_text_only=True)
        kernel.add_plugin(
            smart_plugin,
            plugin_name="http",
            description="Provides HTTP request functions with intelligent content size management for web scraping."
        )
        log_event("[SK Loader] Loaded Smart HTTP plugin with content size limits.", level=logging.INFO)
    except ImportError as e:
        log_event(f"[SK Loader] Smart HTTP plugin not available, falling back to standard HttpPlugin: {e}", level=logging.WARNING)
        # Fallback to standard HTTP plugin
        kernel.add_plugin(
            HttpPlugin(),
            plugin_name="http",
            description="Provides HTTP request functions for making API calls."
        )

def load_wait_plugin(kernel: Kernel):
    kernel.add_plugin(
        WaitPlugin(),
        plugin_name="wait",
        description="Provides wait functions for delaying execution."
    )

def load_math_plugin(kernel: Kernel):
    kernel.add_plugin(
        MathPlugin(),
        plugin_name="math",
        description="Provides mathematical calculation functions."
    )

def load_text_plugin(kernel: Kernel):
    kernel.add_plugin(
        TextPlugin(),
        plugin_name="text",
        description="Provides text manipulation functions."
    )

def load_fact_memory_plugin(kernel: Kernel):
    kernel.add_plugin(
        FactMemoryPlugin(),
        plugin_name="fact_memory",
        description="Provides functions for managing persistent facts."
    )

def load_embedding_model_plugin(kernel: Kernel, settings):
    embedding_endpoint = settings.get('azure_openai_embedding_endpoint')
    embedding_key = settings.get('azure_openai_embedding_key')
    embedding_model = settings.get('embedding_model', {}).get('selected', [None])[0]
    if embedding_endpoint and embedding_key and embedding_model:
        plugin = EmbeddingModelPlugin()
        kernel.add_plugin(
            plugin,
            plugin_name="embedding_model",
            description="Provides text embedding functions using the configured embedding model."
        )

def load_core_plugins_only(kernel: Kernel, settings):
    """Load only core plugins for model-only conversations without agents."""
    debug_print(f"[SK Loader] Loading core plugins only for model-only mode...")
    log_event("[SK Loader] Loading core plugins only for model-only mode...", level=logging.INFO)
    
    if settings.get('enable_time_plugin', True):
        load_time_plugin(kernel)
        log_event("[SK Loader] Loaded Time plugin.", level=logging.INFO)

    if settings.get('enable_fact_memory_plugin', True):
        load_fact_memory_plugin(kernel)
        log_event("[SK Loader] Loaded Fact Memory plugin.", level=logging.INFO)

    if settings.get('enable_math_plugin', True):
        load_math_plugin(kernel)
        log_event("[SK Loader] Loaded Math plugin.", level=logging.INFO)

    if settings.get('enable_text_plugin', True):
        load_text_plugin(kernel)
        log_event("[SK Loader] Loaded Text plugin.", level=logging.INFO)

# =================== Semantic Kernel Initialization ===================
def initialize_semantic_kernel(user_id: str=None, redis_client=None):
    debug_print(f"[SK Loader] Initializing Semantic Kernel and plugins...")
    log_event(
        "[SK Loader] Initializing Semantic Kernel and plugins...",
        level=logging.INFO
    )
    kernel, kernel_agents = Kernel(), None
    if not kernel:
        log_event(
            "[SK Loader] Failed to initialize Semantic Kernel.",
            level=logging.ERROR,
            exceptionTraceback=True
        )
    log_event(
        "[SK Loader] Starting to load Semantic Kernel Agent and Plugins",
        level=logging.INFO
    )
    settings = get_settings()
    print(f"[SK Loader] Settings check - per_user_semantic_kernel: {settings.get('per_user_semantic_kernel', False)}, user_id: {user_id}")
    log_event(f"[SK Loader] Settings check - per_user_semantic_kernel: {settings.get('per_user_semantic_kernel', False)}, user_id: {user_id}", level=logging.INFO)
    
    if settings.get('per_user_semantic_kernel', False) and user_id is not None:
        debug_print(f"[SK Loader] Using per-user semantic kernel mode")
        log_event("[SK Loader] Using per-user semantic kernel mode", level=logging.INFO)
        kernel, kernel_agents = load_user_semantic_kernel(kernel, settings, user_id=user_id, redis_client=redis_client)
        g.kernel = kernel
        g.kernel_agents = kernel_agents
        print(f"[SK Loader] Per-user mode - stored g.kernel_agents: {type(kernel_agents)} with {len(kernel_agents) if kernel_agents else 0} agents")
        log_event(f"[SK Loader] Per-user mode - stored g.kernel_agents: {type(kernel_agents)} with {len(kernel_agents) if kernel_agents else 0} agents", level=logging.INFO)
    else:
        debug_print(f"[SK Loader] Using global semantic kernel mode")
        log_event("[SK Loader] Using global semantic kernel mode", level=logging.INFO)
        kernel, kernel_agents = load_semantic_kernel(kernel, settings)
        builtins.kernel = kernel
        builtins.kernel_agents = kernel_agents
        print(f"[SK Loader] Global mode - stored builtins.kernel_agents: {type(kernel_agents)} with {len(kernel_agents) if kernel_agents else 0} agents")
        log_event(f"[SK Loader] Global mode - stored builtins.kernel_agents: {type(kernel_agents)} with {len(kernel_agents) if kernel_agents else 0} agents", level=logging.INFO)
        
    if kernel and not kernel_agents:
        debug_print(f"[SK Loader] No agents loaded - proceeding in model-only mode")
        log_event(
            "[SK Loader] No agents loaded - proceeding in model-only mode",
            level=logging.INFO
        )
    elif kernel_agents:
        agent_names = []
        if isinstance(kernel_agents, dict):
            agent_names = list(kernel_agents.keys())
        else:
            agent_names = [getattr(agent, 'name', 'unnamed') for agent in kernel_agents]
        print(f"[SK Loader] Successfully loaded {len(kernel_agents)} agents: {agent_names}")
        log_event(f"[SK Loader] Successfully loaded {len(kernel_agents)} agents: {agent_names}", level=logging.INFO)
    else:
        debug_print(f"[SK Loader] No agents loaded - kernel_agents is None")
        log_event("[SK Loader] No agents loaded - kernel_agents is None", level=logging.WARNING)
        
    log_event(
        "[SK Loader] Semantic Kernel Agent and Plugins loading completed.",
        extra={
            "kernel": str(kernel),
            "agents": [agent.name for agent in kernel_agents.values()] if kernel_agents else []
        },
        level=logging.INFO
    )
    debug_print(f"[SK Loader] Semantic Kernel Agent and Plugins loading completed.")

def load_agent_specific_plugins(kernel, plugin_names, mode_label="global", user_id=None):
    """
    Load specific plugins by name for an agent with enhanced logging.
    
    Args:
        kernel: The Semantic Kernel instance
        plugin_names: List of plugin names to load (from agent's actions_to_load)
        mode_label: 'per-user' or 'global' for logging
        user_id: User ID for per-user mode
    """
    if not plugin_names:
        return
        
    print(f"[SK Loader] Loading {len(plugin_names)} agent-specific plugins: {plugin_names}")
    
    try:
        # Create logged plugin loader for enhanced logging
        logged_loader = create_logged_plugin_loader(kernel)
        
        # Get plugin manifests based on mode
        if mode_label == "per-user":
            from functions_personal_actions import get_personal_actions
            if user_id:
                all_plugin_manifests = get_personal_actions(user_id)
                print(f"[SK Loader] Retrieved {len(all_plugin_manifests)} personal plugin manifests for user {user_id}")
            else:
                print(f"[SK Loader] Warning: No user_id provided for per-user plugin loading")
                all_plugin_manifests = []
        else:
            # Global mode - get from global actions container
            from functions_global_actions import get_global_actions
            all_plugin_manifests = get_global_actions()
            print(f"[SK Loader] Retrieved {len(all_plugin_manifests)} global plugin manifests")
            
        # Filter manifests to only include requested plugins
        # Check both 'name' and 'id' fields to support both UUID and name references
        plugin_manifests = [
            p for p in all_plugin_manifests 
            if p.get('name') in plugin_names or p.get('id') in plugin_names
        ]
        
        if not plugin_manifests:
            print(f"[SK Loader] Warning: No plugin manifests found for names/IDs: {plugin_names}")
            print(f"[SK Loader] Available plugin names: {[p.get('name') for p in all_plugin_manifests]}")
            print(f"[SK Loader] Available plugin IDs: {[p.get('id') for p in all_plugin_manifests]}")
            return
            
        print(f"[SK Loader] Found {len(plugin_manifests)} plugin manifests to load")
        
        # Use logged plugin loader for enhanced logging
        print(f"[SK Loader] Using logged plugin loader for enhanced logging")
        results = logged_loader.load_multiple_plugins(plugin_manifests, user_id)
        
        successful_count = sum(1 for success in results.values() if success)
        total_count = len(results)
        
        print(f"[SK Loader] Logged plugin loader results: {successful_count}/{total_count} successful")
        if results:
            for plugin_name, success in results.items():
                print(f"[SK Loader] Plugin {plugin_name}: {'SUCCESS' if success else 'FAILED'}")
        
        log_event(
            f"[SK Loader] Agent-specific plugins loaded: {successful_count}/{total_count} with enhanced logging [{mode_label}]",
            extra={
                "mode": mode_label,
                "user_id": user_id,
                "requested_plugins": plugin_names,
                "successful_plugins": [name for name, success in results.items() if success],
                "failed_plugins": [name for name, success in results.items() if not success],
                "total_plugins": total_count
            },
            level=logging.INFO
        )
        
        # Fallback to original method if logged loader fails completely
        if successful_count == 0 and total_count > 0:
            print(f"[SK Loader] WARNING: Logged plugin loader failed for all plugins, falling back to original method")
            log_event("[SK Loader] Falling back to original plugin loading method for agent plugins", level=logging.WARNING)
            _load_agent_plugins_original_method(kernel, plugin_manifests, mode_label)
        else:
            print(f"[SK Loader] Logged plugin loader completed successfully: {successful_count}/{total_count}")
        
    except Exception as e:
        log_event(
            f"[SK Loader] Error in agent-specific plugin loading: {e}",
            extra={"error": str(e), "mode": mode_label, "user_id": user_id, "plugin_names": plugin_names},
            level=logging.ERROR,
            exceptionTraceback=True
        )
        
        # Fallback to original method
        log_event("[SK Loader] Falling back to original plugin loading method due to error", level=logging.WARNING)
        try:
            # Get plugin manifests again for fallback
            if mode_label == "per-user":
                from functions_personal_actions import get_personal_actions
                if user_id:
                    all_plugin_manifests = get_personal_actions(user_id)
                else:
                    all_plugin_manifests = []
            else:
                from functions_global_actions import get_global_actions
                all_plugin_manifests = get_global_actions()
                
            plugin_manifests = [p for p in all_plugin_manifests if p.get('name') in plugin_names]
            _load_agent_plugins_original_method(kernel, plugin_manifests, mode_label)
        except Exception as fallback_error:
            log_event(
                f"[SK Loader] Fallback plugin loading also failed: {fallback_error}",
                extra={"error": str(fallback_error), "mode": mode_label, "user_id": user_id},
                level=logging.ERROR,
                exceptionTraceback=True
            )


def _load_agent_plugins_original_method(kernel, plugin_manifests, mode_label="global"):
    """
    Original agent plugin loading method as fallback.
    """
    try:
        # Load the filtered plugins using original method
        from semantic_kernel_plugins.plugin_loader import discover_plugins
        discovered_plugins = discover_plugins()
        
        for manifest in plugin_manifests:
            plugin_type = manifest.get('type')
            name = manifest.get('name')
            description = manifest.get('description', '')
            
            # Normalize for matching
            def normalize(s):
                return s.replace('_', '').replace('-', '').replace('plugin', '').lower() if s else ''
            normalized_type = normalize(plugin_type)
            
            matched_class = None
            for class_name, cls in discovered_plugins.items():
                normalized_class = normalize(class_name)
                if normalized_type == normalized_class or normalized_type in normalized_class:
                    matched_class = cls
                    break
                    
            if matched_class:
                try:
                    # Special handling for OpenAPI plugins
                    if normalized_type == normalize('openapi') or 'openapi' in normalized_type:
                        from semantic_kernel_plugins.openapi_plugin_factory import OpenApiPluginFactory
                        plugin = OpenApiPluginFactory.create_from_config(manifest)
                        print(f"[SK Loader] Created OpenAPI plugin: {name}")
                    else:
                        # Standard plugin instantiation
                        from semantic_kernel_plugins.plugin_health_checker import PluginHealthChecker, PluginErrorRecovery
                        plugin_instance, instantiation_errors = PluginHealthChecker.create_plugin_safely(
                            matched_class, manifest, name
                        )
                        
                        if plugin_instance is None:
                            plugin_instance = PluginErrorRecovery.create_fallback_plugin(name, plugin_type)
                            
                        if plugin_instance is None:
                            raise Exception(f"Plugin creation failed: {'; '.join(instantiation_errors)}")
                            
                        plugin = plugin_instance
                    
                    # Add plugin to kernel
                    from semantic_kernel.functions.kernel_plugin import KernelPlugin
                    
                    # Special handling for OpenAPI plugins with dynamic functions
                    if hasattr(plugin, 'get_kernel_plugin'):
                        print(f"[SK Loader] Using custom kernel plugin method for: {name}")
                        kernel_plugin = plugin.get_kernel_plugin(name)
                        kernel.add_plugin(kernel_plugin)
                    else:
                        # Standard plugin registration
                        kernel.add_plugin(KernelPlugin.from_object(name, plugin, description=description))
                    
                    print(f"[SK Loader] Successfully loaded agent plugin: {name} (type: {plugin_type})")
                    log_event(f"[SK Loader] Successfully loaded agent plugin: {name} (type: {plugin_type}) [{mode_label}]", 
                            {"plugin_name": name, "plugin_type": plugin_type}, level=logging.INFO)
                            
                except Exception as e:
                    print(f"[SK Loader] Failed to load agent plugin {name}: {e}")
                    log_event(f"[SK Loader] Failed to load agent plugin: {name}: {e}", 
                            {"plugin_name": name, "plugin_type": plugin_type, "error": str(e)}, 
                            level=logging.ERROR, exceptionTraceback=True)
            else:
                print(f"[SK Loader] No matching plugin class found for: {name} (type: {plugin_type})")
                log_event(f"[SK Loader] No matching plugin class found for: {name} (type: {plugin_type})", 
                        {"plugin_name": name, "plugin_type": plugin_type}, level=logging.WARNING)
                        
    except Exception as e:
        print(f"[SK Loader] Error loading agent-specific plugins: {e}")
        log_event(f"[SK Loader] Error loading agent-specific plugins: {e}", level=logging.ERROR, exceptionTraceback=True)

def load_single_agent_for_kernel(kernel, agent_cfg, settings, context_obj, redis_client=None, mode_label="global"):
    """
    DRY helper to load a single agent (default agent) for the kernel.
    - context_obj: g (per-user) or builtins (global)
    - redis_client: required for per-user mode
    - mode_label: 'per-user' or 'global' (for logging)
    Returns: kernel, agent_objs // dict (name->agent) or None
    """
    print(f"[SK Loader] load_single_agent_for_kernel starting - agent: {agent_cfg.get('name')}, mode: {mode_label}")
    log_event(f"[SK Loader] load_single_agent_for_kernel starting - agent: {agent_cfg.get('name')}, mode: {mode_label}", level=logging.INFO)
    
    # Redis is now optional for per-user mode
    if mode_label == "per-user":
        context_obj.redis_client = redis_client
    agent_objs = {}
    agent_config = resolve_agent_config(agent_cfg, settings)
    print(f"[SK Loader] Agent config resolved for {agent_cfg.get('name')}: endpoint={bool(agent_config.get('endpoint'))}, key={bool(agent_config.get('key'))}, deployment={agent_config.get('deployment')}")
    service_id = f"aoai-chat-{agent_config['name']}"
    chat_service = None
    apim_enabled = settings.get("enable_gpt_apim", False)
    
    log_event(f"[SK Loader] Agent config resolved - endpoint: {bool(agent_config.get('endpoint'))}, key: {bool(agent_config.get('key'))}, deployment: {agent_config.get('deployment')}", level=logging.INFO)
    
    if AzureChatCompletion and agent_config["endpoint"] and agent_config["key"] and agent_config["deployment"]:
        print(f"[SK Loader] Azure config valid for {agent_config['name']}, creating chat service...")
        if apim_enabled:
            log_event(
                f"[SK Loader] Initializing APIM AzureChatCompletion for agent: {agent_config['name']} ({mode_label})",
                {
                    "aoai_endpoint": agent_config["endpoint"],
                    "aoai_key": f"{agent_config['key'][:3]}..." if agent_config["key"] else None,
                    "aoai_deployment": agent_config["deployment"],
                    "agent_name": agent_config["name"]
                },
                level=logging.INFO
            )
            chat_service = AzureChatCompletion(
                service_id=service_id,
                deployment_name=agent_config["deployment"],
                endpoint=agent_config["endpoint"],
                api_key=agent_config["key"],
                api_version=agent_config["api_version"],
                # default_headers={"Ocp-Apim-Subscription-Key": agent_config["key"]}
            )
        else:
            log_event(
                f"[SK Loader] Initializing GPT Direct AzureChatCompletion for agent: {agent_config['name']} ({mode_label})",
                {
                    "aoai_endpoint": agent_config["endpoint"],
                    "aoai_key": f"{agent_config['key'][:3]}..." if agent_config["key"] else None,
                    "aoai_deployment": agent_config["deployment"],
                    "agent_name": agent_config["name"]
                },
                level=logging.INFO
            )
            chat_service = AzureChatCompletion(
                service_id=service_id,
                deployment_name=agent_config["deployment"],
                endpoint=agent_config["endpoint"],
                api_key=agent_config["key"],
                api_version=agent_config["api_version"]
            )
        kernel.add_service(chat_service)
        log_event(
            f"[SK Loader] AOAI chat completion service registered for agent: {agent_config['name']} ({mode_label})",
            {
                "aoai_endpoint": agent_config["endpoint"],
                "aoai_key": f"{agent_config['key'][:3]}..." if agent_config["key"] else None,
                "aoai_deployment": agent_config["deployment"],
                "agent_name": agent_config["name"],
                "apim_enabled": agent_config.get("enable_agent_gpt_apim", False)
            },
            level=logging.INFO
        )
    else:
        print(f"[SK Loader] Azure config INVALID for {agent_config['name']}:")
        print(f"  - AzureChatCompletion available: {bool(AzureChatCompletion)}")
        print(f"  - endpoint: {bool(agent_config.get('endpoint'))}")
        print(f"  - key: {bool(agent_config.get('key'))}")
        print(f"  - deployment: {bool(agent_config.get('deployment'))}")
        log_event(
            f"[SK Loader] AzureChatCompletion or configuration not resolved for agent: {agent_config['name']} ({mode_label})",
            {
                "agent_name": agent_config["name"],
                "aoai_endpoint": agent_config["endpoint"],
                "aoai_key": f"{agent_config['key'][:3]}..." if agent_config["key"] else None,
                "aoai_deployment": agent_config["deployment"],
            },
            level=logging.ERROR,
            exceptionTraceback=True
        )
        print(f"[SK Loader] Returning None, None for agent {agent_config['name']} due to invalid config")
        return None, None
    if LoggingChatCompletionAgent and chat_service:
        print(f"[SK Loader] Creating LoggingChatCompletionAgent for {agent_config['name']}...")
        
        # Load agent-specific plugins into the kernel before creating the agent
        if agent_config.get("actions_to_load"):
            print(f"[SK Loader] Loading agent-specific plugins: {agent_config['actions_to_load']}")
            # Determine plugin source based on agent's global status, not overall mode
            agent_is_global = agent_config.get("is_global", False)
            plugin_mode = "global" if agent_is_global else mode_label
            user_id = get_current_user_id() if not agent_is_global else None
            print(f"[SK Loader] Agent is_global: {agent_is_global}, using plugin_mode: {plugin_mode}")
            load_agent_specific_plugins(kernel, agent_config["actions_to_load"], plugin_mode, user_id=user_id)
        
        try:
            kwargs = {
                "name": agent_config["name"],
                "instructions": agent_config["instructions"],
                "kernel": kernel,
                "service": chat_service,
                "description": agent_config["description"] or agent_config["name"] or "This agent can be assigned to execute tasks and be part of a conversation as a generalist.",
                "id": agent_config.get('id') or agent_config.get('name') or f"agent_1",
                "display_name": agent_config.get('display_name') or agent_config.get('name') or "agent",
                "default_agent": agent_config.get("default_agent", False),
                "deployment_name": agent_config["deployment"],
                "azure_endpoint": agent_config["endpoint"],
                "api_version": agent_config["api_version"]
            }
            # Don't pass plugins to agent since they're already loaded in kernel
            agent_obj = LoggingChatCompletionAgent(**kwargs)
            
            agent_objs[agent_config["name"]] = agent_obj
            print(f"[SK Loader] Successfully created agent {agent_config['name']}")
            log_event(
                f"[SK Loader] ChatCompletionAgent initialized for agent: {agent_config['name']} ({mode_label})",
                {
                    "aoai_endpoint": agent_config["endpoint"],
                    "aoai_key": f"{agent_config['key'][:3]}..." if agent_config["key"] else None,
                    "aoai_deployment": agent_config["deployment"],
                    "agent_name": agent_config["name"]
                },
                level=logging.INFO
            )
        except Exception as e:
            print(f"[SK Loader] EXCEPTION creating agent {agent_config['name']}: {e}")
            log_event(
                f"[SK Loader] Failed to initialize ChatCompletionAgent for agent: {agent_config['name']} ({mode_label}): {e}",
                {"error": str(e), "agent_name": agent_config["name"]},
                level=logging.ERROR,
                exceptionTraceback=True
            )
            print(f"[SK Loader] Returning None, None due to agent creation exception")
            return None, None
    else:
        print(f"[SK Loader] Cannot create agent - LoggingChatCompletionAgent available: {bool(LoggingChatCompletionAgent)}, chat_service available: {bool(chat_service)}")
        log_event(
            f"[SK Loader] ChatCompletionAgent or AzureChatCompletion not available for agent: {agent_config['name']} ({mode_label})",
            {"agent_name": agent_config["name"]},
            level=logging.ERROR,
            exceptionTraceback=True
        )
        print(f"[SK Loader] Returning None, None due to missing dependencies")
        return None, None
    
    print(f"[SK Loader] load_single_agent_for_kernel completed - returning {len(agent_objs)} agents: {list(agent_objs.keys())}")
    log_event(f"[SK Loader] load_single_agent_for_kernel completed - returning {len(agent_objs)} agents: {list(agent_objs.keys())}", level=logging.INFO)
    return kernel, agent_objs

def load_plugins_for_kernel(kernel, plugin_manifests, settings, mode_label="global"):
    """
    DRY helper to load plugins from a manifest list (user or global).
    """
    # Create logged plugin loader for enhanced logging
    logged_loader = create_logged_plugin_loader(kernel)
    
    if settings.get('enable_time_plugin', True):
        load_time_plugin(kernel)
        log_event("[SK Loader] Loaded Time plugin.", level=logging.INFO)
    else:
        log_event("[SK Loader] Time plugin not enabled in settings.", level=logging.INFO)

    if settings.get('enable_http_plugin', True):
        try:
            load_http_plugin(kernel)
            log_event("[SK Loader] Loaded HTTP plugin.", level=logging.INFO)
        except Exception as e:
            log_event(f"[SK Loader] Failed to load HTTP plugin: {e}", level=logging.WARNING)
    else:
        log_event("[SK Loader] HTTP plugin not enabled in settings.", level=logging.INFO)

    if settings.get('enable_wait_plugin', True):
        try:
            load_wait_plugin(kernel)
            log_event("[SK Loader] Loaded Wait plugin.", level=logging.INFO)
        except Exception as e:
            log_event(f"[SK Loader] Failed to load Wait plugin: {e}", level=logging.WARNING)
    else:
        log_event("[SK Loader] Wait plugin not enabled in settings.", level=logging.INFO)

    # Register Math Plugin if enabled
    if settings.get('enable_math_plugin', True):
        try:
            load_math_plugin(kernel)
            log_event("[SK Loader] Loaded Math plugin.", level=logging.INFO)
        except Exception as e:
            log_event(f"[SK Loader] Failed to load Math plugin: {e}", level=logging.WARNING)
    else:
        log_event("[SK Loader] Math plugin not enabled in settings.", level=logging.INFO)

    # Register Text Plugin if enabled
    if settings.get('enable_text_plugin', True):
        try:
            load_text_plugin(kernel)
            log_event("[SK Loader] Loaded Text plugin.", level=logging.INFO)
        except Exception as e:
            log_event(f"[SK Loader] Failed to load Text plugin: {e}", level=logging.WARNING)
    else:
        log_event("[SK Loader] Text plugin not enabled in settings.", level=logging.INFO)

    # Register Fact Memory Plugin if enabled
    if settings.get('enable_fact_memory_plugin', False):
        try:
            load_fact_memory_plugin(kernel)
            log_event("[SK Loader] Loaded Fact Memory Plugin.", level=logging.INFO)
        except Exception as e:
            log_event(f"[SK Loader] Failed to load Fact Memory Plugin: {e}", level=logging.WARNING)

    # Conditionally load static embedding model plugin
    if settings.get('enable_default_embedding_model_plugin', True):
        try:
            load_embedding_model_plugin(kernel, settings)
            log_event("[SK Loader] Loaded Static Embedding Model Plugin.", level=logging.INFO)
        except Exception as e:
            log_event(f"[SK Loader] Failed to load static Embedding Model Plugin: {e}", level=logging.WARNING)
    else:
        log_event("[SK Loader] Default EmbeddingModelPlugin not enabled in settings.", level=logging.INFO)
    
    if not plugin_manifests:
        log_event(f"[SK Loader] No plugins to load for {mode_label} mode.", level=logging.INFO)
        return
    
    # Use the logged plugin loader for custom plugins
    try:
        user_id = None
        try:
            user_id = get_current_user_id()
        except Exception:
            pass  # User ID is optional for plugin loading
        
        # Load plugins with enhanced logging
        results = logged_loader.load_multiple_plugins(plugin_manifests, user_id)
        
        successful_count = sum(1 for success in results.values() if success)
        total_count = len(results)
        
        log_event(
            f"[SK Loader] Loaded {successful_count}/{total_count} custom plugins with invocation logging enabled [{mode_label}]",
            extra={
                "mode": mode_label,
                "successful_plugins": [name for name, success in results.items() if success],
                "failed_plugins": [name for name, success in results.items() if not success],
                "total_plugins": total_count,
                "user_id": user_id
            },
            level=logging.INFO
        )
        
    except Exception as e:
        log_event(
            f"[SK Loader] Error loading plugins with logged loader for {mode_label} mode: {e}", 
            extra={"error": str(e), "mode": mode_label}, 
            level=logging.ERROR, 
            exceptionTraceback=True
        )
        
        # Fallback to original plugin loading method
        log_event("[SK Loader] Falling back to original plugin loading method", level=logging.WARNING)
        _load_plugins_original_method(kernel, plugin_manifests, settings, mode_label)


def _load_plugins_original_method(kernel, plugin_manifests, settings, mode_label="global"):
    """
    Original plugin loading method as fallback.
    """
    try:
        from semantic_kernel_plugins.plugin_loader import discover_plugins
        discovered_plugins = discover_plugins()
        for manifest in plugin_manifests:
            plugin_type = manifest.get('type')
            name = manifest.get('name')
            description = manifest.get('description', '')
            # Normalize for matching
            def normalize(s):
                return s.replace('_', '').replace('-', '').replace('plugin', '').lower() if s else ''
            normalized_type = normalize(plugin_type)
            matched_class = None
            for class_name, cls in discovered_plugins.items():
                normalized_class = normalize(class_name)
                if normalized_type == normalized_class or normalized_type in normalized_class:
                    matched_class = cls
                    break
            if matched_class:
                try:
                    # Special handling for OpenAPI plugins
                    if normalized_type == normalize('openapi') or 'openapi' in normalized_type:
                        from semantic_kernel_plugins.openapi_plugin_factory import OpenApiPluginFactory
                        # Use the factory to create OpenAPI plugins from configuration
                        plugin = OpenApiPluginFactory.create_from_config(manifest)
                    else:
                        # Standard plugin instantiation with health checking and robust error handling
                        plugin_instance, instantiation_errors = PluginHealthChecker.create_plugin_safely(
                            matched_class, manifest, name
                        )
                        
                        if plugin_instance is None:
                            # Try fallback plugin if main plugin fails
                            log_event(f"[SK Loader] Creating fallback plugin for {name} due to instantiation failures: {'; '.join(instantiation_errors)}", 
                                    {"plugin_name": name, "plugin_type": plugin_type, "errors": instantiation_errors}, level=logging.WARNING)
                            plugin_instance = PluginErrorRecovery.create_fallback_plugin(name, plugin_type)
                        
                        if plugin_instance is None:
                            raise Exception(f"Both main and fallback plugin creation failed: {'; '.join(instantiation_errors)}")
                        
                        plugin = plugin_instance
                    
                    # Validate plugin has required methods
                    if hasattr(plugin, 'get_functions'):
                        try:
                            functions = plugin.get_functions()
                            log_event(f"[SK Loader] Plugin {name} exposes {len(functions) if functions else 0} functions", 
                                    {"plugin_name": name, "plugin_type": plugin_type, "function_count": len(functions) if functions else 0}, 
                                    level=logging.DEBUG)
                        except Exception as e:
                            log_event(f"[SK Loader] Warning: Plugin {name} get_functions() failed: {e}", 
                                    {"plugin_name": name, "plugin_type": plugin_type, "error": str(e)}, level=logging.WARNING)
                    
                    kernel.add_plugin(KernelPlugin.from_object(name, plugin, description=description))
                    log_event(f"[SK Loader] Successfully loaded plugin: {name} (type: {plugin_type}) [{mode_label}]", 
                            {"plugin_name": name, "plugin_type": plugin_type}, level=logging.INFO)
                except Exception as e:
                    log_event(f"[SK Loader] Failed to instantiate plugin: {name}: {e}", 
                            {"plugin_name": name, "plugin_type": plugin_type, "error": str(e), "error_type": type(e).__name__}, 
                            level=logging.ERROR, exceptionTraceback=True)
                    # Continue with other plugins instead of failing completely
                    continue
            else:
                log_event(f"[SK Loader] Unknown plugin type: {plugin_type} for plugin '{name}' [{mode_label}]", 
                        {"plugin_name": name, "plugin_type": plugin_type}, level=logging.WARNING)
    except Exception as e:
        log_event(f"[SK Loader] Error discovering plugin types for {mode_label} mode: {e}", {"error": str(e)}, level=logging.ERROR, exceptionTraceback=True)

def load_user_semantic_kernel(kernel: Kernel, settings, user_id: str, redis_client):
    debug_print(f"[SK Loader] Per-user Semantic Kernel mode enabled. Loading user-specific plugins and agents.")
    log_event("[SK Loader] Per-user Semantic Kernel mode enabled. Loading user-specific plugins and agents.", 
        level=logging.INFO
    )
    
    # Early check: Get user settings to see if agents are enabled and if an agent is selected
    user_settings = get_user_settings(user_id).get('settings', {})
    enable_agents = user_settings.get('enable_agents', True)  # Default to True for backward compatibility
    selected_agent = user_settings.get('selected_agent')
    
    # If agents are disabled or no agent is selected, skip agent loading entirely
    if not enable_agents:
        print(f"[SK Loader] User {user_id} has agents disabled. Proceeding in model-only mode.")
        log_event(f"[SK Loader] User {user_id} has agents disabled. Proceeding in model-only mode.", level=logging.INFO)
        # Still load core plugins for basic functionality
        load_core_plugins_only(kernel, settings)
        return kernel, None
        
    if not selected_agent:
        print(f"[SK Loader] User {user_id} has no agent selected. Proceeding in model-only mode.")
        log_event(f"[SK Loader] User {user_id} has no agent selected. Proceeding in model-only mode.", level=logging.INFO)
        # Still load core plugins for basic functionality
        load_core_plugins_only(kernel, settings)
        return kernel, None
    
    # Redis is now optional for per-user mode. If not present, state will not persist.
    
    # Load agents from personal_agents container
    from functions_personal_agents import get_personal_agents, ensure_migration_complete
    
    # Ensure migration is complete (will migrate any remaining legacy data)
    ensure_migration_complete(user_id)
    agents_cfg = get_personal_agents(user_id)
    
    print(f"[SK Loader] User settings found {len(agents_cfg)} agents for user '{user_id}'")
    
    # Always mark user agents as is_global: False
    for agent in agents_cfg:
        agent['is_global'] = False

    # PATCH: Merge global agents if enabled
    merge_global = settings.get('merge_global_semantic_kernel_with_workspace', False)
    print(f"[SK Loader] merge_global_semantic_kernel_with_workspace: {merge_global}")
    if merge_global:
        from functions_global_agents import get_global_agents
        global_agents = get_global_agents()
        print(f"[SK Loader] Found {len(global_agents)} global agents to merge")
        # Mark global agents
        for agent in global_agents:
            agent['is_global'] = True
        
        # Use unique keys to prevent name conflicts between personal and global agents
        # This allows both personal and global agents with same name to coexist
        all_agents = {}
        
        # Add global agents first with 'global_' prefix
        for agent in global_agents:
            key = f"global_{agent['name']}"
            all_agents[key] = agent
            
        # Add personal agents with 'personal_' prefix  
        for agent in agents_cfg:
            key = f"personal_{agent['name']}"
            all_agents[key] = agent
            
        agents_cfg = list(all_agents.values())
        print(f"[SK Loader] After merging: {len(agents_cfg)} total agents")
        debug_print(f"[SK Loader] Merged agents: {[(a.get('name'), a.get('is_global', False)) for a in agents_cfg]}")
        log_event(f"[SK Loader] Merged global agents into per-user agents: {[a.get('name') for a in agents_cfg]}", level=logging.INFO)

    log_event(f"[SK Loader] Found {len(agents_cfg)} agents for user '{user_id}'.",
        extra={
            "user_id": user_id,
            "agents_count": len(agents_cfg),
            "agents": agents_cfg
        },
        level=logging.INFO)
        
    # Load plugins from personal_actions container
    from functions_personal_actions import get_personal_actions, ensure_migration_complete
    
    # Ensure migration is complete (will migrate any remaining legacy data)
    ensure_migration_complete(user_id)
    plugin_manifests = get_personal_actions(user_id)
        
    # PATCH: Merge global plugins if enabled
    if merge_global:
        from functions_global_actions import get_global_actions
        global_plugins = get_global_actions()
        # User plugins take precedence
        all_plugins = {p.get('name'): p for p in plugin_manifests}
        all_plugins.update({p.get('name'): p for p in global_plugins})
        plugin_manifests = list(all_plugins.values())
        log_event(f"[SK Loader] Merged global plugins into per-user plugins: {[p.get('name') for p in plugin_manifests]}", level=logging.INFO)
    
    # DON'T load all user plugins globally - only load core plugins for per-user mode
    # Agent-specific plugins will be loaded by the agent itself based on actions_to_load
    # Only load core Semantic Kernel plugins here
    if settings.get('enable_time_plugin', True):
        load_time_plugin(kernel)
        log_event("[SK Loader] Loaded Time plugin.", level=logging.INFO)

    if settings.get('enable_fact_memory_plugin', True):
        load_fact_memory_plugin(kernel)
        log_event("[SK Loader] Loaded Fact Memory plugin.", level=logging.INFO)

    if settings.get('enable_math_plugin', True):
        load_math_plugin(kernel)
        log_event("[SK Loader] Loaded Math plugin.", level=logging.INFO)

    if settings.get('enable_text_plugin', True):
        load_text_plugin(kernel)
        log_event("[SK Loader] Loaded Text plugin.", level=logging.INFO)

    if settings.get('enable_http_plugin', True):
        load_http_plugin(kernel)
        log_event("[SK Loader] Loaded HTTP plugin.", level=logging.INFO)

    if settings.get('enable_wait_plugin', True):
        load_wait_plugin(kernel)
        log_event("[SK Loader] Loaded Wait plugin.", level=logging.INFO)

    if settings.get('enable_default_embedding_model_plugin', True):
        load_embedding_model_plugin(kernel, settings)
        log_event("[SK Loader] Loaded Default Embedding Model plugin.", level=logging.INFO)
    
    # Get selected agent from user settings (this still needs to be in user settings for UI state)
    user_settings = get_user_settings(user_id).get('settings', {})
    selected_agent = user_settings.get('selected_agent')
    debug_print(f"[SK Loader] User settings selected_agent: {selected_agent}")
    debug_print(f"[SK Loader] Type of selected_agent: {type(selected_agent)}")
    if isinstance(selected_agent, dict):
        selected_agent_name = selected_agent.get('name')
        is_global_flag = selected_agent.get('is_global', False)
        debug_print(f"[SK Loader] Selected agent name: {selected_agent_name}")
        debug_print(f"[SK Loader] Selected agent is_global flag: {is_global_flag}")
    else:
        debug_print(f"[SK Loader] User {user_id} selected_agent is not a dict: {selected_agent}. Using None.")
        log_event(
            f"[SK Loader] User {user_id} selected_agent is not a dict: {selected_agent}. Using None.",
            level=logging.ERROR
        )
        selected_agent_name = None
        is_global_flag = False
    debug_print(f"[SK Loader] Selected agent name: {selected_agent_name}")
    debug_print(f"[SK Loader] Selected agent global flag: {is_global_flag}")
    agent_cfg = None
    # Try user-selected agent
    if selected_agent_name:
        debug_print(f"[SK Loader] Looking for agent named '{selected_agent_name}' with is_global={is_global_flag}")
        debug_print(f"[SK Loader] Available agents: {[{a.get('name'): a.get('is_global', False)} for a in agents_cfg]}")
        
        # First try to find exact match including is_global flag
        found = next((a for a in agents_cfg if a.get('name') == selected_agent_name and a.get('is_global', False) == is_global_flag), None)
        if found:
            debug_print(f"[SK Loader] User {user_id} Found EXACT match for agent: {selected_agent_name} (is_global={is_global_flag})")
            agent_cfg = found
        else:
            # Fallback: try to find by name only
            found = next((a for a in agents_cfg if a.get('name') == selected_agent_name), None)
            if found:
                debug_print(f"[SK Loader] User {user_id} Found NAME-ONLY match for agent: {selected_agent_name} (requested is_global={is_global_flag}, found is_global={found.get('is_global', False)})")
                agent_cfg = found
            else:
                debug_print(f"[SK Loader] User {user_id} NO agent found matching user-selected agent: {selected_agent_name}")
        
        if found:
            print(f"[SK Loader] User {user_id} Found user-selected agent: {selected_agent_name}")
            logging.debug(f"[SK Loader] User {user_id} Found user-selected agent: {selected_agent_name}")
            agent_cfg = found
        else:
            print(f"[SK Loader] User {user_id} No agent found matching user-selected agent: {selected_agent_name}")
            log_event(
                f"[SK Loader] User {user_id} No agent found matching user-selected agent: {selected_agent_name}",
                level=logging.WARNING
            )
    # If not found, try global selected agent
    if agent_cfg is None:
        print(f"[SK Loader] User {user_id} No user-selected agent found. Trying global selected agent.")
        logging.debug(f"[SK Loader] User {user_id} No user-selected agent found. Trying global selected agent.")
        global_selected_agent_info = settings.get('global_selected_agent')
        print(f"[SK Loader] Global selected agent info: {global_selected_agent_info}")
        if global_selected_agent_info:
            global_selected_agent_name = global_selected_agent_info.get('name')
            found = next((a for a in agents_cfg if a.get('name') == global_selected_agent_name), None)
            if found:
                print(f"[SK Loader] User {user_id} Found global selected agent: {global_selected_agent_name}")
                logging.debug(f"[SK Loader] User {user_id} Found global selected agent: {global_selected_agent_name}")
                agent_cfg = found
            else:
                print(f"[SK Loader] User {user_id} No agent found matching global selected agent: {global_selected_agent_name}")
                log_event(
                    f"[SK Loader] User {user_id} No agent found matching global selected agent: {global_selected_agent_name}",
                    level=logging.WARNING
                )
    # If still not found, DON'T use first agent - only load when explicitly selected
    if agent_cfg is None and agents_cfg:
        debug_print(f"[SK Loader] User {user_id} Agent selection final status: agent_cfg is None")
        debug_print(f"[SK Loader] User {user_id} Available agents: {[{a.get('name'): a.get('is_global', False)} for a in agents_cfg]}")
        debug_print(f"[SK Loader] User {user_id} Requested agent: '{selected_agent_name}' with is_global={is_global_flag}")
        print(f"[SK Loader] User {user_id} No agent selected. Proceeding in model-only mode - no agents loaded.")
        log_event(
            f"[SK Loader] User {user_id} No agent selected. Proceeding in model-only mode - no agents loaded.",
            level=logging.INFO
        )
        return kernel, None
        
    if agent_cfg is None:
        debug_print(f"[SK Loader] User {user_id} No agents_cfg available at all - empty agent list")
        print(f"[SK Loader] User {user_id} No agent found to load for user. Proceeding in kernel-only mode (per-user).")
        log_event("[SK Loader] No agent found to load for user. Proceeding in kernel-only mode (per-user).", level=logging.INFO)
        return kernel, None
    
    debug_print(f"[SK Loader] User {user_id} Final agent selected: {agent_cfg.get('name')} (is_global={agent_cfg.get('is_global', False)})")
    debug_print(f"[SK Loader] User {user_id} Agent model: {agent_cfg.get('model', 'NOT SET')}")
    debug_print(f"[SK Loader] User {user_id} Agent azure_deployment: {agent_cfg.get('azure_deployment', 'NOT SET')}")
    
    print(f"[SK Loader] User {user_id} Loading agent: {agent_cfg.get('name')}")
    kernel, agent_objs = load_single_agent_for_kernel(kernel, agent_cfg, settings, g, redis_client=redis_client, mode_label="per-user")
    print(f"[SK Loader] User {user_id} Agent loading completed. Agent objects: {type(agent_objs)} with {len(agent_objs) if agent_objs else 0} items")
    return kernel, agent_objs

def load_semantic_kernel(kernel: Kernel, settings):
    log_event("[SK Loader] Loading Semantic Kernel plugins...")
    log_event("[SK Loader] Global Semantic Kernel mode enabled. Loading global plugins and agents.", level=logging.INFO)
    
    # Conditionally load core plugins based on settings
    from functions_global_actions import get_global_actions
    plugin_manifests = get_global_actions()
    log_event(f"[SK Loader] Found {len(plugin_manifests)} plugin manifests", level=logging.INFO)
    
    # --- Dynamic Plugin Type Loading (semantic_kernel_plugins) ---
    load_plugins_for_kernel(kernel, plugin_manifests, settings, mode_label="global")

# --- Agent and Service Loading ---
# region Multi-agent Orchestration
    from functions_global_agents import get_global_agents
    agents_cfg = get_global_agents()
    enable_multi_agent_orchestration = settings.get('enable_multi_agent_orchestration', False)
    merge_global = settings.get('merge_global_semantic_kernel_with_workspace', False)
    
    log_event(f"[SK Loader] Configuration check - agents_cfg count: {len(agents_cfg)}, enable_multi_agent_orchestration: {enable_multi_agent_orchestration}, merge_global: {merge_global}", level=logging.INFO)
    
    # PATCH: Merge global agents if enabled
    if merge_global:
        global_agents = []
        global_selected_agent_info = settings.get('global_selected_agent')
        if global_selected_agent_info:
            global_agent = next((a for a in agents_cfg if a.get('name') == global_selected_agent_info.get('name')), None)
            if global_agent:
                # Badge as global
                global_agent = dict(global_agent)  # Copy to avoid mutating original
                global_agent['is_global'] = True
                global_agents.append(global_agent)
        # Merge global agents into agents_cfg if not already present
        merged_agents = agents_cfg.copy()
        for ga in global_agents:
            if not any(a.get('name') == ga.get('name') for a in merged_agents):
                merged_agents.append(ga)
        agents_cfg = merged_agents
        log_event(f"[SK Loader] Merged global agents into workspace agents: {[a.get('name') for a in agents_cfg]}", level=logging.INFO)
    # END PATCH
    
    agent_objs = None
    
    if enable_multi_agent_orchestration and len(agents_cfg) > 0:
        log_event(f"[SK Loader] Starting multi-agent orchestration setup with {len(agents_cfg)} agents", level=logging.INFO)
        agent_objs = {}
        orchestrator_cfg = None
        specialist_agents: list[Agent] = []
        # First pass: create all specialist agents (not orchestrator)
        for agent_cfg in agents_cfg:
            if agent_cfg.get('default_agent') or agent_cfg.get('is_default'):
                orchestrator_cfg = agent_cfg
                continue
            agent_config = resolve_agent_config(agent_cfg, settings)
            chat_service = None
            service_id = f"aoai-chat-{agent_config['name'].replace(' ', '').lower()}"
            if AzureChatCompletion and agent_config["endpoint"] and agent_config["key"] and agent_config["deployment"]:
                try:
                    try:
                        chat_service = kernel.get_service(service_id=service_id)
                    except Exception:
                        log_event(
                            f"[SK Loader] Creating AzureChatCompletion service {service_id} for agent: {agent_config['name']}",
                            {
                                "aoai_endpoint": agent_config["endpoint"],
                                "aoai_key": f"{agent_config['key'][:3]}..." if agent_config["key"] else None,
                                "aoai_deployment": agent_config["deployment"],
                                "agent_name": agent_config["name"],
                                "actions_to_load": agent_config.get("actions_to_load", []),
                                "apim_enabled": settings.get("enable_gpt_apim", False)
                            },
                            level=logging.INFO
                        )
                        apim_enabled = settings.get("enable_gpt_apim", False)
                        if apim_enabled:
                            chat_service = AzureChatCompletion(
                                service_id=service_id,
                                deployment_name=agent_config["deployment"],
                                endpoint=agent_config["endpoint"],
                                api_key=agent_config["key"],
                                api_version=agent_config["api_version"],
                                # default_headers={"Ocp-Apim-Subscription-Key": agent_config["key"]}
                            )
                        else:
                            chat_service = AzureChatCompletion(
                                service_id=service_id,
                                deployment_name=agent_config["deployment"],
                                endpoint=agent_config["endpoint"],
                                api_key=agent_config["key"],
                                api_version=agent_config["api_version"]
                            )
                        kernel.add_service(chat_service)
                except Exception as e:
                    log_event(f"[SK Loader] Failed to create or get AzureChatCompletion for agent: {agent_config['name']}: {e}", {"error": str(e)}, level=logging.ERROR, exceptionTraceback=True)
            if LoggingChatCompletionAgent and chat_service:
                try:
                    kwargs = {
                        "name": agent_config["name"],
                        "instructions": agent_config["instructions"],
                        "kernel": kernel,
                        "service": chat_service,
                        "description": agent_config["description"] or agent_config["name"] or "This agent can be assigned to execute tasks and be part of a conversation as a generalist.",
                        "id": agent_config.get('id') or agent_config.get('name') or f"agent_1",
                        "display_name": agent_config.get('display_name') or agent_config.get('name') or "agent",
                        "default_agent": agent_config.get("default_agent", False),
                        "deployment_name": agent_config["deployment"],
                        "azure_endpoint": agent_config["endpoint"],
                        "api_version": agent_config["api_version"]
                    }
                    if agent_config.get("actions_to_load"):
                        kwargs["plugins"] = agent_config["actions_to_load"]
                    agent_obj = LoggingChatCompletionAgent(**kwargs)
                    
                    # PATCH: Badge global agents
                    if agent_cfg.get('is_global'):
                        agent_obj.is_global = True
                        log_event(f"[SK Loader] Agent '{agent_obj.name}' is marked as global.", level=logging.INFO)
                    agent_objs[agent_config["name"]] = agent_obj
                    specialist_agents.append(agent_obj)
                    log_event(
                        f"[SK Loader] ChatCompletionAgent initialized for agent: {agent_config['name']}",
                        {
                            "aoai_endpoint": agent_config["endpoint"],
                            "aoai_key": f"{agent_config['key'][:3]}..." if agent_config["key"] else None,
                            "aoai_deployment": agent_config["deployment"],
                            "agent_name": agent_config["name"],
                            "description": agent_obj.description,
                            "id": agent_obj.id
                        },
                        level=logging.INFO
                    )
                except Exception as e:
                    log_event(
                        f"[SK Loader] Failed to initialize ChatCompletionAgent for agent: {agent_config['name']}: {e}",
                        extra={"error": str(e), "agent_name": agent_config["name"]},
                        level=logging.ERROR,
                        exceptionTraceback=True
                    )
                    continue
            else:
                if chat_service is None:
                    log_event(
                        f"[SK Loader] No AzureChatCompletion service {service_id} available for agent: {agent_config['name']}",
                        extra={"agent_name": agent_config["name"]},
                        level=logging.ERROR
                    )
                log_event(
                    f"[SK Loader] ChatCompletionAgent or AzureChatCompletion not available for agent: {agent_config['name']}",
                    extra={"agent_name": agent_config["name"], },
                    level=logging.WARNING
                )
                continue
        # Now create the orchestrator agent from the default agent
        if orchestrator_cfg:
            try:
                orchestrator_config = resolve_agent_config(orchestrator_cfg, settings)
                service_id = f"aoai-chat-{orchestrator_config['name']}"
                chat_service = None
                if AzureChatCompletion and orchestrator_config["endpoint"] and orchestrator_config["key"] and orchestrator_config["deployment"]:
                    try:
                        chat_service = kernel.get_service(service_id=service_id)
                    except Exception:
                        log_event(
                            f"[SK Loader] Creating AzureChatCompletion service {service_id} for orchestrator agent: {orchestrator_config['name']}",
                            {
                                "aoai_endpoint": orchestrator_config["endpoint"],
                                "aoai_key": f"{orchestrator_config['key'][:3]}..." if orchestrator_config["key"] else None,
                                "aoai_deployment": orchestrator_config["deployment"],
                                "agent_name": orchestrator_config["name"],
                                "service_id": service_id or None,
                                "apim_enabled": settings.get("enable_gpt_apim", False)
                            },
                            level=logging.INFO
                        )
                        apim_enabled = settings.get("enable_gpt_apim", False)
                        if apim_enabled:
                            chat_service = AzureChatCompletion(
                                service_id=service_id,
                                deployment_name=orchestrator_config["deployment"],
                                endpoint=orchestrator_config["endpoint"],
                                api_key=orchestrator_config["key"],
                                api_version=orchestrator_config["api_version"],
                                # default_headers={"Ocp-Apim-Subscription-Key": orchestrator_config["key"]}
                            )
                        else:
                            chat_service = AzureChatCompletion(
                                service_id=service_id,
                                deployment_name=orchestrator_config["deployment"],
                                endpoint=orchestrator_config["endpoint"],
                                api_key=orchestrator_config["key"],
                                api_version=orchestrator_config["api_version"]
                            )
                        kernel.add_service(chat_service)
                if not chat_service:
                    raise RuntimeError(f"[SK Loader] No AzureChatCompletion service available for orchestrator agent '{orchestrator_config['name']}'")

                PromptExecutionSettingsClass = chat_service.get_prompt_execution_settings_class()
                prompt_settings = PromptExecutionSettingsClass()
                num_agents = len(specialist_agents)
                max_rounds = num_agents * (settings.get('max_rounds_per_agent', 1) or 1)
                if max_rounds % 2 == 0:
                    max_rounds += 1
                manager = SCGroupChatManager(
                    max_rounds=max_rounds,
                    prompt_execution_settings=prompt_settings)
                log_event(
                    f"[SK Loader] SCGroupChatManager created for orchestrator agent: {orchestrator_cfg.get('name')}",
                    {
                        "orchestrator_name": orchestrator_cfg.get('name'),
                        "num_specialist_agents": num_agents,
                        "max_rounds": max_rounds
                    },
                    level=logging.INFO
                )
                # Use Application Insights logger if available, else fallback to root logger
                try:
                    ai_logger = get_appinsights_logger()
                except Exception:
                    ai_logger = None
                fallback_logger = logging.getLogger()
                orchestrator_logger = ai_logger or fallback_logger
                orchestrator_desc = orchestrator_cfg.get("description") or orchestrator_cfg.get("name") or "No description provided"
                log_event(
                    f"[SK Loader] Creating OrchestratorAgent: {orchestrator_cfg.get('name')}",
                    {
                        "orchestrator_name": orchestrator_cfg.get('name'),
                        "description": orchestrator_desc,
                        "specialist_agents": [a.name for a in specialist_agents]
                    },
                    level=logging.INFO
                )
                orchestrator = OrchestratorAgent(
                    members=specialist_agents,
                    manager=manager,
                    name=orchestrator_cfg.get("name"),
                    description=orchestrator_desc,
                    input_transform=None,
                    output_transform=None,
                    agent_response_callback=None,
                    streaming_agent_response_callback=None,
                    agent_router=None,
                    scratchpad=None,
                    logger=orchestrator_logger,
                )
                # Ensure the orchestrator agent has an 'id' attribute for downstream use (fallback to name or generated value)
                orchestrator.id = orchestrator_config.get('id') or orchestrator_config.get('name') or "orchestrator"
                agent_objs[orchestrator_cfg.get("name")] = orchestrator
                log_event(
                    f"[SK Loader] OrchestratorAgent initialized: {orchestrator_cfg.get('name')}",
                    {
                        "orchestrator_id": orchestrator.id,
                        "orchestrator_name": orchestrator_cfg.get('name'),
                        "description": orchestrator_desc
                    },
                    level=logging.INFO
                )
            except Exception as e:
                log_event(f"[SK Loader] Failed to initialize OrchestratorAgent: {e}", {"error": str(e)}, level=logging.ERROR, exceptionTraceback=True)
# region Single-agent orchestration
    else:
        log_event(f"[SK Loader] Multi-agent orchestration check: enable_multi_agent_orchestration={enable_multi_agent_orchestration}, agents_cfg_count={len(agents_cfg)}", level=logging.INFO)
        
        if enable_multi_agent_orchestration:
            # Multi-agent orchestration is enabled but no agents defined
            log_event("[SK Loader] Multi-agent orchestration is enabled but no agents defined in settings.", level=logging.WARNING)
        else:
            log_event("[SK Loader] Multi-agent orchestration is disabled in settings.", level=logging.INFO)
        # PATCH: Use global_selected_agent for single-agent mode
        agents_cfg = get_global_agents()
        global_selected_agent_cfg = None
        global_selected_agent_info = settings.get('global_selected_agent')
        
        log_event(f"[SK Loader] Single-agent mode - agents_cfg count: {len(agents_cfg)}, global_selected_agent_info: {global_selected_agent_info}", level=logging.INFO)
        
        if global_selected_agent_info:
            global_selected_agent_cfg = next((a for a in agents_cfg if a.get('name') == global_selected_agent_info.get('name')), None)
            if not global_selected_agent_cfg:
                log_event(f"[SK Loader] global_selected_agent name '{global_selected_agent_info.get('name')}' not found in semantic_kernel_agents. Fallback to first agent.", level=logging.WARNING)
                if agents_cfg:
                    global_selected_agent_cfg = agents_cfg[0]
            else:
                log_event(f"[SK Loader] Found global_selected_agent config: {global_selected_agent_cfg.get('name')}", level=logging.INFO)
        else:
            if agents_cfg:
                global_selected_agent_cfg = agents_cfg[0]
                log_event(f"[SK Loader] No global_selected_agent_info, using first agent: {global_selected_agent_cfg.get('name')}", level=logging.INFO)
                
        if global_selected_agent_cfg:
            log_event(f"[SK Loader] Using global_selected_agent: {global_selected_agent_cfg.get('name')}", level=logging.INFO)
            kernel, agent_objs = load_single_agent_for_kernel(kernel, global_selected_agent_cfg, settings, builtins, redis_client=None, mode_label="global")
            log_event(f"[SK Loader] load_single_agent_for_kernel returned agent_objs: {type(agent_objs)} with {len(agent_objs) if agent_objs else 0} agents", level=logging.INFO)
        else:
            log_event("[SK Loader] No global_selected_agent found. Proceeding in kernel-only mode.", level=logging.WARNING)
            agent_objs = None
            # Optionally, register a global AzureChatCompletion service if config is present in settings
            gpt_model_obj = settings.get('gpt_model', {})
            selected_model = gpt_model_obj.get('selected', [{}])[0] if gpt_model_obj.get('selected') else {}
            endpoint = settings.get("azure_openai_gpt_endpoint") or selected_model.get("endpoint")
            key = settings.get("azure_openai_gpt_key") or selected_model.get("key")
            deployment = settings.get("azure_openai_gpt_deployment") or selected_model.get("deploymentName")
            api_version = settings.get("azure_openai_gpt_api_version") or selected_model.get("api_version")
            if AzureChatCompletion and endpoint and key and deployment:
                apim_enabled = settings.get("enable_gpt_apim", False)
                if apim_enabled:
                    kernel.add_service(
                        AzureChatCompletion(
                            service_id=f"aoai-chat-global",
                            deployment_name=deployment,
                            endpoint=endpoint,
                            api_key=key,
                            api_version=api_version,
                            # default_headers={"Ocp-Apim-Subscription-Key": key}
                        )
                    )
                else:
                    kernel.add_service(
                        AzureChatCompletion(
                            service_id=f"aoai-chat-global",
                            deployment_name=deployment,
                            endpoint=endpoint,
                            api_key=key,
                            api_version=api_version
                        )
                    )
                log_event(
                    f"[SK Loader] Azure OpenAI chat completion service registered (kernel-only mode)",
                    {
                        "aoai_endpoint": endpoint,
                        "aoai_key": f"{key[:3]}..." if key else None,
                        "aoai_deployment": deployment,
                        "agent_name": None,
                        "apim_enabled": apim_enabled
                    },
                    level=logging.INFO
                )

    # Return both kernel and all agents (including orchestrator) for use in the app
    log_event(f"[SK Loader] load_semantic_kernel final return - agent_objs: {type(agent_objs)} with {len(agent_objs) if agent_objs else 0} agents", level=logging.INFO)
    if agent_objs:
        agent_names = list(agent_objs.keys()) if isinstance(agent_objs, dict) else [getattr(agent, 'name', 'unnamed') for agent in agent_objs]
        log_event(f"[SK Loader] Returning agent names: {agent_names}", level=logging.INFO)
    else:
        log_event("[SK Loader] Returning None for agent_objs", level=logging.WARNING)
    return kernel, agent_objs


def load_multi_agent_for_kernel(kernel: Kernel, settings):
    return None, None