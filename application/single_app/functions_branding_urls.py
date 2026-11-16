# functions_branding_urls.py
"""Static URLs for the administrator-supplied branding assets.

The logo and favicon are stored base64-encoded in the settings document and written out
as static files, so every surface that wants to show one needs the same two things: the
path the file is written to, and the version counter that busts the browser cache when an
administrator replaces it. Those rules were previously restated in each place that needed
them -- ``base.html`` for the server-rendered pages, ``BRANDING_IMAGE_TARGETS`` for the
upload endpoint, and ``_build_branding`` for the SPA -- which meant a change to one path
could leave another pointing at a file that no longer existed.

This module holds the paths and the version rule once. It deliberately has no imports:
the V2 SPA shell route is served on every page load and reads the favicon URL from here,
so it must not have to pull in Pillow or the Azure clients to render an icon link.
"""

LOGO_STATIC_URL = "/static/images/custom_logo.png"
LOGO_DARK_STATIC_URL = "/static/images/custom_logo_dark.png"
FAVICON_STATIC_URL = "/static/images/favicon.ico"


def _versioned(url, version):
    """Append the cache-busting version counter to a branding asset URL.

    The static file keeps a stable name across uploads, so without the counter a browser
    keeps serving whichever image it cached before the replacement.
    """
    try:
        resolved = int(version)
    except (TypeError, ValueError):
        resolved = 1
    return f"{url}?v={resolved if resolved > 0 else 1}"


def build_favicon_url(settings):
    """Return the favicon URL, versioned only when a custom icon is stored.

    Mirrors ``base.html``: the shipped default is served unversioned because it only
    changes with a deploy, which already invalidates the cache.
    """
    settings = settings or {}
    if settings.get("custom_favicon_base64"):
        return _versioned(FAVICON_STATIC_URL, settings.get("favicon_version"))
    return FAVICON_STATIC_URL


def build_custom_logo_urls(settings):
    """Return ``(light_url, dark_url)`` for the stored custom logos.

    Either entry is ``None`` when no custom logo has been uploaded; callers decide what to
    show instead. When only a light logo exists it is reused in dark mode, matching the
    server-rendered templates, so a single upload still works in both themes.
    """
    settings = settings or {}

    light_url = None
    dark_url = None

    if settings.get("custom_logo_base64"):
        light_url = _versioned(LOGO_STATIC_URL, settings.get("logo_version"))
    if settings.get("custom_logo_dark_base64"):
        dark_url = _versioned(LOGO_DARK_STATIC_URL, settings.get("logo_dark_version"))
    elif light_url:
        dark_url = light_url

    return light_url, dark_url
