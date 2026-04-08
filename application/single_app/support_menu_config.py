# support_menu_config.py
"""Shared support menu configuration for user-facing latest features."""

from copy import deepcopy


_SUPPORT_LATEST_FEATURE_DOCS_SETTING_KEY = 'enable_support_latest_feature_documentation_links'


def _resolve_support_application_title(settings):
    """Return the application title used for user-facing support copy."""
    app_title = str((settings or {}).get('app_title') or '').strip()
    return app_title or 'Simple Chat'


def _apply_support_application_title(value, app_title):
    """Replace hard-coded product naming in user-facing support metadata."""
    if isinstance(value, str):
        return value.replace('{app_title}', app_title).replace('SimpleChat', app_title)

    if isinstance(value, list):
        return [_apply_support_application_title(item, app_title) for item in value]

    if isinstance(value, dict):
        return {
            key: _apply_support_application_title(item, app_title)
            for key, item in value.items()
        }

    return value


_SUPPORT_LATEST_FEATURE_CATALOG = [
    {
        'id': 'guided_tutorials',
        'title': 'Guided Tutorials',
        'icon': 'bi-signpost-split',
        'summary': 'Step-by-step walkthroughs help users discover core chat, workspace, and onboarding flows faster, and each user can now hide the launchers when they no longer need them.',
        'details': 'Guided Tutorials add in-product walkthroughs so you can learn the interface in context instead of hunting through menus first. Tutorial launchers are shown by default and can be hidden or restored later from your profile page.',
        'why': 'This matters because the fastest way to learn a new workflow is usually inside the workflow itself, with the right controls highlighted as you go, while still letting each user hide the launcher once they are comfortable with the app.',
        'guidance': [
            'Start with the Chat Tutorial to learn message tools, uploads, prompts, and follow-up workflows.',
            'If Personal Workspace is enabled for your environment, open the Workspace Tutorial to learn uploads, filters, tags, prompts, agents, and actions.',
            'Tutorial buttons are visible by default. If you prefer a cleaner interface, open your profile page and hide them for your own account.',
        ],
        'actions': [
            {
                'label': 'Open Chat Tutorial',
                'description': 'Jump to Chat and launch the guided walkthrough from the floating tutorial button.',
                'endpoint': 'chats',
                'fragment': 'chat-tutorial-launch',
                'icon': 'bi-chat-dots',
            },
            {
                'label': 'Open Workspace Tutorial',
                'description': 'Jump to Personal Workspace and launch the workspace walkthrough when that workspace is enabled.',
                'endpoint': 'workspace',
                'fragment': 'workspace-tutorial-launch',
                'icon': 'bi-folder2-open',
                'requires_settings': ['enable_user_workspace'],
            },
            {
                'label': 'Manage Tutorial Visibility',
                'description': 'Open your profile page to show or hide the tutorial launch buttons for your account.',
                'endpoint': 'profile',
                'fragment': 'tutorial-preferences',
                'icon': 'bi-person-gear',
            },
        ],
        'image': 'images/features/guided_tutorials_chat.png',
        'image_alt': 'Guided tutorials feature screenshot',
        'images': [
            {
                'path': 'images/features/guided_tutorials_chat.png',
                'alt': 'Guided chat tutorial screenshot',
                'title': 'Guided Chat Tutorial',
                'caption': 'Guided walkthrough entry point for the live chat experience.',
                'label': 'Chat Tutorial',
            },
            {
                'path': 'images/features/guided_tutorials_workspace.png',
                'alt': 'Workspace guided tutorial screenshot',
                'title': 'Guided Workspace Tutorial',
                'caption': 'Walkthrough entry point for Personal Workspace uploads, filters, tools, and tags.',
                'label': 'Workspace Tutorial',
            },
        ],
    },
    {
        'id': 'background_chat',
        'title': 'Background Chat',
        'icon': 'bi-bell',
        'summary': 'Long-running chat requests can finish in the background while users continue working elsewhere in the app.',
        'details': 'Background Chat lets a long-running request keep working after you move away from the chat page.',
        'why': 'This matters most for larger uploads and heavier prompts, where waiting on one screen is wasted time and makes the app feel blocked.',
        'guidance': [
            'Start the request from Chat the same way you normally would.',
            'If the request takes longer, you can keep using the app and come back when the completion notification appears.',
        ],
        'actions': [
            {
                'label': 'Open Chat',
                'description': 'Start a prompt in Chat and let the app notify you when longer work finishes.',
                'endpoint': 'chats',
                'icon': 'bi-chat-dots',
            },
        ],
        'image': 'images/features/background_completion_notifications-01.png',
        'image_alt': 'Background chat notification screenshot',
        'images': [
            {
                'path': 'images/features/background_completion_notifications-01.png',
                'alt': 'Background completion notification screenshot',
                'title': 'Background Completion Notification',
                'caption': 'Notification example showing that a chat response completed after the user moved away.',
                'label': 'Completion Notification',
            },
            {
                'path': 'images/features/background_completion_notifications-02.png',
                'alt': 'Background completion deep link screenshot',
                'title': 'Notification Deep Link',
                'caption': 'Notification detail showing how users can jump back into the finished chat result.',
                'label': 'Return to Finished Chat',
            },
        ],
    },
    {
        'id': 'gpt_selection',
        'title': 'GPT Selection',
        'icon': 'bi-cpu',
        'summary': 'Teams can expose better model-selection options so users can choose the best experience for a task.',
        'details': 'GPT Selection gives users a clearer way to choose the model that best fits a task when multiple options are available.',
        'why': 'That matters because different prompts often need different tradeoffs in speed, cost, or reasoning depth.',
        'guidance': [
            'Open Chat and look for the model picker in the composer toolbar.',
            'Try another model when you need faster output, stronger reasoning, or a different cost profile.',
        ],
        'actions': [
            {
                'label': 'Open Chat Model Picker',
                'description': 'Go to Chat and jump to the model selector in the composer area.',
                'endpoint': 'chats',
                'fragment': 'model-select-container',
                'icon': 'bi-cpu',
            },
        ],
        'image': 'images/features/model_selection_multi_endpoint_admin.png',
        'image_alt': 'Admin multi-endpoint model management screenshot',
        'images': [
            {
                'path': 'images/features/model_selection_multi_endpoint_admin.png',
                'alt': 'Admin multi-endpoint model management screenshot',
                'title': 'Admin Multi-Endpoint Model Management',
                'caption': 'Admin endpoint table showing configured Azure OpenAI and Foundry model endpoints.',
                'label': 'Admin Endpoint Table',
            },
            {
                'path': 'images/features/model_selection_chat_selector.png',
                'alt': 'User chat model selector screenshot',
                'title': 'User Chat Model Selector',
                'caption': 'Chat composer model selector showing multiple available GPT choices.',
                'label': 'Chat Model Selector',
            },
        ],
    },
    {
        'id': 'tabular_analysis',
        'title': 'Tabular Analysis',
        'icon': 'bi-table',
        'summary': 'Spreadsheet and table workflows continue to improve for exploration, filtering, and grounded follow-up questions.',
        'details': 'Tabular Analysis improves how {app_title} works with CSV and spreadsheet files for filtering, comparisons, and grounded follow-up questions.',
        'why': 'You get the most value after the file is uploaded, because the assistant can reason over the stored rows and columns instead of only whatever is pasted into one message.',
        'guidance': [
            'Upload your CSV or XLSX to Personal Workspace if it is enabled, or add the file directly to Chat when you want a quicker one-off analysis.',
            'If you are updating an existing table, upload the newer file with the same name. You do not need to delete the previous version first.',
            'Ask follow-up questions after the upload so the assistant can stay grounded in the stored tabular data.',
        ],
        'actions': [
            {
                'label': 'Upload in Personal Workspace',
                'description': 'Jump to the Personal Workspace upload area for a durable tabular file workflow.',
                'endpoint': 'workspace',
                'fragment': 'upload-area',
                'icon': 'bi-upload',
                'requires_settings': ['enable_user_workspace'],
            },
            {
                'label': 'Upload a New Revision',
                'description': 'Jump to the same upload area and add the updated file with the same name to create a new revision.',
                'endpoint': 'workspace',
                'fragment': 'upload-area',
                'icon': 'bi-arrow-repeat',
                'requires_settings': ['enable_user_workspace'],
            },
            {
                'label': 'Add a File to Chat',
                'description': 'Use Chat when you want to attach a spreadsheet directly to a conversation.',
                'endpoint': 'chats',
                'fragment': 'choose-file-btn',
                'icon': 'bi-paperclip',
            },
        ],
        'image': 'images/features/tabular_analysis_enhanced_citations.png',
        'image_alt': 'Tabular analysis enhanced citations screenshot',
        'images': [
            {
                'path': 'images/features/tabular_analysis_enhanced_citations.png',
                'alt': 'Tabular analysis enhanced citations screenshot',
                'title': 'Tabular Analysis with Enhanced Citations',
                'caption': 'Tabular analysis preview showing the improved citation-backed experience for spreadsheet content.',
                'label': 'Tabular Analysis Preview',
            },
        ],
    },
    {
        'id': 'citation_improvements',
        'title': 'Citation Improvements',
        'icon': 'bi-journal-text',
        'summary': 'Enhanced citations give users better source traceability, document previews, and history-aware grounding.',
        'details': 'Citation Improvements help you see where answers came from and keep grounded evidence available across follow-up questions.',
        'why': 'That matters because better citation carry-forward means fewer follow-up turns lose context or force you to rebuild the same evidence chain from scratch.',
        'guidance': [
            'Stay in the same conversation when you ask follow-up questions so the assistant can reuse the earlier grounded evidence.',
            'Open citations or previews when you want to inspect the supporting material behind an answer.',
        ],
        'actions': [
            {
                'label': 'Open Chat for Follow-ups',
                'description': 'Ask a follow-up in Chat and review how citations stay available across turns.',
                'endpoint': 'chats',
                'fragment': 'chatbox',
                'icon': 'bi-chat-dots',
            },
        ],
        'image': 'images/features/citation_improvements_history_replay.png',
        'image_alt': 'Conversation history citation replay screenshot',
        'images': [
            {
                'path': 'images/features/citation_improvements_history_replay.png',
                'alt': 'Conversation history citation replay screenshot',
                'title': 'Conversation History Citation Replay',
                'caption': 'Follow-up chat where prior citation summaries are replayed into the next turn\'s reasoning context.',
                'label': 'History Citation Replay',
            },
            {
                'path': 'images/features/citation_improvements_amplified_results.png',
                'alt': 'Citation amplification details screenshot',
                'title': 'Citation Amplification Details',
                'caption': 'Expanded citation detail showing amplified supporting evidence and fuller artifact-backed results.',
                'label': 'Amplified Citation Detail',
            },
        ],
    },
    {
        'id': 'document_versioning',
        'title': 'Document Versioning',
        'icon': 'bi-files',
        'summary': 'Document revision visibility has improved so users can work with the right version of shared content.',
        'details': 'Document Versioning keeps same-name uploads organized as revisions so newer files become current without erasing the older record.',
        'why': 'That matters because ongoing chats and citations can stay tied to the right version while you continue updating the same document over time.',
        'guidance': [
            'Upload the updated file with the same name to create a new current revision.',
            'You do not need to delete the older file first unless you no longer want to keep its history.',
            'Use the workspace document list to confirm which revision is current before you ask more questions about it.',
        ],
        'actions': [
            {
                'label': 'Review Workspace Documents',
                'description': 'Open Personal Workspace and review the current document list for revision-aware uploads.',
                'endpoint': 'workspace',
                'fragment': 'documents-table',
                'icon': 'bi-files',
                'requires_settings': ['enable_user_workspace'],
            },
            {
                'label': 'Upload an Updated Version',
                'description': 'Jump to the upload area and add the newer file with the same name to create a new revision.',
                'endpoint': 'workspace',
                'fragment': 'upload-area',
                'icon': 'bi-arrow-repeat',
                'requires_settings': ['enable_user_workspace'],
            },
        ],
        'image': 'images/features/document_revision_workspace.png',
        'image_alt': 'Document revision workspace screenshot',
        'images': [
            {
                'path': 'images/features/document_revision_workspace.png',
                'alt': 'Document revision workspace screenshot',
                'title': 'Current Revision in Workspace',
                'caption': 'Workspace document list showing the current revision state for same-name uploads.',
                'label': 'Current Revision View',
            },
            {
                'path': 'images/features/document_revision_delete_compare.png',
                'alt': 'Document revision actions and comparison screenshot',
                'title': 'Revision Actions and Comparison',
                'caption': 'Version-aware actions such as comparison, analysis of previous revisions, or current-versus-all-versions deletion choices.',
                'label': 'Revision Actions',
            },
        ],
    },
    {
        'id': 'summaries_export',
        'title': 'Summaries and Export',
        'icon': 'bi-file-earmark-arrow-down',
        'summary': 'Conversation summaries and export workflows continue to expand for reporting and follow-up sharing.',
        'details': 'Summaries and Export features make it easier to capture, reuse, and share the important parts of a chat session.',
        'why': 'This matters when a long chat needs a reusable summary, a PDF handoff, or per-message reuse in email, documents, or other downstream workflows.',
        'guidance': [
            'Open an existing conversation when you want to generate or refresh a summary.',
            'Use export options when you need to share the full conversation or reuse a single message outside the app.',
        ],
        'actions': [
            {
                'label': 'Open Chat History',
                'description': 'Go to Chat and open a conversation with enough content to summarize, export, or reuse.',
                'endpoint': 'chats',
                'fragment': 'chatbox',
                'icon': 'bi-file-earmark-arrow-down',
            },
        ],
        'image': 'images/features/conversation_summary_card.png',
        'image_alt': 'Conversation summary card screenshot',
        'images': [
            {
                'path': 'images/features/conversation_summary_card.png',
                'alt': 'Conversation summary card screenshot',
                'title': 'Conversation Summary Card',
                'caption': 'Conversation summary panel preview in the chat experience.',
                'label': 'Summary Card',
            },
            {
                'path': 'images/features/pdf_export_option.png',
                'alt': 'PDF export option screenshot',
                'title': 'PDF Export Option',
                'caption': 'PDF export entry in the conversation export workflow.',
                'label': 'PDF Export',
            },
            {
                'path': 'images/features/per_message_export_menu.png',
                'alt': 'Per-message export menu screenshot',
                'title': 'Per-Message Export Menu',
                'caption': 'Expanded per-message export and reuse actions.',
                'label': 'Per-Message Actions',
            },
        ],
    },
    {
        'id': 'agent_operations',
        'title': 'Agent Operations',
        'icon': 'bi-grid',
        'summary': 'Agent creation, organization, and operational controls keep getting smoother for advanced scenarios.',
        'details': 'Agent Operations updates improve how teams browse, manage, and reason about reusable AI assistants and their connected actions.',
        'why': 'That matters because advanced agent workflows are only useful when users can find the right assistant quickly and trust the connected tools behind it.',
        'guidance': [
            'Open Personal Workspace if your environment exposes per-user agents and actions.',
            'Use list or grid views to browse agents based on whether you want denser detail or quicker scanning.',
        ],
        'actions': [
            {
                'label': 'Open Personal Workspace',
                'description': 'Jump to Personal Workspace, then switch to the Agents tab if agents are enabled in your environment.',
                'endpoint': 'workspace',
                'icon': 'bi-grid',
                'requires_settings': ['enable_user_workspace', 'enable_semantic_kernel', 'per_user_semantic_kernel'],
            },
        ],
        'image': 'images/features/agent_action_grid_view.png',
        'image_alt': 'Agent and action grid view screenshot',
        'images': [
            {
                'path': 'images/features/agent_action_grid_view.png',
                'alt': 'Agent and action grid view screenshot',
                'title': 'Agent and Action Grid View',
                'caption': 'Grid browsing experience for agents and actions.',
                'label': 'Grid View',
            },
            {
                'path': 'images/features/sql_test_connection.png',
                'alt': 'SQL test connection screenshot',
                'title': 'SQL Test Connection',
                'caption': 'Inline SQL connection test preview before save.',
                'label': 'SQL Test Connection',
            },
        ],
    },
    {
        'id': 'ai_transparency',
        'title': 'AI Transparency',
        'icon': 'bi-stars',
        'summary': 'Thought and reasoning transparency options help users better understand what the assistant is doing.',
        'details': 'AI Transparency adds clearer visibility into the assistant\'s in-flight work when your team chooses to expose it.',
        'why': 'This helps the app feel less opaque during longer responses because you can see progress instead of guessing whether the request stalled.',
        'guidance': [
            'Look for Processing Thoughts while a response is being generated in Chat.',
            'If you do not see them, your admins may have kept this feature turned off for your environment.',
        ],
        'actions': [
            {
                'label': 'Open Chat',
                'description': 'Go to Chat and watch for processing-state visibility while a response is generated.',
                'endpoint': 'chats',
                'fragment': 'chatbox',
                'icon': 'bi-stars',
            },
        ],
        'image': 'images/features/thoughts_visibility.png',
        'image_alt': 'Processing thoughts visibility screenshot',
        'images': [
            {
                'path': 'images/features/thoughts_visibility.png',
                'alt': 'Processing thoughts visibility screenshot',
                'title': 'Processing Thoughts Visibility',
                'caption': 'Processing thoughts state and timing details preview.',
                'label': 'Processing Thoughts',
            },
        ],
    },
    {
        'id': 'fact_memory',
        'title': 'Fact Memory',
        'icon': 'bi-journal-bookmark',
        'summary': 'Profile-based memory now distinguishes always-on Instructions from recall-only Facts so the assistant can carry durable preferences and relevant personal context forward more cleanly.',
        'details': 'Fact Memory gives each user a compact profile experience for saving Instructions and Facts. Instructions act like durable response preferences, while Facts are recalled only when they are relevant to the current request.',
        'why': 'This matters because you no longer need to restate the same preferences or personal context in every conversation, and the chat experience now shows when saved instructions and facts were actually used.',
        'guidance': [
            'Open your profile page and use Fact Memory when you want to save a lasting preference or a detail about yourself.',
            'Choose Instruction for durable preferences like tone, brevity, formatting, or things the assistant should always keep in mind.',
            'Choose Fact for details that should only be recalled when relevant, such as who you are, what you prefer, or other personal context.',
            'Try a chat prompt like "tell me all about myself" when you want to confirm which saved facts the assistant can recall.',
        ],
        'actions': [
            {
                'label': 'Manage Fact Memory',
                'description': 'Open your profile page and jump straight to the Fact Memory section to add, edit, or remove saved instructions and facts.',
                'endpoint': 'profile',
                'fragment': 'fact-memory-settings',
                'icon': 'bi-person-gear',
            },
            {
                'label': 'Try It in Chat',
                'description': 'Open Chat and ask a personal or preference-aware question to see instruction memory and fact recall in action.',
                'endpoint': 'chats',
                'fragment': 'chatbox',
                'icon': 'bi-chat-dots',
            },
        ],
        'image': 'images/features/fact_memory_management.png',
        'image_alt': 'Fact memory management modal screenshot',
        'images': [
            {
                'path': 'images/features/facts_memory_view_profile.png',
                'alt': 'Profile fact memory section screenshot',
                'title': 'Fact Memory on Profile',
                'caption': 'Profile page section for adding saved instructions and facts and opening the manager modal.',
                'label': 'Profile Entry Point',
            },
            {
                'path': 'images/features/fact_memory_management.png',
                'alt': 'Fact memory management modal screenshot',
                'title': 'Manage Fact Memories',
                'caption': 'Compact popup manager showing saved instructions and facts with search, paging, edit, and type controls.',
                'label': 'Memory Manager',
            },
            {
                'path': 'images/features/facts_citation_and_thoughts.png',
                'alt': 'Chat fact memory thoughts and citations screenshot',
                'title': 'Instruction Memory and Fact Recall in Chat',
                'caption': 'Chat response showing instruction memory and fact recall surfaced as dedicated thoughts and citations.',
                'label': 'Chat Recall',
            },
        ],
    },
    {
        'id': 'deployment',
        'title': 'Deployment',
        'icon': 'bi-hdd-rack',
        'summary': 'Deployment guidance and diagnostics keep improving so admins can roll out changes with less guesswork.',
        'details': 'Deployment updates focus on making configuration, startup validation, and operational guidance easier for admins to follow.',
        'why': 'For users, this usually shows up as a more stable rollout of new capabilities rather than a brand-new button on the page.',
        'guidance': [
            'This is mainly an operational improvement managed by your admins.',
            'If a newly announced feature is not visible yet, your environment may still be rolling forward to the latest configuration.',
        ],
        'actions': [],
        'image': 'images/features/gunicorn_startup_guidance.png',
        'image_alt': 'Deployment guidance screenshot',
        'images': [
            {
                'path': 'images/features/gunicorn_startup_guidance.png',
                'alt': 'Deployment guidance screenshot',
                'title': 'Deployment Startup Guidance',
                'caption': 'Startup guidance that helps admins configure the app runtime more predictably.',
                'label': 'Deployment Guidance',
            },
        ],
    },
    {
        'id': 'redis_key_vault',
        'title': 'Redis and Key Vault',
        'icon': 'bi-key',
        'summary': 'Caching and secret-management setup guidance has expanded for more secure and predictable operations.',
        'details': 'Redis and Key Vault improvements make it easier for teams to configure caching and secret storage patterns correctly.',
        'why': 'For users, the practical outcome is usually reliability and performance, with fewer environment-level issues caused by secret or cache misconfiguration.',
        'guidance': [
            'This is another behind-the-scenes improvement mostly managed by your admins.',
            'You may notice it indirectly through smoother repeated access patterns or fewer environment issues.',
        ],
        'actions': [],
        'image': 'images/features/redis_key_vault.png',
        'image_alt': 'Redis and Key Vault screenshot',
        'images': [
            {
                'path': 'images/features/redis_key_vault.png',
                'alt': 'Redis and Key Vault screenshot',
                'title': 'Redis Key Vault Configuration',
                'caption': 'Redis authentication with Key Vault secret name preview.',
                'label': 'Redis Key Vault',
            },
        ],
    },
    {
        'id': 'send_feedback',
        'title': 'Send Feedback',
        'icon': 'bi-envelope-paper',
        'summary': 'End users can prepare bug reports and feature requests for their {app_title} admins directly from the Support menu.',
        'details': 'Send Feedback opens a guided, text-only email draft workflow so you can report issues or request improvements without leaving the app.',
        'why': 'That gives your admins a cleaner starting point for triage than a vague message without context or reproduction details.',
        'guidance': [
            'Choose Bug Report when something is broken, confusing, or behaving differently than you expected.',
            'Choose Feature Request when you want a new workflow, capability, or quality-of-life improvement.',
            'Your draft is addressed to the internal support recipient configured by your admins.',
        ],
        'actions': [
            {
                'label': 'Open Send Feedback',
                'description': 'Go straight to the Support feedback page and prepare a structured email draft.',
                'endpoint': 'support_send_feedback',
                'icon': 'bi-envelope-paper',
                'requires_settings': ['enable_support_send_feedback'],
            },
        ],
        'image': 'images/features/support_menu_entry.png',
        'image_alt': 'Support menu entry showing Send Feedback access',
        'images': [
            {
                'path': 'images/features/support_menu_entry.png',
                'alt': 'Support menu entry screenshot',
                'title': 'Send Feedback Entry Point',
                'caption': 'Support menu entry showing where Send Feedback lives for end users.',
                'label': 'Support Entry Point',
            },
        ],
    },
    {
        'id': 'support_menu',
        'title': 'Support Menu',
        'icon': 'bi-life-preserver',
        'summary': 'Admins can surface a dedicated Support menu in navigation with Latest Features and Send Feedback entries for end users.',
        'details': 'Support Menu configuration lets admins rename the menu, choose the internal feedback recipient, and decide which user-facing release notes are shared.',
        'why': 'That matters because new capabilities are easier to discover when help, feature announcements, and feedback all live in one predictable place.',
        'guidance': [
            'Use Latest Features when you want a curated explanation of what changed and why it matters.',
            'Use Send Feedback when you want to tell your admins what is missing, confusing, or especially helpful.',
        ],
        'actions': [
            {
                'label': 'Browse Latest Features',
                'description': 'Refresh this page later when you want to review other recently shared updates.',
                'endpoint': 'support_latest_features',
                'icon': 'bi-life-preserver',
            },
            {
                'label': 'Open Send Feedback',
                'description': 'Go from Support directly into the structured feedback workflow when that destination is enabled.',
                'endpoint': 'support_send_feedback',
                'icon': 'bi-envelope-paper',
                'requires_settings': ['enable_support_send_feedback'],
            },
        ],
        'image': 'images/features/support_menu_entry.png',
        'image_alt': 'Support menu entry screenshot',
        'images': [
            {
                'path': 'images/features/support_menu_entry.png',
                'alt': 'Support menu entry screenshot',
                'title': 'User Support Menu Entry',
                'caption': 'User-facing Support menu entry exposing Latest Features and Send Feedback.',
                'label': 'Support Menu Entry',
            },
        ],
    },
]

