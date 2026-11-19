# test_dependency_pin_audit.py
"""Regressions for honest direct-pin and transitive-lock auditing.

Version: 0.261.460
Implemented in: 0.261.454
"""

import importlib.util
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "dependency_pin_audit", ROOT / "scripts" / "check_dependency_pins.py",
)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_direct_python_pins_do_not_claim_a_locked_transitive_graph(tmp_path):
    findings = audit.audit_requirements("requirements.txt", "requests==2.33.1\n", tmp_path)
    assert [item["rule"] for item in findings] == ["python-transitive-lock"]
    missing = audit.audit_requirements("requirements.txt", "-c requirements.lock.txt\nrequests==2.33.1\n", tmp_path)
    assert [item["rule"] for item in missing] == ["missing-python-lock"]
    (tmp_path / "requirements.lock.txt").write_text("requests==2.33.1\n", encoding="utf-8")
    complete = audit.audit_requirements("requirements.txt", "-c requirements.lock.txt\nrequests==2.33.1\n", tmp_path)
    assert complete == []


def test_manifest_and_npm_lock_must_agree(tmp_path):
    manifest = {"dependencies": {"react": "18.3.1"}}
    lock = {"packages": {"": {"dependencies": {"react": "^18.3.1"}}}}
    (tmp_path / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    findings = audit.audit_package("package.json", json.dumps(manifest), tmp_path)
    assert [item["rule"] for item in findings] == ["npm-lock-sync"]


def test_latest_is_not_permitted_for_a_third_party_image_even_with_digest():
    findings = audit.audit_dockerfile("Dockerfile", f"FROM vendor/image:latest@sha256:{'a' * 64}\n")
    assert [item["rule"] for item in findings] == ["third-party-latest"]
    application_push = audit.audit_workflow(
        ".github/workflows/publish.yml", '        run: docker push "${REGISTRY}/simple-chat:latest"\n',
    )
    assert application_push == []


def test_base_image_digest_does_not_pin_os_packages():
    findings = audit.audit_dockerfile(
        "Dockerfile", f"FROM vendor/image:1.2.3@sha256:{'a' * 64}\nRUN tdnf install -y curl\n",
    )
    assert [item["rule"] for item in findings] == ["os-package-lock"]


@pytest.mark.parametrize(
    ("release", "selection", "invalid"),
    [
        ("2026-11-05T12:00:00Z", "2026-11-19T12:00:00Z", False),
        ("2026-11-05T12:00:01Z", "2026-11-19T12:00:00Z", True),
        ("2026-12-01T00:00:00Z", "2026-11-19T12:00:00Z", True),
        ("2026-11-01T00:00:00", "2026-11-19T12:00:00Z", True),
    ],
)
def test_new_release_selections_require_fourteen_full_days(release, selection, invalid):
    error = audit.release_age_error(release, selection)
    assert bool(error) is invalid


def test_floating_workflow_selectors_and_actions_are_reported():
    findings = audit.audit_workflow(
        ".github/workflows/check.yml",
        "runs-on: ubuntu-latest\npython-version: '3.12'\n- uses: actions/checkout@v7\n",
    )
    assert {item["rule"] for item in findings} == {"runner-version", "runtime-version", "action-sha"}


def test_generated_lock_evidence_rejects_changes_and_young_transitives(tmp_path):
    source = tmp_path / "requirements.txt"
    source.write_text("requests==2.33.1\n", encoding="utf-8")
    lock = tmp_path / "requirements.lock.txt"
    lock.write_text("requests==2.33.1\n", encoding="utf-8")
    ledger = {
        "selected_at": "2026-11-19T12:00:00Z",
        "inputs": {"requirements.txt": hashlib.sha256(source.read_text().encode()).hexdigest()},
        "lock_sha256": hashlib.sha256(lock.read_text().encode()).hexdigest(),
        "packages": {"requests==2.33.1": {
            "released_at": "2026-11-19T11:00:00Z", "grandfathered_pin": False,
        }},
    }
    (tmp_path / "requirements.lock.json").write_text(json.dumps(ledger), encoding="utf-8")
    findings = audit.audit_lock(Path("requirements.lock.txt"), tmp_path)
    assert [item["rule"] for item in findings] == ["release-age"]
    ledger["packages"]["requests==2.33.1"]["grandfathered_pin"] = True
    (tmp_path / "requirements.lock.json").write_text(json.dumps(ledger), encoding="utf-8")
    findings = audit.audit_lock(Path("requirements.lock.txt"), tmp_path)
    assert findings == []
    source.write_text("requests==2.33.2\n", encoding="utf-8")
    lock.write_text("requests==2.33.2\n", encoding="utf-8")
    findings = audit.audit_lock(Path("requirements.lock.txt"), tmp_path)
    assert {item["rule"] for item in findings} == {"lock-evidence-sync", "python-lock-input"}


def load_dependency_script(relative_path):
    spec = importlib.util.spec_from_file_location(Path(relative_path).stem, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_python_lock_retains_python_and_platform_specific_packages():
    generator = load_dependency_script("scripts/lock_python_dependencies.py")
    combined, _ = generator.combine_platforms({
        ("3.11", "linux"): "common==1.0.0\nlegacy==1.0.0\n",
        ("3.11", "win32"): "common==1.0.0\nlegacy==1.0.0\nwindows-only==2.0.0\n",
        ("3.12", "linux"): "common==1.0.0\n",
        ("3.12", "win32"): "common==1.0.0\nwindows-only==2.0.0\n",
    })
    expected = {
        ("3.11", "linux"): {"common", "legacy"},
        ("3.11", "win32"): {"common", "legacy", "windows-only"},
        ("3.12", "linux"): {"common"},
        ("3.12", "win32"): {"common", "windows-only"},
    }
    for (version, platform), names in expected.items():
        selected = set()
        for line in combined.splitlines():
            requirement = Requirement(line)
            if requirement.marker is None or requirement.marker.evaluate({
                "python_version": version, "sys_platform": platform,
            }):
                selected.add(requirement.name)
        assert selected == names


def test_python_lock_updates_changed_direct_pins_without_upgrading_other_constraints():
    generator = load_dependency_script("scripts/lock_python_dependencies.py")
    retained = generator.retained_constraints(
        "playwright==1.58.0\npyee==13.0.1\ncolorama==0.4.6; sys_platform == \"win32\"\n",
        {"playwright==1.65.1"},
    )
    assert retained == "pyee==13.0.1\ncolorama==0.4.6; sys_platform == \"win32\"\n"


def test_inherited_security_pin_requires_matching_immutable_baseline(tmp_path, monkeypatch):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "Dockerfile").write_text(f"FROM vendor/image:1.2.3@sha256:{'a' * 64}\n", encoding="utf-8")
    selection = {
        "reference": f"vendor/image:1.2.3@sha256:{'a' * 64}",
        "file": "Dockerfile",
        "inherited_from": {"commit": "b" * 40, "reference": "vendor/image:1.2.3"},
    }
    ledger = tmp_path / "scripts" / "dependency-selections.json"
    ledger.write_text(json.dumps({"selections": [selection]}), encoding="utf-8")
    monkeypatch.setattr(audit.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout="FROM vendor/image:1.2.3\n",
    ))
    findings = audit.audit_selections(tmp_path)
    assert findings == []
    selection["inherited_from"]["reference"] = "vendor/image:1.2.2"
    ledger.write_text(json.dumps({"selections": [selection]}), encoding="utf-8")
    findings = audit.audit_selections(tmp_path)
    assert [item["rule"] for item in findings] == ["inherited-pin"]
    selection["inherited_from"]["reference"] = "vendor/image:1.2.3"
    ledger.write_text(json.dumps({"selections": [selection]}), encoding="utf-8")
    monkeypatch.setattr(audit.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout="FROM vendor/image:1.2.2\n",
    ))
    findings = audit.audit_selections(tmp_path)
    assert [item["rule"] for item in findings] == ["inherited-pin"]


