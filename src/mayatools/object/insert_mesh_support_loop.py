from typing import Dict, List, Any, Union


def insert_mesh_support_loop(
    object_name: str,
    component_type: str = "edge",
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    expand: str = "edge_ring",
    axis: str = None,
    target_value: float = None,
    offset: float = 0.0,
    position_mode: str = "centered",
    insert_with_edge_flow: bool = False,
    adjust_edge_flow: float = 0.0,
    construction_history: bool = False,
    space: str = "world",
    validate_quality: bool = False,
    rollback_on_quality_error: bool = True,
    quality_issue_types: List[str] = None,
    area_epsilon: float = 1.0e-8,
    edge_length_epsilon: float = 1.0e-5,
    face_aspect_threshold: float = 20.0,
    use_selection: bool = True,
    select_result: bool = True,
    result_type: str = "vertex",
    max_preview: int = 100,
) -> Dict[str, Any]:
    """Insert one support loop from seed edges and report the new components.

    Position modes:
    - centered: keep Maya's inserted loop at the default connected position
    - axis_value: move the new vertices to target_value along axis
    - axis_offset: add offset to the new vertices along axis

    This wraps Maya's component-level edge-ring connect operation for common
    artist modeling work: adding a support loop, immediately selecting the new
    loop, and optionally aligning it to a precise coordinate for lips, seams,
    shoulder breaks, panel borders, hard-surface bevel support, or gridded mesh
    cleanup. Optional quality validation compares mesh issue counts before and
    after the edit and can automatically roll back support loops that create
    new short edges, zero-area faces, lamina faces, invalid components, or other
    requested topology problems.
    """
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

    def _resolve_edges():
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
        edges = cmds.polyListComponentConversion(resolved, toEdge=True) or []
        edges = cmds.ls(edges, flatten=True) or []
        if not edges:
            raise ValueError("Support loop insertion requires edge components or components convertible to edges.")
        return _unique(edges)

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

    def _expanded_edges(edge_items):
        clean_expand = expand.lower().strip()
        if clean_expand == "none":
            return edge_items
        flag_map = {
            "edge_ring": "edgeRing",
            "edge_loop": "edgeLoop",
            "edge_loop_or_border": "edgeLoopOrBorder",
            "edge_border": "edgeBorder",
        }
        if clean_expand not in flag_map:
            raise ValueError("expand must be none, edge_ring, edge_loop, edge_loop_or_border, or edge_border.")
        edge_ids = _component_ids(edge_items, "e")
        results = []
        for edge_id in edge_ids:
            output = cmds.polySelect(
                object_name,
                asSelectString=True,
                noSelection=True,
                **{flag_map[clean_expand]: int(edge_id)},
            ) or []
            results.extend(output)
        expanded = _unique(results)
        return expanded or edge_items

    def _counts():
        return {
            "vertices": int(cmds.polyEvaluate(object_name, vertex=True)),
            "edges": int(cmds.polyEvaluate(object_name, edge=True)),
            "faces": int(cmds.polyEvaluate(object_name, face=True)),
        }

    def _point_values(point):
        return [float(point.x), float(point.y), float(point.z)]

    def _set_new_vertex_positions(vertex_ids):
        if clean_position_mode == "centered":
            return []
        axis_idx = _axis_index(axis)
        points = mesh_fn.getPoints(om_space)
        before_after = []
        for vertex_id in vertex_ids:
            before = _point_values(points[vertex_id])
            after = before[:]
            if clean_position_mode == "axis_value":
                after[axis_idx] = clean_target_value
            else:
                after[axis_idx] += clean_offset
            points[vertex_id] = om.MPoint(after[0], after[1], after[2])
            before_after.append(
                {
                    "index": vertex_id,
                    "component": f"{prefix_name}.vtx[{vertex_id}]",
                    "before": before,
                    "after": after,
                }
            )
        mesh_fn.setPoints(points, om_space)
        try:
            mesh_fn.updateSurface()
        except Exception:
            pass
        return before_after

    def _components_from_range(kind, start, end):
        if end <= start:
            return []
        return [f"{prefix_name}.{kind}[{index}]" for index in range(start, end)]

    def _select_components(items):
        if items:
            cmds.select(items, replace=True)
        elif result_type.lower().strip() == "vertex":
            cmds.select(clear=True)

    def _poly_info_count(flag_name):
        flag_map = {
            "nonmanifold_edges": {"nonManifoldEdges": True},
            "nonmanifold_vertices": {"nonManifoldVertices": True},
            "lamina_faces": {"laminaFaces": True},
            "invalid_edges": {"invalidEdges": True},
            "invalid_vertices": {"invalidVertices": True},
        }
        lines = cmds.polyInfo(object_name, **flag_map[flag_name]) or []
        components = []
        for line in lines:
            components.extend(re.findall(r"\S+\.(?:e|f|vtx)\[\d+(?::\d+)?\]", line))
        return len(set(cmds.ls(components, flatten=True) or []))

    def _edge_length(mesh_points, vertex_a, vertex_b):
        point_a = mesh_points[int(vertex_a)]
        point_b = mesh_points[int(vertex_b)]
        return float(
            (
                (point_a.x - point_b.x) ** 2
                + (point_a.y - point_b.y) ** 2
                + (point_a.z - point_b.z) ** 2
            )
            ** 0.5
        )

    def _face_aspect(face_vertex_ids, mesh_points):
        lengths = []
        vertex_count = len(face_vertex_ids)
        for index in range(vertex_count):
            vertex_a = face_vertex_ids[index]
            vertex_b = face_vertex_ids[(index + 1) % vertex_count]
            lengths.append(_edge_length(mesh_points, vertex_a, vertex_b))
        nonzero = [length for length in lengths if length > 1.0e-12]
        if not nonzero:
            return float("inf")
        return max(nonzero) / max(1.0e-12, min(nonzero))

    def _quality_counts(issue_types_to_check):
        issue_counts = {}
        current_shape = _mesh_shape(object_name)
        current_dag_path = _dag_path(current_shape)
        current_mesh_fn = om.MFnMesh(current_dag_path)
        mesh_points = current_mesh_fn.getPoints(om_space)

        if "short_edges" in issue_types_to_check:
            count = 0
            edge_it = om.MItMeshEdge(current_dag_path)
            while not edge_it.isDone():
                vertex_a, vertex_b = current_mesh_fn.getEdgeVertices(int(edge_it.index()))
                if _edge_length(mesh_points, vertex_a, vertex_b) <= clean_edge_length_epsilon:
                    count += 1
                edge_it.next()
            issue_counts["short_edges"] = count

        for poly_info_type in ["nonmanifold_edges", "nonmanifold_vertices", "lamina_faces", "invalid_edges", "invalid_vertices"]:
            if poly_info_type in issue_types_to_check:
                issue_counts[poly_info_type] = _poly_info_count(poly_info_type)

        polygon_it = om.MItMeshPolygon(current_dag_path)
        zero_area_count = 0
        skinny_count = 0
        while not polygon_it.isDone():
            face_id = int(polygon_it.index())
            face_area = float(polygon_it.getArea(om_space))
            face_vertex_ids = current_mesh_fn.getPolygonVertices(face_id)
            if "zero_area_faces" in issue_types_to_check and (polygon_it.zeroArea() or face_area <= clean_area_epsilon):
                zero_area_count += 1
            if "skinny_faces" in issue_types_to_check and _face_aspect(face_vertex_ids, mesh_points) >= clean_face_aspect_threshold:
                skinny_count += 1
            polygon_it.next()

        if "zero_area_faces" in issue_types_to_check:
            issue_counts["zero_area_faces"] = zero_area_count
        if "skinny_faces" in issue_types_to_check:
            issue_counts["skinny_faces"] = skinny_count

        return issue_counts

    def _quality_report(before_counts, after_counts):
        issues = []
        deltas = {}
        for issue_type in clean_quality_issue_types:
            before_count = int(before_counts.get(issue_type, 0))
            after_count = int(after_counts.get(issue_type, 0))
            delta = after_count - before_count
            deltas[issue_type] = delta
            if delta > 0:
                issues.append(
                    {
                        "issue_type": issue_type,
                        "before": before_count,
                        "after": after_count,
                        "delta": delta,
                    }
                )
        return {
            "checked": True,
            "passed": not issues,
            "issues": issues,
            "counts_before": before_counts,
            "counts_after": after_counts,
            "deltas": deltas,
        }

    if not object_name:
        raise ValueError("object_name is required.")
    clean_position_mode = position_mode.lower().strip()
    if clean_position_mode not in {"centered", "axis_value", "axis_offset"}:
        raise ValueError("position_mode must be centered, axis_value, or axis_offset.")
    if clean_position_mode in {"axis_value", "axis_offset"} and axis is None:
        raise ValueError("axis is required when position_mode is axis_value or axis_offset.")
    clean_target_value = _validate_scalar(target_value, "target_value") if clean_position_mode == "axis_value" else None
    clean_offset = _validate_scalar(offset, "offset")
    adjust_edge_flow = _validate_scalar(adjust_edge_flow, "adjust_edge_flow")
    clean_validate_quality = _validate_bool(validate_quality, "validate_quality")
    clean_rollback_on_quality_error = _validate_bool(rollback_on_quality_error, "rollback_on_quality_error")
    clean_area_epsilon = _validate_scalar(area_epsilon, "area_epsilon")
    if clean_area_epsilon < 0.0:
        raise ValueError("area_epsilon must be greater than or equal to zero.")
    clean_edge_length_epsilon = _validate_scalar(edge_length_epsilon, "edge_length_epsilon")
    if clean_edge_length_epsilon < 0.0:
        raise ValueError("edge_length_epsilon must be greater than or equal to zero.")
    clean_face_aspect_threshold = _validate_scalar(face_aspect_threshold, "face_aspect_threshold")
    if clean_face_aspect_threshold < 1.0:
        raise ValueError("face_aspect_threshold must be greater than or equal to 1.")
    max_preview = _validate_int(max_preview, "max_preview", 1)
    clean_result_type = result_type.lower().strip()
    if clean_result_type not in {"vertex", "edge", "face"}:
        raise ValueError("result_type must be vertex, edge, or face.")
    all_quality_issue_types = [
        "short_edges",
        "zero_area_faces",
        "lamina_faces",
        "invalid_edges",
        "invalid_vertices",
        "nonmanifold_edges",
        "nonmanifold_vertices",
        "skinny_faces",
    ]
    if quality_issue_types is None:
        clean_quality_issue_types = ["short_edges", "zero_area_faces", "lamina_faces", "invalid_edges", "invalid_vertices"]
    else:
        if not isinstance(quality_issue_types, list) or not all(isinstance(item, str) for item in quality_issue_types):
            raise ValueError("quality_issue_types must be a list of strings or None.")
        clean_quality_issue_types = [item.lower().strip() for item in quality_issue_types]
        unknown = sorted(set(clean_quality_issue_types) - set(all_quality_issue_types))
        if unknown:
            raise ValueError(f"Unknown quality_issue_types: {unknown}.")
    space = space.lower().strip()
    if space not in {"world", "object"}:
        raise ValueError("space must be world or object.")

    shape_name = _mesh_shape(object_name)
    prefix_name = _prefix(shape_name)
    dag_path = _dag_path(shape_name)
    mesh_fn = om.MFnMesh(dag_path)
    om_space = om.MSpace.kWorld if space == "world" else om.MSpace.kObject
    before = _counts()
    quality_before = _quality_counts(clean_quality_issue_types) if clean_validate_quality else None

    seed_edges = _resolve_edges()
    target_edges = _expanded_edges(seed_edges)
    if len(target_edges) < 2:
        raise ValueError("At least two resolved edges are required to insert a support loop.")

    scene_modified_before = bool(cmds.file(query=True, modified=True))
    old_selection = cmds.ls(selection=True, flatten=True) or []
    undo_chunk_open = False
    def _close_undo_chunk():
        nonlocal undo_chunk_open
        if undo_chunk_open:
            cmds.undoInfo(closeChunk=True)
            undo_chunk_open = False

    if clean_validate_quality and clean_rollback_on_quality_error:
        cmds.undoInfo(openChunk=True, chunkName="insertMeshSupportLoopValidated")
        undo_chunk_open = True
    cmds.select(target_edges, replace=True)
    try:
        node = cmds.polyConnectComponents(
            constructionHistory=construction_history,
            insertWithEdgeFlow=bool(insert_with_edge_flow),
            adjustEdgeFlow=adjust_edge_flow,
        )
    except Exception:
        _close_undo_chunk()
        raise
    finally:
        if old_selection:
            cmds.select(old_selection, replace=True)
        else:
            cmds.select(clear=True)

    after = _counts()
    if after["vertices"] <= before["vertices"] or after["edges"] <= before["edges"] or after["faces"] <= before["faces"]:
        _close_undo_chunk()
        raise RuntimeError("Support loop insertion did not change mesh topology.")

    new_vertex_ids = list(range(before["vertices"], after["vertices"]))
    new_vertices = _components_from_range("vtx", before["vertices"], after["vertices"])
    new_edges = _components_from_range("e", before["edges"], after["edges"])
    new_faces = _components_from_range("f", before["faces"], after["faces"])
    try:
        moved_records = _set_new_vertex_positions(new_vertex_ids)
    except Exception:
        _close_undo_chunk()
        raise
    quality_validation = {"checked": False}
    if clean_validate_quality:
        quality_after = _quality_counts(clean_quality_issue_types)
        quality_validation = _quality_report(quality_before, quality_after)
        if not quality_validation["passed"] and clean_rollback_on_quality_error:
            _close_undo_chunk()
            cmds.undo()
            if old_selection:
                cmds.select(old_selection, replace=True)
            else:
                cmds.select(clear=True)
            try:
                cmds.file(modified=scene_modified_before)
            except Exception:
                pass
            rollback_counts = _counts()
            scene_modified_after_rollback = bool(cmds.file(query=True, modified=True))
            return {
                "success": False,
                "message": "Support loop insertion failed quality validation and was rolled back.",
                "object_name": object_name,
                "shape_name": shape_name,
                "operation": "insert_mesh_support_loop",
                "rolled_back": True,
                "component_type": component_type,
                "expand": expand.lower().strip(),
                "seed_edge_count": len(seed_edges),
                "target_edge_count": len(target_edges),
                "seed_edges_preview": seed_edges[:max_preview],
                "target_edges_preview": target_edges[:max_preview],
                "counts_before": before,
                "counts_after_attempt": after,
                "counts_after_rollback": rollback_counts,
                "scene_modified_before": scene_modified_before,
                "scene_modified_after_rollback": scene_modified_after_rollback,
                "new_vertex_count_attempt": len(new_vertices),
                "new_edge_count_attempt": len(new_edges),
                "new_face_count_attempt": len(new_faces),
                "quality_validation": quality_validation,
            }
    _close_undo_chunk()

    selection_items = {"vertex": new_vertices, "edge": new_edges, "face": new_faces}[clean_result_type]
    if select_result:
        _select_components(selection_items)

    return {
        "success": True,
        "object_name": object_name,
        "shape_name": shape_name,
        "operation": "insert_mesh_support_loop",
        "node": node,
        "component_type": component_type,
        "expand": expand.lower().strip(),
        "seed_edge_count": len(seed_edges),
        "target_edge_count": len(target_edges),
        "seed_edges_preview": seed_edges[:max_preview],
        "target_edges_preview": target_edges[:max_preview],
        "insert_with_edge_flow": bool(insert_with_edge_flow),
        "adjust_edge_flow": adjust_edge_flow,
        "position_mode": clean_position_mode,
        "axis": axis.lower().strip() if axis else None,
        "target_value": clean_target_value,
        "offset": clean_offset,
        "space": space,
        "counts_before": before,
        "counts_after": after,
        "new_vertex_count": len(new_vertices),
        "new_edge_count": len(new_edges),
        "new_face_count": len(new_faces),
        "new_vertices": new_vertices[:max_preview],
        "new_edges": new_edges[:max_preview],
        "new_faces": new_faces[:max_preview],
        "new_vertices_truncated": len(new_vertices) > max_preview,
        "new_edges_truncated": len(new_edges) > max_preview,
        "new_faces_truncated": len(new_faces) > max_preview,
        "position_changes": moved_records[:max_preview],
        "position_changes_truncated": len(moved_records) > max_preview,
        "quality_validation": quality_validation,
        "selected": bool(select_result),
        "result_type": clean_result_type if select_result else None,
    }
