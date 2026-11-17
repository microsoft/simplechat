# functions_control_center_usage.py
"""Metadata-only usage queries shared by Classic and V2. No application bootstrap."""

import csv
import json
import threading
import time
from collections import Counter, OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
from io import StringIO

from runtime_usage import USAGE_KINDS, bounded_text, finite_duration, normalize_outcome


USAGE_SCAN_LIMIT = 250000
USAGE_GROUP_LIMIT = 20000
USAGE_CACHE_SECONDS = 90
USAGE_CACHE_SIZE = 128
_cache = OrderedDict()
_cache_lock = threading.Lock()

ENTITY_EXPRESSION = "IIF(c.activity_type = 'agent_run', c.agent.id, c.entity.id)"


class UsageQueryLimitError(RuntimeError):
    """The selected range could not be completely aggregated."""


def project_usage(row):
    """Project legacy records without returning their errors or other raw fields."""
    data = row.get("runtime_usage")
    current = isinstance(data, dict) and data.get("version") == 1
    data = data if current else {}
    kind = row.get("activity_type", "").removesuffix("_run")
    if kind not in USAGE_KINDS:
        raise ValueError("Invalid usage record kind.")
    scope = bounded_text(data.get("scope_type") if current else row.get("workspace_type"))
    scope_id = data.get("scope_id") if current else (
        "global" if scope == "global"
        else row.get("legacy_group_id") if scope == "group"
        else row.get("legacy_public_id") if scope in ("public", "public_workspace")
        else row.get("user_id")
    )
    return {
        "kind": kind,
        "entity_id": bounded_text(data.get("entity_id") if current else row.get("legacy_entity_id")),
        "name": bounded_text(data.get("name") if current else row.get("legacy_name")) or "Unknown entity",
        "scope_type": scope or "unknown",
        "scope_id": bounded_text(scope_id),
        "entity_type": bounded_text(data.get("entity_type")) or "unknown",
        "endpoint_host": bounded_text(data.get("endpoint_host")) or "unknown",
        "auth_type": bounded_text(data.get("auth_type")) or "unknown",
        "operation": bounded_text(data.get("operation")) or "unknown",
        "outcome": normalize_outcome(data.get("outcome") if current else row.get("legacy_outcome")),
        "duration_ms": finite_duration(data.get("duration_ms")) if current else None,
        "legacy": not current,
    }


def _new_total():
    return {"invocations": 0, "outcomes": Counter(), "measured_duration_ms": 0,
            "duration_count": 0, "legacy_records": 0, "_users": set()}


def _add(total, usage, user_id):
    total["invocations"] += 1
    total["outcomes"][usage["outcome"]] += 1
    if isinstance(user_id, str) and user_id and user_id != "system":
        total["_users"].add(user_id)
    if usage["duration_ms"] is not None:
        total["duration_count"] += 1
        total["measured_duration_ms"] += usage["duration_ms"]
    total["legacy_records"] += int(usage["legacy"])


def _finish(total):
    users = total.pop("_users")
    total["unique_users"] = len(users)
    total["outcomes"] = dict(total["outcomes"])
    total["measured_duration_ms"] = round(total["measured_duration_ms"], 3)
    total["average_duration_ms"] = (
        round(total["measured_duration_ms"] / total["duration_count"], 3) if total["duration_count"] else None
    )
    return total


USAGE_PROJECTION = (
    "c.id, c.timestamp, c.user_id, c.activity_type, c.workspace_type, c.runtime_usage, "
    f"{ENTITY_EXPRESSION} AS legacy_entity_id, "
    "IIF(c.activity_type = 'agent_run', c.agent.name, c.entity.name) AS legacy_name, "
    "c.workspace_context.group_id AS legacy_group_id, "
    "c.workspace_context.public_workspace_id AS legacy_public_id, c.run.status AS legacy_outcome"
)


def usage_report(container, where, parameters, *, refresh=False):
    """Stream a complete filtered range, or fail explicitly rather than report a sample."""
    key = (id(container), where, json.dumps(parameters, sort_keys=True))
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if not refresh and cached and now - cached[0] < USAGE_CACHE_SECONDS:
            _cache.move_to_end(key)
            return deepcopy(cached[1])
    groups = {}
    totals = {kind: _new_total() for kind in USAGE_KINDS}
    rows = container.query_items(
        query=f"SELECT {USAGE_PROJECTION} FROM c WHERE ({where}) "
              "AND c.activity_type IN ('agent_run', 'action_run', 'workflow_run') ORDER BY c.timestamp DESC",
        parameters=parameters, enable_cross_partition_query=True, max_item_count=200,
    )
    count = 0
    for row in rows:
        count += 1
        if count > USAGE_SCAN_LIMIT:
            raise UsageQueryLimitError("Narrow the usage date range.")
        usage = project_usage(row)
        # Host/auth/operation remain separate rows so a changed connector configuration
        # does not relabel past executions. Entity counts still use canonical scoped IDs.
        identity = tuple(usage[field] for field in (
            "kind", "scope_type", "scope_id", "entity_id", "endpoint_host", "auth_type", "operation",
        ))
        if identity not in groups:
            if len(groups) >= USAGE_GROUP_LIMIT:
                raise UsageQueryLimitError("Narrow the usage filters.")
            groups[identity] = {**{k: v for k, v in usage.items() if k not in ("outcome", "duration_ms", "legacy")},
                                **_new_total()}
        _add(groups[identity], usage, row.get("user_id"))
        _add(totals[usage["kind"]], usage, row.get("user_id"))
    result = {
        "totals": {kind: _finish(total) for kind, total in totals.items()},
        "entities": sorted((_finish(group) for group in groups.values()), key=lambda group: (
            -group["invocations"], group["kind"], group["name"], group["entity_id"],
        )),
        "complete": True,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "cache_seconds": USAGE_CACHE_SECONDS,
        "record_count": count,
    }
    with _cache_lock:
        _cache[key] = (time.monotonic(), deepcopy(result))
        _cache.move_to_end(key)
        while len(_cache) > USAGE_CACHE_SIZE:
            _cache.popitem(last=False)
    return result


def usage_csv(report):
    """Export the same complete rankings as the interface, without raw activity JSON."""
    output = StringIO()
    columns = ("kind", "entity_id", "name", "scope_type", "scope_id", "entity_type", "endpoint_host",
               "auth_type", "operation", "invocations", "unique_users", "outcomes",
               "duration_count", "measured_duration_ms", "average_duration_ms", "legacy_records")
    writer = csv.writer(output)
    writer.writerow(columns)
    for entity in report["entities"]:
        cells = []
        for column in columns:
            value = entity[column]
            text = json.dumps(value, sort_keys=True) if isinstance(value, dict) else "" if value is None else str(value)
            if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r")):
                text = "'" + text
            cells.append(text)
        writer.writerow(cells)
    return output.getvalue()
