# functions_orchestration_context.py

"""
What a request could act on: resources, seeds, signals, and the conversation's own history.

Three ideas live here, and the first two are the ones that decide whether a plan is any
good.

**Candidates, not a catalogue.** The planner has to be able to name documents, which
tempts an implementation into listing the user's workspace. That does not survive contact
with a real deployment: a user with several hundred documents would spend the planner's
entire context on file names, most of them irrelevant, and the planner would still be
guessing. So candidates are resolved by *relevance* instead -- a cheap search probe using
the user's own message, aggregated to distinct documents. The list is bounded by
construction and is made of the documents that stand a chance of mattering. When the user
has already picked documents, no probe runs at all; their choice is the candidate set.

**The run ledger.** Every turn re-plans, so a conversation accumulates runs. Without any
memory of them, turn five re-searches exactly what turn two already found and re-asks a
question the user has already answered. The ledger is a compact, byte-bounded summary of
what earlier runs did, and it is a planner *input* rather than a display artefact. It is
what lets a plan say "use what we already gathered" instead of gathering again, and it is
why an elicitation never asks the same thing twice in one conversation.

**Seeds are constraints, not hints.** Anything the user explicitly chose in the composer --
a document, an agent, a model, a prompt -- narrows the plan rather than suggesting to it.
A user who picked a document and then watched the planner search their whole workspace
would rightly conclude the control did nothing.

Version: 0.261.085
"""

import json
import logging

from functions_appinsights import log_event

# Relevance probe bounds. Deliberately small: this runs before planning on every
# non-trivial message, so it is on the latency path of the whole feature.
CANDIDATE_PROBE_TOP_N = 30
CANDIDATE_DOCUMENT_LIMIT = 15
CANDIDATE_TITLE_LENGTH = 160

# Ledger bounds, defaults for when the administrator has not set them.
LEDGER_DEFAULT_MAX_RUNS = 10
LEDGER_DEFAULT_MAX_BYTES = 16384
LEDGER_SUMMARY_LENGTH = 240
LEDGER_MAX_DOCUMENTS_PER_RUN = 8
LEDGER_MAX_ANSWERED_QUESTIONS = 12

# Conversation history handed to the planner. The planner decides *what to do*, not what
# to say, so it needs the shape of the conversation rather than its full text.
HISTORY_MAX_TURNS = 6
HISTORY_TURN_LENGTH = 300


def _text(value, limit=None):
    if value is None:
        return ''
    text = str(value).strip()
    if limit is not None and len(text) > limit:
        text = text[:limit].rstrip()
    return text


def _string_list(value, limit=None):
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    out = []
    seen = set()
    for item in value:
        text = _text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if limit is not None and len(out) >= limit:
            break
    return out


def _byte_length(payload):
    try:
        return len(json.dumps(payload, default=str).encode('utf-8'))
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------------------
# Seeds
# --------------------------------------------------------------------------------------

def resolve_seeds(request_data):
    """Read the composer's explicit selections out of a plan request.

    Field names match the existing chat request contract rather than inventing new ones,
    so a client that already knows how to name a document selection does not need a second
    vocabulary for orchestration.
    """
    request_data = request_data if isinstance(request_data, dict) else {}

    document_ids = _string_list(
        request_data.get('selected_document_ids')
        or request_data.get('selected_document_id')
    )

    agent = request_data.get('agent_info')
    agent = agent if isinstance(agent, dict) else None

    model = {
        key: _text(request_data.get(key))
        for key in ('model_deployment', 'model_id', 'model_endpoint_id', 'model_provider')
        if _text(request_data.get(key))
    }

    prompt = request_data.get('prompt_info')
    prompt = prompt if isinstance(prompt, dict) else None

    return {
        'document_ids': document_ids,
        'doc_scope': _text(request_data.get('doc_scope')) or 'all',
        'agent': agent,
        'model': model or None,
        'prompt': prompt,
        # A user who switched web search on has said something about intent even in
        # orchestration mode, so it is carried through as a constraint rather than dropped.
        'web_search': bool(request_data.get('web_search_enabled')),
        'active_group_ids': _string_list(
            request_data.get('active_group_ids') or request_data.get('active_group_id')
        ),
        'active_public_workspace_ids': _string_list(
            request_data.get('active_public_workspace_ids')
            or request_data.get('active_public_workspace_id')
        ),
    }


def seeds_are_explicit(seeds):
    """Whether the user named documents, which turns the candidate probe off."""
    return bool((seeds or {}).get('document_ids'))


# --------------------------------------------------------------------------------------
# Candidate documents
# --------------------------------------------------------------------------------------

