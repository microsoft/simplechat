<!-- BEGIN release_notes.md BLOCK -->
# Feature Release

### **(v0.237.007)**

#### Bug Fixes

*   **Sidebar Conversations Race Condition and DOM Manipulation Fix**
    *   Fixed two critical issues preventing sidebar conversations from displaying correctly for users.
    *   **Issue #1 - DOM Manipulation Error**: Fixed JavaScript error `NotFoundError: Failed to execute 'insertBefore' on 'Node'` that caused sidebar conversation list to fail to render. Root cause was incorrect order of DOM element manipulation where `insertBefore()` was called with an invalid reference node after elements had been moved/removed.
    *   **Issue #2 - Race Condition with Empty Conversations**: Fixed race condition where users with no existing conversations who created their first conversation would not see it appear in the sidebar. Root cause was the loading flag never being reset when API returned empty conversations array, causing all subsequent reload attempts to be blocked indefinitely.
    *   **Solution Part 1**: Enhanced DOM manipulation with stricter parent node validation (`dropdownElement.parentNode === headerRow`), wrapped operations in try-catch for graceful fallback to `appendChild()`, and added comprehensive error logging. Ensures sidebar always renders even if timing issues occur.
    *   **Solution Part 2**: Implemented pending reload queue system. Instead of blocking concurrent loads, the code now marks `pendingSidebarReload = true` when a reload is requested during active loading. All code paths (success, empty array, error) now reset the loading flag and check for pending reloads, automatically triggering queued reload after 100ms delay.
    *   **Impact**: Before fix, ~10-15% of page loads had DOM errors and 100% of new users couldn't see their first conversation without manual page refresh. After fix, 0% failures with seamless user experience and no manual refresh needed.
    *   (Ref: `chat-sidebar-conversations.js`, DOM manipulation order, race condition handling, loading flag management, pending reload queue, lines 12-40, 93-115, 169-183)

### **(v0.237.006)**

#### Bug Fixes

