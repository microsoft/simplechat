# functions_image_formats.py

"""Format detection and conversion for pictures a person uploaded.

An uploaded image is stored exactly as it arrived. Two consumers need it in a different shape:

- **A browser** renders PNG, JPEG, GIF, WEBP and BMP natively, but not TIFF, and renders HEIC
  only in Safari. A chat thumbnail should also not be a 40-megapixel original.
- **An image or vision model** accepts a small set of formats, should not be sent the camera's
  EXIF/GPS metadata, and gains nothing from pixels beyond a couple of thousand on a side.

The functions here produce those derived shapes on demand and never modify the stored original.

HEIC/HEIF is *detected* but never decoded. The only maintained decoder ships codecs under a
copyleft license, so a HEIC file is served to the browser as-is (Safari renders it) and refused
as a model input with a stable error that tells the person to upload a JPG or PNG instead.

Decoding is bounded twice: the byte size is checked before the header is parsed, and the header's
declared dimensions are checked before any pixels are allocated, so a small file that declares an
enormous raster (a decompression bomb) is refused rather than expanded into memory.

This module deliberately imports nothing from the application, so it can be tested directly and
imported by routes, the reference resolver and chat vision without configuration.
"""

import base64
import io
import warnings

from PIL import Image, ImageOps


IMAGE_FILE_EXTENSIONS = frozenset({'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tif', 'tiff', 'heic', 'heif'})
HEIF_FILE_EXTENSIONS = frozenset({'heic', 'heif'})
# Every stored image format except HEIC/HEIF, which cannot be decoded here.
REFERENCE_IMAGE_FILE_EXTENSIONS = IMAGE_FILE_EXTENSIONS - HEIF_FILE_EXTENSIONS

BROWSER_IMAGE_MIME_TYPES = frozenset({'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/bmp'})
HEIF_MIME_TYPES = frozenset({'image/heic', 'image/heif'})

PREVIEW_VARIANT_THUMBNAIL = 'thumbnail'
PREVIEW_VARIANT_DISPLAY = 'display'
PREVIEW_VARIANTS = (PREVIEW_VARIANT_THUMBNAIL, PREVIEW_VARIANT_DISPLAY)

# A chat card is at most a few hundred CSS pixels wide; 1024 keeps it sharp on a dense display.
THUMBNAIL_MAX_EDGE = 1024
# A converted display copy (TIFF) is bounded so a scanned 60-megapixel page does not become a
# 150 MB PNG. Formats the browser renders natively are passed through untouched.
DISPLAY_MAX_EDGE = 4096
# Image models downscale internally; beyond this, extra pixels cost upload time and nothing else.
MODEL_IMAGE_MAX_EDGE = 2048
MODEL_IMAGE_MAX_BYTES = 20 * 1024 * 1024

# Refused before decoding. Stored uploads can legitimately be large, so this is a sanity ceiling
# rather than a product limit.
MAX_INPUT_IMAGE_BYTES = 64 * 1024 * 1024
MAX_DECODE_PIXELS = 64_000_000

THUMBNAIL_JPEG_QUALITY = 85
MODEL_JPEG_QUALITY = 92

DEFAULT_MODEL_INPUT_FORMATS = ('image/png', 'image/jpeg', 'image/webp')

_PIL_FORMAT_MIME_TYPES = {
    'PNG': 'image/png',
    'JPEG': 'image/jpeg',
    'MPO': 'image/jpeg',
    'GIF': 'image/gif',
    'WEBP': 'image/webp',
    'BMP': 'image/bmp',
    'DIB': 'image/bmp',
    'TIFF': 'image/tiff',
}
_MIME_EXTENSIONS = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}

# ISO base media file brands. HEIC brands name the HEVC codec; mif1/msf1 are the generic HEIF
# structure brands, which AVIF also declares, so they only count when no AVIF brand is present.
_HEIC_BRANDS = frozenset({b'heic', b'heix', b'hevc', b'hevx', b'heim', b'heis', b'hevm', b'hevs'})
_HEIF_STRUCTURE_BRANDS = frozenset({b'mif1', b'msf1'})
_AVIF_BRANDS = frozenset({b'avif', b'avis'})

_ALPHA_MODES = frozenset({'RGBA', 'RGBa', 'LA', 'La', 'PA'})
# ICC profiles describe the channel layout they were written for. Kept only when the output keeps
# that layout, so a CMYK or grayscale profile is never attached to converted RGB pixels.
_ICC_PRESERVING_MODES = frozenset({'RGB', 'RGBA', 'P', 'PA'})

