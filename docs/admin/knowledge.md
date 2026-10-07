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

Azure AI Search stores searchable document chunks and vectors for personal, group, and public workspaces. The connection here is also used to inspect and maintain those three index schemas. A missing index can be created; missing compatible fields can be added. A vector-dimension mismatch is different and is not repaired by silently changing the embedding model or rebuilding an index.

In the classic interface, opening Admin Settings checks the three indexes in sequence. Starting in **0.261.125**, unchanged observations do not rewrite settings. A first observation or repair can update embedding metadata, and the page adopts only the revision from its own conditional metadata operation. Saving waits for these checks to settle. Another administrator's edit still requires reviewing the latest settings; copy any unsaved edits before reloading.

Connection and permission failures stay visible rather than being hidden as if the index were healthy. Configure either the direct Search endpoint and authentication method, or the APIM endpoint and subscription key. Public Azure uses the Search audience `https://search.azure.com`; government and custom-cloud audiences remain separate. See [Admin settings troubleshooting]({{ '/troubleshooting/#admin-settings-saves-and-connection-tests' | relative_url }}).

#### Search result cache

Workspace document searches, the retrieval step behind grounded chat answers, agents, and workflows, are cached in the `search_cache` Cosmos DB container. When the same search runs again against the same documents, SimpleChat reuses the earlier results instead of embedding the query and running the semantic-ranked hybrid queries against each workspace index again. Repeated questions come back faster and cite the same sources, and fewer embedding and semantic ranker requests are billed or counted against quota. The cache does not need Redis, and it does not apply to web search.

A cached result is reused only while the query, scope, selected documents, tag filters, embedding model, and the documents in scope, including their versions and content screening state, all still match. Adding, deleting, re-sharing, or re-versioning a document therefore forces a fresh search straight away. Before cached results are returned, each one is re-checked against the requesting user's access and the document's current availability, and if any no longer qualifies the search runs fresh.

Caching is on by default and should stay on. Turn it off only while troubleshooting search relevance, when every search needs to run fresh. The cache lifetime bounds how long other changes can take to appear, such as a document that finishes processing after a search ran, or an edit made directly in Azure AI Search outside SimpleChat.

Both settings are edited in the V2 admin settings, in the **Search result cache** group of this section. The classic admin page has no control for them.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Use APIM instead of direct Azure AI Search | Routes Azure AI Search calls through APIM instead of calling the Search endpoint directly. | Off | `enable_ai_search_apim`; capability toggle |
| Search Endpoint | Provides the endpoint or route SimpleChat uses for this service. | Empty | `azure_ai_search_endpoint` |
| Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | key | `azure_ai_search_authentication_type` |
| Search Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_ai_search_key` |
| Azure APIM AI Search Endpoint | Provides the endpoint or route SimpleChat uses for this service. | Empty | `azure_apim_ai_search_endpoint` |
| Azure APIM AI Search Subscription Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_apim_ai_search_subscription_key` |
| Cache workspace search results | Reuses a recent identical workspace search instead of embedding the query and querying the indexes again. Cached results are re-checked against the user's access before they are returned. | On | `enable_search_result_caching`; V2 admin only |
| Cache lifetime (seconds) | How long cached results can be reused, from 60 to 3,600 seconds. Shown while caching is on. | 300 | `search_cache_ttl_seconds`; V2 admin only |

## Document Extraction {#extraction}

### Content screening before publication

When [Content Screening]({{ '/admin/security/#content-screening-section' | relative_url }}) is enabled, extracted pages, text, and native table data are staged privately before they become usable knowledge. The required policy applies to the complete document, not just the first batch of chunks.

Screening requires Enhanced Citations and is configured in Security so the policy framework is not tied to one extraction engine. Text that was hard to see in the original can still be inspected after extraction; detecting font color or hidden layers themselves is separate functionality. See [Screen and review workspace documents]({{ '/guides/review-screened-documents/' | relative_url }}).

### Document Intelligence {#document-intelligence-section}

Document Intelligence reads PDFs and images, and nothing else in this tab produces
searchable text without it: Standard extraction is its Read model, and Enhanced extraction
falls back to its Layout model. The section is the connection alone -- endpoint,
authentication and a connection test, either directly or through API Management. Only the
path in use is shown.

### Enhanced Extraction {#enhanced-extraction-section}