_SUPPORT_PREVIOUS_RELEASE_FEATURE_CATALOG = [
    {
        'id': 'conversation_export',
        'title': 'Conversation Export',
        'icon': 'bi-download',
        'summary': 'Export one or multiple conversations from Chat in JSON or Markdown without carrying internal-only metadata into the downloaded package.',
        'details': 'Conversation Export adds a guided workflow for choosing format, packaging, and download options when you need to reuse or archive chat history outside the app.',
        'why': 'This matters because users often need to share, archive, or reuse a conversation without copying raw chat text by hand or exposing internal metadata that should stay inside {app_title}.',
        'guidance': [
            'Open an existing conversation from Chat when you want to export content that already has enough context to share.',
            'Choose JSON when you want a machine-readable export and Markdown when you want something easier for people to review directly.',
            'Use the packaging options in the export flow when you need a cleaner handoff for reporting or project documentation.',
        ],
        'actions': [
            {
                'label': 'Open Conversation Export',
                'description': 'Jump to Chat, open the first available conversation, and launch the export workflow directly.',
                'href': '/chats?feature_action=conversation_export',
                'icon': 'bi-box-arrow-in-right',
            },
            {
                'label': 'Read Export Guide',
                'description': 'Open the public release guide that walks through the conversation export workflow.',
                'href': 'https://microsoft.github.io/simplechat/latest-release/export-conversation/',
                'icon': 'bi-box-arrow-up-right',
                'is_external': True,
                'requires_settings': [_SUPPORT_LATEST_FEATURE_DOCS_SETTING_KEY],
            },
        ],
        'images': [
            {
                'path': 'images/features/conversation_export.png',
                'alt': 'Conversation export workflow screenshot',
                'title': 'Conversation Export Workflow',
                'caption': 'Primary export workflow showing how users can package and download conversation history.',
                'label': 'Export Workflow',
            },
            {
                'path': 'images/features/conversation_export_type_option.png',
                'alt': 'Conversation export type option screenshot',
                'title': 'Conversation Export Format Options',
                'caption': 'Format selection options for choosing how conversation exports should be generated.',
                'label': 'Format Options',
            },
        ],
    },
    {
        'id': 'retention_policy',
        'title': 'Retention Policy',
        'icon': 'bi-hourglass-split',
        'summary': 'Retention periods for conversations and documents can be configured with presets, organization defaults, or fully disabled automatic cleanup.',
        'details': 'Retention Policy adds clearer controls for deciding how long conversations and documents should remain available before they are removed automatically.',
        'why': 'This matters because teams often need predictable cleanup rules for compliance, storage hygiene, or operational consistency instead of manually pruning old content.',
        'guidance': [
            'Use the documented presets when you want a consistent retention window without manually calculating dates.',
            'Choose the organization default when you want shared policy behavior across workspaces instead of one-off overrides.',
            'Disable automatic deletion only when your environment has another retention process that already handles lifecycle management.',
        ],
        'actions': [
            {
                'label': 'Open Retention Settings',
                'description': 'Open your profile page and jump to the retention policy settings section.',
                'href': '/profile?feature_action=retention_policy#retention-policy-settings',
                'icon': 'bi-box-arrow-in-right',
            },
            {
                'label': 'Read Retention Guide',
                'description': 'Open the public release guide for workspace and conversation retention controls.',
                'href': 'https://microsoft.github.io/simplechat/latest-release/retention-policy/',
                'icon': 'bi-box-arrow-up-right',
                'is_external': True,
                'requires_settings': [_SUPPORT_LATEST_FEATURE_DOCS_SETTING_KEY],
            },
        ],
        'images': [
            {
                'path': 'images/features/retention_policy-personal_profile.png',
                'alt': 'Personal retention policy profile settings screenshot',
                'title': 'Personal Retention Settings',
                'caption': 'Profile-based retention settings for personal conversations and documents.',
                'label': 'Personal Profile Settings',
            },
            {
                'path': 'images/features/retention_policy-manage_group.png',
                'alt': 'Group retention policy management screenshot',
                'title': 'Group Retention Management',
                'caption': 'Group-level retention policy management for shared workspace content.',
                'label': 'Manage Group Retention',
            },
        ],
    },
    {
        'id': 'owner_only_group_agent_management',
        'title': 'Owner-Only Group Agent Management',
        'icon': 'bi-shield-lock',
        'summary': 'Admins can restrict group agent and action management to the Owner role so other group roles stay read-only.',
        'details': 'Owner-Only Group Agent Management adds a stricter governance option for teams that want group agents and actions maintained only by the group owner.',
        'why': 'This matters because collaborative workspaces often need a smaller set of people with change authority, especially when group agents and connected actions affect many users at once.',
        'guidance': [
            'Use this when group ownership should be the only role that can change shared agents or actions.',
            'Expect non-owner users to keep read access while creation, editing, and deletion move behind a stricter permission boundary.',
            'If your environment relies on delegated group administrators, confirm that workflow before switching to owner-only enforcement.',
        ],
        'actions': [],
    },
    {
        'id': 'enforce_workspace_scope_lock',
        'title': 'Enforce Workspace Scope Lock',
        'icon': 'bi-lock',
        'summary': 'Admins can keep workspace scope locked after the first AI search so users do not accidentally mix sources mid-conversation.',
        'details': 'Workspace Scope Lock prevents a conversation from drifting across personal, group, or public workspaces after the first grounded search has established the working scope.',
        'why': 'This matters because cross-scope drift is hard to detect once a conversation is underway, and locking the scope protects against mixing evidence from the wrong workspace.',
        'guidance': [
            'Use this when your team wants stronger grounding discipline for workspace-scoped chat conversations.',
            'Expect the lock to take effect after the first AI search in a conversation rather than before any prompt is sent.',
            'If you train users to work across multiple scopes in the same session, document that this setting intentionally tightens that behavior.',
        ],
        'actions': [
            {
                'label': 'Read Scope Lock Guide',
                'description': 'Open the public release guide for enforced workspace scope locking.',
                'href': 'https://microsoft.github.io/simplechat/latest-release/workspace-scope-lock/',
                'icon': 'bi-box-arrow-up-right',
                'is_external': True,
                'requires_settings': [_SUPPORT_LATEST_FEATURE_DOCS_SETTING_KEY],
            },
        ],
        'images': [
            {
                'path': 'images/features/workspace_scope_lock.png',
                'alt': 'Workspace scope lock screenshot',
                'title': 'Workspace Scope Lock',
                'caption': 'Locked workspace scope in chat after the first grounded search has established the evidence boundary.',
                'label': 'Scope Lock',
            },
        ],
    },
    {
        'id': 'document_tag_system',
        'title': 'Document Tag System',
        'icon': 'bi-tags',
        'summary': 'Documents can be organized with color-coded tags across personal, group, and public workspaces, with AI search-aware filtering built in.',
        'details': 'Document Tag System adds durable tag management, bulk tag workflows, and tag-aware search filtering so users can organize and target document sets more deliberately.',
        'why': 'This matters because document-heavy workspaces become much easier to navigate when teams can classify content with reusable tags and then ask grounded questions against those tag groupings.',
        'guidance': [
            'Use tags when you want a lightweight way to organize documents without forcing everything into a rigid folder hierarchy.',
            'Apply tags consistently across related documents so AI search filters can narrow results more cleanly during chat.',
            'Revisit the shared guide if you want the combined tags, folder view, and chat filtering walkthrough from the original release.',
        ],
        'actions': [
            {
                'label': 'Open Workspace Tags',
                'description': 'Open Personal Workspace and launch the tag-management workflow directly.',
                'href': '/workspace?feature_action=document_tag_system',
                'icon': 'bi-box-arrow-in-right',
            },
            {
                'label': 'Read Tags Guide',
                'description': 'Open the public release guide covering tags, grid view, and chat filtering together.',
                'href': 'https://microsoft.github.io/simplechat/latest-release/tags-grid-view-chat-filtering/',
                'icon': 'bi-box-arrow-up-right',
                'is_external': True,
                'requires_settings': [_SUPPORT_LATEST_FEATURE_DOCS_SETTING_KEY],
            },
        ],
        'images': [
            {
                'path': 'images/features/workspace_tags.png',
                'alt': 'Workspace tag management screenshot',
                'title': 'Workspace Tags',
                'caption': 'Workspace tag-management experience for creating, organizing, and reusing document tags.',
                'label': 'Tag Management',
            },
        ],
    },
    {
        'id': 'workspace_folder_view',
        'title': 'Workspace Folder View',
        'icon': 'bi-grid-3x3-gap',
        'summary': 'Workspace documents can be viewed in a folder-style grid with tag-based drill-down, counts, search, and saved display preferences.',
        'details': 'Workspace Folder View adds a more visual document-browsing mode for tag-heavy workspaces where users want to scan categories before opening the underlying files.',
        'why': 'This matters because large workspaces become easier to browse when users can move between list and folder-style views depending on whether they are searching for one file or surveying a whole category.',
        'guidance': [
            'Switch to folder view when you want to browse by tag grouping instead of scanning a flat document table.',
            'Use in-folder search when a tag contains many documents and you still need to narrow within that bucket.',
            'The original release guide covers folder view together with tag workflows and chat filtering because those experiences were introduced together.',
        ],
        'actions': [
            {
                'label': 'Open Workspace Grid View',
                'description': 'Open Personal Workspace and switch straight into the folder-style grid view.',
                'href': '/workspace?feature_action=workspace_folder_view',
                'icon': 'bi-box-arrow-in-right',
            },
            {
                'label': 'Read Folder View Guide',
                'description': 'Open the public release guide covering tags, folder view, and chat filtering.',
                'href': 'https://microsoft.github.io/simplechat/latest-release/tags-grid-view-chat-filtering/',
                'icon': 'bi-box-arrow-up-right',
                'is_external': True,
                'requires_settings': [_SUPPORT_LATEST_FEATURE_DOCS_SETTING_KEY],
            },
        ],
        'images': [
            {
                'path': 'images/features/workspace_grid_view.png',
                'alt': 'Workspace grid view screenshot',
                'title': 'Workspace Folder Grid View',
                'caption': 'Folder-style grid view for browsing workspace documents through tag-driven groupings.',
                'label': 'Grid View',
            },
        ],
    },
    {
        'id': 'multi_workspace_scope_management',
        'title': 'Multi-Workspace Scope Management',
        'icon': 'bi-diagram-3',
        'summary': 'Chat can span personal, multiple group, and multiple public workspaces together, with selection freezing after the first grounded search when locking is enabled.',
        'details': 'Multi-Workspace Scope Management expands chat scope selection so users can compose a conversation context from more than one workspace at a time before the grounded search lock takes effect.',
        'why': 'This matters because many real workflows depend on combining evidence from multiple approved workspaces, but that needs clearer selection controls and more predictable locking behavior.',
        'guidance': [
            'Select the needed personal, group, and public scopes before the first grounded search if you expect to work across multiple sources.',
            'Use the lock behavior as a signal that the conversation has now committed to the chosen evidence boundary.',
            'Review the combined guide if you want the original walkthrough for multi-scope chat, document filters, and tag-aware narrowing.',
        ],
        'actions': [
            {
                'label': 'Open Scope Menu',
                'description': 'Open Chat, expand grounded search, and show the multi-workspace scope picker.',
                'href': '/chats?feature_action=multi_workspace_scope_management',
                'icon': 'bi-box-arrow-in-right',
            },
            {
                'label': 'Read Multi-Scope Guide',
                'description': 'Open the public release guide covering multi-workspace scope management and chat filtering.',
                'href': 'https://microsoft.github.io/simplechat/latest-release/tags-grid-view-chat-filtering/',
                'icon': 'bi-box-arrow-up-right',
                'is_external': True,
                'requires_settings': [_SUPPORT_LATEST_FEATURE_DOCS_SETTING_KEY],
            },
        ],
        'images': [
            {
                'path': 'images/features/workspace_scopes_in_chat.png',
                'alt': 'Workspace scopes in chat screenshot',
                'title': 'Workspace Scopes in Chat',
                'caption': 'Chat interface showing how multiple workspace scopes can be selected together before the conversation locks.',
                'label': 'Workspace Scopes',
            },
        ],
    },
    {
        'id': 'chat_document_and_tag_filtering',
        'title': 'Chat Document and Tag Filtering',
        'icon': 'bi-funnel',
        'summary': 'Chat filtering moved from a single-document dropdown to multi-document and multi-tag checkboxes that work across selected workspaces.',
        'details': 'Chat Document and Tag Filtering gives users a more explicit way to narrow grounded chat context to the exact documents and tags they want included.',
        'why': 'This matters because grounded chat gets more predictable when users can select a precise subset of source material instead of relying on one dropdown or a broad workspace search.',
        'guidance': [
            'Use multi-document selection when you know the exact sources that should ground the conversation.',
            'Use multi-tag filtering when the relevant documents share a reusable label but live across several workspaces.',
            'Open the combined release guide when you want the original walkthrough for tags, folder view, and chat filtering as one workflow.',
        ],
        'actions': [
            {
                'label': 'Open Chat Tag Filters',
                'description': 'Open Chat, expand grounded search, and show the tag-filtering controls.',
                'href': '/chats?feature_action=chat_document_and_tag_filtering',
                'icon': 'bi-box-arrow-in-right',
            },
            {
                'label': 'Read Filtering Guide',
                'description': 'Open the public release guide covering chat document and tag filtering.',
                'href': 'https://microsoft.github.io/simplechat/latest-release/tags-grid-view-chat-filtering/',
                'icon': 'bi-box-arrow-up-right',
                'is_external': True,
                'requires_settings': [_SUPPORT_LATEST_FEATURE_DOCS_SETTING_KEY],
            },
        ],
        'images': [
            {
                'path': 'images/features/chat_tags_including_doc_classification.png',
                'alt': 'Chat tags including document classification screenshot',
                'title': 'Chat Tag and Classification Filtering',
                'caption': 'Chat filtering experience showing tags and document classifications together when narrowing grounded sources.',
                'label': 'Tag and Classification Filters',
            },
        ],
    },
]

