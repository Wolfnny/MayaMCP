from typing import Dict, List, Any


def extract_image_region_texture(
    image_path: str,
    output_path: str = None,
    bbox_pixels: List[float] = None,
    bbox_normalized: List[float] = None,
    padding_pixels: int = 0,
    output_width: int = 0,
    output_height: int = 0,
    stretch_to_output: bool = True,
    mask_background: bool = False,
    background_color: List[float] = None,
    background_tolerance: float = 0.06,
    overwrite: bool = True,
) -> Dict[str, Any]:
    """Crop an image reference region into a reusable texture file.

    The crop can be defined in pixels or normalized image coordinates, padded,
    optionally resized, and optionally written with background-colored pixels
    made transparent. The output is intended for generic reference-driven
    texturing workflows such as labels, panels, decals, caps, badges, or trim.
    """
    import os

    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage, QColor
    except Exception:
        try:
            from PySide2.QtCore import Qt
            from PySide2.QtGui import QImage, QColor
        except Exception as exc:
            raise RuntimeError("PySide QImage is required to crop image textures in Maya.") from exc

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(v) for v in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(value) for value in values]

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return value

    def _validate_color(values, arg_name):
        color = _validate_vector(values, 3, arg_name)
        if max(color) > 1.0:
            color = [value / 255.0 for value in color]
        return [max(0.0, min(1.0, value)) for value in color]

    def _pixel_rgb_alpha(image, x, y):
        color = image.pixelColor(int(x), int(y))
        return [color.redF(), color.greenF(), color.blueF(), color.alphaF()]

    def _color_distance(color_a, color_b):
        dr = color_a[0] - color_b[0]
        dg = color_a[1] - color_b[1]
        db = color_a[2] - color_b[2]
        return (dr * dr + dg * dg + db * db) ** 0.5

    def _estimate_background(image):
        width = image.width()
        height = image.height()
        sample_points = []
        radius = max(1, min(width, height, 8))
        corners = [
            (0, 0),
            (width - 1, 0),
            (0, height - 1),
            (width - 1, height - 1),
        ]
        for corner_x, corner_y in corners:
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    x = max(0, min(width - 1, corner_x + dx))
                    y = max(0, min(height - 1, corner_y + dy))
                    sample_points.append(_pixel_rgb_alpha(image, x, y)[:3])
        channels = []
        for index in range(3):
            values = sorted(point[index] for point in sample_points)
            channels.append(values[len(values) // 2])
        return channels

    def _scale_keep_aspect(image, target_width, target_height):
        scaled = image.scaled(target_width, target_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        canvas = QImage(target_width, target_height, QImage.Format_ARGB32)
        canvas.fill(QColor(0, 0, 0, 0))
        try:
            from PySide6.QtGui import QPainter
        except Exception:
            from PySide2.QtGui import QPainter
        painter = QPainter(canvas)
        offset_x = int((target_width - scaled.width()) * 0.5)
        offset_y = int((target_height - scaled.height()) * 0.5)
        painter.drawImage(offset_x, offset_y, scaled)
        painter.end()
        return canvas

    if not image_path:
        raise ValueError("image_path is required.")
    normalized_image_path = os.path.normpath(image_path)
    if not os.path.isfile(normalized_image_path):
        raise ValueError(f"Image path does not exist: {image_path}")
    if bbox_pixels is None and bbox_normalized is None:
        raise ValueError("bbox_pixels or bbox_normalized is required.")
    if bbox_pixels is not None and bbox_normalized is not None:
        raise ValueError("Provide only one of bbox_pixels or bbox_normalized.")

    padding_pixels = _validate_int(padding_pixels, "padding_pixels", 0)
    output_width = _validate_int(output_width, "output_width", 0)
    output_height = _validate_int(output_height, "output_height", 0)
    if not _is_number(background_tolerance):
        raise ValueError("background_tolerance must be numeric.")
    background_tolerance = float(background_tolerance)
    if background_tolerance > 1.0:
        background_tolerance /= 255.0
    if background_tolerance < 0.0:
        raise ValueError("background_tolerance must be greater than or equal to zero.")

    image = QImage(normalized_image_path)
    if image.isNull():
        raise ValueError(f"Unable to load image: {image_path}")
    image_width = image.width()
    image_height = image.height()
    if image_width < 2 or image_height < 2:
        raise ValueError("image must be at least 2x2 pixels.")

    if bbox_normalized is not None:
        bbox = _validate_vector(bbox_normalized, 4, "bbox_normalized")
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            raise ValueError("bbox_normalized must be [min_x, min_y, max_x, max_y].")
        x_min = int(round(max(0.0, min(1.0, bbox[0])) * (image_width - 1)))
        y_min = int(round(max(0.0, min(1.0, bbox[1])) * (image_height - 1)))
        x_max = int(round(max(0.0, min(1.0, bbox[2])) * (image_width - 1)))
        y_max = int(round(max(0.0, min(1.0, bbox[3])) * (image_height - 1)))
    else:
        bbox = _validate_vector(bbox_pixels, 4, "bbox_pixels")
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            raise ValueError("bbox_pixels must be [min_x, min_y, max_x, max_y].")
        x_min = int(round(bbox[0]))
        y_min = int(round(bbox[1]))
        x_max = int(round(bbox[2]))
        y_max = int(round(bbox[3]))

    x_min = max(0, min(image_width - 1, x_min - padding_pixels))
    y_min = max(0, min(image_height - 1, y_min - padding_pixels))
    x_max = max(0, min(image_width - 1, x_max + padding_pixels))
    y_max = max(0, min(image_height - 1, y_max + padding_pixels))
    if x_max <= x_min or y_max <= y_min:
        raise ValueError("Resolved crop bbox is empty.")

    crop_width = x_max - x_min + 1
    crop_height = y_max - y_min + 1
    cropped = image.copy(x_min, y_min, crop_width, crop_height).convertToFormat(QImage.Format_ARGB32)

    clean_background_color = None
    if mask_background:
        clean_background_color = _validate_color(background_color, "background_color") if background_color else _estimate_background(cropped)
        for y in range(cropped.height()):
            for x in range(cropped.width()):
                red, green, blue, alpha = _pixel_rgb_alpha(cropped, x, y)
                if alpha <= 0.0:
                    continue
                if _color_distance([red, green, blue], clean_background_color) <= background_tolerance:
                    color = cropped.pixelColor(x, y)
                    color.setAlpha(0)
                    cropped.setPixelColor(x, y, color)

    final_width = output_width or cropped.width()
    final_height = output_height or cropped.height()
    if output_width or output_height:
        if output_width == 0:
            final_width = max(1, int(round(cropped.width() * (output_height / float(cropped.height())))))
        if output_height == 0:
            final_height = max(1, int(round(cropped.height() * (output_width / float(cropped.width())))))
        if stretch_to_output:
            cropped = cropped.scaled(final_width, final_height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        else:
            cropped = _scale_keep_aspect(cropped, final_width, final_height)

    if output_path is None:
        base_name = os.path.splitext(os.path.basename(normalized_image_path))[0] or "image"
        output_path = os.path.join(os.path.dirname(normalized_image_path), f"{base_name}_crop.png")
    normalized_output_path = os.path.normpath(output_path)
    if not os.path.splitext(normalized_output_path)[1]:
        normalized_output_path += ".png"
    output_dir = os.path.dirname(normalized_output_path)
    if output_dir and not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    if os.path.exists(normalized_output_path) and not overwrite:
        raise ValueError(f"Output path already exists: {output_path}")
    if not cropped.save(normalized_output_path):
        raise RuntimeError(f"Failed to save cropped texture: {output_path}")

    return {
        "success": True,
        "image_path": normalized_image_path,
        "output_path": normalized_output_path,
        "source_image_width": image_width,
        "source_image_height": image_height,
        "crop_bbox_pixels": [x_min, y_min, x_max, y_max],
        "crop_bbox_normalized": [
            x_min / float(image_width - 1),
            y_min / float(image_height - 1),
            x_max / float(image_width - 1),
            y_max / float(image_height - 1),
        ],
        "crop_width": crop_width,
        "crop_height": crop_height,
        "output_width": cropped.width(),
        "output_height": cropped.height(),
        "mask_background": mask_background,
        "background_color": clean_background_color,
        "background_tolerance": background_tolerance,
    }
