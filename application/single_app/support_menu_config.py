# support_menu_config.py
"""Shared support menu configuration for user and admin latest features."""

from copy import deepcopy


_SUPPORT_LATEST_FEATURE_DOCS_SETTING_KEY = 'enable_support_latest_feature_documentation_links'


def _latest_feature_card(feature_id, title, icon, summary, details, why, guidance, actions=None, image_label=None, image_title=None, image_caption=None, image_name=None, include_media=True):
    """Build a latest-feature catalog entry with optional screenshot metadata."""
    if not include_media:
        return {
            'id': feature_id,
            'title': title,
            'icon': icon,
            'summary': summary,
            'details': details,
            'why': why,
            'guidance': guidance,
            'actions': actions or [],
            'image': '',
            'image_alt': '',
            'images': [],
        }

    image_file = image_name or f"{feature_id}.png"
    image_path = f"images/features/{image_file}"
    label = image_label or title
    return {
        'id': feature_id,
        'title': title,
        'icon': icon,
        'summary': summary,
        'details': details,
        'why': why,
        'guidance': guidance,
        'actions': actions or [],
        'image': image_path,
        'image_alt': f"{title} screenshot placeholder",
        'images': [
            {
                'path': image_path,
                'alt': f"{title} screenshot placeholder",
                'title': image_title or title,
                'caption': image_caption or f"Screenshot placeholder for {title}.",
                'label': label,
            },
        ],
    }


