# v2_pending_action_stubs.py
"""
The saved-action list request the V2 chat makes whenever a conversation is open.
Version: 0.261.307
Implemented in: 0.261.307

The chat reads a conversation's saved Microsoft 365 actions (an email or a calendar change
waiting behind Send, Send now and Cancel) when the conversation opens, when the window comes back
into view, and after each reply ends. Closed-API fixtures that serve the built SPA answer it with
these helpers, as a user with nothing saved would see it, so a suite about something else is not
failed by a request it was never written to expect.

A suite about the cards themselves builds the list with `pending_actions_payload(actions)`.
"""

PENDING_ACTIONS_PATH = "/api/msgraph/pending-actions"


def pending_actions_payload(actions=None, continuation_token=None):
    """The answer of the pending-actions list route: one page of saved actions."""
    return {
        "success": True,
        "pending_actions": list(actions or []),
        "continuation_token": continuation_token,
    }


def is_pending_actions_list(method, path):
    """The conversation's list request. One action is read at `PATH/<id>`, which this skips."""
    return method == "GET" and path == PENDING_ACTIONS_PATH
