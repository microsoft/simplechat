# server_minimal.py
"""Minimal MCP server: device-code OAuth login + SimpleChat integration.

Goals:
- Only what we need: login via device code and access SimpleChat.
- Read config from environment variables (optionally loaded from application/external_apps/mcp/.env when present).
- Verbose, safe logs (never print secrets).

Tools exposed:
- login_via_oauth
- oauth_login_status
- show_user_profile
- list_public_workspaces
- list_personal_documents
- list_personal_prompts
- list_group_workspaces
- list_group_documents
- list_group_prompts
- list_public_documents
- list_public_prompts
- list_conversations
- get_conversation_messages
- send_chat_message
"""

from __future__ import annotations

import json
import os
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Dict, Optional, cast

import requests
from dotenv import load_dotenv
from mcp.server.fastmcp import Context, FastMCP


_DOTENV_PATH = Path(__file__).resolve().parent / ".env"
if _DOTENV_PATH.exists():
    load_dotenv(dotenv_path=_DOTENV_PATH, override=True)


def _require_env_value(name: str) -> str:
    """Return a required setting from environment variables.

    Local development may provide these via application/external_apps/mcp/.env.
    Azure deployments should provide these as App Settings / env vars.
    """
    value = os.getenv(name, "").strip()
    if not value:
        source_hint = f" (loadable from {_DOTENV_PATH} when present)" if _DOTENV_PATH.exists() else ""
        raise ValueError(f"Missing required environment variable {name}{source_hint}")
    return value


def _require_env_int(name: str) -> int:
    raw = _require_env_value(name)
    try:
        return int(raw)
    except Exception as exc:
        raise ValueError(f"Invalid integer for {name}: {raw!r} ({exc})")


def _require_env_bool(name: str) -> bool:
    raw = _require_env_value(name).strip().lower()
    if raw in ["1", "true", "yes", "y", "on"]:
        return True
    if raw in ["0", "false", "no", "n", "off"]:
        return False
    raise ValueError(f"Invalid boolean for {name}: {raw!r} (use true/false)")


DEFAULT_REQUIRE_MCP_AUTH = _require_env_bool("MCP_REQUIRE_AUTH")
DEFAULT_PRM_METADATA_PATH = _require_env_value("MCP_PRM_METADATA_PATH").strip()

MCP_BIND_HOST = _require_env_value("FASTMCP_HOST")
MCP_BIND_PORT = _require_env_int("FASTMCP_PORT")


# Pass host=MCP_BIND_HOST so FastMCP does not auto-enable DNS rebinding
# protection with localhost-only allowed_hosts.  When host is "0.0.0.0"
# (local and Azure), FastMCP skips the restriction — otherwise the Azure
# Container Apps FQDN in the Host header triggers a 421 Misdirected Request.
_mcp = FastMCP("simplechat-mcp-minimal", host=MCP_BIND_HOST, port=MCP_BIND_PORT)

# Session cache: bearer_token -> requests.Session
_SESSION_CACHE: Dict[str, requests.Session] = {}
_SESSION_LOCK = threading.Lock()

# Cache the /external/login payload (contains user + claims) per bearer token.
_LOGIN_PAYLOAD_CACHE: Dict[str, Dict[str, Any]] = {}

# Cache bearer token per MCP streamable-http session id. This lets the server reuse
# the PRM-provided bearer token across tool calls even if the client doesn't resend it.
_MCP_SESSION_TOKEN_CACHE: Dict[str, Dict[str, Any]] = {}
_MCP_SESSION_TOKEN_TTL_SECONDS = _require_env_int("MCP_SESSION_TOKEN_TTL_SECONDS")

_STATE_LOCK = threading.Lock()
_STATE: Dict[str, Any] = {
    "event": None,
    "pending": False,
    "error": None,
    "auth_flow": None,
    "user_code": None,
    "verification_uri": None,
    "verification_uri_complete": None,
    "expires_in": None,
    "interval": None,
    "access_token": None,
    "simplechat_session": None,
    "user_profile": None,
    "token_claims": None,
}


def _env(name: str) -> str:
    """Back-compat helper: required value from environment variables (no defaults)."""
    return _require_env_value(name)


def _extract_bearer_token(auth_header: str) -> Optional[str]:
    """Extract bearer token from Authorization header."""
    if not auth_header:
        return None
    token = auth_header.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token or None


def _get_bearer_token_from_context(ctx: Optional[Context[Any, Any, Any]]) -> Optional[str]:
    """Extract bearer token from the current request Context.

    This is the canonical way tools should access PRM-provided auth.
    """
    if ctx is None:
        return None

    request_context = getattr(ctx, "request_context", None)
    request = getattr(request_context, "request", None) if request_context else None
    headers = getattr(request, "headers", None) if request else None
    if not headers:
        return None

    auth_header = headers.get("authorization")
    return _extract_bearer_token(auth_header or "")


def _get_or_create_simplechat_session(bearer_token: str) -> requests.Session:
    """Get cached session or create new one via SimpleChat /external/login."""
    with _SESSION_LOCK:
        if bearer_token in _SESSION_CACHE:
            print("[MCP] Using cached SimpleChat session for token")
            return _SESSION_CACHE[bearer_token]
    
    simplechat_base_url = _env("SIMPLECHAT_BASE_URL")
    simplechat_verify_ssl = _require_env_bool("SIMPLECHAT_VERIFY_SSL")
    
    print("[MCP] Creating new SimpleChat session via /external/login")
    
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {bearer_token}"})
    
    # Call SimpleChat /external/login to establish session
    login_url = f"{simplechat_base_url}/external/login"
    try:
        response = session.post(login_url, json={}, verify=simplechat_verify_ssl, timeout=30)
        
        if response.status_code != 200:
            try:
                error_details = response.json()
            except Exception:
                error_details = {"raw": response.text}
            raise RuntimeError(f"SimpleChat login failed ({response.status_code}): {error_details}")
        
        print("[MCP] SimpleChat session created successfully")

        try:
            login_payload: Dict[str, Any] = response.json()
        except Exception:
            login_payload = {}
        
        # Cache the session
        with _SESSION_LOCK:
            _SESSION_CACHE[bearer_token] = session
            if login_payload:
                _LOGIN_PAYLOAD_CACHE[bearer_token] = login_payload
        
        return session
        
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to connect to SimpleChat: {e}")


def _get_cached_login_payload(bearer_token: str) -> Optional[Dict[str, Any]]:
    with _SESSION_LOCK:
        payload = _LOGIN_PAYLOAD_CACHE.get(bearer_token)
    return payload if isinstance(payload, dict) else None


