from typing import Dict, List, Any


def polar_mesh_deform(
    object_name: str,
    center: List[float] = [0.0, 0.0, 0.0],
    axis: str = "y",
    cycles: int = 5,
    radial_amplitude: float = 0.0,
    axis_amplitude: float = 0.0,
    uniform_axis_amplitude: float = 0.0,
    waveform: str = "ridge",
    phase_degrees: float = 0.0,
    sharpness: float = 2.0,
    axis_range: List[float] = None,
    axis_falloff: float = 0.0,
    axis_profile: List[List[float]] = None,
    radial_range: List[float] = None,
    radial_falloff: float = 0.0,
    radial_profile: List[List[float]] = None,
    smooth: bool = True,
) -> Dict[str, Any]:
    """Apply coupled angular radial and axial deformation to a polygon mesh.

    The deformation is evaluated in polar coordinates around an axis. It can
    create generic petal bases, star-shaped supports, punted bottoms, lobed
    feet, angular ribs, or other cyclic features that need both radial and
    axis-direction displacement. UVs are not edited; only vertex positions move.
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

    def _smoothstep(edge0, edge1, value):
        if abs(edge1 - edge0) <= 1e-9:
            return 1.0 if value >= edge1 else 0.0
        t = max(0.0, min(1.0, (value - edge0) / (edge1 - edge0)))
        return t * t * (3.0 - 2.0 * t)

    def _range_weight(value, value_range, falloff):
        if value_range is None:
            return 1.0
        start, end = value_range
        if start > end:
            start, end = end, start
        if value < start or value > end:
            return 0.0
        if falloff <= 0.0:
            return 1.0
        weight = 1.0
        if value < start + falloff:
            weight *= _smoothstep(start, start + falloff, value)
        if value > end - falloff:
            weight *= 1.0 - _smoothstep(end - falloff, end, value)
        return weight

    def _profile_weight(value, profile):
        if not profile:
            return 1.0
        if value <= profile[0][0]:
            return profile[0][1]
        if value >= profile[-1][0]:
            return profile[-1][1]
        for index in range(len(profile) - 1):
            x0, y0 = profile[index]
            x1, y1 = profile[index + 1]
            if x0 <= value <= x1:
                if abs(x1 - x0) <= 1e-9:
                    return y1
                t = (value - x0) / (x1 - x0)
                return y0 + (y1 - y0) * t
        return 1.0

    def _validate_profile(profile, arg_name):
        if profile is None:
            return None
        if not isinstance(profile, list) or len(profile) < 2:
            raise ValueError(f"{arg_name} must contain at least two [value, weight] points.")
        clean = []
        previous_value = None
        for point in profile:
            value, weight = _validate_vector(point, 2, f"{arg_name} point")
            if previous_value is not None and value <= previous_value:
                raise ValueError(f"{arg_name} values must be strictly increasing.")
            clean.append([value, weight])
            previous_value = value
        return clean

    def _pattern(angle):
        if waveform == "sin":
            return math.sin(angle)
        if waveform == "cosine":
            return math.cos(angle)
        value = max(0.0, 0.5 + 0.5 * math.cos(angle))
        return value ** sharpness

    if not cmds.objExists(object_name):
        raise ValueError(f"Object does not exist: {object_name}")

    center = _validate_vector(center, 3, "center")
    axis = axis.lower()
    axes = {
        "x": (0, 1, 2),
        "y": (1, 0, 2),
        "z": (2, 0, 1),
    }
    if axis not in axes:
        raise ValueError("axis must be one of x, y, or z.")
    axis_index, radial_a, radial_b = axes[axis]

    if not isinstance(cycles, int) or isinstance(cycles, bool) or cycles < 1:
        raise ValueError("cycles must be an integer greater than or equal to 1.")
    radial_amplitude = _validate_scalar(radial_amplitude, "radial_amplitude")
    axis_amplitude = _validate_scalar(axis_amplitude, "axis_amplitude")
    uniform_axis_amplitude = _validate_scalar(uniform_axis_amplitude, "uniform_axis_amplitude")
    phase = math.radians(_validate_scalar(phase_degrees, "phase_degrees"))
    sharpness = _validate_scalar(sharpness, "sharpness")
    if sharpness <= 0.0:
        raise ValueError("sharpness must be greater than zero.")

    waveform = waveform.lower()
    if waveform not in {"ridge", "groove", "sin", "cosine"}:
        raise ValueError("waveform must be one of ridge, groove, sin, or cosine.")

    clean_axis_range = _validate_vector(axis_range, 2, "axis_range") if axis_range is not None else None
    clean_radial_range = _validate_vector(radial_range, 2, "radial_range") if radial_range is not None else None
    axis_falloff = _validate_scalar(axis_falloff, "axis_falloff")
    radial_falloff = _validate_scalar(radial_falloff, "radial_falloff")
    if axis_falloff < 0.0 or radial_falloff < 0.0:
        raise ValueError("falloff values must be non-negative.")
    clean_axis_profile = _validate_profile(axis_profile, "axis_profile")
    clean_radial_profile = _validate_profile(radial_profile, "radial_profile")

    shapes = cmds.listRelatives(object_name, shapes=True, fullPath=True) or []
    if cmds.objectType(object_name) == "mesh":
        shapes = [object_name]
    if not any(cmds.objectType(shape) == "mesh" for shape in shapes):
        raise ValueError(f"{object_name} is not a polygon mesh transform or mesh shape.")

    vertices = cmds.ls(f"{object_name}.vtx[*]", flatten=True) or []
    if not vertices:
        raise ValueError(f"No vertices found on {object_name}.")

    radial_displacements = []
    axis_displacements = []
    deformed_vertices = 0

    for vertex in vertices:
        position = cmds.xform(vertex, query=True, worldSpace=True, translation=True)
        local_axis = position[axis_index] - center[axis_index]
        axis_weight = _range_weight(local_axis, clean_axis_range, axis_falloff)
        axis_weight *= _profile_weight(local_axis, clean_axis_profile)
        if axis_weight == 0.0:
            continue

        delta_a = position[radial_a] - center[radial_a]
        delta_b = position[radial_b] - center[radial_b]
        radius = math.sqrt(delta_a * delta_a + delta_b * delta_b)
        radial_weight = _range_weight(radius, clean_radial_range, radial_falloff)
        radial_weight *= _profile_weight(radius, clean_radial_profile)
        weight = axis_weight * radial_weight
        if weight == 0.0:
            continue

        angle = math.atan2(delta_a, delta_b)
        feature = _pattern(cycles * angle + phase)
        radial_displacement = radial_amplitude * feature * weight
        axis_displacement = (axis_amplitude * feature + uniform_axis_amplitude) * weight

        if radius > 1e-8 and radial_displacement != 0.0:
            new_radius = max(0.0, radius + radial_displacement)
            scale = new_radius / radius
            position[radial_a] = center[radial_a] + delta_a * scale
            position[radial_b] = center[radial_b] + delta_b * scale
        position[axis_index] = position[axis_index] + axis_displacement
        cmds.xform(vertex, worldSpace=True, translation=position)

        radial_displacements.append(radial_displacement)
        axis_displacements.append(axis_displacement)
        deformed_vertices += 1

    if smooth:
        cmds.polySoftEdge(object_name, angle=180, constructionHistory=False)

    return {
        "success": True,
        "object_name": object_name,
        "deformed_vertices": deformed_vertices,
        "cycles": cycles,
        "radial_amplitude": radial_amplitude,
        "axis_amplitude": axis_amplitude,
        "uniform_axis_amplitude": uniform_axis_amplitude,
        "waveform": waveform,
        "phase_degrees": phase_degrees,
        "sharpness": sharpness,
        "axis": axis,
        "axis_range": clean_axis_range,
        "axis_falloff": axis_falloff,
        "axis_profile": clean_axis_profile,
        "radial_range": clean_radial_range,
        "radial_falloff": radial_falloff,
        "radial_profile": clean_radial_profile,
        "min_radial_displacement": min(radial_displacements) if radial_displacements else 0.0,
        "max_radial_displacement": max(radial_displacements) if radial_displacements else 0.0,
        "min_axis_displacement": min(axis_displacements) if axis_displacements else 0.0,
        "max_axis_displacement": max(axis_displacements) if axis_displacements else 0.0,
        "bounding_box": cmds.exactWorldBoundingBox(object_name),
    }
