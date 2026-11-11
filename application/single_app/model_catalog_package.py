# model_catalog_package.py
"""Offline catalog package validation. No bootstrap, network, or storage imports."""

import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from jsonschema import Draft202012Validator, FormatChecker, validators


ROOT = Path(__file__).resolve().parent
TRUST_PATH = ROOT / "static" / "json" / "model_catalog_trusted_keys.json"
DEVELOPMENT_TRUST_PATH = ROOT / "static" / "json" / "model_catalog_development_trusted_keys.json"
SCHEMA_PATH = ROOT / "static" / "json" / "schemas" / "model_capabilities.schema.json"
MAX_PAYLOAD_BYTES = 1024 * 1024
MAX_PACKAGE_BYTES = 1500 * 1024
CATALOG_REPOSITORY = "https://github.com/microsoft/simplechat"
CHANNEL_BRANCHES = {"production": "model-catalog", "development": "model-catalog-development"}
CATALOG_CHANNEL = os.environ.get("MODEL_CATALOG_CHANNEL", "production")
if CATALOG_CHANNEL not in CHANNEL_BRANCHES:
    raise ValueError("MODEL_CATALOG_CHANNEL must be production or development.")
DISCOVERY_URL = (
    "https://raw.githubusercontent.com/microsoft/simplechat/"
    f"{CHANNEL_BRANCHES[CATALOG_CHANNEL]}/model-catalog/latest.json"
)
REVISION_PATTERN = re.compile(r"^[1-9][0-9]{0,8}$")
MANIFEST_FIELDS = {
    "formatVersion", "revision", "publishedAt", "sha256", "size",
    "schemaVersion", "minimumAppVersion", "keyId", "algorithm", "sourceCommit", "channel",
}
CatalogSchemaValidator = validators.extend(
    Draft202012Validator,
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine(
        "integer", lambda _checker, value: type(value) is int,
    ),
)


class CatalogUpdateError(ValueError):
    """A stable error suitable for the administrative interface."""

    def __init__(self, message):
        super().__init__(message)
        self.public_message = message


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CatalogUpdateError("The package contains duplicate JSON fields.")
        result[key] = value
    return result


def read_json(raw, maximum=MAX_PACKAGE_BYTES):
    if not isinstance(raw, bytes) or len(raw) > maximum:
        raise CatalogUpdateError("The catalog package exceeds its size limit.")
    try:
        return json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_constant=lambda _value: _reject_number(),
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise CatalogUpdateError("The catalog package is not valid UTF-8 JSON.") from exc


def _reject_number():
    raise CatalogUpdateError("Non-finite numbers are not supported.")


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def decode_bytes(value, maximum):
    if not isinstance(value, str) or len(value) > (maximum + 2) // 3 * 4:
        raise CatalogUpdateError("The package has an invalid encoded field.")
    try:
        result = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise CatalogUpdateError("The package has an invalid encoded field.") from exc
    if len(result) > maximum:
        raise CatalogUpdateError("The package exceeds its decoded size limit.")
    return result


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise CatalogUpdateError("The package application version is invalid.")
    return tuple(int(part) for part in value.split("."))


def trusted_keys(*, channel=None):
    channel = CATALOG_CHANNEL if channel is None else channel
    if channel not in CHANNEL_BRANCHES:
        raise CatalogUpdateError("The catalog channel is unsupported.")
    path = TRUST_PATH if channel == "production" else DEVELOPMENT_TRUST_PATH
    keys = read_json(path.read_bytes(), 32 * 1024)
    if not isinstance(keys, dict) or not all(isinstance(value, str) for value in keys.values()):
        raise CatalogUpdateError("The configured publisher trust map is invalid.")
    if channel == "development":
        production = trusted_keys(channel="production")
        try:
            production_keys = [
                serialization.load_pem_public_key(value.encode("ascii")).public_numbers()
                for value in production.values()
            ]
            if set(keys) & set(production) or any(
                serialization.load_pem_public_key(value.encode("ascii")).public_numbers() in production_keys
                for value in keys.values()
            ):
                raise CatalogUpdateError("Development and production must use separate publisher keys.")
        except (ValueError, TypeError, UnicodeError, AttributeError) as exc:
            raise CatalogUpdateError("Development publisher keys must be distinct valid public keys.") from exc
    return keys


