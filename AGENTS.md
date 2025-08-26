# Agents and Plugins in Simplechat

Welcome to Simplechat! This guide explains how agents and plugins work, how to configure them, and best practices for deploying and extending your Simplechat environment.

---

## What's New (July 2025)

- **Global vs. Workspace Agents/Plugins**: Admins can now manage global agents and plugins that are protected from editing/deletion by users. Users manage their own workspace agents/plugins.
- **Schema-Driven Validation**: All agent and plugin configuration is validated against backend schemas. The UI and backend will prevent saving invalid or incomplete settings.
- **UI Feedback & Protection**: The UI clearly marks global agents/plugins, disables editing/deletion for protected items, and provides robust error messages for validation issues.
- **Automatic Type Handling**: Plugin creation always requires a valid type, and the UI ensures the type is set before saving.
- **Live Merging**: Admins can toggle merging of global agents/plugins into workspace lists for user convenience.

---

## 1. Introduction

**Agents** are the core automation and intelligence units in Simplechat. They can perform tasks, answer questions, and interact with users or systems.  
**Plugins** extend the capabilities of agents, allowing them to connect to external services, data sources, or APIs.

Agents and plugins work together: agents provide the logic and workflow, while plugins provide the integrations and data access.

---

## 2. Agent Concepts

- **Agent**: A logical entity that can process requests, run workflows, or interact with users. In Simplechat, agents are typically powered by LLMs (Large Language Models) or custom logic.
- **Types of Agents**: Out of the box, Simplechat supports LLM-backed agents, but you can extend or customize agent logic as needed.
- **Agent Lifecycle**: Agents can be created, configured, assigned plugins, and deleted via the UI or API.
- **Capabilities**: Agents can answer questions, run queries, trigger workflows, and more depending on their configuration and plugins.
- **Limitations**: Agents are only as powerful as their plugins and configuration. Some actions require specific plugins to be enabled.


### Configuration, Inheritance, and the Power of Instructions

Configuration settings are the backbone of how plugins and agents behave in Simplechat. These settings, whether required, optional, or metadata, are not only validated by the backend schema, but can also be inherited and extended by custom plugins. When you create a new plugin, you can build on existing schemas and settings, ensuring consistency and reducing duplication across your integrations.

<div class="alert alert-warning" role="alert" style="font-weight: bold;">
<span style="font-size:1.1em;">⚠️ <strong>Critical:</strong></span> The <code>description</code> and <code>instruction</code> fields (in both plugin schemas and function decorators) are absolutely essential. They are not just for documentation; they directly inform the LLM and the application how, when, and why to use a plugin or function. If your instructions are vague, missing, or misleading, the agent may behave unpredictably, ignore your plugin, or even misuse it. <br><br>Always provide clear, specific, and actionable descriptions and instructions for every plugin, field, and function. <u>This is the single most important thing you can do to ensure your plugin works as intended and is discoverable by agents and users alike.</u>
</div>  
<br>
In summary: treat instructions and descriptions as code. They are the bridge between your logic and the LLM's reasoning.


### Global vs. Workspace Agents & Plugins

- **Global Agents/Plugins**: Managed by admins, available to all users. These are protected from editing or deletion by non-admins. Changes require a backend restart to take effect in if global mode. Global items are visually tagged in the UI.
- **Workspace Agents/Plugins**: Managed by users within their workspace. These can be created, edited, or deleted by users, and are isolated to their workspace. Workspace items are created and destroyed per user session.

**Recommended mode:** Workspace Agents/Plugins for most use cases. Use global mode for shared, organization-wide logic or integrations.

---

## 2a. Admin Features

- Manage global agents and plugins from the admin UI or API.
- Global items are protected from user edits/deletes and are visually marked.
- Toggle merging of global agents/plugins into workspace lists for user visibility.
- All changes to global agents/plugins require a backend restart to take effect for all users.
- Backend enforces schema validation and strips protected fields (like `is_global`) from user submissions.

