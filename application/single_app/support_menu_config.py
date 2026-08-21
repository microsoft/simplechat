# support_menu_config.py
"""Shared support menu configuration for user and admin latest features."""

from copy import deepcopy


_SUPPORT_LATEST_FEATURE_DOCS_SETTING_KEY = 'enable_support_latest_feature_documentation_links'
_LEGACY_ACTION_ENDPOINTS = {
    'chats': 'frontend_chats.chats',
    'workspace': 'frontend_workspace.workspace',
    'profile': 'frontend_profile.profile',
    'support_latest_features': 'frontend_support.support_latest_features',
    'support_send_feedback': 'frontend_support.support_send_feedback',
}


def _latest_feature_card(feature_id, title, icon, summary, details, why, guidance, actions=None, image_label=None, image_title=None, image_caption=None, image_name=None, include_media=True, images=None):
    """Build a latest-feature catalog entry with optional screenshot metadata."""
    if images:
        gallery = []
        for index, spec in enumerate(images, start=1):
            image_file = spec.get('name') or f"{feature_id}_{index}.png"
            image_title_value = spec.get('title') or title
            gallery.append({
                'path': f"images/features/{image_file}",
                'alt': spec.get('alt') or f"{image_title_value} screenshot placeholder",
                'title': image_title_value,
                'caption': spec.get('caption') or f"Screenshot placeholder for {image_title_value}.",
                'label': spec.get('label') or image_title_value,
            })

        return {
            'id': feature_id,
            'title': title,
            'icon': icon,
            'summary': summary,
            'details': details,
            'why': why,
            'guidance': guidance,
            'actions': actions or [],
            'image': gallery[0]['path'],
            'image_alt': gallery[0]['alt'],
            'images': gallery,
        }

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


