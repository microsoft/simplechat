# csp_media_sources.py
"""Validate the extra origins an administrator allows in the Content-Security-Policy media-src directive.

Agents and actions can return audio and video hosted on their own domains (for example short-lived,
signed links from an OpenAPI action). The chat can only play those in place when the page's
Content-Security-Policy lists the host in media-src. CSP_MEDIA_SRC_ORIGINS names those hosts.

Only bare https origins are accepted: a host, an optional leading "*." label and an optional port.
Anything else (other schemes, paths, quotes, semicolons, keywords such as 'unsafe-inline', or a bare
"*") is rejected, so the setting cannot widen the policy beyond media or inject another directive.

Kept free of application imports so config.py can use it at start-up and tests can import it alone.
"""

import json
import re

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_ORIGIN_PATTERN = re.compile(rf"^https://(?:\*\.)?{_LABEL}(?:\.{_LABEL})+(?::\d{{1,5}})?$")


def _split(raw_value):
    value = str(raw_value or "").strip()
    if not value:
        return []
    if value.startswith("["):
        try:
            parsed = json.loads(value)
        except ValueError:
            return [value]
        return [str(item) for item in parsed] if isinstance(parsed, list) else [value]
    return [item for item in re.split(r"[\s,]+", value) if item]


def parse_csp_media_origins(raw_value):
    """Return (accepted, rejected) origins from a comma, space or JSON-list value.

    Accepted origins are lower-cased, stripped of a trailing slash and de-duplicated in order.
    """
    accepted = []
    rejected = []
    for item in _split(raw_value):
        candidate = item.strip().rstrip("/").lower()
        port = candidate.rsplit(":", 1)[1] if candidate.count(":") == 2 else ""
        if _ORIGIN_PATTERN.match(candidate) and (not port or 0 < int(port) <= 65535):
            if candidate not in accepted:
                accepted.append(candidate)
        else:
            rejected.append(item)
    return accepted, rejected


def build_media_src_directive(origins):
    """The media-src directive: same-origin and blob media, plus the allowed external origins."""
    return " ".join(["media-src 'self' blob:", *origins])
