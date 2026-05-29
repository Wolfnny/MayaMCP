from typing import Dict, List, Any, Union


def select_mesh_by_region(
    object_name: str,
    result_type: str = "face",
    component_type: str = None,
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    axis: str = None,
    axis_range: List[float] = None,
    box_min: List[float] = None,
    box_max: List[float] = None,
    center: List[float] = None,
    radial_axis: str = "y",
    radial_range: List[float] = None,
    angle_range_degrees: List[float] = None,
    normal: List[float] = None,
    normal_angle_degrees: float = None,
    sample_mode: str = "center",
    space: str = "world",
    selection_mode: str = "replace",
    select_result: bool = True,
    use_selection: bool = True,
    max_preview: int = 200,
) -> Dict[str, Any]:
    """Filter mesh vertices, edges, or faces by spatial and normal criteria.

    Supported criteria:
    - axis_range on x, y, or z, measured relative to center
    - box_min/box_max absolute bounding box limits
    - radial_range and angle_range_degrees around radial_axis and center
    - normal plus normal_angle_degrees for face normals or vertex normals

    Angular filtering uses atan2(delta_on_first_radial_axis, delta_on_second_radial_axis).
    For the default radial_axis="y", 0 degrees points toward +Z, 90 toward +X,
    180 toward -Z, and 270 toward -X. The returned angle_convention field
    reports this basis explicitly for any radial_axis.

    This is a Maya-style component selection constraint for reliably targeting
    local bands, panels, caps, front/back regions, and normal-facing areas before
    transform, material, UV, or topology edits.
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

    def _validate_range(values, arg_name):
        clean = _validate_vector(values, 2, arg_name)
        if clean[0] > clean[1]:
            clean = [clean[1], clean[0]]
        return clean

    def _normalize(values, arg_name):
        vector = _validate_vector(values, 3, arg_name)
        length = math.sqrt(sum(item * item for item in vector))
        if length <= 1.0e-12:
            raise ValueError(f"{arg_name} must not be a zero vector.")
        return [item / length for item in vector]

    def _axis_index(axis_name, arg_name):
        clean_axis = (axis_name or "").lower().strip()
        if clean_axis not in {"x", "y", "z"}:
            raise ValueError(f"{arg_name} must be x, y, or z.")
        return {"x": 0, "y": 1, "z": 2}[clean_axis]

    def _positive_span(start_degrees, end_degrees):
        span = (end_degrees - start_degrees) % 360.0
        return 360.0 if abs(span) < 1.0e-8 else span

    def _angle_in_range(angle, start_degrees, span_degrees):
        delta = (angle - start_degrees) % 360.0
        return delta <= span_degrees + 1.0e-8

    def _axis_name(index):
        return ["x", "y", "z"][index]

    def _signed_axis_name(index, sign=1):
        prefix = "+" if sign >= 0 else "-"
        return f"{prefix}{_axis_name(index).upper()}"

    def _angle_convention(radial_axis_index, first_radial_index, second_radial_index):
        return {
            "radial_axis": _axis_name(radial_axis_index),
            "formula": "degrees(atan2(delta_first_radial_axis, delta_second_radial_axis))",
            "first_radial_axis": _axis_name(first_radial_index),
            "second_radial_axis": _axis_name(second_radial_index),
            "zero_degrees_direction": _signed_axis_name(second_radial_index, 1),
            "ninety_degrees_direction": _signed_axis_name(first_radial_index, 1),
            "one_eighty_degrees_direction": _signed_axis_name(second_radial_index, -1),
            "two_seventy_degrees_direction": _signed_axis_name(first_radial_index, -1),
            "positive_direction": f"from {_signed_axis_name(second_radial_index, 1)} toward {_signed_axis_name(first_radial_index, 1)}",
        }

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

    def _unique(items):
        seen = set()
        result = []
        for item in cmds.ls(items, flatten=True) or []:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

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

    def _resolve_seed_components():
        clean_type = (component_type or result_type).lower().strip()
        kind_map = {"vertex": "vtx", "edge": "e", "face": "f", "uv": "map", "vertex_face": "vtxFace"}
        if components is not None:
            return _flatten(components)
        if clean_type in kind_map and indices is not None:
            return _components_from_indices(kind_map[clean_type])
        selected = _selected_components()
        return selected

    def _convert(items, target):
        flags = {
            "vertex": {"toVertex": True},
            "edge": {"toEdge": True},
            "face": {"toFace": True},
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

    def _candidate_ids():
        seeds = _resolve_seed_components()
        kind = {"vertex": "vtx", "edge": "e", "face": "f"}[clean_result_type]
        if seeds:
            return _component_ids(_convert(seeds, clean_result_type), kind)
        total = {
            "vertex": int(mesh_fn.numVertices),
            "edge": int(mesh_fn.numEdges),
            "face": int(mesh_fn.numPolygons),
        }[clean_result_type]
        return list(range(total))

    def _point_values(point):
        return [float(point.x), float(point.y), float(point.z)]

    def _average_point(points):
        result = om.MPoint()
        for point in points:
            result += point
        return result / float(max(1, len(points)))

    def _edge_points(edge_id):
        iterator = om.MItMeshEdge(dag_path)
        iterator.setIndex(edge_id)
        return [points[int(iterator.vertexId(0))], points[int(iterator.vertexId(1))]]

    def _face_points(face_id):
        vertex_ids = mesh_fn.getPolygonVertices(face_id)
        return [points[int(vertex_id)] for vertex_id in vertex_ids]

    def _sample_points(component_id):
        if clean_result_type == "vertex":
            return [points[component_id]]
        if clean_result_type == "edge":
            edge_points = _edge_points(component_id)
            if clean_sample_mode == "center":
                return [_average_point(edge_points)]
            return edge_points
        face_points = _face_points(component_id)
        if clean_sample_mode == "center":
            return [_average_point(face_points)]
        return face_points

    def _point_matches(point):
        values = _point_values(point)
        if clean_box_min is not None:
            for index in range(3):
                if values[index] < clean_box_min[index] - 1.0e-9 or values[index] > clean_box_max[index] + 1.0e-9:
                    return False
        if clean_axis_range is not None:
            axis_value = values[axis_idx] - clean_center[axis_idx]
            if axis_value < clean_axis_range[0] - 1.0e-9 or axis_value > clean_axis_range[1] + 1.0e-9:
                return False
        if clean_radial_range is not None or clean_angle_range is not None:
            delta_a = values[radial_a] - clean_center[radial_a]
            delta_b = values[radial_b] - clean_center[radial_b]
            radius = math.sqrt(delta_a * delta_a + delta_b * delta_b)
            if clean_radial_range is not None and (radius < clean_radial_range[0] - 1.0e-9 or radius > clean_radial_range[1] + 1.0e-9):
                return False
            if clean_angle_range is not None:
                angle = math.degrees(math.atan2(delta_a, delta_b))
                if not _angle_in_range(angle, clean_angle_range[0], angle_span):
                    return False
        return True

    def _component_position_match(component_id):
        sample_points = _sample_points(component_id)
        if clean_sample_mode in {"center", "any"}:
            return any(_point_matches(point) for point in sample_points)
        if clean_sample_mode == "all":
            return all(_point_matches(point) for point in sample_points)
        raise ValueError("sample_mode must be center, any, or all.")

    def _vertex_normal(vertex_id):
        vector = mesh_fn.getVertexNormal(vertex_id, True, om_space)
        length = math.sqrt(vector.x * vector.x + vector.y * vector.y + vector.z * vector.z)
        if length <= 1.0e-12:
            return None
        return [float(vector.x / length), float(vector.y / length), float(vector.z / length)]

    def _edge_normal(edge_id):
        vertices = _edge_points(edge_id)
        vertex_ids = []
        iterator = om.MItMeshEdge(dag_path)
        iterator.setIndex(edge_id)
        vertex_ids.append(int(iterator.vertexId(0)))
        vertex_ids.append(int(iterator.vertexId(1)))
        normals = [_vertex_normal(vertex_id) for vertex_id in vertex_ids]
        normals = [item for item in normals if item is not None]
        if not normals:
            return None
        summed = [sum(item[index] for item in normals) / float(len(normals)) for index in range(3)]
        return _normalize(summed, "edge normal")

    def _face_normal(face_id):
        vector = mesh_fn.getPolygonNormal(face_id, om_space)
        length = math.sqrt(vector.x * vector.x + vector.y * vector.y + vector.z * vector.z)
        if length <= 1.0e-12:
            return None
        return [float(vector.x / length), float(vector.y / length), float(vector.z / length)]

    def _normal_for_component(component_id):
        if clean_normal is None:
            return None
        if clean_result_type == "vertex":
            return _vertex_normal(component_id)
        if clean_result_type == "edge":
            return _edge_normal(component_id)
        return _face_normal(component_id)

    def _normal_matches(component_id):
        if clean_normal is None:
            return True
        component_normal = _normal_for_component(component_id)
        if component_normal is None:
            return False
        dot = max(-1.0, min(1.0, sum(component_normal[index] * clean_normal[index] for index in range(3))))
        angle = math.degrees(math.acos(dot))
        return angle <= clean_normal_angle + 1.0e-8

    def _component(kind, index):
        return f"{prefix_name}.{kind}[{index}]"

    def _apply_selection(items):
        mode = selection_mode.lower().strip()
        if mode not in {"replace", "add", "toggle", "deselect"}:
            raise ValueError("selection_mode must be replace, add, toggle, or deselect.")
        cmds.select(items, **{mode: True})

    if not object_name:
        raise ValueError("object_name is required.")
    clean_result_type = result_type.lower().strip()
    if clean_result_type not in {"vertex", "edge", "face"}:
        raise ValueError("result_type must be vertex, edge, or face.")
    clean_sample_mode = sample_mode.lower().strip()
    if clean_sample_mode not in {"center", "any", "all"}:
        raise ValueError("sample_mode must be center, any, or all.")
    space = space.lower().strip()
    if space not in {"world", "object"}:
        raise ValueError("space must be world or object.")
    max_preview = _validate_int(max_preview, "max_preview", 0)

    shape_name = _mesh_shape(object_name)
    prefix_name = _prefix(shape_name)
    dag_path = _dag_path(shape_name)
    mesh_fn = _mesh_fn(shape_name)
    om_space = om.MSpace.kWorld if space == "world" else om.MSpace.kObject
    points = mesh_fn.getPoints(om_space)

    clean_center = _validate_vector(center, 3, "center") if center is not None else [0.0, 0.0, 0.0]
    axis_idx = _axis_index(axis, "axis") if axis is not None else None
    clean_axis_range = _validate_range(axis_range, "axis_range") if axis_range is not None else None
    if clean_axis_range is not None and axis_idx is None:
        raise ValueError("axis is required when axis_range is provided.")
    if box_min is None and box_max is None:
        clean_box_min = None
        clean_box_max = None
    elif box_min is not None and box_max is not None:
        clean_box_min = _validate_vector(box_min, 3, "box_min")
        clean_box_max = _validate_vector(box_max, 3, "box_max")
        for index in range(3):
            if clean_box_min[index] > clean_box_max[index]:
                clean_box_min[index], clean_box_max[index] = clean_box_max[index], clean_box_min[index]
    else:
        raise ValueError("box_min and box_max must be provided together.")

    radial_axis_idx = _axis_index(radial_axis, "radial_axis")
    radial_axes = [index for index in range(3) if index != radial_axis_idx]
    radial_a, radial_b = radial_axes[0], radial_axes[1]
    clean_radial_range = _validate_range(radial_range, "radial_range") if radial_range is not None else None
    clean_angle_range = _validate_vector(angle_range_degrees, 2, "angle_range_degrees") if angle_range_degrees is not None else None
    angle_span = _positive_span(clean_angle_range[0], clean_angle_range[1]) if clean_angle_range is not None else None
    clean_normal = _normalize(normal, "normal") if normal is not None else None
    clean_normal_angle = _validate_scalar(normal_angle_degrees if normal_angle_degrees is not None else 15.0, "normal_angle_degrees")
    if clean_normal_angle < 0.0 or clean_normal_angle > 180.0:
        raise ValueError("normal_angle_degrees must be between 0 and 180.")
    if (
        clean_axis_range is None
        and clean_box_min is None
        and clean_radial_range is None
        and clean_angle_range is None
        and clean_normal is None
    ):
        raise ValueError("At least one filter criterion is required.")

    candidate_ids = _candidate_ids()
    matched_ids = []
    for component_id in candidate_ids:
        if _component_position_match(component_id) and _normal_matches(component_id):
            matched_ids.append(component_id)

    kind = {"vertex": "vtx", "edge": "e", "face": "f"}[clean_result_type]
    matched_components = [_component(kind, component_id) for component_id in matched_ids]
    if select_result:
        _apply_selection(matched_components)

    return {
        "success": True,
        "object_name": object_name,
        "shape_name": shape_name,
        "result_type": clean_result_type,
        "space": space,
        "sample_mode": clean_sample_mode,
        "criteria": {
            "axis": axis.lower().strip() if axis else None,
            "axis_range": clean_axis_range,
            "box_min": clean_box_min,
            "box_max": clean_box_max,
            "center": clean_center,
            "radial_axis": radial_axis.lower().strip(),
            "radial_range": clean_radial_range,
            "angle_range_degrees": clean_angle_range,
            "angle_convention": _angle_convention(radial_axis_idx, radial_a, radial_b),
            "normal": clean_normal,
            "normal_angle_degrees": clean_normal_angle if clean_normal is not None else None,
        },
        "candidate_count": len(candidate_ids),
        "matched_count": len(matched_components),
        "components": matched_components[:max_preview],
        "truncated": len(matched_components) > max_preview,
        "selected": bool(select_result),
        "selection_mode": selection_mode if select_result else None,
    }
