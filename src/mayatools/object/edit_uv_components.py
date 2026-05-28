from typing import Dict, List, Any, Union


def edit_uv_components(
    object_name: str,
    operation: str,
    uv_indices: List[int] = None,
    components: Union[str, List[str]] = None,
    values_by_uv: Dict[str, List[float]] = None,
    offset: List[float] = None,
    uv_set: str = None,
    face_components: Union[str, List[str]] = None,
    parameters: Dict[str, Any] = None,
    use_selection: bool = True,
    max_preview: int = 50,
) -> Dict[str, Any]:
    """Query and edit mesh UV components or project UVs onto selected faces.

    Operations:
    - query: report UV coordinates for explicit UVs or current UV selection
    - set: set UV coordinates from values_by_uv keyed by UV index
    - offset: add a UV offset to selected UVs
    - planar_project_faces: run planar UV projection on explicit or selected faces

    This provides component-level UV control for localized label, panel, and
    patch work instead of remapping an entire object.
    """
    import re
    import maya.cmds as cmds

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(value) for value in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(value) for value in values]

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return value

    def _mesh_shape(node):
        if not cmds.objExists(node):
            raise ValueError(f"Object does not exist: {node}")
        if cmds.objectType(node) == "mesh":
            return node
        shapes = cmds.listRelatives(node, shapes=True, fullPath=True) or []
        mesh_shapes = []
        for shape in shapes:
            if cmds.objectType(shape) != "mesh":
                continue
            try:
                if cmds.attributeQuery("intermediateObject", node=shape, exists=True) and cmds.getAttr(f"{shape}.intermediateObject"):
                    continue
            except Exception:
                pass
            mesh_shapes.append(shape)
        if not mesh_shapes:
            raise ValueError(f"{node} is not a polygon mesh transform or mesh shape.")
        return mesh_shapes[0]

    def _prefix(shape):
        parents = cmds.listRelatives(shape, parent=True, fullPath=False) or []
        return parents[0] if parents else object_name

    def _flatten(value):
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("component arguments must be strings, lists of strings, or None.")
        return cmds.ls(value, flatten=True) or []

    def _selected():
        if not use_selection:
            return []
        selected = cmds.ls(selection=True, flatten=True) or []
        object_tokens = {object_name, prefix, shape_name}
        return [item for item in selected if item.split(".", 1)[0] in object_tokens]

    def _uv_components():
        if components is not None:
            resolved = _flatten(components)
        elif uv_indices is not None:
            if not isinstance(uv_indices, list) or not all(isinstance(index, int) and not isinstance(index, bool) for index in uv_indices):
                raise ValueError("uv_indices must be a list of integers.")
            resolved = [f"{prefix}.map[{index}]" for index in uv_indices]
        else:
            resolved = cmds.polyListComponentConversion(_selected(), toUV=True) or []
            resolved = cmds.ls(resolved, flatten=True) or []
        resolved = [item for item in resolved if ".map[" in item]
        if not resolved:
            raise ValueError("No UV components resolved.")
        return resolved

    def _face_components():
        if face_components is not None:
            resolved = _flatten(face_components)
        elif components is not None:
            resolved = cmds.polyListComponentConversion(_flatten(components), toFace=True) or []
            resolved = cmds.ls(resolved, flatten=True) or []
        else:
            resolved = cmds.polyListComponentConversion(_selected(), toFace=True) or []
            resolved = cmds.ls(resolved, flatten=True) or []
        resolved = [item for item in resolved if ".f[" in item]
        if not resolved:
            raise ValueError("No face components resolved.")
        return resolved

    def _uv_id(component):
        match = re.search(r"\.map\[(\d+)\]$", component)
        return int(match.group(1)) if match else None

    def _query_uvs(items):
        values = cmds.polyEditUV(items, query=True) or []
        records = []
        for index, component in enumerate(items):
            offset_index = index * 2
            uv_value = None
            if offset_index + 1 < len(values):
                uv_value = [float(values[offset_index]), float(values[offset_index + 1])]
            records.append({"component": component, "index": _uv_id(component), "uv": uv_value})
        return records

    if not object_name:
        raise ValueError("object_name is required.")
    operation = operation.lower().strip()
    parameters = parameters or {}
    max_preview = _validate_int(max_preview, "max_preview", 0)
    shape_name = _mesh_shape(object_name)
    prefix = _prefix(shape_name)

    all_uv_sets = cmds.polyUVSet(object_name, query=True, allUVSets=True) or []
    previous_uv_set = (cmds.polyUVSet(object_name, query=True, currentUVSet=True) or [None])[0]
    if uv_set:
        if uv_set not in all_uv_sets:
            raise ValueError(f"UV set {uv_set} does not exist on {object_name}.")
        cmds.polyUVSet(object_name, currentUVSet=True, uvSet=uv_set)

    try:
        if operation == "query":
            uv_items = _uv_components()
            records = _query_uvs(uv_items)
            return {
                "success": True,
                "object_name": object_name,
                "operation": operation,
                "uv_set": uv_set or previous_uv_set,
                "uv_count": len(records),
                "uvs": records[:max_preview],
            }

        if operation == "set":
            uv_items = _uv_components()
            if not isinstance(values_by_uv, dict) or not values_by_uv:
                raise ValueError("operation=set requires values_by_uv keyed by UV index.")
            before = _query_uvs(uv_items)
            edited = []
            for component in uv_items:
                uv_id = _uv_id(component)
                key = str(uv_id)
                if key not in values_by_uv:
                    continue
                value = _validate_vector(values_by_uv[key], 2, f"values_by_uv[{key}]")
                cmds.polyEditUV(component, relative=False, uValue=value[0], vValue=value[1])
                edited.append(component)
            after = _query_uvs(uv_items)
            return {
                "success": True,
                "object_name": object_name,
                "operation": operation,
                "uv_set": uv_set or previous_uv_set,
                "edited_count": len(edited),
                "edited_components_preview": edited[:max_preview],
                "before_preview": before[:max_preview],
                "after_preview": after[:max_preview],
            }

        if operation == "offset":
            uv_items = _uv_components()
            clean_offset = _validate_vector(offset, 2, "offset")
            before = _query_uvs(uv_items)
            cmds.polyEditUV(uv_items, relative=True, uValue=clean_offset[0], vValue=clean_offset[1])
            after = _query_uvs(uv_items)
            return {
                "success": True,
                "object_name": object_name,
                "operation": operation,
                "uv_set": uv_set or previous_uv_set,
                "edited_count": len(uv_items),
                "offset": clean_offset,
                "before_preview": before[:max_preview],
                "after_preview": after[:max_preview],
            }

        if operation == "planar_project_faces":
            faces = _face_components()
            result = cmds.polyPlanarProjection(
                faces,
                mapDirection=parameters.get("map_direction", "y"),
                projectionWidth=float(parameters.get("projection_width", 1.0)),
                projectionHeight=float(parameters.get("projection_height", 1.0)),
                imageCenter=parameters.get("image_center", [0.5, 0.5]),
                imageScale=parameters.get("image_scale", [1.0, 1.0]),
                rotate=parameters.get("rotate", [0.0, 0.0, 0.0]),
                constructionHistory=bool(parameters.get("construction_history", True)),
                worldSpace=bool(parameters.get("world_space", True)),
            )
            return {
                "success": True,
                "object_name": object_name,
                "operation": operation,
                "uv_set": uv_set or previous_uv_set,
                "face_count": len(faces),
                "faces_preview": faces[:max_preview],
                "projection_node": result,
            }

        raise ValueError("Unknown operation. Use query, set, offset, or planar_project_faces.")
    finally:
        if uv_set and previous_uv_set and previous_uv_set in all_uv_sets and cmds.objExists(object_name):
            try:
                cmds.polyUVSet(object_name, currentUVSet=True, uvSet=previous_uv_set)
            except Exception:
                pass
