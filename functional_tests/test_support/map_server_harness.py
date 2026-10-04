# map_server_harness.py
"""Shared helpers for the map server functional tests: signed test tokens, actor headers and a test client."""

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAP_SERVER_ROOT = REPO_ROOT / "application" / "map_server"
if str(MAP_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(MAP_SERVER_ROOT))

# The map server package lives outside the test tree, so these imports follow the path setup above.
import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from mapserver.app import create_app  # noqa: E402
from mapserver.auth import TokenValidator, encode_actor  # noqa: E402
from mapserver.settings import Settings  # noqa: E402
from mapserver.store import InMemoryMapStore  # noqa: E402

TENANT_ID = "00000000-0000-0000-0000-00000000aaaa"
AUDIENCE = "api://map-server-test"
ISSUER_V1 = f"https://sts.windows.net/{TENANT_ID}/"
ISSUER_V2 = f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"
CALLER_OBJECT_ID = "11111111-1111-1111-1111-111111111111"
MAP_SERVER_ROLE = "MapServer.ActOnBehalf"

SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _SigningKey:
    def __init__(self, key):
        self.key = key


class StaticJwkClient:
    """Stands in for PyJWKClient: every token is checked against the test public key."""

    def get_signing_key_from_jwt(self, token):
        return _SigningKey(SIGNING_KEY.public_key())


def make_settings(**overrides) -> Settings:
    values = dict(
        tenant_id=TENANT_ID,
        audiences=(AUDIENCE,),
        issuers=(ISSUER_V1, ISSUER_V2),
        jwks_url="https://keys.invalid/discovery/v2.0/keys",
        store="memory",
        events_poll_seconds=0.05,
        events_keepalive_seconds=1.0,
        events_max_seconds=1.0,
    )
    values.update(overrides)
    settings = Settings(**values)
    settings.validate()
    return settings


def make_token(
    *, roles=(MAP_SERVER_ROLE,), audience=AUDIENCE, issuer=ISSUER_V1, object_id=CALLER_OBJECT_ID, expires_in=3600, key=None
) -> str:
    now = int(time.time())
    claims = {
        "aud": audience,
        "iss": issuer,
        "oid": object_id,
        "azp": "simplechat-test-app",
        "tid": TENANT_ID,
        "iat": now,
        "nbf": now,
        "exp": now + expires_in,
    }
    if roles is not None:
        claims["roles"] = list(roles)
    return jwt.encode(claims, key or SIGNING_KEY, algorithm="RS256")


def actor_headers(*, user_id="user-1", scope="group:team-1", access="write", token=None, **extra) -> dict:
    actor = {"user_id": user_id, "display_name": "Test user", "scope": scope, "access": access, **extra}
    return {"Authorization": f"Bearer {token or make_token()}", "X-Map-Actor": encode_actor(actor)}


def make_client(settings=None, *, store=None, tile_service=None, raise_server_exceptions=True) -> TestClient:
    settings = settings or make_settings()
    app = create_app(
        settings,
        store=store or InMemoryMapStore(),
        token_validator=TokenValidator(settings, jwk_client=StaticJwkClient()),
        tile_service=tile_service,
    )
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def create_map(client: TestClient, headers: dict, **body) -> str:
    response = client.post("/v1/maps", json={"title": "Response map", **body}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["map_id"]
