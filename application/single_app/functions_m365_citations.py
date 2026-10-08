# functions_m365_citations.py
"""Microsoft 365 emails, calendar events and files as first-class answer citations.

Version: 0.261.303
Implemented in: 0.261.303

An item an answer draws on is normalized into a small citation record with a deterministic id.
Tool results carry a model-facing citation value in SimpleChat's inline marker grammar,
``(Source: <title>, Location: <where>) [#<id>]``, so the model cites an email, event or file the
same way it cites a workspace document. The records travel with the assistant message and the
conversation, so the browser draws citation chips, source cards and "Open online" links without
calling Microsoft 365 again.

Rules every record follows:

* Records come only from the Microsoft 365 plugins. Their annotators return an
  :class:`M365CitedResult` that carries the records made from Microsoft Graph data, and the plugin
  invocation logger keeps exactly those. Nothing rebuilds a record from the shape of a tool result,
  because any other tool (an HTTP fetch, an OpenAPI or MCP action) can return look-alike JSON.
* A link is only ever a Microsoft Graph ``webLink``/``webUrl`` that is ``https``; model text never
  supplies one.
* Records hold bounded metadata: no message bodies, file content or excerpts. An email keeps at
  most a 280-character preview.
* Ids are ``m365-`` plus 16 hex characters and contain no underscore, because both browsers split
  workspace citation ids at their last underscore.

This module is dependency-light on purpose: it is imported by the plugin invocation logger, the
citation tracker and the chat routes, so it must not import configuration or storage. It loads
application logging only on the failure path that reports an item it could not cite.
"""

import hashlib
import logging
import re
from collections import OrderedDict
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import g, has_request_context

import functions_m365_context as m365_context


M365_CITATION_ID_PREFIX = "m365-"
M365_CITATION_KINDS = ("file", "email", "event")
M365_FILE_SOURCES = ("spo", "onedrive")
M365_FILE_READ_OPERATIONS = frozenset({"prepare_file", "read_file", "read_file_chunk", "analyze_file"})
M365_GATHER_CAPABILITIES = frozenset({"action_invoke", "agent_invoke"})
MAX_MESSAGE_M365_CITATIONS = 100
# Records gathered for one answer before the cited ones are chosen; a bound, not a display limit.
MAX_COLLECTED_M365_RECORDS = 1000
MAX_RESULT_M365_RECORDS = 200
MAX_CONVERSATION_M365_ITEMS = 200
MAX_ITEM_MESSAGE_IDS = 20
MAX_MARKER_TITLE_CHARS = 120
MAX_SOURCES_NOTE_ITEMS = 50

M365_CITATION_INSTRUCTIONS = (
    'Cite each email, event or file you mention by copying its "citation" value verbatim right '
    'after the line or sentence about it. Do not invent, shorten, reformat or renumber citation '
    'values, and do not cite an item you did not use.'
)

_LOCATION_LABELS = {
    "spo": "SharePoint",
    "onedrive": "OneDrive",
    "email": "Email",
    "calendar": "Calendar",
}
_KIND_SOURCES = {
    "file": frozenset(M365_FILE_SOURCES),
    "email": frozenset({"email"}),
    "event": frozenset({"calendar"}),
}
_CITATION_ID_RE = re.compile(r"m365-[0-9a-f]{16}")
_CITATION_GROUP_RE = re.compile(r"\[\s{0,8}#([^\]\r\n]{1,1024})\]")
_TIME_ZONE_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+\-]{0,30}(?:/[A-Za-z0-9_+\-]{1,30}){0,3}")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")
_WHITESPACE_RE = re.compile(r"\s+")
_MARKER_LOCATION_RE = re.compile(r",(\s*(?:pages?|sheets?|location)\s*:)", re.IGNORECASE)
_GRAPH_FRACTION_RE = re.compile(r"(\.\d{6})\d+")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_FIELD_LIMITS = {
    "title": 300,
    "file_name": 255,
    "mime_type": 128,
    "location_label": 32,
    "from_name": 200,
    "from_address": 320,
    "received_display": 80,
    "importance": 16,
    "preview": 280,
    "when_display": 120,
    "location": 200,
    "organizer_name": 200,
    "modified_display": 40,
    "time_zone": 64,
    "data_user_id": 256,
}
_TEXT_FIELDS = {
    "file": ("title", "file_name", "mime_type", "location_label", "modified_display"),
    "email": ("title", "location_label", "from_name", "from_address", "received_display", "importance", "preview"),
    "event": ("title", "location_label", "when_display", "time_zone", "location", "organizer_name"),
}
_TIME_FIELDS = {
    "file": ("modified_at",),
    "email": ("received_at",),
    "event": ("start", "end"),
}

_display_time_zone = ContextVar("m365_display_time_zone", default=None)


# --------------------------------------------------------------------------------------
# Small, total helpers
# --------------------------------------------------------------------------------------

