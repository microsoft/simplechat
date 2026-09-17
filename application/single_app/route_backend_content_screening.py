# route_backend_content_screening.py
"""Authenticated Content Screening API (implementation version 0.261.106).

All paths below begin with /api/content-screening. Errors are
{error: stable_public_message, code: stable_code}; evidence is inert text only.

GET configuration -> {enabled, enhanced_citations_enabled, can_manage_global,
                      can_scan_all, templates}
PUT configuration {enabled: bool} -> the same safe capability payload (Admin).
    Activation validates the baseline's selected scanner bindings and storage
    through the shared settings/service boundary before writing the toggle.
    Model preflight is metadata-only; deterministic-only policies need no model.
GET/PUT policies/<scope_type>/<scope_id> -> {scope_type, scope_id, policy, etag,
    inherited_summary, allowed_models, templates}; PUT accepts {policy, etag}, with etag=null
    for creation. Only Admin may edit global/global. Other scopes require the
    personal owner or current workspace Owner/Admin/DocumentManager.
POST policies/<scope_type>/<scope_id>/test {policy, sample_text} -> {status,
    complete, finding_count, findings, findings_truncated, error_code}. Tests
    evaluate the editable policy, not secret inherited rules, and store nothing.
    Templates are dictionaries: {rules, packs, ai}. Model selections contain only
    endpoint_id/model_id references; use the existing model picker APIs.

GET/POST scans -> {items, continuation} / a safe durable job; POST accepts
    {scope_type, scope_id, document_ids?} OR {all_workspaces: true}.
GET scans/<job_id>; GET scans/<job_id>/items -> {items, continuation}.
POST scans/<job_id>/actions {action: resume|cancel|retry} -> safe job.
    Job = {id,state,selection,counters,created_at,updated_at,error_code,etag,
           allowed_actions,enumeration_complete,cancel_requested}.
    Work item = {id,state,scan_id,finding_count,error_code}; never source names,
    policy snapshots, private subjects, or provider response bodies.

GET reviews [scope_type,scope_id,state=pending|resolved|all] -> {items,continuation}.
GET reviews/<scan_id> -> {id,subject,state,etag,content_fingerprint,
    policy_fingerprint,outcome,coverage:{complete,units_total,status},
    coverage_mode,finding_count,review_required,candidate_of,original_retained,
    sanitized,allowed_actions,downloads,evidence,warning,decision,created_at,updated_at}.
    subject = {kind:workspace_document,scope_type,scope_id,document_id,source_revision}.
    decision = null | {action,actor_id,reason,decided_at}; queues omit decision.
    evidence = {units_available:bool,findings_available:bool}. Missing evidence
    does not prevent authorized metadata-only Reject/Delete or deletion retry.
    downloads = {original:null|{url,file_name},clean:null|{url,file_name}}.
    allowed_actions includes download_original/download_clean only when the
    corresponding attachment is available. URLs are local API paths, never
    storage references. Retained originals stay reviewer-only after release.
GET .../downloads/original -> the exact scan's retained original attachment.
GET .../downloads/clean -> the exact active RELEASED scan's clean derivative.
    Both require the current personal owner/workspace reviewer relationship,
    rechecked before and after reading. No historical/original fallback for
    clean downloads; no browser-provided blob reference or source override.
    Responses are attachment-only application/octet-stream with sanitized
    filenames, private/no-store caching and nosniff (including active HTML).
GET .../units and .../findings -> {items,continuation,total}.
    Unit = {unit_id,text,locator,content_hash,normalization_version:1,
            offset_encoding:unicode_codepoints,text_offset,text_total}.
    Finding = {finding_id,rule_id,unit_id,category,severity,start,end,source,
               confidence,reason,evidence,evidence_truncated}.
    Unit text_offset/text_total describe a bounded window of canonical text;
    add text_offset to Unicode code-point selections. content_hash always hashes
    the entire canonical unit. Paginated evidence never contains blob references.
POST .../preview or .../remediate {etag, edits:[edit]}:
    edit = {action:remove_unit,unit_id,content_hash}
         | {action:remove_span,unit_id,content_hash,start,end}
         | {action:replace_cell,unit_id,content_hash,text}.
    Preview returns {units,total_units,preview_truncated,content_fingerprint,
    removed_unit_ids,removed_unit_count,warnings}. Remediate returns HTTP 202
    with a durably queued pending_scan candidate, never a synchronous scan or
    automatically published document. Refresh/poll GET review until scanning
    completes; pending/error/incomplete candidates cannot be approved.
    Preview units contain changed surviving units, not unmodified document text.
POST .../decision {etag,action:approve_with_flags|approve_clean|reject|delete,
    reason,acknowledge_flags?} -> review. Flags require acknowledge_flags=true.
    Clean approval requires a complete, clean candidate rescan.
    action=retry_publication resumes a stalled publishing operation only after
    its lease expires, for the same still-authorized reviewer and exact existing
    decision. It never approves a scan_error or incomplete scan.
GET status?scope_type=&scope_id=&document_id= -> safe ordinary document status.
    Status = {document_id,state,available,finding_count,scan_id?,review_id?,
              updated_at?,can_review,review_url}.

Pagination accepts page_size=1..100 and opaque continuation tokens. Mutations
inherit app.py's authenticated same-origin CSRF boundary; no route is exempted.
Application and scanner clients are imported at operation boundaries where that
avoids application-initialization cycles.
"""

