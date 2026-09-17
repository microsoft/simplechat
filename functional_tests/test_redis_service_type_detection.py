#!/usr/bin/env python3
"""
Functional test for Azure Managed Redis / Azure Cache for Redis service detection.
Version: 0.261.010
Implemented in: 0.261.010

This test ensures SimpleChat picks the correct TLS port for whichever Azure Redis
offering an administrator configured. Azure Managed Redis listens on port 10000 and
Azure Cache for Redis on port 6380, so a wrong choice silently breaks every cache and
session read. It also pins the fallback behavior for unrecognized host names, which is
what keeps existing Azure Cache for Redis deployments working after this change.
"""

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
sys.path.insert(0, APP_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


HOST_EXPECTATIONS = (
    ("simple-chat.redis.cache.windows.net", "azure_cache_for_redis", 6380),
    ("simple-chat.redis.cache.usgovcloudapi.net", "azure_cache_for_redis", 6380),
    ("simple-chat.redis.cache.chinacloudapi.cn", "azure_cache_for_redis", 6380),
    ("simple-chat.eastus.redis.azure.net", "azure_managed_redis", 10000),
    ("simple-chat.westus3.redis.azure.net", "azure_managed_redis", 10000),
    ("simple-chat.eastus.redisenterprise.cache.azure.net", "azure_managed_redis", 10000),
)


def test_host_suffix_selects_service_and_port():
    """Documented Azure host name suffixes resolve to the right service and port."""
    print("Testing Redis host suffix detection...")
    import functions_redis_client as redis_client

    for host, expected_service, expected_port in HOST_EXPECTATIONS:
        settings = {"redis_url": host}
        service_type = redis_client.resolve_redis_service_type(settings)
        port = redis_client.resolve_redis_port(settings)
        assert service_type == expected_service, f"{host} resolved to {service_type}"
        assert port == expected_port, f"{host} resolved to port {port}"

    print("Test passed!")
    return True


def test_unknown_host_keeps_azure_cache_for_redis_behavior():
    """A custom DNS name must keep the pre-Managed-Redis port so upgrades are safe."""
    print("Testing unknown host fallback...")
    import functions_redis_client as redis_client

    for host in ("cache.contoso.internal", "10.0.0.4", ""):
        settings = {"redis_url": host}
        assert redis_client.resolve_redis_service_type(settings) == "azure_cache_for_redis"
        assert redis_client.resolve_redis_port(settings) == 6380

    print("Test passed!")
    return True


def test_admin_overrides_take_priority():
    """Explicit service type and port settings override host name detection."""
    print("Testing admin overrides...")
    import functions_redis_client as redis_client

    managed_override = {
        "redis_url": "cache.contoso.internal",
        "redis_service_type": "azure_managed_redis",
    }
    assert redis_client.resolve_redis_service_type(managed_override) == "azure_managed_redis"
    assert redis_client.resolve_redis_port(managed_override) == 10000

    classic_override = {
        "redis_url": "simple-chat.eastus.redis.azure.net",
        "redis_service_type": "azure_cache_for_redis",
    }
    assert redis_client.resolve_redis_service_type(classic_override) == "azure_cache_for_redis"
    assert redis_client.resolve_redis_port(classic_override) == 6380

    port_override = {
        "redis_url": "simple-chat.redis.cache.windows.net",
        "redis_port": "10000",
    }
    assert redis_client.resolve_redis_port(port_override) == 10000

    print("Test passed!")
    return True


def test_invalid_port_override_is_ignored():
    """A malformed or out-of-range port must not break client construction."""
    print("Testing invalid port overrides...")
    import functions_redis_client as redis_client

    for bad_port in ("abc", "0", "70000", "-1", "  "):
        settings = {
            "redis_url": "simple-chat.eastus.redis.azure.net",
            "redis_port": bad_port,
        }
        assert redis_client.resolve_redis_port(settings) == 10000, f"port {bad_port!r}"

    print("Test passed!")
    return True


def test_host_normalization_strips_scheme_and_port():
    """Administrators sometimes paste a full connection URL instead of a host name."""
    print("Testing host normalization...")
    import functions_redis_client as redis_client

    assert redis_client.normalize_redis_host(
        "rediss://simple-chat.eastus.redis.azure.net:10000"
    ) == "simple-chat.eastus.redis.azure.net"
    assert redis_client.normalize_redis_host(
        "  Simple-Chat.redis.cache.windows.net:6380  "
    ) == "simple-chat.redis.cache.windows.net"
    assert redis_client.normalize_redis_host(None) == ""

    print("Test passed!")
    return True


def test_describe_redis_connection_reports_detection_source():
    """Admin monitoring must show whether the service was detected or set explicitly."""
    print("Testing connection description...")
    import functions_redis_client as redis_client

    detected = redis_client.describe_redis_connection(
        {"redis_url": "simple-chat.eastus.redis.azure.net"}
    )
    assert detected["service_type"] == "azure_managed_redis"
    assert detected["service_type_source"] == "detected"
    assert detected["port"] == 10000

    configured = redis_client.describe_redis_connection(
        {
            "redis_url": "cache.contoso.internal",
            "redis_service_type": "azure_managed_redis",
        }
    )
    assert configured["service_type"] == "azure_managed_redis"
    assert configured["service_type_source"] == "setting"
    assert configured["service_type_detected"] == "auto"

    print("Test passed!")
    return True


def test_monitoring_status_reports_resolved_service_and_port():
    """Admin monitoring must show which Redis service and port the app resolved."""
    print("Testing monitoring service reporting...")
    import functions_redis_monitoring

    configured = functions_redis_monitoring.get_redis_monitoring_status(
        {
            "enable_redis_cache": True,
            "redis_url": "simple-chat.eastus.redis.azure.net",
            "redis_auth_type": "managed_identity",
        },
        session_type="filesystem",
    )
    assert configured["configuration"]["service_type"] == "azure_managed_redis"
    assert configured["configuration"]["port"] == 10000
    assert configured["configuration"]["service_type_source"] == "detected"

    # With no host name there is nothing to resolve, so the panel must not imply a service.
    unconfigured = functions_redis_monitoring.get_redis_monitoring_status(
        {"enable_redis_cache": True, "redis_url": ""},
        session_type="filesystem",
    )
    assert unconfigured["configuration"]["service_type"] is None
    assert unconfigured["configuration"]["port"] is None

    print("Test passed!")
    return True


def test_version_includes_managed_redis_support():
    """The running application must be at or beyond the implementation version."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.010")
    print("Test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_host_suffix_selects_service_and_port,
        test_unknown_host_keeps_azure_cache_for_redis_behavior,
        test_admin_overrides_take_priority,
        test_invalid_port_override_is_ignored,
        test_host_normalization_strips_scheme_and_port,
        test_describe_redis_connection_reports_detection_source,
        test_monitoring_status_reports_resolved_service_and_port,
        test_version_includes_managed_redis_support,
    ]
    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