_SUPPORT_RELEASE_250_FEATURE_CATALOG = [
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
        'File Sync for Storage Sources',
        'bi-arrow-repeat',
        'File Sync can bring SMB, Azure Files, and Azure Blob Storage content into workspaces, with reusable identities and workflow triggers for automated refreshes.',
        'Users can configure sync sources where enabled, use identities for credentials, review synced-document badges, and connect sync sources to workflows that run before or after file changes. Additional sync providers are planned for future releases.',
        'This matters because workspace documents can stay closer to authoritative file shares instead of depending on repeated manual uploads.',
        ['Use Workspace > Sync to configure SMB, Azure Files, or Azure Blob Storage sources when admins enable File Sync.', 'Use Workspace > Identities to reuse credentials for sync sources and actions.', 'Use workflows with File Sync triggers when analysis should run after synced content changes.'],
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


_ADMIN_RELEASE_250_FEATURE_CATALOG = [
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
        'Admins can enable File Sync, choose SMB, Azure Files, and Azure Blob Storage source types, configure scope gates, limits, connector identities, and workflow integration.',
        'File Sync administration controls which workspaces can sync files, which source types are available, whether app roles are required, and how identities are used for storage credentials.',
        'This matters because synced ingestion needs tenant-level rollout controls before users connect shared file sources.',
        ['Screenshot idea: capture File Sync source-type availability and workspace scope controls.', 'Show SMB, Azure Files, and Azure Blob Storage controls while noting more providers are planned.', 'Call out workflow triggers that can run when File Sync detects changes.'],
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


_SUPPORT_RELEASE_241_FEATURE_CATALOG = [
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

_SUPPORT_RELEASE_239_FEATURE_CATALOG = [
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

_ADMIN_RELEASE_241_FEATURE_CATALOG = [
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
] + _SUPPORT_RELEASE_241_FEATURE_CATALOG

_SUPPORT_RELEASE_260_FEATURE_CATALOG = [
    _latest_feature_card(
        'release_260_enhanced_extraction',
        'Sharper Document Extraction with Figure Descriptions',
        'bi-file-earmark-richtext',
        'Enhanced extraction now reads charts, diagrams, and figures inside your documents and writes searchable descriptions of them, so answers can draw on pictures instead of skipping past them.',
        'When your admins turn on Enhanced extraction, SimpleChat uses Azure AI Content Understanding to describe figures, charts, and diagrams as it processes a file. Those descriptions become searchable text, so a question about a chart can be answered from the chart itself. Workspace document rows show a badge naming which extraction engine actually ran, and why it fell back if a different one was used.',
        'This matters because a large share of the meaning in reports, decks, and scanned documents lives in pictures, and until now that content was effectively invisible to search.',
        [
            'Open Personal Workspace and upload a document that contains charts, diagrams, or scanned figures.',
            'Wait for processing to finish, then expand the document row to see the extraction badge.',
            'Hover the badge to see which engine ran, and the fallback reason if a different engine was used.',
            'Open the document details to read the generated figure descriptions alongside the extracted text.',
            'Go to Chat, ground on that document, and ask a question that can only be answered from a figure or chart.',
            'If an older document was uploaded before this change, use Change Extraction to reprocess it with the newer engine.',
            'If you do not see the option, ask your admin whether Enhanced extraction is enabled for your environment.',
        ],
        actions=[
            {'label': 'Open Personal Workspace', 'description': 'Upload a document and review its extraction badge and figure descriptions.', 'href': '/workspace#documents-tab', 'icon': 'bi-folder2-open', 'requires_settings': ['enable_user_workspace']},
            {'label': 'Open Chat', 'description': 'Ask a question that depends on a chart or diagram inside a processed document.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'},
        ],
        images=[
            {'title': 'Upload a Document With Figures', 'label': 'Upload', 'caption': 'Upload a report or deck that contains charts, diagrams, or scanned figures from Personal Workspace.'},
            {'title': 'Check the Extraction Badge', 'label': 'Extraction Badge', 'caption': 'The document row badge names the extraction engine that ran and explains any fallback.'},
            {'title': 'Ask About a Chart', 'label': 'Chart Answer', 'caption': 'Ground a chat on the document and ask a question that can only be answered from a figure.'},
        ],
    ),
    _latest_feature_card(
        'release_260_office_embedded_images',
        'Pictures Inside Word and PowerPoint Are Now Searchable',
        'bi-image',
        'Images embedded in Word and PowerPoint files, including SmartArt, Visio drawings, and chart graphics, are now analyzed and cited with the correct page or slide.',
        'SimpleChat now pulls images out of DOCX, PPTX, and the legacy DOC and PPT formats, including EMF and WMF metafile diagrams that older Office documents use. Each image is indexed as its own citable chunk with proper page or slide attribution, duplicate images are collapsed, and figures stay in the same chunk as the text around them instead of being dumped at the end of the document.',
        'This matters because architecture diagrams, org charts, and process flows are often the whole point of a deck, and citations now point at the slide those visuals actually live on.',
        [
            'Upload a Word document or PowerPoint deck that contains diagrams, SmartArt, or embedded charts.',
            'Let processing finish, then open the document details to see the extracted image chunks.',
            'Confirm each image chunk reports the page or slide number it came from.',
            'Open Chat and ground a conversation on that document.',
            'Ask about something that only appears in a diagram, such as a process step or a box in an org chart.',
            'Open the citation on the answer and confirm it points at the correct slide or page.',
            'For documents uploaded before this release, use Change Extraction or re-upload so figures land in the right chunk.',
        ],
        actions=[
            {'label': 'Open Personal Workspace', 'description': 'Upload a Word or PowerPoint file and inspect the extracted image chunks.', 'href': '/workspace#documents-tab', 'icon': 'bi-folder2-open', 'requires_settings': ['enable_user_workspace']},
            {'label': 'Open Chat', 'description': 'Ask a question about a diagram and check the returned citation.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'},
        ],
        images=[
            {'title': 'Upload a Deck With Diagrams', 'label': 'Deck Upload', 'caption': 'Word and PowerPoint files with SmartArt, Visio drawings, or charts are now fully analyzed.'},
            {'title': 'Image Chunks With Slide Numbers', 'label': 'Image Chunks', 'caption': 'Each embedded image becomes its own citable chunk carrying the correct page or slide attribution.'},
            {'title': 'Citation Points at the Slide', 'label': 'Slide Citation', 'caption': 'Answers drawn from a diagram cite the exact slide the visual appears on.'},
        ],
    ),
    _latest_feature_card(
        'release_260_workflow_task_sequences',
        'Multi-Step Workflows With Alert Rules',
        'bi-diagram-3',
        'Workflows can now run an ordered sequence of tasks, each with its own model, agent, and documents, and can notify you through configurable alert rules instead of a single priority setting.',
        'The workflow builder is now a stepped experience covering General, Trigger, Tasks, Reliability, and Review. Each task chooses its own model or agent, sets its own document action and targets, and passes context forward to the next task. Alerts moved to a rules engine supporting run status, text matches, regular expressions, File Sync results, and AI-judged conditions across five severity levels. Runs can also be cancelled while in flight.',
        'This matters because real work is rarely one prompt, and chaining steps with targeted notifications turns a workflow into something you can trust to run unattended.',
        [
            'Open Personal Workspace and go to the Workflows section, or open Group Workspaces for a shared workflow.',
            'Create a workflow and step through General and Trigger to name it and choose when it runs.',
            'In the Tasks step, add your first instruction task and pick the model or agent that should run it.',
            'Set that task document action and choose the specific documents it should operate on.',
            'Add a second task and reference what the first task produced so the steps build on each other.',
            'In the Reliability step, set retry and failure handling for tasks that call external systems.',
            'In the Review step, add alert rules such as notify on failure or notify when the output matches a phrase, then save and run it.',
        ],
        actions=[
            {'label': 'Open Personal Workspace', 'description': 'Build or run a personal workflow from the Workflows section.', 'href': '/workspace', 'icon': 'bi-folder2-open', 'requires_settings': ['enable_user_workspace']},
            {'label': 'Open Group Workspaces', 'description': 'Build or run a shared group workflow.', 'href': '/group_workspaces', 'icon': 'bi-people', 'requires_settings': ['enable_group_workspaces']},
            {'label': 'Open Workflow Activity', 'description': 'Review running, completed, failed, and cancelled workflow runs.', 'href': '/workflow-activity', 'icon': 'bi-activity'},
        ],
        images=[
            {'title': 'Stepped Workflow Builder', 'label': 'Builder Steps', 'caption': 'General, Trigger, Tasks, Reliability, and Review guide you through building a workflow.'},
            {'title': 'Per-Task Model and Documents', 'label': 'Task Setup', 'caption': 'Each task picks its own model or agent and its own document action and targets.'},
            {'title': 'Alert Rules in the Review Step', 'label': 'Alert Rules', 'caption': 'Rules can notify on status, text match, regular expression, File Sync result, or an AI-judged condition.'},
        ],
    ),
    _latest_feature_card(
        'release_260_mcp_platform',
        'Model Context Protocol Connections',
        'bi-plug',
        'SimpleChat can now act as a governed MCP server for approved external clients, and outbound MCP actions gained presets, preconfigured catalogs, and a Test Connection button.',
        'Model Context Protocol connections work in both directions. Outbound, your agents reach MCP servers using presets and admin-curated catalogs rather than hand-typed configuration, and you can verify a connection before saving it. Inbound, approved MCP clients can reach SimpleChat conversations, documents, prompts, tags, and workflow tools under admin governance.',
        'This matters because it lets SimpleChat participate in the wider tool ecosystem your organization already uses, without every team hand-rolling its own integration.',
        [
            'Open Personal Workspace and go to the Actions section, or open Agents if you are wiring an agent directly.',
            'Create a new action and choose the MCP action type.',
            'Pick a preset or an admin-preconfigured server entry instead of typing the connection by hand.',
            'Fill in any remaining destination and authentication details the preset does not cover.',
            'Click Test Connection and confirm the server responds before saving.',
            'Attach the saved action to an agent so it can call those MCP tools during a conversation.',
            'Open Chat, select that agent, and ask something that requires the connected MCP tool.',
        ],
        actions=[
            {'label': 'Open Personal Workspace', 'description': 'Create and test an MCP action from the Actions section.', 'href': '/workspace', 'icon': 'bi-folder2-open', 'requires_settings': ['enable_user_workspace']},
            {'label': 'Open Agents', 'description': 'Attach a saved MCP action to an agent.', 'href': '/agents', 'icon': 'bi-robot', 'requires_settings': ['enable_semantic_kernel']},
        ],
        images=[
            {'title': 'Choose an MCP Preset', 'label': 'MCP Presets', 'caption': 'Presets and admin-curated catalogs replace hand-typed MCP server configuration.'},
            {'title': 'Test the Connection', 'label': 'Test Connection', 'caption': 'Verify the MCP server responds before saving the action.'},
            {'title': 'Review the MCP Configuration', 'label': 'MCP Summary', 'caption': 'The final step lists the transport, preset, timeouts, and the exact tools the action will expose.'},
        ],
    ),
    _latest_feature_card(
        'release_260_yamcs_action',
        'Yamcs Mission Control Integration',
        'bi-broadcast',
        'A new Yamcs action type connects agents to Yamcs mission control servers with eleven read-only tools covering telemetry, parameters, events, packets, alarms, and archive queries.',
        'The Yamcs action is strictly read-only by design, so an agent can investigate mission data but cannot command a spacecraft. Archive SQL access is opt-in and enforced as SELECT-only. Several authentication methods are supported, and a dedicated configuration panel plus a Test Connection button make setup verifiable before you rely on it.',
        'This matters because mission operators can ask plain-language questions about telemetry and alarms instead of hand-writing queries against the archive.',
        [
            'Open Personal Workspace and go to the Actions section.',
            'Create a new action and choose the Yamcs action type.',
            'Enter your Yamcs server address and pick the authentication method your instance uses.',
            'Leave archive SQL disabled unless you specifically need archive queries, then enable it deliberately.',
            'Click Test Connection to confirm SimpleChat can reach the server and read an instance.',
            'Attach the saved action to an agent, then open Agents to confirm the eleven Yamcs tools are listed.',
            'Open Chat, select that agent, and ask about recent telemetry, parameters, events, or active alarms.',
        ],
        actions=[
            {'label': 'Open Personal Workspace', 'description': 'Create and test a Yamcs action from the Actions section.', 'href': '/workspace', 'icon': 'bi-folder2-open', 'requires_settings': ['enable_user_workspace']},
            {'label': 'Open Agents', 'description': 'Attach the Yamcs action to an agent that answers mission questions.', 'href': '/agents', 'icon': 'bi-robot', 'requires_settings': ['enable_semantic_kernel']},
        ],
        images=[
            {'title': 'Configure the Yamcs Action', 'label': 'Yamcs Setup', 'caption': 'A dedicated panel collects the server address, authentication method, and optional archive SQL access.'},
            {'title': 'Verify With Test Connection', 'label': 'Connection Test', 'caption': 'Confirm SimpleChat can reach the Yamcs instance before relying on the action.'},
            {'title': 'Review the Yamcs Configuration', 'label': 'Configuration Summary', 'caption': 'The summary confirms the instance, processor, authentication, TLS, limits, and archive SQL state before saving.'},
        ],
    ),
    _latest_feature_card(
        'release_260_rocksdb_action',
        'RocksDB Key-Value Store Action',
        'bi-hdd-rack',
        'A new RocksDB action type lets agents read from an ordered key-value store through a conforming HTTP and JSON service, with get, scan, and stats tools.',
        'The RocksDB action targets an HTTP and JSON service in front of a RocksDB store. It exposes get, scan, and stats tools for reads, plus guarded write operations, and supports no-auth, bearer token, and API key authentication. A dedicated configuration card and a Test Connection button let you confirm the endpoint before saving.',
        'This matters because ordered key-value data is common in telemetry and logging systems, and agents can now query it directly instead of asking a person to run a lookup.',
        [
            'Open Personal Workspace and go to the Actions section.',
            'Create a new action and choose the RocksDB action type.',
            'Enter the base address of the HTTP and JSON service that fronts your RocksDB store.',
            'Choose no-auth, bearer token, or API key authentication to match that service.',
            'Click Test Connection and confirm the endpoint responds before saving.',
            'Attach the saved action to an agent and confirm the get, scan, and stats tools appear.',
            'Open Chat, select that agent, and ask for a specific key or a range scan over a key prefix.',
        ],
        actions=[
            {'label': 'Open Personal Workspace', 'description': 'Create and test a RocksDB action from the Actions section.', 'href': '/workspace', 'icon': 'bi-folder2-open', 'requires_settings': ['enable_user_workspace']},
            {'label': 'Open Agents', 'description': 'Attach the RocksDB action to an agent.', 'href': '/agents', 'icon': 'bi-robot', 'requires_settings': ['enable_semantic_kernel']},
        ],
        images=[
            {'title': 'Configure the RocksDB Action', 'label': 'RocksDB Setup', 'caption': 'Point the action at the HTTP and JSON service fronting your key-value store.'},
            {'title': 'Choose an Authentication Mode', 'label': 'Auth Options', 'caption': 'No-auth, bearer token, and API key authentication are all supported.'},
            {'title': 'Review the Keyspace Configuration', 'label': 'Keyspace Summary', 'caption': 'The summary confirms read-only access, encodings, limits, and the key prefixes the model is told about.'},
        ],
    ),
    _latest_feature_card(
        'release_260_agent_instruction_references',
        'Reference Actions and Knowledge Directly in Agent Instructions',
        'bi-robot',
        'Agent instructions can now name the exact actions and documents an agent holds using autocompleted hash-action and hash-knowledge tokens, and the agent builder reorders its steps so instructions come last.',
        'While writing agent instructions you can type a hash character to open an autocomplete listing the actions, capabilities, and documents that agent actually has, then insert a precise reference instead of describing the tool in prose. The agent modal now runs Actions, then Knowledge, then Instructions, so you choose capabilities before you write about them, and a collapsible summary panel shows your selections while you write.',
        'This matters because vague instructions are the most common reason an agent ignores a tool you gave it, and naming the capability directly removes that guesswork.',
        [
            'Open Agents and create a new agent or edit an existing one.',
            'Work through the Actions step first and attach the actions this agent should be able to call.',
            'Move to the Knowledge step and select the workspaces or documents it should ground on.',
            'Continue to the Instructions step and expand the summary panel to review what you selected.',
            'Start typing a hash character in the instruction editor to open the reference autocomplete.',
            'Insert an action or knowledge reference so the instruction names the capability exactly.',
            'Use Draft Instructions if you want a starting point, then save and test the agent in Chat.',
        ],
        actions=[
            {'label': 'Open Agents', 'description': 'Create or edit an agent and use the instruction reference autocomplete.', 'href': '/agents', 'icon': 'bi-robot', 'requires_settings': ['enable_semantic_kernel']},
            {'label': 'Open Chat', 'description': 'Select your agent and confirm it uses the referenced actions and knowledge.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'},
        ],
        images=[
            {'title': 'Actions and Knowledge Come First', 'label': 'Step Order', 'caption': 'The agent builder now runs Actions, then Knowledge, then Instructions.'},
            {'title': 'Reference Autocomplete', 'label': 'Autocomplete', 'caption': 'Typing a hash character lists the actions, capabilities, and documents this agent actually holds.'},
            {'title': 'Selection Summary While Writing', 'label': 'Summary Panel', 'caption': 'A collapsible panel keeps your selected actions and knowledge visible as you write instructions.'},
        ],
    ),
    _latest_feature_card(
        'release_260_action_test_connection',
        'Test Connection Before You Save an Action',
        'bi-wifi',
        'Test Connection is now available across twelve action types, verifying credentials and reachability without making you re-enter stored secrets.',
        'OpenAPI, Azure Maps, Blob Storage, Databricks, Log Analytics, MCP, Snowflake, Tableau, RocksDB, Yamcs, SQL, and Cosmos DB actions all support Test Connection. The test resolves secrets stored in Key Vault on the server side, so you never retype a credential to check it. A successful test reports useful detail about what it reached, and a failure names the specific cause rather than a generic error.',
        'This matters because a broken action used to surface as a confusing failure mid-conversation, and now you find out at setup time with a message that tells you what to fix.',
        [
            'Open Personal Workspace and go to the Actions section.',
            'Create a new action or open an existing one that is not behaving as expected.',
            'Fill in the connection details for the action type you are configuring.',
            'Click Test Connection and wait for the result rather than saving immediately.',
            'On success, read the returned detail to confirm you reached the intended system and scope.',
            'On failure, read the named cause and correct just that field, then test again.',
            'Save the action once the test passes, then attach it to an agent.',
        ],
        actions=[
            {'label': 'Open Personal Workspace', 'description': 'Test any configured action from the Actions section.', 'href': '/workspace', 'icon': 'bi-folder2-open', 'requires_settings': ['enable_user_workspace']},
            {'label': 'Open Agents', 'description': 'Attach a verified action to an agent.', 'href': '/agents', 'icon': 'bi-robot', 'requires_settings': ['enable_semantic_kernel']},
        ],
        images=[
            {'title': 'Test Connection Button', 'label': 'Test Button', 'caption': 'Twelve action types now expose a Test Connection control during setup.'},
            {'title': 'Successful Test Detail', 'label': 'Success Detail', 'caption': 'A passing test reports what it reached so you can confirm the scope is right.'},
            {'title': 'Named Failure Cause', 'label': 'Failure Cause', 'caption': 'A failing test names the specific problem instead of returning a generic error.'},
        ],
    ),
    _latest_feature_card(
        'release_260_azure_blob_file_sync',
        'Sync Documents From Azure Blob Storage',
        'bi-cloud-upload',
        'Azure Blob Storage containers can now be used as File Sync sources for personal, group, and public workspaces, with folder browsing and change detection.',
        'Blob Storage joins the existing File Sync connectors. Sources support managed identity, Key Vault backed service principals, connection strings, and SAS tokens, and you can browse virtual folders rather than typing paths blind. Change detection uses ETags so only changed blobs are reprocessed, and prefix and filter controls keep a sync narrow.',
        'This matters because a lot of organizational content already lives in blob containers, and syncing it keeps workspace documents current without manual re-uploads.',
        [
            'Open Personal Workspace and go to the Sync section.',
            'Add a new sync source and choose Azure Blob Storage.',
            'Select the authentication method your container uses, such as managed identity or a SAS token.',
            'Browse the virtual folders in the container and pick the prefix you want to sync.',
            'Apply filters so only the file types you care about are pulled in.',
            'Run the sync and watch the status, counts, and history for that source.',
            'Open the Documents section and confirm the synced files appear with their sync badges.',
        ],
        actions=[
            {'label': 'Open Workspace Sync', 'description': 'Add an Azure Blob Storage sync source and run it.', 'href': '/workspace?feature_action=file_sync', 'icon': 'bi-arrow-repeat', 'requires_settings': ['enable_user_workspace']},
            {'label': 'Open Group Workspaces', 'description': 'Configure a blob sync source for a shared group workspace.', 'href': '/group_workspaces', 'icon': 'bi-people', 'requires_settings': ['enable_group_workspaces']},
        ],
        images=[
            {'title': 'Add a Blob Storage Source', 'label': 'Add Source', 'caption': 'Azure Blob Storage is now a first-class File Sync connector.'},
            {'title': 'Browse Virtual Folders', 'label': 'Folder Browser', 'caption': 'Pick the container prefix visually instead of typing a path blind.'},
            {'title': 'Review Sync Status', 'label': 'Sync Status', 'caption': 'Status, counts, and history show what was pulled in and what changed.'},
        ],
    ),
    _latest_feature_card(
        'release_260_terms_of_use',
        'Terms of Use Acceptance',
        'bi-file-earmark-text',
        'Your organization can require you to accept a terms of use or rules of behavior notice before using SimpleChat, with the reminder repeating on a schedule your admins choose.',
        'When enabled, an acceptance screen appears before you reach the app. Admins choose whether it returns every session, once per day, or only when the text changes. Your accept and decline choices are recorded in the activity log, and the gate is enforced on the server so it cannot be skipped by navigating directly to a page.',
        'This matters because many organizations must record that users acknowledged acceptable-use rules before working with an AI assistant.',
        [
            'Sign in to SimpleChat and read the terms of use notice if your organization has enabled one.',
            'Scroll through the full text before responding, since the content is set by your organization.',
            'Choose Accept to continue into the app.',
            'Expect the notice to reappear according to the schedule your admins configured.',
            'If the wording changes, expect to be asked again even if you accepted the earlier version.',
            'Choose Decline if you do not agree, which will end your session rather than continuing.',
            'Contact your admin if you believe the notice is appearing more often than intended.',
        ],
        actions=[],
        images=[
            {'title': 'Acceptance Screen', 'label': 'Terms Screen', 'caption': 'The notice appears before you reach the app when your organization enables it.'},
            {'title': 'Accept or Decline', 'label': 'Accept', 'caption': 'Accepting continues into SimpleChat and is recorded in the activity log.'},
            {'title': 'Recurring Reminder', 'label': 'Recurrence', 'caption': 'Admins choose whether the notice returns every session, daily, or only when the text changes.'},
        ],
    ),
    _latest_feature_card(
        'release_260_audio_file_support',
        'Upload Almost Any Audio File',
        'bi-mic',
        'Audio uploads now cover a much wider set of formats including AAC, FLAC, M4A, OGG, Opus, WAV, WebM audio, and WMA.',
        'Media handling is now bundled directly into SimpleChat container builds, which greatly expands the audio formats it can recognize and transcribe. Transcription degrades gracefully when the media tooling is unavailable rather than failing outright, and iPhone M4A voice memo uploads work correctly.',
        'This matters because meeting recordings and voice memos arrive in whatever format the recording device produced, and converting them by hand first was a real obstacle.',
        [
            'Open Personal Workspace and go to the Documents section.',
            'Upload an audio file in whatever format you have, such as an iPhone M4A voice memo or a WAV recording.',
            'Wait for the file to finish processing and produce a transcript.',
            'Open the document details and read the transcript that was generated.',
            'Open Chat and ground a conversation on that audio file.',
            'Ask for a summary, decisions, or action items from the recording.',
            'Check the returned citation to confirm it points back at the audio document.',
        ],
        actions=[
            {'label': 'Open Personal Workspace', 'description': 'Upload an audio recording and review its transcript.', 'href': '/workspace#documents-tab', 'icon': 'bi-folder2-open', 'requires_settings': ['enable_user_workspace']},
            {'label': 'Open Chat', 'description': 'Ask for a summary or action items from a transcribed recording.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'},
        ],
        images=[
            {'title': 'Upload a Recording', 'label': 'Audio Upload', 'caption': 'AAC, FLAC, M4A, OGG, Opus, WAV, WebM audio, WMA, and more are recognized.'},
            {'title': 'Review the Transcript', 'label': 'Transcript', 'caption': 'The generated transcript becomes searchable text on the document.'},
            {'title': 'Ask About the Recording', 'label': 'Audio Q&A', 'caption': 'Ground a chat on the audio file and ask for decisions or action items.'},
        ],
    ),
    _latest_feature_card(
        'release_260_completion_notifications',
        'Know When a Long Answer Finishes',
        'bi-bell',
        'You can opt in to a sound when a response completes, a desktop notification when the answer lands in a tab you are not looking at, or both.',
        'Two independent opt-in preferences live on your profile. Completion audio cues offer ten bundled sounds with volume control and a preview button. Desktop notifications use your browser notification permission and appear when the response finishes in a hidden or unfocused tab, showing only the app and conversation title rather than the response content, and clicking one focuses the existing tab instead of opening a new one.',
        'This matters because long research answers are worth stepping away from, and there was previously no way to know the response had arrived.',
        [
            'Open your Profile page and find the notification and audio preferences.',
            'Turn on completion audio cues if you want an audible signal.',
            'Pick one of the ten available sounds and set the volume, using preview to hear it.',
            'Turn on desktop notifications separately if you want alerts for background tabs.',
            'Allow the browser notification permission prompt when it appears.',
            'Open Chat, ask a question that takes a while, and switch to another tab.',
            'Confirm you get the notification and that clicking it returns you to the existing tab.',
        ],
        actions=[
            {'label': 'Open Profile', 'description': 'Turn on completion sounds and desktop notifications for your account.', 'href': '/profile', 'icon': 'bi-person-gear'},
            {'label': 'Open Chat', 'description': 'Ask a longer question and confirm the completion signal works.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'},
        ],
        images=[
            {'title': 'Notification Preferences', 'label': 'Preferences', 'caption': 'Completion sounds and desktop notifications are separate opt-in settings on your profile.'},
            {'title': 'Choose a Sound', 'label': 'Sound Picker', 'caption': 'Ten bundled sounds with volume control and a preview button.'},
            {'title': 'Desktop Notification', 'label': 'Desktop Alert', 'caption': 'Background tabs show the app and conversation title without revealing response content.'},
        ],
    ),
    _latest_feature_card(
        'release_260_chat_ai_notice',
        'AI Usage Guidance in Chat',
        'bi-info-circle',
        'Your organization can display its own AI guidance directly under the chat composer, with control over how often it reappears.',
        'Admins write the notice in Markdown and choose how it behaves: always visible, dismissible for the session, dismissible for the day, or dismissible until the wording changes. If your organization updates the text, the notice comes back automatically so you see the current guidance rather than a stale version you dismissed months ago.',
        'This matters because AI usage rules differ by organization, and the reminder is most useful sitting right where you type rather than buried in a policy document.',
        [
            'Open Chat and look directly beneath the message composer.',
            'Read the AI usage notice if your organization has configured one.',
            'Follow any links in the notice for your local policy details.',
            'Dismiss the notice if your admins allowed dismissal and you have read it.',
            'Expect it to return based on the schedule your admins chose, such as each session or each day.',
            'Watch for it to reappear automatically whenever your organization updates the wording.',
            'Contact your admin if the guidance looks out of date for your team.',
        ],
        actions=[
            {'label': 'Open Chat', 'description': 'View the AI usage notice beneath the message composer.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'},
        ],
        images=[
            {'title': 'Notice Under the Composer', 'label': 'AI Notice', 'caption': 'Organization-specific AI guidance appears directly where you type.'},
            {'title': 'Dismiss When Allowed', 'label': 'Dismiss', 'caption': 'Admins choose whether the notice is permanent, per session, daily, or until the text changes.'},
            {'title': 'Returns When Updated', 'label': 'Auto Return', 'caption': 'Updated guidance reappears automatically instead of staying dismissed.'},
        ],
    ),
    _latest_feature_card(
        'release_260_conversation_context_grounding',
        'See Exactly What Shaped Each Answer',
        'bi-chat-quote',
        'Every response now carries a Conversation Context citation showing the model, app version, workspace scope, selected documents, agent, and capabilities that were active when it was written.',
        'The context snapshot is both given to the model as hidden grounding and shown to you as a citation on the response. It covers streaming answers, retries, fallbacks, collaboration conversations, and document actions, so the record is consistent no matter which path produced the answer.',
        'This matters because when an answer surprises you, the first question is usually which model and which documents were actually in play, and now that is one click away.',
        [
            'Open Chat and send any question.',
            'When the response arrives, open the citations area on that message.',
            'Select the Conversation Context citation.',
            'Review the model name and SimpleChat version that produced the answer.',
            'Check the workspace scope and the specific documents that were selected.',
            'Confirm which agent and which capabilities were active for that turn.',
            'Change your model or document selection, ask again, and compare the two context snapshots.',
        ],
        actions=[
            {'label': 'Open Chat', 'description': 'Send a message and open the Conversation Context citation on the response.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'},
        ],
        images=[
            {'title': 'Context Citation on a Response', 'label': 'Context Citation', 'caption': 'Every answer carries a Conversation Context citation alongside Conversation History and Instruction Memory.'},
            {'title': 'Document Sources', 'label': 'Document Sources', 'caption': 'Statements drawn from a workspace document cite the source file and the page they came from.'},
            {'title': 'Scope and Generation Detail', 'label': 'Generation Detail', 'caption': 'The detail panel records the model, workspace action, retrieval flags, and agent citations behind the answer.'},
        ],
    ),
    _latest_feature_card(
        'release_260_used_documents_fork',
        'Used Documents View and Conversation Forking',
        'bi-journals',
        'A Used Documents mode shows only the documents actually cited in a conversation, and you can fork a conversation from any response to explore a different direction.',
        'The chat side pane gained a Used Documents mode that lists the documents a conversation has genuinely drawn on, without opening the full details modal, and it opens automatically the first time cited documents appear. Separately, forking from an assistant response creates an independent copy of the conversation through that message, so the original stays intact.',
        'This matters because long conversations accumulate a lot of context, and both knowing what was actually used and being able to branch without losing the thread are hard problems otherwise.',
        [
            'Open Chat and start a conversation grounded on several workspace documents.',
            'Ask a few questions so the assistant cites real sources.',
            'Watch the side pane open to Used Documents the first time a citation appears.',
            'Switch the side pane to Used Documents manually at any time to see the current list.',
            'Confirm the list shows only documents that were genuinely cited, not everything in scope.',
            'Find an assistant response where you want to try a different direction and choose to fork from it.',
            'Work in the forked copy and confirm the original conversation is unchanged.',
        ],
        actions=[
            {'label': 'Open Chat', 'description': 'Use the Used Documents pane and fork a conversation from a response.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'},
            {'label': 'Open Conversations', 'description': 'Find the forked copy alongside the original conversation.', 'href': '/conversations', 'icon': 'bi-chat-left-text'},
        ],
        images=[
            {'title': 'Used Documents Pane', 'label': 'Used Documents', 'caption': 'The side pane lists only the documents the conversation actually cited.'},
            {'title': 'Fork From a Response', 'label': 'Fork', 'caption': 'Branch from any assistant response into an independent copy of the conversation.'},
            {'title': 'Original Stays Intact', 'label': 'Both Threads', 'caption': 'The forked copy and the original conversation both remain available.'},
        ],
    ),
    _latest_feature_card(
        'release_260_conversation_contents_drawer',
        'Jump Back to Any Earlier Prompt',
        'bi-layout-text-sidebar',
        'A contents drawer indexes the questions you asked in a conversation so you can jump straight back to any of them instead of scrolling.',
        'The drawer lists your saved prompts as navigable entries and tracks where you currently are in the conversation. It is on by default when your admins enable it, works with keyboard navigation, and adapts to an off-canvas panel on smaller screens. You can hide it for your own account from your profile if you prefer a wider chat area.',
        'This matters because a long working session becomes hard to navigate, and the thing you want to return to is almost always a question you already asked.',
        [
            'Open Chat and continue a conversation that already has many messages.',
            'Find the conversation contents drawer beside the message area.',
            'Scan the list of your earlier prompts to locate the point you want.',
            'Select an entry to jump directly to that place in the conversation.',
            'Notice the drawer tracks your current position as you scroll.',
            'On a smaller screen, open the drawer as an off-canvas panel instead.',
            'Open your Profile and hide the drawer for your account if you would rather have the space.',
        ],
        actions=[
            {'label': 'Open Chat', 'description': 'Use the contents drawer to jump between earlier prompts.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'},
            {'label': 'Open Profile', 'description': 'Show or hide the conversation contents drawer for your account.', 'href': '/profile', 'icon': 'bi-person-gear'},
        ],
        images=[
            {'title': 'Contents Drawer', 'label': 'Drawer', 'caption': 'Your earlier prompts are indexed as navigable entries; select one to move straight to that point in a long conversation.'},
            {'title': 'Hide It If You Prefer', 'label': 'Profile Toggle', 'caption': 'Each user can hide the drawer from their own profile page.'},
        ],
    ),
    _latest_feature_card(
        'release_260_font_size_zoom',
        'Choose Your Text Size',
        'bi-fonts',
        'Five font size choices ranging from 75 percent to 200 percent are available on your profile, and the interface stays usable at 200 percent browser zoom.',
        'Font size is a saved per-user preference, so it follows you across sessions rather than resetting. Alongside it, chat, top navigation, classification banners, and the sidebar were reworked to remain fully usable when the browser itself is zoomed to 200 percent.',
        'This matters because readable text is an accessibility requirement, not a preference, and layouts that break under zoom effectively lock people out.',
        [
            'Open your Profile page and find the font size preference.',
            'Choose from the five available sizes ranging from extra small to extra large.',
            'Save the preference and return to Chat to see it applied.',
            'Confirm the size persists after you sign out and back in.',
            'Separately, set your browser zoom to 200 percent to check the layout.',
            'Confirm the chat area, top navigation, and sidebar all remain usable at that zoom level.',
            'Adjust between the font preference and browser zoom to find the combination that reads best.',
        ],
        actions=[
            {'label': 'Open Profile', 'description': 'Choose your preferred font size.', 'href': '/profile', 'icon': 'bi-person-gear'},
            {'label': 'Open Chat', 'description': 'Confirm your font size preference applied to the conversation view.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'},
        ],
        images=[
            {'title': 'Font Size Preference', 'label': 'Font Sizes', 'caption': 'Five sizes from 75 percent to 200 percent, saved to your account.'},
            {'title': 'Applied Across Chat', 'label': 'Applied', 'caption': 'The preference follows you across sessions rather than resetting.'},
            {'title': 'Usable at 200 Percent Zoom', 'label': 'Zoom Support', 'caption': 'Chat, navigation, banners, and sidebar remain usable at full browser zoom.'},
        ],
    ),
    _latest_feature_card(
        'release_260_message_audio_export',
        'Download a Response as Audio',
        'bi-file-earmark-music',
        'Any completed chat message can be exported as an MP3 using the configured speech voice and speed.',
        'The export uses the active Azure Speech voice and speed settings for your environment and produces a normal MP3 download. The audio is generated on demand and is not stored in SimpleChat, so nothing is retained after the download completes.',
        'This matters because a long answer is sometimes easier to absorb on a commute than on a screen.',
        [
            'Open Chat and find a completed assistant response you want to listen to.',
            'Open the message actions for that response.',
            'Choose the option to export the message as audio.',
            'Wait for the MP3 to be generated from the configured speech voice.',
            'Save the downloaded file when your browser prompts you.',
            'Play it back in any normal audio player.',
            'Repeat on another message and note that nothing is stored in SimpleChat between exports.',
        ],
        actions=[
            {'label': 'Open Chat', 'description': 'Export a completed response as an MP3 download.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'},
        ],
        images=[
            {'title': 'Message Actions', 'label': 'Message Menu', 'caption': 'Audio export sits alongside the other actions on a completed response.'},
            {'title': 'Generate the MP3', 'label': 'Generate', 'caption': 'The export uses the configured Azure Speech voice and speed settings.'},
            {'title': 'Download and Listen', 'label': 'Download', 'caption': 'The file downloads normally and is not retained in SimpleChat.'},
        ],
    ),
    _latest_feature_card(
        'release_260_public_workspace_display_name',
        'Public Workspace Can Carry Your Own Name',
        'bi-building',
        'Your organization can rename the Public Workspace to something meaningful such as Domain Knowledge, and the new name appears everywhere in the interface.',
        'When admins set a display name, it replaces the generic label across navigation, your profile, chat scope selection, and directory pages. Only the label changes; the underlying workspace, its documents, and every link continue to work exactly as before.',
        'This matters because shared knowledge collections usually already have a name inside your organization, and matching it removes a translation step for everyone.',
        [
            'Open Chat and look at the workspace scope selector.',
            'Note the name your organization chose in place of the default Public Workspace label.',
            'Open your Profile and confirm the same name appears there.',
            'Check the navigation and directory pages for the same consistent label.',
            'Select that workspace as your chat scope and ask a question against it.',
            'Confirm documents and citations behave exactly as they did before the rename.',
            'Ask your admin if the label does not match what your team calls this collection.',
        ],
        actions=[
            {'label': 'Open Chat', 'description': 'See the workspace name in the chat scope selector.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'},
            {'label': 'Open Profile', 'description': 'Confirm the same workspace name appears on your profile.', 'href': '/profile', 'icon': 'bi-person-gear'},
        ],
        images=[
            {'title': 'Set the End-User Label', 'label': 'Display Name', 'caption': 'An optional display name replaces Public Workspace everywhere end users see it.'},
            {'title': 'Consistent Across Navigation', 'label': 'Navigation', 'caption': 'The same label appears in navigation, profile, and directory pages.'},
            {'title': 'Behavior Is Unchanged', 'label': 'Same Behavior', 'caption': 'Chat scope selection, documents, and citations work exactly as before; only the label changes.'},
        ],
    ),
    _latest_feature_card(
        'release_260_chat_scroll_508',
        'Chat Stops Yanking You to the Bottom',
        'bi-arrow-down-circle',
        'The conversation no longer jumps to the bottom while you are reading further up, and a floating control takes you to the newest content when you want it.',
        'Previously, new streaming content pulled the viewport down even when you had deliberately scrolled up to read something. Now the view stays where you put it, and a floating scroll-to-latest button appears when there is newer content below your current position. The change also improves the experience for keyboard users and screen reader testing.',
        'This matters because losing your place mid-paragraph while an answer is still streaming makes long responses genuinely hard to read.',
        [
            'Open Chat and ask a question that produces a long streaming answer.',
            'While it is still generating, scroll up to re-read an earlier part of the response.',
            'Confirm the view stays where you put it instead of snapping back down.',
            'Look for the floating scroll-to-latest control that appears near the bottom.',
            'Select it when you are ready to return to the newest content.',
            'Try the same flow using only the keyboard to move through the conversation.',
            'Confirm focus order stays sensible as new content arrives.',
        ],
        actions=[
            {'label': 'Open Chat', 'description': 'Scroll up during a long streaming answer and confirm the view holds.', 'href': '/chats#chatbox', 'icon': 'bi-chat-dots'},
        ],
        images=[
            {'title': 'Read While It Streams', 'label': 'Stable View', 'caption': 'Scrolling up during a streaming answer no longer snaps you back to the bottom.'},
            {'title': 'Scroll to Latest Control', 'label': 'Scroll Button', 'caption': 'A floating control appears when newer content is below your current position.'},
            {'title': 'Keyboard Friendly', 'label': 'Keyboard Use', 'caption': 'Focus order stays sensible as new content arrives.'},
        ],
    ),
]


_SUPPORT_LATEST_FEATURE_CATALOG = _SUPPORT_RELEASE_260_FEATURE_CATALOG

_SUPPORT_LATEST_FEATURE_RELEASE_GROUPS = [
    {
        'id': 'current_release',
        'label': 'Latest Features',
        'description': 'The SimpleChat 0.260.001 feature set your admins are currently sharing with end users.',
        'release_version': '0.260.001',
        'default_expanded': True,
        'collapse_id': 'supportLatestFeaturesCurrentRelease',
        'features': _SUPPORT_RELEASE_260_FEATURE_CATALOG,
    },
    {
        'id': 'previous_release',
        'label': 'Previous Release Features',
        'description': 'The v0.250.001 feature set remains available for reference after the v0.260.001 feature set became current.',
        'release_version': '0.250.001',
        'default_expanded': False,
        'collapse_id': 'supportLatestFeaturesPreviousRelease',
        'features': _SUPPORT_RELEASE_250_FEATURE_CATALOG,
    },
    {
        'id': 'archive_release',
        'label': 'Archive Release Features',
        'description': 'Older v0.239.001 through v0.241.007 highlights remain available for longer-term reference.',
        'release_version': '0.239.001 - 0.241.007',
        'default_expanded': False,
        'collapse_id': 'supportLatestFeaturesArchiveRelease',
        'features': _SUPPORT_RELEASE_241_FEATURE_CATALOG + _SUPPORT_RELEASE_239_FEATURE_CATALOG,
    },
]


_ADMIN_RELEASE_260_FEATURE_CATALOG = [
    _latest_feature_card(
        'admin_release_260_data_management',
        'Enterprise Data Management: Backup, Restore & Migration',
        'bi-database-check',
        'Admins can run durable backup, restore, migration, and inspection workflows from the refreshed Backup, Migrate & Restore experience.',
        'Backup jobs now cover Cosmos DB, AI Search, and Blob Storage with keyset paging, ETag verification, adaptive throttling, resume, and retention policies. Restore adds admin-only preflight checks, overwrite confirmation, durable restore jobs, and the migration engine supports delta and mirror modes with provenance tracking and per-resource checkpoints.',
        'This matters because tenant data operations can be planned, audited, resumed, and recovered without relying on one-off scripts.',
        [
            'Open Admin Settings > Backup, Migrate & Restore and review the setup guidance before enabling production jobs.',
            'Configure storage, source resources, and retention policies for Cosmos DB, AI Search, and Blob Storage backups.',
            'Use preflight checks and overwrite confirmations before running restore jobs against live tenant data.',
            'Choose delta or mirror migration mode deliberately and monitor per-resource checkpoints for long-running migrations.',
        ],
        actions=[
            {'label': 'Open Data Management', 'description': 'Configure backup, migration, restore, storage, and inspection workflows.', 'href': '#data-management', 'admin_tab': '#data-management', 'icon': 'bi-database'},
        ],
        image_label='Backup Restore',
    ),
    _latest_feature_card(
        'admin_release_260_keyvault_reminders',
        'Key Vault Secret Expiration Reminders',
        'bi-key',
        'Admins can track action secret expirations and route reminder signals before Key Vault-backed integrations break.',
        'The reminder inventory stores per-action secret expiration dates, lead days, contact emails, and rotation notes. A background sweep emits key_vault_secret_expiring in-app notifications and can also emit Application Insights telemetry for Azure Monitor alert routing, while secret replacement reliably writes a new Key Vault version.',
        'This matters because expiring integration secrets become visible operational work instead of surprise outages.',
        [
            'Open Admin Settings > Security and review Key Vault-backed action secret usage.',
            'Record expiration dates, reminder lead days, contact emails, and rotation notes for managed action secrets.',
            'Connect the optional Application Insights telemetry event to Azure Monitor alerts if central operations teams need escalation.',
            'After rotating a secret, confirm the replacement creates a new Key Vault version and update the reminder inventory.',
        ],
        actions=[
            {'label': 'Open Security', 'description': 'Review Key Vault secret storage and reminder configuration.', 'href': '#security', 'admin_tab': '#security', 'icon': 'bi-key'},
            {'label': 'Open Logging', 'description': 'Review telemetry routing for secret-expiration reminders.', 'href': '#logging', 'admin_tab': '#logging', 'icon': 'bi-activity'},
        ],
        image_label='Secret Reminders',
    ),
    _latest_feature_card(
        'admin_release_260_governance_block_lists',
        'Governance Policy Block Lists & Admin Policy Tools',
        'bi-shield-check',
        'Admins can explicitly block users or groups and manage policies faster with duplicate, inverse, and principal review tools.',
        'Governance policies now support block lists so a user or group can be denied even when allow-all or allow-list rules would otherwise grant access. Duplicate and Inverse actions speed policy creation, a Show Users modal helps review principals, and policy retargeting fixes prevent orphaned duplicates.',
        'This matters because exception handling and access reviews are easier to enforce across models, agents, actions, and delegated items.',
        [
            'Open Admin Settings > Governance and review policies that currently rely on broad allow-all access.',
            'Add block-list entries for users or groups that must be excluded from a capability.',
            'Use Duplicate or Inverse when creating related policies so deny and allow rules stay consistent.',
            'Open Show Users before rollout to confirm the resolved principals match the intended audience.',
        ],
        actions=[
            {'label': 'Open Governance', 'description': 'Configure allow and block policies for AI capabilities.', 'href': '#governance', 'admin_tab': '#governance', 'icon': 'bi-shield-check'},
        ],
        image_label='Policy Blocks',
    ),
    _latest_feature_card(
        'admin_release_260_model_identity_header',
        'Model Endpoint User Identity Header for APIM',
        'bi-person-badge',
        'Admins can send stable hashed user identity headers with model endpoint calls for APIM routing, quota, and attribution scenarios.',
        'The model endpoint path can include an HMAC-hashed user identity key without exposing raw UPN, object ID, or tenant ID. Configuration supports global enablement, custom header names, selectable identity inputs, and per-endpoint overrides.',
        'This matters because APIM policies can enforce per-user quotas and cost attribution without leaking direct user identifiers.',
        [
            'Open Admin Settings > AI Models and identify the endpoints routed through APIM.',
            'Enable the identity header globally only when downstream APIM policies are ready to consume it.',
            'Choose the header name and identity input that match the tenant quota or attribution design.',
            'Use per-endpoint overrides for providers that should not receive the hashed identity header.',
        ],
        actions=[
            {'label': 'Open AI Models', 'description': 'Configure model endpoint identity header behavior.', 'href': '#ai-models', 'admin_tab': '#ai-models', 'icon': 'bi-cpu'},
        ],
        image_label='Identity Header',
    ),
    _latest_feature_card(
        'admin_release_260_per_model_response_length',
        'Per-Model Output Token Ceilings',
        'bi-sliders',
        'Admins can set optional output-token ceilings per global model endpoint instead of relying on one tenant-wide response limit.',
        'Each model in the global multi-endpoint GPT configuration can now carry its own output-token ceiling. The chat path applies the correct backend token parameter for GPT-5 and o-series models as well as other OpenAI-compatible providers.',
        'This matters because administrators can balance cost, latency, and answer depth independently for each deployed model.',
        [
            'Open Admin Settings > AI Models and review each global GPT endpoint.',
            'Set an output-token ceiling for high-cost or latency-sensitive models that need tighter limits.',
            'Leave the ceiling empty for models that should keep provider or application defaults.',
            'Test representative prompts after changing limits to confirm responses remain useful for end users.',
        ],
        actions=[
            {'label': 'Open AI Models', 'description': 'Set per-model output token ceilings.', 'href': '#ai-models', 'admin_tab': '#ai-models', 'icon': 'bi-sliders'},
        ],
        image_label='Token Ceilings',
    ),
    _latest_feature_card(
        'admin_release_260_control_center_refresh',
        'Scheduled Overnight Control Center Refresh',
        'bi-arrow-repeat',
        'Admins can keep Control Center statistics fresh with a daily overnight refresh that is enabled by default.',
        'Control Center metrics refresh automatically at 2:00 AM Eastern each day when the admin schedule is enabled. The schedule follows daylight-saving changes and shows last-run and next-run times in the admin\'s local timezone.',
        'This matters because operational dashboards are ready at the start of the day without manual refresh work.',
        [
            'Open Admin Settings > Control Center and confirm the scheduled refresh toggle matches tenant operations policy.',
            'Review the displayed last-run and next-run times in the local timezone used by admins.',
            'Coordinate any heavy maintenance windows around the 2:00 AM Eastern default schedule.',
            'Check Control Center metrics after the first scheduled run to confirm overnight refresh behavior.',
        ],
        actions=[
            {'label': 'Open Control Center', 'description': 'Review scheduled statistics refresh settings and run timing.', 'href': '#control-center-config', 'admin_tab': '#control-center-config', 'icon': 'bi-arrow-repeat'},
        ],
        image_label='Nightly Refresh',
    ),
    _latest_feature_card(
        'admin_release_260_feedback_safety_lifecycle',
        'Feedback & Safety Violation Archive / Delete Lifecycle',
        'bi-archive',
        'Admins can archive, restore, or permanently delete feedback and safety records with audit-aware controls.',
        'Feedback Review and Safety Violation records now support archive, unarchive, and permanent delete actions. Archived records are hidden from user profile history, deletions require confirmation, violations with pending remediation approvals cannot be deleted, and lifecycle actions create audit records.',
        'This matters because moderation and feedback queues can be retained, cleaned up, and audited with clearer lifecycle rules.',
        [
            'Open Admin Settings > Safety and review active Safety Violation records before archiving or deleting anything.',
            'Use archive when records should leave user profile history but remain recoverable for administrative review.',
            'Resolve pending remediation approvals before attempting permanent deletion of safety violations.',
            'Review audit records after lifecycle actions to confirm the administrative history is complete.',
        ],
        actions=[
            {'label': 'Open Safety', 'description': 'Manage safety violation archive and delete lifecycle.', 'href': '#safety', 'admin_tab': '#safety', 'icon': 'bi-shield-exclamation'},
            {'label': 'Open Send Feedback', 'description': 'Review feedback records affected by archive and delete lifecycle controls.', 'href': '#send-feedback', 'admin_tab': '#send-feedback', 'icon': 'bi-chat-left-text'},
        ],
        include_media=False,
    ),
    _latest_feature_card(
        'admin_release_260_log_cleanup',
        'File Processing Log Cleanup',
        'bi-trash3',
        'Admins can remove old file-processing logs by retention window or purge all logs with confirmation and activity logging.',
        'Cleanup controls can permanently delete file-processing logs older than a configurable retention period measured in days, weeks, or months. Admins can also purge all logs, with confirmation dialogs, exact counts, and admin activity logging for each cleanup action.',
        'This matters because log growth can be controlled while preserving deliberate confirmation and auditability for destructive cleanup.',
        [
            'Open Admin Settings > Logging and review current file-processing log volume.',
            'Choose a retention period in days, weeks, or months that matches tenant support and audit needs.',
            'Review the exact count shown in the confirmation dialog before deleting old logs.',
            'Use purge-all only for intentional reset scenarios and confirm the admin activity log afterward.',
        ],
        actions=[
            {'label': 'Open Logging', 'description': 'Configure and run file-processing log cleanup.', 'href': '#logging', 'admin_tab': '#logging', 'icon': 'bi-trash3'},
        ],
        image_label='Log Cleanup',
    ),
    _latest_feature_card(
        'admin_release_260_redis_explorer',
        'Redis Explorer & Cache Observability Dashboard',
        'bi-speedometer2',
        'Admins can inspect Redis safely and monitor conversation and DAI cache behavior from Scale settings.',
        'Redis Explorer provides read-only, cursor-paginated key browsing with sensitive-key redaction and SimpleChat-specific DAI cache key resolution. Conversation cache and DAI cache dashboards show hit rate, miss, bypass, and invalidation events, while DAI Redis caching, conversation list/feed caching, and low-churn bootstrap caching include enable toggles, TTL controls, and invalidation coverage.',
        'This matters because cache performance and cache safety can be observed without exposing sensitive values or using direct Redis tooling.',
        [
            'Open Admin Settings > Scale and review Redis connection and cache enablement state.',
            'Use Redis Explorer for read-only key browsing when troubleshooting cache behavior.',
            'Review hit, miss, bypass, and invalidation metrics before changing TTL values.',
            'Keep sensitive-key redaction enabled and avoid using cache dashboards as a data export path.',
        ],
        actions=[
            {'label': 'Open Scale', 'description': 'Inspect Redis and review cache metrics, toggles, and TTLs.', 'href': '#scale', 'admin_tab': '#scale', 'icon': 'bi-speedometer2'},
        ],
        image_label='Cache Metrics',
    ),
    _latest_feature_card(
        'admin_release_260_index_auto_login',
        'Auto-Login on Home Page (Entra SSO)',
        'bi-shield-lock',
        'Admins can opt in to redirect unauthenticated home-page visits directly into Microsoft Entra sign-in.',
        'The ENABLE_AUTO_LOGIN_ON_INDEX setting sends unauthenticated visits to the home page into the Microsoft Entra sign-in flow. It supports government tenant SSO scenarios where users commonly already have a browser session.',
        'This matters because SSO-first tenants can reduce landing-page friction while keeping the behavior explicit and opt-in.',
        [
            'Open Admin Settings > Security and confirm Microsoft Entra authentication is the intended sign-in path.',
            'Enable home-page auto-login only for tenants where browser SSO is expected for most users.',
            'Validate the unauthenticated home-page flow in a private browser session before broad rollout.',
            'Document the opt-in redirect behavior for help desk teams that support first-time access.',
        ],
        actions=[
            {'label': 'Open Security', 'description': 'Review Entra SSO and home-page auto-login behavior.', 'href': '#security', 'admin_tab': '#security', 'icon': 'bi-shield-lock'},
        ],
        include_media=False,
    ),
    _latest_feature_card(
        'admin_release_260_enhanced_extraction',
        'Enabling Azure AI Content Understanding Extraction',
        'bi-file-earmark-richtext',
        'Admins can enable Enhanced extraction with Azure AI Content Understanding so users receive richer document and figure understanding.',
        'Enhanced extraction now uses Azure AI Content Understanding prebuilt-documentSearch instead of Document Intelligence Layout, adding AI-generated descriptions for figures, charts, and diagrams. Auto mode upgrades when figures are present, existing Enhanced or Auto deployments are migrated on upgrade, and users see extraction engine badges with fallback reasons in workspaces.',
        'This matters because admins can improve retrieval quality for visual documents while preserving controlled fallback visibility.',
        [
            'Open Admin Settings > Search and Extract and enable the Enhanced extraction toggle for Azure AI Content Understanding.',
            'Review existing Enhanced or Auto settings after upgrade to confirm the migration preserved the intended mode.',
            'Tell workspace owners that users will see extraction engine badges and fallback reasons on processed documents.',
            'Re-extract important documents with figures, charts, or diagrams so end users benefit from generated descriptions.',
        ],
        actions=[
            {'label': 'Open Search and Extract', 'description': 'Enable and review Enhanced extraction configuration.', 'href': '#search-extract', 'admin_tab': '#search-extract', 'icon': 'bi-file-earmark-richtext'},
        ],
        image_label='Enhanced Extract',
    ),
    _latest_feature_card(
        'admin_release_260_mcp_platform',
        'MCP Server Governance & Outbound Action Controls',
        'bi-plug',
        'Admins can govern inbound MCP server exposure and outbound MCP action destinations before users connect external tools.',
        'SimpleChat can operate as a governed inbound MCP server exposing conversations, documents, prompts, tags, and workflow tools to MCP clients. Outbound MCP actions add presets, server-side preconfiguration catalogs, destination governance, Test Connection support, observability controls, Application Insights KQL starters, and standards-compliant tool argument normalization for end users invoking MCP actions.',
        'This matters because admins can unlock MCP interoperability while controlling destinations, observability, and supported tool surfaces.',
        [
            'Open Admin Settings > Agents and review outbound MCP action configuration and available presets.',
            'Open Admin Settings > Governance and apply destination or capability policies before making MCP actions broadly available.',
            'Use Test Connection on configured MCP actions so users see reliable action availability.',
            'Tell users which MCP clients or outbound destinations are approved before enabling the capability tenant-wide.',
        ],
        actions=[
            {'label': 'Open Agents', 'description': 'Configure outbound MCP action presets and server-side catalogs.', 'href': '#agents', 'admin_tab': '#agents', 'icon': 'bi-plug'},
            {'label': 'Open Governance', 'description': 'Control MCP destination and capability access.', 'href': '#governance', 'admin_tab': '#governance', 'icon': 'bi-shield-check'},
            {'label': 'Open Logging', 'description': 'Review observability and KQL starter guidance for MCP operations.', 'href': '#logging', 'admin_tab': '#logging', 'icon': 'bi-activity'},
        ],
        image_label='MCP Controls',
    ),
    _latest_feature_card(
        'admin_release_260_azure_blob_file_sync',
        'Azure Blob Storage File Sync Configuration',
        'bi-cloud-upload',
        'Admins can configure Azure Blob Storage containers as File Sync sources for personal, group, and public workspaces.',
        'Blob File Sync supports managed identity, Key Vault-backed service principal, connection strings, and SAS token authentication. Admin configuration includes virtual-folder browsing, ETag change detection, prefix and filter controls, and full SAS URL validation with permission and expiry guidance; once enabled, workspace users can sync approved Blob content into their workspace document sets.',
        'This matters because admins can connect governed storage sources without forcing users to manually upload every file.',
        [
            'Open Admin Settings > File Sync and add an Azure Blob Storage source for the intended workspace type.',
            'Choose managed identity, Key Vault-backed service principal, connection string, or SAS token authentication based on tenant policy.',
            'Use prefix and filter controls to limit which container content users can sync.',
            'Validate SAS permissions and expiry guidance before allowing workspace owners to run sync jobs.',
        ],
        actions=[
            {'label': 'Open File Sync', 'description': 'Configure Azure Blob Storage sync sources and authentication.', 'href': '#file-sync', 'admin_tab': '#file-sync', 'icon': 'bi-cloud-upload'},
            {'label': 'Open Workspaces', 'description': 'Review workspace availability for synced Blob content.', 'href': '#workspaces', 'admin_tab': '#workspaces', 'icon': 'bi-collection'},
        ],
        image_label='Blob Sync',
    ),
    _latest_feature_card(
        'admin_release_260_terms_of_use',
        'Terms of Use / Rules of Behavior Gate',
        'bi-file-earmark-text',
        'Admins can require users to accept tenant terms or rules of behavior before accessing SimpleChat.',
        'The gate supports every-session, once-per-day, and once-per-version recurrence modes, with accept and decline events activity-logged and enforced server-side. Post-acceptance redirects are restricted to local-only paths, and end users will see the configured notice before they can continue into the app.',
        'This matters because tenant access expectations can be acknowledged consistently and recorded before users interact with AI features.',
        [
            'Open Admin Settings > General and configure the Terms of Use or Rules of Behavior content.',
            'Select the recurrence mode that matches tenant policy: every session, once per day, or once per version.',
            'Review the accept and decline activity logging expectations with compliance stakeholders.',
            'Preview the user gate so support teams know what end users will see before entering SimpleChat.',
        ],
        actions=[
            {'label': 'Open General Settings', 'description': 'Configure terms content, recurrence, and user gate behavior.', 'href': '#general', 'admin_tab': '#general', 'icon': 'bi-file-earmark-text'},
        ],
        image_label='Terms Gate',
    ),
    _latest_feature_card(
        'admin_release_260_chat_ai_notice',
        'Configuring the Chat AI Usage Notice',
        'bi-info-circle',
        'Admins can publish custom Markdown AI guidance directly below the chat composer.',
        'The chat notice supports non-dismissible, per-session, daily, and once-per-message-version dismissal modes. When admins change the configured notice text, the message automatically reappears so end users see updated guidance in Chat.',
        'This matters because AI usage guidance can be kept visible at the point of use without custom template changes.',
        [
            'Open Admin Settings > General and write the Markdown guidance users should see below the chat composer.',
            'Choose whether the notice is non-dismissible, per-session, daily, or once per message version.',
            'Update the notice text when policy changes so the notice reappears for users who previously dismissed it.',
            'Preview Chat after saving so admins can confirm the exact user-facing wording and placement.',
        ],
        actions=[
            {'label': 'Open General Settings', 'description': 'Configure the Chat AI usage notice and dismissal mode.', 'href': '#general', 'admin_tab': '#general', 'icon': 'bi-info-circle'},
        ],
        image_label='AI Notice',
    ),
    _latest_feature_card(
        'admin_release_260_public_workspace_display_name',
        'Custom Public Workspace Display Name',
        'bi-building',
        'Admins can rename the Public Workspace label to a tenant-specific display name without changing internal identifiers.',
        'The optional display name can replace Public Workspace with tenant language such as Domain Knowledge across navigation, Profile, chat scope selection, and directory pages. End users see the custom label throughout the interface while internal workspace identifiers remain unchanged.',
        'This matters because admins can align shared knowledge areas with organizational terminology without data migration.',
        [
            'Open Admin Settings > Workspaces and set the tenant-specific Public Workspace display name.',
            'Choose a short label that users will recognize in navigation, Profile, chat scope selection, and directories.',
            'Confirm help documentation and support scripts use the same display name users will see.',
            'Leave the field empty if the tenant should continue using the default Public Workspace wording.',
        ],
        actions=[
            {'label': 'Open Workspaces', 'description': 'Set the custom Public Workspace display name.', 'href': '#workspaces', 'admin_tab': '#workspaces', 'icon': 'bi-building'},
        ],
        image_label='Workspace Name',
    ),
]


_ADMIN_LATEST_FEATURE_RELEASE_GROUPS = [
    {
        'id': 'current_release',
        'label': 'Admin-Managed Latest Features',
        'description': 'The newest capabilities admins can manage from Admin Settings. These cards focus on tenant controls, governance, and rollout guidance for the v0.260.001 feature set.',
        'release_version': '0.260.001',
        'default_expanded': True,
        'collapse_id': 'adminLatestFeaturesCurrentRelease',
        'features': _ADMIN_RELEASE_260_FEATURE_CATALOG,
    },
    {
        'id': 'previous_release',
        'label': 'Previous Release Features',
        'description': 'Admin-facing release items from the prior v0.250.001 feature set remain available for reference.',
        'release_version': '0.250.001',
        'default_expanded': False,
        'collapse_id': 'adminLatestFeaturesPreviousRelease',
        'features': _ADMIN_RELEASE_250_FEATURE_CATALOG,
    },
    {
        'id': 'archive_release',
        'label': 'Archive Release Features',
        'description': 'Older admin-facing v0.241.001 through v0.241.007 items remain available for longer-term reference.',
        'release_version': '0.241.001 - 0.241.007',
        'default_expanded': False,
        'collapse_id': 'adminLatestFeaturesArchiveRelease',
        'features': _ADMIN_RELEASE_241_FEATURE_CATALOG,
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


def _normalize_action_endpoint(action):
    endpoint = action.get('endpoint')
    if endpoint in _LEGACY_ACTION_ENDPOINTS:
        action['endpoint'] = _LEGACY_ACTION_ENDPOINTS[endpoint]


def _normalize_feature_actions(feature):
    for action in feature.get('actions', []):
        _normalize_action_endpoint(action)


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
    features = _flatten_support_feature_groups(_SUPPORT_LATEST_FEATURE_RELEASE_GROUPS)
    for feature in features:
        _normalize_feature_actions(feature)
    return features


def get_support_latest_feature_release_groups():
    """Return grouped latest-feature metadata organized by release."""
    feature_groups = deepcopy(_SUPPORT_LATEST_FEATURE_RELEASE_GROUPS)
    for feature_group in feature_groups:
        for feature in feature_group.get('features', []):
            _normalize_feature_actions(feature)
    return feature_groups


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

    for item in _SUPPORT_RELEASE_250_FEATURE_CATALOG:
        if normalized_visibility.get(item['id'], True):
            visible_item = deepcopy(item)
            visible_item['actions'] = [
                action for action in visible_item.get('actions', [])
                if _action_enabled(action, settings)
            ]
            _normalize_feature_actions(visible_item)
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
            _normalize_feature_actions(visible_feature)
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
            _normalize_feature_actions(feature)
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
            _normalize_feature_actions(feature)
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