_SUPPORT_LATEST_FEATURE_CATALOG = [
    _latest_feature_card(
        'release_250_ai_access',
        'Personalized Model and Agent Access',
        'bi-person-check',
        'Model and agent access can now be assigned to specific users or groups, so different people can see the AI capabilities approved for their work.',
        'SimpleChat now supports governed access to models, agents, and actions. You may see model or agent choices that are different from another user because admins can assign capabilities to individuals, groups, or broader audiences.',
        'This matters because teams can make powerful AI tools available to the right people without turning every model or agent on for everyone.',
        ['Open Chat and review the model and agent pickers to see what is available to you.', 'If you do not see a model, agent, or action you expected, it may be controlled by an admin governance policy.', 'Group-scoped agents and models can appear when you are working in an approved group context.'],
        actions=[{'label': 'Open Chat', 'description': 'Review available models and agents from Chat.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'}, {'label': 'Open Agents', 'description': 'Browse agents available to your account.', 'href': '/agents', 'icon': 'bi-robot', 'requires_settings': ['enable_semantic_kernel']}],
        image_label='Approved Access',
    ),
    _latest_feature_card(
        'release_250_agents_catalog',
        'Agents Catalog',
        'bi-robot',
        'Users can browse a dedicated agents catalog to find specialized AI partners across popular, personal, group, and enterprise agent collections.',
        'The Agents Catalog gives users a searchable discovery experience for approved agents. Catalog tabs help users scan popular, personal, group, and enterprise agents, then launch a chat or inspect details from the same page.',
        'This matters because users can discover the right agent for a task without already knowing its name or workspace source.',
        ['Open Agents to browse available catalog entries.', 'Use search when you know the topic, skill, workflow, or agent name you need.', 'Review Popular, Personal, Group, and Enterprise tabs to understand which agents are available in each context.'],
        actions=[{'label': 'Open Agents', 'description': 'Browse the agents catalog.', 'href': '/agents', 'icon': 'bi-robot', 'requires_settings': ['enable_semantic_kernel']}],
        image_label='Agents Catalog',
        image_title='Find Your Next AI Partner',
        image_caption='The Agents Catalog helps users search and browse specialized agents across popular, personal, group, and enterprise collections.',
        image_name='release_250_agents_catalog.png',
    ),
    _latest_feature_card(
        'release_250_tabular_analysis',
        'Improved Tabular Analysis',
        'bi-table',
        'Tabular analysis for CSV and Excel files can now page through larger results, preserve sheet context, use related document evidence, and create clearer chart or export outputs.',
        'SimpleChat continues to expand tabular analysis so questions over workbooks and CSV files are answered from computed results instead of guesses. Large result pagination, sheet-aware context, related-document evidence, and chart handoff make workbook answers more useful.',
        'This matters because spreadsheet questions often need exact calculations, filtered rows, grouped results, and reusable exports rather than a short text summary.',
        ['Ask questions against CSV, XLSX, XLS, or XLSM files from Chat or workspace search.', 'Use generated charts or downloadable artifacts when the result is too large to fit cleanly in a message.', 'For multi-sheet workbooks, ask with the sheet name when you know which tab matters.'],
        actions=[{'label': 'Open Chat', 'description': 'Ask a question about a spreadsheet from Chat.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'}],
        image_label='Tabular Analysis',
    ),
    _latest_feature_card(
        'release_250_charts',
        'Chart Creation in Chat',
        'bi-bar-chart-line',
        'Users can now ask SimpleChat to create charts directly in conversation, whether they are exploring pasted data, tabular files, spreadsheet results, or other structured information.',
        'Chart creation turns data-focused prompts into visual answers. Ask for a bar chart, line chart, pie chart, or another useful view while working with CSV, Excel, tables, or computed data from the conversation.',
        'This matters because trends, comparisons, outliers, and summaries are often easier to understand when the assistant can turn the data into a visual in real time.',
        ['Ask Chat to create a chart from tabular data, spreadsheet results, or structured values in the conversation.', 'Use chart requests when you need to compare categories, show trends over time, summarize proportions, or inspect outliers.', 'Pair chart prompts with uploaded CSV or Excel files when the visualization should be grounded in workspace-backed data.'],
        actions=[{'label': 'Open Chat', 'description': 'Ask for a chart from data in your conversation.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'}],
        image_label='Chart Creation',
        image_title='Create Charts from Data in Chat',
        image_caption='Chart creation helps users visualize pasted values, tabular files, spreadsheet answers, and other structured data directly from the conversation.',
    ),
    _latest_feature_card(
        'release_250_custom_pages',
        'Custom Pages',
        'bi-window-plus',
        'Admins can publish trusted internal custom pages, giving users new in-app pages for local guidance, dashboards, forms, or lightweight tools.',
        'Custom Pages let your organization add authenticated experiences inside SimpleChat. Users may see new pages that help with onboarding, request intake, process guidance, or organization-specific workflows.',
        'This matters because teams can tailor SimpleChat to local workflows without sending users to a separate unauthenticated site.',
        ['Look for custom pages in navigation when your admins publish them.', 'Use custom request or guidance pages as part of your normal SimpleChat workflow.', 'If a page is missing or unavailable, it may be disabled or awaiting admin publication.'],
        actions=[],
        image_label='Custom Pages',
    ),
    _latest_feature_card(
        'release_250_tableau_action',
        'Tableau Action',
        'bi-bar-chart',
        'Users with access can ask SimpleChat to discover Tableau projects, workbooks, views, datasources, and workbook details from approved Tableau environments.',
        'The Tableau action adds a read-only way to explore Tableau Server or Tableau Cloud metadata through an approved SimpleChat action. Access may be limited by admins, workspace configuration, or Tableau credentials.',
        'This matters because users can find and reason about Tableau assets without manually switching between systems for every lookup.',
        ['Use a Tableau-enabled agent or action when you need workbook, view, datasource, or project discovery.', 'If Tableau is not available, ask an admin whether the action is enabled for your workspace or account.', 'Treat Tableau actions as read-only discovery tools unless your admins document additional behavior.'],
        actions=[{'label': 'Open Workspace Actions', 'description': 'Review actions available in your workspace.', 'href': '/workspace#plugins-tab', 'icon': 'bi-plug', 'requires_settings': ['enable_user_workspace']}],
        image_label='Tableau',
    ),
    _latest_feature_card(
        'release_250_workflows',
        'Personal and Group Workflows',
        'bi-diagram-3',
        'Users can create or run personal and group workflows for repeatable document analysis, File Sync refreshes, per-document runs, and generated Office outputs.',
        'Workflows are a major new automation surface. They can run prompts over selected documents, process each document separately, monitor File Sync changes, resume failed batches, and create Word or PowerPoint outputs when those actions are enabled.',
        'This matters because repeatable document work can move from one-off chat prompts into reusable personal or shared group automation.',
        ['Open Personal Workspace > Workflows when personal workflows are enabled for your account.', 'Open Group Workspaces to use shared group workflows when your group has access.', 'Use history and activity views to inspect completed, running, or failed workflow runs.'],
        actions=[{'label': 'Open Personal Workflows', 'description': 'Review personal workflows from your workspace.', 'href': '/workspace#workflows-tab', 'icon': 'bi-play-circle', 'requires_settings': ['enable_user_workspace']}, {'label': 'Open Group Workspaces', 'description': 'Review group workflow availability.', 'href': '/group_workspaces', 'icon': 'bi-people'}],
        image_label='Workflows',
    ),
    _latest_feature_card(
        'release_250_voice_assisted_inputs',
        'Voice-Assisted Form Inputs',
        'bi-mic',
        'Speech-to-text controls now appear in supported agent, group, public workspace, document metadata, tag, and instruction fields when speech input is enabled.',
        'Voice-assisted inputs help users draft longer instructions, metadata, descriptions, and tag values without typing everything manually. Dictated tags and keywords are normalized into safer saved values.',
        'This matters because many setup and metadata fields are easier to draft by voice, especially longer agent instructions or document descriptions.',
        ['Look for microphone controls beside supported form fields.', 'Use dictated instruction briefs to draft agent instructions, then review and edit before saving.', 'Expect this pattern to expand to more form fields over time.'],
        actions=[{'label': 'Open Workspace Agents', 'description': 'Try voice drafting in agent setup when enabled.', 'href': '/workspace#agents-tab', 'icon': 'bi-robot', 'requires_settings': ['enable_user_workspace']}],
        image_label='Voice Inputs',
    ),
    _latest_feature_card(
        'release_250_m365_actions',
        'Microsoft 365 Actions',
        'bi-envelope-paper',
        'Microsoft Graph actions expand M365 support so approved users can work with mail, drafts, calendar details, and calendar invites from SimpleChat.',
        'The Microsoft Graph action family can support user mailbox and calendar workflows, including creating drafts, delayed-delivery drafts, sending mail, and working with calendar information when configured by admins.',
        'This matters because common M365 tasks can become part of an agent-assisted workflow instead of requiring manual copying between apps.',
        ['Use an M365-enabled action or agent when you need email or calendar assistance.', 'Review prepared drafts before sending when your environment uses manual draft mode.', 'If M365 actions are unavailable, admins may need to grant scopes or enable the action for your workspace.'],
        actions=[{'label': 'Open Workspace Actions', 'description': 'Review available M365-related actions.', 'href': '/workspace#plugins-tab', 'icon': 'bi-plug', 'requires_settings': ['enable_user_workspace']}],
        image_label='M365 Actions',
    ),
    _latest_feature_card(
        'release_250_chat_uploads',
        'Workspace-Backed Chat Uploads and Paste Support',
        'bi-paperclip',
        'Chat uploads now behave more like workspace uploads, and users can paste or drag files and images directly into the chat input.',
        'Files uploaded from chat can become linked workspace documents with processing progress, search context, citations, and document lifecycle choices. Clipboard paste and drag-and-drop make it faster to get files, screenshots, and images into a conversation.',
        'This matters because users no longer need to decide whether chat or workspace upload is the right path before they start working with a file.',
        ['Paste copied images or files into Chat, or drag files into the chat input when uploads are enabled.', 'Review upload progress in the conversation while workspace processing continues.', 'When deleting a conversation, choose whether linked workspace documents should be deleted or kept.'],
        actions=[{'label': 'Open Chat', 'description': 'Try paste, drag, or file upload from Chat.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'}],
        image_label='Chat Uploads',
    ),
    _latest_feature_card(
        'release_250_document_intelligence',
        'Enhanced Document Intelligence',
        'bi-file-earmark-richtext',
        'Enhanced extraction can capture richer PDF and image structure, including tables, layout, and selection marks, and users can reprocess eligible documents from workspaces.',
        'Document Intelligence now supports Standard, Enhanced, and Auto extraction paths. Users benefit from richer structure when documents need it and can change extraction for stored PDFs when reprocessing is available.',
        'This matters because some documents need more than plain text extraction to answer accurately, especially forms, tables, scanned PDFs, and image-heavy files.',
        ['Check document details for extraction and citation badges.', 'Use Change Extraction when a stored PDF should be reprocessed with a richer or faster mode.', 'Expect Enhanced extraction to take longer and cost more when admins enable it for richer structure.'],
        actions=[{'label': 'Open Workspace Documents', 'description': 'Review extraction badges and Change Extraction actions.', 'href': '/workspace#documents-tab', 'icon': 'bi-folder2-open', 'requires_settings': ['enable_user_workspace']}],
        image_label='Document Extraction',
    ),
    _latest_feature_card(
        'release_250_file_sync',
        'File Sync for SMB and Azure Files',
        'bi-arrow-repeat',
        'File Sync can bring SMB share and Azure Files content into workspaces, with reusable identities and workflow triggers for automated refreshes.',
        'Users can configure sync sources where enabled, use identities for credentials, review synced-document badges, and connect sync sources to workflows that run before or after file changes. Additional sync providers are planned for future releases.',
        'This matters because workspace documents can stay closer to authoritative file shares instead of depending on repeated manual uploads.',
        ['Use Workspace > Sync to configure SMB or Azure Files sources when admins enable File Sync.', 'Use Workspace > Identities to reuse credentials for sync sources and actions.', 'Use workflows with File Sync triggers when analysis should run after synced content changes.'],
        actions=[{'label': 'Open Workspace Sync', 'description': 'Review sync sources and run history.', 'href': '/workspace?feature_action=file_sync', 'icon': 'bi-arrow-repeat', 'requires_settings': ['enable_user_workspace']}, {'label': 'Open Workspace Identities', 'description': 'Review reusable identities for sync and actions.', 'href': '/workspace#identities-tab', 'icon': 'bi-person-badge', 'requires_settings': ['enable_user_workspace']}],
        image_label='File Sync',
    ),
    _latest_feature_card(
        'release_250_conversation_feed',
        'Faster Conversation Lists',
        'bi-chat-left-text',
        'Conversation lists now load in pages, improving startup performance for users with large chat histories.',
        'Chat startup now loads pinned, unread, and recent conversations first, then loads more as needed. Search can still query titles beyond the currently loaded page.',
        'This matters because large conversation histories should not slow down everyday chat startup.',
        ['Use Load More or scroll near the bottom of the conversation list to bring in older conversations.', 'Use title search when you need a conversation that is not loaded on the current page.', 'Hidden conversations stay out of the default feed until you enable the hidden-conversation toggle.'],
        actions=[{'label': 'Open Chat', 'description': 'Review the paged conversation list.', 'href': '/chats', 'icon': 'bi-chat-dots'}],
        image_label='Conversation Feed',
    ),
    _latest_feature_card(
        'release_250_group_file_sharing',
        'Group File Sharing and Approvals',
        'bi-share',
        'Users can share personal or group documents with groups, and receiving groups can approve shared files before they become searchable.',
        'Group file sharing adds notifications, approval decisions, and safer ownership boundaries so shared files can move between groups without giving the receiving group control over the source document.',
        'This matters because collaboration often crosses workspace boundaries, but shared documents still need review and clear ownership.',
        ['Share documents with groups when a file should be available to another team.', 'Receiving group owners, admins, or document managers can approve or remove shared files.', 'Watch notifications for share requests, approvals, and denials.'],
        actions=[{'label': 'Open Group Workspaces', 'description': 'Review shared documents and group approvals.', 'href': '/group_workspaces', 'icon': 'bi-people'}],
        image_label='Group Sharing',
    ),
    _latest_feature_card(
        'release_250_profile_stats',
        'Profile, Stats, and Preferences',
        'bi-person-lines-fill',
        'Profile now brings together stats, groups, public workspaces, feedback, safety items, preferences, and CSV exports in a clearer experience.',
        'Users can review activity windows, export stats, manage settings, inspect group and public workspace membership, and tune navigation, tutorial, memory, speech, and voice preferences from Profile.',
        'This matters because users can understand their own activity and manage everyday preferences without needing an admin to change global settings.',
        ['Open Profile > Stats to review 7-day, 30-day, 90-day, or custom reporting windows.', 'Use Profile tabs to review groups, public workspaces, feedback, and safety items.', 'Use Profile > Settings to control navigation state, tutorial visibility, memories, speech, and voice preferences.'],
        actions=[{'label': 'Open Profile Stats', 'description': 'Review your activity and export options.', 'href': '/profile?tab=stats#profile-stats-pane', 'icon': 'bi-person-lines-fill'}, {'label': 'Open Profile Settings', 'description': 'Review profile preferences.', 'href': '/profile?tab=settings#profile-settings-pane', 'icon': 'bi-person-gear'}],
        image_label='Profile',
    ),
    _latest_feature_card(
        'release_250_databricks_action',
        'Databricks Action',
        'bi-database',
        'Users with access can use approved Databricks actions to run governed read-only SQL against Azure Commercial Databricks workspaces.',
        'The Databricks action connects to Databricks SQL Statement Execution APIs with configured warehouses, catalogs, schemas, identities, and limits. Admins may gate access by user, group, or workspace.',
        'This matters because analytics data can be queried from SimpleChat without giving every user direct database tooling.',
        ['Use a Databricks-enabled action or agent when your admin has made it available.', 'Ask your admin for access if the action is not available in your workspace.', 'Expect Databricks actions to be read-only and governed by configured limits.'],
        actions=[{'label': 'Open Workspace Actions', 'description': 'Review available data actions.', 'href': '/workspace#plugins-tab', 'icon': 'bi-plug', 'requires_settings': ['enable_user_workspace']}],
        image_label='Databricks',
    ),
    _latest_feature_card(
        'release_250_layered_masking',
        'Layered Message Masking',
        'bi-mask',
        'Users can now apply multiple selected-text masks to the same message, including shared personal and group conversations.',
        'Mask-plus and mask-minus controls let you layer selected-text masks independently from full-message masks. In collaborative conversations, masking metadata follows shared event updates while display names are bound to the authenticated user.',
        'This matters because users can hide multiple sensitive ranges in a message without losing control over previous masks.',
        ['Use selected-text masking when only part of a message needs to be hidden.', 'Use full-message masking when the entire message should be covered.', 'Layered masks can be managed independently so one mask can be removed without clearing all others.'],
        actions=[{'label': 'Open Chat', 'description': 'Try masking on a chat message.', 'href': '/chats', 'icon': 'bi-chat-dots'}],
        image_label='Message Masking',
    ),
    _latest_feature_card(
        'release_250_visio_msg_ingestion',
        'Visio and Outlook MSG File Support',
        'bi-file-earmark-text',
        'Users can upload Visio `.vsdx` diagrams and Outlook `.msg` email files so more everyday work artifacts can become searchable knowledge.',
        'Visio ingestion indexes diagram pages and supports citation previews. Outlook MSG ingestion lets saved email files participate in the document processing pipeline so conversations can reason over email content and metadata.',
        'This matters because architecture diagrams, process diagrams, and email files often contain important context that should not be trapped outside workspace search.',
        ['Upload `.vsdx` diagrams when shapes, pages, and connectors should become searchable.', 'Upload `.msg` files when saved Outlook email needs to be processed as workspace knowledge.', 'Use enhanced citations to inspect previews or original files where supported.'],
        actions=[{'label': 'Open Workspace Documents', 'description': 'Upload Visio or Outlook MSG files to a workspace.', 'href': '/workspace#documents-tab', 'icon': 'bi-folder2-open', 'requires_settings': ['enable_user_workspace']}],
        image_label='Visio and MSG',
    ),
    _latest_feature_card(
        'release_250_assigned_knowledge',
        'Assigned Knowledge for Agents',
        'bi-diagram-2',
        'Agents can be bound to specific workspace sources, documents, and tags so they answer from the knowledge selected for their role.',
        'Assigned Knowledge lets agent creators define the search scope an agent should use. When you select an assigned-knowledge agent in Chat, workspace search is enforced and the relevant scope controls become read-only.',
        'This matters because specialized agents can stay focused on the knowledge they were designed to use.',
        ['Use assigned-knowledge agents when you need a purpose-built assistant for a known document set.', 'Review the knowledge context shown in Chat when an assigned-knowledge agent is selected.', 'Agent creators can configure workspace sources, documents, tags, and available actions during setup.'],
        actions=[{'label': 'Open Agents', 'description': 'Browse assigned-knowledge agents.', 'href': '/agents', 'icon': 'bi-robot', 'requires_settings': ['enable_semantic_kernel']}],
        image_label='Assigned Knowledge',
    ),
    _latest_feature_card(
        'release_250_deep_research',
        'Deep Research and Source Review',
        'bi-search-heart',
        'Deep Research and Source Review can inspect web evidence more deeply with bounded traversal, source citation seeding, load-more support, and optional model-assisted link planning.',
        'When enabled, SimpleChat can review pasted URLs and web-search citations, inspect source pages, follow relevant links under admin limits, and surface better evidence for web-grounded answers.',
        'This matters because web-grounded answers are more useful when they are based on reviewed source pages instead of snippets alone.',
        ['Use Sources or Deep Research when your answer depends on current web evidence.', 'Review citations and thoughts to understand which source pages were inspected.', 'If Deep Research is unavailable, admins may need to enable it for your account or domain policy.'],
        actions=[{'label': 'Try Sources in Chat', 'description': 'Use Source Review or Deep Research from Chat.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'}],
        image_label='Deep Research',
    ),
    _latest_feature_card(
        'release_250_url_access',
        'URL Access in Chat',
        'bi-link-45deg',
        'Users can paste URLs into Chat and have SimpleChat treat them as source links or plain text depending on the workflow and admin policy.',
        'URL Access gives users a clearer way to bring web pages into a conversation while letting admins control safety policy, allowed domains, blocklists, page budgets, and source-review behavior.',
        'This matters because links are a natural way to bring external context into a chat, but they need bounded, policy-aware handling.',
        ['Paste a URL into Chat when you want SimpleChat to consider a source page.', 'Use plain text when you want to discuss a URL string without fetching it.', 'If a URL is blocked, it may be restricted by domain policy or safety controls.'],
        actions=[{'label': 'Open Chat', 'description': 'Paste a URL into Chat.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'}],
        image_label='URL Access',
    ),
    _latest_feature_card(
        'release_250_source_continuity',
        'Conversation Source Continuity',
        'bi-journal-text',
        'Chat can now reuse document and citation context from earlier turns, reducing the need to reselect the same documents throughout a conversation.',
        'Stored citation results and document context can be replayed into later turns so follow-up questions can use the files and evidence already established in the conversation history.',
        'This matters because multi-turn document conversations should remember the source trail you already built instead of making you start over every prompt.',
        ['Ask follow-up questions after a document-grounded answer without reselecting the same documents every time.', 'Use citations to confirm which prior evidence was reused.', 'For new source material, update the workspace or document selection before asking the next question.'],
        actions=[{'label': 'Open Chat', 'description': 'Ask follow-up questions in a grounded conversation.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'}],
        image_label='Source Continuity',
    ),
    _latest_feature_card(
        'release_250_generated_documents',
        'Generated Markdown, Word, and PowerPoint Files',
        'bi-file-earmark-arrow-up',
        'Agents and workflows can now create reusable Markdown, Word, and PowerPoint outputs that users can inspect, download, or promote into workspaces.',
        'Generated artifact cards make structured outputs easier to reuse. Markdown can be viewed in Chat, generated Office files can support workflow outputs, and reusable artifacts can become workspace documents with approval where needed.',
        'This matters because important results should become durable files when users need reports, decks, summaries, or workspace knowledge.',
        ['Use generated artifact cards to view or download outputs from Chat.', 'Use Add to Workspace when a generated output should become searchable knowledge.', 'Use workflows when repeatable document analysis should produce Word or PowerPoint outputs.'],
        actions=[{'label': 'Open Chat', 'description': 'Generate and inspect artifacts from Chat.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'}],
        image_label='Generated Files',
    ),
    _latest_feature_card(
        'release_250_multi_inline_image_gen',
        'Multi Inline Image Generation',
        'bi-images',
        'Chat can now create multiple inline images from one request, and model responses can propose useful images during an answer for you to approve before generation.',
        'Image generation now supports richer conversational workflows. You can ask for several images in a single prompt, and models can suggest images that would help explain or complete an answer while keeping generation behind an approval step.',
        'This matters because image creation can become part of the conversation flow without forcing users to send one image request at a time or accept unapproved generated media.',
        ['Ask Chat to create multiple related images in one request when you need a set of options, variations, or supporting visuals.', 'Review proposed images from assistant responses before approving generation.', 'Use inline image cards to inspect generated images directly in the conversation.'],
        actions=[{'label': 'Open Chat', 'description': 'Create or approve inline images from Chat.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'}],
        image_label='Inline Images',
        image_title='Create Multiple Inline Images in Chat',
        image_caption='Multi inline image generation lets users request several images at once and approve image ideas that the assistant proposes while generating a response.',
    ),
    _latest_feature_card(
        'release_250_workspace_views',
        'Workspace Cards and Folder Views',
        'bi-grid-3x3-gap',
        'Workspace documents can now be browsed in list, card, folder, and folder-plus-card views with improved multi-select and action behavior.',
        'Cards and folder-card views help users scan files visually, browse by tags, review document details, and open document actions from personal, group, and public workspaces.',
        'This matters because large workspaces are easier to navigate when users can choose the browsing mode that fits the task.',
        ['Use List for dense scanning, Cards for visual browsing, Folders for tag-first navigation, and Folders + Cards for both together.', 'Use visible-only select-all and multi-select tools for bulk cleanup or organization.', 'Click cards to open document actions such as Chat, Edit, Select, or management controls.'],
        actions=[{'label': 'Open Workspace Documents', 'description': 'Try document card and folder views.', 'href': '/workspace#documents-tab', 'icon': 'bi-folder2-open', 'requires_settings': ['enable_user_workspace']}],
        image_label='Workspace Views',
    ),
    _latest_feature_card(
        'release_250_follow_up_actions',
        'Assistant Follow-Up Actions',
        'bi-arrow-right-circle',
        'Assistant responses can now show suggested next-step buttons that stage the prompt and start a cancelable send countdown.',
        'When a response includes supported next-step suggestions, SimpleChat can render them as clickable prompt actions below the assistant message. Users can continue a workflow without copying and pasting suggested text.',
        'This matters because useful assistant suggestions become one-click follow-up actions while users stay in control before sending.',
        ['Click a suggested follow-up action when it matches what you want to do next.', 'Use the countdown window to cancel before the prompt is sent.', 'Edit the staged prompt if you want to customize the next step.'],
        actions=[{'label': 'Open Chat', 'description': 'Try follow-up actions from assistant responses.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'}],
        image_label='Follow-Up Actions',
    ),
    _latest_feature_card(
        'release_250_model_agent_avatars',
        'Model and Agent Avatars',
        'bi-person-square',
        'Model endpoint icons and uploaded model images now make model-only responses easier to recognize, while agent avatars remain prioritized for agent replies.',
        'When admins configure model icons or images, users can see a clearer visual identity on model-only assistant responses. Agent responses keep their agent identity so users can distinguish the source of an answer.',
        'This matters because visual identity helps users understand whether a response came from a selected model or an agent.',
        ['Look for model icons on model-only assistant messages.', 'Agent avatars still take priority when a response comes from an agent.', 'Admins can configure model endpoint icons and images from endpoint setup.'],
        actions=[{'label': 'Open Chat', 'description': 'Review model or agent avatars in conversation responses.', 'href': '/chats', 'icon': 'bi-chat-dots'}],
        image_label='Avatars',
    ),
]


