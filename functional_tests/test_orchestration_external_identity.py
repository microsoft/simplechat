# test_orchestration_external_identity.py
"""
Functional test for signed-in session identity on retained external orchestration results.
Version: 0.261.209
Implemented in: 0.261.127
Signed-in session roles replaced per-call Microsoft Graph reads in: 0.261.209

Orchestration trusts the app roles in the signed-in session, as classic chat does,
and makes no directory calls. The real reader runs against doubled owner callbacks
with networking blocked. A fresh process imports the real module without settings,
authentication, route or credential modules, in normal and optimized Python.
Refs microsoft/simplechat#1509.
"""

from contextlib import ExitStack
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ResourceNotFoundError
import requests

# These real application modules are imported after adding the repository paths.
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(TESTS))

import functions_orchestration_external_identity as identity_module
from functions_orchestration_external_identity import (
    MAX_SESSION_ROLES,
    ExternalIdentityCancelledError,
    ExternalIdentityServiceError,
    SessionExternalIdentityReader,
)
from functions_orchestration_external_sources import CurrentExternalSourceIdentity
from functions_orchestration_result_contracts import EXTERNAL_SESSION_UNAVAILABLE_REASON, ResultContractError
from functions_orchestration_results import ResultUnavailableError
from test_support.versioning import assert_app_version_at_least


USER_ID = "a1111111-1111-4111-8111-111111111111"
OTHER_ID = "44444444-4444-4444-8444-444444444444"
CONVERSATION_ID = "conversation-1"
EMAIL = "owner@example.test"
SECRET = "synthetic-sensitive-session-secret"


class SessionWorld:
    """Double only the owner's conversation and settings reads; the reader is real."""

    def __init__(self):
        self.stack = ExitStack()
        self.conversation = {"id": CONVERSATION_ID, "user_id": USER_ID}
        self.settings = {"id": USER_ID, "user_id": USER_ID, "settings": {"enable_agents": True}}
        self.events = []
        self.authorizer = Mock(side_effect=self.authorize)
        self.settings_reader = Mock(side_effect=self.read_settings)
        self.execution_check = Mock(return_value=True)

    def __enter__(self):
        def no_network(*_args, **_kwargs):
            raise AssertionError("Session identity must not contact a directory or the network")

        for target, name in (
            (socket.socket, "connect"), (socket, "getaddrinfo"), (requests.Session, "request"),
        ):
            self.stack.enter_context(patch.object(target, name, no_network))
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    def authorize(self, *, user_id, conversation_id):
        self.events.append(("conversation", user_id, conversation_id))
        return deepcopy(self.conversation)

    def read_settings(self, user_id):
        self.events.append(("settings", user_id))
        return deepcopy(self.settings)

    def reader(self, **overrides):
        options = {
            "user_id": USER_ID, "conversation_id": CONVERSATION_ID,
            "roles": ["User"], "email": EMAIL,
            "authorize_conversation": self.authorizer, "read_user_settings": self.settings_reader,
            "execution_check": self.execution_check,
        }
        return SessionExternalIdentityReader(**{**options, **overrides})


def read_identity(reader):
    return reader(user_id=USER_ID, conversation_id=CONVERSATION_ID)


