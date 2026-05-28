from typing import Dict, List, Any, Union


def edit_mesh_topology(
    object_name: str,
    operation: str,
    component_type: str = None,
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    parameters: Dict[str, Any] = None,
    use_selection: bool = True,
    max_preview: int = 50,
) -> Dict[str, Any]:
    """Run component-level polygon topology edits.

    Operations:
    - extrude_faces: extrude selected faces with distance, offset, divisions
    - extrude_edges: extrude selected edges with distance, offset, divisions
    - inset_faces: inset selected faces using offset or local scale
    - bevel_edges: bevel selected edges
    - bevel_vertices: bevel selected vertices
    - poke_faces: poke selected faces into triangles
    - chip_off_faces: detach or duplicate selected faces with optional transform
    - bridge_edges: bridge selected edge loops or edge groups
    - subdivide_faces: subdivide selected faces
    - triangulate_faces: triangulate selected faces
    - quadrangulate_faces: convert selected triangles to quads where possible

    This tool is for Maya-style component topology work. It resolves explicit
    components, indexed components, or the current selection, runs the topology
    operation, and reports before/after mesh counts so no-op topology edits are
    visible.
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

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(item) for item in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(item) for item in values]

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

    def _convert(items, target):
        flags = {
            "vertex": {"toVertex": True},
            "edge": {"toEdge": True},
            "face": {"toFace": True},
        }[target]
        return cmds.ls(cmds.polyListComponentConversion(items, **flags) or [], flatten=True) or []

    def _component_ids(items, kind):
        pattern = re.compile(rf"\.{kind}\[(\d+)\]$")
        ids = []
        for item in cmds.ls(items, flatten=True) or []:
            match = pattern.search(item)
            if match:
                ids.append(int(match.group(1)))
        return sorted(set(ids))

    def _counts():
        return {
            "vertices": int(cmds.polyEvaluate(object_name, vertex=True)),
            "edges": int(cmds.polyEvaluate(object_name, edge=True)),
            "faces": int(cmds.polyEvaluate(object_name, face=True)),
        }

    def _changed(before, after):
        return any(before[key] != after[key] for key in before)

    def _selection_result(node_result, resolved, before):
        after = _counts()
        if not _changed(before, after):
            raise RuntimeError(f"{operation} did not change mesh topology.")
        current_selection = cmds.ls(selection=True, flatten=True) or []
        return {
            "success": True,
            "object_name": object_name,
            "operation": operation,
            "node": node_result,
            "input_component_count": len(resolved),
            "input_components_preview": resolved[:max_preview],
            "selected_after_count": len(current_selection),
            "selected_after_preview": current_selection[:max_preview],
            "counts_before": before,
            "counts_after": after,
        }

    if not object_name:
        raise ValueError("object_name is required.")
    operation = operation.lower().strip()
    allowed = {
        "extrude_faces",
        "extrude_edges",
        "inset_faces",
        "bevel_edges",
        "bevel_vertices",
        "poke_faces",
        "chip_off_faces",
        "bridge_edges",
        "subdivide_faces",
        "triangulate_faces",
        "quadrangulate_faces",
    }
    if operation not in allowed:
        raise ValueError(f"operation must be one of: {', '.join(sorted(allowed))}.")
    parameters = parameters or {}
    max_preview = _validate_int(max_preview, "max_preview", 1)
    shape_name = _mesh_shape(object_name)
    prefix_name = _prefix(shape_name)
    before_counts = _counts()

    construction_history = bool(parameters.get("construction_history", False))

    if operation in {"extrude_faces", "inset_faces"}:
        faces = _convert(_resolve_components("face"), "face")
        if not faces:
            raise ValueError(f"{operation} requires face components.")
        divisions = _validate_int(parameters.get("divisions", 1), "divisions", 1)
        keep_faces_together = bool(parameters.get("keep_faces_together", True))
        local_translate = _validate_vector(parameters.get("local_translate", [0.0, 0.0, float(parameters.get("distance", 0.0))]), 3, "local_translate")
        offset = _validate_scalar(parameters.get("offset", 0.0), "offset")
        local_scale = _validate_vector(parameters.get("local_scale", [1.0, 1.0, 1.0]), 3, "local_scale")
        if operation == "inset_faces" and abs(offset) <= 1e-12 and local_scale == [1.0, 1.0, 1.0]:
            raise ValueError("inset_faces requires parameters.offset or a non-identity local_scale.")
        node = cmds.polyExtrudeFacet(
            faces,
            constructionHistory=construction_history,
            divisions=divisions,
            keepFacesTogether=keep_faces_together,
            localTranslate=local_translate,
            offset=offset,
            localScale=local_scale,
        )
        return _selection_result(node, faces, before_counts)

    if operation == "extrude_edges":
        edges = _convert(_resolve_components("edge"), "edge")
        if not edges:
            raise ValueError("extrude_edges requires edge components.")
        divisions = _validate_int(parameters.get("divisions", 1), "divisions", 1)
        local_translate = _validate_vector(parameters.get("local_translate", [0.0, float(parameters.get("distance", 0.0)), 0.0]), 3, "local_translate")
        offset = _validate_scalar(parameters.get("offset", 0.0), "offset")
        local_scale = _validate_vector(parameters.get("local_scale", [1.0, 1.0, 1.0]), 3, "local_scale")
        node = cmds.polyExtrudeEdge(
            edges,
            constructionHistory=construction_history,
            divisions=divisions,
            localTranslate=local_translate,
            offset=offset,
            localScale=local_scale,
        )
        return _selection_result(node, edges, before_counts)

    if operation in {"bevel_edges", "bevel_vertices"}:
        target_type = "edge" if operation == "bevel_edges" else "vertex"
        resolved = _convert(_resolve_components(target_type), target_type)
        if not resolved:
            raise ValueError(f"{operation} requires {target_type} components.")
        fraction = _validate_scalar(parameters.get("fraction", parameters.get("width", 0.1)), "fraction")
        segments = _validate_int(parameters.get("segments", 1), "segments", 1)
        merge_vertices = bool(parameters.get("merge_vertices", True))
        node = cmds.polyBevel3(
            resolved,
            constructionHistory=construction_history,
            fraction=fraction,
            segments=segments,
            mergeVertices=merge_vertices,
        )
        return _selection_result(node, resolved, before_counts)

    if operation == "poke_faces":
        faces = _convert(_resolve_components("face"), "face")
        if not faces:
            raise ValueError("poke_faces requires face components.")
        local_translate = _validate_vector(parameters.get("local_translate", [0.0, 0.0, float(parameters.get("distance", 0.0))]), 3, "local_translate")
        node = cmds.polyPoke(
            faces,
            constructionHistory=construction_history,
            localTranslate=local_translate,
        )
        return _selection_result(node, faces, before_counts)

    if operation == "chip_off_faces":
        faces = _convert(_resolve_components("face"), "face")
        if not faces:
            raise ValueError("chip_off_faces requires face components.")
        duplicate = bool(parameters.get("duplicate", False))
        keep_faces_together = bool(parameters.get("keep_faces_together", True))
        local_translate = _validate_vector(parameters.get("local_translate", [0.0, 0.0, float(parameters.get("distance", 0.0))]), 3, "local_translate")
        node = cmds.polyChipOff(
            faces,
            constructionHistory=construction_history,
            duplicate=duplicate,
            keepFacesTogether=keep_faces_together,
            localTranslate=local_translate,
        )
        return _selection_result(node, faces, before_counts)

    if operation == "bridge_edges":
        edges = _convert(_resolve_components("edge"), "edge")
        if len(edges) < 2:
            raise ValueError("bridge_edges requires at least two edge components.")
        divisions = _validate_int(parameters.get("divisions", 1), "divisions", 0)
        twist = _validate_scalar(parameters.get("twist", 0.0), "twist")
        bridge_offset = _validate_int(parameters.get("bridge_offset", 0), "bridge_offset", 0)
        node = cmds.polyBridgeEdge(
            edges,
            constructionHistory=construction_history,
            divisions=divisions,
            twist=twist,
            bridgeOffset=bridge_offset,
        )
        return _selection_result(node, edges, before_counts)

    if operation == "subdivide_faces":
        faces = _convert(_resolve_components("face"), "face")
        if not faces:
            raise ValueError("subdivide_faces requires face components.")
        divisions = _validate_int(parameters.get("divisions", 1), "divisions", 1)
        mode = _validate_int(parameters.get("mode", 0), "mode", 0)
        node = cmds.polySubdivideFacet(
            faces,
            constructionHistory=construction_history,
            divisions=divisions,
            mode=mode,
        )
        return _selection_result(node, faces, before_counts)

    if operation == "triangulate_faces":
        faces = _convert(_resolve_components("face"), "face")
        if not faces:
            raise ValueError("triangulate_faces requires face components.")
        node = cmds.polyTriangulate(faces, constructionHistory=construction_history)
        return _selection_result(node, faces, before_counts)

    if operation == "quadrangulate_faces":
        faces = _convert(_resolve_components("face"), "face")
        if not faces:
            raise ValueError("quadrangulate_faces requires face components.")
        angle = _validate_scalar(parameters.get("angle", 30.0), "angle")
        keep_hard_edges = bool(parameters.get("keep_hard_edges", False))
        keep_texture_borders = bool(parameters.get("keep_texture_borders", True))
        node = cmds.polyQuad(
            faces,
            constructionHistory=construction_history,
            angle=angle,
            keepHardEdges=keep_hard_edges,
            keepTextureBorders=keep_texture_borders,
        )
        return _selection_result(node, faces, before_counts)

    raise ValueError(f"Unsupported operation: {operation}")
