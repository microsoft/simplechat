# test_ui_interface_selection.py
"""Real-owner interface preference persistence, policy and SDK regressions.

Version: 0.261.449
Implemented in: 0.261.449

Fresh normal/optimized processes keep application imports real and block network.
Only external storage is doubled using the installed SDK response representation.
"""

import pytest

from test_orchestration_result_imports import run_probe


PROBE = r'''
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports
from test_support.m365 import CosmosContainer

def check(value, message):
    if not value:
        raise AssertionError(message)

with offline_app_imports():
    import app as web
    import functions_settings as owner
    import functions_ui_mode as modes
    import functions_ui_pages as pages
    import functions_ui_redirect as redirects
    import route_backend_users as users
    import route_frontend_terms_of_use as terms_routes
    from flask import Blueprint, Flask, session
    from azure.cosmos._cosmos_responses import CosmosDict
    from admin_settings_fields import normalize_admin_settings_updates

    app = Flask("ui_selection", template_folder=str(Path(sys.argv[1]) / "templates"), static_folder=web.app.static_folder)
    app.secret_key = "test-only"
    app.config["TESTING"] = True
    bp = Blueprint("users_test", __name__)
    users.register_route_backend_users(bp)
    app.register_blueprint(bp)
    app.add_url_rule("/chats", "classic_chat", lambda: "legacy")
    app.add_url_rule("/v2/chat", "modern_chat", lambda: "modern")
    app.add_url_rule("/v2/groups/directory", "modern_directory", lambda: "modern")
    app.add_url_rule("/", "public_app.index", lambda: "home")
    app.add_url_rule("/login", "frontend_authentication.login", lambda: "login")
    terms_bp = Blueprint("frontend_terms_of_use", __name__)
    terms_routes.register_route_frontend_terms_of_use(terms_bp)
    app.register_blueprint(terms_bp)
    store = CosmosContainer("id")
    for who in ("alice", "bob"):
        store.upsert_item({
            "id": who, "display_name": who, "email": who + "@example.test",
            "settings": {"profileImage": None, "agents": [], "plugins": [], "enable_agents": False},
        })
    policy = {"ui_mode_policy": "both", "ui_default_mode": "modern"}
    with ExitStack() as stack:
        stack.enter_context(patch.object(owner, "cosmos_user_settings_container", store))
        stack.enter_context(patch.object(users, "cosmos_user_settings_container", store))
        stack.enter_context(patch.object(users, "get_settings", return_value=policy))

        def client(who, roles=("User",)):
            result = app.test_client()
            with result.session_transaction() as state:
                state["user"] = {"oid": who, "roles": list(roles)}
            return result

        alice, bob = client("alice"), client("bob")
        with app.test_request_context("/chats"):
            session["user"] = {"oid": "alice", "roles": ["User"]}
            check(modes.get_ui_mode(policy) == "modern", "Initial account default changed")
        for value in (True, None, [], {}, "legacy"):
            result = alice.post("/api/user/settings", json={"settings": {"preferredUiMode": value}})
            check(result.status_code == 400, "Invalid preference accepted")
        result = alice.post("/api/user/settings", json={"settings": {"preferredUiMode": "classic"}})
        check(result.status_code == 200, "Valid preference was not saved: " + result.get_data(as_text=True))
        stored = store.read_item("alice", "alice")
        check(isinstance(stored, CosmosDict), "Point-read evidence must use installed SDK")
        check(stored["settings"]["preferredUiMode"] == "classic", "Preference not durable")
        result = client("alice").get("/api/user/settings")
        check(result.json["settings"]["preferredUiMode"] == "classic", "New session lost preference")
        with patch.object(
            owner.app_settings_cache, "get_user_ui_settings_cache",
            return_value={"preferredUiMode": "modern"},
        ), app.test_request_context("/chats"):
            session["user"] = {"oid": "alice", "roles": ["User"]}
            check(modes.get_ui_mode(policy) == "classic", "A stale worker UI cache overrode the saved preference")
        with app.test_request_context("/chats"):
            session["user"] = {"oid": "bob", "roles": ["User"]}
            check(modes.get_ui_mode(policy) == "modern", "Preference leaked across accounts")
        with patch.object(users, "update_user_settings", return_value=False):
            result = alice.post("/api/user/settings", json={"settings": {"preferredUiMode": "modern"}})
            check(result.status_code >= 400, "Persistence failure reported success")
        check(store.read_item("alice", "alice")["settings"]["preferredUiMode"] == "classic", "Failed save mutated choice")

        # Renew the unchanged profile owner's SDK consumer evidence in this changed module.
        with app.test_request_context("/api/user/info/alice"):
            session["user"] = {"oid": "alice", "roles": ["User"]}
            _, who, doc = users._read_authorized_user_profile_document("alice")
            check(who == "alice" and isinstance(doc, CosmosDict), "Authorized SDK read changed")
        result = alice.get("/api/user/info/alice")
        check(result.status_code == 200 and result.json["id"] == "alice", "SDK user info projection failed")
        with patch.object(store, "query_items", return_value=[{"id": "bob", "display_name": "Bob", "email": "bob@example.test"}]):
            result = alice.get("/api/user/collaboration-suggestions?query=bob")
            check(result.status_code == 200 and result.json["results"][0]["user_id"] == "bob", "Plain query rows changed")
        with patch.object(users, "cosmos_user_documents_container") as documents:
            documents.query_items.return_value = ["shared-document"]
            check(users._has_shared_document_profile_relationship("alice", "bob"), "Shared document query changed")
        with patch.object(users, "cosmos_collaboration_user_state_container") as states:
            states.query_items.return_value = [{"conversation_id": "c1"}]
            states.read_item.return_value = CosmosDict({"membership_status": "accepted"}, response_headers={})
            check(users._has_collaboration_profile_relationship("alice", "bob"), "SDK collaboration state changed")

        for key in ("ui_mode_policy", "ui_default_mode"):
            normalized, errors, _ = normalize_admin_settings_updates({key: []}, policy)
            check(key in errors, "Admin validation accepted collection")
        normalized, errors, _ = normalize_admin_settings_updates({"ui_mode_policy": "modern"}, policy)
        check(not errors and normalized["ui_mode_policy"] == "modern", "Admin policy normalization failed")

        terms_policy = {
            **policy, "enable_terms_of_use": True, "terms_of_use_title": "Agreement",
            "terms_of_use_message": "<script>unsafe()</script>",
            "terms_of_use_decline_redirect_url": "/goodbye",
        }
        with patch.object(terms_routes, "get_settings", return_value=terms_policy):
            visitor = app.test_client()
            result = visitor.get("/terms-of-use?next=/workspace")
            check(result.status_code == 200 and b"ms-terms-message" in result.data, "Pre-auth terms lacked modern variant")
            check(b"&lt;script&gt;" in result.data and b"<script>unsafe()" not in result.data, "Terms markup was not escaped")
            result = visitor.post("/terms-of-use/accept")
            check(result.status_code == 302 and result.location == "/login", "Pre-auth acceptance did not continue login")
            from functions_terms_of_use import TERMS_OF_USE_PRE_AUTH_SESSION_KEY
            with visitor.session_transaction() as state:
                check(TERMS_OF_USE_PRE_AUTH_SESSION_KEY in state, "Pre-auth acceptance was not recorded")
            visitor.get("/terms-of-use")
            result = visitor.post("/terms-of-use/decline")
            check(result.status_code == 302 and result.location == "/goodbye", "Terms decline behavior changed")
            with visitor.session_transaction() as state:
                check(not state, "Terms decline did not clear the session")
            terms_policy["ui_mode_policy"] = "classic"
            result = app.test_client().get("/terms-of-use")
            check(result.status_code == 200 and b"ms-terms-message" not in result.data, "Legacy terms did not follow policy")

        # Real redirect wrapper, with signed-in User and Admin sessions.
        app.before_request_funcs[None] = [lambda: redirects.redirect_classic_page_to_modern_ui(lambda: policy)]
        headers = {"Accept": "text/html"}
        with patch.object(pages, "_probe_v2_bundle", return_value=True):
            policy["ui_mode_policy"] = "modern"
            for actor in (client("alice"), client("alice", ("Admin",))):
                result = actor.get("/chats?ui=classic", headers=headers)
                check(result.status_code == 302 and result.location == "/v2/chat", "Modern-only escape bypass")
            policy["ui_mode_policy"] = "classic"
            for address in ("/v2/chat", "/v2/groups/directory"):
                result = alice.get(address, headers=headers, follow_redirects=True)
                check(result.status_code == 200 and result.get_data(as_text=True) == "legacy", "Legacy-only direct URL loop")
            policy["ui_mode_policy"] = "modern"
        with patch.object(pages, "_probe_v2_bundle", return_value=False), patch.object(pages, "_log_bundle_missing") as warning:
            pages.reset_bundle_warning_throttle()
            result = alice.get("/v2/chat", headers=headers, follow_redirects=True)
            check(result.status_code == 200 and result.get_data(as_text=True) == "legacy", "Missing-bundle fallback loop")
            check(warning.call_count == 1, "Missing bundle warning not throttled")
        policy["ui_mode_policy"] = "both"
        with patch.object(pages, "_probe_v2_bundle", return_value=True):
            result = alice.get("/chats", headers=headers)
            check(result.status_code == 200, "Forced mode erased the user's saved choice")
        print("PASS: durable account choices, forced modes, safe fallback and SDK owners")
'''


@pytest.mark.parametrize("optimized", [False, True])
def test_real_account_preference_and_policy_workflows(optimized):
    run_probe(PROBE, (), optimized)
