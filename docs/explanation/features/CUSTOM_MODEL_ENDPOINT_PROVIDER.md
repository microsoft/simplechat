# Custom Model Endpoint Provider

## Overview and Purpose

The Custom provider lets administrators and authorized workspace owners configure chat models through a supported API contract without changing the provider label shown throughout SimpleChat. Custom endpoints are available in global, personal, and group model endpoint scopes and use manual model entry.

**Implemented in version: 0.250.172**

**Issue:** [#1222](https://github.com/microsoft/simplechat/issues/1222)

## Dependencies

- Multi-model endpoint management
- Existing global, personal, and group endpoint governance
- Existing Key Vault model-endpoint secret storage
- OpenAI Python client and the existing Anthropic Messages adapter

## Technical Specifications

### Architecture

Custom endpoints persist `provider: "custom"` and one explicit `api_type`. The API type is authoritative at runtime; endpoint paths and model names do not change the selected protocol.

| API Type | Model Identifier | Version Field | Request Contract |
|---|---|---|---|
| OpenAI API (`openai`) | `modelName` | None | OpenAI-compatible Chat Completions under `/v1/` |
| Azure OpenAI API (`azure_openai`) | `deploymentName` | `connection.api_version` | Azure OpenAI Chat Completions |
| Anthropic (`anthropic`) | `modelName` | `connection.anthropic_version` | Anthropic Messages under `/v1/messages` |

Every model keeps a stable SimpleChat `id` for selection and authorization. The stable ID is never sent as the provider model identifier.

### Authentication and Secret Storage

- API key is the only supported Custom authentication type.
- API keys use the existing model-endpoint Key Vault flow when Key Vault secret storage is enabled.
- Frontend endpoint payloads contain only `has_api_key`; they never contain a stored key.
- Existing blank-on-edit behavior preserves a stored API key.

### Endpoint Safety

- Custom endpoint URLs must use HTTPS and a fully qualified DNS hostname.
- Embedded credentials, query strings, fragments, direct IP literals, and single-label hosts are rejected.
- Loopback, link-local, metadata/platform, multicast, reserved, and unspecified addresses are always rejected.
- Private addresses are rejected unless an administrator enables **Allow private Custom endpoint hosts**.
- DNS and URL policy are checked when configuration is saved and again before runtime client construction.
- Each direct Custom connection is pinned to the addresses from its validated DNS lookup, preventing a second DNS resolution from redirecting the request to a blocked address.
- Direct Custom requests do not follow redirects.
- Provider response bodies and raw provider exceptions are not returned for direct Custom Anthropic failures.

### API Endpoints

- `POST /api/models/test-model`
- `POST /api/user/models/test-model`
- `POST /api/group/models/test-model`
- `GET|POST /api/user/model-endpoints`
- `GET|POST /api/group/model-endpoints`

Model discovery endpoints deliberately reject Custom providers before network dispatch. Models must be entered with **Add Model**.

### Configuration

- `enable_multi_model_endpoints`: enables endpoint-backed model selection.
- `allow_user_custom_endpoints`: allows authorized personal endpoint management.
- `allow_group_custom_endpoints`: allows authorized group endpoint management.
- `allow_private_custom_model_endpoints`: permits private DNS results for Custom endpoints while retaining the always-blocked address classes.

### File Structure

- Canonical types: `application/single_app/functions_model_endpoint_types.py`
- Validation and URL policy: `application/single_app/functions_model_endpoint_validation.py`
- Runtime construction: `application/single_app/functions_model_endpoint_runtime.py`
- Protocol adapters: `application/single_app/model_endpoint_clients.py`
- Save and test routes: `application/single_app/route_backend_models.py`
- Shared modal: `application/single_app/templates/_multiendpoint_modal.html`
- Admin editor: `application/single_app/static/js/admin/admin_model_endpoints.js`
- Workspace editor: `application/single_app/static/js/workspace/workspace_model_endpoints.js`

## Usage Instructions

### Configure an Endpoint

1. Open Model Endpoints in Admin Settings, Personal Workspace, or Group Workspace.
2. Add an endpoint and choose **Custom**.
3. Select **OpenAI API**, **Azure OpenAI API**, or **Anthropic**.
4. Enter the HTTPS endpoint and API key.
5. For Azure OpenAI API, enter the API version. For Anthropic, confirm or change the Anthropic Version.
6. Select **Add Model** and enter a Model Name or Deployment Name as indicated.
7. Optionally set Display Name, Response Length, Description, Icon, and Enabled state.
8. Test the model connection, then save the endpoint.

### Scope and Governance

Global endpoints remain controlled by administrators. Personal and group endpoints continue to use their existing feature flags, role checks, governance decisions, active-group checks, endpoint/model IDs, and Key Vault scope. Runtime requests resolve the saved endpoint and model instead of trusting client-supplied connection details.

## Testing and Validation

- `functional_tests/test_custom_model_endpoint_provider.py`
- Existing model endpoint normalization, protocol, Key Vault, workspace, streaming, summary, metadata, multimodal, and route-policy regressions
- JavaScript syntax checks for both endpoint editors and the chat model selector
- Python compilation checks for all modified runtime and route modules

## Performance Considerations

Custom model discovery is disabled, so configuration does not perform model-list requests. URL validation performs DNS resolution during save and runtime construction, and the protected transport resolves again when opening a connection so it can pin the validated addresses. Runtime latency and model capability depend on the configured API.

## Known Limitations

- API key is the only Custom authentication type.
- Models are entered manually; model discovery is unavailable.
- Supported inference contracts are OpenAI-compatible Chat Completions, Azure OpenAI Chat Completions, and Anthropic Messages.
- Custom endpoints do not add embeddings, image generation, OpenAI Responses, arbitrary headers, or non-HTTPS transport.
- A configured model can only use features supported by its selected API contract.

## Version Reference

The application version was updated in `application/single_app/config.py` to **0.250.172**.
