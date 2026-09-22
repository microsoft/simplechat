# test_orchestration_external_identity.py
"""
Current Microsoft Graph identity for retained external orchestration results.
Version: 0.261.127
Implemented in: 0.261.127

Real requests preparation, response streaming, JSON parsing and identity readers
run against a doubled HTTP adapter, never a tenant. Fresh processes import real
modules with networking blocked. Required operations remain active under -O.
Refs microsoft/simplechat#1509.
"""

from contextlib import ExitStack
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlencode, urlsplit

from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ResourceNotFoundError
import requests
from requests.adapters import BaseAdapter

# These real application modules are imported after adding the repository path.
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))

import functions_orchestration_external_identity as identity_module
from functions_orchestration_external_identity import (
    ExternalIdentityCancelledError,
    ExternalIdentityServiceError,
    GraphExternalIdentityReader,
)
from functions_orchestration_external_sources import CurrentExternalSourceIdentity
from functions_orchestration_result_contracts import ResultContractError
from functions_orchestration_results import ResultUnavailableError


USER_ID = "a1111111-1111-4111-8111-111111111111"
APP_ID = "22222222-2222-4222-8222-222222222222"
PRINCIPAL_ID = "33333333-3333-4333-8333-333333333333"
OTHER_ID = "44444444-4444-4444-8444-444444444444"
USER_ROLE = "55555555-5555-4555-8555-555555555555"
ADMIN_ROLE = "66666666-6666-4666-8666-666666666666"
GROUP_ID = "77777777-7777-4777-8777-777777777777"
URL_ROLE = "88888888-8888-4888-8888-888888888888"
CONVERSATION_ID = "conversation-1"
TOKEN = "synthetic-sensitive-access-token"
BASE_URL = "https://graph.example.test/v1.0"
SCOPE = "https://graph.example.test/.default"


def role(role_id, name, *, enabled=True, members=None):
    return {
        "id": role_id, "value": name, "isEnabled": enabled,
        "allowedMemberTypes": ["User"] if members is None else members,
    }


def assignment(assignment_id="assignment-1", *, role_id=USER_ROLE, group=False, resource=PRINCIPAL_ID):
    return {
        "id": assignment_id, "appRoleId": role_id, "resourceId": resource,
        "principalId": GROUP_ID if group else USER_ID,
        "principalType": "Group" if group else "User",
    }


class ResponseBody(BytesIO):
    def __init__(self, data, *, failure=None):
        super().__init__(data)
        self.failure = failure
        self.released = False

    def read(self, size=-1):
        if self.failure is not None:
            raise self.failure
        return super().read(size)

    def release_conn(self):
        self.released = True
        self.close()


class GraphHTTPAdapter(BaseAdapter):
    """Double the wire only; requests still prepares real HTTP requests/responses."""

    def __init__(self, world):
        super().__init__()
        self.world = world
        self.requests = []
        self.responses = []
        self.on_send = None
        self.error = None

    def send(self, request, **kwargs):
        self.requests.append((request, kwargs))
        if self.on_send is not None:
            self.on_send(request)
        if self.error is not None:
            raise self.error
        specification = self.world.response_for(request)
        response = requests.Response()
        response.status_code = specification.get("status", 200)
        response.url = specification.get("url", request.url)
        response.request = request
        response.headers.update(specification.get("headers", {"Content-Type": "application/json"}))
        raw = specification.get("raw")
        if raw is None:
            raw = json.dumps(specification.get("body"), ensure_ascii=True).encode("utf-8")
        response.raw = ResponseBody(raw, failure=specification.get("read_error"))
        self.responses.append(response)
        return response

    def close(self):
        for response in self.responses:
            response.close()