def _request_device_code(device_code_url: str, client_id: str, scope: str) -> Dict[str, Any]:
    print(f"[MCP] Requesting device code from {device_code_url}")
    response = requests.post(
        device_code_url,
        data={"client_id": client_id, "scope": scope},
        timeout=30,
    )
    if response.status_code != 200:
        try:
            payload = response.json()
        except Exception:
            payload = {"raw": response.text}
        raise RuntimeError(f"Device code request failed ({response.status_code}): {payload}")
    return response.json()


def _infer_device_code_url(token_url: str) -> str:
    token_url = (token_url or "").strip()
    if token_url.endswith("/oauth2/v2.0/token"):
        return token_url.replace("/oauth2/v2.0/token", "/oauth2/v2.0/devicecode")
    if token_url.endswith("/oauth2/token"):
        return token_url.replace("/oauth2/token", "/oauth2/devicecode")
    raise ValueError(
        "Cannot infer device-code URL from OAUTH_TOKEN_URL; set OAUTH_DEVICE_CODE_URL."
    )


def _poll_device_code_token(
    token_url: str,
    client_id: str,
    client_secret: str,
    device_code: str,
    timeout_seconds: int,
    poll_interval: int,
) -> Dict[str, Any]:
    start = time.time()
    interval = max(1, poll_interval)

    secret_present = bool(client_secret)
    print(
        "[MCP] Starting token polling (PUBLIC CLIENT mode - no secret sent). "
        f"token_url={token_url} client_secret_in_env={secret_present} (not used for device code flow)"
    )

    attempt = 0
    while time.time() - start < timeout_seconds:
        attempt += 1
        data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": client_id,
            "device_code": device_code,
        }
        # NOTE: Device code flow for PUBLIC CLIENTS (like this app) does NOT include client_secret.
        # Only confidential clients use client_secret with device code flow.
        # The AADSTS7000218 error means the app registration is NOT configured as confidential,
        # so we must omit client_secret entirely.

        # Debug: show what we're sending
        has_secret_key = "client_secret" in data
        print(f"[MCP] Token poll attempt #{attempt}: POST data keys={list(data.keys())} has_client_secret_key={has_secret_key} (public client mode)")

        response = requests.post(token_url, data=data, timeout=30)
        print(f"[MCP] Token poll attempt #{attempt}: response status={response.status_code}")

        if response.status_code == 200:
            try:
                return response.json()
            except Exception as exc:
                raise RuntimeError(f"Token response was not JSON: {exc}")

        payload: Dict[str, Any]
        try:
            payload = response.json()
        except Exception:
            payload = {"raw": response.text}

        error = str(payload.get("error", "")).lower()
        if error == "authorization_pending":
            time.sleep(interval)
            continue
        if error == "slow_down":
            interval += 5
            time.sleep(interval)
            continue
        if error == "expired_token":
            raise TimeoutError("Device code expired before login completed.")

        raise RuntimeError(f"Device-code token exchange failed ({response.status_code}): {payload}")

    raise TimeoutError("Device code login did not complete within timeout.")


def _start_background_poll() -> None:
    token_url = _env("OAUTH_TOKEN_URL")
    client_id = _env("OAUTH_CLIENT_ID")
    client_secret = _env("OAUTH_CLIENT_SECRET")
    timeout_seconds = _require_env_int("OAUTH_TIMEOUT_SECONDS")

    with _STATE_LOCK:
        device_code = _STATE.get("device_code")
        interval = int(_STATE.get("interval") or 5)
        event = _STATE.get("event")

    if not device_code or not isinstance(event, threading.Event):
        return

    def _worker() -> None:
        try:
            token_payload = _poll_device_code_token(
                token_url=token_url,
                client_id=client_id,
                client_secret=client_secret,
                device_code=device_code,
                timeout_seconds=timeout_seconds,
                poll_interval=interval,
            )
            access_token = token_payload.get("access_token")
            if not access_token:
                raise RuntimeError(f"Token payload missing access_token: {token_payload}")

            simplechat_base_url = _env("SIMPLECHAT_BASE_URL")
            simplechat_verify_ssl = _require_env_bool("SIMPLECHAT_VERIFY_SSL")
            
            session = requests.Session()
            session.headers.update({"Authorization": f"Bearer {access_token}"})
            
            print(f"[MCP] Creating SimpleChat session at {simplechat_base_url}/external/login")
            print(f"[MCP] Token length: {len(access_token)} chars")
            external_login_response = session.post(
                f"{simplechat_base_url}/external/login",
                verify=simplechat_verify_ssl,
                timeout=30
            )
            
            if external_login_response.status_code != 200:
                print(f"[MCP] SimpleChat /external/login failed: {external_login_response.status_code}")
                print(f"[MCP] Response body: {external_login_response.text}")
                external_login_response.raise_for_status()
            
            external_login_payload = external_login_response.json()
            print(f"[MCP] SimpleChat session created: {external_login_payload.get('session_created')}")

            user_info = external_login_payload.get("user", {})
            all_claims = external_login_payload.get("claims", {})

            with _STATE_LOCK:
                _STATE["access_token"] = access_token
                _STATE["simplechat_session"] = session
                _STATE["user_profile"] = user_info
                _STATE["token_claims"] = all_claims
                _STATE["pending"] = False
                _STATE["error"] = None
            print("[MCP] Device-code token exchange succeeded.")
        except Exception as exc:
            error_msg = str(exc)
            with _STATE_LOCK:
                _STATE["pending"] = False
                _STATE["error"] = error_msg
                # Clear stale auth fields so status returns "none" instead of leaving device_code around
                _STATE["auth_flow"] = None
                _STATE["user_code"] = None
                _STATE["verification_uri"] = None
                _STATE["device_code"] = None
            print(f"[MCP] Device-code login failed: {error_msg}")
        finally:
            event.set()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()


@_mcp.tool(name="login_via_oauth")
def login_via_oauth() -> Dict[str, Any]:
    """Start device-code OAuth login.

    Returns device-code instructions (user_code, verification_uri).
    """
    client_id = _env("OAUTH_CLIENT_ID")
    scope = _env("OAUTH_SCOPES")

    token_url = _env("OAUTH_TOKEN_URL")
    explicit_device_code_url = os.getenv("OAUTH_DEVICE_CODE_URL", "").strip()
    device_code_url = explicit_device_code_url or _infer_device_code_url(token_url)

    device_payload = _request_device_code(device_code_url, client_id, scope)

    device_code = device_payload.get("device_code")
    user_code = device_payload.get("user_code")
    verification_uri = device_payload.get("verification_uri")
    verification_uri_complete = device_payload.get("verification_uri_complete")
    expires_in = device_payload.get("expires_in")
    interval = int(device_payload.get("interval", 5))

    if not device_code or not user_code or not verification_uri:
        raise RuntimeError(f"Device code response missing required fields: {device_payload}")

    # Never auto-open a browser unless explicitly enabled.
    open_browser_raw = os.getenv("OAUTH_OPEN_BROWSER", "false").strip().lower()
    open_browser = open_browser_raw in ["1", "true", "yes", "y", "on"]
    if open_browser:
        try:
            webbrowser.open(verification_uri_complete or verification_uri)
        except Exception as exc:
            print(f"[MCP] webbrowser.open failed: {exc}")

    with _STATE_LOCK:
        event = threading.Event()
        _STATE.update(
            {
                "event": event,
                "pending": True,
                "error": None,
                "auth_flow": "device_code",
                "device_code": device_code,
                "user_code": user_code,
                "verification_uri": verification_uri,
                "verification_uri_complete": verification_uri_complete,
                "expires_in": expires_in,
                "interval": interval,
                "access_token": None,
            }
        )

    _start_background_poll()

    message = (
        f"Go to {verification_uri} and enter this code: {user_code}. "
        "Session will be created automatically after you finish sign-in."
    )
    print(f"[MCP] {message}")

    return {
        "auth_flow": "device_code",
        "user_code": user_code,
        "verification_uri": verification_uri,
        "verification_uri_complete": verification_uri_complete,
        "expires_in": expires_in,
        "interval": interval,
        "message": message,
    }


