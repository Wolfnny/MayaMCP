from typing import Dict, List, Any


def radial_mesh_deform(
    object_name: str,
    center: List[float] = [0.0, 0.0, 0.0],
    axis: str = "y",
    cycles: int = 12,
    amplitude: float = -0.05,
    waveform: str = "groove",
    phase_degrees: float = 0.0,
    sharpness: float = 2.0,
    axis_range: List[float] = None,
    axis_falloff: float = 0.0,
    axis_profile: List[List[float]] = None,
    smooth: bool = True,
) -> Dict[str, Any]:
    """Apply a periodic radial deformation to a polygon mesh.

    This is useful for generic lathed or cylindrical forms that need flutes,
    grooves, ridges, corrugation, or other repeated radial detail. UVs are not
    edited; only vertex positions are moved.

    Waveforms:
    - sin: signed sine wave in the range -1..1
    - cosine: signed cosine wave in the range -1..1
    - groove: repeated positive lobes in the range 0..1, usually with negative amplitude
    - ridge: repeated positive lobes in the range 0..1, usually with positive amplitude
    """
    import math
    import maya.cmds as cmds

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector(values, length, name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(v) for v in values):
            raise ValueError(f"{name} must be a list of {length} numeric values.")
        return [float(v) for v in values]

    def _smoothstep(edge0, edge1, value):
        if edge0 == edge1:
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
                if x0 == x1:
                    return y1
                t = (value - x0) / (x1 - x0)
                return y0 + (y1 - y0) * t
        return 1.0

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

    if cycles < 1:
        raise ValueError("cycles must be at least 1.")
    if not _is_number(amplitude):
        raise ValueError("amplitude must be numeric.")
    if not _is_number(phase_degrees):
        raise ValueError("phase_degrees must be numeric.")
    if not _is_number(sharpness) or sharpness <= 0:
        raise ValueError("sharpness must be a number greater than zero.")

    waveform = waveform.lower()
    if waveform not in {"sin", "cosine", "groove", "ridge"}:
        raise ValueError("waveform must be one of sin, cosine, groove, or ridge.")

    clean_axis_range = None
    if axis_range is not None:
        clean_axis_range = _validate_vector(axis_range, 2, "axis_range")
    if not _is_number(axis_falloff) or axis_falloff < 0:
        raise ValueError("axis_falloff must be a non-negative number.")

    clean_axis_profile = None
    if axis_profile is not None:
        if not isinstance(axis_profile, list) or len(axis_profile) < 2:
            raise ValueError("axis_profile must contain at least two [axis_value, weight] points.")
        clean_axis_profile = []
        previous_value = None
        for point in axis_profile:
            axis_value, weight = _validate_vector(point, 2, "axis_profile point")
            if previous_value is not None and axis_value <= previous_value:
                raise ValueError("axis_profile axis values must be strictly increasing.")
            clean_axis_profile.append([axis_value, weight])
            previous_value = axis_value

    shapes = cmds.listRelatives(object_name, shapes=True, fullPath=True) or []
    if cmds.objectType(object_name) == "mesh":
        shapes = [object_name]
    if not any(cmds.objectType(shape) == "mesh" for shape in shapes):
        raise ValueError(f"{object_name} is not a polygon mesh transform or mesh shape.")

    vertices = cmds.ls(f"{object_name}.vtx[*]", flatten=True) or []
    if not vertices:
        raise ValueError(f"No vertices found on {object_name}.")

    phase = math.radians(phase_degrees)
    displacement_values = []
    deformed_vertices = 0

    for vertex in vertices:
        position = cmds.xform(vertex, query=True, worldSpace=True, translation=True)
        axis_value = position[axis_index] - center[axis_index]
        weight = _range_weight(axis_value, clean_axis_range, float(axis_falloff))
        weight *= _profile_weight(axis_value, clean_axis_profile)
        if weight == 0.0:
            continue

        delta_a = position[radial_a] - center[radial_a]
        delta_b = position[radial_b] - center[radial_b]
        radius = math.sqrt(delta_a * delta_a + delta_b * delta_b)
        if radius <= 1e-8:
            continue

        angle = math.atan2(delta_a, delta_b)
        wave_angle = cycles * angle + phase
        if waveform == "sin":
            pattern = math.sin(wave_angle)
        elif waveform == "cosine":
            pattern = math.cos(wave_angle)
        else:
            pattern = max(0.0, 0.5 + 0.5 * math.cos(wave_angle))
            pattern = pattern ** float(sharpness)

        displacement = float(amplitude) * pattern * weight
        new_radius = max(0.0, radius + displacement)
        scale = new_radius / radius
        position[radial_a] = center[radial_a] + delta_a * scale
        position[radial_b] = center[radial_b] + delta_b * scale
        cmds.xform(vertex, worldSpace=True, translation=position)

        displacement_values.append(displacement)
        deformed_vertices += 1

    if smooth:
        cmds.polySoftEdge(object_name, angle=180, constructionHistory=False)

    bbox = cmds.exactWorldBoundingBox(object_name)
    return {
        "success": True,
        "object_name": object_name,
        "deformed_vertices": deformed_vertices,
        "cycles": cycles,
        "amplitude": float(amplitude),
        "waveform": waveform,
        "axis": axis,
        "axis_range": clean_axis_range,
        "axis_falloff": float(axis_falloff),
        "axis_profile": clean_axis_profile,
        "min_displacement": min(displacement_values) if displacement_values else 0.0,
        "max_displacement": max(displacement_values) if displacement_values else 0.0,
        "bounding_box": bbox,
    }
