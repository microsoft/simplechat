# functions_orchestration_planner.py

"""
Triage, plan synthesis and re-planning.

The planner writes a plan. It does not execute one, and it is never given a tool. That
separation is the whole point of this framework: a model choosing among a short list of
described capabilities and returning JSON is a far more reliable thing than a model handed
forty plugins and an auto-invoke loop, and its output can be validated before anything
happens. Everything this module returns therefore passes through
``functions_orchestration_schema`` before it reaches an executor.

Two things are worth explaining because they are not obvious from the code.

**Triage is heuristic first.** The point of triage is to stop "what is the capital of
France" costing a planning round trip. Doing that triage *with a model call* would spend
exactly the round trip it was meant to save, so the cheap path is a set of conservative
heuristics that only fire when there is no evidence of anything to plan: no documents were
selected, no candidate documents came back, the message carries no comparative or
document-shaped language, and it is short. Anything else goes to the planner. The
heuristics are deliberately biased towards planning, because wrongly planning a simple
question wastes a call while wrongly trivialising a complex one produces a bad answer.

**Planner output is parsed defensively.** Models fence their JSON, prefix it with prose,
and occasionally return two objects. That is normal rather than exceptional, so extraction
tries several strategies before giving up, and a total failure degrades to a single
answering step rather than to an error -- a user who asked a question should get an
answer even when the planning layer had a bad day.

Version: 0.261.087
"""

import json
import logging
import re

from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

from config import cognitive_services_scope
from functions_appinsights import log_event
from functions_orchestration_registry import (
    CAPABILITY_RESPOND,
    build_planner_capability_projection,
    resolve_available_capabilities,
)
from functions_orchestration_schema import (
    COMPLEXITY_COMPLEX,
    COMPLEXITY_SIMPLE,
    COMPLEXITY_TRIVIAL,
    PlanValidationError,
    normalize_elicitation,
    normalize_plan,
)

PLANNER_MAX_TOKENS = 2000
PLANNER_TEMPERATURE = 0.1

# Triage heuristics. Short-circuiting is only allowed below this length, because a long
# message is evidence of a request with structure even when it contains none of the
# signal words below.
TRIVIAL_MAX_CHARACTERS = 180

# Language that means the request is about the user's own material or needs staged work.
# Prefixes rather than whole words, so "comparison" and "compared" count alongside
# "compare". That deliberately over-matches -- "comparable" trips it too -- which is the
# right direction to err in: a false positive costs one planning call, a false negative
# answers a document question without looking at the documents.
PLANNING_SIGNAL_PATTERN = re.compile(
    r'\b('
    r'compar\w*|contrast|differ\w*|versus|vs'
    r'|summar\w*|analy[sz]\w*|review|audit|extract|list all|every'
    r'|document|documents|file|files|report|reports|spreadsheet|workbook|csv|excel'
    r'|attachment|attachments|upload\w*|workspace'
    r'|search|find|look up|research|latest|current|news|today'
    r'|table|chart|export|generate'
    r')\b',
    re.IGNORECASE,
)


class PlannerError(RuntimeError):
    """Raised when the planner could not be reached or configured."""


def resolve_planner_client(settings):
    """Create the chat client that writes plans, and return it with its deployment name.

    Falls back to the deployment's ordinary chat configuration when no planner deployment
    is configured, so orchestration works the moment it is switched on rather than
    requiring a second model to be set up first. An administrator who wants planning done
    by something smaller and cheaper sets ``chat_orchestration_planner_deployment``; one
    who does not gets the model they already configured.
    """
    settings = settings or {}
    configured_deployment = str(
        settings.get('chat_orchestration_planner_deployment') or ''
    ).strip()

    if settings.get('enable_gpt_apim', False):
        raw_models = settings.get('azure_apim_gpt_deployment', '') or ''
        apim_models = [model.strip() for model in raw_models.split(',') if model.strip()]
        deployment = configured_deployment or (apim_models[0] if apim_models else '')
        if not deployment:
            raise PlannerError('No chat deployment is configured')
        client = AzureOpenAI(
            api_version=settings.get('azure_apim_gpt_api_version'),
            azure_endpoint=settings.get('azure_apim_gpt_endpoint'),
            api_key=settings.get('azure_apim_gpt_subscription_key'),
        )
        return client, deployment

    deployment = configured_deployment
    if not deployment:
        gpt_model_obj = settings.get('gpt_model', {}) or {}
        if gpt_model_obj.get('selected'):
            deployment = (gpt_model_obj['selected'][0] or {}).get('deploymentName')
    if not deployment:
        raise PlannerError('No chat deployment is configured')

    api_version = settings.get('azure_openai_gpt_api_version')
    endpoint = settings.get('azure_openai_gpt_endpoint')

    if settings.get('azure_openai_gpt_authentication_type') == 'managed_identity':
        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), cognitive_services_scope
        )
        client = AzureOpenAI(
            api_version=api_version,
            azure_endpoint=endpoint,
            azure_ad_token_provider=token_provider,
        )
    else:
        api_key = settings.get('azure_openai_gpt_key')
        if not api_key:
            raise PlannerError('No chat credentials are configured')
        client = AzureOpenAI(
            api_version=api_version,
            azure_endpoint=endpoint,
            api_key=api_key,
        )

    return client, deployment


