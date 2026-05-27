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
    auto_bbox_mode: str = "none",
    alpha_threshold: float = 0.05,
    min_foreground_pixels: int = 1,
    horizontal_remap: str = "none",
    source_arc_degrees: float = 120.0,
    remap_center_x: float = 0.5,
    mask_background: bool = False,
    mask_background_mode: str = "color",
    background_color: List[float] = None,
    background_tolerance: float = 0.06,
    overwrite: bool = True,
) -> Dict[str, Any]:
    """Crop an image reference region into a reusable texture file.

    The crop can be defined in pixels, normalized image coordinates, or
    automatically from foreground pixels against an estimated/provided
    background color. The crop can be padded, optionally resized, optionally
    remapped from a front cylindrical projection, and optionally written with
    background pixels made transparent. Background masking can remove all
    matching pixels or only flood-fill matching pixels connected to crop edges.
    The output is intended for generic reference-driven texturing workflows
    such as labels, panels, decals, caps, badges, silhouettes, or trim.
    """
    import math
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

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

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

    def _is_background_pixel(image, x, y, color, tolerance):
        red, green, blue, alpha = _pixel_rgb_alpha(image, x, y)
        if alpha <= 0.0:
            return False
        return _color_distance([red, green, blue], color) <= tolerance

    def _foreground_bbox(image, color, tolerance, minimum_alpha, minimum_pixels):
        bbox = None
        count = 0
        for y in range(image.height()):
            for x in range(image.width()):
                red, green, blue, alpha = _pixel_rgb_alpha(image, x, y)
                if alpha < minimum_alpha:
                    continue
                if _color_distance([red, green, blue], color) <= tolerance:
                    continue
                count += 1
                if bbox is None:
                    bbox = [x, y, x, y]
                else:
                    bbox[0] = min(bbox[0], x)
                    bbox[1] = min(bbox[1], y)
                    bbox[2] = max(bbox[2], x)
                    bbox[3] = max(bbox[3], y)
        if count < minimum_pixels or bbox is None:
            raise ValueError("No foreground bbox could be found. Adjust background_color, background_tolerance, alpha_threshold, or min_foreground_pixels.")
        return bbox, count

    def _mask_background_by_color(image, color, tolerance):
        for y in range(image.height()):
            for x in range(image.width()):
                if _is_background_pixel(image, x, y, color, tolerance):
                    pixel = image.pixelColor(x, y)
                    pixel.setAlpha(0)
                    image.setPixelColor(x, y, pixel)

    def _mask_background_by_flood_fill(image, color, tolerance):
        width = image.width()
        height = image.height()
        visited = [bytearray(width) for _ in range(height)]
        stack = []
        for x in range(width):
            stack.append((x, 0))
            stack.append((x, height - 1))
        for y in range(1, height - 1):
            stack.append((0, y))
            stack.append((width - 1, y))

        while stack:
            x, y = stack.pop()
            if visited[y][x]:
                continue
            visited[y][x] = 1
            if not _is_background_pixel(image, x, y, color, tolerance):
                continue
            pixel = image.pixelColor(x, y)
            pixel.setAlpha(0)
            image.setPixelColor(x, y, pixel)
            if x > 0:
                stack.append((x - 1, y))
            if x < width - 1:
                stack.append((x + 1, y))
            if y > 0:
                stack.append((x, y - 1))
            if y < height - 1:
                stack.append((x, y + 1))

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

    def _make_color(red, green, blue, alpha):
        color = QColor()
        color.setRgbF(
            max(0.0, min(1.0, red)),
            max(0.0, min(1.0, green)),
            max(0.0, min(1.0, blue)),
            max(0.0, min(1.0, alpha)),
        )
        return color

    def _sample_bilinear(image, x, y):
        width = image.width()
        height = image.height()
        x = max(0.0, min(float(width - 1), x))
        y = max(0.0, min(float(height - 1), y))
        x0 = int(math.floor(x))
        y0 = int(math.floor(y))
        x1 = min(width - 1, x0 + 1)
        y1 = min(height - 1, y0 + 1)
        tx = x - x0
        ty = y - y0
        c00 = _pixel_rgb_alpha(image, x0, y0)
        c10 = _pixel_rgb_alpha(image, x1, y0)
        c01 = _pixel_rgb_alpha(image, x0, y1)
        c11 = _pixel_rgb_alpha(image, x1, y1)
        channels = []
        for index in range(4):
            top = c00[index] * (1.0 - tx) + c10[index] * tx
            bottom = c01[index] * (1.0 - tx) + c11[index] * tx
            channels.append(top * (1.0 - ty) + bottom * ty)
        return _make_color(channels[0], channels[1], channels[2], channels[3])

    def _remap_cylindrical_front(image, target_width, target_height, arc_degrees, center_x):
        arc_radians = math.radians(arc_degrees)
        half_arc = arc_radians * 0.5
        sin_half_arc = math.sin(half_arc)
        if sin_half_arc <= 1e-9:
            raise ValueError("source_arc_degrees is too small for cylindrical_front remap.")
        source_width = image.width()
        source_height = image.height()
        projected_center = center_x * float(source_width - 1)
        left_span = max(1e-9, projected_center)
        right_span = max(1e-9, float(source_width - 1) - projected_center)
        remapped = QImage(target_width, target_height, QImage.Format_ARGB32)
        remapped.fill(QColor(0, 0, 0, 0))
        for y in range(target_height):
            v = 0.0 if target_height == 1 else y / float(target_height - 1)
            source_y = v * float(source_height - 1)
            for x in range(target_width):
                u = 0.0 if target_width == 1 else x / float(target_width - 1)
                theta = (u - 0.5) * arc_radians
                projected = math.sin(theta) / sin_half_arc
                if projected < 0.0:
                    source_x = projected_center + projected * left_span
                else:
                    source_x = projected_center + projected * right_span
                remapped.setPixelColor(x, y, _sample_bilinear(image, source_x, source_y))
        return remapped

    if not image_path:
        raise ValueError("image_path is required.")
    normalized_image_path = os.path.normpath(image_path)
    if not os.path.isfile(normalized_image_path):
        raise ValueError(f"Image path does not exist: {image_path}")
    if bbox_pixels is not None and bbox_normalized is not None:
        raise ValueError("Provide only one of bbox_pixels or bbox_normalized.")

    padding_pixels = _validate_int(padding_pixels, "padding_pixels", 0)
    output_width = _validate_int(output_width, "output_width", 0)
    output_height = _validate_int(output_height, "output_height", 0)
    min_foreground_pixels = _validate_int(min_foreground_pixels, "min_foreground_pixels", 1)
    alpha_threshold = _validate_scalar(alpha_threshold, "alpha_threshold")
    if alpha_threshold < 0.0 or alpha_threshold > 1.0:
        raise ValueError("alpha_threshold must be in the 0..1 range.")
    auto_bbox_mode = auto_bbox_mode.lower().strip()
    if auto_bbox_mode not in {"none", "foreground"}:
        raise ValueError("auto_bbox_mode must be one of none or foreground.")
    if bbox_pixels is None and bbox_normalized is None and auto_bbox_mode == "none":
        raise ValueError("bbox_pixels or bbox_normalized is required unless auto_bbox_mode is foreground.")
    horizontal_remap = horizontal_remap.lower().strip()
    if horizontal_remap not in {"none", "cylindrical_front"}:
        raise ValueError("horizontal_remap must be one of none or cylindrical_front.")
    if not _is_number(source_arc_degrees):
        raise ValueError("source_arc_degrees must be numeric.")
    source_arc_degrees = float(source_arc_degrees)
    if source_arc_degrees <= 0.0 or source_arc_degrees >= 180.0:
        raise ValueError("source_arc_degrees must be greater than 0 and less than 180.")
    if not _is_number(remap_center_x):
        raise ValueError("remap_center_x must be numeric.")
    remap_center_x = float(remap_center_x)
    if remap_center_x <= 0.0 or remap_center_x >= 1.0:
        raise ValueError("remap_center_x must be greater than 0 and less than 1.")
    if not _is_number(background_tolerance):
        raise ValueError("background_tolerance must be numeric.")
    background_tolerance = float(background_tolerance)
    if background_tolerance > 1.0:
        background_tolerance /= 255.0
    if background_tolerance < 0.0:
        raise ValueError("background_tolerance must be greater than or equal to zero.")
    mask_background_mode = mask_background_mode.lower().strip()
    if mask_background_mode not in {"color", "flood_fill"}:
        raise ValueError("mask_background_mode must be one of color or flood_fill.")

    image = QImage(normalized_image_path)
    if image.isNull():
        raise ValueError(f"Unable to load image: {image_path}")
    image_width = image.width()
    image_height = image.height()
    if image_width < 2 or image_height < 2:
        raise ValueError("image must be at least 2x2 pixels.")

    auto_background_color = None
    auto_foreground_count = 0
    if bbox_pixels is None and bbox_normalized is None:
        auto_background_color = _validate_color(background_color, "background_color") if background_color else _estimate_background(image)
        auto_bbox, auto_foreground_count = _foreground_bbox(
            image,
            auto_background_color,
            background_tolerance,
            alpha_threshold,
            min_foreground_pixels,
        )
        x_min, y_min, x_max, y_max = auto_bbox
    elif bbox_normalized is not None:
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
        clean_background_color = _validate_color(background_color, "background_color") if background_color else auto_background_color or _estimate_background(cropped)
        if mask_background_mode == "flood_fill":
            _mask_background_by_flood_fill(cropped, clean_background_color, background_tolerance)
        else:
            _mask_background_by_color(cropped, clean_background_color, background_tolerance)

    final_width = output_width or cropped.width()
    final_height = output_height or cropped.height()
    if output_width or output_height:
        if output_width == 0:
            final_width = max(1, int(round(cropped.width() * (output_height / float(cropped.height())))))
        if output_height == 0:
            final_height = max(1, int(round(cropped.height() * (output_width / float(cropped.width())))))
        if horizontal_remap == "cylindrical_front":
            cropped = _remap_cylindrical_front(cropped, final_width, final_height, source_arc_degrees, remap_center_x)
        elif stretch_to_output:
            cropped = cropped.scaled(final_width, final_height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        else:
            cropped = _scale_keep_aspect(cropped, final_width, final_height)
    elif horizontal_remap == "cylindrical_front":
        cropped = _remap_cylindrical_front(cropped, final_width, final_height, source_arc_degrees, remap_center_x)

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
        "auto_bbox_mode": auto_bbox_mode,
        "auto_foreground_count": auto_foreground_count,
        "alpha_threshold": alpha_threshold,
        "min_foreground_pixels": min_foreground_pixels,
        "horizontal_remap": horizontal_remap,
        "source_arc_degrees": source_arc_degrees,
        "remap_center_x": remap_center_x,
        "mask_background": mask_background,
        "mask_background_mode": mask_background_mode,
        "background_color": clean_background_color or auto_background_color,
        "background_tolerance": background_tolerance,
    }
