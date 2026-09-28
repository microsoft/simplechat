#!/usr/bin/env python3
# test_image_format_conversion.py
"""
Functional tests for uploaded-image format detection and conversion.
Version: 0.261.144
Implemented in: 0.261.144

This test ensures that functions_image_formats detects formats from bytes rather than file
names, converts TIFF for browsers, bounds thumbnails, prepares EXIF-free model inputs within a
model's accepted formats, refuses HEIC/HEIF as a model input with a stable error, and refuses
decompression bombs before pixels are allocated. No application configuration is loaded.
"""

import io
import struct
import subprocess
import sys
import unittest
import zlib
from pathlib import Path

from PIL import Image


TESTS_ROOT = Path(__file__).resolve().parent
APP_ROOT = TESTS_ROOT.parent / 'application' / 'single_app'
sys.path.insert(0, str(TESTS_ROOT))
sys.path.insert(0, str(APP_ROOT))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

import functions_image_formats as formats  # noqa: E402


def encode(image, fmt, **options):
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **options)
    return buffer.getvalue()


def heif_bytes(major=b'heic', compatible=(b'mif1', b'heic')):
    payload = major + b'\x00\x00\x00\x00' + b''.join(compatible)
    box = struct.pack('>I', 8 + len(payload)) + b'ftyp' + payload
    return box + b'\x00' * 64


def png_header_only(width, height):
    """A syntactically valid PNG that declares a raster it does not contain."""
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    chunk = struct.pack('>I', len(ihdr)) + b'IHDR' + ihdr + struct.pack('>I', zlib.crc32(b'IHDR' + ihdr))
    iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', zlib.crc32(b'IEND'))
    return b'\x89PNG\r\n\x1a\n' + chunk + iend


class ImageFormatDetectionTests(unittest.TestCase):
    def test_version_header_is_current(self):
        assert_app_version_at_least('0.261.144')

    def test_detects_formats_from_bytes(self):
        rgb = Image.new('RGB', (8, 6), (10, 120, 200))
        cases = {
            'PNG': 'image/png', 'JPEG': 'image/jpeg', 'GIF': 'image/gif',
            'WEBP': 'image/webp', 'BMP': 'image/bmp', 'TIFF': 'image/tiff',
        }
        for fmt, expected in cases.items():
            with self.subTest(fmt=fmt):
                self.assertEqual(formats.detect_image_format(encode(rgb, fmt)), expected)

    def test_detects_heic_and_heif_without_decoding(self):
        self.assertEqual(formats.detect_image_format(heif_bytes()), 'image/heic')
        self.assertEqual(formats.detect_image_format(heif_bytes(b'mif1', (b'mif1', b'miaf'))), 'image/heif')
        self.assertIsNone(formats.detect_image_format(heif_bytes(b'avif', (b'mif1', b'avif'))))

    def test_rejects_non_images_and_empty_input(self):
        self.assertIsNone(formats.detect_image_format(b''))
        self.assertIsNone(formats.detect_image_format(None))
        self.assertIsNone(formats.detect_image_format(b'%PDF-1.7 not an image'))

    def test_file_name_helpers(self):
        self.assertTrue(formats.is_image_file_name('House.JPG'))
        self.assertTrue(formats.is_image_file_name('scan.tif'))
        self.assertTrue(formats.is_heif_file_name('IMG_0001.HEIC'))
        self.assertFalse(formats.is_reference_image_file_name('IMG_0001.heif'))
        self.assertTrue(formats.is_reference_image_file_name('map.tiff'))
        self.assertFalse(formats.is_image_file_name('report.pdf'))
        self.assertFalse(formats.is_image_file_name('noextension'))
        self.assertEqual(formats.image_file_extension(None), '')


