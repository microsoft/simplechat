#!/usr/bin/env python3
"""
Functional test for saving diagram and chart colours in shared conversations.

Version: 0.261.039
Implemented in: 0.261.039

Recolouring or resizing a mermaid diagram or a SimpleChart chart worked in a personal
conversation and failed in a shared one. The block changed on screen and then reported "That
change could not be saved", with a 404 in the console from:

    POST /api/message/<conversation_id>_<hex>/visual-style

The personal route resolves the conversation through the personal Cosmos container, which a
shared conversation is not in, so the write was refused before it ever reached the message. No
collaboration counterpart existed, and the client never branched on conversation kind for this
one action even though it does for renaming, deleting, pinning, hiding, marking read, deleting a
message and masking.

The same session logged a second 404 from `GET /api/conversations/<id>/metadata`. That one was
intentional — the client used it as a probe to work out whether a deep-linked conversation was
personal or shared — but it made every link to a shared conversation log a failed request. A
conversation-kind endpoint now answers the question directly.

What is asserted here is the wiring that was missing, and the two properties that make the
shared route safe: it validates through the same code as the personal one, so a payload that is
refused in a personal conversation is refused in a shared one, and it takes write access rather
than mere visibility, because the stored choice is seen by every participant.
"""

import ast
import copy
import importlib
import json
import re
import sys
from pathlib import Path

from flask import Flask

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))
sys.path.insert(0, str(APP_DIR))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

from azure.cosmos.exceptions import CosmosResourceNotFoundError  # noqa: E402

from functions_message_visual_styles import (  # noqa: E402
    UNSET,
    VISUAL_STYLES_METADATA_KEY,
    VisualStyleError,
    apply_visual_style,
    read_visual_styles,
)

IMPLEMENTED_IN = "0.261.039"

COLLABORATION_ROUTE = (
    "'/api/collaboration/conversations/<conversation_id>/messages/<message_id>/visual-style'"
)
KIND_ROUTE = "'/api/conversations/<conversation_id>/kind'"
VISUAL_STYLE_EVENT = "collaboration.message.visual_style_updated"


def _read(path):
    return path.read_text(encoding="utf-8", errors="ignore")


class _FakeCosmosDatabase:
    """Stand-in for the database config.py builds containers from at import time."""

    def create_container_if_not_exists(self, id, **kwargs):  # noqa: A002 - Cosmos' own name
        return _FakeMessageContainer()


class _FakeCosmosClient:
    """Stand-in that lets config.py be imported without reaching a live account."""

    def __init__(self, *args, **kwargs):
        self.database = _FakeCosmosDatabase()

    def create_database_if_not_exists(self, *args, **kwargs):
        return self.database


def _import_app_module(module_name):
    """Import an application module without letting config.py connect to Cosmos."""
    if module_name in sys.modules:
        return sys.modules[module_name]

    import azure.cosmos as azure_cosmos

    original = azure_cosmos.CosmosClient
    azure_cosmos.CosmosClient = _FakeCosmosClient
    try:
        return importlib.import_module(module_name)
    finally:
        azure_cosmos.CosmosClient = original


class _FakeMessageContainer:
    """In-memory message container that raises what the real one raises."""

    def __init__(self, items=None):
        self.items = {item["id"]: copy.deepcopy(item) for item in (items or [])}
        self.upserts = []

    def read_item(self, item=None, partition_key=None, *args, **kwargs):
        if item not in self.items:
            raise CosmosResourceNotFoundError(message="Not found")
        return copy.deepcopy(self.items[item])

    def upsert_item(self, item):
        self.items[item["id"]] = copy.deepcopy(item)
        self.upserts.append(copy.deepcopy(item))
        return copy.deepcopy(item)


class _RecordingEventRegistry:
    """Captures what the route broadcasts instead of holding open SSE subscribers."""

    def __init__(self):
        self.published = []

    def publish(self, conversation_id, event):
        self.published.append((conversation_id, copy.deepcopy(event)))


class _Patched:
    """Set module attributes for the duration of a block and put them back afterwards."""

    def __init__(self, module, **replacements):
        self.module = module
        self.replacements = replacements
        self.originals = {}

    def __enter__(self):
        for name, value in self.replacements.items():
            self.originals[name] = getattr(self.module, name)
            setattr(self.module, name, value)
        return self.module

    def __exit__(self, *exc_info):
        for name, value in self.originals.items():
            setattr(self.module, name, value)
        return False


