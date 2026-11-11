# test_model_catalog_publication_lifecycle.py
"""
Functional tests for isolated catalog channels and exact tested-payload promotion.
Version: 0.261.429
Implemented in: 0.261.428

Real signatures and publisher code run offline without application/cloud bootstrap.
"""

import base64
import hashlib
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import pytest
import yaml

from test_support.versioning import read_app_version

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))

import model_catalog_package as package

SPEC = importlib.util.spec_from_file_location("catalog_lifecycle_publisher", ROOT / "scripts" / "publish_model_catalog.py")
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)

VERSION = read_app_version()


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Publication lifecycle tests must not use the network.")
    monkeypatch.setattr(socket.socket, "connect", deny)


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


@pytest.fixture
def candidate(tmp_path, signing_key, monkeypatch):
    manifest = publisher.build_candidate("a" * 40, tmp_path, "production")
    public = signing_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    keys = {"development-test": public}
    development = {**manifest, "channel": "development", "keyId": "development-test"}
    manifest_raw = package.canonical_bytes(development)
    raw = package.canonical_bytes({
        "manifest": base64.b64encode(manifest_raw).decode(),
        "payload": base64.b64encode((tmp_path / "payload.json").read_bytes()).decode(),
        "signature": base64.b64encode(signing_key.sign(
            manifest_raw, padding.PKCS1v15(), hashes.SHA256(),
        )).decode(),
    })
    receipt = {
        "revision": manifest["revision"], "sha256": manifest["sha256"],
        "developmentPackage": hashlib.sha256(raw).hexdigest(),
        "stagingCommit": "b" * 40, "runId": "123",
    }
    run = {
        "head_branch": "Staging", "head_sha": "b" * 40,
        "path": ".github/workflows/publish-model-catalog.yml",
        "event": "push", "status": "completed", "conclusion": "success",
    }
    filename = f"catalog-{manifest['revision']}-2026-11-11.json"
    pointer = {"commit": "c" * 40, "filename": filename}
    files = {
        f"{publisher.RAW_ROOT}/model-catalog-development/model-catalog/revisions/{manifest['revision']}.json":
            package.canonical_bytes(pointer),
        package.package_url("c" * 40, filename): raw,
        f"{publisher.RAW_ROOT}/model-catalog-validation/model-catalog/validated/{manifest['revision']}.json":
            package.canonical_bytes(receipt),
        f"{publisher.RAW_ROOT}/{'b' * 40}/application/single_app/static/json/model_capabilities.json":
            (tmp_path / "payload.json").read_bytes(),
    }
    monkeypatch.setattr(publisher, "trusted_keys", lambda **_kwargs: keys)
    monkeypatch.setattr(publisher, "download_bytes", lambda url, *_args: files[url])
    monkeypatch.setattr(publisher, "github_api", lambda: lambda *_args, **_kwargs: run)
    return SimpleNamespace(
        output=tmp_path, manifest=manifest, raw=raw, keys=keys, receipt=receipt, run=run, files=files,
    )


def test_real_development_signature_is_never_accepted_by_production(candidate):
    # Even adding the test public key to the wrong map cannot cross the signed channel.
    with pytest.raises(package.CatalogUpdateError, match="channel"):
        package.verify_package(candidate.raw, VERSION, keys=candidate.keys, channel="production")
    verified = package.verify_package(candidate.raw, VERSION, keys=candidate.keys, channel="development")
    assert verified["manifest"]["channel"] == "development"


def test_validated_exact_payload_can_be_promoted(candidate):
    publisher.require_staging_validation(candidate.output, VERSION)


@pytest.mark.parametrize("field,value", [
    ("sha256", "0" * 64), ("revision", "999"), ("minimumAppVersion", "0.1.1"),
    ("size", 1), ("schemaVersion", 999),
])
def test_promoted_candidate_must_match_tested_contract(candidate, field, value):
    manifest = {**candidate.manifest, field: value}
    (candidate.output / "candidate.json").write_bytes(package.canonical_bytes(manifest))
    with pytest.raises((ValueError, KeyError)):
        publisher.require_staging_validation(candidate.output, VERSION)


def test_changed_prepared_bytes_are_rejected(candidate):
    (candidate.output / "payload.json").write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        publisher.require_staging_validation(candidate.output, VERSION)


@pytest.mark.parametrize("field,value", [
    ("conclusion", "failure"), ("status", "in_progress"), ("head_branch", "Development"),
    ("head_sha", "d" * 40), ("event", "pull_request"), ("path", ".github/workflows/other.yml"),
])
def test_failed_wrong_or_pending_staging_runs_cannot_authorize_production(candidate, field, value):
    candidate.run[field] = value
    with pytest.raises(ValueError, match="workflow"):
        publisher.require_staging_validation(candidate.output, VERSION)


