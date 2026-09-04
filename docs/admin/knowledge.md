---
layout: page
title: "Knowledge settings"
description: "Knowledge controls web research, URL access, Azure AI Search, extraction, chunking, multimodal processing, audio/video processing, and file sync."
section: "Administration"
audience: admin
admin_tab: knowledge
redirect_from:
  - /admin/file-sync/
  - /admin/search-extract/
---


# Knowledge settings

## What this group controls

Knowledge controls web research, URL access, Azure AI Search, extraction, chunking, multimodal processing, audio/video processing, and file sync.

## Why it matters

These settings decide what evidence enters the system and how it becomes searchable. Endpoint, chunking, and sync choices affect answer quality, indexing cost, and document freshness.

{% include media.html src="admin-settings/search-extract.png" alt="Screenshot of the Knowledge group in Admin Settings." title="Knowledge settings" %}

{% include media.html src="admin-settings/file-sync.png" alt="Screenshot of the Knowledge group in Admin Settings." title="Knowledge settings" %}

{% include media.html type="video" title="Knowledge settings walkthrough" poster="video-posters/admin-knowledge.png" capture="Recording planned. Walk through each tab in the Knowledge group and explain when to change each setting." %}

## Before you change anything

- Provision Azure AI Search and Document Intelligence before enabling dependent features.
- Decide whether web, URL, and deep research access is approved.
- Define allowed sync source types and workspace scopes.

## Web & Research {#web-research}

### Web Search {#web-search-section}

Web Search lets chat ground a single message in current public web results. SimpleChat does not call a search API directly. It calls an Azure AI Foundry agent that you create and configure, and that agent uses the Grounding with Bing Search tool to run the query and return results with citations.

Two things gate the capability, and both are required. `enable_web_search` turns it on, and `web_search_consent_accepted` records that an administrator acknowledged that Grounding with Bing Search moves data outside the Azure compliance boundary and operates under separate terms. Enabling the toggle without accepting the consent leaves the feature off.

Only the user's current chat message is sent to the agent. Conversation history, workspace documents, attached file contents, and system prompts are never included in the outbound query. Decide your rollout policy on that basis, and use the notice settings below if you want users reminded of it in the composer.

An agent ID is not optional. If it is missing, chat tells the user web search is unavailable rather than silently answering from training data, so a half-finished configuration fails loudly instead of quietly degrading.

### URL Access {#url-access-section}

