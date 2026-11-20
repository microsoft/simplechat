#!/usr/bin/env python3
# test_model_catalog_publisher_key_setup.py
"""
Functional test for the model catalog publisher key setup fix.
Version: 0.261.474
Implemented in: 0.261.474

This test ensures that the publisher's Key Vault public key can be written into the
bundled trust map in one step (so it ships with every upgrade), that a bad key leaves
the map untouched, that the online-update setting is drawn only by the Catalog
updates card, and that the admin warning no longer asks administrators to install a
key they cannot install. It also covers publishers whose vaults are
unreachable from GitHub: a locally generated key pair whose private half is a protected
environment secret, and signing with that secret.
"""

import ast
import os
from pathlib import Path
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT / "scripts"))

import model_catalog_package  # noqa: E402
import publish_model_catalog  # noqa: E402
from test_support.versioning import read_app_version  # noqa: E402

OLD_WARNING = "Install the trusted public key"


def _numbers(bits):
    public = rsa.generate_private_key(public_exponent=65537, key_size=bits).public_key().public_numbers()
    return public.n.to_bytes((public.n.bit_length() + 7) // 8, "big"), public.e.to_bytes(3, "big")


def _point_trust_maps(tmp_path, monkeypatch):
    production = tmp_path / "prod.json"
    development = tmp_path / "dev.json"
    production.write_text("{}", encoding="utf-8")
    development.write_text("{}", encoding="utf-8")
    for module in (model_catalog_package, publish_model_catalog):
        monkeypatch.setattr(module, "TRUST_PATH", production)
        monkeypatch.setattr(module, "DEVELOPMENT_TRUST_PATH", development)
    return production, development


def test_vault_public_key_lands_in_bundled_trust_map(tmp_path, monkeypatch):
    """A trusted key written by trust-key is what the app's verifier reads."""
    production, _ = _point_trust_maps(tmp_path, monkeypatch)
    pem = publish_model_catalog.public_key_pem(*_numbers(3072))
    publish_model_catalog.add_trusted_key("simplechat-catalog-2026", pem)

    keys = model_catalog_package.trusted_keys(channel="production")
    assert keys == {"simplechat-catalog-2026": pem}
    assert production.read_text(encoding="utf-8").endswith("\n")
    # Re-running with the same key is harmless; reusing the ID for new material is not.
    publish_model_catalog.add_trusted_key("simplechat-catalog-2026", pem)
    other = publish_model_catalog.public_key_pem(*_numbers(3072))
    try:
        publish_model_catalog.add_trusted_key("simplechat-catalog-2026", other)
    except ValueError:
        pass
    else:
        raise AssertionError("Replacing a trusted key under the same ID must be refused.")


def test_rejected_keys_leave_the_trust_map_unchanged(tmp_path, monkeypatch):
    """Small keys and a production key reused for development are refused."""
    _, development = _point_trust_maps(tmp_path, monkeypatch)
    try:
        publish_model_catalog.public_key_pem(*_numbers(2048))
    except ValueError:
        pass
    else:
        raise AssertionError("A 2,048-bit key must be refused.")

    pem = publish_model_catalog.public_key_pem(*_numbers(3072))
    publish_model_catalog.add_trusted_key("prod-1", pem, "production")
    try:
        publish_model_catalog.add_trusted_key("dev-1", pem, "development")
    except Exception:
        pass
    else:
        raise AssertionError("A production key reused for development must be refused.")
    assert development.read_text(encoding="utf-8") == "{}"


def test_online_update_switch_has_one_control():
    """The generic V2 scan must not draw a second switch for the catalog setting."""
    # Read the literal rather than importing the module, which opens Cosmos clients.
    tree = ast.parse((APP / "admin_settings_fields.py").read_text(encoding="utf-8"))
    suppressed = next(
        ast.literal_eval(node.value) for node in tree.body
        if isinstance(node, ast.Assign)
        and any(getattr(target, "id", None) == "SUPPRESSED_CAPABILITY_KEYS" for target in node.targets)
    )
    assert "enable_model_catalog_online_updates" in suppressed


def test_admin_warning_does_not_ask_for_manual_key_install():
    """Both admin UIs explain that the key ships with SimpleChat."""
    for path in (
        APP / "static" / "js" / "admin" / "model_catalog_updates.js",
        ROOT / "application" / "v2_ui" / "src" / "components" / "admin" / "ModelCatalogUpdates.tsx",
    ):
        text = path.read_text(encoding="utf-8")
        assert OLD_WARNING not in text, path
        assert "ships inside SimpleChat" in text, path


def test_generated_key_pair_trusts_public_half_and_keeps_private_half_out_of_repo(tmp_path, monkeypatch):
    """generate-key writes only the public key into the repository."""
    production, _ = _point_trust_maps(tmp_path, monkeypatch)
    private_path = tmp_path / "catalog-signing.pem"
    publish_model_catalog.generate_signing_key("simplechat-catalog-2026", private_path)

    private_key = serialization.load_pem_private_key(private_path.read_bytes(), password=None)
    trusted = model_catalog_package.trusted_keys(channel="production")["simplechat-catalog-2026"]
    assert serialization.load_pem_public_key(trusted.encode()).public_numbers() == private_key.public_key().public_numbers()
    assert "PRIVATE" not in production.read_text(encoding="utf-8")

    with pytest.raises(FileExistsError):
        publish_model_catalog.generate_signing_key("another-id", private_path)
    with pytest.raises(ValueError, match="outside the repository"):
        publish_model_catalog.generate_signing_key("another-id", ROOT / "catalog-signing.pem")
    assert not (ROOT / "catalog-signing.pem").exists()
    assert list(model_catalog_package.trusted_keys(channel="production")) == ["simplechat-catalog-2026"]


def _signing_setup(tmp_path, monkeypatch):
    _point_trust_maps(tmp_path, monkeypatch)
    private_path = tmp_path / "key.pem"
    publish_model_catalog.generate_signing_key("publisher-1", private_path)
    output = tmp_path / "candidate"
    publish_model_catalog.build_candidate("a" * 40, output)
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    return output, private_path.read_text(encoding="ascii")


def test_secret_signing_produces_a_package_the_app_accepts(tmp_path, monkeypatch):
    """A package signed with the environment secret verifies against the bundled key."""
    output, pem = _signing_setup(tmp_path, monkeypatch)
    version = read_app_version()
    filename = publish_model_catalog.sign_candidate(output, "publisher-1", None, version, signing_key_pem=pem)
    verified = model_catalog_package.verify_package(
        (output / filename).read_bytes(), version,
        keys=model_catalog_package.trusted_keys(channel="production"),
    )
    assert verified["manifest"]["keyId"] == "publisher-1"


def test_secret_signing_refuses_wrong_or_ambiguous_keys(tmp_path, monkeypatch):
    """A secret that is not the trusted key, or two configured sources, never signs."""
    output, pem = _signing_setup(tmp_path, monkeypatch)
    version = read_app_version()
    stranger = rsa.generate_private_key(public_exponent=65537, key_size=3072).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    ).decode("ascii")
    with pytest.raises(ValueError, match="does not match") as caught:
        publish_model_catalog.sign_candidate(output, "publisher-1", None, version, signing_key_pem=stranger)
    assert "PRIVATE" not in str(caught.value)
    with pytest.raises(ValueError, match="not in the production trust map"):
        publish_model_catalog.sign_candidate(output, "unknown-id", None, version, signing_key_pem=pem)
    with pytest.raises(ValueError, match="exactly one"):
        publish_model_catalog.sign_candidate(output, "publisher-1", "https://v.vault.azure.net/keys/k/1", version, signing_key_pem=pem)
    with pytest.raises(ValueError, match="exactly one"):
        publish_model_catalog.sign_candidate(output, "publisher-1", None, version)
    with pytest.raises(ValueError, match="not an unencrypted PEM") as caught:
        publish_model_catalog.sign_candidate(output, "publisher-1", None, version, signing_key_pem="garbage")
    assert "garbage" not in str(caught.value)


def test_workflow_passes_signing_secret_only_to_the_signing_step():
    """The secret reaches one step, and Azure login runs only for vault signing."""
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "publish-model-catalog.yml").read_text(encoding="utf-8"))
    holders = [
        (job_name, step.get("name") or step.get("uses") or step.get("run", "")[:40])
        for job_name, job in workflow["jobs"].items()
        for step in job.get("steps", [])
        if "secrets.CATALOG_SIGNING_KEY" in str(step.get("env", {}).get("CATALOG_SIGNING_KEY", ""))
    ]
    assert holders == [("sign-and-publish", "Sign, verify and publish")]
    steps = workflow["jobs"]["sign-and-publish"]["steps"]
    login = next(step for step in steps if str(step.get("uses", "")).startswith("azure/login@"))
    assert login["if"] == "vars.CATALOG_VAULT_KEY_URL != ''"


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
