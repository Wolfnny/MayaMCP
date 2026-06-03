from typing import Dict, List, Any


def map_silhouette_errors_to_components(
    target_objects: List[str],
    row_width_samples: List[Dict[str, Any]],
    candidate_canvas_bbox_pixels: List[float],
    candidate_crop_bbox_pixels: List[float],
    candidate_foreground_bbox_pixels: List[float],
    view_direction: List[float] = None,
    up_axis: List[float] = None,
    camera_center: List[float] = None,
    orthographic_width: float = None,
    image_width: int = 640,
    image_height: int = 960,
    compare_width: int = 256,
    compare_height: int = 512,
    align_mode: str = "bbox",
    padding_fraction: float = 0.04,
    min_abs_error: float = 0.02,
    max_rows: int = 12,
    row_band_pixels: float = 8.0,
    extreme_count: int = 3,
    component_detail: str = "extremes",
    selection_scope: str = "extremes",
    max_components_per_row_object: int = 200,
    side_component_band_world: float = None,
    select_components: bool = False,
    selection_mode: str = "replace",
    max_preview: int = 200,
) -> Dict[str, Any]:
    """Map image silhouette width errors back to Maya mesh components.

    This is a generic bridge between visual QA and component modeling. It takes
    row samples from compare_image_silhouettes plus the candidate playblast
    framing, converts high-error rows back to world-space view bands, and
    reports the left/right projected extreme vertices on the target meshes. It
    helps an artist decide which vertices, edges, support loops, lips, bevels,
    or profile areas to edit after comparing any product, prop, character,
    vehicle, bottle, or other mesh silhouette against a reference image. Rows
    may pass through polygon edges without containing vertices, so the report
    includes both nearby vertices and edge crossings at the sampled row.
    By default the report returns only left/right extreme previews to keep MCP
    payloads small. Set component_detail="all" to include capped per-row vertex
    and crossing-edge component records; set selection_scope="all" to select
    those capped full row component sets instead of just extreme previews.
    Set side_component_band_world to return left/right side component groups
    within a projected world-space distance from each silhouette side, or set
    selection_scope="side" to select those side groups for artist-style local
    silhouette edits. Set selection_scope="side_edge_vertices" to select the
    deduplicated endpoint vertices of the side crossing edges when the sampled
    row cuts through edges rather than landing on vertices. Each mapped row also
    reports suggested world-space move vectors for symmetric width edits and,
    when the row samples include left/right side errors, side-specific
    correction vectors for asymmetric silhouette edits.
    """
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

    def _normalize_vector(values, arg_name):
        vector = om.MVector(*_validate_vector(values, 3, arg_name))
        if vector.length() <= 1.0e-12:
            raise ValueError(f"{arg_name} must not be a zero vector.")
        vector.normalize()
        return vector

    def _projection_frame(view, up):
        clean_up = up - view * (up * view)
        if clean_up.length() <= 1.0e-12:
            raise ValueError("up_axis must not be parallel to view_direction.")
        clean_up.normalize()
        right = view ^ clean_up
        if right.length() <= 1.0e-12:
            raise ValueError("Unable to build a projection frame.")
        right.normalize()
        return right, clean_up

    def _mesh_shape(node):
        if not cmds.objExists(node):
            raise ValueError(f"Target object does not exist: {node}")
        if cmds.objectType(node) == "mesh":
            return node
        shapes = cmds.listRelatives(node, shapes=True, fullPath=True) or []
        meshes = []
        for shape in shapes:
            if cmds.objectType(shape) != "mesh":
                continue
            try:
                if cmds.attributeQuery("intermediateObject", node=shape, exists=True) and cmds.getAttr(f"{shape}.intermediateObject"):
                    continue
            except Exception:
                pass
            meshes.append(shape)
        if not meshes:
            raise ValueError(f"Target object has no visible polygon mesh shape: {node}")
        return meshes[0]

    def _dag_path(node):
        selection = om.MSelectionList()
        selection.add(node)
        return selection.getDagPath(0)

    def _mesh_fn(shape):
        return om.MFnMesh(_dag_path(shape))

    def _component_prefix(shape, fallback):
        parents = cmds.listRelatives(shape, parent=True, fullPath=False) or []
        return parents[0] if parents else fallback

    def _combined_bbox(objects):
        bbox = list(cmds.exactWorldBoundingBox(objects[0]))
        for obj in objects[1:]:
            item = cmds.exactWorldBoundingBox(obj)
            bbox[0] = min(bbox[0], item[0])
            bbox[1] = min(bbox[1], item[1])
            bbox[2] = min(bbox[2], item[2])
            bbox[3] = max(bbox[3], item[3])
            bbox[4] = max(bbox[4], item[4])
            bbox[5] = max(bbox[5], item[5])
        return bbox

    def _bbox_corners(bbox):
        return [
            [bbox[xi], bbox[yi], bbox[zi]]
            for xi in (0, 3)
            for yi in (1, 4)
            for zi in (2, 5)
        ]

    def _camera_width_from_bbox(bbox):
        projected_x = []
        projected_y = []
        for corner in _bbox_corners(bbox):
            point = om.MVector(*corner)
            projected_x.append(float(point * right_axis))
            projected_y.append(float(point * up_vector))
        width = max(1.0e-6, max(projected_x) - min(projected_x))
        height = max(1.0e-6, max(projected_y) - min(projected_y))
        aspect_value = clean_image_width / float(clean_image_height)
        clean_padding = max(0.0, clean_padding_fraction)
        return max(height, width / max(1.0e-6, aspect_value)) * (1.0 + clean_padding * 2.0)

    def _row_value(sample, key, fallback=None):
        value = sample.get(key)
        if value is None:
            return fallback
        return value

    def _source_y_for_row(row_normalized):
        row_canvas = int(round(row_normalized * float(clean_compare_height - 1)))
        canvas_y0, canvas_y1 = clean_candidate_canvas_bbox[1], clean_candidate_canvas_bbox[3]
        if row_canvas < canvas_y0 - 1.0e-9 or row_canvas > canvas_y1 + 1.0e-9:
            return row_canvas, None
        canvas_span = max(1.0e-9, canvas_y1 - canvas_y0)
        t = (row_canvas - canvas_y0) / canvas_span
        if clean_align_mode == "bbox":
            source_y0 = clean_candidate_crop_bbox[1] + clean_candidate_foreground_bbox[1]
            source_y1 = clean_candidate_crop_bbox[1] + clean_candidate_foreground_bbox[3]
        else:
            source_y0 = clean_candidate_crop_bbox[1]
            source_y1 = clean_candidate_crop_bbox[3]
        return row_canvas, source_y0 + t * (source_y1 - source_y0)

    def _world_row_from_source_y(source_y):
        aspect_value = clean_image_width / float(clean_image_height)
        vertical_span = resolved_orthographic_width / max(1.0e-9, aspect_value)
        source_t = source_y / float(max(1, clean_image_height - 1))
        vertical_offset = vertical_span * 0.5 - source_t * vertical_span
        center_vector = om.MVector(*resolved_camera_center)
        return center_vector + up_vector * vertical_offset, vertical_span

    def _world_width_error(signed_error):
        if clean_align_mode == "bbox":
            source_y0 = clean_candidate_foreground_bbox[1]
            source_y1 = clean_candidate_foreground_bbox[3]
        else:
            source_y0 = 0.0
            source_y1 = clean_candidate_crop_bbox[3] - clean_candidate_crop_bbox[1]
        source_region_height = max(1.0, source_y1 - source_y0 + 1.0)
        canvas_height = max(1.0, clean_candidate_canvas_bbox[3] - clean_candidate_canvas_bbox[1] + 1.0)
        compare_pixels = signed_error * float(clean_compare_width)
        source_pixels = compare_pixels * source_region_height / canvas_height
        return source_pixels * resolved_orthographic_width / float(max(1, clean_image_width - 1))

    def _world_error_from_compare_pixels(compare_pixels):
        return _world_width_error(float(compare_pixels) / float(clean_compare_width))

    def _optional_numeric_sample_fields(sample):
        fields = {}
        for key in [
            "left_error_pixels",
            "right_error_pixels",
            "center_error_pixels",
            "left_error_normalized",
            "right_error_normalized",
            "center_error_normalized",
            "reference_left_pixel",
            "reference_right_pixel",
            "candidate_left_pixel",
            "candidate_right_pixel",
            "reference_left_normalized",
            "reference_right_normalized",
            "candidate_left_normalized",
            "candidate_right_normalized",
            "reference_center_pixel",
            "candidate_center_pixel",
            "reference_center_normalized",
            "candidate_center_normalized",
        ]:
            value = sample.get(key)
            if value is None:
                continue
            try:
                fields[key] = float(value)
            except Exception:
                fields[key] = value
        return fields

    def _side_correction_fields(row):
        fields = {}
        for side in ["left", "right"]:
            error_pixels = row.get(f"{side}_error_pixels")
            if error_pixels is None:
                continue
            error_world = _world_error_from_compare_pixels(error_pixels)
            fields[f"{side}_side_error_world"] = float(error_world)
            fields[f"suggested_{side}_side_correction_vector_world"] = [
                float(-right_axis.x * error_world),
                float(-right_axis.y * error_world),
                float(-right_axis.z * error_world),
            ]
        return fields

    def _truncate_records(records, limit):
        if limit == 0:
            return [], bool(records)
        return records[:limit], len(records) > limit

    def _side_record_groups(records):
        if clean_side_component_band_world is None or not records:
            return [], []
        min_screen_x = min(item["screen_x"] for item in records)
        max_screen_x = max(item["screen_x"] for item in records)
        left_records = [
            item for item in records
            if item["screen_x"] <= min_screen_x + clean_side_component_band_world
        ]
        right_records = [
            item for item in records
            if item["screen_x"] >= max_screen_x - clean_side_component_band_world
        ]
        return (
            sorted(left_records, key=lambda item: item["index"]),
            sorted(right_records, key=lambda item: item["index"]),
        )

    def _side_component_records(records):
        if clean_side_component_band_world is None or not records:
            return {
                "left_count": 0,
                "right_count": 0,
                "left_records": [],
                "right_records": [],
                "left_truncated": False,
                "right_truncated": False,
                "left_selection": [],
                "right_selection": [],
            }
        ordered_left, ordered_right = _side_record_groups(records)
        left_details, left_truncated = _truncate_records(ordered_left, clean_max_components_per_row_object)
        right_details, right_truncated = _truncate_records(ordered_right, clean_max_components_per_row_object)
        return {
            "left_count": len(ordered_left),
            "right_count": len(ordered_right),
            "left_records": left_details if clean_component_detail == "all" else [],
            "right_records": right_details if clean_component_detail == "all" else [],
            "left_truncated": left_truncated if clean_component_detail == "all" else False,
            "right_truncated": right_truncated if clean_component_detail == "all" else False,
            "left_selection": [item["component"] for item in left_details],
            "right_selection": [item["component"] for item in right_details],
        }

    def _component_records_for_band(shape, prefix, center_screen_y, band_world):
        mesh_fn = _mesh_fn(shape)
        points = mesh_fn.getPoints(om.MSpace.kWorld)
        lower = center_screen_y - band_world
        upper = center_screen_y + band_world
        records = []
        for vertex_id, point in enumerate(points):
            vector = om.MVector(point.x, point.y, point.z)
            screen_y = float(vector * up_vector)
            if screen_y < lower or screen_y > upper:
                continue
            records.append({
                "index": int(vertex_id),
                "component": f"{prefix}.vtx[{vertex_id}]",
                "position": [float(point.x), float(point.y), float(point.z)],
                "screen_x": float(vector * right_axis),
                "screen_y": screen_y,
            })
        if not records:
            return {
                "candidate_count": 0,
                "left": [],
                "right": [],
                "vertices": [],
                "vertices_truncated": False,
                "left_side_vertex_count": 0,
                "right_side_vertex_count": 0,
                "left_side_vertices": [],
                "right_side_vertices": [],
                "left_side_vertices_truncated": False,
                "right_side_vertices_truncated": False,
                "_selection_vertices": [],
                "_selection_side_vertices": [],
            }
        left = sorted(records, key=lambda item: (item["screen_x"], item["index"]))[:clean_extreme_count]
        right = sorted(records, key=lambda item: (-item["screen_x"], item["index"]))[:clean_extreme_count]
        ordered_records = sorted(records, key=lambda item: item["index"])
        detailed_records, records_truncated = _truncate_records(ordered_records, clean_max_components_per_row_object)
        side_records = _side_component_records(records)
        return {
            "candidate_count": len(records),
            "left": left,
            "right": right,
            "vertices": detailed_records if clean_component_detail == "all" else [],
            "vertices_truncated": records_truncated if clean_component_detail == "all" else False,
            "left_side_vertex_count": side_records["left_count"],
            "right_side_vertex_count": side_records["right_count"],
            "left_side_vertices": side_records["left_records"],
            "right_side_vertices": side_records["right_records"],
            "left_side_vertices_truncated": side_records["left_truncated"],
            "right_side_vertices_truncated": side_records["right_truncated"],
            "_selection_vertices": [item["component"] for item in detailed_records],
            "_selection_side_vertices": side_records["left_selection"] + side_records["right_selection"],
        }

    def _edge_records_for_row(shape, prefix, center_screen_y, band_world):
        mesh_fn = _mesh_fn(shape)
        points = mesh_fn.getPoints(om.MSpace.kWorld)
        lower = center_screen_y - band_world
        upper = center_screen_y + band_world
        edge_it = om.MItMeshEdge(_dag_path(shape))
        records = []
        while not edge_it.isDone():
            edge_id = int(edge_it.index())
            vertex_a = int(edge_it.vertexId(0))
            vertex_b = int(edge_it.vertexId(1))
            point_a = points[vertex_a]
            point_b = points[vertex_b]
            vector_a = om.MVector(point_a.x, point_a.y, point_a.z)
            vector_b = om.MVector(point_b.x, point_b.y, point_b.z)
            screen_y_a = float(vector_a * up_vector)
            screen_y_b = float(vector_b * up_vector)
            edge_min_y = min(screen_y_a, screen_y_b)
            edge_max_y = max(screen_y_a, screen_y_b)
            crosses_center = edge_min_y <= center_screen_y <= edge_max_y
            overlaps_band = edge_max_y >= lower and edge_min_y <= upper
            if not crosses_center and not overlaps_band:
                edge_it.next()
                continue

            if abs(screen_y_b - screen_y_a) <= 1.0e-12:
                if abs(screen_y_a - center_screen_y) > band_world:
                    edge_it.next()
                    continue
                interpolation = 0.5
            else:
                interpolation = (center_screen_y - screen_y_a) / (screen_y_b - screen_y_a)
                interpolation = max(0.0, min(1.0, interpolation))

            point = point_a + (point_b - point_a) * interpolation
            vector = om.MVector(point.x, point.y, point.z)
            records.append(
                {
                    "index": edge_id,
                    "component": f"{prefix}.e[{edge_id}]",
                    "vertices": [vertex_a, vertex_b],
                    "vertex_components": [f"{prefix}.vtx[{vertex_a}]", f"{prefix}.vtx[{vertex_b}]"],
                    "connected_faces": [int(face_id) for face_id in edge_it.getConnectedFaces()],
                    "interpolation": float(interpolation),
                    "position": [float(point.x), float(point.y), float(point.z)],
                    "screen_x": float(vector * right_axis),
                    "screen_y": float(vector * up_vector),
                    "endpoint_screen_y": [screen_y_a, screen_y_b],
                    "crosses_center": bool(crosses_center),
                    "overlaps_band": bool(overlaps_band),
                }
            )
            edge_it.next()
        if not records:
            return {
                "crossing_edge_count": 0,
                "left_edges": [],
                "right_edges": [],
                "crossing_edges": [],
                "crossing_edges_truncated": False,
                "left_side_edge_count": 0,
                "right_side_edge_count": 0,
                "left_side_edges": [],
                "right_side_edges": [],
                "left_side_edges_truncated": False,
                "right_side_edges_truncated": False,
                "left_side_edge_vertex_count": 0,
                "right_side_edge_vertex_count": 0,
                "left_side_edge_vertex_components": [],
                "right_side_edge_vertex_components": [],
                "left_side_edge_vertices": [],
                "right_side_edge_vertices": [],
                "left_side_edge_vertices_truncated": False,
                "right_side_edge_vertices_truncated": False,
                "_selection_edges": [],
                "_selection_side_edges": [],
                "_selection_side_edge_vertices": [],
            }

        def _endpoint_vertex_records(edge_records):
            vertex_records = {}
            for edge_record in edge_records:
                for vertex_id in edge_record["vertices"]:
                    point = points[vertex_id]
                    vector = om.MVector(point.x, point.y, point.z)
                    record = vertex_records.setdefault(
                        vertex_id,
                        {
                            "index": int(vertex_id),
                            "component": f"{prefix}.vtx[{vertex_id}]",
                            "position": [float(point.x), float(point.y), float(point.z)],
                            "screen_x": float(vector * right_axis),
                            "screen_y": float(vector * up_vector),
                            "source_edges": [],
                        },
                    )
                    record["source_edges"].append(int(edge_record["index"]))
            return sorted(vertex_records.values(), key=lambda item: item["index"])

        left_edges = sorted(records, key=lambda item: (item["screen_x"], item["index"]))[:clean_extreme_count]
        right_edges = sorted(records, key=lambda item: (-item["screen_x"], item["index"]))[:clean_extreme_count]
        ordered_records = sorted(records, key=lambda item: item["index"])
        detailed_records, records_truncated = _truncate_records(ordered_records, clean_max_components_per_row_object)
        left_side_edge_records, right_side_edge_records = _side_record_groups(records)
        left_side_edge_vertices = _endpoint_vertex_records(left_side_edge_records)
        right_side_edge_vertices = _endpoint_vertex_records(right_side_edge_records)
        left_side_edge_vertex_details, left_side_edge_vertices_truncated = _truncate_records(
            left_side_edge_vertices,
            clean_max_components_per_row_object,
        )
        right_side_edge_vertex_details, right_side_edge_vertices_truncated = _truncate_records(
            right_side_edge_vertices,
            clean_max_components_per_row_object,
        )
        side_records = _side_component_records(records)
        return {
            "crossing_edge_count": len(records),
            "left_edges": left_edges,
            "right_edges": right_edges,
            "crossing_edges": detailed_records if clean_component_detail == "all" else [],
            "crossing_edges_truncated": records_truncated if clean_component_detail == "all" else False,
            "left_side_edge_count": side_records["left_count"],
            "right_side_edge_count": side_records["right_count"],
            "left_side_edges": side_records["left_records"],
            "right_side_edges": side_records["right_records"],
            "left_side_edges_truncated": side_records["left_truncated"],
            "right_side_edges_truncated": side_records["right_truncated"],
            "left_side_edge_vertex_count": len(left_side_edge_vertices),
            "right_side_edge_vertex_count": len(right_side_edge_vertices),
            "left_side_edge_vertex_components": [item["component"] for item in left_side_edge_vertex_details],
            "right_side_edge_vertex_components": [item["component"] for item in right_side_edge_vertex_details],
            "left_side_edge_vertices": left_side_edge_vertex_details if clean_component_detail == "all" else [],
            "right_side_edge_vertices": right_side_edge_vertex_details if clean_component_detail == "all" else [],
            "left_side_edge_vertices_truncated": left_side_edge_vertices_truncated,
            "right_side_edge_vertices_truncated": right_side_edge_vertices_truncated,
            "_selection_edges": [item["component"] for item in detailed_records],
            "_selection_side_edges": side_records["left_selection"] + side_records["right_selection"],
            "_selection_side_edge_vertices": (
                [item["component"] for item in left_side_edge_vertex_details]
                + [item["component"] for item in right_side_edge_vertex_details]
            ),
        }

    if not target_objects or not isinstance(target_objects, list) or not all(isinstance(item, str) for item in target_objects):
        raise ValueError("target_objects must be a non-empty list of object names.")
    if not isinstance(row_width_samples, list):
        raise ValueError("row_width_samples must be a list of row sample dictionaries.")
    clean_candidate_canvas_bbox = _validate_vector(candidate_canvas_bbox_pixels, 4, "candidate_canvas_bbox_pixels")
    clean_candidate_crop_bbox = _validate_vector(candidate_crop_bbox_pixels, 4, "candidate_crop_bbox_pixels")
    clean_candidate_foreground_bbox = _validate_vector(candidate_foreground_bbox_pixels, 4, "candidate_foreground_bbox_pixels")
    clean_view = _normalize_vector(view_direction if view_direction is not None else [0.0, 0.0, -1.0], "view_direction")
    clean_up = _normalize_vector(up_axis if up_axis is not None else [0.0, 1.0, 0.0], "up_axis")
    right_axis, up_vector = _projection_frame(clean_view, clean_up)
    clean_image_width = _validate_int(image_width, "image_width", 1)
    clean_image_height = _validate_int(image_height, "image_height", 1)
    clean_compare_width = _validate_int(compare_width, "compare_width", 1)
    clean_compare_height = _validate_int(compare_height, "compare_height", 1)
    clean_padding_fraction = _validate_scalar(padding_fraction, "padding_fraction")
    clean_min_abs_error = _validate_scalar(min_abs_error, "min_abs_error")
    clean_max_rows = _validate_int(max_rows, "max_rows", 1)
    clean_row_band_pixels = _validate_scalar(row_band_pixels, "row_band_pixels")
    clean_extreme_count = _validate_int(extreme_count, "extreme_count", 1)
    clean_component_detail = (component_detail or "").lower().strip()
    if clean_component_detail not in {"extremes", "all"}:
        raise ValueError("component_detail must be extremes or all.")
    clean_selection_scope = (selection_scope or "").lower().strip()
    if clean_selection_scope not in {"extremes", "all", "side", "side_edge_vertices"}:
        raise ValueError("selection_scope must be extremes, all, side, or side_edge_vertices.")
    clean_max_components_per_row_object = _validate_int(max_components_per_row_object, "max_components_per_row_object", 0)
    requested_side_component_band_world = None
    if side_component_band_world is not None:
        requested_side_component_band_world = _validate_scalar(side_component_band_world, "side_component_band_world")
        if requested_side_component_band_world < 0.0:
            raise ValueError("side_component_band_world must be greater than or equal to zero.")
    max_preview = _validate_int(max_preview, "max_preview", 0)
    clean_align_mode = (align_mode or "").lower().strip()
    if clean_align_mode not in {"bbox", "crop"}:
        raise ValueError("align_mode must be bbox or crop.")
    clean_selection_mode = (selection_mode or "").lower().strip()
    if clean_selection_mode not in {"replace", "add", "toggle", "deselect"}:
        raise ValueError("selection_mode must be replace, add, toggle, or deselect.")

    shapes = []
    resolved_targets = []
    seen = set()
    for obj in target_objects:
        if obj in seen:
            continue
        seen.add(obj)
        shape = _mesh_shape(obj)
        shapes.append({"object_name": obj, "shape_name": shape, "prefix": _component_prefix(shape, obj)})
        resolved_targets.append(obj)
    bbox = _combined_bbox(resolved_targets)
    if camera_center is None:
        resolved_camera_center = [
            (bbox[0] + bbox[3]) * 0.5,
            (bbox[1] + bbox[4]) * 0.5,
            (bbox[2] + bbox[5]) * 0.5,
        ]
    else:
        resolved_camera_center = _validate_vector(camera_center, 3, "camera_center")
    if orthographic_width is None:
        resolved_orthographic_width = _camera_width_from_bbox(bbox)
    else:
        resolved_orthographic_width = _validate_scalar(orthographic_width, "orthographic_width")
        if resolved_orthographic_width <= 0.0:
            raise ValueError("orthographic_width must be greater than zero.")

    rows = []
    for sample in row_width_samples:
        if not isinstance(sample, dict):
            continue
        row_normalized = _row_value(sample, "row_normalized", sample.get("row_fraction"))
        if row_normalized is None:
            continue
        signed_error = _row_value(sample, "signed_error", sample.get("signed_width_error"))
        if signed_error is None:
            reference_width = sample.get("reference_width")
            candidate_width = sample.get("candidate_width")
            if reference_width is None or candidate_width is None:
                continue
            signed_error = float(candidate_width) - float(reference_width)
        row_normalized = float(row_normalized)
        signed_error = float(signed_error)
        abs_error = abs(float(sample.get("abs_error", abs(signed_error))))
        if abs_error < clean_min_abs_error:
            continue
        row_record = {
            "row_normalized": row_normalized,
            "reference_width": sample.get("reference_width"),
            "candidate_width": sample.get("candidate_width"),
            "signed_error": signed_error,
            "abs_error": abs_error,
        }
        row_record.update(_optional_numeric_sample_fields(sample))
        rows.append(row_record)
    rows = sorted(rows, key=lambda item: item["abs_error"], reverse=True)[:clean_max_rows]

    world_units_per_image_pixel = resolved_orthographic_width / float(max(1, clean_image_width - 1))
    band_world = max(0.0, clean_row_band_pixels) * world_units_per_image_pixel
    clean_side_component_band_world = requested_side_component_band_world
    if clean_side_component_band_world is None and clean_selection_scope in {"side", "side_edge_vertices"}:
        clean_side_component_band_world = band_world
    mapped_rows = []
    selected_components = []
    for row in rows:
        row_canvas, source_y = _source_y_for_row(row["row_normalized"])
        if source_y is None:
            mapped_rows.append({
                **row,
                "row_canvas_pixel": row_canvas,
                "mapped": False,
                "reason": "row is outside candidate_canvas_bbox_pixels",
            })
            continue
        world_point, vertical_span = _world_row_from_source_y(source_y)
        center_screen_y = float(world_point * up_vector)
        width_error_world = _world_width_error(row["signed_error"])
        side_offset_world = -0.5 * width_error_world
        left_side_move_vector = [
            float(-right_axis.x * side_offset_world),
            float(-right_axis.y * side_offset_world),
            float(-right_axis.z * side_offset_world),
        ]
        right_side_move_vector = [
            float(right_axis.x * side_offset_world),
            float(right_axis.y * side_offset_world),
            float(right_axis.z * side_offset_world),
        ]
        object_reports = []
        for shape_info in shapes:
            report = _component_records_for_band(shape_info["shape_name"], shape_info["prefix"], center_screen_y, band_world)
            edge_report = _edge_records_for_row(shape_info["shape_name"], shape_info["prefix"], center_screen_y, band_world)
            if max_preview == 0:
                report["left"] = []
                report["right"] = []
                edge_report["left_edges"] = []
                edge_report["right_edges"] = []
            else:
                report["left"] = report["left"][:max_preview]
                report["right"] = report["right"][:max_preview]
                edge_report["left_edges"] = edge_report["left_edges"][:max_preview]
                edge_report["right_edges"] = edge_report["right_edges"][:max_preview]
            if clean_selection_scope == "all":
                selected_components.extend(report["_selection_vertices"])
                selected_components.extend(edge_report["_selection_edges"])
            elif clean_selection_scope == "side":
                selected_components.extend(report["_selection_side_vertices"])
                selected_components.extend(edge_report["_selection_side_edges"])
            elif clean_selection_scope == "side_edge_vertices":
                selected_components.extend(edge_report["_selection_side_edge_vertices"])
            else:
                selected_components.extend(item["component"] for item in report["left"])
                selected_components.extend(item["component"] for item in report["right"])
                selected_components.extend(item["component"] for item in edge_report["left_edges"])
                selected_components.extend(item["component"] for item in edge_report["right_edges"])
            report.pop("_selection_vertices", None)
            report.pop("_selection_side_vertices", None)
            edge_report.pop("_selection_edges", None)
            edge_report.pop("_selection_side_edges", None)
            edge_report.pop("_selection_side_edge_vertices", None)
            object_reports.append({
                "object_name": shape_info["object_name"],
                "shape_name": shape_info["shape_name"],
                **report,
                **edge_report,
            })
        mapped_row = {
            **row,
            "mapped": True,
            "row_canvas_pixel": row_canvas,
            "candidate_source_y_pixel": float(source_y),
            "world_row_center": [float(world_point.x), float(world_point.y), float(world_point.z)],
            "screen_y": center_screen_y,
            "screen_y_band": [center_screen_y - band_world, center_screen_y + band_world],
            "world_width_error_estimate": float(width_error_world),
            "suggested_symmetric_side_offset_world": float(side_offset_world),
            "suggested_left_side_move_vector_world": left_side_move_vector,
            "suggested_right_side_move_vector_world": right_side_move_vector,
            "object_reports": object_reports,
        }
        mapped_row.update(_side_correction_fields(row))
        mapped_rows.append(mapped_row)

    unique_selected = list(dict.fromkeys(selected_components))
    if select_components:
        if unique_selected:
            cmds.select(unique_selected, **{clean_selection_mode: True})
        elif clean_selection_mode == "replace":
            cmds.select(clear=True)

    return {
        "success": True,
        "target_objects": resolved_targets,
        "view_direction": [float(clean_view.x), float(clean_view.y), float(clean_view.z)],
        "up_axis": [float(up_vector.x), float(up_vector.y), float(up_vector.z)],
        "right_axis": [float(right_axis.x), float(right_axis.y), float(right_axis.z)],
        "camera_center": resolved_camera_center,
        "orthographic_width": float(resolved_orthographic_width),
        "image_width": clean_image_width,
        "image_height": clean_image_height,
        "compare_width": clean_compare_width,
        "compare_height": clean_compare_height,
        "candidate_canvas_bbox_pixels": clean_candidate_canvas_bbox,
        "candidate_crop_bbox_pixels": clean_candidate_crop_bbox,
        "candidate_foreground_bbox_pixels": clean_candidate_foreground_bbox,
        "align_mode": clean_align_mode,
        "min_abs_error": clean_min_abs_error,
        "row_band_pixels": clean_row_band_pixels,
        "row_band_world": float(band_world),
        "component_detail": clean_component_detail,
        "selection_scope": clean_selection_scope,
        "max_components_per_row_object": clean_max_components_per_row_object,
        "side_component_band_world": clean_side_component_band_world,
        "world_units_per_image_pixel": float(world_units_per_image_pixel),
        "error_row_count": len(rows),
        "mapped_row_count": sum(1 for row in mapped_rows if row.get("mapped")),
        "selected_component_count": len(unique_selected),
        "selected_components": unique_selected[:max_preview],
        "selection_truncated": len(unique_selected) > max_preview,
        "selected": bool(select_components),
        "selection_mode": clean_selection_mode if select_components else None,
        "rows": mapped_rows,
    }
