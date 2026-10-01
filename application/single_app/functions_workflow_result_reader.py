# functions_workflow_result_reader.py
"""Read the stored result of a finished personal workflow run for chat.

The reader is Flask-free. It point-reads the workflow and the run in the
requester's own partition, so someone else's run reads exactly like a missing
one. It authorizes the whole run the way run history does, binds the result to
a digest over its included outputs, and returns a public descriptor. Follow up
also asks for bounded excerpts; those carry only a task label, a kind and text,
never store references or identifiers.

Structured (v3) runs are closed for now: their outputs need an exact node,
execution and attempt selector.
"""

import hashlib
import json
import logging
import math
import re
import unicodedata
from collections import OrderedDict
from collections.abc import Mapping
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from azure.core.exceptions import AzureError, ResourceNotFoundError
from content_screening.contracts import ScreeningError

from functions_appinsights import log_event
from functions_workflow_result_masking import WORKFLOW_RESULT_VERSION
from functions_workflow_result_store import (
    MAX_PAGE_BYTES,
    AnalysisWorkUnitConflictError,
    WorkflowResultStorageUnavailableError,
    load_workflow_task_result,
    read_workflow_task_result_page,
)
from functions_workflow_results import (
    ANALYSIS_RECORD_PAGE_SIZE,
    WORKFLOW_RESULT_CONTRACT_VERSION,
    _require_completed_result,
    authorize_workflow_run_read,
    load_workflow_task_input,
    read_result_records,
)


READABLE_RUN_STATUSES = frozenset({"completed", "completed_partial"})
UNFINISHED_RUN_STATUSES = frozenset({"failed", "invalid", "incomplete", "cancelled", "skipped"})
DEFAULT_EXCERPT_BUDGET_BYTES = 48 * 1024
MIN_EXCERPT_BUDGET_BYTES = 1024
MAX_EXCERPT_BUDGET_BYTES = 128 * 1024
MAX_EXCERPT_OUTPUTS = 8
MIN_OUTPUT_EXCERPT_BYTES = 512
FULL_SECTION_READ_BYTES = 256 * 1024
MAX_RECORD_PAGE_READS = 8
MAX_TASK_ROWS = 200
WORKFLOW_NAME_MAX_CHARS = 80
TASK_LABEL_MAX_CHARS = 120

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_OUTPUT_KINDS = {"text": "text", "records": "records", "json": "json", "documents": "document_results"}
_RECORD_KINDS = frozenset({"records", "document_results"})
_JSON_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~])")
_ITEMS_QUERY = (
    "SELECT c.workflow_id, c.run_id, c.task_id, c.task_order, c.status, c.item_type, c.label, "
    "c.workflow_result FROM c "
    "WHERE c.run_id = @run_id AND c.workflow_id = @workflow_id AND c.item_type = 'task'"
)

