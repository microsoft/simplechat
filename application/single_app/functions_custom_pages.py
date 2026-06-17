# functions_custom_pages.py
"""Custom Pages registry, validation, discovery, and navigation helpers."""

import importlib.util
import inspect
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from azure.cosmos import exceptions
from flask import has_app_context, session, url_for

from config import cosmos_custom_pages_container
from custom_page_extension import CustomPageExtension
from functions_appinsights import log_event


CUSTOM_PAGES_DIR = os.path.join(os.path.dirname(__file__), "custom_pages")
CUSTOM_PAGE_SOURCE_COSMOS = "cosmos"
CUSTOM_PAGE_SOURCE_PYTHON = "python"
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
ENTRY_TYPES = {"static", "python"}
ACCESS_LEVELS = {"app_user", "authenticated"}
ASSET_FOLDERS = {
    "html": {".html", ".htm"},
    "css": {".css"},
    "js": {".js", ".mjs"},
    "assets": {
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
        ".woff", ".woff2", ".ttf", ".otf", ".pdf", ".mp4", ".webm",
    },
    "json": {".json", ".csv"},
}
LIST_FIELDS = ("roles", "css_files", "js_files", "asset_files", "json_files")
PYTHON_EXTENSION_CACHE: Optional[Dict[str, Dict[str, Any]]] = None


def is_custom_pages_enabled(settings: Optional[Dict[str, Any]] = None) -> bool:
    """Return True when custom pages are globally enabled."""
    return bool((settings or {}).get("enable_custom_pages", False))


def is_safe_slug(slug: str) -> bool:
    """Return True when a slug is safe for URL and lookup use."""
    return isinstance(slug, str) and bool(SLUG_PATTERN.fullmatch(slug.strip()))


def normalize_custom_page_metadata(
    metadata: Dict[str, Any],
    source: str = CUSTOM_PAGE_SOURCE_COSMOS,
) -> Dict[str, Any]:
    """Normalize a custom page metadata payload into the persisted contract."""
    page = dict(metadata or {})
    slug = str(page.get("slug") or page.get("id") or "").strip().lower()
    title = str(page.get("title") or page.get("nav_label") or slug).strip()
    nav_label = str(page.get("nav_label") or title or slug).strip()
    entry_type = str(page.get("entry_type") or "static").strip().lower()

    normalized = {
        "id": slug,
        "slug": slug,
        "title": title,
        "description": str(page.get("description") or "").strip(),
        "enabled": _coerce_bool(page.get("enabled", True)),
        "entry_type": entry_type,
        "access_level": str(page.get("access_level") or "app_user").strip().lower(),
        "nav_label": nav_label,
        "nav_icon": _normalize_icon(page.get("nav_icon")),
        "nav_order": _coerce_int(page.get("nav_order"), 100),
        "roles": _normalize_string_list(page.get("roles")),
        "show_in_nav": _coerce_bool(page.get("show_in_nav", True)),
        "open_in_new_tab": _coerce_bool(page.get("open_in_new_tab", False)),
        "render_jinja": _coerce_bool(page.get("render_jinja", False)),
        "html_file": _normalize_optional_path(page.get("html_file")),
        "css_files": _normalize_string_list(page.get("css_files")),
        "js_files": _normalize_string_list(page.get("js_files")),
        "asset_files": _normalize_string_list(page.get("asset_files")),
        "json_files": _normalize_string_list(page.get("json_files")),
        "source": source,
    }

    for optional_key in ("module", "class_name", "decorated_extension_id", "blueprint_name"):
        if page.get(optional_key):
            normalized[optional_key] = str(page.get(optional_key)).strip()

    return normalized


