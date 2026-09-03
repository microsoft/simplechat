#!/usr/bin/env python3
# test_image_proposal_status_endpoint.py
"""
Functional test for the image proposal status route.

Version: 0.261.053
Implemented in: 0.261.053

`GET /api/chat/image-proposals/status/<conversation_id>` exists so a client that reloaded the
page during an image approval can find out whether the image it was waiting for has arrived.
The approval is a blocking POST that the server finishes regardless of who is still connected,
so the work is never lost -- only the knowledge of it.

Everything worth asserting about this route follows from the fact that it is *polled*:

  - It must be cheap. A small generated image is inlined into its message's `content` as a
    base64 data URI, so returning message content would make every poll re-download the thread.
    The route projects identities only.
  - It must be scoped. A query without a partition key would fan out across every conversation
    in the container, at a cost paid per poll.
  - It must be no more permissive than the approval it reports on. It reuses the same
    authorization helper, so there is no second access path to keep in step.
  - It must not build its query out of what the caller sent. The conversation id and the
    `since` window both come from the request and both reach Cosmos as bound parameters.

These are checked against the parsed route rather than the file text, so a rename or a
reformat cannot quietly satisfy them.
"""

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
CHAT_ROUTES = APP_DIR / "route_backend_chats.py"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

IMPLEMENTED_IN = "0.261.053"

ROUTE_FUNCTION = "image_proposal_status"
ROUTE_PATH = "/api/chat/image-proposals/status/<conversation_id>"

# Fields the route is allowed to return for each result. Each one is needed to reunite an
# image with the card that is waiting for it; anything else is weight on a polled request.
ALLOWED_RESULT_FIELDS = {
    "message_id",
    "created_at",
    "source_assistant_message_id",
    "visual_id",
    "title",
    "prompt",
}


