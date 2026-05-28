from typing import Dict, List, Any


def compose_image_layers(
    output_path: str,
    width: int,
    height: int,
    background_color: List[float] = [0.0, 0.0, 0.0, 0.0],
    layers: List[Dict[str, Any]] = None,
    overwrite: bool = True,
) -> Dict[str, Any]:
    """Compose multiple image layers into a single RGBA texture.

    This is a generic texture-atlas and decal-prep utility for labels, panels,
    sprites, UI textures, reference cards, product wraps, and material masks.
    Each layer can crop a source image with pixel or normalized coordinates,
    resize it, position it with pixel or normalized coordinates, preserve aspect
    if requested, and apply opacity before it is drawn onto the output canvas.
    """
    import os

    try:
        from PySide6.QtCore import Qt, QRectF
        from PySide6.QtGui import QImage, QPainter, QColor
    except Exception:
        try:
            from PySide2.QtCore import Qt, QRectF
            from PySide2.QtGui import QImage, QPainter, QColor
        except Exception as exc:
            raise RuntimeError("PySide QImage is required to compose image layers in Maya.") from exc

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

    def _bbox_from_layer(layer, image):
        bbox_pixels = layer.get("source_bbox_pixels")
        bbox_normalized = layer.get("source_bbox_normalized")
        if bbox_pixels is not None and bbox_normalized is not None:
            raise ValueError("Layer cannot provide both source_bbox_pixels and source_bbox_normalized.")
        if bbox_normalized is not None:
            bbox = _validate_vector(bbox_normalized, 4, "source_bbox_normalized")
            x0 = int(round(_clamp(bbox[0]) * (image.width() - 1)))
            y0 = int(round(_clamp(bbox[1]) * (image.height() - 1)))
            x1 = int(round(_clamp(bbox[2]) * (image.width() - 1)))
            y1 = int(round(_clamp(bbox[3]) * (image.height() - 1)))
        elif bbox_pixels is not None:
            bbox = _validate_vector(bbox_pixels, 4, "source_bbox_pixels")
            x0, y0, x1, y1 = [int(round(value)) for value in bbox]
        else:
            x0, y0, x1, y1 = 0, 0, image.width() - 1, image.height() - 1
        x0 = max(0, min(image.width() - 1, x0))
        x1 = max(0, min(image.width() - 1, x1))
        y0 = max(0, min(image.height() - 1, y0))
        y1 = max(0, min(image.height() - 1, y1))
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        return [x0, y0, x1, y1]

    def _resolve_size(layer, source_width, source_height):
        size_pixels = layer.get("size_pixels")
        size_normalized = layer.get("size_normalized")
        if size_pixels is not None and size_normalized is not None:
            raise ValueError("Layer cannot provide both size_pixels and size_normalized.")
        if size_normalized is not None:
            clean = _validate_vector(size_normalized, 2, "size_normalized")
            target_width = int(round(clean[0] * width))
            target_height = int(round(clean[1] * height))
        elif size_pixels is not None:
            clean = _validate_vector(size_pixels, 2, "size_pixels")
            target_width = int(round(clean[0]))
            target_height = int(round(clean[1]))
        else:
            target_width = source_width
            target_height = source_height
        if target_width <= 0 or target_height <= 0:
            raise ValueError("Layer size must resolve to positive dimensions.")
        return target_width, target_height

    def _resolve_position(layer, target_width, target_height):
        position_pixels = layer.get("position_pixels")
        position_normalized = layer.get("position_normalized")
        if position_pixels is not None and position_normalized is not None:
            raise ValueError("Layer cannot provide both position_pixels and position_normalized.")
        if position_normalized is not None:
            clean = _validate_vector(position_normalized, 2, "position_normalized")
            x = clean[0] * width
            y = clean[1] * height
        elif position_pixels is not None:
            clean = _validate_vector(position_pixels, 2, "position_pixels")
            x = clean[0]
            y = clean[1]
        else:
            x = 0.0
            y = 0.0

        anchor = str(layer.get("anchor", "top_left")).lower().strip()
        if anchor == "center":
            x -= target_width * 0.5
            y -= target_height * 0.5
        elif anchor == "top_right":
            x -= target_width
        elif anchor == "bottom_left":
            y -= target_height
        elif anchor == "bottom_right":
            x -= target_width
            y -= target_height
        elif anchor != "top_left":
            raise ValueError("Layer anchor must be top_left, center, top_right, bottom_left, or bottom_right.")
        return x, y

    if not output_path:
        raise ValueError("output_path is required.")
    width = _validate_int(width, "width", 1)
    height = _validate_int(height, "height", 1)
    clean_background = _validate_color(background_color, "background_color")
    if layers is None:
        layers = []
    if not isinstance(layers, list):
        raise ValueError("layers must be a list of layer dictionaries.")

    normalized_output_path = os.path.normpath(output_path)
    if os.path.exists(normalized_output_path) and not overwrite:
        raise ValueError(f"Output path already exists: {output_path}")

    canvas = QImage(width, height, QImage.Format_ARGB32)
    canvas.fill(_make_color(clean_background))
    painter = QPainter(canvas)
    written_layers = []

    for index, layer in enumerate(layers):
        if not isinstance(layer, dict):
            raise ValueError("Each layer must be a dictionary.")
        image_path = layer.get("image_path")
        if not image_path:
            raise ValueError("Each layer requires image_path.")
        normalized_image_path = os.path.normpath(image_path)
        if not os.path.isfile(normalized_image_path):
            raise ValueError(f"Layer image path does not exist: {image_path}")

        image = QImage(normalized_image_path)
        if image.isNull():
            raise ValueError(f"Unable to load layer image: {image_path}")
        image = image.convertToFormat(QImage.Format_ARGB32)
        x0, y0, x1, y1 = _bbox_from_layer(layer, image)
        cropped = image.copy(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
        target_width, target_height = _resolve_size(layer, cropped.width(), cropped.height())
        keep_aspect = bool(layer.get("keep_aspect", False))
        transform_mode = Qt.SmoothTransformation if bool(layer.get("smooth", True)) else Qt.FastTransformation
        aspect_mode = Qt.KeepAspectRatio if keep_aspect else Qt.IgnoreAspectRatio
        scaled = cropped.scaled(target_width, target_height, aspect_mode, transform_mode)
        x, y = _resolve_position(layer, scaled.width(), scaled.height())
        opacity = _clamp(_validate_scalar(layer.get("opacity", 1.0), "opacity"))

        painter.setOpacity(opacity)
        painter.drawImage(QRectF(x, y, scaled.width(), scaled.height()), scaled)
        written_layers.append({
            "index": index,
            "image_path": normalized_image_path,
            "source_bbox_pixels": [x0, y0, x1, y1],
            "draw_rect_pixels": [x, y, x + scaled.width(), y + scaled.height()],
            "opacity": opacity,
        })

    painter.setOpacity(1.0)
    painter.end()

    directory = os.path.dirname(normalized_output_path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    if not canvas.save(normalized_output_path):
        raise RuntimeError(f"Unable to write composed image: {output_path}")

    return {
        "success": True,
        "output_path": normalized_output_path,
        "width": width,
        "height": height,
        "background_color": clean_background,
        "layer_count": len(layers),
        "layers": written_layers,
    }
