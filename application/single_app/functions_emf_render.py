# functions_emf_render.py

"""Pure-Python EMF/WMF rasterizer.

Word stores pasted diagrams, SmartArt, and charts as EMF metafiles, and those are frequently the
most information-dense figures in a document. Neither Document Intelligence nor Content
Understanding accepts a metafile, so it has to be rasterized before it can be described.

Pillow only ships a metafile renderer on Windows, where it is backed by GDI, and the application
container is Linux distroless -- no shell, no package manager, so an external converter such as
LibreOffice or Inkscape is not an option. This module therefore renders the common EMF drawing
subset directly with Pillow, which is already a dependency and behaves identically on every
platform.

Scope: the record subset Office actually emits for diagrams -- path construction, filled and
stroked polygons, Bezier curves, rectangles and ellipses, pen and brush objects, world transforms,
and text runs. Records outside that subset are skipped rather than failing the render, so output
degrades in fidelity instead of disappearing. This is a description aid for search and citation,
not a pixel-accurate GDI reimplementation.
"""

import struct
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont


# --- EMF record types actually handled -------------------------------------------------------
EMR_HEADER = 1
EMR_POLYBEZIER = 2
EMR_POLYGON = 3
EMR_POLYLINE = 4
EMR_POLYBEZIERTO = 5
EMR_POLYLINETO = 6
EMR_POLYPOLYLINE = 7
EMR_POLYPOLYGON = 8
EMR_SETWINDOWEXTEX = 9
EMR_SETWINDOWORGEX = 10
EMR_SETVIEWPORTEXTEX = 11
EMR_SETVIEWPORTORGEX = 12
EMR_EOF = 14
EMR_SETPOLYFILLMODE = 19
EMR_SETTEXTCOLOR = 24
EMR_MOVETOEX = 27
EMR_SAVEDC = 33
EMR_RESTOREDC = 34
EMR_SETWORLDTRANSFORM = 35
EMR_MODIFYWORLDTRANSFORM = 36
EMR_SELECTOBJECT = 37
EMR_CREATEPEN = 38
EMR_CREATEBRUSHINDIRECT = 39
EMR_DELETEOBJECT = 40
EMR_ELLIPSE = 42
EMR_RECTANGLE = 43
EMR_ROUNDRECT = 44
EMR_LINETO = 54
EMR_BEGINPATH = 59
EMR_ENDPATH = 60
EMR_CLOSEFIGURE = 61
EMR_FILLPATH = 62
EMR_STROKEANDFILLPATH = 63
EMR_STROKEPATH = 64
EMR_EXTTEXTOUTA = 83
EMR_EXTTEXTOUTW = 84
EMR_POLYBEZIER16 = 85
EMR_POLYGON16 = 86
EMR_POLYLINE16 = 87
EMR_POLYBEZIERTO16 = 88
EMR_POLYLINETO16 = 89
EMR_POLYPOLYLINE16 = 90
EMR_POLYPOLYGON16 = 91
EMR_EXTCREATEPEN = 95

# Stock object handles have the high bit set.
STOCK_OBJECT_FLAG = 0x80000000
STOCK_WHITE_BRUSH = 0x80000000
STOCK_LTGRAY_BRUSH = 0x80000001
STOCK_GRAY_BRUSH = 0x80000002
STOCK_DKGRAY_BRUSH = 0x80000003
STOCK_BLACK_BRUSH = 0x80000004
STOCK_NULL_BRUSH = 0x80000005
STOCK_WHITE_PEN = 0x80000006
STOCK_BLACK_PEN = 0x80000007
STOCK_NULL_PEN = 0x80000008

BRUSH_STYLE_NULL = 1
PEN_STYLE_NULL = 5

# Guard rails for untrusted input.
EMF_MAX_RECORDS = 200000
EMF_MAX_POINTS_PER_RECORD = 100000
EMF_MAX_OUTPUT_PIXELS = 4000
EMF_MIN_OUTPUT_PIXELS = 16
EMF_SUPERSAMPLE = 2
BEZIER_SEGMENTS = 12


class _GraphicsState:
    """The subset of GDI device-context state this renderer tracks."""

    def __init__(self):
        self.transform = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        self.pen_color = (0, 0, 0)
        self.pen_width = 1.0
        self.pen_visible = True
        self.brush_color = (255, 255, 255)
        self.brush_visible = True
        self.text_color = (0, 0, 0)

    def copy(self):
        clone = _GraphicsState()
        clone.__dict__.update(self.__dict__)
        return clone


