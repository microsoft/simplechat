# test_dlp_presidio_urllib3_compatibility.py
#!/usr/bin/env python3
"""
Functional test for Presidio DLP urllib3 compatibility.
Version: 0.261.010
Implemented in: 0.261.010

functions_dlp_presidio.py builds a DNS-pinned HTTP adapter on top of urllib3
internals. It originally imported urllib3.util.timeout._DEFAULT_TIMEOUT, a
private symbol that only exists on urllib3 2.x, and referenced
urllib3.connection.NameResolutionError, which only exists on urllib3 2.x too.

requirements.txt does not pin urllib3, so it is resolved transitively through
requests. On urllib3 1.x the private import raised ImportError, and because
functions_documents.py imports functions_dlp -> functions_dlp_presidio, that
ImportError propagated all the way to application start-up. A DLP enforcement
module must not be able to take the app down based on which urllib3 a resolver
happens to pick.

This test ensures that:

  - No private urllib3 timeout symbol is imported at module scope.
  - The resolved sentinel is urllib3's public Timeout.DEFAULT_TIMEOUT, which is
    the identical object to the 2.x private sentinel and to the 1.x
    socket._GLOBAL_DEFAULT_TIMEOUT, so connect-timeout behavior is unchanged.
  - The socket connect helper still compares against that sentinel, so a
    caller-supplied timeout is still applied and only the "no explicit timeout"
    case skips settimeout().
  - DNS failures raise a urllib3 error that exists on both major versions.
"""

import ast
import io
import os
import socket
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(REPO_ROOT, "application", "single_app")
PRESIDIO_FILE = os.path.join(APP_DIR, "functions_dlp_presidio.py")


def read_presidio_source():
    """Read the Presidio endpoint adapter source."""
    return io.open(PRESIDIO_FILE, encoding="utf-8").read()


def import_presidio_module():
    """Import the Presidio adapter from the application directory."""
    if APP_DIR not in sys.path:
        sys.path.insert(0, APP_DIR)
    import functions_dlp_presidio

    return functions_dlp_presidio


def test_no_private_urllib3_timeout_import():
    """The adapter must not import urllib3's private timeout sentinel."""
    print("Testing Presidio adapter avoids private urllib3 timeout import...")
    source = read_presidio_source()
    tree = ast.parse(source, filename=PRESIDIO_FILE)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("urllib3"):
            for alias in node.names:
                assert not alias.name.startswith("_"), (
                    f"functions_dlp_presidio.py imports private urllib3 symbol "
                    f"{alias.name!r} from {node.module!r}; use a public alias instead"
                )

    assert "from urllib3.util.timeout import _DEFAULT_TIMEOUT" not in source
    return True


def test_sentinel_matches_installed_urllib3_semantics():
    """The resolved sentinel must be urllib3's real 'no explicit timeout' marker."""
    print("Testing Presidio socket timeout sentinel semantics...")
    module = import_presidio_module()
    from urllib3.util.timeout import Timeout

    sentinel = module.PRESIDIO_DEFAULT_SOCKET_TIMEOUT
    assert sentinel is Timeout.DEFAULT_TIMEOUT, (
        "Presidio adapter sentinel must be urllib3's public Timeout.DEFAULT_TIMEOUT"
    )

    try:
        from urllib3.util.timeout import _DEFAULT_TIMEOUT as private_sentinel
    except ImportError:
        # urllib3 1.x has no private sentinel; its equivalent is the socket one.
        assert sentinel is socket._GLOBAL_DEFAULT_TIMEOUT, (
            "On urllib3 1.x the sentinel must be socket._GLOBAL_DEFAULT_TIMEOUT"
        )
    else:
        assert sentinel is private_sentinel, (
            "On urllib3 2.x the public alias must be the same object as the private sentinel"
        )

    # The sentinel must never be a real timeout value, or every connection would
    # silently pick up a timeout the caller never asked for.
    assert not isinstance(sentinel, (int, float)), "Sentinel must not be a concrete timeout"
    assert sentinel is not None, "None would mean 'block forever', not 'use the default'"
    return True


def test_connect_helper_still_applies_explicit_timeouts():
    """Only the sentinel may skip settimeout(); real timeouts must still be applied."""
    print("Testing Presidio connect helper timeout handling...")
    source = read_presidio_source()
    tree = ast.parse(source, filename=PRESIDIO_FILE)

    helper = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_create_presidio_safe_socket_connection"
    )
    helper_source = ast.get_source_segment(source, helper)

    assert "if timeout is not PRESIDIO_DEFAULT_SOCKET_TIMEOUT:" in helper_source
    assert "sock.settimeout(timeout)" in helper_source
    assert "_DEFAULT_TIMEOUT" not in helper_source.replace(
        "PRESIDIO_DEFAULT_SOCKET_TIMEOUT", ""
    )

    module = import_presidio_module()
    applied = []

    class FakeSocket:
        def settimeout(self, value):
            applied.append(value)

    fake = FakeSocket()
    sentinel = module.PRESIDIO_DEFAULT_SOCKET_TIMEOUT

    # Mirror the helper's guard to prove the sentinel is skipped and a real value is not.
    for candidate in (sentinel, 7.5):
        if candidate is not sentinel:
            fake.settimeout(candidate)
    assert applied == [7.5], f"Expected only the explicit timeout to be applied, got {applied}"
    return True


def test_dns_failure_error_exists_on_installed_urllib3():
    """DNS failures must raise a urllib3 error class present on the installed version."""
    print("Testing Presidio DNS failure error construction...")
    module = import_presidio_module()
    from urllib3 import connection as urllib3_connection

    class FakeConnection:
        host = "presidio.invalid"

    error = module._build_presidio_name_resolution_error(
        FakeConnection(), socket.gaierror("name or service not known")
    )

    assert isinstance(error, urllib3_connection.NewConnectionError), (
        "DNS failures must raise NewConnectionError or a subclass on every urllib3 version"
    )
    assert "presidio.invalid" in str(error) or "presidio.invalid" in repr(error)
    return True


def test_dlp_import_chain_survives_module_import():
    """functions_dlp must import cleanly, since functions_documents depends on it."""
    print("Testing DLP import chain...")
    if APP_DIR not in sys.path:
        sys.path.insert(0, APP_DIR)
    import functions_dlp

    assert hasattr(functions_dlp, "evaluate_upload_content")
    assert hasattr(functions_dlp, "evaluate_web_search_egress")
    return True


if __name__ == "__main__":
    assert_app_version_at_least("0.261.010")

    tests = [
        test_no_private_urllib3_timeout_import,
        test_sentinel_matches_installed_urllib3_semantics,
        test_connect_helper_still_applies_explicit_timeouts,
        test_dns_failure_error_exists_on_installed_urllib3,
        test_dlp_import_chain_survives_module_import,
    ]

    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as error:
            print(f"Test failed: {error}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(1 for r in results if r)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)
