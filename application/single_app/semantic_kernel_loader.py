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
from semantic_kernel.functions.kernel_plugin import KernelPlugin
from semantic_kernel_plugins.embedding_model_plugin import EmbeddingModelPlugin
from semantic_kernel_plugins.fact_memory_plugin import FactMemoryPlugin
from functions_settings import get_settings, get_user_settings
from functions_appinsights import log_event, get_appinsights_logger
from flask import g
import logging
import importlib
import os
import importlib.util
import inspect
import builtins

# Agent and Azure OpenAI chat service imports
if 'logger' in globals() and logger is not None:
    log_event("[SK Loader] Starting loader")
try:
    from semantic_kernel.agents import ChatCompletionAgent
    from agent_logging_chat_completion import LoggingChatCompletionAgent
    from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
except ImportError:
    ChatCompletionAgent = None
    AzureChatCompletion = None
    if 'logger' in globals() and logger is not None:
        log_event(
            "[SK Loader] ChatCompletionAgent or AzureChatCompletion not available. Ensure you have the correct Semantic Kernel version.",
            level=logging.ERROR,
            exceptionTraceback=True
        )
if 'logger' in globals() and logger is not None:    
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
    gpt_model_obj = settings.get('gpt_model', {})
    selected_model = gpt_model_obj.get('selected', [{}])[0] if gpt_model_obj.get('selected') else {}
    # User APIM enabled if agent has azure_apim_gpt_enabled True (or 1, or 'true')
    user_apim_enabled = agent.get("azure_apim_gpt_enabled") in [True, 1, "true", "True"]
    global_apim_enabled = settings.get("enable_gpt_apim", False)
    per_user_enabled = settings.get('per_user_semantic_kernel', False)

    def any_filled(*fields):
        return any(bool(f) for f in fields)

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
                endpoint, key, deployment, api_version = get_global_apim()
            else:
                endpoint, key, deployment, api_version = get_global_gpt()
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
                "default_agent": agent.get("default_agent", False)
            }
        except Exception as e:
            log_event(f"[SK Loader] Error resolving agent config: {e}", level=logging.ERROR, exceptionTraceback=True)

    # Decision tree for config resolution:
    # 1. If user APIM is enabled and any user APIM values are set, use user APIM (with fallback to global APIM if enabled and any values)
    # 2. If user APIM is enabled but no user APIM values are set, and global APIM is enabled and any values, use global APIM
    # 3. If agent/user GPT config is set, use that
    # 4. If global APIM is enabled and any values, use global APIM
    # 5. Otherwise, use global GPT config

    u_apim = get_user_apim()
    g_apim = get_global_apim()
    u_gpt = get_user_gpt()
    g_gpt = get_global_gpt()

    if user_apim_enabled and any_filled(*u_apim):
        # User APIM is enabled and has values
        merged = merge_fields(u_apim, g_apim if global_apim_enabled and any_filled(*g_apim) else (None, None, None, None))
        endpoint, key, deployment, api_version = merged
    elif user_apim_enabled and global_apim_enabled and any_filled(*g_apim):
        # User APIM enabled but no user APIM values, use global APIM if enabled and has values
        endpoint, key, deployment, api_version = g_apim
    elif any_filled(*u_gpt):
        # Use agent/user GPT config
        endpoint, key, deployment, api_version = u_gpt
    elif global_apim_enabled and any_filled(*g_apim):
        # Use global APIM if enabled and has values
        endpoint, key, deployment, api_version = g_apim
    else:
        # Fallback to global GPT config
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
        "default_agent": agent.get("default_agent", False)
    }

def load_time_plugin(kernel: Kernel):
    kernel.add_plugin(
        TimePlugin(),
        plugin_name="time",
        description="Provides time-related functions."
    )

def load_http_plugin(kernel: Kernel):
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

# =================== Semantic Kernel Initialization ===================
def initialize_semantic_kernel(user_id: str=None, redis_client=None):
    print("[SK Loader] Initializing Semantic Kernel and plugins...")
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
    if settings.get('per_user_semantic_kernel', False) and user_id is not None:
        kernel, kernel_agents = load_user_semantic_kernel(kernel, settings, user_id=user_id, redis_client=redis_client)
        g.kernel = kernel
        g.kernel_agents = kernel_agents
    else:
        kernel, kernel_agents = load_semantic_kernel(kernel, settings)
        builtins.kernel = kernel
        builtins.kernel_agents = kernel_agents
    if kernel and not kernel_agents:
        log_event(
            "[SK Loader] Failed to load Agents.",
            level=logging.ERROR
        )
    log_event(
        "[SK Loader] Semantic Kernel Agent and Plugins loading completed.",
        extra={
            "kernel": str(kernel),
            "agents": [agent.name for agent in kernel_agents.values()] if kernel_agents else []
        },
        level=logging.INFO
    )
    print("[SK Loader] Semantic Kernel Agent and Plugins loading completed.")