def _colorref_to_rgb(value):
    """COLORREF is 0x00BBGGRR."""
    return (value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF)


def _multiply_transform(left, right):
    """Compose two 2D affine transforms stored as (m11, m12, m21, m22, dx, dy)."""
    a11, a12, a21, a22, adx, ady = left
    b11, b12, b21, b22, bdx, bdy = right
    return (
        a11 * b11 + a12 * b21,
        a11 * b12 + a12 * b22,
        a21 * b11 + a22 * b21,
        a21 * b12 + a22 * b22,
        adx * b11 + ady * b21 + bdx,
        adx * b12 + ady * b22 + bdy,
    )


def _flatten_bezier(points):
    """Flatten a sequence of cubic Bezier segments into a polyline."""
    if len(points) < 4:
        return list(points)

    flattened = [points[0]]
    for start in range(0, len(points) - 3, 3):
        p0, p1, p2, p3 = points[start:start + 4]
        for step in range(1, BEZIER_SEGMENTS + 1):
            t = step / BEZIER_SEGMENTS
            inv = 1.0 - t
            x = (inv ** 3) * p0[0] + 3 * (inv ** 2) * t * p1[0] + 3 * inv * (t ** 2) * p2[0] + (t ** 3) * p3[0]
            y = (inv ** 3) * p0[1] + 3 * (inv ** 2) * t * p1[1] + 3 * inv * (t ** 2) * p2[1] + (t ** 3) * p3[1]
            flattened.append((x, y))
    return flattened