def _aggregate_candidates(results):
    """Collapse chunk hits into distinct documents, best score first.

    Search returns chunks, and several chunks of one document say nothing more about
    whether that document is worth planning around than the best of them does.
    """
    by_document = {}
    for result in results or ():
        if not isinstance(result, dict):
            continue
        document_id = _text(result.get('document_id'))
        if not document_id:
            continue

        try:
            score = float(result.get('score') or 0.0)
        except (TypeError, ValueError):
            score = 0.0

        existing = by_document.get(document_id)
        if existing and existing['score'] >= score:
            continue

        scope = 'personal'
        if result.get('public_workspace_id'):
            scope = 'public'
        elif result.get('group_id'):
            scope = 'group'

        file_name = _text(result.get('file_name'))
        by_document[document_id] = {
            'document_id': document_id,
            'file_name': file_name,
            'title': _text(result.get('title'), CANDIDATE_TITLE_LENGTH) or file_name,
            'scope': scope,
            'classification': _text(result.get('document_classification')),
            'tags': _string_list(result.get('document_tags'), limit=6),
            'score': score,
        }

    ranked = sorted(by_document.values(), key=lambda item: item['score'], reverse=True)
    return ranked[:CANDIDATE_DOCUMENT_LIMIT]


def resolve_candidate_documents(
    user_message,
    user_id,
    seeds=None,
    conversation_id=None,
    settings=None,
):
    """Documents the plan could reasonably name.

    Returns ``(candidates, probe_ran)``. A failed probe is not an error: it means the
    planner works without document candidates and will lean on searching rather than on
    naming a document, which is a worse plan but still a valid one. Failing the whole
    request because a relevance probe timed out would be far worse.
    """
    seeds = seeds or {}

    if seeds_are_explicit(seeds):
        # The user already answered this question. Probing would only offer alternatives
        # to a choice that has been made.
        return [
            {
                'document_id': document_id,
                'file_name': '',
                'title': '',
                'scope': seeds.get('doc_scope') or 'all',
                'classification': '',
                'tags': [],
                'score': None,
                'selected_by_user': True,
            }
            for document_id in seeds['document_ids']
        ], False

    query = _text(user_message)
    if not query:
        return [], False

    try:
        from functions_search import hybrid_search

        results = hybrid_search(
            query,
            user_id,
            top_n=CANDIDATE_PROBE_TOP_N,
            doc_scope=seeds.get('doc_scope') or 'all',
            active_group_ids=seeds.get('active_group_ids') or None,
            active_public_workspace_id=(
                (seeds.get('active_public_workspace_ids') or [None])[0]
            ),
        )
    except Exception as exc:
        log_event(
            f"[ORCHESTRATION_CONTEXT] Candidate document probe failed; planning without "
            f"document candidates: {exc}",
            level=logging.WARNING,
        )
        return [], False

    return _aggregate_candidates(results), True


# --------------------------------------------------------------------------------------
# Run ledger
# --------------------------------------------------------------------------------------

def _compact_run_entry(entry):
    """Reduce a ledger entry to one line, for when the ledger is over budget."""
    return {
        'run_id': entry.get('run_id'),
        'turn_index': entry.get('turn_index'),
        'intent_summary': _text(entry.get('intent_summary'), 120),
        'status': entry.get('status'),
    }