_SUPPORT_ADMIN_LATEST_FEATURE_CURRENT_CATALOG = [
    _latest_feature_card(
        'admin_release_250_azure_openai_identity',
        'Azure OpenAI Identity Setup',
        'bi-key',
        'Admins now get clearer setup guidance for the difference between Azure OpenAI model discovery identities and runtime data-plane identities or keys.',
        'Fetch Models uses Azure Resource Manager deployment listing through the configured app registration or service principal. Runtime chat, embeddings, file-upload embedding generation, and image generation use the configured Azure OpenAI data-plane identity or key.',
        'This matters because a successful runtime test does not always mean the management-plane Fetch Models action has the right RBAC assignment.',
        ['Screenshot idea: capture the Azure OpenAI setup guide beside model discovery fields.', 'Show where the app registration or service principal needs Cognitive Services User for model discovery.', 'Show where the App Service managed identity needs Cognitive Services OpenAI User for runtime inference.'],
        actions=[
            {'label': 'Open AI Models', 'description': 'Review Azure OpenAI model and identity setup.', 'href': '#ai-models', 'admin_tab': '#ai-models', 'icon': 'bi-cpu'},
            {'label': 'Open Legacy Model Config', 'description': 'Review legacy GPT, embedding, and image model discovery settings.', 'href': '#ai-models', 'admin_tab': '#ai-models', 'icon': 'bi-key'},
            {'label': 'Open Search and Extract', 'description': 'Review embedding and extraction dependencies that use Azure OpenAI at runtime.', 'href': '#search-extract', 'admin_tab': '#search-extract', 'icon': 'bi-search'},
        ],
        image_label='Azure OpenAI Setup',
    ),
    _latest_feature_card(
        'admin_release_250_model_endpoint_setup',
        'Model Endpoint Setup Guidance',
        'bi-hdd-network',
        'Admins now have setup guidance for Azure OpenAI, Foundry, New Foundry, provider routing, model discovery, tests, and model endpoint visual identity.',
        'The model endpoint workflow now explains provider choices, identity/RBAC needs, API-key limitations, model testing, and model icon/image setup.',
        'This matters because multi-provider model configuration is easier to roll out when setup guidance lives beside the controls.',
        ['Screenshot idea: capture Setup Guide buttons beside endpoint actions.', 'Screenshot idea: capture model icon and uploaded image controls in the endpoint modal.', 'Call out provider-specific setup for Azure OpenAI, Foundry, and New Foundry.'],
        actions=[
            {'label': 'Open AI Models', 'description': 'Review model endpoint setup.', 'href': '#ai-models', 'admin_tab': '#ai-models', 'icon': 'bi-cpu'},
            {'label': 'Open Global Endpoints', 'description': 'Manage global model endpoints and defaults.', 'href': '#model-endpoints-wrapper', 'admin_tab': '#ai-models', 'admin_section': 'model-endpoints-wrapper', 'icon': 'bi-hdd-network'},
            {'label': 'Open Governance', 'description': 'Review endpoint access policies after endpoints are configured.', 'href': '#governance', 'admin_tab': '#governance', 'icon': 'bi-shield-check'},
        ],
        image_label='Endpoint Setup',
    ),
    _latest_feature_card(
        'admin_release_250_governance',
        'Governance for Models, Agents, and Actions',
        'bi-shield-check',
        'Admins can govern who can use personal, group, and global endpoints, agents, actions, delegated items, and action types.',
        'Governance adds feature-level policies, allowlists, delegated review flows, and action-type availability so admins can roll out AI capabilities to the right users and groups.',
        'This matters because admins can now manage AI access with policy instead of only broad feature toggles.',
        ['Screenshot idea: capture the Governance tab with feature policies and delegated item policies visible.', 'Show endpoint, agent, action, and action-type governance controls.', 'Call out review workflows for delegated personal or group capabilities.'],
        actions=[
            {'label': 'Open Governance', 'description': 'Review governance controls.', 'href': '#governance', 'admin_tab': '#governance', 'icon': 'bi-shield-check'},
            {'label': 'Feature Policies', 'description': 'Configure feature-level access policies.', 'href': '#governance-feature-policies-section', 'admin_tab': '#governance', 'admin_section': 'governance-feature-policies-section', 'icon': 'bi-list-check'},
            {'label': 'Delegated Item Policies', 'description': 'Review endpoint, agent, and action item policies.', 'href': '#governance-item-policies-section', 'admin_tab': '#governance', 'admin_section': 'governance-item-policies-section', 'icon': 'bi-person-check'},
        ],
        image_label='Governance',
    ),
    _latest_feature_card(
        'admin_release_250_cache_performance',
        'Settings Cache Performance',
        'bi-speedometer',
        'Admins benefit from request-scoped user settings caching and cache-version coordination for settings and governance changes.',
        'User settings reads are memoized during requests, lightweight UI preferences can load without full settings calls, and cache-version coordination reduces stale reads across Redis and no-Redis deployments.',
        'This matters because admin setting changes should take effect predictably while keeping hot-path reads fast.',
        ['Screenshot idea: capture General or Scale settings where cache-related behavior is documented.', 'Explain that Redis-enabled and no-Redis deployments both participate in cache-version invalidation.', 'Use this card as an admin performance and reliability note rather than a user-facing feature.'],
        actions=[
            {'label': 'Open General Settings', 'description': 'Review general settings and cache-adjacent configuration.', 'href': '#general', 'admin_tab': '#general', 'icon': 'bi-gear'},
            {'label': 'Open Governance', 'description': 'Review governance settings that participate in cache versioning.', 'href': '#governance', 'admin_tab': '#governance', 'icon': 'bi-shield-check'},
            {'label': 'Open Scale Settings', 'description': 'Review Redis and scaling settings used by shared cache paths.', 'href': '#scale', 'admin_tab': '#scale', 'icon': 'bi-speedometer2'},
        ],
        image_label='Settings Cache',
    ),
    _latest_feature_card(
        'admin_release_250_custom_pages',
        'Custom Pages Administration',
        'bi-window-plus',
        'Admins can publish trusted custom pages with metadata, navigation, static assets, and optional reviewed Python-backed extensions.',
        'Custom Pages can host internal guidance, dashboards, request pages, and lightweight tools inside the authenticated SimpleChat shell. Admins control enablement and metadata while deployment owns the actual page assets.',
        'This matters because organizations can tailor the app experience without moving users outside SimpleChat.',
        ['Screenshot idea: capture Custom Pages enablement, metadata, and request-access controls.', 'Show how custom page navigation is configured.', 'Call out that routes fail closed while Custom Pages is disabled.'],
        actions=[
            {'label': 'Open Custom Pages', 'description': 'Review custom page administration.', 'href': '#custom-pages', 'admin_tab': '#custom-pages', 'icon': 'bi-window-plus'},
            {'label': 'Custom Pages Settings', 'description': 'Jump to the custom pages metadata and enablement section.', 'href': '#custom-pages-section', 'admin_tab': '#custom-pages', 'admin_section': 'custom-pages-section', 'icon': 'bi-window-sidebar'},
            {'label': 'Open Governance', 'description': 'Review access controls that may affect custom page experiences.', 'href': '#governance', 'admin_tab': '#governance', 'icon': 'bi-shield-check'},
        ],
        image_label='Custom Pages',
    ),
    _latest_feature_card(
        'admin_release_250_action_catalog',
        'Enterprise Action Controls',
        'bi-plug',
        'Admins can control deployment and access for Tableau, Databricks, Microsoft 365, MCP, and other enterprise actions.',
        'Action setup now includes richer enterprise connectors and admin controls for credentials, reusable identities, discovery limits, schemas, allowed transports, and governed availability.',
        'This matters because powerful enterprise integrations need central deployment and access controls before users can rely on them.',
        ['Screenshot idea: capture action type selection with Tableau, Databricks, M365, and MCP-related configuration.', 'Show where admins use identities or secrets for action credentials.', 'Call out that action access may be governed per user, group, or global scope.'],
        actions=[
            {'label': 'Open Actions', 'description': 'Review global action management.', 'href': '#plugins', 'admin_tab': '#agents', 'admin_section': 'plugins-table', 'icon': 'bi-plug'},
            {'label': 'Open Governance', 'description': 'Control who can use actions and action types.', 'href': '#governance', 'admin_tab': '#governance', 'icon': 'bi-shield-check'},
            {'label': 'Open Global Identities', 'description': 'Manage reusable identities for enterprise actions.', 'href': '#global-workspace-identities-root', 'admin_tab': '#workspace-identities', 'admin_section': 'global-workspace-identities-root', 'icon': 'bi-person-badge'},
        ],
        image_label='Enterprise Actions',
    ),
    _latest_feature_card(
        'admin_release_250_agents_catalog',
        'Agents Catalog Administration',
        'bi-robot',
        'Admins can customize the Agents page, guide users through approved agent discovery, and promote selected agents into the Popular tab.',
        'Agents page administration lets admins tune the catalog hero, colors, guidance copy, details visibility, and promoted Popular agents from Admin Settings. Promoted agents remain governed by the same visibility rules, so users only see agents they can already access.',
        'This matters because agent discovery needs local curation, governance context, and launch guidance before users can confidently pick the right AI partner.',
        ['Screenshot idea: capture Agents Page Customization with promoted Popular agents selected.', 'Show hero copy, guidance text, details visibility, and promoted tag controls.', 'Call out that promoted agents respect each user\'s existing agent access policy.'],
        actions=[
            {'label': 'Open Agents Page Settings', 'description': 'Customize the public Agents page and promoted Popular agents.', 'href': '#agents-page-customization-card', 'admin_tab': '#agents', 'admin_section': 'agents-page-customization-card', 'icon': 'bi-palette'},
            {'label': 'Open Global Agents', 'description': 'Review enterprise agents that can appear in the catalog.', 'href': '#agents-configuration', 'admin_tab': '#agents', 'admin_section': 'agents-configuration', 'icon': 'bi-robot'},
            {'label': 'Open Governance', 'description': 'Control who can access agents before they appear in the catalog.', 'href': '#governance', 'admin_tab': '#governance', 'icon': 'bi-shield-check'},
            {'label': 'Preview Agents', 'description': 'Open the user-facing Agents catalog.', 'href': '/agents', 'icon': 'bi-box-arrow-up-right'},
        ],
        image_label='Catalog Admin',
        image_title='Customize and Promote Agents',
        image_caption='Agents Catalog administration lets admins customize the Agents page experience and promote selected agents while preserving access governance.',
        image_name='admin_release_250_agents_catalog.png',
    ),
    _latest_feature_card(
        'admin_release_250_workflows',
        'Workflow Administration',
        'bi-diagram-3',
        'Admins can enable personal workflows, require WorkflowUser, enable group workflows, assign groups, and govern workflow-related capabilities.',
        'Workflow administration covers personal and group workflow rollout, app-role gating, group assignment, owner-only management policies, and generated Office upload capabilities.',
        'This matters because workflows are a major automation feature that admins may need to roll out gradually.',
        ['Screenshot idea: capture Workspaces workflow settings with personal and group workflow controls.', 'Show WorkflowUser role enforcement and group assignment controls.', 'Call out how File Sync and generated Office actions interact with workflows.'],
        actions=[
            {'label': 'Open Workflow Settings', 'description': 'Review personal and group workflow administration controls.', 'href': '#workflow-settings-section', 'admin_tab': '#workspaces', 'admin_section': 'workflow-settings-section', 'icon': 'bi-gear'},
            {'label': 'Open Personal Workflows', 'description': 'Verify the user-facing Personal Workflows experience.', 'href': '/workspace#workflows-tab', 'icon': 'bi-play-circle'},
            {'label': 'Open Group Workspaces', 'description': 'Verify group workflow access in group workspaces.', 'href': '/group_workspaces', 'icon': 'bi-people'},
            {'label': 'Open File Sync', 'description': 'Review File Sync settings used by workflow triggers.', 'href': '#file-sync', 'admin_tab': '#file-sync', 'icon': 'bi-arrow-repeat'},
        ],
        image_label='Workflow Admin',
    ),
    _latest_feature_card(
        'admin_release_250_document_intelligence',
        'Document Intelligence Administration',
        'bi-file-earmark-richtext',
        'Admins can configure Standard, Enhanced, and Auto extraction for PDFs and images, including Auto sample-page behavior and reprocessing guidance.',
        'Document Intelligence settings help admins balance speed, cost, and richer structure extraction for files that need tables, layout, forms, or selection marks.',
        'This matters because richer extraction improves some workflows but should be controlled intentionally.',
        ['Screenshot idea: capture Search & Extract with Standard, Enhanced, and Auto controls visible.', 'Show Auto sample-page configuration and setup guidance.', 'Explain the user-facing impact of extraction badges and PDF reprocessing.'],
        actions=[
            {'label': 'Open Search and Extract', 'description': 'Review Document Intelligence controls.', 'href': '#search-extract', 'admin_tab': '#search-extract', 'icon': 'bi-file-earmark-richtext'},
            {'label': 'Document Intelligence Section', 'description': 'Jump to PDF/image extraction mode and Auto settings.', 'href': '#document-intelligence-section', 'admin_tab': '#search-extract', 'admin_section': 'document-intelligence-section', 'icon': 'bi-file-richtext'},
            {'label': 'Open Citations', 'description': 'Review enhanced citation settings that affect document previews.', 'href': '#citation', 'admin_tab': '#citation', 'icon': 'bi-journal-text'},
        ],
        image_label='Document Intelligence',
    ),
    _latest_feature_card(
        'admin_release_250_cosmos_scaling',
        'Cosmos Throughput Scaling',
        'bi-speedometer2',
        'Admins can monitor Cosmos RU pressure, scale database or container throughput, enforce policies, and convert eligible resources to native autoscale.',
        'The Scale tab now includes throughput status, validation, manual scale actions, container policies, global policy enforcement, cached status, and native autoscale conversion.',
        'This matters because admins can respond to capacity pressure without exposing Cosmos data-plane permissions to users or agents.',
        ['Screenshot idea: capture Cosmos throughput status, Validate Access, Refresh, and policy controls.', 'Show the Containers modal with per-container policies and manual scale actions.', 'Call out native autoscale conversion for eligible manual throughput resources.'],
        actions=[
            {'label': 'Open Scale Settings', 'description': 'Review Cosmos throughput scaling.', 'href': '#cosmos-throughput-section', 'admin_tab': '#scale', 'admin_section': 'cosmos-throughput-section', 'icon': 'bi-speedometer2'},
            {'label': 'Open Containers Policy', 'description': 'Open the per-container policy workflow from the Scale tab.', 'href': '#cosmos-throughput-section', 'admin_tab': '#scale', 'admin_section': 'cosmos-throughput-section', 'icon': 'bi-boxes'},
            {'label': 'Open Setup Guide', 'description': 'Review Cosmos throughput setup and access validation guidance.', 'href': '#cosmos-throughput-section', 'admin_tab': '#scale', 'admin_section': 'cosmos-throughput-section', 'icon': 'bi-book'},
        ],
        image_label='Cosmos Scaling',
    ),
    _latest_feature_card(
        'admin_release_250_file_sync',
        'File Sync Administration',
        'bi-arrow-repeat',
        'Admins can enable File Sync, choose SMB and Azure Files source types, configure scope gates, limits, connector identities, and workflow integration.',
        'File Sync administration controls which workspaces can sync files, which source types are available, whether app roles are required, and how identities are used for SMB and Azure Files credentials.',
        'This matters because synced ingestion needs tenant-level rollout controls before users connect shared file sources.',
        ['Screenshot idea: capture File Sync source-type availability and workspace scope controls.', 'Show SMB and Azure Files controls while noting more providers are planned.', 'Call out workflow triggers that can run when File Sync detects changes.'],
        actions=[
            {'label': 'Open File Sync', 'description': 'Review File Sync administration.', 'href': '#file-sync', 'admin_tab': '#file-sync', 'icon': 'bi-arrow-repeat'},
            {'label': 'Open Global Identities', 'description': 'Review connector identities used by sync sources.', 'href': '#global-workspace-identities-root', 'admin_tab': '#workspace-identities', 'admin_section': 'global-workspace-identities-root', 'icon': 'bi-person-badge'},
            {'label': 'Open Workflow Settings', 'description': 'Review workflow controls that can trigger File Sync.', 'href': '#workflow-settings-section', 'admin_tab': '#workspaces', 'admin_section': 'workflow-settings-section', 'icon': 'bi-diagram-3'},
        ],
        image_label='File Sync Admin',
    ),
    _latest_feature_card(
        'admin_release_250_group_sharing',
        'Group File Sharing Administration',
        'bi-share',
        'Admins and group managers can use approval-aware group file sharing so documents can move across group boundaries safely.',
        'Group file shares notify recipients, require approval from receiving group roles, preserve source ownership, and prevent receiving groups from deleting the owner group document.',
        'This matters because cross-group collaboration needs a controlled approval path.',
        ['Screenshot idea: capture group shared-file approval actions and notifications.', 'Show which group roles can approve or remove shared files.', 'Call out the source-owner boundary and recipient visibility rules.'],
        actions=[
            {'label': 'Open Group Workspaces', 'description': 'Review group document sharing behavior.', 'href': '/group_workspaces', 'icon': 'bi-people'},
            {'label': 'Open Workspace Settings', 'description': 'Review group workspace and document access settings.', 'href': '#workspaces', 'admin_tab': '#workspaces', 'icon': 'bi-folder2-open'},
            {'label': 'Open Notifications', 'description': 'Review notification behavior used by share approvals.', 'href': '#general', 'admin_tab': '#general', 'icon': 'bi-bell'},
        ],
        image_label='Group Sharing',
    ),
    _latest_feature_card(
        'admin_release_250_global_identities',
        'Workspace and Global Identities',
        'bi-person-badge',
        'Admins can manage global reusable identities while users manage workspace identities for File Sync, actions, and model endpoints where enabled.',
        'Global identities keep tenant-managed credentials separate from personal user sync choices, and workspace identity modals make credential purpose and usage clearer.',
        'This matters because credentials should be reusable and governed without duplicating secrets in every source or action.',
        ['Screenshot idea: capture Global Identities with used-for selections and authentication details.', 'Show workspace identity Add, View, and Edit modal flow.', 'Call out that global identities exclude File Sync while workspace identities support sync and actions.'],
        actions=[
            {'label': 'Open Global Identities', 'description': 'Review tenant-managed identities.', 'href': '#global-workspace-identities-root', 'admin_tab': '#workspace-identities', 'admin_section': 'global-workspace-identities-root', 'icon': 'bi-person-badge'},
            {'label': 'Open File Sync', 'description': 'Review sync source identity usage.', 'href': '#file-sync', 'admin_tab': '#file-sync', 'icon': 'bi-arrow-repeat'},
            {'label': 'Open Actions', 'description': 'Review actions that can use managed identities.', 'href': '#plugins', 'admin_tab': '#agents', 'admin_section': 'plugins-table', 'icon': 'bi-plug'},
        ],
        image_label='Identities',
    ),
    _latest_feature_card(
        'admin_release_250_deep_research',
        'Deep Research Administration',
        'bi-search-heart',
        'Admins can configure Deep Research budgets, allowed users, rendered-page support, traversal depth, and research ledger artifacts.',
        'The Deep Research controls govern how search queries, source pages, child links, rendered pages, and audit ledgers are planned and bounded before model responses use web evidence.',
        'This matters because deeper web review needs explicit limits, user controls, and an auditable source trail.',
        ['Screenshot idea: capture Deep Research budgets, allowed users, rendering status, and ledger controls.', 'Show page budgets, traversal depth, query planning, and linked-source inspection.', 'Call out that fetched pages are treated as untrusted source evidence.'],
        actions=[
            {'label': 'Open Search and Extract', 'description': 'Review Search and Extract settings.', 'href': '#search-extract', 'admin_tab': '#search-extract', 'icon': 'bi-search-heart'},
            {'label': 'Open Deep Research', 'description': 'Jump to Deep Research budgets and allowed-user controls.', 'href': '#source-review-section', 'admin_tab': '#search-extract', 'admin_section': 'source-review-section', 'icon': 'bi-search'},
            {'label': 'Open URL Access', 'description': 'Review shared URL policy used by Deep Research.', 'href': '#url-access-section', 'admin_tab': '#search-extract', 'admin_section': 'url-access-section', 'icon': 'bi-link-45deg'},
        ],
        image_label='Deep Research',
    ),
    _latest_feature_card(
        'admin_release_250_url_access',
        'URL Access Administration',
        'bi-link-45deg',
        'Admins can configure URL Access for chat and workflows with role gates, direct URL limits, domain policy, and policy testing.',
        'The URL Access controls govern how pasted links and workflow prompt URLs are fetched, blocked, tested, and shared with Deep Research source-page review.',
        'This matters because direct URL fetching needs bounded counts, domain controls, and predictable safety checks before external content enters a chat or workflow.',
        ['Screenshot idea: capture URL Access enablement, app-role requirement, direct URL limits, and domain policy.', 'Show allowed and blocked domain controls plus the URL Policy Test workflow.', 'Call out that URL Access uses the same server-side URL protections as Deep Research.'],
        actions=[
            {'label': 'Open Search and Extract', 'description': 'Review Search and Extract settings.', 'href': '#search-extract', 'admin_tab': '#search-extract', 'icon': 'bi-search-heart'},
            {'label': 'Open URL Access', 'description': 'Jump to URL Access controls and domain policy.', 'href': '#url-access-section', 'admin_tab': '#search-extract', 'admin_section': 'url-access-section', 'icon': 'bi-link-45deg'},
            {'label': 'Open Deep Research', 'description': 'Review Deep Research controls that share URL policy.', 'href': '#source-review-section', 'admin_tab': '#search-extract', 'admin_section': 'source-review-section', 'icon': 'bi-search'},
        ],
        image_label='URL Access',
    ),
    _latest_feature_card(
        'admin_release_250_model_endpoint_branding',
        'Model and Agent Visual Identity',
        'bi-image',
        'Admins can assign icons or uploaded images to model endpoints so users can distinguish model-only responses from agent responses.',
        'Model endpoint visual identity flows into Chat assistant avatars for model-only responses, while agent avatars remain prioritized when an agent is selected.',
        'This matters because visual identity helps users understand which model or agent produced a response.',
        ['Screenshot idea: capture model endpoint icon and image picker controls.', 'Show a Chat response with a model icon and an agent response with an agent avatar.', 'Call out that agent identity takes priority over model identity.'],
        actions=[
            {'label': 'Open AI Models', 'description': 'Review model endpoint visual identity controls.', 'href': '#ai-models', 'admin_tab': '#ai-models', 'icon': 'bi-image'},
            {'label': 'Open Model Endpoints', 'description': 'Manage endpoint icon and image metadata.', 'href': '#model-endpoints-wrapper', 'admin_tab': '#ai-models', 'admin_section': 'model-endpoints-wrapper', 'icon': 'bi-hdd-network'},
            {'label': 'Open Agents Page Settings', 'description': 'Review agent catalog visual presentation controls.', 'href': '#agents-page-customization-card', 'admin_tab': '#agents', 'admin_section': 'agents-page-customization-card', 'icon': 'bi-robot'},
        ],
        image_label='Visual Identity',
    ),
    _latest_feature_card(
        'admin_release_250_bug_fixes',
        'Reliability and Security Fixes',
        'bi-bug',
        'Admins can review the full 0.250.001 bug-fix list for security hardening, authorization boundaries, dependency refreshes, stream reliability, and deployment stability.',
        'The release notes now group all fixes under 0.250.001 so admins can scan the full bug-fix inventory without navigating every point release.',
        'This matters because the admin-facing value of many fixes is operational trust rather than a new visible control.',
        ['Use this as the pointer for security, deployment, dependency, and reliability fixes.', 'Call out that this card is informational for admins and does not represent a user-facing feature toggle.', 'Use the release notes link when admins need the complete fix inventory.'],
        actions=[
            {'label': 'Open Release Notes', 'description': 'Review the full 0.250.001 bug-fix list.', 'href': 'https://microsoft.github.io/simplechat/explanation/release_notes/', 'icon': 'bi-box-arrow-up-right', 'is_external': True},
            {'label': 'Open Security', 'description': 'Review security-related admin settings.', 'href': '#security', 'admin_tab': '#security', 'icon': 'bi-shield-lock'},
            {'label': 'Open Logging', 'description': 'Review logging and diagnostics settings.', 'href': '#logging', 'admin_tab': '#logging', 'icon': 'bi-card-list'},
        ],
        include_media=False,
    ),
]