class GraphWorld:
    def __init__(self, *, base_url=BASE_URL, scope=SCOPE):
        self.stack = ExitStack()
        self.base_url = base_url
        self.scope = scope
        self.prefix = urlsplit(base_url).path.rstrip("/")
        self.user = {"id": USER_ID, "accountEnabled": True, "userPrincipalName": "owner@example.test"}
        self.principals = [{
            "id": PRINCIPAL_ID, "appId": APP_ID, "accountEnabled": True,
            "appRoles": [role(USER_ROLE, "User"), role(ADMIN_ROLE, "Admin"), role(URL_ROLE, "UrlAccessUser")],
        }]
        self.assignments = [assignment()]
        self.conversation = {"id": CONVERSATION_ID, "user_id": USER_ID}
        self.settings = {"id": USER_ID, "settings": {"enable_agents": True}}
        self.page_size = 100
        self.overrides = {}
        self.events = []
        self.token_provider = Mock(side_effect=self.token)
        self.authorizer = Mock(side_effect=self.authorize)
        self.settings_reader = Mock(side_effect=self.read_settings)
        self.execution_check = Mock(return_value=True)
        self.session = requests.Session()
        self.session.trust_env = False
        self.adapter = GraphHTTPAdapter(self)
        self.session.mount("https://", self.adapter)
        self.session.mount("http://", self.adapter)

    def __enter__(self):
        def no_network(*_args, **_kwargs):
            raise AssertionError("External identity tests must not contact a tenant")

        self.stack.enter_context(patch.object(socket.socket, "connect", no_network))
        self.stack.enter_context(patch.object(socket, "getaddrinfo", no_network))
        self.stack.callback(self.session.close)
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    def authorize(self, *, user_id, conversation_id):
        self.events.append(("conversation", user_id, conversation_id))
        return deepcopy(self.conversation)

    def read_settings(self, user_id):
        self.events.append(("settings", user_id))
        return deepcopy(self.settings)

    def token(self, scope):
        self.events.append(("token", scope))
        return TOKEN

    def reader(self, **overrides):
        options = {
            "user_id": USER_ID, "conversation_id": CONVERSATION_ID,
            "app_client_id": APP_ID, "graph_base_url": self.base_url, "graph_scope": self.scope,
            "get_access_token": self.token_provider, "http_get": self.session.get,
            "authorize_conversation": self.authorizer, "read_user_settings": self.settings_reader,
            "execution_check": self.execution_check,
        }
        return GraphExternalIdentityReader(**{**options, **overrides})

    def response_for(self, request):
        parts = urlsplit(request.url)
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        index = int(query.get("$skiptoken", "0"))
        if parts.path == f"{self.prefix}/users/{USER_ID}":
            kind, default = "user", {"body": deepcopy(self.user)}
        elif parts.path == f"{self.prefix}/servicePrincipals":
            kind, default = "principals", self.page(request.url, self.principals, index, counted=False)
        elif parts.path == f"{self.prefix}/users/{USER_ID}/appRoleAssignments":
            kind, default = "assignments", self.page(request.url, self.assignments, index, counted=True)
        else:
            raise AssertionError("Unexpected directory endpoint")
        return deepcopy(self.overrides.get((kind, index), default))

    def page(self, url, values, index, *, counted):
        body = {"value": deepcopy(values[index:index + self.page_size])}
        if counted:
            body["@odata.count"] = len(values)
        if index + self.page_size < len(values):
            parts = urlsplit(url)
            query = {key: values[0] for key, values in parse_qs(parts.query).items()}
            query["$skiptoken"] = str(index + self.page_size)
            body["@odata.nextLink"] = f"{parts.scheme}://{parts.netloc}{parts.path}?{urlencode(query)}"
        return {"body": body}


def read_identity(reader):
    return reader(user_id=USER_ID, conversation_id=CONVERSATION_ID)