def build_run_ledger(runs, settings=None, answered_questions=None):
    """Summarise a conversation's earlier orchestration runs for the planner.

    ``runs`` are records from ``functions_orchestration_runs.list_conversation_runs``,
    newest last. Trimming happens oldest-first and in two passes -- drop the oldest runs
    beyond the configured count, then compact remaining old entries to a single line until
    the payload fits. Recent runs are what a follow-up question is usually about, so they
    keep their detail longest.

    ``truncated`` is reported honestly. A planner that believes it has seen the whole
    conversation when it has not will confidently assert that something was never looked
    at, which is worse than knowing its view is partial.
    """
    settings = settings if isinstance(settings, dict) else {}

    try:
        max_runs = int(settings.get('chat_orchestration_ledger_max_runs', LEDGER_DEFAULT_MAX_RUNS))
    except (TypeError, ValueError):
        max_runs = LEDGER_DEFAULT_MAX_RUNS
    max_runs = max(0, min(max_runs, 50))

    try:
        max_bytes = int(settings.get('chat_orchestration_ledger_max_bytes', LEDGER_DEFAULT_MAX_BYTES))
    except (TypeError, ValueError):
        max_bytes = LEDGER_DEFAULT_MAX_BYTES
    max_bytes = max(1024, min(max_bytes, 131072))

    # Zero runs is a real configuration: it makes every turn plan from scratch.
    if max_runs == 0:
        return {'runs': [], 'answered_questions': [], 'truncated': bool(runs)}

    ordered = [run for run in (runs or ()) if isinstance(run, dict)]
    truncated = len(ordered) > max_runs
    ordered = ordered[-max_runs:]

    entries = []
    for run in ordered:
        summary = run.get('plan_summary') if isinstance(run.get('plan_summary'), dict) else {}
        entries.append({
            'run_id': run.get('id') or run.get('run_id'),
            'turn_index': run.get('turn_index'),
            'intent_summary': _text(
                summary.get('intent_summary') or run.get('intent_summary'),
                LEDGER_SUMMARY_LENGTH,
            ),
            'status': _text(run.get('status')),
            'capabilities_used': _string_list(
                summary.get('capabilities_used') or run.get('capabilities_used'), limit=8
            ),
            'documents_touched': [
                {
                    'document_id': _text((item or {}).get('document_id')),
                    'display_name': _text((item or {}).get('display_name') or (item or {}).get('file_name')),
                }
                for item in (run.get('documents_touched') or ())[:LEDGER_MAX_DOCUMENTS_PER_RUN]
                if isinstance(item, dict) and _text(item.get('document_id'))
            ],
            'artifacts': [
                {
                    'kind': _text((item or {}).get('kind')),
                    'name': _text((item or {}).get('name') or (item or {}).get('file_name')),
                }
                for item in (run.get('artifacts') or ())[:LEDGER_MAX_DOCUMENTS_PER_RUN]
                if isinstance(item, dict)
            ],
            'unresolved': _string_list(run.get('unresolved'), limit=4),
        })

    answered = []
    for item in (answered_questions or ())[-LEDGER_MAX_ANSWERED_QUESTIONS:]:
        if not isinstance(item, dict):
            continue
        answered.append({
            'elicitation_id': _text(item.get('elicitation_id')),
            'question': _text(item.get('question'), LEDGER_SUMMARY_LENGTH),
            'answer': item.get('answer'),
        })

    ledger = {'runs': entries, 'answered_questions': answered, 'truncated': truncated}

    # Compact oldest-first until it fits. The newest entry is never compacted: a ledger
    # that cannot afford to describe the turn immediately before this one has no value.
    index = 0
    while _byte_length(ledger) > max_bytes and index < len(entries) - 1:
        entries[index] = _compact_run_entry(entries[index])
        ledger['truncated'] = True
        index += 1

    # Still over budget: drop the oldest outright rather than return something unbounded.
    while _byte_length(ledger) > max_bytes and len(entries) > 1:
        entries.pop(0)
        ledger['truncated'] = True

    return ledger


def collect_answered_questions(runs):
    """Every elicitation already answered in this conversation.

    Carried into the ledger so the planner can see what the user has been asked. Asking
    the same question twice is the most obvious way for this feature to feel broken, and
    it is entirely avoidable.
    """
    answered = []
    for run in runs or ():
        if not isinstance(run, dict):
            continue
        for item in run.get('answered_questions') or ():
            if isinstance(item, dict) and _text(item.get('question')):
                answered.append(item)
    return answered


# --------------------------------------------------------------------------------------
# Conversation signals
# --------------------------------------------------------------------------------------

def build_conversation_signals(messages, user_message):
    """The shape of the conversation so far, plus anything in the message itself."""
    turns = []
    for message in (messages or ())[-(HISTORY_MAX_TURNS * 2):]:
        if not isinstance(message, dict):
            continue
        role = _text(message.get('role'))
        if role not in ('user', 'assistant'):
            continue
        content = _text(message.get('content'), HISTORY_TURN_LENGTH)
        if content:
            turns.append({'role': role, 'content': content})

    return {
        'recent_turns': turns[-HISTORY_MAX_TURNS:],
        'urls': _extract_urls(user_message),
    }


def _extract_urls(text):
    """URLs present in the message, matching the client's own detection."""
    import re

    return _string_list(re.findall(r'https?://[^\s<>\'"]+', _text(text)), limit=8)


# --------------------------------------------------------------------------------------
# The planner's view
# --------------------------------------------------------------------------------------

def build_planner_context(
    user_message,
    candidates=None,
    seeds=None,
    ledger=None,
    signals=None,
    capabilities=None,
):
    """Assemble everything the planner is shown, in one place.

    Kept as a single builder so that what the planner sees is auditable and testable
    rather than being spread across the prompt construction. Nothing enters the planner's
    context that is not visible here.
    """
    seeds = seeds or {}
    return {
        'message': _text(user_message),
        'capabilities': capabilities or [],
        'candidate_documents': [
            {key: value for key, value in candidate.items() if key != 'score'}
            for candidate in (candidates or ())
        ],
        'user_selected': {
            'documents': seeds.get('document_ids') or [],
            'agent': (seeds.get('agent') or {}).get('name') if seeds.get('agent') else None,
            'prompt': (seeds.get('prompt') or {}).get('name') if seeds.get('prompt') else None,
            'web_search': bool(seeds.get('web_search')),
        },
        'earlier_runs': ledger or {'runs': [], 'answered_questions': [], 'truncated': False},
        'conversation': signals or {'recent_turns': [], 'urls': []},
    }