@_mcp.tool(name="oauth_login_status")
def oauth_login_status(ctx: Optional[Context[Any, Any, Any]] = None) -> Dict[str, Any]:
    """Return current login status.

    This is intentionally not tied to a specific login mechanism.

    - If the call is authenticated via PRM (bearer token), it reports PRM status.
    - If a device-code flow was used, it also reports the device-code status.
    """

    bearer_token = _get_bearer_token_from_context(ctx) if ctx is not None else None
    has_prm_bearer_token = bool(bearer_token)

    simplechat_base_url_present = bool(os.getenv("SIMPLECHAT_BASE_URL", "").strip())
    simplechat_verify_ssl_present = bool(os.getenv("SIMPLECHAT_VERIFY_SSL", "").strip())

    prm_session_ok: Optional[bool] = None
    prm_error: Optional[str] = None
    prm_user: Dict[str, Any] = {}

    if has_prm_bearer_token:
        if simplechat_base_url_present and simplechat_verify_ssl_present:
            try:
                _get_or_create_simplechat_session(cast(str, bearer_token))
                prm_session_ok = True
                payload = _get_cached_login_payload(cast(str, bearer_token)) or {}
                user = payload.get("user")
                if isinstance(user, dict):
                    prm_user = {
                        "userId": user.get("userId"),
                        "displayName": user.get("displayName"),
                        "email": user.get("email"),
                    }
            except Exception as exc:
                prm_session_ok = False
                prm_error = str(exc)
        else:
            prm_session_ok = None
            missing: list[str] = []
            if not simplechat_base_url_present:
                missing.append("SIMPLECHAT_BASE_URL")
            if not simplechat_verify_ssl_present:
                missing.append("SIMPLECHAT_VERIFY_SSL")
            prm_error = f"Cannot validate PRM session; missing env vars: {', '.join(missing)}"

    with _STATE_LOCK:
        pending = bool(_STATE.get("pending"))
        device_code_has_token = bool(_STATE.get("access_token"))
        device_code_error = _STATE.get("error")
        device_code_status = "pending" if pending else ("complete" if device_code_has_token else "none")

        logged_in = (prm_session_ok is True) or device_code_has_token

        result: Dict[str, Any] = {
            "logged_in": logged_in,
            "prm": {
                "has_bearer_token": has_prm_bearer_token,
                "session_ok": prm_session_ok,
                "error": prm_error,
                "user": prm_user,
            },
            "device_code": {
                "status": device_code_status,
                "pending": pending,
                "error": device_code_error,
                "auth_flow": _STATE.get("auth_flow"),
                "user_code": _STATE.get("user_code"),
                "verification_uri": _STATE.get("verification_uri"),
                "verification_uri_complete": _STATE.get("verification_uri_complete"),
                "expires_in": _STATE.get("expires_in"),
                "interval": _STATE.get("interval"),
            },
            "dotenv_path": str(_DOTENV_PATH),
            "dotenv_found": _DOTENV_PATH.exists(),
        }

    return result


@_mcp.tool(name="show_user_profile")
def show_user_profile(ctx: Context[Any, Any, Any]) -> Dict[str, Any]:
    """Return SimpleChat user profile from the PRM bearer token.

    This tool must never initiate its own auth flow. It relies exclusively on
    PRM/MCP client authentication and reuses that bearer token.
    """
    bearer_token = _get_bearer_token_from_context(ctx)
    auth_source = "prm" if bearer_token else "device_code"
    if not bearer_token:
        with _STATE_LOCK:
            access_token = _STATE.get("access_token")
        if isinstance(access_token, str) and access_token.strip():
            bearer_token = access_token.strip()
        else:
            return {
                "success": False,
                "error": "not_authenticated",
                "message": "Not authenticated. Provide a PRM bearer token or complete device-code login.",
            }

    try:
        _get_or_create_simplechat_session(bearer_token)
    except Exception as e:
        return {
            "success": False,
            "error": "session_creation_failed",
            "message": str(e),
        }

    payload = _get_cached_login_payload(bearer_token) or {}
    user = payload.get("user")
    claims = payload.get("claims")

    # If SimpleChat didn't return claims (older deployed version), decode
    # the JWT locally (without signature verification — already validated
    # by SimpleChat during /external/login).
    if not isinstance(claims, dict) or not claims:
        try:
            import jwt as pyjwt
            claims = pyjwt.decode(bearer_token, options={"verify_signature": False})
        except Exception:
            claims = {}

    if not isinstance(user, dict):
        user = {}
    user = cast(Dict[str, Any], user)
    if not isinstance(claims, dict):
        claims = {}
    claims = cast(Dict[str, Any], claims)

    # Extract roles and delegated permissions with clear labels.
    # Collect all roles from both the "roles" claim and the "scp" claim.
    # A user can have multiple roles across both claims.
    roles_from_claim = claims.get("roles", [])
    if not isinstance(roles_from_claim, list):
        roles_from_claim = [roles_from_claim] if roles_from_claim else []
    scp_raw = claims.get("scp", "")
    roles_from_scp = scp_raw.split() if isinstance(scp_raw, str) and scp_raw.strip() else []
    # Merge and deduplicate, preserving order.
    seen = set()
    all_roles = []
    for r in roles_from_claim + roles_from_scp:
        if r not in seen:
            seen.add(r)
            all_roles.append(r)

    return {
        "auth_source": auth_source,
        "userId": user.get("userId"),
        "displayName": user.get("displayName"),
        "email": user.get("email"),
        "upn": claims.get("upn"),
        "roles": all_roles,
        "all_token_claims": claims,
    }