# Every closed reason has fixed wording; exception text is never shown or logged.
_REASONS = {
    "workflow_results_disabled": (403, "Workflow results in chat are not available."),
    "workflow_result_invalid_context": (400, "The selected workflow result is invalid."),
    "workflow_result_context_conflict": (
        400, "Ask about either a saved analysis or a workflow result, not both.",
    ),
    "workflow_result_private_only": (403, "Workflow results can only be used in your own private chats."),
    "workflow_result_not_found": (404, "This workflow result is unavailable. The run may have been removed."),
    "workflow_result_access_denied": (
        403, "This workflow result is unavailable because access to one of its sources could not be confirmed.",
    ),
    "workflow_result_changed": (
        409,
        "This workflow run's result has changed since it was selected. "
        "Select the run again to ask about its current result.",
    ),
    "workflow_result_in_progress": (409, "This workflow run hasn't finished yet. Ask about it after it completes."),
    "workflow_result_not_finished": (409, "This workflow run didn't complete, so it has no result to ask about."),
    "workflow_result_preview_only": (
        409, "This workflow run has no stored result to ask about. Older runs keep previews only.",
    ),
    "workflow_result_unsupported": (409, "Asking about the results of this kind of workflow isn't supported yet."),
    "workflow_result_invalid": (409, "This workflow run's stored result can't be read."),
    "workflow_result_storage_unavailable": (
        503, "The workflow result couldn't be read right now. Try again in a moment.",
    ),
    # Follow up's own refusals, around the read.
    "workflow_result_conversation_unavailable": (
        404, "This chat is no longer available. Start a new chat to ask about the workflow result.",
    ),
    "workflow_result_retry_unsupported": (
        400, "Retrying or editing a question about a workflow result isn't supported yet. Ask the question again.",
    ),
    "workflow_result_too_large": (
        400,
        "The workflow result and this chat's history don't fit the selected model. "
        "Select a model with a larger context window or start a new chat, then ask again.",
    ),
    "workflow_result_model_unsupported": (
        400,
        "The selected model or agent couldn't answer from this workflow result with its tools turned off. "
        "Select a model or a local chat agent, then ask again.",
    ),
    "workflow_result_answer_failed": (
        503, "The answer couldn't be completed. The workflow result is unchanged. Try again in a moment.",
    ),
    "workflow_result_answer_rejected": (
        400,
        "The answer wasn't kept because it didn't match the stored workflow result. "
        "The result is unchanged. Ask again, or ask a narrower question.",
    ),
}


class WorkflowResultUnavailable(Exception):
    """A closed reason with a fixed status and message; never carries exception text."""

    def __init__(self, code):
        if code not in _REASONS:
            code = "workflow_result_invalid"
        self.code = code
        self.status, self.message = _REASONS[code]
        super().__init__(self.message)


def workflow_result_error_payload(error):
    """Return the fixed response body and status for a closed reason."""
    if not isinstance(error, WorkflowResultUnavailable):
        error = WorkflowResultUnavailable("workflow_result_invalid")
    return {"error": error.message, "code": error.code}, error.status


def workflow_result_context(value):
    """Validate the only selector a browser sends: ``{workflow_id, run_id, result_sha256}``."""
    if not isinstance(value, Mapping):
        raise WorkflowResultUnavailable("workflow_result_invalid_context")
    workflow_id = value.get("workflow_id")
    run_id = value.get("run_id")
    result_sha256 = value.get("result_sha256")
    if (
        not isinstance(workflow_id, str) or not _IDENTIFIER.fullmatch(workflow_id)
        or not isinstance(run_id, str) or not _IDENTIFIER.fullmatch(run_id)
        or not isinstance(result_sha256, str) or not _SHA256.fullmatch(result_sha256)
    ):
        raise WorkflowResultUnavailable("workflow_result_invalid_context")
    return {"workflow_id": workflow_id, "run_id": run_id, "result_sha256": result_sha256}


def workflow_result_context_key(context):
    return (context["workflow_id"], context["run_id"], context["result_sha256"])


def workflow_result_message_contexts(message):
    """Return ``(contexts, malformed)`` for every workflow result a stored message relies on.

    An answer carries its ``workflow_result`` descriptor and the accumulated
    ``workflow_result_contexts``; a user question carries the singular
    ``workflow_result_context``. Any of these keys makes the message dependent on
    a workflow result, and a value that isn't a valid context is reported as
    malformed so the caller can fail closed.
    """
    metadata = message.get("metadata") if isinstance(message, Mapping) else None
    if not isinstance(metadata, Mapping):
        return [], False
    candidates = []
    malformed = False
    for key in ("workflow_result", "workflow_result_context"):
        if key in metadata:
            candidates.append(metadata.get(key))
    if "workflow_result_contexts" in metadata:
        values = metadata.get("workflow_result_contexts")
        if isinstance(values, list):
            candidates.extend(values)
        else:
            malformed = True
    contexts = []
    seen = set()
    for candidate in candidates:
        try:
            context = workflow_result_context(candidate)
        except WorkflowResultUnavailable:
            malformed = True
            continue
        key = workflow_result_context_key(context)
        if key not in seen:
            seen.add(key)
            contexts.append(context)
    return contexts, malformed