_SUPPORT_LATEST_FEATURE_RELEASE_GROUPS = [
    {
        'id': 'current_release',
        'label': 'Latest Features',
        'description': 'The newest feature set your admins are currently sharing with end users.',
        'release_version': None,
        'default_expanded': True,
        'collapse_id': 'supportLatestFeaturesCurrentRelease',
        'features': _SUPPORT_LATEST_FEATURE_CATALOG,
    },
    {
        'id': 'previous_release',
        'label': 'Previous Release Features',
        'description': 'Highlights carried forward from the earlier v0.239.001 release set so users can still find the last major round of feature announcements.',
        'release_version': '0.239.001',
        'default_expanded': False,
        'collapse_id': 'supportLatestFeaturesPreviousRelease',
        'features': _SUPPORT_PREVIOUS_RELEASE_FEATURE_CATALOG,
    },
]


def _flatten_support_feature_groups(feature_groups):
    """Return a flat list of features from grouped latest-feature metadata."""
    flattened = []
    for feature_group in feature_groups:
        for feature in feature_group.get('features', []):
            feature_copy = deepcopy(feature)
            feature_copy['release_group_id'] = feature_group.get('id')
            feature_copy['release_group_label'] = feature_group.get('label')
            feature_copy['release_version'] = feature_group.get('release_version')
            flattened.append(feature_copy)

    return flattened


