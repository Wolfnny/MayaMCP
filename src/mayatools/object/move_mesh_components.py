from typing import Dict, List, Any, Union


def move_mesh_components(
    object_name: str,
    component_type: str = "vertex",
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    mode: str = "offset",
    vector: List[float] = None,
    positions_by_vertex: Dict[str, List[float]] = None,
    space: str = "world",
    along_normal_distance: float = None,
    use_selection: bool = True,
    max_preview: int = 20,
) -> Dict[str, Any]:
    """Move or set polygon mesh components at vertex level.

    Vertices can be edited directly, while selected edges and faces are first
    converted to their unique vertices. mode="offset" adds vector and/or normal
    distance to each resolved vertex. mode="set" assigns explicit coordinates
    from positions_by_vertex, keyed by vertex index. This supports Maya-style
    localized point/edge/face alignment without global deformation.
    """
    import re
    import maya.cmds as cmds
    import maya.api.OpenMaya as om

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(value) for value in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(value) for value in values]

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

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

    def _mesh_fn(shape):
        selection = om.MSelectionList()
        selection.add(shape)
        return om.MFnMesh(selection.getDagPath(0))

    def _component_prefix():
        parents = cmds.listRelatives(shape_name, parent=True, fullPath=False) or []
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
        if not selected:
            return []
        object_tokens = {object_name, prefix, shape_name}
        filtered = []
        for item in selected:
            item_object = item.split(".", 1)[0]
            if item_object in object_tokens:
                filtered.append(item)
        return filtered

    def _vertex_indices_from_components(source_components):
        if not source_components:
            return []
        if component_type == "vertex":
            vertex_components = source_components
        else:
            vertex_components = cmds.polyListComponentConversion(source_components, toVertex=True) or []
            vertex_components = cmds.ls(vertex_components, flatten=True) or []
        vertex_ids = []
        pattern = re.compile(r"\.vtx\[(\d+)\]$")
        for component in vertex_components:
            match = pattern.search(component)
            if match:
                vertex_ids.append(int(match.group(1)))
        return sorted(set(vertex_ids))

    def _point_preview(vertex_id, point):
        return {"index": vertex_id, "position": [float(point.x), float(point.y), float(point.z)]}

    if not object_name:
        raise ValueError("object_name is required.")
    component_type = component_type.lower().strip()
    if component_type not in {"vertex", "edge", "face"}:
        raise ValueError("component_type must be vertex, edge, or face.")
    mode = mode.lower().strip()
    if mode not in {"offset", "set"}:
        raise ValueError("mode must be offset or set.")
    space = space.lower().strip()
    if space not in {"world", "object"}:
        raise ValueError("space must be world or object.")
    max_preview = _validate_int(max_preview, "max_preview", 0)

    shape_name = _mesh_shape(object_name)
    mesh_fn = _mesh_fn(shape_name)
    prefix = _component_prefix()
    om_space = om.MSpace.kWorld if space == "world" else om.MSpace.kObject

    kind = {"vertex": "vtx", "edge": "e", "face": "f"}[component_type]
    source_components = _flatten(components) or _components_from_indices(kind) or _selected_components()
    vertex_ids = _vertex_indices_from_components(source_components)
    if not vertex_ids:
        raise ValueError("No vertices resolved from components, indices, or current selection.")

    points = mesh_fn.getPoints(om_space)
    before_preview = [_point_preview(vertex_id, points[vertex_id]) for vertex_id in vertex_ids[:max_preview]]

    move_vector = None
    if vector is not None:
        move_vector = _validate_vector(vector, 3, "vector")
    normal_distance = None
    if along_normal_distance is not None:
        normal_distance = _validate_scalar(along_normal_distance, "along_normal_distance")

    if mode == "offset":
        if move_vector is None and normal_distance is None:
            raise ValueError("mode=offset requires vector and/or along_normal_distance.")
        for vertex_id in vertex_ids:
            delta = [0.0, 0.0, 0.0]
            if move_vector is not None:
                delta[0] += move_vector[0]
                delta[1] += move_vector[1]
                delta[2] += move_vector[2]
            if normal_distance is not None:
                normal = mesh_fn.getVertexNormal(vertex_id, True, om_space)
                delta[0] += normal.x * normal_distance
                delta[1] += normal.y * normal_distance
                delta[2] += normal.z * normal_distance
            point = points[vertex_id]
            points[vertex_id] = om.MPoint(point.x + delta[0], point.y + delta[1], point.z + delta[2])
    else:
        if not isinstance(positions_by_vertex, dict) or not positions_by_vertex:
            raise ValueError("mode=set requires positions_by_vertex keyed by vertex index.")
        for key, value in positions_by_vertex.items():
            vertex_id = int(key)
            if vertex_id not in vertex_ids:
                continue
            position = _validate_vector(value, 3, f"positions_by_vertex[{key}]")
            points[vertex_id] = om.MPoint(position[0], position[1], position[2])

    mesh_fn.setPoints(points, om_space)
    try:
        mesh_fn.updateSurface()
    except Exception:
        pass
    cmds.select([f"{prefix}.vtx[{vertex_id}]" for vertex_id in vertex_ids], replace=True)

    updated_points = mesh_fn.getPoints(om_space)
    after_preview = [_point_preview(vertex_id, updated_points[vertex_id]) for vertex_id in vertex_ids[:max_preview]]
    return {
        "success": True,
        "object_name": object_name,
        "shape_name": shape_name,
        "component_type": component_type,
        "mode": mode,
        "space": space,
        "resolved_vertex_count": len(vertex_ids),
        "resolved_vertices_preview": vertex_ids[:max_preview],
        "before_preview": before_preview,
        "after_preview": after_preview,
    }