_SUPPORT_CURRENT_FEATURE_IMAGE_METADATA = {
    'document_intelligence': {
        'focused_path': 'images/features/document_intelligence_admin_controls.png',
        'focused_alt': 'Annotated Document Intelligence Auto Mode admin settings screenshot',
        'focused_title': 'Configure Document Intelligence Auto Mode',
        'focused_caption': 'Numbers highlight extraction mode selection, Auto sample-page tuning, and where users review extraction badges or change PDF extraction.',
        'focused_label': 'Admin Controls',
    },
    'cloud_anthropic_models': {
        'focused_path': 'images/features/model_selection_multi_endpoint_admin.png',
        'focused_alt': 'Admin multi-endpoint model management screenshot showing provider choices and configured models',
        'focused_title': 'Configure Cloud and Anthropic Model Endpoints',
        'focused_caption': 'Numbers highlight model endpoint management, provider-aware Foundry configuration, and the admin model choices that can include Claude deployments.',
        'focused_label': 'Model Endpoint Controls',
    },
    'file_sync': {
        'focused_path': 'images/features/file_sync_admin_scope_controls.png',
        'focused_alt': 'Annotated File Sync connector settings screenshot',
        'focused_title': 'Configure File Sync Connectors',
        'focused_caption': 'Numbers highlight SMB and Azure Files source enablement, reusable identity configuration, and sync status or history review.',
        'focused_label': 'Connector Controls',
    },
    'group_workflows': {
        'focused_path': 'images/features/workflow_automation_admin_controls.png',
        'focused_alt': 'Annotated workflow automation admin settings screenshot with workflow access controls',
        'focused_title': 'Configure Group Workflow Support',
        'focused_caption': 'Numbers highlight workflow access enablement, group workflow policy controls, and File Sync before-run automation shared with group workflows.',
        'focused_label': 'Group Workflow Controls',
    },
    'source_review': {
        'focused_path': 'images/features/source_review_admin_policy.png',
        'focused_alt': 'Annotated Source Review and Deep Research policy screenshot',
        'focused_title': 'Configure Source Review Policies',
        'focused_caption': 'Numbers highlight Source Review enablement, Deep Research policy options, and bounded allow or block controls.',
        'focused_label': 'Policy Controls',
    },
    'analyze_compare': {
        'focused_path': 'images/features/document_revision_delete_compare.png',
        'focused_alt': 'Document revision actions and comparison screenshot showing compare-related document actions',
        'focused_title': 'Use Analyze and Compare Document Actions',
        'focused_caption': 'Numbers highlight document action entry points for analysis and comparison workflows that go beyond regular search.',
        'focused_label': 'Document Actions',
    },
    'agent_knowledge_actions': {
        'focused_path': 'images/features/agent_knowledge_actions_assigned_knowledge.png',
        'focused_alt': 'Annotated Assigned Knowledge setup screenshot for agents',
        'focused_title': 'Assign Agent Knowledge and Actions',
        'focused_caption': 'Numbers highlight Assigned Knowledge enablement, source workspace and document selection, and optional web sources or user actions.',
        'focused_label': 'Agent Setup',
    },
    'generated_artifacts': {
        'focused_path': 'images/features/generated_artifacts_chat_artifacts.png',
        'focused_alt': 'Annotated generated artifact card screenshot in chat',
        'focused_title': 'Use Generated Artifacts in Chat',
        'focused_caption': 'Numbers highlight the generated Markdown artifact, rendered structured output, and the action to promote reusable work into a workspace.',
        'focused_label': 'Artifact Workflow',
    },
    'chat_productivity': {
        'focused_path': 'images/features/chat_productivity_chat_toolbar.png',
        'focused_alt': 'Annotated chat productivity toolbar screenshot',
        'focused_title': 'Use Chat Productivity Controls',
        'focused_caption': 'Numbers highlight prompt, model, and agent selection, attachment and paste upload controls, document actions, and Source Review before sending.',
        'focused_label': 'Chat Controls',
    },
    'chat_upload_workspace_parity': {
        'focused_path': 'images/features/chat_productivity_chat_toolbar.png',
        'focused_alt': 'Annotated chat productivity toolbar screenshot showing attachment and workspace controls',
        'focused_title': 'Use Workspace-Backed Chat Uploads',
        'focused_caption': 'Numbers highlight chat attachment controls and workspace grounding paths that turn eligible uploads into personal or group workspace documents.',
        'focused_label': 'Upload Controls',
    },
    'workspace_experience': {
        'focused_path': 'images/features/workspace_experience_document_cards.png',
        'focused_alt': 'Annotated workspace document cards screenshot',
        'focused_title': 'Navigate Workspace Document Views',
        'focused_caption': 'Numbers highlight view switching, card and folder scanning, and document actions such as open, compare, or reprocess.',
        'focused_label': 'Workspace Views',
    },
    'workflow_automation': {
        'focused_path': 'images/features/workflow_automation_admin_controls.png',
        'focused_alt': 'Annotated workflow automation admin settings screenshot',
        'focused_title': 'Configure Workflow Automation',
        'focused_caption': 'Numbers highlight workflow access enablement, optional Enterprise App role enforcement, and File Sync before-run automation.',
        'focused_label': 'Workflow Controls',
    },
    'visio_ingestion': {
        'focused_path': 'images/features/visio_ingestion_workspace_upload.png',
        'focused_alt': 'Annotated Visio diagram upload screenshot in a workspace',
        'focused_title': 'Upload and Search Visio Diagrams',
        'focused_caption': 'Numbers highlight .vsdx upload, page and shape indexing, and citation or original-file inspection workflows.',
        'focused_label': 'Visio Workflow',
    },
    'stats_reporting': {
        'focused_path': 'images/features/stats_reporting_profile_dashboard.png',
        'focused_alt': 'Annotated profile stats reporting dashboard screenshot',
        'focused_title': 'Review Stats and Reporting',
        'focused_caption': 'Numbers highlight reporting windows, cached usage totals, and export controls for offline reporting.',
        'focused_label': 'Reporting Dashboard',
    },
}