# --------------------------------------------------------------------------------------
# Triage
# --------------------------------------------------------------------------------------

def triage_request(user_message, planner_context=None):
    """Decide whether this request needs a plan at all.

    Returns one of the complexity constants. ``trivial`` means the caller may skip the
    planner entirely and answer directly, which is the difference between a conversational
    reply feeling instant and feeling like it went away to think.

    Every condition here has to agree before a request is called trivial. That asymmetry
    is intentional: the cost of planning a simple question is one cheap call, while the
    cost of trivialising a complex one is a wrong answer.
    """
    planner_context = planner_context or {}
    message = str(user_message or '').strip()

    if not message:
        return COMPLEXITY_TRIVIAL

    selected = (planner_context.get('user_selected') or {})
    if selected.get('documents') or selected.get('agent') or selected.get('web_search'):
        # The user pointed at something. Whatever they want, it involves that thing.
        return COMPLEXITY_COMPLEX

    if planner_context.get('candidate_documents'):
        # Their own material looks relevant, so the plan has a real choice to make about
        # whether to read it.
        return COMPLEXITY_COMPLEX

    if (planner_context.get('conversation') or {}).get('urls'):
        return COMPLEXITY_COMPLEX

    if len(message) > TRIVIAL_MAX_CHARACTERS:
        return COMPLEXITY_SIMPLE

    if PLANNING_SIGNAL_PATTERN.search(message):
        return COMPLEXITY_SIMPLE

    return COMPLEXITY_TRIVIAL


def build_trivial_plan(user_message, planner_context=None):
    """The one-step plan for a request that needs no gathering."""
    return {
        'intent': {
            'summary': str(user_message or '').strip()[:200],
            'complexity': COMPLEXITY_TRIVIAL,
            'confidence': 1.0,
        },
        'assumptions': [],
        'steps': [
            {
                'step_id': 'step_1',
                'capability_id': CAPABILITY_RESPOND,
                'title': 'Answer',
                'rationale': 'The question can be answered directly.',
                'arguments': {},
                'depends_on': [],
            }
        ],
    }


# --------------------------------------------------------------------------------------
# Prompting
# --------------------------------------------------------------------------------------

