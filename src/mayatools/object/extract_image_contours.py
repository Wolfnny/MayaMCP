from typing import Dict, List, Any


def extract_image_contours(
    image_path: str,
    bbox_pixels: List[float] = None,
    bbox_normalized: List[float] = None,
    match_mode: str = "luminance",
    target_color: List[float] = None,
    color_tolerance: float = 0.25,
    hue_tolerance: float = 0.05,
    saturation_min: float = 0.25,
    value_min: float = 0.05,
    alpha_threshold: float = 0.05,
    background_color: List[float] = None,
    background_tolerance: float = 0.06,
    threshold: float = 0.5,
    invert: bool = False,
    component_connectivity: int = 8,
    min_component_pixels: int = 20,
    max_components: int = 20,
    min_contour_points: int = 8,
    simplify_tolerance_pixels: float = 1.5,
    max_points_per_contour: int = 160,
    close_contours: bool = True,
    create_curves: bool = False,
    curve_name_prefix: str = None,
    curve_mapping: str = "image_plane",
    plane_axis: str = "z",
    plane_width: float = 1.0,
    plane_height: float = 1.0,
    center: List[float] = [0.0, 0.0, 0.0],
    axis: str = "y",
    axis_range: List[float] = [0.0, 1.0],
    angle_range_degrees: List[float] = [-60.0, 60.0],
    radius: float = 1.0,
    surface_profile: List[List[float]] = None,
    profile_interpolation: str = "linear",
    offset: float = 0.02,
) -> Dict[str, Any]:
    """Extract image-mask component contours and optionally create Maya curves.

    The image region can be segmented by luminance, alpha, RGB color, hue, or
    foreground-vs-background. Connected components are reduced to boundary
    contours, simplified, and returned in crop-local pixel and normalized
    coordinates. When requested, contours can be instantiated as generic Maya
    curves on an image plane or mapped around a cylindrical/lathed surface.
    This is useful for decals, relief outlines, molded marks, panel seams,
    engravings, vents, patches, and other reference-derived curve details.
    """
    import math
    import os
    import maya.cmds as cmds

    try:
        from PySide6.QtGui import QImage
    except Exception:
        try:
            from PySide2.QtGui import QImage
        except Exception as exc:
            raise RuntimeError("PySide QImage is required to extract image contours in Maya.") from exc

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
        corners = [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]
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

    def _component_neighbors():
        if component_connectivity == 4:
            return [(-1, 0), (1, 0), (0, -1), (0, 1)]
        return [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1)]

    def _boundary_neighbors():
        return [(-1, 0), (1, 0), (0, -1), (0, 1)]

    def _point_line_distance(point, start, end):
        px, py = point
        sx, sy = start
        ex, ey = end
        dx = ex - sx
        dy = ey - sy
        length_sq = dx * dx + dy * dy
        if length_sq <= 1e-9:
            return math.hypot(px - sx, py - sy)
        t = ((px - sx) * dx + (py - sy) * dy) / length_sq
        t = max(0.0, min(1.0, t))
        nx = sx + t * dx
        ny = sy + t * dy
        return math.hypot(px - nx, py - ny)

    def _rdp(points, epsilon):
        if len(points) <= 2 or epsilon <= 0.0:
            return points[:]
        start = points[0]
        end = points[-1]
        max_distance = -1.0
        max_index = 0
        for index in range(1, len(points) - 1):
            distance = _point_line_distance(points[index], start, end)
            if distance > max_distance:
                max_distance = distance
                max_index = index
        if max_distance > epsilon:
            left = _rdp(points[: max_index + 1], epsilon)
            right = _rdp(points[max_index:], epsilon)
            return left[:-1] + right
        return [start, end]

    def _resample_points(points, max_points):
        if max_points <= 0 or len(points) <= max_points:
            return points[:]
        if max_points < 2:
            return points[:1]
        return [points[int(round(index * (len(points) - 1) / float(max_points - 1)))] for index in range(max_points)]

    def _profile_radius_at(profile, height, interpolation):
        if height <= profile[0][0]:
            return profile[0][1]
        if height >= profile[-1][0]:
            return profile[-1][1]
        segment_index = 0
        for index in range(len(profile) - 1):
            if profile[index][0] <= height <= profile[index + 1][0]:
                segment_index = index
                break
        h0, r0 = profile[segment_index]
        h1, r1 = profile[segment_index + 1]
        t = (height - h0) / max(1e-9, h1 - h0)
        if interpolation == "linear":
            return r0 + (r1 - r0) * t

        def _slope(point_index):
            if point_index <= 0:
                ha, ra = profile[0]
                hb, rb = profile[1]
            elif point_index >= len(profile) - 1:
                ha, ra = profile[-2]
                hb, rb = profile[-1]
            else:
                ha, ra = profile[point_index - 1]
                hb, rb = profile[point_index + 1]
            return (rb - ra) / max(1e-9, hb - ha)

        m0 = _slope(segment_index)
        m1 = _slope(segment_index + 1)
        t2 = t * t
        t3 = t2 * t
        span = h1 - h0
        radius_value = (
            (2.0 * t3 - 3.0 * t2 + 1.0) * r0
            + (t3 - 2.0 * t2 + t) * span * m0
            + (-2.0 * t3 + 3.0 * t2) * r1
            + (t3 - t2) * span * m1
        )
        lower = min(r0, r1)
        upper = max(r0, r1)
        return max(0.0, min(upper, max(lower, radius_value)))

    def _map_point_to_plane(point):
        x, y = point
        u = 0.0 if crop_width == 1 else x / float(crop_width - 1)
        v = 0.0 if crop_height == 1 else y / float(crop_height - 1)
        local_a = (u - 0.5) * plane_width
        local_b = (0.5 - v) * plane_height
        mapped = center[:]
        if plane_axis == "z":
            mapped[0] += local_a
            mapped[1] += local_b
        elif plane_axis == "x":
            mapped[2] += local_a
            mapped[1] += local_b
        else:
            mapped[0] += local_a
            mapped[2] += local_b
        return mapped

    def _map_point_to_cylinder(point):
        x, y = point
        u = 0.0 if crop_width == 1 else x / float(crop_width - 1)
        v = 0.0 if crop_height == 1 else y / float(crop_height - 1)
        axis_value = axis_start + (1.0 - v) * axis_span
        angle = math.radians(angle_start + angle_span * u)
        surface_radius = radius
        if clean_surface_profile is not None:
            surface_radius = _profile_radius_at(clean_surface_profile, axis_value, profile_interpolation)
        surface_radius += offset
        mapped = center[:]
        mapped[axis_index] = center[axis_index] + axis_value
        mapped[radial_a] = center[radial_a] + surface_radius * math.sin(angle)
        mapped[radial_b] = center[radial_b] + surface_radius * math.cos(angle)
        return mapped

    if not image_path:
        raise ValueError("image_path is required.")
    normalized_image_path = os.path.normpath(image_path)
    if not os.path.isfile(normalized_image_path):
        raise ValueError(f"Image path does not exist: {image_path}")

    match_mode = match_mode.lower().strip()
    if match_mode not in {"luminance", "alpha", "rgb", "hue", "foreground"}:
        raise ValueError("match_mode must be one of luminance, alpha, rgb, hue, or foreground.")
    component_connectivity = _validate_int(component_connectivity, "component_connectivity", 4)
    if component_connectivity not in {4, 8}:
        raise ValueError("component_connectivity must be 4 or 8.")
    min_component_pixels = _validate_int(min_component_pixels, "min_component_pixels", 1)
    max_components = _validate_int(max_components, "max_components", 1)
    min_contour_points = _validate_int(min_contour_points, "min_contour_points", 2)
    max_points_per_contour = _validate_int(max_points_per_contour, "max_points_per_contour", 0)
    simplify_tolerance_pixels = _validate_scalar(simplify_tolerance_pixels, "simplify_tolerance_pixels")
    if simplify_tolerance_pixels < 0.0:
        raise ValueError("simplify_tolerance_pixels must be greater than or equal to zero.")
    threshold = _clamp(_validate_scalar(threshold, "threshold"))
    alpha_threshold = _clamp(_validate_scalar(alpha_threshold, "alpha_threshold"))
    saturation_min = _clamp(_validate_scalar(saturation_min, "saturation_min"))
    value_min = _clamp(_validate_scalar(value_min, "value_min"))
    color_tolerance = _validate_scalar(color_tolerance, "color_tolerance")
    if color_tolerance > 1.0:
        color_tolerance /= 255.0
    color_tolerance = max(0.0, color_tolerance)
    hue_tolerance = _validate_scalar(hue_tolerance, "hue_tolerance")
    if hue_tolerance > 1.0:
        hue_tolerance /= 360.0
    if hue_tolerance < 0.0 or hue_tolerance > 0.5:
        raise ValueError("hue_tolerance must be in the 0..0.5 range, or degrees in the 0..180 range.")
    background_tolerance = _validate_scalar(background_tolerance, "background_tolerance")
    if background_tolerance > 1.0:
        background_tolerance /= 255.0
    background_tolerance = max(0.0, background_tolerance)

    curve_mapping = curve_mapping.lower().strip()
    if curve_mapping not in {"image_plane", "cylindrical"}:
        raise ValueError("curve_mapping must be one of image_plane or cylindrical.")
    center = _validate_vector(center, 3, "center")
    plane_width = _validate_scalar(plane_width, "plane_width")
    plane_height = _validate_scalar(plane_height, "plane_height")
    if plane_width <= 0.0 or plane_height <= 0.0:
        raise ValueError("plane_width and plane_height must be greater than zero.")
    plane_axis = plane_axis.lower().strip()
    if plane_axis not in {"x", "y", "z"}:
        raise ValueError("plane_axis must be one of x, y, or z.")

    axis = axis.lower().strip()
    axes = {"x": (0, 1, 2), "y": (1, 0, 2), "z": (2, 0, 1)}
    if axis not in axes:
        raise ValueError("axis must be one of x, y, or z.")
    axis_index, radial_a, radial_b = axes[axis]
    axis_range = _validate_vector(axis_range, 2, "axis_range")
    axis_start, axis_end = axis_range
    if axis_start > axis_end:
        axis_start, axis_end = axis_end, axis_start
    axis_span = axis_end - axis_start
    if axis_span <= 0.0:
        raise ValueError("axis_range must cover a positive span.")
    angle_range_degrees = _validate_vector(angle_range_degrees, 2, "angle_range_degrees")
    angle_start, angle_end = angle_range_degrees
    angle_span = angle_end - angle_start
    if abs(angle_span) <= 1e-9:
        raise ValueError("angle_range_degrees must cover a non-zero span.")
    radius = _validate_scalar(radius, "radius")
    offset = _validate_scalar(offset, "offset")
    if radius <= 0.0 and surface_profile is None:
        raise ValueError("radius must be greater than zero when surface_profile is not provided.")
    profile_interpolation = profile_interpolation.lower().strip()
    if profile_interpolation not in {"linear", "smooth"}:
        raise ValueError("profile_interpolation must be one of linear or smooth.")

    clean_surface_profile = None
    if surface_profile is not None:
        if not isinstance(surface_profile, list) or len(surface_profile) < 2:
            raise ValueError("surface_profile must contain at least two [height, radius] points.")
        clean_surface_profile = []
        previous_height = None
        for point in surface_profile:
            height, profile_radius = _validate_vector(point, 2, "surface_profile point")
            if profile_radius < 0.0:
                raise ValueError("surface_profile radii must be greater than or equal to zero.")
            if previous_height is not None and height <= previous_height:
                raise ValueError("surface_profile heights must be strictly increasing.")
            clean_surface_profile.append([height, profile_radius])
            previous_height = height

    clean_target_color = None
    target_hsv = None
    if match_mode in {"rgb", "hue"}:
        if target_color is None:
            raise ValueError("target_color is required for rgb and hue match modes.")
        clean_target_color = _normalize_color(target_color, "target_color")
        target_hsv = _rgb_to_hsv(clean_target_color[0], clean_target_color[1], clean_target_color[2])

    image = QImage(normalized_image_path)
    if image.isNull():
        raise ValueError(f"Unable to load image: {image_path}")
    image_width = image.width()
    image_height = image.height()
    if image_width < 2 or image_height < 2:
        raise ValueError("image must be at least 2x2 pixels.")

    if bbox_pixels is not None and bbox_normalized is not None:
        raise ValueError("Provide only one of bbox_pixels or bbox_normalized.")
    if bbox_normalized is not None:
        bbox = _validate_vector(bbox_normalized, 4, "bbox_normalized")
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            raise ValueError("bbox_normalized must be [min_x, min_y, max_x, max_y].")
        x_min = int(round(_clamp(bbox[0]) * (image_width - 1)))
        y_min = int(round(_clamp(bbox[1]) * (image_height - 1)))
        x_max = int(round(_clamp(bbox[2]) * (image_width - 1)))
        y_max = int(round(_clamp(bbox[3]) * (image_height - 1)))
    elif bbox_pixels is not None:
        bbox = _validate_vector(bbox_pixels, 4, "bbox_pixels")
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            raise ValueError("bbox_pixels must be [min_x, min_y, max_x, max_y].")
        x_min = int(round(bbox[0]))
        y_min = int(round(bbox[1]))
        x_max = int(round(bbox[2]))
        y_max = int(round(bbox[3]))
    else:
        x_min, y_min, x_max, y_max = 0, 0, image_width - 1, image_height - 1

    x_min = max(0, min(image_width - 1, x_min))
    y_min = max(0, min(image_height - 1, y_min))
    x_max = max(0, min(image_width - 1, x_max))
    y_max = max(0, min(image_height - 1, y_max))
    if x_max <= x_min or y_max <= y_min:
        raise ValueError("Resolved crop bbox is empty.")

    cropped = image.copy(x_min, y_min, x_max - x_min + 1, y_max - y_min + 1)
    crop_width = cropped.width()
    crop_height = cropped.height()
    clean_background_color = _normalize_color(background_color, "background_color") if background_color else _estimate_background(cropped)

    mask = [bytearray(crop_width) for _ in range(crop_height)]
    matched_pixels = 0
    for y in range(crop_height):
        row = mask[y]
        for x in range(crop_width):
            red, green, blue, alpha = _pixel_rgb_alpha(cropped, x, y)
            if alpha < alpha_threshold:
                continue
            rgb = [red, green, blue]
            if match_mode == "alpha":
                value = alpha
                is_match = value >= threshold
            elif match_mode == "luminance":
                value = 0.2126 * red + 0.7152 * green + 0.0722 * blue
                is_match = value < threshold if invert else value >= threshold
            elif match_mode == "foreground":
                is_match = _color_distance(rgb, clean_background_color) > background_tolerance
            elif match_mode == "rgb":
                is_match = _color_distance(rgb, clean_target_color) <= color_tolerance
            else:
                hue, saturation, value = _rgb_to_hsv(red, green, blue)
                is_match = (
                    _hue_distance(hue, target_hsv[0]) <= hue_tolerance
                    and saturation >= saturation_min
                    and value >= value_min
                )
            if is_match:
                row[x] = 1
                matched_pixels += 1

    visited = [bytearray(crop_width) for _ in range(crop_height)]
    components = []
    for y in range(crop_height):
        for x in range(crop_width):
            if not mask[y][x] or visited[y][x]:
                continue
            stack = [(x, y)]
            visited[y][x] = 1
            pixels = []
            x0 = x1 = x
            y0 = y1 = y
            while stack:
                current_x, current_y = stack.pop()
                pixels.append((current_x, current_y))
                x0 = min(x0, current_x)
                x1 = max(x1, current_x)
                y0 = min(y0, current_y)
                y1 = max(y1, current_y)
                for dx, dy in _component_neighbors():
                    next_x = current_x + dx
                    next_y = current_y + dy
                    if next_x < 0 or next_x >= crop_width or next_y < 0 or next_y >= crop_height:
                        continue
                    if visited[next_y][next_x] or not mask[next_y][next_x]:
                        continue
                    visited[next_y][next_x] = 1
                    stack.append((next_x, next_y))
            if len(pixels) >= min_component_pixels:
                components.append({"pixels": pixels, "bbox_pixels": [x0, y0, x1, y1], "pixel_count": len(pixels)})
    components.sort(key=lambda item: item["pixel_count"], reverse=True)

    contours = []
    for component_index, component in enumerate(components[:max_components]):
        boundary = []
        pixel_set = set(component["pixels"])
        for x, y in component["pixels"]:
            is_boundary = False
            for dx, dy in _boundary_neighbors():
                nx = x + dx
                ny = y + dy
                if nx < 0 or nx >= crop_width or ny < 0 or ny >= crop_height or (nx, ny) not in pixel_set:
                    is_boundary = True
                    break
            if is_boundary:
                boundary.append((float(x), float(y)))
        if len(boundary) < min_contour_points:
            continue
        centroid_x = sum(point[0] for point in boundary) / float(len(boundary))
        centroid_y = sum(point[1] for point in boundary) / float(len(boundary))
        boundary.sort(key=lambda point: math.atan2(point[1] - centroid_y, point[0] - centroid_x))
        simplified = _rdp(boundary, simplify_tolerance_pixels)
        simplified = _resample_points(simplified, max_points_per_contour)
        if close_contours and simplified and simplified[0] != simplified[-1]:
            simplified.append(simplified[0])
        normalized = [
            [
                0.0 if crop_width == 1 else point[0] / float(crop_width - 1),
                0.0 if crop_height == 1 else point[1] / float(crop_height - 1),
            ]
            for point in simplified
        ]
        contours.append({
            "component_index": component_index,
            "pixel_count": component["pixel_count"],
            "bbox_pixels": component["bbox_pixels"],
            "point_count": len(simplified),
            "points_pixels": [[point[0], point[1]] for point in simplified],
            "points_normalized": normalized,
        })

    created_curves = []
    if create_curves:
        if not curve_name_prefix:
            base_name = os.path.splitext(os.path.basename(normalized_image_path))[0] or "image"
            curve_name_prefix = f"{base_name}_contour"
        mapper = _map_point_to_cylinder if curve_mapping == "cylindrical" else _map_point_to_plane
        for contour in contours:
            if contour["point_count"] < 2:
                continue
            world_points = [mapper(point) for point in contour["points_pixels"]]
            if len(world_points) < 2:
                continue
            curve = cmds.curve(
                name=f"{curve_name_prefix}_{contour['component_index']:02d}",
                degree=1,
                point=world_points,
            )
            created_curves.append(curve)

    return {
        "success": True,
        "image_path": normalized_image_path,
        "image_width": image_width,
        "image_height": image_height,
        "crop_bbox_pixels": [x_min, y_min, x_max, y_max],
        "crop_width": crop_width,
        "crop_height": crop_height,
        "match_mode": match_mode,
        "matched_pixels": matched_pixels,
        "component_count": len(components),
        "contour_count": len(contours),
        "contours": contours,
        "create_curves": bool(create_curves),
        "curve_mapping": curve_mapping,
        "created_curves": created_curves,
        "background_color": clean_background_color,
        "target_color": clean_target_color,
    }