---

## 2b. User Features

- Manage workspace agents and plugins from the workspace UI.
- Cannot edit or delete global agents/plugins; these are visually marked and protected.
- UI provides robust feedback: error messages for missing required fields, schema validation errors, and type selection.
- Plugin creation always requires a valid type; the UI prevents saving if type is missing.
- Workspace agents/plugins are isolated to your workspace and do not affect other users.

---

## 3. Plugins Overview

- **Plugin**: A modular integration that connects agents to external systems (e.g., Azure Log Analytics, Blob Storage, custom APIs).
- **Types of Plugins**: Simplechat ships with plugins for Azure, HTTP, storage, and more. You can also develop your own.
- **Plugin Capabilities**: Each plugin exposes specific functions (e.g., run a KQL query, fetch a file, send a webhook).
- **Schema-Driven**: Plugin configuration is validated and defaulted using JSON schemas, ensuring robust and user-friendly setup.

---

## 4. Plugin Management


### Adding, Editing, and Deleting Plugins
- Use the Plugins UI (admin for global, workspace for per-user) to add, edit, or remove plugins.
- Global plugins can only be managed by admins; users cannot edit or delete them.
- Click "New Plugin" to open the modal. Select a type (required), and the system will auto-populate required fields based on the plugin's schema.
- Fill in any required fields (see the right-hand descriptions or placeholders for guidance).
- Save to register the plugin. Plugins are validated against their schema before saving. The UI will prevent saving if required fields are missing or invalid.


### Plugin Settings

- **Required Fields**: Marked in the UI and enforced by the backend schema. The UI will show errors if missing.
- **Additional Fields**: Plugin-specific settings, auto-populated and validated.
- **Metadata**: Optional extra information for advanced scenarios.

> **Note:** The `additionalFields` and `metadata` sections are what make Simplechat plugin development truly modular and extensible. As a developer, you can define any custom settings or data your plugin needs in its schema, and the UI will automatically handle them; no need to modify frontend code. This means you can add new plugin types, features, or integrations simply by updating your plugin's backend code and schema, keeping the UI clean and future-proof.




### How Defaults and Validation Work
- When you select a plugin type, the backend merges your current settings with the schema defaults, ensuring all required fields are present.
- The UI will always show the latest required fields, even if the schema changes.
- The backend and UI both enforce schema validation. If you try to save an invalid plugin or agent, you will see a clear error message and the save will be blocked.


### Plugin Types and Discovery
- Plugin types are discovered automatically from the backend by scanning for Python classes that subclass `BasePlugin` in the plugin directory (`application/single_app/semantic_kernel_plugins/`).
- To add a new plugin type, simply create a new file named `<yourtype>_plugin.py`, ensure your main plugin class inherits from `BasePlugin`, and provide a corresponding JSON schema in `static/json/schemas/`.
- The backend will register any valid plugin type that follows this pattern, and the UI will automatically display it as an option; no frontend changes required.
- Each type has a description and a set of required/optional fields, as defined in its schema:
  - **Required fields** are the minimum settings needed for the plugin to function (e.g., API keys, endpoint URLs, or resource names). These are enforced by the schema and must be provided by the user. The UI will block saving if these are missing.
  - **Optional fields** are additional settings that can customize or extend plugin behavior (e.g., timeouts, filters, or advanced options). These are also defined in the schema and will appear in the UI if present, but are not mandatory.


> **Function Registration:** To make a function in your plugin available to the LLM (agent), decorate it with `@kernel_function` from the Semantic Kernel library. The decorator's `description` argument tells the LLM what the function does, its parameters, and when or why it should be used. If a function is missing this decorator (or the description), it will not be exposed to the agent or LLM for use.

Example:

```python
from semantic_kernel.plugin import kernel_function

class MyPlugin(BasePlugin):
    @kernel_function(description="Fetches the current weather for a given city. Use when the user asks about weather conditions.")
    def get_weather(self, city: str) -> str:
        # ...implementation...
        pass
```