class BrowserImageTests(unittest.TestCase):
    def test_display_passes_browser_native_formats_through(self):
        original = encode(Image.new('RGB', (40, 30), (1, 2, 3)), 'PNG')
        result = formats.to_browser_image(original, 'display')
        self.assertEqual(result['bytes'], original)
        self.assertEqual(result['mime_type'], 'image/png')
        self.assertFalse(result['converted'])
        self.assertEqual((result['width'], result['height']), (40, 30))

    def test_display_converts_first_tiff_page_to_png(self):
        first = Image.new('RGB', (64, 48), (255, 0, 0))
        second = Image.new('RGB', (64, 48), (0, 0, 255))
        buffer = io.BytesIO()
        first.save(buffer, format='TIFF', save_all=True, append_images=[second])
        result = formats.to_browser_image(buffer.getvalue(), 'display')
        self.assertEqual(result['mime_type'], 'image/png')
        self.assertTrue(result['converted'])
        with Image.open(io.BytesIO(result['bytes'])) as converted:
            self.assertEqual(converted.format, 'PNG')
            self.assertEqual(converted.size, (64, 48))
            self.assertEqual(converted.convert('RGB').getpixel((10, 10)), (255, 0, 0))

    def test_thumbnail_bounds_large_photos_as_jpeg(self):
        photo = encode(Image.new('RGB', (3000, 2000), (90, 140, 60)), 'JPEG', quality=90)
        result = formats.to_browser_image(photo, 'thumbnail')
        self.assertEqual(result['mime_type'], 'image/jpeg')
        self.assertLessEqual(max(result['width'], result['height']), formats.THUMBNAIL_MAX_EDGE)
        with Image.open(io.BytesIO(result['bytes'])) as thumbnail:
            self.assertEqual(thumbnail.size, (1024, 683))

    def test_thumbnail_keeps_transparency_as_png(self):
        transparent = encode(Image.new('RGBA', (2048, 1024), (0, 0, 0, 0)), 'PNG')
        result = formats.to_browser_image(transparent, 'thumbnail')
        self.assertEqual(result['mime_type'], 'image/png')
        with Image.open(io.BytesIO(result['bytes'])) as thumbnail:
            self.assertEqual(thumbnail.mode, 'RGBA')
            self.assertEqual(thumbnail.size, (1024, 512))

    def test_small_native_thumbnail_is_passed_through_but_bmp_is_encoded(self):
        small_png = encode(Image.new('RGB', (100, 80)), 'PNG')
        self.assertEqual(formats.to_browser_image(small_png, 'thumbnail')['bytes'], small_png)
        small_bmp = encode(Image.new('RGB', (100, 80), (5, 5, 5)), 'BMP')
        bmp_result = formats.to_browser_image(small_bmp, 'thumbnail')
        self.assertEqual(bmp_result['mime_type'], 'image/jpeg')
        self.assertTrue(bmp_result['converted'])

    def test_thumbnail_applies_exif_orientation(self):
        exif = Image.Exif()
        exif[0x0112] = 6
        rotated = encode(Image.new('RGB', (1600, 800), (200, 10, 10)), 'JPEG', exif=exif.tobytes())
        result = formats.to_browser_image(rotated, 'thumbnail')
        self.assertEqual((result['width'], result['height']), (512, 1024))

    def test_heic_is_passed_through_for_safari(self):
        heic = heif_bytes()
        for variant in formats.PREVIEW_VARIANTS:
            with self.subTest(variant=variant):
                result = formats.to_browser_image(heic, variant)
                self.assertEqual(result['mime_type'], 'image/heic')
                self.assertEqual(result['bytes'], heic)
                self.assertFalse(result['converted'])

    def test_rejects_unknown_variant_and_non_images(self):
        with self.assertRaises(formats.ImageFormatError) as unknown:
            formats.to_browser_image(encode(Image.new('RGB', (4, 4)), 'PNG'), 'original')
        self.assertEqual((unknown.exception.code, unknown.exception.status_code), ('invalid_preview_variant', 400))
        with self.assertRaises(formats.ImageFormatError) as not_image:
            formats.to_browser_image(b'plain text', 'thumbnail')
        self.assertEqual((not_image.exception.code, not_image.exception.status_code), ('invalid_image', 415))


