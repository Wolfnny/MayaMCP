from typing import Dict, List, Any


def create_textured_label(
    texture_path: str,
    name: str = None,
    target_object: str = None,
    radius: float = None,
    surface_profile: List[List[float]] = None,
    profile_interpolation: str = "linear",
    center: List[float] = [0.0, 0.0, 0.0],
    height: float = 1.0,
    vertical_center: float = 0.0,
    angle_start: float = -60.0,
    angle_end: float = 60.0,
    segments_u: int = 48,
    segments_v: int = 4,
    offset: float = 0.02,
    material_name: str = None,
    use_alpha: bool = False,
    opacity: float = 1.0,
) -> Dict[str, Any]:
    """Create a UV-mapped curved label mesh and apply an image texture to it.

    The label is a curved polygon strip around the Y axis. UVs are preserved from
    a generated plane, so the image texture is mapped directly to the label UVs
    instead of being approximated with floating text geometry. If surface_profile
    is provided as [height, radius] points, the label conforms to that lathed
    profile instead of using a constant cylindrical radius. When use_alpha is
    true, texture transparency is connected to the label material. Opacity
    controls the overall material visibility and is multiplied with texture
    alpha when use_alpha is enabled.
    """
    import math
    import os
    import maya.cmds as cmds

    if not texture_path:
        raise ValueError("texture_path is required.")
    normalized_texture_path = os.path.normpath(texture_path)
    if not os.path.exists(normalized_texture_path):
        raise ValueError(f"Texture path does not exist: {texture_path}")

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

    def _validate_profile(profile, arg_name):
        if profile is None:
            return None
        if not isinstance(profile, list) or len(profile) < 2:
            raise ValueError(f"{arg_name} must contain at least two [height, radius] points.")
        clean = []
        previous_height = None
        for point in profile:
            profile_height, profile_radius = _validate_vector(point, 2, f"{arg_name} point")
            if profile_radius < 0.0:
                raise ValueError(f"{arg_name} radii must be greater than or equal to zero.")
            if previous_height is not None and profile_height <= previous_height:
                raise ValueError(f"{arg_name} heights must be strictly increasing.")
            clean.append([profile_height, profile_radius])
            previous_height = profile_height
        if not any(profile_radius > 0.0 for _, profile_radius in clean):
            raise ValueError(f"{arg_name} must contain at least one positive radius.")
        return clean

    def _profile_radius_at(profile, profile_height, interpolation):
        if profile_height <= profile[0][0]:
            return profile[0][1]
        if profile_height >= profile[-1][0]:
            return profile[-1][1]

        segment_index = 0
        for index in range(len(profile) - 1):
            if profile[index][0] <= profile_height <= profile[index + 1][0]:
                segment_index = index
                break

        h0, r0 = profile[segment_index]
        h1, r1 = profile[segment_index + 1]
        t = (profile_height - h0) / max(1e-9, h1 - h0)
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
        interpolated_radius = (
            (2.0 * t3 - 3.0 * t2 + 1.0) * r0
            + (t3 - 2.0 * t2 + t) * span * m0
            + (-2.0 * t3 + 3.0 * t2) * r1
            + (t3 - t2) * span * m1
        )
        lower = min(r0, r1)
        upper = max(r0, r1)
        return max(0.0, min(upper, max(lower, interpolated_radius)))

    if not isinstance(center, list) or len(center) != 3 or not all(_is_number(v) for v in center):
        raise ValueError("center must be a list of 3 float values.")
    center = [float(center[0]), float(center[1]), float(center[2])]
    if height <= 0:
        raise ValueError("height must be greater than zero.")
    if segments_u < 3 or segments_v < 1:
        raise ValueError("segments_u must be >= 3 and segments_v must be >= 1.")
    opacity = _validate_scalar(opacity, "opacity")
    if opacity < 0.0 or opacity > 1.0:
        raise ValueError("opacity must be in the 0..1 range.")
    if angle_end <= angle_start:
        raise ValueError("angle_end must be greater than angle_start.")
    if not isinstance(profile_interpolation, str):
        raise ValueError("profile_interpolation must be one of linear or smooth.")
    profile_interpolation = profile_interpolation.lower()
    if profile_interpolation not in {"linear", "smooth"}:
        raise ValueError("profile_interpolation must be one of linear or smooth.")
    clean_surface_profile = _validate_profile(surface_profile, "surface_profile")

    if target_object:
        if not cmds.objExists(target_object):
            raise ValueError(f"target_object does not exist: {target_object}")
        if radius is None and clean_surface_profile is None:
            bbox = cmds.exactWorldBoundingBox(target_object)
            radius = max((bbox[3] - bbox[0]) * 0.5, (bbox[5] - bbox[2]) * 0.5)
            center = [(bbox[0] + bbox[3]) * 0.5, center[1], (bbox[2] + bbox[5]) * 0.5]

    if radius is None and clean_surface_profile is not None:
        radius = _profile_radius_at(clean_surface_profile, float(vertical_center), profile_interpolation)
    if radius is None:
        raise ValueError("radius or surface_profile is required when target_object is not specified.")
    if radius <= 0:
        raise ValueError("radius must be greater than zero.")

    if name is None:
        base_name = os.path.splitext(os.path.basename(texture_path))[0] or "textured"
        name = f"{base_name}_curved_label"
    if material_name is None:
        material_name = f"{name}_mat"

    angle_span = math.radians(angle_end - angle_start)
    arc_width = radius * angle_span

    label = cmds.polyPlane(
        name=name,
        width=arc_width,
        height=height,
        subdivisionsX=segments_u,
        subdivisionsY=segments_v,
        axis=[0, 0, 1],
        constructionHistory=False,
    )[0]

    vertices = cmds.ls(f"{label}.vtx[*]", flatten=True) or []
    theta_start = math.radians(angle_start)
    theta_end = math.radians(angle_end)

    for vertex in vertices:
        x, y, _ = cmds.xform(vertex, query=True, objectSpace=True, translation=True)
        u = (x / arc_width) + 0.5
        theta = theta_start + (theta_end - theta_start) * u
        local_height = float(vertical_center) + y
        if clean_surface_profile is not None:
            label_radius = _profile_radius_at(clean_surface_profile, local_height, profile_interpolation) + offset
        else:
            label_radius = radius + offset
        world_x = center[0] + label_radius * math.sin(theta)
        world_y = center[1] + local_height
        world_z = center[2] + label_radius * math.cos(theta)
        cmds.xform(vertex, worldSpace=True, translation=[world_x, world_y, world_z])

    try:
        cmds.polySoftEdge(label, angle=180, constructionHistory=False)
    except Exception:
        pass

    shader = cmds.shadingNode("lambert", asShader=True, name=material_name)
    file_node = cmds.shadingNode("file", asTexture=True, name=f"{material_name}_file")
    place2d = cmds.shadingNode("place2dTexture", asUtility=True, name=f"{material_name}_place2d")

    for attr in ["outUV", "outUvFilterSize"]:
        destination = "uvCoord" if attr == "outUV" else "uvFilterSize"
        cmds.connectAttr(f"{place2d}.{attr}", f"{file_node}.{destination}", force=True)
    for attr in [
        "coverage",
        "translateFrame",
        "rotateFrame",
        "mirrorU",
        "mirrorV",
        "stagger",
        "wrapU",
        "wrapV",
        "repeatUV",
        "offset",
        "rotateUV",
        "noiseUV",
        "vertexUvOne",
        "vertexUvTwo",
        "vertexUvThree",
        "vertexCameraOne",
    ]:
        if cmds.attributeQuery(attr, node=place2d, exists=True) and cmds.attributeQuery(attr, node=file_node, exists=True):
            cmds.connectAttr(f"{place2d}.{attr}", f"{file_node}.{attr}", force=True)

    cmds.setAttr(f"{file_node}.fileTextureName", normalized_texture_path, type="string")
    cmds.connectAttr(f"{file_node}.outColor", f"{shader}.color", force=True)
    if cmds.attributeQuery("transparency", node=shader, exists=True):
        cmds.setAttr(f"{shader}.transparency", 1.0 - opacity, 1.0 - opacity, 1.0 - opacity, type="double3")
    alpha_node = None
    alpha_opacity_node = None
    if use_alpha and cmds.attributeQuery("transparency", node=shader, exists=True):
        if cmds.attributeQuery("outAlpha", node=file_node, exists=True):
            alpha_opacity_node = cmds.shadingNode("multiplyDivide", asUtility=True, name=f"{material_name}_alpha_opacity")
            cmds.setAttr(f"{alpha_opacity_node}.input2", opacity, opacity, opacity, type="double3")
            for channel in ["X", "Y", "Z"]:
                cmds.connectAttr(f"{file_node}.outAlpha", f"{alpha_opacity_node}.input1{channel}", force=True)
            alpha_node = cmds.shadingNode("reverse", asUtility=True, name=f"{material_name}_alpha_reverse")
            for channel in ["X", "Y", "Z"]:
                cmds.connectAttr(f"{alpha_opacity_node}.output{channel}", f"{alpha_node}.input{channel}", force=True)
            cmds.connectAttr(f"{alpha_node}.output", f"{shader}.transparency", force=True)
        elif cmds.attributeQuery("outTransparency", node=file_node, exists=True):
            cmds.connectAttr(f"{file_node}.outTransparency", f"{shader}.transparency", force=True)
    shading_group = cmds.sets(name=f"{material_name}SG", empty=True, renderable=True, noSurfaceShader=True)
    cmds.connectAttr(f"{shader}.outColor", f"{shading_group}.surfaceShader", force=True)
    cmds.sets(label, edit=True, forceElement=shading_group)

    return {
        "success": True,
        "name": label,
        "shader": shader,
        "file_node": file_node,
        "place2d": place2d,
        "alpha_node": alpha_node,
        "alpha_opacity_node": alpha_opacity_node,
        "shading_group": shading_group,
        "texture_path": normalized_texture_path,
        "radius": radius,
        "surface_profile": clean_surface_profile,
        "profile_interpolation": profile_interpolation,
        "angle_start": angle_start,
        "angle_end": angle_end,
        "segments_u": segments_u,
        "segments_v": segments_v,
        "use_alpha": bool(use_alpha),
        "opacity": opacity,
    }
