# functions_icon_utils.py
"""Shared helpers for validating small user-configurable icon payloads."""

import base64
import re
from typing import Any, Dict


ALLOWED_ICON_KINDS = {"bootstrap", "image"}
ALLOWED_ICON_MIME_TYPES = {"image/png", "image/jpeg"}
BOOTSTRAP_ICON_PATTERN = re.compile(r"^bi-[a-z0-9][a-z0-9-]{0,80}$")
DATA_IMAGE_PATTERN = re.compile(r"^data:(image/png|image/jpeg);base64,([A-Za-z0-9+/=]+)$")
MAX_ICON_IMAGE_BYTES = 256 * 1024


def normalize_icon_payload(icon: Any, field_name: str = "icon") -> Dict[str, str]:
    """Return a safe icon payload or raise ValueError."""
    if icon in (None, ""):
        return {}

    if isinstance(icon, str):
        icon = {"kind": "bootstrap", "value": icon}

    if not isinstance(icon, dict):
        raise ValueError(f"{field_name} must be an object.")

    kind = str(icon.get("kind") or icon.get("type") or "bootstrap").strip().lower()
    value = str(icon.get("value") or "").strip()
    if not value:
        return {}

    if kind not in ALLOWED_ICON_KINDS:
        raise ValueError(f"{field_name}.kind must be bootstrap or image.")

    if kind == "bootstrap":
        value = value.replace("bi ", "").strip()
        if not BOOTSTRAP_ICON_PATTERN.fullmatch(value):
            raise ValueError(f"{field_name}.value must be a Bootstrap Icons class such as bi-robot.")
        return {"kind": "bootstrap", "value": value}

    compact_value = re.sub(r"\s+", "", value)
    match = DATA_IMAGE_PATTERN.fullmatch(compact_value)
    if not match:
        raise ValueError(f"{field_name}.value must be a PNG or JPEG data image.")

    mime_type, encoded = match.groups()
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError(f"{field_name}.value contains invalid image data.") from exc

    if len(decoded) > MAX_ICON_IMAGE_BYTES:
        raise ValueError(f"{field_name}.value image must be 256 KB or smaller.")

    if mime_type not in ALLOWED_ICON_MIME_TYPES:
        raise ValueError(f"{field_name}.value must be a PNG or JPEG image.")

    return {"kind": "image", "value": compact_value, "mime_type": mime_type}