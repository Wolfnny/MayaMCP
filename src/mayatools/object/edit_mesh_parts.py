from typing import Dict, List, Any, Union


def edit_mesh_parts(
    object_name: str,
    operation: str,
    target_objects: List[str] = None,
    component_type: str = None,
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    parameters: Dict[str, Any] = None,
    use_selection: bool = True,
    max_preview: int = 50,
) -> Dict[str, Any]:
    """Extract, separate, and combine polygon mesh parts.

    Operations:
    - extract_faces: duplicate selected faces into a separate mesh, optionally
      deleting them from the source
    - separate_shells: separate disconnected mesh shells into separate objects
    - combine_meshes: combine multiple mesh transforms into one mesh, optionally
      merging coincident vertices

    This covers common Maya artist workflows where local modeled areas become
    separate editable objects, disconnected shells are split apart, or separate
    pieces are merged back into a single polygon mesh.
    """
    import re
    import maya.cmds as cmds

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return int(value)

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
            raise ValueError("components must be a string, a list of strings, or None.")
        return cmds.ls(value, flatten=True) or []

    def _unique(items):
        result = []
        seen = set()
        for item in cmds.ls(items, flatten=True) or []:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result

    def _selected_components():
        if not use_selection:
            return []
        selected = cmds.ls(selection=True, flatten=True) or []
        object_tokens = {object_name, prefix_name, shape_name}
        return [item for item in selected if item.split(".", 1)[0] in object_tokens]

    def _components_from_indices(kind):
        if indices is None:
            return []
        if not isinstance(indices, list) or not all(isinstance(index, int) and not isinstance(index, bool) for index in indices):
            raise ValueError("indices must be a list of integers.")
        return [f"{prefix_name}.{kind}[{index}]" for index in indices]

    def _resolve_components(default_type=None):
        clean_type = (component_type or default_type or "").lower().strip()
        kind_map = {"vertex": "vtx", "edge": "e", "face": "f", "uv": "map", "vertex_face": "vtxFace"}
        if components is not None:
            resolved = _flatten(components)
        elif clean_type in kind_map and indices is not None:
            resolved = _components_from_indices(kind_map[clean_type])
        else:
            resolved = _selected_components()
        if not resolved:
            raise ValueError("No components resolved from components, indices, or current selection.")
        return resolved

    def _component_ids(items, kind):
        pattern = re.compile(rf"\.{kind}\[(\d+)\]$")
        ids = []
        for item in cmds.ls(items, flatten=True) or []:
            match = pattern.search(item)
            if match:
                ids.append(int(match.group(1)))
        return sorted(set(ids))

    def _face_ids_from_components():
        resolved = _resolve_components("face")
        faces = cmds.polyListComponentConversion(resolved, toFace=True) or []
        face_ids = _component_ids(faces, "f")
        if not face_ids:
            raise ValueError("extract_faces requires faces or components convertible to faces.")
        return face_ids

    def _counts(node):
        if not cmds.objExists(node):
            return None
        return {
            "vertices": int(cmds.polyEvaluate(node, vertex=True)),
            "edges": int(cmds.polyEvaluate(node, edge=True)),
            "faces": int(cmds.polyEvaluate(node, face=True)),
        }

    def _mesh_transforms(nodes):
        result = []
        for node in nodes or []:
            if not cmds.objExists(node) or cmds.objectType(node) != "transform":
                continue
            shapes = cmds.listRelatives(node, shapes=True, fullPath=False) or []
            if any(cmds.objectType(shape) == "mesh" for shape in shapes):
                result.append(node)
        return list(dict.fromkeys(result))

    def _validate_targets(values):
        if values is None:
            values = []
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise ValueError("target_objects must be a list of object names.")
        for item in values:
            _mesh_shape(item)
        return values

    def _delete_history_if_requested(node):
        if bool(parameters.get("delete_history", True)) and cmds.objExists(node):
            cmds.delete(node, constructionHistory=True)

    if not object_name:
        raise ValueError("object_name is required.")
    if not operation:
        raise ValueError("operation is required.")
    operation = operation.lower().strip()
    if operation not in {"extract_faces", "separate_shells", "combine_meshes"}:
        raise ValueError("operation must be extract_faces, separate_shells, or combine_meshes.")
    parameters = parameters or {}
    max_preview = _validate_int(max_preview, "max_preview", 1)
    shape_name = _mesh_shape(object_name)
    prefix_name = _prefix(shape_name)
    before_counts = _counts(prefix_name)

    if operation == "extract_faces":
        face_ids = _face_ids_from_components()
        total_faces = int(cmds.polyEvaluate(prefix_name, face=True))
        if any(face_id < 0 or face_id >= total_faces for face_id in face_ids):
            raise ValueError(f"Face indices must be in range 0..{total_faces - 1}.")
        selected_set = set(face_ids)
        inverse_face_ids = [face_id for face_id in range(total_faces) if face_id not in selected_set]
        result_name = parameters.get("name") or f"{prefix_name}_extracted"
        extracted = cmds.duplicate(prefix_name, name=result_name, renameChildren=True)[0]
        if inverse_face_ids:
            cmds.delete([f"{extracted}.f[{face_id}]" for face_id in inverse_face_ids])
        _delete_history_if_requested(extracted)
        remove_from_source = bool(parameters.get("remove_from_source", False))
        if remove_from_source:
            cmds.delete([f"{prefix_name}.f[{face_id}]" for face_id in face_ids])
            _delete_history_if_requested(prefix_name)
        if bool(parameters.get("select_result", True)):
            cmds.select(extracted, replace=True)
        return {
            "success": True,
            "object_name": object_name,
            "operation": operation,
            "source_object": prefix_name,
            "created_object": extracted,
            "selected_face_count": len(face_ids),
            "selected_faces_preview": face_ids[:max_preview],
            "remove_from_source": remove_from_source,
            "source_counts_before": before_counts,
            "source_counts_after": _counts(prefix_name),
            "created_counts": _counts(extracted),
        }

    if operation == "separate_shells":
        result_name = parameters.get("name") or f"{prefix_name}_part"
        construction_history = bool(parameters.get("construction_history", False))
        separated = cmds.polySeparate(
            prefix_name,
            name=result_name,
            constructionHistory=construction_history,
        )
        objects = _mesh_transforms(separated)
        if len(objects) < 2:
            raise RuntimeError("separate_shells did not create multiple mesh objects.")
        for obj in objects:
            _delete_history_if_requested(obj)
        if bool(parameters.get("select_result", True)):
            cmds.select(objects, replace=True)
        return {
            "success": True,
            "object_name": object_name,
            "operation": operation,
            "source_counts_before": before_counts,
            "created_objects": objects,
            "created_object_count": len(objects),
            "created_counts": {obj: _counts(obj) for obj in objects},
        }

    targets = _validate_targets(target_objects)
    if not targets:
        raise ValueError("combine_meshes requires target_objects.")
    objects_to_combine = [prefix_name] + targets
    result_name = parameters.get("name") or f"{prefix_name}_combined"
    construction_history = bool(parameters.get("construction_history", False))
    merge_uv_sets = _validate_int(parameters.get("merge_uv_sets", 1), "merge_uv_sets", 0)
    combined = cmds.polyUnite(
        objects_to_combine,
        name=result_name,
        constructionHistory=construction_history,
        mergeUVSets=merge_uv_sets,
    )[0]
    if bool(parameters.get("merge_vertices", False)):
        distance = _validate_scalar(parameters.get("merge_distance", 0.001), "merge_distance")
        cmds.polyMergeVertex(
            combined,
            distance=distance,
            texture=bool(parameters.get("merge_texture", True)),
            constructionHistory=construction_history,
        )
    _delete_history_if_requested(combined)
    if bool(parameters.get("center_pivot", False)):
        cmds.xform(combined, centerPivots=True)
    if bool(parameters.get("select_result", True)):
        cmds.select(combined, replace=True)
    return {
        "success": True,
        "object_name": object_name,
        "operation": operation,
        "input_objects": objects_to_combine,
        "combined_object": combined,
        "combined_counts": _counts(combined),
        "merge_vertices": bool(parameters.get("merge_vertices", False)),
    }