def _setting_enabled(settings, key):
    """Return True when the named setting is enabled."""
    value = (settings or {}).get(key, False)
    if isinstance(value, str):
        return value.strip().lower() == 'true'
    return bool(value)


def _action_enabled(action, settings):
    """Return True when an action should be exposed for the current settings."""
    required_settings = action.get('requires_settings', [])
    return all(_setting_enabled(settings, setting_key) for setting_key in required_settings)


def _normalize_feature_media(feature):
    """Ensure every visible feature exposes at least one image entry for the template."""
    images = feature.get('images') or []
    if images:
        if not feature.get('image'):
            feature['image'] = images[0].get('path')
            feature['image_alt'] = images[0].get('alt', '')
        return

    image_path = feature.get('image')
    if not image_path:
        return

    feature['images'] = [
        {
            'path': image_path,
            'alt': feature.get('image_alt') or f"{feature.get('title', 'Feature')} screenshot",
            'title': feature.get('title', 'Feature Preview'),
            'caption': feature.get('summary', ''),
            'label': feature.get('title', 'Preview'),
        }
    ]


def get_support_latest_feature_catalog():
    """Return a copy of the support latest-features catalog."""
    return _flatten_support_feature_groups(_SUPPORT_LATEST_FEATURE_RELEASE_GROUPS)


