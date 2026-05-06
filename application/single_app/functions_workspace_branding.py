# functions_workspace_branding.py

from config import *

DEFAULT_WORKSPACE_HERO_COLOR = "#0078d4"
MAX_WORKSPACE_LOGO_STORAGE_HEIGHT = 500
ALLOWED_WORKSPACE_LOGO_FORMATS = ("PNG", "JPEG")
WORKSPACE_HERO_COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{6})$")


def is_allowed_workspace_logo_file(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    return filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS_IMG


def normalize_workspace_hero_color(color: str | None, fallback: str = DEFAULT_WORKSPACE_HERO_COLOR) -> str:
    candidate = str(color or "").strip()
    if WORKSPACE_HERO_COLOR_PATTERN.fullmatch(candidate):
        return candidate

    normalized_fallback = str(fallback or DEFAULT_WORKSPACE_HERO_COLOR).strip()
    if WORKSPACE_HERO_COLOR_PATTERN.fullmatch(normalized_fallback):
        return normalized_fallback

    return DEFAULT_WORKSPACE_HERO_COLOR


def prepare_workspace_logo_image_for_storage(
    file_bytes: bytes,
    filename: str,
    max_height: int = MAX_WORKSPACE_LOGO_STORAGE_HEIGHT,
) -> dict:
    img = Image.open(BytesIO(file_bytes), formats=list(ALLOWED_WORKSPACE_LOGO_FORMATS))
    img.load()

    detected_format = (img.format or "").upper()
    if detected_format not in ALLOWED_WORKSPACE_LOGO_FORMATS:
        raise ValueError(
            f"Unsupported image format for {filename}. Allowed formats: {', '.join(ALLOWED_WORKSPACE_LOGO_FORMATS)}"
        )

    if img.mode == "P":
        img = img.convert("RGBA")
    elif img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    original_size = img.size
    if max_height and img.height > max_height:
        aspect_ratio = img.width / img.height
        resized_width = max(1, int(round(aspect_ratio * max_height)))
        img = img.resize((resized_width, max_height), Image.Resampling.LANCZOS)

    output = BytesIO()
    img.save(output, format="PNG", optimize=True)
    png_data = output.getvalue()

    return {
        "detected_format": detected_format,
        "original_size": original_size,
        "stored_size": img.size,
        "png_data": png_data,
        "base64_str": base64.b64encode(png_data).decode("utf-8"),
    }


def decode_workspace_logo_base64(logo_base64: str) -> bytes:
    return base64.b64decode(str(logo_base64 or ""))


def get_workspace_logo_metadata(document: dict | None) -> dict:
    doc = document or {}
    logo_base64 = str(doc.get("logoBase64") or "").strip()

    try:
        logo_version = int(doc.get("logoVersion", 1) or 1)
    except (TypeError, ValueError):
        logo_version = 1

    if logo_version < 1:
        logo_version = 1

    return {
        "hasLogo": bool(logo_base64),
        "logoVersion": logo_version,
    }