_SUPPORT_CURRENT_FEATURE_USER_METADATA = {
    'document_intelligence': {
        'guidance': [
            'Open Personal Workspace and expand a document row to review how it was processed.',
            'Use the extraction and citation badges to see whether the file used Standard, Enhanced, or enhanced citation processing.',
            'Use Edit Metadata, Extract Metadata, or Change Extraction when you need to refine or extract a stored document again.',
        ],
        'actions': [
            {
                'label': 'Review Workspace Documents',
                'description': 'Open Personal Workspace and inspect document extraction badges, metadata, and Change Extraction actions.',
                'href': '/workspace#documents-tab',
                'icon': 'bi-folder2-open',
                'requires_settings': ['enable_user_workspace'],
            },
        ],
        'images': [
            {
                'path': 'images/features/document_intelligence_user_details.png',
                'alt': 'Annotated workspace document details screenshot showing extraction badges and Change Extraction actions',
                'title': 'Review Document Enrichment',
                'caption': '1 opens a document row, 2 checks extraction and citation badges, and 3 uses metadata or Change Extraction actions when a different extraction mode is needed.',
                'label': 'Document Details',
            },
        ],
    },
    'cloud_anthropic_models': {
        'guidance': [
            'Open Chat and use the model selector to choose among the Azure OpenAI, Foundry, New Foundry, and Claude-capable models your admins enabled.',
            'Use Claude-backed models for tasks where that deployment is the preferred reasoning or writing option in your environment.',
            'Expect model-bound chat, agents, workflows, and summaries to keep using the selected endpoint metadata when a Claude deployment is selected.',
        ],
        'actions': [
            {
                'label': 'Open Chat Model Picker',
                'description': 'Open Chat and choose one of the model endpoints made available by your admins.',
                'href': '/chats#model-select-container',
                'icon': 'bi-cpu',
            },
        ],
        'images': [
            {
                'path': 'images/features/model_selection_chat_selector.png',
                'alt': 'User chat model selector screenshot showing multiple available model choices',
                'title': 'Choose an Available Chat Model',
                'caption': '1 opens the model picker, 2 reviews available provider-backed model choices, and 3 selects the model for the next chat turn.',
                'label': 'Model Picker',
            },
        ],
    },
    'file_sync': {
        'guidance': [
            'Open Personal Workspace > Sync to add sources, run sync, and review provider status, counts, and history.',
            'Open Personal Workspace > Identities to reuse credentials across sync sources and actions without duplicating setup.',
            'Use SMB or Azure Files sources for the current connector set, then watch synced document badges in the Documents tab.',
        ],
        'actions': [
            {
                'label': 'Open Workspace Sync',
                'description': 'Review sync sources, run status, history, and provider counts from Personal Workspace.',
                'href': '/workspace?feature_action=file_sync',
                'icon': 'bi-arrow-repeat',
                'requires_settings': ['enable_user_workspace'],
            },
            {
                'label': 'Open Workspace Identities',
                'description': 'Review reusable identities used by sync sources and actions.',
                'href': '/workspace#identities-tab',
                'icon': 'bi-person-badge',
                'requires_settings': ['enable_user_workspace'],
            },
        ],
        'images': [
            {
                'path': 'images/features/file_sync_user_sources.png',
                'alt': 'Annotated workspace Sync tab screenshot showing a sync source, counts, and run actions',
                'title': 'Manage Sync Sources',
                'caption': '1 adds a source, 2 reviews provider status and counts, and 3 runs sync or opens history from the user workspace.',
                'label': 'Sync Sources',
            },
            {
                'path': 'images/features/file_sync_user_identities.png',
                'alt': 'Annotated workspace Identities tab screenshot showing reusable credentials for sync and actions',
                'title': 'Reuse Workspace Identities',
                'caption': '1 adds an identity, 2 shows what uses it, and 3 opens view or edit controls for credential maintenance.',
                'label': 'Identities',
            },
        ],
    },
    'group_workflows': {
        'guidance': [
            'Open Group Workspaces, choose an active group, and review the Group Workflows area when your admins enabled it.',
            'Create group workflows with group-scoped agents, model endpoints, File Sync sources, manual runs, or interval schedules.',
            'Use group workflow activity and run history to inspect shared workflow output without moving the work into a personal workspace.',
        ],
        'actions': [
            {
                'label': 'Open Group Workspaces',
                'description': 'Open Group Workspaces and review group workflow availability for the active group.',
                'href': '/group_workspaces',
                'icon': 'bi-people',
            },
        ],
        'images': [
            {
                'path': 'images/features/workflow_automation_user_list.png',
                'alt': 'Annotated workspace Workflows tab screenshot showing workflow list and create controls',
                'title': 'Manage Shared Workflows',
                'caption': '1 creates a workflow, 2 reviews run status, and 3 uses the workflow list pattern now available for group workflows when enabled.',
                'label': 'Workflow List',
            },
        ],
    },
    'source_review': {
        'guidance': [
            'Open Chat and use the Workspaces tool when an answer should be grounded in selected documents or tags.',
            'Turn on Source Review or Deep Research when pasted URLs or web evidence should be reviewed before the final answer.',
            'Choose a narrow scope, tag, or document set so the reviewed evidence stays deliberate and easy to audit.',
        ],
        'actions': [
            {
                'label': 'Try Sources in Chat',
                'description': 'Open Chat and use workspace grounding, source review, or Deep Research controls with your next prompt.',
                'href': '/chats#chatbox',
                'icon': 'bi-chat-dots',
            },
        ],
        'images': [
            {
                'path': 'images/features/source_review_user_grounded_search.png',
                'alt': 'Annotated chat grounded search screenshot showing workspace scope, tags, and document controls',
                'title': 'Ground Chat in Workspace Sources',
                'caption': '1 opens the Workspaces grounding tool, 2 chooses action, scope, tags, and documents, and 3 grounds the next message.',
                'label': 'Grounded Search',
            },
            {
                'path': 'images/features/source_review_user_deep_research.png',
                'alt': 'Annotated chat source review screenshot showing source tools and prompt entry',
                'title': 'Use Source Review and Deep Research',
                'caption': '1 opens source tools, 2 enables source review when available, and 3 asks a URL or web-evidence question.',
                'label': 'Source Review',
            },
        ],
    },
    'analyze_compare': {
        'guidance': [
            'Open Chat, expand the Workspaces tool, and choose Analyze when a prompt should review selected documents end to end.',
            'Choose Compare when you want one source document compared against one or more target documents.',
            'Use progress and coverage details to understand which documents were reviewed or compared in the final answer.',
        ],
        'actions': [
            {
                'label': 'Open Chat Document Actions',
                'description': 'Open Chat and choose Analyze or Compare from the Workspaces tool.',
                'href': '/chats#chatbox',
                'icon': 'bi-chat-dots',
            },
        ],
        'images': [
            {
                'path': 'images/features/document_revision_delete_compare.png',
                'alt': 'Document revision actions and comparison screenshot showing compare-related document actions',
                'title': 'Review Document Action Choices',
                'caption': '1 reviews available document actions, 2 chooses comparison-oriented work when needed, and 3 keeps document history available for follow-up analysis.',
                'label': 'Document Actions',
            },
        ],
    },
    'agent_knowledge_actions': {
        'guidance': [
            'Open Personal Workspace > Agents to view, chat with, or edit agents that have assigned knowledge.',
            'Open Personal Workspace > Actions to see which reusable tools are enabled for agents and workflows.',
            'Use identities with actions that need credentials, then test the agent from Chat before relying on it for repeat work.',
        ],
        'actions': [
            {
                'label': 'Open Workspace Agents',
                'description': 'Review agents, assigned knowledge, and chat or edit controls from Personal Workspace.',
                'href': '/workspace#agents-tab',
                'icon': 'bi-diagram-3',
                'requires_settings': ['enable_user_workspace'],
            },
            {
                'label': 'Open Workspace Actions',
                'description': 'Review enabled actions that agents and workflows can use.',
                'href': '/workspace#plugins-tab',
                'icon': 'bi-plug',
                'requires_settings': ['enable_user_workspace'],
            },
        ],
        'images': [
            {
                'path': 'images/features/agent_knowledge_user_agents.png',
                'alt': 'Annotated workspace Agents tab screenshot showing agent list and chat or edit controls',
                'title': 'Use Workspace Agents',
                'caption': '1 creates or edits an agent, 2 reviews its purpose, and 3 chats, views, or edits the agent.',
                'label': 'Agents',
            },
            {
                'path': 'images/features/agent_knowledge_user_actions.png',
                'alt': 'Annotated workspace Actions tab screenshot showing enabled actions and edit controls',
                'title': 'Use Workspace Actions',
                'caption': '1 creates an action, 2 confirms enabled tools, and 3 views or edits action details.',
                'label': 'Actions',
            },
        ],
    },
    'generated_artifacts': {
        'guidance': [
            'Generate charts, Markdown, or structured analysis in Chat when the response should become reusable work.',
            'Use chart, copy, retry, or artifact controls to inspect the generated output before continuing.',
            'Use Add to Workspace when a generated artifact should become a durable workspace document.',
        ],
        'images': [
            {
                'path': 'images/features/generated_artifacts_user_chat_output.png',
                'alt': 'Annotated chat screenshot showing generated chart output and message action controls',
                'title': 'Review Generated Output in Chat',
                'caption': '1 reviews the generated output, 2 opens chart or artifact controls, and 3 copies, retries, or continues the work.',
                'label': 'Generated Output',
            },
        ],
    },
    'chat_productivity': {
        'guidance': [
            'Use the composer tools to attach images, files, URLs, prompts, source grounding, and agents without leaving Chat.',
            'Use the model selector when a task needs a different model capability or speed profile.',
            'Use Analyze or Compare from the Workspaces tool when a selected document needs full review or side-by-side comparison.',
            'Paste or type the next prompt directly in the composer after reviewing generated charts, artifacts, citations, or document-action output.',
        ],
        'images': [
            {
                'path': 'images/features/chat_productivity_user_chat.png',
                'alt': 'Annotated chat composer screenshot showing attachment tools, model picker, and prompt input',
                'title': 'Use Chat Productivity Controls',
                'caption': '1 opens attachment and workspace tools, 2 switches models, and 3 pastes or types the next prompt.',
                'label': 'Chat Composer',
            },
        ],
    },
    'chat_upload_workspace_parity': {
        'guidance': [
            'Upload or paste files in personal Chat to create linked personal workspace documents when personal workspace processing is enabled.',
            'Upload files in group or group multi-user conversations to create linked documents in the writable group workspace.',
            'After processing finishes, use the linked workspace document for Search, Analyze, Compare, citations, tagging, and normal document governance.',
        ],
        'actions': [
            {
                'label': 'Upload from Chat',
                'description': 'Open Chat and attach a file to use the workspace-backed upload path when enabled.',
                'href': '/chats#chatbox',
                'icon': 'bi-paperclip',
            },
            {
                'label': 'Open Group Workspaces',
                'description': 'Review group workspace documents created from group chat uploads.',
                'href': '/group_workspaces',
                'icon': 'bi-people',
            },
        ],
        'images': [
            {
                'path': 'images/features/chat_productivity_user_chat.png',
                'alt': 'Annotated chat composer screenshot showing attachment tools, model picker, and prompt input',
                'title': 'Upload Files from Chat',
                'caption': '1 opens attachment tools, 2 uploads or pastes a file, and 3 continues the conversation while workspace processing runs.',
                'label': 'Chat Upload',
            },
            {
                'path': 'images/features/workspace_experience_document_cards.png',
                'alt': 'Annotated workspace document cards screenshot showing document cards and actions',
                'title': 'Use Uploaded Files as Workspace Documents',
                'caption': '1 finds the uploaded file in the workspace, 2 opens document actions, and 3 uses search, analysis, comparison, citations, or governance workflows.',
                'label': 'Workspace Document',
            },
        ],
    },
    'workspace_experience': {
        'guidance': [
            'Use List view when you need dense file, title, badge, and action scanning.',
            'Use Cards when you want larger document previews, then switch to Folders or Folders + Cards for tag-first browsing.',
            'Use Manage Tags and multi-select when a set of documents needs cleanup, approval, or organization.',
        ],
        'images': [
            {
                'path': 'images/features/workspace_experience_user_list_view.png',
                'alt': 'Annotated workspace List view screenshot showing dense document rows and row actions',
                'title': 'Scan Documents in List View',
                'caption': '1 switches view mode, 2 scans file names, titles, and badges, and 3 opens chat or row actions.',
                'label': 'List View',
            },
            {
                'path': 'images/features/workspace_experience_user_cards_view.png',
                'alt': 'Annotated workspace Cards view screenshot showing document cards and card actions',
                'title': 'Browse Document Cards',
                'caption': '1 chooses Cards view, 2 scans document cards, and 3 uses document actions.',
                'label': 'Cards View',
            },
            {
                'path': 'images/features/workspace_experience_user_folders_view.png',
                'alt': 'Annotated workspace Folders view screenshot showing tag folders and sort controls',
                'title': 'Browse Tag Folders',
                'caption': '1 chooses Folders view, 2 browses tag folders, and 3 sorts folders by name or file count.',
                'label': 'Folders View',
            },
            {
                'path': 'images/features/workspace_experience_user_folders_cards_view.png',
                'alt': 'Annotated workspace Folders and Cards view screenshot showing tag folders and document organization controls',
                'title': 'Use Folders and Cards Together',
                'caption': '1 chooses Folders + Cards, 2 opens a folder by tag, and 3 manages tags or multi-selects documents.',
                'label': 'Folders + Cards',
            },
        ],
    },
    'workflow_automation': {
        'guidance': [
            'Open Personal Workspace > Workflows for personal automation, or Group Workspaces for shared group workflow automation when enabled.',
            'In the workflow editor, enable File Sync Before Run when the workflow should refresh personal or group source files first.',
            'Select sync sources, choose whether to wait for completion, and use changed files as Analyze targets when appropriate.',
        ],
        'actions': [
            {
                'label': 'Open Workspace Workflows',
                'description': 'Create or review workflows and File Sync before-run controls from Personal Workspace.',
                'href': '/workspace#workflows-tab',
                'icon': 'bi-play-circle',
                'requires_settings': ['enable_user_workspace'],
            },
            {
                'label': 'Open Group Workspaces',
                'description': 'Create or review group workflows from the active group workspace when enabled.',
                'href': '/group_workspaces',
                'icon': 'bi-people',
            },
        ],
        'images': [
            {
                'path': 'images/features/workflow_automation_user_list.png',
                'alt': 'Annotated workspace Workflows tab screenshot showing workflow list and create controls',
                'title': 'Manage Workspace Workflows',
                'caption': '1 creates a workflow, 2 reviews workflow runs and status, and 3 switches list or grid view.',
                'label': 'Workflow List',
            },
            {
                'path': 'images/features/workflow_automation_user_file_sync_trigger.png',
                'alt': 'Annotated workflow editor screenshot showing File Sync Before Run controls',
                'title': 'Trigger File Sync Before Workflow Runs',
                'caption': '1 enables File Sync before run, 2 selects sources, and 3 chooses wait, continue, and changed-file targeting behavior.',
                'label': 'File Sync Trigger',
            },
        ],
    },
    'visio_ingestion': {
        'guidance': [
            'Upload `.vsdx` files from Personal Workspace when diagrams should become searchable workspace knowledge.',
            'Find Visio documents in the document list like any other workspace file.',
            'Use Chat on the Visio file to ask about pages, labels, shapes, and connectors.',
        ],
        'images': [
            {
                'path': 'images/features/visio_ingestion_user_upload.png',
                'alt': 'Annotated workspace document list screenshot showing Visio upload support and chat action',
                'title': 'Upload and Use Visio Diagrams',
                'caption': '1 uploads `.vsdx` diagrams, 2 finds Visio files in the workspace, and 3 opens Chat for the diagram.',
                'label': 'Visio Upload',
            },
        ],
    },
    'stats_reporting': {
        'guidance': [
            'Open Profile > Stats to review your activity with 7-day, 30-day, 90-day, or custom windows and export visible metrics.',
            'Open Profile > Settings to control navigation preferences, tutorial visibility, retention, saved memories, speech preferences, and text-to-speech voice selection.',
            'Use Profile tabs to review your groups, public workspaces, submitted feedback, and safety violations from one place.',
        ],
        'actions': [
            {
                'label': 'Open Profile Stats',
                'description': 'Review your personal activity windows and export options from Profile.',
                'href': '/profile?tab=stats#profile-stats-pane',
                'icon': 'bi-person-lines-fill',
            },
            {
                'label': 'Open Profile Settings',
                'description': 'Review navigation, tutorial, memory, speech, and voice preferences from Profile.',
                'href': '/profile?tab=settings#profile-settings-pane',
                'icon': 'bi-person-gear',
            },
            {
                'label': 'Open Groups',
                'description': 'Review the groups connected to your account from Profile.',
                'href': '/profile?tab=groups#profile-groups-pane',
                'icon': 'bi-people',
            },
            {
                'label': 'Open Public Workspaces',
                'description': 'Review public workspaces connected to your account from Profile.',
                'href': '/profile?tab=public-workspaces#profile-public-workspaces-pane',
                'icon': 'bi-globe',
            },
        ],
        'images': [
            {
                'path': 'images/features/stats_reporting_user_profile.png',
                'alt': 'Annotated profile stats screenshot showing time windows, export, and activity charts',
                'title': 'Review Profile Stats and Preferences',
                'caption': '1 chooses a reporting window, 2 exports stats to CSV, and 3 reviews profile activity, settings, groups, workspaces, feedback, and violations from the profile tabs.',
                'label': 'Profile Stats',
            },
            {
                'path': 'images/features/facts_memory_view_profile.png',
                'alt': 'Profile fact memory section screenshot showing saved instructions and facts controls',
                'title': 'Manage Profile Memories',
                'caption': 'Fact Memory lives in Profile settings alongside tutorial, retention, speech, and voice preferences.',
                'label': 'Profile Memories',
            },
        ],
    },
}


