from typing import Dict, List, Any


def set_mesh_vertex_positions(
    object_name: str,
    vertex_positions: List[Dict[str, Any]],
    coordinate_mask: List[bool] = None,
    space: str = "world",
    select_result: bool = True,
    max_preview: int = 20,
) -> Dict[str, Any]:
    """Set exact polygon mesh vertex positions.

    This is the direct coordinate-editing counterpart to transform tools. It
    supports the common Maya artist workflow of selecting specific points and
    typing precise coordinates, restoring a tested point snapshot, or applying
    an externally computed correction map one vertex at a time.

    vertex_positions entries support:
    - index: vertex id on object_name
    - component: a single vertex component such as mesh.vtx[12]
    - position: target [x, y, z] coordinate in the requested space

    Provide exactly one of index or component for each entry. coordinate_mask
    is an optional [x, y, z] boolean list; masked-off axes keep their existing
    coordinate. The tool only edits polygon vertex positions and does not
    modify topology, materials, UVs, or scene state beyond optional selection.
    """
    import re
    import maya.cmds as cmds
    import maya.api.OpenMaya as om

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return int(value)

    def _validate_bool(value, arg_name):
        if not isinstance(value, bool):
            raise ValueError(f"{arg_name} must be a boolean.")
        return value

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(item) for item in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(item) for item in values]

    def _validate_mask(values):
        if values is None:
            return [True, True, True]
        if not isinstance(values, list) or len(values) != 3 or not all(isinstance(item, bool) for item in values):
            raise ValueError("coordinate_mask must be a list of three booleans.")
        if not any(values):
            raise ValueError("coordinate_mask must enable at least one axis.")
        return list(values)

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

    def _mesh_fn(shape):
        selection = om.MSelectionList()
        selection.add(shape)
        return om.MFnMesh(selection.getDagPath(0))

    def _prefix(shape):
        parents = cmds.listRelatives(shape, parent=True, fullPath=False) or []
        return parents[0] if parents else object_name

    def _point_to_list(point):
        return [float(point.x), float(point.y), float(point.z)]

    def _component_to_vertex_id(component):
        if not isinstance(component, str) or not component:
            raise ValueError("component must be a non-empty string.")
        flattened = cmds.ls(component, flatten=True) or []
        if len(flattened) != 1:
            raise ValueError(f"component must resolve to exactly one vertex: {component}")
        match = re.search(r"\.vtx\[(\d+)\]$", flattened[0])
        if not match:
            raise ValueError(f"component must be a vertex component: {component}")
        return int(match.group(1))

    def _entry_vertex_id(entry, entry_index):
        has_index = "index" in entry and entry["index"] is not None
        has_component = "component" in entry and entry["component"] is not None
        if has_index == has_component:
            raise ValueError(f"vertex_positions[{entry_index}] must provide exactly one of index or component.")
        if has_index:
            return _validate_int(entry["index"], f"vertex_positions[{entry_index}].index", 0)
        return _component_to_vertex_id(entry["component"])

    if not object_name:
        raise ValueError("object_name is required.")
    if not isinstance(vertex_positions, list) or not vertex_positions:
        raise ValueError("vertex_positions must be a non-empty list.")
    clean_space = (space or "").lower().strip()
    if clean_space not in {"world", "object"}:
        raise ValueError("space must be world or object.")
    clean_select_result = _validate_bool(select_result, "select_result")
    clean_max_preview = _validate_int(max_preview, "max_preview", 0)
    clean_mask = _validate_mask(coordinate_mask)

    shape_name = _mesh_shape(object_name)
    mesh_fn = _mesh_fn(shape_name)
    prefix_name = _prefix(shape_name)
    om_space = om.MSpace.kWorld if clean_space == "world" else om.MSpace.kObject
    points = mesh_fn.getPoints(om_space)

    resolved_entries = []
    seen = set()
    for entry_index, entry in enumerate(vertex_positions):
        if not isinstance(entry, dict):
            raise ValueError(f"vertex_positions[{entry_index}] must be a dictionary.")
        vertex_id = _entry_vertex_id(entry, entry_index)
        if vertex_id >= mesh_fn.numVertices:
            raise ValueError(f"vertex index out of range: {vertex_id}")
        if vertex_id in seen:
            raise ValueError(f"duplicate vertex index in vertex_positions: {vertex_id}")
        seen.add(vertex_id)
        if "position" not in entry:
            raise ValueError(f"vertex_positions[{entry_index}].position is required.")
        target = _validate_vector(entry["position"], 3, f"vertex_positions[{entry_index}].position")
        resolved_entries.append({"entry_index": entry_index, "vertex_id": vertex_id, "target": target})

    edits = []
    for item in resolved_entries:
        vertex_id = item["vertex_id"]
        before = points[vertex_id]
        before_values = _point_to_list(before)
        target = item["target"]
        after_values = [
            target[index] if clean_mask[index] else before_values[index]
            for index in range(3)
        ]
        points[vertex_id] = om.MPoint(after_values[0], after_values[1], after_values[2])
        if len(edits) < clean_max_preview:
            edits.append(
                {
                    "entry_index": item["entry_index"],
                    "index": vertex_id,
                    "component": f"{prefix_name}.vtx[{vertex_id}]",
                    "before": before_values,
                    "target": target,
                    "after": after_values,
                }
            )

    mesh_fn.setPoints(points, om_space)
    try:
        mesh_fn.updateSurface()
    except Exception:
        pass

    edited_ids = [item["vertex_id"] for item in resolved_entries]
    if clean_select_result:
        cmds.select([f"{prefix_name}.vtx[{vertex_id}]" for vertex_id in edited_ids], replace=True)
    else:
        cmds.select(clear=True)

    return {
        "success": True,
        "object_name": object_name,
        "shape_name": shape_name,
        "space": clean_space,
        "coordinate_mask": clean_mask,
        "requested_vertex_count": len(vertex_positions),
        "edited_vertex_count": len(edited_ids),
        "select_result": clean_select_result,
        "edited_vertices_preview": edited_ids[:clean_max_preview],
        "edits_preview": edits,
        "preview_truncated": len(edited_ids) > clean_max_preview,
    }
