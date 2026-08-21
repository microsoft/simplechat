# yamcs_plugin.py
"""Semantic Kernel plugin for read-only Yamcs mission control access."""

import itertools
import json
import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, List, Optional

from semantic_kernel.functions import kernel_function

from functions_appinsights import log_event
from functions_debug import debug_print
from functions_yamcs_operations import (
    YAMCS_ALLOWED_READ_STATEMENTS,
    YAMCS_AUTH_METHOD_API_KEY,
    YAMCS_AUTH_METHOD_BEARER_TOKEN,
    YAMCS_AUTH_METHOD_NONE,
    YAMCS_AUTH_METHOD_USERNAME_PASSWORD,
    YAMCS_DEFAULT_PROCESSOR,
    YAMCS_PLUGIN_TYPE,
    YAMCS_SUPPORTED_AUTH_METHODS,
    YAMCS_SUPPORTED_AUTH_TYPES,
    normalize_yamcs_additional_fields,
    normalize_yamcs_server_url,
)
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger


class YamcsPlugin(BasePlugin):
    """Yamcs connector plugin focused on read-only telemetry, MDB, and archive retrieval.

    Commanding is intentionally unsupported. This plugin never issues commands, writes
    parameter values, runs scripts, or changes data link state.
    """

    _SQL_COMMENT_PATTERN = re.compile(r"(--[^\r\n]*|/\*.*?\*/)", re.DOTALL)
    _FIRST_WORD_PATTERN = re.compile(r"^\s*([A-Za-z]+)", re.IGNORECASE)
    _LIMIT_PATTERN = re.compile(r"\blimit\b", re.IGNORECASE)
    _FORBIDDEN_READ_ONLY_PATTERN = re.compile(
        r"\b(ALTER|CREATE|DELETE|DROP|INSERT|LOAD|MERGE|SET|TRUNCATE|UPDATE|UPSERT)\b",
        re.IGNORECASE,
    )
    _SECRET_REDACTION_PATTERN = re.compile(
        r"(?i)(password|api\s*key|access\s*token|token|secret)\s*[=:]\s*[^\s,;]+"
    )

    def __init__(self, manifest: Optional[Dict[str, Any]] = None):
        super().__init__(manifest)
        self.manifest = manifest or {}
        self._metadata = self.manifest.get("metadata", {}) or {}
        self._auth = self.manifest.get("auth", {}) if isinstance(self.manifest.get("auth"), dict) else {}
        self.auth_type = str(self._auth.get("type") or "username_password").strip()
        self._additional_fields = normalize_yamcs_additional_fields(
            self.manifest.get("additionalFields", {}),
            auth_type=self.auth_type,
        )
        self.server_url = (
            normalize_yamcs_server_url(self.manifest.get("endpoint"))
            or self._additional_fields.get("server_url")
            or ""
        )
        self.instance = self._additional_fields.get("instance") or ""
        self.processor = self._additional_fields.get("processor") or YAMCS_DEFAULT_PROCESSOR
        self.auth_method = self._additional_fields.get("auth_method") or YAMCS_AUTH_METHOD_USERNAME_PASSWORD
        self.tls_verify = bool(self._additional_fields.get("tls_verify", True))
        self.enable_archive_sql = bool(self._additional_fields.get("enable_archive_sql", False))
        self.max_rows = int(self._additional_fields.get("max_rows") or 500)
        self.timeout = int(self._additional_fields.get("timeout") or 30)
        self.byte_limit = int(self._additional_fields.get("byte_limit") or 250000)
        self._validate_configuration()

    @property
    def display_name(self) -> str:
        return "Yamcs"

    @property
    def metadata(self) -> Dict[str, Any]:
        user_description = self._metadata.get(
            "description",
            "Yamcs mission control action using the official Yamcs Python client.",
        )
        description = (
            f"{user_description}\n\n"
            "This action reads telemetry, mission database definitions, and archived data from a "
            "Yamcs server so the agent can analyze spacecraft and ground segment state. "
            "It is strictly read-only: it cannot issue commands, set parameter values, run scripts, "
            "or enable/disable data links. Use list_instances and list_parameters to discover what "
            "is available before requesting values or history."
        )
        return {
            "name": self.manifest.get("name", "yamcs"),
            "type": YAMCS_PLUGIN_TYPE,
            "description": description,
            "methods": [
                {
                    "name": "list_instances",
                    "description": "List Yamcs instances available on the configured server.",
                    "parameters": [],
                    "returns": {"type": "dict", "description": "Instance names, states, and mission times."},
                },
                {
                    "name": "list_links",
                    "description": "List data links and their status for a Yamcs instance.",
                    "parameters": [
                        {"name": "instance", "type": "str", "description": "Optional Yamcs instance name.", "required": False},
                    ],
                    "returns": {"type": "dict", "description": "Link names, status, and packet counts."},
                },
                {
                    "name": "list_parameters",
                    "description": "List mission database parameters, optionally filtered by name text or parameter type.",
                    "parameters": [
                        {"name": "search", "type": "str", "description": "Optional case-insensitive text to match in the parameter name.", "required": False},
                        {"name": "parameter_type", "type": "str", "description": "Optional parameter type such as float or integer.", "required": False},
                        {"name": "instance", "type": "str", "description": "Optional Yamcs instance name.", "required": False},
                    ],
                    "returns": {"type": "dict", "description": "Parameter names, types, units, and descriptions."},
                },
                {
                    "name": "describe_parameter",
                    "description": "Describe a single mission database parameter, including type, units, and enumerations.",
                    "parameters": [
                        {"name": "parameter", "type": "str", "description": "Qualified XTCE name or NAMESPACE/NAME alias.", "required": True},
                        {"name": "instance", "type": "str", "description": "Optional Yamcs instance name.", "required": False},
                    ],
                    "returns": {"type": "dict", "description": "Parameter definition details."},
                },
                {
                    "name": "list_commands",
                    "description": "List mission database command definitions. This only describes commands and never issues them.",
                    "parameters": [
                        {"name": "search", "type": "str", "description": "Optional case-insensitive text to match in the command name.", "required": False},
                        {"name": "instance", "type": "str", "description": "Optional Yamcs instance name.", "required": False},
                    ],
                    "returns": {"type": "dict", "description": "Command names, significance, and argument definitions."},
                },
                {
                    "name": "get_parameter_values",
                    "description": "Get the latest processed values for one or more parameters.",
                    "parameters": [
                        {"name": "parameters", "type": "str", "description": "Comma-separated parameter names.", "required": True},
                        {"name": "instance", "type": "str", "description": "Optional Yamcs instance name.", "required": False},
                        {"name": "processor", "type": "str", "description": "Optional processor name.", "required": False},
                    ],
                    "returns": {"type": "dict", "description": "Engineering and raw values with monitoring status."},
                },
                {
                    "name": "list_parameter_history",
                    "description": "Read archived values for a parameter over a time range.",
                    "parameters": [
                        {"name": "parameter", "type": "str", "description": "Qualified XTCE name or NAMESPACE/NAME alias.", "required": True},
                        {"name": "start", "type": "str", "description": "Optional ISO-8601 start time.", "required": False},
                        {"name": "stop", "type": "str", "description": "Optional ISO-8601 stop time.", "required": False},
                        {"name": "instance", "type": "str", "description": "Optional Yamcs instance name.", "required": False},
                    ],
                    "returns": {"type": "dict", "description": "Time-ordered archived parameter values."},
                },
                {
                    "name": "list_events",
                    "description": "Read archived Yamcs events, optionally filtered by severity, source, or text.",
                    "parameters": [
                        {"name": "severity", "type": "str", "description": "Optional minimum severity such as warning or critical.", "required": False},
                        {"name": "source", "type": "str", "description": "Optional event source.", "required": False},
                        {"name": "text_filter", "type": "str", "description": "Optional text to match in the event message.", "required": False},
                        {"name": "start", "type": "str", "description": "Optional ISO-8601 start time.", "required": False},
                        {"name": "stop", "type": "str", "description": "Optional ISO-8601 stop time.", "required": False},
                        {"name": "instance", "type": "str", "description": "Optional Yamcs instance name.", "required": False},
                    ],
                    "returns": {"type": "dict", "description": "Archived events with severity, source, and message."},
                },
                {
                    "name": "list_packets",
                    "description": "Read archived telemetry packet metadata over a time range.",
                    "parameters": [
                        {"name": "name", "type": "str", "description": "Optional packet name.", "required": False},
                        {"name": "start", "type": "str", "description": "Optional ISO-8601 start time.", "required": False},
                        {"name": "stop", "type": "str", "description": "Optional ISO-8601 stop time.", "required": False},
                        {"name": "instance", "type": "str", "description": "Optional Yamcs instance name.", "required": False},
                    ],
                    "returns": {"type": "dict", "description": "Packet names, times, sizes, and links."},
                },
                {
                    "name": "list_alarms",
                    "description": "Read archived alarms over a time range.",
                    "parameters": [
                        {"name": "name", "type": "str", "description": "Optional alarm or parameter name.", "required": False},
                        {"name": "start", "type": "str", "description": "Optional ISO-8601 start time.", "required": False},
                        {"name": "stop", "type": "str", "description": "Optional ISO-8601 stop time.", "required": False},
                        {"name": "instance", "type": "str", "description": "Optional Yamcs instance name.", "required": False},
                    ],
                    "returns": {"type": "dict", "description": "Alarms with severity, trigger time, and acknowledgement state."},
                },
                {
                    "name": "execute_archive_sql",
                    "description": "Run a read-only Yamcs archive SQL statement. Disabled unless archive SQL is enabled on the action.",
                    "parameters": [
                        {"name": "statement", "type": "str", "description": "Read-only SELECT, SHOW, or DESCRIBE statement.", "required": True},
                        {"name": "instance", "type": "str", "description": "Optional Yamcs instance name.", "required": False},
                    ],
                    "returns": {"type": "dict", "description": "Columns and rows returned by the archive query."},
                },
            ],
        }

    def get_functions(self) -> List[str]:
        return [
            "list_instances",
            "list_links",
            "list_parameters",
            "describe_parameter",
            "list_commands",
            "get_parameter_values",
            "list_parameter_history",
            "list_events",
            "list_packets",
            "list_alarms",
            "execute_archive_sql",
        ]

    def _validate_configuration(self) -> None:
        if not self.server_url:
            raise ValueError("Yamcs action requires a server URL.")
        if not self.instance:
            raise ValueError("Yamcs action requires additionalFields.instance.")
        if self.auth_type not in YAMCS_SUPPORTED_AUTH_TYPES:
            raise ValueError(
                "Yamcs action supports auth.type values 'NoAuth', 'key', 'identity', or 'username_password'."
            )
        if self.auth_method not in YAMCS_SUPPORTED_AUTH_METHODS:
            raise ValueError(
                "Yamcs action supports auth methods username_password, api_key, bearer_token, or none."
            )
        if self.auth_type == "identity":
            if not (self._auth.get("identity") or self.manifest.get("identity_id")):
                raise ValueError("Yamcs reusable identity auth requires auth.identity or identity_id.")
            return
        if self.auth_method == YAMCS_AUTH_METHOD_USERNAME_PASSWORD:
            if not self._auth.get("identity"):
                raise ValueError("Yamcs username/password auth requires a username in auth.identity.")
            if not self._auth.get("key"):
                raise ValueError("Yamcs username/password auth requires a password in auth.key.")
        elif self.auth_method in {YAMCS_AUTH_METHOD_API_KEY, YAMCS_AUTH_METHOD_BEARER_TOKEN}:
            if not self._auth.get("key"):
                raise ValueError("Yamcs API key and bearer token auth require auth.key.")

    def _build_credentials(self):
        """Build a Yamcs credentials object for the configured auth method."""
        if self.auth_method == YAMCS_AUTH_METHOD_NONE:
            return None

        try:
            from yamcs.client import APIKeyCredentials, Credentials
        except ImportError as exc:
            raise ImportError(
                "Yamcs client library is not installed. Install yamcs-client to use Yamcs actions."
            ) from exc

        auth_key = str(self._auth.get("key") or "")
        if self.auth_method == YAMCS_AUTH_METHOD_API_KEY:
            return APIKeyCredentials(auth_key)
        if self.auth_method == YAMCS_AUTH_METHOD_BEARER_TOKEN:
            return Credentials(access_token=auth_key)
        return Credentials(username=str(self._auth.get("identity") or ""), password=auth_key)

    def _connect(self):
        try:
            from yamcs.client import YamcsClient
        except ImportError as exc:
            raise ImportError(
                "Yamcs client library is not installed. Install yamcs-client to use Yamcs actions."
            ) from exc

        debug_print(
            f"[YAMCS_PLUGIN] Opening Yamcs connection server_url={self.server_url} "
            f"instance={self.instance} processor={self.processor} auth_method={self.auth_method} "
            f"tls_verify={self.tls_verify} timeout={self.timeout}"
        )
        client = YamcsClient(
            self.server_url,
            credentials=self._build_credentials(),
            tls_verify=self.tls_verify,
            user_agent="SimpleChat",
        )
        # The Yamcs client wraps a requests.Session; apply the configured timeout to it so a
        # slow or unreachable ground segment cannot hang an agent turn indefinitely.
        session = getattr(getattr(client, "ctx", None), "session", None)
        if session is not None:
            session.request = self._with_timeout(session.request)
        return client

    def _with_timeout(self, request_callable: Callable) -> Callable:
        configured_timeout = self.timeout

        def request_with_timeout(*args, **kwargs):
            kwargs.setdefault("timeout", configured_timeout)
            return request_callable(*args, **kwargs)

        return request_with_timeout

    def _resolve_instance(self, instance: str = "") -> str:
        return str(instance or self.instance or "").strip()

    def _resolve_processor(self, processor: str = "") -> str:
        return str(processor or self.processor or YAMCS_DEFAULT_PROCESSOR).strip()

    def _parse_datetime(self, value: Any, field_name: str) -> Optional[datetime]:
        if value in [None, ""]:
            return None
        if isinstance(value, datetime):
            parsed = value
        else:
            raw_value = str(value).strip()
            normalized = raw_value[:-1] + "+00:00" if raw_value.endswith("Z") else raw_value
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError as exc:
                raise ValueError(f"{field_name} must be an ISO-8601 timestamp.") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _serialize_value(self, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, (date, time)):
            return value.isoformat()
        if isinstance(value, timedelta):
            return value.total_seconds()
        if isinstance(value, bytes):
            return value.hex()
        if isinstance(value, (list, tuple, set)):
            return [self._serialize_value(item) for item in value]
        if isinstance(value, dict):
            return {str(key): self._serialize_value(item) for key, item in value.items()}
        return str(value)

    def _extract(self, source: Any, attribute_names: Iterable[str]) -> Dict[str, Any]:
        """Read named attributes off a Yamcs model object, tolerating version differences."""
        extracted: Dict[str, Any] = {}
        for attribute_name in attribute_names:
            try:
                extracted[attribute_name] = self._serialize_value(getattr(source, attribute_name, None))
            except Exception:
                extracted[attribute_name] = None
        return extracted

    def _bounded(self, results: Iterable[Any], limit: Optional[int] = None) -> List[Any]:
        """Materialize at most `limit` items so a broad query cannot walk an entire archive."""
        max_items = limit if isinstance(limit, int) and limit > 0 else self.max_rows
        return list(itertools.islice(results, max_items))

    def _truncate_rows(self, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        serialized_rows = json.dumps(rows, default=str)
        if len(serialized_rows) <= self.byte_limit:
            return {"rows": rows, "truncated_by_bytes": False}

        trimmed_rows: List[Dict[str, Any]] = []
        current_size = 2
        for row in rows:
            row_size = len(json.dumps(row, default=str)) + 1
            if trimmed_rows and current_size + row_size > self.byte_limit:
                break
            trimmed_rows.append(row)
            current_size += row_size
        return {"rows": trimmed_rows or rows[:1], "truncated_by_bytes": True}

    def _success_rows(self, rows: List[Dict[str, Any]], requested_limit: int, **extra: Any) -> Dict[str, Any]:
        truncation = self._truncate_rows(rows)
        final_rows = truncation["rows"]
        payload = {
            "success": True,
            "server_url": self.server_url,
            "rows": final_rows,
            "row_count": len(final_rows),
            "truncated": bool(truncation["truncated_by_bytes"] or len(rows) >= requested_limit),
        }
        payload.update(extra)
        return payload

    def _safe_error_message(self, exc: Exception, fallback: str) -> str:
        raw_message = str(getattr(exc, "message", None) or exc or fallback)
        sanitized = self._SECRET_REDACTION_PATTERN.sub(r"\1=[REDACTED]", raw_message)
        return sanitized[:500] or fallback

    def _error_response(self, message: str, error_type: str = "validation", **extra: Any) -> Dict[str, Any]:
        payload = {
            "success": False,
            "error": message,
            "error_type": error_type,
        }
        payload.update(extra)
        return payload

    def _run(self, operation_name: str, operation: Callable[[Any], Dict[str, Any]]) -> Dict[str, Any]:
        """Open a Yamcs client, run a read-only operation, and normalize failures."""
        client = None
        try:
            client = self._connect()
            result = operation(client)
            debug_print(
                f"[YAMCS_PLUGIN] {operation_name} succeeded instance={self.instance} "
                f"row_count={result.get('row_count')} truncated={result.get('truncated')}"
            )
            return result
        except ValueError as exc:
            return self._error_response(str(exc), error_type="validation")
        except ImportError as exc:
            return self._error_response(str(exc), error_type="dependency")
        except Exception as exc:
            message = self._safe_error_message(exc, f"Yamcs {operation_name} failed.")
            debug_print(
                f"[YAMCS_PLUGIN] {operation_name} failed server_url={self.server_url} "
                f"instance={self.instance} exception_type={type(exc).__name__} message={message}"
            )
            log_event(
                f"[YAMCS_PLUGIN] Yamcs {operation_name} failed: {exc}",
                extra={
                    "server_url": self.server_url,
                    "instance": self.instance,
                    "operation": operation_name,
                    "plugin_name": self.manifest.get("name"),
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return self._error_response(message, error_type="yamcs", operation=operation_name)
        finally:
            if client is not None:
                try:
                    client.close()
                    debug_print("[YAMCS_PLUGIN] Yamcs connection closed.")
                except Exception:
                    pass

    def _first_word(self, statement: str) -> str:
        first_word_match = self._FIRST_WORD_PATTERN.match(statement or "")
        return first_word_match.group(1).upper() if first_word_match else ""

    def _validate_read_only_statement(self, statement: str) -> Optional[str]:
        normalized = self._SQL_COMMENT_PATTERN.sub(" ", str(statement or "")).strip()
        if not normalized:
            return "Yamcs archive SQL statement is required."

        statements = [part.strip() for part in normalized.split(";") if part.strip()]
        if len(statements) != 1:
            return "Only one Yamcs archive SQL statement can be executed at a time."

        first_word = self._first_word(statements[0])
        if first_word not in YAMCS_ALLOWED_READ_STATEMENTS:
            return f"Only read-only Yamcs archive SQL statements are allowed. Found: {first_word or 'UNKNOWN'}."

        forbidden_match = self._FORBIDDEN_READ_ONLY_PATTERN.search(statements[0])
        if forbidden_match:
            return f"Read-only mode blocks Yamcs archive SQL keyword: {forbidden_match.group(1).upper()}."
        return None

    def _apply_statement_limit(self, statement: str) -> str:
        stripped = str(statement or "").strip().rstrip(";")
        if self._first_word(stripped) == "SELECT" and not self._LIMIT_PATTERN.search(stripped):
            return f"{stripped} limit {self.max_rows}"
        return stripped

    @plugin_function_logger("YamcsPlugin")
    @kernel_function(description="List Yamcs instances available on the configured server.", name="list_instances")
    def list_instances(self) -> Dict[str, Any]:
        def operation(client):
            instances = self._bounded(client.list_instances())
            rows = [self._extract(item, ("name", "state", "failure_cause", "mission_time")) for item in instances]
            return self._success_rows(rows, self.max_rows)

        return self._run("list_instances", operation)

    @plugin_function_logger("YamcsPlugin")
    @kernel_function(description="List Yamcs data links and their status for an instance.", name="list_links")
    def list_links(self, instance: str = "") -> Dict[str, Any]:
        def operation(client):
            resolved_instance = self._resolve_instance(instance)
            links = self._bounded(client.list_links(resolved_instance))
            rows = [
                self._extract(item, ("name", "class_name", "enabled", "status", "in_count", "out_count"))
                for item in links
            ]
            return self._success_rows(rows, self.max_rows, instance=resolved_instance)

        return self._run("list_links", operation)

    @plugin_function_logger("YamcsPlugin")
    @kernel_function(
        description="List Yamcs mission database parameters, optionally filtered by name text or parameter type.",
        name="list_parameters",
    )
    def list_parameters(self, search: str = "", parameter_type: str = "", instance: str = "") -> Dict[str, Any]:
        def operation(client):
            resolved_instance = self._resolve_instance(instance)
            mdb = client.get_mdb(instance=resolved_instance)
            normalized_search = str(search or "").strip().lower()
            normalized_type = str(parameter_type or "").strip() or None
            parameters = mdb.list_parameters(parameter_type=normalized_type)
            if normalized_search:
                parameters = (
                    item
                    for item in parameters
                    if normalized_search in str(getattr(item, "qualified_name", "") or "").lower()
                    or normalized_search in str(getattr(item, "name", "") or "").lower()
                )
            rows = [
                self._extract(item, ("name", "qualified_name", "type", "units", "data_source", "description"))
                for item in self._bounded(parameters)
            ]
            return self._success_rows(rows, self.max_rows, instance=resolved_instance, search=normalized_search)

        return self._run("list_parameters", operation)

    @plugin_function_logger("YamcsPlugin")
    @kernel_function(
        description="Describe a single Yamcs mission database parameter, including type, units, and enumerations.",
        name="describe_parameter",
    )
    def describe_parameter(self, parameter: str, instance: str = "") -> Dict[str, Any]:
        def operation(client):
            parameter_name = str(parameter or "").strip()
            if not parameter_name:
                raise ValueError("Yamcs parameter name is required.")
            resolved_instance = self._resolve_instance(instance)
            mdb = client.get_mdb(instance=resolved_instance)
            found = mdb.get_parameter(parameter_name)
            details = self._extract(
                found,
                ("name", "qualified_name", "type", "units", "data_source", "description", "long_description", "aliases"),
            )
            details["enum_values"] = [
                self._extract(enum_value, ("value", "label", "description"))
                for enum_value in (getattr(found, "enum_values", None) or [])
            ]
            return {
                "success": True,
                "server_url": self.server_url,
                "instance": resolved_instance,
                "parameter": details,
            }

        return self._run("describe_parameter", operation)

    @plugin_function_logger("YamcsPlugin")
    @kernel_function(
        description="List Yamcs mission database command definitions. This describes commands only and never issues them.",
        name="list_commands",
    )
    def list_commands(self, search: str = "", instance: str = "") -> Dict[str, Any]:
        def operation(client):
            resolved_instance = self._resolve_instance(instance)
            mdb = client.get_mdb(instance=resolved_instance)
            normalized_search = str(search or "").strip().lower()
            commands = mdb.list_commands()
            if normalized_search:
                commands = (
                    item
                    for item in commands
                    if normalized_search in str(getattr(item, "qualified_name", "") or "").lower()
                    or normalized_search in str(getattr(item, "name", "") or "").lower()
                )
            rows = []
            for item in self._bounded(commands):
                row = self._extract(item, ("name", "qualified_name", "description", "abstract"))
                row["arguments"] = [
                    self._extract(argument, ("name", "description", "initial_value"))
                    for argument in (getattr(item, "arguments", None) or [])
                ]
                rows.append(row)
            return self._success_rows(rows, self.max_rows, instance=resolved_instance)

        return self._run("list_commands", operation)

    @plugin_function_logger("YamcsPlugin")
    @kernel_function(
        description="Get the latest processed values for one or more Yamcs parameters.",
        name="get_parameter_values",
    )
    def get_parameter_values(self, parameters: str, instance: str = "", processor: str = "") -> Dict[str, Any]:
        def operation(client):
            requested = [name.strip() for name in str(parameters or "").split(",") if name.strip()]
            if not requested:
                raise ValueError("At least one Yamcs parameter name is required.")
            requested = requested[: self.max_rows]

            resolved_instance = self._resolve_instance(instance)
            resolved_processor = self._resolve_processor(processor)
            processor_client = client.get_processor(instance=resolved_instance, processor=resolved_processor)
            values = processor_client.get_parameter_values(requested, from_cache=True)

            rows = []
            for requested_name, value in zip(requested, values or []):
                if value is None:
                    rows.append({"name": requested_name, "available": False})
                    continue
                row = self._extract(
                    value,
                    ("name", "generation_time", "reception_time", "eng_value", "raw_value", "monitoring_result", "validity_status"),
                )
                row["requested_name"] = requested_name
                row["available"] = True
                rows.append(row)

            return self._success_rows(
                rows,
                len(requested),
                instance=resolved_instance,
                processor=resolved_processor,
            )

        return self._run("get_parameter_values", operation)

    @plugin_function_logger("YamcsPlugin")
    @kernel_function(
        description="Read archived Yamcs values for a parameter over a time range.",
        name="list_parameter_history",
    )
    def list_parameter_history(
        self,
        parameter: str,
        start: str = "",
        stop: str = "",
        instance: str = "",
    ) -> Dict[str, Any]:
        def operation(client):
            parameter_name = str(parameter or "").strip()
            if not parameter_name:
                raise ValueError("Yamcs parameter name is required.")
            start_time = self._parse_datetime(start, "start")
            stop_time = self._parse_datetime(stop, "stop")
            resolved_instance = self._resolve_instance(instance)
            archive = client.get_archive(instance=resolved_instance)
            values = archive.list_parameter_values(
                parameter_name,
                start=start_time,
                stop=stop_time,
                page_size=min(self.max_rows, 500),
                descending=True,
            )
            rows = [
                self._extract(
                    item,
                    ("generation_time", "reception_time", "eng_value", "raw_value", "monitoring_result", "validity_status"),
                )
                for item in self._bounded(values)
            ]
            return self._success_rows(
                rows,
                self.max_rows,
                instance=resolved_instance,
                parameter=parameter_name,
            )

        return self._run("list_parameter_history", operation)

    @plugin_function_logger("YamcsPlugin")
    @kernel_function(
        description="Read archived Yamcs events, optionally filtered by severity, source, or message text.",
        name="list_events",
    )
    def list_events(
        self,
        severity: str = "",
        source: str = "",
        text_filter: str = "",
        start: str = "",
        stop: str = "",
        instance: str = "",
    ) -> Dict[str, Any]:
        def operation(client):
            start_time = self._parse_datetime(start, "start")
            stop_time = self._parse_datetime(stop, "stop")
            resolved_instance = self._resolve_instance(instance)
            archive = client.get_archive(instance=resolved_instance)
            events = archive.list_events(
                source=str(source or "").strip() or None,
                severity=str(severity or "").strip() or None,
                text_filter=str(text_filter or "").strip() or None,
                start=start_time,
                stop=stop_time,
                page_size=min(self.max_rows, 500),
                descending=True,
            )
            rows = [
                self._extract(
                    item,
                    ("generation_time", "reception_time", "severity", "message", "event_type", "source", "sequence_number"),
                )
                for item in self._bounded(events)
            ]
            return self._success_rows(rows, self.max_rows, instance=resolved_instance)

        return self._run("list_events", operation)

    @plugin_function_logger("YamcsPlugin")
    @kernel_function(
        description="Read archived Yamcs telemetry packet metadata over a time range.",
        name="list_packets",
    )
    def list_packets(
        self,
        name: str = "",
        start: str = "",
        stop: str = "",
        instance: str = "",
    ) -> Dict[str, Any]:
        def operation(client):
            start_time = self._parse_datetime(start, "start")
            stop_time = self._parse_datetime(stop, "stop")
            resolved_instance = self._resolve_instance(instance)
            archive = client.get_archive(instance=resolved_instance)
            packets = archive.list_packets(
                name=str(name or "").strip() or None,
                start=start_time,
                stop=stop_time,
                page_size=min(self.max_rows, 500),
                descending=True,
            )
            rows = [
                self._extract(
                    item,
                    ("name", "generation_time", "reception_time", "sequence_number", "link", "size"),
                )
                for item in self._bounded(packets)
            ]
            return self._success_rows(rows, self.max_rows, instance=resolved_instance)

        return self._run("list_packets", operation)

    @plugin_function_logger("YamcsPlugin")
    @kernel_function(description="Read archived Yamcs alarms over a time range.", name="list_alarms")
    def list_alarms(
        self,
        name: str = "",
        start: str = "",
        stop: str = "",
        instance: str = "",
    ) -> Dict[str, Any]:
        def operation(client):
            start_time = self._parse_datetime(start, "start")
            stop_time = self._parse_datetime(stop, "stop")
            resolved_instance = self._resolve_instance(instance)
            archive = client.get_archive(instance=resolved_instance)
            alarms = archive.list_alarms(
                name=str(name or "").strip() or None,
                start=start_time,
                stop=stop_time,
                page_size=min(self.max_rows, 500),
                descending=True,
            )
            rows = [
                self._extract(
                    item,
                    ("name", "severity", "trigger_time", "update_time", "is_acknowledged", "acknowledged_by", "violation_count", "count"),
                )
                for item in self._bounded(alarms)
            ]
            return self._success_rows(rows, self.max_rows, instance=resolved_instance)

        return self._run("list_alarms", operation)

    @plugin_function_logger("YamcsPlugin")
    @kernel_function(
        description="Run a read-only Yamcs archive SQL statement. Disabled unless archive SQL is enabled on this action.",
        name="execute_archive_sql",
    )
    def execute_archive_sql(self, statement: str, instance: str = "") -> Dict[str, Any]:
        if not self.enable_archive_sql:
            return self._error_response(
                "Yamcs archive SQL is disabled for this action. Enable it in the action configuration to use this function.",
                error_type="disabled",
            )

        validation_error = self._validate_read_only_statement(statement)
        if validation_error:
            return self._error_response(validation_error, error_type="validation")

        bounded_statement = self._apply_statement_limit(statement)

        def operation(client):
            resolved_instance = self._resolve_instance(instance)
            archive = client.get_archive(instance=resolved_instance)
            result_set = archive.execute_sql(bounded_statement)
            fetched = self._bounded(result_set)
            columns = [
                str(getattr(column, "name", column))
                for column in (getattr(result_set, "columns", None) or [])
            ]
            rows = []
            for row in fetched:
                if isinstance(row, dict):
                    rows.append({str(key): self._serialize_value(value) for key, value in row.items()})
                elif columns:
                    rows.append(
                        {
                            column: self._serialize_value(row[index] if index < len(row) else None)
                            for index, column in enumerate(columns)
                        }
                    )
                else:
                    rows.append({"value": self._serialize_value(row)})
            return self._success_rows(
                rows,
                self.max_rows,
                instance=resolved_instance,
                statement=bounded_statement,
                columns=columns,
            )

        return self._run("execute_archive_sql", operation)