class ModelImageTests(unittest.TestCase):
    def test_model_image_is_upright_bounded_and_metadata_free(self):
        exif = Image.Exif()
        exif[0x0112] = 6
        exif[0x010F] = 'TestCam'
        exif[0x0110] = 'Model 9'
        photo = encode(Image.new('RGB', (4000, 2000), (30, 60, 90)), 'JPEG', exif=exif.tobytes())
        prepared = formats.normalize_model_image(photo, ['image/png', 'image/jpeg'])
        self.assertEqual(prepared['mime_type'], 'image/jpeg')
        self.assertEqual(prepared['file_name'], 'reference.jpg')
        self.assertEqual((prepared['width'], prepared['height']), (1024, 2048))
        with Image.open(io.BytesIO(prepared['bytes'])) as decoded:
            self.assertEqual(decoded.size, (1024, 2048))
            self.assertEqual(len(decoded.getexif()), 0)
            self.assertNotIn('exif', decoded.info)

    def test_transparency_is_kept_as_png_when_allowed(self):
        palette = Image.new('P', (32, 32), 0)
        palette.info['transparency'] = 0
        prepared = formats.normalize_model_image(encode(palette, 'PNG'), ['image/png', 'image/jpeg'])
        self.assertEqual(prepared['mime_type'], 'image/png')
        with Image.open(io.BytesIO(prepared['bytes'])) as decoded:
            self.assertEqual(decoded.mode, 'RGBA')

    def test_transparency_is_flattened_when_only_jpeg_is_accepted(self):
        transparent = encode(Image.new('RGBA', (16, 16), (0, 0, 0, 0)), 'PNG')
        prepared = formats.normalize_model_image(transparent, ['image/jpeg'])
        self.assertEqual(prepared['mime_type'], 'image/jpeg')
        with Image.open(io.BytesIO(prepared['bytes'])) as decoded:
            self.assertEqual(decoded.mode, 'RGB')
            self.assertEqual(decoded.getpixel((4, 4)), (255, 255, 255))

    def test_accepted_formats_are_honored(self):
        rgb = encode(Image.new('RGB', (20, 20), (9, 9, 9)), 'BMP')
        self.assertEqual(formats.normalize_model_image(rgb, ['image/png'])['mime_type'], 'image/png')
        self.assertEqual(formats.normalize_model_image(rgb, ['image/webp'])['mime_type'], 'image/webp')
        self.assertEqual(formats.normalize_model_image(rgb, None)['mime_type'], 'image/jpeg')
        with self.assertRaises(formats.ImageFormatError) as refused:
            formats.normalize_model_image(rgb, ['image/gif'])
        self.assertEqual(refused.exception.code, 'unsupported_reference_format')

    def test_cmyk_and_16_bit_images_convert_to_rgb(self):
        cmyk = encode(Image.new('CMYK', (10, 10), (0, 255, 255, 0)), 'JPEG')
        with Image.open(io.BytesIO(formats.normalize_model_image(cmyk, ['image/png'])['bytes'])) as decoded:
            self.assertEqual(decoded.mode, 'RGB')
        deep = Image.new('I;16', (10, 10), 32768)
        with Image.open(io.BytesIO(formats.normalize_model_image(encode(deep, 'TIFF'), ['image/png'])['bytes'])) as decoded:
            self.assertEqual(decoded.mode, 'RGB')
            self.assertEqual(decoded.getpixel((1, 1)), (128, 128, 128))

    def test_first_tiff_page_is_the_reference(self):
        first = Image.new('RGB', (40, 40), (0, 255, 0))
        second = Image.new('RGB', (80, 80), (255, 0, 255))
        buffer = io.BytesIO()
        first.save(buffer, format='TIFF', save_all=True, append_images=[second])
        prepared = formats.normalize_model_image(buffer.getvalue(), ['image/png'])
        self.assertEqual((prepared['width'], prepared['height']), (40, 40))

    def test_byte_budget_shrinks_the_image(self):
        noisy = Image.effect_noise((1500, 1500), 90).convert('RGB')
        original = encode(noisy, 'PNG')
        prepared = formats.normalize_model_image(original, ['image/png'], max_bytes=900_000)
        self.assertLessEqual(len(prepared['bytes']), 900_000)
        self.assertLess(prepared['width'], 1500)
        with self.assertRaises(formats.ImageFormatError) as too_small:
            formats.normalize_model_image(original, ['image/png'], max_bytes=64)
        self.assertEqual((too_small.exception.code, too_small.exception.status_code), ('image_too_large', 413))

    def test_heif_and_unreadable_references_are_refused_with_stable_codes(self):
        for payload in (heif_bytes(), heif_bytes(b'mif1', (b'mif1',))):
            with self.subTest(payload=payload[:12]):
                with self.assertRaises(formats.ImageFormatError) as refused:
                    formats.normalize_model_image(payload, ['image/png'])
                self.assertEqual(refused.exception.code, 'unsupported_reference_format')
                self.assertEqual(refused.exception.status_code, 415)
                self.assertIn('JPG or PNG', refused.exception.public_message)
        with self.assertRaises(formats.ImageFormatError) as unreadable:
            formats.normalize_model_image(b'not an image at all', ['image/png'])
        self.assertEqual(unreadable.exception.code, 'unsupported_reference_format')

    def test_decompression_bombs_are_refused_before_decoding(self):
        for width, height in ((9000, 8000), (12000, 12000), (40000, 40000)):
            with self.subTest(size=(width, height)):
                bomb = png_header_only(width, height)
                with self.assertRaises(formats.ImageFormatError) as refused:
                    formats.to_browser_image(bomb, 'thumbnail')
                self.assertEqual((refused.exception.code, refused.exception.status_code), ('image_too_large', 413))
                with self.assertRaises(formats.ImageFormatError):
                    formats.normalize_model_image(bomb, ['image/png'])
                self.assertIsNone(formats.detect_image_format(bomb))

    def test_image_data_url(self):
        prepared = formats.normalize_model_image(encode(Image.new('RGB', (4, 4)), 'PNG'), ['image/png'])
        self.assertTrue(formats.image_data_url(prepared).startswith('data:image/png;base64,'))
        with self.assertRaises(formats.ImageFormatError):
            formats.image_data_url({'mime_type': 'text/plain', 'bytes': b'x'})

    def test_module_imports_without_application_configuration(self):
        probe = (
            'import sys; sys.path.insert(0, sys.argv[1]); import functions_image_formats; '
            "leaked = sorted(name for name in ('config', 'flask', 'functions_settings') if name in sys.modules); "
            'print(leaked); sys.exit(1 if leaked else 0)'
        )
        completed = subprocess.run(
            [sys.executable, '-c', probe, str(APP_ROOT)], capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == '__main__':
    unittest.main()
