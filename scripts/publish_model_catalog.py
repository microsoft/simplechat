# publish_model_catalog.py
"""Build, Key Vault-sign and publish a catalog from a protected Actions job."""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import sys

import requests

APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))

from model_catalog_package import (
    CHANNEL_BRANCHES, MAX_PACKAGE_BYTES, MAX_PAYLOAD_BYTES, REVISION_PATTERN,
    canonical_bytes, package_url, read_json, trusted_keys, validate_catalog, verify_package, version_tuple,
)


PUBLISHING_POLICIES = {
    "production": ("refs/heads/main", "model-catalog-publishing"),
    "development": ("refs/heads/Development", "model-catalog-development"),
    "validation": ("refs/heads/Staging", "model-catalog-validation"),
}
RAW_ROOT = "https://raw.githubusercontent.com/microsoft/simplechat"
API_ROOT = "https://api.github.com/repos/microsoft/simplechat"


def require_publishing_approval(channel="production"):
    """Fail closed if the named environment has not actually been protected."""
    if channel not in PUBLISHING_POLICIES:
        raise ValueError("Unsupported publishing channel.")
    source_ref, environment = PUBLISHING_POLICIES[channel]
    if os.environ.get("GITHUB_REPOSITORY") != "microsoft/simplechat" or os.environ.get("GITHUB_REF") != source_ref:
        raise ValueError("Catalog publishing must use the official channel's reviewed source branch.")
    response = requests.get(
        f"{API_ROOT}/environments/{environment}",
        headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json"},
        timeout=30,
    )
    response.raise_for_status()
    rules = response.json().get("protection_rules", [])
    if not any(rule.get("type") == "required_reviewers" and rule.get("reviewers") for rule in rules):
        raise ValueError(f"Configure required reviewers on {environment} before publishing.")


def build_candidate(source_commit, output, channel="production"):
    if channel not in CHANNEL_BRANCHES:
        raise ValueError("Unsupported catalog channel.")
    if not re.fullmatch(r"[a-f0-9]{40}", source_commit):
        raise ValueError("A full reviewed source commit is required.")
    payload = (APP / "static" / "json" / "model_capabilities.json").read_bytes()
    document = validate_catalog(read_json(payload))
    release = read_json((APP.parents[1] / "model-catalog" / "release.json").read_bytes())
    if set(release) != {"revision", "minimumAppVersion"}:
        raise ValueError("Invalid catalog release metadata.")
    if not isinstance(release["revision"], str) or not REVISION_PATTERN.fullmatch(release["revision"]):
        raise ValueError("Catalog release revision must be a positive monotonic integer.")
    version_tuple(release["minimumAppVersion"])
    manifest = {
        "formatVersion": 1, **release,
        "publishedAt": datetime.now(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload),
        "schemaVersion": document["schemaVersion"], "sourceCommit": source_commit,
        "algorithm": "RS256", "channel": channel,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "payload.json").write_bytes(payload)
    (output / "candidate.json").write_bytes(canonical_bytes(manifest))
    return manifest


def sign_candidate(output, key_id, vault_key_url, app_version, channel="production"):
    # Publisher-only dependencies must not enter the application bootstrap graph.
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.keys.crypto import CryptographyClient, SignatureAlgorithm

    manifest = read_json((output / "candidate.json").read_bytes())
    if manifest["channel"] != channel or channel not in CHANNEL_BRANCHES:
        raise ValueError("The candidate channel differs from the signing job.")
    reviewed = os.environ.get("GITHUB_SHA")
    if reviewed and manifest["sourceCommit"] != reviewed:
        raise ValueError("The candidate does not match the reviewed workflow commit.")
    manifest["keyId"] = key_id
    manifest_raw = canonical_bytes(manifest)
    payload_raw = (output / "payload.json").read_bytes()
    if hashlib.sha256(payload_raw).hexdigest() != manifest["sha256"]:
        raise ValueError("Candidate contents changed after preparation.")
    if payload_raw != (APP / "static" / "json" / "model_capabilities.json").read_bytes():
        raise ValueError("The candidate differs from the reviewed catalog source.")
    credential = DefaultAzureCredential()
    try:
        with CryptographyClient(vault_key_url, credential) as client:
            signature = client.sign(
                SignatureAlgorithm.rs256, hashlib.sha256(manifest_raw).digest(),
            ).signature
    finally:
        credential.close()
    package = canonical_bytes({
        "manifest": base64.b64encode(manifest_raw).decode("ascii"),
        "payload": base64.b64encode(payload_raw).decode("ascii"),
        "signature": base64.b64encode(signature).decode("ascii"),
    })
    verify_package(package, app_version, keys=trusted_keys(channel=channel), channel=channel)
    filename = f"catalog-{manifest['revision']}-{manifest['publishedAt'][:10]}.json"
    (output / filename).write_bytes(package)
    return filename