def _neutralize_route_decorators():
    """Replace auth and documentation decorators so routes can be exercised directly."""
    return {
        "login_required": lambda func: func,
        "user_required": lambda func: func,
        "swagger_route": lambda **kwargs: (lambda func: func),
        "get_auth_security": lambda: {},
    }


def _route_function_source(file_name, function_name):
    """Return the source of one route handler, located by name rather than by offset."""
    path = APP_DIR / file_name
    source = _read(path)
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"{function_name} is not defined in {file_name}")


def _route_decorators(file_name, function_name):
    """Return the decorator names applied to one route handler."""
    path = APP_DIR / file_name
    tree = ast.parse(_read(path), filename=str(path))

    def dotted(node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = dotted(node.value)
            return f"{parent}.{node.attr}" if parent else node.attr
        if isinstance(node, ast.Call):
            return dotted(node.func)
        return ""

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return [dotted(decorator) for decorator in node.decorator_list]
    raise AssertionError(f"{function_name} is not defined in {file_name}")


def test_version_is_at_least_the_implementing_release():
    """The fix is present from the version it was implemented in onwards."""
    assert_app_version_at_least(IMPLEMENTED_IN)
    print("  ok  application version is at or beyond the implementing release")


def test_the_shared_conversation_route_exists():
    """A shared conversation has an endpoint that can save a block's colours."""
    source = _read(APP_DIR / "route_backend_collaboration.py")
    assert COLLABORATION_ROUTE in source, "the collaboration visual style route is missing"

    decorators = _route_decorators(
        "route_backend_collaboration.py", "set_collaboration_message_visual_style_api"
    )
    for required in ("bp.route", "swagger_route", "login_required", "user_required"):
        assert required in decorators, f"missing {required}"

    print("  ok  the shared conversation endpoint exists and is authenticated")


def test_the_shared_route_requires_write_access_and_the_feature_flag():
    """Restyling a shared block changes what everyone sees, so it needs write access."""
    block = _route_function_source(
        "route_backend_collaboration.py", "set_collaboration_message_visual_style_api"
    )

    # Participate, not view. A read-only viewer recolouring a chart would be changing the
    # conversation for the other participants.
    assert "assert_user_can_participate_in_collaboration_conversation" in block
    assert "assert_user_can_view_collaboration_conversation" not in block

    assert "_require_collaboration_feature_enabled" in block
    assert "PermissionError" in block

    # A message reached through a different conversation's URL is not this conversation's
    # message, however the lookup found it.
    assert "message_doc.get('conversation_id')" in block

    print("  ok  the shared endpoint requires write access and the feature flag")


def test_the_shared_route_reuses_the_personal_validator():
    """Both routes hand the payload to the same validator, so neither can drift."""
    shared = _route_function_source(
        "route_backend_collaboration.py", "set_collaboration_message_visual_style_api"
    )
    personal = _route_function_source("route_backend_chats.py", "set_message_visual_style_api")

    assert "apply_visual_style(" in shared
    assert "VisualStyleError" in shared

    # The shared route must not grow its own colour handling. If it did, a value refused in a
    # personal conversation could be stored in a shared one, and the stored value ends up in a
    # style attribute and in mermaid's theme configuration in a browser.
    for forbidden in ("normalize_hex_color", "HEX_COLOR_PATTERN", "sanitize_visual_style("):
        assert forbidden not in shared, f"{forbidden} was re-implemented on the shared route"

    # The same request fields, read the same way, including the distinction between a body that
    # omits the height and one that clears it.
    for field in ("block_kind", "block_index", "style", "source_hash"):
        assert f"data.get('{field}')" in shared, field
        assert f"data.get('{field}')" in personal, field

    height_read = "data.get('height') if 'height' in data else VISUAL_STYLE_HEIGHT_UNSET"
    assert height_read in shared
    assert height_read in personal

    print("  ok  the shared endpoint validates through the personal route's code")


def test_the_shared_route_writes_to_the_collaboration_container():
    """A shared message lives in its own container, and that is where the write must land."""
    block = _route_function_source(
        "route_backend_collaboration.py", "set_collaboration_message_visual_style_api"
    )

    assert "cosmos_collaboration_messages_container.upsert_item" in block
    # Writing to the personal container is the mistake this whole fix is about.
    assert "cosmos_messages_container.upsert_item" not in block

    print("  ok  the shared endpoint writes to the collaboration message container")


def test_the_shared_route_broadcasts_the_change():
    """Everyone sees the stored colours, so everyone is told when they change."""
    block = _route_function_source(
        "route_backend_collaboration.py", "set_collaboration_message_visual_style_api"
    )

    assert "COLLABORATION_EVENT_REGISTRY.publish" in block
    assert VISUAL_STYLE_EVENT in block
    assert "serialize_collaboration_message" in block

    print("  ok  the shared endpoint broadcasts the change to the other participants")


def test_the_stored_shape_is_the_same_in_both_kinds_of_conversation():
    """A shared message stores exactly what a personal one stores."""
    personal_message = {"id": "p1", "conversation_id": "c1", "metadata": {}}
    shared_message = {"id": "s1", "conversation_id": "c2", "metadata": {"sender": {}}}

    style = {"palette": "vivid", "background": "#112233", "colors": {"0": "#445566"}}
    for message in (personal_message, shared_message):
        apply_visual_style(message, "mermaid", 0, style, "abc123", 400)

    assert (
        read_visual_styles(personal_message)["mermaid"]["0"]
        == read_visual_styles(shared_message)["mermaid"]["0"]
    )

    # Metadata a shared message carries and a personal one does not is left alone, because the
    # collaboration serializer reads the sender back out of it.
    assert shared_message["metadata"]["sender"] == {}

    # Omitting the height keeps it; sending null clears it. Both routes rely on this, so it is
    # checked here rather than assumed from the personal route's tests.
    apply_visual_style(shared_message, "mermaid", 0, style, "abc123", UNSET)
    assert read_visual_styles(shared_message)["mermaid"]["0"]["height"] == 400
    apply_visual_style(shared_message, "mermaid", 0, style, "abc123", None)
    assert "height" not in read_visual_styles(shared_message)["mermaid"]["0"]

    # And a bad payload is still refused for a shared message.
    try:
        apply_visual_style(shared_message, "mermaid", 0, {"background": "red"}, "abc123")
        raise AssertionError("accepted a non-hex background on a shared message")
    except VisualStyleError:
        pass

    print("  ok  a shared message stores the same shape as a personal one")


def test_the_client_sends_a_shared_conversation_to_the_shared_endpoint():
    """The store branches on conversation kind, as it does for every other write."""
    store = _read(V2_SRC / "stores" / "chatStore.ts")
    collaboration = _read(V2_SRC / "lib" / "collaboration.ts")

    assert "setCollaborationMessageVisualStyle" in collaboration
    assert "/visual-style" in collaboration
    assert "setCollaborationMessageVisualStyle" in store

    body = store.split("applyVisualStyle: async")[1].split("forkFromMessage:")[0]
    assert "setCollaborationMessageVisualStyle(" in body
    assert "setMessageVisualStyleApi(" in body
    assert "collaborative" in body

    print("  ok  a shared conversation is saved through the shared endpoint")


def test_the_conversation_kind_is_captured_when_the_change_is_made():
    """A change flushed after the reader moved on still goes to the right endpoint."""
    block_style = _read(V2_SRC / "lib" / "blockVisualStyle.ts")

    # The conversation id was already captured at schedule time, for exactly this reason. The
    # kind has to travel with it: a pending change is flushed when the block unmounts, and
    # switching to a conversation of the other kind is one of the ways a block unmounts.
    assert "conversationKind" in block_style
    assert "activeConversationKind" in block_style
    assert "change.conversationKind" in block_style

    print("  ok  the conversation kind is captured with the change")


def test_the_deep_link_probe_no_longer_relies_on_a_404():
    """Opening a link to a shared conversation does not log a failed request."""
    store = _read(V2_SRC / "stores" / "chatStore.ts")
    endpoints = _read(V2_SRC / "lib" / "endpoints.ts")
    routes = _read(APP_DIR / "route_backend_conversations.py")

    assert KIND_ROUTE in routes, "the conversation kind route is missing"
    decorators = _route_decorators("route_backend_conversations.py", "get_conversation_kind_api")
    for required in ("bp.route", "swagger_route", "login_required", "user_required"):
        assert required in decorators, f"missing {required}"

    assert "fetchConversationKind" in endpoints
    assert "/kind" in endpoints

    resolver = store.split("async function resolveConversationKind")[1].split(
        "\n/**"
    )[0]
    assert "fetchConversationKind(" in resolver
    # The old probe: call the personal metadata endpoint and read its 404 as "not personal".
    assert "fetchConversationMetadata(" not in resolver
    assert "fetchCollaborationConversation(" not in resolver

    print("  ok  the deep-link kind probe no longer depends on a 404")


def test_the_kind_route_does_not_leak_conversations_or_misdirect_the_client():
    """Not yours reads as not there, and a disabled feature never answers 'shared'."""
    block = _route_function_source(
        "route_backend_conversations.py", "get_conversation_kind_api"
    )

    # A conversation the caller may not see must be reported as absent. Distinguishing the two
    # would confirm that a conversation with a given id exists.
    assert "except PermissionError:" in block
    forbidden_responses = re.findall(r"return jsonify\([^)]*\), 403", block)
    assert not forbidden_responses, forbidden_responses

    # Naming a conversation as shared while collaboration is switched off would send the client
    # to endpoints that refuse everything.
    assert "enable_collaborative_conversations" in block

    # The collaboration document travels with the answer, which is what the old two-request
    # probe was paying for.
    assert "serialize_collaboration_conversation" in block

    print("  ok  the kind route neither leaks conversations nor misdirects the client")


def test_a_broadcast_style_change_reaches_the_other_participants():
    """A change made by somebody else updates the block without reloading the thread."""
    events = _read(V2_SRC / "lib" / "collaborationEvents.ts")
    store = _read(V2_SRC / "stores" / "chatStore.ts")

    assert VISUAL_STYLE_EVENT in events
    assert "onMessageVisualStyleUpdated" in events
    assert "onMessageVisualStyleUpdated" in store

    handler = store.split("onMessageVisualStyleUpdated:")[1].split("onTyping:")[0]
    # Only the styles are taken. The broadcast carries the whole message, and replacing it
    # wholesale would discard client-side state the thread built up around it.
    assert "visual_styles" in handler
    assert "stillOpen()" in handler

    # A colour change is cosmetic; announcing every drag on somebody else's screen is noise.
    # Comments are stripped first so this reads the code rather than the prose about it.
    code = "\n".join(
        line for line in handler.splitlines() if not line.strip().startswith("//")
    )
    assert "toast" not in code, "the broadcast handler raises a notification"

    print("  ok  a broadcast style change updates the open thread")


def test_no_new_browser_dependency_or_remote_asset_was_introduced():
    """The fix stays inside the existing local bundles."""
    package_json = json.loads(
        _read(REPO_ROOT / "application" / "v2_ui" / "package.json")
    )
    declared = set(package_json.get("dependencies", {})) | set(
        package_json.get("devDependencies", {})
    )
    for forbidden in ("axios", "socket.io-client", "eventsource", "swr", "react-query"):
        assert forbidden not in declared, f"{forbidden} was added as a dependency"

    for path in (
        V2_SRC / "lib" / "blockVisualStyle.ts",
        V2_SRC / "lib" / "collaboration.ts",
        V2_SRC / "lib" / "collaborationEvents.ts",
        V2_SRC / "lib" / "endpoints.ts",
        V2_SRC / "stores" / "chatStore.ts",
    ):
        urls = re.findall(r"https?://[^\s'\"`)]+", _read(path))
        unexpected = [
            url
            for url in urls
            if url not in ("http://www.w3.org/2000/svg", "http://www.w3.org/1999/xlink")
        ]
        assert not unexpected, f"{path.name} references {unexpected}"

    print("  ok  no new browser dependency or remote asset was introduced")


def test_the_personal_route_is_unchanged_in_behaviour():
    """A personal conversation still saves exactly as it did before."""
    block = _route_function_source("route_backend_chats.py", "set_message_visual_style_api")

    assert "_authorize_personal_conversation_access" in block
    assert "cosmos_messages_container.read_item" in block
    assert "cosmos_messages_container.upsert_item" in block
    # The personal route still takes the conversation in the body, so no client that has not
    # been rebuilt starts failing.
    assert "data.get('conversation_id')" in block

    message = {"id": "p1", "conversation_id": "c1", "metadata": {}}
    apply_visual_style(message, "simplechart", 2, {"palette": "calm"}, "ffff0000")
    assert VISUAL_STYLES_METADATA_KEY in message["metadata"]
    assert read_visual_styles(message)["simplechart"]["2"]["palette"] == "calm"

    print("  ok  the personal endpoint is unchanged")


def _shared_style_client(
    message_container,
    registry,
    participate=None,
    conversation=None,
    message_lookup=None,
):
    """Register the collaboration routes against in-memory dependencies."""
    module = _import_app_module("route_backend_collaboration")

    conversation_doc = conversation or {"id": "shared-1", "title": "Shared"}

    def _participate(user_id, conversation_doc_arg):
        if participate is not None:
            return participate(user_id, conversation_doc_arg)
        return {}

    def _get_message(message_id):
        if message_lookup is not None:
            return message_lookup(message_id)
        if message_id not in message_container.items:
            raise CosmosResourceNotFoundError(message="Collaborative message not found")
        return copy.deepcopy(message_container.items[message_id])

    patches = _neutralize_route_decorators()
    patches.update(
        cosmos_collaboration_messages_container=message_container,
        COLLABORATION_EVENT_REGISTRY=registry,
        _require_collaboration_feature_enabled=lambda: {},
        _get_current_collaboration_user=lambda: {"user_id": "user-1"},
        get_collaboration_conversation=lambda conversation_id: conversation_doc,
        assert_user_can_participate_in_collaboration_conversation=_participate,
        get_collaboration_message=_get_message,
    )

    return module, patches


def _post_shared_style(module, patches, message_id, body, conversation_id="shared-1"):
    """Call the shared visual style route once and return (status, payload)."""
    with _Patched(module, **patches):
        app = Flask(__name__)
        app.config["TESTING"] = True
        module.register_route_backend_collaboration(app)
        path = (
            f"/api/collaboration/conversations/{conversation_id}"
            f"/messages/{message_id}/visual-style"
        )
        # Dispatched through a request context rather than a test client: this project's other
        # route tests do the same, and `test_client` reads `werkzeug.__version__`, which newer
        # Werkzeug releases no longer define.
        with app.test_request_context(path, method="POST", json=body):
            response = app.full_dispatch_request()
        return response.status_code, response.get_json()


def test_a_shared_block_can_actually_be_restyled():
    """The request that used to 404 now stores the colours on the shared message."""
    container = _FakeMessageContainer(
        [
            {
                "id": "shared-1_abc",
                "conversation_id": "shared-1",
                "role": "assistant",
                "content": "```mermaid\ngraph TD;A-->B;\n```",
                "metadata": {"sender": {"user_id": "user-1"}},
            }
        ]
    )
    registry = _RecordingEventRegistry()
    module, patches = _shared_style_client(container, registry)

    status, payload = _post_shared_style(
        module,
        patches,
        "shared-1_abc",
        {
            "block_kind": "mermaid",
            "block_index": 0,
            "source_hash": "deadbeef",
            "style": {"palette": "vivid", "background": "#101820", "colors": {"0": "#ff8800"}},
            "height": 520,
        },
    )

    assert status == 200, payload
    stored = payload["visual_styles"]["mermaid"]["0"]
    assert stored["palette"] == "vivid"
    assert stored["background"] == "#101820"
    assert stored["colors"] == {"0": "#ff8800"}
    assert stored["height"] == 520
    assert stored["source_hash"] == "deadbeef"

    # It reached the collaboration container, which is the whole point of the fix.
    written = container.items["shared-1_abc"]["metadata"][VISUAL_STYLES_METADATA_KEY]
    assert written["mermaid"]["0"]["palette"] == "vivid"
    # Metadata the collaboration serializer depends on survives the write.
    assert container.items["shared-1_abc"]["metadata"]["sender"] == {"user_id": "user-1"}

    # And the other participants are told, so their charts do not stay the old colour.
    assert len(registry.published) == 1
    conversation_id, event = registry.published[0]
    assert conversation_id == "shared-1"
    assert event["event_type"] == VISUAL_STYLE_EVENT
    assert event["payload"]["message_id"] == "shared-1_abc"
    assert event["payload"]["updated_by_user_id"] == "user-1"
    assert (
        event["payload"]["message"]["metadata"][VISUAL_STYLES_METADATA_KEY]["mermaid"]["0"][
            "palette"
        ]
        == "vivid"
    )

    print("  ok  a shared block is restyled and the change is broadcast")


def test_a_shared_resize_and_recolour_stay_independent():
    """Recolouring does not reset a size, and clearing colours does not clear the size."""
    container = _FakeMessageContainer(
        [
            {
                "id": "shared-1_abc",
                "conversation_id": "shared-1",
                "role": "assistant",
                "content": "```simplechart\n{}\n```",
                "metadata": {},
            }
        ]
    )
    module, patches = _shared_style_client(container, _RecordingEventRegistry())

    base = {"block_kind": "simplechart", "block_index": 0, "source_hash": "cafe1234"}
    style = {"palette": "warm", "background": "theme", "colors": {}}

    status, _ = _post_shared_style(
        module, patches, "shared-1_abc", {**base, "style": style, "height": 480}
    )
    assert status == 200

    # A recolour that says nothing about the height keeps it.
    status, payload = _post_shared_style(
        module,
        patches,
        "shared-1_abc",
        {**base, "style": {**style, "palette": "calm"}},
    )
    assert status == 200
    assert payload["visual_styles"]["simplechart"]["0"]["height"] == 480
    assert payload["visual_styles"]["simplechart"]["0"]["palette"] == "calm"

    # An explicit null clears it.
    status, payload = _post_shared_style(
        module, patches, "shared-1_abc", {**base, "style": style, "height": None}
    )
    assert status == 200
    assert "height" not in payload["visual_styles"]["simplechart"]["0"]

    # Clearing the colours leaves the block following the reader's own default.
    status, payload = _post_shared_style(
        module, patches, "shared-1_abc", {**base, "style": None}
    )
    assert status == 200
    assert payload["visual_styles"] == {}

    print("  ok  a shared block's size and colours are changed independently")


def test_a_shared_block_refuses_what_a_personal_one_refuses():
    """The values that reach a browser are constrained identically in both kinds."""
    container = _FakeMessageContainer(
        [
            {
                "id": "shared-1_abc",
                "conversation_id": "shared-1",
                "role": "assistant",
                "content": "",
                "metadata": {},
            }
        ]
    )
    module, patches = _shared_style_client(container, _RecordingEventRegistry())

    base = {"block_kind": "mermaid", "block_index": 0, "source_hash": "aaaa1111"}
    for rejected in (
        {**base, "style": {"palette": "vivid", "background": "javascript:alert(1)"}},
        {**base, "style": {"palette": "../../etc/passwd"}},
        {**base, "style": {"palette": "vivid", "colors": {"0": "red"}}},
        {**base, "block_kind": "script", "style": {"palette": "vivid"}},
        {**base, "block_index": -1, "style": {"palette": "vivid"}},
        {**base, "style": {"palette": "vivid"}, "height": float("inf")},
    ):
        status, payload = _post_shared_style(module, patches, "shared-1_abc", rejected)
        assert status == 400, (rejected, status, payload)

    assert container.upserts == [], "a refused request wrote to the message"

    print("  ok  a shared block refuses the same payloads a personal one refuses")


def test_a_shared_block_cannot_be_restyled_without_write_access():
    """A viewer cannot change what every other participant sees."""
    container = _FakeMessageContainer(
        [
            {
                "id": "shared-1_abc",
                "conversation_id": "shared-1",
                "role": "assistant",
                "content": "",
                "metadata": {},
            }
        ]
    )

    def _refuse(user_id, conversation_doc):
        raise PermissionError("You do not have permission to post in this conversation")

    module, patches = _shared_style_client(
        container, _RecordingEventRegistry(), participate=_refuse
    )
    status, payload = _post_shared_style(
        module,
        patches,
        "shared-1_abc",
        {"block_kind": "mermaid", "block_index": 0, "source_hash": "a1", "style": None},
    )

    assert status == 403, payload
    assert container.upserts == []

    print("  ok  restyling a shared block requires write access")


def test_a_message_from_another_conversation_is_not_found():
    """A message id is not a capability: it must belong to the conversation in the URL."""
    container = _FakeMessageContainer(
        [
            {
                "id": "other-1_abc",
                "conversation_id": "other-1",
                "role": "assistant",
                "content": "",
                "metadata": {},
            }
        ]
    )
    module, patches = _shared_style_client(container, _RecordingEventRegistry())

    status, payload = _post_shared_style(
        module,
        patches,
        "other-1_abc",
        {"block_kind": "mermaid", "block_index": 0, "source_hash": "a1", "style": None},
    )
    assert status == 404, payload

    status, payload = _post_shared_style(
        module,
        patches,
        "does-not-exist",
        {"block_kind": "mermaid", "block_index": 0, "source_hash": "a1", "style": None},
    )
    assert status == 404, payload

    assert container.upserts == []

    print("  ok  a message from another conversation is refused")


def _get_conversation_kind(
    conversation_id,
    personal_items=(),
    user_id="user-1",
    collaboration_enabled=True,
    collaboration_doc=None,
    collaboration_error=None,
    view_error=None,
):
    """Call the conversation kind route once and return (status, payload)."""
    module = _import_app_module("route_backend_conversations")

    class _PersonalContainer:
        def __init__(self, items):
            self.items = {item["id"]: copy.deepcopy(item) for item in items}

        def read_item(self, item=None, partition_key=None, *args, **kwargs):
            if item not in self.items:
                raise CosmosResourceNotFoundError(message="Not found")
            return copy.deepcopy(self.items[item])

    def _get_collaboration(requested_id):
        if collaboration_error is not None:
            raise collaboration_error
        if collaboration_doc is None:
            raise CosmosResourceNotFoundError(message="Not found")
        return collaboration_doc

    def _assert_can_view(requesting_user_id, conversation_doc, allow_pending=False):
        if view_error is not None:
            raise view_error
        return {"user_state": {"role": "member"}}

    patches = _neutralize_route_decorators()
    patches.update(
        cosmos_conversations_container=_PersonalContainer(personal_items),
        get_current_user_id=lambda: user_id,
        get_settings=lambda: {"enable_collaborative_conversations": collaboration_enabled},
        get_collaboration_conversation=_get_collaboration,
        assert_user_can_view_collaboration_conversation=_assert_can_view,
        serialize_collaboration_conversation=lambda doc, current_user_id=None, user_state=None: {
            "id": doc.get("id"),
            "title": doc.get("title"),
            "current_user_role": (user_state or {}).get("role"),
        },
    )

    with _Patched(module, **patches):
        app = Flask(__name__)
        app.config["TESTING"] = True
        module.register_route_backend_conversations(app)
        path = f"/api/conversations/{conversation_id}/kind"
        with app.test_request_context(path, method="GET"):
            response = app.full_dispatch_request()
        return response.status_code, response.get_json()


def test_the_kind_route_answers_for_both_families():
    """One request tells the client which endpoints a linked conversation belongs to."""
    status, payload = _get_conversation_kind(
        "personal-1",
        personal_items=[{"id": "personal-1", "user_id": "user-1", "title": "Mine"}],
    )
    assert status == 200, payload
    assert payload["kind"] == "personal"
    assert payload["conversation_id"] == "personal-1"
    # Nothing about a personal conversation beyond its kind, which is all that was asked.
    assert "conversation" not in payload

    status, payload = _get_conversation_kind(
        "shared-1",
        collaboration_doc={"id": "shared-1", "title": "Shared"},
    )
    assert status == 200, payload
    assert payload["kind"] == "collaborative"
    # The document travels with the answer, which is what the old two-request probe was for.
    assert payload["conversation"]["id"] == "shared-1"
    assert payload["conversation"]["current_user_role"] == "member"

    print("  ok  the kind route answers for personal and shared conversations")


def test_the_kind_route_reports_inaccessible_conversations_as_absent():
    """Not yours, not there and not permitted all read the same from outside."""
    # Somebody else's personal conversation, which is not a shared one either.
    status, payload = _get_conversation_kind(
        "personal-1",
        personal_items=[{"id": "personal-1", "user_id": "someone-else", "title": "Theirs"}],
    )
    assert status == 404, (status, payload)

    # A shared conversation the caller is not a member of.
    status, payload = _get_conversation_kind(
        "shared-1",
        collaboration_doc={"id": "shared-1"},
        view_error=PermissionError("You do not have access to this conversation"),
    )
    assert status == 404, (status, payload)

    # A conversation that does not exist at all.
    status, payload = _get_conversation_kind("nope")
    assert status == 404, (status, payload)

    print("  ok  an inaccessible conversation is reported as absent")


def test_the_kind_route_never_names_a_shared_conversation_when_sharing_is_off():
    """With collaboration disabled, its endpoints refuse everything, so do not point there."""
    status, payload = _get_conversation_kind(
        "shared-1",
        collaboration_doc={"id": "shared-1", "title": "Shared"},
        collaboration_enabled=False,
    )
    assert status == 404, (status, payload)

    # A personal conversation is still resolved with collaboration switched off.
    status, payload = _get_conversation_kind(
        "personal-1",
        personal_items=[{"id": "personal-1", "user_id": "user-1"}],
        collaboration_enabled=False,
    )
    assert status == 200, payload
    assert payload["kind"] == "personal"

    print("  ok  a disabled collaboration feature never yields a shared answer")


def test_a_conversation_that_is_not_a_shared_one_is_not_found():
    """A document that is not a collaborative conversation is absent, not a server error.

    `assert_user_can_view_collaboration_conversation` signals that with `LookupError`, which is
    neither the Cosmos not-found error nor a `PermissionError`, so without handling it the
    request would surface as a 500.
    """
    status, payload = _get_conversation_kind(
        "shared-1",
        collaboration_doc={"id": "shared-1"},
        view_error=LookupError("Collaboration conversation not found"),
    )
    assert status == 404, (status, payload)

    container = _FakeMessageContainer(
        [
            {
                "id": "shared-1_abc",
                "conversation_id": "shared-1",
                "role": "assistant",
                "content": "",
                "metadata": {},
            }
        ]
    )

    def _not_collaborative(user_id, conversation_doc):
        raise LookupError("Collaboration conversation not found")

    module, patches = _shared_style_client(
        container, _RecordingEventRegistry(), participate=_not_collaborative
    )
    status, payload = _post_shared_style(
        module,
        patches,
        "shared-1_abc",
        {"block_kind": "mermaid", "block_index": 0, "source_hash": "a1", "style": None},
    )
    assert status == 404, (status, payload)
    assert container.upserts == []

    print("  ok  a document that is not a shared conversation reads as not found")


TESTS = [
    test_version_is_at_least_the_implementing_release,
    test_the_shared_conversation_route_exists,
    test_the_shared_route_requires_write_access_and_the_feature_flag,
    test_the_shared_route_reuses_the_personal_validator,
    test_the_shared_route_writes_to_the_collaboration_container,
    test_the_shared_route_broadcasts_the_change,
    test_the_stored_shape_is_the_same_in_both_kinds_of_conversation,
    test_the_client_sends_a_shared_conversation_to_the_shared_endpoint,
    test_the_conversation_kind_is_captured_when_the_change_is_made,
    test_the_deep_link_probe_no_longer_relies_on_a_404,
    test_the_kind_route_does_not_leak_conversations_or_misdirect_the_client,
    test_a_broadcast_style_change_reaches_the_other_participants,
    test_no_new_browser_dependency_or_remote_asset_was_introduced,
    test_the_personal_route_is_unchanged_in_behaviour,
    test_a_shared_block_can_actually_be_restyled,
    test_a_shared_resize_and_recolour_stay_independent,
    test_a_shared_block_refuses_what_a_personal_one_refuses,
    test_a_shared_block_cannot_be_restyled_without_write_access,
    test_a_message_from_another_conversation_is_not_found,
    test_the_kind_route_answers_for_both_families,
    test_the_kind_route_reports_inaccessible_conversations_as_absent,
    test_the_kind_route_never_names_a_shared_conversation_when_sharing_is_off,
    test_a_conversation_that_is_not_a_shared_one_is_not_found,
]


def main():
    print("Testing shared conversation diagram and chart styling...\n")
    failures = []

    for test in TESTS:
        try:
            test()
        except Exception as error:  # noqa: BLE001 - a failure must not stop the rest
            failures.append(test.__name__)
            print(f"FAIL  {test.__name__}: {error}")
            import traceback

            traceback.print_exc()

    print(f"\n{len(TESTS) - len(failures)}/{len(TESTS)} tests passed")
    if failures:
        print("Failed: " + ", ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