import copy
import json
import logging
from urllib.parse import quote

from flask import Response, jsonify, request, session
from werkzeug.exceptions import HTTPException

from content_screening import reviews
from content_screening.contracts import (
    ContentUnit,
    ScreeningConfigurationError,
    ScreeningConflictError,
    ScreeningError,
    ScreeningValidationError,
    Subject,
    normalize_identifier,
    public_screening_summary,
    subject_from_document,
)
from content_screening.permissions import (
    ScreeningNotFoundError,
    ScreeningPermissionError,
    assert_scope_access,
)
from functions_appinsights import log_event
from functions_authentication import (
    admin_required,
    get_current_user_id,
    login_required,
    user_required,
    user_required_blueprint,
)
from functions_settings import cosmos_settings_container, get_settings, update_settings, validate_content_screening_settings
from swagger_wrapper import swagger_route, get_auth_security


MAX_REQUEST_BYTES = 256000
MAX_SAMPLE_CHARACTERS = 20000
MAX_SELECTION_DOCUMENTS = 1000
SAMPLE_LIMITS = {
    "max_units": 1, "max_total_characters": MAX_SAMPLE_CHARACTERS,
    "max_findings": 100, "max_windows": 32, "max_runtime_seconds": 30.0,
}
JOB_ACTIONS = frozenset({"resume", "cancel", "retry"})


def _repository():
    from content_screening.repository import get_repository

    return get_repository()


def _actor_id():
    actor_id = get_current_user_id()
    if not actor_id:
        raise ScreeningPermissionError()
    return normalize_identifier(actor_id, "actor_id")


def _is_admin():
    roles = (session.get("user") or {}).get("roles") or []
    return isinstance(roles, (list, tuple)) and "Admin" in roles


def _body(allowed, required=()):
    if not request.is_json or request.content_length and request.content_length > MAX_REQUEST_BYTES:
        raise ScreeningValidationError()
    raw = request.stream.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        raise ScreeningValidationError(code="screening_request_too_large")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ScreeningValidationError() from error
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ScreeningValidationError()
    return value


def _query(allowed):
    if set(request.args) - set(allowed) or any(len(values) != 1 for _key, values in request.args.lists()):
        raise ScreeningValidationError()
    return request.args


def _pagination(args):
    raw = args.get("page_size", "50")
    if not raw.isascii() or not raw.isdigit() or len(raw) > 3 or not 1 <= int(raw) <= 100:
        raise ScreeningValidationError()
    continuation = args.get("continuation")
    if continuation is not None and (not continuation or len(continuation) > 32768):
        raise ScreeningValidationError()
    return {"page_size": int(raw), "continuation": continuation}


def _safe_code(value):
    if (
        isinstance(value, str) and 0 < len(value) <= 80 and value.replace("_", "").isalnum()
        and (value.startswith(("screening_", "invalid_screening_")) or value == "document_under_review")
    ):
        return value
    return "screening_error"


