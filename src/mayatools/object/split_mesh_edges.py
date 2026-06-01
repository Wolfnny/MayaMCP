from typing import Any, Dict, List, Union


def split_mesh_edges(
    object_name: str,
    component_type: str = "edge",
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    split_count: int = 1,
    ratio: float = 0.5,
    ratios: List[float] = None,
    position_mode: str = "ratio",
    axis: str = None,
    target_value: float = None,
    filter_to_spanning_edges: bool = True,
    connect_new_vertices: bool = False,
    construction_history: bool = False,
    space: str = "world",
    use_selection: bool = True,
    select_result: bool = True,
    max_preview: int = 100,
) -> Dict[str, Any]:
    """Split selected polygon edges and optionally place new vertices at exact ratios or coordinates.

    Position modes:
    - even: keep Maya's evenly spaced split vertices
    - ratio: split each edge once and move the new vertex to ratio along the original edge
    - ratios: split each edge at every ratio in ratios
    - axis_value: split only edges crossing target_value on axis and place the new vertex there

    This is a generic Maya-style component modeling operation for adding local
    control vertices or support points before manual silhouette, crease, weld,
    or cleanup work. It reports the original edges, new vertices, coordinate
    changes, mesh count deltas, and n-gon count changes. Enable
    connect_new_vertices to ask Maya to connect the newly created vertices after
    splitting, which can reduce n-gons when selected split points share faces.
    """
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

    def _validate_ratio(value, arg_name):
        clean = _validate_scalar(value, arg_name)
        if clean <= 0.0 or clean >= 1.0:
            raise ValueError(f"{arg_name} must be greater than 0.0 and less than 1.0.")
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

    def _resolve_edges():
        clean_type = (component_type or "edge").lower().strip()
        kind_map = {"vertex": "vtx", "edge": "e", "face": "f", "uv": "map", "vertex_face": "vtxFace"}
        if components is not None:
            resolved = _flatten(components)
        elif clean_type in kind_map and indices is not None:
            resolved = _components_from_indices(kind_map[clean_type])
        else:
            resolved = _selected_components()
        if not resolved:
            raise ValueError("No components resolved from components, indices, or current selection.")
        edges = cmds.polyListComponentConversion(resolved, toEdge=True) or []
        return _unique(edges)

    def _counts():
        return {
            "vertices": int(cmds.polyEvaluate(object_name, vertex=True)),
            "edges": int(cmds.polyEvaluate(object_name, edge=True)),
            "faces": int(cmds.polyEvaluate(object_name, face=True)),
        }

    def _ngon_faces():
        faces = []
        face_total = int(cmds.polyEvaluate(object_name, face=True))
        for face_id in range(face_total):
            info = (cmds.polyInfo(f"{prefix_name}.f[{face_id}]", faceToVertex=True) or [""])[0]
            numbers = [int(value) for value in re.findall(r"\d+", info)]
            vertex_count = max(0, len(numbers) - 1)
            if vertex_count > 4:
                faces.append(f"{prefix_name}.f[{face_id}]")
        return faces

    def _point_values(point):
        return [float(point.x), float(point.y), float(point.z)]

    def _interpolate(point_a, point_b, amount):
        return [
            float(point_a[index] + (point_b[index] - point_a[index]) * amount)
            for index in range(3)
        ]

    def _distance_to_segment_sq(point, start, end):
        vx = end[0] - start[0]
        vy = end[1] - start[1]
        vz = end[2] - start[2]
        wx = point[0] - start[0]
        wy = point[1] - start[1]
        wz = point[2] - start[2]
        length_sq = vx * vx + vy * vy + vz * vz
        if length_sq <= 1.0e-24:
            return 0.0, wx * wx + wy * wy + wz * wz
        amount = max(0.0, min(1.0, (wx * vx + wy * vy + wz * vz) / length_sq))
        closest = _interpolate(start, end, amount)
        dx = point[0] - closest[0]
        dy = point[1] - closest[1]
        dz = point[2] - closest[2]
        return amount, dx * dx + dy * dy + dz * dz

    def _target_ratios_for_edge(edge_record, current_count):
        if clean_position_mode == "even":
            return None
        if clean_position_mode == "ratio":
            return [clean_ratio]
        if clean_position_mode == "ratios":
            return clean_ratios
        if clean_position_mode == "axis_value":
            axis_delta = edge_record["end"][axis_idx] - edge_record["start"][axis_idx]
            if abs(axis_delta) <= 1.0e-12:
                return None
            amount = (clean_target_value - edge_record["start"][axis_idx]) / axis_delta
            if amount <= 0.0 or amount >= 1.0:
                return None
            return [float(amount)]
        return None

    def _edge_spans_axis_value(edge_record):
        low = min(edge_record["start"][axis_idx], edge_record["end"][axis_idx])
        high = max(edge_record["start"][axis_idx], edge_record["end"][axis_idx])
        return low < clean_target_value < high

    def _assign_new_vertices_to_edges(new_vertex_ids, edge_records, mesh_points):
        groups = {record["edge_id"]: [] for record in edge_records}
        for vertex_id in new_vertex_ids:
            point = _point_values(mesh_points[vertex_id])
            best_record = None
            best_amount = 0.0
            best_distance = None
            for record in edge_records:
                amount, distance = _distance_to_segment_sq(point, record["start"], record["end"])
                if best_distance is None or distance < best_distance:
                    best_record = record
                    best_amount = amount
                    best_distance = distance
            if best_record is not None:
                groups[best_record["edge_id"]].append(
                    {
                        "vertex_id": vertex_id,
                        "initial_ratio": float(best_amount),
                        "initial_position": point,
                    }
                )
        for edge_id, items in groups.items():
            items.sort(key=lambda item: item["initial_ratio"])
        return groups

    if not object_name:
        raise ValueError("object_name is required.")
    clean_position_mode = (position_mode or "ratio").lower().strip()
    if clean_position_mode not in {"even", "ratio", "ratios", "axis_value"}:
        raise ValueError("position_mode must be even, ratio, ratios, or axis_value.")
    clean_split_count = _validate_int(split_count, "split_count", 1)
    max_preview = _validate_int(max_preview, "max_preview", 1)
    clean_ratio = _validate_ratio(ratio, "ratio")
    clean_ratios = None
    axis_idx = None
    clean_target_value = None

    if clean_position_mode == "ratio":
        if clean_split_count != 1:
            raise ValueError("position_mode=ratio requires split_count=1. Use position_mode=ratios for multiple split points.")
    elif clean_position_mode == "ratios":
        if ratios is None or not isinstance(ratios, list) or not ratios:
            raise ValueError("position_mode=ratios requires a non-empty ratios list.")
        clean_ratios = sorted(_validate_ratio(item, f"ratios[{index}]") for index, item in enumerate(ratios))
        if len(set(clean_ratios)) != len(clean_ratios):
            raise ValueError("ratios values must be unique.")
        clean_split_count = len(clean_ratios)
    elif clean_position_mode == "axis_value":
        clean_split_count = 1
        axis_idx = _axis_index(axis)
        clean_target_value = _validate_scalar(target_value, "target_value")

    clean_space = (space or "world").lower().strip()
    if clean_space not in {"world", "object"}:
        raise ValueError("space must be world or object.")
    om_space = om.MSpace.kWorld if clean_space == "world" else om.MSpace.kObject

    shape_name = _mesh_shape(object_name)
    prefix_name = _prefix(shape_name)
    mesh_fn = om.MFnMesh(_dag_path(shape_name))
    before_counts = _counts()
    ngon_faces_before = _ngon_faces()
    before_points = mesh_fn.getPoints(om_space)

    resolved_edges = _resolve_edges()
    edge_ids = _component_ids(resolved_edges, "e")
    if not edge_ids:
        raise ValueError("No edge components resolved.")

    edge_records = []
    for edge_id in edge_ids:
        vertex_a, vertex_b = mesh_fn.getEdgeVertices(edge_id)
        record = {
            "edge_id": int(edge_id),
            "component": f"{prefix_name}.e[{edge_id}]",
            "vertex_ids": [int(vertex_a), int(vertex_b)],
            "start": _point_values(before_points[vertex_a]),
            "end": _point_values(before_points[vertex_b]),
        }
        edge_records.append(record)

    skipped_edges = []
    if clean_position_mode == "axis_value" and filter_to_spanning_edges:
        filtered_records = []
        for record in edge_records:
            if _edge_spans_axis_value(record):
                filtered_records.append(record)
            else:
                skipped_edges.append(record)
        edge_records = filtered_records
        if not edge_records:
            raise ValueError("No resolved edges cross target_value on the requested axis.")

    split_edges = [record["component"] for record in edge_records]
    node = cmds.polySubdivideEdge(
        split_edges,
        constructionHistory=bool(construction_history),
        divisions=clean_split_count,
    )

    after_counts = _counts()
    if after_counts["vertices"] <= before_counts["vertices"]:
        raise RuntimeError("split_mesh_edges did not create new vertices.")

    mesh_fn = om.MFnMesh(_dag_path(shape_name))
    new_vertex_ids = list(range(before_counts["vertices"], after_counts["vertices"]))
    after_points = mesh_fn.getPoints(om_space)
    groups = _assign_new_vertices_to_edges(new_vertex_ids, edge_records, after_points)

    edited_vertices = []
    output_points = mesh_fn.getPoints(om_space)
    for record in edge_records:
        items = groups.get(record["edge_id"], [])
        target_ratios = _target_ratios_for_edge(record, len(items))
        if target_ratios is None:
            continue
        if len(items) != len(target_ratios):
            raise RuntimeError(
                f"Expected {len(target_ratios)} new vertices for edge {record['edge_id']} but found {len(items)}."
            )
        for item, amount in zip(items, target_ratios):
            vertex_id = item["vertex_id"]
            before = _point_values(output_points[vertex_id])
            target = _interpolate(record["start"], record["end"], amount)
            output_points[vertex_id] = om.MPoint(target[0], target[1], target[2])
            edited_vertices.append(
                {
                    "index": int(vertex_id),
                    "component": f"{prefix_name}.vtx[{vertex_id}]",
                    "source_edge": record["component"],
                    "target_ratio": float(amount),
                    "before": before,
                    "after": target,
                }
            )

    if edited_vertices:
        mesh_fn.setPoints(output_points, om_space)
        try:
            mesh_fn.updateSurface()
        except Exception:
            pass

    result_vertices = [f"{prefix_name}.vtx[{index}]" for index in new_vertex_ids]
    connect_node = None
    if connect_new_vertices and result_vertices:
        cmds.select(result_vertices, replace=True)
        connect_node = cmds.polyConnectComponents(
            constructionHistory=bool(construction_history),
        )
        mesh_fn = om.MFnMesh(_dag_path(shape_name))
        after_counts = _counts()

    if select_result:
        cmds.select(result_vertices, replace=True)

    ngon_faces_after = _ngon_faces()
    before_ngon_set = set(ngon_faces_before)
    new_ngons = [face for face in ngon_faces_after if face not in before_ngon_set]

    return {
        "success": True,
        "object_name": object_name,
        "operation": "split_mesh_edges",
        "position_mode": clean_position_mode,
        "node": node,
        "connect_new_vertices": bool(connect_new_vertices),
        "connect_node": connect_node,
        "space": clean_space,
        "split_count": clean_split_count,
        "input_edge_count": len(edge_ids),
        "split_edge_count": len(edge_records),
        "skipped_edge_count": len(skipped_edges),
        "input_edges_preview": [record["component"] for record in edge_records[:max_preview]],
        "skipped_edges_preview": [record["component"] for record in skipped_edges[:max_preview]],
        "new_vertex_count": len(new_vertex_ids),
        "new_vertices_preview": result_vertices[:max_preview],
        "edited_vertex_count": len(edited_vertices),
        "edited_vertices_preview": edited_vertices[:max_preview],
        "counts_before": before_counts,
        "counts_after": after_counts,
        "ngon_count_before": len(ngon_faces_before),
        "ngon_count_after": len(ngon_faces_after),
        "new_ngon_count_delta": len(new_ngons),
        "new_ngons_preview": new_ngons[:max_preview],
        "new_vertex_count_delta": after_counts["vertices"] - before_counts["vertices"],
        "new_edge_count_delta": after_counts["edges"] - before_counts["edges"],
        "new_face_count_delta": after_counts["faces"] - before_counts["faces"],
    }
