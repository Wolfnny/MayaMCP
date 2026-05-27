from typing import Dict, List, Any


def create_cylindrical_detail_band(
    name: str,
    radius: float,
    height: float,
    center: List[float] = [0.0, 0.0, 0.0],
    axis: str = "y",
    radial_segments: int = 96,
    height_segments: int = 8,
    circumferential_cycles: int = 0,
    circumferential_amplitude: float = 0.0,
    circumferential_sharpness: float = 2.0,
    circumferential_phase_degrees: float = 0.0,
    vertical_cycles: int = 0,
    vertical_amplitude: float = 0.0,
    vertical_sharpness: float = 2.0,
    vertical_phase_degrees: float = 0.0,
    twist_degrees: float = 0.0,
    waveform: str = "ridge",
    smooth: bool = True,
    material_color: List[float] = None,
    material_name: str = None,
) -> Dict[str, Any]:
    """Create a UV-mapped cylindrical detail band with repeated radial features.

    The band can represent generic cap knurling, grip ridges, ring grooves,
    corrugation, or thread-like helical detail. It creates geometry only and is
    not tied to any specific product or model.
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

    def _pattern(angle, sharpness):
        if waveform == "sin":
            return math.sin(angle)
        if waveform == "cosine":
            return math.cos(angle)
        value = max(0.0, 0.5 + 0.5 * math.cos(angle))
        return value ** sharpness

    if not name:
        raise ValueError("name is required.")
    radius = _validate_scalar(radius, "radius")
    height = _validate_scalar(height, "height")
    if radius <= 0:
        raise ValueError("radius must be greater than zero.")
    if height <= 0:
        raise ValueError("height must be greater than zero.")
    if not isinstance(radial_segments, int) or isinstance(radial_segments, bool) or radial_segments < 3:
        raise ValueError("radial_segments must be at least 3.")
    if not isinstance(height_segments, int) or isinstance(height_segments, bool) or height_segments < 1:
        raise ValueError("height_segments must be at least 1.")
    if not isinstance(circumferential_cycles, int) or isinstance(circumferential_cycles, bool):
        raise ValueError("circumferential_cycles must be an integer greater than or equal to zero.")
    if not isinstance(vertical_cycles, int) or isinstance(vertical_cycles, bool):
        raise ValueError("vertical_cycles must be an integer greater than or equal to zero.")
    if circumferential_cycles < 0 or vertical_cycles < 0:
        raise ValueError("cycle counts must be greater than or equal to zero.")
    circumferential_sharpness = _validate_scalar(circumferential_sharpness, "circumferential_sharpness")
    vertical_sharpness = _validate_scalar(vertical_sharpness, "vertical_sharpness")
    if circumferential_sharpness <= 0 or vertical_sharpness <= 0:
        raise ValueError("sharpness values must be greater than zero.")

    center = _validate_vector(center, 3, "center")
    waveform = waveform.lower()
    if waveform not in {"ridge", "groove", "sin", "cosine"}:
        raise ValueError("waveform must be one of ridge, groove, sin, or cosine.")

    axis = axis.lower()
    axes = {
        "x": (0, 1, 2),
        "y": (1, 0, 2),
        "z": (2, 0, 1),
    }
    if axis not in axes:
        raise ValueError("axis must be one of x, y, or z.")
    axis_index, radial_a, radial_b = axes[axis]

    circumferential_amplitude = _validate_scalar(circumferential_amplitude, "circumferential_amplitude")
    vertical_amplitude = _validate_scalar(vertical_amplitude, "vertical_amplitude")
    circumferential_phase = math.radians(_validate_scalar(circumferential_phase_degrees, "circumferential_phase_degrees"))
    vertical_phase = math.radians(_validate_scalar(vertical_phase_degrees, "vertical_phase_degrees"))
    twist = math.radians(_validate_scalar(twist_degrees, "twist_degrees"))

    band = cmds.polyPlane(
        name=name,
        width=1.0,
        height=1.0,
        subdivisionsX=radial_segments,
        subdivisionsY=height_segments,
        axis=[0, 0, 1],
        constructionHistory=False,
    )[0]

    vertices = cmds.ls(f"{band}.vtx[*]", flatten=True) or []
    for vertex in vertices:
        x, y, _ = cmds.xform(vertex, query=True, objectSpace=True, translation=True)
        u = max(0.0, min(1.0, x + 0.5))
        v = max(0.0, min(1.0, y + 0.5))
        theta = math.tau * u
        phase_shift = twist * (v - 0.5)

        offset = 0.0
        if circumferential_cycles:
            angle = circumferential_cycles * theta + phase_shift + circumferential_phase
            offset += circumferential_amplitude * _pattern(angle, float(circumferential_sharpness))
        if vertical_cycles:
            angle = math.tau * vertical_cycles * v + vertical_phase
            offset += vertical_amplitude * _pattern(angle, float(vertical_sharpness))

        detail_radius = max(0.0, radius + offset)
        position = [center[0], center[1], center[2]]
        position[axis_index] = center[axis_index] + (v - 0.5) * height
        position[radial_a] = center[radial_a] + detail_radius * math.sin(theta)
        position[radial_b] = center[radial_b] + detail_radius * math.cos(theta)
        cmds.xform(vertex, worldSpace=True, translation=position)

    if smooth:
        cmds.polySoftEdge(band, angle=180, constructionHistory=False)

    material = None
    shading_group = None
    if material_color is not None:
        material_color = _validate_vector(material_color, 3, "material_color")
        material = cmds.shadingNode("lambert", asShader=True, name=material_name or f"{name}_mat")
        cmds.setAttr(f"{material}.color", material_color[0], material_color[1], material_color[2], type="double3")
        shading_group = cmds.sets(name=f"{material}SG", empty=True, renderable=True, noSurfaceShader=True)
        cmds.connectAttr(f"{material}.outColor", f"{shading_group}.surfaceShader", force=True)
        cmds.sets(band, edit=True, forceElement=shading_group)

    return {
        "success": True,
        "name": band,
        "radius": radius,
        "height": height,
        "center": center,
        "axis": axis,
        "radial_segments": radial_segments,
        "height_segments": height_segments,
        "circumferential_cycles": circumferential_cycles,
        "circumferential_amplitude": circumferential_amplitude,
        "vertical_cycles": vertical_cycles,
        "vertical_amplitude": vertical_amplitude,
        "twist_degrees": twist_degrees,
        "waveform": waveform,
        "material": material,
        "shading_group": shading_group,
        "uv_range": {"min_u": 0.0, "max_u": 1.0, "min_v": 0.0, "max_v": 1.0},
    }
