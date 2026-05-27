from typing import Dict, List, Any, Union


def create_textured_material(
    texture_path: str,
    name: str = None,
    material_type: str = "lambert",
    assign_to: Union[str, List[str]] = None,
    color_attribute: str = "color",
    repeat_uv: List[float] = [1.0, 1.0],
    offset_uv: List[float] = [0.0, 0.0],
    rotate_uv: float = 0.0,
    use_alpha: bool = False,
) -> Dict[str, Any]:
    """Create a material driven by an image texture and optionally assign it to objects.

    Supported material types are lambert, phong, blinn, and surfaceShader.
    The target mesh should already have usable UVs. Use uv_operations to create
    or adjust UVs before assigning this material when needed.
    """
    import os
    import maya.cmds as cmds

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector2(values: List[float], arg_name: str):
        if not isinstance(values, list) or len(values) != 2 or not all(_is_number(v) for v in values):
            raise ValueError(f"{arg_name} must be a list of 2 float values.")
        return [float(values[0]), float(values[1])]

    repeat_uv = _validate_vector2(repeat_uv, "repeat_uv")
    offset_uv = _validate_vector2(offset_uv, "offset_uv")

    if not texture_path:
        raise ValueError("texture_path is required.")

    normalized_texture_path = os.path.normpath(texture_path)
    if not os.path.exists(normalized_texture_path):
        raise ValueError(f"Texture path does not exist: {texture_path}")

    material_type = material_type.strip()
    supported = {"lambert", "phong", "blinn", "surfaceShader"}
    if material_type not in supported:
        raise ValueError(f"Unsupported material_type {material_type}. Use one of {sorted(supported)}")

    if name is None:
        base_name = os.path.splitext(os.path.basename(texture_path))[0] or "textured"
        name = f"{base_name}_{material_type}_mat"

    shader = cmds.shadingNode(material_type, asShader=True, name=name)
    file_node = cmds.shadingNode("file", asTexture=True, name=f"{name}_file")
    place2d = cmds.shadingNode("place2dTexture", asUtility=True, name=f"{name}_place2d")

    for attr in ["outUV", "outUvFilterSize"]:
        destination = "uvCoord" if attr == "outUV" else "uvFilterSize"
        cmds.connectAttr(f"{place2d}.{attr}", f"{file_node}.{destination}", force=True)

    passthrough_attrs = [
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
    ]
    for attr in passthrough_attrs:
        if cmds.attributeQuery(attr, node=place2d, exists=True) and cmds.attributeQuery(attr, node=file_node, exists=True):
            cmds.connectAttr(f"{place2d}.{attr}", f"{file_node}.{attr}", force=True)

    cmds.setAttr(f"{file_node}.fileTextureName", normalized_texture_path, type="string")
    cmds.setAttr(f"{place2d}.repeatU", repeat_uv[0])
    cmds.setAttr(f"{place2d}.repeatV", repeat_uv[1])
    cmds.setAttr(f"{place2d}.offsetU", offset_uv[0])
    cmds.setAttr(f"{place2d}.offsetV", offset_uv[1])
    cmds.setAttr(f"{place2d}.rotateUV", rotate_uv)

    if material_type == "surfaceShader":
        target_attribute = "outColor"
    else:
        target_attribute = color_attribute

    if not cmds.attributeQuery(target_attribute, node=shader, exists=True):
        raise ValueError(f"Shader {shader} does not have attribute {target_attribute}")

    cmds.connectAttr(f"{file_node}.outColor", f"{shader}.{target_attribute}", force=True)

    if use_alpha and material_type != "surfaceShader" and cmds.attributeQuery("transparency", node=shader, exists=True):
        cmds.connectAttr(f"{file_node}.outTransparency", f"{shader}.transparency", force=True)

    shading_group = cmds.sets(name=f"{name}SG", empty=True, renderable=True, noSurfaceShader=True)
    source_attr = "outColor" if material_type != "surfaceShader" else "outColor"
    cmds.connectAttr(f"{shader}.{source_attr}", f"{shading_group}.surfaceShader", force=True)

    assigned_to = []
    if assign_to:
        objects = assign_to if isinstance(assign_to, list) else [assign_to]
        for obj in objects:
            if not cmds.objExists(obj):
                raise ValueError(f"Object does not exist: {obj}")
        cmds.sets(objects, edit=True, forceElement=shading_group)
        assigned_to = objects

    return {
        "success": True,
        "name": name,
        "shader": shader,
        "file_node": file_node,
        "place2d": place2d,
        "shading_group": shading_group,
        "texture_path": normalized_texture_path,
        "assigned_to": assigned_to,
    }
