# v2_pending_action_stubs.py
"""
The saved-action list request the V2 chat makes whenever a conversation is open.
Version: 0.261.489
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


# The other requests the V2 chat makes in the background while a conversation is open
# (0.261.489): action credentials waiting for re-entry, guided user-input requests, and
# orchestration questions. Each is answered as a user with nothing waiting would see it.
BACKGROUND_POLL_PAYLOADS = {
    "/api/action-credentials/pending": lambda: {"requests": [], "csrf_token": "fixture-csrf"},
    "/api/v2/user-input/pending": lambda: {"requests": [], "csrf_token": "fixture-csrf"},
    "/api/v2/orchestration/questions": lambda: {"questions": [], "csrf_token": "fixture-csrf"},
}


def background_poll_payload(method, path):
    """Return the empty answer for one of the chat's background polls, or None for other requests.

    A closed-API fixture calls this before its own routing so a suite about something else is
    not failed by a poll it was never written to expect::

        payload = background_poll_payload(request.method, path)
        if payload is not None:
            route.fulfill(json=payload)
            return
    """
    if method != "GET":
        return None
    if path == PENDING_ACTIONS_PATH:
        return pending_actions_payload()
    factory = BACKGROUND_POLL_PAYLOADS.get(path)
    return factory() if factory else None
