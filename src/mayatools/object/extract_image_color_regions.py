from typing import Dict, List, Any


def extract_image_color_regions(
    image_path: str,
    target_color: List[float] = None,
    match_mode: str = "rgb",
    color_tolerance: float = 0.25,
    hue_tolerance: float = 0.05,
    saturation_min: float = 0.25,
    value_min: float = 0.05,
    crop: List[float] = [0.0, 0.0, 1.0, 1.0],
    alpha_threshold: float = 0.05,
    background_color: List[float] = None,
    background_tolerance: float = 0.06,
    reference_bbox_pixels: List[float] = None,
    target_height: float = 0.0,
    min_component_pixels: int = 25,
    min_component_width: int = 2,
    min_component_height: int = 2,
    min_band_row_pixels: int = 5,
    max_regions: int = 20,
) -> Dict[str, Any]:
    """Extract connected image regions that match a color or foreground mask.

    This is a generic reference-measurement helper for product modeling. It can
    find RGB-distance matches, hue matches, or non-background foreground regions,
    then report connected components, horizontal bands, normalized image bounds,
    and optional product-height-space measurements.
    """
    import os

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

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return value

    def _clamp(value, lower, upper):
        return max(lower, min(upper, value))

    def _normalize_color(values, arg_name):
        color = _validate_vector(values, 3, arg_name)
        if max(color) > 1.0:
            color = [value / 255.0 for value in color]
        return [_clamp(value, 0.0, 1.0) for value in color]

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

    def _rgb_to_hsv(red, green, blue):
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

    def _hue_distance(hue_a, hue_b):
        direct = abs(hue_a - hue_b)
        return min(direct, 1.0 - direct)

    def _estimate_background(image, x_min, y_min, x_max, y_max):
        sample_points = []
        inset_x = max(1, int((x_max - x_min) * 0.03))
        inset_y = max(1, int((y_max - y_min) * 0.03))
        radius = max(1, min(inset_x, inset_y, 8))
        corners = [
            (x_min + inset_x, y_min + inset_y),
            (x_max - inset_x, y_min + inset_y),
            (x_min + inset_x, y_max - inset_y),
            (x_max - inset_x, y_max - inset_y),
        ]
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

    def _height_space_from_bbox(bbox, reference_bbox):
        if target_height <= 0.0 or reference_bbox is None:
            return None
        ref_height = max(1e-9, float(reference_bbox[3] - reference_bbox[1]))
        bottom_height = (reference_bbox[3] - bbox[3]) / ref_height * target_height
        top_height = (reference_bbox[3] - bbox[1]) / ref_height * target_height
        region_height = max(0.0, top_height - bottom_height)
        width = (bbox[2] - bbox[0]) / ref_height * target_height
        return {
            "bottom": bottom_height,
            "top": top_height,
            "center": (bottom_height + top_height) * 0.5,
            "height": region_height,
            "width": width,
        }

    def _normalized_bbox(bbox, image_width, image_height):
        return [
            bbox[0] / float(image_width - 1),
            bbox[1] / float(image_height - 1),
            bbox[2] / float(image_width - 1),
            bbox[3] / float(image_height - 1),
        ]

    if not image_path:
        raise ValueError("image_path is required.")
    normalized_image_path = os.path.normpath(image_path)
    if not os.path.isfile(normalized_image_path):
        raise ValueError(f"Image path does not exist: {image_path}")

    match_mode = match_mode.lower().strip()
    if match_mode not in {"rgb", "hue", "foreground"}:
        raise ValueError("match_mode must be one of rgb, hue, or foreground.")
    clean_target_color = None
    target_hsv = None
    if match_mode in {"rgb", "hue"}:
        if target_color is None:
            raise ValueError("target_color is required for rgb and hue match modes.")
        clean_target_color = _normalize_color(target_color, "target_color")
        target_hsv = _rgb_to_hsv(clean_target_color[0], clean_target_color[1], clean_target_color[2])

    color_tolerance = _validate_scalar(color_tolerance, "color_tolerance")
    if color_tolerance > 1.0:
        color_tolerance /= 255.0
    if color_tolerance < 0.0:
        raise ValueError("color_tolerance must be greater than or equal to zero.")
    hue_tolerance = _validate_scalar(hue_tolerance, "hue_tolerance")
    if hue_tolerance > 1.0:
        hue_tolerance /= 360.0
    if hue_tolerance < 0.0 or hue_tolerance > 0.5:
        raise ValueError("hue_tolerance must be in the 0..0.5 range, or degrees in the 0..180 range.")
    saturation_min = _clamp(_validate_scalar(saturation_min, "saturation_min"), 0.0, 1.0)
    value_min = _clamp(_validate_scalar(value_min, "value_min"), 0.0, 1.0)
    alpha_threshold = _validate_scalar(alpha_threshold, "alpha_threshold")
    if alpha_threshold < 0.0 or alpha_threshold > 1.0:
        raise ValueError("alpha_threshold must be in the 0..1 range.")
    background_tolerance = _validate_scalar(background_tolerance, "background_tolerance")
    if background_tolerance > 1.0:
        background_tolerance /= 255.0
    if background_tolerance < 0.0:
        raise ValueError("background_tolerance must be greater than or equal to zero.")
    target_height = _validate_scalar(target_height, "target_height")
    if target_height < 0.0:
        raise ValueError("target_height must be greater than or equal to zero.")
    crop = _validate_vector(crop, 4, "crop")
    crop = [_clamp(value, 0.0, 1.0) for value in crop]
    if crop[2] <= crop[0] or crop[3] <= crop[1]:
        raise ValueError("crop must be [min_x, min_y, max_x, max_y] in normalized image coordinates.")
    min_component_pixels = _validate_int(min_component_pixels, "min_component_pixels", 1)
    min_component_width = _validate_int(min_component_width, "min_component_width", 1)
    min_component_height = _validate_int(min_component_height, "min_component_height", 1)
    min_band_row_pixels = _validate_int(min_band_row_pixels, "min_band_row_pixels", 1)
    max_regions = _validate_int(max_regions, "max_regions", 1)

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
    crop_width = x_max - x_min + 1
    crop_height = y_max - y_min + 1

    clean_background_color = None
    if background_color is None:
        clean_background_color = _estimate_background(image, x_min, y_min, x_max, y_max)
    else:
        clean_background_color = _normalize_color(background_color, "background_color")

    reference_bbox = None
    if reference_bbox_pixels is not None:
        reference_bbox = _validate_vector(reference_bbox_pixels, 4, "reference_bbox_pixels")
    matched = [bytearray(crop_width) for _ in range(crop_height)]
    foreground_bbox = None
    row_stats = []
    matched_count = 0

    for local_y, y in enumerate(range(y_min, y_max + 1)):
        row_count = 0
        row_min = None
        row_max = None
        for local_x, x in enumerate(range(x_min, x_max + 1)):
            red, green, blue, alpha = _pixel_rgb_alpha(image, x, y)
            if alpha < alpha_threshold:
                continue
            rgb = [red, green, blue]
            is_foreground = _color_distance(rgb, clean_background_color) > background_tolerance
            if is_foreground:
                if foreground_bbox is None:
                    foreground_bbox = [x, y, x, y]
                else:
                    foreground_bbox[0] = min(foreground_bbox[0], x)
                    foreground_bbox[1] = min(foreground_bbox[1], y)
                    foreground_bbox[2] = max(foreground_bbox[2], x)
                    foreground_bbox[3] = max(foreground_bbox[3], y)

            if match_mode == "foreground":
                is_match = is_foreground
            elif match_mode == "rgb":
                is_match = _color_distance(rgb, clean_target_color) <= color_tolerance
            else:
                hue, saturation, value = _rgb_to_hsv(red, green, blue)
                is_match = (
                    _hue_distance(hue, target_hsv[0]) <= hue_tolerance
                    and saturation >= saturation_min
                    and value >= value_min
                )
            if not is_match:
                continue
            matched[local_y][local_x] = 1
            matched_count += 1
            row_count += 1
            row_min = x if row_min is None else min(row_min, x)
            row_max = x if row_max is None else max(row_max, x)
        row_stats.append({"y": y, "count": row_count, "min_x": row_min, "max_x": row_max})

    if reference_bbox is None:
        reference_bbox = foreground_bbox

    visited = [bytearray(crop_width) for _ in range(crop_height)]
    components = []
    for local_y in range(crop_height):
        for local_x in range(crop_width):
            if not matched[local_y][local_x] or visited[local_y][local_x]:
                continue
            stack = [(local_x, local_y)]
            visited[local_y][local_x] = 1
            count = 0
            min_x = max_x = x_min + local_x
            min_y = max_y = y_min + local_y
            sum_red = sum_green = sum_blue = 0.0
            while stack:
                current_x, current_y = stack.pop()
                image_x = x_min + current_x
                image_y = y_min + current_y
                red, green, blue, _ = _pixel_rgb_alpha(image, image_x, image_y)
                sum_red += red
                sum_green += green
                sum_blue += blue
                count += 1
                min_x = min(min_x, image_x)
                max_x = max(max_x, image_x)
                min_y = min(min_y, image_y)
                max_y = max(max_y, image_y)
                for next_x, next_y in [
                    (current_x - 1, current_y),
                    (current_x + 1, current_y),
                    (current_x, current_y - 1),
                    (current_x, current_y + 1),
                ]:
                    if next_x < 0 or next_y < 0 or next_x >= crop_width or next_y >= crop_height:
                        continue
                    if visited[next_y][next_x] or not matched[next_y][next_x]:
                        continue
                    visited[next_y][next_x] = 1
                    stack.append((next_x, next_y))
            bbox = [min_x, min_y, max_x, max_y]
            width = max_x - min_x + 1
            height = max_y - min_y + 1
            if count < min_component_pixels or width < min_component_width or height < min_component_height:
                continue
            components.append(
                {
                    "pixel_count": count,
                    "bbox_pixels": bbox,
                    "bbox_normalized": _normalized_bbox(bbox, image_width, image_height),
                    "center_pixels": [(min_x + max_x) * 0.5, (min_y + max_y) * 0.5],
                    "width_pixels": width,
                    "height_pixels": height,
                    "mean_color": [sum_red / count, sum_green / count, sum_blue / count],
                    "height_space": _height_space_from_bbox(bbox, reference_bbox),
                }
            )

    components.sort(key=lambda component: component["pixel_count"], reverse=True)
    components = components[:max_regions]

    bands = []
    active_band = None
    for row in row_stats:
        if row["count"] >= min_band_row_pixels:
            if active_band is None:
                active_band = {
                    "min_y": row["y"],
                    "max_y": row["y"],
                    "min_x": row["min_x"],
                    "max_x": row["max_x"],
                    "pixel_count": row["count"],
                }
            else:
                active_band["max_y"] = row["y"]
                active_band["min_x"] = min(active_band["min_x"], row["min_x"])
                active_band["max_x"] = max(active_band["max_x"], row["max_x"])
                active_band["pixel_count"] += row["count"]
        elif active_band is not None:
            bbox = [active_band["min_x"], active_band["min_y"], active_band["max_x"], active_band["max_y"]]
            bands.append(
                {
                    "pixel_count": active_band["pixel_count"],
                    "bbox_pixels": bbox,
                    "bbox_normalized": _normalized_bbox(bbox, image_width, image_height),
                    "height_space": _height_space_from_bbox(bbox, reference_bbox),
                }
            )
            active_band = None
    if active_band is not None:
        bbox = [active_band["min_x"], active_band["min_y"], active_band["max_x"], active_band["max_y"]]
        bands.append(
            {
                "pixel_count": active_band["pixel_count"],
                "bbox_pixels": bbox,
                "bbox_normalized": _normalized_bbox(bbox, image_width, image_height),
                "height_space": _height_space_from_bbox(bbox, reference_bbox),
            }
        )

    bands.sort(key=lambda band: band["bbox_pixels"][1])

    return {
        "success": True,
        "image_path": normalized_image_path,
        "image_width": image_width,
        "image_height": image_height,
        "crop_pixels": [x_min, y_min, x_max, y_max],
        "target_color": clean_target_color,
        "match_mode": match_mode,
        "color_tolerance": color_tolerance,
        "hue_tolerance": hue_tolerance,
        "saturation_min": saturation_min,
        "value_min": value_min,
        "background_color": clean_background_color,
        "background_tolerance": background_tolerance,
        "foreground_bbox_pixels": foreground_bbox,
        "reference_bbox_pixels": reference_bbox,
        "matched_count": matched_count,
        "components": components,
        "horizontal_bands": bands,
    }
