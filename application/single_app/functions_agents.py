# function_agents.py

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functions_settings import get_settings
from semantic_kernel.agents.runtime.in_process.in_process_runtime import InProcessRuntime

# Global executor for background orchestration
executor = ThreadPoolExecutor(max_workers=4)  # Tune as needed

def run_orchestration_in_thread(orchestrator, agent_message_history, run_sk_call):
    def _runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        runtime = None
        try:
            runtime = InProcessRuntime()
            result = loop.run_until_complete(
                run_sk_call(
                    orchestrator.invoke,
                    agent_message_history,
                    runtime=runtime,
                )
            )
            return result
        except Exception as e:
            print(f"Orchestration error: {e}")
            return None
        finally:
            loop.close()
    return executor.submit(_runner)

def get_agent_id_by_name(agent_name):
    """
    Returns the agent's GUID (id) given its name. Returns None if not found.
    """
    settings = get_settings()
    agents = settings.get('semantic_kernel_agents', [])
    for agent in agents:
        if agent.get('name') == agent_name:
            return agent.get('id')
    return None
