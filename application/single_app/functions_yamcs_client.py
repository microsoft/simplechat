# functions_yamcs_client.py
"""Invocation-local native Yamcs clients with guarded authentication and transport."""

import itertools
from urllib.parse import unquote, urljoin, urlsplit

from requests.auth import AuthBase

from functions_yamcs_operations import (
    YAMCS_AUTH_METHOD_API_KEY,
    YAMCS_AUTH_METHOD_BEARER_TOKEN,
    YAMCS_AUTH_METHOD_HTTP_BASIC,
    YAMCS_AUTH_METHOD_NONE,
    YAMCS_AUTH_METHOD_USERNAME_PASSWORD,
    YAMCS_SUPPORTED_AUTH_TYPES,
    normalize_yamcs_manifest,
)


class YamcsAuthenticationError(RuntimeError):
    """The provider explicitly rejected a credential, rather than denying a resource."""

    def __init__(self):
        super().__init__("Yamcs rejected the supplied credentials.")


class YamcsPermissionError(RuntimeError):
    """The provider denied access without establishing that a credential is invalid."""

    def __init__(self):
        super().__init__("Your account does not have access to this Yamcs resource.")


class YamcsConnectionError(RuntimeError):
    """A transport, destination-policy, or unexpected provider failure."""

    def __init__(self):
        super().__init__("Unable to connect to the configured Yamcs service.")


def _destination_parts(url, *, allow_query=False):
    """Parse a credential recipient without ambiguous authority or path components."""
    if not isinstance(url, str) or any(ord(character) < 32 or ord(character) == 127 for character in url):
        raise ValueError("Invalid Yamcs destination.")
    try:
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or "#" in url
            or (not allow_query and "?" in url)
            or "\\" in url
        ):
            raise ValueError("Invalid Yamcs destination.")
        port = parts.port or 443
        path = parts.path or "/"
        # Encoded traversal can otherwise escape a gateway's approved service base path.
        for _ in range(4):
            decoded = unquote(path)
            if decoded == path:
                break
            path = decoded
        else:
            raise ValueError("Invalid Yamcs destination.")
        if (
            "\\" in path
            or any(ord(character) < 32 or ord(character) == 127 for character in path)
            or any(segment in {".", ".."} for segment in path.split("/"))
        ):
            raise ValueError("Invalid Yamcs destination.")
        return (parts.scheme, parts.hostname.lower(), port), path.rstrip("/")
    except (TypeError, ValueError):
        raise ValueError("Invalid Yamcs destination.") from None


def validate_yamcs_user_destination(manifest):
    """Validate per-user transport policy without reading an actor or a secret."""
    fields = manifest["additionalFields"]
    if fields["tls_verify"] is not True:
        raise ValueError("Personal Yamcs credentials require HTTPS and certificate verification.")
    _destination_parts(manifest["endpoint"])


class _SDKHeaderAuth(AuthBase):
    """Keep native SDK headers without allowing Requests to select a netrc account."""

    def __call__(self, request):
        return request


