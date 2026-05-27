from typing import Dict, List, Any


def cylindrical_image_deform(
    object_name: str,
    image_path: str,
    center: List[float] = [0.0, 0.0, 0.0],
    axis: str = "y",
    axis_range: List[float] = [0.0, 1.0],
    angle_range_degrees: List[float] = [-60.0, 60.0],
    amplitude: float = 0.02,
    displacement_direction: str = "radial",
    sample_channel: str = "luminance",
    invert: bool = False,
    black_point: float = 0.0,
    white_point: float = 1.0,
    threshold: float = None,
    threshold_softness: float = 0.0,
    neutral_value: float = 0.0,
    gamma: float = 1.0,
    flip_u: bool = False,
    flip_v: bool = False,
    axis_falloff: float = 0.0,
    angle_falloff_degrees: float = 0.0,
    smooth: bool = True,
) -> Dict[str, Any]:
    """Deform a cylindrical or lathed mesh from an image sampled in angle/height space.

    The image's horizontal axis maps to an angular range around the selected
    axis, and the image's vertical axis maps to an axis-height range. Sampled
    pixel values can drive radial or axis-direction displacement, making this
    useful for generic photo-driven relief, emboss/deboss patterns, grips,
    dents, labels, panels, and localized texture-to-geometry transfer on
    bottles, cans, cups, knobs, and other lathed objects.
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
            raise RuntimeError("PySide QImage is required to sample image pixels in Maya.") from exc

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

    def _clamp(value, lower=0.0, upper=1.0):
        return max(lower, min(upper, value))

    def _positive_span(start_degrees, end_degrees):
        span = (end_degrees - start_degrees) % 360.0
        return 360.0 if abs(span) < 1e-8 else span

    def _angle_range_t(angle, start_degrees, span_degrees):
        delta = (angle - start_degrees) % 360.0
        if delta < -1e-8 or delta > span_degrees + 1e-8:
            return None
        return _clamp(delta / span_degrees)

    def _edge_weight(value, start, end, falloff):
        if value < start or value > end:
            return 0.0
        if falloff <= 0.0:
            return 1.0
        weight = 1.0
        if value < start + falloff:
            t = _clamp((value - start) / max(1e-9, falloff))
            weight *= t * t * (3.0 - 2.0 * t)
        if value > end - falloff:
            t = _clamp((end - value) / max(1e-9, falloff))
            weight *= t * t * (3.0 - 2.0 * t)
        return weight

    def _angle_edge_weight(angle_t, span_degrees, falloff_degrees):
        if falloff_degrees <= 0.0:
            return 1.0
        falloff_t = _clamp(falloff_degrees / max(1e-9, span_degrees))
        if falloff_t <= 0.0:
            return 1.0
        weight = 1.0
        if angle_t < falloff_t:
            t = _clamp(angle_t / falloff_t)
            weight *= t * t * (3.0 - 2.0 * t)
        if angle_t > 1.0 - falloff_t:
            t = _clamp((1.0 - angle_t) / falloff_t)
            weight *= t * t * (3.0 - 2.0 * t)
        return weight

    def _pixel_rgb_alpha(image, x, y):
        color = image.pixelColor(int(x), int(y))
        return [color.redF(), color.greenF(), color.blueF(), color.alphaF()]

    def _sample_bilinear(image, u, v):
        width = image.width()
        height = image.height()
        x = _clamp(u) * float(width - 1)
        y = _clamp(v) * float(height - 1)
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
        return channels

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

    def _sample_value(image, u, v):
        red, green, blue, alpha = _sample_bilinear(image, u, v)
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
        if invert:
            value = 1.0 - value
        if threshold is not None:
            if threshold_softness <= 0.0:
                value = 1.0 if value >= threshold else 0.0
            else:
                lower = threshold - threshold_softness * 0.5
                upper = threshold + threshold_softness * 0.5
                value = _clamp((value - lower) / max(1e-9, upper - lower))
                value = value * value * (3.0 - 2.0 * value)
        if gamma != 1.0:
            value = value ** gamma
        return value

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
    if threshold is not None:
        threshold = _validate_scalar(threshold, "threshold")
    threshold_softness = _validate_scalar(threshold_softness, "threshold_softness")
    if threshold_softness < 0.0:
        raise ValueError("threshold_softness must be greater than or equal to zero.")
    neutral_value = _validate_scalar(neutral_value, "neutral_value")
    gamma = _validate_scalar(gamma, "gamma")
    if gamma <= 0.0:
        raise ValueError("gamma must be greater than zero.")
    axis_falloff = _validate_scalar(axis_falloff, "axis_falloff")
    angle_falloff_degrees = _validate_scalar(angle_falloff_degrees, "angle_falloff_degrees")
    if axis_falloff < 0.0 or angle_falloff_degrees < 0.0:
        raise ValueError("falloff values must be greater than or equal to zero.")

    displacement_direction = displacement_direction.lower().strip()
    if displacement_direction not in {"radial", "axis"}:
        raise ValueError("displacement_direction must be one of radial or axis.")
    sample_channel = sample_channel.lower().strip()
    if sample_channel not in {"luminance", "red", "green", "blue", "alpha", "value", "saturation"}:
        raise ValueError("sample_channel must be one of luminance, red, green, blue, alpha, value, or saturation.")

    axis = axis.lower()
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
    if image.width() < 2 or image.height() < 2:
        raise ValueError("image must be at least 2x2 pixels.")

    shapes = cmds.listRelatives(object_name, shapes=True, fullPath=True) or []
    if cmds.objectType(object_name) == "mesh":
        shapes = [object_name]
    if not any(cmds.objectType(shape) == "mesh" for shape in shapes):
        raise ValueError(f"{object_name} is not a polygon mesh transform or mesh shape.")

    vertices = cmds.ls(f"{object_name}.vtx[*]", flatten=True) or []
    if not vertices:
        raise ValueError(f"No vertices found on {object_name}.")

    deformed_vertices = 0
    sample_values = []
    displacement_values = []
    for vertex in vertices:
        position = cmds.xform(vertex, query=True, worldSpace=True, translation=True)
        local_axis = position[axis_index] - center[axis_index]
        axis_weight = _edge_weight(local_axis, axis_start, axis_end, axis_falloff)
        if axis_weight <= 0.0:
            continue

        delta_a = position[radial_a] - center[radial_a]
        delta_b = position[radial_b] - center[radial_b]
        radius = math.sqrt(delta_a * delta_a + delta_b * delta_b)
        if radius <= 1e-8:
            continue

        angle_degrees = math.degrees(math.atan2(delta_a, delta_b))
        angle_t = _angle_range_t(angle_degrees, angle_start, angle_span)
        if angle_t is None:
            continue
        angle_weight = _angle_edge_weight(angle_t, angle_span, angle_falloff_degrees)
        if angle_weight <= 0.0:
            continue

        u = 1.0 - angle_t if flip_u else angle_t
        v = (local_axis - axis_start) / axis_span
        v = 1.0 - v if flip_v else v
        sampled = _sample_value(image, u, v)
        displacement = amplitude * (sampled - neutral_value) * axis_weight * angle_weight
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
        sample_values.append(sampled)
        displacement_values.append(displacement)

    if smooth:
        cmds.polySoftEdge(object_name, angle=180, constructionHistory=False)

    return {
        "success": True,
        "object_name": object_name,
        "image_path": normalized_image_path,
        "image_width": image.width(),
        "image_height": image.height(),
        "deformed_vertices": deformed_vertices,
        "axis": axis,
        "axis_range": [axis_start, axis_end],
        "angle_range_degrees": angle_range_degrees,
        "amplitude": amplitude,
        "displacement_direction": displacement_direction,
        "sample_channel": sample_channel,
        "invert": bool(invert),
        "black_point": black_point,
        "white_point": white_point,
        "threshold": threshold,
        "threshold_softness": threshold_softness,
        "neutral_value": neutral_value,
        "gamma": gamma,
        "flip_u": bool(flip_u),
        "flip_v": bool(flip_v),
        "axis_falloff": axis_falloff,
        "angle_falloff_degrees": angle_falloff_degrees,
        "min_sample_value": min(sample_values) if sample_values else 0.0,
        "max_sample_value": max(sample_values) if sample_values else 0.0,
        "min_displacement": min(displacement_values) if displacement_values else 0.0,
        "max_displacement": max(displacement_values) if displacement_values else 0.0,
        "bounding_box": cmds.exactWorldBoundingBox(object_name),
    }