def github_api():
    """Keep write credentials in the trusted deterministic publisher, never the researcher."""
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
    })

    def api(method, path, body=None, *, missing=False):
        response = session.request(method, API_ROOT + path, json=body, timeout=30)
        if missing and response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    return api


def commit_files(api, files, message, previous, base_tree):
    entries = []
    for path, content in files.items():
        blob = api("POST", "/git/blobs", {
            "content": base64.b64encode(content).decode("ascii"), "encoding": "base64",
        })
        entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    tree = api("POST", "/git/trees", {
        "tree": entries, **({"base_tree": base_tree} if base_tree else {}),
    })
    commit = api("POST", "/git/commits", {
        "message": message, "tree": tree["sha"], "parents": [previous] if previous else [],
    })
    return commit["sha"], tree["sha"]


def publish(output, filename, channel="production"):
    """Commit package and discovery pointer atomically on a separate data-only branch."""
    branch = CHANNEL_BRANCHES[channel]
    api = github_api()
    reference = api("GET", f"/git/ref/heads/{branch}", missing=True)
    parent = reference["object"]["sha"] if reference else None
    base = api("GET", f"/git/commits/{parent}")["tree"]["sha"] if parent else None
    manifest = read_json((output / "candidate.json").read_bytes())
    if parent:
        existing = api("GET", f"/contents/model-catalog/latest.json?ref={branch}")
        previous = read_json(base64.b64decode(existing["content"]))
        match = re.fullmatch(r"catalog-([1-9][0-9]*)-\d{4}-\d{2}-\d{2}\.json", previous["filename"])
        if match is None or int(manifest["revision"]) <= int(match.group(1)):
            raise ValueError("Publication must advance the catalog revision; older and repeated runs cannot replace it.")

    package_commit, package_tree = commit_files(
        api,
        {f"model-catalog/{filename}": (output / filename).read_bytes()},
        f"Publish signed model catalog {manifest['revision']}", parent, base,
    )
    latest_commit, _tree = commit_files(
        api,
        dict.fromkeys(
            ["model-catalog/latest.json", f"model-catalog/revisions/{manifest['revision']}.json"],
            canonical_bytes({"commit": package_commit, "filename": filename}),
        ),
        f"Advance model catalog to {manifest['revision']}", package_commit, package_tree,
    )
    if parent:
        api("PATCH", f"/git/refs/heads/{branch}", {"sha": latest_commit, "force": False})
    else:
        api("POST", "/git/refs", {"ref": f"refs/heads/{branch}", "sha": latest_commit})


def download_bytes(url, maximum=MAX_PACKAGE_BYTES):
    with requests.get(url, timeout=(3, 10), allow_redirects=False, stream=True) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("The official catalog source did not return a file.")
        result = bytearray()
        for chunk in response.iter_content(16384):
            result.extend(chunk)
            if len(result) > maximum:
                raise ValueError("The official catalog file exceeds its size limit.")
        return bytes(result)


def check_development_candidate(output, app_version):
    """Resolve the requested revision, not the moving development latest pointer."""
    manifest = read_json((output / "candidate.json").read_bytes())
    revision = manifest["revision"]
    if not isinstance(revision, str) or not REVISION_PATTERN.fullmatch(revision):
        raise ValueError("Invalid catalog revision.")
    pointer = read_json(download_bytes(
        f"{RAW_ROOT}/model-catalog-development/model-catalog/revisions/{revision}.json", 8192,
    ))
    if not isinstance(pointer, dict) or set(pointer) != {"commit", "filename"}:
        raise ValueError("The development revision pointer is invalid.")
    package = download_bytes(package_url(pointer["commit"], pointer["filename"]))
    verified = verify_package(
        package, app_version, keys=trusted_keys(channel="development"), channel="development",
    )
    tested = verified["manifest"]
    if any(tested[field] != manifest[field] for field in (
        "revision", "sha256", "size", "schemaVersion", "minimumAppVersion",
    )):
        raise ValueError("The reviewed catalog differs from the signed development candidate.")
    payload = (output / "payload.json").read_bytes()
    if hashlib.sha256(payload).hexdigest() != tested["sha256"]:
        raise ValueError("The prepared catalog changed after development verification.")
    return manifest, verified


