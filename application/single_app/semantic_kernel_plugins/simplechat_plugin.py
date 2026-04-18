# simplechat_plugin.py
"""Semantic Kernel plugin for SimpleChat-native workspace operations."""

import logging
from typing import Any, Callable, Dict, List, Optional

from semantic_kernel.functions import kernel_function
from semantic_kernel.functions.kernel_plugin import KernelPlugin

from functions_appinsights import log_event
from functions_simplechat_operations import (
    SIMPLECHAT_CAPABILITY_DEFINITIONS,
    add_conversation_message_for_current_user,
    add_group_member_for_current_user,
    create_group_collaboration_conversation_for_current_user,
    create_group_for_current_user,
    invite_group_conversation_members_for_current_user,
    create_personal_workflow_for_current_user,
    create_personal_collaboration_conversation_for_current_user,
    create_personal_conversation_for_current_user,
    get_simplechat_enabled_function_names,
    make_group_inactive_for_current_user,
    normalize_simplechat_capabilities,
    upload_markdown_document_for_current_user,
)
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger


class SimpleChatPlugin(BasePlugin):
    def __init__(self, manifest: Optional[Dict[str, Any]] = None):
        super().__init__(manifest)
        self.manifest = manifest or {}
        self._metadata = self.manifest.get("metadata", {})
        self._capabilities = normalize_simplechat_capabilities(
            self.manifest.get("simplechat_capabilities")
        )
        self._enabled_function_names = set(
            self.manifest.get("enabled_functions")
            or get_simplechat_enabled_function_names(self._capabilities)
        )
        self._default_group_id = str(
            self.manifest.get("group_id") or self.manifest.get("default_group_id") or ""
        ).strip()

    @property
    def display_name(self) -> str:
        return "Simple Chat"

    @property
    def metadata(self) -> Dict[str, Any]:
        enabled_methods = set(self.get_functions())
        return {
            "name": self.manifest.get("name", "simplechat"),
            "type": "simplechat",
            "description": (
                "Simple Chat workspace actions for creating groups, conversations, "
                "personal workflows, group membership changes, group status updates, "
                "and Markdown document uploads using the "
                "invoking user's own permissions."
            ),
            "methods": [
                {
                    "name": definition["function_name"],
                    "description": definition["description"],
                    "parameters": [],
                    "returns": {"type": "dict", "description": definition["description"]},
                }
                for definition in SIMPLECHAT_CAPABILITY_DEFINITIONS
                if definition["function_name"] in enabled_methods
            ],
        }

    def get_functions(self) -> List[str]:
        return [
            definition["function_name"]
            for definition in SIMPLECHAT_CAPABILITY_DEFINITIONS
            if definition["function_name"] in self._enabled_function_names
        ]

    def get_kernel_plugin(self, plugin_name: str = "simplechat") -> KernelPlugin:
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

    def _execute_operation(self, operation_name: str, callback):
        try:
            result = callback()
            if isinstance(result, dict):
                payload = dict(result)
            else:
                payload = {"result": result}
            payload.setdefault("success", True)
            return payload
        except PermissionError as exc:
            return {"success": False, "error": str(exc), "error_type": "permission"}
        except LookupError as exc:
            return {"success": False, "error": str(exc), "error_type": "not_found"}
        except ValueError as exc:
            return {"success": False, "error": str(exc), "error_type": "validation"}
        except Exception as exc:
            log_event(
                f"[SimpleChatPlugin] {operation_name} failed: {exc}",
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return {
                "success": False,
                "error": f"Failed to {operation_name.replace('_', ' ')}",
                "error_type": "unexpected",
                "details": str(exc),
            }

    def _normalize_initial_message(self, initial_message: str = "") -> str:
        normalized_initial_message = str(initial_message or "").strip()
        if not normalized_initial_message:
            return ""

        if "add_conversation_message" not in self._enabled_function_names:
            raise PermissionError(
                "The add conversation message capability is disabled for this action. "
                "Enable it to seed a newly created conversation."
            )

        return normalized_initial_message

    def _seed_initial_message_if_requested(self, conversation_id: str, initial_message: str = "") -> Dict[str, Any]:
        normalized_initial_message = self._normalize_initial_message(initial_message)
        if not normalized_initial_message:
            return {}

        seeded_message_payload = add_conversation_message_for_current_user(
            conversation_id=conversation_id,
            content=normalized_initial_message,
        )
        return {
            "conversation": seeded_message_payload.get("conversation"),
            "message": seeded_message_payload.get("message"),
            "seeded_initial_message": True,
        }

    def _create_group_conversation_with_optional_seed(
        self,
        title: str = "",
        group_id: str = "",
        initial_message: str = "",
    ) -> Dict[str, Any]:
        normalized_initial_message = self._normalize_initial_message(initial_message)
        conversation, _, group_doc = create_group_collaboration_conversation_for_current_user(
            title=title,
            group_id=group_id,
            default_group_id=self._default_group_id,
        )

        payload = self._build_seeded_creation_payload(
            conversation,
            initial_message=normalized_initial_message,
        )
        normalized_group_doc = group_doc if isinstance(group_doc, dict) else {}
        group_name = str(normalized_group_doc.get("name") or "Group Workspace").strip() or "Group Workspace"
        conversation_title = str((conversation or {}).get("title") or "New Group Collaborative Conversation").strip()
        payload["group"] = {
            "id": normalized_group_doc.get("id"),
            "name": group_name,
        }
        payload.setdefault(
            "message",
            (
                f"Created group multi-user conversation '{conversation_title}' in group '{group_name}'. "
                "Use invite_group_conversation_members to add current group members as participants and grant access."
            ),
        )
        return payload

    @plugin_function_logger("SimpleChatPlugin")
    @kernel_function(description="Create a new group workspace as the current user.")
    def create_group(self, name: str, description: str = "") -> dict:
        return self._execute_operation(
            "create_group",
            lambda: {
                "group": create_group_for_current_user(name=name, description=description),
            },
        )

    @plugin_function_logger("SimpleChatPlugin")
    @kernel_function(description="Create a new personal conversation for the current user.")
    def create_personal_conversation(
        self,
        title: str = "New Conversation",
        initial_message: str = "",
    ) -> dict:
        return self._execute_operation(
            "create_personal_conversation",
            lambda: self._create_conversation_with_optional_seed(
                lambda: create_personal_conversation_for_current_user(
                    title=title,
                    notify_creation=True,
                ),
                initial_message=initial_message,
            ),
        )

    @plugin_function_logger("SimpleChatPlugin")
    @kernel_function(description="Create a new personal workflow under the current user's identity. runner_type can be 'model' or 'agent'. trigger_type can be 'manual' or 'interval'.")
    def create_personal_workflow(
        self,
        name: str,
        task_prompt: str,
        description: str = "",
        runner_type: str = "model",
        trigger_type: str = "manual",
        selected_agent_name: str = "",
        selected_agent_id: str = "",
        selected_agent_is_global: bool = False,
        model_endpoint_id: str = "",
        model_id: str = "",
        alert_priority: str = "none",
        is_enabled: bool = True,
        schedule_value: int = 1,
        schedule_unit: str = "hours",
        conversation_id: str = "",
    ) -> dict:
        return self._execute_operation(
            "create_personal_workflow",
            lambda: create_personal_workflow_for_current_user(
                name=name,
                task_prompt=task_prompt,
                description=description,
                runner_type=runner_type,
                trigger_type=trigger_type,
                selected_agent_name=selected_agent_name,
                selected_agent_id=selected_agent_id,
                selected_agent_is_global=selected_agent_is_global,
                model_endpoint_id=model_endpoint_id,
                model_id=model_id,
                alert_priority=alert_priority,
                is_enabled=is_enabled,
                schedule_value=schedule_value,
                schedule_unit=schedule_unit,
                conversation_id=conversation_id,
            ),
        )

    @plugin_function_logger("SimpleChatPlugin")
    @kernel_function(description="Create a new invite-managed group multi-user conversation in a group the current user can access. If group_id is omitted, the active group is used. Add current group members as participants to grant access.")
    def create_group_conversation(
        self,
        title: str = "",
        group_id: str = "",
        initial_message: str = "",
    ) -> dict:
        return self._execute_operation(
            "create_group_conversation",
            lambda: self._create_group_conversation_with_optional_seed(
                title=title,
                group_id=group_id,
                initial_message=initial_message,
            ),
        )

    @plugin_function_logger("SimpleChatPlugin")
    @kernel_function(description="Invite current group members into an existing invite-managed group multi-user conversation. Provide participant_identifiers as emails, user principal names, or user IDs separated by commas or new lines.")
    def invite_group_conversation_members(
        self,
        conversation_id: str,
        participant_identifiers: str = "",
    ) -> dict:
        return self._execute_operation(
            "invite_group_conversation_members",
            lambda: invite_group_conversation_members_for_current_user(
                conversation_id=conversation_id,
                participant_identifiers=participant_identifiers,
            ),
        )

    @plugin_function_logger("SimpleChatPlugin")
    @kernel_function(description="Mark a group inactive using the current user's Control Center admin permissions. If group_id is omitted, the action's group context or active group is used.")
    def make_group_inactive(
        self,
        group_id: str = "",
        reason: str = "",
    ) -> dict:
        return self._execute_operation(
            "make_group_inactive",
            lambda: make_group_inactive_for_current_user(
                group_id=group_id,
                reason=reason,
                default_group_id=self._default_group_id,
            ),
        )

    @plugin_function_logger("SimpleChatPlugin")
    @kernel_function(description="Add a user-authored message to an existing personal or collaborative conversation the current user can access. Use this after creating a conversation when you need to seed the opening request.")
    def add_conversation_message(
        self,
        conversation_id: str,
        content: str,
        reply_to_message_id: str = "",
    ) -> dict:
        return self._execute_operation(
            "add_conversation_message",
            lambda: add_conversation_message_for_current_user(
                conversation_id=conversation_id,
                content=content,
                reply_to_message_id=reply_to_message_id,
            ),
        )

    @plugin_function_logger("SimpleChatPlugin")
    @kernel_function(description="Create and upload a Markdown document into the current user's personal workspace or an allowed group workspace. Use workspace_scope='group' to target a group workspace and optionally provide group_id.")
    def upload_markdown_document(
        self,
        file_name: str,
        markdown_content: str,
        workspace_scope: str = "personal",
        group_id: str = "",
    ) -> dict:
        return self._execute_operation(
            "upload_markdown_document",
            lambda: upload_markdown_document_for_current_user(
                file_name=file_name,
                markdown_content=markdown_content,
                workspace_scope=workspace_scope,
                group_id=group_id,
                default_group_id=self._default_group_id,
            ),
        )

    @plugin_function_logger("SimpleChatPlugin")
    @kernel_function(description="Create a personal collaborative conversation and invite one or more users. Provide participant_identifiers as emails, user principal names, or user IDs separated by commas or new lines.")
    def create_personal_collaboration_conversation(
        self,
        participant_identifiers: str = "",
        title: str = "",
        initial_message: str = "",
    ) -> dict:
        return self._execute_operation(
            "create_personal_collaboration_conversation",
            lambda: self._create_conversation_with_optional_seed(
                lambda: create_personal_collaboration_conversation_for_current_user(
                    title=title,
                    participant_identifiers=participant_identifiers,
                )[0],
                initial_message=initial_message,
            ),
        )

    @plugin_function_logger("SimpleChatPlugin")
    @kernel_function(description="Add a user directly to a group as the current user. user_identifier can be an email, user principal name, or user ID. If group_id is omitted, the active group is used.")
    def add_user_to_group(
        self,
        user_identifier: str = "",
        group_id: str = "",
        role: str = "user",
        display_name: str = "",
        email: str = "",
    ) -> dict:
        return self._execute_operation(
            "add_group_member",
            lambda: add_group_member_for_current_user(
                group_id=group_id,
                user_identifier=user_identifier,
                email=email,
                display_name=display_name,
                role=role,
                default_group_id=self._default_group_id,
            ),
        )

    def _build_seeded_creation_payload(
        self,
        conversation: Dict[str, Any],
        initial_message: str = "",
    ) -> Dict[str, Any]:
        payload = {"conversation": conversation}
        seeded_payload = self._seed_initial_message_if_requested(
            conversation_id=str((conversation or {}).get("id") or "").strip(),
            initial_message=initial_message,
        )
        if seeded_payload:
            payload.update(seeded_payload)
        return payload

    def _create_conversation_with_optional_seed(
        self,
        create_conversation: Callable[[], Dict[str, Any]],
        initial_message: str = "",
    ) -> Dict[str, Any]:
        normalized_initial_message = self._normalize_initial_message(initial_message)
        conversation = create_conversation()
        return self._build_seeded_creation_payload(
            conversation,
            initial_message=normalized_initial_message,
        )