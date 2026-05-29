from typing import Dict, List, Any


def select_mesh_silhouette_components(
    object_name: str,
    result_type: str = "vertex",
    method: str = "projected_extremes",
    view_direction: List[float] = None,
    camera_name: str = None,
    up_axis: List[float] = None,
    axis: str = None,
    axis_range: List[float] = None,
    box_min: List[float] = None,
    box_max: List[float] = None,
    center: List[float] = None,
    screen_y_range: List[float] = None,
    bin_count: int = 32,
    extreme_sides: List[str] = None,
    extreme_count: int = 1,
    normal_dot_tolerance: float = 0.02,
    include_boundary_edges: bool = True,
    space: str = "world",
    selection_mode: str = "replace",
    select_result: bool = True,
    max_preview: int = 200,
) -> Dict[str, Any]:
    """Select mesh components that define a view-dependent silhouette.

    Methods:
    - projected_extremes: project components into a view plane, split them into
      vertical bins, and select the left/right projected extremes in each bin.
      This matches the common Maya modeling workflow of checking front/side
      outline and moving the visible profile components.
    - normal_edges: select edges whose adjacent face normals cross the view
      direction, optionally including border edges.

    The tool is generic for props, characters, bottles, cars, hard-surface
    panels, icons, and any mesh where view silhouette control matters. It does
    not modify geometry.
    """
    import math
    import re
    import maya.cmds as cmds
    import maya.api.OpenMaya as om

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return int(value)

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(item) for item in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(item) for item in values]

    def _validate_range(values, arg_name):
        clean = _validate_vector(values, 2, arg_name)
        if clean[0] > clean[1]:
            clean = [clean[1], clean[0]]
        if abs(clean[1] - clean[0]) <= 1.0e-12:
            raise ValueError(f"{arg_name} must have non-zero span.")
        return clean

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

    def _dag_path(node):
        selection = om.MSelectionList()
        selection.add(node)
        return selection.getDagPath(0)

    def _mesh_fn(shape):
        return om.MFnMesh(_dag_path(shape))

    def _prefix(shape):
        parents = cmds.listRelatives(shape, parent=True, fullPath=False) or []
        return parents[0] if parents else object_name

    def _normalize_vector(values, arg_name):
        vector = om.MVector(*_validate_vector(values, 3, arg_name))
        length = vector.length()
        if length <= 1.0e-12:
            raise ValueError(f"{arg_name} must not be a zero vector.")
        return vector / length

    def _camera_view_direction(name):
        if not name or not cmds.objExists(name):
            raise ValueError(f"Camera does not exist: {name}")
        node = name
        if cmds.objectType(node) == "camera":
            parents = cmds.listRelatives(node, parent=True, fullPath=True) or []
            if not parents:
                raise ValueError(f"Camera shape has no transform: {name}")
            node = parents[0]
        matrix = _dag_path(node).inclusiveMatrix()
        direction = om.MVector(0.0, 0.0, -1.0) * matrix
        length = direction.length()
        if length <= 1.0e-12:
            raise ValueError(f"Unable to derive view direction from camera: {name}")
        return direction / length

    def _projection_basis():
        view = _camera_view_direction(camera_name) if camera_name else _normalize_vector(clean_view_direction, "view_direction")
        up = _normalize_vector(clean_up_axis, "up_axis")
        up = up - view * (up * view)
        if up.length() <= 1.0e-12:
            raise ValueError("up_axis must not be parallel to view_direction.")
        up.normalize()
        right = view ^ up
        if right.length() <= 1.0e-12:
            raise ValueError("Unable to build a projection basis.")
        right.normalize()
        return view, right, up

    def _point_values(point):
        return [float(point.x), float(point.y), float(point.z)]

    def _point_from_values(values):
        return om.MPoint(float(values[0]), float(values[1]), float(values[2]))

    def _average_points(point_items):
        result = om.MPoint()
        for point in point_items:
            result += point
        return result / float(max(1, len(point_items)))

    def _edge_vertices(edge_id):
        vertices = mesh_fn.getEdgeVertices(int(edge_id))
        return int(vertices[0]), int(vertices[1])

    def _component_center(component_id):
        if clean_result_type == "vertex":
            return points[int(component_id)]
        if clean_result_type == "edge":
            a, b = _edge_vertices(component_id)
            return _average_points([points[a], points[b]])
        vertex_ids = mesh_fn.getPolygonVertices(int(component_id))
        return _average_points([points[int(vertex_id)] for vertex_id in vertex_ids])

    def _component_name(component_id, result_type_name=None):
        kind = {"vertex": "vtx", "edge": "e", "face": "f"}[result_type_name or clean_result_type]
        return f"{prefix_name}.{kind}[{int(component_id)}]"

    def _passes_filters(point):
        values = _point_values(point)
        if clean_box_min is not None:
            for index in range(3):
                if values[index] < clean_box_min[index] - 1.0e-9 or values[index] > clean_box_max[index] + 1.0e-9:
                    return False
        if axis_idx is not None:
            axis_value = values[axis_idx] - clean_center[axis_idx]
            if axis_value < clean_axis_range[0] - 1.0e-9 or axis_value > clean_axis_range[1] + 1.0e-9:
                return False
        return True

    def _component_ids(items, kind):
        pattern = re.compile(rf"\.{kind}\[(\d+)\]$")
        ids = []
        for item in cmds.ls(items, flatten=True) or []:
            match = pattern.search(item)
            if match:
                ids.append(int(match.group(1)))
        return sorted(set(ids))

    def _convert_components(source_items, target_type):
        flags = {
            "vertex": {"toVertex": True},
            "edge": {"toEdge": True},
            "face": {"toFace": True},
        }[target_type]
        converted = cmds.polyListComponentConversion(source_items, **flags) or []
        kind = {"vertex": "vtx", "edge": "e", "face": "f"}[target_type]
        return _component_ids(converted, kind)

    def _candidate_ids_for_result_type():
        total = {
            "vertex": int(mesh_fn.numVertices),
            "edge": int(mesh_fn.numEdges),
            "face": int(mesh_fn.numPolygons),
        }[clean_result_type]
        ids = []
        for component_id in range(total):
            center_point = _component_center(component_id)
            if _passes_filters(center_point):
                ids.append(component_id)
        return ids

    def _projected_extreme_ids():
        candidate_ids = _candidate_ids_for_result_type()
        records = []
        for component_id in candidate_ids:
            point = _component_center(component_id)
            vector = om.MVector(point.x, point.y, point.z)
            screen_x = float(vector * right_axis)
            screen_y = float(vector * up_vector)
            records.append({"id": component_id, "screen_x": screen_x, "screen_y": screen_y})
        if not records:
            return [], []

        if clean_screen_y_range is None:
            y_min = min(record["screen_y"] for record in records)
            y_max = max(record["screen_y"] for record in records)
            if abs(y_max - y_min) <= 1.0e-12:
                y_max = y_min + 1.0
            y_range = [y_min, y_max]
        else:
            y_range = clean_screen_y_range
            records = [record for record in records if y_range[0] - 1.0e-9 <= record["screen_y"] <= y_range[1] + 1.0e-9]
        if not records:
            return [], []

        span = y_range[1] - y_range[0]
        bins = [[] for _ in range(clean_bin_count)]
        for record in records:
            t = (record["screen_y"] - y_range[0]) / span
            index = int(math.floor(t * clean_bin_count))
            index = max(0, min(clean_bin_count - 1, index))
            bins[index].append(record)

        selected = []
        bin_reports = []
        for bin_index, bin_records in enumerate(bins):
            if not bin_records:
                continue
            bin_report = {
                "bin_index": bin_index,
                "screen_y_min": y_range[0] + span * (bin_index / float(clean_bin_count)),
                "screen_y_max": y_range[0] + span * ((bin_index + 1) / float(clean_bin_count)),
                "candidate_count": len(bin_records),
                "selected": [],
            }
            if "left" in clean_extreme_sides:
                for record in sorted(bin_records, key=lambda item: (item["screen_x"], item["id"]))[:clean_extreme_count]:
                    selected.append(record["id"])
                    bin_report["selected"].append({"side": "left", "index": record["id"], "screen_x": record["screen_x"], "screen_y": record["screen_y"]})
            if "right" in clean_extreme_sides:
                for record in sorted(bin_records, key=lambda item: (-item["screen_x"], item["id"]))[:clean_extreme_count]:
                    selected.append(record["id"])
                    bin_report["selected"].append({"side": "right", "index": record["id"], "screen_x": record["screen_x"], "screen_y": record["screen_y"]})
            bin_reports.append(bin_report)
        return sorted(set(selected)), bin_reports

    def _normal_edge_ids():
        edge_ids = []
        edge_reports = []
        edge_iterator = om.MItMeshEdge(_dag_path(shape_name))
        while not edge_iterator.isDone():
            edge_id = int(edge_iterator.index())
            a, b = int(edge_iterator.vertexId(0)), int(edge_iterator.vertexId(1))
            center_point = _average_points([points[a], points[b]])
            if not _passes_filters(center_point):
                edge_iterator.next()
                continue
            try:
                face_ids = [int(face_id) for face_id in edge_iterator.getConnectedFaces()]
            except Exception:
                face_ids = []
            selected = False
            dots = []
            if len(face_ids) < 2:
                selected = bool(include_boundary_edges)
            else:
                for face_id in face_ids[:2]:
                    normal = mesh_fn.getPolygonNormal(face_id, om_space)
                    normal.normalize()
                    dots.append(float(normal * view_vector))
                if dots[0] * dots[1] <= 0.0:
                    selected = True
                elif min(abs(dots[0]), abs(dots[1])) <= clean_normal_dot_tolerance:
                    selected = True
            if selected:
                edge_ids.append(edge_id)
                edge_reports.append({"edge": edge_id, "faces": face_ids, "normal_dots": dots})
            edge_iterator.next()
        if clean_result_type == "edge":
            return edge_ids, edge_reports
        edge_components = [_component_name(edge_id, "edge") for edge_id in edge_ids]
        converted_ids = _convert_components(edge_components, clean_result_type) if edge_components else []
        return converted_ids, edge_reports

    def _apply_selection(component_ids):
        mode = selection_mode.lower().strip()
        if mode not in {"replace", "add", "toggle", "deselect"}:
            raise ValueError("selection_mode must be replace, add, toggle, or deselect.")
        items = [_component_name(component_id) for component_id in component_ids]
        if items:
            cmds.select(items, **{mode: True})
        elif mode == "replace":
            cmds.select(clear=True)

    if not object_name:
        raise ValueError("object_name is required.")
    clean_result_type = (result_type or "").lower().strip()
    if clean_result_type not in {"vertex", "edge", "face"}:
        raise ValueError("result_type must be vertex, edge, or face.")
    clean_method = (method or "").lower().strip()
    if clean_method not in {"projected_extremes", "normal_edges"}:
        raise ValueError("method must be projected_extremes or normal_edges.")
    space = (space or "").lower().strip()
    if space not in {"world", "object"}:
        raise ValueError("space must be world or object.")
    om_space = om.MSpace.kWorld if space == "world" else om.MSpace.kObject
    clean_view_direction = view_direction if view_direction is not None else [0.0, 0.0, -1.0]
    clean_up_axis = up_axis if up_axis is not None else [0.0, 1.0, 0.0]
    clean_center = _validate_vector(center, 3, "center") if center is not None else [0.0, 0.0, 0.0]
    axis_idx = _axis_index(axis) if axis is not None else None
    clean_axis_range = _validate_range(axis_range, "axis_range") if axis_range is not None else None
    if axis_idx is not None and clean_axis_range is None:
        raise ValueError("axis_range is required when axis is provided.")
    if axis_idx is None and clean_axis_range is not None:
        raise ValueError("axis is required when axis_range is provided.")
    clean_box_min = clean_box_max = None
    if box_min is not None or box_max is not None:
        clean_box_min = _validate_vector(box_min, 3, "box_min")
        clean_box_max = _validate_vector(box_max, 3, "box_max")
        for index in range(3):
            if clean_box_min[index] > clean_box_max[index]:
                clean_box_min[index], clean_box_max[index] = clean_box_max[index], clean_box_min[index]
    clean_screen_y_range = _validate_range(screen_y_range, "screen_y_range") if screen_y_range is not None else None
    clean_bin_count = _validate_int(bin_count, "bin_count", 1)
    clean_extreme_count = _validate_int(extreme_count, "extreme_count", 1)
    clean_extreme_sides = [str(item).lower().strip() for item in (extreme_sides or ["left", "right"])]
    if not clean_extreme_sides or any(item not in {"left", "right"} for item in clean_extreme_sides):
        raise ValueError("extreme_sides must contain left and/or right.")
    clean_normal_dot_tolerance = _validate_scalar(normal_dot_tolerance, "normal_dot_tolerance")
    if clean_normal_dot_tolerance < 0.0:
        raise ValueError("normal_dot_tolerance must be greater than or equal to zero.")
    max_preview = _validate_int(max_preview, "max_preview", 0)

    shape_name = _mesh_shape(object_name)
    prefix_name = _prefix(shape_name)
    mesh_fn = _mesh_fn(shape_name)
    points = mesh_fn.getPoints(om_space)
    view_vector, right_axis, up_vector = _projection_basis()

    if clean_method == "projected_extremes":
        result_ids, detail_records = _projected_extreme_ids()
        detail_key = "bins"
    else:
        result_ids, detail_records = _normal_edge_ids()
        detail_key = "edges"

    if select_result:
        _apply_selection(result_ids)

    components = [_component_name(component_id) for component_id in result_ids]
    return {
        "success": True,
        "object_name": object_name,
        "shape_name": shape_name,
        "operation": "select_mesh_silhouette_components",
        "method": clean_method,
        "result_type": clean_result_type,
        "space": space,
        "view_direction": [float(view_vector.x), float(view_vector.y), float(view_vector.z)],
        "up_axis": [float(up_vector.x), float(up_vector.y), float(up_vector.z)],
        "right_axis": [float(right_axis.x), float(right_axis.y), float(right_axis.z)],
        "filters": {
            "axis": axis,
            "axis_range": clean_axis_range,
            "box_min": clean_box_min,
            "box_max": clean_box_max,
            "screen_y_range": clean_screen_y_range,
        },
        "bin_count": clean_bin_count if clean_method == "projected_extremes" else None,
        "extreme_sides": clean_extreme_sides if clean_method == "projected_extremes" else None,
        "extreme_count": clean_extreme_count if clean_method == "projected_extremes" else None,
        "normal_dot_tolerance": clean_normal_dot_tolerance if clean_method == "normal_edges" else None,
        "include_boundary_edges": bool(include_boundary_edges) if clean_method == "normal_edges" else None,
        "component_count": len(components),
        "components": components[:max_preview],
        "indices": result_ids[:max_preview],
        "truncated": len(components) > max_preview,
        "selected": bool(select_result),
        "selection_mode": selection_mode if select_result else None,
        detail_key: detail_records[:max_preview],
        f"{detail_key}_truncated": len(detail_records) > max_preview,
    }