HEIF_REFERENCE_MESSAGE = (
    "HEIC and HEIF images can't be used as a reference image yet. "
    'Convert the picture to JPG or PNG and upload it again.'
)


class ImageFormatError(ValueError):
    """A browser-safe reason an image could not be converted, with a stable code and status."""

    def __init__(self, message, code='unsupported_image_format', status_code=415):
        super().__init__(message)
        self.public_message = message
        self.code = code
        self.status_code = status_code


def image_file_extension(file_name):
    """Return the lowercase extension of a file name without its dot, or an empty string."""
    name = str(file_name or '').strip().lower()
    if '.' not in name:
        return ''
    return name.rsplit('.', 1)[1]


def is_image_file_name(file_name):
    """Return whether a file name carries an image extension the application stores."""
    return image_file_extension(file_name) in IMAGE_FILE_EXTENSIONS


def is_heif_file_name(file_name):
    """Return whether a file name names a HEIC/HEIF image, which is never decoded here."""
    return image_file_extension(file_name) in HEIF_FILE_EXTENSIONS


def is_reference_image_file_name(file_name):
    """Return whether a file name names an image that can be sent to a model."""
    return image_file_extension(file_name) in REFERENCE_IMAGE_FILE_EXTENSIONS


def _heif_mime_type(image_bytes):
    """Return image/heic or image/heif for an ISO-BMFF HEIF container, otherwise None."""
    if len(image_bytes) < 16 or image_bytes[4:8] != b'ftyp':
        return None
    box_size = int.from_bytes(image_bytes[0:4], 'big')
    end = box_size if 16 <= box_size <= 4096 else 64
    end = min(end, len(image_bytes))
    brands = {bytes(image_bytes[8:12])}
    for offset in range(16, end - 3, 4):
        brands.add(bytes(image_bytes[offset:offset + 4]))
    if brands & _HEIC_BRANDS:
        return 'image/heic'
    if brands & _HEIF_STRUCTURE_BRANDS and not brands & _AVIF_BRANDS:
        return 'image/heif'
    return None


def _open_bounded(image_bytes):
    """Open an image header, refusing oversized files and rasters before pixels are decoded."""
    if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
        raise ImageFormatError('The image is empty.', 'invalid_image', 415)
    if len(image_bytes) > MAX_INPUT_IMAGE_BYTES:
        raise ImageFormatError('This image is too large to process.', 'image_too_large', 413)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(bytes(image_bytes)))
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageFormatError('This image is too large to process.', 'image_too_large', 413) from exc
    except Exception as exc:
        raise ImageFormatError('This file could not be read as an image.', 'invalid_image', 415) from exc
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ImageFormatError('This file could not be read as an image.', 'invalid_image', 415)
    if width * height > MAX_DECODE_PIXELS:
        raise ImageFormatError('This image is too large to process.', 'image_too_large', 413)
    if image.format not in _PIL_FORMAT_MIME_TYPES:
        raise ImageFormatError('This image format is not supported.', 'unsupported_image_format', 415)
    return image


def detect_image_format(image_bytes):
    """Return the canonical MIME type of image bytes, or None when they are not a known image.

    The bytes decide, never the file name: an upload named ``.png`` that is really a TIFF is
    converted like a TIFF, and a renamed document is not served as a picture.
    """
    if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
        return None
    heif_mime_type = _heif_mime_type(image_bytes)
    if heif_mime_type:
        return heif_mime_type
    try:
        image = _open_bounded(image_bytes)
    except ImageFormatError:
        return None
    try:
        return _PIL_FORMAT_MIME_TYPES.get(image.format)
    finally:
        image.close()


def _has_alpha(image):
    if image.mode in _ALPHA_MODES:
        return True
    return 'transparency' in image.info and image.mode in ('P', 'L', 'RGB')


def _load_first_frame(image, max_edge):
    """Decode only the first frame, letting JPEG decode at a reduced scale when that suffices."""
    try:
        image.seek(0)
    except EOFError:
        pass
    if image.format in ('JPEG', 'MPO') and image.mode in ('RGB', 'L') and max_edge:
        # draft() keeps both edges at or above the request, so the later resize stays exact.
        image.draft(image.mode, (max_edge, max_edge))
    try:
        image.load()
    except Exception as exc:
        raise ImageFormatError('This file could not be read as an image.', 'invalid_image', 415) from exc
    return image