class _SessionCredentials:
    """Install per-session protections through the SDK's pre-login credential hook."""

    def __init__(self, credentials, manifest, *, explicit_credentials):
        self._credentials = credentials
        self._session = None
        self._responses = []
        self._closed = False
        self._timeout = manifest["additionalFields"]["timeout"]
        self._strict = "credential_requirement" in manifest
        self._explicit_credentials = explicit_credentials
        self._destination = _destination_parts(manifest["endpoint"]) if self._strict else None

    def _check_url(self, url):
        if not self._strict:
            return
        try:
            origin, path = _destination_parts(url, allow_query=True)
            approved_origin, approved_path = self._destination
            if origin != approved_origin or (
                approved_path and path != approved_path and not path.startswith(f"{approved_path}/")
            ):
                raise ValueError("Unapproved Yamcs destination.")
        except ValueError:
            raise YamcsConnectionError() from None

    def _bounded_timeout(self, timeout):
        if isinstance(timeout, (tuple, list)) and len(timeout) == 2:
            return tuple(self._bounded_timeout(value) for value in timeout)
        if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and timeout > 0:
            return min(timeout, self._timeout)
        return self._timeout

    def login(self, session, auth_url, on_token_update=None):
        self._session = session
        self._check_url(auth_url)
        original_request = session.request
        original_send = session.send
        original_close = session.close
        original_redirects = session.resolve_redirects
        if self._explicit_credentials:
            session.auth = _SDKHeaderAuth()
            session.cookies.clear()
            for header in ("Authorization", "Proxy-Authorization", "x-api-key"):
                session.headers.pop(header, None)

            def rebuild_explicit_auth(prepared_request, response):
                # Redirect rebuilding otherwise checks netrc even when session.auth is set.
                if "Authorization" in prepared_request.headers and session.should_strip_auth(
                    response.request.url, prepared_request.url
                ):
                    del prepared_request.headers["Authorization"]

            session.rebuild_auth = rebuild_explicit_auth
        if self._strict:
            session.verify = True
            session.max_redirects = 3

        def guarded_request(method, url, **kwargs):
            self._check_url(url)
            kwargs["timeout"] = self._bounded_timeout(kwargs.get("timeout"))
            if self._strict:
                kwargs["verify"] = kwargs.get("verify") or True
            return original_request(method, url, **kwargs)

        def guarded_send(request, **kwargs):
            # Requests follows redirects via Session.send(), bypassing Session.request().
            self._check_url(request.url)
            kwargs["timeout"] = self._bounded_timeout(kwargs.get("timeout"))
            if self._strict:
                kwargs["verify"] = kwargs.get("verify") or True
            try:
                response = original_send(request, **kwargs)
                self._responses.append(response)
                if response.status_code == 401:
                    response.close()
                    raise YamcsAuthenticationError()
                if response.status_code == 403:
                    response.close()
                    raise YamcsPermissionError()
                if not 200 <= response.status_code < 400:
                    response.close()
                    raise YamcsConnectionError()
                return response
            except (YamcsAuthenticationError, YamcsPermissionError, YamcsConnectionError):
                raise
            except Exception:
                raise YamcsConnectionError() from None

        def guarded_redirects(response, request, **kwargs):
            if self._strict and response.is_redirect:
                try:
                    target = urljoin(request.url, session.get_redirect_target(response))
                    _destination_parts(target)
                    self._check_url(target)
                except (ValueError, YamcsConnectionError):
                    response.close()
                    raise YamcsConnectionError() from None
            yield from original_redirects(response, request, **kwargs)

        def guarded_close():
            if self._closed:
                return
            self._closed = True
            for response in self._responses:
                try:
                    response.close()
                except Exception:
                    pass
            self._responses.clear()
            for header in ("Authorization", "Proxy-Authorization", "x-api-key"):
                session.headers.pop(header, None)
            session.cookies.clear()
            session.auth = None
            original_close()

        session.request = guarded_request
        session.send = guarded_send
        session.close = guarded_close
        session.resolve_redirects = guarded_redirects
        credentials = self._credentials
        self._credentials = None
        return credentials.login(session, auth_url, on_token_update)

    def close(self):
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
        self._credentials = None


