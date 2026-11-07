# functions_branding_images.py
"""Image processing for administrator-supplied branding assets.

Logos and favicons are uploaded by an administrator, converted to a canonical
form, and stored base64-encoded in the settings document. Two interfaces now
accept those uploads -- the server-rendered Admin Settings form and the V2
React admin surface -- so the conversion lives here rather than inside either
route module. A logo that is resized in one interface and not the other would
render at a different size depending on where it was uploaded from.

The conversion rules are the ones the server-rendered form has always applied:

- Only PNG and JPEG are decoded, regardless of the file extension supplied, so
  a renamed file cannot reach Pillow's other decoders.
- Palette images become RGBA and anything else that is not already RGB or RGBA
  becomes RGB, because neither PNG nor ICO can encode every Pillow mode.
- Logos taller than ``MAX_CUSTOM_LOGO_STORAGE_HEIGHT`` are scaled down with
  their aspect ratio preserved, which keeps the settings document small while
  still being sharp enough for the landing page to enlarge.
- Favicons are squared off at 32x32 and encoded as ICO.
"""

import base64
from io import BytesIO

from PIL import Image

# Pillow is asked for these formats explicitly. Passing an allow-list to
# Image.open means an attacker-supplied file cannot select a different decoder
# by claiming a different format internally.
ALLOWED_PIL_IMAGE_UPLOAD_FORMATS = ('PNG', 'JPEG')

# Tall enough for the landing page to render a logo scaled up to 500% without
# visible softening, small enough that the base64 copy stays a reasonable size
# inside the settings document.
MAX_CUSTOM_LOGO_STORAGE_HEIGHT = 500

FAVICON_SIZE = (32, 32)

ALLOWED_LOGO_EXTENSIONS = {'png', 'jpg', 'jpeg'}
ALLOWED_FAVICON_EXTENSIONS = {'png', 'jpg', 'jpeg', 'ico'}


def is_allowed_branding_image_filename(filename, allowed_extensions):
    """Return True when ``filename`` carries one of ``allowed_extensions``.

    This is a first-pass check only. The extension is attacker-controlled, so
    the real format check happens in ``open_allowed_uploaded_image`` once the
    bytes have been decoded.
    """
    if not filename or '.' not in filename:
        return False
    return filename.rsplit('.', 1)[1].lower() in allowed_extensions


def open_allowed_uploaded_image(file_bytes, filename):
    """Decode ``file_bytes`` as PNG or JPEG, or raise ``ValueError``.

    Returns the loaded image and the format Pillow actually detected, which is
    what callers should log rather than the supplied extension.
    """
    img = Image.open(BytesIO(file_bytes), formats=list(ALLOWED_PIL_IMAGE_UPLOAD_FORMATS))
    img.load()

    detected_format = (img.format or '').upper()
    if detected_format not in ALLOWED_PIL_IMAGE_UPLOAD_FORMATS:
        raise ValueError(
            f"Unsupported image format for {filename}. Allowed formats: "
            f"{', '.join(ALLOWED_PIL_IMAGE_UPLOAD_FORMATS)}"
        )

    return img, detected_format


def _normalize_image_mode(img):
    """Convert ``img`` into a mode both PNG and ICO can encode."""
    if img.mode == 'P':
        return img.convert('RGBA')
    if img.mode not in ('RGB', 'RGBA'):
        return img.convert('RGB')
    return img


def prepare_logo_image_for_storage(file_bytes, filename, max_height=MAX_CUSTOM_LOGO_STORAGE_HEIGHT):
    """Return a PNG-encoded, height-capped copy of an uploaded logo.

    The returned dict carries both the raw PNG bytes and their base64 form,
    plus the original and stored dimensions so callers can record what the
    resize actually did.
    """
    img, detected_format = open_allowed_uploaded_image(file_bytes, filename)
    original_size = img.size

    img = _normalize_image_mode(img)

    if max_height and img.height > max_height:
        aspect_ratio = img.width / img.height
        resized_width = max(1, int(round(aspect_ratio * max_height)))
        img = img.resize((resized_width, max_height), Image.Resampling.LANCZOS)

    img_bytes_io = BytesIO()
    img.save(img_bytes_io, format='PNG', optimize=True)
    png_data = img_bytes_io.getvalue()

    return {
        'detected_format': detected_format,
        'original_size': original_size,
        'stored_size': img.size,
        'png_data': png_data,
        'base64_str': base64.b64encode(png_data).decode('utf-8'),
    }


def prepare_favicon_image_for_storage(file_bytes, filename, size=FAVICON_SIZE):
    """Return an ICO-encoded 32x32 copy of an uploaded favicon."""
    img, detected_format = open_allowed_uploaded_image(file_bytes, filename)
    original_size = img.size

    img = _normalize_image_mode(img)
    img = img.resize(size, Image.Resampling.LANCZOS)

    img_bytes_io = BytesIO()
    img.save(img_bytes_io, format='ICO')
    ico_data = img_bytes_io.getvalue()

    return {
        'detected_format': detected_format,
        'original_size': original_size,
        'stored_size': img.size,
        'ico_data': ico_data,
        'base64_str': base64.b64encode(ico_data).decode('utf-8'),
    }
