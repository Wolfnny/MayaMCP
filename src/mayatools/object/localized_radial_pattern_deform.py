from typing import Dict, List, Any


def localized_radial_pattern_deform(
    object_name: str,
    center: List[float] = [0.0, 0.0, 0.0],
    axis: str = "y",
    axis_range: List[float] = [0.0, 1.0],
    angle_range_degrees: List[float] = [-45.0, 45.0],
    axis_count: int = 6,
    angle_count: int = 8,
    feature_axis_radius: float = 0.05,
    feature_angle_radius_degrees: float = 4.0,
    amplitude: float = -0.02,
    falloff: str = "smooth",
    stagger: bool = False,
    stagger_offset_degrees: float = 0.0,
    smooth: bool = True,
) -> Dict[str, Any]:
    """Apply localized repeated radial features to a cylindrical or lathed mesh.

    The tool deforms vertices radially inside a bounded angular and axial
    region. It is useful for generic grip dimples, raised dot fields, localized
    emboss/deboss patterns, perforation-like dents, and other repeated surface
    details on bottles, cans, cups, knobs, handles, and similar forms. UVs are
    not edited; only vertex positions are moved.
    """
    import math
    import maya.cmds as cmds

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(v) for v in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(v) for v in values]

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

    def _validate_count(value, arg_name):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to 1.")
        return value

    def _positive_span(start_degrees, end_degrees):
        span = (end_degrees - start_degrees) % 360.0
        return 360.0 if abs(span) < 1e-8 else span

    def _angle_delta_degrees(a, b):
        return (a - b + 180.0) % 360.0 - 180.0

    def _angle_range_t(angle, start_degrees, span_degrees):
        delta = (angle - start_degrees) % 360.0
        if delta < -1e-8 or delta > span_degrees + 1e-8:
            return None
        return max(0.0, min(1.0, delta / span_degrees))

    def _feature_weight(distance):
        if distance > 1.0:
            return 0.0
        if falloff == "hard":
            return 1.0
        if falloff == "linear":
            return 1.0 - distance
        if falloff == "gaussian":
            return math.exp(-4.0 * distance * distance)
        t = max(0.0, min(1.0, distance))
        return 1.0 - (t * t * (3.0 - 2.0 * t))

    if not cmds.objExists(object_name):
        raise ValueError(f"Object does not exist: {object_name}")

    center = _validate_vector(center, 3, "center")
    axis_range = _validate_vector(axis_range, 2, "axis_range")
    angle_range_degrees = _validate_vector(angle_range_degrees, 2, "angle_range_degrees")
    axis_count = _validate_count(axis_count, "axis_count")
    angle_count = _validate_count(angle_count, "angle_count")
    feature_axis_radius = _validate_scalar(feature_axis_radius, "feature_axis_radius")
    feature_angle_radius_degrees = _validate_scalar(feature_angle_radius_degrees, "feature_angle_radius_degrees")
    amplitude = _validate_scalar(amplitude, "amplitude")
    stagger_offset_degrees = _validate_scalar(stagger_offset_degrees, "stagger_offset_degrees")
    if feature_axis_radius <= 0.0:
        raise ValueError("feature_axis_radius must be greater than zero.")
    if feature_angle_radius_degrees <= 0.0:
        raise ValueError("feature_angle_radius_degrees must be greater than zero.")

    falloff = falloff.lower()
    if falloff not in {"smooth", "linear", "gaussian", "hard"}:
        raise ValueError("falloff must be one of smooth, linear, gaussian, or hard.")

    axis = axis.lower()
    axes = {
        "x": (0, 1, 2),
        "y": (1, 0, 2),
        "z": (2, 0, 1),
    }
    if axis not in axes:
        raise ValueError("axis must be one of x, y, or z.")
    axis_index, radial_a, radial_b = axes[axis]

    shapes = cmds.listRelatives(object_name, shapes=True, fullPath=True) or []
    if cmds.objectType(object_name) == "mesh":
        shapes = [object_name]
    if not any(cmds.objectType(shape) == "mesh" for shape in shapes):
        raise ValueError(f"{object_name} is not a polygon mesh transform or mesh shape.")

    vertices = cmds.ls(f"{object_name}.vtx[*]", flatten=True) or []
    if not vertices:
        raise ValueError(f"No vertices found on {object_name}.")

    axis_start, axis_end = axis_range
    if axis_start > axis_end:
        axis_start, axis_end = axis_end, axis_start
    axis_span = axis_end - axis_start
    if axis_span <= 0.0:
        raise ValueError("axis_range must cover a positive span.")

    angle_start, angle_end = angle_range_degrees
    angle_span = _positive_span(angle_start, angle_end)
    angle_spacing = angle_span / float(angle_count)
    if stagger and abs(stagger_offset_degrees) < 1e-8:
        stagger_offset_degrees = angle_spacing * 0.5

    feature_centers = []
    for axis_index_center in range(axis_count):
        axis_t = (axis_index_center + 0.5) / float(axis_count)
        axis_value = axis_start + axis_span * axis_t
        row_offset = stagger_offset_degrees if stagger and axis_index_center % 2 == 1 else 0.0
        for angle_index in range(angle_count):
            angle_t = (angle_index + 0.5) / float(angle_count)
            angle_value = angle_start + angle_span * angle_t + row_offset
            feature_centers.append((axis_value, angle_value))

    displacement_values = []
    deformed_vertices = 0
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

        weight = 0.0
        for feature_axis, feature_angle in feature_centers:
            axis_distance = abs(local_axis - feature_axis) / feature_axis_radius
            if axis_distance > 1.0:
                continue
            angle_distance = abs(_angle_delta_degrees(angle, feature_angle)) / feature_angle_radius_degrees
            if angle_distance > 1.0:
                continue
            distance = math.sqrt(axis_distance * axis_distance + angle_distance * angle_distance)
            weight = max(weight, _feature_weight(distance))

        if weight <= 0.0:
            continue

        displacement = amplitude * weight
        new_radius = max(0.0, radius + displacement)
        scale = new_radius / radius
        position[radial_a] = center[radial_a] + delta_a * scale
        position[radial_b] = center[radial_b] + delta_b * scale
        cmds.xform(vertex, worldSpace=True, translation=position)
        displacement_values.append(displacement)
        deformed_vertices += 1

    if smooth:
        cmds.polySoftEdge(object_name, angle=180, constructionHistory=False)

    return {
        "success": True,
        "object_name": object_name,
        "deformed_vertices": deformed_vertices,
        "feature_count": len(feature_centers),
        "axis": axis,
        "axis_range": [axis_start, axis_end],
        "angle_range_degrees": angle_range_degrees,
        "axis_count": axis_count,
        "angle_count": angle_count,
        "feature_axis_radius": feature_axis_radius,
        "feature_angle_radius_degrees": feature_angle_radius_degrees,
        "amplitude": amplitude,
        "falloff": falloff,
        "stagger": bool(stagger),
        "stagger_offset_degrees": stagger_offset_degrees,
        "min_displacement": min(displacement_values) if displacement_values else 0.0,
        "max_displacement": max(displacement_values) if displacement_values else 0.0,
        "bounding_box": cmds.exactWorldBoundingBox(object_name),
    }