class GraphExternalIdentityTests(unittest.TestCase):
    def test_real_http_protocol_and_exact_direct_and_group_role_mapping(self):
        with GraphWorld() as world:
            world.assignments.extend([
                assignment("assignment-2", role_id=URL_ROLE, group=True),
                assignment("assignment-3", group=True),
                assignment("assignment-4", role_id=ADMIN_ROLE, resource=OTHER_ID),
            ])
            identity = read_identity(world.reader())
            self.assertIs(type(identity), CurrentExternalSourceIdentity)
            self.assertEqual(identity.user_id, USER_ID)
            self.assertEqual(identity.roles, ("UrlAccessUser", "User"))
            self.assertTrue(identity.user_enable_agents)
            self.assertEqual(identity.email, "owner@example.test")
            self.assertEqual(world.events[0], ("conversation", USER_ID, CONVERSATION_ID))
            self.assertGreaterEqual(world.settings_reader.call_count, 2)
            self.assertEqual(len(world.adapter.requests), 3)
            for request, options in world.adapter.requests:
                self.assertEqual(request.method, "GET")
                self.assertIsNone(request.body)
                self.assertEqual(request.headers["Authorization"], f"Bearer {TOKEN}")
                self.assertTrue(options["stream"])
                self.assertGreater(options["timeout"], 0)
                self.assertLessEqual(options["timeout"], 10)
            user_request = world.adapter.requests[0][0]
            self.assertIn("accountEnabled", parse_qs(urlsplit(user_request.url).query)["$select"][0])
            principal_request = world.adapter.requests[1][0]
            self.assertEqual(parse_qs(urlsplit(principal_request.url).query)["$filter"], [f"appId eq '{APP_ID}'"])
            assignment_request = world.adapter.requests[2][0]
            self.assertEqual(assignment_request.headers["ConsistencyLevel"], "eventual")
            query = parse_qs(urlsplit(assignment_request.url).query)
            self.assertEqual(query["$count"], ["true"])
            self.assertEqual(query["$filter"], [f"resourceId eq {PRINCIPAL_ID}"])
            for response in world.adapter.responses:
                self.assertTrue(response.raw.released)

    def test_group_assignment_alone_can_supply_current_user_or_admin(self):
        for role_id, expected in ((USER_ROLE, "User"), (ADMIN_ROLE, "Admin")):
            with self.subTest(role=expected), GraphWorld() as world:
                world.assignments = [assignment(group=True, role_id=role_id)]
                identity = read_identity(world.reader())
                self.assertEqual(identity.roles, (expected,))

    def test_injected_msal_callback_stays_lazy_and_uses_the_configured_application_scope(self):
        with GraphWorld(
            base_url="https://graph.microsoft.us/v1.0",
            scope="https://graph.microsoft.us/.default",
        ) as world:
            application = Mock()
            application.acquire_token_for_client.return_value = {"access_token": TOKEN}
            factory = Mock(return_value=application)
            initialized = []

            def get_access_token(scope):
                if not initialized:
                    initialized.append(factory(
                        cache=None, authority_override="https://login.microsoftonline.us/configured-tenant",
                    ))
                result = initialized[0].acquire_token_for_client(scopes=[scope])
                return result["access_token"]

            reader = world.reader(get_access_token=get_access_token)
            factory.assert_not_called()
            application.acquire_token_for_client.assert_not_called()
            self.assertEqual(world.adapter.requests, [])
            current = read_identity(reader)
            self.assertEqual(current.roles, ("User",))
            factory.assert_called_once_with(
                cache=None, authority_override="https://login.microsoftonline.us/configured-tenant",
            )
            self.assertEqual(application.acquire_token_for_client.call_count, 3)
            for call in application.acquire_token_for_client.call_args_list:
                self.assertEqual(call.kwargs, {"scopes": [world.scope]})
            requests_before = len(world.adapter.requests)
            with self.assertRaises(ExternalIdentityServiceError):
                read_identity(world.reader(get_access_token=lambda _scope: {"access_token": TOKEN}))
            self.assertEqual(len(world.adapter.requests), requests_before)

    def test_foreign_default_and_application_only_assignments_are_not_user_authority(self):
        for change in ("foreign", "default", "application", "disabled", "deleted", "no-base-role"):
            with self.subTest(change=change), GraphWorld() as world:
                definitions = world.principals[0]["appRoles"]
                if change == "foreign":
                    world.assignments[0]["resourceId"] = OTHER_ID
                elif change == "default":
                    world.assignments[0]["appRoleId"] = "00000000-0000-0000-0000-000000000000"
                elif change == "application":
                    definitions[0]["allowedMemberTypes"] = ["Application"]
                elif change == "disabled":
                    definitions[0]["isEnabled"] = False
                elif change == "deleted":
                    del definitions[0]
                else:
                    world.assignments[0]["appRoleId"] = URL_ROLE
                with self.assertRaises(ResultUnavailableError):
                    read_identity(world.reader())

    def test_account_and_service_principal_disable_delete_or_identity_change_deny(self):
        cases = (
            ("user", "accountEnabled", False), ("user", "id", OTHER_ID),
            ("user", "deletedDateTime", "2026-01-01T00:00:00Z"),
            ("principal", "accountEnabled", False), ("principal", "appId", OTHER_ID),
            ("principal", "deletedDateTime", "2026-01-01T00:00:00Z"),
        )
        for target, field, value in cases:
            with self.subTest(target=target, field=field), GraphWorld() as world:
                record = world.user if target == "user" else world.principals[0]
                record[field] = value
                with self.assertRaises(ResultUnavailableError):
                    read_identity(world.reader())
        with GraphWorld() as world:
            world.principals = []
            with self.assertRaises(ResultUnavailableError):
                read_identity(world.reader())

    def test_actor_and_conversation_binding_precedes_tokens_and_directory_reads(self):
        for kwargs in (
            {"user_id": OTHER_ID, "conversation_id": CONVERSATION_ID},
            {"user_id": USER_ID, "conversation_id": "different-conversation"},
            {"user_id": 1, "conversation_id": CONVERSATION_ID},
            {"user_id": USER_ID, "conversation_id": True},
        ):
            with self.subTest(kwargs=kwargs), GraphWorld() as world:
                reader = world.reader()
                with self.assertRaises(ResultUnavailableError):
                    reader(**kwargs)
                self.assertEqual(world.events, [])
                self.assertEqual(world.adapter.requests, [])
        for conversation in (
            None, True, {}, {"id": CONVERSATION_ID, "user_id": OTHER_ID},
            {"id": "wrong", "user_id": USER_ID},
            {"id": CONVERSATION_ID, "user_id": USER_ID, "deleted": True},
        ):
            with self.subTest(conversation=conversation), GraphWorld() as world:
                world.conversation = conversation
                with self.assertRaises(ResultUnavailableError):
                    read_identity(world.reader())
                world.token_provider.assert_not_called()
                self.assertEqual(world.adapter.requests, [])

    def test_conversation_and_preferences_are_rechecked_during_the_call(self):
        for change in ("conversation", "settings"):
            with self.subTest(change=change), GraphWorld() as world:
                def revoke_on_assignments(request):
                    if "/appRoleAssignments?" in request.url:
                        if change == "conversation":
                            world.conversation["orchestration_deleted"] = True
                        else:
                            world.settings["settings"]["access"] = {"status": "deny"}

                world.adapter.on_send = revoke_on_assignments
                with self.assertRaises(ResultUnavailableError):
                    read_identity(world.reader())

    def test_live_and_new_readers_do_not_keep_revoked_directory_authority(self):
        for restart in (False, True):
            for mutation in ("role", "account", "principal"):
                with self.subTest(restart=restart, mutation=mutation), GraphWorld() as world:
                    reader = world.reader()
                    first = read_identity(reader)
                    self.assertIn("User", first.roles)
                    if mutation == "role":
                        world.assignments = []
                    elif mutation == "account":
                        world.user["accountEnabled"] = False
                    else:
                        world.principals[0]["appRoles"][0]["isEnabled"] = False
                    if restart:
                        reader = world.reader()
                    with self.assertRaises(ResultUnavailableError):
                        read_identity(reader)
                    self.assertGreater(len(world.adapter.requests), 3)

    def test_current_control_center_restrictions_and_expiration_are_read_only(self):
        now = datetime(2026, 9, 21, 22, 0, tzinfo=timezone.utc)
        cases = (
            ({"status": "deny"}, False),
            ({"status": "deny", "datetime_to_allow": "2026-09-21T22:00:01Z"}, False),
            ({"status": "deny", "datetime_to_allow": "2026-09-21T22:00:00Z"}, True),
            ({"status": "deny", "datetime_to_allow": "2026-09-21T21:00:00+00:00"}, True),
            ({"status": "deny", "datetime_to_allow": "2026-09-21T21:00:00"}, False),
            ({"status": "deny", "datetime_to_allow": "not-a-time"}, False),
            ({"status": "deny", "datetime_to_allow": 0}, False),
            ({"status": "unrecognized"}, False), ({"status": []}, False), (None, False),
            ({"status": "allow"}, True), ({}, True),
        )
        for access, allowed in cases:
            with self.subTest(access=access), GraphWorld() as world:
                world.settings["settings"]["access"] = access
                before = deepcopy(world.settings)
                with patch.object(identity_module, "datetime", wraps=datetime) as clock:
                    clock.now.return_value = now
                    if allowed:
                        current = read_identity(world.reader())
                        self.assertIn("User", current.roles)
                    else:
                        with self.assertRaises(ResultUnavailableError):
                            read_identity(world.reader())
                self.assertEqual(world.settings, before)

    def test_only_fresh_admin_bypasses_restrictions_and_agent_preference_still_applies(self):
        with GraphWorld() as world:
            world.settings["settings"] = {"access": {"status": "deny"}, "enable_agents": False}
            world.assignments = [assignment(role_id=ADMIN_ROLE)]
            reader = world.reader()
            current = read_identity(reader)
            self.assertEqual(current.roles, ("Admin",))
            self.assertFalse(current.user_enable_agents)
            world.assignments = [assignment()]
            with self.assertRaises(ResultUnavailableError):
                read_identity(reader)

    def test_missing_malformed_or_wrong_actor_settings_never_default_to_allow(self):
        for value in (
            None, True, {}, {"id": OTHER_ID, "settings": {}}, {"id": USER_ID},
            {"id": USER_ID, "settings": None}, {"id": USER_ID, "settings": {"enable_agents": "false"}},
            {"id": USER_ID, "settings": {"enable_agents": 1}},
        ):
            with self.subTest(settings=value), GraphWorld() as world:
                world.settings = value
                with self.assertRaises(ResultUnavailableError):
                    read_identity(world.reader())
                world.token_provider.assert_not_called()
        with GraphWorld() as world:
            world.settings["settings"] = {}
            current = read_identity(world.reader())
            self.assertTrue(current.user_enable_agents)

    def test_all_pages_are_exhausted_including_late_group_roles(self):
        with GraphWorld() as world:
            world.page_size = 1
            world.assignments = [
                assignment("other-app", resource=OTHER_ID),
                assignment("late-user", group=True),
                assignment("last-role", role_id=URL_ROLE, group=True),
            ]
            current = read_identity(world.reader())
            self.assertEqual(current.roles, ("UrlAccessUser", "User"))
            pages = [request for request, _ in world.adapter.requests if "/appRoleAssignments?" in request.url]
            self.assertEqual(len(pages), 3)
            for page in pages:
                self.assertEqual(page.headers["ConsistencyLevel"], "eventual")
                self.assertEqual(parse_qs(urlsplit(page.url).query)["$count"], ["true"])

    def test_late_page_failure_never_returns_earlier_roles(self):
        for status in (403, 429, 503):
            with self.subTest(status=status), GraphWorld() as world:
                world.page_size = 1
                world.assignments.append(assignment("second", role_id=URL_ROLE, group=True))
                world.overrides["assignments", 1] = {"status": status, "raw": b"sensitive upstream message"}
                expected = ResultUnavailableError if status == 403 else ExternalIdentityServiceError
                with self.assertRaises(expected):
                    read_identity(world.reader())

    def test_counts_missing_pages_and_duplicate_assignments_are_rejected(self):
        for body in (
            {"value": [assignment()]},
            {"value": [assignment()], "@odata.count": True},
            {"value": [assignment()], "@odata.count": 2},
            {"value": [assignment()], "@odata.count": 0},
            {"value": [assignment(), assignment()], "@odata.count": 2},
            {"value": [assignment()], "@odata.count": 1, "@odata.nextLink": None},
            {"value": "not-a-collection", "@odata.count": 1},
            {"value": [None], "@odata.count": 1},
        ):
            with self.subTest(body=body), GraphWorld() as world:
                world.overrides["assignments", 0] = {"body": body}
                with self.assertRaises(ExternalIdentityServiceError):
                    read_identity(world.reader())

    def test_ambiguous_service_principals_and_role_definitions_are_rejected(self):
        for mutation in ("principal", "role-id", "role-value", "role-page", "role-count"):
            with self.subTest(mutation=mutation), GraphWorld() as world:
                principal = world.principals[0]
                if mutation == "principal":
                    world.principals.append(deepcopy(principal))
                    world.page_size = 1
                elif mutation == "role-id":
                    principal["appRoles"].append(deepcopy(principal["appRoles"][0]))
                elif mutation == "role-value":
                    principal["appRoles"].append(role(OTHER_ID, "User"))
                elif mutation == "role-page":
                    principal["appRoles@odata.nextLink"] = f"{BASE_URL}/servicePrincipals"
                else:
                    principal["appRoles@odata.count"] = 4
                with self.assertRaises(ExternalIdentityServiceError):
                    read_identity(world.reader())

    def test_next_link_cannot_escape_origin_version_or_exact_collection_before_token(self):
        path = f"/v1.0/users/{USER_ID}/appRoleAssignments"
        links = (
            f"http://graph.example.test{path}",
            f"https://evil.example.test{path}",
            f"https://graph.example.test.evil.example{path}",
            f"https://graph.example.test:444{path}",
            f"https://user:secret@graph.example.test{path}",
            f"//graph.example.test{path}",
            f"https://graph.example.test/beta/users/{USER_ID}/appRoleAssignments",
            f"https://graph.example.test/v1.0evil/users/{USER_ID}/appRoleAssignments",
            f"https://graph.example.test/v1.0/users/{OTHER_ID}/appRoleAssignments",
            f"{BASE_URL}/servicePrincipals",
            f"{BASE_URL}/../users/{USER_ID}/appRoleAssignments",
            f"{BASE_URL}/%2e%2e/users/{USER_ID}/appRoleAssignments",
            f"https://graph.example.test{path}#secret",
            f"https://graph.example.test\\@evil.example{path}",
            f"https://graph.example.test{path}\n",
        )
        for link in links:
            with self.subTest(link=link), GraphWorld() as world:
                world.overrides["assignments", 0] = {
                    "body": {"value": [assignment()], "@odata.count": 1, "@odata.nextLink": link},
                }
                with self.assertRaises(ExternalIdentityServiceError):
                    read_identity(world.reader())
                self.assertEqual(len(world.adapter.requests), 3)
                self.assertEqual(world.token_provider.call_count, 3)

    def test_pagination_cycle_and_global_page_record_and_byte_limits_fail_closed(self):
        with GraphWorld() as world:
            link = f"{BASE_URL}/users/{USER_ID}/appRoleAssignments?$skiptoken=1"
            world.overrides["assignments", 0] = {
                "body": {"value": [], "@odata.count": 1, "@odata.nextLink": link},
            }
            world.overrides["assignments", 1] = {
                "body": {"value": [], "@odata.count": 1, "@odata.nextLink": link},
            }
            with self.assertRaises(ExternalIdentityServiceError) as caught:
                read_identity(world.reader())
            self.assertEqual(caught.exception.code, "external_identity_pagination_invalid")
            self.assertEqual(len(world.adapter.requests), 4)
        for override in ({"max_pages": 2}, {"max_records": 4}, {"max_response_bytes": 10}):
            with self.subTest(override=override), GraphWorld() as world:
                with self.assertRaises(ExternalIdentityServiceError) as caught:
                    read_identity(world.reader(**override))
                self.assertEqual(caught.exception.code, "external_identity_limit_exceeded")

    def test_directory_status_denials_are_distinct_from_transient_failures(self):
        for kind in ("user", "principals", "assignments"):
            for status in (401, 403, 404, 410, 202, 408, 429, 500, 502, 503):
                with self.subTest(kind=kind, status=status), GraphWorld() as world:
                    world.overrides[kind, 0] = {"status": status, "raw": TOKEN.encode()}
                    expected = ResultUnavailableError if status in (401, 403, 404, 410) else ExternalIdentityServiceError
                    with self.assertRaises(expected) as caught:
                        read_identity(world.reader())
                    self.assertNotIn(TOKEN, str(caught.exception))
                    self.assertIsNone(caught.exception.__cause__)
                    self.assertIsNone(caught.exception.__context__)
                    if isinstance(caught.exception, ExternalIdentityServiceError):
                        self.assertTrue(caught.exception.retryable)

    def test_redirects_are_not_followed_and_response_origin_is_checked(self):
        for specification in (
            {"status": 302, "headers": {"Location": "https://evil.example/secret"}},
            {"body": {}, "url": "https://evil.example/v1.0/users"},
        ):
            with self.subTest(specification=specification), GraphWorld() as world:
                world.overrides["user", 0] = specification
                with self.assertRaises(ExternalIdentityServiceError):
                    read_identity(world.reader())
                self.assertEqual(len(world.adapter.requests), 1)

    def test_timeout_network_and_credential_errors_have_safe_exception_contracts(self):
        cases = (
            (requests.Timeout(TOKEN), ExternalIdentityServiceError, "external_identity_timeout"),
            (requests.ConnectionError(TOKEN), ExternalIdentityServiceError, "external_identity_service_unavailable"),
            (TimeoutError(TOKEN), ExternalIdentityServiceError, "external_identity_timeout"),
            (ClientAuthenticationError(TOKEN), ResultUnavailableError, "external_identity_access_denied"),
            (ResourceNotFoundError(TOKEN), ResultUnavailableError, "external_identity_access_denied"),
            (PermissionError(TOKEN), ResultUnavailableError, "external_identity_access_denied"),
            (RuntimeError(TOKEN), ExternalIdentityServiceError, "external_identity_callback_invalid"),
        )
        for exception, expected, code in cases:
            for target in ("token", "http", "settings"):
                with self.subTest(error=type(exception).__name__, target=target), GraphWorld() as world:
                    if target == "token":
                        world.token_provider.side_effect = exception
                    elif target == "settings":
                        world.settings_reader.side_effect = exception
                    else:
                        world.adapter.error = exception
                    with self.assertRaises(expected) as caught:
                        read_identity(world.reader())
                    self.assertEqual(caught.exception.code, code)
                    self.assertNotIn(TOKEN, repr(caught.exception))
                    self.assertIsNone(caught.exception.__cause__)
                    self.assertIsNone(caught.exception.__context__)
        with GraphWorld() as world:
            world.overrides["user", 0] = {"body": world.user, "read_error": requests.ReadTimeout(TOKEN)}
            with self.assertRaises(ExternalIdentityServiceError) as caught:
                read_identity(world.reader())
            self.assertEqual(caught.exception.code, "external_identity_timeout")
            self.assertTrue(world.adapter.responses[0].raw.released)

    def test_sdk_http_statuses_keep_transient_and_permission_categories(self):
        for status in (403, 429, 503):
            with self.subTest(status=status), GraphWorld() as world:
                error = HttpResponseError(TOKEN)
                error.status_code = status
                world.settings_reader.side_effect = error
                expected = ResultUnavailableError if status == 403 else ExternalIdentityServiceError
                with self.assertRaises(expected) as caught:
                    read_identity(world.reader())
                self.assertNotIn(TOKEN, str(caught.exception))

    def test_elapsed_budget_and_execution_cancellation_prevent_authority(self):
        with GraphWorld() as world:
            world.execution_check.return_value = False
            with self.assertRaises(ExternalIdentityCancelledError):
                read_identity(world.reader())
            world.token_provider.assert_not_called()
        with GraphWorld() as world:
            clock = Mock(return_value=1.0)
            world.adapter.on_send = lambda _request: clock.configure_mock(return_value=100.0)
            with patch.object(identity_module, "monotonic", clock):
                with self.assertRaises(ExternalIdentityServiceError) as caught:
                    read_identity(world.reader(max_elapsed=2))
            self.assertEqual(caught.exception.code, "external_identity_timeout")
            self.assertEqual(len(world.adapter.requests), 1)
        with GraphWorld() as world:
            world.adapter.on_send = lambda _request: world.execution_check.configure_mock(return_value=False)
            with self.assertRaises(ExternalIdentityCancelledError):
                read_identity(world.reader())
            self.assertEqual(len(world.adapter.requests), 1)

    def test_owning_lease_or_budget_exception_is_not_reclassified_as_directory_io(self):
        class OwnerExecutionStopped(RuntimeError):
            pass

        with GraphWorld() as world:
            stopped = OwnerExecutionStopped("The owning execution stopped.")

            def check_execution():
                if world.adapter.requests:
                    raise stopped
                return None

            world.execution_check.side_effect = check_execution
            with self.assertRaises(OwnerExecutionStopped) as caught:
                read_identity(world.reader())
            self.assertIs(caught.exception, stopped)
            self.assertTrue(world.adapter.responses[0].raw.released)

    def test_transient_failure_after_success_does_not_reuse_prior_identity(self):
        with GraphWorld() as world:
            reader = world.reader()
            current = read_identity(reader)
            self.assertEqual(current.roles, ("User",))
            world.adapter.error = requests.Timeout(TOKEN)
            with self.assertRaises(ExternalIdentityServiceError) as caught:
                read_identity(reader)
            self.assertEqual(caught.exception.code, "external_identity_timeout")
            self.assertTrue(caught.exception.retryable)

    def test_invalid_record_types_and_role_value_shapes_never_become_authority(self):
        cases = (
            ("user", "accountEnabled", "true"), ("user", "id", 1),
            ("user", "@odata.type", "#microsoft.graph.servicePrincipal"),
            ("principal", "appId", True), ("principal", "appRoles", {}),
            ("role", "id", "not-a-guid"), ("role", "value", " User"),
            ("role", "value", ".User"), ("role", "value", ["User"]),
            ("role", "value", "U" * 121), ("role", "value", "User\n"),
            ("role", "allowedMemberTypes", "User"), ("role", "allowedMemberTypes", ["User", "User"]),
            ("role", "allowedMemberTypes", [True]), ("role", "isEnabled", 1),
            ("assignment", "principalId", OTHER_ID), ("assignment", "principalType", "ServicePrincipal"),
            ("assignment", "appRoleId", True), ("assignment", "id", {}),
            ("assignment", "resourceId", 1),
        )
        for target, field, value in cases:
            with self.subTest(target=target, field=field, value=value), GraphWorld() as world:
                targets = {
                    "user": world.user, "principal": world.principals[0],
                    "role": world.principals[0]["appRoles"][0], "assignment": world.assignments[0],
                }
                targets[target][field] = value
                with self.assertRaises((ExternalIdentityServiceError, ResultUnavailableError)):
                    read_identity(world.reader())

    def test_ambiguous_or_malformed_json_and_media_types_are_rejected_safely(self):
        bodies = (
            b"not-json-sensitive", b'{"id": "one", "id": "two"}',
            b'{"number": NaN}', b"[]", b"null", b"\xff",
        )
        for raw in bodies:
            with self.subTest(raw=raw), GraphWorld() as world:
                world.overrides["user", 0] = {"raw": raw}
                with self.assertRaises(ExternalIdentityServiceError) as caught:
                    read_identity(world.reader())
                self.assertEqual(caught.exception.code, "external_identity_response_invalid")
                self.assertIsNone(caught.exception.__context__)
        with GraphWorld() as world:
            world.overrides["user", 0] = {"body": world.user, "headers": {"Content-Type": "text/html"}}
            with self.assertRaises(ExternalIdentityServiceError):
                read_identity(world.reader())
        with GraphWorld() as world:
            world.overrides["user", 0] = {"body": {**world.user, "error": {"message": TOKEN}}}
            with self.assertRaises(ExternalIdentityServiceError) as caught:
                read_identity(world.reader())
            self.assertNotIn(TOKEN, str(caught.exception))

    def test_national_and_custom_cloud_base_and_scope_are_injected_not_rewritten(self):
        for base, scope in (
            ("https://graph.microsoft.us/v1.0", "https://graph.microsoft.us/.default"),
            ("https://dod-graph.microsoft.us/v1.0", "https://dod-graph.microsoft.us/.default"),
            ("https://microsoftgraph.chinacloudapi.cn/v1.0", "https://microsoftgraph.chinacloudapi.cn/.default"),
            ("https://gateway.example.test/tenant/graph/v1.0", "https://upstream.example.test/.default"),
        ):
            with self.subTest(base=base), GraphWorld(base_url=base, scope=scope) as world:
                identity = read_identity(world.reader())
                self.assertIn("User", identity.roles)
                for request, _ in world.adapter.requests:
                    self.assertTrue(request.url.startswith(f"{base}/"))
                for call in world.token_provider.call_args_list:
                    self.assertEqual(call.args, (scope,))

    def test_invalid_constructor_values_and_tokens_do_not_trigger_graph_calls(self):
        for override in (
            {"user_id": True}, {"user_id": USER_ID.upper()}, {"user_id": "owner"},
            {"app_client_id": "https://secret.invalid"}, {"app_client_id": 123},
            {"graph_base_url": "http://graph.example.test/v1.0"},
            {"graph_base_url": f"{BASE_URL}?secret=private"}, {"graph_base_url": f"{BASE_URL}#"},
            {"graph_base_url": "https://%67raph.example.test/v1.0"},
            {"graph_base_url": "https://graph.example.test:0/v1.0"},
            {"graph_scope": "User.Read"}, {"graph_scope": 1}, {"get_access_token": None},
            {"request_timeout": True}, {"max_elapsed": float("inf")}, {"max_pages": 0},
            {"max_pages": 101}, {"max_records": False}, {"max_response_bytes": -1},
        ):
            with self.subTest(override=override), GraphWorld() as world:
                with self.assertRaises(ResultContractError):
                    world.reader(**override)
                self.assertEqual(world.events, [])
        for token in (None, True, b"token", "", "token\r\ninjected: yes", "token with whitespace"):
            with self.subTest(token=token), GraphWorld() as world:
                world.token_provider.side_effect = None
                world.token_provider.return_value = token
                with self.assertRaises(ExternalIdentityServiceError):
                    read_identity(world.reader())
                self.assertEqual(world.adapter.requests, [])

    def test_returned_identity_contains_no_directory_config_credentials_or_cached_roles(self):
        with GraphWorld() as world:
            reader = world.reader()
            before = deepcopy((world.user, world.principals, world.assignments, world.settings))
            identity = read_identity(reader)
            encoded = json.dumps(asdict(identity))
            self.assertNotIn(TOKEN, encoded)
            self.assertNotIn(BASE_URL, encoded)
            self.assertNotIn(SCOPE, encoded)
            self.assertNotIn(APP_ID, encoded)
            self.assertNotIn(PRINCIPAL_ID, encoded)
            self.assertEqual(before, (world.user, world.principals, world.assignments, world.settings))
            self.assertFalse(any("cache" in key or "token" == key or "roles" in key for key in vars(reader)))

    def test_fresh_process_real_imports_and_directory_revocation_normal_and_optimized(self):
        for optimized in (False, True):
            with self.subTest(optimized=optimized):
                command = [sys.executable, "-B"] + (["-O"] if optimized else [])
                result = subprocess.run(
                    command + ["-c", PROCESS_PROBE, str(APP), str(Path(__file__).resolve().parent)],
                    cwd=ROOT, capture_output=True, text=True, timeout=60, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


PROCESS_PROBE = r"""
import builtins
from contextlib import ExitStack
import importlib
import socket
import sys
from unittest.mock import patch

sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
original_import = builtins.__import__

def checked_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and (
        name in {"config", "functions_settings", "functions_authentication"}
        or name.startswith("route_")
    ):
        raise AssertionError("Unexpected application/credential discovery import")
    return original_import(name, globals, locals, fromlist, level)

def no_network(*args, **kwargs):
    raise AssertionError("Unexpected network access")

with (
    patch.object(builtins, "__import__", checked_import),
    patch.object(socket.socket, "connect", no_network),
    patch.object(socket, "getaddrinfo", no_network),
):
    import azure.identity
    import requests

    with ExitStack() as constructors:
        for name, credential in vars(azure.identity).items():
            if name.endswith("Credential") and isinstance(credential, type):
                constructors.enter_context(patch.object(credential, "__init__", no_network))
        constructors.enter_context(patch.object(requests.Session, "__init__", no_network))
        module = importlib.import_module("functions_orchestration_external_identity")
    fixtures = importlib.import_module("test_orchestration_external_identity")
    with fixtures.GraphWorld() as world:
        reader = world.reader()
        if world.events or world.adapter.requests:
            raise AssertionError("Constructing a reader performed I/O")
        current = fixtures.read_identity(reader)
        if current.roles != ("User",):
            raise AssertionError("Current directory role was not returned")
        world.assignments = []
        restarted = world.reader()
        try:
            fixtures.read_identity(restarted)
        except fixtures.ResultUnavailableError:
            pass
        else:
            raise AssertionError("Restart reused obsolete roles")
        if len(world.adapter.requests) != 6:
            raise AssertionError("Required directory reads were skipped")
"""


if __name__ == "__main__":
    unittest.main()
