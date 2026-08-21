---

layout: page

title: "Admin Configuration"

description: "Concise hub for SimpleChat Admin Settings, setup walkthrough behavior, tab references, and operator notes."

section: "Administration"

permalink: /admin_configuration/

menubar: docs_menu

redirect_from:

  - /reference/admin_configuration/

---



Admin Settings turns a running deployment into an operating environment by centralizing branding, model routing, workspace policy, safety controls, scale features, and logging. Use this page for orientation, then use the tab-specific pages for the full setting-by-setting guidance.



## Accessing Admin Settings

Sign in with an account that has the Admin role, open **Admin Settings**, and use the tab pages below to configure the deployment.

## Start with the tab guide



The [Administration settings guide]({{ '/admin/' | relative_url }}) is the canonical tab-by-tab reference. It explains the recommended first-time configuration order and summarizes what each tab controls.



## Configuration sections



- [General]({{ '/admin/appearance/' | relative_url }})

- [AI models]({{ '/admin/ai-models/' | relative_url }})

- [Search and extract]({{ '/admin/knowledge/' | relative_url }})

- [Workspaces]({{ '/admin/workspaces/' | relative_url }})

- [File sync]({{ '/admin/knowledge/' | relative_url }})

- [Global identities]({{ '/admin/workspaces/' | relative_url }})

- [Citations]({{ '/admin/chat/' | relative_url }})

- [Safety]({{ '/admin/security/' | relative_url }})

- [Security]({{ '/admin/security/' | relative_url }})

- [Agents]({{ '/admin/agents-actions/' | relative_url }})

- [Scale]({{ '/admin/scale/' | relative_url }})

- [Control center]({{ '/admin/operations/' | relative_url }})

- [Backup, migrate and restore]({{ '/admin/backup-recovery/' | relative_url }})

- [Governance]({{ '/admin/governance/' | relative_url }})

- [Logging]({{ '/admin/operations/' | relative_url }})

- [Send feedback]({{ '/admin/help/' | relative_url }})

- [Custom pages]({{ '/admin/appearance/' | relative_url }})

- [Latest features]({{ '/admin/help/' | relative_url }})



For step-by-step branding and home page changes, see [Configure branding, home page, and support settings]({{ '/guides/configure-branding-and-support-settings/' | relative_url }}).




## Related deployment and identity pages

- [Choose a deployment path]({{ '/start/deployment-options/' | relative_url }})
- [Manual setup reference]({{ '/setup_instructions_manual/' | relative_url }})
- [Use managed identity]({{ '/guides/use-managed-identity/' | relative_url }})

## Legacy screenshots

The legacy full configuration reference included annotated screenshots for several tabs. The tab pages remain the primary reference, and these image links are preserved for readers who bookmarked or reviewed the previous visual guide.

- [Admin Settings page]({{ '/images/admin_settings_page.png' | relative_url }})
- [General settings screenshot]({{ '/images/admin-settings/general.png' | relative_url }})
- [AI models screenshot]({{ '/images/admin-settings/ai-models.png' | relative_url }})
- [Agents and actions screenshot]({{ '/images/admin-settings/agents-actions.png' | relative_url }})
- [Logging screenshot]({{ '/images/admin-settings/logging.png' | relative_url }})
- [Scale screenshot]({{ '/images/admin-settings/scale.png' | relative_url }})
- [Control Center screenshot]({{ '/images/admin-settings/control-center.png' | relative_url }})
- [Workspaces screenshot]({{ '/images/admin-settings/workspaces.png' | relative_url }})
- [File Sync screenshot]({{ '/images/admin-settings/file-sync.png' | relative_url }})
- [Global Identity screenshot]({{ '/images/admin-settings/global-identity.png' | relative_url }})
- [Citations screenshot]({{ '/images/admin-settings/citation.png' | relative_url }})
- [Safety screenshot]({{ '/images/admin-settings/safety.png' | relative_url }})
- [Security screenshot]({{ '/images/admin-settings/security.png' | relative_url }})
- [Search and Extract screenshot]({{ '/images/admin-settings/search-extract.png' | relative_url }})
- [Send Feedback screenshot]({{ '/images/admin-settings/send-feedback.png' | relative_url }})

## Setup walkthrough



The Admin Settings page includes an interactive setup walkthrough for first-time configuration. It appears automatically when critical settings are missing, and admins can relaunch it with **Start Setup Walkthrough**.



### Walkthrough behavior



- It navigates to the relevant tab as each step starts.

