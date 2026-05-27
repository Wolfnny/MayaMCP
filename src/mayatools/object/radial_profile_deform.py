from typing import Dict, List, Any


def radial_profile_deform(
    object_name: str,
    profile_points: List[List[float]],
    center: List[float] = None,
    axis: str = "y",
    position_mode: str = "normalized",
    value_mode: str = "scale",
    interpolation: str = "smooth",
    axis_range: List[float] = None,
    blend: float = 1.0,
    max_abs_displacement: float = None,
    min_radius: float = 1e-6,
    smooth: bool = True,
) -> Dict[str, Any]:
    """Apply an axial radial profile deformation to a polygon mesh.

    The tool samples a user-provided profile along a chosen axis and changes
    each vertex radius around that axis. It is useful for generic silhouette
    correction and shaping on lathed or cylindrical meshes: bottle shoulders,
    can tapers, cup waists, vase bellies, tube bulges, neck transitions, and
    other non-periodic profile adjustments. UVs are not edited.

    profile_points are [position, value] pairs. With position_mode="normalized",
    positions are 0..1 over axis_range or the object's bounding box. With
    value_mode="scale", values multiply the current radius. With
    value_mode="offset", values add to the current radius. With
    value_mode="target_radius", values are absolute target radii.
    """
    import math
    import maya.cmds as cmds

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

    def _clamp(value, lower, upper):
        return max(lower, min(upper, value))

    def _smoothstep(value):
        value = _clamp(value, 0.0, 1.0)
        return value * value * (3.0 - 2.0 * value)

    def _validate_profile(points):
        if not isinstance(points, list) or len(points) < 2:
            raise ValueError("profile_points must contain at least two [position, value] points.")
        clean = []
        previous_position = None
        for point in points:
            position, value = _validate_vector(point, 2, "profile_points point")
            if position_mode == "normalized" and (position < 0.0 or position > 1.0):
                raise ValueError("Normalized profile point positions must be in the range 0..1.")
            if previous_position is not None and position <= previous_position:
                raise ValueError("profile_points positions must be strictly increasing.")
            clean.append([position, value])
            previous_position = position
        return clean

    def _sample_profile(position):
        if position <= clean_profile[0][0]:
            return clean_profile[0][1]
        if position >= clean_profile[-1][0]:
            return clean_profile[-1][1]
        for index in range(len(clean_profile) - 1):
            x0, y0 = clean_profile[index]
            x1, y1 = clean_profile[index + 1]
            if x0 <= position <= x1:
                if abs(x1 - x0) <= 1e-9:
                    return y1
                t = (position - x0) / (x1 - x0)
                if interpolation == "smooth":
                    t = _smoothstep(t)
                return y0 + (y1 - y0) * t
        return clean_profile[-1][1]

    if not cmds.objExists(object_name):
        raise ValueError(f"Object does not exist: {object_name}")

    axis = axis.lower().strip()
    axes = {
        "x": (0, 1, 2),
        "y": (1, 0, 2),
        "z": (2, 0, 1),
    }
    if axis not in axes:
        raise ValueError("axis must be one of x, y, or z.")
    axis_index, radial_a, radial_b = axes[axis]

    position_mode = position_mode.lower().strip()
    if position_mode not in {"normalized", "world"}:
        raise ValueError("position_mode must be normalized or world.")
    value_mode = value_mode.lower().strip()
    if value_mode not in {"scale", "offset", "target_radius"}:
        raise ValueError("value_mode must be scale, offset, or target_radius.")
    interpolation = interpolation.lower().strip()
    if interpolation not in {"linear", "smooth"}:
        raise ValueError("interpolation must be linear or smooth.")

    clean_profile = _validate_profile(profile_points)
    blend = _validate_scalar(blend, "blend")
    if blend < 0.0 or blend > 1.0:
        raise ValueError("blend must be in the range 0..1.")
    min_radius = _validate_scalar(min_radius, "min_radius")
    if min_radius < 0.0:
        raise ValueError("min_radius must be greater than or equal to zero.")
    if max_abs_displacement is not None:
        max_abs_displacement = _validate_scalar(max_abs_displacement, "max_abs_displacement")
        if max_abs_displacement < 0.0:
            raise ValueError("max_abs_displacement must be greater than or equal to zero.")

    shapes = cmds.listRelatives(object_name, shapes=True, fullPath=True) or []
    if cmds.objectType(object_name) == "mesh":
        shapes = [object_name]
    if not any(cmds.objectType(shape) == "mesh" for shape in shapes):
        raise ValueError(f"{object_name} is not a polygon mesh transform or mesh shape.")

    bbox = cmds.exactWorldBoundingBox(object_name)
    if center is None:
        clean_center = [
            (bbox[0] + bbox[3]) * 0.5,
            (bbox[1] + bbox[4]) * 0.5,
            (bbox[2] + bbox[5]) * 0.5,
        ]
    else:
        clean_center = _validate_vector(center, 3, "center")

    if axis_range is None:
        clean_axis_range = [bbox[axis_index], bbox[axis_index + 3]]
    else:
        clean_axis_range = _validate_vector(axis_range, 2, "axis_range")
    if clean_axis_range[1] < clean_axis_range[0]:
        clean_axis_range = [clean_axis_range[1], clean_axis_range[0]]
    axis_span = clean_axis_range[1] - clean_axis_range[0]
    if position_mode == "normalized" and abs(axis_span) <= 1e-9:
        raise ValueError("axis_range must have non-zero length when position_mode is normalized.")

    vertices = cmds.ls(f"{object_name}.vtx[*]", flatten=True) or []
    if not vertices:
        raise ValueError(f"No vertices found on {object_name}.")

    displacements = []
    deformed_vertices = 0
    skipped_vertices = 0

    for vertex in vertices:
        position = cmds.xform(vertex, query=True, worldSpace=True, translation=True)
        axis_value = position[axis_index]
        if axis_value < clean_axis_range[0] or axis_value > clean_axis_range[1]:
            skipped_vertices += 1
            continue

        if position_mode == "normalized":
            profile_position = (axis_value - clean_axis_range[0]) / axis_span
        else:
            profile_position = axis_value

        delta_a = position[radial_a] - clean_center[radial_a]
        delta_b = position[radial_b] - clean_center[radial_b]
        radius = math.sqrt(delta_a * delta_a + delta_b * delta_b)
        if radius <= min_radius:
            skipped_vertices += 1
            continue

        value = _sample_profile(profile_position)
        if value_mode == "scale":
            target_radius = radius * value
        elif value_mode == "offset":
            target_radius = radius + value
        else:
            target_radius = value
        target_radius = max(0.0, target_radius)

        displacement = (target_radius - radius) * blend
        if max_abs_displacement is not None:
            displacement = _clamp(displacement, -max_abs_displacement, max_abs_displacement)
        if abs(displacement) <= 1e-12:
            continue

        new_radius = max(0.0, radius + displacement)
        scale = new_radius / radius
        position[radial_a] = clean_center[radial_a] + delta_a * scale
        position[radial_b] = clean_center[radial_b] + delta_b * scale
        cmds.xform(vertex, worldSpace=True, translation=position)
        displacements.append(displacement)
        deformed_vertices += 1

    if smooth:
        cmds.polySoftEdge(object_name, angle=180, constructionHistory=False)

    return {
        "success": True,
        "object_name": object_name,
        "axis": axis,
        "center": clean_center,
        "axis_range": clean_axis_range,
        "position_mode": position_mode,
        "value_mode": value_mode,
        "interpolation": interpolation,
        "profile_points": clean_profile,
        "blend": blend,
        "max_abs_displacement": max_abs_displacement,
        "deformed_vertices": deformed_vertices,
        "skipped_vertices": skipped_vertices,
        "min_displacement": min(displacements) if displacements else 0.0,
        "max_displacement": max(displacements) if displacements else 0.0,
        "mean_abs_displacement": (
            sum(abs(value) for value in displacements) / float(len(displacements))
            if displacements else 0.0
        ),
        "bounding_box": cmds.exactWorldBoundingBox(object_name),
    }