def validate_catalog(document):
    schema = read_json(SCHEMA_PATH.read_bytes(), 256 * 1024)
    errors = CatalogSchemaValidator(schema, format_checker=FormatChecker()).iter_errors(document)
    if next(errors, None) is not None:
        raise CatalogUpdateError("The catalog does not match the supported model schema.")
    identities = set()
    sources = {entry["id"] for entry in document["sources"]}
    if len(sources) != len(document["sources"]):
        raise CatalogUpdateError("The catalog contains duplicate evidence sources.")
    for record in document["models"]:
        for value in [record["id"], *record.get("aliases", []), *record.get("verifiedAliases", [])]:
            normalized = re.sub(r"[\s_.]+", "-", value.strip().lower())
            # An alias may repeat its own canonical ID, but not another record's.
            if normalized in identities:
                raise CatalogUpdateError("The catalog contains ambiguous model identities.")
        identities.update(
            re.sub(r"[\s_.]+", "-", value.strip().lower())
            for value in [record["id"], *record.get("aliases", []), *record.get("verifiedAliases", [])]
        )
        if set(record.get("sourceIds", [])) - sources:
            raise CatalogUpdateError("The catalog references missing evidence sources.")
    return document


def verify_package(raw, app_version, *, keys=None, channel=None):
    envelope = read_json(raw)
    if not isinstance(envelope, dict) or set(envelope) != {"manifest", "payload", "signature"}:
        raise CatalogUpdateError("Choose a publisher-signed catalog package.")
    manifest_raw = decode_bytes(envelope["manifest"], 16 * 1024)
    manifest = read_json(manifest_raw, 16 * 1024)
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS:
        raise CatalogUpdateError("The signed catalog manifest is invalid.")
    if manifest["formatVersion"] != 1 or type(manifest["formatVersion"]) is not int:
        raise CatalogUpdateError("This catalog package format requires an application upgrade.")
    if manifest["algorithm"] != "RS256":
        raise CatalogUpdateError("The catalog signature algorithm is unsupported.")
    channel = CATALOG_CHANNEL if channel is None else channel
    if channel not in CHANNEL_BRANCHES or manifest["channel"] != channel:
        raise CatalogUpdateError("The signed catalog is not for this application's catalog channel.")
    key_id = manifest["keyId"]
    keys = trusted_keys(channel=channel) if keys is None else keys
    if not isinstance(key_id, str) or key_id not in keys:
        raise CatalogUpdateError("The catalog publisher key is not trusted by this application.")
    try:
        public_key = serialization.load_pem_public_key(keys[key_id].encode("ascii"))
        if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size < 3072:
            raise CatalogUpdateError("The configured publisher key is invalid.")
        public_key.verify(
            decode_bytes(envelope["signature"], 1024), manifest_raw,
            padding.PKCS1v15(), hashes.SHA256(),
        )
    except (InvalidSignature, ValueError, TypeError, UnicodeError) as exc:
        raise CatalogUpdateError("The catalog signature could not be verified.") from exc
    payload_raw = decode_bytes(envelope["payload"], MAX_PAYLOAD_BYTES)
    if (
        type(manifest["size"]) is not int or manifest["size"] != len(payload_raw)
        or manifest["sha256"] != hashlib.sha256(payload_raw).hexdigest()
    ):
        raise CatalogUpdateError("The catalog contents do not match the signed manifest.")
    if not isinstance(manifest["revision"], str) or not REVISION_PATTERN.fullmatch(manifest["revision"]):
        raise CatalogUpdateError("The catalog revision must be a positive monotonic integer.")
    if (
        not isinstance(manifest["sourceCommit"], str)
        or not re.fullmatch(r"[a-f0-9]{40}", manifest["sourceCommit"])
        or not isinstance(manifest["publishedAt"], str)
        or not FormatChecker().conforms(manifest["publishedAt"], "date-time")
    ):
        raise CatalogUpdateError("The catalog publication metadata is invalid.")
    if version_tuple(manifest["minimumAppVersion"]) > version_tuple(app_version):
        raise CatalogUpdateError("Upgrade SimpleChat before installing this catalog.")
    document = validate_catalog(read_json(payload_raw, MAX_PAYLOAD_BYTES))
    if type(manifest["schemaVersion"]) is not int or manifest["schemaVersion"] != document["schemaVersion"]:
        raise CatalogUpdateError("The catalog schema does not match the signed manifest.")
    return {"manifest": manifest, "document": document, "digest": hashlib.sha256(raw).hexdigest()}


def package_url(commit, filename):
    if (
        not isinstance(commit, str) or not re.fullmatch(r"[a-f0-9]{40}", commit)
        or not isinstance(filename, str)
        or not re.fullmatch(r"catalog-[1-9][0-9]{0,8}-\d{4}-\d{2}-\d{2}\.json", filename)
    ):
        raise CatalogUpdateError("The official catalog discovery response is invalid.")
    return f"https://raw.githubusercontent.com/microsoft/simplechat/{commit}/model-catalog/{filename}"