class EmfRenderer:
    """Parse an EMF byte string and rasterize the supported drawing records."""

    def __init__(self, data, max_pixels=1600):
        self.data = data
        self.max_pixels = max_pixels
        self.state = _GraphicsState()
        self.state_stack = []
        self.objects = {}
        self.current_point = (0.0, 0.0)
        self.path = []
        self.current_subpath = []
        self.in_path = False
        self.text_runs = []
        self.records_drawn = 0
        self.image = None
        self.draw = None
        self.scale = 1.0
        self.origin = (0.0, 0.0)
        self.size = (0, 0)

    # --- coordinate mapping ------------------------------------------------------------------
    def _to_device(self, point):
        m11, m12, m21, m22, dx, dy = self.state.transform
        x, y = point
        return (m11 * x + m21 * y + dx, m12 * x + m22 * y + dy)

    def _to_pixels(self, point):
        device_x, device_y = self._to_device(point)
        return (
            (device_x - self.origin[0]) * self.scale,
            (device_y - self.origin[1]) * self.scale,
        )

    def _map_points(self, points):
        return [self._to_pixels(point) for point in points]

    # --- record payload readers --------------------------------------------------------------
    @staticmethod
    def _read_points16(payload, offset):
        """Read the bounds + count + 16-bit point array shared by the *16 records."""
        if len(payload) < offset + 4:
            return []
        count = struct.unpack_from('<I', payload, offset)[0]
        if count == 0 or count > EMF_MAX_POINTS_PER_RECORD:
            return []
        start = offset + 4
        if len(payload) < start + count * 4:
            return []
        raw = struct.unpack_from(f'<{count * 2}h', payload, start)
        return [(float(raw[i]), float(raw[i + 1])) for i in range(0, len(raw), 2)]

    @staticmethod
    def _read_points32(payload, offset):
        if len(payload) < offset + 4:
            return []
        count = struct.unpack_from('<I', payload, offset)[0]
        if count == 0 or count > EMF_MAX_POINTS_PER_RECORD:
            return []
        start = offset + 4
        if len(payload) < start + count * 8:
            return []
        raw = struct.unpack_from(f'<{count * 2}i', payload, start)
        return [(float(raw[i]), float(raw[i + 1])) for i in range(0, len(raw), 2)]

    # --- drawing -----------------------------------------------------------------------------
    def _stroke(self, points, close=False):
        if not self.state.pen_visible or len(points) < 2:
            return
        pixels = [(round(x), round(y)) for x, y in points]
        if close:
            pixels = pixels + [pixels[0]]
        width = max(1, int(round(self.state.pen_width * self.scale)))
        self.draw.line(pixels, fill=self.state.pen_color, width=width, joint='curve')
        self.records_drawn += 1

    def _fill(self, points):
        if not self.state.brush_visible or len(points) < 3:
            return
        pixels = [(round(x), round(y)) for x, y in points]
        try:
            self.draw.polygon(pixels, fill=self.state.brush_color)
            self.records_drawn += 1
        except (ValueError, TypeError):
            pass

    def _flush_current_subpath(self):
        if len(self.current_subpath) >= 2:
            self.path.append(list(self.current_subpath))
        self.current_subpath = []

    def _render_path(self, fill, stroke):
        self._flush_current_subpath()
        for subpath in self.path:
            mapped = self._map_points(subpath)
            if fill:
                self._fill(mapped)
            if stroke:
                self._stroke(mapped)
        self.path = []

    # --- object table ------------------------------------------------------------------------
    def _select_stock_object(self, handle):
        if handle == STOCK_NULL_BRUSH:
            self.state.brush_visible = False
        elif handle in (STOCK_WHITE_BRUSH, STOCK_LTGRAY_BRUSH, STOCK_GRAY_BRUSH,
                        STOCK_DKGRAY_BRUSH, STOCK_BLACK_BRUSH):
            shades = {
                STOCK_WHITE_BRUSH: (255, 255, 255),
                STOCK_LTGRAY_BRUSH: (192, 192, 192),
                STOCK_GRAY_BRUSH: (128, 128, 128),
                STOCK_DKGRAY_BRUSH: (64, 64, 64),
                STOCK_BLACK_BRUSH: (0, 0, 0),
            }
            self.state.brush_color = shades[handle]
            self.state.brush_visible = True
        elif handle == STOCK_NULL_PEN:
            self.state.pen_visible = False
        elif handle in (STOCK_WHITE_PEN, STOCK_BLACK_PEN):
            self.state.pen_color = (255, 255, 255) if handle == STOCK_WHITE_PEN else (0, 0, 0)
            self.state.pen_visible = True
            self.state.pen_width = 1.0

    def _select_object(self, handle):
        if handle & STOCK_OBJECT_FLAG:
            self._select_stock_object(handle)
            return
        entry = self.objects.get(handle)
        if not entry:
            return
        kind, payload = entry
        if kind == 'brush':
            color, visible = payload
            self.state.brush_color = color
            self.state.brush_visible = visible
        elif kind == 'pen':
            color, width, visible = payload
            self.state.pen_color = color
            self.state.pen_width = width
            self.state.pen_visible = visible

    # --- header ------------------------------------------------------------------------------
    def _parse_header(self, payload):
        if len(payload) < 32:
            return None
        bounds = struct.unpack_from('<4i', payload, 0)
        left, top, right, bottom = bounds
        width = right - left
        height = bottom - top
        if width <= 0 or height <= 0:
            return None
        return (left, top, width, height)

    def render(self):
        """Rasterize the metafile. Returns a PIL Image, or None when nothing could be drawn."""
        data = self.data
        if len(data) < 88:
            return None

        record_type, record_size = struct.unpack_from('<II', data, 0)
        if record_type != EMR_HEADER or record_size < 88 or record_size > len(data):
            return None

        header_bounds = self._parse_header(data[8:record_size])
        if header_bounds is None:
            return None

        left, top, logical_width, logical_height = header_bounds

        longest_edge = max(logical_width, logical_height)
        target_scale = min(1.0, float(self.max_pixels) / float(longest_edge)) if longest_edge else 1.0
        output_width = max(EMF_MIN_OUTPUT_PIXELS, min(EMF_MAX_OUTPUT_PIXELS, int(logical_width * target_scale)))
        output_height = max(EMF_MIN_OUTPUT_PIXELS, min(EMF_MAX_OUTPUT_PIXELS, int(logical_height * target_scale)))

        self.scale = (output_width / logical_width) * EMF_SUPERSAMPLE
        self.origin = (left, top)
        canvas_size = (output_width * EMF_SUPERSAMPLE, output_height * EMF_SUPERSAMPLE)
        self.size = (output_width, output_height)

        self.image = Image.new('RGB', canvas_size, (255, 255, 255))
        self.draw = ImageDraw.Draw(self.image)

        self._walk_records(data)

        if self.records_drawn == 0 and not self.text_runs:
            return None

        return self.image.resize(self.size, Image.LANCZOS)

    def _walk_records(self, data):
        offset = 0
        records = 0
        length = len(data)

        while offset + 8 <= length and records < EMF_MAX_RECORDS:
            record_type, record_size = struct.unpack_from('<II', data, offset)
            if record_size < 8 or offset + record_size > length:
                break
            payload = data[offset + 8: offset + record_size]
            records += 1
            offset += record_size

            if record_type == EMR_EOF:
                break
            try:
                self._handle_record(record_type, payload)
            except (struct.error, ValueError, IndexError, TypeError):
                # A malformed record must not abort the whole render.
                continue

    def _handle_record(self, record_type, payload):
        state = self.state

        if record_type == EMR_SAVEDC:
            self.state_stack.append(state.copy())

        elif record_type == EMR_RESTOREDC:
            if self.state_stack:
                self.state = self.state_stack.pop()

        elif record_type == EMR_SETWORLDTRANSFORM:
            state.transform = struct.unpack_from('<6f', payload, 0)

        elif record_type == EMR_MODIFYWORLDTRANSFORM:
            xform = struct.unpack_from('<6f', payload, 0)
            mode = struct.unpack_from('<I', payload, 24)[0]
            if mode == 1:      # MWT_IDENTITY
                state.transform = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
            elif mode == 2:    # MWT_LEFTMULTIPLY
                state.transform = _multiply_transform(xform, state.transform)
            elif mode == 3:    # MWT_RIGHTMULTIPLY
                state.transform = _multiply_transform(state.transform, xform)
            elif mode == 4:    # MWT_SET
                state.transform = xform

        elif record_type == EMR_CREATEBRUSHINDIRECT:
            handle = struct.unpack_from('<I', payload, 0)[0]
            brush_style, color = struct.unpack_from('<II', payload, 4)
            self.objects[handle] = ('brush', (_colorref_to_rgb(color), brush_style != BRUSH_STYLE_NULL))

        elif record_type == EMR_CREATEPEN:
            handle = struct.unpack_from('<I', payload, 0)[0]
            pen_style, width_x = struct.unpack_from('<Ii', payload, 4)
            color = struct.unpack_from('<I', payload, 16)[0]
            self.objects[handle] = (
                'pen',
                (_colorref_to_rgb(color), max(1.0, float(width_x)), pen_style != PEN_STYLE_NULL),
            )

        elif record_type == EMR_EXTCREATEPEN:
            handle = struct.unpack_from('<I', payload, 0)[0]
            pen_style, width = struct.unpack_from('<II', payload, 20)
            color = struct.unpack_from('<I', payload, 32)[0]
            self.objects[handle] = (
                'pen',
                (_colorref_to_rgb(color), max(1.0, float(width)), (pen_style & 0xF) != PEN_STYLE_NULL),
            )

        elif record_type == EMR_SELECTOBJECT:
            self._select_object(struct.unpack_from('<I', payload, 0)[0])

        elif record_type == EMR_DELETEOBJECT:
            self.objects.pop(struct.unpack_from('<I', payload, 0)[0], None)

        elif record_type == EMR_SETTEXTCOLOR:
            state.text_color = _colorref_to_rgb(struct.unpack_from('<I', payload, 0)[0])

        elif record_type == EMR_BEGINPATH:
            self.in_path = True
            self.path = []
            self.current_subpath = []

        elif record_type == EMR_ENDPATH:
            self.in_path = False
            self._flush_current_subpath()

        elif record_type == EMR_CLOSEFIGURE:
            if len(self.current_subpath) >= 2:
                self.current_subpath.append(self.current_subpath[0])
            self._flush_current_subpath()

        elif record_type == EMR_FILLPATH:
            self._render_path(fill=True, stroke=False)

        elif record_type == EMR_STROKEPATH:
            self._render_path(fill=False, stroke=True)

        elif record_type == EMR_STROKEANDFILLPATH:
            self._render_path(fill=True, stroke=True)

        elif record_type == EMR_MOVETOEX:
            x, y = struct.unpack_from('<2i', payload, 0)
            self._flush_current_subpath()
            self.current_point = (float(x), float(y))
            self.current_subpath = [self.current_point]

        elif record_type == EMR_LINETO:
            x, y = struct.unpack_from('<2i', payload, 0)
            point = (float(x), float(y))
            if not self.current_subpath:
                self.current_subpath = [self.current_point]
            self.current_subpath.append(point)
            self.current_point = point
            if not self.in_path:
                self._stroke(self._map_points(self.current_subpath[-2:]))

        elif record_type in (EMR_POLYGON16, EMR_POLYLINE16, EMR_POLYBEZIER16):
            points = self._read_points16(payload, 16)
            if record_type == EMR_POLYBEZIER16:
                points = _flatten_bezier(points)
            self._draw_standalone(record_type, points)

        elif record_type in (EMR_POLYGON, EMR_POLYLINE, EMR_POLYBEZIER):
            points = self._read_points32(payload, 16)
            if record_type == EMR_POLYBEZIER:
                points = _flatten_bezier(points)
            self._draw_standalone(record_type, points)

        elif record_type in (EMR_POLYLINETO16, EMR_POLYBEZIERTO16):
            points = self._read_points16(payload, 16)
            if record_type == EMR_POLYBEZIERTO16:
                points = _flatten_bezier([self.current_point] + points)
            self._append_to_current(points)

        elif record_type in (EMR_POLYLINETO, EMR_POLYBEZIERTO):
            points = self._read_points32(payload, 16)
            if record_type == EMR_POLYBEZIERTO:
                points = _flatten_bezier([self.current_point] + points)
            self._append_to_current(points)

        elif record_type in (EMR_POLYPOLYGON16, EMR_POLYPOLYLINE16):
            self._draw_poly_poly(payload, record_type == EMR_POLYPOLYGON16)

        elif record_type == EMR_RECTANGLE:
            left, top, right, bottom = struct.unpack_from('<4i', payload, 0)
            corners = [(left, top), (right, top), (right, bottom), (left, bottom)]
            mapped = self._map_points([(float(x), float(y)) for x, y in corners])
            self._fill(mapped)
            self._stroke(mapped, close=True)

        elif record_type in (EMR_ELLIPSE, EMR_ROUNDRECT):
            left, top, right, bottom = struct.unpack_from('<4i', payload, 0)
            mapped = self._map_points([
                (float(left), float(top)), (float(right), float(top)),
                (float(right), float(bottom)), (float(left), float(bottom)),
            ])
            xs = [p[0] for p in mapped]
            ys = [p[1] for p in mapped]
            box = [round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))]
            if box[2] > box[0] and box[3] > box[1]:
                shape = self.draw.ellipse if record_type == EMR_ELLIPSE else self.draw.rectangle
                if self.state.brush_visible:
                    shape(box, fill=self.state.brush_color)
                    self.records_drawn += 1
                if self.state.pen_visible:
                    shape(box, outline=self.state.pen_color,
                          width=max(1, int(round(self.state.pen_width * self.scale))))
                    self.records_drawn += 1

        elif record_type in (EMR_EXTTEXTOUTW, EMR_EXTTEXTOUTA):
            self._handle_text(record_type, payload)

    def _draw_standalone(self, record_type, points):
        if not points:
            return
        if self.in_path:
            self._flush_current_subpath()
            self.path.append(points)
            return
        mapped = self._map_points(points)
        if record_type in (EMR_POLYGON16, EMR_POLYGON):
            self._fill(mapped)
            self._stroke(mapped, close=True)
        else:
            self._stroke(mapped)

    def _append_to_current(self, points):
        if not points:
            return
        if not self.current_subpath:
            self.current_subpath = [self.current_point]
        self.current_subpath.extend(points)
        self.current_point = points[-1]
        if not self.in_path:
            self._stroke(self._map_points(self.current_subpath))
            self.current_subpath = [self.current_point]

    def _draw_poly_poly(self, payload, filled):
        polygon_count, total_points = struct.unpack_from('<II', payload, 16)
        if polygon_count == 0 or polygon_count > 10000 or total_points > EMF_MAX_POINTS_PER_RECORD:
            return
        counts = struct.unpack_from(f'<{polygon_count}I', payload, 24)
        offset = 24 + polygon_count * 4
        for count in counts:
            if count == 0 or count > EMF_MAX_POINTS_PER_RECORD:
                break
            if len(payload) < offset + count * 4:
                break
            raw = struct.unpack_from(f'<{count * 2}h', payload, offset)
            points = [(float(raw[i]), float(raw[i + 1])) for i in range(0, len(raw), 2)]
            offset += count * 4
            mapped = self._map_points(points)
            if filled:
                self._fill(mapped)
                self._stroke(mapped, close=True)
            else:
                self._stroke(mapped)

    def _handle_text(self, record_type, payload):
        """Record a text run and draw it approximately.

        EMR_EXTTEXTOUT payload layout: rclBounds(16), iGraphicsMode(4), exScale(4), eyScale(4),
        then the EmrText struct: ptlReference(8), nChars(4), offString(4), fOptions(4), rcl(16),
        offDx(4). ``offString`` is measured from the start of the record, which begins 8 bytes
        before this payload.
        """
        if len(payload) < 44:
            return

        reference_x, reference_y = struct.unpack_from('<2i', payload, 28)
        char_count, string_offset = struct.unpack_from('<II', payload, 36)
        if char_count == 0 or char_count > 8192:
            return

        start = string_offset - 8
        if start < 0:
            return

        if record_type == EMR_EXTTEXTOUTW:
            byte_length = char_count * 2
            if len(payload) < start + byte_length:
                return
            text = payload[start:start + byte_length].decode('utf-16-le', errors='ignore')
        else:
            if len(payload) < start + char_count:
                return
            text = payload[start:start + char_count].decode('latin-1', errors='ignore')

        text = text.replace('\x00', '').strip()
        if not text:
            return

        self.text_runs.append(text)

        pixel_x, pixel_y = self._to_pixels((float(reference_x), float(reference_y)))
        if not (0 <= pixel_x < self.image.width and 0 <= pixel_y < self.image.height):
            return
        try:
            font_size = max(8, int(round(11 * self.scale)))
            font = ImageFont.load_default(size=font_size)
        except (AttributeError, TypeError, OSError):
            font = None
        try:
            self.draw.text((pixel_x, pixel_y), text, fill=self.state.text_color, font=font)
            self.records_drawn += 1
        except (ValueError, OSError):
            pass


