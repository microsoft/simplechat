# publish_model_catalog.py
"""Build, sign and publish a catalog from a protected Actions job.

Signing uses either an Azure Key Vault key (CATALOG_VAULT_KEY_URL) or a private key
held as the protected environment's CATALOG_SIGNING_KEY secret, for publishers whose
vaults cannot be reached from GitHub-hosted runners.
"""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

import requests

APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))

from model_catalog_package import (
    DEVELOPMENT_TRUST_PATH, TRUST_PATH, CHANNEL_BRANCHES, MAX_PACKAGE_BYTES, MAX_PAYLOAD_BYTES, REVISION_PATTERN,
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


def _sign_with_vault(vault_key_url, manifest_raw):
    # Publisher-only dependencies must not enter the application bootstrap graph.
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.keys.crypto import CryptographyClient, SignatureAlgorithm

    credential = DefaultAzureCredential()
    try:
        with CryptographyClient(vault_key_url, credential) as client:
            return client.sign(
                SignatureAlgorithm.rs256, hashlib.sha256(manifest_raw).digest(),
            ).signature
    finally:
        credential.close()


def _sign_with_secret(signing_key_pem, key_id, channel, manifest_raw):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    try:
        private_key = serialization.load_pem_private_key(signing_key_pem.encode("ascii"), password=None)
    except (ValueError, TypeError, UnicodeError):
        # Never include the secret or the parser's detail in the message.
        raise ValueError("CATALOG_SIGNING_KEY is not an unencrypted PEM private key.") from None
    if not isinstance(private_key, rsa.RSAPrivateKey) or private_key.key_size < 3072:
        raise ValueError("CATALOG_SIGNING_KEY must be an RSA key of at least 3,072 bits.")
    trusted = trusted_keys(channel=channel).get(key_id)
    if trusted is None:
        raise ValueError(f"Key ID {key_id} is not in the {channel} trust map shipped with the application.")
    trusted_numbers = serialization.load_pem_public_key(trusted.encode("ascii")).public_numbers()
    if trusted_numbers != private_key.public_key().public_numbers():
        raise ValueError(f"CATALOG_SIGNING_KEY does not match the trusted public key for {key_id}.")
    return private_key.sign(manifest_raw, padding.PKCS1v15(), hashes.SHA256())


def sign_candidate(output, key_id, vault_key_url, app_version, channel="production", *, signing_key_pem=None):
    if bool(vault_key_url) == bool(signing_key_pem):
        raise ValueError("Configure exactly one of CATALOG_VAULT_KEY_URL or the CATALOG_SIGNING_KEY secret.")
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
    if vault_key_url:
        signature = _sign_with_vault(vault_key_url, manifest_raw)
    else:
        signature = _sign_with_secret(signing_key_pem, key_id, channel, manifest_raw)
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


def public_key_pem(n, e):
    """Return the SubjectPublicKeyInfo PEM for an RSA key's modulus and exponent."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    numbers = rsa.RSAPublicNumbers(int.from_bytes(e, "big"), int.from_bytes(n, "big"))
    key = numbers.public_key()
    if key.key_size < 3072:
        raise ValueError("The publisher key must be an RSA key of at least 3,072 bits.")
    return key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def add_trusted_key(key_id, pem, channel="production"):
    """Write one public key into the channel's bundled trust map and re-verify the map."""
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", key_id or ""):
        raise ValueError("The key ID must be 1-64 letters, digits, dots, dashes or underscores.")
    path = TRUST_PATH if channel == "production" else DEVELOPMENT_TRUST_PATH
    original = path.read_bytes()
    keys = read_json(original, 32 * 1024)
    if key_id in keys and keys[key_id] != pem:
        raise ValueError(f"Key ID {key_id} is already trusted with different key material. Use a new key ID to rotate.")
    keys[key_id] = pem
    path.write_text(json.dumps(keys, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        # Re-reads the file: rejects a development key that reuses production material.
        trusted_keys(channel=channel)
    except Exception:
        path.write_bytes(original)
        raise
    return path


def generate_signing_key(key_id, private_key_out, channel="production"):
    """Create a publisher key pair locally: public half into the trust map, private half to a file.

    The private file is for loading into the protected GitHub environment's
    CATALOG_SIGNING_KEY secret and then deleting. It is refused inside the repository
    so it cannot be committed by accident, and never overwrites an existing file.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    target = Path(private_key_out).expanduser().resolve()
    repository = APP.parents[1].resolve()
    if target == repository or repository in target.parents:
        raise ValueError("Write the private key outside the repository so it cannot be committed.")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    # Mode "xb" refuses to replace an existing key file.
    with open(target, "xb") as handle:
        handle.write(private_pem)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    try:
        trust_path = add_trusted_key(key_id, public_pem, channel)
    except Exception:
        target.unlink()
        raise
    return trust_path, target


def trust_vault_key(key_id, vault_key_url, channel="production"):
    """Read the public half of the publisher's Key Vault key and bundle it with the app.

    Only the public key leaves the vault. The URL must name a key version, because
    the signing job signs with that exact version.
    """
    # Publisher-only dependencies must not enter the application bootstrap graph.
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.keys import KeyClient, KeyVaultKeyIdentifier

    identifier = KeyVaultKeyIdentifier(vault_key_url)
    if not identifier.version:
        raise ValueError("The Key Vault key URL must include the key version that signs packages.")
    credential = DefaultAzureCredential()
    try:
        client = KeyClient(identifier.vault_url, credential)
        try:
            key = client.get_key(identifier.name, identifier.version).key
        finally:
            client.close()
    finally:
        credential.close()
    if key.kty not in ("RSA", "RSA-HSM"):
        raise ValueError("The publisher key must be an RSA key.")
    return add_trusted_key(key_id, public_key_pem(key.n, key.e), channel)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "sign-publish", "record-validation", "trust-key", "generate-key"])
    parser.add_argument("--channel", choices=list(CHANNEL_BRANCHES), default="production")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--key-id", help="trust-key: stable ID written into the trust map (CATALOG_KEY_ID)")
    parser.add_argument("--vault-key-url", help="trust-key: versioned Key Vault key URL (CATALOG_VAULT_KEY_URL)")
    parser.add_argument("--private-key-out", help="generate-key: file outside the repository for the private key")
    args = parser.parse_args()
    if args.command == "generate-key":
        if not args.key_id or not args.private_key_out:
            parser.error("generate-key requires --key-id and --private-key-out")
        trust_path, private_path = generate_signing_key(args.key_id, args.private_key_out, args.channel)
        print(f"Trusted {args.key_id} in {trust_path.relative_to(APP.parents[1])}. Commit it and ship it in a release.")
        print(
            f"Private key written to {private_path}. Load it into the CATALOG_SIGNING_KEY secret of the "
            f"{PUBLISHING_POLICIES[args.channel][1]} environment, then delete the file."
        )
        return
    if args.command == "trust-key":
        if not args.key_id or not args.vault_key_url:
            parser.error("trust-key requires --key-id and --vault-key-url")
        path = trust_vault_key(args.key_id, args.vault_key_url, args.channel)
        print(f"Trusted {args.key_id} in {path.relative_to(APP.parents[1])}. Commit it and ship it in a release.")
        return
    if args.output is None:
        parser.error("--output is required for this command")
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
            args.output, os.environ["CATALOG_KEY_ID"], os.environ.get("CATALOG_VAULT_KEY_URL"),
            os.environ["CATALOG_APP_VERSION"],
            args.channel,
            signing_key_pem=os.environ.pop("CATALOG_SIGNING_KEY", None),
        )
        publish(args.output, filename, args.channel)


if __name__ == "__main__":
    main()