@_mcp.tool(name="list_public_workspaces")
def list_public_workspaces(
    ctx: Context[Any, Any, Any],
    page: int = 1,
    page_size: int = 25,
    search: Optional[str] = None
) -> Dict[str, Any]:
    """Return the authenticated user's public workspaces from SimpleChat.
    
    Uses the bearer token from PRM authentication to create a SimpleChat session.
    """
    bearer_token = _get_bearer_token_from_context(ctx)
    auth_source = "prm" if bearer_token else "device_code"
    if not bearer_token:
        with _STATE_LOCK:
            access_token = _STATE.get("access_token")
        if isinstance(access_token, str) and access_token.strip():
            bearer_token = access_token.strip()
        else:
            return {
                "success": False,
                "error": "not_authenticated",
                "message": "Not authenticated. Provide a PRM bearer token or complete device-code login.",
            }
    
    print(f"[MCP] Using token from {auth_source} authentication")
    try:
        session = _get_or_create_simplechat_session(bearer_token)
    except Exception as e:
        return {
            "success": False,
            "error": "session_creation_failed",
            "message": str(e),
            "hint": "Ensure your bearer token is valid and SimpleChat is accessible.",
        }

    simplechat_base_url = _env("SIMPLECHAT_BASE_URL")
    simplechat_verify_ssl = _require_env_bool("SIMPLECHAT_VERIFY_SSL")

    params: Dict[str, Any] = {
        "page": page,
        "page_size": page_size
    }
    if search:
        params["search"] = search

    url = f"{simplechat_base_url}/api/public_workspaces"
    print(f"[MCP] Calling SimpleChat GET {url}")
    response = session.get(
        url,
        params=params,
        verify=simplechat_verify_ssl,
        timeout=30
    )
    
    if response.status_code != 200:
        try:
            details = response.json()
        except Exception:
            details = {"raw": response.text}
        return {
            "error": "simplechat_request_failed",
            "status_code": response.status_code,
            "details": details,
            "hint": "If this is 401/403, ensure your PRM bearer token has SimpleChat API access.",
        }

    result = response.json()
    if isinstance(result, dict):
        result.setdefault("auth_source", auth_source)
    return result


