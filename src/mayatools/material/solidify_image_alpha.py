from typing import Dict, List, Any


def solidify_image_alpha(
    image_path: str,
    output_path: str = None,
    alpha_threshold: float = 0.05,
    source_mode: str = "alpha",
    background_color: List[float] = None,
    background_tolerance: float = 0.08,
    saturation_min: float = 0.0,
    value_min: float = 0.0,
    set_alpha: str = "opaque",
    overwrite: bool = True,
) -> Dict[str, Any]:
    """Fill transparent pixels with nearby opaque color and optionally remove alpha.

    This prepares RGBA textures for workflows where the RGB data will be sampled
    directly: opaque decal meshes, UV-projected geometry, texture-driven
    displacement, viewport previews that sort transparency poorly, or export
    targets that ignore alpha. Transparent pixels are flood-filled from the
    nearest accepted source pixel in image space, preserving the visible artwork
    while preventing black or empty RGB pixels from appearing on real geometry.
    source_mode can filter source pixels by alpha only, foreground against a
    background color, saturation/value, or foreground plus saturation/value.
    """
    import os
    from collections import deque

    try:
        from PySide6.QtGui import QImage, QColor
    except Exception:
        try:
            from PySide2.QtGui import QImage, QColor
        except Exception as exc:
            raise RuntimeError("PySide QImage is required to process image alpha.") from exc

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _clamp(value, lower=0.0, upper=1.0):
        return max(lower, min(upper, value))

    def _validate_color(values, arg_name):
        if not isinstance(values, list) or len(values) != 3 or not all(_is_number(value) for value in values):
            raise ValueError(f"{arg_name} must be a list of 3 numeric values.")
        color = [float(values[0]), float(values[1]), float(values[2])]
        if max(color) > 1.0:
            color = [value / 255.0 for value in color]
        return [_clamp(value) for value in color]

    def _color_distance(color_a, color_b):
        dr = color_a[0] - color_b[0]
        dg = color_a[1] - color_b[1]
        db = color_a[2] - color_b[2]
        return (dr * dr + dg * dg + db * db) ** 0.5

    def _rgb_to_hsv(red, green, blue):
        red /= 255.0
        green /= 255.0
        blue /= 255.0
        max_value = max(red, green, blue)
        min_value = min(red, green, blue)
        delta = max_value - min_value
        if delta == 0.0:
            hue = 0.0
        elif max_value == red:
            hue = ((green - blue) / delta) % 6.0
        elif max_value == green:
            hue = ((blue - red) / delta) + 2.0
        else:
            hue = ((red - green) / delta) + 4.0
        hue /= 6.0
        saturation = 0.0 if max_value == 0.0 else delta / max_value
        return hue, saturation, max_value

    def _estimate_background(source_image, alpha_limit_value):
        width = source_image.width()
        height = source_image.height()
        points = []
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
                    color = source_image.pixelColor(x, y)
                    if color.alpha() >= alpha_limit_value:
                        points.append([color.redF(), color.greenF(), color.blueF()])
        if not points:
            return [0.0, 0.0, 0.0]
        channels = []
        for index in range(3):
            values = sorted(point[index] for point in points)
            channels.append(values[len(values) // 2])
        return channels

    if not image_path:
        raise ValueError("image_path is required.")
    normalized_image_path = os.path.normpath(image_path)
    if not os.path.isfile(normalized_image_path):
        raise ValueError(f"Image path does not exist: {image_path}")
    if not _is_number(alpha_threshold):
        raise ValueError("alpha_threshold must be numeric.")
    alpha_threshold = _clamp(float(alpha_threshold))
    if not _is_number(background_tolerance):
        raise ValueError("background_tolerance must be numeric.")
    background_tolerance = float(background_tolerance)
    if background_tolerance > 1.0:
        background_tolerance /= 255.0
    background_tolerance = max(0.0, background_tolerance)
    if not _is_number(saturation_min):
        raise ValueError("saturation_min must be numeric.")
    if not _is_number(value_min):
        raise ValueError("value_min must be numeric.")
    saturation_min = _clamp(float(saturation_min))
    value_min = _clamp(float(value_min))

    source_mode = source_mode.lower().strip()
    if source_mode not in {"alpha", "foreground", "saturation", "foreground_saturation"}:
        raise ValueError("source_mode must be alpha, foreground, saturation, or foreground_saturation.")

    set_alpha = set_alpha.lower().strip()
    if set_alpha not in {"opaque", "preserve"}:
        raise ValueError("set_alpha must be opaque or preserve.")

    image = QImage(normalized_image_path)
    if image.isNull():
        raise ValueError(f"Unable to load image: {image_path}")
    if image.width() < 1 or image.height() < 1:
        raise ValueError("image must not be empty.")

    image = image.convertToFormat(QImage.Format_ARGB32)
    width = image.width()
    height = image.height()
    alpha_limit = int(round(alpha_threshold * 255.0))
    clean_background_color = None
    if source_mode in {"foreground", "foreground_saturation"}:
        clean_background_color = (
            _validate_color(background_color, "background_color")
            if background_color
            else _estimate_background(image, alpha_limit)
        )

    def _is_source_color(color):
        if color.alpha() < alpha_limit:
            return False
        if source_mode in {"foreground", "foreground_saturation"}:
            rgb = [color.redF(), color.greenF(), color.blueF()]
            if _color_distance(rgb, clean_background_color) <= background_tolerance:
                return False
        if source_mode in {"saturation", "foreground_saturation"}:
            _, saturation, value = _rgb_to_hsv(color.red(), color.green(), color.blue())
            if saturation < saturation_min or value < value_min:
                return False
        return True

    visited = [bytearray(width) for _ in range(height)]
    queue = deque()
    opaque_count = 0
    filled_count = 0

    for y in range(height):
        for x in range(width):
            color = image.pixelColor(x, y)
            if _is_source_color(color):
                visited[y][x] = 1
                queue.append((x, y, color.red(), color.green(), color.blue()))
                opaque_count += 1

    if opaque_count == 0:
        raise ValueError("No source pixels meet alpha_threshold.")

    neighbors = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    while queue:
        x, y, red, green, blue = queue.popleft()
        for dx, dy in neighbors:
            nx = x + dx
            ny = y + dy
            if nx < 0 or nx >= width or ny < 0 or ny >= height or visited[ny][nx]:
                continue
            visited[ny][nx] = 1
            original = image.pixelColor(nx, ny)
            alpha = 255 if set_alpha == "opaque" else original.alpha()
            image.setPixelColor(nx, ny, QColor(red, green, blue, alpha))
            queue.append((nx, ny, red, green, blue))
            filled_count += 1

    if set_alpha == "opaque":
        for y in range(height):
            for x in range(width):
                color = image.pixelColor(x, y)
                if color.alpha() != 255:
                    color.setAlpha(255)
                    image.setPixelColor(x, y, color)

    if output_path is None:
        base_name = os.path.splitext(os.path.basename(normalized_image_path))[0] or "image"
        output_path = os.path.join(os.path.dirname(normalized_image_path), f"{base_name}_solid.png")
    normalized_output_path = os.path.normpath(output_path)
    if not os.path.splitext(normalized_output_path)[1]:
        normalized_output_path += ".png"
    output_dir = os.path.dirname(normalized_output_path)
    if output_dir and not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    if os.path.exists(normalized_output_path) and not overwrite:
        raise ValueError(f"Output path already exists: {output_path}")
    if not image.save(normalized_output_path):
        raise RuntimeError(f"Failed to save solidified texture: {output_path}")

    return {
        "success": True,
        "image_path": normalized_image_path,
        "output_path": normalized_output_path,
        "image_width": width,
        "image_height": height,
        "alpha_threshold": alpha_threshold,
        "source_mode": source_mode,
        "background_color": clean_background_color,
        "background_tolerance": background_tolerance,
        "saturation_min": saturation_min,
        "value_min": value_min,
        "set_alpha": set_alpha,
        "source_pixel_count": opaque_count,
        "filled_pixel_count": filled_count,
    }