WMF_PLACEABLE_KEY = 0x9AC6CDD7

META_SETWINDOWORG = 0x020B
META_SETWINDOWEXT = 0x020C
META_LINETO = 0x0213
META_MOVETO = 0x0214
META_POLYGON = 0x0324
META_POLYLINE = 0x0325
META_ELLIPSE = 0x0418
META_RECTANGLE = 0x041B
META_ROUNDRECT = 0x061C
META_POLYPOLYGON = 0x0538
META_TEXTOUT = 0x0521
META_EXTTEXTOUT = 0x0A32
META_SELECTOBJECT = 0x012D
META_DELETEOBJECT = 0x01F0
META_CREATEPENINDIRECT = 0x02FA
META_CREATEBRUSHINDIRECT = 0x02FC
META_SETTEXTCOLOR = 0x0209
META_SAVEDC = 0x001E
META_RESTOREDC = 0x0127


def _looks_like_wmf(data):
    """Return True for a placeable or standard WMF header."""
    if len(data) < 18:
        return False
    if struct.unpack_from('<I', data, 0)[0] == WMF_PLACEABLE_KEY:
        return True
    meta_type, header_size = struct.unpack_from('<HH', data, 0)
    return meta_type in (1, 2) and header_size == 9


class WmfRenderer(EmfRenderer):
    """Render the common WMF record subset, reusing the EMF drawing primitives.

    WMF predates EMF and uses 16-bit records with a window-based coordinate system rather than a
    world transform, so only the record walker and coordinate setup differ.
    """

    def __init__(self, data, max_pixels=1600):
        super().__init__(data, max_pixels=max_pixels)
        self.window_origin = (0.0, 0.0)
        self.window_extent = None
        self.object_table = []

    def render(self):
        data = self.data
        offset = 0
        placeable_bounds = None

        if struct.unpack_from('<I', data, 0)[0] == WMF_PLACEABLE_KEY:
            left, top, right, bottom = struct.unpack_from('<4h', data, 6)
            units_per_inch = struct.unpack_from('<H', data, 14)[0] or 1440
            placeable_bounds = (left, top, right, bottom, units_per_inch)
            offset = 22

        if len(data) < offset + 18:
            return None
        offset += 18  # standard WMF header

        # A first pass establishes the logical extent so coordinates can be mapped.
        self._scan_window(data, offset)

        if self.window_extent and self.window_extent[0] and self.window_extent[1]:
            logical_width = abs(self.window_extent[0])
            logical_height = abs(self.window_extent[1])
            self.origin = self.window_origin
        elif placeable_bounds:
            left, top, right, bottom, _units = placeable_bounds
            logical_width = abs(right - left) or 1
            logical_height = abs(bottom - top) or 1
            self.origin = (float(left), float(top))
        else:
            return None

        longest_edge = max(logical_width, logical_height)
        target_scale = min(1.0, float(self.max_pixels) / float(longest_edge)) if longest_edge else 1.0
        output_width = max(EMF_MIN_OUTPUT_PIXELS, min(EMF_MAX_OUTPUT_PIXELS, int(logical_width * target_scale)))
        output_height = max(EMF_MIN_OUTPUT_PIXELS, min(EMF_MAX_OUTPUT_PIXELS, int(logical_height * target_scale)))

        self.scale = (output_width / logical_width) * EMF_SUPERSAMPLE
        self.size = (output_width, output_height)
        self.image = Image.new('RGB', (output_width * EMF_SUPERSAMPLE, output_height * EMF_SUPERSAMPLE), (255, 255, 255))
        self.draw = ImageDraw.Draw(self.image)

        self._walk_wmf_records(data, offset)

        if self.records_drawn == 0 and not self.text_runs:
            return None
        return self.image.resize(self.size, Image.LANCZOS)

    def _scan_window(self, data, offset):
        records = 0
        length = len(data)
        while offset + 6 <= length and records < EMF_MAX_RECORDS:
            record_words, function = struct.unpack_from('<IH', data, offset)
            record_bytes = record_words * 2
            if record_bytes < 6 or offset + record_bytes > length:
                break
            params = data[offset + 6: offset + record_bytes]
            if function == META_SETWINDOWORG and len(params) >= 4:
                y, x = struct.unpack_from('<2h', params, 0)
                self.window_origin = (float(x), float(y))
            elif function == META_SETWINDOWEXT and len(params) >= 4:
                height, width = struct.unpack_from('<2h', params, 0)
                self.window_extent = (float(width), float(height))
            offset += record_bytes
            records += 1

    def _walk_wmf_records(self, data, offset):
        records = 0
        length = len(data)
        while offset + 6 <= length and records < EMF_MAX_RECORDS:
            record_words, function = struct.unpack_from('<IH', data, offset)
            record_bytes = record_words * 2
            if record_bytes < 6 or offset + record_bytes > length:
                break
            params = data[offset + 6: offset + record_bytes]
            offset += record_bytes
            records += 1
            if function == 0:
                break
            try:
                self._handle_wmf_record(function, params)
            except (struct.error, ValueError, IndexError, TypeError):
                continue

    def _add_object(self, entry):
        for index, existing in enumerate(self.object_table):
            if existing is None:
                self.object_table[index] = entry
                return
        self.object_table.append(entry)

    def _handle_wmf_record(self, function, params):
        state = self.state

        if function == META_SAVEDC:
            self.state_stack.append(state.copy())

        elif function == META_RESTOREDC:
            if self.state_stack:
                self.state = self.state_stack.pop()

        elif function == META_CREATEBRUSHINDIRECT and len(params) >= 8:
            brush_style, color = struct.unpack_from('<HI', params, 0)
            self._add_object(('brush', (_colorref_to_rgb(color), brush_style != BRUSH_STYLE_NULL)))

        elif function == META_CREATEPENINDIRECT and len(params) >= 10:
            pen_style, width = struct.unpack_from('<Hh', params, 0)
            color = struct.unpack_from('<I', params, 6)[0]
            self._add_object(('pen', (_colorref_to_rgb(color), max(1.0, float(width)), pen_style != PEN_STYLE_NULL)))

        elif function == META_SELECTOBJECT and len(params) >= 2:
            index = struct.unpack_from('<H', params, 0)[0]
            if 0 <= index < len(self.object_table):
                entry = self.object_table[index]
                if entry:
                    kind, payload = entry
                    if kind == 'brush':
                        state.brush_color, state.brush_visible = payload
                    else:
                        state.pen_color, state.pen_width, state.pen_visible = payload

        elif function == META_DELETEOBJECT and len(params) >= 2:
            index = struct.unpack_from('<H', params, 0)[0]
            if 0 <= index < len(self.object_table):
                self.object_table[index] = None

        elif function == META_SETTEXTCOLOR and len(params) >= 4:
            state.text_color = _colorref_to_rgb(struct.unpack_from('<I', params, 0)[0])

        elif function == META_MOVETO and len(params) >= 4:
            y, x = struct.unpack_from('<2h', params, 0)
            self.current_point = (float(x), float(y))

        elif function == META_LINETO and len(params) >= 4:
            y, x = struct.unpack_from('<2h', params, 0)
            end_point = (float(x), float(y))
            self._stroke(self._map_points([self.current_point, end_point]))
            self.current_point = end_point

        elif function in (META_POLYGON, META_POLYLINE) and len(params) >= 2:
            count = struct.unpack_from('<H', params, 0)[0]
            if count and count <= EMF_MAX_POINTS_PER_RECORD and len(params) >= 2 + count * 4:
                raw = struct.unpack_from(f'<{count * 2}h', params, 2)
                points = [(float(raw[i]), float(raw[i + 1])) for i in range(0, len(raw), 2)]
                mapped = self._map_points(points)
                if function == META_POLYGON:
                    self._fill(mapped)
                    self._stroke(mapped, close=True)
                else:
                    self._stroke(mapped)

        elif function == META_POLYPOLYGON and len(params) >= 2:
            polygon_count = struct.unpack_from('<H', params, 0)[0]
            if polygon_count and polygon_count <= 10000 and len(params) >= 2 + polygon_count * 2:
                counts = struct.unpack_from(f'<{polygon_count}H', params, 2)
                point_offset = 2 + polygon_count * 2
                for count in counts:
                    if not count or len(params) < point_offset + count * 4:
                        break
                    raw = struct.unpack_from(f'<{count * 2}h', params, point_offset)
                    points = [(float(raw[i]), float(raw[i + 1])) for i in range(0, len(raw), 2)]
                    point_offset += count * 4
                    mapped = self._map_points(points)
                    self._fill(mapped)
                    self._stroke(mapped, close=True)

        elif function in (META_RECTANGLE, META_ELLIPSE, META_ROUNDRECT) and len(params) >= 8:
            # Parameters are stored bottom, right, top, left.
            bottom, right, top, left = struct.unpack_from('<4h', params, 0)
            mapped = self._map_points([
                (float(left), float(top)), (float(right), float(top)),
                (float(right), float(bottom)), (float(left), float(bottom)),
            ])
            if function == META_RECTANGLE or function == META_ROUNDRECT:
                self._fill(mapped)
                self._stroke(mapped, close=True)
            else:
                xs = [p[0] for p in mapped]
                ys = [p[1] for p in mapped]
                box = [round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))]
                if box[2] > box[0] and box[3] > box[1]:
                    if state.brush_visible:
                        self.draw.ellipse(box, fill=state.brush_color)
                        self.records_drawn += 1
                    if state.pen_visible:
                        self.draw.ellipse(box, outline=state.pen_color,
                                          width=max(1, int(round(state.pen_width * self.scale))))
                        self.records_drawn += 1

        elif function in (META_TEXTOUT, META_EXTTEXTOUT):
            self._handle_wmf_text(function, params)

    def _handle_wmf_text(self, function, params):
        if function == META_TEXTOUT:
            if len(params) < 2:
                return
            char_count = struct.unpack_from('<H', params, 0)[0]
            if not char_count or char_count > 8192 or len(params) < 2 + char_count:
                return
            raw_text = params[2:2 + char_count]
            padded = char_count + (char_count % 2)
            if len(params) >= 2 + padded + 4:
                y, x = struct.unpack_from('<2h', params, 2 + padded)
            else:
                y, x = 0, 0
        else:
            if len(params) < 8:
                return
            y, x, char_count = struct.unpack_from('<3h', params, 0)
            char_count = max(0, char_count)
            if not char_count or char_count > 8192:
                return
            options = struct.unpack_from('<H', params, 6)[0]
            text_offset = 8 + (8 if options & 0x0006 else 0)
            if len(params) < text_offset + char_count:
                return
            raw_text = params[text_offset:text_offset + char_count]

        text = raw_text.decode('latin-1', errors='ignore').replace('\x00', '').strip()
        if not text:
            return
        self.text_runs.append(text)

        pixel_x, pixel_y = self._to_pixels((float(x), float(y)))
        if not (0 <= pixel_x < self.image.width and 0 <= pixel_y < self.image.height):
            return
        try:
            font = ImageFont.load_default(size=max(8, int(round(11 * self.scale))))
        except (AttributeError, TypeError, OSError):
            font = None
        try:
            self.draw.text((pixel_x, pixel_y), text, fill=self.state.text_color, font=font)
            self.records_drawn += 1
        except (ValueError, OSError):
            pass