def _normalized_frame(image, max_edge):
    """Return an upright RGB or RGBA copy of the first frame with no metadata attached."""
    source_mode = image.mode
    icc_profile = image.info.get('icc_profile') if source_mode in _ICC_PRESERVING_MODES else None
    try:
        upright = ImageOps.exif_transpose(image)
        if source_mode.startswith('I;16'):
            # 16-bit grayscale (scanned maps, medical TIFF): scale to 8 bits rather than clipping.
            frame = upright.convert('I').point(lambda value: value * (1 / 256)).convert('L').convert('RGB')
        elif source_mode in ('I', 'F'):
            frame = upright.convert('L').convert('RGB')
        elif _has_alpha(upright):
            frame = upright.convert('RGBA')
        else:
            frame = upright.convert('RGB')
    except Exception as exc:
        raise ImageFormatError('This image could not be converted.', 'invalid_image', 415) from exc
    if max_edge and max(frame.size) > max_edge:
        frame.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    # EXIF (camera, GPS, orientation) and text chunks are dropped; only a compatible ICC profile
    # is re-attached at encode time so colors stay faithful.
    frame.info = {}
    return frame, icc_profile


def _encode(frame, mime_type, icc_profile=None, jpeg_quality=MODEL_JPEG_QUALITY):
    buffer = io.BytesIO()
    options = {}
    if icc_profile:
        options['icc_profile'] = icc_profile
    if mime_type == 'image/jpeg':
        if frame.mode != 'RGB':
            frame = _flatten_on_white(frame)
        frame.save(buffer, format='JPEG', quality=jpeg_quality, **options)
    elif mime_type == 'image/webp':
        frame.save(buffer, format='WEBP', quality=jpeg_quality, **options)
    else:
        frame.save(buffer, format='PNG', **options)
    return buffer.getvalue()


def _flatten_on_white(frame):
    if frame.mode != 'RGBA':
        return frame.convert('RGB')
    background = Image.new('RGB', frame.size, (255, 255, 255))
    background.paste(frame, mask=frame.getchannel('A'))
    return background


def to_browser_image(image_bytes, variant=PREVIEW_VARIANT_DISPLAY):
    """Return ``{bytes, mime_type, width, height, converted}`` a browser can render.

    ``display`` passes browser-native formats through unchanged and converts TIFF (first page)
    to PNG. ``thumbnail`` bounds the long edge at ``THUMBNAIL_MAX_EDGE``: PNG when the picture
    has transparency, JPEG otherwise. HEIC/HEIF passes through for both variants as
    ``image/heic``/``image/heif``, which Safari renders and other browsers report as a decode
    failure the caller can fall back from.
    """
    if variant not in PREVIEW_VARIANTS:
        raise ImageFormatError('The preview variant is not supported.', 'invalid_preview_variant', 400)
    if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
        raise ImageFormatError('The image is empty.', 'invalid_image', 415)
    heif_mime_type = _heif_mime_type(image_bytes)
    if heif_mime_type:
        if len(image_bytes) > MAX_INPUT_IMAGE_BYTES:
            raise ImageFormatError('This image is too large to process.', 'image_too_large', 413)
        return {
            'bytes': bytes(image_bytes), 'mime_type': heif_mime_type,
            'width': None, 'height': None, 'converted': False,
        }

    image = _open_bounded(image_bytes)
    try:
        mime_type = _PIL_FORMAT_MIME_TYPES[image.format]
        width, height = image.size
        if variant == PREVIEW_VARIANT_DISPLAY and mime_type in BROWSER_IMAGE_MIME_TYPES:
            return {
                'bytes': bytes(image_bytes), 'mime_type': mime_type,
                'width': width, 'height': height, 'converted': False,
            }
        if (
            variant == PREVIEW_VARIANT_THUMBNAIL
            and mime_type in BROWSER_IMAGE_MIME_TYPES
            and mime_type != 'image/bmp'
            and max(width, height) <= THUMBNAIL_MAX_EDGE
        ):
            return {
                'bytes': bytes(image_bytes), 'mime_type': mime_type,
                'width': width, 'height': height, 'converted': False,
            }

        max_edge = THUMBNAIL_MAX_EDGE if variant == PREVIEW_VARIANT_THUMBNAIL else DISPLAY_MAX_EDGE
        _load_first_frame(image, max_edge)
        frame, icc_profile = _normalized_frame(image, max_edge)
        if variant == PREVIEW_VARIANT_THUMBNAIL and frame.mode != 'RGBA':
            output_mime_type = 'image/jpeg'
        else:
            output_mime_type = 'image/png'
        encoded = _encode(frame, output_mime_type, icc_profile, THUMBNAIL_JPEG_QUALITY)
        return {
            'bytes': encoded, 'mime_type': output_mime_type,
            'width': frame.size[0], 'height': frame.size[1], 'converted': True,
        }
    finally:
        image.close()