def _single_line(value, limit):
    """A bounded one-line string with control characters and runs of whitespace collapsed."""
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    text = _WHITESPACE_RE.sub(" ", _CONTROL_RE.sub(" ", str(value))).strip()
    if len(text) > limit:
        text = text[: max(1, limit - 1)].rstrip() + "\u2026"
    return text


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def safe_https_url(value):
    """``value`` when it is an absolute https URL without credentials or whitespace, else ''."""
    if not isinstance(value, str):
        return ""
    url = value.strip()
    if not url or len(url) > 2048 or _CONTROL_RE.search(url) or " " in url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    if parts.scheme.lower() != "https" or not parts.netloc or "@" in parts.netloc:
        return ""
    return url


def m365_citation_id(source, key):
    """The deterministic citation id for one item: ``m365-`` and 16 hex characters."""
    digest = hashlib.sha256(f"{source}\x00{key}".encode("utf-8")).hexdigest()
    return f"{M365_CITATION_ID_PREFIX}{digest[:16]}"


def is_m365_citation_id(value):
    return isinstance(value, str) and _CITATION_ID_RE.fullmatch(value) is not None


def m365_location_label(source):
    return _LOCATION_LABELS.get(source, "Microsoft 365")


def sanitize_marker_title(value, fallback="Microsoft 365 item"):
    """A title that the v2 and classic inline-citation grammars both parse back intact.

    Newlines end a marker, a nested ``(Source:`` restarts one, square brackets open the id list,
    and ``, Location:`` (or ``, Page:``/``, Sheet:``) inside the title would end the title early, so
    each is removed or defused. The result is bounded for the model and the chip.
    """
    text = _single_line(value, 2048)
    text = re.sub(r"\(\s*source\s*:", "(", text, flags=re.IGNORECASE)
    text = text.replace("[", "").replace("]", "")
    text = _MARKER_LOCATION_RE.sub(r";\1", text)
    text = _single_line(text, MAX_MARKER_TITLE_CHARS)
    return text or fallback


def build_m365_citation_marker(record):
    """``(Source: <title>, Location: <where>) [#<id>]`` for one normalized record."""
    title = sanitize_marker_title(record.get("title") or record.get("file_name"))
    label = record.get("location_label") or m365_location_label(record.get("source"))
    return f"(Source: {title}, Location: {label}) [#{record['citation_id']}]"


# --------------------------------------------------------------------------------------
# Display time zone
# --------------------------------------------------------------------------------------