def load_single_agent_for_kernel(kernel, agent_cfg, settings, context_obj, redis_client=None, mode_label="global"):
    """
    DRY helper to load a single agent (default agent) for the kernel.
    - context_obj: g (per-user) or builtins (global)
    - redis_client: required for per-user mode
    - mode_label: 'per-user' or 'global' (for logging)
    Returns: kernel, agent_objs // dict (name->agent) or None
    """
    # Redis is now optional for per-user mode
    if mode_label == "per-user":
        context_obj.redis_client = redis_client
    agent_objs = {}
    agent_config = resolve_agent_config(agent_cfg, settings)
    service_id = f"aoai-chat-{agent_config['name']}"
    chat_service = None
    apim_enabled = settings.get("enable_gpt_apim", False)
    if AzureChatCompletion and agent_config["endpoint"] and agent_config["key"] and agent_config["deployment"]:
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
        log_event(
            f"[SK Loader] Azure OpenAI chat completion service registered for agent: {agent_config['name']} ({mode_label})",
            {
                "aoai_endpoint": agent_config["endpoint"],
                "aoai_key": f"{agent_config['key'][:3]}..." if agent_config["key"] else None,
                "aoai_deployment": agent_config["deployment"],
                "agent_name": agent_config["name"],
                "apim_enabled": apim_enabled
            },
            level=logging.INFO
        )
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
                "default_agent": agent_config.get("default_agent", False)
            }
            if agent_config.get("actions_to_load"):
                kwargs["plugins"] = agent_config["actions_to_load"]
            agent_obj = LoggingChatCompletionAgent(**kwargs)
            agent_objs[agent_config["name"]] = agent_obj
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
            log_event(
                f"[SK Loader] Failed to initialize ChatCompletionAgent for agent: {agent_config['name']} ({mode_label}): {e}",
                {"error": str(e), "agent_name": agent_config["name"]},
                level=logging.ERROR,
                exceptionTraceback=True
            )
            return None
    else:
        log_event(
            f"[SK Loader] ChatCompletionAgent or AzureChatCompletion not available for agent: {agent_config['name']} ({mode_label})",
            {"agent_name": agent_config["name"]},
            level=logging.ERROR,
            exceptionTraceback=True
        )
        return None
    return kernel, agent_objs

def load_plugins_for_kernel(kernel, plugin_manifests, settings, mode_label="global"):
    """
    DRY helper to load plugins from a manifest list (user or global).
    """
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
                    plugin = matched_class(manifest) if 'manifest' in matched_class.__init__.__code__.co_varnames else matched_class()
                    kernel.add_plugin(KernelPlugin.from_object(name, plugin, description=description))
                    log_event(f"[SK Loader] Loaded plugin: {name} (type: {plugin_type}) [{mode_label}]", {"plugin_name": name, "plugin_type": plugin_type}, level=logging.INFO)
                except Exception as e:
                    log_event(f"[SK Loader] Failed to instantiate plugin: {name}: {e}", {"plugin_name": name, "plugin_type": plugin_type, "error": str(e)}, level=logging.ERROR, exceptionTraceback=True)
            else:
                log_event(f"[SK Loader] Unknown plugin type: {plugin_type} for plugin '{name}' [{mode_label}]", {"plugin_name": name, "plugin_type": plugin_type}, level=logging.WARNING)
    except Exception as e:
        log_event(f"[SK Loader] Error discovering plugin types for {mode_label} mode: {e}", {"error": str(e)}, level=logging.ERROR, exceptionTraceback=True)