def get_support_latest_feature_release_groups():
    """Return grouped latest-feature metadata organized by release."""
    return deepcopy(_SUPPORT_LATEST_FEATURE_RELEASE_GROUPS)


def get_default_support_latest_features_visibility():
    """Return default visibility for each user-facing latest feature."""
    defaults = {
        item['id']: True
        for item in _flatten_support_feature_groups(_SUPPORT_LATEST_FEATURE_RELEASE_GROUPS)
    }
    defaults['deployment'] = False
    defaults['redis_key_vault'] = False
    return defaults


def normalize_support_latest_features_visibility(raw_visibility):
    """Normalize persisted latest-feature visibility to the current catalog."""
    defaults = get_default_support_latest_features_visibility()
    if not isinstance(raw_visibility, dict):
        return defaults

    normalized = defaults.copy()
    for feature_id in defaults:
        if feature_id in raw_visibility:
            normalized[feature_id] = bool(raw_visibility.get(feature_id))

    return normalized


def get_visible_support_latest_features(settings):
    """Return the subset of latest-feature entries enabled for end users."""
    normalized_visibility = normalize_support_latest_features_visibility(
        (settings or {}).get('support_latest_features_visibility', {})
    )
    app_title = _resolve_support_application_title(settings)
    visible_items = []

    for item in _SUPPORT_LATEST_FEATURE_CATALOG:
        if normalized_visibility.get(item['id'], True):
            visible_item = deepcopy(item)
            visible_item['actions'] = [
                action for action in visible_item.get('actions', [])
                if _action_enabled(action, settings)
            ]
            visible_item = _apply_support_application_title(visible_item, app_title)
            _normalize_feature_media(visible_item)
            visible_items.append(visible_item)

    return visible_items