This approach ensures the LLM knows how and when to use your function as part of an agent workflow.

---

## 5. Using Agents with Plugins

- **Assigning Plugins**: When configuring an agent, you can whitelist one or more plugins to extend its capabilities. Leaving actions to load allows the agent to dynamically use any plugins as needed.
- **Runtime Usage**: Agents use plugins to perform actions (e.g., query data, send messages) as part of their workflow.
- **Best Practices**:
  - Only enable plugins you need for your use case.
  - Review plugin permissions and settings for security.
  - Test agent workflows with plugins in a non-production environment first.

---

## 6. Advanced Topics

### Custom Plugin Development
- Place new plugin code in `application/single_app/semantic_kernel_plugins/`.
- Name your file `<yourtype>_plugin.py` and follow the structure of existing plugins.
- Provide a JSON schema for your plugin in `static/json/schemas/` (see existing schemas for examples).
- Register your plugin type by ensuring it subclasses `BasePlugin`.

### Adding New Agent Types
- (If supported) Extend agent logic by subclassing the agent base class and registering it in the backend.

### Backend Endpoints
- `/api/user/plugins` and `/api/admin/plugins`: Manage plugins via API.
- `/api/plugins/<plugin_type>/merge_settings`: Get schema-compliant plugin settings.
- See code for more endpoints and usage.


### Troubleshooting
- If you see schema validation errors, check your field values and consult the plugin's schema. The UI will show a detailed error message if a required field is missing or invalid.
- If a plugin type is missing, ensure its code and schema are present and valid.
- If you cannot edit or delete a plugin or agent, check if it is marked as global (admins only can manage these).
- If you see a message about "Please select a plugin type", make sure you have chosen a type from the dropdown before saving.

---


## 7. Security, Permissions, and Protections


- Only admins can manage global plugins and agents, as well as enable per-user mode. Users can manage their own workspace plugins and agents when admins allow it.
- Global agents/plugins are protected from user edits/deletes and are visually marked in the UI.
- Authentication and authorization are enforced for all plugin and agent actions.
    - Plugin authentication currently supports:
        - **API Key**: Simple key-based authentication.
        - **UserOAuth2**: Standard OAuth2 flow for user delegation.
        - **ServicePrincipalOAuth2**: Service Principal authentication.
        - **Managed Identity**: Leverage a managed identity for Azure resources.
- Review plugin settings and permissions regularly.

---

## 8. FAQ / Tips


**Q: Can I use multiple plugins with one agent?**
A: Yes! Assign as many as needed for your workflow.

**Q: Should I enable all plugins?**
A: Only enable the plugins you need for your specific use case with that agent. Enabling more plugins than needed increases complexity which can result in diminished performance (bad answers, increased token usage, etc).

**Q: How do I add a new plugin type?**
A: Add the code and schema, then restart the backend if needed. The UI will pick it up automatically.

**Q: What if a required field is missing?**
A: The UI and backend will prompt you to fill it in before saving. You will see a clear error message and the save will be blocked until you fix it.

**Q: Why can't I edit or delete a plugin or agent?**
A: It is likely a global agent/plugin, which is protected. Only admins can manage global items.

**Q: Why do I see 'Please select a plugin type'?**
A: You must select a type from the dropdown before saving a new plugin. The UI will block saving until you do.

**Q: Where can I get help?**
A: Check the README, this guide, or open an issue in the repo.

---

## 9. Glossary

- **Agent**: A logic unit that performs actions or answers questions in Simplechat.
- **Plugin**: An integration module that extends agent capabilities.
- **Schema**: A JSON definition of required/optional fields for plugin configuration.
- **Metadata**: Extra information attached to a plugin for advanced scenarios.
- **Additional Fields**: Plugin-specific settings, validated by schema.