def test_compiler_sdk_cannot_silently_replace_locked_versions():
    sdk = load_dependency_script("scripts/prepare_model_catalog_sdk.py")
    dependencies = {"@github/copilot-sdk": "1.0.16", "undici": "6.28.0"}
    sdk.verify_install_command(
        "run: npm install --ignore-scripts --no-save @github/copilot-sdk@1.0.16 undici@6.28.0\n",
        dependencies,
    )
    with pytest.raises(ValueError, match="Regenerate and review"):
        sdk.verify_install_command(
            "run: npm install --ignore-scripts --no-save @github/copilot-sdk@1.0.17 undici@6.28.0\n",
            dependencies,
        )


def test_rpm_download_rejects_modified_artifact_and_unexpected_origin(tmp_path, monkeypatch):
    installer = load_dependency_script("docker-customization/install_locked_rpms.py")
    requests = []

    def download(url, timeout):
        requests.append(url)
        return io.BytesIO(b"modified-rpm")

    monkeypatch.setattr(installer, "urlopen", download)
    with pytest.raises(ValueError, match="unexpected artifact URL"):
        installer.download_package({"url": "https://example.com/tool.rpm", "sha256": "0" * 64}, tmp_path)
    assert requests == []
    with pytest.raises(ValueError, match="checksum mismatch"):
        installer.download_package({
            "url": "https://packages.microsoft.com/tool.rpm", "sha256": "0" * 64,
        }, tmp_path)
    assert len(requests) == 1