def _apply_current_feature_image_metadata():
    """Attach practical annotated screenshots to the current Latest Features catalog."""
    for feature in _SUPPORT_LATEST_FEATURE_CATALOG:
        image_metadata = _SUPPORT_CURRENT_FEATURE_IMAGE_METADATA.get(feature['id'])
        if not image_metadata:
            continue

        feature['image'] = image_metadata['focused_path']
        feature['image_alt'] = image_metadata['focused_alt']
        feature['images'] = [
            {
                'path': image_metadata['focused_path'],
                'alt': image_metadata['focused_alt'],
                'title': image_metadata['focused_title'],
                'caption': image_metadata['focused_caption'],
                'label': image_metadata['focused_label'],
            },
        ]


def _apply_user_support_feature_metadata(feature):
    """Apply user-facing screenshots, guidance, and actions to current release support cards."""
    user_metadata = _SUPPORT_CURRENT_FEATURE_USER_METADATA.get(feature.get('id'))
    if not user_metadata:
        return

    if 'guidance' in user_metadata:
        feature['guidance'] = deepcopy(user_metadata['guidance'])

    if 'actions' in user_metadata:
        feature['actions'] = deepcopy(user_metadata['actions'])

    images = deepcopy(user_metadata.get('images', []))
    if images:
        feature['images'] = images
        feature['image'] = images[0].get('path')
        feature['image_alt'] = images[0].get('alt', '')