@pytest.mark.parametrize("field,value", [
    ("developmentPackage", "0" * 64), ("sha256", "0" * 64), ("revision", "2"),
    ("stagingCommit", "../main"), ("runId", "../runs"),
])
def test_receipt_must_identify_exact_package_and_run(candidate, field, value):
    if field == "revision":
        value = str(int(candidate.manifest["revision"]) + 1)
    receipt = {**candidate.receipt, field: value}
    url = f"{publisher.RAW_ROOT}/model-catalog-validation/model-catalog/validated/{candidate.manifest['revision']}.json"
    candidate.files[url] = package.canonical_bytes(receipt)
    with pytest.raises(ValueError, match="exact tested"):
        publisher.require_staging_validation(candidate.output, VERSION)


def test_successful_staging_run_must_contain_exact_payload(candidate):
    url = f"{publisher.RAW_ROOT}/{'b' * 40}/application/single_app/static/json/model_capabilities.json"
    candidate.files[url] = b"different catalog"
    with pytest.raises(ValueError, match="catalog bytes"):
        publisher.require_staging_validation(candidate.output, VERSION)


@pytest.mark.parametrize("channel,ref", [
    ("production", "Development"), ("production", "Staging"), ("development", "main"),
    ("development", "Staging"), ("validation", "main"), ("validation", "Development"),
])
def test_signing_branch_policy_cannot_be_crossed(monkeypatch, channel, ref):
    monkeypatch.setenv("GITHUB_REPOSITORY", "microsoft/simplechat")
    monkeypatch.setenv("GITHUB_REF", f"refs/heads/{ref}")
    with pytest.raises(ValueError, match="reviewed source branch"):
        publisher.require_publishing_approval(channel)


@pytest.mark.parametrize("channel,branch,environment", [
    ("production", "main", "model-catalog-publishing"),
    ("development", "Development", "model-catalog-development"),
    ("validation", "Staging", "model-catalog-validation"),
])
def test_each_channel_requires_its_own_environment_reviewers(monkeypatch, channel, branch, environment):
    monkeypatch.setenv("GITHUB_REPOSITORY", "microsoft/simplechat")
    monkeypatch.setenv("GITHUB_REF", f"refs/heads/{branch}")
    monkeypatch.setenv("GH_TOKEN", "test-token")
    calls = []

    def get(url, **_kwargs):
        calls.append(url)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"protection_rules": []})
    monkeypatch.setattr(publisher.requests, "get", get)
    with pytest.raises(ValueError, match="required reviewers"):
        publisher.require_publishing_approval(channel)
    assert calls == [f"{publisher.API_ROOT}/environments/{environment}"]


def test_development_and_production_keys_must_be_distinct(tmp_path, signing_key, monkeypatch):
    public = signing_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    production = tmp_path / "production.json"
    development = tmp_path / "development.json"
    production.write_bytes(package.canonical_bytes({"production": public}))
    development.write_bytes(package.canonical_bytes({"development": public}))
    monkeypatch.setattr(package, "TRUST_PATH", production)
    monkeypatch.setattr(package, "DEVELOPMENT_TRUST_PATH", development)
    with pytest.raises(package.CatalogUpdateError, match="distinct"):
        package.trusted_keys(channel="development")


@pytest.mark.parametrize("channel,expected", [
    ("production", "/model-catalog/model-catalog/latest.json"),
    ("development", "/model-catalog-development/model-catalog/latest.json"),
    ("other", None),
])
def test_startup_channel_uses_fixed_feed_and_rejects_unknown_values(channel, expected):
    env = {**os.environ, "PYTHONPATH": str(APP), "MODEL_CATALOG_CHANNEL": channel}
    result = subprocess.run(
        [sys.executable, "-c", "import model_catalog_package as p; print(p.DISCOVERY_URL)"],
        env=env, text=True, capture_output=True, timeout=30, check=False,
    )
    if expected is None:
        assert result.returncode != 0
        assert "must be production or development" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"{publisher.RAW_ROOT}{expected}"


def test_publisher_workflow_gates_every_stage_and_never_uses_pr_credentials():
    path = ROOT / ".github" / "workflows" / "publish-model-catalog.yml"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    assert triggers["push"]["branches"] == ["Development", "Staging", "main"]
    assert "workflow_dispatch" in triggers
    assert "pull_request" not in triggers and "pull_request_target" not in triggers
    jobs = workflow["jobs"]
    assert jobs["validate-for-production"]["environment"] == "model-catalog-validation"
    assert jobs["validate-for-production"]["if"] == "github.ref_name == 'Staging'"
    assert jobs["sign-and-publish"]["environment"] == "${{ needs.prepare.outputs.environment }}"
    assert jobs["sign-and-publish"]["permissions"]["actions"] == "read"


