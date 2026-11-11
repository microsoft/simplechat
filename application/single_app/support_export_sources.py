# support_export_sources.py
"""Bounded support collectors with explicit subject/resource relationships."""

import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

from azure.core.exceptions import ResourceNotFoundError
from azure.monitor.query import LogsQueryClient, LogsQueryStatus

from collaboration_models import is_shared_conversation_backing
from cosmos_document_utils import normalize_cosmos_document
from functions_control_center_activity import ACTIVITY_ACTOR_FIELDS, cosmos_property_path
from functions_azure_endpoint_validation import validate_azure_monitor_query_endpoint
from functions_appinsights import log_event
from support_export_contracts import (
    MAX_RECORDS, check_size, fail, identifier, identity_hash, iso,
    normalize_configuration, timestamp, within_intervals,
)


CONVERSATION_FIELDS = (
    "c.id, c.user_id, c.created_at, c.created_date, c.last_updated, c.updated_at, "
    "c.last_message_at, c.message_count, c.conversation_kind, c.collaboration_conversation_id, "
    "c.converted_to_collaboration_at, c.group_id"
)
OMIT_PROPERTY_KEYS = {
    "headers", "requestheaders", "responseheaders", "settings", "configuration", "requestbody",
    "responsebody", "prompt", "systemprompt", "messages", "messagecontent", "documentcontent",
    "requestcontent", "responsecontent", "rawcontent", "body",
}


def build_support_monitor_client(configuration, credential, *, transport=None):
    configuration = normalize_configuration(configuration)
    origin = validate_azure_monitor_query_endpoint(
        "https://api.loganalytics.us" if configuration["cloud"] == "usgovernment"
        else "https://api.loganalytics.io",
    )
    # The pinned 1.4.1 SDK treats endpoint as the full /v1 base, not an origin.
    return LogsQueryClient(
        credential, endpoint=origin + "/v1", audience=origin,
        **({"transport": transport} if transport is not None else {}),
    )


INLINE_DATA = re.compile(r"data:[A-Za-z0-9.+/-]{1,120};base64,[A-Za-z0-9+/=]+", re.I)


