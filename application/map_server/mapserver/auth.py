# auth.py
"""Who is calling: a trusted caller's Entra token, and the person that caller acts for."""

import base64
import binascii
import hmac
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Literal, Optional

import jwt
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import MapServerError, forbidden, unauthorized
from .settings import Settings

LOGGER = logging.getLogger("mapserver.auth")

ACTOR_HEADER = "X-Map-Actor"
MAX_ACTOR_HEADER_LENGTH = 4096
TOKEN_ALGORITHMS = ["RS256"]
TOKEN_LEEWAY_SECONDS = 60
LOCAL_DEV_CALLER_ID = "local-dev"
ID_PATTERN = r"^[A-Za-z0-9._:@-]{1,128}$"
OPTIONAL_ID_PATTERN = r"^[A-Za-z0-9._:@-]{0,128}$"
SCOPE_PATTERN = r"^(user|group):[A-Za-z0-9._-]{1,128}$"


@dataclass(frozen=True)
class Caller:
    """The application that presented the token, such as SimpleChat's managed identity."""

    object_id: str
    app_id: str
    roles: FrozenSet[str]


class ActorAgent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(default="", pattern=OPTIONAL_ID_PATTERN)
    name: str = Field(default="", max_length=120)


class Actor(BaseModel):
    """The person a trusted caller acts for, the scope it vouches for, and where the request came from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: str = Field(pattern=ID_PATTERN)
    display_name: str = Field(default="", max_length=120)
    scope: str = Field(pattern=SCOPE_PATTERN)
    access: Literal["read", "write"]
    conversation_id: str = Field(default="", pattern=OPTIONAL_ID_PATTERN)
    message_id: str = Field(default="", pattern=OPTIONAL_ID_PATTERN)
    run_id: str = Field(default="", pattern=OPTIONAL_ID_PATTERN)
    agent: Optional[ActorAgent] = None

    @property
    def can_write(self) -> bool:
        return self.access == "write"

    def summary(self) -> Dict[str, Any]:
        """What the map records about who made a change."""
        summary: Dict[str, Any] = {"user_id": self.user_id}
        for name in ("display_name", "conversation_id", "message_id", "run_id"):
            value = getattr(self, name)
            if value:
                summary[name] = value
        if self.agent and (self.agent.id or self.agent.name):
            summary["agent"] = {key: value for key, value in self.agent.model_dump().items() if value}
        return summary


def encode_actor(actor: Dict[str, Any]) -> str:
    """Encode an actor context for the X-Map-Actor header."""
    raw = json.dumps(actor, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def parse_actor(raw_header: Optional[str]) -> Actor:
    if not raw_header:
        raise MapServerError(400, "actor_required", f"The {ACTOR_HEADER} header is required.")
    if len(raw_header) > MAX_ACTOR_HEADER_LENGTH:
        raise MapServerError(400, "invalid_actor", "The actor context is invalid.")
    try:
        padded = raw_header.strip() + "=" * (-len(raw_header.strip()) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        return Actor.model_validate(payload)
    except (UnicodeError, binascii.Error, ValueError, ValidationError) as exc:
        LOGGER.info(f"[MAP_SERVER_AUTH] Rejected an invalid actor context ({type(exc).__name__}).")
        raise MapServerError(400, "invalid_actor", "The actor context is invalid.") from exc


def _bearer_token(authorization: Optional[str]) -> str:
    scheme, _, token = str(authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise unauthorized()
    return token.strip()


class TokenValidator:
    """Checks that a request carries an Entra token from a caller allowed to act for people."""

    def __init__(self, settings: Settings, jwk_client: Optional[Any] = None):
        self._settings = settings
        self._jwk_client = jwk_client
        if self._jwk_client is None and settings.jwks_url and not settings.local_dev_key:
            self._jwk_client = jwt.PyJWKClient(settings.jwks_url, cache_keys=True, lifespan=3600, timeout=10)

    def validate(self, authorization: Optional[str]) -> Caller:
        token = _bearer_token(authorization)
        if self._settings.local_dev_key:
            if hmac.compare_digest(token.encode("utf-8"), self._settings.local_dev_key.encode("utf-8")):
                return Caller(LOCAL_DEV_CALLER_ID, LOCAL_DEV_CALLER_ID, frozenset({self._settings.required_role}))
            raise unauthorized()

        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=TOKEN_ALGORITHMS,
                audience=list(self._settings.audiences),
                issuer=list(self._settings.issuers),
                leeway=TOKEN_LEEWAY_SECONDS,
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            LOGGER.info(f"[MAP_SERVER_AUTH] Rejected a caller token ({type(exc).__name__}).")
            raise unauthorized() from exc

        object_id = str(claims.get("oid") or "")
        app_id = str(claims.get("azp") or claims.get("appid") or "")
        roles = frozenset(role for role in claims.get("roles") or [] if isinstance(role, str))
        has_role = bool(self._settings.required_role) and self._settings.required_role in roles
        if has_role or (object_id and object_id in self._settings.allowed_caller_ids):
            return Caller(object_id, app_id, roles)

        LOGGER.warning(f"[MAP_SERVER_AUTH] Refused a caller without the map server role (caller {object_id or 'unknown'}).")
        raise forbidden("caller_not_allowed", "This caller isn't allowed to use the map server.")
