# agent_interaction_contracts.py
"""Typed, bootstrap-free stops at a retained agent tool boundary."""

from contextvars import ContextVar


agent_tool_call_id = ContextVar("agent_tool_call_id", default=None)


class AgentInteractionRequired(RuntimeError):
    """A tool is waiting for a person, not a failed model invocation."""


def find_agent_interaction(error, error_type=AgentInteractionRequired):
    seen = set()
    while error is not None and id(error) not in seen:
        if isinstance(error, error_type):
            return error
        seen.add(id(error))
        error = error.__cause__ or error.__context__
    return None


class UserInputRequired(AgentInteractionRequired):
    def __init__(self, input_request):
        super().__init__("The agent is waiting for an answer.")
        self.input_request = input_request

    @property
    def event(self):
        return {"type": "user_input_required", "input_request": self.input_request}


class UserInputError(ValueError):
    def __init__(self, code="input_unavailable", status_code=409):
        self.code, self.status_code = code, status_code
        super().__init__("This question could not be continued. Refresh the conversation.")
