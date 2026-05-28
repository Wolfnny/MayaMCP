from typing import Dict, List, Any, Union


def transform_mesh_components(
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
    value_mode: str = "explicit",
    start_value: float = None,
    end_value: float = None,
    pivot: List[float] = None,
    pivot_mode: str = "selection_center",
    space: str = "world",
    use_selection: bool = True,
    max_preview: int = 20,
) -> Dict[str, Any]:
    """Transform selected polygon components by editing mesh vertices.

    Operations:
    - translate: add vector to resolved vertices
    - scale: scale resolved vertices around a pivot
    - rotate: rotate resolved vertices around a pivot using XYZ degrees
    - align_axis: set all resolved vertices to one coordinate on x, y, or z
    - distribute_axis: evenly distribute resolved vertices along x, y, or z

    Components can be explicit, built from component_type plus indices, or read
    from the current selection. Edges and faces are converted to their unique
    vertices, so this supports Maya-style local loop scaling, point flattening,
    coordinate alignment, and manual proportional shaping without global
    procedural deformation.
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

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(item) for item in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(item) for item in values]

    def _validate_int(value_to_check, arg_name, minimum):
        if not isinstance(value_to_check, int) or isinstance(value_to_check, bool) or value_to_check < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return int(value_to_check)

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

    def _prefix():
        parents = cmds.listRelatives(shape_name, parent=True, fullPath=False) or []
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
        ids = []
        pattern = re.compile(r"\.vtx\[(\d+)\]$")
        for vertex in vertices:
            match = pattern.search(vertex)
            if match:
                ids.append(int(match.group(1)))
        return sorted(set(ids))

    def _point_to_list(point):
        return [float(point.x), float(point.y), float(point.z)]

    def _point_preview(vertex_ids, current_points):
        return [
            {"index": vertex_id, "position": _point_to_list(current_points[vertex_id])}
            for vertex_id in vertex_ids[:max_preview]
        ]

    def _bounds(vertex_ids, current_points):
        mins = [float("inf"), float("inf"), float("inf")]
        maxs = [float("-inf"), float("-inf"), float("-inf")]
        for vertex_id in vertex_ids:
            point = current_points[vertex_id]
            values = [point.x, point.y, point.z]
            for index in range(3):
                mins[index] = min(mins[index], values[index])
                maxs[index] = max(maxs[index], values[index])
        center = [(mins[index] + maxs[index]) * 0.5 for index in range(3)]
        return mins, maxs, center

    def _all_vertex_ids():
        return list(range(mesh_fn.numVertices))

    def _pivot(current_points):
        if pivot is not None:
            return _validate_vector(pivot, 3, "pivot")
        mode = pivot_mode.lower().strip()
        if mode == "origin":
            return [0.0, 0.0, 0.0]
        if mode == "selection_center":
            return selection_center[:]
        if mode == "selection_min":
            return selection_min[:]
        if mode == "selection_max":
            return selection_max[:]
        if mode in {"object_center", "object_min", "object_max"}:
            object_min, object_max, object_center = _bounds(_all_vertex_ids(), current_points)
            if mode == "object_min":
                return object_min
            if mode == "object_max":
                return object_max
            return object_center
        raise ValueError("pivot_mode must be origin, selection_center, selection_min, selection_max, object_center, object_min, or object_max.")

    def _axis_index(axis_name):
        clean_axis = (axis_name or "").lower().strip()
        if clean_axis not in {"x", "y", "z"}:
            raise ValueError("axis must be x, y, or z.")
        return {"x": 0, "y": 1, "z": 2}[clean_axis]

    def _target_axis_value(axis_idx, current_points):
        mode = value_mode.lower().strip()
        if mode == "explicit":
            return _validate_scalar(value, "value")
        if mode == "selection_min":
            return selection_min[axis_idx]
        if mode == "selection_max":
            return selection_max[axis_idx]
        if mode == "selection_center":
            return selection_center[axis_idx]
        if mode in {"object_min", "object_max", "object_center"}:
            object_min, object_max, object_center = _bounds(_all_vertex_ids(), current_points)
            if mode == "object_min":
                return object_min[axis_idx]
            if mode == "object_max":
                return object_max[axis_idx]
            return object_center[axis_idx]
        raise ValueError("value_mode must be explicit, selection_min, selection_max, selection_center, object_min, object_max, or object_center.")

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

    if not object_name:
        raise ValueError("object_name is required.")
    operation = operation.lower().strip()
    if operation not in {"translate", "scale", "rotate", "align_axis", "distribute_axis"}:
        raise ValueError("operation must be translate, scale, rotate, align_axis, or distribute_axis.")
    component_type = component_type.lower().strip()
    if component_type not in {"vertex", "edge", "face", "uv", "vertex_face"}:
        raise ValueError("component_type must be vertex, edge, face, uv, or vertex_face.")
    space = space.lower().strip()
    if space not in {"world", "object"}:
        raise ValueError("space must be world or object.")
    max_preview = _validate_int(max_preview, "max_preview", 0)

    shape_name = _mesh_shape(object_name)
    mesh_fn = _mesh_fn(shape_name)
    prefix_name = _prefix()
    om_space = om.MSpace.kWorld if space == "world" else om.MSpace.kObject

    resolved_components = _resolve_components()
    vertex_ids = _vertex_ids_from_components(resolved_components)
    if not vertex_ids:
        raise ValueError("No vertices resolved from components, indices, or current selection.")

    points = mesh_fn.getPoints(om_space)
    selection_min, selection_max, selection_center = _bounds(vertex_ids, points)
    before_preview = _point_preview(vertex_ids, points)

    applied = {}
    if operation == "translate":
        move_vector = _validate_vector(vector, 3, "vector")
        for vertex_id in vertex_ids:
            point = points[vertex_id]
            points[vertex_id] = om.MPoint(point.x + move_vector[0], point.y + move_vector[1], point.z + move_vector[2])
        applied["vector"] = move_vector

    elif operation == "scale":
        scale_vector = _validate_vector(scale, 3, "scale")
        pivot_value = _pivot(points)
        for vertex_id in vertex_ids:
            point = points[vertex_id]
            points[vertex_id] = om.MPoint(
                pivot_value[0] + (point.x - pivot_value[0]) * scale_vector[0],
                pivot_value[1] + (point.y - pivot_value[1]) * scale_vector[1],
                pivot_value[2] + (point.z - pivot_value[2]) * scale_vector[2],
            )
        applied["scale"] = scale_vector
        applied["pivot"] = pivot_value

    elif operation == "rotate":
        rotation_value = _validate_vector(rotation, 3, "rotation")
        pivot_value = _pivot(points)
        for vertex_id in vertex_ids:
            points[vertex_id] = _rotate_point(points[vertex_id], pivot_value, rotation_value)
        applied["rotation"] = rotation_value
        applied["pivot"] = pivot_value

    elif operation == "align_axis":
        axis_idx = _axis_index(axis)
        target_value = _target_axis_value(axis_idx, points)
        for vertex_id in vertex_ids:
            point = points[vertex_id]
            values = [point.x, point.y, point.z]
            values[axis_idx] = target_value
            points[vertex_id] = om.MPoint(values[0], values[1], values[2])
        applied["axis"] = axis.lower().strip()
        applied["value"] = target_value
        applied["value_mode"] = value_mode

    elif operation == "distribute_axis":
        axis_idx = _axis_index(axis)
        ordered_ids = sorted(
            vertex_ids,
            key=lambda vertex_id: (
                [points[vertex_id].x, points[vertex_id].y, points[vertex_id].z][axis_idx],
                vertex_id,
            ),
        )
        if start_value is None:
            start = selection_min[axis_idx]
        else:
            start = _validate_scalar(start_value, "start_value")
        if end_value is None:
            end = selection_max[axis_idx]
        else:
            end = _validate_scalar(end_value, "end_value")
        denominator = max(1, len(ordered_ids) - 1)
        for order_index, vertex_id in enumerate(ordered_ids):
            target_value = start + (end - start) * (order_index / float(denominator))
            point = points[vertex_id]
            values = [point.x, point.y, point.z]
            values[axis_idx] = target_value
            points[vertex_id] = om.MPoint(values[0], values[1], values[2])
        applied["axis"] = axis.lower().strip()
        applied["start_value"] = start
        applied["end_value"] = end

    mesh_fn.setPoints(points, om_space)
    try:
        mesh_fn.updateSurface()
    except Exception:
        pass

    updated_points = mesh_fn.getPoints(om_space)
    after_preview = _point_preview(vertex_ids, updated_points)
    cmds.select([f"{prefix_name}.vtx[{vertex_id}]" for vertex_id in vertex_ids], replace=True)

    return {
        "success": True,
        "object_name": object_name,
        "shape_name": shape_name,
        "operation": operation,
        "component_type": component_type,
        "space": space,
        "resolved_vertex_count": len(vertex_ids),
        "resolved_vertices_preview": vertex_ids[:max_preview],
        "selection_bounds_before": {
            "min": selection_min,
            "max": selection_max,
            "center": selection_center,
        },
        "applied": applied,
        "before_preview": before_preview,
        "after_preview": after_preview,
    }
