# test_registry_destination.py
"""Registry preflight and independent publishing failure regressions.

Version: 0.261.454
Implemented in: 0.261.454
"""

import importlib.util
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from unittest.mock import MagicMock

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "registry_destination", ROOT / "scripts" / "check_registry_destination.py",
)
registry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(registry)


@pytest.mark.parametrize("host", ["", " https://private.test", "registry.test/path", "registry.test:443", "user@registry.test", "a..test"])
def test_invalid_destination_fails_without_network_access(host, monkeypatch):
    lookup = MagicMock()
    monkeypatch.setattr(registry.socket, "getaddrinfo", lookup)
    with pytest.raises(ValueError, match="configuration"):
        registry.check_registry_destination(host)
    lookup.assert_not_called()


@pytest.mark.parametrize(
    ("failure", "message"),
    [(socket.gaierror("sensitive DNS detail"), "DNS lookup failed"), (TimeoutError("sensitive network detail"), "HTTPS port is unreachable")],
)
def test_failed_preflight_is_actionable_without_disclosing_hostname(failure, message, monkeypatch, capsys):
    monkeypatch.setenv("REGISTRY_LOGIN_SERVER", "private-registry.example.test")
    lookup = MagicMock(side_effect=failure if isinstance(failure, socket.gaierror) else None)
    connect = MagicMock(side_effect=failure)
    monkeypatch.setattr(registry.socket, "getaddrinfo", lookup)
    monkeypatch.setattr(registry.socket, "create_connection", connect)
    result = registry.main()
    error = capsys.readouterr().err
    assert result == 1 and message in error
    assert "private-registry" not in error and "sensitive" not in error


def test_reachable_destination_requires_dns_and_https_connection(monkeypatch):
    lookup, connect = MagicMock(), MagicMock()
    monkeypatch.setattr(registry.socket, "getaddrinfo", lookup)
    monkeypatch.setattr(registry.socket, "create_connection", connect)
    registry.check_registry_destination("registry.azurecr.us")
    lookup.assert_called_once_with("registry.azurecr.us", 443, type=socket.SOCK_STREAM)
    connect.assert_called_once_with(("registry.azurecr.us", 443), timeout=10)
    connect.return_value.__exit__.assert_called_once()


def test_publishing_keeps_both_destinations_and_stops_before_dependent_work():
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "docker_image_publish_dev.yml").read_text(encoding="utf-8"),
    )
    for job, suffix in (("build-tomain", ""), ("build-nadoyle", "_NADOYLE")):
        steps = workflow["jobs"][job]["steps"]
        positions = {step.get("name"): index for index, step in enumerate(steps)}
        preflight = positions["Check destination DNS and connectivity"]
        login = positions["Azure Container Registry Login"]
        build = positions["Build application image"]
        tag = positions["Tag application image"]
        push = positions["Push application images"]
        assert preflight < login < build < tag < push
        assert steps[preflight]["env"]["REGISTRY_LOGIN_SERVER"] == f"${{{{ secrets.ACR_LOGIN_SERVER{suffix} }}}}"
        assert all(not step.get("continue-on-error") for step in steps)
        script = steps[push]["run"]
        assert script.startswith("set -euo pipefail\n")
        assert script.count("docker push ") == 2
        assert 'simple-chat-dev:${IMAGE_TAG}"' in script
        assert 'simple-chat-dev:latest"' in script


@pytest.mark.parametrize("job", ["build-tomain", "build-nadoyle"])
def test_failed_versioned_push_does_not_publish_latest(job):
    bash = shutil.which("bash")
    if sys.platform == "win32" and (
        not bash or any(part.lower() == "system32" for part in Path(bash).parts)
    ):
        git = shutil.which("git")
        git_bash = Path(git).parent.parent / "bin" / "bash.exe" if git else None
        bash = str(git_bash) if git_bash and git_bash.is_file() else None
    if not bash:
        pytest.skip("This execution contract requires Bash, as provided by the publishing runner.")
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "docker_image_publish_dev.yml").read_text(encoding="utf-8"),
    )
    push = next(
        step["run"] for step in workflow["jobs"][job]["steps"]
        if step.get("name") == "Push application images"
    )
    result = subprocess.run(
        [bash, "--noprofile", "--norc", "-c",
         'docker() { printf "docker %s\\n" "$*"; return 23; }\n' + push],
        env={
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "REGISTRY_LOGIN_SERVER": "registry.example.test",
            "IMAGE_TAG": "offline-version",
        },
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 23, result.stderr
    assert result.stdout.count("docker push ") == 1
    assert ":offline-version" in result.stdout
    assert ":latest" not in result.stdout
