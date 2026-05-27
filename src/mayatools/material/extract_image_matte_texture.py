from typing import Dict, List, Any


def extract_image_matte_texture(
    image_path: str,
    output_path: str = None,
    bbox_pixels: List[float] = None,
    bbox_normalized: List[float] = None,
    padding_pixels: int = 0,
    output_width: int = 0,
    output_height: int = 0,
    stretch_to_output: bool = True,
    horizontal_remap: str = "none",
    source_arc_degrees: float = 120.0,
    remap_center_x: float = 0.5,
    match_mode: str = "hue",
    target_color: List[float] = None,
    color_tolerance: float = 0.25,
    hue_tolerance: float = 0.05,
    saturation_min: float = 0.25,
    value_min: float = 0.05,
    alpha_threshold: float = 0.05,
    background_color: List[float] = None,
    background_tolerance: float = 0.06,
    component_selection: str = "largest",
    seed_pixels: List[float] = None,
    seed_normalized: List[float] = None,
    component_connectivity: int = 8,
    min_component_pixels: int = 25,
    matte_mode: str = "row_span",
    matte_expand_pixels: int = 0,
    overwrite: bool = True,
) -> Dict[str, Any]:
    """Extract a cropped texture with alpha matte derived from image regions.

    The crop can be masked by RGB, hue, foreground, or source alpha. A connected
    component is selected from the mask, then converted into an output matte as
    exact matched pixels, per-row spans, or a component bbox. Row-span and bbox
    mattes preserve all original colors inside the selected region, which is
    useful for generic labels, decals, badges, signs, panels, patches, and
    product graphics where internal artwork should remain opaque even when it
    differs from the target color used to find the region.
    """
    import math
    import os

    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage, QColor, QPainter
    except Exception:
        try:
            from PySide2.QtCore import Qt
            from PySide2.QtGui import QImage, QColor, QPainter
        except Exception as exc:
            raise RuntimeError("PySide QImage is required to extract matte textures in Maya.") from exc

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

    def _clamp(value, lower=0.0, upper=1.0):
        return max(lower, min(upper, value))

    def _normalize_color(values, arg_name):
        color = _validate_vector(values, 3, arg_name)
        if max(color) > 1.0:
            color = [value / 255.0 for value in color]
        return [_clamp(value) for value in color]

    def _pixel_rgb_alpha(image, x, y):
        color = image.pixelColor(int(x), int(y))
        return color.redF(), color.greenF(), color.blueF(), color.alphaF()

    def _make_color(red, green, blue, alpha):
        color = QColor()
        color.setRgbF(_clamp(red), _clamp(green), _clamp(blue), _clamp(alpha))
        return color

    def _color_distance(a, b):
        dr = a[0] - b[0]
        dg = a[1] - b[1]
        db = a[2] - b[2]
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

    def _hue_distance(a, b):
        direct = abs(a - b)
        return min(direct, 1.0 - direct)

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

    def _scale_keep_aspect(image, target_width, target_height):
        scaled = image.scaled(target_width, target_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        canvas = QImage(target_width, target_height, QImage.Format_ARGB32)
        canvas.fill(QColor(0, 0, 0, 0))
        painter = QPainter(canvas)
        offset_x = int((target_width - scaled.width()) * 0.5)
        offset_y = int((target_height - scaled.height()) * 0.5)
        painter.drawImage(offset_x, offset_y, scaled)
        painter.end()
        return canvas

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

    def _build_match_mask(image, mode):
        width = image.width()
        height = image.height()
        matched = [bytearray(width) for _ in range(height)]
        matched_count = 0
        for y in range(height):
            row = matched[y]
            for x in range(width):
                red, green, blue, alpha = _pixel_rgb_alpha(image, x, y)
                if alpha < alpha_threshold:
                    continue
                rgb = [red, green, blue]
                is_match = False
                if mode == "alpha":
                    is_match = alpha >= alpha_threshold
                elif mode == "foreground":
                    is_match = _color_distance(rgb, clean_background_color) > background_tolerance
                elif mode == "rgb":
                    is_match = _color_distance(rgb, clean_target_color) <= color_tolerance
                elif mode == "hue":
                    hue, saturation, value = _rgb_to_hsv(red, green, blue)
                    is_match = (
                        _hue_distance(hue, target_hsv[0]) <= hue_tolerance
                        and saturation >= saturation_min
                        and value >= value_min
                    )
                if is_match:
                    row[x] = 1
                    matched_count += 1
        return matched, matched_count

    def _find_components(mask, width, height):
        visited = [bytearray(width) for _ in range(height)]
        if component_connectivity == 4:
            neighbors = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        else:
            neighbors = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1)]
        components = []
        for y in range(height):
            for x in range(width):
                if not mask[y][x] or visited[y][x]:
                    continue
                stack = [(x, y)]
                visited[y][x] = 1
                pixels = []
                x_min = x_max = x
                y_min = y_max = y
                while stack:
                    current_x, current_y = stack.pop()
                    pixels.append((current_x, current_y))
                    x_min = min(x_min, current_x)
                    x_max = max(x_max, current_x)
                    y_min = min(y_min, current_y)
                    y_max = max(y_max, current_y)
                    for dx, dy in neighbors:
                        next_x = current_x + dx
                        next_y = current_y + dy
                        if next_x < 0 or next_x >= width or next_y < 0 or next_y >= height:
                            continue
                        if visited[next_y][next_x] or not mask[next_y][next_x]:
                            continue
                        visited[next_y][next_x] = 1
                        stack.append((next_x, next_y))
                if len(pixels) >= min_component_pixels:
                    components.append({
                        "pixels": pixels,
                        "pixel_count": len(pixels),
                        "bbox_pixels": [x_min, y_min, x_max, y_max],
                        "width_pixels": x_max - x_min + 1,
                        "height_pixels": y_max - y_min + 1,
                    })
        components.sort(key=lambda item: item["pixel_count"], reverse=True)
        return components

    def _select_component(components, width, height):
        if not components:
            return None
        if component_selection == "seed":
            if seed_pixels is None and seed_normalized is None:
                raise ValueError("seed_pixels or seed_normalized is required when component_selection is seed.")
            if seed_pixels is not None:
                seed = _validate_vector(seed_pixels, 2, "seed_pixels")
                seed_x = int(round(seed[0]))
                seed_y = int(round(seed[1]))
            else:
                seed = _validate_vector(seed_normalized, 2, "seed_normalized")
                seed_x = int(round(_clamp(seed[0]) * (width - 1)))
                seed_y = int(round(_clamp(seed[1]) * (height - 1)))
            for component in components:
                x_min, y_min, x_max, y_max = component["bbox_pixels"]
                if x_min <= seed_x <= x_max and y_min <= seed_y <= y_max:
                    if (seed_x, seed_y) in set(component["pixels"]):
                        return component
            raise ValueError("No selected component contains the seed point.")
        return components[0]

    def _expanded_bbox(bbox, width, height):
        return [
            max(0, bbox[0] - matte_expand_pixels),
            max(0, bbox[1] - matte_expand_pixels),
            min(width - 1, bbox[2] + matte_expand_pixels),
            min(height - 1, bbox[3] + matte_expand_pixels),
        ]

    def _component_to_alpha(component, width, height):
        alpha = [bytearray(width) for _ in range(height)]
        if component is None:
            return alpha
        if matte_mode == "match":
            for x, y in component["pixels"]:
                for yy in range(max(0, y - matte_expand_pixels), min(height - 1, y + matte_expand_pixels) + 1):
                    for xx in range(max(0, x - matte_expand_pixels), min(width - 1, x + matte_expand_pixels) + 1):
                        alpha[yy][xx] = 255
        elif matte_mode == "bbox":
            x_min, y_min, x_max, y_max = _expanded_bbox(component["bbox_pixels"], width, height)
            for y in range(y_min, y_max + 1):
                for x in range(x_min, x_max + 1):
                    alpha[y][x] = 255
        else:
            row_bounds = {}
            for x, y in component["pixels"]:
                if y not in row_bounds:
                    row_bounds[y] = [x, x]
                else:
                    row_bounds[y][0] = min(row_bounds[y][0], x)
                    row_bounds[y][1] = max(row_bounds[y][1], x)
            for y, bounds in row_bounds.items():
                x_min = max(0, bounds[0] - matte_expand_pixels)
                x_max = min(width - 1, bounds[1] + matte_expand_pixels)
                y_min = max(0, y - matte_expand_pixels)
                y_max = min(height - 1, y + matte_expand_pixels)
                for yy in range(y_min, y_max + 1):
                    for xx in range(x_min, x_max + 1):
                        alpha[yy][xx] = 255
        return alpha

    def _apply_alpha(image, alpha):
        for y in range(image.height()):
            for x in range(image.width()):
                color = image.pixelColor(x, y)
                color.setAlpha(alpha[y][x])
                image.setPixelColor(x, y, color)

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
    matte_expand_pixels = _validate_int(matte_expand_pixels, "matte_expand_pixels", 0)
    min_component_pixels = _validate_int(min_component_pixels, "min_component_pixels", 1)
    component_connectivity = _validate_int(component_connectivity, "component_connectivity", 4)
    if component_connectivity not in {4, 8}:
        raise ValueError("component_connectivity must be 4 or 8.")

    horizontal_remap = horizontal_remap.lower().strip()
    if horizontal_remap not in {"none", "cylindrical_front"}:
        raise ValueError("horizontal_remap must be one of none or cylindrical_front.")
    source_arc_degrees = _validate_scalar(source_arc_degrees, "source_arc_degrees")
    if source_arc_degrees <= 0.0 or source_arc_degrees >= 180.0:
        raise ValueError("source_arc_degrees must be greater than 0 and less than 180.")
    remap_center_x = _validate_scalar(remap_center_x, "remap_center_x")
    if remap_center_x <= 0.0 or remap_center_x >= 1.0:
        raise ValueError("remap_center_x must be greater than 0 and less than 1.")

    match_mode = match_mode.lower().strip()
    if match_mode not in {"rgb", "hue", "foreground", "alpha"}:
        raise ValueError("match_mode must be one of rgb, hue, foreground, or alpha.")
    component_selection = component_selection.lower().strip()
    if component_selection not in {"largest", "seed"}:
        raise ValueError("component_selection must be one of largest or seed.")
    matte_mode = matte_mode.lower().strip()
    if matte_mode not in {"match", "row_span", "bbox"}:
        raise ValueError("matte_mode must be one of match, row_span, or bbox.")

    color_tolerance = _validate_scalar(color_tolerance, "color_tolerance")
    if color_tolerance > 1.0:
        color_tolerance /= 255.0
    color_tolerance = max(0.0, color_tolerance)
    hue_tolerance = _validate_scalar(hue_tolerance, "hue_tolerance")
    if hue_tolerance > 1.0:
        hue_tolerance /= 360.0
    if hue_tolerance < 0.0 or hue_tolerance > 0.5:
        raise ValueError("hue_tolerance must be in 0..0.5 or degrees in 0..180.")
    saturation_min = _clamp(_validate_scalar(saturation_min, "saturation_min"))
    value_min = _clamp(_validate_scalar(value_min, "value_min"))
    alpha_threshold = _clamp(_validate_scalar(alpha_threshold, "alpha_threshold"))
    background_tolerance = _validate_scalar(background_tolerance, "background_tolerance")
    if background_tolerance > 1.0:
        background_tolerance /= 255.0
    background_tolerance = max(0.0, background_tolerance)

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
        x_min = int(round(_clamp(bbox[0]) * (image_width - 1)))
        y_min = int(round(_clamp(bbox[1]) * (image_height - 1)))
        x_max = int(round(_clamp(bbox[2]) * (image_width - 1)))
        y_max = int(round(_clamp(bbox[3]) * (image_height - 1)))
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

    cropped = image.copy(x_min, y_min, x_max - x_min + 1, y_max - y_min + 1).convertToFormat(QImage.Format_ARGB32)

    clean_target_color = None
    target_hsv = None
    if match_mode in {"rgb", "hue"}:
        if target_color is None:
            raise ValueError("target_color is required for rgb and hue match modes.")
        clean_target_color = _normalize_color(target_color, "target_color")
        target_hsv = _rgb_to_hsv(clean_target_color[0], clean_target_color[1], clean_target_color[2])

    if background_color is None:
        clean_background_color = _estimate_background(cropped)
    else:
        clean_background_color = _normalize_color(background_color, "background_color")

    mask, matched_pixels = _build_match_mask(cropped, match_mode)
    components = _find_components(mask, cropped.width(), cropped.height())
    selected_component = _select_component(components, cropped.width(), cropped.height())
    alpha = _component_to_alpha(selected_component, cropped.width(), cropped.height())
    _apply_alpha(cropped, alpha)

    crop_width = cropped.width()
    crop_height = cropped.height()
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
        output_path = os.path.join(os.path.dirname(normalized_image_path), f"{base_name}_matte.png")
    normalized_output_path = os.path.normpath(output_path)
    if not os.path.splitext(normalized_output_path)[1]:
        normalized_output_path += ".png"
    output_dir = os.path.dirname(normalized_output_path)
    if output_dir and not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    if os.path.exists(normalized_output_path) and not overwrite:
        raise ValueError(f"Output path already exists: {output_path}")
    if not cropped.save(normalized_output_path):
        raise RuntimeError(f"Failed to save matte texture: {output_path}")

    selected_summary = None
    if selected_component is not None:
        selected_summary = {
            "pixel_count": selected_component["pixel_count"],
            "bbox_pixels": selected_component["bbox_pixels"],
            "width_pixels": selected_component["width_pixels"],
            "height_pixels": selected_component["height_pixels"],
        }

    return {
        "success": True,
        "image_path": normalized_image_path,
        "output_path": normalized_output_path,
        "source_image_width": image_width,
        "source_image_height": image_height,
        "crop_bbox_pixels": [x_min, y_min, x_max, y_max],
        "crop_width": crop_width,
        "crop_height": crop_height,
        "output_width": cropped.width(),
        "output_height": cropped.height(),
        "horizontal_remap": horizontal_remap,
        "source_arc_degrees": source_arc_degrees,
        "remap_center_x": remap_center_x,
        "match_mode": match_mode,
        "target_color": clean_target_color,
        "background_color": clean_background_color,
        "matched_pixels": matched_pixels,
        "component_count": len(components),
        "selected_component": selected_summary,
        "component_selection": component_selection,
        "component_connectivity": component_connectivity,
        "matte_mode": matte_mode,
        "matte_expand_pixels": matte_expand_pixels,
    }
