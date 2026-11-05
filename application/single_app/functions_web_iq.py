# functions_web_iq.py
"""Web IQ retrieval and policy contracts, independent of application bootstrap."""

from datetime import datetime, timezone
import ipaddress
import json
import os
import re
import time
from urllib.parse import urlsplit

import requests
from azure.core.exceptions import AzureError
from azure.identity import ClientSecretCredential


WEB_IQ_ENDPOINT = "https://api.microsoft.ai/v3"
RESULT_TYPES = ("web", "news", "image", "video")
MEDIA_MODES = ("off", "text_only", "with_media")
RESULT_LIMITS = {"web": 50, "news": 20, "image": 30, "video": 30}
RESULT_FIELDS = {"web": "webResults", "news": "newsResults", "image": "imageResults", "video": "videoResults"}
RESULT_PATHS = {"web": "web", "news": "news", "image": "images", "video": "videos"}


class WebIQError(ValueError):
    """Stable, client-safe retrieval failure."""

    def __init__(self, code, *, provider_status=None):
        self.code = code
        self.provider_status = provider_status
        super().__init__(f"Web IQ is unavailable ({code}).")


def get_web_search_provider(settings):
    provider = settings.get("web_search_provider", "foundry")
    if provider not in ("foundry", "web_iq"):
        raise WebIQError("invalid_provider")
    return provider


def _bounded_integer(value, minimum, maximum, name):
    if isinstance(value, bool):
        raise WebIQError(f"invalid_{name}")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise WebIQError(f"invalid_{name}") from None
    if str(number) != str(value) or not minimum <= number <= maximum:
        raise WebIQError(f"invalid_{name}")
    return number


def get_web_iq_config(settings):
    raw = settings.get("web_iq", {})
    if not isinstance(raw, dict):
        raise WebIQError("invalid_configuration")
    config = {
        "endpoint": raw.get("endpoint", WEB_IQ_ENDPOINT),
        "authentication_type": raw.get("authentication_type", "key"),
        "key": raw.get("key", ""),
        "tenant_id": raw.get("tenant_id", ""),
        "client_id": raw.get("client_id", ""),
        "client_secret": raw.get("client_secret", ""),
        "app_id": raw.get("app_id", ""),
        "language": raw.get("language", "en"),
        "region": raw.get("region", "US"),
        "max_results": _bounded_integer(raw.get("max_results", 10), 1, 50, "max_results"),
        "max_length": _bounded_integer(raw.get("max_length", 3000), 1, 3000, "max_length"),
    }
    # Credentials are never sent to an administrator-supplied host or redirect.
    if config["endpoint"] != WEB_IQ_ENDPOINT:
        raise WebIQError("invalid_endpoint")
    if config["authentication_type"] not in ("key", "service_principal"):
        raise WebIQError("invalid_authentication")
    for name in ("language", "region"):
        value = config[name]
        if not isinstance(value, str) or len(value) != 2 or not value.isascii() or not value.isalpha():
            raise WebIQError(f"invalid_{name}")
    for name in ("key", "tenant_id", "client_id", "client_secret", "app_id"):
        if not isinstance(config[name], str):
            raise WebIQError("invalid_configuration")
        config[name] = config[name].strip()
    return config


def web_iq_policy(settings):
    modes = {}
    for kind in ("image", "video"):
        mode = settings.get(f"web_iq_{kind}_mode", "off")
        if mode not in MEDIA_MODES:
            raise WebIQError("invalid_media_policy")
        modes[kind] = mode
    news = settings.get("web_iq_news_enabled", False)
    if not isinstance(news, bool):
        raise WebIQError("invalid_news_policy")
    return {"news": news, **modes}


def available_web_iq_types(settings):
    policy = web_iq_policy(settings)
    return ["web"] + (["news"] if policy["news"] else []) + [
        kind for kind in ("image", "video") if policy[kind] != "off"
    ]


def resolve_web_iq_types(settings, result_types=None):
    selected = ["web"] if result_types is None else result_types
    if not isinstance(selected, list) or not selected or len(selected) > 4:
        raise WebIQError("invalid_result_types")
    if any(not isinstance(kind, str) or kind not in RESULT_TYPES for kind in selected):
        raise WebIQError("invalid_result_types")
    if len(set(selected)) != len(selected):
        raise WebIQError("invalid_result_types")
    if any(kind not in available_web_iq_types(settings) for kind in selected):
        raise WebIQError("result_type_disabled")
    return list(selected)