The URL Access section belongs to the Web & Research tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Deep Research {#source-review-section}

The Deep Research section belongs to the Web & Research tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Web Search via Foundry Agent | Adds web search through the configured Azure AI Foundry agent for approved chat flows. Requires accepted consent to take effect. | Off | `enable_web_search`; capability toggle |
| Show data notice to users when web search is used | Shows a dismissible banner above the chat composer while web search is active, so users know the message will leave the tenant. | Off | `enable_web_search_user_notice`; capability toggle |
| Notice Text | The banner wording. Shown once per browser session, from the first time the user activates web search until they dismiss it. | N/A (runtime control) | `web_search_user_notice_text` |
| Foundry Project Endpoint | Project endpoint format: https://<foundry-resource>.services.ai.azure.com/api/projects/<project-name> (not the inference endpoint). | N/A (runtime control) | `web_search_foundry_endpoint` |
| Foundry API Version | Pins the service API version SimpleChat sends with requests for this feature. | N/A (runtime control) | `web_search_foundry_api_version` |
| Foundry Agent ID | Identifies the agent that carries the Grounding with Bing Search tool. Without it, chat reports web search as unavailable. | N/A (runtime control) | `web_search_foundry_agent_id` |
| Authentication Type | Selects how SimpleChat authenticates to the Foundry project. The identity must have Cognitive Services User and AI Developer roles on that project. | N/A (runtime control) | `web_search_foundry_auth_type` |
| Cloud | Selects the Azure cloud whose endpoints and authority are used to reach the Foundry project. | N/A (runtime control) | `web_search_foundry_cloud` |
| Managed Identity Type | Chooses between the system-assigned identity and a user-assigned identity when authenticating with a managed identity. | N/A (runtime control) | `web_search_foundry_managed_identity_type` |
| Authority Endpoint (Custom Cloud) | Overrides the login authority when the selected cloud is a custom or sovereign environment. | N/A (runtime control) | `web_search_foundry_authority` |
| Managed Identity Client ID (UAMI) | Identifies which user-assigned managed identity to authenticate with. | N/A (runtime control) | `web_search_foundry_managed_identity_client_id` |
| Tenant ID | Directory the service principal authenticates against. | N/A (runtime control) | `web_search_foundry_tenant_id` |
| Client ID | Application ID of the service principal used for authentication. | N/A (runtime control) | `web_search_foundry_client_id` |
| Client Secret | Provides the secret credential used when the selected authentication mode requires one. | N/A (runtime control) | `web_search_foundry_client_secret` |
| Enable URL Access for chat and workflows | Allows chat and workflows to inspect user-provided URLs within the configured URL limits and domain policy. | Off | `enable_url_access`; capability toggle |
| Require UrlAccessUser App Role | Required app role value: UrlAccessUser. Assign this role to users or groups in the Enterprise App before enabling the requirement. When enabled, only assigned users can use URL Access in chat or enable it for workflows. | Off | `require_member_of_url_access_user` |
| Chat URL Limit | Hard limit: 100 direct URLs per chat message. | 10 | `url_access_max_chat_urls_per_turn` |
| Workflow URL Limit | Hard limit: 500 direct URLs per workflow prompt. | 50 | `url_access_max_workflow_urls_per_run` |
| Url Access Allowed Domains | Lists the approved IDs, domains, groups, workspaces, or sources that may use this feature. | Empty list | `url_access_allowed_domains` |
| Allowed Domains | Lists the approved IDs, domains, groups, workspaces, or sources that may use this feature. | N/A (runtime control) | `url_access_allowed_domains_new` |
| Url Access Blocked Domains | Lists the domains, users, or destinations that this feature must not use. | Empty list | `url_access_blocked_domains` |
| Blocked Domains | Lists the domains, users, or destinations that this feature must not use. | N/A (runtime control) | `url_access_blocked_domains_new` |
| Enable Deep Research for chat | Enables Deep Research in chat so SimpleChat can inspect search results and linked source pages within the configured crawl limits. | Off | `enable_source_review`; capability toggle |
| Allow internal network hostnames | Allows DNS hostnames that resolve to private/internal addresses. Literal IP URL targets, localhost, metadata hosts, link-local addresses, and reserved addresses remain blocked. | Off | `source_review_allow_internal_hosts` |
| Activation Mode | Defines behavior for the related admin workflow; verify the affected feature after saving. | manual | `source_review_default_mode` |
| Max Pages per Turn | Hard limit: 10 pages. | 10 | `source_review_max_pages_per_turn` |
| Max Seed Pages per Turn | Limits initial search-result and direct URL pages so budget remains for child pages. | 10 | `source_review_max_seed_pages_per_turn` |
| Timeout per Turn | Hard limit: 30 seconds. | 30 | `source_review_timeout_seconds` |
| Max Redirects | Every redirect target is revalidated. | 5 | `source_review_max_redirects` |
| Max MB per Page | Hard limit: 5 MB. | 5 MB | `source_review_max_bytes_per_page` converted from `source_review_max_bytes_per_page` bytes |
| Source Traversal Depth | Depth 2 follows selected links from seed and child pages. | 2 | `source_review_max_depth` |
| Inspect linked source pages | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_deep_source_review`; capability toggle |
| Use model-assisted source link planning | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `source_review_enable_llm_planning` |
| Allow JavaScript rendering fallback | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `source_review_allow_js_rendering` |
| Rendered Load More Clicks | When JavaScript rendering is enabled, Deep Research can click visible Load More controls until this cap is reached. | 12 | `source_review_js_load_more_clicks` |
| Respect robots.txt | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `source_review_respect_robots_txt` |
| Log Deep Research activity | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `source_review_audit_logging` |
| Test Prompt | Narrows the admin list shown for test prompt. | N/A (runtime control) | `web_search_test_query` |
| URL | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `url_access_policy_test_url` |

## Search Index {#search-index}

### Azure AI Search {#azure-ai-search-section}

The Azure AI Search section belongs to the Search Index tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Use APIM instead of direct Azure AI Search | Routes Azure AI Search calls through APIM instead of calling the Search endpoint directly. | Off | `enable_ai_search_apim`; capability toggle |
| Search Endpoint | Provides the endpoint or route SimpleChat uses for this service. | Empty | `azure_ai_search_endpoint` |
| Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | key | `azure_ai_search_authentication_type` |
| Search Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_ai_search_key` |
| Azure APIM AI Search Endpoint | Provides the endpoint or route SimpleChat uses for this service. | Empty | `azure_apim_ai_search_endpoint` |
| Azure APIM AI Search Subscription Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_apim_ai_search_subscription_key` |

## Document Extraction {#extraction}

### Document Intelligence {#document-intelligence-section}

Document Intelligence reads PDFs and images. Nothing else in this tab produces searchable
text without it, so the tab leads with the connection: endpoint, authentication and a
connection test, either directly or through API Management. Only the path in use is shown.

Extraction behaviour follows. Standard uses Document Intelligence Read and is the fastest
and cheapest path for plain text. Enhanced captures tables, page structure, forms and
checkbox states, at roughly six times the cost per thousand pages. Auto inspects the
opening pages of a PDF and picks: if it finds tables, selection marks or figures the whole
document uses Enhanced, otherwise it finishes with Standard. Images always use Enhanced
under Auto.

Formula extraction is a separately billed Document Intelligence add-on that captures
equations as LaTeX instead of approximate OCR text. It applies to the Layout model only,
so it has no effect while extraction is set to Standard.

### Content Understanding {#content-understanding-section}

Azure AI Content Understanding is what backs Enhanced extraction where it is available. It
returns tables, page structure, checkbox states and generated descriptions of figures and
charts. Leave the endpoint blank and Enhanced falls back to Document Intelligence Layout,
which still captures tables, structure, forms and checkbox states but not figure
descriptions.

Content Understanding is not offered in every Azure cloud. Where it is unavailable the tab
says so and Enhanced uses the Layout fallback with nothing further to configure.

### Images Inside Office Files {#office-embedded-image-section}

Neither extraction engine describes figures embedded in Word and PowerPoint files, so a
chart pasted into a slide deck is invisible to search. With this on, embedded images are
extracted from the file, analysed with whichever engine backs the selected extraction mode,
and indexed as their own citable chunks. It works with Standard extraction as well as
Enhanced.

The two limits control cost. The minimum size skips icons, bullets and spacers, and the
per-document maximum caps how many images one file can charge for. Duplicate images within
a document are analysed once.

### Chunk Sizes {#chunk-size-section}

Documents are split into chunks before they are indexed, and each chunk is embedded as a single
request. That makes chunk size a retrieval decision and a hard technical limit at the same time:
smaller chunks return more precise citations, larger chunks keep more surrounding context in one
result, and a chunk that does not fit in the embedding model's context window cannot be indexed
at all.

Because of that limit, overrides are capped per unit rather than by one shared number. Word fields
and character fields have different ceilings, both derived from the embedding model's context
window, and the tab shows the current values. A value above the ceiling is reduced on save and the
page reports which fields were changed.

Page and slide counts are structural: how much text a page holds is not known until extraction
runs, so they are not capped here. If an extracted chunk still turns out to be too large to embed,
its text is stored and remains searchable and citable while only the portion used to compute its
vector is trimmed, and the event is logged.

Custom sizes apply to new uploads only. Existing documents keep the chunks they were indexed with
until they are uploaded again.

### Maximum File Size {#file-size-limit-section}

The ceiling applies to every upload, whether a document going into a workspace or a file
attached to a chat message, and it is checked before any extraction runs. That makes it the
cheapest control available for protecting the extraction pipeline: an oversized file is
refused outright rather than consuming Document Intelligence capacity and then failing.

It sits with extraction rather than with Workspaces because both upload paths feed the same
pipeline, and because the practical ceiling is whatever your extraction and storage tiers can
absorb rather than a workspace policy decision.

### Metadata Extraction {#metadata-extraction-section}

After a document is chunked, a further model pass can read it and record structured metadata
about it -- title, authors, subject, keywords -- which is what makes a citation readable as a
source rather than as a filename. It runs on upload, so enabling it later does not backfill
documents that are already indexed.

It costs an extra model call per document, and it needs a deployment selected for it, so it
is off by default.

### Multi-Modal Vision Analysis {#multimodal-vision-section}

Sends page images to a vision-capable model so the text inside diagrams, screenshots and
scanned pages becomes searchable alongside the extracted text. Only vision-capable
deployments are offered for selection, because a text-only model silently returns nothing
useful here.

Which deployments count as vision-capable is resolved in three steps, most authoritative
first: an explicit choice recorded on the model under [AI Models](ai-models.md), then the
application's built-in model capability data, then the model's name. A model resolved by
name alone is marked as inferred, because a name is a guess -- a self-hosted deployment may
read images without saying so, and some text-only chat variants are named like models that
do. If a model you expect is missing from the list, set its image support explicitly on the
endpoint that hosts it.

This is the most expensive extraction path in the group. Reach for it when the material is
genuinely visual; for text documents that happen to contain a chart, Document Intelligence
already captures the surrounding structure.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Maximum File Size (MB) | Rejects an upload larger than this before extraction runs. Applies to workspace documents and chat attachments alike. | 150 | `max_file_size_mb` |
| Enable Extract Meta Data | Runs a model pass on upload to record title, authors, subject and keywords for each document. | Off | `enable_extract_meta_data`; capability toggle |
| Extraction Model | The deployment the metadata pass sends its requests to. | Empty | `metadata_extraction_model` |
| Enable Multi-Modal Vision Analysis | Sends page images to a vision model so text inside diagrams and scans becomes searchable. | Off | `enable_multimodal_vision`; capability toggle |
| Vision Model | A vision-capable deployment, such as gpt-4o or a supported GPT 5 or later model. Only vision-capable models are offered. | Empty | `multimodal_vision_model` |
| Require DeepResearchUser App Role | Required app role value: DeepResearchUser. Assign this role to users or groups in the Enterprise App before enabling the requirement. When enabled, only assigned users can use Deep Research. | Off | `require_member_of_deep_research_user` |
| Max User URLs per Turn | Direct URLs beyond this cap are recorded as omitted in the ledger. | 100 | `deep_research_max_user_urls_per_turn` |
| Max Search Queries per Turn | Includes the original current-message query. | 8 | `deep_research_max_search_queries_per_turn` |
| Plan multiple web search queries | Narrows the admin list shown for plan multiple web search queries. | On | `deep_research_enable_query_planning` |
| Save research ledger artifacts | Narrows the admin list shown for save research ledger artifacts. | On | `deep_research_enable_ledger_artifact` |
| Enable Enhanced extraction | Enables the enhanced extraction path for richer PDF and image structure when the required services are configured. | Off | `enable_enhanced_extraction`; capability toggle |
| PDF and Image Extraction Mode | Enhanced captures more document detail for PDFs and images, including tables, page structure, and checked or unchecked marks. It adds latency and has a 6X increase for every 1000 pages when selected. | read | `document_intelligence_pdf_image_extraction_mode` |
| Auto Sample Pages | Auto samples this many first PDF pages with Document Intelligence Layout. If it detects tables, selection marks, or figures, the full PDF uses Enhanced; otherwise it finishes with Standard. Images use Enhanced in Auto mo | Not specified in defaults | `document_intelligence_auto_sample_pages` |
| Extract mathematical formulas | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_document_intelligence_formula_extraction`; capability toggle |
| Foundry Endpoint | Your Microsoft Foundry resource endpoint, without a trailing path. | Empty | `azure_content_understanding_endpoint` |
| Authentication Type | Managed identity requires the Cognitive Services User role on the Foundry resource. | key | `azure_content_understanding_authentication_type` |
| Content Understanding Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_content_understanding_key` |
| API Version | Default: | Not specified in defaults | `azure_content_understanding_api_version` |
| Document Analyzer | Default: | Not specified in defaults | `azure_content_understanding_analyzer_id` |
| Image Analyzer | Default: | Not specified in defaults | `azure_content_understanding_image_analyzer_id` |
| Analyze images embedded in DOCX and PPTX files | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_office_embedded_image_analysis`; capability toggle |
| Minimum Image Size (pixels) | Images narrower or shorter than this are skipped as icons or spacers. | Not specified in defaults | `office_embedded_image_min_pixels` |
| Maximum Images Per Document | Caps per-document cost. Duplicate images are analyzed once. | Not specified in defaults | `office_embedded_image_max_per_document` |
| Use APIM instead of direct Document Intelligence endpoint | Routes Document Intelligence calls through APIM instead of calling the service endpoint directly. | Off | `enable_document_intelligence_apim`; capability toggle |
| Document Intelligence Endpoint | Provides the endpoint or route SimpleChat uses for this service. | Empty | `azure_document_intelligence_endpoint` |
| Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | key | `azure_document_intelligence_authentication_type` |
| Document Intelligence Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_document_intelligence_key` |
| Azure APIM Document Intelligence Endpoint | Provides the endpoint or route SimpleChat uses for this service. | Empty | `azure_apim_document_intelligence_endpoint` |
| Azure APIM Document Intelligence Subscription Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_apim_document_intelligence_subscription_key` |
| Enable custom chunk sizes by file type | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_chunk_size_override`; capability toggle |
| Summarize history for search context | Adds a model-generated summary of recent conversation history into search context when hybrid document search is active, so follow-up searches can use prior conversational context. | Off | `enable_summarize_content_history_for_search` |
| Summarize older history beyond conversation limit | Summarizes older conversation messages that fall outside the configured conversation-history window so long chats can retain condensed context instead of dropping all older content. | Off | `enable_summarize_content_history_beyond_conversation_history_limit` |
| TXT (words) | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 400 words | `chunk_size_txt` |
| LOG (words) | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 1000 words | `chunk_size_log` |
| DOC (words) | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 400 words | `chunk_size_doc` |
| DOCM (words) | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 400 words | `chunk_size_docm` |
| DOCX (words) | Defines a capacity or timing boundary that keeps the feature inside supported limits. | configured WORD_CHUNK_SIZE words | `chunk_size_docx` |
| HTML (words) | Minimum enforced at 50% of target on merge. | 1200 words | `chunk_size_html` |
| Markdown (words) | Target words per chunk. Heading sections larger than this are split, so a long section under one heading cannot become a single unindexable chunk. Minimum enforced at 50% of target on merge. | 1200 words | `chunk_size_md` |
| XML (characters) | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 4000 characters | `chunk_size_xml` |
| YAML (characters) | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 4000 characters | `chunk_size_yaml` |
| YML (characters) | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 4000 characters | `chunk_size_yml` |
| JSON (characters) | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 4000 characters | `chunk_size_json` |
| Transcripts (words) | Applies to new audio transcripts. | 400 words | `chunk_size_transcript` |
| PDF (pages) | Pages per chunk after extraction. | 1 page | `chunk_size_pdf` |
| PPT/PPTX (slides) | Slides per chunk after extraction. | 1 slide | `chunk_size_pptx` |

## Audio & Video {#audio-video}

### AI Video Intelligence {#video-intelligence-section}

Uploaded video is processed by Azure Video Indexer, which extracts spoken content, speakers,
faces and brands into metadata that is then searchable and citable like any other document.

The endpoint comes first because the account details are read against it: use
`https://api.videoindexer.ai` for Azure Public and `https://api.videoindexer.ai.azure.us`
for Azure Government, and another value only for a non-standard deployment. The account id,
name, location, resource group and subscription follow, and the indexing timeout bounds how
long one file may take.

### AI Voice Conversations {#ai-voice-chat-section}

Three capabilities share one Azure Speech resource, which is why the resource is configured
first and the capabilities follow:

- **Audio file upload and transcription** transcribes and indexes uploaded recordings, so
  meetings, interviews and lectures become searchable.
- **Voice input** lets users record up to 90 seconds in the chat box instead of typing.
- **Voice responses** adds a speaker button to each message that reads the response aloud.

Configure the Speech resource once and turn on whichever of the three you need. Key
authentication needs only the key; managed identity needs the resource id, which can be
built from the subscription, resource group and resource name rather than typed by hand.

How many audio formats can be accepted depends on whether FFmpeg is present in the
deployment. The tab reports what the current runtime supports; without FFmpeg, only formats
that transcribe directly are accepted.

The completion chime is not here. It plays a local browser sound and needs no Speech
resource, so it lives with the other notification settings under
[Chat › Feedback & Alerts](chat.md#desktop-notifications-section).

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Video File Upload & Processing | Allows users to upload video files for processing through the configured Video Indexer resource. | Off | `enable_video_file_support`; capability toggle |
| Cloud / Endpoint Mode | Choose the endpoint family that matches your deployed cloud. Use Custom only when you need a non-standard Video Indexer endpoint. | Not specified in defaults | `video_indexer_cloud` |
| Custom API Endpoint | Provides the endpoint or route SimpleChat uses for this service. | Not specified in defaults | `video_indexer_custom_endpoint` |
| Effective API Endpoint | Provides the endpoint or route SimpleChat uses for this service. | Not specified in defaults | `video_indexer_endpoint_display` |
| Resource Group * | The Azure resource group containing your Video Indexer account | Empty | `video_indexer_resource_group` |
| Subscription ID * | Your Azure subscription ID | Empty | `video_indexer_subscription_id` |
| Account Name * | The name of your Video Indexer account resource | Empty | `video_indexer_account_name` |
| Location * | Azure region where your Video Indexer account is deployed (e.g., eastus, westus2, northeurope) | Empty | `video_indexer_location` |
| Account ID * | Found in the Video Indexer account Overview page in Azure Portal | Empty | `video_indexer_account_id` |
| ARM API Version | Default for : | Not specified in defaults | `video_indexer_arm_api_version` |
| Timeout (seconds) | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 600 | `video_index_timeout` |
| Enable Audio File Upload & Processing | Allows users to upload audio files for transcription through the configured Speech service. | Off | `enable_audio_file_support`; capability toggle |
| Enable Voice Input (Speech-to-Text) | Shows voice input controls in chat and sends captured speech to the configured Speech service. | Off | `enable_speech_to_text_input`; capability toggle |
| Enable Voice Responses (Text-to-Speech) | Allows voice responses from chat output through the configured Speech service. | Off | `enable_text_to_speech`; capability toggle |
| Endpoint | Use the resource-specific custom-domain endpoint when selecting Managed Identity. | Empty | `speech_service_endpoint` |
| Location | Required for speech recognition locale defaults and for text-to-speech when using Managed Identity. | Empty | `speech_service_location` |
| Speech Subscription ID | Defines behavior for the related admin workflow; verify the affected feature after saving. | Empty | `speech_service_subscription_id` |
| Speech Resource Group | Defines behavior for the related admin workflow; verify the affected feature after saving. | Empty | `speech_service_resource_group` |
| Speech Resource Name | If you use a custom-domain Speech endpoint, this is usually the first part of that hostname. | Empty | `speech_service_resource_name` |
| Speech Resource ID | Provide Subscription ID, Resource Group, and Speech Resource Name to auto-build the ARM resource ID. | Empty | `speech_service_resource_id` |
| Locale | Defines behavior for the related admin workflow; verify the affected feature after saving. | en-US | `speech_service_locale` |
| Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | key | `speech_service_authentication_type` |
| API Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `speech_service_key` |

## File Sync {#file-sync}

### File Sync {#file-sync-section}

The File Sync section belongs to the File Sync tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Visible Source Types {#file-sync-source-types-section}

The Visible Source Types section belongs to the File Sync tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Personal Workspace Sync {#file-sync-personal-section}

The Personal Workspace Sync section belongs to the File Sync tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Group Workspace Sync {#file-sync-group-section}

The Group Workspace Sync section belongs to the File Sync tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Public Workspace Sync {#file-sync-public-section}

The Public Workspace Sync section belongs to the File Sync tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable File Sync | Enables the File Sync feature so configured external sources can import files into workspaces. | Off | `enable_file_sync`; capability toggle |
| Max Sources | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 10 | `file_sync_max_sources_per_scope` |
| Min Schedule Minutes | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 15 | `file_sync_min_schedule_interval_minutes` |
| Max Files Per Run | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 1000 | `file_sync_max_files_per_run` |
| Max GB Per Run | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 5 GB | `file_sync_max_gb_per_run` |
| Max Concurrent Runs | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 2 | `file_sync_max_concurrent_runs` |
| Allow Recursive Sources | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `file_sync_allow_recursive_sources` |
| SMB Share | Available now. | On | `file_sync_visible_source_types` |
| OneDrive | Coming Soon. | Off | `file_sync_visible_source_type_onedrive` |
| On-prem SharePoint | Coming Soon. | Off | `file_sync_visible_source_type_sharepoint_on_prem` |
| Google Workspace | Coming Soon. | Off | `file_sync_visible_source_type_google_workspace` |
| Enable personal sync | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_file_sync_personal`; capability toggle |
| Admins manage sources only | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `file_sync_personal_admin_only` |
| Require PersonalFileSyncUser App Role | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `file_sync_personal_require_app_role` |
| Manage User Sources | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | Runtime UI control |
| Enable group sync | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_file_sync_group`; capability toggle |
| Admins manage sources only | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `file_sync_group_admin_only` |
| Require Group Assignment to Use File Sync | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `require_group_assignment_for_file_sync` |
| File Sync Allowed Group Ids | Lists the approved IDs, domains, groups, workspaces, or sources that may use this feature. | Empty list | `file_sync_allowed_group_ids` |
| Manage Group Sources | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | Runtime UI control |
| Enable public sync | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_file_sync_public`; capability toggle |
| Admins manage sources only | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `file_sync_public_admin_only` |
| Require Public Workspace Assignment to Use File Sync | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `require_public_workspace_assignment_for_file_sync` |
| File Sync Allowed Public Workspace Ids | Lists the approved IDs, domains, groups, workspaces, or sources that may use this feature. | Empty list | `file_sync_allowed_public_workspace_ids` |
| Manage Public Workspace Sources | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | Runtime UI control |
| Search Groups | Defines behavior for the related admin workflow; verify the affected feature after saving. | N/A (runtime control) | Runtime UI control |
| Search Public Workspaces | Defines behavior for the related admin workflow; verify the affected feature after saving. | N/A (runtime control) | Runtime UI control |

## Common tasks

1. **Configure document grounding.** Set search and extraction dependencies, upload a small document, and ask a grounded question. Outcome to verify: The answer cites indexed content.
2. **Enable approved research.** Enable only allowed web, URL, or deep research routes and test allowed and blocked cases. Outcome to verify: Research follows policy.
3. **Publish file sync.** Enable sync, choose source types and scopes, then run a small source. Outcome to verify: Files appear in the intended workspace.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| A synced file is not searchable | The source ran but extraction or indexing failed later. | Check sync state, extraction settings, and Azure AI Search before rerunning. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Security settings]({{ '/admin/security/' | relative_url }})
- [Workflow settings]({{ '/admin/workflow/' | relative_url }})