@_mcp.tool(name="list_personal_documents")
def list_personal_documents(
    ctx: Context[Any, Any, Any],
    page: int = 1,
    page_size: int = 10,
    search: Optional[str] = None,
    classification: Optional[str] = None,
    author: Optional[str] = None,
    keywords: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the authenticated user's personal workspace documents from SimpleChat.

    Lists documents the user has uploaded or that have been shared with them.

    Args:
        page: Page number (default 1).
        page_size: Items per page (default 10).
        search: Search by file name or title (case-insensitive substring match).
        classification: Filter by document classification. Use "none" for unclassified.
        author: Filter by author name (substring match).
        keywords: Filter by keyword (substring match).

    Returns a paginated list of documents with metadata.
    """
    bearer_token = _get_bearer_token_from_context(ctx)
    auth_source = "prm" if bearer_token else "device_code"
    if not bearer_token:
        with _STATE_LOCK:
            access_token = _STATE.get("access_token")
        if isinstance(access_token, str) and access_token.strip():
            bearer_token = access_token.strip()
        else:
            return {
                "success": False,
                "error": "not_authenticated",
                "message": "Not authenticated. Provide a PRM bearer token or complete device-code login.",
            }

    try:
        session = _get_or_create_simplechat_session(bearer_token)
    except Exception as e:
        return {
            "success": False,
            "error": "session_creation_failed",
            "message": str(e),
            "hint": "Ensure your bearer token is valid and SimpleChat is accessible.",
        }

    simplechat_base_url = _env("SIMPLECHAT_BASE_URL")
    simplechat_verify_ssl = _require_env_bool("SIMPLECHAT_VERIFY_SSL")

    params: Dict[str, Any] = {
        "page": page,
        "page_size": page_size,
    }
    if search:
        params["search"] = search
    if classification:
        params["classification"] = classification
    if author:
        params["author"] = author
    if keywords:
        params["keywords"] = keywords

    url = f"{simplechat_base_url}/api/documents"
    print(f"[MCP] Calling SimpleChat GET {url}")
    response = session.get(
        url,
        params=params,
        verify=simplechat_verify_ssl,
        timeout=30,
    )

    if response.status_code != 200:
        try:
            details = response.json()
        except Exception:
            details = {"raw": response.text}
        return {
            "error": "simplechat_request_failed",
            "status_code": response.status_code,
            "details": details,
            "hint": "If this is 401/403, ensure your PRM bearer token has SimpleChat API access.",
        }

    result = response.json()
    if isinstance(result, dict):
        result.setdefault("auth_source", auth_source)
    return result


@_mcp.tool(name="list_personal_prompts")
def list_personal_prompts(
    ctx: Context[Any, Any, Any],
    page: int = 1,
    page_size: int = 10,
    search: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the authenticated user's personal prompts from SimpleChat.

    Lists prompts the user has created in their personal workspace.

    Args:
        page: Page number (default 1).
        page_size: Items per page (default 10).
        search: Search by prompt name (case-insensitive substring match).

    Returns a paginated list of prompts with name, content, and metadata.
    """
    bearer_token = _get_bearer_token_from_context(ctx)
    auth_source = "prm" if bearer_token else "device_code"
    if not bearer_token:
        with _STATE_LOCK:
            access_token = _STATE.get("access_token")
        if isinstance(access_token, str) and access_token.strip():
            bearer_token = access_token.strip()
        else:
            return {
                "success": False,
                "error": "not_authenticated",
                "message": "Not authenticated. Provide a PRM bearer token or complete device-code login.",
            }

    try:
        session = _get_or_create_simplechat_session(bearer_token)
    except Exception as e:
        return {
            "success": False,
            "error": "session_creation_failed",
            "message": str(e),
            "hint": "Ensure your bearer token is valid and SimpleChat is accessible.",
        }

    simplechat_base_url = _env("SIMPLECHAT_BASE_URL")
    simplechat_verify_ssl = _require_env_bool("SIMPLECHAT_VERIFY_SSL")

    params: Dict[str, Any] = {
        "page": page,
        "page_size": page_size,
    }
    if search:
        params["search"] = search

    url = f"{simplechat_base_url}/api/prompts"
    print(f"[MCP] Calling SimpleChat GET {url}")
    response = session.get(
        url,
        params=params,
        verify=simplechat_verify_ssl,
        timeout=30,
    )

    if response.status_code != 200:
        try:
            details = response.json()
        except Exception:
            details = {"raw": response.text}
        return {
            "error": "simplechat_request_failed",
            "status_code": response.status_code,
            "details": details,
            "hint": "If this is 401/403, ensure your PRM bearer token has SimpleChat API access.",
        }

    result = response.json()
    if isinstance(result, dict):
        result.setdefault("auth_source", auth_source)
    return result


@_mcp.tool(name="list_group_workspaces")
def list_group_workspaces(
    ctx: Context[Any, Any, Any],
    page: int = 1,
    page_size: int = 10,
    search: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the authenticated user's group workspaces from SimpleChat.

    Lists groups the user is a member of (Owner, Admin, or Member).

    Args:
        page: Page number (default 1).
        page_size: Items per page (default 10).
        search: Search by group name or description (case-insensitive substring match).

    Returns a paginated list of groups with id, name, description, userRole, status, and isActive flag.
    """
    bearer_token = _get_bearer_token_from_context(ctx)
    auth_source = "prm" if bearer_token else "device_code"
    if not bearer_token:
        with _STATE_LOCK:
            access_token = _STATE.get("access_token")
        if isinstance(access_token, str) and access_token.strip():
            bearer_token = access_token.strip()
        else:
            return {
                "success": False,
                "error": "not_authenticated",
                "message": "Not authenticated. Provide a PRM bearer token or complete device-code login.",
            }

    try:
        session = _get_or_create_simplechat_session(bearer_token)
    except Exception as e:
        return {
            "success": False,
            "error": "session_creation_failed",
            "message": str(e),
            "hint": "Ensure your bearer token is valid and SimpleChat is accessible.",
        }

    simplechat_base_url = _env("SIMPLECHAT_BASE_URL")
    simplechat_verify_ssl = _require_env_bool("SIMPLECHAT_VERIFY_SSL")

    params: Dict[str, Any] = {
        "page": page,
        "page_size": page_size,
    }
    if search:
        params["search"] = search

    url = f"{simplechat_base_url}/api/groups"
    print(f"[MCP] Calling SimpleChat GET {url}")
    response = session.get(
        url,
        params=params,
        verify=simplechat_verify_ssl,
        timeout=30,
    )

    if response.status_code != 200:
        try:
            details = response.json()
        except Exception:
            details = {"raw": response.text}
        return {
            "error": "simplechat_request_failed",
            "status_code": response.status_code,
            "details": details,
            "hint": "If this is 401/403, ensure your PRM bearer token has SimpleChat API access.",
        }

    result = response.json()
    if isinstance(result, dict):
        result.setdefault("auth_source", auth_source)
    return result


@_mcp.tool(name="list_group_documents")
def list_group_documents(
    ctx: Context[Any, Any, Any],
    page: int = 1,
    page_size: int = 10,
    search: Optional[str] = None,
    classification: Optional[str] = None,
    author: Optional[str] = None,
    keywords: Optional[str] = None,
) -> Dict[str, Any]:
    """Return documents from the user's active group workspace in SimpleChat.

    Lists documents uploaded to the currently active group. The active group
    is determined by the user's settings (activeGroupOid).

    Args:
        page: Page number (default 1).
        page_size: Items per page (default 10).
        search: Search by file name or title (case-insensitive substring match).
        classification: Filter by document classification. Use "none" for unclassified.
        author: Filter by author name (substring match).
        keywords: Filter by keyword (substring match).

    Returns a paginated list of group documents with metadata.
    """
    bearer_token = _get_bearer_token_from_context(ctx)
    auth_source = "prm" if bearer_token else "device_code"
    if not bearer_token:
        with _STATE_LOCK:
            access_token = _STATE.get("access_token")
        if isinstance(access_token, str) and access_token.strip():
            bearer_token = access_token.strip()
        else:
            return {
                "success": False,
                "error": "not_authenticated",
                "message": "Not authenticated. Provide a PRM bearer token or complete device-code login.",
            }

    try:
        session = _get_or_create_simplechat_session(bearer_token)
    except Exception as e:
        return {
            "success": False,
            "error": "session_creation_failed",
            "message": str(e),
            "hint": "Ensure your bearer token is valid and SimpleChat is accessible.",
        }

    simplechat_base_url = _env("SIMPLECHAT_BASE_URL")
    simplechat_verify_ssl = _require_env_bool("SIMPLECHAT_VERIFY_SSL")

    params: Dict[str, Any] = {
        "page": page,
        "page_size": page_size,
    }
    if search:
        params["search"] = search
    if classification:
        params["classification"] = classification
    if author:
        params["author"] = author
    if keywords:
        params["keywords"] = keywords

    url = f"{simplechat_base_url}/api/group_documents"
    print(f"[MCP] Calling SimpleChat GET {url}")
    response = session.get(
        url,
        params=params,
        verify=simplechat_verify_ssl,
        timeout=30,
    )

    if response.status_code != 200:
        try:
            details = response.json()
        except Exception:
            details = {"raw": response.text}
        return {
            "error": "simplechat_request_failed",
            "status_code": response.status_code,
            "details": details,
            "hint": "If this is 401/403, ensure your PRM bearer token has SimpleChat API access. If 400, ensure you have an active group selected.",
        }

    result = response.json()
    if isinstance(result, dict):
        result.setdefault("auth_source", auth_source)
    return result


@_mcp.tool(name="list_group_prompts")
def list_group_prompts(
    ctx: Context[Any, Any, Any],
    page: int = 1,
    page_size: int = 10,
    search: Optional[str] = None,
) -> Dict[str, Any]:
    """Return prompts from the user's active group workspace in SimpleChat.

    Lists prompts created in the currently active group. The active group
    is determined by the user's settings (activeGroupOid).

    Args:
        page: Page number (default 1).
        page_size: Items per page (default 10).
        search: Search by prompt name (case-insensitive substring match).

    Returns a paginated list of group prompts with name, content, and metadata.
    """
    bearer_token = _get_bearer_token_from_context(ctx)
    auth_source = "prm" if bearer_token else "device_code"
    if not bearer_token:
        with _STATE_LOCK:
            access_token = _STATE.get("access_token")
        if isinstance(access_token, str) and access_token.strip():
            bearer_token = access_token.strip()
        else:
            return {
                "success": False,
                "error": "not_authenticated",
                "message": "Not authenticated. Provide a PRM bearer token or complete device-code login.",
            }

    try:
        session = _get_or_create_simplechat_session(bearer_token)
    except Exception as e:
        return {
            "success": False,
            "error": "session_creation_failed",
            "message": str(e),
            "hint": "Ensure your bearer token is valid and SimpleChat is accessible.",
        }

    simplechat_base_url = _env("SIMPLECHAT_BASE_URL")
    simplechat_verify_ssl = _require_env_bool("SIMPLECHAT_VERIFY_SSL")

    params: Dict[str, Any] = {
        "page": page,
        "page_size": page_size,
    }
    if search:
        params["search"] = search

    url = f"{simplechat_base_url}/api/group_prompts"
    print(f"[MCP] Calling SimpleChat GET {url}")
    response = session.get(
        url,
        params=params,
        verify=simplechat_verify_ssl,
        timeout=30,
    )

    if response.status_code != 200:
        try:
            details = response.json()
        except Exception:
            details = {"raw": response.text}
        return {
            "error": "simplechat_request_failed",
            "status_code": response.status_code,
            "details": details,
            "hint": "If this is 401/403, ensure your PRM bearer token has SimpleChat API access. If 400, ensure you have an active group selected.",
        }

    result = response.json()
    if isinstance(result, dict):
        result.setdefault("auth_source", auth_source)
    return result


@_mcp.tool(name="list_public_documents")
def list_public_documents(
    ctx: Context[Any, Any, Any],
    page: int = 1,
    page_size: int = 10,
    search: Optional[str] = None,
) -> Dict[str, Any]:
    """Return documents from the user's active public workspace in SimpleChat.

    Lists documents uploaded to the currently active public workspace. The active
    workspace is determined by the user's settings (activePublicWorkspaceOid).

    Args:
        page: Page number (default 1).
        page_size: Items per page (default 10).
        search: Search by file name or title (case-insensitive substring match).

    Returns a paginated list of public workspace documents with metadata.
    """
    bearer_token = _get_bearer_token_from_context(ctx)
    auth_source = "prm" if bearer_token else "device_code"
    if not bearer_token:
        with _STATE_LOCK:
            access_token = _STATE.get("access_token")
        if isinstance(access_token, str) and access_token.strip():
            bearer_token = access_token.strip()
        else:
            return {
                "success": False,
                "error": "not_authenticated",
                "message": "Not authenticated. Provide a PRM bearer token or complete device-code login.",
            }

    try:
        session = _get_or_create_simplechat_session(bearer_token)
    except Exception as e:
        return {
            "success": False,
            "error": "session_creation_failed",
            "message": str(e),
            "hint": "Ensure your bearer token is valid and SimpleChat is accessible.",
        }

    simplechat_base_url = _env("SIMPLECHAT_BASE_URL")
    simplechat_verify_ssl = _require_env_bool("SIMPLECHAT_VERIFY_SSL")

    params: Dict[str, Any] = {
        "page": page,
        "page_size": page_size,
    }
    if search:
        params["search"] = search

    url = f"{simplechat_base_url}/api/public_documents"
    print(f"[MCP] Calling SimpleChat GET {url}")
    response = session.get(
        url,
        params=params,
        verify=simplechat_verify_ssl,
        timeout=30,
    )

    if response.status_code != 200:
        try:
            details = response.json()
        except Exception:
            details = {"raw": response.text}
        return {
            "error": "simplechat_request_failed",
            "status_code": response.status_code,
            "details": details,
            "hint": "If this is 401/403, ensure your PRM bearer token has SimpleChat API access. If 400, ensure you have an active public workspace selected.",
        }

    result = response.json()
    if isinstance(result, dict):
        result.setdefault("auth_source", auth_source)
    return result


@_mcp.tool(name="list_public_prompts")
def list_public_prompts(
    ctx: Context[Any, Any, Any],
    page: int = 1,
    page_size: int = 10,
    search: Optional[str] = None,
) -> Dict[str, Any]:
    """Return prompts from the user's active public workspace in SimpleChat.

    Lists prompts created in the currently active public workspace. The active
    workspace is determined by the user's settings (activePublicWorkspaceOid).

    Args:
        page: Page number (default 1).
        page_size: Items per page (default 10).
        search: Search by prompt name (case-insensitive substring match).

    Returns a paginated list of public workspace prompts with name, content, and metadata.
    """
    bearer_token = _get_bearer_token_from_context(ctx)
    auth_source = "prm" if bearer_token else "device_code"
    if not bearer_token:
        with _STATE_LOCK:
            access_token = _STATE.get("access_token")
        if isinstance(access_token, str) and access_token.strip():
            bearer_token = access_token.strip()
        else:
            return {
                "success": False,
                "error": "not_authenticated",
                "message": "Not authenticated. Provide a PRM bearer token or complete device-code login.",
            }

    try:
        session = _get_or_create_simplechat_session(bearer_token)
    except Exception as e:
        return {
            "success": False,
            "error": "session_creation_failed",
            "message": str(e),
            "hint": "Ensure your bearer token is valid and SimpleChat is accessible.",
        }

    simplechat_base_url = _env("SIMPLECHAT_BASE_URL")
    simplechat_verify_ssl = _require_env_bool("SIMPLECHAT_VERIFY_SSL")

    params: Dict[str, Any] = {
        "page": page,
        "page_size": page_size,
    }
    if search:
        params["search"] = search

    url = f"{simplechat_base_url}/api/public_prompts"
    print(f"[MCP] Calling SimpleChat GET {url}")
    response = session.get(
        url,
        params=params,
        verify=simplechat_verify_ssl,
        timeout=30,
    )

    if response.status_code != 200:
        try:
            details = response.json()
        except Exception:
            details = {"raw": response.text}
        return {
            "error": "simplechat_request_failed",
            "status_code": response.status_code,
            "details": details,
            "hint": "If this is 401/403, ensure your PRM bearer token has SimpleChat API access. If 400, ensure you have an active public workspace selected.",
        }

    result = response.json()
    if isinstance(result, dict):
        result.setdefault("auth_source", auth_source)
    return result


@_mcp.tool(name="list_conversations")
def list_conversations(
    ctx: Context[Any, Any, Any],
) -> Dict[str, Any]:
    """Return the authenticated user's conversations (chats) from SimpleChat.

    Returns a list of all conversations including id, title, last_updated,
    tags, classification, and pinned/hidden status.
    """
    bearer_token = _get_bearer_token_from_context(ctx)
    auth_source = "prm" if bearer_token else "device_code"
    if not bearer_token:
        with _STATE_LOCK:
            access_token = _STATE.get("access_token")
        if isinstance(access_token, str) and access_token.strip():
            bearer_token = access_token.strip()
        else:
            return {
                "success": False,
                "error": "not_authenticated",
                "message": "Not authenticated. Provide a PRM bearer token or complete device-code login.",
            }

    try:
        session = _get_or_create_simplechat_session(bearer_token)
    except Exception as e:
        return {
            "success": False,
            "error": "session_creation_failed",
            "message": str(e),
            "hint": "Ensure your bearer token is valid and SimpleChat is accessible.",
        }

    simplechat_base_url = _env("SIMPLECHAT_BASE_URL")
    simplechat_verify_ssl = _require_env_bool("SIMPLECHAT_VERIFY_SSL")

    url = f"{simplechat_base_url}/api/get_conversations"
    print(f"[MCP] Calling SimpleChat GET {url}")
    response = session.get(url, verify=simplechat_verify_ssl, timeout=30)

    if response.status_code != 200:
        try:
            details = response.json()
        except Exception:
            details = {"raw": response.text}
        return {
            "error": "simplechat_request_failed",
            "status_code": response.status_code,
            "details": details,
            "hint": "If this is 401/403, ensure your PRM bearer token has SimpleChat API access.",
        }

    result = response.json()
    if isinstance(result, dict):
        result.setdefault("auth_source", auth_source)
    return result


@_mcp.tool(name="get_conversation_messages")
def get_conversation_messages(
    ctx: Context[Any, Any, Any],
    conversation_id: str = "",
) -> Dict[str, Any]:
    """Return messages for a specific conversation from SimpleChat.

    Args:
        conversation_id: The UUID of the conversation to retrieve messages from.

    Returns a list of messages with role, content, timestamp, and metadata.
    """
    if not conversation_id or not conversation_id.strip():
        return {
            "success": False,
            "error": "missing_parameter",
            "message": "conversation_id is required.",
        }

    bearer_token = _get_bearer_token_from_context(ctx)
    auth_source = "prm" if bearer_token else "device_code"
    if not bearer_token:
        with _STATE_LOCK:
            access_token = _STATE.get("access_token")
        if isinstance(access_token, str) and access_token.strip():
            bearer_token = access_token.strip()
        else:
            return {
                "success": False,
                "error": "not_authenticated",
                "message": "Not authenticated. Provide a PRM bearer token or complete device-code login.",
            }

    try:
        session = _get_or_create_simplechat_session(bearer_token)
    except Exception as e:
        return {
            "success": False,
            "error": "session_creation_failed",
            "message": str(e),
            "hint": "Ensure your bearer token is valid and SimpleChat is accessible.",
        }

    simplechat_base_url = _env("SIMPLECHAT_BASE_URL")
    simplechat_verify_ssl = _require_env_bool("SIMPLECHAT_VERIFY_SSL")

    url = f"{simplechat_base_url}/api/get_messages"
    print(f"[MCP] Calling SimpleChat GET {url}?conversation_id={conversation_id}")
    response = session.get(
        url,
        params={"conversation_id": conversation_id.strip()},
        verify=simplechat_verify_ssl,
        timeout=30,
    )

    if response.status_code != 200:
        try:
            details = response.json()
        except Exception:
            details = {"raw": response.text}
        return {
            "error": "simplechat_request_failed",
            "status_code": response.status_code,
            "details": details,
            "hint": "Verify the conversation_id is correct and belongs to your user.",
        }

    result = response.json()
    if isinstance(result, dict):
        result.setdefault("auth_source", auth_source)
        result.setdefault("conversation_id", conversation_id.strip())
    return result


@_mcp.tool(name="send_chat_message")
def send_chat_message(
    ctx: Context[Any, Any, Any],
    conversation_id: str = "",
    message: str = "",
) -> Dict[str, Any]:
    """Send a chat message to a SimpleChat conversation and return the AI response.

    Args:
        conversation_id: The UUID of the conversation to send the message to.
            If empty, a new conversation will be created automatically by SimpleChat.
        message: The text message to send.

    Returns the AI reply, conversation_id, title, model info, and citations.
    """
    if not message or not message.strip():
        return {
            "success": False,
            "error": "missing_parameter",
            "message": "message is required.",
        }

    bearer_token = _get_bearer_token_from_context(ctx)
    auth_source = "prm" if bearer_token else "device_code"
    if not bearer_token:
        with _STATE_LOCK:
            access_token = _STATE.get("access_token")
        if isinstance(access_token, str) and access_token.strip():
            bearer_token = access_token.strip()
        else:
            return {
                "success": False,
                "error": "not_authenticated",
                "message": "Not authenticated. Provide a PRM bearer token or complete device-code login.",
            }

    try:
        session = _get_or_create_simplechat_session(bearer_token)
    except Exception as e:
        return {
            "success": False,
            "error": "session_creation_failed",
            "message": str(e),
            "hint": "Ensure your bearer token is valid and SimpleChat is accessible.",
        }

    simplechat_base_url = _env("SIMPLECHAT_BASE_URL")
    simplechat_verify_ssl = _require_env_bool("SIMPLECHAT_VERIFY_SSL")

    payload: Dict[str, Any] = {
        "message": message.strip(),
    }
    if conversation_id and conversation_id.strip():
        payload["conversation_id"] = conversation_id.strip()

    url = f"{simplechat_base_url}/api/chat"
    print(f"[MCP] Calling SimpleChat POST {url}")
    response = session.post(
        url,
        json=payload,
        verify=simplechat_verify_ssl,
        timeout=120,
    )

    if response.status_code != 200:
        try:
            details = response.json()
        except Exception:
            details = {"raw": response.text}
        return {
            "error": "simplechat_request_failed",
            "status_code": response.status_code,
            "details": details,
            "hint": "Check that the conversation_id is valid and SimpleChat is configured with an AI model.",
        }

    result = response.json()
    if isinstance(result, dict):
        result.setdefault("auth_source", auth_source)
    return result


class _PrmAndAuthShim:
    """ASGI middleware that serves PRM metadata and enforces authentication."""
    
    def __init__(self, app: Any, streamable_path: str, require_auth: bool, prm_metadata_path: str) -> None:
        self._app = app
        self._streamable_path = streamable_path
        self._require_auth = require_auth
        self._prm_metadata_path = prm_metadata_path

        # Validate PRM metadata at startup (no fallbacks/defaults).
        _ = self._load_prm_metadata()
    
    def _load_prm_metadata(self) -> Dict[str, Any]:
        candidate_path = Path(self._prm_metadata_path)
        if not candidate_path.is_absolute():
            candidate_path = Path(__file__).resolve().parent / candidate_path
        
        if not candidate_path.exists():
            raise ValueError(f"PRM metadata file not found at {candidate_path}")
        
        with candidate_path.open("r", encoding="utf-8") as handle:
            data: Any = json.load(handle)

        if isinstance(data, dict):
            return cast(Dict[str, Any], data)
        raise ValueError(f"PRM metadata at {candidate_path} must be a JSON object")
    
    @staticmethod
    def _get_request_origin(scope: Dict[str, Any]) -> str:
        headers_list = list(scope.get("headers", []))

        # Behind a reverse proxy (e.g. Azure Container Apps), TLS is terminated
        # at the ingress and the ASGI scope["scheme"] is always "http".
        # Check X-Forwarded-Proto first, then FASTMCP_SCHEME, then scope.
        forwarded_proto_values = [
            value for (key, value) in headers_list
            if (key or b"").lower() == b"x-forwarded-proto"
        ]
        forwarded_proto = (
            b"".join(forwarded_proto_values).decode("utf-8", errors="ignore").strip()
            if forwarded_proto_values else ""
        )

        if forwarded_proto:
            scheme = forwarded_proto
        else:
            scheme = str(scope.get("scheme") or "").strip()
            if not scheme:
                scheme = _require_env_value("FASTMCP_SCHEME")

        host_values = [value for (key, value) in headers_list if (key or b"").lower() == b"host"]
        host = b"".join(host_values).decode("utf-8", errors="ignore").strip()
        if not host:
            host = f"{MCP_BIND_HOST}:{MCP_BIND_PORT}"
        return f"{scheme}://{host}"
    
    async def _send_json(self, send: Any, status: int, payload: Dict[str, Any], headers: Optional[list[tuple[bytes, bytes]]] = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        response_headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"cache-control", b"no-store"),
        ]
        if headers:
            response_headers.extend(headers)
        
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": response_headers,
        })
        await send({
            "type": "http.response.body",
            "body": body,
        })
    
    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        
        path = scope.get("path") or ""
        method = scope.get("method") or ""
        
        origin = self._get_request_origin(scope)
        prm_url = f"{origin}/.well-known/oauth-protected-resource"
        streamable_path = (self._streamable_path or "").rstrip("/")
        normalized_path = path.rstrip("/")
        
        # Serve PRM metadata
        if method == "GET" and path == "/.well-known/oauth-protected-resource":
            prm = self._load_prm_metadata()
            prm["resource"] = f"{origin}{streamable_path}"
            await self._send_json(send, 200, prm)
            return

        # Enforce authentication for MCP endpoints (this is what triggers PRM handshake).
        is_mcp_path = normalized_path == streamable_path or path.startswith(streamable_path + "/")
        if self._require_auth and is_mcp_path:
            headers_list = list(scope.get("headers", []))

            # 1) Try Authorization header
            auth_values = [value for (key, value) in headers_list if (key or b"").lower() == b"authorization"]
            auth_header_bytes = b"".join(auth_values).strip()
            auth_header = auth_header_bytes.decode("utf-8", errors="ignore") if auth_header_bytes else ""
            bearer_token = _extract_bearer_token(auth_header)

            # 2) If missing, try cached token via MCP session id header
            session_id_values = [value for (key, value) in headers_list if (key or b"").lower() == b"mcp-session-id"]
            mcp_session_id = b"".join(session_id_values).decode("utf-8", errors="ignore").strip() if session_id_values else ""

            if not bearer_token and mcp_session_id:
                with _SESSION_LOCK:
                    cached = _MCP_SESSION_TOKEN_CACHE.get(mcp_session_id)
                if isinstance(cached, dict):
                    cached_token = cached.get("bearer_token")
                    expires_at = cached.get("expires_at")
                    if isinstance(expires_at, (int, float)) and expires_at < time.time():
                        with _SESSION_LOCK:
                            _MCP_SESSION_TOKEN_CACHE.pop(mcp_session_id, None)
                    elif isinstance(cached_token, str) and cached_token.strip():
                        bearer_token = cached_token.strip()
                        # Inject Authorization header into scope so tools can read it via Context
                        scope_headers = list(scope.get("headers", []))
                        scope_headers.append((b"authorization", f"Bearer {bearer_token}".encode("utf-8")))
                        scope["headers"] = scope_headers

            has_token = bool(bearer_token)
            print(
                f"[MCP PRM] {method} {path} - has_bearer_token={has_token} has_mcp_session_id={bool(mcp_session_id)}"
            )

            if not has_token:
                link_target = f'<{prm_url}>; rel="oauth-protected-resource"'.encode("utf-8")
                # Keep this header minimal and PRM-focused so clients can discover metadata and reuse auth silently.
                scope_hint = ""
                try:
                    prm = self._load_prm_metadata()
                    scopes = prm.get("scopes_supported")
                    if isinstance(scopes, list) and scopes and isinstance(scopes[0], str) and scopes[0].strip():
                        scope_hint = scopes[0].strip()
                except Exception:
                    scope_hint = ""

                if scope_hint:
                    www_auth = f'Bearer resource_metadata="{prm_url}", scope="{scope_hint}"'.encode("utf-8")
                else:
                    www_auth = f'Bearer resource_metadata="{prm_url}"'.encode("utf-8")
                await self._send_json(
                    send,
                    401,
                    {
                        "error": "unauthorized",
                        "message": "Authorization required to use this MCP server.",
                        "hint": "Complete PRM auth in the client; the server will cache the token after the first authenticated request.",
                    },
                    headers=[
                        (b"www-authenticate", www_auth),
                        (b"link", link_target),
                    ],
                )
                return

            # If we have a bearer token, capture the MCP session id from either the request
            # (mcp-session-id header) or the response (base transport may assign it).
            if bearer_token:
                if mcp_session_id:
                    with _SESSION_LOCK:
                        _MCP_SESSION_TOKEN_CACHE[mcp_session_id] = {
                            "bearer_token": bearer_token,
                            "expires_at": time.time() + _MCP_SESSION_TOKEN_TTL_SECONDS,
                        }

                async def send_capture_session_id(message: Dict[str, Any]) -> None:
                    if message.get("type") == "http.response.start":
                        resp_headers = list(message.get("headers", []))
                        resp_session_values = [
                            value
                            for (key, value) in resp_headers
                            if (key or b"").lower() == b"mcp-session-id"
                        ]
                        resp_session_id = (
                            b"".join(resp_session_values).decode("utf-8", errors="ignore").strip()
                            if resp_session_values
                            else ""
                        )
                        if resp_session_id:
                            with _SESSION_LOCK:
                                _MCP_SESSION_TOKEN_CACHE[resp_session_id] = {
                                    "bearer_token": bearer_token,
                                    "expires_at": time.time() + _MCP_SESSION_TOKEN_TTL_SECONDS,
                                }
                    await send(message)

                await self._app(scope, receive, send_capture_session_id)
                return
        
        await self._app(scope, receive, send)


if __name__ == "__main__":
    print(f"[MCP] Starting server with MCP_REQUIRE_AUTH={DEFAULT_REQUIRE_MCP_AUTH}")
    print(f"[MCP] PRM metadata path: {DEFAULT_PRM_METADATA_PATH}")

    import uvicorn

    base_app = _mcp.streamable_http_app()

    # Streamable HTTP transport is required for MCP Inspector.
    if DEFAULT_REQUIRE_MCP_AUTH:
        app_to_run: Any = _PrmAndAuthShim(
            app=base_app,
            streamable_path="/mcp",
            require_auth=DEFAULT_REQUIRE_MCP_AUTH,
            prm_metadata_path=DEFAULT_PRM_METADATA_PATH,
        )
        print(f"[MCP] Server starting on {MCP_BIND_HOST}:{MCP_BIND_PORT}/mcp (with PRM authentication)")
    else:
        app_to_run = base_app
        print(f"[MCP] Server starting on {MCP_BIND_HOST}:{MCP_BIND_PORT}/mcp (no authentication)")

    uvicorn.run(app_to_run, host=MCP_BIND_HOST, port=MCP_BIND_PORT, log_level="info")
