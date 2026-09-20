# msgraph_plugin.py

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from azure.core.exceptions import AzureError

from functions_authentication import get_current_user_info
from functions_m365_approvals import M365ApprovalRequired, M365PolicyError
from functions_m365_operations import (
    M365_INTERNAL_OPERATION_FUNCTIONS,
    M365_SELECTED_RESOURCE_SOURCES,
    get_m365_action_definition,
    get_m365_enabled_function_names,
    get_m365_operation_source,
    guarded_m365_operation,
    is_m365_action_type,
    normalize_m365_action_config,
)
from functions_m365_transport import (
    M365ProviderError,
    M365Transport,
    authorize_m365_capability,
    authorize_m365_source,
    get_m365_context,
    log_m365_failure,
)
from semantic_kernel.functions import kernel_function
from semantic_kernel.functions.kernel_plugin import KernelPlugin
from functions_group import assert_group_role, find_group_by_id, require_active_group
from functions_msgraph_operations import (
    MSGRAPH_CALENDAR_SEND_MODE_AUTO_SEND,
    MSGRAPH_CALENDAR_SEND_MODE_DRAFT_DELAYED,
    MSGRAPH_CALENDAR_SEND_MODE_DRAFT_MANUAL,
    MSGRAPH_CAPABILITY_DEFINITIONS,
    MSGRAPH_DEFAULT_ENDPOINT,
    MSGRAPH_MAIL_SEND_MODE_AUTO_SEND,
    MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED,
    MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL,
    MSGRAPH_PLUGIN_TYPE,
    get_msgraph_enabled_function_names,
    normalize_msgraph_calendar_send_options,
    normalize_msgraph_mail_send_options,
    normalize_msgraph_capabilities,
)
from functions_msgraph_pending_actions import (
    MSGRAPH_PENDING_ACTION_DELAYED,
    MSGRAPH_PENDING_ACTION_MANUAL,
    MSGRAPH_PENDING_OPERATION_CREATE_CALENDAR_INVITE,
    MSGRAPH_PENDING_OPERATION_SEND_MAIL,
    MSGRAPH_PENDING_RESOURCE_CALENDAR,
    MSGRAPH_PENDING_RESOURCE_MAIL,
    MSGRAPH_PENDING_STATUS_PENDING,
    MSGRAPH_PENDING_STATUS_SCHEDULED,
    build_calendar_pending_action_summary,
    build_mail_pending_action_summary,
    create_msgraph_pending_action,
    sanitize_msgraph_pending_action_for_client,
    schedule_msgraph_pending_action_auto_commit,
)
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger


