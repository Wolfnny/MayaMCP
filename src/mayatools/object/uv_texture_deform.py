from typing import Dict, List, Any


def uv_texture_deform(
    object_name: str,
    image_path: str,
    uv_set: str = None,
    amplitude: float = 0.02,
    direction: str = "normal",
    radial_axis: str = "y",
    center: List[float] = [0.0, 0.0, 0.0],
    sample_channel: str = "luminance",
    invert: bool = False,
    black_point: float = 0.0,
    white_point: float = 1.0,
    threshold: float = None,
    threshold_softness: float = 0.0,
    neutral_value: float = 0.0,
    gamma: float = 1.0,
    flip_v: bool = True,
    wrap_u: bool = False,
    wrap_v: bool = False,
    min_abs_displacement: float = 0.0,
    smooth: bool = True,
) -> Dict[str, Any]:
    """Deform a UV-mapped polygon mesh by sampling an image through vertex UVs.

    Each vertex samples the supplied image at the average of its connected UVs.
    The sampled value can move vertices along their normals, along a world axis,
    or radially around a selected axis. This is useful for generic texture to
    geometry transfer: emboss/deboss details, stamped panels, fabric puckering,
    decals, relief labels, surface scuffs, grip textures, and other UV-driven
    displacement workflows.
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
        if not isinstance(values, list) or len(values) != length or not all(_is_number(value) for value in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(value) for value in values]

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

    def _clamp(value, lower=0.0, upper=1.0):
        return max(lower, min(upper, value))

    def _wrap_or_clamp(value, wrap):
        if wrap:
            return value % 1.0
        return _clamp(value)

    def _length(vector):
        return math.sqrt(sum(component * component for component in vector))

    def _normalize(vector):
        length = _length(vector)
        if length <= 1e-12:
            return None
        return [component / length for component in vector]

    def _pixel_rgb_alpha(image, x, y):
        color = image.pixelColor(int(x), int(y))
        return [color.redF(), color.greenF(), color.blueF(), color.alphaF()]

    def _sample_bilinear(image, u, v):
        width = image.width()
        height = image.height()
        u = _wrap_or_clamp(u, wrap_u)
        v = _wrap_or_clamp(v, wrap_v)
        if flip_v:
            v = 1.0 - v
        x = u * float(width - 1)
        y = v * float(height - 1)
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

    def _channel_value(channels):
        red, green, blue, alpha = channels
        if sample_channel == "red":
            return red
        if sample_channel == "green":
            return green
        if sample_channel == "blue":
            return blue
        if sample_channel == "alpha":
            return alpha
        if sample_channel == "value":
            return max(red, green, blue)
        if sample_channel == "saturation":
            return _rgb_to_hsv(red, green, blue)[1]
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    def _sample_value(image, u, v):
        value = _channel_value(_sample_bilinear(image, u, v))
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

    def _vertex_uv(vertex):
        uv_components = cmds.polyListComponentConversion(vertex, fromVertex=True, toUV=True) or []
        uv_components = cmds.ls(uv_components, flatten=True) or []
        if not uv_components:
            return None
        values = cmds.polyEditUV(uv_components, query=True) or []
        if len(values) < 2:
            return None
        us = values[0::2]
        vs = values[1::2]
        return sum(us) / float(len(us)), sum(vs) / float(len(vs))

    def _vertex_normal(vertex):
        values = cmds.polyNormalPerVertex(vertex, query=True, xyz=True) or []
        if len(values) < 3:
            return None
        normals = []
        for index in range(0, len(values) - 2, 3):
            normal = _normalize([values[index], values[index + 1], values[index + 2]])
            if normal is not None:
                normals.append(normal)
        if not normals:
            return None
        averaged = [
            sum(normal[axis_index] for normal in normals) / float(len(normals))
            for axis_index in range(3)
        ]
        return _normalize(averaged)

    def _direction_vector(vertex, position):
        if direction == "normal":
            return _vertex_normal(vertex)
        if direction in axis_vectors:
            return axis_vectors[direction][:]
        axis_index, radial_a, radial_b = radial_axes[radial_axis]
        vector = [0.0, 0.0, 0.0]
        vector[radial_a] = position[radial_a] - center[radial_a]
        vector[radial_b] = position[radial_b] - center[radial_b]
        return _normalize(vector)

    if not cmds.objExists(object_name):
        raise ValueError(f"Object does not exist: {object_name}")
    if not image_path:
        raise ValueError("image_path is required.")
    normalized_image_path = os.path.normpath(image_path)
    if not os.path.isfile(normalized_image_path):
        raise ValueError(f"Image path does not exist: {image_path}")

    amplitude = _validate_scalar(amplitude, "amplitude")
    center = _validate_vector(center, 3, "center")
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
    min_abs_displacement = _validate_scalar(min_abs_displacement, "min_abs_displacement")
    if min_abs_displacement < 0.0:
        raise ValueError("min_abs_displacement must be greater than or equal to zero.")

    direction = direction.lower().strip()
    axis_vectors = {
        "x": [1.0, 0.0, 0.0],
        "y": [0.0, 1.0, 0.0],
        "z": [0.0, 0.0, 1.0],
        "-x": [-1.0, 0.0, 0.0],
        "-y": [0.0, -1.0, 0.0],
        "-z": [0.0, 0.0, -1.0],
    }
    if direction not in {"normal", "radial", *axis_vectors.keys()}:
        raise ValueError("direction must be normal, radial, x, y, z, -x, -y, or -z.")
    radial_axis = radial_axis.lower().strip()
    radial_axes = {
        "x": (0, 1, 2),
        "y": (1, 0, 2),
        "z": (2, 0, 1),
    }
    if radial_axis not in radial_axes:
        raise ValueError("radial_axis must be one of x, y, or z.")
    sample_channel = sample_channel.lower().strip()
    if sample_channel not in {"luminance", "red", "green", "blue", "alpha", "value", "saturation"}:
        raise ValueError("sample_channel must be one of luminance, red, green, blue, alpha, value, or saturation.")

    shapes = cmds.listRelatives(object_name, shapes=True, fullPath=True) or []
    if cmds.objectType(object_name) == "mesh":
        shapes = [object_name]
    if not any(cmds.objectType(shape) == "mesh" for shape in shapes):
        raise ValueError(f"{object_name} is not a polygon mesh transform or mesh shape.")

    all_uv_sets = cmds.polyUVSet(object_name, query=True, allUVSets=True) or []
    previous_uv_set = None
    current_uv = cmds.polyUVSet(object_name, query=True, currentUVSet=True) or []
    if current_uv:
        previous_uv_set = current_uv[0]
    if uv_set:
        if uv_set not in all_uv_sets:
            raise ValueError(f"UV set {uv_set} does not exist on {object_name}.")
        cmds.polyUVSet(object_name, currentUVSet=True, uvSet=uv_set)
    else:
        uv_set = previous_uv_set

    image = QImage(normalized_image_path)
    if image.isNull():
        raise ValueError(f"Unable to load image: {image_path}")
    if image.width() < 2 or image.height() < 2:
        raise ValueError("image must be at least 2x2 pixels.")

    vertices = cmds.ls(f"{object_name}.vtx[*]", flatten=True) or []
    if not vertices:
        raise ValueError(f"No vertices found on {object_name}.")

    sampled_vertices = 0
    deformed_vertices = 0
    skipped_vertices = 0
    sample_values = []
    displacement_values = []
    for vertex in vertices:
        uv = _vertex_uv(vertex)
        if uv is None:
            skipped_vertices += 1
            continue
        sampled = _sample_value(image, uv[0], uv[1])
        displacement = amplitude * (sampled - neutral_value)
        sampled_vertices += 1
        sample_values.append(sampled)
        if abs(displacement) <= min_abs_displacement:
            continue

        position = cmds.xform(vertex, query=True, worldSpace=True, translation=True)
        vector = _direction_vector(vertex, position)
        if vector is None:
            skipped_vertices += 1
            continue
        new_position = [
            position[index] + vector[index] * displacement
            for index in range(3)
        ]
        cmds.xform(vertex, worldSpace=True, translation=new_position)
        deformed_vertices += 1
        displacement_values.append(displacement)

    if previous_uv_set and previous_uv_set in all_uv_sets and previous_uv_set != uv_set and cmds.objExists(object_name):
        try:
            cmds.polyUVSet(object_name, currentUVSet=True, uvSet=previous_uv_set)
        except Exception:
            pass

    if smooth and cmds.objExists(object_name):
        cmds.polySoftEdge(object_name, angle=180, constructionHistory=False)

    return {
        "success": True,
        "object_name": object_name,
        "image_path": normalized_image_path,
        "image_width": image.width(),
        "image_height": image.height(),
        "uv_set": uv_set,
        "amplitude": amplitude,
        "direction": direction,
        "radial_axis": radial_axis,
        "center": center,
        "sample_channel": sample_channel,
        "invert": bool(invert),
        "black_point": black_point,
        "white_point": white_point,
        "threshold": threshold,
        "threshold_softness": threshold_softness,
        "neutral_value": neutral_value,
        "gamma": gamma,
        "flip_v": bool(flip_v),
        "wrap_u": bool(wrap_u),
        "wrap_v": bool(wrap_v),
        "min_abs_displacement": min_abs_displacement,
        "vertex_count": len(vertices),
        "sampled_vertices": sampled_vertices,
        "deformed_vertices": deformed_vertices,
        "skipped_vertices": skipped_vertices,
        "min_sample_value": min(sample_values) if sample_values else 0.0,
        "max_sample_value": max(sample_values) if sample_values else 0.0,
        "mean_sample_value": sum(sample_values) / float(len(sample_values)) if sample_values else 0.0,
        "min_displacement": min(displacement_values) if displacement_values else 0.0,
        "max_displacement": max(displacement_values) if displacement_values else 0.0,
        "bounding_box": cmds.exactWorldBoundingBox(object_name) if cmds.objExists(object_name) else None,
    }