def record_validation(output, app_version):
    """Record the Staging approver's test attestation for this exact payload."""
    manifest, verified = check_development_candidate(output, app_version)
    if manifest["channel"] != "development":
        raise ValueError("Staging validation must use a development candidate.")
    source_commit = os.environ["GITHUB_SHA"]
    if manifest["sourceCommit"] != source_commit:
        raise ValueError("Validation must use the reviewed Staging commit.")
    receipt = {
        "revision": manifest["revision"], "sha256": manifest["sha256"],
        "developmentPackage": verified["digest"], "stagingCommit": source_commit,
        "runId": os.environ["GITHUB_RUN_ID"],
    }
    if not re.fullmatch(r"[1-9][0-9]*", receipt["runId"]):
        raise ValueError("A GitHub Actions validation run is required.")
    api = github_api()
    branch = "model-catalog-validation"
    path = f"model-catalog/validated/{manifest['revision']}.json"
    reference = api("GET", f"/git/ref/heads/{branch}", missing=True)
    parent = reference["object"]["sha"] if reference else None
    base = api("GET", f"/git/commits/{parent}")["tree"]["sha"] if parent else None
    if parent and api("GET", f"/contents/{path}?ref={branch}", missing=True) is not None:
        raise ValueError("This revision already has a validation record; records cannot be replaced.")
    commit, _tree = commit_files(
        api, {path: canonical_bytes(receipt)},
        f"Record approved Staging validation for catalog {manifest['revision']}", parent, base,
    )
    if parent:
        api("PATCH", f"/git/refs/heads/{branch}", {"sha": commit, "force": False})
    else:
        api("POST", "/git/refs", {"ref": f"refs/heads/{branch}", "sha": commit})


def require_staging_validation(output, app_version):
    manifest, verified = check_development_candidate(output, app_version)
    receipt = read_json(download_bytes(
        f"{RAW_ROOT}/model-catalog-validation/model-catalog/validated/{manifest['revision']}.json", 8192,
    ))
    if not isinstance(receipt, dict) or set(receipt) != {
        "revision", "sha256", "developmentPackage", "stagingCommit", "runId",
    }:
        raise ValueError("The Staging validation record is invalid.")
    if (
        receipt["revision"] != manifest["revision"] or receipt["sha256"] != manifest["sha256"]
        or receipt["developmentPackage"] != verified["digest"]
        or not isinstance(receipt["runId"], str) or not re.fullmatch(r"[1-9][0-9]*", receipt["runId"])
        or not isinstance(receipt["stagingCommit"], str)
        or not re.fullmatch(r"[a-f0-9]{40}", receipt["stagingCommit"])
    ):
        raise ValueError("Staging validation does not identify this exact tested catalog.")
    run = github_api()("GET", f"/actions/runs/{receipt['runId']}")
    if (
        run.get("head_branch") != "Staging" or run.get("head_sha") != receipt["stagingCommit"]
        or run.get("path") != ".github/workflows/publish-model-catalog.yml"
        or run.get("event") not in {"push", "workflow_dispatch"}
        or run.get("status") != "completed" or run.get("conclusion") != "success"
    ):
        raise ValueError("The attested Staging validation workflow did not complete successfully.")
    reviewed = download_bytes(
        f"{RAW_ROOT}/{receipt['stagingCommit']}/application/single_app/static/json/model_capabilities.json",
        MAX_PAYLOAD_BYTES,
    )
    if reviewed != (output / "payload.json").read_bytes():
        raise ValueError("The successful Staging run did not validate these catalog bytes.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "sign-publish", "record-validation"])
    parser.add_argument("--channel", choices=list(CHANNEL_BRANCHES), default="production")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit")
    args = parser.parse_args()
    if args.command == "prepare":
        policy = "validation" if os.environ.get("GITHUB_REF") == "refs/heads/Staging" else args.channel
        require_publishing_approval(policy)
        build_candidate(args.source_commit, args.output, args.channel)
    elif args.command == "record-validation":
        if args.channel != "development":
            raise ValueError("Staging validation is restricted to the development channel.")
        require_publishing_approval("validation")
        record_validation(args.output, os.environ["CATALOG_APP_VERSION"])
    else:
        require_publishing_approval(args.channel)
        if args.channel == "production":
            require_staging_validation(args.output, os.environ["CATALOG_APP_VERSION"])
        filename = sign_candidate(
            args.output, os.environ["CATALOG_KEY_ID"], os.environ["CATALOG_VAULT_KEY_URL"],
            os.environ["CATALOG_APP_VERSION"],
            args.channel,
        )
        publish(args.output, filename, args.channel)


if __name__ == "__main__":
    main()
