# functions_m365_pending_review.py
"""Owner-only manual delivery editing and durable, field-constrained AI suggestions.

Implemented in: 0.261.325. Calendar edits are local; email edits patch the actual
Outlook draft. An edit claim prevents approval during a Graph/Cosmos partial save.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import re
import uuid
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from azure.core import MatchConditions
from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError

from cosmos_document_utils import normalize_cosmos_document
from functions_assist_submissions import SubmissionIdError, normalize_submission_id
from functions_editor_assist import EditorAssistError, parse_editor_assist_request, run_editor_assist
import functions_m365_pending_delivery as delivery
from functions_m365_approvals import M365PolicyError, material_fingerprint
from functions_m365_review_history import clear_review_history, commit_review_history, read_review_history
from functions_m365_transport import M365ProviderError


MAIL_FIELDS = frozenset({
    "subject", "body", "content_type", "to_recipients", "cc_recipients", "bcc_recipients",
})
CALENDAR_FIELDS = frozenset({
    "subject", "body", "content_type", "attendee_recipients", "start_datetime",
    "end_datetime", "timezone", "location", "teams_meeting_requested",
})
EDIT_LEASE_SECONDS = 600
_EMAIL = re.compile(r"^[^\s@<>,;:]+@[^\s@<>,;:]+\.[^\s@<>,;:]+$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Graph accepts Windows names as well as IANA zones. Do not accept arbitrary strings.
_WINDOWS_ZONES = {
    "Dateline Standard Time": "Etc/GMT+12", "UTC-11": "Etc/GMT+11",
    "Aleutian Standard Time": "America/Adak", "Hawaiian Standard Time": "Pacific/Honolulu",
    "Marquesas Standard Time": "Pacific/Marquesas", "Alaskan Standard Time": "America/Anchorage",
    "UTC-09": "Etc/GMT+9", "UTC-08": "Etc/GMT+8",
    "Pacific Standard Time (Mexico)": "America/Tijuana",
    "UTC": "UTC", "Pacific Standard Time": "America/Los_Angeles",
    "Mountain Standard Time": "America/Denver", "US Mountain Standard Time": "America/Phoenix",
    "Mountain Standard Time (Mexico)": "America/Mazatlan",
    "Yukon Standard Time": "America/Whitehorse",
    "Central America Standard Time": "America/Guatemala",
    "Central Standard Time": "America/Chicago", "Eastern Standard Time": "America/New_York",
    "Easter Island Standard Time": "Pacific/Easter", "Central Standard Time (Mexico)": "America/Mexico_City",
    "Canada Central Standard Time": "America/Regina", "SA Pacific Standard Time": "America/Bogota",
    "Eastern Standard Time (Mexico)": "America/Cancun", "Haiti Standard Time": "America/Port-au-Prince",
    "Cuba Standard Time": "America/Havana", "US Eastern Standard Time": "America/Indianapolis",
    "Turks And Caicos Standard Time": "America/Grand_Turk", "Paraguay Standard Time": "America/Asuncion",
    "Atlantic Standard Time": "America/Halifax", "Venezuela Standard Time": "America/Caracas",
    "Central Brazilian Standard Time": "America/Cuiaba", "SA Western Standard Time": "America/La_Paz",
    "Pacific SA Standard Time": "America/Santiago", "Newfoundland Standard Time": "America/St_Johns",
    "Tocantins Standard Time": "America/Araguaina", "E. South America Standard Time": "America/Sao_Paulo",
    "SA Eastern Standard Time": "America/Cayenne", "Argentina Standard Time": "America/Buenos_Aires",
    "Greenland Standard Time": "America/Godthab", "Montevideo Standard Time": "America/Montevideo",
    "Magallanes Standard Time": "America/Punta_Arenas", "Saint Pierre Standard Time": "America/Miquelon",
    "Bahia Standard Time": "America/Bahia", "UTC-02": "Etc/GMT+2",
    "Azores Standard Time": "Atlantic/Azores", "Cape Verde Standard Time": "Atlantic/Cape_Verde",
    "GMT Standard Time": "Europe/London", "W. Europe Standard Time": "Europe/Berlin",
    "Greenwich Standard Time": "Atlantic/Reykjavik", "Sao Tome Standard Time": "Africa/Sao_Tome",
    "Morocco Standard Time": "Africa/Casablanca", "Central Europe Standard Time": "Europe/Budapest",
    "Romance Standard Time": "Europe/Paris", "India Standard Time": "Asia/Kolkata",
    "Central European Standard Time": "Europe/Warsaw", "W. Central Africa Standard Time": "Africa/Lagos",
    "Jordan Standard Time": "Asia/Amman", "GTB Standard Time": "Europe/Bucharest",
    "Middle East Standard Time": "Asia/Beirut", "Egypt Standard Time": "Africa/Cairo",
    "E. Europe Standard Time": "Europe/Chisinau", "Syria Standard Time": "Asia/Damascus",
    "West Bank Standard Time": "Asia/Hebron", "South Africa Standard Time": "Africa/Johannesburg",
    "FLE Standard Time": "Europe/Kyiv", "Israel Standard Time": "Asia/Jerusalem",
    "South Sudan Standard Time": "Africa/Juba", "Kaliningrad Standard Time": "Europe/Kaliningrad",
    "Sudan Standard Time": "Africa/Khartoum", "Libya Standard Time": "Africa/Tripoli",
    "Namibia Standard Time": "Africa/Windhoek", "Arabic Standard Time": "Asia/Baghdad",
    "Turkey Standard Time": "Europe/Istanbul", "Arab Standard Time": "Asia/Riyadh",
    "Belarus Standard Time": "Europe/Minsk", "Russian Standard Time": "Europe/Moscow",
    "E. Africa Standard Time": "Africa/Nairobi", "Volgograd Standard Time": "Europe/Volgograd",
    "Iran Standard Time": "Asia/Tehran", "Arabian Standard Time": "Asia/Dubai",
    "Astrakhan Standard Time": "Europe/Astrakhan", "Azerbaijan Standard Time": "Asia/Baku",
    "Russia Time Zone 3": "Europe/Samara", "Mauritius Standard Time": "Indian/Mauritius",
    "Saratov Standard Time": "Europe/Saratov", "Georgian Standard Time": "Asia/Tbilisi",
    "Caucasus Standard Time": "Asia/Yerevan", "Afghanistan Standard Time": "Asia/Kabul",
    "West Asia Standard Time": "Asia/Tashkent", "Ekaterinburg Standard Time": "Asia/Yekaterinburg",
    "Pakistan Standard Time": "Asia/Karachi", "Qyzylorda Standard Time": "Asia/Qyzylorda",
    "Sri Lanka Standard Time": "Asia/Colombo", "Nepal Standard Time": "Asia/Kathmandu",
    "Central Asia Standard Time": "Asia/Almaty", "Bangladesh Standard Time": "Asia/Dhaka",
    "Omsk Standard Time": "Asia/Omsk", "Myanmar Standard Time": "Asia/Yangon",
    "SE Asia Standard Time": "Asia/Bangkok", "Altai Standard Time": "Asia/Barnaul",
    "W. Mongolia Standard Time": "Asia/Hovd", "North Asia Standard Time": "Asia/Krasnoyarsk",
    "N. Central Asia Standard Time": "Asia/Novosibirsk", "Tomsk Standard Time": "Asia/Tomsk",
    "China Standard Time": "Asia/Shanghai", "Tokyo Standard Time": "Asia/Tokyo",
    "North Asia East Standard Time": "Asia/Irkutsk", "Singapore Standard Time": "Asia/Singapore",
    "W. Australia Standard Time": "Australia/Perth", "Taipei Standard Time": "Asia/Taipei",
    "Ulaanbaatar Standard Time": "Asia/Ulaanbaatar", "Aus Central W. Standard Time": "Australia/Eucla",
    "Transbaikal Standard Time": "Asia/Chita", "North Korea Standard Time": "Asia/Pyongyang",
    "Korea Standard Time": "Asia/Seoul", "Yakutsk Standard Time": "Asia/Yakutsk",
    "Cen. Australia Standard Time": "Australia/Adelaide", "AUS Central Standard Time": "Australia/Darwin",
    "E. Australia Standard Time": "Australia/Brisbane", "West Pacific Standard Time": "Pacific/Port_Moresby",
    "Tasmania Standard Time": "Australia/Hobart", "Vladivostok Standard Time": "Asia/Vladivostok",
    "Lord Howe Standard Time": "Australia/Lord_Howe", "Bougainville Standard Time": "Pacific/Bougainville",
    "Russia Time Zone 10": "Asia/Srednekolymsk", "Magadan Standard Time": "Asia/Magadan",
    "Norfolk Standard Time": "Pacific/Norfolk", "Sakhalin Standard Time": "Asia/Sakhalin",
    "Central Pacific Standard Time": "Pacific/Guadalcanal", "Russia Time Zone 11": "Asia/Kamchatka",
    "New Zealand Standard Time": "Pacific/Auckland", "UTC+12": "Etc/GMT-12",
    "Fiji Standard Time": "Pacific/Fiji", "Chatham Islands Standard Time": "Pacific/Chatham",
    "UTC+13": "Etc/GMT-13", "Tonga Standard Time": "Pacific/Tongatapu",
    "Samoa Standard Time": "Pacific/Apia", "Line Islands Standard Time": "Pacific/Kiritimati",
    "AUS Eastern Standard Time": "Australia/Sydney",
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _fail(code, message):
    raise M365PolicyError(code, message)


def _read_owned(container, user_id, action_id, *, editable=False):
    if not isinstance(user_id, str) or not user_id or not isinstance(action_id, str) or not 1 <= len(action_id) <= 256:
        raise ValueError("Invalid action identity.")
    try:
        action = normalize_cosmos_document(container.read_item(action_id, partition_key=user_id))
    except CosmosResourceNotFoundError:
        raise LookupError("Action not found.") from None
    if action.get("type") != "msgraph_pending_action" or action.get("user_id") != user_id:
        raise LookupError("Action not found.")
    if not delivery.authorize_pending_action_view(action, user_id):
        raise PermissionError("Action is unavailable.")
    if editable:
        if action.get("action_mode") != "manual" or action.get("status") not in {"pending", "review_required"}:
            _fail("pending_action_changed", "This action is not editable. Refresh its current status.")
        if not delivery.has_verified_delivery_binding(action):
            _fail("m365_action_review_required", "Prepare a new action with its original authorized context.")
        if action.get("review_sync_required"):
            _fail("pending_action_changed", "Refresh the Outlook draft before editing or sending.")
        if action["material_fingerprint"] != delivery.pending_delivery_fingerprint(action):
            _fail("m365_action_material_changed", "The saved review changed. Refresh the action.")
    return action


def _check_version(action, version):
    if not isinstance(version, str) or not 1 <= len(version) <= 256:
        raise ValueError("An action revision is required.")
    if version != action["_etag"]:
        _fail("pending_action_changed", "This action changed. Reload the editor before saving.")


def _addresses(recipients):
    return [item["emailAddress"]["address"] for item in recipients or []]


def review_fields(action):
    payload = action["graph_payload"]
    mail = action["operation"] == "send_mail"
    payload = payload["message"] if mail else payload
    fields = {
        "subject": payload.get("subject", ""),
        "body": (payload.get("body") or {}).get("content", ""),
        "content_type": (payload.get("body") or {}).get("contentType", "Text"),
    }
    if mail:
        fields.update({
            "to_recipients": _addresses(payload.get("toRecipients")),
            "cc_recipients": _addresses(payload.get("ccRecipients")),
            "bcc_recipients": _addresses(payload.get("bccRecipients")),
        })
    else:
        fields.update({
            "attendee_recipients": _addresses(payload.get("attendees")),
            "start_datetime": (payload.get("start") or {}).get("dateTime", ""),
            "end_datetime": (payload.get("end") or {}).get("dateTime", ""),
            "timezone": (payload.get("start") or {}).get("timeZone", "UTC"),
            "location": (payload.get("location") or {}).get("displayName", ""),
            "teams_meeting_requested": payload.get("isOnlineMeeting") is True,
        })
    return fields


def _text(value, max_length, *, required=False, multiline=False):
    if not isinstance(value, str) or len(value) > max_length or _CONTROL.search(value):
        raise ValueError("Invalid field text.")
    if not multiline and any(char in value for char in "\r\n\t"):
        raise ValueError("Invalid field text.")
    if required and not value.strip():
        raise ValueError("A required field is empty.")
    return value if multiline else value.strip()


def _recipients(value, *, required=False):
    if not isinstance(value, list) or len(value) > 100 or (required and not value):
        raise ValueError("Invalid recipients.")
    result = []
    for address in value:
        address = _text(address, 254, required=True)
        if not _EMAIL.fullmatch(address):
            raise ValueError("Invalid email address.")
        if address.casefold() not in {item.casefold() for item in result}:
            result.append(address)
    return result


def validate_fields(action, edits):
    allowed = MAIL_FIELDS if action["operation"] == "send_mail" else CALENDAR_FIELDS
    if not isinstance(edits, dict) or not edits or set(edits) - allowed:
        raise ValueError("Unsupported review fields.")
    fields = {**review_fields(action), **deepcopy(edits)}
    fields["subject"] = _text(fields["subject"], 500, required=True)
    fields["body"] = _text(fields["body"], 50000, multiline=True)
    if fields["content_type"] not in {"Text", "HTML"}:
        raise ValueError("Invalid content type.")
    if action["operation"] == "send_mail":
        for key in ("to_recipients", "cc_recipients", "bcc_recipients"):
            fields[key] = _recipients(fields[key], required=key == "to_recipients")
    else:
        fields["attendee_recipients"] = _recipients(fields["attendee_recipients"], required=True)
        fields["location"] = _text(fields["location"], 500)
        fields["timezone"] = _text(fields["timezone"], 100, required=True)
        try:
            zone = ZoneInfo(_WINDOWS_ZONES.get(fields["timezone"], fields["timezone"]))
        except ZoneInfoNotFoundError:
            raise ValueError("Unsupported timezone.") from None
        dates = []
        for key in ("start_datetime", "end_datetime"):
            fields[key] = _text(fields[key], 64, required=True)
            value = datetime.fromisoformat(fields[key].replace("Z", "+00:00"))
            local = value.replace(tzinfo=zone) if value.tzinfo is None else value
            # Reject nonexistent wall times instead of silently shifting the invitation.
            if value.tzinfo is None and local.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != value:
                raise ValueError("This local time does not exist in the selected timezone.")
            if value.tzinfo is not None:
                fields[key] = local.astimezone(zone).replace(tzinfo=None).isoformat()
            dates.append(local.astimezone(timezone.utc))
        if dates[1] <= dates[0]:
            raise ValueError("The event must end after it starts.")
        if type(fields["teams_meeting_requested"]) is not bool:
            raise ValueError("Invalid online meeting option.")
    # Two complete revision snapshots must fit below Cosmos's 2 MiB document limit.
    if len(json.dumps(fields, ensure_ascii=True).encode()) > 750000:
        raise ValueError("The complete review material is too large.")
    return fields


def _payload(action, fields):
    payload = deepcopy(action["graph_payload"])
    mail = action["operation"] == "send_mail"
    target = payload["message"] if mail else payload
    target.update(subject=fields["subject"], body={
        "content": fields["body"], "contentType": fields["content_type"],
    })
    if mail:
        for field, key in (("to_recipients", "toRecipients"), ("cc_recipients", "ccRecipients"), ("bcc_recipients", "bccRecipients")):
            target[key] = [{"emailAddress": {"address": address}} for address in fields[field]]
    else:
        old = {item["emailAddress"]["address"].casefold(): item for item in target.get("attendees", [])}
        target["attendees"] = [
            deepcopy(old[address.casefold()]) if address.casefold() in old else {
                "emailAddress": {"address": address}, "type": "required",
            } for address in fields["attendee_recipients"]
        ]
        target["start"] = {"dateTime": fields["start_datetime"], "timeZone": fields["timezone"]}
        target["end"] = {"dateTime": fields["end_datetime"], "timeZone": fields["timezone"]}
        target["location"] = {"displayName": fields["location"]}
        target["isOnlineMeeting"] = fields["teams_meeting_requested"]
        if fields["teams_meeting_requested"]:
            target["onlineMeetingProvider"] = "teamsForBusiness"
        else:
            target.pop("onlineMeetingProvider", None)
    return payload


def _with_material(action, fields):
    updated = {**action, "graph_payload": _payload(action, fields), "updated_at": _now()}
    # The browser summary is a projection, not the source for saved review fields.
    updated["summary"] = {**fields, "body_preview": fields["body"]}
    updated["summary"].pop("body", None)
    if action["operation"] == "send_mail":
        updated["summary"]["bcc_recipient_count"] = len(fields["bcc_recipients"])
    updated["material_fingerprint"] = delivery.pending_delivery_fingerprint(updated)
    return updated


def history_page(container, action, *, cursor="", limit=20):
    if type(limit) is not int or not 1 <= limit <= 40 or not isinstance(cursor, str) or len(cursor) > 100:
        raise ValueError("Invalid history page.")
    if action.get("status") in {"sent", "cancelled", "failed", "recovery_required"}:
        return {"items": [], "next_cursor": ""}
    record = read_review_history(container, action)
    items = list(reversed(record["items"])) if record else []
    if cursor:
        positions = [index for index, item in enumerate(items) if item["id"] == cursor]
        if not positions:
            raise ValueError("History page expired. Reload history.")
        items = items[positions[0] + 1:]
    page = items[:limit]
    return {"items": page, "next_cursor": page[-1]["id"] if len(items) > limit else ""}


def get_pending_review(container, user_id, action_id, *, cursor="", limit=20):
    action = _read_owned(container, user_id, action_id)
    if action.get("status") in {"sent", "cancelled", "failed", "recovery_required"}:
        clear_review_history(container, action)
    if action["operation"] == "send_mail" and action.get("status") in {"pending", "review_required", "editing"} and action.get("action_mode") == "manual":
        action = refresh_review_draft(container, action)
    return {"action": action, "fields": review_fields(action), "history": history_page(container, action, cursor=cursor, limit=limit)}


def _draft_headers(action):
    return {"Prefer": 'IdType="ImmutableId"'} if action.get("graph_send_strategy") == "draft_send_v1" else {}


def _read_draft(transport, action):
    draft = transport.request_json(
        "GET", f"/v1.0/me/messages/{quote(action['graph_message_id'], safe='')}", ["Mail.ReadWrite"],
        params={"$select": "id,changeKey,isDraft,subject,body,toRecipients,ccRecipients,bccRecipients,webLink"},
        additional_headers=_draft_headers(action),
    )
    if not isinstance(draft, dict) or draft.get("isDraft") is not True or not isinstance(draft.get("changeKey"), str) or not draft["changeKey"]:
        _fail("m365_action_material_changed", "The Outlook message is no longer an editable draft.")
    return draft


def _sync_draft(container, action, draft):
    material = {**action, "graph_payload": {**action["graph_payload"], "message": {
        key: deepcopy(draft[key]) for key in ("subject", "body", "toRecipients", "ccRecipients", "bccRecipients") if key in draft
    }}}
    fields = review_fields(material)
    updated = _with_material(material, fields)
    updated.update(
        graph_draft_version=draft["changeKey"], web_link=draft.get("webLink", action.get("web_link", "")),
        status="pending", review_sync_required=False, review_edit_expires_at=None,
        error="", error_code="",
    )
    updated["material_fingerprint"] = delivery.pending_delivery_fingerprint(updated)
    return commit_review_history(container, action, updated, {
        "id": str(uuid.uuid4()), "kind": "revision", "origin": "outlook",
        "created_at": _now(), "fields": fields, "from_fields": review_fields(action),
        "saved": True, "applied": True,
    })


def refresh_review_draft(container, action):
    expires = action.get("review_edit_expires_at")
    if action.get("status") == "editing" and expires and datetime.fromisoformat(expires) > datetime.now(timezone.utc):
        return action
    with delivery._dependencies["context_scope"](action, automatic=False):
        transport = delivery._dependencies["transport_factory"]("email", action["m365_execution"]["action_id"])
        with transport.operation_context("send_mail"):
            draft = _read_draft(transport, action)
    if draft["changeKey"] != action.get("graph_draft_version") or action.get("review_sync_required") or action.get("status") == "editing":
        return _sync_draft(container, action, draft)
    return action


def save_pending_review(container, user_id, action_id, *, expected_version, fields, origin="direct", assist_turn_id=None):
    action = _read_owned(container, user_id, action_id, editable=True)
    _check_version(action, expected_version)
    if origin not in {"direct", "ai"} or (assist_turn_id is not None and (not isinstance(assist_turn_id, str) or len(assist_turn_id) > 100)):
        raise ValueError("Invalid edit attribution.")
    checked = validate_fields(action, fields)
    if assist_turn_id:
        history = read_review_history(container, action)
        if not history or not any(item["id"] == assist_turn_id and item["kind"] == "assist" for item in history["items"]):
            raise ValueError("Unknown assistant turn.")
    updated = _with_material(action, checked)
    delivery.check_pending_delivery_content(updated)
    claimed = action
    if action["operation"] == "send_mail":
        claimed = normalize_cosmos_document(container.replace_item(
            action_id, body={**action, "status": "editing", "review_sync_required": True,
                             "review_edit_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=EDIT_LEASE_SECONDS)).isoformat()},
            etag=action["_etag"], match_condition=MatchConditions.IfNotModified,
        ))
        try:
            with delivery._dependencies["context_scope"](action, automatic=False):
                transport = delivery._dependencies["transport_factory"]("email", action["m365_execution"]["action_id"])
                with transport.operation_context("send_mail"):
                    draft = _read_draft(transport, action)
                    if draft["changeKey"] != action.get("graph_draft_version"):
                        _sync_draft(container, claimed, draft)
                        _fail("pending_action_changed", "The Outlook draft changed. Review the refreshed content before saving.")
                    # Graph ETag guards only this PATCH. Approval sends the actual current draft.
                    graph_etag = draft.get("@odata.etag") or f'W/"{draft["changeKey"]}"'
                    result = transport.request_json(
                        "PATCH", f"/v1.0/me/messages/{quote(action['graph_message_id'], safe='')}", ["Mail.ReadWrite"],
                        json_body=updated["graph_payload"]["message"],
                        additional_headers={**_draft_headers(action), "If-Match": graph_etag},
                    )
                    if not isinstance(result, dict) or not isinstance(result.get("changeKey"), str) or not result["changeKey"]:
                        raise M365ProviderError("incomplete_response", "Refresh the Outlook draft before continuing.")
                    updated.update(graph_draft_version=result["changeKey"], web_link=result.get("webLink", draft.get("webLink", "")))
        except (M365PolicyError, M365ProviderError, AzureError, PermissionError, LookupError, ValueError):
            # If Graph succeeded but Cosmos did not, the durable claim stays non-sendable.
            latest = _read_owned(container, user_id, action_id)
            if latest["_etag"] == claimed["_etag"]:
                container.replace_item(
                    action_id, body={**latest, "status": "review_required", "review_sync_required": True, "review_edit_expires_at": None},
                    etag=latest["_etag"], match_condition=MatchConditions.IfNotModified,
                )
            raise
    updated.update(status="pending", review_sync_required=False, review_edit_expires_at=None, error="", error_code="")
    updated["material_fingerprint"] = delivery.pending_delivery_fingerprint(updated)
    try:
        saved = commit_review_history(container, claimed, updated, {
            "id": str(uuid.uuid4()), "kind": "revision", "origin": origin,
            "assist_turn_id": assist_turn_id, "created_at": _now(), "fields": checked,
            "from_fields": review_fields(action), "saved": True, "applied": True,
        })
    except AzureError:
        if action["operation"] == "send_mail":
            try:
                container.replace_item(
                    action_id, body={**claimed, "status": "review_required", "review_sync_required": True, "review_edit_expires_at": None},
                    etag=claimed["_etag"], match_condition=MatchConditions.IfNotModified,
                )
            except AzureError as error:
                # A lost response may mean the batch committed. Never overwrite its newer revision.
                delivery._dependencies["log_event"](
                    "[MS_GRAPH_PENDING_ACTIONS] Draft save recovery marker could not be recorded.",
                    {"action_id": action_id, "exception_type": type(error).__name__},
                )
        raise
    return {"action": saved, "fields": checked, "history": history_page(container, saved)}


def assist_pending_review(container, user_id, action_id, body, *, services):
    action = _read_owned(container, user_id, action_id, editable=True)
    required = {"submission_id", "instruction", "fields", "expected_version"}
    if not isinstance(body, dict) or not required <= set(body) or set(body) - required - {"conversation"}:
        raise ValueError("Invalid assistant request.")
    fields = validate_fields(action, body.get("fields"))
    existing = read_review_history(container, action)
    try:
        submission = normalize_submission_id(body["submission_id"])
    except SubmissionIdError:
        raise EditorAssistError("invalid_request") from None
    if not submission:
        raise EditorAssistError("invalid_request")
    request_fingerprint = material_fingerprint({"instruction": body["instruction"], "fields": fields})
    if existing:
        repeated = next((item for item in existing["items"] if item.get("submission_id") == submission), None)
        if repeated:
            if repeated.get("request_fingerprint") != request_fingerprint:
                _fail("pending_action_changed", "This assistant submission already belongs to different review material.")
            candidate = repeated.get("candidate_fields")
            return {
                "submission_id": submission, "outcome": repeated["outcome"], "reply": repeated["reply"],
                "candidate_fields": candidate,
                "candidate": {"values": {f"/{key}": value for key, value in candidate.items()}, "new_items": []} if candidate else None,
                "changes": [], "warnings": repeated.get("warnings", []),
                "action": action, "assist_turn_id": repeated["id"], "history": history_page(container, action),
            }
    _check_version(action, body.get("expected_version"))
    descriptors = []
    for name, value in fields.items():
        if name == "content_type":
            descriptor = {"kind": "select", "options": [{"value": item, "label": item} for item in ("Text", "HTML")]}
        elif isinstance(value, list):
            descriptor = {"kind": "lines", "max_items": 100, "max_length": 254}
        elif isinstance(value, bool):
            descriptor = {"kind": "boolean"}
        else:
            descriptor = {"kind": "textarea" if name == "body" else "text", "max_length": 50000 if name == "body" else 500}
        descriptors.append({"path": f"/{name}", "label": name.replace("_", " ").title(), **descriptor})
    # Only the bounded durable thread feeds the model, never giant action documents.
    conversation = []
    for item in (existing["items"] if existing else []):
        if item["kind"] == "assist":
            conversation.extend([{"role": "user", "text": item["instruction"]}, {"role": "assistant", "text": item["reply"]}])
    core_body = {
        "submission_id": submission, "instruction": body.get("instruction"),
        "fields": descriptors, "values": {f"/{key}": value for key, value in fields.items()},
        "conversation": body.get("conversation"),
    }
    kind = "pending_email" if action["operation"] == "send_mail" else "pending_calendar"
    # Validate optional browser thread limits too, but only durable owned turns enter model context.
    parse_editor_assist_request(core_body, kind=kind, scope="personal")
    core_body["conversation"] = conversation[-20:]
    result = run_editor_assist(core_body, kind=kind, scope="personal", user_id=user_id, services=services)
    candidate = result.get("candidate")
    if candidate:
        proposed = {key.removeprefix("/"): value for key, value in candidate["values"].items()}
        try:
            result["candidate_fields"] = validate_fields(action, proposed)
        except ValueError:
            raise EditorAssistError("assistant_output_invalid") from None
    latest = _read_owned(container, user_id, action_id, editable=True)
    _check_version(latest, action["_etag"])
    turn_id = str(uuid.uuid4())
    saved = commit_review_history(container, latest, {**latest, "updated_at": _now()}, {
        "id": turn_id, "kind": "assist", "origin": "ai", "submission_id": submission,
        "request_fingerprint": request_fingerprint,
        "instruction": body["instruction"], "reply": result["reply"], "outcome": result["outcome"],
        "from_fields": fields, "warnings": result["warnings"],
        "candidate_fields": result.get("candidate_fields"), "expected_version": body["expected_version"],
        "created_at": _now(), "saved": False, "applied": False,
    })
    return {**result, "action": saved, "assist_turn_id": turn_id, "history": history_page(container, saved)}