_apply_current_feature_image_metadata()

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


_SUPPORT_PREVIOUS_RELEASE_FEATURE_CATALOG = [
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

_SUPPORT_EARLIER_RELEASE_FEATURE_CATALOG = [
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

_ADMIN_PREVIOUS_RELEASE_FEATURE_CATALOG = [
    {
        'id': 'release_notifications_status_badge',
        'title': 'Registered / Unregistered Badge',
        'icon': 'bi-megaphone',
        'summary': 'The badge next to the Admin Settings version number shows whether this admin instance is registered for latest release and community call notifications.',
        'details': 'The Admin Settings header can show Registered or Unregistered status and opens the release notification registration modal for saved name, email, and organization details.',
        'why': 'This matters because admins can confirm release-notification status without hunting through setup screens.',
        'guidance': [
            'Unregistered means this environment has not saved release notification registration details yet.',
            'Registered means saved contact details exist for release and community call notifications.',
            'Clicking the badge opens the registration modal and can prepare a prefilled email draft to simplechat@microsoft.com.',
        ],
        'actions': [],
    },
] + _SUPPORT_PREVIOUS_RELEASE_FEATURE_CATALOG

_SUPPORT_LATEST_FEATURE_RELEASE_GROUPS = [
    {
        'id': 'current_release',
        'label': 'Latest Features',
        'description': 'The SimpleChat 0.250.001 feature set your admins are currently sharing with end users.',
        'release_version': '0.250.001',
        'default_expanded': True,
        'collapse_id': 'supportLatestFeaturesCurrentRelease',
        'features': _SUPPORT_LATEST_FEATURE_CATALOG,
    },
    {
        'id': 'previous_release',
        'label': 'Previous Release Features',
        'description': 'The v0.241.001 through v0.241.007 feature set remains available for reference after the v0.250.001 feature set became current.',
        'release_version': '0.241.001 - 0.241.007',
        'default_expanded': False,
        'collapse_id': 'supportLatestFeaturesPreviousRelease',
        'features': _SUPPORT_PREVIOUS_RELEASE_FEATURE_CATALOG,
    },
    {
        'id': 'archive_release',
        'label': 'Archive Release Features',
        'description': 'Older v0.239.001 highlights remain available for longer-term reference.',
        'release_version': '0.239.001',
        'default_expanded': False,
        'collapse_id': 'supportLatestFeaturesArchiveRelease',
        'features': _SUPPORT_EARLIER_RELEASE_FEATURE_CATALOG,
    },
]


_ADMIN_LATEST_FEATURE_RELEASE_GROUPS = [
    {
        'id': 'current_release',
        'label': 'Admin-Managed Latest Features',
        'description': 'The newest capabilities admins can manage from Admin Settings. These cards focus on tenant controls, governance, and screenshot ideas for the admin guide.',
        'release_version': '0.250.001',
        'default_expanded': True,
        'collapse_id': 'adminLatestFeaturesCurrentRelease',
        'features': _SUPPORT_ADMIN_LATEST_FEATURE_CURRENT_CATALOG,
    },
    {
        'id': 'previous_release',
        'label': 'Previous Release Features',
        'description': 'Admin-facing release items from the prior v0.241.001 through v0.241.007 feature set remain available for reference.',
        'release_version': '0.241.001 - 0.241.007',
        'default_expanded': False,
        'collapse_id': 'adminLatestFeaturesPreviousRelease',
        'features': _ADMIN_PREVIOUS_RELEASE_FEATURE_CATALOG,
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
            _apply_user_support_feature_metadata(visible_item)
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
            _apply_user_support_feature_metadata(visible_feature)
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


def get_admin_latest_feature_release_groups_for_settings(settings):
    """Return grouped admin latest-feature metadata with safe media defaults."""
    filtered_groups = deepcopy(_ADMIN_LATEST_FEATURE_RELEASE_GROUPS)
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