Enhanced extraction is for documents where structure matters: tables, page layout, forms,
checkbox states and, with Content Understanding, figures and charts. The section is led by
its switch, and every setting that only takes effect while Enhanced is on sits beneath it
and is hidden while it is off -- the Content Understanding connection included, since
Content Understanding is never called while Enhanced is off. With the switch off, every
PDF and image uses Standard extraction.

The extraction mode decides what new uploads use. Standard uses Document Intelligence Read
and is the fastest and cheapest path for plain text. Enhanced captures tables, page
structure, forms and checkbox states, at roughly six times the cost per thousand pages.
Auto inspects the opening pages of a PDF and picks: if it finds tables, selection marks or
figures the whole document uses Enhanced, otherwise it finishes with Standard. Images
always use Enhanced under Auto. Turning Enhanced on moves the mode from Standard to Auto,
because Enhanced with the mode left on Standard would change nothing for new uploads. With
Standard selected deliberately, people can still extract a document again as Enhanced from
its workspace.

Formula extraction is a separately billed add-on to the Document Intelligence Layout model
that captures equations as LaTeX instead of approximate OCR text. It applies wherever
Layout runs -- Auto's page sampling, and Enhanced extraction without Content
Understanding -- so it has no effect on Standard extraction or on documents Content
Understanding extracts.

The section also names the engine Enhanced extraction will use with the settings on
screen: Azure AI Content Understanding, or Document Intelligence Layout together with the
reason Content Understanding is not in use. It judges configuration rather than
connectivity; the connection test is what confirms the service answers.

#### Content Understanding connection {#content-understanding-section}

Azure AI Content Understanding is what backs Enhanced extraction where it is available. It
returns tables, page structure, checkbox states and generated descriptions of figures and
charts. It is optional: leave the endpoint blank and Enhanced uses Document Intelligence
Layout, which still captures tables, structure, forms and checkbox states but not figure
descriptions.

Content Understanding is not offered in every Azure cloud. Where it is unavailable its
connection is not shown, the section says Enhanced uses Document Intelligence Layout, and
there is nothing further to configure.

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

OneNote `.one` and `.onepkg` ingestion (from **0.261.142** on the React v2
branch) reuses the TXT word target. Each chunk stays within a OneNote page and
includes section/page context; that context counts toward both the word target
and the embedding character budget. No separate OneNote chunk-size setting is
required.

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

Multi-modal vision analysis asks a vision-capable model to describe an uploaded image, list its
notable objects, and read any visible text. For workspace uploads, the description is added to the
image's search chunk and embedded with it, so an image can be found by what it shows rather than
only by the text OCR happens to read. When OCR finds no text at all, as with a photo of an empty
room, the description becomes the image's only chunk, and metadata extraction, when enabled, runs
on it. For images attached directly to a chat, the description is added to the file content the
model receives.

Workspace images are analyzed only when Enhanced Citations is enabled. Images attached directly to
a chat are analyzed whenever this setting is on.

