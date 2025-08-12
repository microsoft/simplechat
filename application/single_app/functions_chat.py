import json
import logging
import types
from semantic_kernel import Kernel
from functions_appinsights import log_event

def load_user_kernel(user_id, redis_client):
    """
    Loads the per-user kernel and agent state from Redis, reconstructs as much as possible.
    Returns (kernel, kernel_agents)
    """
    kernel = None
    kernel_agents = None
    if not user_id or not redis_client:
        # Redis is optional; if not present, just return empty state
        return None, None
    kernel_state_json = redis_client.get(f"sk:state:{user_id}") if redis_client else None
    if not kernel_state_json:
        return None, None
    log_event(f"[SK Loader] Loaded kernel state from Redis for user {user_id}.",
        extra={
            "user_id": user_id,
            "kernel_state": kernel_state_json
        },
        level=logging.INFO
    )
    try:
        kernel_state = json.loads(kernel_state_json)
        log_event(f"[SK Loader][DEBUG] Loaded kernel state from Redis for user {user_id}.")
        kernel = Kernel()
        # Restore kernel config if possible
        kernel_config = kernel_state.get('kernel_config')
        if kernel_config:
            try:
                if hasattr(kernel, 'config'):
                    config = getattr(kernel, 'config')
                    if hasattr(config, 'update') and isinstance(kernel_config, dict):
                        config.update(kernel_config)
                    elif hasattr(config, '__dict__') and isinstance(kernel_config, dict):
                        config.__dict__.update(kernel_config)
            except Exception as conf_ex:
                log_event(
                    f"[SK Loader] Error restoring kernel config: {conf_ex}",
                    level=logging.WARNING
                )
        # Restore memory/chat history if possible
        memory_state = kernel_state.get('memory')
        if memory_state and hasattr(kernel, 'memory'):
            mem = getattr(kernel, 'memory')
            try:
                if hasattr(mem, 'load_history') and callable(getattr(mem, 'load_history')):
                    mem.load_history(memory_state)
                elif hasattr(mem, 'from_dict') and callable(getattr(mem, 'from_dict')) and isinstance(memory_state, dict):
                    mem.from_dict(memory_state)
                elif hasattr(mem, '__dict__') and isinstance(memory_state, dict):
                    mem.__dict__.update(memory_state)
            except Exception as mem_ex:
                log_event(
                    f"[SK Loader] Error restoring memory: {mem_ex}",
                    level=logging.WARNING
                )
        # Restore agents/plugins state if possible
        kernel_agents = {}
        agents_state = kernel_state.get('agents_state', {})
        for agent_name, agent_class in kernel_state.get('agents', {}).items():
            try:
                agent_obj = type(agent_class, (), {})()  # Dummy instance with class name
                agent_state = agents_state.get(agent_name)
                if agent_state and hasattr(agent_obj, 'set_state') and callable(getattr(agent_obj, 'set_state')):
                    agent_obj.set_state(agent_state)
                elif hasattr(agent_obj, '__dict__') and isinstance(agent_state, dict):
                    agent_obj.__dict__.update(agent_state)
                kernel_agents[agent_name] = agent_obj
            except Exception as agent_ex:
                log_event(
                    f"[SK Loader] Error restoring agent '{agent_name}': {agent_ex}",
                    level=logging.WARNING
                )
        return kernel, kernel_agents
    except Exception as e:
        log_event(
            f"[SK Loader] Error loading kernel state from Redis: {e}",
            level=logging.ERROR
        )
        return None, None

def save_user_kernel(user_id, kernel, kernel_agents, redis_client):
    """
    Extracts and saves as much user-affecting kernel state as possible to Redis.
    """
    if not redis_client:
        # Redis is optional; skip saving if not present
        return
    try:
        kernel_services = {}
        for sid, service in getattr(kernel, 'services', {}).items():
            kernel_services[sid] = {
                'class': service.__class__.__name__,
                'prompt_tokens': getattr(service, 'prompt_tokens', None),
                'completion_tokens': getattr(service, 'completion_tokens', None),
                'total_tokens': getattr(service, 'total_tokens', None),
            }
        kernel_plugins = list(getattr(kernel, 'plugins', {}).keys())
        kernel_agents_dict = {}
        kernel_agents_state = {}
        if kernel_agents:
            for k, v in kernel_agents.items():
                kernel_agents_dict[k] = v.__class__.__name__ if hasattr(v, '__class__') else str(type(v))
                if hasattr(v, 'get_state') and callable(getattr(v, 'get_state')):
                    try:
                        agent_state = v.get_state()
                        kernel_agents_state[k] = agent_state
                    except Exception as agent_ex:
                        kernel_agents_state[k] = f"[SK Loader] Error extracting agent state: {agent_ex}"
        # Extract memory/chat history if present
        memory_state = None
        if hasattr(kernel, 'memory'):
            mem = getattr(kernel, 'memory')
            if hasattr(mem, 'get_history') and callable(getattr(mem, 'get_history')):
                try:
                    memory_state = mem.get_history()
                except Exception as mem_ex:
                    memory_state = f"[SK Loader] Error extracting memory history: {mem_ex}"
            elif hasattr(mem, 'to_dict') and callable(getattr(mem, 'to_dict')):
                try:
                    memory_state = mem.to_dict()
                except Exception as mem_ex:
                    memory_state = f"[Error extracting memory to_dict: {mem_ex}]"
            elif hasattr(mem, '__dict__'):
                try:
                    memory_state = mem.__dict__
                except Exception as mem_ex:
                    memory_state = f"[Error extracting memory __dict__: {mem_ex}]"
        # Extract kernel config if present
        kernel_config = None
        if hasattr(kernel, 'config'):
            try:
                config = getattr(kernel, 'config')
                if hasattr(config, 'to_dict') and callable(getattr(config, 'to_dict')):
                    kernel_config = config.to_dict()
                elif hasattr(config, '__dict__'):
                    kernel_config = config.__dict__
                else:
                    kernel_config = str(config)
            except Exception as conf_ex:
                kernel_config = f"[Error extracting kernel config: {conf_ex}]"
        state = {
            'services': kernel_services,
            'plugins': kernel_plugins,
            'agents': kernel_agents_dict,
            'agents_state': kernel_agents_state,
            'memory': memory_state,
            'kernel_config': kernel_config,
        }
        redis_client.set(f"sk:state:{user_id}", json.dumps(state, default=str))
        log_event(
            f"[SK Loader][DEBUG] Saved kernel state snapshot to Redis for user {user_id}.",
            extra={
                "user_id": user_id,
                'services': kernel_services,
                'plugins': kernel_plugins,
                'agents': kernel_agents_dict,
                'agents_state': kernel_agents_state,
                'memory': memory_state,
                'kernel_config': kernel_config,
            },
            level=logging.INFO
        )
    except Exception as e:
        log_event(
            f"[SK Loader] Error saving kernel state to Redis: {e}",
            level=logging.ERROR
        )
