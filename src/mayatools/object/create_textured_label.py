from typing import Dict, List, Any


def create_textured_label(
    texture_path: str,
    name: str = None,
    target_object: str = None,
    radius: float = None,
    center: List[float] = [0.0, 0.0, 0.0],
    height: float = 1.0,
    vertical_center: float = 0.0,
    angle_start: float = -60.0,
    angle_end: float = 60.0,
    segments_u: int = 48,
    segments_v: int = 4,
    offset: float = 0.02,
    material_name: str = None,
) -> Dict[str, Any]:
    """Create a UV-mapped curved label mesh and apply an image texture to it.

    The label is a curved polygon strip around the Y axis. UVs are preserved from
    a generated plane, so the image texture is mapped directly to the label UVs
    instead of being approximated with floating text geometry.
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

    if not isinstance(center, list) or len(center) != 3 or not all(_is_number(v) for v in center):
        raise ValueError("center must be a list of 3 float values.")
    center = [float(center[0]), float(center[1]), float(center[2])]
    if height <= 0:
        raise ValueError("height must be greater than zero.")
    if segments_u < 3 or segments_v < 1:
        raise ValueError("segments_u must be >= 3 and segments_v must be >= 1.")
    if angle_end <= angle_start:
        raise ValueError("angle_end must be greater than angle_start.")

    if target_object:
        if not cmds.objExists(target_object):
            raise ValueError(f"target_object does not exist: {target_object}")
        if radius is None:
            bbox = cmds.exactWorldBoundingBox(target_object)
            radius = max((bbox[3] - bbox[0]) * 0.5, (bbox[5] - bbox[2]) * 0.5)
            center = [(bbox[0] + bbox[3]) * 0.5, center[1], (bbox[2] + bbox[5]) * 0.5]

    if radius is None:
        raise ValueError("radius is required when target_object is not specified.")
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
    label_radius = radius + offset

    for vertex in vertices:
        x, y, _ = cmds.xform(vertex, query=True, objectSpace=True, translation=True)
        u = (x / arc_width) + 0.5
        theta = theta_start + (theta_end - theta_start) * u
        world_x = center[0] + label_radius * math.sin(theta)
        world_y = center[1] + vertical_center + y
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
    shading_group = cmds.sets(name=f"{material_name}SG", empty=True, renderable=True, noSurfaceShader=True)
    cmds.connectAttr(f"{shader}.outColor", f"{shading_group}.surfaceShader", force=True)
    cmds.sets(label, edit=True, forceElement=shading_group)

    return {
        "success": True,
        "name": label,
        "shader": shader,
        "file_node": file_node,
        "place2d": place2d,
        "shading_group": shading_group,
        "texture_path": normalized_texture_path,
        "radius": radius,
        "angle_start": angle_start,
        "angle_end": angle_end,
        "segments_u": segments_u,
        "segments_v": segments_v,
    }