def json_value(value, *, omit_payload=True):
    if isinstance(value, datetime):
        return iso(value if value.tzinfo else value.replace(tzinfo=timezone.utc))
    if isinstance(value, Mapping):
        return {
            str(key): json_value(item, omit_payload=omit_payload) for key, item in value.items()
            if not omit_payload or "".join(char for char in str(key).lower() if char.isalnum()) not in OMIT_PROPERTY_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [json_value(item, omit_payload=omit_payload) for item in value]
    if value is None or type(value) in (str, int, float, bool):
        return value
    fail("invalid_source_value", "A log source returned unsupported diagnostic data.", 422)


def _bounded_rows(container, query, parameters, *, partition=None, maximum=MAX_RECORDS, omit_payload=True):
    options = {"max_item_count": min(maximum + 1, 200)}
    if partition is None:
        options["enable_cross_partition_query"] = True
    else:
        options["partition_key"] = partition
    result = []
    byte_count = 0
    for row in container.query_items(query=query, parameters=parameters, **options):
        item = json_value(row, omit_payload=omit_payload)
        byte_count += len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
        check_size(len(result) + 1, byte_count)
        if len(result) >= maximum:
            fail("source_limit", "A source has too many matching records. Narrow the export.", 413)
        result.append(item)
    return result


def _metadata(record, kind):
    first = record.get("created_at") or record.get("created_date")
    last = record.get("last_message_at") or record.get("last_updated") or record.get("updated_at") or first
    personal = kind == "personal" and not (
        is_shared_conversation_backing(record) or record.get("collaboration_conversation_id")
        or record.get("converted_to_collaboration_at")
        or record.get("conversation_kind") in ("collaborative", "collaboration_source") or record.get("group_id")
    )
    return {
        "id": record["id"], "kind": "personal" if personal else ("shared" if kind == "personal" else kind),
        "first_activity": first, "last_activity": last, "message_count": record.get("message_count"),
        "transcript_eligible": personal,
    }


class SupportExportSources:
    def __init__(self, containers, *, monitor=None, authorize_shared=None, filter_messages=None):
        self.containers = containers
        self.monitor = monitor
        self.authorize_shared = authorize_shared
        self.filter_messages = filter_messages

    def require_registered_user(self, user_id):
        user_id = identifier(user_id)
        rows = _bounded_rows(
            self.containers["users"], "SELECT VALUE c.id FROM c WHERE c.id = @user",
            [{"name": "@user", "value": user_id}], partition=user_id, maximum=1,
        )
        if not rows:
            fail("subject_not_found", "The selected SimpleChat user is unavailable.", 404)

    def users(self, term="", after=""):
        if not isinstance(term, str) or len(term) > 200:
            fail("invalid_search", "Search text must be at most 200 characters.")
        if after:
            identifier(after)
        query = (
            "SELECT TOP 51 c.id, c.display_name, c.email, c.settings.displayName AS displayName, "
            "c.settings.display_name AS settings_name, c.settings.email AS settings_email "
            "FROM c WHERE c.id > @after AND ("
            "@term = '' OR CONTAINS(c.id, @term, true) OR CONTAINS(c.display_name, @term, true) "
            "OR CONTAINS(c.email, @term, true) OR CONTAINS(c.settings.displayName, @term, true) "
            "OR CONTAINS(c.settings.display_name, @term, true) OR CONTAINS(c.settings.email, @term, true)) ORDER BY c.id"
        )
        rows = _bounded_rows(
            self.containers["users"], query,
            [{"name": "@after", "value": after}, {"name": "@term", "value": term.strip()}], maximum=51,
        )
        return {
            "items": [{
                "id": row["id"], "name": row.get("display_name") or row.get("displayName")
                or row.get("settings_name") or row.get("email") or row["id"],
                "email": row.get("email") or row.get("settings_email") or "",
            } for row in rows[:50]],
            "next": rows[49]["id"] if len(rows) > 50 else None,
        }

    def _shared(self, user_id, conversation_id):
        states = _bounded_rows(
            self.containers["collaboration_states"],
            "SELECT TOP 1 c.conversation_id FROM c WHERE c.user_id = @user "
            "AND c.conversation_id = @id AND c.membership_status = 'accepted'",
            [{"name": "@user", "value": user_id}, {"name": "@id", "value": conversation_id}],
            partition=user_id, maximum=1,
        )
        if not states or self.authorize_shared is None:
            return None
        try:
            response = self.containers["collaboration"].read_item(item=conversation_id, partition_key=conversation_id)
        except ResourceNotFoundError:
            return None
        document = normalize_cosmos_document(response)
        try:
            self.authorize_shared(user_id, document)
        except (PermissionError, LookupError):
            log_event("[SUPPORT_EXPORT] Shared metadata is no longer accessible.", extra={"status": "not_accessible"}, debug_only=True)
            return None
        return document

    def conversations(self, user_id, *, after="", term=""):
        self.require_registered_user(user_id)
        if after:
            identifier(after)
        if not isinstance(term, str) or len(term) > 128:
            fail("invalid_search", "Search conversation IDs using at most 128 characters.")
        rows = {}
        frontiers = []
        parameters = [
            {"name": "@user", "value": user_id}, {"name": "@after", "value": after},
            {"name": "@term", "value": term},
        ]
        for kind, container in (("personal", "conversations"), ("group", "group_conversations")):
            records = _bounded_rows(
                self.containers[container],
                f"SELECT TOP 51 {CONVERSATION_FIELDS} FROM c WHERE c.user_id = @user "
                "AND c.id > @after AND (@term = '' OR CONTAINS(c.id, @term, true)) ORDER BY c.id",
                parameters, maximum=51,
            )
            if len(records) == 51:
                frontiers.append(records[-1]["id"])
            for record in records:
                rows[record["id"]] = _metadata(record, kind)
        states = _bounded_rows(
            self.containers["collaboration_states"],
            "SELECT TOP 51 c.conversation_id FROM c WHERE c.user_id = @user "
            "AND c.membership_status = 'accepted' AND c.conversation_id > @after "
            "AND (@term = '' OR CONTAINS(c.conversation_id, @term, true)) ORDER BY c.conversation_id",
            parameters, partition=user_id, maximum=51,
        )
        if len(states) == 51:
            frontiers.append(states[-1]["conversation_id"])
        for state in states:
            document = self._shared(user_id, state["conversation_id"])
            if document:
                rows[document["id"]] = _metadata(document, "shared")
        frontier = min(frontiers) if frontiers else None
        ordered = sorted(
            (row for row in rows.values() if frontier is None or row["id"] <= frontier),
            key=lambda row: row["id"],
        )
        return {"items": ordered[:50], "next": ordered[49]["id"] if len(ordered) > 50 else frontier}

    def conversation(self, user_id, conversation_id, *, bounds=False):
        self.require_registered_user(user_id)
        identifier(conversation_id)
        parameters = [{"name": "@id", "value": conversation_id}, {"name": "@user", "value": user_id}]
        matches = []
        for kind, container in (("personal", "conversations"), ("group", "group_conversations")):
            records = _bounded_rows(
                self.containers[container],
                f"SELECT TOP 1 {CONVERSATION_FIELDS} FROM c WHERE c.id = @id AND c.user_id = @user",
                parameters, partition=conversation_id, maximum=1,
            )
            matches.extend((_metadata(record, kind), "messages" if kind == "personal" else "group_messages") for record in records)
        shared = self._shared(user_id, conversation_id)
        if shared:
            matches = [(_metadata(shared, "shared"), "collaboration_messages")]
        if len(matches) != 1:
            fail("conversation_not_found", "A selected conversation is unavailable for this user.", 404)
        metadata, message_container = matches[0]
        if bounds:
            rows = _bounded_rows(
                self.containers[message_container],
                "SELECT MIN(c.timestamp) AS first_time, MAX(c.timestamp) AS last_time, COUNT(1) AS total "
                "FROM c WHERE c.conversation_id = @id AND IS_STRING(c.timestamp)",
                [{"name": "@id", "value": conversation_id}], partition=conversation_id, maximum=1,
            )
            if rows and rows[0].get("first_time"):
                metadata.update(
                    first_activity=rows[0]["first_time"], last_activity=rows[0]["last_time"],
                    message_count=rows[0]["total"],
                )
        return metadata

    def snapshot(self, user_id, conversation_ids, cutoff):
        snapshots = []
        count = size = 0
        for conversation_id in conversation_ids:
            metadata = self.conversation(user_id, conversation_id)
            if not metadata["transcript_eligible"]:
                fail("personal_only", "Only personal conversations can be released with owner consent.", 403)
            messages = _bounded_rows(
                self.containers["messages"],
                "SELECT * FROM c WHERE c.conversation_id = @id AND c.role IN ('user', 'assistant') "
                "ORDER BY c.timestamp",
                [{"name": "@id", "value": conversation_id}], partition=conversation_id,
                omit_payload=False,
            )
            if self.filter_messages is None:
                fail("transcript_filter_required", "Transcript availability checks are unavailable.", 503)
            messages = self.filter_messages(messages, user_id)
            visible = []
            for message in messages:
                if message.get("role") not in ("user", "assistant") or not message.get("timestamp"):
                    continue
                if timestamp(message["timestamp"], stored=True) > timestamp(cutoff):
                    continue
                content = message.get("content")
                metadata = message.get("metadata") or {}
                if any(metadata.get(key) is True for key in ("is_hidden", "is_internal", "hidden")):
                    continue
                if isinstance(content, list):
                    content = "\n\n".join(
                        part["text"] for part in content if isinstance(part, dict)
                        and part.get("type") in ("text", "input_text", "output_text") and isinstance(part.get("text"), str)
                    )
                if not isinstance(content, str) or content.startswith("data:") or message.get("message_type") == "image":
                    continue
                content = INLINE_DATA.sub("[Binary data omitted]", content)
                item = {
                    "id": message.get("id"), "role": message["role"],
                    "timestamp": message["timestamp"], "content": content,
                }
                count += 1
                size += len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
                check_size(count, size)
                visible.append(item)
            snapshots.append({"conversation_id": conversation_id, "messages": visible})
        return snapshots

    def collect_cosmos(self, source, plan, intervals, progress):
        first = timestamp(intervals[0][0]).date()
        last = timestamp(intervals[-1][1]).date() + timedelta(days=1)
        clauses = ["c.timestamp >= @start", "c.timestamp < @end"]
        parameters = [{"name": "@start", "value": first.isoformat()}, {"name": "@end", "value": last.isoformat()}]
        if not plan["all_users"]:
            actors = ACTIVITY_ACTOR_FIELDS if source == "activity" else ("user_id",)
            clauses.append("(" + " OR ".join(f"{cosmos_property_path(key)} = @user" for key in actors) + ")")
            parameters.append({"name": "@user", "value": plan["user_id"]})
        rows = _bounded_rows(
            self.containers[source], "SELECT * FROM c WHERE " + " AND ".join(clauses), parameters,
        )
        result = []
        for index, row in enumerate(rows):
            if index % 100 == 0:
                progress()
            if not within_intervals(row["timestamp"], intervals):
                continue
            conversation_id = row.get("conversation_id") or (row.get("conversation") or {}).get("id")
            if plan["conversation_ids"] and conversation_id and conversation_id not in plan["conversation_ids"]:
                continue
            properties = {key: item for key, item in row.items() if not key.startswith("_") and key not in ("id", "timestamp")}
            result.append({
                "timestamp": row["timestamp"], "source": source, "severity": "info",
                "message": row.get("log") or row.get("description") or row.get("activity_type") or "Activity",
                "properties": properties, "context_scope": "correlated",
            })
        return result

    def collect_monitor(self, source, configuration, plan, intervals, progress):
        if self.monitor is None:
            fail("monitor_not_configured", "Azure Monitor query access is not configured.", 503)
        resource = configuration["site_resource_id" if source == "console" else "app_resource_id"]
        table = (
            "AppServiceConsoleLogs" if source == "console"
            else "union isfuzzy=true withsource=SourceTable AppTraces, AppExceptions, AppRequests, AppDependencies, AppEvents"
        )
        windows = " or ".join(
            f"(TimeGenerated >= datetime({start}) and TimeGenerated < datetime({end}))" for start, end in intervals
        )
        base = (
            f"{table} | where tolower(_ResourceId) == tolower({json.dumps(resource)}) "
            f"| where {windows} "
            "| extend p=todynamic(column_ifexists('Properties', dynamic({}))) "
            "| extend u=tostring(p.sc_user_id_hash), c=tostring(p.sc_conversation_id_hash), "
            "lu=coalesce(tostring(p.sc_user_id), tostring(p.user_id)), "
            "lc=coalesce(tostring(p.sc_conversation_id), tostring(p.conversation_id)), "
            "op=tostring(column_ifexists('OperationId', ''))"
        )
        if plan["all_users"]:
            query = f"let b=({base}); b | extend ContextScope='correlated'"
        else:
            user = json.dumps(plan["user_id"])
            user_hash = json.dumps(identity_hash(plan["user_id"]))
            ids = json.dumps(plan["conversation_ids"])
            hashes = json.dumps([identity_hash(item) for item in plan["conversation_ids"]])
            subject = f"(u == {user_hash} or lu == {user})"
            selected = f"(c in (dynamic({hashes})) or lc in (dynamic({ids})))"
            no_user = "(isempty(u) and isempty(lu))"
            no_conversation = "(isempty(c) and isempty(lc))"
            anchor = f"({subject} or {selected})" if plan["conversation_ids"] else subject
            if plan["conversation_ids"]:
                anchor += f" and ({no_conversation} or {selected})"
            query = (
                f"let b=({base}); let a=(b | where {anchor}); "
                "let ops=(a | where isnotempty(op) | distinct op); "
                f"b | where ({anchor}) or (op in (ops) and ({no_user} or {subject}) "
                f"and ({no_conversation} or {selected}))"
            )
            if plan["include_system_context"]:
                query += f" or ({no_user} and {no_conversation})"
            query += f" | extend ContextScope=iff({anchor}, 'correlated', 'system_context')"
        query += (
            " | project TimeGenerated, ContextScope, "
            "Message=coalesce(tostring(p.sc_message), tostring(column_ifexists('Message', '')), "
            "tostring(column_ifexists('OuterMessage', '')), tostring(column_ifexists('ResultDescription', '')), "
            "tostring(column_ifexists('Name', ''))), "
            "Severity=tostring(column_ifexists('SeverityLevel', '')), "
            "Table=tostring(column_ifexists('SourceTable', 'AppServiceConsoleLogs')), Operation=op, Properties=p, "
            "Details=column_ifexists('Details', dynamic(null)), "
            "Success=column_ifexists('Success', bool(null)), Duration=column_ifexists('DurationMs', real(null)), "
            "ResultCode=tostring(column_ifexists('ResultCode', '')), Target=tostring(column_ifexists('Target', '')), "
            "ExceptionType=tostring(column_ifexists('ExceptionType', '')), "
            "RequestId=tostring(column_ifexists('Id', '')), ParentId=tostring(column_ifexists('ParentId', '')), "
            "Instance=tostring(column_ifexists('AppRoleInstance', '')) "
            f"| take {MAX_RECORDS + 1}"
        )
        progress()
        response = self.monitor.query_resource(
            resource, query,
            timespan=(timestamp(intervals[0][0]), timestamp(intervals[-1][1])), server_timeout=120,
        )
        if response.status != LogsQueryStatus.SUCCESS:
            fail("monitor_partial", "Azure Monitor returned incomplete results. Narrow the export and retry.", 503)
        result = []
        for table_result in response.tables:
            columns = [column if isinstance(column, str) else column.name for column in table_result.columns]
            for row in table_result.rows:
                check_size(len(result) + 1, 0)
                record = json_value(dict(zip(columns, row)))
                result.append({
                    "timestamp": record["TimeGenerated"], "source": source, "severity": record["Severity"],
                    "message": record["Message"], "context_scope": record["ContextScope"],
                    "properties": {
                        "table": record["Table"], "operation_id": record["Operation"],
                        "dimensions": record["Properties"], "exception": record["Details"],
                        "success": record["Success"], "duration_ms": record["Duration"],
                        "result_code": record["ResultCode"], "target": record["Target"],
                        "exception_type": record["ExceptionType"], "request_id": record["RequestId"],
                        "parent_id": record["ParentId"], "instance_id": record["Instance"],
                    },
                })
        progress()
        return result

    def probe_monitor(self, source, configuration):
        if self.monitor is None:
            fail("monitor_not_configured", "Azure Monitor query access is not configured.", 503)
        resource = configuration["site_resource_id" if source == "console" else "app_resource_id"]
        table = (
            "AppServiceConsoleLogs" if source == "console"
            else "union isfuzzy=true AppTraces, AppExceptions, AppRequests, AppDependencies, AppEvents"
        )
        response = self.monitor.query_resource(
            resource,
            f"{table} | where tolower(_ResourceId) == tolower({json.dumps(resource)}) | project TimeGenerated | take 1",
            timespan=timedelta(minutes=5), server_timeout=30,
        )
        if response.status != LogsQueryStatus.SUCCESS:
            fail("monitor_partial", "Azure Monitor access testing returned an incomplete result.", 503)
