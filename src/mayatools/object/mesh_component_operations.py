from typing import Dict, List, Any, Union


def mesh_component_operations(
    object_name: str,
    operation: str,
    component_type: str = None,
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    parameters: Dict[str, Any] = None,
    use_selection: bool = True,
) -> Dict[str, Any]:
    """Run common Maya polygon component operations.

    Operations include select, delete, merge_vertices, set_normals,
    soften_edges, harden_edges, insert_support_loop, and insert_edge_loop.
    Components can be passed explicitly, built from component_type plus
    indices, or taken from the current Maya selection. This covers low-level
    artist operations such as selecting faces/edges/vertices, welding points,
    changing soft/hard edges, deleting local geometry, and inserting support
    loops.
    """
    import re
    import maya.cmds as cmds

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

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

    def _component_prefix(shape):
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

    def _components_from_indices(kind):
        if indices is None:
            return []
        if not isinstance(indices, list) or not all(isinstance(index, int) and not isinstance(index, bool) for index in indices):
            raise ValueError("indices must be a list of integers.")
        return [f"{prefix}.{kind}[{index}]" for index in indices]

    def _selected_components():
        if not use_selection:
            return []
        selected = cmds.ls(selection=True, flatten=True) or []
        object_tokens = {object_name, prefix, shape_name}
        filtered = []
        for item in selected:
            item_object = item.split(".", 1)[0]
            if item_object in object_tokens:
                filtered.append(item)
        return filtered

    def _resolve_components(default_type=None):
        clean_type = (component_type or default_type or "").lower().strip()
        kind_map = {"vertex": "vtx", "edge": "e", "face": "f", "uv": "map"}
        if components is not None:
            resolved = _flatten(components)
        elif clean_type in kind_map and indices is not None:
            resolved = _components_from_indices(kind_map[clean_type])
        else:
            resolved = _selected_components()
        if not resolved:
            raise ValueError("No components resolved from components, indices, or current selection.")
        return resolved

    def _convert_to_vertices(items):
        converted = cmds.polyListComponentConversion(items, toVertex=True) or []
        vertices = cmds.ls(converted, flatten=True) or []
        return sorted(set(vertices), key=lambda item: int(re.search(r"\.vtx\[(\d+)\]$", item).group(1)) if re.search(r"\.vtx\[(\d+)\]$", item) else -1)

    def _counts():
        return {
            "vertices": int(cmds.polyEvaluate(object_name, vertex=True)),
            "edges": int(cmds.polyEvaluate(object_name, edge=True)),
            "faces": int(cmds.polyEvaluate(object_name, face=True)),
        }

    if not object_name:
        raise ValueError("object_name is required.")
    operation = operation.lower().strip()
    parameters = parameters or {}
    shape_name = _mesh_shape(object_name)
    prefix = _component_prefix(shape_name)
    before_counts = _counts()

    if operation == "select":
        resolved = _resolve_components()
        cmds.select(resolved, replace=True)
        return {
            "success": True,
            "object_name": object_name,
            "operation": operation,
            "selected_count": len(resolved),
            "selected_components_preview": resolved[:50],
            "counts_before": before_counts,
            "counts_after": _counts(),
        }

    if operation == "delete":
        resolved = _resolve_components()
        cmds.delete(resolved)
        return {
            "success": True,
            "object_name": object_name,
            "operation": operation,
            "deleted_count": len(resolved),
            "deleted_components_preview": resolved[:50],
            "counts_before": before_counts,
            "counts_after": _counts() if cmds.objExists(object_name) else None,
        }

    if operation == "merge_vertices":
        resolved = _resolve_components("vertex")
        vertices = _convert_to_vertices(resolved)
        if len(vertices) < 2:
            raise ValueError("merge_vertices requires at least two vertices.")
        distance = _validate_scalar(parameters.get("distance", 0.001), "distance")
        always_merge = bool(parameters.get("always_merge", False))
        construction_history = bool(parameters.get("construction_history", False))
        result = cmds.polyMergeVertex(
            vertices,
            distance=distance,
            alwaysMergeTwoVertices=always_merge,
            constructionHistory=construction_history,
        )
        return {
            "success": True,
            "object_name": object_name,
            "operation": operation,
            "input_vertex_count": len(vertices),
            "input_vertices_preview": vertices[:50],
            "node": result,
            "distance": distance,
            "always_merge": always_merge,
            "counts_before": before_counts,
            "counts_after": _counts(),
        }

    if operation in {"set_normals", "soften_edges", "harden_edges"}:
        if operation == "soften_edges":
            angle = 180.0
        elif operation == "harden_edges":
            angle = 0.0
        else:
            angle = _validate_scalar(parameters.get("angle", 30.0), "angle")
        construction_history = bool(parameters.get("construction_history", False))
        try:
            resolved = _resolve_components("edge")
        except ValueError:
            resolved = [object_name]
        result = cmds.polySoftEdge(resolved, angle=angle, constructionHistory=construction_history)
        return {
            "success": True,
            "object_name": object_name,
            "operation": operation,
            "angle": angle,
            "component_count": len(resolved),
            "components_preview": resolved[:50],
            "node": result,
            "counts_before": before_counts,
            "counts_after": _counts(),
        }

    if operation == "insert_support_loop":
        axis = str(parameters.get("axis", "y")).lower().strip()
        if axis not in {"x", "y", "z"}:
            raise ValueError("parameters.axis must be x, y, or z.")
        position = _validate_scalar(parameters.get("position", 0.0), "position")
        construction_history = bool(parameters.get("construction_history", False))
        delete_faces = bool(parameters.get("delete_faces", False))
        bbox = cmds.exactWorldBoundingBox(object_name)
        center = [
            (bbox[0] + bbox[3]) * 0.5,
            (bbox[1] + bbox[4]) * 0.5,
            (bbox[2] + bbox[5]) * 0.5,
        ]
        center[{"x": 0, "y": 1, "z": 2}[axis]] = position
        result = cmds.polyCut(
            object_name,
            constructionHistory=construction_history,
            cutPlaneCenter=center,
            cuttingDirection=axis,
            deleteFaces=delete_faces,
        )
        after_counts = _counts()
        if after_counts == before_counts:
            raise RuntimeError("insert_support_loop did not change mesh topology.")
        return {
            "success": True,
            "object_name": object_name,
            "operation": operation,
            "axis": axis,
            "position": position,
            "cut_plane_center": center,
            "node": result,
            "counts_before": before_counts,
            "counts_after": after_counts,
        }

    if operation == "insert_edge_loop":
        edges = _resolve_components("edge")
        if not any(".e[" in item for item in edges):
            raise ValueError("insert_edge_loop requires edge components.")
        divisions = int(parameters.get("divisions", 1))
        weight = _validate_scalar(parameters.get("weight", 0.5), "weight")
        smoothing_angle = _validate_scalar(parameters.get("smoothing_angle", 30.0), "smoothing_angle")
        construction_history = bool(parameters.get("construction_history", True))
        insert_with_edge_flow = bool(parameters.get("insert_with_edge_flow", False))
        nodes = []
        for edge in edges:
            try:
                node = cmds.polySplitRing(
                    edge,
                    constructionHistory=construction_history,
                    splitType=1,
                    divisions=divisions,
                    weight=weight,
                    smoothingAngle=smoothing_angle,
                    insertWithEdgeFlow=insert_with_edge_flow,
                )
            except TypeError:
                node = cmds.polySplitRing(
                    edge,
                    ch=construction_history,
                    splitType=1,
                    divisions=divisions,
                    weight=weight,
                    smoothingAngle=smoothing_angle,
                )
            nodes.append(node)
        after_counts = _counts()
        if after_counts == before_counts:
            raise RuntimeError(
                "insert_edge_loop did not change mesh topology. "
                "Use insert_support_loop with axis and position for a plane-based support cut."
            )
        return {
            "success": True,
            "object_name": object_name,
            "operation": operation,
            "edge_count": len(edges),
            "edges_preview": edges[:50],
            "divisions": divisions,
            "weight": weight,
            "nodes": nodes,
            "counts_before": before_counts,
            "counts_after": after_counts,
        }

    raise ValueError(
        "Unknown operation. Use select, delete, merge_vertices, set_normals, "
        "soften_edges, harden_edges, insert_support_loop, or insert_edge_loop."
    )
