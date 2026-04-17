# simplechat_plugin.py
"""Semantic Kernel plugin for SimpleChat-native workspace operations."""

import logging
from typing import Any, Dict, List, Optional

from semantic_kernel.functions import kernel_function
from semantic_kernel.functions.kernel_plugin import KernelPlugin

from functions_appinsights import log_event
from functions_simplechat_operations import (
    SIMPLECHAT_CAPABILITY_DEFINITIONS,
    add_group_member_for_current_user,
    create_group_collaboration_conversation_for_current_user,
    create_group_for_current_user,
    create_personal_collaboration_conversation_for_current_user,
    create_personal_conversation_for_current_user,
    get_simplechat_enabled_function_names,
    normalize_simplechat_capabilities,
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
                "Simple Chat workspace actions for creating groups, conversations, and "
                "group membership changes using the invoking user's own permissions."
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
    def create_personal_conversation(self, title: str = "New Conversation") -> dict:
        return self._execute_operation(
            "create_personal_conversation",
            lambda: {
                "conversation": create_personal_conversation_for_current_user(title=title),
            },
        )

    @plugin_function_logger("SimpleChatPlugin")
    @kernel_function(description="Create a new collaborative conversation in a group the current user can access. If group_id is omitted, the active group is used.")
    def create_group_conversation(self, title: str = "", group_id: str = "") -> dict:
        return self._execute_operation(
            "create_group_conversation",
            lambda: {
                "conversation": create_group_collaboration_conversation_for_current_user(
                    title=title,
                    group_id=group_id,
                    default_group_id=self._default_group_id,
                )[0],
            },
        )

    @plugin_function_logger("SimpleChatPlugin")
    @kernel_function(description="Create a personal collaborative conversation and invite one or more users. Provide participant_identifiers as emails, user principal names, or user IDs separated by commas or new lines.")
    def create_personal_collaboration_conversation(
        self,
        participant_identifiers: str = "",
        title: str = "",
    ) -> dict:
        return self._execute_operation(
            "create_personal_collaboration_conversation",
            lambda: {
                "conversation": create_personal_collaboration_conversation_for_current_user(
                    title=title,
                    participant_identifiers=participant_identifiers,
                )[0],
            },
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