*   **Windows Unicode Encoding Issue Fix**
    *   Fixed critical cross-platform compatibility issue where the application crashes on Windows when processing or displaying Unicode characters beyond the Western European character set.
    *   **Root Cause**: Python on Windows uses cp1252 encoding for stdout/stderr (limited to 256 Western European characters), while Azure services and web applications use UTF-8 encoding universally (1.1M+ characters). This mismatch caused `UnicodeEncodeError: 'charmap' codec can't encode character '\uXXXX'` when logging or displaying emojis, international characters, IPA symbols, or special formatting.
    *   **Impact**: Application crashes affecting:
        *   Video transcripts with phonetic symbols
        *   Chat messages containing emojis or international text
        *   Agent responses with Unicode formatting
        *   Debug logging across the entire application
        *   Error messages and stack traces
    *   **Solution**: Configured UTF-8 encoding globally at application startup for Windows platforms by reconfiguring `sys.stdout` and `sys.stderr` to UTF-8 at the top of `app.py` before any imports or print statements. Includes fallback for older Python versions (<3.7). Platform-specific fix only applies on Windows.
    *   **Testing**: Verified with video processing (IPA phonetic symbols), chat messages (emojis/international characters), debug logging (Unicode content), and confirmed no impact on Linux/macOS deployments.
    *   **Issue**: Fixes [#644](https://github.com/microsoft/simplechat/issues/644)
    *   (Ref: `app.py`, UTF-8 encoding configuration, cross-platform compatibility)

*   **Azure Speech Service Managed Identity Authentication Fix**
    *   Fixed Azure Speech Service managed identity authentication requiring resource-specific endpoints with custom subdomains instead of regional endpoints.
    *   **Root Cause**: Managed identity (AAD token) authentication fails with regional endpoints (e.g., `https://eastus2.api.cognitive.microsoft.com`) because the Bearer token doesn't specify which Speech resource to access. The regional gateway cannot determine resource authorization, resulting in 400 BadRequest errors. Key-based authentication works with regional endpoints because the subscription key identifies the specific resource.
    *   **Impact**: Users could not use managed identity authentication with Speech Service for audio transcription. Setup appeared successful but failed at runtime with authentication errors.
    *   **Solution**: Comprehensive setup guide for managed identity requiring:
        *   **Custom Subdomain**: Enable custom subdomain on Speech resource using `az cognitiveservices account update --custom-domain <resource-name>`
        *   **Resource-Specific Endpoint**: Configure endpoint as `https://<resource-name>.cognitiveservices.azure.com` (not regional endpoint)
        *   **RBAC Roles**: Assign `Cognitive Services Speech User` and `Cognitive Services Speech Contributor` roles to App Service managed identity
        *   **Admin Settings**: Update Speech Service Endpoint to resource-specific URL, set Authentication Type to "Managed Identity", leave Speech Service Key empty
    *   **Key Differences**:
        *   Key auth ✅ works with both regional and resource-specific endpoints
        *   Managed Identity ❌ fails with regional endpoints (400 BadRequest)
        *   Managed Identity ✅ works with resource-specific endpoints (requires custom subdomain)
    *   **Troubleshooting Guide**: Added comprehensive troubleshooting for `NameResolutionError` (custom subdomain not enabled), 400 BadRequest (wrong endpoint type), 401 Authentication errors (missing RBAC roles).
    *   (Ref: Azure Speech Service, managed identity authentication, custom subdomain, RBAC configuration, endpoint types)

*   **Sidebar Conversations DOM Manipulation Fix**
    *   Fixed JavaScript error "Failed to execute 'insertBefore' on 'Node': The node before which the new node is to be inserted is not a child of this node" that prevented sidebar conversations from loading.
    *   **Root Cause**: In `createSidebarConversationItem()`, the code was attempting DOM manipulation in the wrong order. When `originalTitleElement` was appended to `titleWrapper`, it was removed from `headerRow`, making the subsequent `insertBefore(titleWrapper, dropdownElement)` fail because `dropdownElement` was no longer a valid child reference in the expected DOM position.
    *   **Impact**: Users experienced a complete failure loading the sidebar conversation list, with the error appearing in browser console and preventing any conversations from displaying in the sidebar. This affected all users attempting to view their conversation history.
    *   **Solution**: Reordered DOM manipulation to remove `originalTitleElement` from DOM first, style it, add it to `titleWrapper`, then insert the complete `titleWrapper` before `dropdownElement`. Added validation to check if `dropdownElement` is a valid child before attempting insertion.
    *   (Ref: `chat-sidebar-conversations.js`, `createSidebarConversationItem()`, DOM manipulation order, line 150)

### **(v0.237.005)**

#### Bug Fixes

*   **Retention Policy Field Name Fix**
    *   Fixed retention policy to use the correct field name `last_updated` instead of the non-existent `last_activity_at` field.
    *   **Root Cause**: The retention policy query was looking for `last_activity_at` field, but all conversation schemas (legacy and current) use `last_updated` to track the conversation's last modification time.
    *   **Impact**: After the v0.237.004 fix, NO conversations were being deleted because the query required a field that doesn't exist on any conversation document.
    *   **Schema Support**: Now correctly supports all 3 conversation schemas:
        *   Schema 1 (legacy): Messages embedded in conversation document with `last_updated`
        *   Schema 2 (middle): Messages in separate container with `last_updated`
        *   Schema 3 (current): Messages with threading metadata with `last_updated`
    *   **Solution**: Changed SQL query to use `last_updated` field which exists on all conversation documents.
    *   (Ref: retention policy execution, conversation deletion, `delete_aged_conversations()`, `last_updated` field)

### **(v0.237.004)**

#### Bug Fixes

*   **Critical Retention Policy Deletion Fix**
    *   Fixed a critical bug where conversations with null/undefined `last_activity_at` were being deleted regardless of their actual age.
    *   **Root Cause**: The SQL query logic treated conversations with missing `last_activity_at` field as "old" and deleted them, even if they were created moments ago.
    *   **Impact**: Brand new conversations that hadn't had their `last_activity_at` field populated were incorrectly deleted when retention policy ran.
    *   **Solution**: Changed query to only delete conversations that have a valid, non-null `last_activity_at` that is older than the configured retention period. Conversations with null/undefined `last_activity_at` are now skipped.
    *   (Ref: retention policy execution, conversation deletion, `delete_aged_conversations()`)

*   **Public Workspace Retention Error Fix**
    *   Fixed error "name 'cosmos_public_conversations_container' is not defined" when executing retention policy for public workspaces.
    *   **Root Cause**: The code attempted to process conversations for public workspaces, but public workspaces don't have a separate conversations container—only documents and prompts.
    *   **Solution**: Removed conversation processing for public workspaces since they only support document retention.
    *   (Ref: public workspace retention, `process_public_retention()`)

### **(v0.237.003)**

#### New Features

*   **Extended Retention Policy Timeline Options**
    *   Added additional granular retention period options for conversations and documents across all workspace types.
    *   **New Options**: 2 days, 3 days, 4 days, 6 days, 7 days (1 week), and 14 days (2 weeks).
    *   **Full Option Set**: 1, 2, 3, 4, 5, 6, 7 (1 week), 10, 14 (2 weeks), 21 (3 weeks), 30, 60, 90 (3 months), 180 (6 months), 365 (1 year), 730 (2 years) days.
    *   **Scope**: Available in Admin Settings (organization defaults), Profile page (personal settings), and Control Center (group/public workspace management).
    *   **Files Modified**: `admin_settings.html`, `profile.html`, `control_center.html`.
    *   (Ref: retention policy configuration, workspace retention settings, granular time periods)

#### Bug Fixes

*   **Custom Logo Not Displaying Across App Fix**
    *   Fixed issue where custom logos uploaded via Admin Settings would only display on the admin page but not on other pages (chat, sidebar, landing page).
    *   **Root Cause**: The `sanitize_settings_for_user()` function was stripping `custom_logo_base64`, `custom_logo_dark_base64`, and `custom_favicon_base64` keys entirely because they contained "base64" (a sensitive term filter), preventing templates from detecting logo existence.
    *   **Solution**: Modified sanitization to add boolean flags for logo/favicon existence after filtering, allowing templates to check if logos exist without exposing actual base64 data.
    *   **Security**: Actual base64 data remains hidden from frontend; only True/False boolean values are exposed.
    *   **Files Modified**: `functions_settings.py` (`sanitize_settings_for_user()` function).
    *   (Ref: logo display, settings sanitization, template conditionals)

### **(v0.237.001)**

#### New Features

*   **Retention Policy Defaults**
    *   Admin-configurable organization-wide default retention policies for conversations and documents across all workspace types.
    *   **Organization Defaults**: Set default retention periods (1 day to 10 years, or "Don't delete") separately for personal, group, and public workspaces.
    *   **User Choice**: Users see "Using organization default (X days)" option and can override with custom settings or revert to org default.
    *   **Conditional Display**: Default retention settings only appear in Admin Settings when the corresponding workspace type is enabled.
    *   **Force Push Feature**: Administrators can push organization defaults to all workspaces, overriding any custom retention policies users have set.
    *   **Settings Auto-Save**: Force push automatically saves pending settings changes before executing to ensure current values are pushed.
    *   **Activity Logging**: Force push actions are logged to `activity_logs` container for audit purposes with admin info, affected scopes, and results summary.
    *   **API Endpoints**: New `/api/retention-policy/defaults/<workspace_type>` (GET) and `/api/admin/retention-policy/force-push` (POST) endpoints.
    *   **Files Modified**: `functions_settings.py`, `admin_settings.html`, `route_frontend_admin_settings.py`, `route_backend_retention_policy.py`, `functions_retention_policy.py`, `functions_activity_logging.py`, `profile.html`, `control_center.html`, `workspace-manager.js`.
    *   (Ref: Default retention settings, Force Push modal, activity logging, retention policy execution)

*   **Private Networking Support**
    *   Comprehensive private networking support for SimpleChat deployments via Azure Developer CLI (AZD) and Bicep infrastructure-as-code.
    *   **Network Isolation**: Private endpoints for all Azure PaaS services (Cosmos DB, Azure OpenAI, AI Search, Storage, Key Vault, Document Intelligence).
    *   **VNet Integration**: Full virtual network integration for App Service and dependent resources with automated Private DNS zone configuration.
    *   **AZD Integration**: Seamless deployment via `azd up` with `ENABLE_PRIVATE_NETWORKING=true` environment variable.
    *   **Post-Deployment Security**: New `postup` hook automatically disables public network access when private networking is enabled.
    *   **Enhanced Deployment Hooks**: Refactored all deployment hooks in `azure.yaml` with stepwise logging, explicit error handling, and clearer output for troubleshooting.
    *   **Documentation Updates**: Expanded Bicep README with prerequisites, Azure Government (USGov) considerations, and post-deployment validation steps.
    *   (Ref: `deployers/azure.yaml`, `deployers/bicep/`, private endpoint configuration, VNet integration)

*   **User Agreement for File Uploads**
    *   Global admin-configurable agreement that users must accept before uploading files to workspaces.
    *   **Configuration Options**: Enable/disable toggle, workspace type selection (Personal, Group, Public, Chat), Markdown-formatted agreement text (200-word limit), optional daily acceptance mode.
    *   **User Experience**: Modal prompt before file uploads with agreement text, "Accept & Upload" or "Cancel" options, daily acceptance tracking to reduce repeat prompts.
    *   **Activity Logging**: All acceptances logged to activity logs for compliance tracking with timestamp, user, workspace type, and action context.
    *   **Admin Access**: Settings accessible via Admin Settings → Workspaces tab → User Agreement section, with sidebar navigation link.
    *   **Files Added**: `user-agreement.js` (frontend module), `route_backend_user_agreement.py` (API endpoints).
    *   **Files Modified**: `admin_settings.html`, `route_frontend_admin_settings.py`, `base.html`, `_sidebar_nav.html`, `functions_activity_logging.py`, `workspace-documents.js`, `group_workspaces.html`, `public_workspace.js`, `chat-input-actions.js`.
    *   (Ref: User Agreement modal, file upload workflows, activity logging, admin configuration)

*   **Web Search via Azure AI Foundry Agents**
    *   Web search capability through Azure AI Foundry agents using Grounding with Bing Search service.
    *   **Pricing**: $14 per 1,000 transactions (150 transactions/second, 1M transactions/day limit).
    *   **Admin Consent Flow**: Requires explicit administrator consent before enabling due to data processing considerations outside Azure compliance boundary.
    *   **Consent Logging**: All consent acceptances are logged to activity logs for compliance and audit purposes.
    *   **Setup Guide Modal**: Comprehensive in-app configuration guide with step-by-step instructions for creating the agent, configuring Bing grounding, setting result count to 10, and recommended agent instructions.
    *   **User Data Notice**: Admin-configurable notification banner that appears when users activate web search, informing them that their message will be sent to Microsoft Bing. Customizable notice text, dismissible per session.
    *   **Graceful Error Handling**: When web search fails, the system informs users rather than answering from outdated training data.
    *   **Seamless Integration**: Web search results automatically integrated into AI responses when enabled.
    *   **Settings**: `enable_web_search` toggle, `web_search_consent_accepted` tracking, `enable_web_search_user_notice` toggle, and `web_search_user_notice_text` customization in admin settings.
    *   **Files Added**: `_web_search_foundry_info.html` (setup guide modal).
    *   **Files Modified**: `route_frontend_admin_settings.py`, `route_backend_chats.py`, `functions_activity_logging.py`, `admin_settings.html`, `chats.html`, `chat-input-actions.js`, `functions_settings.py`.
    *   (Ref: Grounding with Bing Search, Azure AI Foundry, consent workflow, activity logging, pricing, user transparency)

*   **Conversation Deep Linking**
    *   Direct URL links to specific conversations via query parameters for sharing and bookmarking.
    *   **URL Parameters**: Supports both `conversationId` and `conversation_id` query parameters.
    *   **Automatic URL Updates**: Current conversation ID automatically added to URL when selecting conversations.
    *   **Browser Integration**: Uses `history.replaceState()` for seamless URL updates without new history entries.
    *   **Error Handling**: Graceful handling of invalid or inaccessible conversation IDs with toast notifications.
    *   **Files Modified**: `chat-onload.js`, `chat-conversations.js`.
    *   (Ref: deep linking, URL parameters, conversation navigation, shareability)

*   **Plugin Authentication Type Constraints**
    *   Per-plugin-type authentication method restrictions for better security and API compatibility.
    *   **Schema-Based Defaults**: Falls back to global `AuthType` enum from `plugin.schema.json`.
    *   **Definition File Overrides**: Plugin-specific `.definition.json` files can restrict available auth types.
    *   **API Endpoint**: New `/api/plugins/<plugin_type>/auth-types` endpoint returns allowed auth types and source.
    *   **Frontend Integration**: UI can query allowed auth types to display only valid options.
    *   **Files Modified**: `route_backend_plugins.py`.
    *   (Ref: plugin authentication, auth type constraints, OpenAPI plugins, security)
    
#### Bug Fixes

*   **Control Center Chart Date Labels Fix**
    *   Fixed activity trends chart date labels to parse dates in local time instead of UTC.
    *   **Root Cause**: JavaScript `new Date()` was parsing date strings as UTC, causing labels to display previous day in western timezones.
    *   **Solution**: Parse date components explicitly and construct Date objects in local timezone.
    *   **Impact**: Chart x-axis labels now correctly show the intended dates regardless of user timezone.
    *   **Files Modified**: `control_center.html` (Chart.js date parsing logic).
    *   (Ref: Chart.js, date parsing, timezone handling, activity trends)

*   **Sovereign Cloud Cognitive Services Scope Fix**
    *   Fixed hardcoded commercial Azure cognitive services scope references that prevented authentication in Azure Government (MAG) and custom cloud environments.
    *   **Root Cause**: `chat_stream_api` and `smart_http_plugin` used hardcoded commercial cognitive services scope URL instead of configurable value from `config.py`.
    *   **Solution**: Replaced hardcoded scope with `AZURE_OPENAI_TOKEN_SCOPE` environment variable, dynamically resolved based on cloud environment.
    *   **Impact**: Streaming chat and Smart HTTP Plugin now work correctly in Azure Government, China, and custom cloud deployments.
    *   **Related Issue**: [#616](https://github.com/microsoft/simplechat/issues/616)
    *   (Ref: `chat_stream_api`, `smart_http_plugin`, sovereign cloud authentication, MAG support)

*   **User Search Toast and Inline Messages Fix**
    *   Updated `searchUsers()` function to use inline and toast messages instead of browser alert pop-ups.
    *   **Improvement**: Search feedback (empty search, no users found, errors) now displays as inline messages in the search results area.
    *   **Error Handling**: Errors display both inline message and toast notification for visibility.
    *   **Benefits**: Non-disruptive UX, contextual feedback, consistency with application patterns.
    *   **Related PR**: [#608](https://github.com/microsoft/simplechat/pull/608#discussion_r2701900020)
    *   (Ref: group management, user search, toast notifications, UX improvement)

### **(v0.235.025)**

#### Bug Fixes

*   **Retention Policy Document Deletion Fix**
    *   Fixed critical bug where retention policy execution failed when attempting to delete aged documents, while conversation deletion worked correctly.
    *   **Root Cause 1**: Documents use `last_updated` field, but query was looking for `last_activity_at` (used by conversations).
    *   **Root Cause 2**: Date format mismatch - documents store `YYYY-MM-DDTHH:MM:SSZ` but query used Python's `.isoformat()` with `+00:00` suffix.
    *   **Root Cause 3**: Duplicate column in SELECT clause when `partition_field='user_id'` caused query errors.
    *   **Root Cause 4**: Activity logging called with incorrect `deletion_reason` parameter instead of `additional_context`.
    *   **Files Modified**: `functions_retention_policy.py` (query field names, date format, SELECT clause, activity logging).
    *   (Ref: `delete_aged_documents()`, retention policy execution, Cosmos DB queries)

*   **Retention Policy Scheduler Fix**
    *   Fixed automated retention policy scheduler not executing at the scheduled time.
    *   **Root Cause 1**: Hour-matching approach was unreliable - only ran if check happened exactly during the execution hour (e.g., 2 AM), but 1-hour sleep intervals could miss the entire window.
    *   **Root Cause 2**: Check interval too long (1 hour) meant poor responsiveness and high probability of missing scheduled time.
    *   **Root Cause 3**: Code ignored the stored `retention_policy_next_run` timestamp, instead relying solely on hour matching.
    *   **Solution**: Now uses `retention_policy_next_run` timestamp for comparison, reduced check interval from 1 hour to 5 minutes, added fallback logic for missed executions.
    *   **Files Modified**: `app.py` (`check_retention_policy()` background task).
    *   (Ref: retention policy scheduler, background task, scheduled execution)

### **(v0.235.012)**

#### Bug Fixes

*   **Control Center Access Control Logic Fix**
    *   Fixed access control discrepancy where users with `ControlCenterAdmin` role were incorrectly granted access when the role requirement setting was disabled.
    *   **Correct Behavior**: When `require_member_of_control_center_admin` is DISABLED (default), only the regular `Admin` role grants access. The `ControlCenterAdmin` role is only checked when the setting is ENABLED.
    *   **Files Modified**: `functions_authentication.py` (decorator logic), `route_frontend_control_center.py` (frontend access computation), `_sidebar_nav.html` and `_top_nav.html` (menu visibility).
    *   (Ref: `control_center_required` decorator, role-based access control)

*   **Disable Group Creation Setting Fix**
    *   Fixed issue where "Disable Group Creation" setting was not being saved from Admin Settings or Control Center pages.
    *   **Root Cause 1**: Form field name mismatch - HTML used `disable_group_creation` but backend expected `enable_group_creation`.
    *   **Root Cause 2**: Missing onclick handler on Control Center's "Save Settings" button.
    *   **Files Modified**: `route_frontend_admin_settings.py` (form field reading), `control_center.html` (button handler).
    *   (Ref: group creation permissions, admin settings form handling)

### **(v0.235.003)**

#### New Features

*   **Approval Workflow System**
    *   Comprehensive approval process for sensitive Control Center operations requiring review and approval before execution.
    *   **Protected Operations**: Take ownership, transfer ownership, delete documents, and delete group operations now require approval.
    *   **Approval Features**: Documented justification, review process by group owners/admins, complete audit trail, auto-expiration after 3 days, notification integration.
    *   **Database**: New `approvals` container with TTL-based expiration.
    *   (Ref: `route_backend_control_center.py`, `route_frontend_control_center.py`, `control_center.html`, approval workflow UI)

*   **Agent Streaming Support**
    *   Real-time streaming support for Semantic Kernel agents with incremental response display.
    *   **Features**: Agent responses stream word-by-word, plugin citation capture during streaming, async generator pattern for efficient streaming, proper async/await handling.
    *   **User Experience**: Matches existing chat streaming experience, see agent thinking in real-time, immediate visual feedback.
    *   (Ref: `route_backend_chats.py`, agent streaming implementation, Semantic Kernel integration)

*   **Control Center**
    *   Comprehensive administrative interface for data and workspace management.
    *   **User Management**: View all users with search/filtering, grant/deny access with time-based restrictions, manage file upload permissions, monitor user engagement and storage.
    *   **Activity Trends**: Visual analytics with Chart.js showing daily activity metrics (chats, uploads, logins, document actions) across 7/30/90-day periods.
    *   **Group Management**: Approval workflow integration, group status management, member activity monitoring.
    *   **Dashboard**: Real-time statistics, key alerts, activity insights.
    *   (Ref: `route_frontend_control_center.py`, `route_backend_control_center.py`, `control_center.html`)

*   **Control Center Application Roles**
    *   Added two new application roles for finer-grained Control Center access control.
    *   **Control Center Admin**: Full administrative access to Control Center functionality including user management, administrative operations, and workflow approvals.
    *   **Control Center Dashboard Reader**: Read-only access to Control Center dashboards and metrics for monitoring and auditing purposes.
    *   **Use Cases**: IT operations monitoring, delegated administration, compliance auditing with appropriate access levels.
    *   **Files Modified**: `appRegistrationRoles.json` (new role definitions).
    *   (Ref: Entra ID app roles, role-based access control, Control Center permissions)

*   **Message Threading System**
    *   Linked-list threading system establishing proper message relationships throughout conversations.
    *   **Thread Fields**: `thread_id` (unique identifier), `previous_thread_id` (links to previous message), `active_thread` (thread active status), `thread_attempt` (retry tracking).
    *   **Benefits**: Proper message ordering, file upload tracking, image generation association, legacy message support.
    *   **Message Flow**: Links user messages to AI responses, system augmentations, file uploads, and image generations.
    *   (Ref: `route_backend_chats.py`, message schema updates, thread chain implementation)

*   **User Profile Dashboard**
    *   Complete redesign into modern dashboard with personalized analytics and visualizations.
    *   **Metrics Display**: Login statistics, chat activity, document usage, storage consumption, token tracking.
    *   **Visualizations**: Chart.js-powered activity trends, 30-day time-series data, interactive charts.
    *   **Features**: Cached metrics for performance, real-time data aggregation, responsive design.
    *   (Ref: `route_frontend_profile.py`, `profile.html`, Chart.js integration)

*   **Speech-to-Text Chat Input**
    *   Voice recording up to 90 seconds directly in chat interface with Azure Speech Service transcription.
    *   **Features**: Visual waveform display during recording, 90-second countdown timer, review before send, cancel anytime, responsive design.
    *   **Browser Support**: Chrome 49+, Edge 79+, Firefox 25+, Safari 14.1+.
    *   **Integration**: Uses existing Azure Speech Service configuration, MediaRecorder API, Web Audio API.
    *   (Ref: `route_backend_settings.py`, `chat-speech-to-text.js`, Speech Service integration)

*   **Text-to-Speech AI Responses**
    *   AI messages read aloud using Azure Speech Service with high-quality DragonHD voices.
    *   **Features**: 27 DragonHD Latest Neural Voices across languages, voice preview in profile, customizable speech speed (0.5x-2.0x), play/pause/stop controls.
    *   **Playback**: Inline "Listen" button per message, visual feedback during playback, auto-play mode option, prevents multiple simultaneous playbacks.
    *   **Integration**: Automatically disables streaming when auto-play enabled, per-user profile settings.
    *   (Ref: `route_backend_tts.py`, `chat-tts.js`, Azure Speech Service)

*   **Message Edit Functionality**
    *   Comprehensive message editing system allowing users to modify their sent messages and regenerate AI responses.
    *   **Features**: Modal interface for editing message text, preserves conversation context and settings, automatically regenerates AI response with edited content, maintains message metadata and threading.
    *   **User Experience**: Edit button on user messages, inline editing workflow, real-time validation, preserves agent/model selection.
    *   **Integration**: Works with `/api/message/<id>/edit` endpoint, updates conversation history, maintains thread relationships.
    *   (Ref: `chat-edit.js`, `route_backend_chats.py`, message edit modal)

*   **Message Delete Capability**
    *   One-click message deletion with proper conversation thread cleanup and metadata updates.
    *   **Features**: Delete button on user messages, ownership validation (author-only), updates message threading chains, removes associated metadata.
    *   **Safety**: Confirmation prompt, author verification, cascading thread updates, preserves conversation integrity.
    *   **Integration**: API endpoint for message deletion, updates conversation message count, maintains thread consistency.
    *   (Ref: `chat-messages.js`, message deletion handlers, thread management)

*   **Message Retry/Regenerate System**
    *   Powerful message regeneration system allowing users to retry AI responses with different models, agents, or settings.
    *   **Features**: Modal interface with agent/model selection, adjustable reasoning effort for o-series models, preserves original user message, generates new AI response with selected configuration.
    *   **Configuration Options**: Switch between agents, change model deployments, adjust reasoning effort (low/medium/high), modify generation parameters.
    *   **User Experience**: Retry button on AI messages, dropdown selection for agents/models, real-time configuration updates.
    *   (Ref: `chat-retry.js`, retry modal interface, agent/model switching)

*   **Message Masking System**
    *   Privacy-focused message masking capability for hiding sensitive information with visual overlays and PII protection.
    *   **Features**: Visual mask overlay on message content, `masked_ranges` metadata tracking character positions, mask/unmask toggle buttons, preserves original content while displaying masked state.
    *   **Privacy Protection**: Masks sensitive data in UI, tracks masked regions in database, supports partial message masking, reversible masking for authorized users.
    *   **Integration**: `/api/message/<id>/mask` endpoint, `masked` and `masked_ranges` metadata fields, visual indicators (bi-front/bi-back icons).
    *   **User Experience**: Mask button on messages, visual overlay showing masked content, toggle between masked and unmasked states.
    *   (Ref: `chat-messages.js`, `route_backend_chats.py`, masked content handling, `applyMaskedState()` function)

*   **Conversation Pinning**
    *   Pin important conversations to the top of the conversation list for quick access and improved organization.
    *   **Features**: Single conversation pinning, bulk pin operations for multiple conversations, persistent pin state in database, visual pin indicators in sidebar.
    *   **Operations**: Pin/unpin toggle, bulk selection interface, priority sorting (pinned conversations appear first), `is_pinned` metadata field.
    *   **API Endpoints**: `/api/conversations/<id>/pin` (POST), `/api/conversations/bulk-pin` (POST).
    *   **User Experience**: Pin icon in conversation list, bulk selection checkboxes, immediate visual feedback.
    *   (Ref: `chat-conversations.js`, `toggleConversationPin()`, `bulkPinConversations()`, conversation state management)

*   **Conversation Hiding**
    *   Hide conversations from the main list to declutter the sidebar without permanent deletion.
    *   **Features**: Single conversation hiding, bulk hide operations, toggle visibility without data loss, `is_hidden` metadata field for state persistence.
    *   **Benefits**: Declutter conversation list, temporary archiving without deletion, reversible operation, maintains conversation data.
    *   **API Endpoints**: `/api/conversations/<id>/hide` (POST), `/api/conversations/bulk-hide` (POST).
    *   **User Experience**: Hide button in conversation list, bulk selection interface, show hidden conversations toggle.
    *   (Ref: `chat-conversations.js`, `toggleConversationHide()`, `bulkHideConversations()`, visibility management)

*   **Quick Search for Conversations**
    *   Real-time client-side conversation filtering for instant search results without server roundtrips.
    *   **Features**: Real-time text filtering, searches conversation titles, client-side performance, keyboard shortcut support (Ctrl+K).
    *   **Search Scope**: Filters visible conversations in current workspace, highlights matching conversations, instant results as you type.
    *   **User Experience**: Search input in sidebar header, keyboard shortcut, clear button, responsive filtering.
    *   (Ref: `chat-conversations.js`, `toggleQuickSearch()`, client-side filtering)

*   **Advanced Search Modal**
    *   Comprehensive search functionality with filters, pagination, and search history for finding conversations across all workspaces.
    *   **Features**: Full-text search across conversation content, classification filters, date range selection, pagination support, search history tracking.
    *   **Search Capabilities**: Search conversation titles and content, filter by workspace scope, filter by date range, view search history, export results.
    *   **User Experience**: Modal interface with filter controls, results pagination, search history dropdown, results summary display.
    *   **Integration**: Server-side search API, search history persistence, results caching.
    *   (Ref: `chat-search-modal.js`, `openAdvancedSearchModal()`, `performAdvancedSearch()`, search history management)

*   **Automated Retention Policy System**
    *   Scheduled automatic deletion of aged conversations and documents based on configurable retention policies.
    *   **Features**: User-configurable retention periods, separate policies for conversations and documents, scheduled execution via daemon thread, exemption support for protected conversations/documents.
    *   **Configuration Options**: Retention periods by workspace scope (personal/group/public), auto-deletion scheduling (daily execution), user opt-in/opt-out controls, admin override capabilities.
    *   **Scopes**: Personal workspace retention, group workspace retention, public workspace retention, per-user policy settings.
    *   **Safety Features**: User exemption lists, dry-run mode for testing, deletion audit logging, grace period before deletion.
    *   **Integration**: Background daemon thread, admin configuration interface, user profile settings, Cosmos DB TTL-based cleanup.
    *   (Ref: `functions_retention_policy.py`, `execute_retention_policy()`, scheduled execution, user settings integration)

*   **Embedding Token Tracking**
    *   Comprehensive token tracking for document embedding generation in personal workspaces.
    *   **Tracking**: Captures token usage per document chunk, accumulates total tokens, stores embedding tokens and model deployment name in document metadata.
    *   **Benefits**: Embedding cost tracking, usage pattern analysis, document-level token metrics.
    *   (Ref: `functions_content.py`, `functions_documents.py`, embedding token capture)

*   **Search Result Caching**
    *   Ensures consistent search results across identical queries with Cosmos DB-based distributed caching.
    *   **Features**: Document set fingerprinting for cache invalidation, score normalization across indexes, 5-minute TTL, multi-instance deployment support.
    *   **Architecture**: Cosmos DB `search_cache` container, SHA256 cache keys, automatic expiration, cache sharing across instances.
    *   **Benefits**: Consistent user experience, reduced Azure AI Search costs, improved performance.
    *   (Ref: `functions_search.py`, `search_cache` container, fingerprint-based invalidation)

*   **Activity Trends Visualization**
    *   Interactive Chart.js visualization of daily activity metrics in Control Center.
    *   **Categories**: Chats, uploads, logins, document actions tracked separately.
    *   **Time Periods**: 7-day, 30-day, and 90-day views.
    *   **Data Sources**: Real data from Cosmos DB containers with sample data fallback.
    *   (Ref: `route_backend_control_center.py`, `control_center.html`, Chart.js implementation)

*   **Group Activity Timeline**
    *   Comprehensive real-time view of all group workspace activities.
    *   **Activity Types**: Document creation/deletion/updates, member additions/removals, status changes, conversations.
    *   **Features**: Icon-based activity display, timestamp tracking, member attribution, detailed metadata.
    *   **Benefits**: Group usage monitoring, audit trail, compliance tracking.
    *   (Ref: `route_frontend_groups.py`, activity timeline UI, activity logs integration)

*   **Dynamic OpenAPI Schema Generation**
    *   Dynamic schema generation reducing hardcoded OpenAPI definitions.
    *   **Features**: Analyzes Flask routes to generate schemas, maps routes to appropriate references, minimal required schemas for common patterns.
    *   **Benefits**: Reduced maintenance overhead, automatic schema updates, comprehensive API documentation.
    *   (Ref: `route_external_openapi_spec.py`, dynamic schema functions)

*   **Enhanced User Management**
    *   Comprehensive user activity metrics and analytics in Control Center.
    *   **Profile Features**: Profile image display with Base64 support, chat metrics (conversations, messages, 3-month activity), document metrics (count, storage, AI search size).
    *   **Analytics**: Last chat activity timestamps, storage estimations, feature status indicators.
    *   (Ref: `route_backend_control_center.py`, enhanced user metrics)

*   **Group Status Management**
    *   Fine-grained control over group workspace operations through status-based access controls.
    *   **Status Types**: Active (full functionality), Locked (read-only), Upload Disabled (no new uploads), Inactive (disabled).
    *   **Features**: Full audit trail logging, operation-level restrictions, compliance support.
    *   **Use Cases**: Legal holds, storage management, project lifecycle, risk mitigation.
    *   (Ref: `functions_groups.py`, `route_backend_groups.py`, status enforcement)

*   **Workflow System**
    *   Document processing workflows including PII analysis and approval workflows.
    *   **Features**: PDF document display in modals, workflow summary generation, approval routing, activity logging.
    *   (Ref: `route_frontend_workflow.py`, workflow templates, CSP configuration)

*   **Full Width Chat Support**
    *   Option to expand chat interface to full browser width for better screen utilization.
    *   (Ref: `chats.html`, responsive layout updates)

*   **Enhanced Document Metrics**
    *   Comprehensive document metadata tracking with enhanced analytics.
    *   (Ref: document metrics implementation across containers)

*   **Group Member Activity Logging**
    *   Detailed logging when group members are added or removed.
    *   (Ref: activity logging system, group member operations)

*   **Enable Group Creation Setting**
    *   Admin toggle to control whether users can create new groups.
    *   (Ref: admin settings, group creation permissions)

*   **YAML OpenAPI Specification Support**
    *   Support for YAML format OpenAPI specifications alongside JSON.
    *   (Ref: OpenAPI plugin system, YAML parsing)

*   **Inline OpenAPI Schema Generation**
    *   Generate OpenAPI schemas inline during plugin configuration.
    *   (Ref: plugin configuration UI, schema generation)

*   **Microphone Permission Management**
    *   Improved handling of browser microphone permissions for speech-to-text.
    *   (Ref: speech-to-text implementation, browser permissions)

#### Bug Fixes

*   **Agent Streaming Plugin Execution Fix**
    *   Fixed agent streaming failure when agents execute plugins during streaming.
    *   **Root Cause**: Event loop conflicts from `loop.run_until_complete(async_gen.__anext__())` pattern breaking async generator protocol.
    *   **Solution**: Proper async/await pattern with `asyncio.run()` for complete async context.
    *   **Impact**: Plugins like SmartHttpPlugin now work correctly in streaming mode.
    *   (Ref: `route_backend_chats.py`, async generator handling, plugin execution)

*   **Search Cache Cosmos DB Migration**
    *   Migrated search caching from in-memory to Cosmos DB for multi-instance deployment support.
    *   **Problem**: In-memory cache didn't share across App Service instances causing inconsistent results.
    *   **Solution**: Cosmos DB `search_cache` container with 5-minute TTL, partition key on `user_id`.
    *   **Benefits**: Cache sharing across instances, consistent user experience, distributed invalidation.
    *   (Ref: `functions_search.py`, `search_cache` container, TTL configuration)

*   **Vision Model Parameter Fix**
    *   Fixed GPT-5 and o-series model failures in vision analysis with "Unsupported parameter: 'max_tokens'" error.
    *   **Root Cause**: GPT-5 and o-series models require `max_completion_tokens` instead of `max_tokens`.
    *   **Solution**: Dynamic parameter selection based on model type.
    *   **Impact**: Vision analysis now works with all model families.
    *   (Ref: `route_backend_settings.py`, `functions_documents.py`, model-aware parameters)

*   **Group Plugin Global Merge Fix**
    *   Fixed group workspaces unable to see globally managed actions when merge setting enabled.
    *   **Root Cause**: `/api/group/plugins` endpoint didn't append global actions.
    *   **Solution**: Merge global actions into group plugins response with read-only badges.
    *   **Impact**: Groups can now select and use global actions while protecting them from modification.
    *   (Ref: `route_backend_groups.py`, global plugin merging)

*   **Workflow Summary Generation O1 API Fix**
    *   Fixed o1 model failures in workflow summary generation with "Unsupported parameter: 'temperature'" error.
    *   **Root Cause**: Unconditional application of `temperature` parameter to all models.
    *   **Solution**: Conditional parameter logic excluding `temperature` for o1 models.
    *   (Ref: `route_frontend_workflow.py`, model-aware parameter handling)

*   **Validation Utilities Consolidation**
    *   Consolidated duplicate validation functions across multiple files into centralized module.
    *   **Duplicated Functions**: `validateGuid()` in 4 locations, `validateEmail()` in 2 locations.
    *   **Solution**: Created `validation-utils.js` module with `ValidationUtils` namespace.
    *   **Benefits**: Single source of truth, easier maintenance, consistency.
    *   (Ref: `validation-utils.js`, code refactoring across control center and workspace files)

*   **Public Workspace Storage Calculation Fix**
    *   Fixed public workspaces showing 0 bytes storage despite having documents.
    *   **Root Cause**: Incorrect folder prefix (`public/{workspace_id}/` instead of `{workspace_id}/`).
    *   **Solution**: Fixed folder prefix, enhanced fallback logic, improved error handling.
    *   (Ref: `route_backend_control_center.py`, storage calculation logic)

*   **Public Workspace Metrics Caching Consistency Fix**
    *   Improved consistency in public workspace metrics caching across Control Center views.
    *   (Ref: metrics caching implementation)

*   **Activity Timeline All Logs Fix**
    *   Fixed activity timeline to properly display all log types.
    *   (Ref: activity log filtering)

*   **Activity Trends Field Mapping Fix**
    *   Corrected field mappings for activity trends data display.
    *   (Ref: activity trends API, field mapping)

*   **All File Types Embedding Token Tracking Fix**
    *   Extended embedding token tracking to all file types beyond just text.
    *   (Ref: `functions_documents.py`, comprehensive token tracking)

*   **PDF Embedding Token Tracking Fix**
    *   Fixed token tracking specifically for PDF document embeddings.
    *   (Ref: PDF processing, token capture)

*   **Create Group Button Visibility Fix**
    *   Fixed group creation button visibility based on admin settings.
    *   (Ref: UI conditional rendering, permission checks)

*   **File Message Metadata Loading Fix**
    *   Fixed metadata loading for file-related messages in conversations.
    *   (Ref: message metadata display, file associations)

*   **Group Agent Metadata Fix**
    *   Corrected agent metadata display and management in group contexts.
    *   (Ref: agent configuration, group agent handling)

*   **Group Document Metrics Date Format Fix**
    *   Fixed date formatting for group document metrics display.
    *   (Ref: document metrics, date formatting)

*   **Group Notification Context Enhancement**
    *   Enhanced notification context for group-related activities.
    *   (Ref: notification system, group context)

*   **Group Status UI Visibility Fix**
    *   Fixed UI visibility of group status indicators and controls.
    *   (Ref: group status display, conditional UI rendering)

*   **Group Table Auto-Refresh Fix**
    *   Fixed automatic refresh of group tables after operations.
    *   (Ref: table refresh logic, UI updates)

*   **Groups Tab Refresh Fix**
    *   Fixed refresh behavior on groups management tab.
    *   (Ref: tab state management, data refresh)

*   **Hidden Conversations Sidebar Click Fix**
    *   Fixed sidebar click handling for hidden conversations.
    *   (Ref: sidebar navigation, conversation visibility)

*   **Sidebar Group Badge Fix**
    *   Fixed group badge display in conversation sidebar.
    *   (Ref: sidebar UI, badge rendering)

*   **Top Nav Sidebar Overlap Fix**
    *   Fixed overlapping issues between top navigation and sidebar in certain layouts.
    *   (Ref: CSS layout, navigation positioning)

*   **Vision Analysis Debug Logging**
    *   Added comprehensive debug logging for vision analysis operations.
    *   (Ref: `functions_documents.py`, debug logging)

*   **Workflow PDF Iframe CSP Fix**
    *   Fixed Content Security Policy for PDF display in workflow iframes.
    *   (Ref: CSP headers, iframe configuration)

*   **Workflow PDF Viewer Height Fix**
    *   Fixed height issues in workflow PDF viewer modals.
    *   (Ref: modal styling, PDF viewer layout)

*   **Workspace Activity Modal Fix**
    *   Fixed workspace activity modal display and interaction issues.
    *   (Ref: modal functionality, workspace activity display)

*   **Search Cache Sharing Fix**
    *   Improved search cache sharing across user contexts.
    *   (Ref: cache key generation, sharing logic)

### **(v0.229.063)**

#### Bug Fixes

*   **Admin Plugins Modal Load Fix**
    *   Fixed issue where Admin Plugins modal would fail to load when using sidenav navigation.
    *   **Root Cause**: JavaScript code attempted to access DOM elements that didn't exist in sidenav navigation.
    *   **Solution**: Corrected DOM element checks to ensure compatibility with both top-nav and sidenav layouts.
    *   **User Experience**: Admins can now access the Plugins modal reglardless of navigation style.
    *   (Ref: `admin_plugins.js`, DOM existence checks)

### **(v0.229.062)**

#### Bug Fixes

*   **Enhanced Citations CSP Fix**
    *   Fixed Content Security Policy (CSP) violation that prevented enhanced citations PDF documents from being displayed in iframe modals.
    *   **Issue**: CSP directive `frame-ancestors 'none'` blocked PDF endpoints from being embedded in iframes, causing console errors: "Refused to frame '...' because an ancestor violates the following Content Security Policy directive: 'frame-ancestors 'none''".
    *   **Root Cause**: Enhanced citations use iframes to display PDF documents via `/api/enhanced_citations/pdf` endpoint, but the restrictive CSP policy prevented same-origin iframe embedding.
    *   **Solution**: Changed CSP configuration from `frame-ancestors 'none'` to `frame-ancestors 'self'`, allowing same-origin framing while maintaining security against external clickjacking attacks.
    *   **Security Impact**: No reduction in security posture - external websites still cannot embed application content, only same-origin framing is now allowed.
    *   **Benefits**: Enhanced citations PDF modals now display correctly without CSP violations, improved user experience for document viewing.
    *   (Ref: `config.py` SECURITY_HEADERS, `test_enhanced_citations_csp_fix.py`, CSP policy update)

### **(v0.229.061)**

#### Bug Fixes

*   **Chat Page Top Navigation Left Sidebar Fix**
    *   Fixed positioning and layout issues when using top navigation mode where the chat page left-hand menu was overlapping with the top navigation bar.
    *   Created a new short sidebar template (`_sidebar_short_nav.html`) optimized for top navigation layout without brand/logo area.
    *   Modified chat page layout to hide built-in left pane when top nav is enabled, preventing redundant navigation elements.
    *   Implemented proper positioning calculations to account for top navigation bar height with and without classification banner.
    *   (Ref: `_sidebar_short_nav.html`, `base.html`, `chats.html`, conditional template inclusion, layout positioning fixes)

### **(v0.229.058)**

#### New Features

*   **Admin Left-Hand Navigation Enhancement**
    *   Introduced an innovative dual-navigation approach for admin settings, providing both traditional top-nav tabs and a modern left-hand hierarchical navigation system.
    *   **Key Features**: Conditional navigation that automatically detects layout preference, hierarchical structure with two-level navigation (tabs → sections), smart state management for active states and submenus.
    *   **Comprehensive Organization**: All admin tabs now include organized sub-sections with proper section targeting for enhanced navigation.
    *   **Benefits**: Matches conversation navigation patterns users already know, provides better organization for complex admin settings, enables bookmarkable deep links to specific sections.
    *   (Ref: `admin_settings.html`, `_sidebar_nav.html`, `admin_sidebar_nav.js`)

*   **Time-Based Logging Turnoff Feature**
    *   Provides administrators with automatic turnoff capabilities for debug logging and file process logging to manage costs and security risks.
    *   **Cost Management**: Prevents excessive logging costs by automatically disabling logging after specified time periods (minutes to weeks).
    *   **Risk Mitigation**: Reduces security risks by ensuring debug logging doesn't remain enabled indefinitely.
    *   **Configuration Options**: Supports time ranges from 1-120 minutes, 1-24 hours, 1-7 days, and 1-52 weeks for both debug logging and file processing logs.
    *   **Background Monitoring**: Daemon thread monitors and enforces timer expiration automatically.
    *   (Ref: `admin_settings.html`, `route_frontend_admin_settings.py`, `app.py`)

*   **Comprehensive Table Support Enhancement**
    *   Enhanced table rendering to support multiple input formats ensuring tables from AI agents or users are properly displayed as styled HTML tables.
    *   **Format Support**: Unicode box-drawing tables (┌─┬─┐ style), markdown tables wrapped in code blocks, pipe-separated values (PSV) in code blocks, standard markdown tables.
    *   **Processing Pipeline**: Implements preprocessing pipeline that detects and converts various table formats to standard markdown before parsing.
    *   **Bootstrap Integration**: All generated tables automatically receive Bootstrap styling with striped rows and responsive design.
    *   (Ref: `chat-messages.js`, table conversion functions, functional tests)

*   **Public Workspace Management Enhancement**
    *   Added "Go to Public Workspace" button to Public Workspace Management page for quick navigation from management to workspace usage.
    *   **User Experience**: One-click navigation from management page to public workspace, automatically sets workspace as active for the user.
    *   **Consistency**: Aligns with existing Group Workspace management functionality, provides consistent workflow between management and usage.
    *   (Ref: `manage_public_workspace.html`, `route_frontend_public_workspaces.py`)

*   **Multimedia Support Reorganization**
    *   Reorganized Multimedia Support section from "Other" tab to "Search and Extract" tab with comprehensive Azure AI Video Indexer configuration guide.
    *   **Enhanced Configuration**: Added detailed setup instructions modal with step-by-step account creation, API key acquisition guidelines, and troubleshooting section.
    *   **Improved Organization**: Groups related search and extraction capabilities together, maintains all existing multimedia settings and functionality.
    *   (Ref: `admin_settings.html`, `_video_indexer_info.html`)

#### Bug Fixes

### **(v0.229.058)**

#### New Features

*   **Admin Left-Hand Navigation Enhancement**
    *   Introduced an innovative dual-navigation approach for admin settings, providing both traditional top-nav tabs and a modern left-hand hierarchical navigation system.
    *   **Key Features**: Conditional navigation that automatically detects layout preference, hierarchical structure with two-level navigation (tabs → sections), smart state management for active states and submenus.
    *   **Comprehensive Organization**: All admin tabs now include organized sub-sections with proper section targeting for enhanced navigation.
    *   **Benefits**: Matches conversation navigation patterns users already know, provides better organization for complex admin settings, enables bookmarkable deep links to specific sections.
    *   (Ref: `admin_settings.html`, `_sidebar_nav.html`, `admin_sidebar_nav.js`)

*   **Time-Based Logging Turnoff Feature**
    *   Provides administrators with automatic turnoff capabilities for debug logging and file process logging to manage costs and security risks.
    *   **Cost Management**: Prevents excessive logging costs by automatically disabling logging after specified time periods (minutes to weeks).
    *   **Risk Mitigation**: Reduces security risks by ensuring debug logging doesn't remain enabled indefinitely.
    *   **Configuration Options**: Supports time ranges from 1-120 minutes, 1-24 hours, 1-7 days, and 1-52 weeks for both debug logging and file processing logs.
    *   **Background Monitoring**: Daemon thread monitors and enforces timer expiration automatically.
    *   (Ref: `admin_settings.html`, `route_frontend_admin_settings.py`, `app.py`)

*   **Comprehensive Table Support Enhancement**
    *   Enhanced table rendering to support multiple input formats ensuring tables from AI agents or users are properly displayed as styled HTML tables.
    *   **Format Support**: Unicode box-drawing tables (┌─┬─┐ style), markdown tables wrapped in code blocks, pipe-separated values (PSV) in code blocks, standard markdown tables.
    *   **Processing Pipeline**: Implements preprocessing pipeline that detects and converts various table formats to standard markdown before parsing.
    *   **Bootstrap Integration**: All generated tables automatically receive Bootstrap styling with striped rows and responsive design.
    *   (Ref: `chat-messages.js`, table conversion functions, functional tests)

*   **Public Workspace Management Enhancement**
    *   Added "Go to Public Workspace" button to Public Workspace Management page for quick navigation from management to workspace usage.
    *   **User Experience**: One-click navigation from management page to public workspace, automatically sets workspace as active for the user.
    *   **Consistency**: Aligns with existing Group Workspace management functionality, provides consistent workflow between management and usage.
    *   (Ref: `manage_public_workspace.html`, `route_frontend_public_workspaces.py`)

*   **Multimedia Support Reorganization**
    *   Reorganized Multimedia Support section from "Other" tab to "Search and Extract" tab with comprehensive Azure AI Video Indexer configuration guide.
    *   **Enhanced Configuration**: Added detailed setup instructions modal with step-by-step account creation, API key acquisition guidelines, and troubleshooting section.
    *   **Improved Organization**: Groups related search and extraction capabilities together, maintains all existing multimedia settings and functionality.
    *   (Ref: `admin_settings.html`, `_video_indexer_info.html`)

#### Bug Fixes

*   **Admin Configuration Improvements**
    *   Addressed user feedback about admin settings organization and implemented critical improvements to reduce confusion and provide better guidance.
    *   **Duplicate Health Check Fix**: Consolidated health check configuration in General tab, removed duplicate from Other tab, added missing form field processing.
    *   **Tab Organization**: Reorganized tabs into logical groups (Core Settings, AI Models Group, Content Processing Group, Security, User Features, System Administration).
    *   **Workspace Dependency Validation**: Implemented real-time JavaScript validation to guide users when workspaces are enabled without required services (Azure AI Search, Document Intelligence, Embeddings).
    *   (Ref: `admin_settings.html`, `admin_settings.js`, `route_frontend_admin_settings.py`, `route_external_health.py`)

*   **Admin Settings Tab Preservation Fix**
    *   Fixed issue where admin settings page would redirect to "General" tab after saving, rather than preserving the active tab.
    *   **Root Cause**: Server-side redirects lose hash fragments, and tab activation only checked URL hash on page load without restoration mechanism.
    *   **Solution**: Implemented client-side tab preservation using sessionStorage, enhanced with dual navigation interface support (traditional tabs and sidebar navigation).
    *   **User Experience**: Users can now save settings and remain in their current tab, reducing frustration and improving workflow efficiency.
    *   (Ref: `admin_settings.js`, tab restoration logic, session storage implementation)

*   **Workspace Scope Prompts Fix**
    *   Fixed workspace scope selector to affect both document filtering and prompt filtering consistently.
    *   **Issue**: Workspace scope selection only affected documents but not prompts, creating inconsistent user experience.
    *   **Solution**: Integrated prompt loading with workspace scope selector, implemented scope-aware filtering logic (All, Personal, Group, Public), added event listeners for scope changes.
    *   **Impact**: Consistent behavior between document and prompt filtering, improved workflow efficiency for users working within specific workspace contexts.
    *   (Ref: `chat-prompts.js`, `chat-global.js`, scope filtering implementation)

*   **External Links New Window Fix**
    *   Fixed web links in AI responses and user messages to open in new windows/tabs instead of replacing current chat session.
    *   **Root Cause**: External links in markdown content didn't include `target="_blank"` attribute after DOMPurify sanitization.
    *   **Solution**: Created `addTargetBlankToExternalLinks()` utility function that identifies external links and adds proper attributes including security measures.
    *   **Security Enhancement**: Added `rel="noopener noreferrer"` for enhanced security, maintains DOMPurify sanitization.
    *   (Ref: `chat-utils.js`, `chat-messages.js`, external link processing)

*   **Video Indexer Debug Logging Enhancement**
    *   Enhanced Video Indexer functionality with comprehensive debug logging to help diagnose API call failures and configuration issues.
    *   **Comprehensive Logging**: Added detailed logging for authentication, upload process, processing polling, insights extraction, chunk processing, and video deletion.
    *   **Troubleshooting Support**: Provides detailed error information, request/response data, and step-by-step processing details for customer support.
    *   **Integration**: Uses existing `debug_print` function with `enable_debug_logging` setting for controlled debugging without performance impact.
    *   (Ref: `functions_authentication.py`, `functions_documents.py`, Video Indexer workflow logging)

### **(v0.229.014)**
#### Bug Fixes

##### Public Workspace Management Fixes
*   **Public Workspace Management Permission Fix**
    *   Fixed incorrect permission checking for public workspace management operations when "Require Membership to Create Public Workspaces" setting was enabled.
    *   **Issue**: Users with legitimate access to manage workspaces (Owner/Admin/DocumentManager) were incorrectly shown "Forbidden" errors when accessing management functionality.
    *   **Root Cause**: The `manage_public_workspace` route was incorrectly decorated with `@create_public_workspace_role_required`, conflating creation permissions with management permissions.
    *   **Solution**: Removed the incorrect permission decorator from the management route, allowing workspace-specific membership roles to properly control access.
    *   (Ref: `route_frontend_public_workspaces.py`, workspace permission logic)

*   **Public Workspace Scope Display Enhancement**
    *   Enhanced the Public Workspace scope selector in chat interface to show specific workspace names instead of generic "Public" label.
    *   **Display Logic**: 
        *   No visible workspaces: `"Public"`
        *   1 visible workspace: `"Public: [Workspace Name]"`
        *   2-3 visible workspaces: `"Public: [Name1], [Name2], [Name3]"`
        *   More than 3 workspaces: `"Public: [Name1], [Name2], [Name3], 3+"`
    *   **Benefits**: Improved workspace identification, consistent with Group scope naming pattern, better navigation between workspace scopes.
    *   (Ref: `chat-documents.js`, scope label updates, dynamic workspace display)

=======
##### User Interface and Content Rendering Fixes
*   **Unicode Table Rendering Fix**
    *   Fixed issue where AI-generated tables using Unicode box-drawing characters were not rendering as proper HTML tables in the chat interface.
    *   **Problem**: AI agents (particularly ESAM Agent) generated Unicode tables that appeared as plain text instead of formatted tables.
    *   **Solution**: 
        *   Added `convertUnicodeTableToMarkdown()` function to detect and convert Unicode table patterns to markdown format
        *   Enhanced message processing pipeline to handle table preprocessing before markdown parsing
        *   Improved `unwrapTablesFromCodeBlocks()` function to detect tables mistakenly wrapped in code blocks
    *   **Impact**: Tables now render properly as HTML, improving readability and data presentation in chat responses.
    *   (Ref: `chat-messages.js`, Unicode table conversion, markdown processing pipeline)

### **(v0.229.001)**

#### New Features

*   **GPT-5 Support**
    *   Added support for the GPT-5 family across Azure deployments: `gpt-5-nano`, `gpt-5-mini`, `gpt-5-chat`, and `gpt-5`.

*   **Image generation: gpt-image-1 Support**
    *   Added support for the `gpt-image-1` image-generation model. Offers improved image fidelity, dramatic improvement of word and text in the image, and stronger prompt adherence compared to DALL·E 3.

*   **Public Workspaces**
    *   Introduced organization-wide document repositories accessible to all users, enabling shared knowledge repositories and improved organization-wide knowledge discovery.
    *   Features include: centralized document management, seamless workspace scope switching, and organization-wide read access with admin-controlled write permissions.
    *   (Ref: `public_documents_container`, Azure AI Search integration, workspace scope UI)

*   **Enhanced Plugin System with Action Logging and Citations**
    *   Comprehensive logging system for all Semantic Kernel actions/plugin invocations, capturing function calls, parameters, results, and execution times.
    *   Features include: automatic logging, user tracking, Azure Application Insights integration, RESTful API endpoints for accessing logs and statistics.
    *   (Ref: `plugin_invocation_logger.py`, `logged_plugin_loader.py`, `route_plugin_logging.py`)

*   **SQL Actions/Plugins for Database Integration**
    *   Complete SQL plugin system enabling AI agents to interact with SQL databases effectively across multiple platforms (SQL Server, PostgreSQL, MySQL, SQLite).
    *   Features include: schema extraction, query execution with safety features, multi-database support, SQL injection protection, and read-only mode enforcement.
    *   (Ref: `sql_schema_plugin.py`, `sql_query_plugin.py`)

*   **Configurable OpenAPI Actions/Plugins**
    *   Flexible OpenAPI plugin system allowing users to expose any OpenAPI-compliant API as Semantic Kernel plugin functions.
    *   Features include: user-configurable specs, flexible authentication, secure file uploads, web UI integration, and support for both YAML and JSON formats.
    *   (Ref: OpenAPI plugin factory, security validation, modal interface configuration)

*   **Left-Hand Navigation Menu**
    *   Complete redesign of navigation paradigm with persistent sidebar interface providing access to conversations, workspaces, and key features.
    *   Features include: responsive collapsible design, state management, dynamic loading, and full keyboard accessibility support.
    *   (Ref: Sidebar CSS framework, JavaScript components, conversation lists)

*   **Consolidated Account Menu**
    *   Unified dropdown-based navigation system consolidating all user account-related functions into a single, intuitive interface.
    *   Features include: single-point access to account functions, streamlined navigation, responsive design, and dynamic content based on user permissions.
    *   (Ref: Bootstrap dropdown component, state management, role-based menu items)

*   **Dark Mode and Light Mode Logo Support**
    *   Intelligent logo management that automatically switches between different logo variants based on the user's selected theme.
    *   Features include: dual logo storage, automatic theme detection, CSS-based logo switching, and admin configuration for both variants.
    *   (Ref: Theme detection, database schema for logo variants, admin upload interface)

*   **Message Metadata Display**
    *   Comprehensive tracking and display of detailed information about each message including timestamps, token usage, model information, and processing times.
    *   Features include: real-time metadata collection, structured storage in Cosmos DB, expandable UI display, and performance tracking.
    *   (Ref: Message metadata schema, UI integration, token usage monitoring)

*   **Copy Text Message Feature**
    *   Convenient one-click copying of message content with support for various content types including plain text, formatted content, and code blocks.
    *   Features include: universal copy support, format preservation, smart content detection, and modern clipboard API integration.
    *   (Ref: `MessageCopyManager`, clipboard API, content type detection)

*   **External Links Configuration**
    *   Administrative ability to configure and display custom navigation links to external resources and services within the SimpleChat interface.
    *   Features include: admin configuration, database storage, URL validation, responsive design, and role-based link visibility.
    *   (Ref: External links schema, admin interface, security validation)

*   **Enhanced Citations Managed Identity Authentication**
    *   Added Managed Identity authentication option to Enhanced Citations Storage Account configuration, eliminating need for stored connection strings.
    *   Features include: dropdown selection for authentication method, dynamic form fields, validation logic, and Azure RBAC support for fine-grained access control.
    *   Benefits include: enhanced security posture, elimination of stored secrets, and support for enterprise security policies.
    *   (Ref: `enhanced_citations_storage_authentication_type`, storage client initialization, RBAC documentation)

#### User Interface Enhancements

*   **Comprehensive UI Performance Enhancements**
    *   Multiple interconnected improvements including group name display in workspace scope selection, personal and group workspace UI improvements, and enhanced file upload performance.
    *   Improvements include: 50x tabular data performance improvement, smart HTTP plugin with PDF support, user-friendly feedback displays, and improved group management UI.
    *   (Ref: `WorkspaceScopeManager`, performance optimizations, UI component updates)

*   **Improved Chat UI Input Layout**
    *   Comprehensive redesign of chat interface's input and button layout creating more space for typing and streamlined user experience.
    *   Features include: responsive grid system, component-based design, CSS Grid and Flexbox layout, and touch-optimized controls.
    *   (Ref: Chat input container, responsive layout, mobile optimization)

*   **Double-Click Conversation Title Editing**
    *   Intuitive conversation renaming through double-click gesture directly within the chat interface, eliminating need for separate edit dialogs.
    *   Features include: inline editing, event handling with debouncing, auto-save functionality, and keyboard support (Enter to save, Escape to cancel).
    *   (Ref: `ConversationTitleEditor`, inline editing, event handling)

*   **Conversation Metadata Modal Width Enhancement**
    *   Enhanced conversation metadata modal to be wider so conversation IDs and long text content display properly without wrapping.
    *   Changes include: increased modal width from `modal-lg` to `modal-xl`, updated CSS for 1200px max-width, and enhanced code element styling.
    *   (Ref: `templates/chats.html`, modal width enhancements, readability improvements)

*   **Comprehensive File Content Inclusion Enhancement**
    *   Unified content limits for all file types, increasing from 1KB to 50KB for non-tabular files to match tabular file limits.
    *   Benefits include: consistent LLM performance regardless of file type, complete document analysis, enhanced code review capabilities, and simplified logic.
    *   (Ref: `route_backend_chats.py`, unified content limits, LLM context enhancement)

#### Bug Fixes

##### Agent and Plugin System Fixes

*   **Agent Citations Cross-Conversation Contamination Fix**
    *   Fixed critical bug where agent citations leaked between different conversations due to global singleton logger returning all invocations without filtering.
    *   (Ref: `route_backend_chats.py`, plugin invocation logger filtering)

*   **Agent Citations Per-Message Isolation Fix**
    *   Resolved issue where agent citations accumulated across messages within the same conversation instead of being specific to each user interaction.
    *   (Ref: message-specific citation tracking, plugin logger timestamp filtering)

*   **Agents/Plugins Blueprint Registration Fix**
    *   Fixed registration issues with agent and plugin blueprints preventing proper initialization and route handling.
    *   (Ref: blueprint registration order, route conflicts resolution)

*   **Agent JavaScript Loading Error Fix**
    *   Resolved JavaScript loading errors in agent configuration interface that prevented proper agent management.
    *   (Ref: agent settings UI, JavaScript dependency loading)

*   **Agent Model Display Fixes**
    *   Fixed display issues with agent model selection and configuration in the admin interface.
    *   (Ref: model dropdown rendering, agent configuration UI)

*   **Plugin Duplication Bug Fix**
    *   Eliminated duplicate plugin registrations that caused conflicts and unexpected behavior in plugin execution.
    *   (Ref: plugin loader deduplication, registration tracking)

*   **Smart HTTP Plugin Citations Integration Fix**
    *   Added missing citation support for Smart HTTP Plugin calls to ensure consistent citation display across all plugin types.
    *   (Ref: `@plugin_function_logger` decorator integration, citation system uniformity)

*   **Smart HTTP Plugin Content Management Fix**
    *   Improved content handling and processing for Smart HTTP Plugin responses and data management.
    *   (Ref: HTTP response processing, content formatting)

*   **SQL Plugin Validation Fix**
    *   Enhanced SQL plugin input validation and error handling for safer database interactions.
    *   (Ref: SQL injection protection, query validation)

##### File Processing and Data Handling Fixes

*   **Tabular Data CSV Storage Optimization Fix**
    *   Replaced inefficient HTML table storage format with clean CSV format, reducing storage overhead by up to 50x and improving LLM processing efficiency.
    *   (Ref: CSV format preservation, token usage optimization)

*   **Tabular Data LLM Content Inclusion Fix**
    *   Improved integration of tabular data content into LLM context for better analytical capabilities.
    *   (Ref: content formatting, LLM context optimization)

*   **CSV Column Consistency Fix**
    *   Fixed DataTables errors caused by inconsistent column counts in CSV files by implementing column normalization.
    *   (Ref: DataTables compatibility, column padding)

*   **File Upload Executor Fix**
    *   Resolved file upload processing issues in the executor system for more reliable file handling.
    *   (Ref: upload pipeline, error handling)

*   **Document Upload Azure DI Fix**
    *   Fixed Azure Document Intelligence integration issues during document upload processing.
    *   (Ref: Azure DI parameter handling, document processing pipeline)

*   **Workspace Upload Conversation Fix**
    *   Resolved issues with file uploads not properly associating with conversations in workspace context.
    *   (Ref: conversation context preservation, file association)

##### Azure Integration Fixes

*   **Azure DI Parameter Fix**
    *   Corrected Azure Document Intelligence parameter handling and configuration issues.
    *   (Ref: DI service configuration, parameter validation)

*   **Azure Search Exception Handling Fix**
    *   Improved error handling for Azure Search operations with better user feedback and graceful degradation.
    *   (Ref: search service error handling, user notifications)

*   **AI Search Index Management and Agent Settings Fix**
    *   Fixed 404 errors when agents are disabled and improved AI Search index field checking with better error handling.
    *   (Ref: conditional loading, index management UI)

*   **Sovereign Cloud Managed Identity Authentication Fix**
    *   Fixed Document Intelligence, Content Safety, and AI Search client initialization issues when using Managed Identity in Government and custom cloud contexts.
    *   Implemented proper credential scopes, API versions, and audience specifications for sovereign cloud environments.
    *   (Ref: credential scope configuration, sovereign cloud authentication, RBAC requirements)

*   **Client Reinitialization on Settings Update Fix**
    *   Added automatic client reinitialization when admin settings are updated, eliminating need for application restart when changing authentication methods.
    *   (Ref: `route_frontend_admin_settings.py`, dynamic client management)

*   **Video Indexer Setup Walkthrough Fix**
    *   Updated Video Indexer settings validation to make API Key optional since the service now requires ARM authentication via Entra ID instead of API Key authentication.
    *   (Ref: setup walkthrough validation, ARM authentication requirements)

##### User Interface and Navigation Fixes

*   **Enhanced Citations PDF Modal Fix**
    *   Improved PDF display and interaction within citation modals for better document viewing experience.
    *   (Ref: PDF rendering, modal interface)

*   **Enhanced Citations Server-Side Rendering Fix**
    *   Fixed server-side rendering issues with citation display for improved performance and reliability.
    *   (Ref: SSR optimization, citation rendering)

*   **Conversation ID Display Fix**
    *   Resolved issues with conversation ID visibility and formatting in the user interface.
    *   (Ref: conversation metadata display, UI formatting)

*   **Navigation Menu Access Fix**
    *   Fixed navigation menu accessibility and functionality issues across different user roles and permissions.
    *   (Ref: menu rendering, permission handling)

*   **Sidebar Title Length Control Fix**
    *   Implemented proper title truncation and display control for sidebar conversation titles.
    *   (Ref: CSS text handling, title display)

*   **Find Group Modal Enhancements**
    *   Improved group discovery and selection modal functionality and user experience.
    *   (Ref: group search interface, modal interactions)

*   **Logging Tab UI Improvement**
    *   Enhanced logging interface display and functionality for better debugging and monitoring.
    *   (Ref: logging UI, tab interface improvements)

##### Permissions and Access Control Fixes

*   **Create Group Permission Display Fix**
    *   Fixed permission validation and display for group creation functionality based on user roles.
    *   (Ref: permission checking, UI conditional rendering)

*   **Create Public Workspace Permission Display Fix**
    *   Resolved permission display issues for public workspace creation based on admin settings and user roles.
    *   (Ref: workspace permissions, admin controls)

*   **Group API Error Handling Fix**
    *   Improved error handling and user feedback for group-related API operations.
    *   (Ref: API error responses, user notifications)

##### System and Performance Fixes

*   **Message Metadata Loading Fix**
    *   Resolved issues with message metadata loading and display in conversation interfaces.
    *   (Ref: metadata processing, conversation loading)

*   **Large API Response Enhancement**
    *   Improved handling of large API responses for better system stability and performance.
    *   (Ref: response processing, memory management)

*   **Large PDF Summarization Support**
    *   Enhanced PDF processing capabilities for large documents with improved chunking and summarization.
    *   (Ref: PDF processing pipeline, document chunking)

*   **PDF Processing Limits Optimization**
    *   Resolved inconsistent and overly restrictive PDF processing limits, aligning with Azure Document Intelligence's actual capabilities.
    *   (Ref: SmartHttpPlugin processing limits, Azure DI integration)

*   **Image Generation Model Compatibility Fix**
    *   Fixed compatibility issues with various image generation models and configurations.
    *   (Ref: model integration, image generation pipeline)

*   **Debug Logging Toggle Feature**
    *   Added configurable debug logging controls for better system monitoring and troubleshooting.
    *   (Ref: logging configuration, debug controls)

*   **Duplicate Logo Version Setting Fix**
    *   Removed duplicate `logo_version` setting in admin settings configuration to prevent configuration conflicts.
    *   (Ref: `route_frontend_admin_settings.py` line 389, configuration cleanup)

#### Breaking Changes

*   **Bing Web Search Removal**
    *   Removed all Bing Web Search functionality due to service deprecation by Microsoft. This includes:
        *   Removed `functions_bing_search.py` module
        *   Removed Bing configuration settings and UI elements
        *   Removed web search button from chat interface
        *   Removed Bing-related admin settings
        *   Updated documentation to remove Bing references
    *   **Impact**: Web search functionality is no longer available. Document search and other features remain fully functional.
    *   **Migration**: No action required - existing conversations and data are preserved.

### **(v0.215.36)**

#### New Features

*   **Bulk Uploader Utility**
    *   Introduced a command-line tool for batch uploading files mapped to users/groups via CSV. This dramatically reduces manual effort and errors during large-scale onboarding or migrations, making it easier for admins to populate the system with existing documents.  
        *   Includes: CLI, mapping CSV, and documentation.  
        *   (Ref: `application/external_apps/bulkloader/`)
*   **Database Seeder Utility**
    *   Added a utility to seed or overwrite CosmosDB admin settings from a JSON artifact. This ensures consistent, repeatable environment setup and simplifies configuration drift management across dev, test, and prod.  
        *   (Ref: `application/external_apps/databaseseeder/`)
*   **Redis Cache Support for Sessions**
    *   Full support for Azure Cache for Redis as a session backend. This enables true horizontal scaling and high availability for enterprise deployments, as user sessions are no longer tied to a single app instance.  
        *   Admin UI for configuration and connection testing.  
        *   (Ref: `app.py`, `route_backend_settings.py`, `admin_settings.html`)
*   **Comprehensive Private Endpoint & Enterprise Network Documentation**
    *   Added a detailed section and architecture diagram to the README covering Private Endpoints, Virtual Networks, Private DNS Zones, and secure enterprise network deployment. This guidance helps organizations implement best practices for network isolation, compliance, and secure Azure PaaS integration.
*   **Custom Azure Environment Support**
    *   Added support for "custom" Azure environments, allowing deployment in sovereign or private clouds with non-standard endpoints. This increases flexibility for government, regulated, or air-gapped scenarios.
        *   (Ref: `config.py`)
*   **Admin Setting: Use Local File for Document Intelligence Testing**
    *   The Document Intelligence test now uses a local test file, making it easier to validate configuration without relying on external URLs or network access.  
        *   (Ref: `route_backend_settings.py`)
*   **Support for Azure File Share as Temp Storage**
    *   File uploads can now use an Azure File Share mount (`/sc-temp-files`) for temporary storage, improving performance and scalability for large files or distributed deployments.  
        *   (Ref: `route_backend_documents.py`)
*   **Custom Favicon Support**
    *   Admins can upload a custom favicon (PNG/JPG/ICO) via the admin UI, allowing organizations to brand the application for their users.  
        *   (Ref: `route_frontend_admin_settings.py`, `admin_settings.html`, `config.py`, `base.html`)
*   **Show/Hide Application Title Independently of Logo**
    *   New admin setting to hide the app title in the navbar, even if the logo is shown. This provides more control over branding and UI layout.  
        *   (Ref: `route_frontend_admin_settings.py`, `admin_settings.html`, `base.html`)
*   **Multi-Conversation Delete**
    *   Users can now select and delete multiple conversations at once in the chat UI, streamlining cleanup and improving user productivity.  
        *   (Ref: `route_backend_conversations.py`, `chat-conversations.js`, `chats.html`)
*   **Markdown Alignment Setting for Index Page**
    *   Admins can set the alignment (left/center/right) of the landing page markdown, supporting more flexible and visually appealing home pages.  
        *   (Ref: `route_frontend_admin_settings.py`, `admin_settings.html`, `index.html`)
*   **Added Group.Read.All to Documentation**
    *   The README now documents the need for Group.Read.All permission for group workspaces, reducing confusion during setup.  
        *   (Ref: `README.md`)
*   **New Infrastructure-as-Code Deployers**
    *   Added Bicep, Terraform, and Azure CLI deployers, making it easier for organizations to automate and standardize deployments in CI/CD pipelines.  
        *   (Ref: `deployers/`)
*   **Architecture Diagram Update**
    *   Updated architecture.vsdx to include Redis cache, reflecting the new scalable architecture for documentation and planning.  
        *   (Ref: `artifacts/architecture.vsdx`)
*   **Health Check**
    *   Provide admins ability to enable a healthcheck api.
    *  (Ref: `route_external_health.py`)

#### Bug Fixes

*   **Improved Code Snippet Readability in Dark Mode**
    *   Code blocks now have better background and text color contrast, making them easier to read for all users, especially in accessibility scenarios.  
        *   (Ref: `chats.css`)
*   **Improved File Link Contrast in Dark Mode**
    *   File links in chat messages are now more visible in dark mode, reducing user frustration and improving accessibility.  
        *   (Ref: `chats.css`)
*   **Prevented Chat When Embedding Fails**
    *   The system now returns a clear error if embedding fails, preventing users from sending messages that would be lost or cause confusion. This improves reliability and user trust.  
        *   (Ref: `route_backend_chats.py`, `chat-messages.js`, `workspace-documents.js`)
*   **Resolved Document Classification Bug**
    *   Fixed issues where document classification was not updating or displaying correctly, ensuring that document metadata is always accurate and actionable.  
        *   (Ref: `chat-documents.js`)
*   **Fixed Prompt Input Field Display Bug**
    *   Resolved a UI bug where prompt text only appeared when clicking on the input field, improving usability for prompt editing.  
        *   (Ref: `workspace-prompts.js`)
*   **Repaired Search in Workspaces**
    *   Fixed search and filter logic in workspace and group workspace document lists, so users can reliably find documents by metadata or keywords.  
        *   (Ref: `workspace-documents.js`, `workspace.html`, `group_workspaces.html`)
*   **Restored System Prompt in Chat Workflow**
    *   Ensures the default system prompt is always included in the chat history if not present, maintaining intended conversation context and behavior.  
        *   (Ref: `route_backend_chats.py`)
*   **Improved Author/Keyword Filter Logic**
    *   Filters for authors and keywords now use case-insensitive substring matching, making search more intuitive and forgiving for users.  
        *   (Ref: `route_backend_documents.py`, `route_backend_group_documents.py`)
*   **Removed Test Files from Bulk Uploader**
    *   Cleaned up test files from the bulk uploader app, reducing clutter and potential confusion for new users.  
        *   (Ref: `bulkloader/`)
*   **Updated Dockerfile to Use Chainguard Images**
    *   Switched to Chainguard Python images for improved security and reduced CVEs, aligning with best practices for container hardening.  
        *   (Ref: `Dockerfile`)
*   **Changed Base Image to Reduce CVEs**
    *   Updated the base image to further reduce vulnerabilities, supporting compliance and security requirements.  
        *   (Ref: `Dockerfile`)
*   **Other Minor UI/UX and Documentation Fixes**
    *   Various small improvements and typo fixes across admin UI, documentation, and error handling, contributing to a more polished and reliable user experience.

# Feature Release

### **(v0.214.001)**

#### New Features

*   **Dark Mode Support**
    *   Added full dark mode theming with support for:
        *   Chat interface (left and right panes)
        *   File metadata panels
        *   Dropdowns, headers, buttons, and classification tables
    *   User preferences persist across sessions.
    *   Dark mode toggle in navbar with text labels and styling fixes (no flash during navigation).
*   **Admin Management Enhancements**
    *   **First-Time Configuration Wizard**: Introduced a guided setup wizard on the Admin Settings page. This wizard simplifies the initial configuration process for application basics (title, logo), GPT API settings, workspace settings, additional services (Embedding, AI Search, Document Intelligence), and optional features. (Ref: `README.md`, `admin_settings.js`, `admin_settings.html`)
    *   Admin Settings UI updated to show application version check status, comparing against the latest GitHub release. (Ref: `route_frontend_admin_settings.py`, `admin_settings.html`)
    *   Added `logout_hint` parameter to resolve multi-identity logout errors.
    *   Updated favicon and admin settings layout for improved clarity and usability.
*   **UI Banner & Visual Updates**
    *   **Enhanced Document Dropdown (Chat Interface)**: The document selection dropdown in the chat interface has been significantly improved:
        *   Increased width and scrollability for better handling of numerous documents.
        *   Client-side search/filter functionality added to quickly find documents.
        *   Improved visual feedback, including a "no matches found" message. (Ref: `chats.css`, `chat-documents.js`, `chats.html`)
    *   New top-of-page banner added (configurable).
    *   Local CSS/JS used across admin, group, and user workspaces for consistency and performance.
    *   Updated `base.html` and `workspace.html` to reflect visual improvements.
*   **Application Setup & Configuration**
    *   **Automatic Storage Container Creation**: The application now attempts to automatically create the `user-documents` and `group-documents` Azure Storage containers during initialization if they are not found, provided "Enhanced Citations" are enabled and a valid storage connection string is configured. Manual creation as per documentation is still the recommended primary approach. (Ref: `config.py`)
    *   Updated documentation for Azure Storage Account setup, including guidance for the new First-Time Configuration Wizard. (Ref: `README.md`)
*   **Security Improvements**
    *   Implemented `X-Content-Type-Options: nosniff` header to mitigate MIME sniffing vulnerabilities.
    *   Enhanced security for loading AI Search index schema JSON files by implementing path validation and using `secure_filename` in backend settings. (Ref: `route_backend_settings.py`)
*   **Build & Deployment**
    *   Added `docker_image_publish_dev.yml` GitHub Action workflow for publishing dev Docker images.
    *   Updated Dockerfile to use Python 3.12.
*   **Version Enforcement**
    *   GitHub workflow `enforce-dev-to-main.yml` added to prevent pull requests to `main` unless from `development`.

#### Bug Fixes

*   **A. Document Processing**
    *   **Document Deletion**: Resolved an issue where documents were not properly deleted from Azure Blob Storage. Now, when a document is deleted from the application, its corresponding blob is also removed from the `user-documents` or `group-documents` container if enhanced citations are enabled. (Ref: `functions_documents.py`)
    *   **Configuration Validation (Enhanced Citations)**: Added validation in Admin Settings to ensure that if "Enhanced Citations" is enabled, the "Office Docs Storage Account Connection String" is also provided. If the connection string is missing, Enhanced Citations will be automatically disabled, and a warning message will be displayed to the admin, preventing silent failures. (Ref: `route_frontend_admin_settings.py`)
*   **C. UI & Usability**
    *   **Local Assets for SimpleMDE**: The SimpleMDE Markdown editor assets (JS/CSS) are now served locally from `/static/js/simplemde/` and `/static/css/simplemde.min.css` instead of a CDN. This improves page load times, reduces external dependencies, and allows for use in offline or air-gapped environments. (Ref: `simplemde.min.js`, `simplemde.min.css` additions, template updates in `group_workspaces.html`, `workspace.html`)
    *   General CSS cleanups across admin and workspace UIs.
*   **D. General Stability**
    *   Merged contributions from multiple devs including UI fixes, backend updates, and config changes.
    *   Removed unused video/audio container declarations for a leaner frontend.

### **(v0.213.001)**

#### New Features

1. **Dark Mode Support**
   - Added full dark mode theming with support for:
     - Chat interface (left and right panes)
     - File metadata panels
     - Dropdowns, headers, buttons, and classification tables
   - User preferences persist across sessions.
   - Dark mode toggle in navbar with text labels and styling fixes (no flash during navigation).
2. **Admin Management Enhancements**
   - Admin Settings UI updated to show version check.
   - Added logout_hint parameter to resolve multi-identity logout errors.
   - Updated favicon and admin settings layout for improved clarity and usability.
3. **UI Banner & Visual Updates**
   - New top-of-page banner added (configurable).
   - Local CSS/JS used across admin, group, and user workspaces for consistency and performance.
   - Updated `base.html` and `workspace.html` to reflect visual improvements.
4. **Security Improvements**
   - Implemented `X-Content-Type-Options: nosniff` header to mitigate MIME sniffing vulnerabilities.
5. **Build & Deployment**
   - Added `docker_image_publish_dev.yml` GitHub Action workflow for publishing dev Docker images.
   - Updated Dockerfile to use **Python 3.12**.
6. **Version Enforcement**
   - GitHub workflow `enforce-dev-to-main.yml` added to prevent pull requests to `main` unless from `development`.

#### Bug Fixes

A. **Document Processing**

- Resolved document deletion error.

C. **UI & Usability**

- Local assets now used for JS/CSS to improve load times and offline compatibility.
- General CSS cleanups across admin and workspace UIs.

D. **General Stability**

- Merged contributions from multiple devs including UI fixes, backend updates, and config changes.
- Removed unused video/audio container declarations for a leaner frontend.

## (v0.212.79)

### New Features

#### 1. Audio & Video Processing

- **Audio processing pipeline**
  - Integrated Azure Speech transcriptions into document ingestion.
  - Splits transcripts into ~400-word chunks for downstream indexing.
- **Video Indexer settings UI**
  - Added input fields in Admin Settings for Video Indexer endpoint, key and locale.

#### 2. Multi-Model Support

- Users may choose from **multiple OpenAI deployments** at runtime.
- Model list is dynamically populated based on Admin settings (including APIM).

#### 3. Advanced Chunking Logic

- **PDF & PPTX**: page-based chunks via Document Intelligence.
- **DOC/DOCX**: ~400-word chunks via Document Intelligence.
- **Images** (jpg/jpeg/png/bmp/tiff/tif/heif): single-chunk OCR.
- **Plain Text (.txt)**: ~400-word chunks.
- **HTML**: hierarchical H1–H5 splits with table rebuilding, 600–1200-word sizing.
- **Markdown (.md)**: header-based splitting, table & code-block integrity, 600–1200-word sizing.
- **JSON**: `RecursiveJsonSplitter` w/ `convert_lists=True`, `max_chunk_size=600`.
- **Tabular (CSV/XLSX/XLS)**: pandas-driven row chunks (≤800 chars + header), sheets as separate files, formulas stripped.

#### 4. Group Workspace Consolidation

- Unified all group document logic into `functions_documents.js`.
- Removed `functions_group_documents.js` duplication.

#### 5. Bulk File Uploads

- Support for uploading **up to 10 files** in a single operation, with parallel ingestion and processing.

#### 6. GPT-Driven Metadata Extraction

- Admins can select a **GPT model** to power metadata parsing.
- All new documents are processed through the chosen model for entity, keyword, and summary extraction.

#### 7. Advanced Document Classification

- Admin-configurable classification fields, each with **custom color-coded labels**.
- Classification metadata persisted per document for filtering and display.

#### 8. Contextual Classification Propagation

- When a classified document is referenced in chat, its tags are **automatically applied to the conversation** as contextual metadata.

#### 9. Chat UI Enhancements

- **Left-docked** conversation menu for persistent navigation.
- **Editable** conversation titles inline (left & right panes stay in sync).
- Streamlined **new chat** flow: click-to-start or type-to-auto-create.
- **User-defined prompts** surfaced inline within the message input.

#### 10. Semantic Reranking & Extractive Answers

* Switched to semantic queries (`query_type="semantic"`) on both user and group indexes. 
* Enabled extractive highlights (`query_caption="extractive"`) to surface the most relevant snippet in each hit.  
* Enabled extractive answers (`query_answer="extractive"`) so the engine returns a concise, context-rich response directly from the index.  
* Automatically falls back to full-text search (`query_type="full"`, `search_mode="all"`) whenever no literal match is found, ensuring precise retrieval of references or other exact phrases.

### Bug Fixes

#### A. AI Search Index Migration

- Automatically add any **missing** fields (e.g. `author`, `chunk_keywords`, `document_classification`, `page_number`, `start_time`, `video_ocr_chunk_text`, etc.) on every Admin page load.
- Fixed SDK usage (`Collection` attribute) to update index schema without full-index replacement.

#### B. User & Group Management

- **User search 401 error** when adding a new user to a group resolved by:
  - Implementing `SerializableTokenCache` in MSAL tied to Flask session.
  - Ensuring `_save_cache()` is called after `acquire_token_by_authorization_code`.
  - Refactoring `get_valid_access_token()` to use `acquire_token_silent()`.
- Restored **metadata extraction** & **classification** buttons in Group Workspace.
- Fixed new role language in Admin settings and published an OpenAPI spec for `/api/`.

#### C. Conversation Flow & UI

- **Auto-create** a new conversation on first user input, prompt selection or file upload.
- **Custom logo persistence** across reboots via Base64 storage in Cosmos (max 100 px height, ≤ 500 KB).
- Prevent uploaded files from **overflowing** the chat window (CSS update).
- Sync conversation title in left pane **without** manual refresh.
- Restore missing `loadConversations()` in `chat-input-actions.js`.
- Fix feedback button behavior and ensure prompt selection sends full content.
- Include original `search_query` & `user_message` in AI Search telemetry.
- Ensure existing documents no longer appear “Not Available” by populating `percent_complete`.
- Support **Unicode** (e.g. Japanese) in text-file chunking.

#### D. Miscellaneous Fixes

- **Error uploading file** (`loadConversations is not defined`) fixed.
- **Classification disabled** no longer displays in documents list or title.
- **Select prompt/upload file** now always creates a conversation if none exists.
- **Fix new categories** error by seeding missing nested settings with defaults on startup.



### Breaking Changes & Migration Notes

- **Index schema** must be re-migrated via Admin Settings (admin initiates in the app settings page).

## (v0.203.15)

The update introduces "Workspaces," allowing users and groups to store both **documents** and **custom prompts** in a shared context. A new **prompt selection** feature enhances the chat workflow for a smoother experience. Additionally, admin configuration has been streamlined, and the landing page editor now supports improved Markdown formatting.

#### 1. Renaming Documents to Workspaces

- **Your Documents** → **Your Workspace**
- **Group Documents** → **Group Workspaces**
- All references, routes, and templates updated (`documents.html` → `workspace.html`, `group_documents.html` → `group_workspaces.html`).
- New admin settings flags: `enable_user_workspace` and `enable_group_workspaces` replaced the old `enable_user_documents` / `enable_group_documents`.

#### 2. Custom Prompt Support

- User Prompts:
  - New backend routes in `route_backend_prompts.py` (CRUD for user-specific prompts).
- Group Prompts:
  - New backend routes in `route_backend_group_prompts.py` (CRUD for group-shared prompts).

#### 3. Chat Page Enhancements

- Prompt Selection Dropdown:
  - New button (“Prompts”) toggles a dropdown for selecting saved user/group prompts.
  - Eliminates copy-paste; helps users insert larger or more complex prompts quickly.
  - Lays groundwork for future workflow automation.
- **Toast Notifications** for errors and status messages (replacing browser alerts).

#### 4. Cosmos Containers

- Added `prompts_container` and `group_prompts_container`.

- **Simplified** or standardized the container creation logic in `config.py`.

## (v0.202.41)

- **Azure Government Support**:

  - Introduced an `AZURE_ENVIRONMENT` variable (e.g. `"public"` or `"usgovernment"`) and logic to handle separate authority hosts, resource managers, and credential scopes.

  ```
  # Azure Cosmos DB
  AZURE_COSMOS_ENDPOINT="<your-cosmosdb-endpoint>"
  AZURE_COSMOS_KEY="<your-cosmosdb-key>"
  AZURE_COSMOS_AUTHENTICATION_TYPE="key" # key or managed_identity
  
  # Azure AD Authentication
  CLIENT_ID="<your-client-id>"
  TENANT_ID="<your-tenant-id>"
  AZURE_ENVIRONMENT="public" #public, usgovernment
  SECRET_KEY="32-characters" # Example - "YouSh0uldGener8teYour0wnSecr3tKey!", import secrets; print(secrets.token_urlsafe(32))
  ```

- **Admin Settings Overhaul**:

  - **Route & UI**: Added `route_backend_settings.py` and significantly expanded `admin_settings.html` to configure GPT, Embeddings, Image Gen, Content Safety, AI Search, and Document Intelligence—all from a single Admin page.
  - **APIM Toggles**: Each service (GPT, Embeddings, Image Generation, Content Safety, etc.) can now be routed through Azure API Management instead of direct endpoints by switching a toggle.
  - **“Test Connection” Buttons**: Each service (GPT, Embeddings, Image Generation, Content Safety, Azure AI Search, and Document Intelligence) now has a dedicated “Test Connection” button that performs a live connectivity check.

- **Improved Safety Features**:

  - New pages/sections for “Admin Safety Violations” vs. “My Safety Violations.”

- **Miscellaneous Frontend & Template Updates**:

  - All templates now reference an `app_settings.app_title` for a dynamic page title.
  - Enhanced navigation and labeling in “My Documents,” “My Groups,” and “Profile” pages.

### Bug Fixes

- **Conversation Pipeline**:
  - Removed the `"image"` role from the allowed conversation roles to streamline message handling.
- **Group Management**:
  - Now correctly passes and references the current user’s ID in various group actions.

## (v0.201.5)

#### 1. **Managed Identity Support**

- Azure Cosmos DB (enabled/disabled via environment variable)
- Azure Document Intelligence (enabled/disabled via app settings)
- Azure AI Search (enabled/disabled via app settings)
- Azure OpenAI (enabled/disabled via app settings)

#### 2. **Conversation Archiving**

- Introduced a new setting 

  ```
  enable_conversation_archiving
  ```

  - When enabled, deleting a conversation will first copy (archive) the conversation document into an `archived_conversations_container` before removing it from the main `conversations` container.
  - Helps preserve conversation history if you want to restore or analyze it later.

#### 3. **Configuration & Environment Variable Updates**

- `example.env` & `example_advance_edit_environment_variables.json`:
  - Added `AZURE_COSMOS_AUTHENTICATION_TYPE` to demonstrate how to switch between `key`-based or `managed_identity`-based authentication.
  - Cleaned up references to Azure AI Search and Azure Document Intelligence environment variables to reduce clutter and reflect the new approach of toggling authentication modes.
- Default Settings Updates
  - `functions_settings.py` has more descriptive defaults covering GPT, Embeddings, and Image Generation for both key-based and managed identity scenarios.
  - New config fields such as `content_safety_authentication_type`, `azure_document_intelligence_authentication_type`, and `enable_conversation_archiving`.

#### 6. **Bug Fixes**

- Fixed bug affecting the ability to manage groups
  - Renamed or refactored `manage_groups.js` to `manage_group.js`, and updated the template (`manage_group.html`) to use the new filename.
  - Injected `groupId` directly via Jinja for improved client-side handling.

#### 7. **Architecture Diagram Updates**

- Updated `architecture.vsdx` and `architecture.png` to align with the new authentication flow and container usage.

------

#### How to Use / Test the New Features

1. **Enable Managed Identity**
   - In your `.env` or Azure App Service settings, set `AZURE_COSMOS_AUTHENTICATION_TYPE="managed_identity"` (and similarly for `azure_document_intelligence_authentication_type`, etc.).
   - Ensure the Azure resource (e.g., App Service, VM) has a system- or user-assigned Managed Identity with the correct roles (e.g., “Cosmos DB Account Contributor”).
   - Deploy, and the application will now connect to Azure resources without storing any keys in configuration.
2. **Test Conversation Archiving**
   - In the Admin Settings, enable `Enable Conversation Archiving`.
   - Delete a conversation.
   - Verify the record is copied to `archived_conversations_container` before being removed from the active container.
3. **Check New Environment Variables**
   - Review `example.env` and `example_advance_edit_environment_variables.json` for the newly added variables.
   - Update your application settings in Azure or your local `.env` accordingly to test various authentication modes (key vs. managed identity).

## (V0.199.3)

We introduced a robust user feedback system, expanded content-safety features for both admins and end users, added new Cosmos DB containers, and refined route-level permission toggles. These changes help administrators collect feedback on AI responses, manage content safety more seamlessly, and give end users clearer ways to manage their documents, groups, and personal logs. Enjoy the new functionality, and let us know if you have any questions or issues!

1. **New “User Feedback” System**
   - **Thumbs Up / Thumbs Down**: Users can now provide feedback on individual AI responses (when enabled in App Settings)
   - **Frontend Feedback Pages**:
     - **/my_feedback** page shows each user’s submitted feedback.
     - **/admin/feedback_review** page allows admins to review, filter, and manage all feedback.
2. **Extended Content Safety Features**
   - **New “Safety Violations” Page**: Admins can manage safety violations.
   - **New “My Safety Violations” Page**: Users can view their violations and add personal notes to each violation.
3. **New or Updated Database Containers**
   - feedback_container for user feedback.
   - archived_conversations_container / archived_feedback_container / archived_safety_container for long-term archival.
4. **Route-Level Feature Toggles**
   - **enabled_required(setting_key) Decorator**:
     - Dynamically block or allow routes based on an admin setting (e.g., enable_user_documents or enable_group_documents).
     - Reduces scattered if checks; you simply annotate the route.
5. **Conversation & Messaging Improvements**
   - **Unique message_id for Each Chat Message**:
     - Every user, assistant, safety, or image message now includes a message_id.
     - Makes it easier to tie user feedback or safety logs to a specific message.
   - **Public vs. Secret Settings**:
     - Frontend references a public_settings = sanitize_settings_for_user(settings) to avoid the potential to expose secrets on the client side.
6. **UI/UX Tweaks**
   - **Chat Layout Updates**:
     - “Start typing to create a new conversation…” message if none selected.
     - Automatic creation of new conversation when user tries to send a message with no active conversation.
   - **Navigation Bar Adjustments**:
     - Consolidated admin links into a dropdown.
     - “My Account” dropdown for quick access to “My Groups,” “My Feedback,” etc., if enabled.

## (v0.196.9)

1. **Content Safety Integration**
   - **New Safety Tab in Admin Settings**: A dedicated “Safety” section now appears under Admin Settings, allowing you to enable Azure Content Safety, configure its endpoint and key, and test connectivity.
   - **Real-Time Message Scanning**: If Content Safety is enabled, user prompts are scanned for potentially disallowed content. Blocked messages are flagged and a “safety” message is added to the conversation log in place of a normal AI reply.
   - **Admin Safety Logs**: Site admins (with “Admin” role) can view a new “Safety Violations” page (at /admin/safety_violations) showing blocked or flagged messages. Admins can update the status, action taken, or notes on each violation.
2. **Expanded APIM Support for GPT, Embeddings, and Image Generation**
   - **Fine-Grained APIM Toggles**: You can now enable or disable APIM usage independently for GPT, embeddings, and image generation. Each service has its own APIM endpoint, version, and subscription key fields in Admin Settings.
   - **UI-Driven Switching**: Check/uncheck “Enable APIM” to toggle between native Azure OpenAI endpoints or APIM-managed endpoints, all without redeploying the app.
3. **Workspaces & Documents Configuration**
   - **User Documents and Group Documents**: A new “Workspaces” tab in Admin Settings (replacing the old “Web Search” tab) lets you enable or disable user-specific documents and group-based documents.
   - **Group Documents Page**: The front-end for Group Documents now checks whether “Enable My Groups” is turned on. If enabled, members can manage shared group files and see group-level search results.
   - **My Groups & Group Management**: Navigation includes “My Groups” (if group features are enabled). This leads to a new set of pages for viewing groups, managing memberships, transferring ownership, and more.
4. **Search & Extract Tab**
   - **Azure AI Search & Document Intelligence**: Azure AI Search, and Azure Document Intelligence settings into a new “Search and Extract” tab (replacing the older “Web Search” tab).
   - **Azure Document Intelligence**: Configure endpoints and keys for file ingestion (OCR, form analysis, etc.) in a more structured place within Admin Settings.
5. **Updated UI & Navigation**
   - **Admin Dropdown**: Admin-specific features (App Settings, Safety Violations, etc.) are grouped in an “Admin” dropdown on the main navbar.
   - **Safety**: For Content Safety (as noted above).
   - **Search & Extract**: For Azure AI Search, and Document Intelligence.
   - **Minor Styling Adjustments**: Updated top navbar to show/hide “Groups” or “Documents” links based on new toggles (Enable Your Documents, Enable My Groups).

## (v0.191.0)

1. **Azure API Management (APIM) Support**  
   - **New APIM Toggles**: In the Admin Settings, you can now enable or disable APIM usage separately for GPT, embeddings, and image generation.  
   - **APIM Endpoints & Subscription Keys**: For each AI service (GPT, Embeddings, Image Generation), you can specify an APIM endpoint, version, deployment, and subscription key—allowing a unified API gateway approach (e.g., rate limiting, authentication) without changing your core service code.  
   - **Seamless Switching**: A single checkbox (`Enable APIM`) within each tab (GPT, Embeddings, Image Generation) instantly switches the app between native Azure endpoints and APIM-protected endpoints, with no redeployment required.

2. **Enhanced Admin Settings UI**  
   - **Advanced Fields**: Collapsible “Show Advanced” sections for GPT, Embeddings, and Image Generation let you configure API versions or other fine-tuning details only when needed.  
   - **Test Connectivity**: Each service tab (GPT, Embeddings, Image Gen) now has a dedicated “Test Connection” button, providing immediate feedback on whether your settings and credentials are valid.  
   - **Improved UX for Keys**: Updated show/hide password toggles for all key fields (including APIM subscription keys), making it easier to confirm you’ve entered credentials correctly.

3. **Miscellaneous Improvements**  
   - **UI Polishing**: Minor styling updates and improved tooltips in Admin Settings to guide first-time users.  
   - **Performance Tweaks**: Reduced initial load time for the Admin Settings page when large model lists are returned from the OpenAI endpoints.  
   - **Logging & Error Handling**: More descriptive error messages and client-side alerts for failed fetches (e.g., if the user tries to fetch GPT models but hasn’t set the endpoint properly).

## v0.191.0

1. **Azure API Management (APIM) Support**  
   - **New APIM Toggles**: In the Admin Settings, you can now enable or disable APIM usage separately for GPT, embeddings, and image generation.  
   - **APIM Endpoints & Subscription Keys**: For each AI service (GPT, Embeddings, Image Generation), you can specify an APIM endpoint, version, deployment, and subscription key—allowing a unified API gateway approach (e.g., rate limiting, authentication) without changing your core service code.  
   - **Seamless Switching**: A single checkbox (`Enable APIM`) within each tab (GPT, Embeddings, Image Generation) instantly switches the app between native Azure endpoints and APIM-protected endpoints, with no redeployment required.

2. **Enhanced Admin Settings UI**  
   - **Advanced Fields**: Collapsible “Show Advanced” sections for GPT, Embeddings, and Image Generation let you configure API versions or other fine-tuning details only when needed.  
   - **Test Connectivity**: Each service tab (GPT, Embeddings, Image Gen) now has a dedicated “Test Connection” button, providing immediate feedback on whether your settings and credentials are valid.  
   - **Improved UX for Keys**: Updated show/hide password toggles for all key fields (including APIM subscription keys), making it easier to confirm you’ve entered credentials correctly.

3. **Miscellaneous Improvements**  
   - **UI Polishing**: Minor styling updates and improved tooltips in Admin Settings to guide first-time users.  
   - **Performance Tweaks**: Reduced initial load time for the Admin Settings page when large model lists are returned from the OpenAI endpoints.  
   - **Logging & Error Handling**: More descriptive error messages and client-side alerts for failed fetches (e.g., if the user tries to fetch GPT models but hasn’t set the endpoint properly).

## v0.190.1

1. **Admin Settings UI**  
   - Configure Azure OpenAI GPT, Embeddings, and Image Generation settings directly through an in-app interface (rather than `.env`).  
   - Choose between **key-based** or **managed identity** authentication for GPT, Embeddings, and Image Generation.  
   - Dynamically switch models/deployments without redeploying the app.

2. **Multiple Roles & Group Permissions**  
   - Roles include `Owner`, `Admin`, `DocumentManager`, and `User`.  
   - Group Owners/Admins can invite or remove members, manage documents, and set “active workspace” for group-based search.

3. **One-Click Switching of Active Group**  
   - Users in multiple groups can quickly switch their active group to see group-specific documents and chat references.

4. **Ephemeral Document Upload**  
   - Upload a file for a single conversation. The file is not saved in Azure Cognitive Search; instead, it is only used for the session’s RAG context.

5. **Inline File Previews in Chat**  
   - Files attached to a conversation can be previewed directly from the chat, with text or data displayed in a pop-up.

7. **Optional Image Generation**  
   - Users can toggle an “Image” button to create images via Azure OpenAI (e.g., DALL·E) when configured in Admin Settings.

8. **App Roles & Enterprise Application**  
   - Provides a robust way to control user access at scale.  
   - Admins can assign roles to new users or entire Azure AD groups.