def load_user_semantic_kernel(kernel: Kernel, settings, user_id: str, redis_client):
    log_event("[SK Loader] Per-user Semantic Kernel mode enabled. Loading user-specific plugins and agents.", 
        level=logging.INFO
    )
    # Redis is now optional for per-user mode. If not present, state will not persist.
    user_settings = get_user_settings(user_id).get('settings', {})
    agents_cfg = user_settings.get('agents', [])
    # Always mark user agents as is_global: False
    for agent in agents_cfg:
        agent['is_global'] = False

    # PATCH: Merge global agents if enabled
    merge_global = settings.get('merge_global_semantic_kernel_with_workspace', False)
    if merge_global:
        global_agents = settings.get('semantic_kernel_agents', [])
        # Mark global agents
        for agent in global_agents:
            agent['is_global'] = True
        # User agents take precedence
        all_agents = {a['name']: a for a in global_agents}
        all_agents.update({a['name']: a for a in agents_cfg})
        agents_cfg = list(all_agents.values())
        log_event(f"[SK Loader] Merged global agents into per-user agents: {[a.get('name') for a in agents_cfg]}", level=logging.INFO)

    log_event(f"[SK Loader] Found {len(agents_cfg)} agents in user settings for user '{user_id}'.",
        extra={
            "user_id": user_id,
            "agents_count": len(agents_cfg),
            "agents": agents_cfg,
            "user_settings": user_settings
        },
        level=logging.INFO)
    plugin_manifests = user_settings.get('plugins', [])
    # PATCH: Merge global plugins if enabled
    if merge_global:
        global_plugins = settings.get('semantic_kernel_plugins', [])
        # User plugins take precedence
        all_plugins = {p.get('name'): p for p in plugin_manifests}
        all_plugins.update({p.get('name'): p for p in global_plugins})
        plugin_manifests = list(all_plugins.values())
        log_event(f"[SK Loader] Merged global plugins into per-user plugins: {[p.get('name') for p in plugin_manifests]}", level=logging.INFO)
    # Load user+global plugins from merged list
    load_plugins_for_kernel(kernel, plugin_manifests, settings, mode_label="per-user")
    # Only single-agent supported in per-user mode
    default_agents = [a for a in agents_cfg if a.get('default_agent')]
    if not default_agents:
        log_event("[SK Loader] No default agent defined in user settings. Proceeding in kernel-only mode (per-user).", level=logging.INFO)
        return kernel, None
    if len(default_agents) > 1:
        log_event(f"[SK Loader] No more than one agent can be marked as default in user settings. Found: {len(default_agents)}", level=logging.ERROR, exceptionTraceback=True)
        raise Exception("No more than one agent can be marked as default in user settings.")
    kernel, agent_objs = load_single_agent_for_kernel(kernel, default_agents[0], settings, g, redis_client=redis_client, mode_label="per-user")
    return kernel, agent_objs

def load_semantic_kernel(kernel: Kernel, settings):
    log_event("[SK Loader] Loading Semantic Kernel plugins...")
    log_event("[SK Loader] Global Semantic Kernel mode enabled. Loading global plugins and agents.", level=logging.INFO)
    # Conditionally load core plugins based on settings
    plugin_manifests = settings.get('semantic_kernel_plugins', [])
    # --- Dynamic Plugin Type Loading (semantic_kernel_plugins) ---
    load_plugins_for_kernel(kernel, plugin_manifests, settings, mode_label="global")

# --- Agent and Service Loading ---
# region Multi-agent Orchestration
    agents_cfg = settings.get('semantic_kernel_agents', [])
    enable_multi_agent_orchestration = settings.get('enable_multi_agent_orchestration', False)
    merge_global = settings.get('merge_global_semantic_kernel_with_workspace', False)
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
    if enable_multi_agent_orchestration and len(agents_cfg) > 0:
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
                        "default_agent": agent_config.get("default_agent", False)
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
        if enable_multi_agent_orchestration:
            # Multi-agent orchestration is enabled but no agents defined
            log_event("[SK Loader] Multi-agent orchestration is enabled but no agents defined in settings.", level=logging.WARNING)
        else:
            log_event("[SK Loader] Multi-agent orchestration is disabled in settings.", level=logging.INFO)
        # PATCH: Use global_selected_agent for single-agent mode
        agents_cfg = settings.get('semantic_kernel_agents', [])
        global_selected_agent_cfg = None
        global_selected_agent_info = settings.get('global_selected_agent')
        if global_selected_agent_info:
            global_selected_agent_cfg = next((a for a in agents_cfg if a.get('name') == global_selected_agent_info.get('name')), None)
            if not global_selected_agent_cfg:
                log_event(f"[SK Loader] global_selected_agent name '{global_selected_agent_info.get('name')}' not found in semantic_kernel_agents. Fallback to first agent.", level=logging.WARNING)
                if agents_cfg:
                    global_selected_agent_cfg = agents_cfg[0]
        else:
            if agents_cfg:
                global_selected_agent_cfg = agents_cfg[0]
        if global_selected_agent_cfg:
            log_event(f"[SK Loader] Using global_selected_agent: {global_selected_agent_cfg.get('name')}", level=logging.INFO)
            kernel, agent_objs = load_single_agent_for_kernel(kernel, global_selected_agent_cfg, settings, builtins, redis_client=None, mode_label="global")
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
    return kernel, agent_objs