def test_weekly_workflow_is_review_only_bounded_and_targets_development():
    source = (ROOT / ".github" / "workflows" / "refresh-model-catalog.md").read_text(encoding="utf-8")
    workflow = yaml.safe_load(source.split("---", 2)[1])
    triggers = workflow.get("on", workflow.get(True))
    assert triggers["schedule"] == [{"cron": "23 9 * * 1"}]
    assert "workflow_dispatch" in triggers
    assert triggers["push"]["branches"] == ["Development"]
    assert workflow["checkout"]["ref"] == "Development"
    assert workflow["permissions"]["contents"] == "read"
    assert "id-token" not in workflow["permissions"]
    assert "ENABLE_MODEL_CATALOG_REFRESH" in workflow["if"]
    outputs = workflow["safe-outputs"]
    assert set(outputs) == {"create-pull-request", "report-incomplete"}
    assert outputs["report-incomplete"]["create-issue"] is False
    create = outputs["create-pull-request"]
    assert create["base-branch"] == "Development" and create["draft"] is True
    assert create["max"] == 1 and create["stacked"] is False
    assert not any("trusted_keys" in path or "workflows" in path for path in create["allowed-files"])
    assert "azure.microsoft.com" in workflow["network"]["allowed"]
    assert "provider-wide indexes" in source and "no structured pricing fields" in source
    assert "No schema changes or runtime-code changes" in source


def test_development_publication_only_advances_development_reference(candidate, monkeypatch):
    calls = []

    def api(method, path, body=None, **_kwargs):
        calls.append((method, path, body))
        if path.startswith("/git/ref/"):
            return None
        return {"sha": "d" * 40}
    monkeypatch.setattr(publisher, "github_api", lambda: api)
    filename = "catalog-1-2026-11-11.json"
    (candidate.output / filename).write_bytes(candidate.raw)
    publisher.publish(candidate.output, filename, "development")
    assert calls[-1] == (
        "POST", "/git/refs", {"ref": "refs/heads/model-catalog-development", "sha": "d" * 40},
    )
    assert not any(path == "/git/refs/heads/model-catalog" for _method, path, _body in calls)


def test_validation_receipt_is_written_only_for_the_approved_staging_candidate(candidate, monkeypatch):
    manifest = {**candidate.manifest, "channel": "development"}
    (candidate.output / "candidate.json").write_bytes(package.canonical_bytes(manifest))
    monkeypatch.setenv("GITHUB_SHA", manifest["sourceCommit"])
    monkeypatch.setenv("GITHUB_RUN_ID", "456")
    calls = []

    def api(method, path, body=None, **_kwargs):
        calls.append((method, path, body))
        if path.startswith("/git/ref/"):
            return None
        return {"sha": "e" * 40}
    monkeypatch.setattr(publisher, "github_api", lambda: api)
    publisher.record_validation(candidate.output, VERSION)
    blobs = [
        package.read_json(base64.b64decode(body["content"]))
        for method, path, body in calls if method == "POST" and path == "/git/blobs"
    ]
    assert blobs == [{
        **candidate.receipt, "stagingCommit": manifest["sourceCommit"], "runId": "456",
    }]
    assert calls[-1] == (
        "POST", "/git/refs", {"ref": "refs/heads/model-catalog-validation", "sha": "e" * 40},
    )


def test_validation_records_cannot_be_replaced(candidate, monkeypatch):
    manifest = {**candidate.manifest, "channel": "development"}
    (candidate.output / "candidate.json").write_bytes(package.canonical_bytes(manifest))
    monkeypatch.setenv("GITHUB_SHA", manifest["sourceCommit"])
    monkeypatch.setenv("GITHUB_RUN_ID", "456")
    calls = []

    def api(method, path, body=None, **_kwargs):
        calls.append(method)
        if path.startswith("/git/ref/"):
            return {"object": {"sha": "parent"}}
        if path.startswith("/git/commits/"):
            return {"tree": {"sha": "base"}}
        return {"content": "existing"}
    monkeypatch.setattr(publisher, "github_api", lambda: api)
    with pytest.raises(ValueError, match="cannot be replaced"):
        publisher.record_validation(candidate.output, VERSION)
    assert set(calls) == {"GET"}


def test_main_checks_staging_before_requesting_a_production_signature(candidate, monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "argv", ["publisher", "sign-publish", "--output", str(candidate.output)])
    monkeypatch.setenv("CATALOG_APP_VERSION", VERSION)
    monkeypatch.setattr(publisher, "require_publishing_approval", lambda channel: calls.append(channel))
    monkeypatch.setattr(publisher, "sign_candidate", lambda *_args: calls.append("SIGN"))

    def reject(*_args):
        calls.append("CHECK")
        raise ValueError("Missing validation")
    monkeypatch.setattr(publisher, "require_staging_validation", reject)
    with pytest.raises(ValueError, match="Missing validation"):
        publisher.main()
    assert calls == ["production", "CHECK"]


@pytest.mark.parametrize("status,chunks", [
    (302, [b"redirect"]), (200, [b"too", b"-large"]), (503, [b"unavailable"]),
])
def test_official_file_download_refuses_redirects_oversize_and_failures(monkeypatch, status, chunks):
    calls = []

    class Response:
        status_code = status

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, _size):
            return iter(chunks)

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    monkeypatch.setattr(publisher.requests, "get", get)
    with pytest.raises(ValueError):
        publisher.download_bytes(f"{publisher.RAW_ROOT}/fixture.json", 3)
    assert calls[0][1] == {"timeout": (3, 10), "allow_redirects": False, "stream": True}
