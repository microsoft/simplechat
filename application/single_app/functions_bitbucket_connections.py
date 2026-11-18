# functions_bitbucket_connections.py
"""Private Bitbucket OAuth connections; storage and secrets supplied by composition."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlencode

import requests
from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from cryptography.fernet import Fernet, InvalidToken

from cosmos_document_utils import normalize_cosmos_document
from functions_bitbucket_operations import (
    BitbucketError, bounded_response, fail, normalize_bitbucket_manifest, policy_fingerprint,
)
from functions_outbound_http import create_guarded_session
from functions_outbound_destinations import OutboundDestinationError


_service = None


def configure_bitbucket_connections(service):
    global _service
    _service = service


def bitbucket_connections():
    if _service is None:
        fail("connection_unavailable", "Bitbucket connections are not configured.", 503)
    return _service


def encryption_key():
    """Deploy through a server-side secret/Key Vault App Service reference, never settings JSON."""
    value = os.environ.get("BITBUCKET_TOKEN_ENCRYPTION_KEY", "")
    try:
        return Fernet(value.encode("ascii"))
    except (ValueError, UnicodeError):
        fail("encryption_required", "Configure BITBUCKET_TOKEN_ENCRYPTION_KEY before connecting Bitbucket.", 503)


class BitbucketConnections:
    def __init__(self, container, authorize, *, key_provider=encryption_key, clock=time.time,
                 session_factory=create_guarded_session):
        self.container = container
        self.authorize = authorize
        self.key_provider = key_provider
        self.clock = clock
        self.session_factory = session_factory

    def read(self, user_id, item_id):
        try:
            item = normalize_cosmos_document(self.container.read_item(item=item_id, partition_key=user_id))
        except CosmosResourceNotFoundError:
            return None
        if item.get("user_id") != user_id or item.get("id") != item_id:
            fail("connection_invalid", "Bitbucket connection ownership could not be verified.", 409)
        return item

    def replace(self, item, changes):
        return normalize_cosmos_document(self.container.replace_item(
            item=item["id"], body={**item, **changes}, etag=item["_etag"],
            match_condition=MatchConditions.IfNotModified,
        ))

    def binding(self, user_id, action_ref):
        manifest = normalize_bitbucket_manifest(self.authorize(user_id, action_ref), allow_empty=True)
        fingerprint = policy_fingerprint(manifest)
        key = hashlib.sha256(json.dumps([user_id, action_ref]).encode()).hexdigest()
        return manifest, fingerprint, f"bitbucket-{key}"

    def seal(self, value, binding):
        return self.key_provider().encrypt(json.dumps({"binding": binding, "value": value}).encode()).decode("ascii")

    def open(self, value, binding):
        try:
            payload = json.loads(self.key_provider().decrypt(value.encode("ascii")))
            if payload["binding"] != binding or not isinstance(payload["value"], dict):
                raise ValueError("binding")
            return payload["value"]
        except (InvalidToken, ValueError, KeyError, TypeError):
            fail("reconnect_required", "Bitbucket credentials could not be verified. Reconnect your account.", 409)

    def endpoints(self, manifest):
        if manifest["additionalFields"]["edition"] == "cloud":
            return "https://bitbucket.org/site/oauth2/authorize", "https://bitbucket.org/site/oauth2/access_token"
        root = manifest["endpoint"] + "/rest/oauth2/latest"
        return root + "/authorize", root + "/token"

    def status(self, user_id, action_ref):
        _manifest, fingerprint, item_id = self.binding(user_id, action_ref)
        item = self.read(user_id, item_id)
        return {"connected": bool(item and item.get("fingerprint") == fingerprint
                                  and item.get("tokens") and not item.get("refresh_lease")), "connection_id": item_id}

    def start(self, user_id, action_ref, session_binding, redirect_uri):
        manifest, fingerprint, item_id = self.binding(user_id, action_ref)
        if manifest["additionalFields"]["auth_method"] != "oauth":
            fail("configuration_invalid", "This action is not configured for OAuth.")
        if not manifest["auth"].get("identity") or not manifest["auth"].get("key"):
            fail("configuration_invalid", "Configure the Bitbucket OAuth client ID and secret.")
        self.key_provider()
        current = self.read(user_id, item_id)
        if current is None:
            self.container.create_item({"id": item_id, "user_id": user_id, "generation": secrets.token_hex(16),
                                        "tokens": None, "refresh_lease": None, "ttl": -1})
            current = self.read(user_id, item_id)
        current = self.replace(current, {"generation": secrets.token_hex(16), "fingerprint": fingerprint,
                                         "tokens": None, "refresh_lease": None})
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        flow = {
            "id": f"flow-{hashlib.sha256(state.encode()).hexdigest()}", "user_id": user_id,
            "action_ref": action_ref, "fingerprint": fingerprint, "connection_id": item_id,
            "generation": current["generation"], "session_binding": session_binding,
            "redirect_uri": redirect_uri, "expires": self.clock() + 600, "ttl": 600,
            "consumed": False, "verifier": self.seal({"verifier": verifier}, [user_id, item_id]),
        }
        self.container.create_item(flow)
        endpoint, _token = self.endpoints(manifest)
        query = {"client_id": manifest["auth"]["identity"], "response_type": "code",
                 "redirect_uri": redirect_uri, "state": state}
        if manifest["additionalFields"]["edition"] == "data_center":
            query.update(scope="REPO_READ", code_challenge_method="S256",
                         code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("="))
        return {"authorization_url": endpoint + "?" + urlencode(query)}

    def exchange(self, manifest, data):
        _authorize, endpoint = self.endpoints(manifest)
        client = manifest["auth"]
        basic = None
        if manifest["additionalFields"]["edition"] == "cloud":
            basic = (client["identity"], client["key"])
        else:
            data = {**data, "client_id": client["identity"], "client_secret": client["key"]}
        try:
            with self.session_factory() as session:
                response = session.post(endpoint, data=data, auth=basic, timeout=(10, 30),
                                        stream=True, allow_redirects=False)
                if response.status_code in {400, 401, 403}:
                    response.close()
                    fail("reconnect_required", "Bitbucket authorization expired or was rejected. Reconnect your account.", 409)
                tokens = bounded_response(response, limit=65536)
        except requests.RequestException:
            fail("connection_failed", "The Bitbucket authorization service could not be reached.", 502)
        except OutboundDestinationError as error:
            raise BitbucketError("destination_invalid", error.public_message) from None
        if (
            not isinstance(tokens.get("access_token"), str) or not tokens["access_token"]
            or str(tokens.get("token_type", "")).lower() != "bearer"
            or not isinstance(tokens.get("refresh_token"), str) or not tokens["refresh_token"]
            or type(tokens.get("expires_in")) is not int or tokens["expires_in"] <= 0
        ):
            fail("response_invalid", "Bitbucket returned an invalid OAuth token response.", 502)
        return {key: tokens[key] for key in ("access_token", "refresh_token", "expires_in")}

    def complete(self, user_id, state, code, session_binding):
        if not isinstance(state, str) or not 32 <= len(state) <= 128 or not isinstance(code, str) or not 1 <= len(code) <= 8192:
            fail("state_invalid", "The Bitbucket sign-in request is invalid or expired.")
        flow = self.read(user_id, f"flow-{hashlib.sha256(state.encode()).hexdigest()}")
        if (
            not flow or flow["consumed"] or flow["expires"] < self.clock()
            or not hmac.compare_digest(flow["session_binding"], session_binding)
        ):
            fail("state_invalid", "The Bitbucket sign-in request is invalid or expired.")
        manifest, fingerprint, item_id = self.binding(user_id, flow["action_ref"])
        current = self.read(user_id, item_id)
        if fingerprint != flow["fingerprint"] or not current or current["generation"] != flow["generation"]:
            fail("connection_changed", "The action or connection changed. Start sign-in again.", 409)
        self.replace(flow, {"consumed": True})
        verifier = self.open(flow["verifier"], [user_id, item_id])["verifier"]
        data = {"grant_type": "authorization_code", "code": code, "redirect_uri": flow["redirect_uri"]}
        if manifest["additionalFields"]["edition"] == "data_center":
            data["code_verifier"] = verifier
        tokens = self.exchange(manifest, data)
        # A concurrent disconnect or reconnect must win over an in-flight token exchange.
        self.replace(current, {"tokens": self.seal(tokens, [user_id, item_id]),
                               "expires": self.clock() + tokens["expires_in"],
                               "redirect_uri": flow["redirect_uri"], "refresh_lease": None})

    def disconnect(self, user_id, action_ref):
        _manifest, _fingerprint, item_id = self.binding(user_id, action_ref)
        item = self.read(user_id, item_id)
        if item:
            self.replace(item, {"tokens": None, "generation": secrets.token_hex(16), "refresh_lease": None})

    def token(self, user_id, action_ref):
        manifest, fingerprint, item_id = self.binding(user_id, action_ref)
        item = self.read(user_id, item_id)
        if not item or item.get("fingerprint") != fingerprint or not item.get("tokens"):
            fail("reconnect_required", "Connect Bitbucket in the action's connection controls before reviewing code.", 409)
        if item.get("refresh_lease"):
            fail("refresh_in_progress", "Bitbucket token refresh is in progress. Retry or reconnect if interrupted.", 409)
        tokens = self.open(item["tokens"], [user_id, item_id])
        if item["expires"] > self.clock() + 60:
            return tokens["access_token"]
        claimed = self.replace(item, {"refresh_lease": secrets.token_hex(16)})
        try:
            refreshed = self.exchange(manifest, {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
                                                 "redirect_uri": item["redirect_uri"]})
        except BitbucketError:
            # Rotation may have happened even if a response was lost. Never replay the old refresh token.
            self.replace(claimed, {"tokens": None, "refresh_lease": None})
            raise
        self.replace(claimed, {"tokens": self.seal(refreshed, [user_id, item_id]),
                               "expires": self.clock() + refreshed["expires_in"], "refresh_lease": None})
        return refreshed["access_token"]