def _review_attachment_response(scan_id, kind):
    content, file_name = reviews.read_review_attachment(
        scan_id, _actor_id(), kind, repository=_repository(),
    )
    response = Response(content, content_type="application/octet-stream")
    response.headers.set("Content-Disposition", "attachment", filename=file_name)
    response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return response


def _templates():
    from content_screening.policies import AI_STARTER_CRITERIA, STARTER_PACKS, STARTER_RULE_TEMPLATES

    return copy.deepcopy({
        "rules": STARTER_RULE_TEMPLATES, "packs": STARTER_PACKS, "ai": AI_STARTER_CRITERIA,
    })


def _configuration(settings=None):
    settings = settings if isinstance(settings, dict) else get_settings() or {}
    return {
        "enabled": settings.get("enable_content_screening") is True,
        "enhanced_citations_enabled": settings.get("enable_enhanced_citations") is True,
        "can_manage_global": _is_admin(), "can_scan_all": _is_admin(),
        "templates": _templates(),
    }


def _authorize_policy(scope_type, scope_id):
    if scope_type == "global":
        if scope_id != "global":
            raise ScreeningValidationError()
        if not _is_admin():
            raise ScreeningPermissionError()
    else:
        assert_scope_access(_actor_id(), scope_type, scope_id)


def _policy_payload(repository, scope_type, scope_id):
    from content_screening.policies import compose_policy, default_policy, normalize_policy, safe_baseline_summary

    record = repository.get_policy(scope_type, scope_id)
    baseline = repository.get_policy("global", "global")
    policy = normalize_policy(
        record["policy"] if record else default_policy(), scope_type=scope_type,
    )
    baseline_policy = baseline["policy"] if baseline else default_policy()
    allowed_models = compose_policy(baseline_policy)["allowed_models"]
    return {
        "scope_type": scope_type, "scope_id": scope_id,
        "policy": policy, "etag": record.get("_etag") if record else None,
        "allowed_models": allowed_models,
        "inherited_summary": {**safe_baseline_summary(baseline_policy), "allowed_models": allowed_models}
        if scope_type != "global" else None,
        "templates": _templates(),
    }


def _selection(value):
    all_workspaces = value.get("all_workspaces", False)
    if type(all_workspaces) is not bool:
        raise ScreeningValidationError()
    if all_workspaces:
        if set(value) != {"all_workspaces"}:
            raise ScreeningValidationError()
        if not _is_admin():
            raise ScreeningPermissionError()
        return {"all_workspaces": True}
    scope_type, scope_id = value.get("scope_type"), value.get("scope_id")
    if not isinstance(scope_type, str) or scope_type not in {"personal", "group", "public"}:
        raise ScreeningValidationError()
    scope_id = normalize_identifier(scope_id, "scope_id")
    if not _is_admin():
        assert_scope_access(_actor_id(), scope_type, scope_id)
    selection = {"scope_type": scope_type, "scope_id": scope_id}
    if "document_ids" in value:
        ids = value["document_ids"]
        if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_SELECTION_DOCUMENTS:
            raise ScreeningValidationError()
        selection["document_ids"] = [normalize_identifier(value, "document_id") for value in ids]
        if len(set(selection["document_ids"])) != len(ids):
            raise ScreeningValidationError()
    return selection


def _authorize_job(job):
    if _is_admin():
        return
    selection = job.get("selection") or {}
    if selection.get("all_workspaces"):
        raise ScreeningPermissionError()
    assert_scope_access(_actor_id(), selection.get("scope_type"), selection.get("scope_id"))


def _get_job(repository, job_id):
    job_id = normalize_identifier(job_id, "job_id")
    job = repository.get(job_id, job_id)
    if not job or job.get("kind") != "job":
        raise ScreeningNotFoundError()
    _authorize_job(job)
    return job