def select_manual_web_iq_types(settings, query):
    """Only explicit current-message discovery intent adds authorized endpoints."""
    selected = ["web"]
    text = str(query or "")
    patterns = {
        "news": r"\b(news|headlines|announcements)\b",
        "image": r"\b(images?|photos?|pictures?|visual examples)\b",
        "video": r"\b(videos?|video tutorials?)\b",
    }
    allowed = available_web_iq_types(settings)
    for kind, pattern in patterns.items():
        intent = re.search(pattern, text, re.IGNORECASE)
        negative = re.search(
            r"\b(no|without|exclude|avoid|do not|don't)\b.{0,30}" + pattern,
            text, re.IGNORECASE,
        )
        discovery = kind == "news" or re.search(
            r"\b(find|show|search|look for|locate|give|provide|discover)\b.{0,80}" + pattern,
            text, re.IGNORECASE,
        )
        if kind in allowed and intent and discovery and not negative:
            selected.append(kind)
    return selected


def resolve_web_iq_credentials(settings):
    """Resolve only this connection's global references, never transmit reference names."""
    config = get_web_iq_config(settings)
    active_field = "key" if config["authentication_type"] == "key" else "client_secret"
    for field in (active_field,):
        value = config[field]
        if value in ("Stored_In_KeyVault", "********", "***REDACTED***"):
            raise WebIQError("credential_unavailable")
        if not re.fullmatch(r"[A-Za-z0-9-]+--[A-Za-z-]+--[A-Za-z]+--[A-Za-z0-9-]+", value):
            continue
        # Key Vault depends on initialized settings; import only at invocation/current-source reads.
        from functions_keyvault import (
            retrieve_secret_from_key_vault_by_full_name, secret_reference_matches_context,
        )

        if not secret_reference_matches_context(
            value, scope_value="web-iq", scope="global", allowed_sources={"model-endpoint"},
        ):
            raise WebIQError("credential_scope_mismatch")
        try:
            config[field] = retrieve_secret_from_key_vault_by_full_name(value, strict=True)
        except (ValueError, AzureError):
            raise WebIQError("credential_unavailable") from None
        if not isinstance(config[field], str) or not config[field].strip() or config[field] == value:
            raise WebIQError("credential_unavailable")
    return config


def web_iq_configuration_snapshot(settings, *, resolved_config=None):
    """Private configuration proof: the owning capture layer HMACs credentials."""
    raw = get_web_iq_config(settings)
    config = resolved_config if resolved_config is not None else resolve_web_iq_credentials(settings)
    return {"provider": get_web_search_provider(settings), "connection": config,
            "credential_references": {name: raw[name] for name in ("key", "client_secret")
                                      if raw[name] != config[name]},
            "policy": web_iq_policy(settings), "consent": settings.get("web_iq_consent_accepted", False),
            "enabled": settings.get("enable_web_search", False),
            "cloud": settings.get("azure_environment", os.getenv("AZURE_ENVIRONMENT", "public"))}


def validate_web_iq_ready(settings):
    config = get_web_iq_config(settings)
    cloud = settings.get("azure_environment", os.getenv("AZURE_ENVIRONMENT", "public"))
    if not isinstance(cloud, str) or cloud.lower() not in ("public", "azurecloud"):
        raise WebIQError("unsupported_cloud")
    if settings.get("enable_web_search") is not True or settings.get("web_iq_consent_accepted") is not True:
        raise WebIQError("consent_required")
    required = ("key",) if config["authentication_type"] == "key" else (
        "tenant_id", "client_id", "client_secret", "app_id",
    )
    if any(not config[name] for name in required):
        raise WebIQError("not_configured")
    resolve_web_iq_types(settings)
    return config


def _safe_url(value):
    if not isinstance(value, str) or len(value) > 8192 or "\\" in value:
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if any(ord(char) < 32 for char in value):
        return None
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        return None
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        return None
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        return None
    if port is not None and not 1 <= port <= 65535:
        return None
    return value


