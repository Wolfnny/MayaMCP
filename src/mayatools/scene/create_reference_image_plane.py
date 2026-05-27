from typing import Dict, List, Any, Union


def create_reference_image_plane(
    image_path: str,
    name: str = "reference_image_plane",
    target_objects: Union[str, List[str]] = None,
    center: List[float] = None,
    width: float = None,
    height: float = None,
    image_aspect: float = 0.0,
    fit_to_targets: bool = True,
    fit_padding: float = 1.0,
    plane_axis: str = "z",
    offset: float = -0.05,
    opacity: float = 0.45,
    use_alpha: bool = False,
    material_name: str = None,
    subdivisions_x: int = 1,
    subdivisions_y: int = 1,
    lock_transform: bool = False,
    replace_existing: bool = True,
) -> Dict[str, Any]:
    """Create a world-space textured reference image plane.

    The plane can be fitted to one or more target objects so photographed or
    concept-art references can be compared directly against modeled geometry.
    plane_axis controls the plane normal: "z" creates an XY front plane, "x"
    creates a YZ side plane, and "y" creates an XZ top/bottom plane. When
    use_alpha is true, texture alpha is connected to material transparency.
    """
    import os
    import struct
    import maya.cmds as cmds

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(v) for v in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(v) for v in values]

    def _validate_optional_scalar(value, arg_name):
        if value is None:
            return None
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric or None.")
        value = float(value)
        if value <= 0.0:
            raise ValueError(f"{arg_name} must be greater than zero.")
        return value

    def _validate_segments(value, arg_name):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to 1.")
        return value

    def _normalize_targets(targets):
        if targets is None:
            return []
        if isinstance(targets, str):
            targets = [targets]
        if not isinstance(targets, list) or not all(isinstance(item, str) for item in targets):
            raise ValueError("target_objects must be a string, a list of strings, or None.")
        for target in targets:
            if not cmds.objExists(target):
                raise ValueError(f"target object does not exist: {target}")
        return targets

    def _combined_bbox(objects):
        first = cmds.exactWorldBoundingBox(objects[0])
        bbox = list(first)
        for obj in objects[1:]:
            obj_bbox = cmds.exactWorldBoundingBox(obj)
            bbox[0] = min(bbox[0], obj_bbox[0])
            bbox[1] = min(bbox[1], obj_bbox[1])
            bbox[2] = min(bbox[2], obj_bbox[2])
            bbox[3] = max(bbox[3], obj_bbox[3])
            bbox[4] = max(bbox[4], obj_bbox[4])
            bbox[5] = max(bbox[5], obj_bbox[5])
        return bbox

    def _read_image_dimensions(path):
        with open(path, "rb") as handle:
            header = handle.read(32)
            if header.startswith(b"\x89PNG\r\n\x1a\n"):
                return struct.unpack(">II", header[16:24])
            if header[:6] in {b"GIF87a", b"GIF89a"}:
                return struct.unpack("<HH", header[6:10])
            if header.startswith(b"\xff\xd8"):
                handle.seek(2)
                while True:
                    byte = handle.read(1)
                    while byte and byte != b"\xff":
                        byte = handle.read(1)
                    if not byte:
                        break
                    marker = handle.read(1)
                    while marker == b"\xff":
                        marker = handle.read(1)
                    if not marker:
                        break
                    marker_code = marker[0]
                    if marker_code in {0xD8, 0xD9}:
                        continue
                    length_bytes = handle.read(2)
                    if len(length_bytes) != 2:
                        break
                    block_length = int.from_bytes(length_bytes, "big")
                    if block_length < 2:
                        break
                    sof_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
                    if marker_code in sof_markers:
                        data = handle.read(block_length - 2)
                        if len(data) >= 5:
                            image_height = int.from_bytes(data[1:3], "big")
                            image_width = int.from_bytes(data[3:5], "big")
                            return image_width, image_height
                        break
                    handle.seek(block_length - 2, os.SEEK_CUR)
        return None, None

    def _safe_delete(node_name):
        if node_name and cmds.objExists(node_name):
            try:
                cmds.delete(node_name)
            except Exception:
                pass

    if not image_path:
        raise ValueError("image_path is required.")
    normalized_image_path = os.path.normpath(image_path)
    if not os.path.isfile(normalized_image_path):
        raise ValueError(f"Image path does not exist: {image_path}")
    if not name:
        base_name = os.path.splitext(os.path.basename(normalized_image_path))[0] or "reference"
        name = f"{base_name}_reference_plane"

    target_objects = _normalize_targets(target_objects)
    width = _validate_optional_scalar(width, "width")
    height = _validate_optional_scalar(height, "height")
    if not _is_number(image_aspect):
        raise ValueError("image_aspect must be numeric.")
    image_aspect = float(image_aspect)
    if image_aspect < 0.0:
        raise ValueError("image_aspect must be greater than or equal to zero.")
    if not _is_number(fit_padding) or fit_padding <= 0.0:
        raise ValueError("fit_padding must be numeric and greater than zero.")
    fit_padding = float(fit_padding)
    if not _is_number(offset):
        raise ValueError("offset must be numeric.")
    offset = float(offset)
    if not _is_number(opacity) or opacity < 0.0 or opacity > 1.0:
        raise ValueError("opacity must be numeric in the 0..1 range.")
    opacity = float(opacity)
    subdivisions_x = _validate_segments(subdivisions_x, "subdivisions_x")
    subdivisions_y = _validate_segments(subdivisions_y, "subdivisions_y")

    plane_axis = plane_axis.lower().strip()
    axis_data = {
        "x": {"axis": [1, 0, 0], "width_index": 2, "height_index": 1, "normal_index": 0},
        "y": {"axis": [0, 1, 0], "width_index": 0, "height_index": 2, "normal_index": 1},
        "z": {"axis": [0, 0, 1], "width_index": 0, "height_index": 1, "normal_index": 2},
    }
    if plane_axis not in axis_data:
        raise ValueError("plane_axis must be one of x, y, or z.")
    plane_info = axis_data[plane_axis]

    image_width_pixels, image_height_pixels = _read_image_dimensions(normalized_image_path)
    if image_aspect == 0.0:
        if image_width_pixels and image_height_pixels:
            image_aspect = float(image_width_pixels) / float(image_height_pixels)
        else:
            image_aspect = 1.0

    bbox = None
    bbox_center = [0.0, 0.0, 0.0]
    bbox_size = [1.0, 1.0, 1.0]
    if target_objects:
        bbox = _combined_bbox(target_objects)
        bbox_center = [
            (bbox[0] + bbox[3]) * 0.5,
            (bbox[1] + bbox[4]) * 0.5,
            (bbox[2] + bbox[5]) * 0.5,
        ]
        bbox_size = [
            max(1e-6, bbox[3] - bbox[0]),
            max(1e-6, bbox[4] - bbox[1]),
            max(1e-6, bbox[5] - bbox[2]),
        ]

    if center is None:
        center = bbox_center[:]
    else:
        center = _validate_vector(center, 3, "center")

    if target_objects and fit_to_targets:
        if height is None:
            height = bbox_size[plane_info["height_index"]] * fit_padding
        if width is None:
            width = height * image_aspect
    if height is None and width is None:
        height = 1.0
        width = height * image_aspect
    elif height is None:
        height = width / max(1e-9, image_aspect)
    elif width is None:
        width = height * image_aspect

    if target_objects and center is not None:
        normal_index = plane_info["normal_index"]
        if offset < 0.0:
            center[normal_index] = bbox[normal_index] + offset
        else:
            center[normal_index] = bbox[normal_index + 3] + offset
    else:
        center[plane_info["normal_index"]] += offset

    if material_name is None:
        material_name = f"{name}_mat"
    shading_group = f"{material_name}SG"

    if replace_existing:
        for node_name in [
            name,
            shading_group,
            f"{material_name}_file",
            f"{material_name}_place2d",
            f"{material_name}_alpha_opacity",
            f"{material_name}_alpha_reverse",
            material_name,
        ]:
            _safe_delete(node_name)

    plane = cmds.polyPlane(
        name=name,
        width=width,
        height=height,
        subdivisionsX=subdivisions_x,
        subdivisionsY=subdivisions_y,
        axis=plane_info["axis"],
        constructionHistory=False,
    )[0]
    cmds.xform(plane, translation=center, worldSpace=True)

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

    cmds.setAttr(f"{file_node}.fileTextureName", normalized_image_path, type="string")
    cmds.connectAttr(f"{file_node}.outColor", f"{shader}.color", force=True)
    cmds.setAttr(f"{shader}.ambientColor", 1.0, 1.0, 1.0, type="double3")
    cmds.setAttr(f"{shader}.diffuse", 1.0)
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

    shading_group = cmds.sets(name=shading_group, empty=True, renderable=True, noSurfaceShader=True)
    cmds.connectAttr(f"{shader}.outColor", f"{shading_group}.surfaceShader", force=True)
    cmds.sets(plane, edit=True, forceElement=shading_group)

    shape_nodes = cmds.listRelatives(plane, shapes=True, fullPath=False) or []
    for shape in shape_nodes:
        for attr in ["castsShadows", "receiveShadows", "visibleInReflections", "visibleInRefractions"]:
            if cmds.attributeQuery(attr, node=shape, exists=True):
                try:
                    cmds.setAttr(f"{shape}.{attr}", False)
                except Exception:
                    pass

    if lock_transform:
        for attr in ["tx", "ty", "tz", "rx", "ry", "rz", "sx", "sy", "sz"]:
            try:
                cmds.setAttr(f"{plane}.{attr}", lock=True, keyable=False, channelBox=False)
            except Exception:
                pass

    return {
        "success": True,
        "plane": plane,
        "shape_nodes": shape_nodes,
        "material": shader,
        "file_node": file_node,
        "place2d": place2d,
        "alpha_node": alpha_node,
        "alpha_opacity_node": alpha_opacity_node,
        "shading_group": shading_group,
        "image_path": normalized_image_path,
        "image_width_pixels": image_width_pixels,
        "image_height_pixels": image_height_pixels,
        "image_aspect": image_aspect,
        "target_objects": target_objects,
        "bounding_box": bbox,
        "center": center,
        "width": width,
        "height": height,
        "plane_axis": plane_axis,
        "offset": offset,
        "opacity": opacity,
        "use_alpha": bool(use_alpha),
    }