PLANNER_SYSTEM_PROMPT = """You plan how an AI assistant should answer a user's request.

You do NOT answer the request and you do NOT perform any work. You return a plan as JSON
and nothing else.

You will be given the capabilities available to you. Use only those. Each capability lists
what it is for and the arguments it takes. Never invent a capability or an argument.

Each capability names a phase. The phases run in a fixed order: knowledge, then reasoning,
then output. "knowledge" is every capability that gathers or produces the evidence an
answer stands on. "reasoning" is the single "respond" step that writes the answer from
what those steps gathered. Because the phases are ordered, a plan may never gather after
it answers: every gathering step comes before "respond", which is always the last step.

Some requests are best handed to an agent -- a preconfigured assistant with its own tools
and knowledge. The agents you may use are listed under "agents", each with its name and
what it is for. To use one, add the agent capability and set "agent_name" to a name that
appears in that list, spelled exactly. Never name an agent that is not listed; if the list
is empty you have no agent to call, so do not plan an agent step.

Return ONE JSON object with this shape:

{
  "kind": "plan",
  "intent": {"summary": "<one sentence describing what the user wants>",
             "complexity": "trivial" | "simple" | "complex",
             "confidence": <0.0 to 1.0>},
  "assumptions": ["<anything you assumed, if it matters>"],
  "steps": [
    {"step_id": "step_1",
     "capability_id": "<one of the available capability ids>",
     "title": "<short label a person would recognise>",
     "rationale": "<why this step is needed, one sentence>",
     "arguments": { ... matching that capability's declared inputs ... },
     "depends_on": ["<step_id of a step whose result this one needs>"]}
  ]
}

Rules:
- The final step is always "respond". Everything before it gathers what "respond" needs.
- Prefer the cheapest capability that will actually answer the question. Searching
  documents is much cheaper than analysing them; only analyse when the question needs
  whole-document coverage.
- On the open web, web_search is the cheap default. deep_research is the most expensive
  capability available to you; reach for it deliberately, only when a shallow web_search
  genuinely could not cover the question.
- Only name a document id that appears in the candidate documents or that the user
  selected. Never invent one.
- If the user already selected documents, plan around those documents.
- Read the earlier runs. If a previous run already gathered something, do not gather it
  again; depend on the answer instead and say so in the rationale.
- Keep the plan as short as it can be while still being right. A one-step plan is a good
  plan when the question is simple.

If you genuinely cannot plan without more information from the user, return this instead:

{
  "kind": "elicitation",
  "message": "<why you need more, one sentence>",
  "requested_schema": {
    "type": "object",
    "properties": {
      "<field_name>": {"type": "string"|"number"|"integer"|"boolean"|"array",
                       "title": "<the question, phrased for a person>",
                       "enum": [...],
                       "items": {"type": "string", "enum": [...]}}
    },
    "required": ["<field_name>"]
  },
  "ui_hints": {"pages": [["<field_name>"]]}
}

The schema must be a FLAT object of simple fields. No nested objects. Offer enum choices
whenever you can, so the user picks rather than types. Do not ask something the earlier
runs show has already been answered. Only ask when you truly cannot proceed; a reasonable
assumption stated in "assumptions" is better than a question."""


def build_planner_messages(planner_context, replan_hint=None):
    """The two messages the planner sees.

    The context is passed as JSON rather than prose because it is data the model has to
    read precisely -- document ids especially. A prose rendering invites paraphrase, and a
    paraphrased document id is a plan step that fails validation.
    """
    payload = dict(planner_context or {})

    user_content = json.dumps(payload, indent=2, default=str)

    if replan_hint:
        user_content += (
            "\n\nA step in your previous plan reported this and the plan needs "
            f"reconsidering:\n{replan_hint}\n"
            "Return a revised plan that takes it into account. Do not repeat work that "
            "already succeeded."
        )

    return [
        {'role': 'system', 'content': PLANNER_SYSTEM_PROMPT},
        {'role': 'user', 'content': user_content},
    ]


# --------------------------------------------------------------------------------------
# Response parsing
# --------------------------------------------------------------------------------------

def extract_planner_json(reply):
    """Pull one JSON object out of a planner reply.

    Tried in order of how much the reply is trusted: the whole string, then a fenced
    block, then the widest brace-balanced span. Models do all three of these routinely,
    and treating a fenced object as a parse failure would discard a perfectly good plan
    over formatting.
    """
    text = str(reply or '').strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except (TypeError, ValueError):
        pass

    fenced = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            return parsed if isinstance(parsed, dict) else None
        except (TypeError, ValueError):
            pass

    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end > start:
        try:
            parsed = json.loads(text[start:end + 1])
            return parsed if isinstance(parsed, dict) else None
        except (TypeError, ValueError):
            pass

    return None


def _call_planner(client, deployment, messages):
    """One planner completion, asking for JSON where the deployment supports it."""
    try:
        response = client.chat.completions.create(
            model=deployment,
            messages=messages,
            temperature=PLANNER_TEMPERATURE,
            max_tokens=PLANNER_MAX_TOKENS,
            response_format={'type': 'json_object'},
        )
    except Exception as exc:
        # Not every deployment or API version accepts response_format, and a refusal here
        # is a configuration difference rather than a failure. The prompt already asks for
        # one JSON object, and the extractor copes with a reply that merely contains one.
        log_event(
            f"[ORCHESTRATION_PLANNER] Retrying without a JSON response format: {exc}",
            level=logging.INFO,
        )
        response = client.chat.completions.create(
            model=deployment,
            messages=messages,
            temperature=PLANNER_TEMPERATURE,
            max_tokens=PLANNER_MAX_TOKENS,
        )

    if not response or not response.choices:
        return '', None

    usage = getattr(response, 'usage', None)
    return (response.choices[0].message.content or ''), usage