def _text(value, limit=3000):
    return value[:limit] if isinstance(value, str) else ""


def normalize_web_iq_response(payload, kind, *, mode="text_only", max_results=10, max_length=3000):
    if not isinstance(payload, dict) or not isinstance(payload.get(RESULT_FIELDS[kind]), list):
        raise WebIQError("invalid_response")
    citations = []
    seen = set()
    for item in payload[RESULT_FIELDS[kind]][:max_results]:
        if not isinstance(item, dict):
            raise WebIQError("invalid_response")
        url = _safe_url(item.get("hostPageUrl") if kind == "image" else item.get("url"))
        if not url or url in seen or item.get("isAdult") is True:
            continue
        seen.add(url)
        description = item.get("content") if kind in ("web", "news") else (
            item.get("caption") if kind == "image" else item.get("summary") or item.get("description")
        )
        citation = {
            "url": url, "title": _text(item.get("title"), 500) or url,
            "description": _text(description, max_length), "provider": "web_iq",
            "source": "web_iq", "source_kind": kind,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
        for source, target in (("lastUpdatedAt", "last_updated_at"), ("crawledAt", "crawled_at"),
                               ("language", "language"), ("source", "publisher"), ("publishedBy", "publisher"),
                               ("length", "duration"), ("contentTier", "content_tier")):
            value = _text(item.get(source), 300)
            if value:
                citation[target] = value
        if kind in ("image", "video"):
            citation["delivery_mode"] = mode
            citation["description_origin"] = "provider_metadata"
            if mode == "with_media":
                for source, target in (("thumbnailUrl", "thumbnail_url"),):
                    media_url = _safe_url(item.get(source))
                    if media_url and media_url.startswith("https://"):
                        citation[target] = media_url
                if kind == "image":
                    image_url = _safe_url(item.get("url"))
                    if image_url and image_url.startswith("https://"):
                        citation["image_url"] = image_url
                else:
                    citation["video_url"] = url
                for source, target in (("width", "media_width"), ("height", "media_height")):
                    value = item.get(source)
                    if type(value) is int and 0 < value <= 100000:
                        citation[target] = value
            if kind == "video" and isinstance(item.get("moments"), list):
                citation["moments"] = [
                    {"title": _text(moment.get("title"), 300), "url": _safe_url(moment.get("momentUrl")),
                     "start_time": _text(moment.get("startTime"), 30)}
                    for moment in item["moments"][:5] if isinstance(moment, dict) and _safe_url(moment.get("momentUrl"))
                ]
        citations.append(citation)
    return citations


def search_web_iq(settings, query, result_types=None, cancel_requested=None,
                  invocation_capture=None, invocation_source_type="web"):
    """Retrieve bounded evidence; never follow provider redirects with credentials."""
    config = validate_web_iq_ready(settings)
    selected = resolve_web_iq_types(settings, result_types)
    if config["max_results"] < len(selected):
        raise WebIQError("result_budget_too_small")
    if not isinstance(query, str) or not query.strip() or len(query) > 1000:
        raise WebIQError("invalid_query")
    if cancel_requested and cancel_requested():
        raise InterruptedError("Web IQ search cancelled.")
    config = resolve_web_iq_credentials(settings)
    snapshot = web_iq_configuration_snapshot(settings, resolved_config=config)
    envelope = {"version": "orchestration-external-acquisition-v1", "kind": "web_iq",
                "phase": "definition", "configuration": snapshot, "result_types": selected}
    if invocation_capture is not None:
        invocation_capture(invocation_source_type, settings=settings, source=envelope)
    headers = {"Content-Type": "application/json"}
    params = None
    credential = None
    if config["authentication_type"] == "key":
        headers["x-apikey"] = config["key"]
    else:
        try:
            credential = ClientSecretCredential(config["tenant_id"], config["client_id"], config["client_secret"])
        except ValueError:
            raise WebIQError("invalid_authentication") from None
        try:
            headers["Authorization"] = f"Bearer {credential.get_token('https://api.microsoft.ai/.default').token}"
        except AzureError:
            credential.close()
            raise WebIQError("authentication_failed") from None
        params = {"APPID": config["app_id"]}
    citations, runs = [], []
    try:
        with requests.Session() as session:
            for kind_index, kind in enumerate(selected):
                if cancel_requested and cancel_requested():
                    raise InterruptedError("Web IQ search cancelled.")
                started_at = datetime.now(timezone.utc).isoformat()
                result_budget = config["max_results"] // len(selected) + (
                    1 if kind_index < config["max_results"] % len(selected) else 0
                )
                body = {"query": query.strip(), "maxResults": min(result_budget, RESULT_LIMITS[kind]),
                        "language": config["language"], "region": config["region"]}
                if kind in ("web", "news"):
                    body.update(contentFormat="passage", maxLength=config["max_length"])
                if kind != "news":
                    body["safeSearch"] = "strict"
                for attempt in range(2):
                    try:
                        response = session.post(f"{WEB_IQ_ENDPOINT}/search/{RESULT_PATHS[kind]}",
                                                headers=headers, params=params, json=body, timeout=(5, 20),
                                                allow_redirects=False, stream=True)
                        with response:
                            if response.status_code in (429, 503) and attempt == 0:
                                retry_after = response.headers.get("Retry-After", "1")
                                if not retry_after.isdigit() or int(retry_after) > 2:
                                    raise WebIQError("provider_http_error", provider_status=response.status_code)
                                retry_seconds = int(retry_after)
                            elif response.status_code != 200:
                                raise WebIQError("provider_http_error", provider_status=response.status_code)
                            else:
                                content = bytearray()
                                for chunk in response.iter_content(chunk_size=65536):
                                    if cancel_requested and cancel_requested():
                                        raise InterruptedError("Web IQ search cancelled.")
                                    content.extend(chunk)
                                    if len(content) > 2_000_000:
                                        raise WebIQError("response_limit_exceeded")
                                try:
                                    payload = json.loads(content)
                                except (ValueError, UnicodeError):
                                    raise WebIQError("invalid_response") from None
                                break
                    except requests.Timeout:
                        raise WebIQError("provider_timeout") from None
                    except requests.RequestException:
                        raise WebIQError("connection_failed") from None
                    deadline = time.monotonic() + retry_seconds
                    while time.monotonic() < deadline:
                        if cancel_requested and cancel_requested():
                            raise InterruptedError("Web IQ search cancelled.")
                        time.sleep(min(0.1, max(0, deadline - time.monotonic())))
                policy = web_iq_policy(settings)
                found = normalize_web_iq_response(
                    payload, kind, mode=policy.get(kind, "text_only"),
                    max_results=body["maxResults"], max_length=config["max_length"],
                )
                seeds_before = len(citations)
                for citation in found:
                    existing = next((item for item in citations if item["url"] == citation["url"]
                                     and item["source_kind"] not in ("image", "video")
                                     and citation["source_kind"] not in ("image", "video")), None)
                    if existing is None:
                        citations.append(citation)
                    else:
                        existing["source_kinds"] = list(dict.fromkeys(
                            existing.get("source_kinds", [existing["source_kind"]]) + [citation["source_kind"]]
                        ))
                runs.append({"provider": "web_iq", "source_kind": kind, "status": "completed",
                             "success": True, "result_count": len(found),
                             "query": query.strip()[:300], "started_at": started_at,
                             "completed_at": datetime.now(timezone.utc).isoformat(),
                             "seed_url_count_before": seeds_before, "seed_url_count_after": len(citations),
                             "new_seed_url_count": len(citations) - seeds_before,
                             "trace_id": _text(payload.get("traceId"), 100)})
        if cancel_requested and cancel_requested():
            raise InterruptedError("Web IQ search cancelled.")
        if invocation_capture is not None:
            invocation_capture(invocation_source_type, settings=settings,
                               source={**envelope, "phase": "run"})
    finally:
        if credential is not None:
            credential.close()
    message = "\n\n".join(
        f"Source {index}: {citation['title']}\nURL: {citation['url']}\n"
        f"Type: {citation['source_kind']}\n{citation['description']}"
        for index, citation in enumerate(citations, 1)
    )
    return {"provider": "web_iq", "message": message, "citations": citations, "runs": runs}
