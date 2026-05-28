from typing import Dict, List, Any


def draw_image_primitives(
    output_path: str,
    width: int,
    height: int,
    background_color: List[float] = [0.0, 0.0, 0.0, 0.0],
    primitives: List[Dict[str, Any]] = None,
    overwrite: bool = True,
) -> Dict[str, Any]:
    """Draw simple vector primitives into an RGBA image.

    This is a generic procedural texture helper for labels, decals, masks,
    signs, UI textures, packaging mockups, material debugging, and annotation
    plates. Supported primitive types are rect, ellipse, line, polygon, and
    text. Coordinates can be provided in pixels or normalized image space.
    """
    import os

    try:
        from PySide6.QtCore import Qt, QRectF, QPointF
        from PySide6.QtGui import QImage, QPainter, QColor, QPen, QBrush, QFont, QPolygonF
    except Exception:
        try:
            from PySide2.QtCore import Qt, QRectF, QPointF
            from PySide2.QtGui import QImage, QPainter, QColor, QPen, QBrush, QFont, QPolygonF
        except Exception as exc:
            raise RuntimeError("PySide QImage is required to draw image primitives in Maya.") from exc

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _clamp(value, lower=0.0, upper=1.0):
        return max(lower, min(upper, value))

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return value

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(value) for value in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(value) for value in values]

    def _validate_color(values, arg_name):
        color = _validate_vector(values, 4, arg_name)
        if max(color) > 1.0:
            color = [value / 255.0 for value in color]
        return [_clamp(value) for value in color]

    def _make_color(values):
        color = QColor()
        color.setRgbF(values[0], values[1], values[2], values[3])
        return color

    def _qt_enum(group_name, value_name, fallback_name=None):
        if hasattr(Qt, value_name):
            return getattr(Qt, value_name)
        if hasattr(Qt, group_name):
            group = getattr(Qt, group_name)
            if hasattr(group, value_name):
                return getattr(group, value_name)
            if fallback_name and hasattr(group, fallback_name):
                return getattr(group, fallback_name)
        raise AttributeError(value_name)

    def _set_antialiasing(painter):
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
        except AttributeError:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    def _rect_from_primitive(primitive, arg_prefix):
        bbox_pixels = primitive.get("bbox_pixels")
        bbox_normalized = primitive.get("bbox_normalized")
        if bbox_pixels is not None and bbox_normalized is not None:
            raise ValueError(f"{arg_prefix} cannot provide both bbox_pixels and bbox_normalized.")
        if bbox_normalized is not None:
            values = _validate_vector(bbox_normalized, 4, f"{arg_prefix}.bbox_normalized")
            x0 = values[0] * width
            y0 = values[1] * height
            x1 = values[2] * width
            y1 = values[3] * height
        elif bbox_pixels is not None:
            values = _validate_vector(bbox_pixels, 4, f"{arg_prefix}.bbox_pixels")
            x0, y0, x1, y1 = values
        else:
            raise ValueError(f"{arg_prefix} requires bbox_pixels or bbox_normalized.")
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        return QRectF(x0, y0, max(0.0, x1 - x0), max(0.0, y1 - y0)), [x0, y0, x1, y1]

    def _points_from_primitive(primitive, arg_prefix):
        points_pixels = primitive.get("points_pixels")
        points_normalized = primitive.get("points_normalized")
        if points_pixels is not None and points_normalized is not None:
            raise ValueError(f"{arg_prefix} cannot provide both points_pixels and points_normalized.")
        if points_normalized is not None:
            source = points_normalized
            normalized = True
        elif points_pixels is not None:
            source = points_pixels
            normalized = False
        else:
            raise ValueError(f"{arg_prefix} requires points_pixels or points_normalized.")
        if not isinstance(source, list) or len(source) < 2:
            raise ValueError(f"{arg_prefix} points must contain at least two [x, y] pairs.")
        points = []
        clean = []
        for index, point in enumerate(source):
            values = _validate_vector(point, 2, f"{arg_prefix}.points[{index}]")
            x = values[0] * width if normalized else values[0]
            y = values[1] * height if normalized else values[1]
            points.append(QPointF(x, y))
            clean.append([x, y])
        return points, clean

    def _position_from_primitive(primitive, arg_prefix):
        position_pixels = primitive.get("position_pixels")
        position_normalized = primitive.get("position_normalized")
        if position_pixels is not None and position_normalized is not None:
            raise ValueError(f"{arg_prefix} cannot provide both position_pixels and position_normalized.")
        if position_normalized is not None:
            values = _validate_vector(position_normalized, 2, f"{arg_prefix}.position_normalized")
            return [values[0] * width, values[1] * height]
        if position_pixels is not None:
            return _validate_vector(position_pixels, 2, f"{arg_prefix}.position_pixels")
        raise ValueError(f"{arg_prefix} requires position_pixels or position_normalized.")

    def _pen(color_values, line_width):
        pen = QPen(_make_color(color_values))
        pen.setWidthF(max(0.0, line_width))
        return pen

    def _fill_brush(primitive):
        fill_color = primitive.get("fill_color")
        if fill_color is None:
            return QBrush(_qt_enum("BrushStyle", "NoBrush"))
        return QBrush(_make_color(_validate_color(fill_color, "fill_color")))

    def _outline_pen(primitive):
        outline_color = primitive.get("outline_color")
        if outline_color is None:
            return QPen(_qt_enum("PenStyle", "NoPen"))
        outline_width = _validate_scalar(primitive.get("outline_width", 1.0), "outline_width")
        return _pen(_validate_color(outline_color, "outline_color"), outline_width)

    def _text_flags(primitive):
        alignment = str(primitive.get("align", "left")).lower().strip()
        vertical_align = str(primitive.get("vertical_align", "center")).lower().strip()
        if alignment == "center":
            horizontal = _qt_enum("AlignmentFlag", "AlignHCenter")
        elif alignment == "right":
            horizontal = _qt_enum("AlignmentFlag", "AlignRight")
        elif alignment == "left":
            horizontal = _qt_enum("AlignmentFlag", "AlignLeft")
        else:
            raise ValueError("text align must be left, center, or right.")
        if vertical_align == "top":
            vertical = _qt_enum("AlignmentFlag", "AlignTop")
        elif vertical_align == "bottom":
            vertical = _qt_enum("AlignmentFlag", "AlignBottom")
        elif vertical_align == "center":
            vertical = _qt_enum("AlignmentFlag", "AlignVCenter")
        else:
            raise ValueError("text vertical_align must be top, center, or bottom.")
        flags = horizontal | vertical
        if bool(primitive.get("word_wrap", False)):
            flags = flags | _qt_enum("TextFlag", "TextWordWrap")
        return flags

    def _anchor_offset(anchor, box_width, box_height):
        anchor = str(anchor or "top_left").lower().strip()
        offsets = {
            "top_left": (0.0, 0.0),
            "top_right": (-box_width, 0.0),
            "bottom_left": (0.0, -box_height),
            "bottom_right": (-box_width, -box_height),
            "center": (-box_width * 0.5, -box_height * 0.5),
            "middle_left": (0.0, -box_height * 0.5),
            "middle_right": (-box_width, -box_height * 0.5),
            "top_middle": (-box_width * 0.5, 0.0),
            "bottom_middle": (-box_width * 0.5, -box_height),
        }
        if anchor not in offsets:
            raise ValueError("anchor must be top_left, top_right, bottom_left, bottom_right, center, middle_left, middle_right, top_middle, or bottom_middle.")
        return offsets[anchor]

    if not output_path:
        raise ValueError("output_path is required.")
    width = _validate_int(width, "width", 1)
    height = _validate_int(height, "height", 1)
    clean_background = _validate_color(background_color, "background_color")
    if primitives is None:
        primitives = []
    if not isinstance(primitives, list):
        raise ValueError("primitives must be a list of dictionaries.")

    normalized_output_path = os.path.normpath(output_path)
    if os.path.exists(normalized_output_path) and not overwrite:
        raise ValueError(f"Output path already exists: {output_path}")

    canvas = QImage(width, height, QImage.Format_ARGB32)
    canvas.fill(_make_color(clean_background))
    painter = QPainter(canvas)
    _set_antialiasing(painter)

    written_primitives = []
    for index, primitive in enumerate(primitives):
        if not isinstance(primitive, dict):
            raise ValueError("Each primitive must be a dictionary.")
        primitive_type = str(primitive.get("type", "")).lower().strip()
        if not primitive_type:
            raise ValueError("Each primitive requires type.")
        opacity = _clamp(_validate_scalar(primitive.get("opacity", 1.0), "opacity"))
        painter.save()
        painter.setOpacity(opacity)
        record = {"index": index, "type": primitive_type, "opacity": opacity}

        if primitive_type in {"rect", "rectangle", "ellipse"}:
            rect, bbox = _rect_from_primitive(primitive, f"primitives[{index}]")
            painter.setBrush(_fill_brush(primitive))
            painter.setPen(_outline_pen(primitive))
            if primitive_type == "ellipse":
                painter.drawEllipse(rect)
            else:
                painter.drawRect(rect)
            record["bbox_pixels"] = bbox
        elif primitive_type == "line":
            points, clean_points = _points_from_primitive(primitive, f"primitives[{index}]")
            color = _validate_color(primitive.get("color", [1.0, 1.0, 1.0, 1.0]), "color")
            line_width = _validate_scalar(primitive.get("width", 1.0), "width")
            painter.setPen(_pen(color, line_width))
            for point_index in range(len(points) - 1):
                painter.drawLine(points[point_index], points[point_index + 1])
            record["points_pixels"] = clean_points
        elif primitive_type == "polygon":
            points, clean_points = _points_from_primitive(primitive, f"primitives[{index}]")
            painter.setBrush(_fill_brush(primitive))
            painter.setPen(_outline_pen(primitive))
            painter.drawPolygon(QPolygonF(points))
            record["points_pixels"] = clean_points
        elif primitive_type == "text":
            text = primitive.get("text")
            if text is None:
                raise ValueError("text primitive requires text.")
            text = str(text)
            position = _position_from_primitive(primitive, f"primitives[{index}]")
            font_family = str(primitive.get("font_family", "Arial"))
            font_size = _validate_scalar(primitive.get("font_size", 24.0), "font_size")
            if font_size <= 0.0:
                raise ValueError("font_size must be greater than zero.")
            font = QFont(font_family)
            font.setPixelSize(int(round(font_size)))
            font.setBold(bool(primitive.get("bold", False)))
            font.setItalic(bool(primitive.get("italic", False)))
            painter.setFont(font)
            painter.setPen(_pen(_validate_color(primitive.get("color", [1.0, 1.0, 1.0, 1.0]), "color"), 1.0))
            metrics = painter.fontMetrics()
            lines = text.splitlines() or [text]
            max_width = primitive.get("max_width_pixels")
            max_height = primitive.get("max_height_pixels")
            if max_width is None:
                max_width = max(1, max(metrics.horizontalAdvance(line) for line in lines))
            else:
                max_width = _validate_scalar(max_width, "max_width_pixels")
            if max_height is None:
                max_height = max(1, metrics.height() * max(1, len(lines)))
            else:
                max_height = _validate_scalar(max_height, "max_height_pixels")
            offset_x, offset_y = _anchor_offset(primitive.get("anchor", "top_left"), max_width, max_height)
            rotation = _validate_scalar(primitive.get("rotation_degrees", 0.0), "rotation_degrees")
            painter.translate(position[0], position[1])
            if rotation:
                painter.rotate(rotation)
            painter.drawText(QRectF(offset_x, offset_y, max_width, max_height), _text_flags(primitive), text)
            record["position_pixels"] = position
            record["text_box_pixels"] = [position[0] + offset_x, position[1] + offset_y, position[0] + offset_x + max_width, position[1] + offset_y + max_height]
        else:
            raise ValueError("primitive type must be rect, ellipse, line, polygon, or text.")

        painter.restore()
        written_primitives.append(record)

    painter.end()

    directory = os.path.dirname(normalized_output_path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    if not canvas.save(normalized_output_path):
        raise RuntimeError(f"Unable to write primitive image: {output_path}")

    return {
        "success": True,
        "output_path": normalized_output_path,
        "width": width,
        "height": height,
        "background_color": clean_background,
        "primitive_count": len(primitives),
        "primitives": written_primitives,
    }
