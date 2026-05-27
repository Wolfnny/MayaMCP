from typing import Dict, List, Any


def create_curved_text(
    text: str,
    name: str = None,
    radius: float = 1.0,
    center: List[float] = [0.0, 0.0, 0.0],
    axis: str = "y",
    axis_center: float = 0.0,
    angle_start: float = -45.0,
    angle_end: float = 45.0,
    text_height: float = 0.35,
    surface_offset: float = 0.02,
    font: str = "Arial",
    fit_to_arc: bool = True,
    create_geometry: bool = True,
    bevel_radius: float = 0.008,
    bevel_segments: int = 6,
    keep_curves: bool = False,
    material_color: List[float] = None,
    material_name: str = None,
) -> Dict[str, Any]:
    """Create text curves or tube geometry conformed to a cylindrical surface.

    The text is generated as Maya text curves, mapped around a cylindrical
    surface, and optionally converted into raised/engraved tube geometry. This
    is useful for generic curved labels, embossing guides, raised outlines, and
    engraved text on bottles, cups, cans, handles, or other cylindrical forms.
    """
    import math
    import random
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

    if not text:
        raise ValueError("text is required.")
    if name is None:
        name = f"curved_text_{int(random.random() * 1000)}"

    radius = _validate_scalar(radius, "radius")
    axis_center = _validate_scalar(axis_center, "axis_center")
    angle_start = _validate_scalar(angle_start, "angle_start")
    angle_end = _validate_scalar(angle_end, "angle_end")
    text_height = _validate_scalar(text_height, "text_height")
    surface_offset = _validate_scalar(surface_offset, "surface_offset")
    bevel_radius = _validate_scalar(bevel_radius, "bevel_radius")
    if radius <= 0:
        raise ValueError("radius must be greater than zero.")
    if angle_end <= angle_start:
        raise ValueError("angle_end must be greater than angle_start.")
    if text_height <= 0:
        raise ValueError("text_height must be greater than zero.")
    if bevel_radius < 0:
        raise ValueError("bevel_radius must be greater than or equal to zero.")
    if not isinstance(bevel_segments, int) or isinstance(bevel_segments, bool) or bevel_segments < 3:
        raise ValueError("bevel_segments must be an integer greater than or equal to 3.")

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

    text_result = cmds.textCurves(name=f"{name}_curves", font=font, text=text, constructionHistory=False)
    if not text_result:
        raise RuntimeError("Unable to create text curves.")
    curve_group = text_result[0]
    if cmds.objExists(curve_group):
        curve_group = cmds.rename(curve_group, f"{name}_curves")

    bbox = cmds.exactWorldBoundingBox(curve_group)
    width = max(1e-6, bbox[3] - bbox[0])
    height = max(1e-6, bbox[4] - bbox[1])
    text_center_x = (bbox[0] + bbox[3]) * 0.5
    text_center_y = (bbox[1] + bbox[4]) * 0.5
    angle_span = math.radians(angle_end - angle_start)
    arc_width = radius * angle_span
    if fit_to_arc:
        scale = min(arc_width / width, text_height / height)
    else:
        scale = text_height / height

    theta_start = math.radians(angle_start)
    theta_end = math.radians(angle_end)
    mapped_radius = radius + surface_offset

    curve_shapes = cmds.listRelatives(curve_group, allDescendents=True, fullPath=True, type="nurbsCurve") or []
    curve_transforms = []
    for shape in curve_shapes:
        parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
        if parents and parents[0] not in curve_transforms:
            curve_transforms.append(parents[0])

    for shape in curve_shapes:
        cvs = cmds.ls(f"{shape}.cv[*]", flatten=True) or []
        for cv in cvs:
            x, y, _ = cmds.xform(cv, query=True, worldSpace=True, translation=True)
            local_x = (x - text_center_x) * scale
            local_y = (y - text_center_y) * scale
            u = (local_x / arc_width) + 0.5
            theta = theta_start + (theta_end - theta_start) * u
            position = [center[0], center[1], center[2]]
            position[axis_index] = center[axis_index] + axis_center + local_y
            position[radial_a] = center[radial_a] + mapped_radius * math.sin(theta)
            position[radial_b] = center[radial_b] + mapped_radius * math.cos(theta)
            cmds.xform(cv, worldSpace=True, translation=position)

    geometry = []
    if create_geometry and bevel_radius > 0:
        for index, path in enumerate(curve_transforms):
            profile = cmds.circle(
                name=f"{name}_profile_{index}",
                radius=bevel_radius,
                sections=bevel_segments,
                normal=[0, 1, 0],
                constructionHistory=False,
            )[0]
            try:
                result = cmds.extrude(
                    profile,
                    path,
                    name=f"{name}_geo_{index}",
                    fixedPath=True,
                    useComponentPivot=1,
                    constructionHistory=False,
                )
                if result:
                    geometry.append(result[0])
            finally:
                if cmds.objExists(profile):
                    cmds.delete(profile)

    material = None
    shading_group = None
    assign_targets = geometry if geometry else curve_transforms
    if material_color is not None:
        material_color = _validate_vector(material_color, 3, "material_color")
        material = cmds.shadingNode("lambert", asShader=True, name=material_name or f"{name}_mat")
        cmds.setAttr(f"{material}.color", material_color[0], material_color[1], material_color[2], type="double3")
        shading_group = cmds.sets(name=f"{material}SG", empty=True, renderable=True, noSurfaceShader=True)
        cmds.connectAttr(f"{material}.outColor", f"{shading_group}.surfaceShader", force=True)
        if assign_targets:
            cmds.sets(assign_targets, edit=True, forceElement=shading_group)

    output_group = None
    if geometry:
        output_group = cmds.group(geometry, name=f"{name}_geometry")
    if geometry and not keep_curves and cmds.objExists(curve_group):
        cmds.delete(curve_group)
        curve_group = None
    elif curve_group:
        try:
            cmds.rename(curve_group, f"{name}_curve_group")
            curve_group = f"{name}_curve_group"
        except Exception:
            pass

    return {
        "success": True,
        "name": output_group or curve_group,
        "text": text,
        "curve_group": curve_group,
        "geometry_group": output_group,
        "geometry": geometry,
        "curve_count": len(curve_transforms),
        "radius": radius,
        "surface_offset": surface_offset,
        "axis": axis,
        "axis_center": axis_center,
        "angle_start": angle_start,
        "angle_end": angle_end,
        "text_height": text_height,
        "font": font,
        "material": material,
        "shading_group": shading_group,
    }