def validate_custom_page_metadata(metadata: Dict[str, Any], require_static_html: bool = False) -> List[str]:
    """Validate a custom page metadata payload and return error messages."""
    page = normalize_custom_page_metadata(metadata, source=metadata.get("source", CUSTOM_PAGE_SOURCE_COSMOS))
    errors = []

    if not is_safe_slug(page.get("slug")):
        errors.append("Slug must start with a lowercase letter or number and use only lowercase letters, numbers, hyphens, or underscores.")
    if not page.get("title"):
        errors.append("Title is required.")
    if page.get("entry_type") not in ENTRY_TYPES:
        errors.append("entry_type must be either static or python.")
    if page.get("access_level") not in ACCESS_LEVELS:
        errors.append("access_level must be either app_user or authenticated.")
    if page.get("entry_type") == "static" and require_static_html and not page.get("html_file"):
        errors.append("Static custom pages require an HTML file.")

    if page.get("html_file"):
        errors.extend(validate_custom_page_file_reference("html", page["html_file"]))
    for file_name in page.get("css_files", []):
        errors.extend(validate_custom_page_file_reference("css", file_name))
    for file_name in page.get("js_files", []):
        errors.extend(validate_custom_page_file_reference("js", file_name))
    for file_name in page.get("asset_files", []):
        errors.extend(validate_custom_page_file_reference("assets", file_name))
    for file_name in page.get("json_files", []):
        errors.extend(validate_custom_page_file_reference("json", file_name))

    return errors


def validate_custom_page_file_reference(folder: str, file_name: str) -> List[str]:
    """Validate a metadata file reference without requiring file existence."""
    errors = []
    if folder not in ASSET_FOLDERS:
        return [f"Unsupported custom page folder: {folder}"]
    if not isinstance(file_name, str) or not file_name.strip():
        return [f"{folder} file reference cannot be empty."]
    normalized = file_name.replace("\\", "/").strip()
    if normalized.startswith("/") or ".." in normalized.split("/"):
        errors.append(f"Unsafe {folder} file path: {file_name}")
    extension = os.path.splitext(normalized)[1].lower()
    if extension not in ASSET_FOLDERS[folder]:
        errors.append(f"Unsupported {folder} file extension for {file_name}.")
    return errors


def list_custom_pages(include_python: bool = True) -> List[Dict[str, Any]]:
    """Return custom page metadata from Cosmos and optional Python extensions."""
    pages = {}
    for page in list_cosmos_custom_pages():
        pages[page["slug"]] = page

    if include_python:
        for slug, page in discover_python_custom_pages().items():
            pages[slug] = page

    return sorted(pages.values(), key=lambda item: (item.get("nav_order", 100), item.get("nav_label", "").lower()))


