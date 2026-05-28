from typing import Dict, List, Any, Union


def slide_mesh_components(
    object_name: str,
    component_type: str = "vertex",
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    direction: str = "positive_axis",
    axis: str = "y",
    factor: float = 0.25,
    distance: float = None,
    target_point: List[float] = None,
    prefer_unselected_neighbors: bool = True,
    preserve_boundary: bool = False,
    space: str = "world",
    use_selection: bool = True,
    select_result: bool = True,
    max_preview: int = 50,
) -> Dict[str, Any]:
    """Slide resolved mesh vertices along their connected topology.

    Operations like Insert Edge Loop often create a centered loop. This tool
    moves the resolved vertices along neighboring mesh edges instead of through
    arbitrary world-space translation, which matches the common Maya artist
    workflow of sliding support loops, edge loops, or local vertex rows while
    keeping them on the existing surface flow.

    Directions:
    - positive_axis / negative_axis: choose the connected neighbor in the
      requested x, y, or z direction
    - toward_point / away_from_point: choose the connected neighbor closest to
      or farthest from target_point
    - closest_neighbor / farthest_neighbor: choose by edge length

    Edges, faces, UVs, and vertex-faces are converted to unique vertices before
    sliding. When prefer_unselected_neighbors is true, selected vertices slide
    toward neighbors outside the resolved set when possible, which is useful for
    moving a whole selected loop toward one side of its surrounding quad strip.
    """
    import math
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

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(item) for item in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(item) for item in values]

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

    def _mesh_fn(shape):
        return om.MFnMesh(_dag_path(shape))

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

    def _resolve_components():
        clean_type = component_type.lower().strip()
        kind_map = {
            "vertex": "vtx",
            "edge": "e",
            "face": "f",
            "uv": "map",
            "vertex_face": "vtxFace",
        }
        if components is not None:
            resolved = _flatten(components)
        elif clean_type in kind_map and indices is not None:
            resolved = _components_from_indices(kind_map[clean_type])
        else:
            resolved = _selected_components()
        if not resolved:
            raise ValueError("No components resolved from components, indices, or current selection.")
        return resolved

    def _vertex_ids_from_components(items):
        converted = cmds.polyListComponentConversion(items, toVertex=True) or []
        vertices = cmds.ls(converted, flatten=True) or []
        pattern = re.compile(r"\.vtx\[(\d+)\]$")
        ids = []
        for vertex in vertices:
            match = pattern.search(vertex)
            if match:
                ids.append(int(match.group(1)))
        return sorted(set(ids))

    def _point_values(point):
        return [float(point.x), float(point.y), float(point.z)]

    def _distance(a, b):
        return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)

    def _distance_to_values(point, values):
        return math.sqrt((point.x - values[0]) ** 2 + (point.y - values[1]) ** 2 + (point.z - values[2]) ** 2)

    def _adjacency_and_boundary():
        adjacency = {vertex_id: set() for vertex_id in range(mesh_fn.numVertices)}
        boundary = set()
        edge_it = om.MItMeshEdge(dag)
        while not edge_it.isDone():
            v0 = int(edge_it.vertexId(0))
            v1 = int(edge_it.vertexId(1))
            adjacency[v0].add(v1)
            adjacency[v1].add(v0)
            try:
                connected_faces = edge_it.getConnectedFaces()
            except Exception:
                connected_faces = []
            if len(connected_faces) < 2:
                boundary.add(v0)
                boundary.add(v1)
            edge_it.next()
        return adjacency, boundary

    def _candidate_neighbors(vertex_id):
        neighbors = sorted(adjacency.get(vertex_id, []))
        if prefer_unselected_neighbors:
            outside = [neighbor for neighbor in neighbors if neighbor not in seed_vertex_set]
            if outside:
                return outside
        return neighbors

    def _choose_neighbor(vertex_id, neighbor_ids, current_points):
        point = current_points[vertex_id]
        if clean_direction == "positive_axis":
            directional = [neighbor_id for neighbor_id in neighbor_ids if _point_values(current_points[neighbor_id])[axis_idx] > _point_values(point)[axis_idx] + 1.0e-10]
            if not directional:
                return None, "no_positive_axis_neighbor"
            return max(directional, key=lambda neighbor_id: _point_values(current_points[neighbor_id])[axis_idx]), None
        if clean_direction == "negative_axis":
            directional = [neighbor_id for neighbor_id in neighbor_ids if _point_values(current_points[neighbor_id])[axis_idx] < _point_values(point)[axis_idx] - 1.0e-10]
            if not directional:
                return None, "no_negative_axis_neighbor"
            return min(directional, key=lambda neighbor_id: _point_values(current_points[neighbor_id])[axis_idx]), None
        if clean_direction == "toward_point":
            return min(neighbor_ids, key=lambda neighbor_id: _distance_to_values(current_points[neighbor_id], clean_target_point)), None
        if clean_direction == "away_from_point":
            return max(neighbor_ids, key=lambda neighbor_id: _distance_to_values(current_points[neighbor_id], clean_target_point)), None
        if clean_direction == "closest_neighbor":
            return min(neighbor_ids, key=lambda neighbor_id: _distance(point, current_points[neighbor_id])), None
        if clean_direction == "farthest_neighbor":
            return max(neighbor_ids, key=lambda neighbor_id: _distance(point, current_points[neighbor_id])), None
        raise ValueError("Unsupported direction.")

    def _slide_point(source, target):
        vector = om.MVector(target.x - source.x, target.y - source.y, target.z - source.z)
        length = vector.length()
        if length <= 1.0e-12:
            return om.MPoint(source), 0.0
        if clean_distance is None:
            amount = clean_factor
        else:
            amount = min(1.0, clean_distance / length)
        return om.MPoint(
            source.x + vector.x * amount,
            source.y + vector.y * amount,
            source.z + vector.z * amount,
        ), amount

    def _preview(vertex_ids, before_points, after_points, records):
        items = []
        for vertex_id in vertex_ids[:max_preview]:
            before = before_points[vertex_id]
            after = after_points[vertex_id]
            record = records.get(vertex_id, {})
            items.append(
                {
                    "index": vertex_id,
                    "component": f"{prefix_name}.vtx[{vertex_id}]",
                    "before": _point_values(before),
                    "after": _point_values(after),
                    "movement": _distance(before, after),
                    "chosen_neighbor": record.get("chosen_neighbor"),
                    "slide_amount": record.get("slide_amount"),
                }
            )
        return items

    if not object_name:
        raise ValueError("object_name is required.")
    component_type = component_type.lower().strip()
    if component_type not in {"vertex", "edge", "face", "uv", "vertex_face"}:
        raise ValueError("component_type must be vertex, edge, face, uv, or vertex_face.")
    clean_direction = direction.lower().strip()
    if clean_direction not in {"positive_axis", "negative_axis", "toward_point", "away_from_point", "closest_neighbor", "farthest_neighbor"}:
        raise ValueError("direction must be positive_axis, negative_axis, toward_point, away_from_point, closest_neighbor, or farthest_neighbor.")
    axis_idx = _axis_index(axis)
    clean_factor = _validate_scalar(factor, "factor")
    if clean_factor < 0.0 or clean_factor > 1.0:
        raise ValueError("factor must be between 0 and 1.")
    clean_distance = None if distance is None else _validate_scalar(distance, "distance")
    if clean_distance is not None and clean_distance < 0.0:
        raise ValueError("distance must be greater than or equal to zero.")
    if clean_direction in {"toward_point", "away_from_point"}:
        clean_target_point = _validate_vector(target_point, 3, "target_point")
    else:
        clean_target_point = None
    space = space.lower().strip()
    if space not in {"world", "object"}:
        raise ValueError("space must be world or object.")
    max_preview = _validate_int(max_preview, "max_preview", 0)

    shape_name = _mesh_shape(object_name)
    dag = _dag_path(shape_name)
    mesh_fn = _mesh_fn(shape_name)
    prefix_name = _prefix(shape_name)
    om_space = om.MSpace.kWorld if space == "world" else om.MSpace.kObject

    resolved_components = _resolve_components()
    seed_vertex_ids = _vertex_ids_from_components(resolved_components)
    if not seed_vertex_ids:
        raise ValueError("No vertices resolved from components, indices, or current selection.")
    seed_vertex_set = set(seed_vertex_ids)

    adjacency, boundary_vertices = _adjacency_and_boundary()
    points = mesh_fn.getPoints(om_space)
    before_points = {vertex_id: om.MPoint(points[vertex_id]) for vertex_id in seed_vertex_ids}
    next_points = om.MPointArray(points)
    skipped = []
    records = {}

    for vertex_id in seed_vertex_ids:
        if preserve_boundary and vertex_id in boundary_vertices:
            skipped.append({"index": vertex_id, "reason": "boundary"})
            continue
        neighbor_ids = _candidate_neighbors(vertex_id)
        if not neighbor_ids:
            skipped.append({"index": vertex_id, "reason": "no_connected_neighbors"})
            continue
        chosen_neighbor, reason = _choose_neighbor(vertex_id, neighbor_ids, points)
        if chosen_neighbor is None:
            skipped.append({"index": vertex_id, "reason": reason})
            continue
        target_point = points[chosen_neighbor]
        new_point, amount = _slide_point(points[vertex_id], target_point)
        next_points[vertex_id] = new_point
        records[vertex_id] = {
            "chosen_neighbor": int(chosen_neighbor),
            "slide_amount": float(amount),
        }

    mesh_fn.setPoints(next_points, om_space)
    try:
        mesh_fn.updateSurface()
    except Exception:
        pass

    updated_points = mesh_fn.getPoints(om_space)
    moved_ids = [
        vertex_id
        for vertex_id in seed_vertex_ids
        if _distance(before_points[vertex_id], updated_points[vertex_id]) > 1.0e-9
    ]
    if not moved_ids:
        raise RuntimeError(f"{clean_direction} slide did not move any vertices.")

    if select_result:
        cmds.select([f"{prefix_name}.vtx[{vertex_id}]" for vertex_id in seed_vertex_ids], replace=True)

    return {
        "success": True,
        "object_name": object_name,
        "shape_name": shape_name,
        "component_type": component_type,
        "space": space,
        "direction": clean_direction,
        "axis": axis.lower().strip(),
        "factor": clean_factor,
        "distance": clean_distance,
        "target_point": clean_target_point,
        "prefer_unselected_neighbors": bool(prefer_unselected_neighbors),
        "preserve_boundary": bool(preserve_boundary),
        "resolved_vertex_count": len(seed_vertex_ids),
        "moved_vertex_count": len(moved_ids),
        "skipped_count": len(skipped),
        "resolved_vertices_preview": seed_vertex_ids[:max_preview],
        "moved_vertices_preview": moved_ids[:max_preview],
        "skipped_preview": skipped[:max_preview],
        "preview": _preview(seed_vertex_ids, before_points, updated_points, records),
    }
