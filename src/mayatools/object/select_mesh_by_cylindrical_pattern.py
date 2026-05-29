from typing import Dict, List, Any, Union


def select_mesh_by_cylindrical_pattern(
    object_name: str,
    result_type: str = "face",
    component_type: str = None,
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    center: List[float] = None,
    axis: str = "y",
    axis_range: List[float] = None,
    angle_range_degrees: List[float] = None,
    angular_count: int = 8,
    angular_duty_cycle: float = 0.5,
    angular_phase_degrees: float = 0.0,
    axis_count: int = 0,
    axis_duty_cycle: float = 1.0,
    axis_phase: float = 0.0,
    invert: bool = False,
    sample_mode: str = "center",
    space: str = "world",
    selection_mode: str = "replace",
    select_result: bool = True,
    use_selection: bool = True,
    max_preview: int = 200,
) -> Dict[str, Any]:
    """Select mesh components by repeated cylindrical coordinate bands.

    The angular pattern divides angle_range_degrees into angular_count repeated
    cells and selects the duty-cycle portion of each cell. Optionally, axis_count
    applies the same repeated pattern along the cylinder axis. This is useful
    for Maya-style component work on cap knurling, grooves, flutes, corrugated
    surfaces, vents, gear teeth, grip ridges, and other repeated cylindrical
    details before transform, material, normal, crease, or extraction edits.
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
        if clean[1] < clean[0]:
            clean = [clean[1], clean[0]]
        if clean[1] == clean[0]:
            raise ValueError(f"{arg_name} must have non-zero span.")
        return clean

    def _positive_span(start_degrees, end_degrees):
        span = (end_degrees - start_degrees) % 360.0
        return 360.0 if abs(span) < 1.0e-8 else span

    def _axis_tuple(axis_name):
        clean_axis = (axis_name or "").lower().strip()
        axes = {
            "x": (0, 1, 2),
            "y": (1, 0, 2),
            "z": (2, 0, 1),
        }
        if clean_axis not in axes:
            raise ValueError("axis must be x, y, or z.")
        return clean_axis, axes[clean_axis]

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

    def _resolve_components():
        clean_type = (component_type or clean_result_type).lower().strip()
        kind_map = {"vertex": "vtx", "edge": "e", "face": "f", "uv": "map", "vertex_face": "vtxFace"}
        if components is not None:
            return _flatten(components)
        if clean_type in kind_map and indices is not None:
            return _components_from_indices(kind_map[clean_type])
        return _selected_components()

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

    def _convert(items, target):
        flags = {
            "vertex": {"toVertex": True},
            "edge": {"toEdge": True},
            "face": {"toFace": True},
        }[target]
        return _unique(cmds.polyListComponentConversion(items, **flags) or [])

    def _candidate_ids():
        source = _resolve_components()
        if source:
            kind = {"vertex": "vtx", "edge": "e", "face": "f"}[clean_result_type]
            return _component_ids(_convert(source, clean_result_type), kind)
        total = {
            "vertex": int(mesh_fn.numVertices),
            "edge": int(mesh_fn.numEdges),
            "face": int(mesh_fn.numPolygons),
        }[clean_result_type]
        return list(range(total))

    def _point_values(point):
        return [float(point.x), float(point.y), float(point.z)]

    def _average(points_to_average):
        values = [0.0, 0.0, 0.0]
        for point in points_to_average:
            point_values = _point_values(point)
            values[0] += point_values[0]
            values[1] += point_values[1]
            values[2] += point_values[2]
        count = float(max(1, len(points_to_average)))
        return [values[0] / count, values[1] / count, values[2] / count]

    def _edge_points(edge_id):
        vertex_a, vertex_b = mesh_fn.getEdgeVertices(edge_id)
        return [points[int(vertex_a)], points[int(vertex_b)]]

    def _face_points(face_id):
        return [points[int(vertex_id)] for vertex_id in mesh_fn.getPolygonVertices(face_id)]

    def _sample_points(component_id):
        if clean_result_type == "vertex":
            return [points[component_id]]
        if clean_result_type == "edge":
            edge_points = _edge_points(component_id)
            if clean_sample_mode == "center":
                return [om.MPoint(*_average(edge_points))]
            return edge_points
        face_points = _face_points(component_id)
        if clean_sample_mode == "center":
            return [om.MPoint(*_average(face_points))]
        return face_points

    def _coordinate_record(point):
        values = _point_values(point)
        local_axis = values[axis_index] - clean_center[axis_index]
        delta_a = values[radial_a] - clean_center[radial_a]
        delta_b = values[radial_b] - clean_center[radial_b]
        angle = math.degrees(math.atan2(delta_a, delta_b))
        radius = math.sqrt(delta_a * delta_a + delta_b * delta_b)
        return {"axis_value": local_axis, "angle_degrees": angle, "radius": radius}

    def _angle_match(angle_degrees):
        delta = (angle_degrees - clean_angle_start - clean_angular_phase) % 360.0
        if delta > clean_angle_span + 1.0e-8 and clean_angle_span < 360.0 - 1.0e-8:
            return False, None
        if clean_angle_span >= 360.0 - 1.0e-8:
            range_t = (delta % 360.0) / 360.0
        else:
            range_t = max(0.0, min(1.0, delta / clean_angle_span))
        cell_position = (range_t * clean_angular_count) % 1.0
        return cell_position <= clean_angular_duty + 1.0e-8, cell_position

    def _axis_match(axis_value):
        if clean_axis_range is None:
            return True, None
        if axis_value < clean_axis_range[0] - 1.0e-8 or axis_value > clean_axis_range[1] + 1.0e-8:
            return False, None
        if clean_axis_count <= 0:
            return True, None
        axis_t = (axis_value - clean_axis_range[0]) / (clean_axis_range[1] - clean_axis_range[0])
        cell_position = ((axis_t * clean_axis_count) + clean_axis_phase) % 1.0
        return cell_position <= clean_axis_duty + 1.0e-8, cell_position

    def _point_matches(point):
        record = _coordinate_record(point)
        angle_ok, angle_cell = _angle_match(record["angle_degrees"])
        axis_ok, axis_cell = _axis_match(record["axis_value"])
        matched = angle_ok and axis_ok
        if invert:
            matched = not matched
        record["angle_cell_position"] = angle_cell
        record["axis_cell_position"] = axis_cell
        record["matched"] = matched
        return matched, record

    def _component_matches(component_id):
        sample_points = _sample_points(component_id)
        matches = []
        records = []
        for point in sample_points:
            matched, record = _point_matches(point)
            matches.append(matched)
            records.append(record)
        if clean_sample_mode in {"center", "any"}:
            return any(matches), records
        return all(matches), records

    def _component(kind, index):
        return f"{prefix_name}.{kind}[{index}]"

    def _apply_selection(items):
        mode_name = selection_mode.lower().strip()
        if mode_name not in {"replace", "add", "toggle", "deselect"}:
            raise ValueError("selection_mode must be replace, add, toggle, or deselect.")
        if items:
            cmds.select(items, **{mode_name: True})
        elif mode_name == "replace":
            cmds.select(clear=True)

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
    clean_axis_name, (axis_index, radial_a, radial_b) = _axis_tuple(axis)
    clean_center = _validate_vector(center, 3, "center") if center is not None else [0.0, 0.0, 0.0]
    clean_axis_range = _validate_range(axis_range, "axis_range") if axis_range is not None else None
    clean_angle_range = _validate_vector(angle_range_degrees if angle_range_degrees is not None else [0.0, 360.0], 2, "angle_range_degrees")
    clean_angle_start = clean_angle_range[0]
    clean_angle_span = _positive_span(clean_angle_range[0], clean_angle_range[1])
    clean_angular_count = _validate_int(angular_count, "angular_count", 1)
    clean_axis_count = _validate_int(axis_count, "axis_count", 0)
    clean_angular_duty = _validate_scalar(angular_duty_cycle, "angular_duty_cycle")
    clean_axis_duty = _validate_scalar(axis_duty_cycle, "axis_duty_cycle")
    clean_angular_phase = _validate_scalar(angular_phase_degrees, "angular_phase_degrees")
    clean_axis_phase = _validate_scalar(axis_phase, "axis_phase")
    if clean_angular_duty < 0.0 or clean_angular_duty > 1.0:
        raise ValueError("angular_duty_cycle must be between 0 and 1.")
    if clean_axis_duty < 0.0 or clean_axis_duty > 1.0:
        raise ValueError("axis_duty_cycle must be between 0 and 1.")
    max_preview = _validate_int(max_preview, "max_preview", 0)

    shape_name = _mesh_shape(object_name)
    prefix_name = _prefix(shape_name)
    mesh_fn = om.MFnMesh(_dag_path(shape_name))
    om_space = om.MSpace.kWorld if space == "world" else om.MSpace.kObject
    points = mesh_fn.getPoints(om_space)

    matched_ids = []
    records = []
    for component_id in _candidate_ids():
        matched, sample_records = _component_matches(component_id)
        if not matched:
            continue
        matched_ids.append(component_id)
        records.append(
            {
                "component": _component({"vertex": "vtx", "edge": "e", "face": "f"}[clean_result_type], component_id),
                "index": component_id,
                "samples": sample_records[:max_preview],
            }
        )

    kind = {"vertex": "vtx", "edge": "e", "face": "f"}[clean_result_type]
    matched_components = [_component(kind, component_id) for component_id in matched_ids]
    if select_result:
        _apply_selection(matched_components)

    return {
        "success": True,
        "object_name": object_name,
        "shape_name": shape_name,
        "operation": "select_mesh_by_cylindrical_pattern",
        "result_type": clean_result_type,
        "sample_mode": clean_sample_mode,
        "space": space,
        "center": clean_center,
        "axis": clean_axis_name,
        "axis_range": clean_axis_range,
        "angle_range_degrees": clean_angle_range,
        "angle_span_degrees": clean_angle_span,
        "angular_count": clean_angular_count,
        "angular_duty_cycle": clean_angular_duty,
        "angular_phase_degrees": clean_angular_phase,
        "axis_count": clean_axis_count,
        "axis_duty_cycle": clean_axis_duty,
        "axis_phase": clean_axis_phase,
        "invert": bool(invert),
        "matched_count": len(matched_components),
        "components": matched_components[:max_preview],
        "truncated": len(matched_components) > max_preview,
        "selected": bool(select_result),
        "selection_mode": selection_mode if select_result else None,
        "records": records[:max_preview],
        "records_truncated": len(records) > max_preview,
    }