# --------------------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------------------

def plan_request(
    user_message,
    planner_context,
    conversation_id,
    user_id,
    settings=None,
    approval_mode=None,
    authorized_document_ids=None,
    replan_hint=None,
    revision=0,
    allow_elicitation=True,
    turn_id=None,
    seeds=None,
    document_labels=None,
    request_context=None,
):
    """Produce a validated plan, or a question set, for one request.

    Returns ``(kind, document)`` where ``kind`` is ``'plan'`` or ``'elicitation'``.

    ``request_context`` describes *this caller*, as opposed to the deployment: their app
    roles, whether their message contains a URL, whether they have an agent to invoke. It
    is what the capability request gates read. Passing it here narrows one resolution and
    thereby three things at once -- what the planner is shown, what the validator will
    accept, and so what can reach an adapter. Omitting it describes the deployment instead,
    which is what the admin page and the bootstrap payload want but never what a real
    request wants.

    A planner that fails -- unreachable, unparseable, or producing something that cannot
    be validated -- degrades to a single answering step rather than raising. The user
    asked a question; an orchestration layer having a bad day is not a reason to refuse to
    answer it.
    """
    settings = settings if isinstance(settings, dict) else {}

    capabilities = resolve_available_capabilities(
        settings,
        allowed_ids=settings.get('chat_orchestration_enabled_capabilities'),
        request_context=request_context,
    )
    available_ids = [capability['id'] for capability in capabilities]

    context = dict(planner_context or {})
    context['capabilities'] = build_planner_capability_projection(capabilities)

    def _fallback(reason):
        log_event(
            f"[ORCHESTRATION_PLANNER] Falling back to a direct answer: {reason}",
            level=logging.WARNING,
        )
        plan = normalize_plan(
            build_trivial_plan(user_message, context),
            conversation_id,
            user_id,
            settings=settings,
            approval_mode=approval_mode,
            authorized_document_ids=authorized_document_ids,
            available_capability_ids=available_ids,
            turn_id=turn_id,
            seeds=seeds,
            document_labels=document_labels,
        )
        plan['revision'] = revision
        plan['planner_fallback_reason'] = reason
        return 'plan', plan

    try:
        client, deployment = resolve_planner_client(settings)
    except PlannerError as exc:
        return _fallback(str(exc))

    try:
        reply, usage = _call_planner(
            client, deployment, build_planner_messages(context, replan_hint=replan_hint)
        )
    except Exception as exc:
        return _fallback(f'the planner call failed: {exc}')

    parsed = extract_planner_json(reply)
    if not parsed:
        return _fallback('the planner returned nothing parseable')

    kind = str(parsed.get('kind') or '').strip().lower()

    if kind == 'elicitation' and allow_elicitation:
        try:
            elicitation = normalize_elicitation(parsed, run_id=None, revision=revision)
            return 'elicitation', elicitation
        except PlanValidationError as exc:
            # A question we cannot render is worse than no question: the run would stall
            # on a card that never appears. Planning again without the option is the only
            # honest recovery.
            log_event(
                f"[ORCHESTRATION_PLANNER] Discarding an unrenderable question set: {exc}",
                level=logging.WARNING,
            )
            return plan_request(
                user_message,
                planner_context,
                conversation_id,
                user_id,
                settings=settings,
                approval_mode=approval_mode,
                authorized_document_ids=authorized_document_ids,
                replan_hint=replan_hint,
                revision=revision,
                allow_elicitation=False,
                turn_id=turn_id,
                seeds=seeds,
                document_labels=document_labels,
            )

    if kind == 'elicitation':
        return _fallback('the planner asked a question when it had already asked one')

    try:
        plan = normalize_plan(
            parsed,
            conversation_id,
            user_id,
            settings=settings,
            approval_mode=approval_mode,
            authorized_document_ids=authorized_document_ids,
            available_capability_ids=available_ids,
            turn_id=turn_id,
            seeds=seeds,
            document_labels=document_labels,
        )
    except PlanValidationError as exc:
        return _fallback(f'no runnable step survived validation: {exc}')

    plan['revision'] = revision
    plan['planner_model'] = deployment
    if usage is not None:
        plan['token_usage'] = {
            'prompt_tokens': getattr(usage, 'prompt_tokens', None),
            'completion_tokens': getattr(usage, 'completion_tokens', None),
            'total_tokens': getattr(usage, 'total_tokens', None),
        }

    return 'plan', plan