def test_cargo_requires_exact_direct_versions_and_resolved_integrity(tmp_path):
    (tmp_path / "Cargo.lock").write_text(
        '[[package]]\nname="serde"\nversion="1.0.229"\nsource="registry+https://github.com/rust-lang/crates.io-index"\n'
        f'checksum="{"a" * 64}"\n', encoding="utf-8",
    )
    pinned = audit.audit_cargo("Cargo.toml", '[dependencies]\nserde="=1.0.229"\n', tmp_path)
    assert pinned == []
    floating = audit.audit_cargo("Cargo.toml", '[dependencies]\nserde="1.0.229"\n', tmp_path)
    assert [item["rule"] for item in floating] == ["cargo-direct-pin"]
    (tmp_path / "Cargo.lock").write_text(
        '[[package]]\nname="serde"\nversion="1.0.229"\nsource="registry+https://github.com/rust-lang/crates.io-index"\n',
        encoding="utf-8",
    )
    missing_integrity = audit.audit_cargo("Cargo.toml", '[dependencies]\nserde="=1.0.229"\n', tmp_path)
    assert [item["rule"] for item in missing_integrity] == ["cargo-integrity"]


def test_ruby_lock_retains_platform_specific_exact_resolutions(tmp_path):
    (tmp_path / "Gemfile.lock").write_text(
        "GEM\n  specs:\n    nokogiri (1.19.4-x64-mingw-ucrt)\n\nBUNDLED WITH\n   2.7.2\n",
        encoding="utf-8",
    )
    pinned = audit.audit_gemfile("Gemfile", 'gem "nokogiri", "1.19.4"\n', tmp_path)
    assert pinned == []
    floating = audit.audit_gemfile("Gemfile", 'gem "nokogiri", "~> 1.19"\n', tmp_path)
    assert [item["rule"] for item in floating] == ["ruby-direct-pin"]


def test_terraform_provider_pin_must_match_its_resolved_lock(tmp_path):
    (tmp_path / ".terraform.lock.hcl").write_text(
        'provider "registry.terraform.io/hashicorp/azurerm" {\n  version = "4.63.0"\n}\n',
        encoding="utf-8",
    )
    source = 'terraform { required_version = "= 1.12.0"\n required_providers { azurerm { source = "hashicorp/azurerm"\n version = "= 4.63.0" } } }\n'
    pinned = audit.audit_terraform("main.tf", source, tmp_path)
    assert pinned == []
    mismatched = audit.audit_terraform("main.tf", source.replace("= 4.63.0", "= 4.62.0"), tmp_path)
    assert [item["rule"] for item in mismatched] == ["terraform-lock-sync"]


def test_workflow_latest_exception_does_not_cover_other_acr_images():
    findings = audit.audit_workflow(
        "workflow.yml", "run: docker pull example.azurecr.io/third-party:latest\n",
    )
    assert [item["rule"] for item in findings] == ["third-party-latest"]


def test_evidence_hashes_are_portable_between_lf_and_crlf_checkouts(tmp_path):
    source = tmp_path / "requirements.txt"
    lock = tmp_path / "requirements.lock.txt"
    source.write_bytes(b"requests==2.33.1\r\n")
    lock.write_bytes(b"requests==2.33.1\r\n")
    digest = hashlib.sha256(b"requests==2.33.1\n").hexdigest()
    (tmp_path / "requirements.lock.json").write_text(json.dumps({
        "selected_at": "2026-11-19T12:00:00Z",
        "inputs": {"requirements.txt": digest},
        "lock_sha256": digest,
        "packages": {},
    }), encoding="utf-8")
    findings = audit.audit_lock(Path("requirements.lock.txt"), tmp_path)
    assert findings == []


def test_verified_rpms_are_installed_without_repository_resolution(tmp_path, monkeypatch):
    installer = load_dependency_script("docker-customization/install_locked_rpms.py")
    payload = b"verified-rpm"
    (tmp_path / "azurelinux-packages.lock.json").write_text(json.dumps({
        "profiles": {"common": [{
            "url": "https://packages.microsoft.com/test.rpm",
            "sha256": hashlib.sha256(payload).hexdigest(),
        }]},
    }), encoding="utf-8")
    monkeypatch.setattr(installer, "__file__", str(tmp_path / "install_locked_rpms.py"))
    monkeypatch.setattr("sys.argv", ["install_locked_rpms.py", "--profile", "common"])
    monkeypatch.setattr(installer, "urlopen", lambda url, timeout: io.BytesIO(payload))
    invocations = []

    def run(command, check):
        invocations.append((command[:4], Path(command[4]).read_bytes(), check))

    monkeypatch.setattr(installer.subprocess, "run", run)
    installer.main()
    assert invocations == [(["tdnf", "--disablerepo=*", "install", "-y"], payload, True)]
