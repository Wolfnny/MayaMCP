from typing import Dict, List, Any, Union


def symmetrize_mesh_components(
    object_name: str,
    operation: str = "symmetrize",
    component_type: str = "vertex",
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    axis: str = "x",
    center: List[float] = None,
    center_mode: str = "origin",
    direction: str = "average",
    tolerance: float = 0.001,
    unique_pairs: bool = True,
    snap_center_vertices: bool = True,
    space: str = "object",
    use_selection: bool = True,
    select_result: bool = True,
    max_preview: int = 50,
) -> Dict[str, Any]:
    """Mirror or symmetrize selected polygon mesh components by vertex pairs.

    Operations:
    - query_pairs: find mirror-paired vertices without editing the mesh
    - symmetrize: move one or both sides of each pair

    Directions:
    - average: average both paired vertices into symmetric positions
    - positive_to_negative: copy the positive side across the mirror plane
    - negative_to_positive: copy the negative side across the mirror plane
    - selected_to_mirror: copy the selected vertex to its unselected pair mate
    - mirror_to_selected: copy the unselected pair mate into the selected vertex

    Edges, faces, UVs, and vertex-faces are converted to vertices. This supports
    Maya-style local symmetry cleanup after hand-moving components, without
    rebuilding a procedural or object-wide shape. By default each vertex can be
    used in at most one mirror pair, avoiding accidental many-to-one collapses
    when several edited vertices fall within the same tolerance region.
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

    def _validate_bool(value, arg_name):
        if not isinstance(value, bool):
            raise ValueError(f"{arg_name} must be a boolean.")
        return value

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
        ids = []
        pattern = re.compile(r"\.vtx\[(\d+)\]$")
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

    def _distance_to_values(point, values):
        return math.sqrt((point.x - values[0]) ** 2 + (point.y - values[1]) ** 2 + (point.z - values[2]) ** 2)

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

    def _center_point(current_points):
        if center is not None:
            return _validate_vector(center, 3, "center")
        mode = center_mode.lower().strip()
        if mode == "origin":
            return [0.0, 0.0, 0.0]
        if mode == "selection_center":
            return _bounds(vertex_ids, current_points)[2]
        if mode == "object_center":
            return _bounds(list(range(mesh_fn.numVertices)), current_points)[2]
        raise ValueError("center_mode must be origin, selection_center, or object_center.")

    def _mirror_values(values, center_value, axis_idx):
        mirrored = values[:]
        mirrored[axis_idx] = center_value[axis_idx] * 2.0 - mirrored[axis_idx]
        return mirrored

    def _mirror_point(point, center_value, axis_idx):
        return _point_from_values(_mirror_values(_point_values(point), center_value, axis_idx))

    def _side(vertex_id, current_points, center_value, axis_idx, clean_tolerance):
        delta = _point_values(current_points[vertex_id])[axis_idx] - center_value[axis_idx]
        if delta > clean_tolerance:
            return "positive"
        if delta < -clean_tolerance:
            return "negative"
        return "center"

    def _positive_negative(pair, current_points, center_value, axis_idx):
        first, second = pair
        first_value = _point_values(current_points[first])[axis_idx]
        second_value = _point_values(current_points[second])[axis_idx]
        if first_value >= second_value:
            return first, second
        return second, first

    def _find_pairs(selected_ids, current_points, center_value, axis_idx, clean_tolerance):
        pairs = []
        skipped = []
        center_vertices = []
        seen_pairs = set()
        used_vertices = set()
        tolerance_sq = clean_tolerance * clean_tolerance
        all_ids = list(range(mesh_fn.numVertices))

        for vertex_id in selected_ids:
            if clean_unique_pairs and vertex_id in used_vertices:
                skipped.append(
                    {
                        "index": vertex_id,
                        "component": f"{prefix_name}.vtx[{vertex_id}]",
                        "reason": "already_used_in_unique_pair",
                    }
                )
                continue
            current_side = _side(vertex_id, current_points, center_value, axis_idx, clean_tolerance)
            if current_side == "center":
                center_vertices.append(vertex_id)
                continue

            target_values = _mirror_values(_point_values(current_points[vertex_id]), center_value, axis_idx)
            best_id = None
            best_distance_sq = tolerance_sq
            for candidate_id in all_ids:
                if candidate_id == vertex_id:
                    continue
                if clean_unique_pairs and candidate_id in used_vertices:
                    continue
                candidate = current_points[candidate_id]
                distance_sq = (
                    (candidate.x - target_values[0]) ** 2
                    + (candidate.y - target_values[1]) ** 2
                    + (candidate.z - target_values[2]) ** 2
                )
                if distance_sq <= best_distance_sq:
                    best_distance_sq = distance_sq
                    best_id = candidate_id

            if best_id is None:
                skipped.append(
                    {
                        "index": vertex_id,
                        "component": f"{prefix_name}.vtx[{vertex_id}]",
                        "reason": "no_mirror_match_within_tolerance",
                    }
                )
                continue

            pair = tuple(sorted((vertex_id, best_id)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            if clean_unique_pairs:
                used_vertices.update(pair)
            positive_id, negative_id = _positive_negative(pair, current_points, center_value, axis_idx)
            pairs.append(
                {
                    "positive": positive_id,
                    "negative": negative_id,
                    "distance": math.sqrt(best_distance_sq),
                }
            )

        return pairs, center_vertices, skipped

    def _average_pair_positions(positive_point, negative_point, center_value, axis_idx):
        positive_values = _point_values(positive_point)
        mirrored_negative = _mirror_values(_point_values(negative_point), center_value, axis_idx)
        averaged_positive = [
            (positive_values[index] + mirrored_negative[index]) * 0.5
            for index in range(3)
        ]
        averaged_negative = _mirror_values(averaged_positive, center_value, axis_idx)
        return _point_from_values(averaged_positive), _point_from_values(averaged_negative)

    def _apply_pair(pair_record, current_points, next_points, selected_set, center_value, axis_idx, clean_direction):
        positive_id = pair_record["positive"]
        negative_id = pair_record["negative"]
        positive_point = current_points[positive_id]
        negative_point = current_points[negative_id]

        if clean_direction == "average":
            next_positive, next_negative = _average_pair_positions(positive_point, negative_point, center_value, axis_idx)
            next_points[positive_id] = next_positive
            next_points[negative_id] = next_negative
            return [positive_id, negative_id], None

        if clean_direction == "positive_to_negative":
            next_points[negative_id] = _mirror_point(positive_point, center_value, axis_idx)
            return [negative_id], None

        if clean_direction == "negative_to_positive":
            next_points[positive_id] = _mirror_point(negative_point, center_value, axis_idx)
            return [positive_id], None

        selected_in_pair = [vertex_id for vertex_id in (positive_id, negative_id) if vertex_id in selected_set]
        if len(selected_in_pair) != 1:
            return [], {
                "indices": [positive_id, negative_id],
                "components": [f"{prefix_name}.vtx[{positive_id}]", f"{prefix_name}.vtx[{negative_id}]"],
                "reason": "requires_exactly_one_selected_vertex_in_pair",
            }

        selected_id = selected_in_pair[0]
        other_id = negative_id if selected_id == positive_id else positive_id

        if clean_direction == "selected_to_mirror":
            next_points[other_id] = _mirror_point(current_points[selected_id], center_value, axis_idx)
            return [other_id], None

        next_points[selected_id] = _mirror_point(current_points[other_id], center_value, axis_idx)
        return [selected_id], None

    def _pair_preview(pair_records, before_points, after_points):
        preview = []
        for pair in pair_records[:max_preview]:
            positive_id = pair["positive"]
            negative_id = pair["negative"]
            preview.append(
                {
                    "positive": {
                        "index": positive_id,
                        "component": f"{prefix_name}.vtx[{positive_id}]",
                        "before": _point_values(before_points[positive_id]),
                        "after": _point_values(after_points[positive_id]),
                        "movement": _distance(before_points[positive_id], after_points[positive_id]),
                    },
                    "negative": {
                        "index": negative_id,
                        "component": f"{prefix_name}.vtx[{negative_id}]",
                        "before": _point_values(before_points[negative_id]),
                        "after": _point_values(after_points[negative_id]),
                        "movement": _distance(before_points[negative_id], after_points[negative_id]),
                    },
                    "match_distance": float(pair["distance"]),
                }
            )
        return preview

    if not object_name:
        raise ValueError("object_name is required.")
    operation = operation.lower().strip()
    if operation not in {"query_pairs", "symmetrize"}:
        raise ValueError("operation must be query_pairs or symmetrize.")
    component_type = component_type.lower().strip()
    if component_type not in {"vertex", "edge", "face", "uv", "vertex_face"}:
        raise ValueError("component_type must be vertex, edge, face, uv, or vertex_face.")
    clean_direction = direction.lower().strip()
    if clean_direction not in {"average", "positive_to_negative", "negative_to_positive", "selected_to_mirror", "mirror_to_selected"}:
        raise ValueError("direction must be average, positive_to_negative, negative_to_positive, selected_to_mirror, or mirror_to_selected.")
    clean_tolerance = _validate_scalar(tolerance, "tolerance")
    if clean_tolerance <= 0.0:
        raise ValueError("tolerance must be greater than 0.")
    clean_unique_pairs = _validate_bool(unique_pairs, "unique_pairs")
    space = space.lower().strip()
    if space not in {"world", "object"}:
        raise ValueError("space must be world or object.")
    max_preview = _validate_int(max_preview, "max_preview", 0)

    shape_name = _mesh_shape(object_name)
    mesh_fn = _mesh_fn(shape_name)
    prefix_name = _prefix(shape_name)
    om_space = om.MSpace.kWorld if space == "world" else om.MSpace.kObject

    resolved_components = _resolve_components()
    vertex_ids = _vertex_ids_from_components(resolved_components)
    if not vertex_ids:
        raise ValueError("No vertices resolved from components, indices, or current selection.")

    axis_idx = _axis_index(axis)
    points = mesh_fn.getPoints(om_space)
    center_value = _center_point(points)
    pairs, center_vertices, skipped = _find_pairs(vertex_ids, points, center_value, axis_idx, clean_tolerance)

    next_points = om.MPointArray(points)
    moved_ids = set()
    pair_skipped = []

    if operation == "symmetrize":
        selected_set = set(vertex_ids)
        for pair in pairs:
            moved_pair_ids, skip_record = _apply_pair(pair, points, next_points, selected_set, center_value, axis_idx, clean_direction)
            moved_ids.update(moved_pair_ids)
            if skip_record:
                pair_skipped.append(skip_record)

        if snap_center_vertices:
            for vertex_id in center_vertices:
                values = _point_values(next_points[vertex_id])
                values[axis_idx] = center_value[axis_idx]
                next_points[vertex_id] = _point_from_values(values)
                moved_ids.add(vertex_id)

        mesh_fn.setPoints(next_points, om_space)
        try:
            mesh_fn.updateSurface()
        except Exception:
            pass

    updated_points = mesh_fn.getPoints(om_space)
    actual_moved_ids = sorted(
        vertex_id
        for vertex_id in moved_ids
        if _distance(points[vertex_id], updated_points[vertex_id]) > 1.0e-9
    )

    if operation == "symmetrize" and not actual_moved_ids:
        skipped.extend(pair_skipped)
        raise RuntimeError("symmetrize did not move any vertices.")

    result_components = [f"{prefix_name}.vtx[{vertex_id}]" for vertex_id in sorted(set(vertex_ids).union(actual_moved_ids))]
    if select_result and result_components:
        cmds.select(result_components, replace=True)

    skipped.extend(pair_skipped)
    return {
        "success": True,
        "object_name": object_name,
        "shape_name": shape_name,
        "operation": operation,
        "component_type": component_type,
        "space": space,
        "axis": axis.lower().strip(),
        "center": center_value,
        "center_mode": center_mode.lower().strip() if center is None else "explicit",
        "direction": clean_direction,
        "tolerance": clean_tolerance,
        "unique_pairs": clean_unique_pairs,
        "resolved_vertex_count": len(vertex_ids),
        "pair_count": len(pairs),
        "center_vertex_count": len(center_vertices),
        "moved_vertex_count": len(actual_moved_ids),
        "moved_vertices_preview": actual_moved_ids[:max_preview],
        "skipped_count": len(skipped),
        "skipped_preview": skipped[:max_preview],
        "pair_preview": _pair_preview(pairs, points, updated_points),
    }
