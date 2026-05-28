from typing import Dict, List, Any, Union


def insert_mesh_support_loop(
    object_name: str,
    component_type: str = "edge",
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    expand: str = "edge_ring",
    axis: str = None,
    target_value: float = None,
    offset: float = 0.0,
    position_mode: str = "centered",
    insert_with_edge_flow: bool = False,
    adjust_edge_flow: float = 0.0,
    construction_history: bool = False,
    space: str = "world",
    use_selection: bool = True,
    select_result: bool = True,
    result_type: str = "vertex",
    max_preview: int = 100,
) -> Dict[str, Any]:
    """Insert one support loop from seed edges and report the new components.

    Position modes:
    - centered: keep Maya's inserted loop at the default connected position
    - axis_value: move the new vertices to target_value along axis
    - axis_offset: add offset to the new vertices along axis

    This wraps Maya's component-level edge-ring connect operation for common
    artist modeling work: adding a support loop, immediately selecting the new
    loop, and optionally aligning it to a precise coordinate for lips, seams,
    shoulder breaks, panel borders, hard-surface bevel support, or gridded mesh
    cleanup.
    """
    import re
    import maya.cmds as cmds
    import maya.api.OpenMaya as om

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

    def _axis_index(axis_name):
        clean_axis = (axis_name or "").lower().strip()
        if clean_axis not in {"x", "y", "z"}:
            raise ValueError("axis must be x, y, or z.")
        return {"x": 0, "y": 1, "z": 2}[clean_axis]

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

    def _dag_path(shape):
        selection = om.MSelectionList()
        selection.add(shape)
        return selection.getDagPath(0)

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

    def _components_from_indices(kind):
        if indices is None:
            return []
        if not isinstance(indices, list) or not all(isinstance(index, int) and not isinstance(index, bool) for index in indices):
            raise ValueError("indices must be a list of integers.")
        return [f"{prefix_name}.{kind}[{index}]" for index in indices]

    def _selected_components():
        if not use_selection:
            return []
        selected = cmds.ls(selection=True, flatten=True) or []
        object_tokens = {object_name, prefix_name, shape_name}
        return [item for item in selected if item.split(".", 1)[0] in object_tokens]

    def _resolve_edges():
        clean_type = component_type.lower().strip()
        kind_map = {"vertex": "vtx", "edge": "e", "face": "f", "uv": "map", "vertex_face": "vtxFace"}
        if components is not None:
            resolved = _flatten(components)
        elif clean_type in kind_map and indices is not None:
            resolved = _components_from_indices(kind_map[clean_type])
        else:
            resolved = _selected_components()
        if not resolved:
            raise ValueError("No components resolved from components, indices, or current selection.")
        edges = cmds.polyListComponentConversion(resolved, toEdge=True) or []
        edges = cmds.ls(edges, flatten=True) or []
        if not edges:
            raise ValueError("Support loop insertion requires edge components or components convertible to edges.")
        return _unique(edges)

    def _unique(items):
        seen = set()
        result = []
        for item in cmds.ls(items, flatten=True) or []:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    def _component_ids(items, kind):
        pattern = re.compile(rf"\.{kind}\[(\d+)\]$")
        ids = []
        for item in cmds.ls(items, flatten=True) or []:
            match = pattern.search(item)
            if match:
                ids.append(int(match.group(1)))
        return list(dict.fromkeys(ids))

    def _expanded_edges(edge_items):
        clean_expand = expand.lower().strip()
        if clean_expand == "none":
            return edge_items
        flag_map = {
            "edge_ring": "edgeRing",
            "edge_loop": "edgeLoop",
            "edge_loop_or_border": "edgeLoopOrBorder",
            "edge_border": "edgeBorder",
        }
        if clean_expand not in flag_map:
            raise ValueError("expand must be none, edge_ring, edge_loop, edge_loop_or_border, or edge_border.")
        edge_ids = _component_ids(edge_items, "e")
        results = []
        for edge_id in edge_ids:
            output = cmds.polySelect(
                object_name,
                asSelectString=True,
                noSelection=True,
                **{flag_map[clean_expand]: int(edge_id)},
            ) or []
            results.extend(output)
        expanded = _unique(results)
        return expanded or edge_items

    def _counts():
        return {
            "vertices": int(cmds.polyEvaluate(object_name, vertex=True)),
            "edges": int(cmds.polyEvaluate(object_name, edge=True)),
            "faces": int(cmds.polyEvaluate(object_name, face=True)),
        }

    def _point_values(point):
        return [float(point.x), float(point.y), float(point.z)]

    def _set_new_vertex_positions(vertex_ids):
        if clean_position_mode == "centered":
            return []
        axis_idx = _axis_index(axis)
        points = mesh_fn.getPoints(om_space)
        before_after = []
        for vertex_id in vertex_ids:
            before = _point_values(points[vertex_id])
            after = before[:]
            if clean_position_mode == "axis_value":
                after[axis_idx] = clean_target_value
            else:
                after[axis_idx] += clean_offset
            points[vertex_id] = om.MPoint(after[0], after[1], after[2])
            before_after.append(
                {
                    "index": vertex_id,
                    "component": f"{prefix_name}.vtx[{vertex_id}]",
                    "before": before,
                    "after": after,
                }
            )
        mesh_fn.setPoints(points, om_space)
        try:
            mesh_fn.updateSurface()
        except Exception:
            pass
        return before_after

    def _components_from_range(kind, start, end):
        if end <= start:
            return []
        return [f"{prefix_name}.{kind}[{index}]" for index in range(start, end)]

    def _select_components(items):
        if items:
            cmds.select(items, replace=True)
        elif result_type.lower().strip() == "vertex":
            cmds.select(clear=True)

    if not object_name:
        raise ValueError("object_name is required.")
    clean_position_mode = position_mode.lower().strip()
    if clean_position_mode not in {"centered", "axis_value", "axis_offset"}:
        raise ValueError("position_mode must be centered, axis_value, or axis_offset.")
    if clean_position_mode in {"axis_value", "axis_offset"} and axis is None:
        raise ValueError("axis is required when position_mode is axis_value or axis_offset.")
    clean_target_value = _validate_scalar(target_value, "target_value") if clean_position_mode == "axis_value" else None
    clean_offset = _validate_scalar(offset, "offset")
    adjust_edge_flow = _validate_scalar(adjust_edge_flow, "adjust_edge_flow")
    max_preview = _validate_int(max_preview, "max_preview", 1)
    clean_result_type = result_type.lower().strip()
    if clean_result_type not in {"vertex", "edge", "face"}:
        raise ValueError("result_type must be vertex, edge, or face.")
    space = space.lower().strip()
    if space not in {"world", "object"}:
        raise ValueError("space must be world or object.")

    shape_name = _mesh_shape(object_name)
    prefix_name = _prefix(shape_name)
    dag_path = _dag_path(shape_name)
    mesh_fn = om.MFnMesh(dag_path)
    om_space = om.MSpace.kWorld if space == "world" else om.MSpace.kObject
    before = _counts()

    seed_edges = _resolve_edges()
    target_edges = _expanded_edges(seed_edges)
    if len(target_edges) < 2:
        raise ValueError("At least two resolved edges are required to insert a support loop.")

    old_selection = cmds.ls(selection=True, flatten=True) or []
    cmds.select(target_edges, replace=True)
    try:
        node = cmds.polyConnectComponents(
            constructionHistory=construction_history,
            insertWithEdgeFlow=bool(insert_with_edge_flow),
            adjustEdgeFlow=adjust_edge_flow,
        )
    finally:
        if old_selection:
            cmds.select(old_selection, replace=True)
        else:
            cmds.select(clear=True)

    after = _counts()
    if after["vertices"] <= before["vertices"] or after["edges"] <= before["edges"] or after["faces"] <= before["faces"]:
        raise RuntimeError("Support loop insertion did not change mesh topology.")

    new_vertex_ids = list(range(before["vertices"], after["vertices"]))
    new_vertices = _components_from_range("vtx", before["vertices"], after["vertices"])
    new_edges = _components_from_range("e", before["edges"], after["edges"])
    new_faces = _components_from_range("f", before["faces"], after["faces"])
    moved_records = _set_new_vertex_positions(new_vertex_ids)

    selection_items = {"vertex": new_vertices, "edge": new_edges, "face": new_faces}[clean_result_type]
    if select_result:
        _select_components(selection_items)

    return {
        "success": True,
        "object_name": object_name,
        "shape_name": shape_name,
        "operation": "insert_mesh_support_loop",
        "node": node,
        "component_type": component_type,
        "expand": expand.lower().strip(),
        "seed_edge_count": len(seed_edges),
        "target_edge_count": len(target_edges),
        "seed_edges_preview": seed_edges[:max_preview],
        "target_edges_preview": target_edges[:max_preview],
        "insert_with_edge_flow": bool(insert_with_edge_flow),
        "adjust_edge_flow": adjust_edge_flow,
        "position_mode": clean_position_mode,
        "axis": axis.lower().strip() if axis else None,
        "target_value": clean_target_value,
        "offset": clean_offset,
        "space": space,
        "counts_before": before,
        "counts_after": after,
        "new_vertex_count": len(new_vertices),
        "new_edge_count": len(new_edges),
        "new_face_count": len(new_faces),
        "new_vertices": new_vertices[:max_preview],
        "new_edges": new_edges[:max_preview],
        "new_faces": new_faces[:max_preview],
        "new_vertices_truncated": len(new_vertices) > max_preview,
        "new_edges_truncated": len(new_edges) > max_preview,
        "new_faces_truncated": len(new_faces) > max_preview,
        "position_changes": moved_records[:max_preview],
        "position_changes_truncated": len(moved_records) > max_preview,
        "selected": bool(select_result),
        "result_type": clean_result_type if select_result else None,
    }
