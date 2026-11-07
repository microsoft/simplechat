# user_input_plugin.py
"""Interactive questions, scoped to a retained V2 local-agent execution."""

from semantic_kernel.functions import kernel_function
from azure.core.exceptions import AzureError

from agent_interaction_contracts import agent_tool_call_id, UserInputError
from functions_user_input import request_user_input


INTERACTIVE_INPUT_INSTRUCTIONS = (
    "When a missing fact genuinely prevents you from continuing, use "
    "UserInput.request_user_input rather than asking an unstructured question in the final reply. "
    "Collect all currently known missing facts in one question set, usually two to four. "
    "Use useful suggestions with a custom answer for open questions. Do not invent optional "
    "interviews, repeat answered questions, ask for secrets, or use answers as action approval."
)


class UserInputPlugin:
    @kernel_function(
        name="request_user_input",
        description=(
            "Ask only for facts needed to continue the user's task. Collect all currently missing facts "
            "(usually 2-4) in one request. specification is JSON with message, requested_schema "
            "(a flat object schema with primitive properties and required names), and ui_hints. "
            "For open suggestions use a string/string-array without enum and "
            'ui_hints.fields[name]={"input":"choices","allow_custom":true,'
            '"choices":[{"value":"...","label":"..."}]}. '
            "Use enum only for genuinely closed choices. Never ask for secrets or treat an answer as "
            "permission to execute an outgoing action. Do not ask what the user already answered."
        ),
    )
    def ask(self, specification: str) -> str:
        try:
            return request_user_input(specification, agent_tool_call_id.get())
        except UserInputError:
            raise
        except (AzureError, ValueError, TypeError, PermissionError) as error:
            raise UserInputError("input_unavailable", 503) from error
