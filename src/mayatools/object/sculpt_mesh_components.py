from typing import Dict, List, Union


def sculpt_mesh_components(
    object_name: str,
    operation: str,
    component_type: str = "vertex",
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    iterations: int = 1,
    strength: float = 1.0,
    distance: float = 0.0,
    preserve_boundary: bool = True,
    space: str = "world",
    use_selection: bool = True,
    max_preview: int = 20,
) -> Dict[str, object]:
    """Locally smooth, relax, or inflate polygon mesh components.

    Operations:
    - average_vertices: move vertices toward the average of connected vertices
    - relax_vertices: move vertices tangentially toward connected averages,
      reducing irregular spacing while preserving local volume better
    - shrink_fatten_vertices: move vertices along their averaged vertex normals

    Components can be explicit, indexed, or taken from the current selection.
    Edges and faces are converted to vertices. This supports Maya-style local
    cleanup of uneven point spacing, soft sculpt-like surface relaxation, and
    small inflate/deflate adjustments without global procedural deformation.
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

    def _edge_adjacency_and_boundary():
        adjacency = {vertex_id: set() for vertex_id in range(mesh_fn.numVertices)}
        boundary_vertices = set()
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
                boundary_vertices.add(v0)
                boundary_vertices.add(v1)
            edge_it.next()
        return adjacency, boundary_vertices

    def _point_list(point):
        return [float(point.x), float(point.y), float(point.z)]

    def _distance(a, b):
        return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)

    def _average_point(points, neighbor_ids):
        center = om.MPoint()
        for neighbor_id in neighbor_ids:
            center += points[neighbor_id]
        return center / float(len(neighbor_ids))

    def _normal(vertex_id):
        normal = mesh_fn.getVertexNormal(vertex_id, True, om_space)
        vector = om.MVector(normal.x, normal.y, normal.z)
        if vector.length() <= 1e-9:
            return om.MVector(0.0, 1.0, 0.0)
        vector.normalize()
        return vector

    def _preview(vertex_ids, before_points, after_points):
        items = []
        for vertex_id in vertex_ids[:max_preview]:
            before = before_points[vertex_id]
            after = after_points[vertex_id]
            items.append({
                "index": vertex_id,
                "component": f"{prefix_name}.vtx[{vertex_id}]",
                "before": _point_list(before),
                "after": _point_list(after),
                "movement": _distance(before, after),
            })
        return items

    if not object_name:
        raise ValueError("object_name is required.")
    if not operation:
        raise ValueError("operation is required.")
    operation = operation.lower().strip()
    if operation not in {"average_vertices", "relax_vertices", "shrink_fatten_vertices"}:
        raise ValueError("operation must be average_vertices, relax_vertices, or shrink_fatten_vertices.")
    component_type = component_type.lower().strip()
    if component_type not in {"vertex", "edge", "face", "uv", "vertex_face"}:
        raise ValueError("component_type must be vertex, edge, face, uv, or vertex_face.")
    clean_iterations = _validate_int(iterations, "iterations", 1)
    clean_strength = _validate_scalar(strength, "strength")
    if clean_strength < 0.0:
        raise ValueError("strength must be greater than or equal to 0.")
    clean_distance = _validate_scalar(distance, "distance")
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
    vertex_ids = _vertex_ids_from_components(resolved_components)
    if not vertex_ids:
        raise ValueError("No vertices resolved from components, indices, or current selection.")

    adjacency, boundary_vertices = _edge_adjacency_and_boundary()
    points = mesh_fn.getPoints(om_space)
    before_points = {vertex_id: om.MPoint(points[vertex_id]) for vertex_id in vertex_ids}
    skipped = []

    if operation in {"average_vertices", "relax_vertices"}:
        for _ in range(clean_iterations):
            next_points = om.MPointArray(points)
            for vertex_id in vertex_ids:
                if preserve_boundary and vertex_id in boundary_vertices:
                    skipped.append({"index": vertex_id, "reason": "boundary"})
                    continue
                neighbors = sorted(adjacency.get(vertex_id, []))
                if not neighbors:
                    skipped.append({"index": vertex_id, "reason": "no_connected_vertices"})
                    continue
                average = _average_point(points, neighbors)
                displacement = om.MVector(average.x - points[vertex_id].x, average.y - points[vertex_id].y, average.z - points[vertex_id].z)
                if operation == "relax_vertices":
                    normal = _normal(vertex_id)
                    displacement = displacement - normal * (displacement * normal)
                next_points[vertex_id] = om.MPoint(
                    points[vertex_id].x + displacement.x * clean_strength,
                    points[vertex_id].y + displacement.y * clean_strength,
                    points[vertex_id].z + displacement.z * clean_strength,
                )
            points = next_points

    if operation == "shrink_fatten_vertices":
        for _ in range(clean_iterations):
            next_points = om.MPointArray(points)
            for vertex_id in vertex_ids:
                if preserve_boundary and vertex_id in boundary_vertices:
                    skipped.append({"index": vertex_id, "reason": "boundary"})
                    continue
                normal = _normal(vertex_id)
                offset = clean_distance * clean_strength
                next_points[vertex_id] = om.MPoint(
                    points[vertex_id].x + normal.x * offset,
                    points[vertex_id].y + normal.y * offset,
                    points[vertex_id].z + normal.z * offset,
                )
            points = next_points

    mesh_fn.setPoints(points, om_space)
    try:
        mesh_fn.updateSurface()
    except Exception:
        pass
    updated_points = mesh_fn.getPoints(om_space)
    after_points = {vertex_id: om.MPoint(updated_points[vertex_id]) for vertex_id in vertex_ids}
    movements = [_distance(before_points[vertex_id], after_points[vertex_id]) for vertex_id in vertex_ids]
    moved_count = sum(1 for movement in movements if movement > 1e-9)
    if moved_count == 0:
        raise RuntimeError(f"{operation} did not move any vertices.")
    cmds.select([f"{prefix_name}.vtx[{vertex_id}]" for vertex_id in vertex_ids], replace=True)

    return {
        "success": True,
        "object_name": object_name,
        "shape_name": shape_name,
        "operation": operation,
        "component_type": component_type,
        "space": space,
        "iterations": clean_iterations,
        "strength": clean_strength,
        "distance": clean_distance,
        "preserve_boundary": bool(preserve_boundary),
        "resolved_vertex_count": len(vertex_ids),
        "moved_vertex_count": moved_count,
        "skipped_count": len(skipped),
        "skipped_preview": skipped[:max_preview],
        "total_movement": float(sum(movements)),
        "max_movement": float(max(movements) if movements else 0.0),
        "preview": _preview(vertex_ids, before_points, after_points),
    }