def _clean_line(value, limit):
    text = "".join(
        " " if unicodedata.category(char).startswith(("C", "Z")) else char
        for char in str(value or "")
    )
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit].rstrip()
    return text


def _iso_utc(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def format_workflow_run_time(completed_at, time_zone=None):
    """Format a run's completion time in the user's zone, falling back to UTC."""
    moment_text = _iso_utc(completed_at)
    if moment_text is None:
        return ""
    zone = timezone.utc
    if isinstance(time_zone, str) and 0 < len(time_zone) <= 64:
        try:
            zone = ZoneInfo(time_zone)
        except Exception:
            zone = timezone.utc
    moment = datetime.fromisoformat(moment_text).astimezone(zone)
    hour = moment.hour % 12 or 12
    period = "AM" if moment.hour < 12 else "PM"
    zone_name = moment.tzname() or "UTC"
    return f"{moment:%a} {moment:%b} {moment.day}, {moment.year}, {hour}:{moment:%M} {period} {zone_name}"


def escape_markdown_text(value):
    return _MARKDOWN_SPECIAL.sub(r"\\\1", str(value or ""))


def format_workflow_result_disclosure(descriptor, time_zone=None, *, truncated=False, partial=False,
                                      analysis_only=False, skipped_reports=False):
    """The fixed, server-written line appended to every Follow up answer."""
    name = escape_markdown_text(_clean_line((descriptor or {}).get("workflow_name"), WORKFLOW_NAME_MAX_CHARS))
    when = format_workflow_run_time((descriptor or {}).get("completed_at"), time_zone)
    subject = f"the {name or 'workflow'} run of {when}" if when else f"a stored {name or 'workflow'} run"
    sentences = [f"This answer uses the stored result of {subject}. The workflow was not re-run."]
    if partial:
        sentences.append("The run completed partially, so its result may be incomplete.")
    if analysis_only:
        sentences.append("Only the saved analysis in this run's result was used.")
    if skipped_reports:
        sentences.append("A report that combined several saved analyses couldn't be used.")
    if truncated:
        sentences.append("Only part of the result fit in this answer.")
    return "_" + " ".join(sentences) + "_"


def _log_unavailable(code, stage, error=None):
    extra = {"code": code, "stage": stage}
    if error is not None:
        extra["error_type"] = type(error).__name__
    level = logging.WARNING if code == "workflow_result_storage_unavailable" else logging.INFO
    log_event("[WorkflowResults] Workflow result unavailable", extra=extra, level=level)


def _closed(code, stage, error=None):
    _log_unavailable(code, stage, error)
    return WorkflowResultUnavailable(code)


def _default_containers():
    # Config initializes Azure clients at import; keep the reader importable without it.
    from config import (
        cosmos_personal_workflow_run_items_container,
        cosmos_personal_workflow_runs_container,
        cosmos_personal_workflows_container,
    )

    return {
        "workflows": cosmos_personal_workflows_container,
        "runs": cosmos_personal_workflow_runs_container,
        "run_items": cosmos_personal_workflow_run_items_container,
    }


def _point_read(container, item_id, partition_key, stage):
    try:
        document = container.read_item(item=item_id, partition_key=partition_key)
    except ResourceNotFoundError:
        raise _closed("workflow_result_not_found", stage) from None
    except AzureError as exc:
        raise _closed("workflow_result_storage_unavailable", stage, exc) from None
    if not isinstance(document, Mapping):
        raise _closed("workflow_result_not_found", stage)
    return {key: value for key, value in document.items() if not str(key).startswith("_")}


class _ManifestMemo:
    """Load each stored manifest once per check; data sections always pass through.

    Authorization, the completion rule and the Analyze reader all load the same
    manifests, so they share this loader. Only manifests are kept, and only a
    bounded number of them, so a large record page never stays in memory.
    """

    def __init__(self, load, limit=64):
        self._load = load
        self._limit = limit
        self._cache = OrderedDict()
        self.load_count = 0

    def __call__(self, workflow, run_id, task_id, reference, **selectors):
        key = (
            str(run_id), str(task_id),
            json.dumps(reference, sort_keys=True, default=str),
            json.dumps(selectors, sort_keys=True, default=str),
        )
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        self.load_count += 1
        value = self._load(workflow, run_id, task_id, reference, **selectors)
        if isinstance(value, Mapping) and "identity" in value and "outputs" in value:
            self._cache[key] = value
            if len(self._cache) > self._limit:
                self._cache.popitem(last=False)
        return value


def _is_structured(workflow, run):
    runtime = run.get("runtime") if isinstance(run.get("runtime"), Mapping) else {}
    return (
        workflow.get("definition_version") == 3
        or run.get("definition_version") == 3
        or runtime.get("schema_version") == 2
        or "workflow_outputs" in run
    )


def _task_rows(container, workflow_id, run_id):
    try:
        rows = []
        for row in container.query_items(
            query=_ITEMS_QUERY,
            parameters=[
                {"name": "@run_id", "value": run_id},
                {"name": "@workflow_id", "value": workflow_id},
            ],
            partition_key=run_id,
        ):
            rows.append(row)
            if len(rows) > MAX_TASK_ROWS:
                raise _closed("workflow_result_invalid", "items")
    except WorkflowResultUnavailable:
        raise
    except AzureError as exc:
        raise _closed("workflow_result_storage_unavailable", "items", exc) from None
    if any(not isinstance(row, Mapping) for row in rows):
        raise _closed("workflow_result_invalid", "items")
    return rows


def _eligible_rows(rows, workflow_id, run_id):
    eligible = []
    for row in rows:
        summary = row.get("workflow_result") if isinstance(row.get("workflow_result"), Mapping) else {}
        if summary.get("contract_version") == "workflow-result-v2":
            raise _closed("workflow_result_unsupported", "items")
        if row.get("status") != "succeeded":
            continue
        reference = summary.get("result_ref")
        if not isinstance(reference, Mapping):
            continue
        task_id = row.get("task_id")
        if (
            row.get("workflow_id") != workflow_id or row.get("run_id") != run_id
            or not isinstance(task_id, str) or not task_id
            or summary.get("contract_version") != WORKFLOW_RESULT_CONTRACT_VERSION
            or not isinstance(reference.get("sha256"), str) or not _SHA256.fullmatch(reference["sha256"])
            or summary.get("authoritative_output") not in _OUTPUT_KINDS
        ):
            raise _closed("workflow_result_invalid", "items")
        eligible.append(row)
    order = {}
    for row in eligible:
        value = row.get("task_order")
        order[id(row)] = value if type(value) is int else 0
    eligible.sort(key=lambda row: (order[id(row)], row["task_id"]))
    if len({row["task_id"] for row in eligible}) != len(eligible):
        raise _closed("workflow_result_invalid", "items")
    return eligible


def workflow_result_digest(workflow_id, run_id, status, eligible_rows):
    """A canonical digest over the ids, the run status and every included output, independent of any excerpt."""
    outputs = [
        [
            row["task_id"],
            row["workflow_result"]["authoritative_output"],
            row["workflow_result"]["result_ref"]["sha256"],
        ]
        for row in eligible_rows
    ]
    document = {
        "version": WORKFLOW_RESULT_VERSION,
        "workflow_id": workflow_id,
        "run_id": run_id,
        "status": status,
        "outputs": outputs,
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _authorization_code(error):
    if isinstance(error, WorkflowResultUnavailable):
        return error.code
    if isinstance(error, ScreeningError):
        return "workflow_result_storage_unavailable" if getattr(error, "retryable", False) else "workflow_result_access_denied"
    if isinstance(error, PermissionError):
        return "workflow_result_access_denied"
    if isinstance(error, (LookupError, ResourceNotFoundError)):
        return "workflow_result_not_found"
    if isinstance(error, (WorkflowResultStorageUnavailableError, AzureError)):
        return "workflow_result_storage_unavailable"
    if isinstance(error, (ValueError, AnalysisWorkUnitConflictError)):
        return "workflow_result_invalid"
    return None


def _guarded(stage, operation):
    """Run a result-store operation, mapping every known failure to a closed reason."""
    try:
        return operation()
    except Exception as exc:
        code = _authorization_code(exc)
        if code is None:
            raise
        if isinstance(exc, WorkflowResultUnavailable):
            raise
        raise _closed(code, stage, exc) from None


def _cut_text(text, limit):
    data = str(text).encode("utf-8", "replace")
    if len(data) <= limit:
        return data.decode("utf-8", "replace"), False
    return data[:limit].decode("utf-8", "ignore"), True


def _kilobytes(size):
    return max(1, math.ceil(size / 1024))


def _json_text(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(", ", ": "))


def decode_json_string_prefix(text):
    """Decode the body of a JSON string cut at an arbitrary byte, trimming a partial escape.

    A lone or incomplete surrogate at the cut is trimmed rather than guessed; one
    inside the text becomes U+FFFD.
    """
    output = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == '"':
            break
        if char != "\\":
            output.append(char)
            index += 1
            continue
        if index + 1 >= length:
            break
        escape = text[index + 1]
        if escape in _JSON_ESCAPES:
            output.append(_JSON_ESCAPES[escape])
            index += 2
            continue
        if escape != "u":
            raise ValueError("The stored text contains an invalid escape.")
        if index + 6 > length:
            break
        code = _hex_code(text[index + 2:index + 6])
        if 0xD800 <= code <= 0xDBFF:
            if index + 12 > length:
                break
            if text[index + 6:index + 8] == "\\u":
                low = _hex_code(text[index + 8:index + 12])
                if 0xDC00 <= low <= 0xDFFF:
                    output.append(chr(0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)))
                    index += 12
                    continue
            output.append("\ufffd")
            index += 6
            continue
        output.append("\ufffd" if 0xDC00 <= code <= 0xDFFF else chr(code))
        index += 6
    return "".join(output)


def _hex_code(value):
    if len(value) != 4 or any(char not in "0123456789abcdefABCDEF" for char in value):
        raise ValueError("The stored text contains an invalid escape.")
    return int(value, 16)


def _section_matches(section, manifest, name, kind):
    return (
        isinstance(section, Mapping)
        and section.get("contract_version") == manifest.get("contract_version")
        and section.get("producer") == manifest.get("identity")
        and section.get("output_name") == name
        and section.get("kind") == kind
    )


def _value_prefix(content, manifest, name, kind):
    """Extract the start of a section's ``value`` from a canonical JSON page prefix."""
    decoder = json.JSONDecoder()
    if not isinstance(content, str) or not content.startswith("{"):
        raise ValueError("The stored result page is not canonical JSON.")
    position = 1
    header = {}
    while True:
        key, position = decoder.raw_decode(content, position)
        if not isinstance(key, str) or content[position:position + 1] != ":":
            raise ValueError("The stored result page is not canonical JSON.")
        position += 1
        if key == "value":
            break
        header[key], position = decoder.raw_decode(content, position)
        if content[position:position + 1] != "," or len(header) > 8:
            raise ValueError("The stored result page is not canonical JSON.")
        position += 1
    if not _section_matches(header, manifest, name, kind):
        raise ValueError("The stored result page does not match its manifest.")
    rest = content[position:]
    if kind == "text":
        if not rest.startswith('"'):
            raise ValueError("The stored text output is invalid.")
        return decode_json_string_prefix(rest[1:])
    return rest


def _record_lines(rows, limit, lines, used):
    for row in rows:
        line = _json_text(row)
        size = len(line.encode("utf-8", "replace")) + (1 if lines else 0)
        if used + size > limit:
            if not lines:
                text, _ = _cut_text(line, limit)
                lines.append(text)
                used = limit
            return used, True
        lines.append(line)
        used += size
    return used, False


def _output_excerpt(workflow, run_id, task_id, manifest, loader, read_page, limit):
    name = manifest.get("authoritative_output")
    descriptor = (manifest.get("outputs") or {}).get(name)
    kind = _OUTPUT_KINDS.get(name)
    if (
        kind is None or not isinstance(descriptor, Mapping) or descriptor.get("kind") != kind
        or not isinstance(descriptor.get("result_ref"), Mapping)
    ):
        raise ValueError("The saved task has no authoritative output binding.")
    reference = descriptor["result_ref"]

    def load_section(section_reference):
        return loader(workflow, run_id, task_id, section_reference)

    storage_kind = descriptor.get("storage_kind")
    if storage_kind in {"record_pages", "record_tree"}:
        lines = []
        used = 0
        offset = 0
        total = 0
        cut = False
        for _read in range(MAX_RECORD_PAGE_READS):
            rows, total = read_result_records(
                manifest, name, load_section, offset=offset, limit=ANALYSIS_RECORD_PAGE_SIZE,
            )
            used, cut = _record_lines(rows, limit, lines, used)
            offset += len(rows)
            if cut or not rows or offset >= total:
                break
        shown = len(lines)
        cut = cut or shown < total
        note = f"[Excerpt truncated: the first {shown} of {total} records.]" if cut else None
        return "\n".join(lines), cut, note
    size = reference.get("size_bytes")
    if type(size) is int and 0 < size <= FULL_SECTION_READ_BYTES:
        section = load_section(reference)
        if not _section_matches(section, manifest, name, kind):
            raise ValueError("The saved output does not match its producer's manifest.")
        value = section.get("value")
        if kind == "text":
            if not isinstance(value, str):
                raise ValueError("The saved text output is invalid.")
            text, cut = _cut_text(value, limit)
            full_size = len(value.encode("utf-8", "replace"))
        elif kind in _RECORD_KINDS:
            if not isinstance(value, list):
                raise ValueError("The saved record output is invalid.")
            lines = []
            _used, cut = _record_lines(value, limit, lines, 0)
            text = "\n".join(lines)
            if cut or len(lines) < len(value):
                return text, True, f"[Excerpt truncated: the first {len(lines)} of {len(value)} records.]"
            return text, False, None
        else:
            full = _json_text(value)
            text, cut = _cut_text(full, limit)
            full_size = len(full.encode("utf-8", "replace"))
        note = (
            f"[Excerpt truncated: the first {_kilobytes(len(text.encode('utf-8')))} KB "
            f"of {_kilobytes(full_size)} KB.]"
        ) if cut else None
        return text, cut, note
    if type(size) is not int or size <= 0:
        raise ValueError("The saved output reference is invalid.")
    page = read_page(
        workflow, run_id, task_id, reference, offset=0, limit=min(MAX_PAGE_BYTES, limit * 3 + 4096),
    )
    if not isinstance(page, Mapping):
        raise ValueError("The saved result page is invalid.")
    prefix = _value_prefix(page.get("content"), manifest, name, kind)
    text, _cut = _cut_text(prefix, limit)
    total_bytes = page.get("total_bytes") if type(page.get("total_bytes")) is int else size
    note = (
        f"[Excerpt truncated: the first {_kilobytes(len(text.encode('utf-8')))} KB "
        f"of {_kilobytes(total_bytes)} KB.]"
    )
    return text, True, note


def _is_multi_parent_report(row, manifest):
    """The shape ``load_workflow_task_input`` refuses to substitute for analysis records."""
    summary = row.get("workflow_result") or {}
    return (
        summary.get("analysis_result") is True
        and not manifest.get("analysis_access")
        and len(manifest.get("consumed_inputs") or []) != 1
    )


def _descriptor(workflow, run, workflow_id, run_id, digest):
    name = _clean_line(workflow.get("name") or run.get("workflow_name"), WORKFLOW_NAME_MAX_CHARS) or "Workflow"
    return {
        "version": WORKFLOW_RESULT_VERSION,
        "workflow_id": workflow_id,
        "run_id": run_id,
        "workflow_name": name,
        "status": run.get("status"),
        "completed_at": _iso_utc(run.get("completed_at")),
        "result_sha256": digest,
        "available": True,
    }


def read_workflow_result(
    user_id, workflow_id, run_id, *, expected_sha256=None, include_excerpts=False,
    excerpt_budget_bytes=DEFAULT_EXCERPT_BUDGET_BYTES, containers=None,
    load_result=None, read_page=None, source_resolver=None,
):
    """Authorize one finished personal run and describe (or excerpt) its stored result.

    Raises ``WorkflowResultUnavailable`` with a fixed code and status for every
    closed reason. Returns ``descriptor`` (safe for the browser) and, when asked,
    ``excerpts`` and ``saved_inputs`` for the model only.
    """
    if not isinstance(user_id, str) or not user_id.strip():
        raise _closed("workflow_result_not_found", "request")
    if (
        not isinstance(workflow_id, str) or not _IDENTIFIER.fullmatch(workflow_id)
        or not isinstance(run_id, str) or not _IDENTIFIER.fullmatch(run_id)
    ):
        raise _closed("workflow_result_not_found", "request")
    if expected_sha256 is not None and (
        not isinstance(expected_sha256, str) or not _SHA256.fullmatch(expected_sha256)
    ):
        raise _closed("workflow_result_invalid_context", "request")
    if (
        type(excerpt_budget_bytes) is not int
        or not MIN_EXCERPT_BUDGET_BYTES <= excerpt_budget_bytes <= MAX_EXCERPT_BUDGET_BYTES
    ):
        raise ValueError("The excerpt budget must be an integer from 1024 to 131072 bytes.")
    stores = containers if containers is not None else _default_containers()
    loader = _ManifestMemo(load_result or load_workflow_task_result)
    page_reader = read_page or read_workflow_task_result_page

    workflow = _point_read(stores["workflows"], workflow_id, user_id, "workflow")
    if (
        workflow.get("id") != workflow_id or workflow.get("user_id") != user_id
        or workflow.get("group_id") or workflow.get("deleting")
    ):
        raise _closed("workflow_result_not_found", "workflow")
    run = _point_read(stores["runs"], run_id, user_id, "run")
    if (
        run.get("id") != run_id or run.get("workflow_id") != workflow_id
        or run.get("user_id") != user_id or run.get("group_id")
    ):
        raise _closed("workflow_result_not_found", "run")
    if _is_structured(workflow, run):
        raise _closed("workflow_result_unsupported", "run")
    status = run.get("status")
    if status not in READABLE_RUN_STATUSES:
        raise _closed(
            "workflow_result_not_finished" if status in UNFINISHED_RUN_STATUSES else "workflow_result_in_progress",
            "run",
        )
    allow_partial = status == "completed_partial"

    rows = _task_rows(stores["run_items"], workflow_id, run_id)
    eligible = _eligible_rows(rows, workflow_id, run_id)
    if not eligible:
        raise _closed("workflow_result_preview_only", "items")
    digest = workflow_result_digest(workflow_id, run_id, status, eligible)
    if expected_sha256 is not None and expected_sha256 != digest:
        raise _closed("workflow_result_changed", "digest")

    # The whole run, including every stored task result and its analysis sources,
    # is authorized exactly as run history is. The rows are the digest's rows.
    _guarded("authorize", lambda: authorize_workflow_run_read(
        workflow, run_id, reader_user_id=user_id, result_items=rows,
        load_result=loader, source_resolver=source_resolver,
    ))
    manifests = {}
    for row in eligible:
        task_id = row["task_id"]
        reference = row["workflow_result"]["result_ref"]
        manifest = _guarded("manifest", lambda: loader(workflow, run_id, task_id, reference))
        identity = manifest.get("identity") if isinstance(manifest, Mapping) else None
        if (
            not isinstance(identity, Mapping)
            or identity.get("workflow_id") != workflow_id or identity.get("run_id") != run_id
            or identity.get("task_id") != task_id
            or manifest.get("authoritative_output") != row["workflow_result"]["authoritative_output"]
        ):
            raise _closed("workflow_result_invalid", "manifest")
        _guarded("manifest", lambda: _require_completed_result(manifest, allow_partial=allow_partial))
        manifests[task_id] = manifest
    if all(_is_multi_parent_report(row, manifests[row["task_id"]]) for row in eligible):
        raise _closed("workflow_result_unsupported", "manifest")

    result = {
        "descriptor": _descriptor(workflow, run, workflow_id, run_id, digest),
        "partial": allow_partial,
        "output_count": len(eligible),
        "excerpts": [],
        "saved_inputs": [],
        "truncated": False,
        "omitted_outputs": 0,
        "skipped_reports": 0,
        "analysis_only": False,
    }
    if not include_excerpts:
        return result
    _build_excerpts(
        result, workflow, run_id, eligible, manifests, loader, page_reader,
        allow_partial=allow_partial, budget=excerpt_budget_bytes, user_id=user_id,
        source_resolver=source_resolver,
    )
    return result


def _build_excerpts(result, workflow, run_id, eligible, manifests, loader, page_reader, *,
                    allow_partial, budget, user_id, source_resolver):
    from functions_saved_analysis import SavedAnalysisInput

    final_task_id = eligible[-1]["task_id"]
    ordered = [eligible[-1], *eligible[:-1]]
    plain_rows = []
    seen = set()
    for row in ordered:
        if (row.get("workflow_result") or {}).get("analysis_result") is not True:
            plain_rows.append(row)
            continue
        task_id = row["task_id"]
        if _is_multi_parent_report(row, manifests[task_id]):
            # load_workflow_task_input refuses to stand one report in for several analyses.
            result["omitted_outputs"] += 1
            result["skipped_reports"] += 1
            continue
        reference = row["workflow_result"]["result_ref"]
        saved_input, _consumed = _guarded("analysis", lambda: load_workflow_task_input(
            workflow, run_id, task_id, reference, load_result=loader, reader_user_id=user_id,
            source_resolver=source_resolver, bounded=True, allow_partial=allow_partial,
        ))
        if not isinstance(saved_input, SavedAnalysisInput):
            # No analysis sources to verify against: read it like any other output.
            plain_rows.append(row)
            continue
        key = saved_input.context.get("result_sha256")
        if key not in seen:
            seen.add(key)
            result["saved_inputs"].append(saved_input)
    if result["saved_inputs"]:
        # Saved-analysis answers are checked against their records, so plain outputs
        # would make the answer unverifiable; they're set aside and disclosed.
        result["analysis_only"] = bool(plain_rows)
        result["omitted_outputs"] += len(plain_rows)
        return
    if len(plain_rows) > MAX_EXCERPT_OUTPUTS:
        result["omitted_outputs"] += len(plain_rows) - MAX_EXCERPT_OUTPUTS
        result["truncated"] = True
        plain_rows = plain_rows[:MAX_EXCERPT_OUTPUTS]
    remaining = budget
    for index, row in enumerate(plain_rows):
        left = len(plain_rows) - index
        # The final output gets up to half the budget when others follow; they share the rest in order.
        if index == 0 and left > 1:
            limit = budget // 2
        else:
            limit = max(remaining // left, min(remaining, MIN_OUTPUT_EXCERPT_BYTES))
        if limit < MIN_OUTPUT_EXCERPT_BYTES:
            result["omitted_outputs"] += 1
            result["truncated"] = True
            continue
        task_id = row["task_id"]
        text, cut, note = _guarded("excerpt", lambda: _output_excerpt(
            workflow, run_id, task_id, manifests[task_id], loader, page_reader, limit,
        ))
        remaining -= len(text.encode("utf-8", "replace"))
        result["excerpts"].append({
            "label": _clean_line(row.get("label"), TASK_LABEL_MAX_CHARS) or "Task",
            "kind": _OUTPUT_KINDS[manifests[task_id]["authoritative_output"]],
            "final": task_id == final_task_id,
            "text": text,
            "truncated": cut,
            "note": note,
        })
        result["truncated"] = result["truncated"] or cut


def authorize_workflow_result_context(user_id, context, **options):
    """Authorization only: re-check a stored context against its digest, reading no excerpts."""
    context = workflow_result_context(context)
    return read_workflow_result(
        user_id, context["workflow_id"], context["run_id"],
        expected_sha256=context["result_sha256"], include_excerpts=False, **options,
    )["descriptor"]
