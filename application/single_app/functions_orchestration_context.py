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

Version: 0.261.102
"""

import hashlib
import json
import logging
import math
from copy import deepcopy
from datetime import datetime, timezone

from functions_appinsights import log_event
from functions_action_catalog import build_action_planner_projection
from functions_message_block_revisions import resolve_block_sources_in_content
from functions_message_masking import remove_masked_content
from functions_orchestration_registry import (
    CAPABILITY_ACTION_INVOKE,
    WORKSPACE_SCOPE_SETTINGS,
    build_agent_planner_projection,
    resolve_available_capability_ids,
)
from functions_orchestration_schema import validate_elicitation_response
from functions_prompt_metadata import build_prompt_selection_metadata

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

HISTORY_MAX_TURNS = 6
HISTORY_MAX_MESSAGES = 50
HISTORY_MAX_BYTES = 16384
HISTORY_SCAN_LIMIT = 200
HISTORY_SCHEMA_VERSION = 1
CLARIFICATION_MAX_BYTES = 32768

# How much of a selected prompt the planner is shown.
#
# The name alone was not enough to plan with: "Quarterly review" says nothing about whether the
# work involves reading documents, searching the web or comparing two things, which is precisely
# what the plan has to decide. The wording says all of it.
#
# Capped rather than sent whole because a saved prompt has no length limit and the planner's
# budget does. A prompt long enough to be truncated here has said what kind of work it is well
# before this point.
SELECTED_PROMPT_LENGTH = 2000
ELICITATION_TEXT_LIMIT = 16000
ELICITATION_CONTEXT_BYTE_LIMIT = 131072
ELICITATION_REFERENCE_LIMIT = 100
ELICITATION_IDENTIFIER_LIMIT = 512


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
    filter_mode = _text(request_data.get('document_filter_mode')).lower()
    if filter_mode in ('union', 'or', 'additive'):
        filter_mode = 'union'
    elif filter_mode != 'intersection':
        filter_mode = ''

    # Display names for the picked documents, sent by the composer because it already knows
    # them. Used for labels only -- what the user may actually read is decided from the ids
    # against Cosmos, never from anything the browser asserts about them.
    document_labels = {}
    for entry in request_data.get('context_documents') or ():
        if not isinstance(entry, dict):
            continue
        document_id = _text(entry.get('id') or entry.get('document_id'))
        label = _text(entry.get('label') or entry.get('file_name'), 200)
        if document_id and label:
            document_labels[document_id] = label

    return {
        'document_ids': document_ids,
        'document_labels': document_labels,
        'doc_scope': _text(request_data.get('doc_scope')) or 'all',
        # Tags narrow a search rather than naming documents, so they are a separate seed
        # from document_ids and are treated differently: a picked document replaces the
        # candidate probe, a picked tag scopes it.
        'tags': _string_list(request_data.get('tags')),
        'document_filter_mode': filter_mode,
        'agent': agent,
        'model': model or None,
        'reasoning_effort': _text(request_data.get('reasoning_effort')),
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
    """Whether the user named documents, which turns the candidate probe off.

    Naming a tag deliberately does not count. A document is an answer to "which documents";
    a tag is an answer to "which shelf", and the probe is still the thing that decides which
    documents on that shelf are worth naming. Treating a tag as explicit would hand the
    planner every document carrying it, which is the opposite of narrowing.
    """
    return bool((seeds or {}).get('document_ids'))


# --------------------------------------------------------------------------------------
# Accepted clarification context
# --------------------------------------------------------------------------------------

class ElicitationContextError(ValueError):
    """User-safe, field-addressable validation failure for supplemental context."""

    def __init__(self, message, field=None):
        super().__init__(message)
        self.message = message
        self.field = field


def _bounded_answer_text(value, limit=ELICITATION_TEXT_LIMIT):
    if not isinstance(value, str) or len(value) > limit:
        raise ElicitationContextError(f'Use text of at most {limit} characters.')
    return value.strip()


def normalize_elicitation_reference(reference):
    """Validate only shape here. Labels and scope claims are never authorization."""
    if not isinstance(reference, dict) or set(reference) - {'kind', 'id', 'label', 'scope'}:
        raise ElicitationContextError('Choose a file, tag, or workspace from the context picker.')
    kind = reference.get('kind')
    scope = reference.get('scope')
    if kind not in ('document', 'tag', 'scope', 'chat_attachment') or not isinstance(scope, dict):
        raise ElicitationContextError('The context reference is invalid.')
    if set(scope) - {'kind', 'id', 'name'} or scope.get('kind') not in ('personal', 'group', 'public', 'chat'):
        raise ElicitationContextError('The context scope is invalid.')
    reference_id = _bounded_answer_text(reference.get('id'), ELICITATION_IDENTIFIER_LIMIT)
    scope_kind = scope['kind']
    scope_id = scope.get('id')
    if scope_id is not None:
        scope_id = _bounded_answer_text(scope_id, ELICITATION_IDENTIFIER_LIMIT)
    if not reference_id and not (kind == 'scope' and scope_kind == 'personal'):
        raise ElicitationContextError('The context reference has no identity.')
    if scope_kind != 'personal' and not scope_id:
        raise ElicitationContextError('Select the workspace or conversation that owns this reference.')
    if (kind == 'chat_attachment') != (scope_kind == 'chat'):
        raise ElicitationContextError('Conversation attachments must use their owning conversation.')
    return {
        'kind': kind, 'id': reference_id,
        'scope': {'kind': scope_kind, 'id': scope_id},
    }


def _owned_elicitation_conversation(user_id, conversation_id):
    # The import is lazy because config initializes Azure clients at module import time.
    from config import cosmos_conversations_container

    try:
        conversation = cosmos_conversations_container.read_item(
            item=conversation_id, partition_key=conversation_id,
        )
    except Exception as exc:
        log_event(
            '[ORCHESTRATION_CONTEXT] Could not authorize clarification conversation.',
            extra={'exception_type': type(exc).__name__}, level=logging.WARNING,
        )
        raise ElicitationContextError('That conversation is no longer available.') from exc
    if conversation.get('user_id') != user_id:
        raise ElicitationContextError('That conversation is no longer available.')
    return conversation


def _authorize_elicitation_scope(scope, user_id, conversation, settings):
    kind, scope_id = scope['kind'], scope['id']
    if kind == 'chat':
        if scope_id != conversation['id']:
            raise ElicitationContextError('Select an attachment from this conversation.')
        return {'kind': 'chat', 'id': conversation['id'], 'name': 'This conversation'}

    if not settings.get(WORKSPACE_SCOPE_SETTINGS[kind], False):
        raise ElicitationContextError('That workspace capability is currently disabled.')
    if kind == 'personal' and scope_id not in (None, '', user_id):
        raise ElicitationContextError('That personal workspace is not available.')

    if conversation.get('scope_locked'):
        locked = conversation.get('locked_contexts') or conversation.get('context') or []
        if not any(
            item.get('scope') == kind
            and (item.get('id') == (user_id if kind == 'personal' else scope_id))
            for item in locked if isinstance(item, dict)
        ):
            raise ElicitationContextError('This conversation is locked to different workspaces.')

    if kind == 'personal':
        return {'kind': kind, 'id': None, 'name': 'My workspace'}
    if kind == 'group':
        # Membership must be rechecked at this boundary, not inferred from an active ID.
        from functions_group import assert_group_role, find_group_by_id

        assert_group_role(user_id, scope_id, allowed_roles=('Owner', 'Admin', 'DocumentManager', 'User'))
        workspace = find_group_by_id(scope_id)
    else:
        from functions_public_workspaces import (
            find_public_workspace_by_id,
            get_user_visible_public_workspace_ids_from_settings,
        )

        if scope_id not in get_user_visible_public_workspace_ids_from_settings(user_id):
            raise ElicitationContextError('That public workspace is not available.')
        workspace = find_public_workspace_by_id(scope_id)
    if not workspace:
        raise ElicitationContextError('That workspace is no longer available.')
    return {'kind': kind, 'id': scope_id, 'name': _text(workspace.get('name'), 200)}


def _elicitation_document_ready(document):
    status = _text(document.get('status')).lower()
    if any(value in status for value in ('error', 'failed', 'cancelled', 'canceled')):
        return False
    if 'complete' not in status and any(
        value in status for value in ('queued', 'pending', 'uploading', 'processing')
    ):
        return False
    percentage = document.get('percentage_complete')
    if percentage is not None:
        try:
            return math.isfinite(float(percentage)) and float(percentage) >= 100
        except (TypeError, ValueError):
            return False
    # Historical documents have no progress field; explicit in-flight states were checked.
    return True


def resolve_elicitation_references(references, user_id, conversation_id, settings=None):
    """Reauthorize exact source identities and readiness, without a silent-drop path."""
    settings = settings or {}
    if not isinstance(references, list) or len(references) > ELICITATION_REFERENCE_LIMIT:
        raise ElicitationContextError(f'Select at most {ELICITATION_REFERENCE_LIMIT} context references.')
    if not references:
        return []
    conversation = _owned_elicitation_conversation(user_id, conversation_id)
    normalized = []
    seen = set()
    scopes = {}
    for raw in references:
        reference = normalize_elicitation_reference(raw)
        key = (reference['kind'], reference['id'], reference['scope']['kind'], reference['scope']['id'])
        if key in seen:
            continue
        seen.add(key)
        scope_key = (reference['scope']['kind'], reference['scope']['id'])
        if scope_key not in scopes:
            try:
                scopes[scope_key] = _authorize_elicitation_scope(reference['scope'], user_id, conversation, settings)
            except ElicitationContextError:
                raise
            except Exception as exc:
                log_event(
                    '[ORCHESTRATION_CONTEXT] Clarification workspace authorization failed.',
                    extra={'exception_type': type(exc).__name__}, level=logging.WARNING,
                )
                raise ElicitationContextError('That workspace is not available. Select another reference.') from exc
        reference['scope'] = scopes[scope_key]
        normalized.append(reference)

    documents = [item for item in normalized if item['kind'] in ('document', 'chat_attachment')]
    if documents:
        # Reuse the same document-context and manifest boundaries as mixed-source reads.
        # Keeping metadata locally lets us check processing without exposing storage URLs.
        from functions_mixed_source_orchestration import resolve_authorized_source_manifest
        from functions_search_service import resolve_document_contexts

        batches = {}
        for reference in documents:
            scope = reference['scope']
            batches.setdefault((scope['kind'], scope['id']), []).append(reference['id'])
        contexts_by_reference = {}
        sources_by_reference = {}
        try:
            # A shared document can resolve in more than one authorized workspace.
            # Batch by the selected scope so the first accessible group cannot change
            # another reference's identity or make acceptance depend on selection order.
            for (scope_kind, scope_id), document_ids in batches.items():
                ids = _string_list(document_ids)
                lookup_scope = 'all' if scope_kind == 'chat' else scope_kind
                group_ids = [scope_id] if scope_kind == 'group' else []
                public_ids = [scope_id] if scope_kind == 'public' else []
                contexts = resolve_document_contexts(
                    ids, user_id, doc_scope=lookup_scope, active_group_ids=group_ids,
                    active_public_workspace_id=public_ids, conversation_id=conversation_id,
                    include_content=False,
                )
                if not isinstance(contexts, list) or len(contexts) != len(ids):
                    raise ElicitationContextError('The selected files could not be verified. Please retry.')
                by_id = dict(zip(ids, contexts))
                manifest = resolve_authorized_source_manifest(
                    ids, user_id, conversation_id=conversation_id, doc_scope=lookup_scope,
                    active_group_ids=group_ids, active_public_workspace_ids=public_ids,
                    context_resolver=lambda document_id, resolved=by_id, **kwargs: resolved.get(document_id),
                )
                for document_id, document_context in by_id.items():
                    contexts_by_reference[(scope_kind, scope_id, document_id)] = document_context
                for source in manifest:
                    sources_by_reference[(scope_kind, scope_id, source['document_id'])] = source
        except ElicitationContextError:
            raise
        except Exception as exc:
            log_event(
                '[ORCHESTRATION_CONTEXT] Clarification source resolution failed.',
                extra={'exception_type': type(exc).__name__}, level=logging.WARNING,
            )
            raise ElicitationContextError('The selected files could not be verified. Please retry.') from exc
        for reference in documents:
            scope = reference['scope']
            key = (scope['kind'], scope['id'], reference['id'])
            source = sources_by_reference.get(key) or {}
            if (
                source.get('authorization_status') != 'authorized'
                or source.get('scope') != scope['kind']
                or (scope['kind'] != 'personal' and source.get('scope_id') != scope['id'])
            ):
                raise ElicitationContextError('A selected file is unavailable or no longer authorized. Select another file.')
            document = (contexts_by_reference.get(key) or {}).get('document') or {}
            if scope['kind'] == 'chat':
                # The manifest proved ownership of this conversation and file message.
                # Workspace upload wrapper messages are not synchronous chat attachments;
                # accepting one would bypass the workspace document's processing gate.
                from config import cosmos_messages_container

                try:
                    rows = list(cosmos_messages_container.query_items(
                        query=(
                            'SELECT c.id, c.workspace_document_id, c.file_content_source, '
                            'c.status, c.percentage_complete FROM c WHERE c.id = @document_id'
                        ),
                        parameters=[{'name': '@document_id', 'value': reference['id']}],
                        partition_key=conversation_id,
                    ))
                except Exception as exc:
                    log_event(
                        '[ORCHESTRATION_CONTEXT] Clarification attachment readiness could not be checked.',
                        extra={'exception_type': type(exc).__name__}, level=logging.WARNING,
                    )
                    raise ElicitationContextError('That attachment could not be checked. Please retry.') from exc
                if not rows:
                    raise ElicitationContextError('That attachment is no longer available.')
                document = rows[0]
                if document.get('workspace_document_id') or document.get('file_content_source') == 'workspace':
                    raise ElicitationContextError('Select the workspace document for this upload and wait for its processing to finish.')
            if not _elicitation_document_ready(document):
                raise ElicitationContextError('A selected file is still processing or failed. Wait for it to finish, retry the upload, or remove it.')
            reference['label'] = _text(source.get('display_name') or source.get('file_name'), 200) or reference['id']

    for reference in normalized:
        scope = reference['scope']
        if reference['kind'] == 'scope':
            allowed_ids = ('', 'personal', user_id) if scope['kind'] == 'personal' else (scope['id'],)
            if reference['id'] not in allowed_ids:
                raise ElicitationContextError('The workspace identity does not match its scope.')
            reference['id'] = scope['id'] or 'personal'
            reference['label'] = scope['name']
        elif reference['kind'] == 'tag':
            from functions_documents import get_workspace_tags

            tags = get_workspace_tags(
                user_id,
                group_id=scope['id'] if scope['kind'] == 'group' else None,
                public_workspace_id=scope['id'] if scope['kind'] == 'public' else None,
            )
            tag = next((item for item in tags or [] if item.get('name') == reference['id']), None)
            if not tag:
                raise ElicitationContextError('That tag is no longer available in the selected workspace.')
            reference['label'] = tag['name']
    return normalized


def resolve_elicitation_candidates(candidates, user_id, conversation_id, seeds=None, settings=None):
    """Enrich only actual candidate IDs. Unavailable suggestions are never an allowlist."""
    seeds = seeds or {}
    ids = _string_list([item.get('document_id') for item in candidates or []], CANDIDATE_DOCUMENT_LIMIT)
    if not ids:
        return []
    # Lazy: the search service imports config and its live clients.
    from functions_search_service import resolve_document_contexts
    contexts = resolve_document_contexts(
        ids, user_id, doc_scope=seeds.get('doc_scope') or 'all',
        active_group_ids=seeds.get('active_group_ids') or None,
        active_public_workspace_id=seeds.get('active_public_workspace_ids') or None,
        conversation_id=conversation_id, include_content=False,
    )
    references = []
    for document_id, context in zip(ids, contexts or []):
        if not isinstance(context, dict):
            continue
        scope_kind = context.get('scope')
        if scope_kind not in ('personal', 'group', 'public', 'chat'):
            continue
        scope_id = {
            'personal': None,
            'group': context.get('group_id'),
            'public': context.get('public_workspace_id'),
            'chat': context.get('conversation_id'),
        }[scope_kind]
        try:
            references.extend(resolve_elicitation_references([{
                'kind': 'chat_attachment' if scope_kind == 'chat' else 'document',
                'id': document_id, 'scope': {'kind': scope_kind, 'id': scope_id},
            }], user_id, conversation_id, settings=settings))
        except ElicitationContextError:
            log_event(
                '[ORCHESTRATION_CONTEXT] Omitted an unavailable clarification suggestion.',
                level=logging.INFO, debug_only=True,
            )
    return references


def _normalize_answer_prompt(prompt):
    if not isinstance(prompt, dict) or set(prompt) - {
        'id', 'name', 'content', 'original_content', 'variables', 'edited', 'user_text',
        'template_content', 'composer_text', 'composer_embedded', 'scope_type', 'scope_name', 'index',
    }:
        raise ElicitationContextError('The attached prompt metadata is invalid.')
    clean = {}
    for key in (
        'id', 'name', 'content', 'original_content', 'user_text',
        'template_content', 'composer_text', 'scope_type', 'scope_name',
    ):
        if key in prompt:
            if prompt[key] is None and key in ('id', 'name', 'scope_type', 'scope_name'):
                clean[key] = None
            else:
                _bounded_answer_text(prompt[key])
                clean[key] = prompt[key]
    for key in ('edited', 'composer_embedded'):
        if key in prompt:
            if not isinstance(prompt[key], bool):
                raise ElicitationContextError('The attached prompt metadata is invalid.')
            clean[key] = prompt[key]
    if 'index' in prompt:
        if prompt['index'] is not None and type(prompt['index']) not in (str, int):
            raise ElicitationContextError('The attached prompt metadata is invalid.')
        clean['index'] = prompt['index']
    if 'variables' in prompt:
        variables = prompt['variables']
        if not isinstance(variables, dict) or len(variables) > 50:
            raise ElicitationContextError('The attached prompt has too many variables.')
        clean['variables'] = {}
        for key, value in variables.items():
            _bounded_answer_text(key, 128)
            _bounded_answer_text(value, 4000)
            clean['variables'][key] = value
    return clean


def normalize_elicitation_answer(question, response, answer_context, user_id, conversation_id, settings=None):
    """Validate primitive answers plus optional rich context against a stored question."""
    if isinstance(response, dict) and response.get('action') in ('decline', 'cancel'):
        return {'action': response['action'], 'content': {}}, {}
    if not isinstance(response, dict) or response.get('action') != 'accept':
        raise ElicitationContextError('Choose Finish, Decline, or Cancel for this question.')
    answer_context = {} if answer_context is None else answer_context
    if not isinstance(answer_context, dict) or _byte_length(answer_context) > ELICITATION_CONTEXT_BYTE_LIMIT:
        raise ElicitationContextError('The answer context is too large or invalid.')
    properties = question['requested_schema']['properties']
    if set(answer_context) - set(properties):
        raise ElicitationContextError('Answer context names an unknown question field.')
    content = response.get('content', {})
    if not isinstance(content, dict) or set(content) - set(properties):
        raise ElicitationContextError('Answer content names an unknown question field.')
    content = deepcopy(content)
    fields = (question.get('ui_hints') or {}).get('fields') or {}
    normalized_context = {}
    reference_count = 0
    for name, rules in properties.items():
        try:
            raw = answer_context.get(name, {})
            if not isinstance(raw, dict) or set(raw) - {'text', 'prompt_info', 'references'}:
                raise ElicitationContextError('Use text, a prompt, or context references for this answer.')
            context = {}
            if 'text' in raw:
                context['text'] = _bounded_answer_text(raw['text'])
            if 'prompt_info' in raw:
                context['prompt_info'] = _normalize_answer_prompt(raw['prompt_info'])
                if not context.get('text'):
                    context['text'] = context['prompt_info'].get('content', '')
                if any(key in context['prompt_info'] for key in (
                    'template_content', 'composer_text', 'composer_embedded',
                )) and build_prompt_selection_metadata(
                    context['prompt_info'], _elicitation_answer_text(context),
                ) is None:
                    raise ElicitationContextError('The attached prompt snapshot does not match this answer.')
            references = raw.get('references', [])
            if not isinstance(references, list):
                raise ElicitationContextError('Context references must be a list.')
            references = list(references)
            hint = fields.get(name) or {}
            if hint.get('input') == 'files':
                offered = {item['id']: item for item in hint.get('candidates') or []}
                supplied = {
                    item.get('id') for item in references
                    if isinstance(item, dict) and item.get('kind') in ('document', 'chat_attachment')
                }
                chosen = content.get(name)
                chosen = [] if chosen in (None, '') else chosen if isinstance(chosen, list) else [chosen]
                for document_id in chosen:
                    if not isinstance(document_id, str):
                        raise ElicitationContextError('Select a real file rather than entering a filename.')
                    if document_id not in supplied:
                        if document_id not in offered:
                            raise ElicitationContextError('Select that file from the context picker or upload it first.')
                        references.append(offered[document_id])
                        supplied.add(document_id)
            references = resolve_elicitation_references(references, user_id, conversation_id, settings)
            reference_count += len(references)
            if reference_count > ELICITATION_REFERENCE_LIMIT:
                raise ElicitationContextError(f'Select at most {ELICITATION_REFERENCE_LIMIT} context references.')
            if references:
                context['references'] = references
            if hint.get('input') == 'files':
                file_ids = _string_list([
                    item['id'] for item in references if item['kind'] in ('document', 'chat_attachment')
                ])
                if not file_ids and name in question['requested_schema'].get('required', []):
                    raise ElicitationContextError('Select or upload a file to answer this question. Tags and workspaces alone are not files.')
                if rules['type'] == 'array':
                    content[name] = file_ids
                elif len(file_ids) > 1:
                    raise ElicitationContextError('This question accepts one file. Remove the extra files.')
                elif file_ids:
                    content[name] = file_ids[0]
                else:
                    content.pop(name, None)
            if context:
                normalized_context[name] = context
        except ElicitationContextError as exc:
            exc.field = name
            raise
    validated, errors = validate_elicitation_response(question, {'action': 'accept', 'content': content})
    if errors:
        raise ElicitationContextError(' '.join(errors))
    return validated, normalized_context


def merge_elicitation_context(seeds, answer_context):
    """Add accepted resources without replacing the original prompt/agent/model settings."""
    merged = deepcopy(seeds or {})
    references = [
        reference for context in (answer_context or {}).values()
        for reference in context.get('references') or []
    ]
    if not references:
        return merged
    had_selection = bool(
        merged.get('document_ids') or merged.get('tags')
        or merged.get('active_group_ids') or merged.get('active_public_workspace_ids')
    )
    had_document_tag_filter = bool(merged.get('document_ids') and merged.get('tags'))
    existing = merged.setdefault('elicitation_references', [])
    keys = {(item['kind'], item['id'], item['scope']['kind'], item['scope']['id']) for item in existing}
    for reference in references:
        key = (reference['kind'], reference['id'], reference['scope']['kind'], reference['scope']['id'])
        if key not in keys:
            existing.append(deepcopy(reference))
            keys.add(key)
        kind = reference['kind']
        if kind in ('document', 'chat_attachment'):
            merged['document_ids'] = _string_list((merged.get('document_ids') or []) + [reference['id']])
            merged.setdefault('document_labels', {})[reference['id']] = reference.get('label', '')
        elif kind == 'tag':
            merged['tags'] = _string_list((merged.get('tags') or []) + [reference['id']])
        scope = reference['scope']
        if scope['kind'] == 'group':
            merged['active_group_ids'] = _string_list((merged.get('active_group_ids') or []) + [scope['id']])
        elif scope['kind'] == 'public':
            merged['active_public_workspace_ids'] = _string_list((merged.get('active_public_workspace_ids') or []) + [scope['id']])
    if references:
        kinds = {item['scope']['kind'] for item in references}
        original_scope = merged.get('doc_scope') or 'all'
        if original_scope != 'all':
            kinds.add(original_scope)
        merged['doc_scope'] = (
            next(iter(kinds))
            if len(kinds) == 1 and 'chat' not in kinds and not (had_selection and original_scope == 'all')
            else 'all'
        )
    if (
        merged.get('document_ids') and merged.get('tags')
        and not merged.get('document_filter_mode') and not had_document_tag_filter
    ):
        # New complementary selections use the composer's additive default. An existing
        # explicit mode, or an existing implicit intersection, remains a constraint.
        merged['document_filter_mode'] = 'union'
    return merged


def _elicitation_answer_text(context):
    """Support separate prompt/text fields and the V2 prompt-first combined text."""
    text = _text(context.get('text'))
    prompt = context.get('prompt_info') if isinstance(context.get('prompt_info'), dict) else {}
    prompt_text = _text(prompt.get('content'))
    if not prompt_text or text == prompt_text or text.startswith(f'{prompt_text}\n\n'):
        return text
    return f'{prompt_text}\n\n{text}' if text else prompt_text


def build_elicitation_user_request(user_message, answered_questions):
    accepted = []
    for answer in answered_questions or []:
        if answer.get('action', 'accept') != 'accept':
            continue
        accepted.append({
            'question': answer.get('question', ''),
            'answer': answer.get('answer', {}),
            'context': {
                name: {
                    'text': _elicitation_answer_text(context),
                    'references': context.get('references', []),
                }
                for name, context in (answer.get('context') or {}).items()
            },
        })
    if not accepted:
        return _text(user_message)
    return (
        f'{_text(user_message)}\n\nAccepted clarification answers (supplemental to the original request; '
        'reference labels identify sources, not file contents):\n'
        + json.dumps(accepted, ensure_ascii=False, sort_keys=True)
    )


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
            'scope_id': result.get('group_id') or result.get('public_workspace_id'),
            'group_id': result.get('group_id'),
            'public_workspace_id': result.get('public_workspace_id'),
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
        #
        # The names come from the composer, which had them on screen when the user picked.
        # Without them the planner reasons about bare uuids -- it cannot write "compare the
        # Q3 and Q4 contracts" if it has never been told which document is which, and the
        # approval card, whose whole purpose is letting someone check the planner picked the
        # right document, would show a row of identifiers.
        labels = seeds.get('document_labels') or {}
        references = {item['id']: item for item in seeds.get('elicitation_references') or []}
        return [
            {
                'document_id': document_id,
                'file_name': labels.get(document_id, ''),
                'title': labels.get(document_id, ''),
                'scope': (references.get(document_id, {}).get('scope') or {}).get('kind') or seeds.get('doc_scope') or 'all',
                'reference': references.get(document_id),
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
            active_public_workspace_id=seeds.get('active_public_workspace_ids') or None,
            # A picked tag is part of the question. Probing without it would offer the
            # planner documents the user has already excluded, and the plan would then be
            # built around a candidate they did not want considered.
            tags_filter=seeds.get('tags') or None,
            document_filter_mode=seeds.get('document_filter_mode') or 'intersection',
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
# Agents
# --------------------------------------------------------------------------------------

def resolve_agent_catalog(user_id, seeds=None, settings=None, user_groups=None):
    """The agents a plan may invoke, resolved once for the whole plan.

    Returns full catalog records rather than the planner projection. Two very different
    consumers read the same list, and they need different fields from it: the executor's
    agent step needs the scope and identifiers to load a kernel, while the planner needs
    only the handful of naming fields ``build_agent_planner_projection`` keeps. Feeding
    both from one resolution is the point -- ``build_accessible_agent_catalog`` is a
    multi-query Cosmos operation with no cache (personal, global and every group's agents,
    plus the model and action label maps and the user's group memberships), so resolving
    it once per plan and handing the result to ``build_planner_context`` *and* to
    ``RunContext.agent_catalog`` is the difference between one such traversal and one per
    step.

    Seeding mirrors ``resolve_candidate_documents``. A user who picked an agent in the
    composer has already made the choice this catalog exists to inform, so the selection
    is returned as-is and the traversal never runs -- and because the planner is then shown
    that agent alone, it is the only one a plan may name, exactly as a selected document is
    the only candidate.

    Fails soft. A Cosmos hiccup degrades to "no agent available" -- a plan that simply
    cannot reach for an agent -- rather than failing the whole request, on the same
    reasoning as the candidate probe above.
    """
    seeds = seeds or {}

    seeded_agent = seeds.get('agent')
    if isinstance(seeded_agent, dict) and _text(seeded_agent.get('name')):
        return [seeded_agent]

    try:
        # Lazy for the same reason as the candidate probe: functions_agent_catalog reaches
        # config.py and its import-time Cosmos client, and this module is imported by the
        # validator and by tests that have no Azure to talk to. Keeping the import inside
        # the resolver is what lets those import functions_orchestration_context at all.
        from functions_agent_catalog import build_accessible_agent_catalog

        return build_accessible_agent_catalog(
            user_id,
            settings=settings,
            user_groups=user_groups,
        )
    except Exception as exc:
        log_event(
            f"[ORCHESTRATION_CONTEXT] Agent catalog resolution failed; planning without "
            f"agents: {exc}",
            level=logging.WARNING,
        )
        return []


# --------------------------------------------------------------------------------------
# Run ledger
# --------------------------------------------------------------------------------------

def resolve_action_catalog(user_id, seeds=None, settings=None, user_groups=None):
    """Discover action metadata only when this request can use direct actions."""
    settings = settings or {}
    seeds = seeds or {}
    if (seeds.get('agent') or {}).get('name'):
        return []
    available = resolve_available_capability_ids(
        settings, allowed_ids=settings.get('chat_orchestration_enabled_capabilities'),
        candidate_ids=(CAPABILITY_ACTION_INVOKE,),
    )
    if CAPABILITY_ACTION_INVOKE not in available:
        return []

    # Storage imports initialize Azure clients; keep disabled orchestration lightweight.
    from functions_action_catalog import build_accessible_action_catalog

    return build_accessible_action_catalog(
        user_id, settings=settings, user_groups=user_groups,
    )


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

    ordered = [
        run for run in (runs or ())
        if isinstance(run, dict) and run.get('record_type') in (None, 'run', 'orchestration_run')
    ]
    # Zero runs is a real configuration: it makes every turn plan from scratch.
    if max_runs == 0:
        return {'runs': [], 'answered_questions': [], 'truncated': bool(ordered)}
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
        if not isinstance(run, dict) or run.get('record_type') not in (None, 'run', 'orchestration_run'):
            continue
        for item in run.get('answered_questions') or ():
            if isinstance(item, dict) and _text(item.get('question')):
                answered.append(item)
    return answered


# --------------------------------------------------------------------------------------
# Conversation signals
# --------------------------------------------------------------------------------------

class ConversationContextError(ValueError):
    """Conversation context could not be safely prepared or reused."""


def history_message_limit(settings=None):
    """Honor the chat history setting, rounding up to an even, bounded message count."""
    try:
        limit = math.ceil(float((settings or {}).get(
            'conversation_history_limit', HISTORY_MAX_TURNS
        )))
    except (TypeError, ValueError, OverflowError):
        log_event(
            '[ORCHESTRATION_CONTEXT] Invalid history limit; using the default.',
            level=logging.WARNING,
        )
        limit = HISTORY_MAX_TURNS
    return max(0, min(HISTORY_MAX_MESSAGES, limit + limit % 2))


def _history_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(
            block['text'] for block in content
            if isinstance(block, dict)
            and block.get('type') in ('text', 'input_text')
            and isinstance(block.get('text'), str)
        )
    return ''


def normalize_history_message(message):
    """Project one eligible stored message, after masks and current block revisions."""
    if not isinstance(message, dict) or message.get('role') not in ('user', 'assistant'):
        return None
    metadata = message.get('metadata') or {}
    if not isinstance(metadata, dict):
        raise ConversationContextError('The conversation contains invalid message metadata.')
    thread = metadata.get('thread_info') or {}
    if not isinstance(thread, dict):
        raise ConversationContextError('The conversation contains invalid thread metadata.')
    if (
        metadata.get('masked')
        or metadata.get('is_generated_chat_artifact')
        or thread.get('active_thread') is False
    ):
        return None

    content = _history_text(message.get('content'))
    ranges = metadata.get('masked_ranges') or []
    if not isinstance(ranges, list):
        raise ConversationContextError('The conversation contains invalid message masks.')
    content = remove_masked_content(content, ranges)
    content = resolve_block_sources_in_content(message, content).strip()
    if not content:
        return None

    projected = {
        'id': _text(message.get('id')),
        'role': message['role'],
        'content': content,
        'timestamp': _text(message.get('timestamp')),
    }
    projected['fingerprint'] = hashlib.sha256(
        json.dumps(projected, ensure_ascii=False, sort_keys=True).encode('utf-8')
    ).hexdigest()
    return projected


def _history_order(message):
    timestamp = _text(message.get('timestamp'))
    try:
        parsed = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    except ValueError:
        raise ConversationContextError('The conversation contains an invalid timestamp.') from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed, message['id']


def conversation_snapshot_size(snapshot):
    return len(json.dumps(snapshot, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def build_conversation_snapshot(messages, settings=None, *, turn_id=None, truncated=False):
    """Keep the recent eligible conversation, bounded independently of the current request."""
    eligible = []
    for message in messages or ():
        if not isinstance(message, dict):
            continue
        metadata = message.get('metadata') or {}
        orchestration = (metadata.get('orchestration') or {}) if isinstance(metadata, dict) else {}
        if turn_id and isinstance(orchestration, dict) and orchestration.get('turn_id') == turn_id:
            continue
        normalized = normalize_history_message(message)
        if normalized is not None:
            if not normalized['id']:
                raise ConversationContextError('The conversation contains a message without an ID.')
            eligible.append(normalized)
    eligible.sort(key=_history_order)
    limit = history_message_limit(settings)
    retained = eligible[-limit:] if limit else []
    snapshot = {
        'schema_version': HISTORY_SCHEMA_VERSION,
        'messages': retained,
        'truncated': bool(truncated or len(eligible) > len(retained)),
    }
    while len(retained) > 1 and conversation_snapshot_size(snapshot) > HISTORY_MAX_BYTES:
        retained.pop(0)
        snapshot['truncated'] = True
    if retained and conversation_snapshot_size(snapshot) > HISTORY_MAX_BYTES:
        # Preserve both ends of an oversized turn; constraints often occur at the end.
        newest = retained[0]
        original = newest['content']
        newest['truncated'] = True
        snapshot['truncated'] = True
        lower, upper = 0, len(original)
        while lower < upper:
            length = (lower + upper + 1) // 2
            tail_length = length // 2
            newest['content'] = (
                original[:length - tail_length]
                + '\n[Conversation message truncated.]\n'
                + (original[-tail_length:] if tail_length else '')
            )
            if conversation_snapshot_size(snapshot) <= HISTORY_MAX_BYTES:
                lower = length
            else:
                upper = length - 1
        tail_length = lower // 2
        newest['content'] = (
            original[:lower - tail_length]
            + '\n[Conversation message truncated.]\n'
            + (original[-tail_length:] if tail_length else '')
        )
    if conversation_snapshot_size(snapshot) > HISTORY_MAX_BYTES:
        raise ConversationContextError('The conversation context exceeds its size limit.')
    return snapshot


def validate_conversation_snapshot(snapshot, messages):
    """Reject a saved context if a source was edited, hidden, or removed after planning."""
    if (
        not isinstance(snapshot, dict)
        or snapshot.get('schema_version') != HISTORY_SCHEMA_VERSION
        or not isinstance(snapshot.get('messages'), list)
        or len(snapshot['messages']) > HISTORY_MAX_MESSAGES
        or conversation_snapshot_size(snapshot) > HISTORY_MAX_BYTES
    ):
        raise ConversationContextError('This plan needs to be created again.')
    current = {}
    sources = {}
    for message in messages or ():
        normalized = normalize_history_message(message)
        if normalized is not None:
            current[normalized['id']] = normalized
            sources[normalized['id']] = message
    seen = set()
    for previous in snapshot['messages']:
        if not isinstance(previous, dict):
            raise ConversationContextError('This plan needs to be created again.')
        message_id = previous.get('id')
        if (
            not message_id
            or message_id in seen
            or message_id not in current
            or previous.get('fingerprint') != current[message_id]['fingerprint']
        ):
            raise ConversationContextError(
                'Conversation context changed. Create a new plan before running this request.'
            )
        seen.add(message_id)
    rebuilt = build_conversation_snapshot(
        [sources[item['id']] for item in snapshot['messages']],
        {'conversation_history_limit': len(snapshot['messages'])},
        truncated=bool(snapshot.get('truncated')),
    )
    if rebuilt != snapshot:
        raise ConversationContextError('This plan needs to be created again.')
    return rebuilt


def conversation_reference_messages(snapshot, message_ids=None):
    """Return only role/content/ID fields, never stored metadata or citation payloads."""
    allowed = set(message_ids) if message_ids is not None else None
    return [
        {'id': message['id'], 'role': message['role'], 'content': message['content']}
        for message in (snapshot or {}).get('messages', [])
        if allowed is None or message['id'] in allowed
    ]


def validate_clarification_answers(answers):
    primitive_answers = [
        {key: value for key, value in answer.items() if key != 'context'}
        if isinstance(answer, dict) else answer
        for answer in answers
    ]
    if (
        len(answers) > LEDGER_MAX_ANSWERED_QUESTIONS
        or len(json.dumps(primitive_answers, ensure_ascii=False).encode('utf-8')) > CLARIFICATION_MAX_BYTES
        or len(json.dumps(answers, ensure_ascii=False).encode('utf-8')) > ELICITATION_CONTEXT_BYTE_LIMIT
    ):
        raise ConversationContextError('The clarification limit was reached. Start a new request.')


def conversation_user_urls(user_message, snapshot=None, message_ids=None, answered_questions=None):
    """URL provenance comes from user text, not from a model's interpretation."""
    urls = []
    for answer in reversed(answered_questions or []):
        if not isinstance(answer, dict) or answer.get('action', 'accept') != 'accept':
            continue
        content = answer.get('answer')
        values = list(content.values()) if isinstance(content, dict) else [content]
        for value in values:
            texts = value if isinstance(value, list) else [value]
            for text in texts:
                if isinstance(text, str):
                    urls.extend(_extract_urls(text))
        for context in (answer.get('context') or {}).values():
            if isinstance(context, dict):
                urls.extend(_extract_urls(_elicitation_answer_text(context)))
    urls.extend(_extract_urls(user_message))
    allowed = set(message_ids or [])
    for message in (snapshot or {}).get('messages', []):
        if message['id'] in allowed and message['role'] == 'user' and not message.get('truncated'):
            urls.extend(_extract_urls(message['content']))
    return _string_list(urls, limit=8)


def build_capability_request_context(
    user_id, identity, user_message, agent_catalog, action_catalog=None, *, allowed_user_urls=None,
):
    """Apply the same caller-specific capability gates to planning, revisions, and execution."""
    identity = identity or {}
    urls = (
        list(allowed_user_urls) if allowed_user_urls is not None
        else conversation_user_urls(user_message)
    )
    return {
        'user_id': user_id,
        'user_message': user_message or '',
        'message_urls': urls,
        'user_roles': identity.get('user_roles') or [],
        'user_email': identity.get('user_email'),
        'user_enable_agents': identity.get('user_enable_agents', True),
        'agent_catalog': list(agent_catalog or ()),
        'action_catalog': list(action_catalog or ()),
    }


def build_conversation_signals(messages, user_message, *, truncated=False, message_ids=None):
    """Project already bounded history for the planner; the route owns loading it."""
    allowed = set(message_ids) if message_ids is not None else None
    turns = [
        {'id': message.get('id'), 'role': message['role'], 'content': _history_text(message.get('content'))}
        for message in messages or ()
        if isinstance(message, dict)
        and message.get('role') in ('user', 'assistant')
        and (allowed is None or message.get('id') in allowed)
        and _history_text(message.get('content'))
    ]

    return {
        'recent_turns': turns,
        'truncated': bool(truncated),
        'urls': _extract_urls(user_message),
    }


def _extract_urls(text):
    """URLs present in the message, matching the client's own detection."""
    import re

    return _string_list(re.findall(r'https?://[^\s<>\'"]+', _text(text)), limit=8)


# --------------------------------------------------------------------------------------
# The planner's view
# --------------------------------------------------------------------------------------

def _selected_prompt(seeds):
    """The prompt the user attached, as the planner should see it.

    Both the name and the wording, because a plan is chosen from what the work involves and
    only the wording says that. Returns ``None`` rather than an empty dict when there is no
    prompt, so ``triage_request`` can test it the same way it tests the other selections.
    """
    prompt = seeds.get('prompt')
    if not isinstance(prompt, dict):
        return None

    name = _text(prompt.get('name'))
    content = _text(prompt.get('content'), SELECTED_PROMPT_LENGTH)
    if not name and not content:
        return None

    return {'name': name, 'content': content}


def build_planner_context(
    user_message,
    candidates=None,
    seeds=None,
    ledger=None,
    signals=None,
    capabilities=None,
    agents=None,
    answered_questions=None,
    actions=None,
    original_message=None,
    request_resolution=None,
):
    """Assemble everything the planner is shown, in one place.

    Kept as a single builder so that what the planner sees is auditable and testable
    rather than being spread across the prompt construction. Nothing enters the planner's
    context that is not visible here.

    ``agents`` are the full catalog records from ``resolve_agent_catalog``; they are
    projected here rather than trusted as-is so the planner is only ever shown the naming
    fields ``AGENT_PLANNER_FIELDS`` allows. Projecting at the single point the context is
    built means an agent's instructions cannot leak into the prompt even if a caller passes
    raw records, which is exactly what the executor is handed for ``RunContext.agent_catalog``.
    """
    seeds = seeds or {}
    return {
        'message': _text(user_message),
        'user_request': build_elicitation_user_request(user_message, answered_questions),
        'clarifications': deepcopy(answered_questions or []),
        'original_message': _text(original_message) if original_message is not None else _text(user_message),
        'request_resolution': request_resolution or {},
        'capabilities': capabilities or [],
        'agents': build_agent_planner_projection(agents),
        'actions': build_action_planner_projection(actions),
        'candidate_documents': [
            {key: value for key, value in candidate.items() if key != 'score'}
            for candidate in (candidates or ())
        ],
        'user_selected': {
            'documents': seeds.get('document_ids') or [],
            'context_references': deepcopy(seeds.get('elicitation_references') or []),
            'agent': (seeds.get('agent') or {}).get('name') if seeds.get('agent') else None,
            'prompt': _selected_prompt(seeds),
            'web_search': bool(seeds.get('web_search')),
        },
        'earlier_runs': ledger or {'runs': [], 'answered_questions': [], 'truncated': False},
        'conversation': signals or {'recent_turns': [], 'urls': []},
    }