def validate_m365_display_time_zone(value):
    """An exact IANA time zone name the server can load, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > 64 or not _TIME_ZONE_NAME_RE.fullmatch(text):
        return None
    try:
        ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None
    return text


def set_request_m365_display_time_zone(value):
    """Remember the browser's time zone for this request's Microsoft 365 display strings."""
    zone = validate_m365_display_time_zone(value)
    if has_request_context():
        g.m365_display_time_zone = zone
    return zone


@contextmanager
def m365_display_time_zone(value):
    """Use ``value`` for Microsoft 365 display strings inside the block, for worker execution."""
    token = _display_time_zone.set(validate_m365_display_time_zone(value))
    try:
        yield
    finally:
        _display_time_zone.reset(token)


def get_m365_display_time_zone():
    """The validated display zone for the current execution, or None for UTC."""
    zone = _display_time_zone.get()
    if zone:
        return zone
    if has_request_context():
        return validate_m365_display_time_zone(getattr(g, "m365_display_time_zone", None))
    return None


def _zone(display_time_zone):
    name = validate_m365_display_time_zone(display_time_zone)
    return (ZoneInfo(name), name) if name else (timezone.utc, "UTC")


def _parse_graph_datetime(value):
    """An aware UTC datetime from a Graph timestamp or ``{dateTime, timeZone}`` value, or None."""
    zone_name = ""
    if isinstance(value, Mapping):
        zone_name = str(value.get("timeZone") or "").strip()
        value = value.get("dateTime")
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        return None
    text = value.strip()
    if text[-1] in "Zz":
        text = f"{text[:-1]}+00:00"
    text = _GRAPH_FRACTION_RE.sub(r"\1", text)
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            source_zone = timezone.utc
            if zone_name and zone_name.upper() not in ("UTC", "Z", "COORDINATED UNIVERSAL TIME"):
                loaded = validate_m365_display_time_zone(zone_name)
                if loaded is None:
                    return None
                source_zone = ZoneInfo(loaded)
            parsed = parsed.replace(tzinfo=source_zone)
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError, OSError):
        # Graph uses 0001-01-01 for unset times; an offset can push such a value out of range.
        return None


def _in_zone(moment, zone):
    """``moment`` in ``zone``, or None when the shift leaves the representable date range."""
    try:
        return moment.astimezone(zone)
    except (ValueError, OverflowError, OSError):
        return None


def _iso_utc(value):
    moment = _in_zone(value, timezone.utc) if value else None
    if moment is None:
        return ""
    return (
        f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d}"
        f"T{moment.hour:02d}:{moment.minute:02d}:{moment.second:02d}Z"
    )


def _clock(value):
    hour = value.hour % 12 or 12
    return f"{hour}:{value.minute:02d} {'AM' if value.hour < 12 else 'PM'}"


def _date_label(value, *, weekday=False):
    text = f"{_MONTHS[value.month - 1]} {value.day}, {value.year}"
    return f"{_WEEKDAYS[value.weekday()]}, {text}" if weekday else text


def _zone_label(value):
    try:
        abbreviation = value.tzname() or ""
        offset = value.utcoffset() or timedelta(0)
    except (ValueError, OverflowError):
        return "UTC"
    if abbreviation and abbreviation[0] not in "+-":
        return abbreviation
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, remainder = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours}" + (f":{remainder:02d}" if remainder else "")


def format_m365_received(value, display_time_zone=None):
    """``Oct 7, 2026, 12:52 PM EDT`` for a received or modified time, or ''."""
    moment = _parse_graph_datetime(value)
    local = _in_zone(moment, _zone(display_time_zone)[0]) if moment is not None else None
    if local is None:
        return ""
    return f"{_date_label(local)}, {_clock(local)} {_zone_label(local)}"


def format_m365_date(value, display_time_zone=None):
    """``Oct 7, 2026`` in the display zone, or ''."""
    moment = _parse_graph_datetime(value)
    local = _in_zone(moment, _zone(display_time_zone)[0]) if moment is not None else None
    return _date_label(local) if local is not None else ""


def _all_day_date(value):
    raw = value.get("dateTime") if isinstance(value, Mapping) else value
    if not isinstance(raw, str) or len(raw) < 10:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def format_m365_event_when(start, end, *, is_all_day=False, display_time_zone=None):
    """One readable span: ``Thu, Oct 8, 2026, 2:00 PM – 3:00 PM EDT`` or ``... · All day``."""
    if is_all_day:
        first = _all_day_date(start)
        if first is None:
            return ""
        last = _all_day_date(end)
        # An all-day event ends at the midnight after its last day.
        last = last - timedelta(days=1) if last and last > first else first
        if last == first:
            return f"{_date_label(first, weekday=True)} \u00b7 All day"
        return f"{_date_label(first, weekday=True)} \u2013 {_date_label(last, weekday=True)} \u00b7 All day"
    begins = _parse_graph_datetime(start)
    zone = _zone(display_time_zone)[0]
    local_start = _in_zone(begins, zone) if begins is not None else None
    if local_start is None:
        return ""
    ends = _parse_graph_datetime(end)
    local_end = _in_zone(ends, zone) if ends is not None and ends > begins else None
    text = f"{_date_label(local_start, weekday=True)}, {_clock(local_start)}"
    if local_end is not None:
        if local_end.date() == local_start.date():
            text = f"{text} \u2013 {_clock(local_end)}"
        else:
            text = f"{text} \u2013 {_date_label(local_end, weekday=True)}, {_clock(local_end)}"
    return f"{text} {_zone_label(local_start)}"


# --------------------------------------------------------------------------------------
# Normalizers: one Graph item to one bounded record
# --------------------------------------------------------------------------------------

def _email_address(value):
    address = _mapping(_mapping(value).get("emailAddress"))
    return (
        _single_line(address.get("name"), _FIELD_LIMITS["from_name"]),
        _single_line(address.get("address"), _FIELD_LIMITS["from_address"]),
    )


def normalize_m365_email(message, display_time_zone=None):
    """A citation record for one Graph mail message, or None when it has no id."""
    if not isinstance(message, Mapping):
        return None
    graph_id = message.get("id")
    if not isinstance(graph_id, str) or not graph_id.strip() or len(graph_id) > 1024:
        return None
    from_name, from_address = _email_address(message.get("from") or message.get("sender"))
    received = _parse_graph_datetime(message.get("receivedDateTime"))
    received_display = _single_line(message.get("received_display"), _FIELD_LIMITS["received_display"])
    if not received_display and received is not None:
        received_display = format_m365_received(message.get("receivedDateTime"), display_time_zone)
    is_read = message.get("isRead")
    record = {
        "citation_id": m365_citation_id("email", f"message:{graph_id.strip()}"),
        "kind": "email",
        "source": "email",
        "title": _single_line(message.get("subject"), _FIELD_LIMITS["title"]) or "(no subject)",
        "location_label": m365_location_label("email"),
        "from_name": from_name,
        "from_address": from_address,
        "received_at": _iso_utc(received),
        "received_display": received_display,
        "is_read": is_read if isinstance(is_read, bool) else None,
        "importance": _single_line(message.get("importance"), _FIELD_LIMITS["importance"]).lower(),
        "preview": _single_line(message.get("bodyPreview"), _FIELD_LIMITS["preview"]),
        "web_url": safe_https_url(message.get("webLink")),
    }
    return _drop_empty(record)


def normalize_m365_event(event, display_time_zone=None):
    """A citation record for one Graph calendar event, or None when it has no id."""
    if not isinstance(event, Mapping):
        return None
    graph_id = event.get("id")
    if not isinstance(graph_id, str) or not graph_id.strip() or len(graph_id) > 1024:
        return None
    is_all_day = event.get("isAllDay") is True
    _zone_info, zone_name = _zone(display_time_zone)
    when_display = _single_line(event.get("when_display"), _FIELD_LIMITS["when_display"]) or format_m365_event_when(
        event.get("start"), event.get("end"), is_all_day=is_all_day, display_time_zone=display_time_zone,
    )
    if is_all_day:
        first, last = _all_day_date(event.get("start")), _all_day_date(event.get("end"))
        start_text = first.isoformat() if first else ""
        end_text = last.isoformat() if last else ""
    else:
        start_text = _iso_utc(_parse_graph_datetime(event.get("start")))
        end_text = _iso_utc(_parse_graph_datetime(event.get("end")))
    organizer_name, organizer_address = _email_address(event.get("organizer"))
    record = {
        "citation_id": m365_citation_id("calendar", f"event:{graph_id.strip()}"),
        "kind": "event",
        "source": "calendar",
        "title": _single_line(event.get("subject"), _FIELD_LIMITS["title"]) or "(untitled event)",
        "location_label": m365_location_label("calendar"),
        "start": start_text,
        "end": end_text,
        "time_zone": zone_name,
        "is_all_day": is_all_day,
        "when_display": when_display,
        "location": _single_line(_mapping(event.get("location")).get("displayName"), _FIELD_LIMITS["location"]),
        "organizer_name": organizer_name or organizer_address,
        "web_url": safe_https_url(event.get("webLink")),
    }
    return _drop_empty(record)


def _file_modified_at(file_info):
    version = _mapping(file_info.get("captured_version"))
    for candidate in (
        version.get("last_modified"),
        _mapping(version.get("observed_metadata")).get("last_modified"),
        file_info.get("lastModifiedDateTime"),
        file_info.get("modified_at"),
    ):
        moment = _parse_graph_datetime(candidate)
        if moment is not None:
            return moment
    return None


def _file_name_from_url(url):
    path = urlsplit(url).path if url else ""
    return _single_line(unquote(path.rstrip("/").rsplit("/", 1)[-1]), _FIELD_LIMITS["file_name"]) if path else ""


def normalize_m365_file(file_info, source, display_time_zone=None, *, content_read=False):
    """A citation record for one normalized SharePoint or OneDrive file identity, or None."""
    if not isinstance(file_info, Mapping) or source not in M365_FILE_SOURCES:
        return None
    canonical = _mapping(file_info.get("canonical_id"))
    drive_id = file_info.get("drive_id") or canonical.get("drive_id")
    item_id = file_info.get("item_id") or canonical.get("item_id")
    if not (isinstance(drive_id, str) and drive_id and isinstance(item_id, str) and item_id):
        source_id = file_info.get("source_id") or (file_info.get("canonical_id") if isinstance(file_info.get("canonical_id"), str) else "")
        if isinstance(source_id, str) and source_id.count(":") == 1:
            drive_id, item_id = source_id.split(":", 1)
    if not (isinstance(drive_id, str) and drive_id and isinstance(item_id, str) and item_id):
        return None
    if len(drive_id) > 512 or len(item_id) > 512:
        return None
    web_url = safe_https_url(file_info.get("web_url") or file_info.get("url") or file_info.get("webUrl"))
    file_name = (
        _single_line(file_info.get("display_name") or file_info.get("name"), _FIELD_LIMITS["file_name"])
        or _file_name_from_url(web_url)
    )
    size = file_info.get("size_bytes", file_info.get("size"))
    modified = _file_modified_at(file_info)
    record = {
        "citation_id": m365_citation_id(source, f"{drive_id}:{item_id}"),
        "kind": "file",
        "source": source,
        "title": file_name or "Untitled file",
        "file_name": file_name,
        "mime_type": _single_line(file_info.get("mime_type") or _mapping(file_info.get("file")).get("mimeType"), _FIELD_LIMITS["mime_type"]),
        "size_bytes": size if type(size) is int and size >= 0 else None,
        "modified_at": _iso_utc(modified),
        "modified_display": format_m365_date(_iso_utc(modified), display_time_zone) if modified else "",
        "location_label": m365_location_label(source),
        "web_url": web_url,
    }
    if content_read:
        record["content_read"] = True
    return _drop_empty(record)


def _drop_empty(record):
    return {key: value for key, value in record.items() if value not in (None, "")}


def sanitize_m365_citation_record(value):
    """A re-validated copy of a stored or captured record, or None when it is not one."""
    if not isinstance(value, Mapping):
        return None
    citation_id = value.get("citation_id")
    kind = value.get("kind")
    source = value.get("source")
    if not is_m365_citation_id(citation_id) or kind not in _KIND_SOURCES or source not in _KIND_SOURCES[kind]:
        return None
    record = {"citation_id": citation_id, "kind": kind, "source": source}
    for field in _TEXT_FIELDS[kind]:
        text = _single_line(value.get(field), _FIELD_LIMITS[field])
        if text:
            record[field] = text
    for field in _TIME_FIELDS[kind]:
        text = value.get(field)
        if isinstance(text, str) and 0 < len(text) <= 40 and not _CONTROL_RE.search(text):
            record[field] = text.strip()
    record.setdefault("title", "Microsoft 365 item")
    record["location_label"] = m365_location_label(source)
    if kind == "file":
        size = value.get("size_bytes")
        if type(size) is int and size >= 0:
            record["size_bytes"] = size
    if kind == "email" and isinstance(value.get("is_read"), bool):
        record["is_read"] = value["is_read"]
    if kind == "event" and isinstance(value.get("is_all_day"), bool):
        record["is_all_day"] = value["is_all_day"]
    web_url = safe_https_url(value.get("web_url"))
    if web_url:
        record["web_url"] = web_url
    for flag in ("cited", "content_read"):
        if value.get(flag) is True:
            record[flag] = True
        elif flag == "cited" and value.get(flag) is False:
            record[flag] = False
    data_user_id = _single_line(value.get("data_user_id"), _FIELD_LIMITS["data_user_id"])
    if data_user_id:
        record["data_user_id"] = data_user_id
    return record


# --------------------------------------------------------------------------------------
# Tool-result annotation (what the model reads)
# --------------------------------------------------------------------------------------

class M365CitedResult(dict):
    """A Microsoft 365 tool result plus the citation records made from its Graph data.

    Only the annotators below create one, from results the Microsoft 365 plugins built out of
    Microsoft Graph responses, so its records are the one trusted source of citation titles and
    links. The plugin invocation logger keeps them with the invocation. The records are an
    attribute, not a key, so the model never reads them and no tool output can supply them.
    """

    m365_citation_records = ()


def captured_m365_records(result):
    """Copies of the records a Microsoft 365 plugin attached to its own result, else ``[]``.

    A dict or JSON text that merely looks like a Graph result, which any tool can return, never
    yields a record.
    """
    if not isinstance(result, M365CitedResult):
        return []
    return [dict(record) for record in result.m365_citation_records[:MAX_RESULT_M365_RECORDS]]


def _with_records(result, records):
    """``result`` as an :class:`M365CitedResult` carrying ``records``; unchanged when there are none."""
    if not records:
        return result
    cited = result if isinstance(result, M365CitedResult) else M365CitedResult(result)
    cited.m365_citation_records = tuple(
        _dedupe([*cited.m365_citation_records, *records])[:MAX_RESULT_M365_RECORDS]
    )
    return cited


def _log_annotation_failure(kind, error):
    """Report an item or result that could not be cited; the tool result itself is unaffected."""
    try:
        # Logging owns application bootstrap; this module stays cold-importable, so it loads
        # log_event only on this failure path.
        from functions_appinsights import log_event

        log_event(
            "[M365_CITATIONS] Citation values could not be added to a Microsoft 365 result.",
            extra={"kind": kind, "error_type": type(error).__name__},
            level=logging.WARNING,
        )
    except Exception:
        pass


def _safe_record(normalize, kind, *args, **kwargs):
    """``normalize(*args, **kwargs)``, or None when one unusual item cannot be normalized."""
    try:
        return normalize(*args, **kwargs)
    except Exception as error:
        _log_annotation_failure(kind, error)
        return None


def _plural(count, singular, plural=None):
    return singular if count == 1 else (plural or f"{singular}s")


def _received_order_is_newest_first(items):
    times = [_parse_graph_datetime(item.get("receivedDateTime")) for item in items if isinstance(item, Mapping)]
    times = [value for value in times if value is not None]
    return all(left >= right for left, right in zip(times, times[1:]))


def m365_mail_presentation(count, *, matching=False, all_unread=False, newest_first=True):
    header = f"{count} {'matching' if matching else 'most recent'} {_plural(count, 'email')}"
    if all_unread:
        header += ", all unread"
    if newest_first:
        header += ", newest first"
    return (
        f'Present these emails in this exact layout. First line: "{header}:". Then one numbered line '
        'per email: "{n}. **{subject}** \u2014 {sender}, {received_display}{ \u00b7 Unread}'
        '{ \u00b7 High importance} {citation}". {sender} is the sender name, or the address when there '
        'is no name. Add " \u00b7 Unread" only when is_read is false and the first line does not already '
        'say all unread, and " \u00b7 High importance" only when importance is high. {citation} is that '
        "email's citation value, copied verbatim. Add one indented line summarizing an email only when "
        'the user asked about its content. Copy received_display exactly; do not convert or reformat times.'
    )


def m365_event_presentation(count, *, matching=False, newest_first=False):
    header = (
        f"{count} {'matching ' if matching else ''}{_plural(count, 'event')}, "
        f"{'latest' if newest_first else 'earliest'} first"
    )
    return (
        f'Present these events in this exact layout. First line: "{header}:". Then one numbered line '
        'per event: "{n}. **{subject}** \u2014 {when_display}{ \u00b7 location}{ \u00b7 Organizer: name} '
        '{citation}". Leave out the location or organizer part when it is empty. {citation} is that '
        "event's citation value, copied verbatim. Copy when_display exactly; do not convert or reformat times."
    )


def m365_file_presentation():
    return (
        'When you list these files, use one numbered line per file: "{n}. **{file name}** \u2014 '
        '{location}, modified {modified_display} {citation}", where {location} is SharePoint or OneDrive '
        "and {citation} is that file's citation value, copied verbatim. When you use a file's content in "
        "prose, put that file's citation right after the sentence it supports."
    )


def annotate_m365_mail_result(result, *, display_time_zone=None, matching=False):
    """Add each message's citation id, citation value and received_display, plus the layout.

    Returns an :class:`M365CitedResult` that carries the messages' records. A failure leaves the
    result as it was, because a citation problem must never cost the user their mail.
    """
    try:
        return _annotate_mail_result(result, display_time_zone, matching)
    except Exception as error:
        _log_annotation_failure("email", error)
        return result


def _annotate_mail_result(result, display_time_zone, matching):
    if not isinstance(result, dict) or result.get("error") or not isinstance(result.get("value"), list):
        return result
    items = [item for item in result["value"] if isinstance(item, dict)]
    records = []
    for item in items:
        record = _safe_record(normalize_m365_email, "email", item, display_time_zone)
        if record is None:
            continue
        item["citation_id"] = record["citation_id"]
        item["citation"] = build_m365_citation_marker(record)
        if record.get("received_display"):
            item["received_display"] = record["received_display"]
        records.append(record)
    if records:
        all_unread = all(item.get("isRead") is False for item in items)
        result["citation_instructions"] = M365_CITATION_INSTRUCTIONS
        result["presentation"] = m365_mail_presentation(
            len(items), matching=matching, all_unread=all_unread,
            newest_first=_received_order_is_newest_first(items),
        )
        result["display_time_zone"] = _zone(display_time_zone)[1]
    return _with_records(result, records)


def annotate_m365_event_result(result, *, display_time_zone=None, matching=False, newest_first=False):
    """Add each event's citation id, citation value and when_display, plus the layout.

    Returns an :class:`M365CitedResult` that carries the events' records, or the result as it
    was when citing fails.
    """
    try:
        return _annotate_event_result(result, display_time_zone, matching, newest_first)
    except Exception as error:
        _log_annotation_failure("event", error)
        return result


def _annotate_event_result(result, display_time_zone, matching, newest_first):
    if not isinstance(result, dict) or result.get("error") or not isinstance(result.get("value"), list):
        return result
    items = [item for item in result["value"] if isinstance(item, dict)]
    records = []
    for item in items:
        record = _safe_record(normalize_m365_event, "event", item, display_time_zone)
        if record is None:
            continue
        item["citation_id"] = record["citation_id"]
        item["citation"] = build_m365_citation_marker(record)
        if record.get("when_display"):
            item["when_display"] = record["when_display"]
        records.append(record)
    if records:
        result["citation_instructions"] = M365_CITATION_INSTRUCTIONS
        result["presentation"] = m365_event_presentation(len(items), matching=matching, newest_first=newest_first)
        result["display_time_zone"] = _zone(display_time_zone)[1]
    return _with_records(result, records)


def _annotate_file(file_info, source, display_time_zone, *, content_read=False):
    record = _safe_record(
        normalize_m365_file, "file", file_info, source, display_time_zone, content_read=content_read,
    )
    if record is None:
        return None
    file_info["citation_id"] = record["citation_id"]
    file_info["citation"] = build_m365_citation_marker(record)
    if record.get("modified_display"):
        file_info["modified_display"] = record["modified_display"]
    return record


def annotate_m365_file_result(result, source, *, display_time_zone=None, operation=None):
    """Add citation values to every file identity in a SharePoint or OneDrive tool result.

    ``operation`` is the file tool that ran; a file that prepare, read or analyze returns is
    marked as read. Returns an :class:`M365CitedResult` that carries the files' records, or the
    result as it was when citing fails.
    """
    try:
        return _annotate_file_result(result, source, display_time_zone, operation)
    except Exception as error:
        _log_annotation_failure("file", error)
        return result


def _annotate_file_result(result, source, display_time_zone, operation):
    if not isinstance(result, dict) or source not in M365_FILE_SOURCES or result.get("status") == "error":
        return result
    content_read = operation in M365_FILE_READ_OPERATIONS
    records = [
        _annotate_file(file_info, source, display_time_zone)
        for file_info in result.get("results") or () if isinstance(file_info, dict)
    ]
    if isinstance(result.get("file"), dict):
        records.append(_annotate_file(result["file"], source, display_time_zone, content_read=content_read))
    records = [record for record in records if record]
    if (
        not records and isinstance(result.get("canonical_id"), str)
        and safe_https_url(result.get("web_url"))
    ):
        # A retained chunk names its file only by canonical id and URL.
        record = _annotate_file(result, source, display_time_zone, content_read=content_read)
        records = [record] if record else []
    if records:
        result["citation_instructions"] = M365_CITATION_INSTRUCTIONS
        result["presentation"] = m365_file_presentation()
    return _with_records(result, records)


# --------------------------------------------------------------------------------------
# Collection: the records captured when Microsoft 365 plugins ran
# --------------------------------------------------------------------------------------


def _merge_record(existing, incoming):
    merged = dict(existing)
    for key, value in incoming.items():
        if key in ("cited", "content_read"):
            continue
        if value not in (None, "") and (key not in merged or merged[key] in (None, "")):
            merged[key] = value
    if existing.get("content_read") or incoming.get("content_read"):
        merged["content_read"] = True
    return merged


def _dedupe(records):
    """One record per citation id, in first-seen order, later calls filling missing details."""
    by_id = OrderedDict()
    for record in records:
        if not isinstance(record, Mapping) or not is_m365_citation_id(record.get("citation_id")):
            continue
        citation_id = record["citation_id"]
        by_id[citation_id] = _merge_record(by_id[citation_id], record) if citation_id in by_id else dict(record)
    return list(by_id.values())


def _captured_records(captured):
    if not isinstance(captured, list):
        return []
    return [
        record for record in (sanitize_m365_citation_record(item) for item in captured[:MAX_RESULT_M365_RECORDS])
        if record
    ]


def _records_from_citation(citation):
    """The records captured when a Microsoft 365 plugin ran; never parsed out of its result."""
    if not isinstance(citation, Mapping) or citation.get("success") is False:
        return []
    return _captured_records(citation.get("m365_items"))


def _records_from_invocation(invocation):
    if getattr(invocation, "success", None) is False:
        return []
    return _captured_records(getattr(invocation, "m365_items", None))


def collect_m365_citation_records(agent_citations=None, invocations=None, limit=MAX_COLLECTED_M365_RECORDS):
    """Deduplicated records from tool citation records and live plugin invocations, in call order.

    The list is not trimmed to what a message keeps: :func:`finalize_m365_citations` does that
    once it knows which records the answer cites.
    """
    records = []
    for citation in agent_citations or ():
        records.extend(_records_from_citation(citation))
    for invocation in invocations or ():
        records.extend(_records_from_invocation(invocation))
    return _dedupe(records)[:limit]


def extract_cited_m365_ids(content):
    """Ordered, unique ``m365-`` ids referenced by explicit ``[#id]`` groups in answer text."""
    cited = []
    for group in _CITATION_GROUP_RE.findall(str(content or "")):
        for part in re.split(r"[;,]", group):
            candidate = part.strip().lstrip("#").strip()
            if is_m365_citation_id(candidate) and candidate not in cited:
                cited.append(candidate)
    return cited


def _context_data_user_id():
    try:
        context = m365_context.get_m365_execution_context()
    except RuntimeError:
        return None
    data_user_id = getattr(context, "data_user_id", None)
    return data_user_id if isinstance(data_user_id, str) and data_user_id else None


def _retention_rank(record):
    if record.get("cited"):
        return 0
    return 1 if record.get("content_read") else 2


def finalize_m365_citations(records, content, data_user_id=None):
    """Mark which records the final text cites and stamp the data owner on each.

    When there are more records than a message keeps, the cited ones are kept first, then files
    whose content was read, so the trim never drops a source the answer relies on. The kept
    records stay in call order.
    """
    cited_ids = set(extract_cited_m365_ids(content))
    owner = _context_data_user_id() or data_user_id
    finalized = []
    for record in _dedupe(list(records or ())):
        clean = sanitize_m365_citation_record(record)
        if clean is None:
            continue
        clean["cited"] = clean["citation_id"] in cited_ids
        if owner:
            clean["data_user_id"] = _single_line(owner, _FIELD_LIMITS["data_user_id"])
        finalized.append(clean)
    if len(finalized) <= MAX_MESSAGE_M365_CITATIONS:
        return finalized
    kept = {
        record["citation_id"]
        for record in sorted(finalized, key=_retention_rank)[:MAX_MESSAGE_M365_CITATIONS]
    }
    return [record for record in finalized if record["citation_id"] in kept]


def build_message_m365_citations(agent_citations=None, content="", invocations=None, data_user_id=None):
    return finalize_m365_citations(
        collect_m365_citation_records(agent_citations, invocations), content, data_user_id=data_user_id,
    )


def attach_m365_message_citations(message, agent_citations=None, invocations=None, data_user_id=None):
    """Set ``message['m365_citations']`` from this reply's tool calls, or leave it absent."""
    if not isinstance(message, dict):
        return message
    records = build_message_m365_citations(
        agent_citations, message.get("content"), invocations=invocations, data_user_id=data_user_id,
    )
    if records:
        message["m365_citations"] = records
    else:
        message.pop("m365_citations", None)
    return message


def collect_gathered_m365_records(task_results, read_value):
    """Records from every gather step's retained tool citations, for an orchestrated answer.

    ``task_results`` maps step ids to TaskResult objects and ``read_value(reference)`` reads a
    retained "prepared" value through the owning authorization service. A step whose value
    cannot be read contributes nothing; the answer's own publication rechecks access.
    """
    records = []
    for task in (task_results or {}).values():
        capability_id = getattr(getattr(task, "producer", None), "capability_id", None)
        if getattr(task, "status", None) not in ("complete", "partial") or capability_id not in M365_GATHER_CAPABILITIES:
            continue
        for reference in getattr(task, "outputs", ()) or ():
            completeness = getattr(reference, "completeness", None)
            if getattr(reference, "output_name", None) != "prepared" or getattr(completeness, "status", None) not in ("complete", "partial"):
                continue
            value = read_value(reference)
            citations = value.get("citations") if isinstance(value, Mapping) else None
            if isinstance(citations, list):
                records.extend(collect_m365_citation_records(citations))
    return _dedupe(records)[:MAX_COLLECTED_M365_RECORDS]


def build_m365_sources_note(records):
    """A deterministic list of citation values and key details for an orchestration step's notes."""
    lines = []
    for record in (sanitize_m365_citation_record(item) for item in (records or ())[:MAX_SOURCES_NOTE_ITEMS]):
        if record is None:
            continue
        if record["kind"] == "email":
            sender = record.get("from_name") or record.get("from_address") or "Unknown sender"
            details = [f"from {sender}", record.get("received_display", "")]
            if record.get("is_read") is False:
                details.append("unread")
            if record.get("importance") == "high":
                details.append("high importance")
        elif record["kind"] == "event":
            details = [record.get("when_display", ""), record.get("location", "")]
            if record.get("organizer_name"):
                details.append(f"organizer {record['organizer_name']}")
        else:
            details = [record.get("location_label", "")]
            if record.get("modified_display"):
                details.append(f"modified {record['modified_display']}")
        detail_text = ", ".join(part for part in details if part)
        lines.append(f"- {build_m365_citation_marker(record)}" + (f" \u2014 {detail_text}" if detail_text else ""))
    if not lines:
        return ""
    return (
        "Microsoft 365 sources (copy each citation value verbatim right after the claim or list line it "
        "supports; never invent or alter one):\n" + "\n".join(lines)
    )


# --------------------------------------------------------------------------------------
# Conversation aggregate: used_m365_items
# --------------------------------------------------------------------------------------

def _eligible_message_records(message):
    records = []
    for value in (message.get("m365_citations") if isinstance(message, Mapping) else None) or ():
        record = sanitize_m365_citation_record(value)
        if record and (record.get("cited") or record.get("content_read")):
            records.append(record)
    return records


def _timestamp_text(value):
    return value if isinstance(value, str) and 0 < len(value) <= 64 else ""


def _sanitize_used_item(value):
    record = sanitize_m365_citation_record(value)
    if record is None:
        return None
    record["cited"] = value.get("cited") is True
    message_ids = [
        message_id for message_id in (value.get("message_ids") or ())
        if isinstance(message_id, str) and 0 < len(message_id) <= 256
    ]
    record["message_ids"] = list(dict.fromkeys(message_ids))[-MAX_ITEM_MESSAGE_IDS:]
    record["last_used_at"] = _timestamp_text(value.get("last_used_at"))
    return record


def merge_used_m365_items(existing, incoming_records, *, message_id=None, used_at=None):
    """Merge one message's cited or read records into the conversation aggregate."""
    items = OrderedDict()
    for value in existing or ():
        item = _sanitize_used_item(value) if isinstance(value, Mapping) else None
        if item:
            items[item["citation_id"]] = item
    used_at = _timestamp_text(used_at)
    for record in incoming_records or ():
        clean = sanitize_m365_citation_record(record)
        if clean is None:
            continue
        current = items.get(clean["citation_id"])
        cited = clean.get("cited") is True or bool(current and current.get("cited"))
        content_read = clean.get("content_read") is True or bool(current and current.get("content_read"))
        message_ids = list(current.get("message_ids", [])) if current else []
        if isinstance(message_id, str) and message_id:
            message_ids = [value for value in message_ids if value != message_id] + [message_id]
        item = {**clean, "cited": cited, "message_ids": message_ids[-MAX_ITEM_MESSAGE_IDS:]}
        if content_read:
            item["content_read"] = True
        item["last_used_at"] = max(used_at, current.get("last_used_at", "")) if current else used_at
        items.pop(clean["citation_id"], None)
        items[clean["citation_id"]] = item
    ordered = sorted(items.values(), key=lambda item: item.get("last_used_at") or "", reverse=True)
    return ordered[:MAX_CONVERSATION_M365_ITEMS]


def merge_m365_items_into_conversation(conversation, message):
    """Fold one finalized assistant message's Microsoft 365 items into the conversation."""
    if not isinstance(conversation, dict) or not isinstance(message, Mapping):
        return []
    incoming = _eligible_message_records(message)
    if not incoming and "used_m365_items" not in conversation:
        return []
    conversation["used_m365_items"] = merge_used_m365_items(
        conversation.get("used_m365_items"), incoming,
        message_id=message.get("id"), used_at=message.get("timestamp"),
    )
    return deepcopy(conversation["used_m365_items"])


def rebuild_conversation_used_m365_items(conversation, active_assistant_messages):
    """Recompute the aggregate from the conversation's current active assistant messages."""
    if not isinstance(conversation, dict):
        return []
    messages = sorted(
        (message for message in active_assistant_messages or () if isinstance(message, Mapping)),
        key=lambda message: str(message.get("timestamp") or ""),
    )
    items = []
    for message in messages:
        items = merge_used_m365_items(
            items, _eligible_message_records(message),
            message_id=message.get("id"), used_at=message.get("timestamp"),
        )
    if items or "used_m365_items" in conversation:
        conversation["used_m365_items"] = items
    return deepcopy(items)


def used_m365_items_for_viewer(items, viewer_user_id):
    """Only the items whose Microsoft 365 data belongs to the viewer, without the owner id."""
    if not isinstance(viewer_user_id, str) or not viewer_user_id:
        return []
    visible = []
    for value in items or ():
        item = _sanitize_used_item(value) if isinstance(value, Mapping) else None
        if item and item.get("data_user_id") == viewer_user_id:
            item.pop("data_user_id", None)
            visible.append(item)
    return visible


def message_m365_sources(message):
    """The Microsoft 365 sources a stored message recorded, for history-sharing approval."""
    sources = set()
    for value in (message.get("m365_citations") if isinstance(message, Mapping) else None) or ():
        record = sanitize_m365_citation_record(value)
        if record:
            sources.add(record["source"])
    return sources
