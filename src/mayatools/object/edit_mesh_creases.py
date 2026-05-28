from typing import Dict, List, Any, Union


def edit_mesh_creases(
    object_name: str,
    operation: str = "query",
    component_type: str = None,
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    value: float = 2.0,
    include_zero: bool = False,
    use_selection: bool = True,
    max_preview: int = 100,
) -> Dict[str, Any]:
    """Query and edit polygon subdivision crease weights.

    Operations:
    - query: report crease values for selected, indexed, or nonzero mesh creases
    - set_edge_creases: set selected/resolved edge crease values
    - set_vertex_creases: set selected/resolved vertex crease values
    - clear_creases: set selected/resolved edge and vertex crease values to zero

    Creases control subdivision sharpness and are separate from soft/hard
    normals. Use this for Maya-style local hard-surface control when extra
    support geometry is unnecessary or too heavy.
    """
    import re
    import maya.cmds as cmds

    def _is_number(item):
        return isinstance(item, (int, float)) and not isinstance(item, bool)

    def _validate_scalar(item, arg_name):
        if not _is_number(item):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(item)

    def _validate_int(item, arg_name, minimum):
        if not isinstance(item, int) or isinstance(item, bool) or item < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return int(item)

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

    def _flatten(item):
        if item is None:
            return []
        if isinstance(item, str):
            item = [item]
        if not isinstance(item, list) or not all(isinstance(entry, str) for entry in item):
            raise ValueError("components must be a string, a list of strings, or None.")
        return cmds.ls(item, flatten=True) or []

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

    def _resolve_components(default_type=None, allow_empty=False):
        clean_type = (component_type or default_type or "").lower().strip()
        kind_map = {"vertex": "vtx", "edge": "e", "face": "f", "uv": "map", "vertex_face": "vtxFace"}
        if components is not None:
            resolved = _flatten(components)
        elif clean_type in kind_map and indices is not None:
            resolved = _components_from_indices(kind_map[clean_type])
        else:
            resolved = _selected_components()
        if not resolved and not allow_empty:
            raise ValueError("No components resolved from components, indices, or current selection.")
        return resolved

    def _unique(items):
        seen = set()
        result = []
        for item in cmds.ls(items, flatten=True) or []:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    def _convert(items, target):
        flags = {
            "edge": {"toEdge": True},
            "vertex": {"toVertex": True},
        }[target]
        return _unique(cmds.polyListComponentConversion(items, **flags) or [])

    def _component_ids(items, kind):
        pattern = re.compile(rf"\.{kind}\[(\d+)\]$")
        ids = []
        for item in cmds.ls(items, flatten=True) or []:
            match = pattern.search(item)
            if match:
                ids.append(int(match.group(1)))
        return list(dict.fromkeys(ids))

    def _all_components(kind):
        count_flag = "edge" if kind == "e" else "vertex"
        total = int(cmds.polyEvaluate(object_name, **{count_flag: True}))
        return [f"{prefix_name}.{kind}[{index}]" for index in range(total)]

    def _query_edges(edge_items):
        records = []
        for component in _unique(edge_items):
            values = cmds.polyCrease(component, query=True, value=True) or []
            crease_value = float(values[0]) if values else 0.0
            if crease_value < 0.0:
                crease_value = 0.0
            if include_zero or abs(crease_value) > 1.0e-9:
                edge_id = _component_ids([component], "e")
                records.append({"component": component, "index": edge_id[0] if edge_id else None, "value": crease_value})
        return records

    def _query_vertices(vertex_items):
        records = []
        for component in _unique(vertex_items):
            values = cmds.polyCrease(component, query=True, vertexValue=True) or []
            crease_value = float(values[0]) if values else 0.0
            if crease_value < 0.0:
                crease_value = 0.0
            if include_zero or abs(crease_value) > 1.0e-9:
                vertex_id = _component_ids([component], "vtx")
                records.append({"component": component, "index": vertex_id[0] if vertex_id else None, "value": crease_value})
        return records

    def _query_payload(edge_items, vertex_items):
        edge_records = _query_edges(edge_items)
        vertex_records = _query_vertices(vertex_items)
        return {
            "edge_count": len(edge_records),
            "vertex_count": len(vertex_records),
            "edges": edge_records[:max_preview],
            "vertices": vertex_records[:max_preview],
            "truncated_edges": len(edge_records) > max_preview,
            "truncated_vertices": len(vertex_records) > max_preview,
        }

    def _resolved_edges_and_vertices(allow_empty=False):
        resolved = _resolve_components(allow_empty=allow_empty)
        if not resolved:
            return [], [], resolved
        clean_type = (component_type or "").lower().strip()
        if clean_type == "vertex":
            return [], _convert(resolved, "vertex"), resolved
        if clean_type == "edge":
            return _convert(resolved, "edge"), [], resolved
        if clean_type == "face":
            return _convert(resolved, "edge"), _convert(resolved, "vertex"), resolved
        edges = _convert(resolved, "edge")
        vertices = _convert(resolved, "vertex")
        return edges, vertices, resolved

    def _counts():
        return {
            "vertices": int(cmds.polyEvaluate(object_name, vertex=True)),
            "edges": int(cmds.polyEvaluate(object_name, edge=True)),
            "faces": int(cmds.polyEvaluate(object_name, face=True)),
        }

    if not object_name:
        raise ValueError("object_name is required.")
    operation = operation.lower().strip()
    allowed = {"query", "set_edge_creases", "set_vertex_creases", "clear_creases"}
    if operation not in allowed:
        raise ValueError(f"operation must be one of: {', '.join(sorted(allowed))}.")

    clean_value = _validate_scalar(value, "value")
    if clean_value < 0.0:
        raise ValueError("value must be greater than or equal to zero.")
    max_preview = _validate_int(max_preview, "max_preview", 0)
    shape_name = _mesh_shape(object_name)
    prefix_name = _prefix(shape_name)
    counts = _counts()

    if operation == "query":
        edge_targets, vertex_targets, resolved = _resolved_edges_and_vertices(allow_empty=True)
        if not resolved:
            edge_targets = _all_components("e")
            vertex_targets = _all_components("vtx")
        return {
            "success": True,
            "object_name": object_name,
            "operation": operation,
            "component_count": len(resolved),
            "components_preview": resolved[:max_preview],
            "include_zero": bool(include_zero),
            "counts": counts,
            "query": _query_payload(edge_targets, vertex_targets),
        }

    if operation == "set_edge_creases":
        resolved = _resolve_components("edge")
        edge_targets = _convert(resolved, "edge")
        if not edge_targets:
            raise ValueError("set_edge_creases requires edge components.")
        before = _query_payload(edge_targets, [])
        cmds.polyCrease(edge_targets, value=clean_value)
        return {
            "success": True,
            "object_name": object_name,
            "operation": operation,
            "value": clean_value,
            "component_count": len(edge_targets),
            "components_preview": edge_targets[:max_preview],
            "counts": counts,
            "query_before": before,
            "query_after": _query_payload(edge_targets, []),
        }

    if operation == "set_vertex_creases":
        resolved = _resolve_components("vertex")
        vertex_targets = _convert(resolved, "vertex")
        if not vertex_targets:
            raise ValueError("set_vertex_creases requires vertex components.")
        before = _query_payload([], vertex_targets)
        cmds.polyCrease(vertex_targets, vertexValue=clean_value)
        return {
            "success": True,
            "object_name": object_name,
            "operation": operation,
            "value": clean_value,
            "component_count": len(vertex_targets),
            "components_preview": vertex_targets[:max_preview],
            "counts": counts,
            "query_before": before,
            "query_after": _query_payload([], vertex_targets),
        }

    if operation == "clear_creases":
        edge_targets, vertex_targets, resolved = _resolved_edges_and_vertices()
        if not edge_targets and not vertex_targets:
            raise ValueError("clear_creases requires edge, vertex, face, or mixed components.")
        before = _query_payload(edge_targets, vertex_targets)
        if edge_targets:
            cmds.polyCrease(edge_targets, value=0.0)
        if vertex_targets:
            cmds.polyCrease(vertex_targets, vertexValue=0.0)
        return {
            "success": True,
            "object_name": object_name,
            "operation": operation,
            "component_count": len(resolved),
            "components_preview": resolved[:max_preview],
            "cleared_edge_count": len(edge_targets),
            "cleared_vertex_count": len(vertex_targets),
            "counts": counts,
            "query_before": before,
            "query_after": _query_payload(edge_targets, vertex_targets),
        }

    raise ValueError(f"Unsupported operation: {operation}")