def _build_credentials(manifest, identity_auth):
    # Yamcs is an optional connector dependency; do not import it during action discovery.
    try:
        from yamcs.client import APIKeyCredentials, BasicAuthCredentials, Credentials
    except ImportError:
        raise ImportError("Install yamcs-client to use Yamcs actions.") from None

    method = manifest["additionalFields"]["auth_method"]
    auth = manifest["auth"]
    if auth["type"] not in YAMCS_SUPPORTED_AUTH_TYPES:
        raise ValueError("Invalid Yamcs authentication type.")
    if identity_auth is not None:
        if not isinstance(identity_auth, dict):
            raise ValueError("Invalid Yamcs identity credentials.")
        expected_type = (
            "username_password"
            if method in {YAMCS_AUTH_METHOD_USERNAME_PASSWORD, YAMCS_AUTH_METHOD_HTTP_BASIC}
            else method
        )
        if identity_auth.get("auth_type") != expected_type:
            raise ValueError("The identity is incompatible with the Yamcs authentication profile.")
        username = identity_auth.get("username")
        secret = identity_auth.get("password") if expected_type == "username_password" else identity_auth.get("secret")
    else:
        username = auth.get("identity")
        secret = auth.get("key")
    if method == YAMCS_AUTH_METHOD_NONE:
        return Credentials()
    if not isinstance(secret, str) or not secret:
        raise ValueError("A Yamcs credential is required.")
    if method in {YAMCS_AUTH_METHOD_USERNAME_PASSWORD, YAMCS_AUTH_METHOD_HTTP_BASIC}:
        if not isinstance(username, str) or not username:
            raise ValueError("A Yamcs username is required.")
        if method == YAMCS_AUTH_METHOD_HTTP_BASIC:
            return BasicAuthCredentials(username=username, password=secret)
        return Credentials(username=username, password=secret)
    if method == YAMCS_AUTH_METHOD_BEARER_TOKEN:
        return Credentials(access_token=secret)
    if method == YAMCS_AUTH_METHOD_API_KEY:
        return APIKeyCredentials(secret)
    raise ValueError("Invalid Yamcs authentication method.")


def create_yamcs_client(manifest, *, identity_auth=None):
    """Return a fresh native client; its owner must close it after the invocation."""
    manifest = normalize_yamcs_manifest(manifest)
    if not manifest.get("endpoint"):
        raise ValueError("Yamcs action requires a server URL.")
    if "credential_requirement" in manifest:
        validate_yamcs_user_destination(manifest)
        if identity_auth is None:
            # Resolve only at invocation time; this may raise the private control signal.
            from functions_action_auth import resolve_action_auth_credentials

            identity_auth = resolve_action_auth_credentials(manifest)
            if identity_auth is None:
                raise ValueError("A personal Yamcs credential is required.")
    credentials = _build_credentials(manifest, identity_auth)
    adapter = _SessionCredentials(
        credentials,
        manifest,
        explicit_credentials=manifest["additionalFields"]["auth_method"] != YAMCS_AUTH_METHOD_NONE,
    )
    # Lazy SDK import also keeps pure manifest/factory validation free of network setup.
    try:
        from yamcs.client import YamcsClient
    except ImportError:
        raise ImportError("Install yamcs-client to use Yamcs actions.") from None

    try:
        return YamcsClient(
            manifest["endpoint"],
            credentials=adapter,
            tls_verify=manifest["additionalFields"]["tls_verify"],
            user_agent="SimpleChat",
            keep_alive=False,
        )
    except (YamcsAuthenticationError, YamcsPermissionError, YamcsConnectionError):
        adapter.close()
        raise
    except Exception:
        adapter.close()
        raise YamcsConnectionError() from None


def validate_yamcs_credentials(manifest, identity_auth):
    """Perform bounded read-only discovery with already owner-checked credentials."""
    if not isinstance(identity_auth, dict):
        raise ValueError("A Yamcs identity credential is required.")
    manifest = normalize_yamcs_manifest(manifest)
    fields = manifest["additionalFields"]
    if not fields["instance"]:
        raise ValueError("Yamcs action requires an instance.")
    fields["timeout"] = min(fields["timeout"], 30)
    limit = min(fields["max_rows"], 500)
    client = create_yamcs_client(manifest, identity_auth=identity_auth)
    try:
        client.get_server_info()
        # SDK 2.1's get_time reads /instances/{name}; an unset mission time is valid.
        client.get_time(fields["instance"])
        instances = list(itertools.islice(client.list_instances(), limit + 1))
        visible_instances = instances[:limit]
        return {
            "success": True,
            "message": "Successfully connected to Yamcs.",
            "instance": fields["instance"],
            "instance_count": len(visible_instances),
            "truncated": len(instances) > limit,
        }
    except (YamcsAuthenticationError, YamcsPermissionError, YamcsConnectionError):
        raise
    except Exception:
        raise YamcsConnectionError() from None
    finally:
        try:
            client.close()
        except Exception:
            pass
