# Azure AI Foundry Agent Support

## Overview

SimpleChat now supports Azure AI Foundry agents as a first-class agent type. This integration allows users to leverage pre-built agents from Azure AI Foundry (formerly Azure AI Agent Service) directly within SimpleChat, combining the power of cloud-hosted AI agents with SimpleChat's conversation management and workspace features.

**Version Implemented:** 0.236.011

## Key Features

- **Native Agent Type**: `aifoundry` agent type in agent configuration
- **Semantic Kernel Integration**: Uses Semantic Kernel's `AzureAIAgent` for execution
- **Credential Management**: Supports Azure Default Credential and Client Secret authentication
- **Citation Support**: Captures and displays citations from Foundry agent responses
- **Model Tracking**: Tracks which model was used for each response

## Configuration

### Agent Configuration Structure

Azure AI Foundry agents are configured with the `agent_type: "aifoundry"` setting:

```json
{
    "name": "my-foundry-agent",
    "display_name": "My Foundry Agent",
    "description": "An agent powered by Azure AI Foundry",
    "agent_type": "aifoundry",
    "other_settings": {
        "azure_ai_foundry": {
            "agent_id": "asst_xxxxxxxxxxxxxx",
            "api_version": "2024-12-01-preview"
        }
    }
}
```

### Required Settings

| Setting | Location | Description |
|---------|----------|-------------|
| `agent_id` | `other_settings.azure_ai_foundry.agent_id` | The Azure AI Foundry agent ID |
| Endpoint | Global settings or Foundry settings | Azure AI Foundry endpoint URL |

### Optional Settings

| Setting | Description |
|---------|-------------|
| `api_version` | API version to use (default from global settings) |
| Credential settings | For client secret authentication |

## Technical Architecture

### Core Components

| File | Purpose |
|------|---------|
| [foundry_agent_runtime.py](../../../../application/single_app/foundry_agent_runtime.py) | Agent execution and Semantic Kernel integration |

### Key Classes

#### `AzureAIFoundryChatCompletionAgent`

Lightweight wrapper that makes Foundry agents behave like Semantic Kernel chat agents:

```python
class AzureAIFoundryChatCompletionAgent:
    """Lightweight wrapper so Foundry agents behave like SK chat agents."""

    agent_type = "aifoundry"

    def __init__(self, agent_config: Dict[str, Any], settings: Dict[str, Any]):
        self.name = agent_config.get("name")
        self.display_name = agent_config.get("display_name") or self.name
        self.description = agent_config.get("description", "")
        # ... additional properties

    def invoke(self, agent_message_history, metadata=None) -> str:
        """Synchronously invoke the Foundry agent."""
        # Executes async Foundry call and returns response text
```

#### `FoundryAgentInvocationResult`

Data class representing the outcome from a Foundry agent run:

```python
@dataclass
class FoundryAgentInvocationResult:
    message: str           # The response text
    model: Optional[str]   # Model used for response
    citations: List[Dict]  # Any citations from the response
    metadata: Dict         # Additional metadata
```

### Execution Flow

1. **Agent Invocation**: `invoke()` method is called with message history
2. **Async Execution**: `execute_foundry_agent()` handles the actual API call
3. **Client Creation**: `AzureAIAgent.create_client()` sets up authenticated client
4. **Agent Retrieval**: Fetches agent definition from Foundry
5. **Message Processing**: Sends messages and collects responses
6. **Result Extraction**: Captures message, model, and citations

### Authentication

The runtime supports multiple authentication methods:

1. **Default Azure Credential**: Uses `DefaultAzureCredential` for managed identity
2. **Client Secret**: Uses `ClientSecretCredential` for service principal auth
3. **Key Vault Integration**: Secrets can be retrieved from Azure Key Vault

```python
credential = _build_async_credential(foundry_settings, global_settings)
client = AzureAIAgent.create_client(
    credential=credential,
    endpoint=endpoint,
    api_version=api_version,
)
```

## Admin Configuration

### Creating a Foundry Agent

1. Navigate to **Agent Builder** or **Admin Settings → Agents**
2. Select **Create New Agent**
3. Choose **Azure AI Foundry** as the agent type
4. Enter the **Agent ID** from Azure AI Foundry
5. Configure any additional settings
6. Save the agent

### Global Settings

Azure AI Foundry settings can be configured at the global level:

| Setting | Description |
|---------|-------------|
| `azure_ai_foundry_endpoint` | Default Foundry endpoint |
| `azure_ai_foundry_api_version` | Default API version |

## User Experience

### For End Users

- Foundry agents appear alongside other agents in the agent selector
- Chat interactions work identically to other agent types
- Responses may include citations from Foundry agent capabilities

### For Administrators

- Full control over which Foundry agents are available
- Can configure as global, group, or personal agents
- Monitor usage through activity logging

## Error Handling

### `FoundryAgentInvocationError`

Raised when the Foundry agent invocation cannot be completed:

```python
class FoundryAgentInvocationError(RuntimeError):
    """Raised when the Foundry agent invocation cannot be completed."""
```

Common causes:
- Missing agent_id configuration
- Invalid credentials
- Network connectivity issues
- Foundry service unavailable

### Validation

The runtime validates required configuration:

```python
agent_id = (foundry_settings.get("agent_id") or "").strip()
if not agent_id:
    raise FoundryAgentInvocationError(
        "Azure AI Foundry agents require an agent_id in other_settings.azure_ai_foundry."
    )
```

## Logging and Monitoring

### Event Logging

Agent invocations are logged to Application Insights:

```python
log_event(
    "[FoundryAgent] Invocation runtime error",
    extra={
        "agent_id": self.id,
        "agent_name": self.name,
    },
    level=logging.ERROR,
)
```

### Debug Output

Debug information is available during development:

```python
debug_print(
    f"[FoundryAgent] Invoking agent '{self.name}' with {len(history)} messages"
)
```

## Security Considerations

1. **Credential Security**: Use managed identity when possible
2. **Key Vault**: Store secrets in Azure Key Vault
3. **Access Control**: Control which users can access Foundry agents
4. **Data Boundaries**: Be aware of data processing in Azure AI Foundry

## Dependencies

- `semantic-kernel`: For `AzureAIAgent` abstraction
- `azure-identity`: For Azure authentication
- Azure AI Foundry account with configured agents

## Known Limitations

- Plugins attached to SimpleChat agents are not passed to Foundry agents
- APIM metadata is stripped for Foundry agent calls
- Streaming responses are collected before returning

## Related Features

- [Web Search via Azure AI Foundry](WEB_SEARCH_AZURE_AI_FOUNDRY.md)
- Agent Builder
- Plugin Management