def _safe_job(job):
    selection = job.get("selection") or {}
    counters = job.get("counts") or job.get("counters") or {}
    state = job.get("status") or job.get("state")
    return {
        "id": job["id"], "state": state,
        "selection": {
            key: selection[key] for key in ("scope_type", "scope_id", "all_workspaces", "document_ids")
            if key in selection
        },
        "counters": {
            key: value for key, value in counters.items()
            if key in {"total", "queued", "running", "completed", "cleared", "findings",
                       "incomplete", "failed", "cancelled", "enumerated", "scanned", "retry", "skipped"}
            and type(value) is int and value >= 0
        } if isinstance(counters, dict) else {},
        "created_at": job.get("created_at"), "updated_at": job.get("updated_at"),
        "error_code": _safe_code(job["error_code"]) if job.get("error_code") else None,
        "etag": job.get("_etag"),
        "allowed_actions": ["resume", "retry"] if state in {"cancelled", "failed", "incomplete"}
        else [] if state in {"completed", "completed_with_findings"} else ["cancel"],
        "enumeration_complete": (job.get("enumeration") or {}).get("complete") is True,
        "cancel_requested": job.get("cancel_requested") is True,
    }


def register_route_backend_content_screening(bp):
    bp.before_request(user_required_blueprint())

    @bp.after_request
    def screening_private_response(response):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @bp.errorhandler(ScreeningError)
    def screening_error(error):
        return jsonify({"error": error.public_message, "code": _safe_code(error.code)}), error.status_code

    @bp.errorhandler(Exception)
    def screening_unexpected_error(error):
        if isinstance(error, HTTPException):
            return jsonify({"error": "The content screening request could not be processed.",
                            "code": "invalid_screening_request"}), error.code
        log_event(
            "[CONTENT_SCREENING] api_request_failed",
            extra={"error_type": type(error).__name__},
            level=logging.ERROR,
        )
        return jsonify({"error": ScreeningError.public_message, "code": "screening_error"}), 503

    @bp.route("/api/content-screening/configuration", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def content_screening_configuration():
        _query(())
        return jsonify(_configuration())

    @bp.route("/api/content-screening/configuration", methods=["PUT"])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def content_screening_update_configuration():
        value = _body({"enabled"}, {"enabled"})
        if type(value["enabled"]) is not bool:
            raise ScreeningValidationError()
        updates = {"enable_content_screening": value["enabled"]}
        settings = cosmos_settings_container.read_item(item="app_settings", partition_key="app_settings")
        if not isinstance(settings, dict):
            raise ScreeningConfigurationError()
        validate_content_screening_settings(updates, settings, repository=_repository())
        if not update_settings(updates):
            raise ScreeningConfigurationError()
        return jsonify(_configuration({**settings, **updates}))

    @bp.route("/api/content-screening/policies/<scope_type>/<scope_id>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def content_screening_get_policy(scope_type, scope_id):
        _query(())
        scope_id = normalize_identifier(scope_id, "scope_id")
        _authorize_policy(scope_type, scope_id)
        return jsonify(_policy_payload(_repository(), scope_type, scope_id))

    @bp.route("/api/content-screening/policies/<scope_type>/<scope_id>", methods=["PUT"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def content_screening_save_policy(scope_type, scope_id):
        from content_screening.policies import compose_policy, default_policy, normalize_policy

        scope_id = normalize_identifier(scope_id, "scope_id")
        _authorize_policy(scope_type, scope_id)
        value = _body({"policy", "etag"}, {"policy", "etag"})
        if value["etag"] is not None and not isinstance(value["etag"], str):
            raise ScreeningValidationError()
        repository = _repository()
        policy = normalize_policy(value["policy"], scope_type=scope_type)
        if scope_type != "global":
            baseline = repository.get_policy("global", "global")
            compose_policy(baseline["policy"] if baseline else default_policy(), policy)
        repository.save_policy(scope_type, scope_id, policy, _actor_id(), etag=value["etag"])
        return jsonify(_policy_payload(repository, scope_type, scope_id))

    @bp.route("/api/content-screening/policies/<scope_type>/<scope_id>/test", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def content_screening_test_policy(scope_type, scope_id):
        from content_screening.engine import inspect_content
        from content_screening.policies import compose_policy, default_policy, normalize_policy

        scope_id = normalize_identifier(scope_id, "scope_id")
        _authorize_policy(scope_type, scope_id)
        value = _body({"policy", "sample_text"}, {"policy", "sample_text"})
        sample = value["sample_text"]
        if not isinstance(sample, str) or not sample.strip() or len(sample) > MAX_SAMPLE_CHARACTERS:
            raise ScreeningValidationError()
        policy = normalize_policy(value["policy"], scope_type=scope_type)
        if scope_type != "global":
            baseline = _repository().get_policy("global", "global")
            effective = compose_policy(baseline["policy"] if baseline else default_policy(), policy)
            policy["allowed_models"] = effective["allowed_models"]
            policy["limits"] = {
                key: min(value, effective["limits"][key]) for key, value in policy["limits"].items()
            }
        policy["limits"] = {
            key: min(value, SAMPLE_LIMITS.get(key, value)) for key, value in policy["limits"].items()
        }
        policy["enabled"] = True
        effective = compose_policy(policy)
        actor = _actor_id()
        result = inspect_content(
            Subject("personal", actor, "policy-preview", "1"),
            [ContentUnit("sample", sample, {"kind": "sample"})], effective,
        )
        payload = result.to_dict()
        return jsonify({
            "status": payload["status"],
            "complete": payload["status"] in {"pass", "findings"},
            "finding_count": len(payload["findings"]),
            "findings": [
                {**{key: finding.get(key) for key in (
                    "finding_id", "rule_id", "unit_id", "category", "severity",
                    "start", "end", "source", "confidence",
                )}, "reason": str(finding.get("reason") or "")[:2000],
                    "evidence": str(finding.get("evidence") or "")[:4000]}
                for finding in payload["findings"][:20]
            ],
            "findings_truncated": len(payload["findings"]) > 20,
            "error_code": _safe_code(payload["error_code"]) if payload.get("error_code") else None,
        })

    @bp.route("/api/content-screening/scans", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def content_screening_start_scan():
        from content_screening.jobs import create_scan_job

        value = _body({"scope_type", "scope_id", "document_ids", "all_workspaces"})
        selection = _selection(value)
        job = create_scan_job(_actor_id(), selection, is_admin=_is_admin(), repository=_repository())
        return jsonify(_safe_job(job)), 202

    @bp.route("/api/content-screening/scans", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def content_screening_list_scans():
        args = _query({"scope_type", "scope_id", "page_size", "continuation"})
        scope_key = None
        filters = {}
        if args.get("scope_type") is not None or args.get("scope_id") is not None:
            selection = _selection({"scope_type": args.get("scope_type"), "scope_id": args.get("scope_id")})
            scope_key = f"{selection['scope_type']}:{selection['scope_id']}"
        elif not _is_admin():
            filters = {"actor_id": _actor_id()}
        page = _repository().query("job", scope_key, filters=filters, **_pagination(args))
        items = []
        for job in page["items"]:
            try:
                _authorize_job(job)
            except ScreeningPermissionError:
                continue
            items.append(_safe_job(job))
        return jsonify({"items": items, "continuation": page.get("continuation")})

    @bp.route("/api/content-screening/scans/<job_id>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def content_screening_get_scan(job_id):
        _query(())
        return jsonify(_safe_job(_get_job(_repository(), job_id)))

    @bp.route("/api/content-screening/scans/<job_id>/items", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def content_screening_scan_items(job_id):
        args = _query({"page_size", "continuation"})
        repository = _repository()
        _get_job(repository, job_id)
        page = repository.query("work_item", filters={"job_id": job_id}, **_pagination(args))
        return jsonify({
            "items": [{
                "id": item["id"], "state": item.get("status") or item.get("state"), "scan_id": item.get("scan_id"),
                "finding_count": reviews._safe_count(item.get("finding_count")),
                "error_code": _safe_code(item["error_code"]) if item.get("error_code") else None,
            } for item in page["items"]],
            "continuation": page.get("continuation"),
        })

    @bp.route("/api/content-screening/scans/<job_id>/actions", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def content_screening_scan_action(job_id):
        from content_screening.jobs import request_scan_job_action

        value = _body({"action"}, {"action"})
        if not isinstance(value["action"], str) or value["action"] not in JOB_ACTIONS:
            raise ScreeningValidationError()
        repository = _repository()
        _get_job(repository, job_id)
        result = request_scan_job_action(
            job_id=job_id, actor_id=_actor_id(), action=value["action"],
            is_admin=_is_admin(), repository=repository,
        )
        return jsonify(_safe_job(result))

    @bp.route("/api/content-screening/reviews", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def content_screening_reviews():
        args = _query({"scope_type", "scope_id", "state", "page_size", "continuation"})
        return jsonify(reviews.list_reviews(
            _actor_id(), scope_type=args.get("scope_type"), scope_id=args.get("scope_id"),
            state=args.get("state", "pending"), repository=_repository(), **_pagination(args),
        ))

    @bp.route("/api/content-screening/reviews/<scan_id>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def content_screening_review(scan_id):
        _query(())
        return jsonify(reviews.get_review(scan_id, _actor_id(), repository=_repository()))

    @bp.route("/api/content-screening/reviews/<scan_id>/downloads/original", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def content_screening_download_original(scan_id):
        _query(())
        return _review_attachment_response(scan_id, "original")

    @bp.route("/api/content-screening/reviews/<scan_id>/downloads/clean", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def content_screening_download_clean(scan_id):
        _query(())
        return _review_attachment_response(scan_id, "clean")

    @bp.route("/api/content-screening/reviews/<scan_id>/units", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def content_screening_review_units(scan_id):
        args = _query({"page_size", "continuation"})
        return jsonify(reviews.get_review_units(
            scan_id, _actor_id(), repository=_repository(), **_pagination(args),
        ))

    @bp.route("/api/content-screening/reviews/<scan_id>/findings", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def content_screening_review_findings(scan_id):
        args = _query({"page_size", "continuation"})
        return jsonify(reviews.get_review_findings(
            scan_id, _actor_id(), repository=_repository(), **_pagination(args),
        ))

    @bp.route("/api/content-screening/reviews/<scan_id>/preview", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def content_screening_preview(scan_id):
        value = _body({"etag", "edits"}, {"etag", "edits"})
        return jsonify(reviews.preview_remediation(
            scan_id, _actor_id(), value["etag"], value["edits"], repository=_repository(),
        ))

    @bp.route("/api/content-screening/reviews/<scan_id>/remediate", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def content_screening_remediate(scan_id):
        value = _body({"etag", "edits"}, {"etag", "edits"})
        return jsonify(reviews.remediate_review(
            scan_id, _actor_id(), value["etag"], value["edits"], repository=_repository(),
        )), 202

    @bp.route("/api/content-screening/reviews/<scan_id>/decision", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def content_screening_decision(scan_id):
        value = _body({"etag", "action", "reason", "acknowledge_flags"}, {"etag", "action", "reason"})
        return jsonify(reviews.decide_review(
            scan_id, _actor_id(), value["etag"], value["action"], value["reason"],
            acknowledge_flags=value.get("acknowledge_flags", False), repository=_repository(),
        ))

    @bp.route("/api/content-screening/status", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def content_screening_status():
        args = _query({"scope_type", "scope_id", "document_id"})
        scope_type = args.get("scope_type")
        scope_id = normalize_identifier(args.get("scope_id"), "scope_id")
        document_id = normalize_identifier(args.get("document_id"), "document_id")
        actor = _actor_id()
        assert_scope_access(actor, scope_type, scope_id, review=False)
        page = _repository().query_documents(
            scope_type, scope_id, document_ids=[document_id], page_size=1,
        )
        if not page["items"]:
            raise ScreeningNotFoundError()
        document = page["items"][0]
        subject = subject_from_document(document)
        if subject.scope_type != scope_type or subject.scope_id != scope_id or subject.document_id != document_id:
            raise ScreeningPermissionError()
        summary = public_screening_summary(document) or {
            "state": "not_enrolled", "available": True, "finding_count": 0,
        }
        can_review = False
        try:
            assert_scope_access(actor, scope_type, scope_id)
            can_review = bool(summary.get("review_id"))
        except ScreeningPermissionError:
            pass
        return jsonify({
            "document_id": document_id, **summary, "can_review": can_review,
            "review_url": (
                f"/content-review?scope_type={scope_type}&scope_id={quote(scope_id, safe='')}"
                f"&scan_id={quote(summary['scan_id'], safe='')}"
            )
            if can_review and summary.get("scan_id") else None,
        })