- It skips steps that do not apply to the current configuration choices.

- It enables **Next** only when required fields for the current step are complete.

- It shows progress through the setup flow and supports previous, next, and close actions.



### Walkthrough order



1. Application basics for the app title and logo.

2. GPT API settings for Azure OpenAI endpoint and authentication.

3. GPT model selection for user-visible models.

4. Workspace enablement for personal and group workspaces.

5. Embedding API, Azure AI Search, and Document Intelligence when workspaces are enabled.

6. Optional video support and shared Speech service configuration.

7. Optional Content Safety, user feedback, conversation archiving, enhanced citations, and image generation.



## Admin Settings Execution Guide

Use the tab-specific pages below when you need to configure an area, validate it, and know what to check after saving. Open **Admin Settings**, select the named tab, make the change, use local test buttons where available, then click **Save Settings**.

## Operator notes preserved from the legacy reference



## Navigation Options



Admin Settings supports horizontal tab navigation and a collapsible left-sidebar layout. Admins can set the default in **General** settings, users can toggle layouts individually, and the setup walkthrough works with both layouts.



## Tips for Configuration

### Save and test before rollout



Use the floating **Save Settings** button after each set of changes. Use local **Test Connection** buttons before saving service endpoints. APIM-routed model settings require manually specified model names because automatic model fetching is not available through APIM.



### Managed identity role reminders



- Azure OpenAI chat access needs the **Cognitive Services OpenAI User** role.

- Multi-endpoint model discovery also needs **Reader** on the Azure OpenAI resource.

- Foundry endpoints need **Foundry User** or **Azure AI User** where older role names are still shown.

- Speech managed identity starts with **Cognitive Services Speech User**; transcription may also require **Cognitive Services Speech Contributor**. Managed identity also requires the custom-domain Speech endpoint, and text-to-speech needs the Speech Resource ID.

- Video Indexer runtime calls use the App Service system-assigned managed identity with **Contributor** on the Video Indexer resource. If Azure asks for a user-assigned managed identity during Video Indexer resource creation, that identity is for the Video Indexer resource itself, not for SimpleChat runtime calls.



For model endpoint identity details, see [Configure model endpoint identity]({{ '/guides/model-endpoint-identity-setup/' | relative_url }}).



### Mixed-source rollout controls



Mixed-source rollout is independently reversible. Keep `enable_mixed_source_manifest`, `enable_mixed_source_chat_search`, `enable_mixed_source_analyze`, `enable_cross_format_compare`, and `enable_mixed_source_conversation_continuity` off until the preceding stage is validated. The subordinate relevance, Analyze All, one-to-many Compare (`enable_cross_format_compare_one_to_many`), and development telemetry stages also default off. `enable_mixed_source_development_telemetry` records aggregate counts and latency only; it must never capture prompts, evidence, source identifiers, filenames, or storage paths.



### Dependency reminders



The walkthrough warns when dependent features are enabled without required services. For example, workspaces require embeddings, Azure AI Search, and Document Intelligence before retrieval-backed features are usable.



## Configuration Best Practices

### Security

Store secrets in the approved secret store where possible, prefer managed identity for Azure services, and validate role assignments before enabling role-gated features.

### Performance

Use connection tests, telemetry, and the Scale tab before increasing service tiers or throughput.

### Operational

Change one area at a time, save intentionally, and verify with both admin and normal-user accounts when a setting changes user-facing behavior.

### Cost Management

Enable optional services only when their features are needed, and monitor Cosmos DB, Search, OpenAI, Speech, Document Intelligence, and storage usage after rollout.

## Troubleshooting Configuration Issues

### Service Connection Failures

Use each tab's test button, verify endpoint URLs and authentication mode, and confirm managed identity or key-based permissions on the Azure resource.

### Multimedia Support

Configure video processing and shared Speech settings from the Search and Extract tab before allowing users to upload multimedia files.

### RBAC Access Control

Use Entra app roles and the relevant Admin Settings toggles before enforcing role-gated admin or workspace behavior.

### Feature Configuration Problems

Review dependencies first. Workspace features need embeddings, Azure AI Search, and Document Intelligence; scale-out needs Redis-backed sessions; APIM-routed models need explicitly configured model names.

## API Configuration Reference

### Configuration API Endpoints

Admin configuration changes are saved through the application's authenticated admin settings routes. Keep using the Admin Settings UI unless you are maintaining an approved automation path.

### Configuration Schema

The effective schema is organized by the Admin Settings tabs listed on this page and documented in the tab-specific references.
