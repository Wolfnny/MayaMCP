from typing import Dict, List, Any


def extract_revolved_profile_from_image(
    image_path: str,
    target_height: float = 1.0,
    height_samples: int = 64,
    background_color: List[float] = None,
    background_tolerance: float = 0.06,
    alpha_threshold: float = 0.05,
    crop: List[float] = [0.0, 0.0, 1.0, 1.0],
    axis_x: float = None,
    side: str = "both",
    smoothing_window: int = 3,
    min_row_pixels: int = 2,
    radius_scale: float = 1.0,
    radius_offset: float = 0.0,
    create_profile_curve: bool = False,
    curve_name: str = None,
    center: List[float] = [0.0, 0.0, 0.0],
) -> Dict[str, Any]:
    """Extract a lathe-ready radius/height profile from a product silhouette image.

    The image is segmented by comparing pixels against a background color. If no
    background_color is provided, it is estimated from the crop corners. Explicit
    background_color values may be provided in either 0..1 or 0..255 range. The
    returned profile is ordered bottom-to-top as [height, radius] points, making
    it directly usable with create_revolved_mesh, create_revolved_shell, and
    create_textured_label surface_profile.
    """
    import os
    import maya.cmds as cmds

    try:
        from PySide6.QtGui import QImage
    except Exception:
        try:
            from PySide2.QtGui import QImage
        except Exception as exc:
            raise RuntimeError("PySide QImage is required to read image pixels in Maya.") from exc

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(v) for v in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(value) for value in values]

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

    def _clamp(value, lower, upper):
        return max(lower, min(upper, value))

    def _pixel_rgb_alpha(image, x, y):
        color = image.pixelColor(int(x), int(y))
        return (
            color.redF(),
            color.greenF(),
            color.blueF(),
            color.alphaF(),
        )

    def _color_distance(color_a, color_b):
        dr = color_a[0] - color_b[0]
        dg = color_a[1] - color_b[1]
        db = color_a[2] - color_b[2]
        return (dr * dr + dg * dg + db * db) ** 0.5

    def _estimate_background(image, x_min, y_min, x_max, y_max):
        sample_points = []
        inset_x = max(1, int((x_max - x_min) * 0.03))
        inset_y = max(1, int((y_max - y_min) * 0.03))
        corners = [
            (x_min + inset_x, y_min + inset_y),
            (x_max - inset_x, y_min + inset_y),
            (x_min + inset_x, y_max - inset_y),
            (x_max - inset_x, y_max - inset_y),
        ]
        radius = max(1, min(inset_x, inset_y, 8))
        for corner_x, corner_y in corners:
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    x = int(_clamp(corner_x + dx, x_min, x_max))
                    y = int(_clamp(corner_y + dy, y_min, y_max))
                    sample_points.append(_pixel_rgb_alpha(image, x, y)[:3])
        if not sample_points:
            return [1.0, 1.0, 1.0]
        channels = []
        for index in range(3):
            values = sorted(point[index] for point in sample_points)
            channels.append(values[len(values) // 2])
        return channels

    def _moving_average(values, window):
        if window <= 1:
            return values[:]
        half = window // 2
        smoothed = []
        for index in range(len(values)):
            start = max(0, index - half)
            end = min(len(values), index + half + 1)
            smoothed.append(sum(values[start:end]) / float(end - start))
        return smoothed

    if not image_path:
        raise ValueError("image_path is required.")
    normalized_image_path = os.path.normpath(image_path)
    if not os.path.isfile(normalized_image_path):
        raise ValueError(f"Image path does not exist: {image_path}")
    target_height = _validate_scalar(target_height, "target_height")
    if target_height <= 0.0:
        raise ValueError("target_height must be greater than zero.")
    if not isinstance(height_samples, int) or isinstance(height_samples, bool) or height_samples < 2:
        raise ValueError("height_samples must be an integer greater than or equal to 2.")
    background_tolerance = _validate_scalar(background_tolerance, "background_tolerance")
    if background_tolerance < 0.0:
        raise ValueError("background_tolerance must be greater than or equal to zero.")
    alpha_threshold = _validate_scalar(alpha_threshold, "alpha_threshold")
    if alpha_threshold < 0.0 or alpha_threshold > 1.0:
        raise ValueError("alpha_threshold must be in the 0..1 range.")
    crop = _validate_vector(crop, 4, "crop")
    if crop[2] <= crop[0] or crop[3] <= crop[1]:
        raise ValueError("crop must be [min_x, min_y, max_x, max_y] in normalized image coordinates.")
    crop = [_clamp(value, 0.0, 1.0) for value in crop]
    if crop[2] <= crop[0] or crop[3] <= crop[1]:
        raise ValueError("crop must define a non-empty normalized region.")
    if axis_x is not None:
        axis_x = _validate_scalar(axis_x, "axis_x")
        if axis_x < 0.0 or axis_x > 1.0:
            raise ValueError("axis_x must be None or a normalized 0..1 image coordinate.")
    side = side.lower().strip()
    if side not in {"both", "left", "right"}:
        raise ValueError("side must be one of both, left, or right.")
    if not isinstance(smoothing_window, int) or isinstance(smoothing_window, bool) or smoothing_window < 1:
        raise ValueError("smoothing_window must be an integer greater than or equal to 1.")
    if smoothing_window % 2 == 0:
        smoothing_window += 1
    if not isinstance(min_row_pixels, int) or isinstance(min_row_pixels, bool) or min_row_pixels < 1:
        raise ValueError("min_row_pixels must be an integer greater than or equal to 1.")
    radius_scale = _validate_scalar(radius_scale, "radius_scale")
    radius_offset = _validate_scalar(radius_offset, "radius_offset")
    center = _validate_vector(center, 3, "center")

    image = QImage(normalized_image_path)
    if image.isNull():
        raise ValueError(f"Unable to load image: {image_path}")
    image_width = image.width()
    image_height = image.height()
    if image_width < 2 or image_height < 2:
        raise ValueError("image must be at least 2x2 pixels.")

    x_min = int(round(crop[0] * (image_width - 1)))
    y_min = int(round(crop[1] * (image_height - 1)))
    x_max = int(round(crop[2] * (image_width - 1)))
    y_max = int(round(crop[3] * (image_height - 1)))
    x_min = max(0, min(image_width - 1, x_min))
    x_max = max(0, min(image_width - 1, x_max))
    y_min = max(0, min(image_height - 1, y_min))
    y_max = max(0, min(image_height - 1, y_max))

    if background_color is None:
        clean_background_color = _estimate_background(image, x_min, y_min, x_max, y_max)
    else:
        clean_background_color = _validate_vector(background_color, 3, "background_color")
        if max(clean_background_color) > 1.0:
            clean_background_color = [value / 255.0 for value in clean_background_color]
        clean_background_color = [_clamp(value, 0.0, 1.0) for value in clean_background_color]

    foreground_rows = {}
    foreground_count = 0
    foreground_bbox = None
    for y in range(y_min, y_max + 1):
        row_xs = []
        for x in range(x_min, x_max + 1):
            red, green, blue, alpha = _pixel_rgb_alpha(image, x, y)
            if alpha < alpha_threshold:
                continue
            if _color_distance([red, green, blue], clean_background_color) <= background_tolerance:
                continue
            row_xs.append(x)
        if len(row_xs) >= min_row_pixels:
            foreground_rows[y] = row_xs
            foreground_count += len(row_xs)
            row_min = min(row_xs)
            row_max = max(row_xs)
            if foreground_bbox is None:
                foreground_bbox = [row_min, y, row_max, y]
            else:
                foreground_bbox[0] = min(foreground_bbox[0], row_min)
                foreground_bbox[1] = min(foreground_bbox[1], y)
                foreground_bbox[2] = max(foreground_bbox[2], row_max)
                foreground_bbox[3] = max(foreground_bbox[3], y)

    if foreground_bbox is None:
        raise ValueError("No foreground silhouette pixels were found. Adjust crop, background_color, or background_tolerance.")

    if axis_x is None:
        axis_x_pixels = (foreground_bbox[0] + foreground_bbox[2]) * 0.5
    else:
        axis_x_pixels = axis_x * (image_width - 1)

    foreground_height_pixels = max(1.0, float(foreground_bbox[3] - foreground_bbox[1]))
    raw_heights = []
    raw_radii = []
    source_rows = []
    band_radius = max(0, int(round((foreground_bbox[3] - foreground_bbox[1]) / max(1.0, height_samples * 2.0))))
    for sample_index in range(height_samples):
        t = sample_index / float(height_samples - 1)
        source_y = foreground_bbox[3] - t * (foreground_bbox[3] - foreground_bbox[1])
        row_radius_values = []
        for row_y in range(int(round(source_y)) - band_radius, int(round(source_y)) + band_radius + 1):
            if row_y not in foreground_rows:
                continue
            row_xs = foreground_rows[row_y]
            left_x = min(row_xs)
            right_x = max(row_xs)
            if side == "left":
                radius_pixels = max(0.0, axis_x_pixels - left_x)
            elif side == "right":
                radius_pixels = max(0.0, right_x - axis_x_pixels)
            else:
                radius_pixels = (max(0.0, axis_x_pixels - left_x) + max(0.0, right_x - axis_x_pixels)) * 0.5
            row_radius_values.append(radius_pixels)
        if not row_radius_values:
            if raw_radii:
                height = t * target_height
                raw_heights.append(height)
                raw_radii.append(raw_radii[-1])
                source_rows.append(int(round(source_y)))
                continue
            else:
                radius_pixels = 0.0
        else:
            row_radius_values = sorted(row_radius_values)
            radius_pixels = row_radius_values[len(row_radius_values) // 2]
        height = t * target_height
        radius = radius_pixels / foreground_height_pixels * target_height
        raw_heights.append(height)
        raw_radii.append(max(0.0, radius * radius_scale + radius_offset))
        source_rows.append(int(round(source_y)))

    smoothed_radii = _moving_average(raw_radii, smoothing_window)
    profile = []
    for height, radius in zip(raw_heights, smoothed_radii):
        profile.append([height, max(0.0, radius)])

    created_curve = None
    if create_profile_curve:
        if curve_name is None:
            base_name = os.path.splitext(os.path.basename(normalized_image_path))[0] or "image"
            curve_name = f"{base_name}_silhouette_profile_curve"
        points = [[center[0] + radius, center[1] + height, center[2]] for height, radius in profile]
        created_curve = cmds.curve(name=curve_name, degree=1, point=points)

    return {
        "success": True,
        "image_path": normalized_image_path,
        "image_width": image_width,
        "image_height": image_height,
        "crop_pixels": [x_min, y_min, x_max, y_max],
        "background_color": clean_background_color,
        "background_tolerance": background_tolerance,
        "foreground_count": foreground_count,
        "foreground_bbox_pixels": foreground_bbox,
        "axis_x_pixels": axis_x_pixels,
        "side": side,
        "target_height": target_height,
        "height_samples": height_samples,
        "smoothing_window": smoothing_window,
        "radius_scale": radius_scale,
        "radius_offset": radius_offset,
        "profile": profile,
        "source_rows": source_rows,
        "created_curve": created_curve,
    }