class MSGraphPlugin(BasePlugin):
    ACTION_TYPE = MSGRAPH_PLUGIN_TYPE
    DEFAULT_ENDPOINT = MSGRAPH_DEFAULT_ENDPOINT
    DEFAULT_TIMEOUT_SECONDS = 30
    MAX_ITEMS_PER_RESULT = 25
    MAX_PAGES_PER_REQUEST = 5
    DEFERRED_DELIVERY_EXTENDED_PROPERTY_ID = "SystemTime 0x000F"

    def __init__(self, manifest: Optional[Dict[str, Any]] = None):
        super().__init__(manifest)
        self._action_type = self.ACTION_TYPE
        if self._action_type == MSGRAPH_PLUGIN_TYPE and is_m365_action_type((manifest or {}).get("type")):
            self._action_type = manifest["type"]
        self.manifest = (
            normalize_m365_action_config(self._action_type, manifest)
            if is_m365_action_type(self._action_type)
            else manifest or {}
        )
        self._metadata = self.manifest.get("metadata", {})
        self._transports = {}
        additional_fields = self.manifest.get("additionalFields") if isinstance(self.manifest.get("additionalFields"), dict) else {}
        if is_m365_action_type(self._action_type):
            self._capabilities = {
                definition["function_name"]: self.manifest["m365_capabilities"].get(definition["function_name"], False)
                for definition in MSGRAPH_CAPABILITY_DEFINITIONS
            }
        else:
            self._capabilities = normalize_msgraph_capabilities(
                self.manifest.get("msgraph_capabilities", additional_fields.get("msgraph_capabilities"))
            )
        mail_send_options = normalize_msgraph_mail_send_options({
            **additional_fields,
            "msgraph_mail_send_mode": self.manifest.get(
                "msgraph_mail_send_mode",
                additional_fields.get("msgraph_mail_send_mode"),
            ),
            "msgraph_mail_delay_seconds": self.manifest.get(
                "msgraph_mail_delay_seconds",
                additional_fields.get("msgraph_mail_delay_seconds"),
            ),
        })
        self._mail_send_mode = mail_send_options["msgraph_mail_send_mode"]
        self._mail_delay_seconds = mail_send_options["msgraph_mail_delay_seconds"]
        calendar_send_options = normalize_msgraph_calendar_send_options({
            **additional_fields,
            "msgraph_calendar_send_mode": self.manifest.get(
                "msgraph_calendar_send_mode",
                additional_fields.get("msgraph_calendar_send_mode"),
            ),
            "msgraph_calendar_delay_seconds": self.manifest.get(
                "msgraph_calendar_delay_seconds",
                additional_fields.get("msgraph_calendar_delay_seconds"),
            ),
        })
        self._calendar_send_mode = calendar_send_options["msgraph_calendar_send_mode"]
        self._calendar_delay_seconds = calendar_send_options["msgraph_calendar_delay_seconds"]
        if is_m365_action_type(self._action_type):
            self._enabled_function_names = set(get_m365_enabled_function_names(self._action_type, self.manifest))
        else:
            allowed_functions = set(get_msgraph_enabled_function_names(self._capabilities))
            configured_functions = self.manifest.get("enabled_functions")
            self._enabled_function_names = (
                allowed_functions.intersection(configured_functions)
                if isinstance(configured_functions, (list, tuple, set))
                else allowed_functions
            )
        self._default_group_id = str(
            self.manifest.get("group_id") or self.manifest.get("default_group_id") or ""
        ).strip()

    @property
    def display_name(self) -> str:
        if is_m365_action_type(self._action_type):
            return get_m365_action_definition(self._action_type)["display_name"]
        return "Microsoft Graph"

    @property
    def _endpoint(self) -> str:
        return self._transport_for_operation("").cloud.resource_url

    def _transport_for_operation(self, operation_name):
        source = get_m365_operation_source(operation_name, self._action_type)
        return self._transport_for_source(source)

    def _transport_for_source(self, source):
        if source not in self._transports:
            additional = self.manifest.get("additionalFields") or {}
            self._transports[source] = M365Transport(
                source,
                self.manifest.get("id") or self.manifest.get("name") or "",
                {
                    "maximum_sharing_acknowledgement": self.manifest.get(
                        "maximum_sharing_acknowledgement",
                        additional.get("maximum_sharing_acknowledgement", "always"),
                    ),
                },
                action_type=self._action_type,
            )
        return self._transports[source]

    def _operation_context(self, operation_name):
        return self._transport_for_operation(operation_name).operation_context(operation_name)

    def _authorize_operation(self, operation_name, select_fields=""):
        function_name = M365_INTERNAL_OPERATION_FUNCTIONS.get(operation_name, operation_name)
        if function_name not in self._enabled_function_names or not self._capabilities.get(function_name, False):
            return {
                "error": "function_not_enabled",
                "message": "This function is not enabled for this Microsoft 365 action.",
                "operation": operation_name,
            }
        source = get_m365_operation_source(operation_name, self._action_type)
        if is_m365_action_type(self._action_type) and source is None:
            return {
                "error": "source_not_allowed",
                "message": "This function belongs to a different Microsoft 365 source.",
                "operation": operation_name,
            }
        sources = {source} if source else set()
        if isinstance(select_fields, str):
            selected_resources = {
                segment.strip().lower()
                for field in select_fields.split(",") for segment in field.split("/")
            }
            for resource in selected_resources.intersection(M365_SELECTED_RESOURCE_SOURCES):
                selected_source, selected_function = M365_SELECTED_RESOURCE_SOURCES[resource]
                if (
                    selected_source != source
                    or selected_function not in self._enabled_function_names
                    or not self._capabilities.get(selected_function, False)
                ):
                    return {
                        "error": "source_not_allowed",
                        "message": "These selected fields belong to a source or capability unavailable to this action.",
                        "operation": operation_name,
                    }
                sources.add(selected_source)
        if not sources:
            try:
                authorize_m365_capability(
                    self.manifest.get("id") or self.manifest.get("name") or "",
                    function_name, self._action_type,
                )
            except M365ApprovalRequired:
                raise
            except M365PolicyError as exc:
                return self._policy_error_result(exc, operation_name)
            except M365ProviderError as exc:
                log_m365_failure(exc.code, operation=operation_name)
                return {"error": exc.code, "message": exc.message, "operation": operation_name}
        for required_source in sorted(sources):
            transport = self._transport_for_source(required_source)
            try:
                authorize_m365_source(
                    required_source, transport.action_id, transport.action_policy,
                    operation_name=function_name, action_type=self._action_type,
                )
            except M365ApprovalRequired:
                raise
            except M365PolicyError as exc:
                return self._policy_error_result(exc, operation_name, required_source)
            except M365ProviderError as exc:
                log_m365_failure(exc.code, source=required_source, operation=operation_name)
                return {
                    "error": exc.code, "message": exc.message,
                    "operation": operation_name, "source": required_source,
                    **exc.details,
                }
        return None

    def _policy_error_result(self, error, operation_name, source=None):
        log_m365_failure(error.code, source=source or "", operation=operation_name)
        return {**error.payload, "operation": operation_name, "source": source, "provider": "graph"}

    @property
    def metadata(self) -> Dict[str, Any]:
        enabled_methods = set(self.get_functions())
        method_specs = {
            "get_my_profile": {
                "name": "get_my_profile",
                "description": "Get the signed-in user's profile details.",
                "parameters": [
                    {
                        "name": "select_fields",
                        "type": "str",
                        "description": "Optional comma-separated Graph fields to include.",
                        "required": False,
                    }
                ],
                "returns": {"type": "dict", "description": "User profile information from Microsoft Graph."},
            },
            "get_my_timezone": {
                "name": "get_my_timezone",
                "description": "Get the signed-in user's Microsoft 365 mailbox time zone and related formatting settings. Use this before answering timezone-sensitive questions.",
                "parameters": [],
                "returns": {"type": "dict", "description": "Mailbox timezone, date format, and time format settings from Microsoft Graph."},
            },
            "get_my_events": {
                "name": "get_my_events",
                "description": "Get upcoming calendar events for the signed-in user.",
                "parameters": [
                    {"name": "top", "type": "int", "description": "Maximum number of events to return.", "required": False},
                    {
                        "name": "start_datetime",
                        "type": "str",
                        "description": "Optional ISO datetime. If provided with end_datetime, uses calendarView.",
                        "required": False,
                    },
                    {
                        "name": "end_datetime",
                        "type": "str",
                        "description": "Optional ISO datetime. If provided with start_datetime, uses calendarView.",
                        "required": False,
                    },
                    {
                        "name": "select_fields",
                        "type": "str",
                        "description": "Optional comma-separated Graph fields to include.",
                        "required": False,
                    },
                ],
                "returns": {"type": "dict", "description": "Calendar event results from Microsoft Graph."},
            },
            "create_calendar_invite": {
                "name": "create_calendar_invite",
                "description": "Create a calendar invite for the signed-in user, optionally add current group members as attendees, and turn it into a Microsoft Teams meeting.",
                "parameters": [
                    {"name": "subject", "type": "str", "description": "Subject for the calendar invite.", "required": True},
                    {"name": "start_datetime", "type": "str", "description": "Event start as an ISO 8601 datetime string.", "required": True},
                    {"name": "end_datetime", "type": "str", "description": "Event end as an ISO 8601 datetime string.", "required": True},
                    {"name": "body_content", "type": "str", "description": "Optional plain-text body content for the invite.", "required": False},
                    {"name": "location", "type": "str", "description": "Optional location display name.", "required": False},
                    {"name": "attendee_emails", "type": "str", "description": "Optional attendee emails separated by commas, semicolons, or new lines.", "required": False},
                    {"name": "include_group_members", "type": "bool", "description": "If true, include current group members as required attendees.", "required": False},
                    {"name": "group_id", "type": "str", "description": "Optional group id to use when include_group_members is true. Defaults to the action or active group context.", "required": False},
                    {"name": "make_teams_meeting", "type": "bool", "description": "If true, create the invite as a Microsoft Teams meeting.", "required": False},
                    {"name": "timezone", "type": "str", "description": "Optional Outlook time zone name for the event. Defaults to the user's mailbox time zone or UTC.", "required": False},
                    {"name": "allow_new_time_proposals", "type": "bool", "description": "If true, attendees can propose a new time.", "required": False},
                ],
                "returns": {"type": "dict", "description": "Created event result from Microsoft Graph."},
            },
            "get_my_messages": {
                "name": "get_my_messages",
                "description": "Get recent mail messages for the signed-in user.",
                "parameters": [
                    {"name": "top", "type": "int", "description": "Maximum number of messages to return.", "required": False},
                    {"name": "folder", "type": "str", "description": "Optional mail folder name, such as inbox.", "required": False},
                    {"name": "unread_only", "type": "bool", "description": "If true, only unread messages are returned.", "required": False},
                    {
                        "name": "select_fields",
                        "type": "str",
                        "description": "Optional comma-separated Graph fields to include.",
                        "required": False,
                    },
                ],
                "returns": {"type": "dict", "description": "Mail message results from Microsoft Graph."},
            },
            "mark_message_as_read": {
                "name": "mark_message_as_read",
                "description": "Mark a mail message as read or unread for the signed-in user. Requires Mail.ReadWrite delegated permission.",
                "parameters": [
                    {
                        "name": "message_id",
                        "type": "str",
                        "description": "Microsoft Graph message id to update.",
                        "required": True,
                    },
                    {
                        "name": "is_read",
                        "type": "bool",
                        "description": "If true, marks the message as read. If false, marks it as unread.",
                        "required": False,
                    },
                ],
                "returns": {"type": "dict", "description": "Updated mail message result from Microsoft Graph."},
            },
            "send_mail": {
                "name": "send_mail",
                "description": "Create or send an email from the signed-in user's mailbox using this action's configured delivery mode: manual draft, delayed delivery, or automatic send.",
                "parameters": [
                    {
                        "name": "to_recipients",
                        "type": "str",
                        "description": "Required recipient email addresses separated by commas, semicolons, or new lines.",
                        "required": True,
                    },
                    {"name": "subject", "type": "str", "description": "Email subject.", "required": True},
                    {"name": "body_content", "type": "str", "description": "Plain-text email body content.", "required": False},
                    {
                        "name": "cc_recipients",
                        "type": "str",
                        "description": "Optional CC recipient email addresses separated by commas, semicolons, or new lines.",
                        "required": False,
                    },
                    {
                        "name": "bcc_recipients",
                        "type": "str",
                        "description": "Optional BCC recipient email addresses separated by commas, semicolons, or new lines.",
                        "required": False,
                    },
                    {
                        "name": "save_to_sent_items",
                        "type": "bool",
                        "description": "For automatic send mode, save the message to Sent Items when true.",
                        "required": False,
                    },
                ],
                "returns": {"type": "dict", "description": "Draft or send status from Microsoft Graph."},
            },
            "search_users": {
                "name": "search_users",
                "description": "Search directory users by name or email prefix.",
                "parameters": [
                    {"name": "query", "type": "str", "description": "Search text for display name or email.", "required": True},
                    {"name": "top", "type": "int", "description": "Maximum number of users to return.", "required": False},
                    {
                        "name": "select_fields",
                        "type": "str",
                        "description": "Optional comma-separated Graph fields to include.",
                        "required": False,
                    },
                ],
                "returns": {"type": "dict", "description": "Matching users from Microsoft Graph."},
            },
            "get_user_by_email": {
                "name": "get_user_by_email",
                "description": "Get a directory user by exact email address or UPN.",
                "parameters": [
                    {"name": "email", "type": "str", "description": "Exact email address or user principal name.", "required": True},
                    {
                        "name": "select_fields",
                        "type": "str",
                        "description": "Optional comma-separated Graph fields to include.",
                        "required": False,
                    },
                ],
                "returns": {"type": "dict", "description": "User match information from Microsoft Graph."},
            },
            "list_drive_items": {
                "name": "list_drive_items",
                "description": "List OneDrive items from the root or a child path for the signed-in user.",
                "parameters": [
                    {"name": "path", "type": "str", "description": "Optional path below the drive root.", "required": False},
                    {"name": "top", "type": "int", "description": "Maximum number of items to return.", "required": False},
                    {
                        "name": "select_fields",
                        "type": "str",
                        "description": "Optional comma-separated Graph fields to include.",
                        "required": False,
                    },
                ],
                "returns": {"type": "dict", "description": "Drive item results from Microsoft Graph."},
            },
            "get_my_security_alerts": {
                "name": "get_my_security_alerts",
                "description": "Get recent security alerts for the signed-in user. Requires elevated Graph permissions.",
                "parameters": [
                    {"name": "top", "type": "int", "description": "Maximum number of alerts to return.", "required": False}
                ],
                "returns": {"type": "dict", "description": "Security alert results from Microsoft Graph."},
            },
        }

        return {
            "name": self.manifest.get(
                "name", self._action_type if is_m365_action_type(self._action_type) else "msgraph_plugin",
            ),
            "type": self._action_type,
            "source": get_m365_action_definition(self._action_type)["source"] if is_m365_action_type(self._action_type) else None,
            "description": get_m365_action_definition(self._action_type)["description"] if is_m365_action_type(self._action_type) else (
                "Plugin for interacting with Microsoft Graph API. Supports user profile, "
                "calendar reads and invite creation, mailbox timezone settings, mail, directory, "
                "drive, and security alert operations."
            ),
            "methods": [
                method_specs[definition["function_name"]]
                for definition in MSGRAPH_CAPABILITY_DEFINITIONS
                if definition["function_name"] in enabled_methods
            ],
        }

    def get_functions(self) -> List[str]:
        type_functions = (
            {definition["function_name"] for definition in get_m365_action_definition(self._action_type)["capabilities"]}
            if is_m365_action_type(self._action_type)
            else {definition["function_name"] for definition in MSGRAPH_CAPABILITY_DEFINITIONS}
        )
        return [
            definition["function_name"]
            for definition in MSGRAPH_CAPABILITY_DEFINITIONS
            if definition["function_name"] in self._enabled_function_names
            and definition["function_name"] in type_functions
            and self._capabilities.get(definition["function_name"], False)
        ]

    def get_kernel_plugin(self, plugin_name: str = "msgraph") -> KernelPlugin:
        functions = {}
        for function_name in self.get_functions():
            bound_method = getattr(self, function_name, None)
            if callable(bound_method) and hasattr(bound_method, "__kernel_function__"):
                functions[function_name] = bound_method

        return KernelPlugin.from_object(
            plugin_name,
            functions,
            description=self.metadata.get("description"),
        )

    def _get_scopes(self, operation_name: str, default_scopes: List[str]) -> List[str]:
        return default_scopes

    def _get_token(self, operation_name: str, default_scopes: List[str]) -> Tuple[Optional[str], List[str], Optional[Dict[str, Any]]]:
        denial = self._authorize_operation(operation_name)
        if denial:
            return None, default_scopes, denial
        try:
            token, scopes = self._transport_for_operation(operation_name).get_token(default_scopes)
            return token, scopes, None
        except M365ApprovalRequired:
            raise
        except M365PolicyError as exc:
            return None, default_scopes, self._policy_error_result(
                exc, operation_name, get_m365_operation_source(operation_name, self._action_type),
            )
        except M365ProviderError as exc:
            log_m365_failure(exc.code, operation=operation_name)
            return None, default_scopes, {
                "error": exc.code, "message": exc.message,
                "operation": operation_name, "scopes": default_scopes,
                **exc.details,
            }

    def _invalid_parameter_error(self, operation_name: str, message: str) -> Dict[str, Any]:
        return {
            "error": "invalid_parameters",
            "message": message,
            "operation": operation_name,
        }

    def _normalize_boolean_parameter(
        self,
        value: Any,
        parameter_name: str,
        operation_name: str,
    ) -> Tuple[Optional[bool], Optional[Dict[str, Any]]]:
        if isinstance(value, bool):
            return value, None

        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value), None

        if isinstance(value, str):
            lowered_value = value.strip().lower()
            if lowered_value in {"true", "1", "yes"}:
                return True, None
            if lowered_value in {"false", "0", "no"}:
                return False, None

        return None, self._invalid_parameter_error(
            operation_name,
            f"{parameter_name} must be a boolean value.",
        )

    def _resolve_event_timezone(self, timezone_value: str = "") -> str:
        normalized_timezone = str(timezone_value or "").strip()
        if normalized_timezone:
            return normalized_timezone

        mailbox_settings = self._perform_graph_request(
            "resolve_calendar_timezone",
            "GET",
            "/v1.0/me/mailboxSettings",
            ["MailboxSettings.Read"],
        )
        if isinstance(mailbox_settings, dict) and mailbox_settings.get("error"):
            raise M365ProviderError(
                str(mailbox_settings["error"]),
                "The mailbox timezone could not be read. Resolve Microsoft 365 access or supply an explicit timezone.",
            )
        if isinstance(mailbox_settings, dict) and not mailbox_settings.get("error"):
            mailbox_timezone = str(mailbox_settings.get("timeZone") or "").strip()
            if mailbox_timezone:
                return mailbox_timezone

        return "UTC"

    def _add_attendee_candidate(
        self,
        attendees_by_email: Dict[str, Dict[str, Any]],
        invalid_entries: List[str],
        email: str,
        name: str = "",
        attendee_type: str = "required",
        current_user_email: str = "",
        strict: bool = True,
    ) -> bool:
        normalized_email = str(email or "").strip()
        if not normalized_email:
            return False

        lowered_email = normalized_email.lower()
        if current_user_email and lowered_email == current_user_email.lower():
            return False

        if "@" not in normalized_email:
            if strict:
                invalid_entries.append(normalized_email)
            return False

        normalized_type = str(attendee_type or "required").strip().lower()
        if normalized_type not in {"required", "optional", "resource"}:
            normalized_type = "required"

        if lowered_email in attendees_by_email:
            return False

        attendees_by_email[lowered_email] = {
            "emailAddress": {
                "address": normalized_email,
                "name": str(name or normalized_email).strip() or normalized_email,
            },
            "type": normalized_type,
        }
        return True

    def _collect_attendees(
        self,
        attendees_by_email: Dict[str, Dict[str, Any]],
        raw_attendees: Any,
        invalid_entries: List[str],
        current_user_email: str = "",
        strict: bool = True,
    ) -> None:
        if raw_attendees is None:
            return

        if isinstance(raw_attendees, str):
            for raw_item in re.split(r"[,;\n]+", raw_attendees):
                normalized_item = raw_item.strip()
                if normalized_item:
                    self._add_attendee_candidate(
                        attendees_by_email,
                        invalid_entries,
                        normalized_item,
                        current_user_email=current_user_email,
                        strict=strict,
                    )
            return

        if isinstance(raw_attendees, dict):
            email_address = raw_attendees.get("emailAddress")
            if isinstance(email_address, dict):
                email = email_address.get("address")
                name = email_address.get("name") or raw_attendees.get("displayName") or raw_attendees.get("name")
                attendee_type = raw_attendees.get("type", "required")
            else:
                email = (
                    raw_attendees.get("email")
                    or raw_attendees.get("address")
                    or raw_attendees.get("mail")
                    or raw_attendees.get("userPrincipalName")
                )
                name = raw_attendees.get("displayName") or raw_attendees.get("name")
                attendee_type = raw_attendees.get("type", "required")

            self._add_attendee_candidate(
                attendees_by_email,
                invalid_entries,
                email,
                name=name or "",
                attendee_type=attendee_type,
                current_user_email=current_user_email,
                strict=strict,
            )
            return

        if isinstance(raw_attendees, (list, tuple, set)):
            for entry in raw_attendees:
                self._collect_attendees(
                    attendees_by_email,
                    entry,
                    invalid_entries,
                    current_user_email=current_user_email,
                    strict=strict,
                )
            return

        if strict and str(raw_attendees or "").strip():
            invalid_entries.append(str(raw_attendees))

    def _collect_mail_recipients(
        self,
        raw_recipients: Any,
        parameter_name: str,
        operation_name: str,
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        recipients_by_email: Dict[str, Dict[str, Any]] = {}
        invalid_entries: List[str] = []
        self._collect_attendees(
            recipients_by_email,
            raw_recipients,
            invalid_entries,
            strict=True,
        )
        if invalid_entries:
            invalid_sample = ", ".join(invalid_entries[:5])
            return [], self._invalid_parameter_error(
                operation_name,
                f"{parameter_name} must contain valid email addresses. Invalid entries: {invalid_sample}",
            )

        return [
            {"emailAddress": recipient.get("emailAddress", {})}
            for recipient in recipients_by_email.values()
        ], None

    def _build_deferred_delivery_time(self, delay_seconds: int) -> str:
        scheduled_time = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        return scheduled_time.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _get_execution_context(self) -> Dict[str, str]:
        context = get_m365_context()
        return {
            "user_id": context.data_user_id,
            "conversation_id": context.conversation_id or "",
            "workflow_id": context.workflow_id or "",
            "run_id": context.run_id or "",
        }

    def _build_pending_action_tool_result(
        self,
        operation_name: str,
        delivery_mode: str,
        pending_action: Dict[str, Any],
        status_key: str,
        message: str,
    ) -> Dict[str, Any]:
        return {
            "operation": operation_name,
            "delivery_mode": delivery_mode,
            status_key: pending_action.get("status") or MSGRAPH_PENDING_STATUS_PENDING,
            "pending_user_action": True,
            "pending_action": sanitize_msgraph_pending_action_for_client(
                pending_action, viewer_user_id=get_m365_context().actor_user_id, include_preview=False,
            ),
            "message": message,
        }

    def _create_mail_pending_action(
        self,
        message_payload: Dict[str, Any],
        draft_result: Dict[str, Any],
        action_mode: str,
        auto_send_at_utc: str = "",
        delay_seconds: Optional[int] = None,
        save_to_sent_items: bool = True,
    ) -> Dict[str, Any]:
        denial = self._authorize_operation("send_mail")
        if denial:
            return denial
        execution_context = self._get_execution_context()
        user_id = execution_context.get("user_id")
        if not user_id:
            return self._invalid_parameter_error("send_mail", "Signed-in user context is required to track the pending mail action.")
        draft_id = str(draft_result.get("id") or "").strip()
        draft_version = str(draft_result.get("changeKey") or "").strip()
        if not draft_id:
            return self._invalid_parameter_error("send_mail", "Microsoft 365 did not return a saved draft identifier.")
        if not draft_version:
            current_draft = self._perform_graph_request(
                "send_mail", "GET", f"/v1.0/me/messages/{quote(draft_id, safe='')}",
                ["Mail.ReadWrite"], params={"$select": "id,changeKey,isDraft"},
            )
            if current_draft.get("error"):
                return current_draft
            draft_version = str(current_draft.get("changeKey") or "").strip()
            if not draft_version or current_draft.get("isDraft") is not True:
                return self._invalid_parameter_error("send_mail", "The saved Outlook draft could not be prepared for safe review.")

        if action_mode == MSGRAPH_PENDING_ACTION_DELAYED:
            auto_send_at_utc = self._build_deferred_delivery_time(delay_seconds)
        try:
            pending_action = create_msgraph_pending_action(
                user_id,
                operation=MSGRAPH_PENDING_OPERATION_SEND_MAIL,
                graph_resource_type=MSGRAPH_PENDING_RESOURCE_MAIL,
                action_mode=action_mode,
                status=MSGRAPH_PENDING_STATUS_SCHEDULED if action_mode == MSGRAPH_PENDING_ACTION_DELAYED else MSGRAPH_PENDING_STATUS_PENDING,
                graph_message_id=draft_id,
                graph_draft_version=draft_version,
                graph_payload={"message": message_payload, "saveToSentItems": save_to_sent_items},
                summary=build_mail_pending_action_summary(message_payload),
                conversation_id=execution_context.get("conversation_id", ""),
                workflow_id=execution_context.get("workflow_id", ""),
                run_id=execution_context.get("run_id", ""),
                auto_send_at_utc=auto_send_at_utc,
                delay_seconds=delay_seconds,
                graph_endpoint=self._endpoint,
                web_link=draft_result.get("webLink") or "",
                m365_action_id=self.manifest.get("id") or self.manifest.get("name"),
            )
        except AzureError:
            log_m365_failure("pending_action_storage_failed", source="email", operation="send_mail")
            return {
                "error": "pending_action_storage_failed", "operation": "send_mail",
                "message": (
                    "An Outlook draft was created, but saving its review action did not return a confirmed result. "
                    "Check Outgoing actions in Approvals and the Outlook draft before trying again."
                ),
            }
        return pending_action

    def _create_calendar_pending_action(
        self,
        event_payload: Dict[str, Any],
        action_mode: str,
        auto_send_at_utc: str = "",
        delay_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        denial = self._authorize_operation("create_calendar_invite")
        if denial:
            return denial
        execution_context = self._get_execution_context()
        user_id = execution_context.get("user_id")
        if not user_id:
            return self._invalid_parameter_error("create_calendar_invite", "Signed-in user context is required to track the pending calendar invite.")

        if action_mode == MSGRAPH_PENDING_ACTION_DELAYED:
            auto_send_at_utc = self._build_deferred_delivery_time(delay_seconds)
        pending_action = create_msgraph_pending_action(
            user_id,
            operation=MSGRAPH_PENDING_OPERATION_CREATE_CALENDAR_INVITE,
            graph_resource_type=MSGRAPH_PENDING_RESOURCE_CALENDAR,
            action_mode=action_mode,
            status=MSGRAPH_PENDING_STATUS_SCHEDULED if action_mode == MSGRAPH_PENDING_ACTION_DELAYED else MSGRAPH_PENDING_STATUS_PENDING,
            graph_payload=event_payload,
            m365_action_id=self.manifest.get("id") or self.manifest.get("name"),
            summary=build_calendar_pending_action_summary(event_payload),
            conversation_id=execution_context.get("conversation_id", ""),
            workflow_id=execution_context.get("workflow_id", ""),
            run_id=execution_context.get("run_id", ""),
            auto_send_at_utc=auto_send_at_utc,
            delay_seconds=delay_seconds,
            graph_endpoint=self._endpoint,
        )
        return pending_action

    def _resolve_group_attendees(
        self,
        group_id: str,
        attendees_by_email: Dict[str, Dict[str, Any]],
        current_user_email: str = "",
    ) -> Tuple[str, int]:
        context = get_m365_context()
        current_user_id = context.actor_user_id
        if not current_user_id:
            raise PermissionError("Signed-in user context is required to include group members.")

        normalized_group_id = str(group_id or "").strip() or self._default_group_id or context.group_id
        if not normalized_group_id:
            normalized_group_id = require_active_group(current_user_id)

        assert_group_role(
            current_user_id,
            normalized_group_id,
            allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
        )

        group_doc = find_group_by_id(normalized_group_id)
        if not group_doc:
            raise LookupError("Group not found")

        added_count = 0
        invalid_entries: List[str] = []

        owner = group_doc.get("owner") if isinstance(group_doc.get("owner"), dict) else {}
        if owner and self._add_attendee_candidate(
            attendees_by_email,
            invalid_entries,
            owner.get("email"),
            name=owner.get("displayName") or owner.get("email") or "",
            current_user_email=current_user_email,
            strict=False,
        ):
            added_count += 1

        for member in group_doc.get("users", []):
            if not isinstance(member, dict):
                continue
            if self._add_attendee_candidate(
                attendees_by_email,
                invalid_entries,
                member.get("email"),
                name=member.get("displayName") or member.get("email") or "",
                current_user_email=current_user_email,
                strict=False,
            ):
                added_count += 1

        return normalized_group_id, added_count

    def _normalize_top(self, top: int) -> int:
        try:
            normalized_top = int(top)
        except (TypeError, ValueError):
            return 5
        return max(1, min(normalized_top, self.MAX_ITEMS_PER_RESULT))

    def _sanitize_select_fields(self, select_fields: str) -> Optional[str]:
        if not select_fields:
            return None

        allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./")
        fields = []
        for raw_field in select_fields.split(","):
            field = raw_field.strip()
            if field and all(char in allowed_chars for char in field):
                fields.append(field)

        return ",".join(fields) if fields else None

    def _sanitize_filter_value(self, value: str) -> str:
        return value.replace("'", "''").strip()

    def _build_odata_params(
        self,
        top: int = 5,
        select_fields: str = "",
        filter_query: str = "",
        order_by: str = "",
        search_query: str = "",
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        params: Dict[str, Any] = {"$top": self._normalize_top(top)}
        headers: Dict[str, str] = {}

        normalized_select = self._sanitize_select_fields(select_fields)
        if normalized_select:
            params["$select"] = normalized_select

        if filter_query.strip():
            params["$filter"] = filter_query.strip()

        if order_by.strip():
            params["$orderby"] = order_by.strip()

        if search_query.strip():
            params["$search"] = search_query.strip()
            headers["ConsistencyLevel"] = "eventual"

        if extra_params:
            for key, value in extra_params.items():
                if value is not None and value != "":
                    params[key] = value

        return params, headers

    def _shape_graph_result(self, operation_name: str, payload: Any, max_items: int) -> Dict[str, Any]:
        if isinstance(payload, dict) and isinstance(payload.get("value"), list):
            items = payload.get("value", [])
            next_link = payload.get("@odata.nextLink")
            limited_items = items[:max_items]
            return {
                "operation": operation_name,
                "count": len(limited_items),
                "value": limited_items,
                "next_link": next_link,
                "truncated": len(items) > max_items,
            }

        if isinstance(payload, dict):
            shaped_payload = dict(payload)
            shaped_payload.setdefault("operation", operation_name)
            return shaped_payload

        return {
            "operation": operation_name,
            "value": payload,
        }

    def _perform_graph_request(
        self,
        operation_name: str,
        method: str,
        path: str,
        default_scopes: List[str],
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        paginate: bool = False,
        max_items: int = 5,
        additional_headers: Optional[Dict[str, str]] = None,
        expect_json_response: bool = True,
    ) -> Dict[str, Any]:
        denial = self._authorize_operation(operation_name, (params or {}).get("$select", ""))
        if denial:
            return denial
        transport = self._transport_for_operation(operation_name)
        normalized_max_items = self._normalize_top(max_items)
        collected_items: List[Any] = []
        next_url = path
        next_params = dict(params or {})
        pages_fetched = 0
        last_next_link = None

        while next_url and pages_fetched < self.MAX_PAGES_PER_REQUEST:
            denial = self._authorize_operation(operation_name, (params or {}).get("$select", ""))
            if denial:
                return denial
            try:
                payload = transport.request_json(
                    method.upper(),
                    next_url,
                    default_scopes,
                    params=next_params,
                    json_body=json_body,
                    additional_headers=additional_headers,
                    expect_json=expect_json_response,
                )
            except M365ApprovalRequired:
                raise
            except M365PolicyError as exc:
                return self._policy_error_result(exc, operation_name, transport.source)
            except M365ProviderError as exc:
                log_m365_failure(exc.code, source=transport.source or "", operation=operation_name)
                result = {
                    "error": exc.code, "message": exc.message,
                    "operation": operation_name, "scopes": default_scopes,
                    "source": transport.source, "provider": "graph",
                    **exc.details,
                }
                if exc.status_code is not None:
                    result["status_code"] = exc.status_code
                if exc.retry_after_seconds is not None:
                    result["retry_after_seconds"] = exc.retry_after_seconds
                if collected_items:
                    result.update({"value": collected_items, "count": len(collected_items), "truncated": True})
                return result

            pages_fetched += 1
            if not expect_json_response:
                return {**payload, "operation": operation_name, "source": transport.source, "provider": "graph"}

            if paginate and isinstance(payload, dict) and isinstance(payload.get("value"), list):
                remaining_capacity = max(0, normalized_max_items - len(collected_items))
                page_items = payload.get("value", [])
                collected_items.extend(page_items[:remaining_capacity])
                last_next_link = payload.get("@odata.nextLink")
                if len(collected_items) >= normalized_max_items or not last_next_link:
                    return {
                        "operation": operation_name,
                        "count": len(collected_items),
                        "value": collected_items,
                        "next_link": last_next_link,
                        "truncated": bool(last_next_link) or len(page_items) > remaining_capacity,
                        "source": transport.source,
                        "provider": "graph",
                    }
                next_url = last_next_link
                next_params = None
                continue

            result = self._shape_graph_result(operation_name, payload, normalized_max_items)
            result.update({"source": transport.source, "provider": "graph"})
            return result

        return {
            "operation": operation_name,
            "count": len(collected_items),
            "value": collected_items,
            "next_link": last_next_link,
            "truncated": bool(last_next_link),
            "source": transport.source,
            "provider": "graph",
        }

    @plugin_function_logger("MSGraphPlugin")
    @kernel_function(description="Get information about the signed-in user.")
    @guarded_m365_operation
    def get_my_profile(self, select_fields: str = "") -> dict:
        params, headers = self._build_odata_params(
            top=1,
            select_fields=select_fields or "id,displayName,givenName,surname,mail,userPrincipalName,jobTitle,department,officeLocation,mobilePhone,businessPhones",
        )
        params.pop("$top", None)
        return self._perform_graph_request(
            "get_my_profile",
            "GET",
            "/v1.0/me",
            ["User.Read"],
            params=params,
            additional_headers=headers,
        )

    @plugin_function_logger("MSGraphPlugin")
    @kernel_function(description="Get the signed-in user's Microsoft 365 mailbox timezone settings. Use this before answering timezone-sensitive date and time questions.")
    @guarded_m365_operation
    def get_my_timezone(self) -> dict:
        result = self._perform_graph_request(
            "get_my_timezone",
            "GET",
            "/v1.0/me/mailboxSettings",
            ["MailboxSettings.Read"],
        )
        if not isinstance(result, dict) or result.get("error"):
            return result

        working_hours = result.get("workingHours") if isinstance(result.get("workingHours"), dict) else {}
        return {
            "operation": "get_my_timezone",
            "time_zone": result.get("timeZone") or "",
            "date_format": result.get("dateFormat") or "",
            "time_format": result.get("timeFormat") or "",
            "language": result.get("language") or {},
            "working_hours_time_zone": working_hours.get("timeZone") or {},
            "message": (
                "Use the user's mailbox time_zone instead of assuming UTC when answering "
                "user-facing date and time questions."
            ),
        }

    @plugin_function_logger("MSGraphPlugin")
    @kernel_function(description="Get upcoming calendar events for the signed-in user.")
    @guarded_m365_operation
    def get_my_events(
        self,
        top: int = 5,
        start_datetime: str = "",
        end_datetime: str = "",
        select_fields: str = "",
    ) -> dict:
        use_calendar_view = bool(start_datetime.strip() or end_datetime.strip())
        if use_calendar_view and not (start_datetime.strip() and end_datetime.strip()):
            return {
                "error": "invalid_parameters",
                "message": "Both start_datetime and end_datetime are required when filtering calendar events by time range.",
                "operation": "get_my_events",
            }

        params, headers = self._build_odata_params(
            top=top,
            select_fields=select_fields or "id,subject,start,end,location,organizer,isAllDay,webLink",
            order_by="start/dateTime",
            extra_params={
                "startDateTime": start_datetime.strip() or None,
                "endDateTime": end_datetime.strip() or None,
            },
        )
        path = "/v1.0/me/calendarView" if use_calendar_view else "/v1.0/me/events"
        return self._perform_graph_request(
            "get_my_events",
            "GET",
            path,
            ["Calendars.Read"],
            params=params,
            paginate=True,
            max_items=top,
            additional_headers=headers,
        )

    @plugin_function_logger("MSGraphPlugin")
    # bac-check: ignore - _resolve_group_attendees validates group_id with require_active_group/assert_group_role.
    @kernel_function(description="Create a calendar invite for the signed-in user and optionally turn it into a Microsoft Teams meeting.")
    @guarded_m365_operation
    def create_calendar_invite(
        self,
        subject: str,
        start_datetime: str,
        end_datetime: str,
        body_content: str = "",
        location: str = "",
        attendee_emails: Any = "",
        include_group_members: Any = False,
        group_id: str = "",
        make_teams_meeting: Any = False,
        timezone: str = "",
        allow_new_time_proposals: Any = True,
    ) -> dict:
        operation_name = "create_calendar_invite"
        normalized_subject = str(subject or "").strip()
        normalized_start = str(start_datetime or "").strip()
        normalized_end = str(end_datetime or "").strip()
        normalized_body = str(body_content or "").strip()
        normalized_location = str(location or "").strip()

        if not normalized_subject:
            return self._invalid_parameter_error(operation_name, "subject is required to create a calendar invite.")
        if not normalized_start or not normalized_end:
            return self._invalid_parameter_error(operation_name, "start_datetime and end_datetime are required to create a calendar invite.")

        normalized_include_group_members, boolean_error = self._normalize_boolean_parameter(
            include_group_members,
            "include_group_members",
            operation_name,
        )
        if boolean_error:
            return boolean_error

        normalized_make_teams_meeting, boolean_error = self._normalize_boolean_parameter(
            make_teams_meeting,
            "make_teams_meeting",
            operation_name,
        )
        if boolean_error:
            return boolean_error

        normalized_allow_new_time_proposals, boolean_error = self._normalize_boolean_parameter(
            allow_new_time_proposals,
            "allow_new_time_proposals",
            operation_name,
        )
        if boolean_error:
            return boolean_error

        current_user = get_current_user_info() or {}
        current_user_email = str(current_user.get("email") or "").strip()
        execution_context = get_m365_context()
        if execution_context.workflow_id:
            profile = self._perform_graph_request(
                "resolve_calendar_identity", "GET", "/v1.0/me", ["User.Read"],
                params={"$select": "mail,userPrincipalName"},
            )
            if profile.get("error"):
                return profile
            current_user_email = str(profile.get("mail") or profile.get("userPrincipalName") or "").strip()
        attendees_by_email: Dict[str, Dict[str, Any]] = {}
        invalid_entries: List[str] = []
        self._collect_attendees(
            attendees_by_email,
            attendee_emails,
            invalid_entries,
            current_user_email=current_user_email,
            strict=True,
        )
        if invalid_entries:
            invalid_sample = ", ".join(invalid_entries[:5])
            return self._invalid_parameter_error(
                operation_name,
                f"attendee_emails must contain valid email addresses. Invalid entries: {invalid_sample}",
            )

        resolved_group_id = ""
        group_attendee_count = 0
        if normalized_include_group_members:
            try:
                resolved_group_id, group_attendee_count = self._resolve_group_attendees(
                    group_id,
                    attendees_by_email,
                    current_user_email=current_user_email,
                )
            except ValueError as exc:
                return self._invalid_parameter_error(operation_name, str(exc))
            except LookupError as exc:
                return {
                    "error": "not_found",
                    "message": str(exc),
                    "operation": operation_name,
                }
            except PermissionError as exc:
                return {
                    "error": "permission_denied",
                    "message": str(exc),
                    "operation": operation_name,
                }

        try:
            normalized_timezone = self._resolve_event_timezone(timezone)
        except M365ProviderError as exc:
            log_m365_failure(exc.code, source="calendar", operation=operation_name)
            return {"error": exc.code, "message": exc.message, "operation": operation_name}
        attendees = list(attendees_by_email.values())
        event_payload: Dict[str, Any] = {
            "subject": normalized_subject,
            "start": {
                "dateTime": normalized_start,
                "timeZone": normalized_timezone,
            },
            "end": {
                "dateTime": normalized_end,
                "timeZone": normalized_timezone,
            },
            "allowNewTimeProposals": bool(normalized_allow_new_time_proposals),
        }

        if normalized_body:
            event_payload["body"] = {
                "contentType": "Text",
                "content": normalized_body,
            }
        if normalized_location:
            event_payload["location"] = {"displayName": normalized_location}
        if attendees:
            event_payload["attendees"] = attendees
        if normalized_make_teams_meeting:
            event_payload["isOnlineMeeting"] = True
            event_payload["onlineMeetingProvider"] = "teamsForBusiness"

        if self._calendar_send_mode in {
            MSGRAPH_CALENDAR_SEND_MODE_DRAFT_MANUAL,
            MSGRAPH_CALENDAR_SEND_MODE_DRAFT_DELAYED,
        }:
            scheduled_send_time = ""
            delay_seconds = None
            action_mode = MSGRAPH_PENDING_ACTION_MANUAL
            if self._calendar_send_mode == MSGRAPH_CALENDAR_SEND_MODE_DRAFT_DELAYED:
                scheduled_send_time = self._build_deferred_delivery_time(self._calendar_delay_seconds)
                delay_seconds = self._calendar_delay_seconds
                action_mode = MSGRAPH_PENDING_ACTION_DELAYED
                token, _, token_error = self._get_token("create_calendar_invite_delayed_delivery", ["Calendars.ReadWrite"])
                if token_error:
                    return token_error
            else:
                token = None

            pending_action = self._create_calendar_pending_action(
                event_payload,
                action_mode,
                auto_send_at_utc=scheduled_send_time,
                delay_seconds=delay_seconds,
            )
            if pending_action.get("error"):
                return pending_action
            if token:
                schedule_msgraph_pending_action_auto_commit(pending_action, token)
            scheduled_send_time = pending_action.get("auto_send_at_utc") or ""

            result = self._build_pending_action_tool_result(
                operation_name,
                self._calendar_send_mode,
                pending_action,
                "calendar_invite_status",
                (
                    "Calendar invite is waiting for the delayed send window. It can be cancelled or sent now before the timer ends."
                    if action_mode == MSGRAPH_PENDING_ACTION_DELAYED
                    else "Calendar invite is waiting for review. Send or cancel it from the action card."
                ),
            )
            result["requested_attendee_count"] = len(attendees)
            result["included_group_member_count"] = group_attendee_count
            result["event_timezone"] = normalized_timezone
            result["teams_meeting_requested"] = bool(normalized_make_teams_meeting)
            if resolved_group_id:
                result["group_id"] = resolved_group_id
            if scheduled_send_time:
                result["scheduled_send_time_utc"] = scheduled_send_time
                result["delay_seconds"] = delay_seconds
            return result

        result = self._perform_graph_request(
            operation_name,
            "POST",
            "/v1.0/me/events",
            ["Calendars.ReadWrite"],
            json_body=event_payload,
            additional_headers={"Prefer": f'outlook.timezone="{normalized_timezone}"'},
        )
        if not isinstance(result, dict) or result.get("error"):
            return result

        result.setdefault("operation", operation_name)
        result["requested_attendee_count"] = len(attendees)
        result["included_group_member_count"] = group_attendee_count
        result["event_timezone"] = normalized_timezone
        result["teams_meeting_requested"] = bool(normalized_make_teams_meeting)
        if resolved_group_id:
            result["group_id"] = resolved_group_id

        online_meeting = result.get("onlineMeeting") if isinstance(result.get("onlineMeeting"), dict) else {}
        if online_meeting.get("joinUrl"):
            result["join_url"] = online_meeting.get("joinUrl")

        return result

    @plugin_function_logger("MSGraphPlugin")
    @kernel_function(description="Get recent mail messages for the signed-in user.")
    @guarded_m365_operation
    def get_my_messages(
        self,
        top: int = 5,
        folder: str = "inbox",
        unread_only: bool = False,
        select_fields: str = "",
    ) -> dict:
        filter_query = "isRead eq false" if unread_only else ""
        params, headers = self._build_odata_params(
            top=top,
            select_fields=select_fields or "id,subject,from,receivedDateTime,isRead,importance,webLink",
            filter_query=filter_query,
            order_by="receivedDateTime desc",
        )
        normalized_folder = (folder or "").strip().strip("/")
        if normalized_folder:
            path = f"/v1.0/me/mailFolders/{quote(normalized_folder, safe='')}/messages"
        else:
            path = "/v1.0/me/messages"
        return self._perform_graph_request(
            "get_my_messages",
            "GET",
            path,
            ["Mail.Read"],
            params=params,
            paginate=True,
            max_items=top,
            additional_headers=headers,
        )

    @plugin_function_logger("MSGraphPlugin")
    @kernel_function(description="Mark a mail message as read or unread for the signed-in user.")
    @guarded_m365_operation
    def mark_message_as_read(self, message_id: str, is_read: bool = True) -> dict:
        normalized_message_id = (message_id or "").strip()
        if not normalized_message_id:
            return {
                "error": "invalid_parameters",
                "message": "message_id is required to update a mail message.",
                "operation": "mark_message_as_read",
            }

        normalized_is_read = is_read
        if isinstance(is_read, str):
            lowered_value = is_read.strip().lower()
            if lowered_value in {"true", "1", "yes"}:
                normalized_is_read = True
            elif lowered_value in {"false", "0", "no"}:
                normalized_is_read = False
            else:
                return {
                    "error": "invalid_parameters",
                    "message": "is_read must be a boolean value.",
                    "operation": "mark_message_as_read",
                }

        return self._perform_graph_request(
            "mark_message_as_read",
            "PATCH",
            f"/v1.0/me/messages/{quote(normalized_message_id, safe='')}",
            ["Mail.ReadWrite"],
            json_body={"isRead": bool(normalized_is_read)},
        )

    @plugin_function_logger("MSGraphPlugin")
    @kernel_function(description="Create or send an email from the signed-in user's mailbox using this action's configured delivery mode.")
    @guarded_m365_operation
    def send_mail(
        self,
        to_recipients: Any,
        subject: str,
        body_content: str = "",
        cc_recipients: Any = "",
        bcc_recipients: Any = "",
        save_to_sent_items: Any = True,
    ) -> dict:
        operation_name = "send_mail"
        normalized_subject = str(subject or "").strip()
        normalized_body = str(body_content or "")

        if not normalized_subject:
            return self._invalid_parameter_error(operation_name, "subject is required to send mail.")

        to_payload, recipient_error = self._collect_mail_recipients(
            to_recipients,
            "to_recipients",
            operation_name,
        )
        if recipient_error:
            return recipient_error
        if not to_payload:
            return self._invalid_parameter_error(operation_name, "to_recipients must include at least one valid email address.")

        cc_payload, recipient_error = self._collect_mail_recipients(
            cc_recipients,
            "cc_recipients",
            operation_name,
        )
        if recipient_error:
            return recipient_error

        bcc_payload, recipient_error = self._collect_mail_recipients(
            bcc_recipients,
            "bcc_recipients",
            operation_name,
        )
        if recipient_error:
            return recipient_error

        normalized_save_to_sent_items, boolean_error = self._normalize_boolean_parameter(
            save_to_sent_items,
            "save_to_sent_items",
            operation_name,
        )
        if boolean_error:
            return boolean_error

        message_payload: Dict[str, Any] = {
            "subject": normalized_subject,
            "body": {
                "contentType": "Text",
                "content": normalized_body,
            },
            "toRecipients": to_payload,
        }
        if cc_payload:
            message_payload["ccRecipients"] = cc_payload
        if bcc_payload:
            message_payload["bccRecipients"] = bcc_payload

        if self._mail_send_mode == MSGRAPH_MAIL_SEND_MODE_AUTO_SEND:
            send_result = self._perform_graph_request(
                operation_name,
                "POST",
                "/v1.0/me/sendMail",
                ["Mail.Send"],
                json_body={
                    "message": message_payload,
                    "saveToSentItems": bool(normalized_save_to_sent_items),
                },
                expect_json_response=False,
            )
            if not isinstance(send_result, dict) or send_result.get("error"):
                return send_result

            send_result.update({
                "operation": operation_name,
                "delivery_mode": self._mail_send_mode,
                "mail_send_status": "sent",
                "saved_to_sent_items": bool(normalized_save_to_sent_items),
            })
            return send_result

        if self._mail_send_mode == MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED:
            token, _, token_error = self._get_token("send_mail_delayed_delivery", ["Mail.Send", "Mail.ReadWrite"])
            if token_error:
                return token_error
            draft_result = self._perform_graph_request(
                operation_name,
                "POST",
                "/v1.0/me/messages",
                ["Mail.ReadWrite"],
                json_body=message_payload,
            )
            if not isinstance(draft_result, dict) or draft_result.get("error"):
                return draft_result

            message_id = str(draft_result.get("id") or "").strip()
            if not message_id:
                return self._invalid_parameter_error(
                    operation_name,
                    "Microsoft Graph created the mail draft but did not return a message id for delayed delivery.",
                )

            pending_action = self._create_mail_pending_action(
                message_payload,
                draft_result,
                MSGRAPH_PENDING_ACTION_DELAYED,
                delay_seconds=self._mail_delay_seconds,
                save_to_sent_items=bool(normalized_save_to_sent_items),
            )
            if pending_action.get("error"):
                return pending_action
            schedule_msgraph_pending_action_auto_commit(pending_action, token)

            return {
                "operation": operation_name,
                "delivery_mode": self._mail_send_mode,
                "mail_send_status": "scheduled_pending",
                "message_id": message_id,
                "delay_seconds": self._mail_delay_seconds,
                "scheduled_send_time_utc": pending_action["auto_send_at_utc"],
                "pending_user_action": True,
                "pending_action": sanitize_msgraph_pending_action_for_client(
                    pending_action, viewer_user_id=get_m365_context().actor_user_id, include_preview=False,
                ),
                "message": "Mail draft is waiting for the delayed send window. It can be cancelled or sent now before the timer ends.",
            }

        draft_result = self._perform_graph_request(
            operation_name,
            "POST",
            "/v1.0/me/messages",
            ["Mail.ReadWrite"],
            json_body=message_payload,
        )
        if not isinstance(draft_result, dict) or draft_result.get("error"):
            return draft_result

        pending_action = self._create_mail_pending_action(
            message_payload,
            draft_result,
            MSGRAPH_PENDING_ACTION_MANUAL,
            save_to_sent_items=bool(normalized_save_to_sent_items),
        )
        if pending_action.get("error"):
            return pending_action

        return self._build_pending_action_tool_result(
            operation_name,
            MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL,
            pending_action,
            "mail_send_status",
            "Mail draft is waiting for review. Send or cancel it from the action card.",
        )

    @plugin_function_logger("MSGraphPlugin")
    @kernel_function(description="Search directory users by name or email prefix.")
    @guarded_m365_operation
    def search_users(self, query: str, top: int = 5, select_fields: str = "") -> dict:
        normalized_query = (query or "").strip()
        if not normalized_query:
            return {
                "error": "invalid_parameters",
                "message": "query is required to search users.",
                "operation": "search_users",
            }

        safe_query = self._sanitize_filter_value(normalized_query)
        filter_query = (
            f"startswith(displayName,'{safe_query}') or "
            f"startswith(givenName,'{safe_query}') or "
            f"startswith(surname,'{safe_query}') or "
            f"startswith(mail,'{safe_query}') or "
            f"startswith(userPrincipalName,'{safe_query}')"
        )
        params, headers = self._build_odata_params(
            top=top,
            select_fields=select_fields or "id,displayName,mail,userPrincipalName,jobTitle,department,officeLocation",
            filter_query=filter_query,
            order_by="displayName",
        )
        return self._perform_graph_request(
            "search_users",
            "GET",
            "/v1.0/users",
            ["User.ReadBasic.All"],
            params=params,
            paginate=True,
            max_items=top,
            additional_headers=headers,
        )

    @plugin_function_logger("MSGraphPlugin")
    @kernel_function(description="Get a directory user by exact email address or user principal name.")
    @guarded_m365_operation
    def get_user_by_email(self, email: str, select_fields: str = "") -> dict:
        normalized_email = (email or "").strip()
        if not normalized_email:
            return {
                "error": "invalid_parameters",
                "message": "email is required to look up a user.",
                "operation": "get_user_by_email",
            }

        safe_email = self._sanitize_filter_value(normalized_email)
        filter_query = f"mail eq '{safe_email}' or userPrincipalName eq '{safe_email}'"
        params, headers = self._build_odata_params(
            top=1,
            select_fields=select_fields or "id,displayName,mail,userPrincipalName,jobTitle,department,officeLocation",
            filter_query=filter_query,
        )
        result = self._perform_graph_request(
            "get_user_by_email",
            "GET",
            "/v1.0/users",
            ["User.ReadBasic.All"],
            params=params,
            paginate=False,
            max_items=1,
            additional_headers=headers,
        )
        if isinstance(result, dict) and isinstance(result.get("value"), list):
            result["value"] = result.get("value", [])[:1]
            result["count"] = len(result["value"])
        return result

    @plugin_function_logger("MSGraphPlugin")
    @kernel_function(description="List OneDrive items from the drive root or a child path for the signed-in user.")
    @guarded_m365_operation
    def list_drive_items(self, path: str = "", top: int = 10, select_fields: str = "") -> dict:
        normalized_path = (path or "").strip().strip("/")
        params, headers = self._build_odata_params(
            top=top,
            select_fields=select_fields or "id,name,webUrl,lastModifiedDateTime,size,folder,file,parentReference",
            order_by="name",
        )
        if normalized_path:
            graph_path = f"/v1.0/me/drive/root:/{quote(normalized_path, safe='/')}:/children"
        else:
            graph_path = "/v1.0/me/drive/root/children"
        return self._perform_graph_request(
            "list_drive_items",
            "GET",
            graph_path,
            ["Files.Read"],
            params=params,
            paginate=True,
            max_items=top,
            additional_headers=headers,
        )

    @plugin_function_logger("MSGraphPlugin")
    @kernel_function(description="Get recent security alerts for the signed-in user.")
    @guarded_m365_operation
    def get_my_security_alerts(self, top: int = 5) -> dict:
        params, headers = self._build_odata_params(
            top=top,
            order_by="createdDateTime desc",
        )
        return self._perform_graph_request(
            "get_my_security_alerts",
            "GET",
            "/v1.0/security/alerts",
            ["SecurityEvents.Read.All"],
            params=params,
            paginate=True,
            max_items=top,
            additional_headers=headers,
        )
