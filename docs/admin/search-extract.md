---
layout: page
title: "Search and Extract Settings"
description: "Controls retrieval, web search, URL access, Deep Research, extraction services, chunking, video processing, and speech features."
section: "Administration"
audience: admin
admin_tab: search-extract
---

## What this tab controls

Controls retrieval, web search, URL access, Deep Research, extraction services, chunking, video processing, and speech features.

## Why it matters

This is the tab where document ingestion, retrieval, outbound web evidence, and media processing meet. The wrong setting can silently make uploaded files unsearchable, send user-provided URLs to external sites, increase Document Intelligence or Content Understanding cost, or allow Deep Research to crawl more than intended. Limits and allowlists are as important as endpoints.

{% include media.html src="admin/search-extract-overview.png" alt="Screenshot of the Search and Extract settings tab showing search and extract tab." title="Search and Extract tab" capture="Capture the Search and Extract tab for Search and Extract tab. Show relevant controls and redact secrets." %}

{% include media.html type="video" title="Search and Extract settings walkthrough" poster="video-posters/admin-search-extract.png" capture="Recording planned. Walk through every setting on the Search and Extract tab and explain when to change each one." %}

## Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Web Search via Foundry Agent | Adds web search through the configured Azure AI Foundry agent for approved chat flows. | Off | `enable_web_search`; capability toggle |
| Show data notice to users when web search is used | Makes show data notice to users when web search is used available in the product when its required service and access policy are configured. | Off | `enable_web_search_user_notice`; capability toggle |
| Notice Text | This message will be shown to users once per session when they first use web search. | N/A (runtime control) | `web_search_user_notice_text` |
| Foundry Project Endpoint | Project endpoint format: https://<foundry-resource>.services.ai.azure.com/api/projects/<project-name> (not the inference endpoint). | N/A (runtime control) | `web_search_foundry_endpoint` |
| Foundry API Version | Pins the service API version SimpleChat sends with requests for this feature. | N/A (runtime control) | `web_search_foundry_api_version` |
| Foundry Agent ID | Narrows the admin list shown for foundry agent id. | N/A (runtime control) | `web_search_foundry_agent_id` |
| Authentication Type | Identity must have Cognitive Services User and AI Developer roles on the Foundry project. | N/A (runtime control) | `web_search_foundry_auth_type` |
| Cloud | Narrows the admin list shown for cloud. | N/A (runtime control) | `web_search_foundry_cloud` |
| Managed Identity Type | Narrows the admin list shown for managed identity type. | N/A (runtime control) | `web_search_foundry_managed_identity_type` |
| Authority Endpoint (Custom Cloud) | Narrows the admin list shown for authority endpoint (custom cloud). | N/A (runtime control) | `web_search_foundry_authority` |
| Managed Identity Client ID (UAMI) | Narrows the admin list shown for managed identity client id (uami). | N/A (runtime control) | `web_search_foundry_managed_identity_client_id` |
| Tenant ID | Narrows the admin list shown for tenant id. | N/A (runtime control) | `web_search_foundry_tenant_id` |
| Client ID | Narrows the admin list shown for client id. | N/A (runtime control) | `web_search_foundry_client_id` |
| Client Secret | Provides the secret credential used when the selected authentication mode requires one. | N/A (runtime control) | `web_search_foundry_client_secret` |
| Enable URL Access for chat and workflows | Allows chat and workflows to inspect user-provided URLs within the configured URL limits and domain policy. | Off | `enable_url_access`; capability toggle |
| Require UrlAccessUser App Role | Required app role value: UrlAccessUser . Assign this role to users or groups in the Enterprise App before enabling the requirement. When enabled, only assigned users can use URL Access in chat or enable it for workflows. | Off | `require_member_of_url_access_user` |
| Chat URL Limit | Hard limit: 100 direct URLs per chat message. | 10 | `url_access_max_chat_urls_per_turn` |
| Workflow URL Limit | Hard limit: 500 direct URLs per workflow prompt. | 50 | `url_access_max_workflow_urls_per_run` |
| Url Access Allowed Domains | Lists the approved IDs, domains, groups, workspaces, or sources that may use this feature. | Empty list | `url_access_allowed_domains` |
| Allowed Domains | Lists the approved IDs, domains, groups, workspaces, or sources that may use this feature. | N/A (runtime control) | `url_access_allowed_domains_new` |
| Url Access Blocked Domains | Lists the domains, users, or destinations that this feature must not use. | Empty list | `url_access_blocked_domains` |
| Blocked Domains | Lists the domains, users, or destinations that this feature must not use. | N/A (runtime control) | `url_access_blocked_domains_new` |
| Enable Deep Research for chat | Enables Deep Research in chat so SimpleChat can inspect search results and linked source pages within the configured crawl limits. | Off | `enable_source_review`; capability toggle |
| Require DeepResearchUser App Role | Required app role value: DeepResearchUser . Assign this role to users or groups in the Enterprise App before enabling the requirement. When enabled, only assigned users can use Deep Research. | Off | `require_member_of_deep_research_user` |
| Allow internal network hostnames | Allows DNS hostnames that resolve to private/internal addresses. Literal IP URL targets, localhost, metadata hosts, link-local addresses, and reserved addresses remain blocked. | Off | `source_review_allow_internal_hosts` |
| Activation Mode | Controls how SimpleChat uses activation mode on this tab. | manual | `source_review_default_mode` |
| Max Pages per Turn | Hard limit: 10 pages. | 10 | `source_review_max_pages_per_turn` |
| Max Seed Pages per Turn | Limits initial search-result and direct URL pages so budget remains for child pages. | 10 | `source_review_max_seed_pages_per_turn` |
| Max User URLs per Turn | Direct URLs beyond this cap are recorded as omitted in the ledger. | 100 | `deep_research_max_user_urls_per_turn` |
| Max Search Queries per Turn | Includes the original current-message query. | 8 | `deep_research_max_search_queries_per_turn` |
| Timeout per Turn | Hard limit: 30 seconds. | 30 | `source_review_timeout_seconds` |
| Max Redirects | Every redirect target is revalidated. | 5 | `source_review_max_redirects` |
| Max MB per Page | Hard limit: 5 MB. | 5 MB | `source_review_max_bytes_per_page` converted from `source_review_max_bytes_per_page` bytes |
| Source Traversal Depth | Depth 2 follows selected links from seed and child pages. | 2 | `source_review_max_depth` |
| Inspect linked source pages | Makes inspect linked source pages available in the product when its required service and access policy are configured. | On | `enable_deep_source_review`; capability toggle |
| Plan multiple web search queries | Narrows the admin list shown for plan multiple web search queries. | On | `deep_research_enable_query_planning` |
| Save research ledger artifacts | Narrows the admin list shown for save research ledger artifacts. | On | `deep_research_enable_ledger_artifact` |
| Use model-assisted source link planning | Controls how SimpleChat uses use model-assisted source link planning on this tab. | On | `source_review_enable_llm_planning` |
| Allow JavaScript rendering fallback | Controls how SimpleChat uses allow javascript rendering fallback on this tab. | On | `source_review_allow_js_rendering` |
| Rendered Load More Clicks | When JavaScript rendering is enabled, Deep Research can click visible Load More controls until this cap is reached. | 12 | `source_review_js_load_more_clicks` |
| Respect robots.txt | Controls how SimpleChat uses respect robots.txt on this tab. | On | `source_review_respect_robots_txt` |
| Log Deep Research activity | Controls how SimpleChat uses log deep research activity on this tab. | On | `source_review_audit_logging` |
| Test Prompt | Narrows the admin list shown for test prompt. | N/A (runtime control) | `web_search_test_query` |
| URL | Controls how SimpleChat uses url on this tab. | Not specified in defaults | `url_access_policy_test_url` |
| Use APIM instead of direct Azure AI Search | Routes Azure AI Search calls through APIM instead of calling the Search endpoint directly. | Off | `enable_ai_search_apim`; capability toggle |
| Search Endpoint | Points SimpleChat to the search endpoint used by this feature. | Empty | `azure_ai_search_endpoint` |
| Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | key | `azure_ai_search_authentication_type` |
| Search Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_ai_search_key` |
| Azure APIM AI Search Endpoint | Points SimpleChat to the azure apim ai search endpoint used by this feature. | Empty | `azure_apim_ai_search_endpoint` |
| Azure APIM AI Search Subscription Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_apim_ai_search_subscription_key` |
| Enable Enhanced extraction | Enables the enhanced extraction path for richer PDF and image structure when the required services are configured. | Off | `enable_enhanced_extraction`; capability toggle |
| PDF and Image Extraction Mode | Enhanced captures more document detail for PDFs and images, including tables, page structure, and checked or unchecked marks. It adds latency and has a 6X increase for every 1000 pages when selected. | read | `document_intelligence_pdf_image_extraction_mode` |
| Auto Sample Pages | Auto samples this many first PDF pages with Document Intelligence Layout. If it detects tables, selection marks, or figures, the full PDF uses Enhanced; otherwise it finishes with Standard. Images use Enhanced in Auto mo | Not specified in defaults | `document_intelligence_auto_sample_pages` |
| Extract mathematical formulas | Makes extract mathematical formulas available in the product when its required service and access policy are configured. | Off | `enable_document_intelligence_formula_extraction`; capability toggle |
| Foundry Endpoint | Your Microsoft Foundry resource endpoint, without a trailing path. | Empty | `azure_content_understanding_endpoint` |
| Authentication Type | Managed identity requires the Cognitive Services User role on the Foundry resource. | key | `azure_content_understanding_authentication_type` |
| Content Understanding Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_content_understanding_key` |
| API Version | Default: | Not specified in defaults | `azure_content_understanding_api_version` |
| Document Analyzer | Default: | Not specified in defaults | `azure_content_understanding_analyzer_id` |
| Image Analyzer | Default: | Not specified in defaults | `azure_content_understanding_image_analyzer_id` |
| Analyze images embedded in DOCX and PPTX files | Makes analyze images embedded in docx and pptx files available in the product when its required service and access policy are configured. | On | `enable_office_embedded_image_analysis`; capability toggle |
| Minimum Image Size (pixels) | Images narrower or shorter than this are skipped as icons or spacers. | Not specified in defaults | `office_embedded_image_min_pixels` |
| Maximum Images Per Document | Caps per-document cost. Duplicate images are analyzed once. | Not specified in defaults | `office_embedded_image_max_per_document` |
| Use APIM instead of direct Document Intelligence endpoint | Routes Document Intelligence calls through APIM instead of calling the service endpoint directly. | Off | `enable_document_intelligence_apim`; capability toggle |
| Document Intelligence Endpoint | Points SimpleChat to the document intelligence endpoint used by this feature. | Empty | `azure_document_intelligence_endpoint` |
| Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | key | `azure_document_intelligence_authentication_type` |
| Document Intelligence Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_document_intelligence_key` |
| Azure APIM Document Intelligence Endpoint | Points SimpleChat to the azure apim document intelligence endpoint used by this feature. | Empty | `azure_apim_document_intelligence_endpoint` |
| Azure APIM Document Intelligence Subscription Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_apim_document_intelligence_subscription_key` |
| Enable custom chunk sizes by file type | Makes custom chunk sizes by file type available in the product when its required service and access policy are configured. | Off | `enable_chunk_size_override`; capability toggle |
| TXT (words) | Caps or schedules txt (words) so the feature stays within expected capacity. | 400 words | `chunk_size_txt` |
| LOG (words) | Caps or schedules log (words) so the feature stays within expected capacity. | 1000 words | `chunk_size_log` |
| DOC (words) | Caps or schedules doc (words) so the feature stays within expected capacity. | 400 words | `chunk_size_doc` |
| DOCM (words) | Caps or schedules docm (words) so the feature stays within expected capacity. | 400 words | `chunk_size_docm` |
| DOCX (words) | Caps or schedules docx (words) so the feature stays within expected capacity. | configured WORD_CHUNK_SIZE words | `chunk_size_docx` |
| HTML (words) | Minimum enforced at 50% of target on merge. | 1200 words | `chunk_size_html` |
| Markdown (words) | Caps or schedules markdown (words) so the feature stays within expected capacity. | 1200 words | `chunk_size_md` |
| XML (characters) | Caps or schedules xml (characters) so the feature stays within expected capacity. | 4000 characters | `chunk_size_xml` |
| YAML (characters) | Caps or schedules yaml (characters) so the feature stays within expected capacity. | 4000 characters | `chunk_size_yaml` |
| YML (characters) | Caps or schedules yml (characters) so the feature stays within expected capacity. | 4000 characters | `chunk_size_yml` |
| JSON (characters) | Caps or schedules json (characters) so the feature stays within expected capacity. | 4000 characters | `chunk_size_json` |
| Transcripts (words) | Applies to new audio transcripts. | 400 words | `chunk_size_transcript` |
| PDF (pages) | Pages per chunk after extraction. | 1 page | `chunk_size_pdf` |
| PPT/PPTX (slides) | Slides per chunk after extraction. | 1 slide | `chunk_size_pptx` |
| Enable Video File Upload & Processing | Allows users to upload video files for processing through the configured Video Indexer resource. | Off | `enable_video_file_support`; capability toggle |
| Cloud / Endpoint Mode | Choose the endpoint family that matches your deployed cloud. Use Custom only when you need a non-standard Video Indexer endpoint. | Not specified in defaults | `video_indexer_cloud` |
| Custom API Endpoint | Points SimpleChat to the custom api endpoint used by this feature. | Not specified in defaults | `video_indexer_custom_endpoint` |
| Effective API Endpoint | Points SimpleChat to the effective api endpoint used by this feature. | Not specified in defaults | `video_indexer_endpoint_display` |
| Resource Group * | The Azure resource group containing your Video Indexer account | Empty | `video_indexer_resource_group` |
| Subscription ID * | Your Azure subscription ID | Empty | `video_indexer_subscription_id` |
| Account Name * | The name of your Video Indexer account resource | Empty | `video_indexer_account_name` |
| Location * | Azure region where your Video Indexer account is deployed (e.g., eastus, westus2, northeurope) | Empty | `video_indexer_location` |
| Account ID * | Found in the Video Indexer account Overview page in Azure Portal | Empty | `video_indexer_account_id` |
| ARM API Version | Default for : | Not specified in defaults | `video_indexer_arm_api_version` |
| Timeout (seconds) | Caps or schedules timeout (seconds) so the feature stays within expected capacity. | 600 | `video_index_timeout` |
| Enable AI Response Completion Audio Cues | Makes ai response completion audio cues available in the product when its required service and access policy are configured. | Off | `enable_chat_completion_audio_cues`; capability toggle |
| Enable Audio File Upload & Processing | Allows users to upload audio files for transcription through the configured Speech service. | Off | `enable_audio_file_support`; capability toggle |
| Enable Voice Input (Speech-to-Text) | Shows voice input controls in chat and sends captured speech to the configured Speech service. | Off | `enable_speech_to_text_input`; capability toggle |
| Enable Voice Responses (Text-to-Speech) | Allows voice responses from chat output through the configured Speech service. | Off | `enable_text_to_speech`; capability toggle |
| Endpoint | Use the resource-specific custom-domain endpoint when selecting Managed Identity. | Empty | `speech_service_endpoint` |
| Location | Required for speech recognition locale defaults and for text-to-speech when using Managed Identity. | Empty | `speech_service_location` |
| Speech Subscription ID | Controls how SimpleChat uses speech subscription id on this tab. | Empty | `speech_service_subscription_id` |
| Speech Resource Group | Controls how SimpleChat uses speech resource group on this tab. | Empty | `speech_service_resource_group` |
| Speech Resource Name | If you use a custom-domain Speech endpoint, this is usually the first part of that hostname. | Empty | `speech_service_resource_name` |
| Speech Resource ID | Provide Subscription ID, Resource Group, and Speech Resource Name to auto-build the ARM resource ID. | Empty | `speech_service_resource_id` |
| Locale | Controls how SimpleChat uses locale on this tab. | en-US | `speech_service_locale` |
| Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | key | `speech_service_authentication_type` |
| API Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `speech_service_key` |

### Web Search, URL Access, and Deep Research

These features let chat or workflows inspect web content. Web Search uses the configured Foundry agent; URL Access and Deep Research are bounded by URL counts, domain policy, redirect limits, byte limits, timeouts, and role requirements. Configure policy first, then enable the user-facing switches.

### Document Intelligence and enhanced extraction

Document Intelligence extracts text from uploaded documents; enhanced extraction can use richer layout or Content Understanding paths. Enhanced modes can improve tables, figures, and selection marks, but they add latency and cost. Test with representative files before changing defaults.

### Video and speech processing

Video uploads depend on Video Indexer settings. Audio uploads, voice input, and voice responses depend on Speech settings. Enable only the features backed by resources you have configured and tested.

## Before you change anything

- Provision Azure AI Search and Document Intelligence before relying on workspace uploads.
- Approve outbound web, URL Access, and Deep Research policy before enabling those user-facing features.
- For Content Understanding, Video Indexer, and Speech, create the specific Azure resources and assign the app identity before enabling processing.
- Define domain allowlists or blocklists before allowing URL Access or Deep Research in regulated environments.

## Common tasks

1. **Configure document retrieval services.**
    1. Enter **Search Endpoint** and authentication settings under **Azure AI Search**.
    2. Enter **Document Intelligence Endpoint** and authentication settings.
    3. Choose **PDF and Image Extraction Mode**.
    4. Save and upload a test document to a workspace.
    Outcome to verify: The test document is extracted, indexed, and searchable.

{% include media.html src="admin/search-extract-configure-document-retrieval-services.png" alt="Screenshot of the Search and Extract settings tab showing configure document retrieval services." title="Search and Extract: Configure document retrieval services" capture="Capture the Search and Extract tab while performing Configure document retrieval services. Show the relevant controls and redact secrets." %}

2. **Enable URL Access safely.**
    1. Enable **Enable URL Access for chat and workflows**.
    2. Set **Chat URL Limit** and **Workflow URL Limit**.
    3. Populate **Allowed Domains** or **Blocked Domains**.
    4. Enable **Require UrlAccessUser App Role** only after assigning that role.
    Outcome to verify: Only approved users and domains can be used for URL inspection.

{% include media.html src="admin/search-extract-enable-url-access-safely.png" alt="Screenshot of the Search and Extract settings tab showing enable url access safely." title="Search and Extract: Enable URL Access safely" capture="Capture the Search and Extract tab while performing Enable URL Access safely. Show the relevant controls and redact secrets." %}

3. **Roll out Deep Research.**
    1. Enable **Enable Deep Research for chat**.
    2. Set page, seed-page, redirect, depth, byte, timeout, and query limits.
    3. Decide whether **Allow internal network hostnames** remains off.
    4. Test with the URL policy test before broad rollout.
    Outcome to verify: Deep Research stays within the configured crawl and safety boundaries.

{% include media.html src="admin/search-extract-roll-out-deep-research.png" alt="Screenshot of the Search and Extract settings tab showing roll out deep research." title="Search and Extract: Roll out Deep Research" capture="Capture the Search and Extract tab while performing Roll out Deep Research. Show the relevant controls and redact secrets." %}

4. **Enable audio or video processing.**
    1. Enable the specific upload or voice switches needed.
    2. Complete **Azure Video Indexer Configuration** or **Azure Speech Service Configuration**.
    3. Choose authentication type and provide required resource IDs or keys.
    4. Upload a small media file or test voice input.
    Outcome to verify: Media features work without exposing unsupported controls.

{% include media.html src="admin/search-extract-enable-audio-or-video-processing.png" alt="Screenshot of the Search and Extract settings tab showing enable audio or video processing." title="Search and Extract: Enable audio or video processing" capture="Capture the Search and Extract tab while performing Enable audio or video processing. Show the relevant controls and redact secrets." %}

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Web Search is unavailable | `enable_web_search` is off or Foundry agent settings are incomplete. | Enable Web Search and provide the Foundry settings. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Workspaces]({{ '/admin/workspaces/' | relative_url }})
- [Citations]({{ '/admin/citation/' | relative_url }})
- [Safety]({{ '/admin/safety/' | relative_url }})