def _model_output_mime_type(has_alpha, allowed_formats):
    if has_alpha and 'image/png' in allowed_formats:
        return 'image/png'
    if 'image/jpeg' in allowed_formats:
        return 'image/jpeg'
    if 'image/png' in allowed_formats:
        return 'image/png'
    if 'image/webp' in allowed_formats:
        return 'image/webp'
    return ''


def normalize_model_image(
    image_bytes,
    allowed_formats=None,
    max_edge=MODEL_IMAGE_MAX_EDGE,
    max_bytes=MODEL_IMAGE_MAX_BYTES,
    file_stem='reference',
):
    """Return a model-ready copy: ``{bytes, mime_type, file_name, width, height}``.

    The shape matches ``functions_image_edit.prepare_source_image`` so the result can be passed
    straight to the edit adapter. The copy is always re-encoded, which applies the EXIF
    orientation and drops EXIF/GPS metadata; multi-page TIFF contributes its first page. The long
    edge is bounded by ``max_edge`` and the encoded size by ``max_bytes``, shrinking further when
    a detailed picture encodes larger than the budget.

    PNG is used when the picture has transparency, otherwise high-quality JPEG, within the MIME
    types in ``allowed_formats`` (the capability's ``input_formats``).
    """
    if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
        raise ImageFormatError('The reference image is empty.', 'invalid_image', 415)
    if _heif_mime_type(image_bytes):
        raise ImageFormatError(HEIF_REFERENCE_MESSAGE, 'unsupported_reference_format', 415)
    allowed = tuple(allowed_formats) if allowed_formats else DEFAULT_MODEL_INPUT_FORMATS
    try:
        edge_limit = max(64, int(max_edge or MODEL_IMAGE_MAX_EDGE))
        byte_limit = max(1, int(max_bytes or MODEL_IMAGE_MAX_BYTES))
    except (TypeError, ValueError) as exc:
        raise ImageFormatError('The reference image limits are invalid.', 'invalid_image_request', 400) from exc

    try:
        image = _open_bounded(image_bytes)
    except ImageFormatError as exc:
        if exc.code in ('invalid_image', 'unsupported_image_format'):
            raise ImageFormatError(
                'This file could not be used as a reference image. Upload a PNG, JPG, BMP, or TIFF picture.',
                'unsupported_reference_format', 415,
            ) from exc
        raise
    try:
        _load_first_frame(image, edge_limit)
        frame, icc_profile = _normalized_frame(image, edge_limit)
    finally:
        image.close()

    output_mime_type = _model_output_mime_type(frame.mode == 'RGBA', allowed)
    if not output_mime_type:
        raise ImageFormatError(
            'The selected image model does not accept PNG, JPEG, or WEBP reference images.',
            'unsupported_reference_format', 415,
        )

    encoded = _encode(frame, output_mime_type, icc_profile)
    attempts = 0
    while len(encoded) > byte_limit and attempts < 5 and max(frame.size) > 64:
        attempts += 1
        next_edge = max(64, int(max(frame.size) * 0.75))
        frame.thumbnail((next_edge, next_edge), Image.Resampling.LANCZOS)
        encoded = _encode(frame, output_mime_type, icc_profile)
    if len(encoded) > byte_limit:
        raise ImageFormatError('This reference image is too large to send.', 'image_too_large', 413)

    stem = ''.join(character for character in str(file_stem or 'reference') if character.isalnum() or character in '-_')
    return {
        'bytes': encoded,
        'mime_type': output_mime_type,
        'file_name': f"{stem or 'reference'}.{_MIME_EXTENSIONS[output_mime_type]}",
        'width': frame.size[0],
        'height': frame.size[1],
    }


def image_data_url(prepared_image):
    """Return a ``data:`` URL for a prepared image (``{bytes, mime_type}``)."""
    mime_type = str((prepared_image or {}).get('mime_type') or '').strip()
    image_bytes = (prepared_image or {}).get('bytes')
    if not mime_type.startswith('image/') or not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
        raise ImageFormatError('The prepared image is empty.', 'invalid_image', 415)
    return f"data:{mime_type};base64,{base64.b64encode(bytes(image_bytes)).decode('ascii')}"