class SessionExternalIdentityTests(unittest.TestCase):
    def test_version_includes_session_identity(self):
        assert_app_version_at_least("0.261.209")

    def test_session_roles_supply_current_identity_without_directory_calls(self):
        with SessionWorld() as world:
            identity = read_identity(world.reader(roles=["User", "UrlAccessUser", "User"]))
            self.assertIs(type(identity), CurrentExternalSourceIdentity)
            self.assertEqual(identity.user_id, USER_ID)
            self.assertEqual(identity.roles, ("UrlAccessUser", "User"))
            self.assertTrue(identity.user_enable_agents)
            self.assertEqual(identity.email, EMAIL)
            self.assertEqual(world.events, [
                ("conversation", USER_ID, CONVERSATION_ID), ("settings", USER_ID),
            ])
            self.assertEqual(world.execution_check.call_count, 3)
        for name in ("GraphExternalIdentityReader", "requests", "msal"):
            self.assertFalse(hasattr(identity_module, name), name)

    def test_user_or_admin_session_role_is_required_before_any_read(self):
        for roles in ([], (), ["UrlAccessUser"], ["user"], ["admin"], ["Users"]):
            with self.subTest(roles=roles), SessionWorld() as world:
                with self.assertRaises(ResultUnavailableError) as caught:
                    read_identity(world.reader(roles=roles))
                self.assertEqual(caught.exception.code, "external_identity_role_required")
                self.assertEqual(world.events, [])
        for roles, expected in (
            (["Admin"], ("Admin",)), (("User",), ("User",)), (["User", "Admin"], ("Admin", "User")),
        ):
            with self.subTest(roles=roles), SessionWorld() as world:
                self.assertEqual(read_identity(world.reader(roles=roles)).roles, expected)

    def test_missing_signed_in_session_fails_closed_before_any_read(self):
        self.assertEqual(EXTERNAL_SESSION_UNAVAILABLE_REASON, "external_identity_session_unavailable")
        with SessionWorld() as world:
            reader = world.reader(roles=None, email=None)
            for _attempt in range(2):
                with self.assertRaises(ResultUnavailableError) as caught:
                    read_identity(reader)
                self.assertEqual(caught.exception.code, EXTERNAL_SESSION_UNAVAILABLE_REASON)
                self.assertIsInstance(caught.exception, PermissionError)
            self.assertEqual(world.events, [])
            world.execution_check.assert_not_called()

    def test_session_roles_are_validated_deduplicated_and_bounded(self):
        with SessionWorld() as world:
            identity = read_identity(world.reader(roles=[
                "User", "User", " Admin", "Admin\n", "", 1, None, ["Admin"], "U" * 129, "UrlAccessUser",
            ]))
            self.assertEqual(identity.roles, ("UrlAccessUser", "User"))
        for roles in ("User", {"User": True}, {"User"}, 1, True):
            with self.subTest(roles=roles), SessionWorld() as world:
                with self.assertRaises(ResultContractError) as caught:
                    world.reader(roles=roles)
                self.assertEqual(caught.exception.code, "external_identity_configuration_invalid")
                self.assertEqual(world.events, [])
        with SessionWorld() as world:
            roles = ["User", *(f"Role{index}" for index in range(MAX_SESSION_ROLES))]
            with self.assertRaises(ExternalIdentityServiceError) as caught:
                read_identity(world.reader(roles=roles))
            self.assertEqual(caught.exception.code, "external_identity_limit_exceeded")
            self.assertFalse(caught.exception.retryable)
            self.assertEqual(world.events, [])
        with SessionWorld() as world:
            roles = ["User", *(f"Role{index}" for index in range(MAX_SESSION_ROLES - 1))]
            self.assertEqual(len(read_identity(world.reader(roles=roles)).roles), MAX_SESSION_ROLES)

    def test_email_comes_from_the_session_and_is_never_malformed(self):
        for email, expected in (
            (EMAIL, EMAIL), (None, None), ("", None), ("owner @example.test", None),
            (" owner@example.test", None), (1, None), ("o" * 321, None),
        ):
            with self.subTest(email=email), SessionWorld() as world:
                self.assertEqual(read_identity(world.reader(email=email)).email, expected)

    def test_actor_and_conversation_binding_precedes_reads(self):
        for kwargs in (
            {"user_id": OTHER_ID, "conversation_id": CONVERSATION_ID},
            {"user_id": USER_ID, "conversation_id": "different-conversation"},
            {"user_id": 1, "conversation_id": CONVERSATION_ID},
            {"user_id": USER_ID, "conversation_id": True},
        ):
            for roles in (["User"], None):
                with self.subTest(kwargs=kwargs, roles=roles), SessionWorld() as world:
                    with self.assertRaises(ResultUnavailableError) as caught:
                        world.reader(roles=roles)(**kwargs)
                    self.assertEqual(caught.exception.code, "external_identity_actor_mismatch")
                    self.assertEqual(world.events, [])

    def test_conversation_ownership_is_checked_before_settings(self):
        for conversation in (
            None, True, {}, {"id": CONVERSATION_ID, "user_id": OTHER_ID},
            {"id": "wrong", "user_id": USER_ID},
            {"id": CONVERSATION_ID, "user_id": USER_ID, "deleted": True},
            {"id": CONVERSATION_ID, "user_id": USER_ID, "orchestration_deleted": "2026-09-21T00:00:00Z"},
        ):
            with self.subTest(conversation=conversation), SessionWorld() as world:
                world.conversation = conversation
                with self.assertRaises(ResultUnavailableError) as caught:
                    read_identity(world.reader())
                self.assertEqual(caught.exception.code, "external_identity_conversation_unavailable")
                world.settings_reader.assert_not_called()
        with SessionWorld() as world:
            world.conversation.update({"deleted": False, "orchestration_deleted": None})
            self.assertEqual(read_identity(world.reader()).roles, ("User",))

    def test_live_reader_rereads_conversation_and_restrictions_on_every_access(self):
        with SessionWorld() as world:
            reader = world.reader()
            self.assertEqual(read_identity(reader).roles, ("User",))
            world.conversation["orchestration_deleted"] = True
            with self.assertRaises(ResultUnavailableError) as caught:
                read_identity(reader)
            self.assertEqual(caught.exception.code, "external_identity_conversation_unavailable")
            del world.conversation["orchestration_deleted"]
            world.settings["settings"]["access"] = {"status": "deny"}
            with self.assertRaises(ResultUnavailableError) as caught:
                read_identity(reader)
            self.assertEqual(caught.exception.code, "external_identity_access_restricted")
            world.settings["settings"] = {"enable_agents": False}
            self.assertFalse(read_identity(reader).user_enable_agents)
            self.assertEqual(world.authorizer.call_count, 4)
            self.assertEqual(world.settings_reader.call_count, 3)

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
            with self.subTest(access=access), SessionWorld() as world:
                world.settings["settings"]["access"] = access
                before = deepcopy(world.settings)
                with patch.object(identity_module, "datetime", wraps=datetime) as clock:
                    clock.now.return_value = now
                    if allowed:
                        self.assertEqual(read_identity(world.reader()).roles, ("User",))
                    else:
                        with self.assertRaises(ResultUnavailableError) as caught:
                            read_identity(world.reader())
                        self.assertEqual(caught.exception.code, "external_identity_access_restricted")
                self.assertEqual(world.settings, before)
                self.assertEqual(world.settings_reader.call_count, 1)

    def test_only_session_admin_bypasses_restrictions_and_agent_preference_still_applies(self):
        with SessionWorld() as world:
            world.settings["settings"] = {"access": {"status": "deny"}, "enable_agents": False}
            current = read_identity(world.reader(roles=["Admin"]))
            self.assertEqual(current.roles, ("Admin",))
            self.assertFalse(current.user_enable_agents)
            with self.assertRaises(ResultUnavailableError) as caught:
                read_identity(world.reader(roles=["User"]))
            self.assertEqual(caught.exception.code, "external_identity_access_restricted")

    def test_missing_malformed_or_wrong_actor_settings_never_default_to_allow(self):
        for value in (
            None, True, {}, {"id": OTHER_ID, "settings": {}}, {"id": USER_ID},
            {"id": USER_ID, "settings": None}, {"id": USER_ID, "user_id": OTHER_ID, "settings": {}},
            {"id": USER_ID, "user_id": 1, "settings": {}},
            {"id": USER_ID, "settings": {"enable_agents": "false"}},
            {"id": USER_ID, "settings": {"enable_agents": 1}},
        ):
            with self.subTest(settings=value), SessionWorld() as world:
                world.settings = value
                with self.assertRaises(ResultUnavailableError) as caught:
                    read_identity(world.reader())
                self.assertEqual(caught.exception.code, "external_identity_settings_unavailable")
        with SessionWorld() as world:
            world.settings_reader.side_effect = ResourceNotFoundError(SECRET)
            with self.assertRaises(ResultUnavailableError) as caught:
                read_identity(world.reader())
            self.assertEqual(caught.exception.code, "external_identity_access_denied")
        with SessionWorld() as world:
            world.settings = {"id": USER_ID, "settings": {}}
            self.assertTrue(read_identity(world.reader()).user_enable_agents)

    def test_owner_io_errors_have_safe_exception_contracts(self):
        def http_error(status):
            error = HttpResponseError(SECRET)
            error.status_code = status
            return error

        cases = (
            (requests.Timeout(SECRET), ExternalIdentityServiceError, "external_identity_timeout", True),
            (TimeoutError(SECRET), ExternalIdentityServiceError, "external_identity_timeout", True),
            (
                requests.ConnectionError(SECRET), ExternalIdentityServiceError,
                "external_identity_service_unavailable", True,
            ),
            (http_error(429), ExternalIdentityServiceError, "external_identity_throttled", True),
            (http_error(503), ExternalIdentityServiceError, "external_identity_service_unavailable", True),
            (http_error(403), ResultUnavailableError, "external_identity_access_denied", None),
            (ClientAuthenticationError(SECRET), ResultUnavailableError, "external_identity_access_denied", None),
            (ResourceNotFoundError(SECRET), ResultUnavailableError, "external_identity_access_denied", None),
            (PermissionError(SECRET), ResultUnavailableError, "external_identity_access_denied", None),
            (RuntimeError(SECRET), ExternalIdentityServiceError, "external_identity_callback_invalid", False),
        )
        for exception, expected, code, retryable in cases:
            for target in ("conversation", "settings"):
                with self.subTest(code=code, error=type(exception).__name__, target=target), SessionWorld() as world:
                    owner = world.authorizer if target == "conversation" else world.settings_reader
                    owner.side_effect = exception
                    with self.assertRaises(expected) as caught:
                        read_identity(world.reader())
                    self.assertEqual(caught.exception.code, code)
                    if retryable is not None:
                        self.assertIs(caught.exception.retryable, retryable)
                    self.assertNotIn(SECRET, repr(caught.exception))
                    self.assertNotIn(SECRET, str(caught.exception))
                    self.assertIsNone(caught.exception.__cause__)
                    self.assertIsNone(caught.exception.__context__)

    def test_execution_cancellation_stops_authority_between_reads(self):
        with SessionWorld() as world:
            world.execution_check.return_value = False
            with self.assertRaises(ExternalIdentityCancelledError):
                read_identity(world.reader())
            self.assertEqual(world.events, [])

        with SessionWorld() as world:
            def authorize_then_stop(**kwargs):
                world.execution_check.return_value = False
                return world.authorize(**kwargs)

            world.authorizer.side_effect = authorize_then_stop
            with self.assertRaises(ExternalIdentityCancelledError):
                read_identity(world.reader())
            world.settings_reader.assert_not_called()

        with SessionWorld() as world:
            def read_then_stop(user_id):
                world.execution_check.return_value = False
                return world.read_settings(user_id)

            world.settings_reader.side_effect = read_then_stop
            with self.assertRaises(ExternalIdentityCancelledError):
                read_identity(world.reader())

        for value in ("yes", 1, [], "true"):
            with self.subTest(value=value), SessionWorld() as world:
                world.execution_check.return_value = value
                with self.assertRaises(ExternalIdentityServiceError) as caught:
                    read_identity(world.reader())
                self.assertEqual(caught.exception.code, "external_identity_callback_invalid")
                self.assertEqual(world.events, [])
        with SessionWorld() as world:
            world.execution_check.return_value = None
            self.assertEqual(read_identity(world.reader()).roles, ("User",))
        with SessionWorld() as world:
            self.assertEqual(read_identity(world.reader(execution_check=None)).roles, ("User",))

    def test_owning_lease_exception_is_not_reclassified(self):
        class OwnerExecutionStopped(RuntimeError):
            pass

        with SessionWorld() as world:
            stopped = OwnerExecutionStopped("The owning execution stopped.")

            def check_execution():
                if world.events:
                    raise stopped
                return True

            world.execution_check.side_effect = check_execution
            with self.assertRaises(OwnerExecutionStopped) as caught:
                read_identity(world.reader())
            self.assertIs(caught.exception, stopped)
            world.settings_reader.assert_not_called()

    def test_invalid_constructor_values_perform_no_reads(self):
        for override in (
            {"user_id": True}, {"user_id": ""}, {"user_id": " owner"},
            {"conversation_id": None}, {"conversation_id": "c" * 257},
        ):
            with self.subTest(override=override), SessionWorld() as world:
                with self.assertRaises(ResultContractError) as caught:
                    world.reader(**override)
                self.assertEqual(caught.exception.code, "external_identity_configuration_invalid")
                self.assertEqual(world.events, [])
        for override in (
            {"authorize_conversation": None}, {"read_user_settings": "reader"}, {"execution_check": 1},
        ):
            with self.subTest(override=override), SessionWorld() as world:
                with self.assertRaises(ResultContractError) as caught:
                    world.reader(**override)
                self.assertEqual(caught.exception.code, "external_identity_callback_required")
                self.assertEqual(world.events, [])

    def test_returned_identity_and_reader_keep_no_tokens_or_writes(self):
        with SessionWorld() as world:
            reader = world.reader()
            before = deepcopy((world.conversation, world.settings))
            identity = read_identity(reader)
            self.assertEqual(asdict(identity), {
                "user_id": USER_ID, "roles": ("User",), "user_enable_agents": True, "email": EMAIL,
            })
            self.assertFalse(any("token" in key or "cache" in key for key in vars(reader)))
            self.assertEqual(before, (world.conversation, world.settings))

    def test_fresh_process_real_imports_and_missing_session_normal_and_optimized(self):
        for optimized in (False, True):
            with self.subTest(optimized=optimized):
                command = [sys.executable, "-B"] + (["-O"] if optimized else [])
                result = subprocess.run(
                    command + ["-c", PROCESS_PROBE, str(APP), str(TESTS)],
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
        raise AssertionError("Unexpected application or credential discovery import")
    return original_import(name, globals, locals, fromlist, level)

def no_network(*args, **kwargs):
    raise AssertionError("Unexpected network or credential access")

with (
    patch.object(builtins, "__import__", checked_import),
    patch.object(socket.socket, "connect", no_network),
    patch.object(socket, "getaddrinfo", no_network),
):
    import azure.identity
    import msal

    with ExitStack() as constructors:
        for name, credential in vars(azure.identity).items():
            if name.endswith("Credential") and isinstance(credential, type):
                constructors.enter_context(patch.object(credential, "__init__", no_network))
        constructors.enter_context(patch.object(msal.ClientApplication, "__init__", no_network))
        importlib.import_module("functions_orchestration_external_identity")
        fixtures = importlib.import_module("test_orchestration_external_identity")
        with fixtures.SessionWorld() as world:
            reader = world.reader()
            if world.events:
                raise AssertionError("Constructing a reader performed I/O")
            current = fixtures.read_identity(reader)
            if current.roles != ("User",):
                raise AssertionError("The session role was not returned")
            background = world.reader(roles=None)
            try:
                fixtures.read_identity(background)
            except fixtures.ResultUnavailableError as error:
                if error.code != "external_identity_session_unavailable":
                    raise AssertionError("A missing session was not reported")
            else:
                raise AssertionError("A reader without a session returned authority")
            if len(world.events) != 2:
                raise AssertionError("Required conversation and settings reads were skipped")
"""


if __name__ == "__main__":
    unittest.main()