def get_visible_support_latest_feature_groups(settings):
    """Return visible latest-feature entries grouped by release metadata."""
    normalized_visibility = normalize_support_latest_features_visibility(
        (settings or {}).get('support_latest_features_visibility', {})
    )
    app_title = _resolve_support_application_title(settings)
    visible_groups = []

    for feature_group in _SUPPORT_LATEST_FEATURE_RELEASE_GROUPS:
        visible_features = []
        for feature in feature_group.get('features', []):
            if not normalized_visibility.get(feature['id'], True):
                continue

            visible_feature = deepcopy(feature)
            visible_feature['actions'] = [
                action for action in visible_feature.get('actions', [])
                if _action_enabled(action, settings)
            ]
            visible_feature = _apply_support_application_title(visible_feature, app_title)
            _normalize_feature_media(visible_feature)
            visible_features.append(visible_feature)

        if visible_features:
            visible_group = deepcopy(feature_group)
            visible_group['features'] = visible_features
            visible_group = _apply_support_application_title(visible_group, app_title)
            visible_groups.append(visible_group)

    return visible_groups


def get_support_latest_feature_release_groups_for_settings(settings):
    """Return grouped latest-feature metadata with actions filtered for the current settings."""
    filtered_groups = deepcopy(_SUPPORT_LATEST_FEATURE_RELEASE_GROUPS)
    app_title = _resolve_support_application_title(settings)

    for feature_group in filtered_groups:
        for feature in feature_group.get('features', []):
            feature['actions'] = [
                action for action in feature.get('actions', [])
                if _action_enabled(action, settings)
            ]
            feature.update(_apply_support_application_title(feature, app_title))
            _normalize_feature_media(feature)

        feature_group.update(_apply_support_application_title(feature_group, app_title))

    return filtered_groups


def has_visible_support_latest_features(settings):
    """Return True when at least one latest-feature entry is enabled for users."""
    normalized_visibility = normalize_support_latest_features_visibility(
        (settings or {}).get('support_latest_features_visibility', {})
    )
    return any(normalized_visibility.values())