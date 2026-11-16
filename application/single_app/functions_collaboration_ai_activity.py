# functions_collaboration_ai_activity.py
"""Plain-language steps for the activity line of a shared conversation.

Thoughts are written for whoever debugs a request: plugin and function names, model deployment
names, argument values and timings. The other participants only need to know what the assistant
is doing, so each stream event is described in plain words before it is broadcast. An event that
is not recognised describes as an empty string, which leaves the line on its previous step.
"""

import re


THINKING_STEP = 'Thinking'
WRITING_STEP = 'Writing the answer'
REVIEWING_STEP = 'Reviewing what it found'
FINISHING_STEP = 'Finishing up'

STEP_TYPE_PHRASES = {
    'history_context': 'Reading the conversation',
    'search': 'Searching documents',
    'web_search': 'Searching the web',
    'deep_research': 'Researching the web',
    'url_access': 'Reading a web page',
    'tabular_analysis': 'Analyzing the data',
    'fact_memory': 'Checking saved facts',
    'orchestration_triage': 'Planning the work',
    'orchestration_planning': 'Planning the work',
    'orchestration_step': 'Working through the plan',
    'orchestration_synthesis': 'Putting the answer together',
}

PLUGIN_PHRASES = {
    'DocumentSearchPlugin': 'Searching documents',
    'SharedMapPlugin': 'Updating the map',
    'MathPlugin': 'Calculating',
    'WaitPlugin': 'Waiting',
}

VERB_PHRASES = {
    'get': 'Looking up', 'fetch': 'Looking up', 'retrieve': 'Looking up', 'lookup': 'Looking up',
    'read': 'Reading', 'find': 'Finding', 'search': 'Searching', 'query': 'Searching',
    'list': 'Reviewing', 'show': 'Showing', 'view': 'Viewing', 'check': 'Checking', 'verify': 'Checking',
    'validate': 'Checking', 'create': 'Creating', 'new': 'Creating', 'add': 'Adding', 'open': 'Opening',
    'start': 'Starting', 'update': 'Updating', 'set': 'Updating', 'edit': 'Updating', 'patch': 'Updating',
    'submit': 'Submitting', 'send': 'Sending', 'post': 'Posting', 'file': 'Filing', 'upload': 'Saving',
    'save': 'Saving', 'draft': 'Drafting', 'generate': 'Generating', 'write': 'Writing',
    'delete': 'Removing', 'remove': 'Removing', 'close': 'Closing', 'cancel': 'Cancelling',
    'approve': 'Approving', 'sign': 'Signing', 'analyze': 'Analyzing', 'summarize': 'Summarizing',
    'calculate': 'Calculating', 'run': 'Running', 'schedule': 'Scheduling', 'assign': 'Assigning',
    'invite': 'Inviting', 'notify': 'Notifying', 'publish': 'Publishing', 'export': 'Exporting',
    'download': 'Downloading', 'claim': 'Claiming', 'record': 'Recording', 'link': 'Linking',
}

PROPER_WORDS = {
    'word': 'Word', 'powerpoint': 'PowerPoint', 'excel': 'Excel', 'markdown': 'Markdown',
    'pdf': 'PDF', 'teams': 'Teams', 'outlook': 'Outlook',
}

FUNCTION_WORD_PATTERN = re.compile(r'[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+')


def _text(value):
    return str(value or '').strip()


def _display_word(word):
    if len(word) > 1 and word.isupper():
        return word
    return PROPER_WORDS.get(word.lower(), word.lower())


def describe_function_name(function_name):
    """'getOrderStatus' -> 'Looking up order status', 'search_documents' -> 'Searching documents'."""
    words = FUNCTION_WORD_PATTERN.findall(_text(function_name))
    if not words:
        return ''
    verb = VERB_PHRASES.get(words[0].lower())
    rest = [_display_word(word) for word in (words[1:] if verb else words)]
    if not verb:
        return f"Using {' '.join(rest)}"
    return ' '.join([verb, *rest])


def _describe_tool_invocation(activity):
    status = _text(activity.get('status') or activity.get('state')).lower()
    if status == 'failed':
        return ''
    plugin_name = _text(activity.get('plugin_name'))
    if plugin_name == 'AgentPlugin':
        delegation = activity.get('delegation') if isinstance(activity.get('delegation'), dict) else {}
        target = _text(delegation.get('target_label'))
        if status == 'completed':
            return f"Reviewing {target}'s reply" if target else REVIEWING_STEP
        return f'Asking {target}' if target else 'Asking another agent'
    if status == 'completed':
        return REVIEWING_STEP
    return PLUGIN_PHRASES.get(plugin_name) or describe_function_name(activity.get('function_name'))


def _describe_generation(content):
    lowered = content.lower()
    if lowered.startswith('sending to'):
        return THINKING_STEP
    if 'responded' in lowered or lowered.startswith('image generated'):
        return FINISHING_STEP
    if 'image' in lowered:
        return 'Creating the image'
    return THINKING_STEP


def describe_ai_activity_step(payload):
    """Describe one collaboration stream event for the activity line, or return '' to skip it."""
    if not isinstance(payload, dict) or payload.get('done') or payload.get('error'):
        return ''

    if payload.get('type') is None:
        content = payload.get('content')
        return WRITING_STEP if isinstance(content, str) and content.strip() else ''
    if payload.get('type') != 'thought':
        return ''

    activity = payload.get('activity')
    if isinstance(activity, dict) and _text(activity.get('kind')) == 'tool_invocation':
        return _describe_tool_invocation(activity)

    step_type = _text(payload.get('step_type')).lower()
    content = _text(payload.get('content'))
    if step_type == 'generation':
        return _describe_generation(content)
    if step_type == 'agent_tool_call' and content.lower().startswith('sending to agent'):
        return 'Getting started'
    return STEP_TYPE_PHRASES.get(step_type, '')