The Vision Model setting stores a model name. When multi-endpoint models are enabled, SimpleChat
sends the analysis through the enabled AI connection that hosts an enabled model with that
deployment name, model name, or id, so a model deployed on a different connection than the primary
GPT resource works. A deployment name match wins over a model name match, and the first matching
connection in the list wins over later ones. When no connection matches, or multi-endpoint models
are off, the GPT connection is used, directly or through APIM. **Test Vision Analysis** uses the
same connection as ingestion.

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
| Enable Multi-Modal Vision Analysis | Asks a vision model to describe each uploaded image, so an image can be found and cited by what it shows even when it contains no text. | Off | `enable_multimodal_vision`; capability toggle |
| Vision Model | A vision-capable deployment, such as gpt-4o or a supported GPT 5 or later model. Only vision-capable models are offered. With multi-endpoint models enabled, it is called through the AI connection that hosts it; otherwise through the GPT connection. | Empty | `multimodal_vision_model` |
| Require DeepResearchUser App Role | Required app role value: DeepResearchUser. Assign this role to users or groups in the Enterprise App before enabling the requirement. When enabled, only assigned users can use Deep Research. | Off | `require_member_of_deep_research_user` |
| Max User URLs per Turn | Direct URLs beyond this cap are recorded as omitted in the ledger. | 100 | `deep_research_max_user_urls_per_turn` |
| Max Search Queries per Turn | Includes the original current-message query. | 8 | `deep_research_max_search_queries_per_turn` |
| Plan multiple web search queries | Narrows the admin list shown for plan multiple web search queries. | On | `deep_research_enable_query_planning` |
| Save research ledger artifacts | Narrows the admin list shown for save research ledger artifacts. | On | `deep_research_enable_ledger_artifact` |
| Enable Enhanced extraction | Leads the Enhanced Extraction section. While it is off every PDF and image uses Standard extraction, and the extraction mode, formula extraction and Content Understanding connection are hidden because none of them can take effect. Turning it on moves a Standard mode to Auto. | Off | `enable_enhanced_extraction`; capability toggle |
| PDF and Image Extraction Mode | Enhanced captures more document detail for PDFs and images, including tables, page structure, and checked or unchecked marks. It adds latency and has a 6X increase for every 1000 pages when selected. | read | `document_intelligence_pdf_image_extraction_mode` |
| Auto Sample Pages | Auto samples this many first PDF pages with Document Intelligence Layout. If it detects tables, selection marks, or figures, the full PDF uses Enhanced; otherwise it finishes with Standard. Images use Enhanced in Auto mo | Not specified in defaults | `document_intelligence_auto_sample_pages` |
| Extract mathematical formulas | Captures equations as LaTeX through a billed add-on to the Document Intelligence Layout model, so it adds per-page cost wherever Layout runs: Auto's page sampling, and Enhanced extraction without Content Understanding. | Off | `enable_document_intelligence_formula_extraction`; capability toggle |
| Foundry Endpoint | Your Microsoft Foundry resource endpoint, without a trailing path. | Empty | `azure_content_understanding_endpoint` |
| Authentication Type | Managed identity requires the Cognitive Services User role on the Foundry resource. | key | `azure_content_understanding_authentication_type` |
| Content Understanding Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_content_understanding_key` |
| API Version | Default: | Not specified in defaults | `azure_content_understanding_api_version` |
| Document Analyzer | Default: | Not specified in defaults | `azure_content_understanding_analyzer_id` |
| Image Analyzer | Content Understanding analyzer that describes images embedded in DOCX and PPTX files, and standalone images when the document analyzer finds no text in them. Its `Summary` field is indexed as the image description. | prebuilt-imageSearch | `azure_content_understanding_image_analyzer_id` |
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
long one file may take. All five account fields are required: the name, resource group and
subscription identify the account when SimpleChat requests an access token, and the location
and account id address its API. Video Indexer is not offered in every region, so the account
can sit in a different region from SimpleChat; enter the account's own region as the location.

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

File Sync lets a workspace pull documents from an external source on a schedule instead
of relying on manual upload. In V2 Admin Settings everything that governs it is one
card, read from the top down: whether File Sync is on, which workspace types may use it
and who manages their sources, how much a single run may do, and which kinds of source
can be added.

Sync runs need [Redis Cache](scale.md#redis-cache-section) switched on with its URL set,
and its key when Redis uses key authentication. You can turn File Sync on and save its
settings first, but runs stay inactive until Redis is ready. The V2 card warns while
Redis Cache is switched off but does not check the URL or key, so confirm those under
Redis Cache.

#### Workspace types

Turning File Sync on shows **Personal workspaces**, **Group workspaces**, and **Public
workspaces** nested beneath it. A workspace type can sync only while both File Sync and
its own switch are on, which is why the type switches are hidden while File Sync is
off. Personal and group workspaces are on by default; public workspaces are off.

Each workspace type that is on has an **Access** panel directly under its switch. Its
rules decide who can open and manage that type's sources. Apart from the assignment
lists, they do not stop sources that already exist: those keep syncing on their
schedule.

- **Only administrators manage sources** stops anyone without the Admin role from
  opening or changing that workspace type's sources. Documents that have already synced
  stay.
- **Require the PersonalFileSyncUser app role** (personal workspaces only) limits
  opening and managing personal sources to holders of the `PersonalFileSyncUser` app
  role. Create and assign the role in the Enterprise App first, or no user will be able
  to manage their own personal sources. The requirement is also listed under
  [App Role Requirements](security.md#app-role-requirements-section).
- **Restrict to assigned groups** and **Restrict to assigned public workspaces** limit
  File Sync to the workspaces chosen in the list that appears beneath the switch.
  Workspaces left off the list can no longer manage their sources, and their scheduled
  runs are skipped, so an empty list with the restriction on leaves no workspace of
  that type able to manage or schedule a sync.

None of these rules apply to administrators managing sources on a workspace's behalf.
The classic admin page has a tool for that on its File Sync card: search for a user,
group, or public workspace and manage its sources directly. V2 does not offer that tool
yet.

#### Run limits

Run limits bound what a single workspace and a single run can do, and they apply to
every workspace type. A run skips the files that would take it past its file or size
limit rather than failing, and no new run starts while the concurrent run limit is
reached. Start with low limits and a conservative schedule: a broad share can create
many document versions in one run.

#### Source types

Source types decides which kinds of source the Add Source workflow offers. SMB Share,
Azure Files, and Azure Blob Storage are available; OneDrive, on-premises SharePoint,
and Google Workspace are listed as coming soon and cannot be selected yet. At least one
source type must stay selected while File Sync is on. While the panel is closed, its
header shows how many are selected.

With Key Vault secret storage enabled and a Key Vault name set, a source's credentials
are stored in Key Vault; otherwise they are stored with the source itself.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable File Sync | Lets workspaces pull documents from a configured source on a schedule instead of relying on manual upload. | Off | `enable_file_sync`; capability toggle; runs need a configured Redis Cache |
| Personal workspaces | Allows File Sync in personal workspaces while File Sync is on. | On | `enable_file_sync_personal` |
| Group workspaces | Allows File Sync in group workspaces while File Sync is on. | On | `enable_file_sync_group` |
| Public workspaces | Allows File Sync in public workspaces while File Sync is on. | Off | `enable_file_sync_public` |
| Only administrators manage sources | Stops anyone without the Admin role from opening or changing that workspace type's sources. Existing sources keep syncing on their schedule. | Off | `file_sync_personal_admin_only`, `file_sync_group_admin_only`, `file_sync_public_admin_only`; one in each Access panel |
| Require the PersonalFileSyncUser app role | Limits opening and managing personal sources to holders of the `PersonalFileSyncUser` app role. Existing sources keep syncing on their schedule. | Off | `file_sync_personal_require_app_role` |
| Restrict to assigned groups | Limits group File Sync to the groups in Assigned groups; scheduled runs for other groups are skipped. | Off | `require_group_assignment_for_file_sync` |
| Assigned groups | The groups that may use File Sync while the restriction is on. An empty list allows none. | Empty list | `file_sync_allowed_group_ids` |
| Restrict to assigned public workspaces | Limits public File Sync to the workspaces in Assigned public workspaces; scheduled runs for other public workspaces are skipped. | Off | `require_public_workspace_assignment_for_file_sync` |
| Assigned public workspaces | The public workspaces that may use File Sync while the restriction is on. An empty list allows none. | Empty list | `file_sync_allowed_public_workspace_ids` |
| Max Sources per Workspace | The most sync sources one workspace can hold; adding another is refused. | 10 | `file_sync_max_sources_per_scope`; 1–100 |
| Minimum Schedule Interval | The shortest gap a workspace may schedule between runs. | 15 minutes | `file_sync_min_schedule_interval_minutes`; 5–1440 |
| Max Files per Run | The most files one run imports; files past the limit are skipped in that run. | 1000 | `file_sync_max_files_per_run`; 1–100000 |
| Max Size per Run | The most data one run imports; a file that would exceed it is skipped in that run. Entered in gigabytes, stored in bytes. | 5 GB | `file_sync_max_bytes_per_run`; 1–1024 GB |
| Max Concurrent Runs | How many sync runs may be queued or running at once across the whole deployment; no new run starts while the limit is reached. | 2 | `file_sync_max_concurrent_runs`; 1–25 |
| Allow recursive sources | Lets a source include subfolders rather than only its top level. | On | `file_sync_allow_recursive_sources` |
| Source types offered when adding a source | Which source types the Add Source workflow offers. | SMB Share, Azure Files | `file_sync_visible_source_types`; at least one while File Sync is on |

## Common tasks

1. **Configure document grounding.** Set search and extraction dependencies, upload a small document, and ask a grounded question. Outcome to verify: The answer cites indexed content.
2. **Enable approved research.** Enable only allowed web, URL, or deep research routes and test allowed and blocked cases. Outcome to verify: Research follows policy.
3. **Publish file sync.** Enable sync, choose source types and scopes, then run a small source. Outcome to verify: Files appear in the intended workspace.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| A synced file is not searchable | The source ran but extraction or indexing failed later. | Check sync state, extraction settings, and Azure AI Search before rerunning. |
| A repeated question still returns the old sources after a change made directly in Azure AI Search | The search result cache is reusing results from before the change, which it cannot detect. | Wait for the cache lifetime to pass. To check the change sooner, rephrase the question, because different wording is a separate cache entry. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Security settings]({{ '/admin/security/' | relative_url }})
- [Workflow settings]({{ '/admin/workflow/' | relative_url }})
