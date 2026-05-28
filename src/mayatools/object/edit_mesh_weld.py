from typing import Dict, List, Any, Union


def edit_mesh_weld(
    object_name: str,
    operation: str,
    component_type: str = None,
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    parameters: Dict[str, Any] = None,
    use_selection: bool = True,
    max_preview: int = 50,
) -> Dict[str, Any]:
    """Weld, merge, sew, or collapse polygon mesh components.

    Operations:
    - merge_vertices: merge selected vertices within distance
    - merge_vertices_to_target: merge selected vertices to one target vertex
    - collapse_edges: collapse selected edges
    - collapse_faces: collapse selected faces
    - sew_edges: sew selected border edges within tolerance
    - merge_edge_pair: merge exactly two selected edge components
    - merge_face_pair: merge exactly two adjacent face components

    This covers explicit Maya-style weld/collapse workflows with before/after
    topology counts and no-op detection.
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
        return list(dict.fromkeys(ids))

    def _face_edge_ids(face_component):
        edge_components = cmds.polyListComponentConversion(face_component, fromFace=True, toEdge=True) or []
        return set(_component_ids(edge_components, "e"))

    def _counts():
        return {
            "vertices": int(cmds.polyEvaluate(object_name, vertex=True)),
            "edges": int(cmds.polyEvaluate(object_name, edge=True)),
            "faces": int(cmds.polyEvaluate(object_name, face=True)),
        }

    def _changed(before, after):
        return any(before[key] != after[key] for key in before)

    def _result(node_result, resolved, before, extra=None):
        after = _counts()
        if not _changed(before, after):
            raise RuntimeError(f"{operation} did not change mesh topology.")
        current_selection = cmds.ls(selection=True, flatten=True) or []
        payload = {
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
        if extra:
            payload.update(extra)
        return payload

    def _target_vertex_component(vertices):
        target_component = parameters.get("target_component")
        if target_component is not None:
            flattened = _flatten(target_component)
            converted = _convert(flattened, "vertex")
            if len(converted) != 1:
                raise ValueError("parameters.target_component must resolve to exactly one vertex.")
            return converted[0]
        target_index = parameters.get("target_index")
        if target_index is not None:
            clean_index = _validate_int(target_index, "target_index", 0)
            return f"{prefix_name}.vtx[{clean_index}]"
        return vertices[0]

    if not object_name:
        raise ValueError("object_name is required.")
    if not operation:
        raise ValueError("operation is required.")
    operation = operation.lower().strip()
    allowed = {
        "merge_vertices",
        "merge_vertices_to_target",
        "collapse_edges",
        "collapse_faces",
        "sew_edges",
        "merge_edge_pair",
        "merge_face_pair",
    }
    if operation not in allowed:
        raise ValueError(f"operation must be one of: {', '.join(sorted(allowed))}.")

    parameters = parameters or {}
    max_preview = _validate_int(max_preview, "max_preview", 1)
    shape_name = _mesh_shape(object_name)
    prefix_name = _prefix(shape_name)
    before_counts = _counts()
    construction_history = bool(parameters.get("construction_history", False))

    if operation in {"merge_vertices", "merge_vertices_to_target"}:
        vertices = _convert(_resolve_components("vertex"), "vertex")
        if len(vertices) < 2:
            raise ValueError(f"{operation} requires at least two vertices.")
        distance = _validate_scalar(parameters.get("distance", 0.001), "distance")
        texture = bool(parameters.get("texture", True))
        world_space = bool(parameters.get("world_space", False))
        if operation == "merge_vertices":
            always_merge = bool(parameters.get("always_merge", False))
            node = cmds.polyMergeVertex(
                vertices,
                distance=distance,
                alwaysMergeTwoVertices=always_merge,
                texture=texture,
                worldSpace=world_space,
                constructionHistory=construction_history,
            )
            return _result(
                node,
                vertices,
                before_counts,
                {"distance": distance, "always_merge": always_merge, "texture": texture, "world_space": world_space},
            )

        target_vertex = _target_vertex_component(vertices)
        if target_vertex not in vertices:
            vertices = [target_vertex] + vertices
        node = cmds.polyMergeVertex(
            vertices,
            distance=max(distance, 1.0e-9),
            alwaysMergeTwoVertices=True,
            mergeToComponents=target_vertex,
            texture=texture,
            worldSpace=world_space,
            constructionHistory=construction_history,
        )
        return _result(
            node,
            vertices,
            before_counts,
            {"distance": distance, "target_component": target_vertex, "texture": texture, "world_space": world_space},
        )

    if operation == "collapse_edges":
        edges = _convert(_resolve_components("edge"), "edge")
        if not edges:
            raise ValueError("collapse_edges requires edge components.")
        node = cmds.polyCollapseEdge(edges, constructionHistory=construction_history)
        return _result(node, edges, before_counts)

    if operation == "collapse_faces":
        faces = _convert(_resolve_components("face"), "face")
        if not faces:
            raise ValueError("collapse_faces requires face components.")
        use_area_threshold = bool(parameters.get("use_area_threshold", False))
        area_threshold = _validate_scalar(parameters.get("area_threshold", 0.0), "area_threshold")
        node = cmds.polyCollapseFacet(
            faces,
            constructionHistory=construction_history,
            useAreaThreshold=use_area_threshold,
            areaThreshold=area_threshold,
        )
        return _result(
            node,
            faces,
            before_counts,
            {"use_area_threshold": use_area_threshold, "area_threshold": area_threshold},
        )

    if operation == "sew_edges":
        edges = _convert(_resolve_components("edge"), "edge")
        if len(edges) < 2:
            raise ValueError("sew_edges requires at least two edge components.")
        tolerance = _validate_scalar(parameters.get("tolerance", 0.001), "tolerance")
        texture = bool(parameters.get("texture", True))
        world_space = bool(parameters.get("world_space", False))
        node = cmds.polySewEdge(
            edges,
            tolerance=tolerance,
            texture=texture,
            worldSpace=world_space,
            constructionHistory=construction_history,
        )
        return _result(node, edges, before_counts, {"tolerance": tolerance, "texture": texture, "world_space": world_space})

    if operation == "merge_edge_pair":
        edges = _convert(_resolve_components("edge"), "edge")
        edge_ids = _component_ids(edges, "e")
        if len(edge_ids) != 2:
            raise ValueError("merge_edge_pair requires exactly two edge components.")
        merge_mode = _validate_int(parameters.get("merge_mode", 0), "merge_mode", 0)
        merge_texture = bool(parameters.get("merge_texture", True))
        node = cmds.polyMergeEdge(
            object_name,
            firstEdge=edge_ids[0],
            secondEdge=edge_ids[1],
            mergeMode=merge_mode,
            mergeTexture=merge_texture,
            constructionHistory=construction_history,
        )
        return _result(
            node,
            edges,
            before_counts,
            {"edge_ids": edge_ids, "merge_mode": merge_mode, "merge_texture": merge_texture},
        )

    if operation == "merge_face_pair":
        faces = _convert(_resolve_components("face"), "face")
        face_ids = _component_ids(faces, "f")
        if len(face_ids) != 2:
            raise ValueError("merge_face_pair requires exactly two face components.")
        face_components = [f"{prefix_name}.f[{face_id}]" for face_id in face_ids]
        shared_edge_ids = sorted(_face_edge_ids(face_components[0]) & _face_edge_ids(face_components[1]))
        if len(shared_edge_ids) != 1:
            raise ValueError("merge_face_pair requires two adjacent faces with exactly one shared edge.")
        clean_vertices = bool(parameters.get("clean_vertices", False))
        node = cmds.polyDelEdge(
            f"{prefix_name}.e[{shared_edge_ids[0]}]",
            cleanVertices=clean_vertices,
            constructionHistory=construction_history,
        )
        return _result(
            node,
            faces,
            before_counts,
            {"face_ids": face_ids, "shared_edge_id": shared_edge_ids[0], "clean_vertices": clean_vertices},
        )

    raise ValueError(f"Unsupported operation: {operation}")
