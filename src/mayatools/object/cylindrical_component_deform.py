from typing import Dict, List, Any


def cylindrical_component_deform(
    object_name: str,
    image_path: str,
    center: List[float] = [0.0, 0.0, 0.0],
    axis: str = "y",
    axis_range: List[float] = [0.0, 1.0],
    angle_range_degrees: List[float] = [-60.0, 60.0],
    amplitude: float = -0.02,
    displacement_direction: str = "radial",
    sample_channel: str = "luminance",
    invert: bool = False,
    black_point: float = 0.0,
    white_point: float = 1.0,
    threshold: float = 0.5,
    component_connectivity: int = 8,
    min_component_pixels: int = 12,
    max_component_pixels: int = 0,
    min_component_width: int = 2,
    min_component_height: int = 2,
    max_component_width: int = 0,
    max_component_height: int = 0,
    max_components: int = 200,
    feature_axis_scale: float = 0.7,
    feature_angle_scale: float = 0.7,
    min_feature_axis_radius: float = 0.01,
    min_feature_angle_radius_degrees: float = 0.75,
    max_feature_axis_radius: float = 0.25,
    max_feature_angle_radius_degrees: float = 15.0,
    falloff: str = "smooth",
    blend_mode: str = "max",
    flip_u: bool = False,
    flip_v: bool = False,
    smooth: bool = True,
) -> Dict[str, Any]:
    """Apply fitted image-mask components as local relief on a cylindrical mesh.

    The input image is thresholded into connected components. Each component is
    fitted to an axis/angle-space ellipse, then used as a localized radial or
    axis-direction deformation feature. This is useful for generic grip
    dimples, raised dots, molded emboss/deboss marks, perforation-like dents,
    droplets, rivets, vents, or other component-shaped details on bottles,
    cans, cups, knobs, handles, and other lathed forms. UVs are not edited.
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

    def _clamp(value, lower=0.0, upper=1.0):
        return max(lower, min(upper, value))

    def _positive_span(start_degrees, end_degrees):
        span = (end_degrees - start_degrees) % 360.0
        return 360.0 if abs(span) < 1e-8 else span

    def _angle_delta_degrees(a, b):
        return (a - b + 180.0) % 360.0 - 180.0

    def _angle_range_t(angle, start_degrees, span_degrees):
        delta = (angle - start_degrees) % 360.0
        if delta < -1e-8 or delta > span_degrees + 1e-8:
            return None
        return _clamp(delta / span_degrees)

    def _pixel_rgb_alpha(image, x, y):
        color = image.pixelColor(int(x), int(y))
        return color.redF(), color.greenF(), color.blueF(), color.alphaF()

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

    def _sample_value(image, x, y):
        red, green, blue, alpha = _pixel_rgb_alpha(image, x, y)
        if sample_channel == "red":
            value = red
        elif sample_channel == "green":
            value = green
        elif sample_channel == "blue":
            value = blue
        elif sample_channel == "alpha":
            value = alpha
        elif sample_channel == "value":
            value = max(red, green, blue)
        elif sample_channel == "saturation":
            value = _rgb_to_hsv(red, green, blue)[1]
        else:
            value = 0.2126 * red + 0.7152 * green + 0.0722 * blue

        value = _clamp((value - black_point) / max(1e-9, white_point - black_point))
        return 1.0 - value if invert else value

    def _is_valid_component(component):
        if component["pixel_count"] < min_component_pixels:
            return False
        if max_component_pixels > 0 and component["pixel_count"] > max_component_pixels:
            return False
        if component["width_pixels"] < min_component_width or component["height_pixels"] < min_component_height:
            return False
        if max_component_width > 0 and component["width_pixels"] > max_component_width:
            return False
        if max_component_height > 0 and component["height_pixels"] > max_component_height:
            return False
        return True

    def _feature_weight(distance):
        if distance > 1.0:
            return 0.0
        if falloff == "hard":
            return 1.0
        if falloff == "linear":
            return 1.0 - distance
        if falloff == "gaussian":
            return math.exp(-4.0 * distance * distance)
        t = _clamp(distance)
        return 1.0 - (t * t * (3.0 - 2.0 * t))

    if not cmds.objExists(object_name):
        raise ValueError(f"Object does not exist: {object_name}")
    if not image_path:
        raise ValueError("image_path is required.")
    normalized_image_path = os.path.normpath(image_path)
    if not os.path.isfile(normalized_image_path):
        raise ValueError(f"Image path does not exist: {image_path}")

    center = _validate_vector(center, 3, "center")
    axis_range = _validate_vector(axis_range, 2, "axis_range")
    angle_range_degrees = _validate_vector(angle_range_degrees, 2, "angle_range_degrees")
    amplitude = _validate_scalar(amplitude, "amplitude")
    black_point = _validate_scalar(black_point, "black_point")
    white_point = _validate_scalar(white_point, "white_point")
    if abs(white_point - black_point) <= 1e-9:
        raise ValueError("white_point must differ from black_point.")
    threshold = _clamp(_validate_scalar(threshold, "threshold"))
    component_connectivity = _validate_int(component_connectivity, "component_connectivity", 4)
    if component_connectivity not in {4, 8}:
        raise ValueError("component_connectivity must be 4 or 8.")
    min_component_pixels = _validate_int(min_component_pixels, "min_component_pixels", 1)
    max_component_pixels = _validate_int(max_component_pixels, "max_component_pixels", 0)
    min_component_width = _validate_int(min_component_width, "min_component_width", 1)
    min_component_height = _validate_int(min_component_height, "min_component_height", 1)
    max_component_width = _validate_int(max_component_width, "max_component_width", 0)
    max_component_height = _validate_int(max_component_height, "max_component_height", 0)
    max_components = _validate_int(max_components, "max_components", 1)
    feature_axis_scale = _validate_scalar(feature_axis_scale, "feature_axis_scale")
    feature_angle_scale = _validate_scalar(feature_angle_scale, "feature_angle_scale")
    min_feature_axis_radius = _validate_scalar(min_feature_axis_radius, "min_feature_axis_radius")
    min_feature_angle_radius_degrees = _validate_scalar(min_feature_angle_radius_degrees, "min_feature_angle_radius_degrees")
    max_feature_axis_radius = _validate_scalar(max_feature_axis_radius, "max_feature_axis_radius")
    max_feature_angle_radius_degrees = _validate_scalar(max_feature_angle_radius_degrees, "max_feature_angle_radius_degrees")
    if feature_axis_scale <= 0.0 or feature_angle_scale <= 0.0:
        raise ValueError("feature scale values must be greater than zero.")
    if min_feature_axis_radius <= 0.0 or min_feature_angle_radius_degrees <= 0.0:
        raise ValueError("minimum feature radii must be greater than zero.")
    if max_feature_axis_radius < min_feature_axis_radius:
        raise ValueError("max_feature_axis_radius must be greater than or equal to min_feature_axis_radius.")
    if max_feature_angle_radius_degrees < min_feature_angle_radius_degrees:
        raise ValueError("max_feature_angle_radius_degrees must be greater than or equal to min_feature_angle_radius_degrees.")

    displacement_direction = displacement_direction.lower().strip()
    if displacement_direction not in {"radial", "axis"}:
        raise ValueError("displacement_direction must be one of radial or axis.")
    sample_channel = sample_channel.lower().strip()
    if sample_channel not in {"luminance", "red", "green", "blue", "alpha", "value", "saturation"}:
        raise ValueError("sample_channel must be one of luminance, red, green, blue, alpha, value, or saturation.")
    falloff = falloff.lower().strip()
    if falloff not in {"smooth", "linear", "gaussian", "hard"}:
        raise ValueError("falloff must be one of smooth, linear, gaussian, or hard.")
    blend_mode = blend_mode.lower().strip()
    if blend_mode not in {"max", "add"}:
        raise ValueError("blend_mode must be one of max or add.")

    axis = axis.lower().strip()
    axes = {
        "x": (0, 1, 2),
        "y": (1, 0, 2),
        "z": (2, 0, 1),
    }
    if axis not in axes:
        raise ValueError("axis must be one of x, y, or z.")
    axis_index, radial_a, radial_b = axes[axis]

    axis_start, axis_end = axis_range
    if axis_start > axis_end:
        axis_start, axis_end = axis_end, axis_start
    axis_span = axis_end - axis_start
    if axis_span <= 0.0:
        raise ValueError("axis_range must cover a positive span.")

    angle_start, angle_end = angle_range_degrees
    angle_span = _positive_span(angle_start, angle_end)

    image = QImage(normalized_image_path)
    if image.isNull():
        raise ValueError(f"Unable to load image: {image_path}")
    image_width = image.width()
    image_height = image.height()
    if image_width < 2 or image_height < 2:
        raise ValueError("image must be at least 2x2 pixels.")

    mask = [bytearray(image_width) for _ in range(image_height)]
    value_sum = 0.0
    active_pixels = 0
    min_value = None
    max_value = None
    for y in range(image_height):
        row = mask[y]
        for x in range(image_width):
            value = _sample_value(image, x, y)
            min_value = value if min_value is None else min(min_value, value)
            max_value = value if max_value is None else max(max_value, value)
            value_sum += value
            if value >= threshold:
                row[x] = 1
                active_pixels += 1

    visited = [bytearray(image_width) for _ in range(image_height)]
    if component_connectivity == 4:
        neighbors = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    else:
        neighbors = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1)]

    components = []
    for y in range(image_height):
        for x in range(image_width):
            if not mask[y][x] or visited[y][x]:
                continue
            stack = [(x, y)]
            visited[y][x] = 1
            pixel_count = 0
            x_sum = 0.0
            y_sum = 0.0
            x_min = x_max = x
            y_min = y_max = y

            while stack:
                current_x, current_y = stack.pop()
                pixel_count += 1
                x_sum += current_x
                y_sum += current_y
                x_min = min(x_min, current_x)
                x_max = max(x_max, current_x)
                y_min = min(y_min, current_y)
                y_max = max(y_max, current_y)

                for dx, dy in neighbors:
                    next_x = current_x + dx
                    next_y = current_y + dy
                    if next_x < 0 or next_x >= image_width or next_y < 0 or next_y >= image_height:
                        continue
                    if visited[next_y][next_x] or not mask[next_y][next_x]:
                        continue
                    visited[next_y][next_x] = 1
                    stack.append((next_x, next_y))

            width_pixels = x_max - x_min + 1
            height_pixels = y_max - y_min + 1
            component = {
                "pixel_count": pixel_count,
                "bbox_pixels": [x_min, y_min, x_max, y_max],
                "width_pixels": width_pixels,
                "height_pixels": height_pixels,
                "center_pixels": [x_sum / float(pixel_count), y_sum / float(pixel_count)],
            }
            if _is_valid_component(component):
                components.append(component)

    components.sort(key=lambda item: item["pixel_count"], reverse=True)
    retained_components = components[:max_components]

    features = []
    for component in retained_components:
        center_x, center_y = component["center_pixels"]
        image_u = center_x / float(image_width - 1)
        image_v = center_y / float(image_height - 1)
        angle_t = 1.0 - image_u if flip_u else image_u
        axis_t = 1.0 - image_v if flip_v else image_v
        component_angle = angle_start + angle_span * angle_t
        component_axis = axis_start + axis_span * axis_t

        axis_radius = (component["height_pixels"] / float(image_height)) * axis_span * 0.5 * feature_axis_scale
        angle_radius = (component["width_pixels"] / float(image_width)) * angle_span * 0.5 * feature_angle_scale
        axis_radius = max(min_feature_axis_radius, min(max_feature_axis_radius, axis_radius))
        angle_radius = max(min_feature_angle_radius_degrees, min(max_feature_angle_radius_degrees, angle_radius))

        features.append({
            "axis": component_axis,
            "angle_degrees": component_angle,
            "feature_axis_radius": axis_radius,
            "feature_angle_radius_degrees": angle_radius,
            "pixel_count": component["pixel_count"],
            "bbox_pixels": component["bbox_pixels"],
            "center_pixels": component["center_pixels"],
        })

    shapes = cmds.listRelatives(object_name, shapes=True, fullPath=True) or []
    if cmds.objectType(object_name) == "mesh":
        shapes = [object_name]
    if not any(cmds.objectType(shape) == "mesh" for shape in shapes):
        raise ValueError(f"{object_name} is not a polygon mesh transform or mesh shape.")

    vertices = cmds.ls(f"{object_name}.vtx[*]", flatten=True) or []
    if not vertices:
        raise ValueError(f"No vertices found on {object_name}.")

    deformed_vertices = 0
    displacement_values = []
    for vertex in vertices:
        position = cmds.xform(vertex, query=True, worldSpace=True, translation=True)
        local_axis = position[axis_index] - center[axis_index]
        if local_axis < axis_start or local_axis > axis_end:
            continue

        delta_a = position[radial_a] - center[radial_a]
        delta_b = position[radial_b] - center[radial_b]
        radius = math.sqrt(delta_a * delta_a + delta_b * delta_b)
        if radius <= 1e-8:
            continue

        angle = math.degrees(math.atan2(delta_a, delta_b))
        if _angle_range_t(angle, angle_start, angle_span) is None:
            continue

        feature_weight = 0.0
        for feature in features:
            axis_distance = abs(local_axis - feature["axis"]) / feature["feature_axis_radius"]
            if axis_distance > 1.0:
                continue
            angle_distance = abs(_angle_delta_degrees(angle, feature["angle_degrees"])) / feature["feature_angle_radius_degrees"]
            if angle_distance > 1.0:
                continue
            distance = math.sqrt(axis_distance * axis_distance + angle_distance * angle_distance)
            weight = _feature_weight(distance)
            if blend_mode == "add":
                feature_weight += weight
            else:
                feature_weight = max(feature_weight, weight)

        if feature_weight <= 0.0:
            continue
        feature_weight = min(1.0, feature_weight)
        displacement = amplitude * feature_weight
        if abs(displacement) <= 1e-12:
            continue

        if displacement_direction == "radial":
            new_radius = max(0.0, radius + displacement)
            scale = new_radius / radius
            position[radial_a] = center[radial_a] + delta_a * scale
            position[radial_b] = center[radial_b] + delta_b * scale
        else:
            position[axis_index] = position[axis_index] + displacement

        cmds.xform(vertex, worldSpace=True, translation=position)
        deformed_vertices += 1
        displacement_values.append(displacement)

    if smooth:
        cmds.polySoftEdge(object_name, angle=180, constructionHistory=False)

    return {
        "success": True,
        "object_name": object_name,
        "image_path": normalized_image_path,
        "image_width": image_width,
        "image_height": image_height,
        "active_pixels": active_pixels,
        "active_pixel_ratio": active_pixels / float(image_width * image_height),
        "image_value_min": min_value if min_value is not None else 0.0,
        "image_value_max": max_value if max_value is not None else 0.0,
        "image_value_mean": value_sum / float(image_width * image_height),
        "detected_components": len(components),
        "retained_components": len(retained_components),
        "deformed_vertices": deformed_vertices,
        "axis": axis,
        "axis_range": [axis_start, axis_end],
        "angle_range_degrees": angle_range_degrees,
        "amplitude": amplitude,
        "displacement_direction": displacement_direction,
        "threshold": threshold,
        "component_connectivity": component_connectivity,
        "component_filters": {
            "min_component_pixels": min_component_pixels,
            "max_component_pixels": max_component_pixels,
            "min_component_width": min_component_width,
            "min_component_height": min_component_height,
            "max_component_width": max_component_width,
            "max_component_height": max_component_height,
            "max_components": max_components,
        },
        "feature_axis_scale": feature_axis_scale,
        "feature_angle_scale": feature_angle_scale,
        "falloff": falloff,
        "blend_mode": blend_mode,
        "flip_u": bool(flip_u),
        "flip_v": bool(flip_v),
        "min_displacement": min(displacement_values) if displacement_values else 0.0,
        "max_displacement": max(displacement_values) if displacement_values else 0.0,
        "features": features,
        "bounding_box": cmds.exactWorldBoundingBox(object_name),
    }
