from typing import Dict, List, Any, Union


def soft_transform_mesh_components(
    object_name: str,
    operation: str = "translate",
    component_type: str = "vertex",
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    vector: List[float] = None,
    scale: List[float] = None,
    rotation: List[float] = None,
    axis: str = None,
    value: float = None,
    offset: float = 0.0,
    pivot: List[float] = None,
    pivot_mode: str = "selection_center",
    center: List[float] = None,
    center_mode: str = "origin",
    radius_mode: str = "explicit",
    falloff_radius: float = 1.0,
    falloff_mode: str = "distance",
    topology_depth: int = 3,
    falloff_curve: str = "smooth",
    strength: float = 1.0,
    affect_all_vertices: bool = True,
    preserve_boundary: bool = False,
    space: str = "world",
    use_selection: bool = True,
    select_result: bool = True,
    max_preview: int = 50,
) -> Dict[str, Any]:
    """Apply soft-selection style transforms around resolved mesh components.

    Operations:
    - translate: move vertices by vector scaled by falloff weight
    - scale: scale vertices around a pivot with falloff
    - rotate: rotate vertices around a pivot with falloff
    - align_axis: move vertices toward one x, y, or z value with falloff
    - align_radial: move vertices toward a cylinder radius around an axis
    - radial_offset: add a radial offset around an axis

    Seed components can be explicit, indexed, or current selection. Edges,
    faces, UVs, and vertex-faces are converted to seed vertices. When
    affect_all_vertices is true, nearby mesh vertices are included according to
    falloff_radius. Set falloff_mode="topology" to include connected vertex
    rings by topology_depth instead of world-space distance, matching Maya's
    soft selection workflow for hand shaping shoulders, waists, lips, dents,
    and other local form changes without hard ring artifacts.
    """
    import math
    import re
    import maya.cmds as cmds
    import maya.api.OpenMaya as om

    def _is_number(value_to_check):
        return isinstance(value_to_check, (int, float)) and not isinstance(value_to_check, bool)

    def _validate_scalar(value_to_check, arg_name):
        if not _is_number(value_to_check):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value_to_check)

    def _validate_int(value_to_check, arg_name, minimum):
        if not isinstance(value_to_check, int) or isinstance(value_to_check, bool) or value_to_check < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return int(value_to_check)

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

    def _flatten(value_to_flatten):
        if value_to_flatten is None:
            return []
        if isinstance(value_to_flatten, str):
            value_to_flatten = [value_to_flatten]
        if not isinstance(value_to_flatten, list) or not all(isinstance(item, str) for item in value_to_flatten):
            raise ValueError("components must be a string, a list of strings, or None.")
        return cmds.ls(value_to_flatten, flatten=True) or []

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

    def _point_from_values(values):
        return om.MPoint(float(values[0]), float(values[1]), float(values[2]))

    def _distance(a, b):
        return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)

    def _bounds(vertex_ids_to_check, current_points):
        mins = [float("inf"), float("inf"), float("inf")]
        maxs = [float("-inf"), float("-inf"), float("-inf")]
        for vertex_id in vertex_ids_to_check:
            values = _point_values(current_points[vertex_id])
            for index in range(3):
                mins[index] = min(mins[index], values[index])
                maxs[index] = max(maxs[index], values[index])
        center_value = [(mins[index] + maxs[index]) * 0.5 for index in range(3)]
        return mins, maxs, center_value

    def _boundary_vertices():
        if not preserve_boundary:
            return set()
        boundary = set()
        edge_it = om.MItMeshEdge(dag)
        while not edge_it.isDone():
            try:
                connected_faces = edge_it.getConnectedFaces()
            except Exception:
                connected_faces = []
            if len(connected_faces) < 2:
                boundary.add(int(edge_it.vertexId(0)))
                boundary.add(int(edge_it.vertexId(1)))
            edge_it.next()
        return boundary

    def _edge_adjacency():
        adjacency = {vertex_id: set() for vertex_id in range(mesh_fn.numVertices)}
        edge_it = om.MItMeshEdge(dag)
        while not edge_it.isDone():
            vertex_a = int(edge_it.vertexId(0))
            vertex_b = int(edge_it.vertexId(1))
            adjacency[vertex_a].add(vertex_b)
            adjacency[vertex_b].add(vertex_a)
            edge_it.next()
        return adjacency

    def _falloff_weight(distance, radius):
        if distance <= 1.0e-9:
            return clean_strength
        if radius <= 1.0e-9 or distance > radius:
            return 0.0
        t = max(0.0, min(1.0, distance / radius))
        if clean_falloff_curve == "linear":
            weight = 1.0 - t
        elif clean_falloff_curve == "gaussian":
            weight = math.exp(-4.0 * t * t)
        elif clean_falloff_curve == "hard":
            weight = 1.0
        else:
            weight = 1.0 - (t * t * (3.0 - 2.0 * t))
        return weight * clean_strength

    def _distance_candidate_weights(current_points):
        candidates = list(range(mesh_fn.numVertices)) if affect_all_vertices else seed_vertex_ids[:]
        seed_points = [current_points[vertex_id] for vertex_id in seed_vertex_ids]
        weights = {}
        for vertex_id in candidates:
            if vertex_id in boundary_vertices:
                continue
            point = current_points[vertex_id]
            minimum_distance = min(_distance(point, seed_point) for seed_point in seed_points)
            weight = _falloff_weight(minimum_distance, clean_falloff_radius)
            if weight > 1.0e-9:
                weights[vertex_id] = {
                    "weight": weight,
                    "distance": float(minimum_distance),
                }
        return weights

    def _topology_candidate_weights():
        if not affect_all_vertices:
            candidates = {vertex_id: 0 for vertex_id in seed_vertex_ids}
        else:
            adjacency = _edge_adjacency()
            candidates = {}
            frontier = list(seed_vertex_ids)
            for vertex_id in frontier:
                candidates[vertex_id] = 0
            depth = 0
            while frontier and depth < clean_topology_depth:
                next_frontier = []
                next_depth = depth + 1
                for vertex_id in frontier:
                    for neighbor_id in adjacency.get(vertex_id, []):
                        if neighbor_id in candidates:
                            continue
                        candidates[neighbor_id] = next_depth
                        next_frontier.append(neighbor_id)
                frontier = next_frontier
                depth = next_depth
        weights = {}
        topology_radius = float(clean_topology_depth + 1)
        for vertex_id, depth in candidates.items():
            if vertex_id in boundary_vertices:
                continue
            weight = _falloff_weight(float(depth), topology_radius)
            if weight > 1.0e-9:
                weights[vertex_id] = {
                    "weight": weight,
                    "distance": float(depth),
                }
        return weights

    def _candidate_weights(current_points):
        if clean_falloff_mode == "topology":
            return _topology_candidate_weights()
        return _distance_candidate_weights(current_points)

    def _pivot(current_points):
        if pivot is not None:
            return _validate_vector(pivot, 3, "pivot")
        mode = pivot_mode.lower().strip()
        if mode == "origin":
            return [0.0, 0.0, 0.0]
        if mode == "selection_center":
            return selection_center[:]
        if mode == "object_center":
            return object_center[:]
        if mode == "selection_min":
            return selection_min[:]
        if mode == "selection_max":
            return selection_max[:]
        if mode == "object_min":
            return object_min[:]
        if mode == "object_max":
            return object_max[:]
        raise ValueError("pivot_mode must be origin, selection_center, selection_min, selection_max, object_center, object_min, or object_max.")

    def _center(current_points):
        if center is not None:
            return _validate_vector(center, 3, "center")
        mode = center_mode.lower().strip()
        if mode == "origin":
            return [0.0, 0.0, 0.0]
        if mode == "selection_center":
            return selection_center[:]
        if mode == "object_center":
            return object_center[:]
        raise ValueError("center_mode must be origin, selection_center, or object_center.")

    def _target_radius(current_points, center_value, axis_idx):
        mode = radius_mode.lower().strip()
        radial_axes = [index for index in range(3) if index != axis_idx]
        radii = []
        for vertex_id in seed_vertex_ids:
            values = _point_values(current_points[vertex_id])
            da = values[radial_axes[0]] - center_value[radial_axes[0]]
            db = values[radial_axes[1]] - center_value[radial_axes[1]]
            radii.append(math.sqrt(da * da + db * db))
        if mode == "explicit":
            radius = _validate_scalar(value, "value")
        elif mode == "selection_min":
            radius = min(radii)
        elif mode == "selection_max":
            radius = max(radii)
        elif mode in {"selection_mean", "selection_center"}:
            radius = sum(radii) / float(len(radii))
        elif mode == "selection_median":
            ordered = sorted(radii)
            mid = len(ordered) // 2
            radius = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) * 0.5
        else:
            raise ValueError("radius_mode must be explicit, selection_min, selection_max, selection_mean, selection_center, or selection_median.")
        if radius < 0.0:
            raise ValueError("target radius must be greater than or equal to zero.")
        return radius

    def _rotate_point(point, pivot_value, rotation_value):
        rx, ry, rz = [math.radians(item) for item in rotation_value]
        x = point.x - pivot_value[0]
        y = point.y - pivot_value[1]
        z = point.z - pivot_value[2]

        cos_x, sin_x = math.cos(rx), math.sin(rx)
        y, z = y * cos_x - z * sin_x, y * sin_x + z * cos_x

        cos_y, sin_y = math.cos(ry), math.sin(ry)
        x, z = x * cos_y + z * sin_y, -x * sin_y + z * cos_y

        cos_z, sin_z = math.cos(rz), math.sin(rz)
        x, y = x * cos_z - y * sin_z, x * sin_z + y * cos_z

        return om.MPoint(x + pivot_value[0], y + pivot_value[1], z + pivot_value[2])

    def _lerp_point(source, target, weight):
        return om.MPoint(
            source.x + (target.x - source.x) * weight,
            source.y + (target.y - source.y) * weight,
            source.z + (target.z - source.z) * weight,
        )

    def _preview(vertex_ids_to_preview, before_points, after_points, weights):
        items = []
        for vertex_id in vertex_ids_to_preview[:max_preview]:
            before = before_points[vertex_id]
            after = after_points[vertex_id]
            weight_record = weights.get(vertex_id, {"weight": 0.0, "distance": None})
            items.append(
                {
                    "index": vertex_id,
                    "component": f"{prefix_name}.vtx[{vertex_id}]",
                    "before": _point_values(before),
                    "after": _point_values(after),
                    "weight": float(weight_record["weight"]),
                    "distance_to_seed": weight_record["distance"],
                    "movement": _distance(before, after),
                }
            )
        return items

    if not object_name:
        raise ValueError("object_name is required.")
    operation = operation.lower().strip()
    allowed = {"translate", "scale", "rotate", "align_axis", "align_radial", "radial_offset"}
    if operation not in allowed:
        raise ValueError(f"operation must be one of: {', '.join(sorted(allowed))}.")
    component_type = component_type.lower().strip()
    if component_type not in {"vertex", "edge", "face", "uv", "vertex_face"}:
        raise ValueError("component_type must be vertex, edge, face, uv, or vertex_face.")
    space = space.lower().strip()
    if space not in {"world", "object"}:
        raise ValueError("space must be world or object.")
    clean_falloff_radius = _validate_scalar(falloff_radius, "falloff_radius")
    if clean_falloff_radius < 0.0:
        raise ValueError("falloff_radius must be greater than or equal to zero.")
    clean_falloff_mode = (falloff_mode or "").lower().strip()
    if clean_falloff_mode not in {"distance", "topology"}:
        raise ValueError("falloff_mode must be distance or topology.")
    clean_topology_depth = _validate_int(topology_depth, "topology_depth", 0)
    clean_strength = _validate_scalar(strength, "strength")
    if clean_strength < 0.0 or clean_strength > 1.0:
        raise ValueError("strength must be between 0 and 1.")
    clean_falloff_curve = falloff_curve.lower().strip()
    if clean_falloff_curve not in {"smooth", "linear", "gaussian", "hard"}:
        raise ValueError("falloff_curve must be smooth, linear, gaussian, or hard.")
    max_preview = _validate_int(max_preview, "max_preview", 0)

    shape_name = _mesh_shape(object_name)
    dag = _dag_path(shape_name)
    mesh_fn = _mesh_fn(shape_name)
    prefix_name = _prefix(shape_name)
    om_space = om.MSpace.kWorld if space == "world" else om.MSpace.kObject

    resolved_components = _resolve_components()
    seed_vertex_ids = _vertex_ids_from_components(resolved_components)
    if not seed_vertex_ids:
        raise ValueError("No seed vertices resolved from components, indices, or current selection.")

    points = mesh_fn.getPoints(om_space)
    all_vertex_ids = list(range(mesh_fn.numVertices))
    selection_min, selection_max, selection_center = _bounds(seed_vertex_ids, points)
    object_min, object_max, object_center = _bounds(all_vertex_ids, points)
    boundary_vertices = _boundary_vertices()
    weights = _candidate_weights(points)
    if not weights:
        raise ValueError("No vertices fall within the requested soft selection.")

    next_points = om.MPointArray(points)
    applied = {}

    if operation == "translate":
        move_vector = _validate_vector(vector, 3, "vector")
        for vertex_id, record in weights.items():
            weight = record["weight"]
            point = points[vertex_id]
            next_points[vertex_id] = om.MPoint(
                point.x + move_vector[0] * weight,
                point.y + move_vector[1] * weight,
                point.z + move_vector[2] * weight,
            )
        applied["vector"] = move_vector

    elif operation == "scale":
        scale_vector = _validate_vector(scale, 3, "scale")
        pivot_value = _pivot(points)
        for vertex_id, record in weights.items():
            point = points[vertex_id]
            target = om.MPoint(
                pivot_value[0] + (point.x - pivot_value[0]) * scale_vector[0],
                pivot_value[1] + (point.y - pivot_value[1]) * scale_vector[1],
                pivot_value[2] + (point.z - pivot_value[2]) * scale_vector[2],
            )
            next_points[vertex_id] = _lerp_point(point, target, record["weight"])
        applied["scale"] = scale_vector
        applied["pivot"] = pivot_value

    elif operation == "rotate":
        rotation_value = _validate_vector(rotation, 3, "rotation")
        pivot_value = _pivot(points)
        for vertex_id, record in weights.items():
            point = points[vertex_id]
            target = _rotate_point(point, pivot_value, rotation_value)
            next_points[vertex_id] = _lerp_point(point, target, record["weight"])
        applied["rotation"] = rotation_value
        applied["pivot"] = pivot_value

    elif operation == "align_axis":
        axis_idx = _axis_index(axis)
        target_value = _validate_scalar(value, "value")
        for vertex_id, record in weights.items():
            values = _point_values(points[vertex_id])
            values[axis_idx] = values[axis_idx] + (target_value - values[axis_idx]) * record["weight"]
            next_points[vertex_id] = _point_from_values(values)
        applied["axis"] = axis.lower().strip()
        applied["value"] = target_value

    elif operation in {"align_radial", "radial_offset"}:
        axis_idx = _axis_index(axis)
        center_value = _center(points)
        radial_axes = [index for index in range(3) if index != axis_idx]
        target_radius = _target_radius(points, center_value, axis_idx) if operation == "align_radial" else None
        radial_offset_value = _validate_scalar(offset, "offset") if operation == "radial_offset" else None
        fallback_axis = radial_axes[0]
        for vertex_id, record in weights.items():
            values = _point_values(points[vertex_id])
            delta_a = values[radial_axes[0]] - center_value[radial_axes[0]]
            delta_b = values[radial_axes[1]] - center_value[radial_axes[1]]
            current_radius = math.sqrt(delta_a * delta_a + delta_b * delta_b)
            if operation == "align_radial":
                desired_radius = target_radius
            else:
                desired_radius = max(0.0, current_radius + radial_offset_value)
            weighted_radius = current_radius + (desired_radius - current_radius) * record["weight"]
            if current_radius <= 1.0e-12:
                values[radial_axes[0]] = center_value[radial_axes[0]]
                values[radial_axes[1]] = center_value[radial_axes[1]]
                values[fallback_axis] = center_value[fallback_axis] + weighted_radius
            else:
                scale_factor = weighted_radius / current_radius
                values[radial_axes[0]] = center_value[radial_axes[0]] + delta_a * scale_factor
                values[radial_axes[1]] = center_value[radial_axes[1]] + delta_b * scale_factor
            next_points[vertex_id] = _point_from_values(values)
        applied["axis"] = axis.lower().strip()
        applied["center"] = center_value
        if operation == "align_radial":
            applied["radius"] = target_radius
            applied["radius_mode"] = radius_mode.lower().strip()
        else:
            applied["offset"] = radial_offset_value

    mesh_fn.setPoints(next_points, om_space)
    try:
        mesh_fn.updateSurface()
    except Exception:
        pass

    updated_points = mesh_fn.getPoints(om_space)
    affected_ids = sorted(weights)
    moved_ids = [vertex_id for vertex_id in affected_ids if _distance(points[vertex_id], updated_points[vertex_id]) > 1.0e-9]
    if not moved_ids:
        raise RuntimeError(f"{operation} did not move any vertices.")

    if select_result:
        cmds.select([f"{prefix_name}.vtx[{vertex_id}]" for vertex_id in affected_ids], replace=True)

    distances = [weights[vertex_id]["distance"] for vertex_id in affected_ids]
    return {
        "success": True,
        "object_name": object_name,
        "shape_name": shape_name,
        "operation": operation,
        "component_type": component_type,
        "space": space,
        "seed_vertex_count": len(seed_vertex_ids),
        "affected_vertex_count": len(affected_ids),
        "moved_vertex_count": len(moved_ids),
        "seed_vertices_preview": seed_vertex_ids[:max_preview],
        "moved_vertices_preview": moved_ids[:max_preview],
        "falloff_radius": clean_falloff_radius,
        "falloff_mode": clean_falloff_mode,
        "topology_depth": clean_topology_depth,
        "falloff_curve": clean_falloff_curve,
        "strength": clean_strength,
        "affect_all_vertices": bool(affect_all_vertices),
        "preserve_boundary": bool(preserve_boundary),
        "distance_range": [float(min(distances)), float(max(distances))],
        "selection_bounds_before": {
            "min": selection_min,
            "max": selection_max,
            "center": selection_center,
        },
        "applied": applied,
        "preview": _preview(affected_ids, points, updated_points, weights),
    }
