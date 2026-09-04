# admin_settings_nav.py
"""Single source of truth for the Admin Settings navigation.

The top tab strip and the sidebar previously maintained the same
structure twice, by hand, and had already drifted: tab order differed
between them and three tabs carried different labels in each. Both now
render from this one definition, so they cannot disagree.

Structure is GROUP -> TAB -> SECTION. A section points at a card id in
the rendered page; card ids are stable and are what cross-references
resolve against, so cards can move between tabs without breaking links.
"""


ADMIN_NAV = [
    {
        "id": "appearance",
        "label": "Appearance",
        "icon": "bi-palette",
        "tabs": [
            {
                "id": "branding",
                "label": "Branding",
                "icon": "bi-palette",
                "sections": [
                    {"id": "branding-section", "label": "Branding", "icon": "bi-palette"},
                    {"id": "home-page-text-section", "label": "Home Page Text", "icon": "bi-house"},
                    {"id": "appearance-section", "label": "Appearance", "icon": "bi-brush"},
                ],
            },
            {
                # Everything the app states to the user before or during use:
                # banners, notices and the agreements they must accept.
                "id": "notices",
                "label": "Notices & Agreements",
                "icon": "bi-megaphone",
                "sections": [
                    {"id": "classification-banner-section", "label": "Classification Banner", "icon": "bi-shield-exclamation"},
                    {"id": "ai-notice-section", "label": "Chat AI Notice", "icon": "bi-robot"},
                    {"id": "terms-of-use-section", "label": "Terms of Use", "icon": "bi-door-open"},
                    {"id": "user-agreement-section", "label": "User Agreement", "icon": "bi-file-earmark-check"},
                ],
            },
            {
                "id": "custom-pages",
                "label": "Pages & Links",
                "icon": "bi-window-plus",
                "sections": [
                    {"id": "custom-pages-section", "label": "Static Pages", "icon": "bi-file-earmark-richtext"},
                    {"id": "external-links-section", "label": "External Links", "icon": "bi-box-arrow-up-right"},
                ],
            },
        ],
    },
    {
        "id": "chat",
        "label": "Chat",
        "icon": "bi-chat-square-text",
        "tabs": [
            {
                "id": "chat-experience",
                "label": "Chat Experience",
                "icon": "bi-chat-square-dots",
                "sections": [
                    {"id": "processing-thoughts-section", "label": "Processing Thoughts", "icon": "bi-stars"},
                    {"id": "chat-file-uploads-section", "label": "Chat File Uploads", "icon": "bi-paperclip"},
                    {"id": "conversation-contents-drawer-section", "label": "Conversation Contents Drawer", "icon": "bi-list-nested"},
                    {"id": "workspace-scope-lock-section", "label": "Workspace Scope Lock", "icon": "bi-lock"},
                    {"id": "conversation-history-section", "label": "Conversation History", "icon": "bi-clock-history"},
                    {"id": "default-system-prompt-section", "label": "Default System Prompt", "icon": "bi-chat-square-quote"},
                    {"id": "fact-memory-section", "label": "Fact Memory", "icon": "bi-journal-text"},
                ],
            },
            {
                "id": "feedback-alerts",
                "label": "Feedback & Alerts",
                "icon": "bi-chat-square-heart",
                "sections": [
                    {"id": "user-feedback-section", "label": "User Feedback", "icon": "bi-chat-square-heart"},
                    {"id": "desktop-notifications-section", "label": "Desktop Conversation Notifications", "icon": "bi-bell"},
                ],
            },
            {
                "id": "citation",
                "label": "Citations",
                "icon": "bi-quote",
                "sections": [
                    {"id": "standard-citations-section", "label": "Standard", "icon": "bi-quote"},
                    {"id": "enhanced-citations-section", "label": "Enhanced", "icon": "bi-star"},
                ],
            },
        ],
    },
    {
        "id": "ai-models",
        "label": "AI Models",
        "icon": "bi-cpu",
        "tabs": [
            {
                # The Chat Model card is reached through the legacy model
                # settings dialog opened from here, so it is listed with the
                # endpoints rather than as a tab of its own.
                "id": "model-endpoints",
                "label": "Model Endpoints",
                "icon": "bi-hdd-network",
                "sections": [
                    {"id": "multi-endpoint-configuration", "label": "Model Endpoints", "icon": "bi-hdd-network"},
                    {"id": "gpt-config", "label": "Chat Model", "icon": "bi-chat-square-text"},
                ],
            },
            {
                "id": "embeddings",
                "label": "Embeddings",
                "icon": "bi-vector-pen",
                "sections": [
                    {"id": "embeddings-config", "label": "Embeddings", "icon": "bi-vector-pen"},
                ],
            },
            {
                "id": "image-generation",
                "label": "Image Generation",
                "icon": "bi-image",
                "sections": [
                    {"id": "image-config", "label": "Image Generation", "icon": "bi-image"},
                ],
            },
        ],
    },
    {
        "id": "agents-actions",
        "label": "Agents & Actions",
        "icon": "bi-robot",
        "tabs": [
            {
                "id": "agents",
                "label": "Agents",
                "icon": "bi-robot",
                "sections": [
                    {"id": "agents-config", "label": "Agents Configuration", "icon": "bi-robot"},
                    {"id": "agent-template-approvals-section", "label": "Agent Template Approvals", "icon": "bi-layers", "condition": "enable_agent_template_gallery"},
                ],
            },
            {
                "id": "actions",
                "label": "Actions",
                "icon": "bi-plugin",
                "sections": [
                    {"id": "document-action-capabilities-card", "label": "Document Action Capabilities", "icon": "bi-files"},
                    {"id": "actions-config", "label": "Actions Configuration", "icon": "bi-plugin"},
                ],
            },
            {
                # Keep the tab visible when the preview UI gate is off so admins
                # can see how to enable the required App Service setting.
                "id": "inbound-mcp",
                "label": "Inbound MCP",
                "icon": "bi-diagram-3",
                "sections": [
                    {"id": "inbound-mcp-configuration", "label": "Inbound MCP", "icon": "bi-diagram-3"},
                ],
            },
        ],
    },
    {
        "id": "workspaces",
        "label": "Workspaces",
        "icon": "bi-folder",
        "tabs": [
            {
                "id": "workspace-types",
                "label": "Workspace Types",
                "icon": "bi-folder",
                "sections": [
                    {"id": "personal-workspaces-section", "label": "Personal Workspaces", "icon": "bi-person"},
                    {"id": "group-workspaces-section", "label": "Group Workspaces", "icon": "bi-people"},
                    {"id": "public-workspaces-section", "label": "Public Workspaces", "icon": "bi-globe"},
                ],
            },
            {
                # Who may take a file out of a workspace, and who must approve
                # it first.
                "id": "files-sharing",
                "label": "Files & Sharing",
                "icon": "bi-share",
                "sections": [
                    {"id": "file-download-settings-section", "label": "File Downloads", "icon": "bi-download"},
                    {"id": "file-sharing-section", "label": "File Sharing", "icon": "bi-share"},
                    {"id": "shared-conversation-file-approvals-section", "label": "Shared Conversation File Approvals", "icon": "bi-check2-square"},
                    {"id": "file-size-limit-section", "label": "Maximum File Size", "icon": "bi-file-earmark-arrow-up"},
                ],
            },
            {
                "id": "workspace-identities",
                "label": "Global Identities",
                "icon": "bi-person-badge",
                "sections": [],
            },
        ],
    },
    {
        # Workflow drives approvals and assignment across workspaces and is
        # large enough to stand on its own rather than sit inside Workspaces.
        "id": "workflow",
        "label": "Workflow",
        "icon": "bi-diagram-3",
        "tabs": [
            {
                "id": "workflow",
                "label": "Workflow",
                "icon": "bi-diagram-3",
                "sections": [
                    {"id": "workflow-settings-section", "label": "Workflow", "icon": "bi-diagram-3"},
                ],
            },
        ],
    },
    {
        # Orchestration plans, approves and runs a chat request on the user's behalf.
        # It spans chat, agents and (later) workflows rather than belonging to any one
        # of them, so it stands on its own rather than hiding inside Chat.
        "id": "orchestration",
        "label": "Orchestration",
        "icon": "bi-signpost-split",
        "tabs": [
            {
                "id": "chat-orchestration",
                "label": "Chat Orchestration",
                "icon": "bi-signpost-split",
                "sections": [
                    {"id": "chat-orchestration-section", "label": "Chat Orchestration", "icon": "bi-signpost-split"},
                    {"id": "chat-orchestration-approval-section", "label": "Plan Approval", "icon": "bi-check2-square"},
                    {"id": "chat-orchestration-capabilities-section", "label": "Capabilities", "icon": "bi-puzzle"},
                    {"id": "chat-orchestration-limits-section", "label": "Limits", "icon": "bi-speedometer2"},
                    {"id": "chat-orchestration-planner-model-section", "label": "Planner Model", "icon": "bi-cpu"},
                ],
            },
        ],
    },
    {
        "id": "knowledge",
        "label": "Knowledge",
        "icon": "bi-search",
        "tabs": [
            {
                # Reaching outside the tenant for material.
                "id": "web-research",
                "label": "Web & Research",
                "icon": "bi-globe",
                "sections": [
                    {"id": "web-search-section", "label": "Web Search", "icon": "bi-globe"},
                    {"id": "url-access-section", "label": "URL Access", "icon": "bi-link-45deg"},
                    {"id": "source-review-section", "label": "Deep Research", "icon": "bi-binoculars"},
                ],
            },
            {
                "id": "search-index",
                "label": "Search Index",
                "icon": "bi-search",
                "sections": [
                    {"id": "azure-ai-search-section", "label": "Azure AI Search", "icon": "bi-search"},
                ],
            },
            {
                # Turning a document into something searchable.
                "id": "extraction",
                "label": "Document Extraction",
                "icon": "bi-file-earmark-text",
                "sections": [
                    {"id": "document-intelligence-section", "label": "Document Intelligence", "icon": "bi-file-earmark-text"},
                    {"id": "chunk-size-section", "label": "Chunk Sizes", "icon": "bi-collection"},
                    {"id": "metadata-extraction-section", "label": "Metadata Extraction", "icon": "bi-file-earmark-code"},
                    {"id": "multimodal-vision-section", "label": "Multi-Modal Vision Analysis", "icon": "bi-eye"},
                ],
            },
            {
                # Voice and video are extraction pipelines, not chat features.
                "id": "audio-video",
                "label": "Audio & Video",
                "icon": "bi-play-circle",
                "sections": [
                    {"id": "video-intelligence-section", "label": "AI Video Intelligence", "icon": "bi-play-circle"},
                    {"id": "ai-voice-chat-section", "label": "AI Voice Conversations", "icon": "bi-mic"},
                ],
            },
            {
                "id": "file-sync",
                "label": "File Sync",
                "icon": "bi-arrow-repeat",
                "sections": [
                    {"id": "file-sync-section", "label": "File Sync", "icon": "bi-arrow-repeat"},
                    {"id": "file-sync-source-types-section", "label": "Visible Source Types", "icon": "bi-sliders"},
                    {"id": "file-sync-personal-section", "label": "Personal Workspace Sync", "icon": "bi-person"},
                    {"id": "file-sync-group-section", "label": "Group Workspace Sync", "icon": "bi-people"},
                    {"id": "file-sync-public-section", "label": "Public Workspace Sync", "icon": "bi-globe"},
                ],
            },
        ],
    },
    {
        "id": "security",
        "label": "Security",
        "icon": "bi-shield-lock",
        "tabs": [
            {
                # Who can get in and what role they need. Distinct from Content
                # Safety, which is about what may be said once you are in.
                "id": "access-roles",
                "label": "Access & Roles",
                "icon": "bi-person-check",
                "sections": [
                    {"id": "permissions-section", "label": "Permissions", "icon": "bi-person-check"},
                    {"id": "app-role-requirements-section", "label": "App Role Requirements", "icon": "bi-person-badge"},
                    {"id": "access-denied-message-section", "label": "Access Denied Message", "icon": "bi-shield-x"},
                ],
            },
            {
                "id": "secrets",
                "label": "Secrets",
                "icon": "bi-safe",
                "sections": [
                    {"id": "keyvault-section", "label": "Key Vault", "icon": "bi-safe"},
                ],
            },
            {
                "id": "content-safety",
                "label": "Content Safety",
                "icon": "bi-shield-exclamation",
                "sections": [
                    {"id": "content-safety-section", "label": "Content Safety", "icon": "bi-shield-exclamation"},
                ],
            },
            {
                # Idle timeout is the only thing left here. The rest of the old
                # System Settings card was split out to the tabs that own each
                # setting, without renaming a single field.
                "id": "session",
                "label": "Session",
                "icon": "bi-hourglass-split",
                "sections": [
                    {"id": "idle-timeout-section", "label": "Idle Session Timeout", "icon": "bi-hourglass-split"},
                ],
            },
            {
                # Front Door configures authentication and redirect flows, so it
                # belongs with Security rather than with throughput settings.
                "id": "network",
                "label": "Network",
                "icon": "bi-door-open",
                "sections": [
                    {"id": "front-door-section", "label": "Azure Front Door", "icon": "bi-door-open"},
                ],
            },
            {
                # What a throttled user is told. The limits themselves are
                # enforced upstream or per feature, so this owns the response
                # rather than the thresholds.
                "id": "rate-limiting",
                "label": "Rate Limiting",
                "icon": "bi-hourglass-split",
                "sections": [
                    {"id": "rate-limit-message-section", "label": "Rate Limit Message", "icon": "bi-hourglass-split"},
                ],
            },
        ],
    },
    {
        "id": "governance",
        "label": "Governance",
        "icon": "bi-clipboard-check",
        "tabs": [
            {
                "id": "feature-governance",
                "label": "Feature Governance",
                "icon": "bi-braces-asterisk",
                "sections": [
                    {"id": "governance-feature-toggles-section", "label": "Governance Feature Toggles", "icon": "bi-braces-asterisk"},
                ],
            },
            {
                "id": "governance-policies",
                "label": "Policies",
                "icon": "bi-sliders2",
                "sections": [
                    {"id": "governance-feature-policies-section", "label": "Feature Policies", "icon": "bi-sliders2"},
                    {"id": "governance-item-policies-section", "label": "Delegated Item Policies", "icon": "bi-list-check"},
                ],
            },
            {
                "id": "mcp-governance",
                "label": "MCP Governance",
                "icon": "bi-diagram-3",
                "sections": [
                    {"id": "governance-mcp-destination-section", "label": "MCP Action Destination Governance", "icon": "bi-diagram-3"},
                    {"id": "governance-inbound-mcp-section", "label": "Inbound MCP Source Governance", "icon": "bi-box-arrow-in-down-right"},
                ],
            },
        ],
    },
    {
        "id": "data-lifecycle",
        "label": "Data Lifecycle",
        "icon": "bi-hourglass-split",
        "tabs": [
            {
                "id": "retention",
                "label": "Retention",
                "icon": "bi-hourglass-split",
                "sections": [
                    {"id": "retention-policy-section", "label": "Retention Policy", "icon": "bi-hourglass-split"},
                ],
            },
            {
                "id": "classification",
                "label": "Classification",
                "icon": "bi-tags",
                "sections": [
                    {"id": "document-classification-section", "label": "Document Classification", "icon": "bi-tags"},
                ],
            },
            {
                "id": "archiving",
                "label": "Archiving",
                "icon": "bi-archive",
                "sections": [
                    {"id": "conversation-archiving-section", "label": "Conversation Archiving", "icon": "bi-archive"},
                ],
            },
        ],
    },
    {
        "id": "backup-recovery",
        "label": "Backup & Recovery",
        "icon": "bi-database",
        "tabs": [
            {
                # Schedule, storage and encryption are cards nested inside the
                # backup card, so they stay with it.
                "id": "backup",
                "label": "Backup",
                "icon": "bi-archive",
                "sections": [
                    {"id": "data-management-readiness-section", "label": "Start Here", "icon": "bi-compass"},
                    {"id": "data-management-backup-section", "label": "Backup", "icon": "bi-archive"},
                    {"id": "data-management-schedule-section", "label": "Schedule", "icon": "bi-calendar-event"},
                    {"id": "data-management-storage-section", "label": "Storage", "icon": "bi-hdd"},
                    {"id": "data-management-encryption-section", "label": "Encryption", "icon": "bi-key"},
                ],
            },
            {
                "id": "migrate",
                "label": "Migrate",
                "icon": "bi-arrow-left-right",
                "sections": [
                    {"id": "data-management-migration-section", "label": "Migration", "icon": "bi-arrow-left-right"},
                ],
            },
            {
                "id": "restore",
                "label": "Restore",
                "icon": "bi-box-seam",
                "sections": [
                    {"id": "data-management-backup-inventory-section", "label": "Backup Inventory &amp; Restore", "icon": "bi-box-seam"},
                ],
            },
            {
                # A direct database editor. It is a repair tool that belongs
                # with the backup and restore tooling it shares a module with.
                "id": "cosmos-editor",
                "label": "Cosmos Editor",
                "icon": "bi-database-exclamation",
                "sections": [
                    {"id": "data-management-cosmos-editor-section", "label": "Cosmos Editor", "icon": "bi-database-exclamation"},
                ],
            },
            {
                "id": "jobs",
                "label": "Jobs",
                "icon": "bi-clock-history",
                "sections": [
                    {"id": "data-management-jobs-section", "label": "Jobs", "icon": "bi-clock-history"},
                ],
            },
        ],
    },
    {
        "id": "scale",
        "label": "Scale",
        "icon": "bi-speedometer2",
        "tabs": [
            {
                "id": "redis-caching",
                "label": "Redis & Caching",
                "icon": "bi-database",
                "sections": [
                    {"id": "redis-cache-section", "label": "Redis Cache", "icon": "bi-database"},
                    {"id": "redis-monitoring-section", "label": "Redis Metrics", "icon": "bi-activity"},
                    {"id": "conversation-cache-section", "label": "Conversation Cache", "icon": "bi-chat-square-text"},
                ],
            },
            {
                "id": "cosmos",
                "label": "Cosmos",
                "icon": "bi-diagram-3",
                "sections": [
                    {"id": "document-access-index-section", "label": "DAI Metrics", "icon": "bi-diagram-3"},
                    {"id": "cosmos-maintenance-section", "label": "Cosmos Maintenance", "icon": "bi-tools"},
                    {"id": "cosmos-throughput-section", "label": "Cosmos DB Throughput", "icon": "bi-speedometer2"},
                    {"id": "cosmos-throughput-metrics-table-section", "label": "Cosmos Metrics", "icon": "bi-table"},
                ],
            },
        ],
    },
    {
        "id": "operations",
        "label": "Operations",
        "icon": "bi-activity",
        "tabs": [
            {
                "id": "control-center-config",
                "label": "Control Center",
                "icon": "bi-speedometer2",
                "sections": [
                    {"id": "control-center-auto-refresh-section", "label": "Automatic Data Refresh", "icon": "bi-calendar-check"},
                    {"id": "control-center-overview-section", "label": "Control Center Access", "icon": "bi-gear-wide-connected"},
                ],
            },
            {
                "id": "logging",
                "label": "Logging & Health",
                "icon": "bi-journal-text",
                "sections": [
                    {"id": "application-insights-section", "label": "Application Insights", "icon": "bi-graph-up"},
                    {"id": "debug-logging-section", "label": "Debug Logging", "icon": "bi-bug"},
                    {"id": "file-processing-logs-section", "label": "File Process Logging", "icon": "bi-file-earmark-text"},
                    {"id": "health-check-section", "label": "Health Check", "icon": "bi-heart-pulse"},
                    {"id": "swagger-section", "label": "API Documentation", "icon": "bi-file-earmark-code"},
                ],
            },
        ],
    },
    {
        "id": "help",
        "label": "Help",
        "icon": "bi-life-preserver",
        "tabs": [
            {
                # Where an admin looks first when a user needs help, ahead of
                # raising it with the project.
                "id": "support-menu",
                "label": "Support Menu",
                "icon": "bi-life-preserver",
                "sections": [
                    {"id": "support-menu-section", "label": "Support", "icon": "bi-life-preserver"},
                ],
            },
            {
                "id": "send-feedback",
                "label": "Send Feedback",
                "icon": "bi-envelope-paper",
                "sections": [
                    {"id": "send-feedback-overview-card", "label": "Overview", "icon": "bi-info-circle"},
                    {"id": "send-feedback-bug-card", "label": "Report a Bug", "icon": "bi-bug"},
                    {"id": "send-feedback-feature-card", "label": "Request a Feature", "icon": "bi-lightbulb"},
                ],
            },
            {
                "id": "user-facing-latest-features",
                "label": "User-Facing Latest Features",
                "icon": "bi-megaphone",
                "sections": [
                    {"id": "user-facing-latest-features-section", "label": "User-Facing Latest Features", "icon": "bi-megaphone"},
                ],
            },
            {
                "id": "latest-features",
                "label": "Admin Latest Features",
                "icon": "bi-lightning-charge",
                "sections": [],
                # Rendered specially: it can be hidden per user, carries a New
                # badge and a hide/unhide menu, and its sections are generated
                # from the release catalogue rather than declared here.
                "render": "latest_features",
            },
        ],
    },
]


def iter_tabs():
    """Yield (group, tab) pairs in navigation order."""
    for group in ADMIN_NAV:
        for tab in group["tabs"]:
            yield group, tab


def get_tab_ids():
    """Return every tab id in navigation order."""
    return [tab["id"] for _, tab in iter_tabs()]


def get_group_for_tab(tab_id):
    """Return the group owning a tab, or None when the tab is unknown."""
    for group, tab in iter_tabs():
        if tab["id"] == tab_id:
            return group
    return None


def get_landing_tab_id():
    """Return the tab an admin lands on when no tab is requested.

    This is the first tab of the first group rather than a fixed id, so the
    landing pane follows the navigation map as cards are regrouped. Latest
    Features is pinned last precisely so it can never win this.
    """
    for _, tab in iter_tabs():
        return tab["id"]
    return None


def get_section_ids():
    """Return every section target declared across the navigation."""
    return [
        section["id"]
        for _, tab in iter_tabs()
        for section in tab["sections"]
    ]