def list_cosmos_custom_pages() -> List[Dict[str, Any]]:
    """Return static custom page metadata stored in Cosmos DB."""
    try:
        items = list(cosmos_custom_pages_container.query_items(
            query="SELECT * FROM c",
            enable_cross_partition_query=True,
        ))
        return [normalize_custom_page_metadata(_strip_cosmos_fields(item), source=CUSTOM_PAGE_SOURCE_COSMOS) for item in items]
    except exceptions.CosmosResourceNotFoundError:
        return []
    except Exception as ex:
        log_event(
            "[CustomPages] Failed to list custom pages.",
            extra={"error": str(ex)},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return []


def get_custom_page(slug: str, include_python: bool = True) -> Optional[Dict[str, Any]]:
    """Return a custom page by slug from Cosmos or Python discovery."""
    if not is_safe_slug(slug):
        return None
    normalized_slug = slug.strip().lower()

    if include_python:
        python_pages = discover_python_custom_pages()
        if normalized_slug in python_pages:
            return python_pages[normalized_slug]

    try:
        item = cosmos_custom_pages_container.read_item(item=normalized_slug, partition_key=normalized_slug)
        return normalize_custom_page_metadata(_strip_cosmos_fields(item), source=CUSTOM_PAGE_SOURCE_COSMOS)
    except exceptions.CosmosResourceNotFoundError:
        return None
    except Exception as ex:
        log_event(
            "[CustomPages] Failed to read custom page.",
            extra={"slug": normalized_slug, "error": str(ex)},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return None


def save_custom_page(metadata: Dict[str, Any], user_id: str = "system") -> Dict[str, Any]:
    """Create or update a static custom page metadata record."""
    page = normalize_custom_page_metadata(metadata, source=CUSTOM_PAGE_SOURCE_COSMOS)
    page["entry_type"] = "static"
    errors = validate_custom_page_metadata(page, require_static_html=True)
    if errors:
        raise ValueError("; ".join(errors))

    now = datetime.utcnow().isoformat()
    existing = get_custom_page(page["slug"], include_python=False)
    page["created_by"] = existing.get("created_by", user_id) if existing else user_id
    page["created_at"] = existing.get("created_at", now) if existing else now
    page["modified_by"] = user_id
    page["modified_at"] = now
    result = cosmos_custom_pages_container.upsert_item(body=page)
    return normalize_custom_page_metadata(_strip_cosmos_fields(result), source=CUSTOM_PAGE_SOURCE_COSMOS)


def delete_custom_page(slug: str) -> bool:
    """Delete a static custom page metadata record."""
    if not is_safe_slug(slug):
        return False
    try:
        cosmos_custom_pages_container.delete_item(item=slug, partition_key=slug)
        return True
    except exceptions.CosmosResourceNotFoundError:
        return False
    except Exception as ex:
        log_event(
            "[CustomPages] Failed to delete custom page.",
            extra={"slug": slug, "error": str(ex)},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        raise


def discover_python_custom_pages(force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
    """Discover trusted Python custom page extensions from custom_pages/python."""
    global PYTHON_EXTENSION_CACHE
    if PYTHON_EXTENSION_CACHE is not None and not force_refresh:
        return PYTHON_EXTENSION_CACHE

    discovered = {}
    python_dir = os.path.join(CUSTOM_PAGES_DIR, "python")
    if not os.path.isdir(python_dir):
        PYTHON_EXTENSION_CACHE = discovered
        return discovered

    for file_name in sorted(os.listdir(python_dir)):
        if not file_name.endswith(".py") or file_name.startswith("_"):
            continue
        module_path = os.path.join(python_dir, file_name)
        module_name = f"simplechat_custom_pages_{os.path.splitext(file_name)[0]}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for _, obj in inspect.getmembers(module):
                metadata, extension_instance = _extract_python_extension(obj)
                if not metadata:
                    continue
                page = normalize_custom_page_metadata(metadata, source=CUSTOM_PAGE_SOURCE_PYTHON)
                page["entry_type"] = "python"
                page["module"] = file_name
                page["extension"] = extension_instance
                errors = validate_custom_page_metadata(page)
                if errors:
                    log_event(
                        "[CustomPages] Ignored invalid Python custom page.",
                        extra={"module": file_name, "errors": errors},
                        level=logging.WARNING,
                    )
                    continue
                discovered[page["slug"]] = page
        except Exception as ex:
            log_event(
                "[CustomPages] Failed to import Python custom page module.",
                extra={"module": file_name, "error": str(ex)},
                level=logging.ERROR,
                exceptionTraceback=True,
            )

    PYTHON_EXTENSION_CACHE = discovered
    return discovered


def get_custom_pages_nav(settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return authorized custom page navigation items for the current request."""
    if not is_custom_pages_enabled(settings):
        return []

    roles = _current_user_roles()
    nav_items = []
    for page in list_custom_pages(include_python=True):
        if not page.get("enabled", True) or not page.get("show_in_nav", True):
            continue
        if not is_custom_page_authorized(page, roles):
            continue
        if has_app_context():
            href = url_for("custom_page", slug=page["slug"])
        else:
            href = f"/custom/{page['slug']}"
        nav_items.append({
            "slug": page["slug"],
            "label": page.get("nav_label") or page.get("title") or page["slug"],
            "icon": page.get("nav_icon") or "bi-file-earmark-text",
            "url": href,
            "href": href,
            "open_in_new_tab": bool(page.get("open_in_new_tab", False)),
            "order": page.get("nav_order", 100),
        })

    return sorted(nav_items, key=lambda item: (item.get("order", 100), item.get("label", "").lower()))


def is_custom_page_authorized(page: Dict[str, Any], roles: Optional[List[str]] = None) -> bool:
    """Return True when the current user roles satisfy custom page metadata."""
    role_set = set(roles if roles is not None else _current_user_roles())
    access_level = page.get("access_level") or "app_user"
    if access_level != "authenticated" and not ({"User", "Admin"}.intersection(role_set)):
        return False

    required_roles = page.get("roles") or []
    if not required_roles:
        return True
    required_role_set = set(required_roles)
    if role_set.intersection(required_role_set):
        return True
    return "Admin" in role_set and "User" in required_role_set


def resolve_custom_page_file(page: Dict[str, Any], folder: str, file_name: str) -> Tuple[Optional[str], Optional[str]]:
    """Resolve a custom page file reference to an absolute path if allowed."""
    errors = validate_custom_page_file_reference(folder, file_name)
    if errors:
        return None, "; ".join(errors)

    normalized_name = file_name.replace("\\", "/").strip()
    base_dir = os.path.abspath(os.path.join(CUSTOM_PAGES_DIR, folder))
    candidate = os.path.abspath(os.path.join(base_dir, normalized_name))
    if os.path.commonpath([base_dir, candidate]) != base_dir:
        return None, "File path is outside the allowed custom page folder."

    if not _file_reference_is_declared(page, folder, normalized_name):
        return None, "File is not declared by the custom page metadata."

    if not os.path.exists(candidate) or not os.path.isfile(candidate):
        return None, "File does not exist."
    return candidate, None


def build_custom_page_context(page: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
    """Build the safe request context passed to trusted custom page extensions."""
    return {
        "page": {key: value for key, value in page.items() if key != "extension"},
        "settings": settings,
        "user": session.get("user", {}),
        "roles": _current_user_roles(),
    }


def _extract_python_extension(obj: Any) -> Tuple[Optional[Dict[str, Any]], Optional[CustomPageExtension]]:
    if inspect.isclass(obj) and issubclass(obj, CustomPageExtension) and obj is not CustomPageExtension:
        instance = obj()
        metadata = getattr(obj, "__simplechat_custom_page__", None) or getattr(instance, "metadata", None)
        return metadata, instance

    metadata = getattr(obj, "__simplechat_custom_page__", None)
    if metadata and inspect.isclass(obj):
        instance = obj()
        return metadata, instance
    if metadata and callable(obj):
        extension = obj()
        if isinstance(extension, CustomPageExtension):
            return metadata, extension
    return None, None


def _file_reference_is_declared(page: Dict[str, Any], folder: str, file_name: str) -> bool:
    if folder == "html":
        return page.get("html_file") == file_name
    field_name = {
        "css": "css_files",
        "js": "js_files",
        "assets": "asset_files",
        "json": "json_files",
    }.get(folder)
    return file_name in set(page.get(field_name, [])) if field_name else False


def _normalize_optional_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip()


def _normalize_string_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).replace("\\", "/").strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [item.replace("\\", "/").strip() for item in value.split(",") if item.strip()]
    return []


def _normalize_icon(value: Any) -> str:
    icon = str(value or "bi-file-earmark-text").strip()
    if not re.fullmatch(r"bi-[a-z0-9-]+", icon):
        return "bi-file-earmark-text"
    return icon


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _strip_cosmos_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in (item or {}).items() if not key.startswith("_")}


def _current_user_roles() -> List[str]:
    user = session.get("user", {}) if has_app_context() else {}
    roles = user.get("roles", []) if isinstance(user, dict) else []
    return roles if isinstance(roles, list) else []