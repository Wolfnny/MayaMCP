from typing import Dict, List, Any


def clean_image_alpha_edges(
    image_path: str,
    output_path: str = None,
    background_color: List[float] = None,
    alpha_threshold: float = 0.01,
    unmatte_background: bool = False,
    unmatte_strength: float = 1.0,
    erode_alpha_pixels: int = 0,
    feather_alpha_pixels: int = 0,
    fill_transparent_rgb: bool = True,
    overwrite: bool = True,
) -> Dict[str, Any]:
    """Clean alpha-texture edge contamination and transparent RGB padding.

    This is a generic texture-prep utility for decals, cards, labels, leaves,
    sprites, product-photo cutouts, and other RGBA assets used on real geometry.
    It can flood-fill fully transparent RGB from nearby visible pixels so
    viewport filtering does not reveal black or empty padding. When the source
    is known to be premultiplied or matted over a background, it can also remove
    matte/background color contamination from semi-transparent pixels and
    optionally erode a thin alpha fringe. feather_alpha_pixels fades the
    remaining alpha near transparent edges, which is useful for projected
    decals or partial photo textures that should not end with a hard boundary.
    """
    import os
    from collections import deque

    try:
        from PySide6.QtGui import QImage, QColor
    except Exception:
        try:
            from PySide2.QtGui import QImage, QColor
        except Exception as exc:
            raise RuntimeError("PySide QImage is required to clean image alpha edges.") from exc

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _clamp(value, lower=0.0, upper=1.0):
        return max(lower, min(upper, value))

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return value

    def _validate_color(values, arg_name):
        if not isinstance(values, list) or len(values) != 3 or not all(_is_number(value) for value in values):
            raise ValueError(f"{arg_name} must be a list of 3 numeric values.")
        color = [float(values[0]), float(values[1]), float(values[2])]
        if max(color) > 1.0:
            color = [value / 255.0 for value in color]
        return [_clamp(value) for value in color]

    def _estimate_background(image):
        width = image.width()
        height = image.height()
        samples = []
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
                    color = image.pixelColor(x, y)
                    if color.alphaF() > 0.0:
                        samples.append([color.redF(), color.greenF(), color.blueF()])
        if not samples:
            return [1.0, 1.0, 1.0]
        channels = []
        for index in range(3):
            values = sorted(sample[index] for sample in samples)
            channels.append(values[len(values) // 2])
        return channels

    def _eroded_mask(mask, radius):
        if radius <= 0:
            return [bytearray(row) for row in mask]
        height = len(mask)
        width = len(mask[0]) if height else 0
        result = [bytearray(width) for _ in range(height)]
        for y in range(height):
            for x in range(width):
                if not mask[y][x]:
                    continue
                keep = True
                for dy in range(-radius, radius + 1):
                    if not keep:
                        break
                    for dx in range(-radius, radius + 1):
                        nx = x + dx
                        ny = y + dy
                        if nx < 0 or nx >= width or ny < 0 or ny >= height or not mask[ny][nx]:
                            keep = False
                            break
                if keep:
                    result[y][x] = 1
        return result

    def _feather_alpha(mask, radius):
        if radius <= 0:
            return 0
        max_distance = radius + 1
        distances = [[-1 for _ in range(width)] for _ in range(height)]
        queue = deque()
        for y in range(height):
            for x in range(width):
                if not mask[y][x]:
                    continue
                touches_transparent = False
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nx = x + dx
                    ny = y + dy
                    if nx < 0 or nx >= width or ny < 0 or ny >= height or not mask[ny][nx]:
                        touches_transparent = True
                        break
                if touches_transparent:
                    distances[y][x] = 1
                    queue.append((x, y, 1))

        while queue:
            x, y, distance = queue.popleft()
            if distance >= max_distance:
                continue
            next_distance = distance + 1
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx = x + dx
                ny = y + dy
                if nx < 0 or nx >= width or ny < 0 or ny >= height:
                    continue
                if not mask[ny][nx] or distances[ny][nx] != -1:
                    continue
                distances[ny][nx] = next_distance
                queue.append((nx, ny, next_distance))

        feathered = 0
        for y in range(height):
            for x in range(width):
                distance = distances[y][x]
                if distance <= 0 or distance >= max_distance:
                    continue
                color = image.pixelColor(x, y)
                original_alpha = color.alpha()
                faded_alpha = int(round(original_alpha * (distance / float(max_distance))))
                if faded_alpha != original_alpha:
                    color.setAlpha(max(0, min(255, faded_alpha)))
                    image.setPixelColor(x, y, color)
                    feathered += 1
        return feathered

    if not image_path:
        raise ValueError("image_path is required.")
    normalized_image_path = os.path.normpath(image_path)
    if not os.path.isfile(normalized_image_path):
        raise ValueError(f"Image path does not exist: {image_path}")

    alpha_threshold = _clamp(_validate_scalar(alpha_threshold, "alpha_threshold"))
    unmatte_strength = _clamp(_validate_scalar(unmatte_strength, "unmatte_strength"))
    erode_alpha_pixels = _validate_int(erode_alpha_pixels, "erode_alpha_pixels", 0)
    feather_alpha_pixels = _validate_int(feather_alpha_pixels, "feather_alpha_pixels", 0)
    if not isinstance(unmatte_background, bool):
        raise ValueError("unmatte_background must be a boolean.")
    if not isinstance(fill_transparent_rgb, bool):
        raise ValueError("fill_transparent_rgb must be a boolean.")
    if not isinstance(overwrite, bool):
        raise ValueError("overwrite must be a boolean.")

    image = QImage(normalized_image_path)
    if image.isNull():
        raise ValueError(f"Unable to load image: {image_path}")
    image = image.convertToFormat(QImage.Format_ARGB32)
    width = image.width()
    height = image.height()
    if width < 1 or height < 1:
        raise ValueError("image must not be empty.")

    clean_background = (
        _validate_color(background_color, "background_color")
        if background_color is not None
        else _estimate_background(image)
    )

    visible_mask = [bytearray(width) for _ in range(height)]
    thresholded_alpha_pixels = 0
    unmatte_pixels = 0
    for y in range(height):
        for x in range(width):
            color = image.pixelColor(x, y)
            alpha = color.alphaF()
            if alpha <= alpha_threshold:
                if color.alpha() != 0:
                    thresholded_alpha_pixels += 1
                color.setAlpha(0)
                image.setPixelColor(x, y, color)
                continue

            visible_mask[y][x] = 1
            if unmatte_background and alpha < 1.0 and alpha > 1e-6:
                source = [color.redF(), color.greenF(), color.blueF()]
                cleaned = []
                for index, channel in enumerate(source):
                    unmatted = (channel - clean_background[index] * (1.0 - alpha)) / alpha
                    cleaned.append(channel + (_clamp(unmatted) - channel) * unmatte_strength)
                color.setRgbF(cleaned[0], cleaned[1], cleaned[2], alpha)
                image.setPixelColor(x, y, color)
                unmatte_pixels += 1

    if erode_alpha_pixels > 0:
        eroded = _eroded_mask(visible_mask, erode_alpha_pixels)
        for y in range(height):
            for x in range(width):
                if visible_mask[y][x] and not eroded[y][x]:
                    color = image.pixelColor(x, y)
                    if color.alpha() != 0:
                        color.setAlpha(0)
                        image.setPixelColor(x, y, color)
                        thresholded_alpha_pixels += 1
        visible_mask = eroded

    feathered_alpha_pixels = _feather_alpha(visible_mask, feather_alpha_pixels)

    filled_rgb_pixels = 0
    if fill_transparent_rgb:
        visited = [bytearray(width) for _ in range(height)]
        queue = deque()
        for y in range(height):
            for x in range(width):
                color = image.pixelColor(x, y)
                if color.alphaF() > alpha_threshold:
                    visited[y][x] = 1
                    queue.append((x, y, color.red(), color.green(), color.blue()))

        while queue:
            x, y, red, green, blue = queue.popleft()
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx = x + dx
                ny = y + dy
                if nx < 0 or nx >= width or ny < 0 or ny >= height or visited[ny][nx]:
                    continue
                visited[ny][nx] = 1
                color = image.pixelColor(nx, ny)
                image.setPixelColor(nx, ny, QColor(red, green, blue, color.alpha()))
                queue.append((nx, ny, red, green, blue))
                filled_rgb_pixels += 1

    if output_path is None:
        base_name = os.path.splitext(os.path.basename(normalized_image_path))[0] or "image"
        output_path = os.path.join(os.path.dirname(normalized_image_path), f"{base_name}_alpha_clean.png")
    normalized_output_path = os.path.normpath(output_path)
    if not os.path.splitext(normalized_output_path)[1]:
        normalized_output_path += ".png"
    output_dir = os.path.dirname(normalized_output_path)
    if output_dir and not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    if os.path.exists(normalized_output_path) and not overwrite:
        raise ValueError(f"Output path already exists: {output_path}")
    if not image.save(normalized_output_path):
        raise RuntimeError(f"Failed to save cleaned alpha texture: {output_path}")

    visible_pixels = 0
    transparent_pixels = 0
    semi_transparent_pixels = 0
    for y in range(height):
        for x in range(width):
            alpha = image.pixelColor(x, y).alpha()
            if alpha == 0:
                transparent_pixels += 1
            else:
                visible_pixels += 1
                if alpha < 255:
                    semi_transparent_pixels += 1

    return {
        "success": True,
        "image_path": normalized_image_path,
        "output_path": normalized_output_path,
        "image_width": width,
        "image_height": height,
        "background_color": clean_background,
        "alpha_threshold": alpha_threshold,
        "unmatte_background": bool(unmatte_background),
        "unmatte_strength": unmatte_strength,
        "erode_alpha_pixels": erode_alpha_pixels,
        "feather_alpha_pixels": feather_alpha_pixels,
        "fill_transparent_rgb": bool(fill_transparent_rgb),
        "thresholded_alpha_pixels": thresholded_alpha_pixels,
        "feathered_alpha_pixels": feathered_alpha_pixels,
        "unmatte_pixels": unmatte_pixels,
        "filled_rgb_pixels": filled_rgb_pixels,
        "visible_pixels": visible_pixels,
        "transparent_pixels": transparent_pixels,
        "semi_transparent_pixels": semi_transparent_pixels,
    }