def render_metafile_to_png(data, max_pixels=1600):
    """Rasterize EMF/WMF bytes to PNG bytes.

    Returns ``(png_bytes, width, height, text, reason)``. On failure ``png_bytes`` is None and
    ``reason`` explains why.
    """
    if not data or len(data) < 32:
        return None, 0, 0, '', 'metafile_too_small'

    # The EMF header carries the ASCII signature " EMF" at offset 40. Checking it is the reliable
    # way to tell EMF from WMF, because an EMF also begins with bytes that look like a WMF type.
    if len(data) >= 88 and data[40:44] == b' EMF':
        renderer_factory = EmfRenderer
    elif _looks_like_wmf(data):
        renderer_factory = WmfRenderer
    else:
        return None, 0, 0, '', 'unrecognized_metafile_format'

    try:
        renderer = renderer_factory(data, max_pixels=max_pixels)
        image = renderer.render()
    except Exception as render_error:
        return None, 0, 0, '', f'metafile_render_failed ({type(render_error).__name__})'

    if image is None:
        return None, 0, 0, '', 'metafile_had_no_drawable_records'

    buffer = BytesIO()
    image.save(buffer, format='PNG')
    text = '\n'.join(dict.fromkeys(run for run in renderer.text_runs if run))
    return buffer.getvalue(), image.width, image.height, text, ''