def _route_function():
    """The parsed status route, or a failure explaining that it is gone."""
    tree = ast.parse(CHAT_ROUTES.read_text(encoding="utf-8", errors="ignore"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == ROUTE_FUNCTION:
            return node
    raise AssertionError(f"{ROUTE_FUNCTION} is not defined in {CHAT_ROUTES.name}.")


def _decorator_name(node):
    target = node.func if isinstance(node, ast.Call) else node
    parts = []
    while isinstance(target, ast.Attribute):
        parts.append(target.attr)
        target = target.value
    if isinstance(target, ast.Name):
        parts.append(target.id)
    return ".".join(reversed(parts))


def _calls(node, name):
    """Every call to `name` inside the function, by dotted name."""
    return [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Call) and _decorator_name(child) == name
    ]


def test_the_route_is_registered_on_the_chat_blueprint():
    """A direct app route would sit outside the blueprint's security policy."""
    print("Testing route registration...")
    function = _route_function()
    decorators = [_decorator_name(item) for item in function.decorator_list]

    if decorators[0] != "bp.route":
        raise AssertionError(
            "The status route is not registered on the chat blueprint, so it does not inherit "
            f"that blueprint's security policy. Decorators: {decorators}"
        )

    route_call = function.decorator_list[0]
    path = route_call.args[0].value if route_call.args else None
    if path != ROUTE_PATH:
        raise AssertionError(f"The status route path is {path!r}, expected {ROUTE_PATH!r}.")

    methods = next(
        (kw.value for kw in route_call.keywords if kw.arg == "methods"),
        None,
    )
    method_names = [element.value for element in getattr(methods, "elts", [])]
    if method_names != ["GET"]:
        raise AssertionError(
            f"The status route accepts {method_names}. A read that is polled should be a GET "
            "and nothing else."
        )
    print(f"  {ROUTE_PATH} is a GET on the chat blueprint.")

    print("Route registration test passed!")
    return True


def test_the_route_carries_the_required_decorators():
    """Every route in this application declares its swagger security and its auth."""
    print("Testing decorators...")
    function = _route_function()
    decorators = [_decorator_name(item) for item in function.decorator_list]

    for required in ("swagger_route", "login_required", "user_required"):
        if required not in decorators:
            raise AssertionError(
                f"The status route is missing @{required}. Decorators: {decorators}"
            )

    # Order is part of the contract: the swagger declaration wraps the authenticated view, so
    # it has to sit above the auth decorators.
    if decorators.index("swagger_route") > decorators.index("login_required"):
        raise AssertionError(
            "@swagger_route is applied below the authentication decorators."
        )
    print("  swagger_route, login_required and user_required, in that order.")

    swagger = function.decorator_list[decorators.index("swagger_route")]
    security = next((kw for kw in swagger.keywords if kw.arg == "security"), None)
    if security is None or _decorator_name(security.value) != "get_auth_security":
        raise AssertionError("@swagger_route does not declare get_auth_security().")
    print("  The swagger security comes from get_auth_security().")

    print("Decorator test passed!")
    return True


def test_the_route_authorizes_before_it_reads():
    """A read that authorizes afterwards has already leaked what it was guarding."""
    print("Testing authorization...")
    function = _route_function()

    authorizations = _calls(function, "_authorize_personal_conversation_access")
    if not authorizations:
        raise AssertionError(
            "The status route does not authorize the conversation with the same helper the "
            "approval route uses, so it is a second access path that can drift out of step."
        )

    queries = _calls(function, "cosmos_messages_container.query_items")
    if not queries:
        raise AssertionError("The status route never queries for the conversation's images.")

    if min(call.lineno for call in authorizations) > min(call.lineno for call in queries):
        raise AssertionError(
            "The conversation is read before the caller is authorized to read it."
        )
    print("  It authorizes with the approval route's helper, before reading anything.")

    # 401 for no user is not the same as 403 for the wrong user, and neither is a 200.
    returns = ast.dump(function)
    for expected in ("'User not authenticated'", "'You do not have access to this conversation'"):
        if expected not in returns:
            raise AssertionError(f"The status route never returns {expected}.")
    print("  Unauthenticated and unauthorized callers are answered differently.")

    print("Authorization test passed!")
    return True


def test_the_query_is_scoped_and_parameterised():
    """A polled query has to be cheap, and it is built from what the caller sent."""
    print("Testing the query...")
    function = _route_function()
    query_call = _calls(function, "cosmos_messages_container.query_items")[0]

    keywords = {kw.arg for kw in query_call.keywords}
    if "partition_key" not in keywords:
        raise AssertionError(
            "The query has no partition key, so it fans out across every conversation in the "
            "container -- on every poll."
        )
    if "parameters" not in keywords:
        raise AssertionError("The query passes no bound parameters.")
    print("  It is scoped to the conversation's partition and takes bound parameters.")

    # The conversation id and the `since` window both come from the request. Neither may be
    # concatenated or interpolated into the query text; both reach Cosmos as parameters.
    query_source = ast.get_source_segment(
        CHAT_ROUTES.read_text(encoding="utf-8", errors="ignore"), function
    )
    query_assignment = re.search(r"query = \(\s*([\s\S]*?)\)\n", query_source)
    if not query_assignment:
        raise AssertionError("The query text could not be read from the route.")
    clause_assignment = re.search(r"clauses = \[\s*([\s\S]*?)\]\n", query_source)
    # The WHERE clauses are assembled separately from the statement they are joined into, so
    # both halves of the query text have to be inspected.
    query_text = query_assignment.group(1) + (
        clause_assignment.group(1) if clause_assignment else ""
    )

    for tainted in ("conversation_id", "normalized_conversation_id", "since"):
        if re.search(rf"\{{\s*{tainted}\b", query_text):
            raise AssertionError(
                f"`{tainted}` is interpolated into the query text rather than bound as a "
                "parameter."
            )
    for bound in ("@conversation_id", "@limit"):
        if bound not in query_text:
            raise AssertionError(f"The query does not bind {bound}.")
    print("  Nothing the caller sent is interpolated into the query text.")

    if "@since" not in query_source:
        raise AssertionError(
            "The route ignores the `since` window, so every poll reads every proposal image "
            "the conversation has ever contained."
        )
    print("  The since window is honoured, and bound.")

    print("Query test passed!")
    return True


def test_the_route_returns_no_image_bytes():
    """This exists to be cheaper than reading the thread. Returning content would not be."""
    print("Testing the response...")
    source = CHAT_ROUTES.read_text(encoding="utf-8", errors="ignore")
    function = _route_function()
    route_source = ast.get_source_segment(source, function)

    projected = re.search(r"SELECT TOP @limit ([^\"']+)", route_source)
    if not projected:
        raise AssertionError("The query does not project a fixed set of fields.")
    projection = projected.group(1)
    if "*" in projection:
        raise AssertionError(
            "The query selects whole documents. A small generated image is inlined into "
            "`content` as a base64 data URI, so a poll would re-download the thread."
        )
    print(f"  The query projects only: {projection.strip()}")

    # The response is built as a literal, so the fields it can carry are knowable here.
    result_dicts = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Dict)
        and any(
            isinstance(key, ast.Constant) and key.value == "message_id" for key in node.keys
        )
    ]
    if not result_dicts:
        raise AssertionError("The route does not build a result record for each image.")

    fields = {
        key.value
        for node in result_dicts
        for key in node.keys
        if isinstance(key, ast.Constant)
    }
    unexpected = fields - ALLOWED_RESULT_FIELDS
    if unexpected:
        raise AssertionError(
            f"The status route returns unexpected fields: {sorted(unexpected)}. Anything beyond "
            "an image's identity is weight on a request made every few seconds."
        )
    missing = {"message_id", "source_assistant_message_id", "prompt"} - fields
    if missing:
        raise AssertionError(
            f"The status route omits {sorted(missing)}, which a client needs to tell whether an "
            "image is the one it is waiting for."
        )
    print(f"  Each result carries only: {sorted(fields)}")

    print("Response test passed!")
    return True


def test_the_result_limit_is_bounded():
    """An unbounded read is an unbounded cost, repeated on a timer."""
    print("Testing the result limit...")
    source = CHAT_ROUTES.read_text(encoding="utf-8", errors="ignore")

    match = re.search(r"IMAGE_PROPOSAL_STATUS_RESULT_LIMIT = (\d+)", source)
    if not match:
        raise AssertionError("The status route has no result limit.")

    limit = int(match.group(1))
    if not 1 <= limit <= 1000:
        raise AssertionError(f"The result limit is {limit}, which is not a sane ceiling.")

    function = _route_function()
    if "IMAGE_PROPOSAL_STATUS_RESULT_LIMIT" not in ast.get_source_segment(source, function):
        raise AssertionError("The route does not apply the limit it defines.")
    print(f"  Capped at {limit} results.")

    print("Result limit test passed!")
    return True


def test_version_was_incremented():
    """The application version records when this shipped."""
    print("Testing version...")
    version = assert_app_version_at_least(
        IMPLEMENTED_IN,
        reason="The image proposal status route.",
    )
    print(f"  config.py VERSION is {version}.")
    print("Version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_the_route_is_registered_on_the_chat_blueprint,
        test_the_route_carries_the_required_decorators,
        test_the_route_authorizes_before_it_reads,
        test_the_query_is_scoped_and_parameterised,
        test_the_route_returns_no_image_bytes,
        test_the_result_limit_is_bounded,
        test_version_was_incremented,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(test())
        except Exception as error:  # noqa: BLE001
            print(f"FAILED: {error}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(1 for r in results if r)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
