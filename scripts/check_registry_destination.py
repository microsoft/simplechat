# check_registry_destination.py
"""Fail before a container build when its configured registry is unreachable."""

import os
import re
import socket
import sys


HOST_LABEL = re.compile(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\Z")


def check_registry_destination(host):
    if (
        not host or len(host) > 253 or "." not in host
        or any(not HOST_LABEL.fullmatch(label) for label in host.split("."))
    ):
        raise ValueError(
            "Registry configuration must contain a DNS hostname without a scheme, path, port, or credentials."
        )
    try:
        socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise ValueError(
            "Registry DNS lookup failed. Check this destination's login-server secret and runner DNS/private-network access."
        ) from None
    try:
        with socket.create_connection((host, 443), timeout=10):
            pass
    except OSError:
        raise ValueError(
            "Registry HTTPS port is unreachable. Check registry availability, firewall rules, and runner network access."
        ) from None


def main():
    try:
        check_registry_destination(os.environ.get("REGISTRY_LOGIN_SERVER", ""))
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    print("Registry DNS and HTTPS port connectivity checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
