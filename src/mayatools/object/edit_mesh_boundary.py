from typing import Dict, List, Any, Union


def edit_mesh_boundary(
    object_name: str,
    operation: str,
    component_type: str = None,
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    parameters: Dict[str, Any] = None,
    use_selection: bool = True,
    max_preview: int = 50,
) -> Dict[str, Any]:
    """Open, clean, and repair polygon mesh boundaries.

    Operations:
    - delete_faces: remove selected faces, leaving border edges around the hole
    - delete_edges: delete selected edges, optionally cleaning unused vertices
    - fill_holes: close selected border loops, or all current border loops when
      no components are provided
    - cap_boundary_loops: create ngon or triangle-fan cap polygons for selected
      closed border loops using mesh vertex order

    This is a Maya-style component repair tool for local mesh work: make an
    opening, remove support edges, then close border loops while reporting
    before/after topology counts and border edge changes.
    """
    import re
    import maya.cmds as cmds
    import maya.api.OpenMaya as om

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return int(value)

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

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

    def _mesh_dag(shape):
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

    def _resolve_components(default_type=None, allow_empty=False):
        clean_type = (component_type or default_type or "").lower().strip()
        kind_map = {"vertex": "vtx", "edge": "e", "face": "f", "uv": "map", "vertex_face": "vtxFace"}
        if components is not None:
            resolved = _flatten(components)
        elif clean_type in kind_map and indices is not None:
            resolved = _components_from_indices(kind_map[clean_type])
        else:
            resolved = _selected_components()
        if not resolved and not allow_empty:
            raise ValueError("No components resolved from components, indices, or current selection.")
        return resolved

    def _convert(items, target):
        flags = {
            "vertex": {"toVertex": True},
            "edge": {"toEdge": True},
            "face": {"toFace": True},
        }[target]
        return cmds.ls(cmds.polyListComponentConversion(items, **flags) or [], flatten=True) or []

    def _component_ids(items, kind):
        pattern = re.compile(rf"\.{kind}\[(\d+)\]$")
        ids = []
        for item in cmds.ls(items, flatten=True) or []:
            match = pattern.search(item)
            if match:
                ids.append(int(match.group(1)))
        return list(dict.fromkeys(ids))

    def _counts():
        return {
            "vertices": int(cmds.polyEvaluate(object_name, vertex=True)),
            "edges": int(cmds.polyEvaluate(object_name, edge=True)),
            "faces": int(cmds.polyEvaluate(object_name, face=True)),
        }

    def _boundary_edge_data_for_shape(target_shape):
        dag_path = _mesh_dag(target_shape)
        edge_it = om.MItMeshEdge(dag_path)
        data = {}
        while not edge_it.isDone():
            try:
                is_boundary = bool(edge_it.onBoundary())
            except Exception:
                is_boundary = len(edge_it.getConnectedFaces()) < 2
            if is_boundary:
                edge_id = int(edge_it.index())
                data[edge_id] = (int(edge_it.vertexId(0)), int(edge_it.vertexId(1)))
            edge_it.next()
        return data

    def _boundary_edge_data():
        return _boundary_edge_data_for_shape(shape_name)

    def _component(kind, index):
        return f"{prefix_name}.{kind}[{index}]"

    def _prefixed_component(component_prefix, kind, index):
        return f"{component_prefix}.{kind}[{index}]"

    def _counts_for_object(target_object):
        return {
            "vertices": int(cmds.polyEvaluate(target_object, vertex=True)),
            "edges": int(cmds.polyEvaluate(target_object, edge=True)),
            "faces": int(cmds.polyEvaluate(target_object, face=True)),
        }

    def _edge_groups(edge_ids, boundary_data):
        seed_edges = set(edge_ids)
        adjacency = {edge_id: set() for edge_id in boundary_data}
        edges_by_vertex = {}
        for edge_id in boundary_data:
            for vertex_id in boundary_data[edge_id]:
                edges_by_vertex.setdefault(vertex_id, []).append(edge_id)
        for connected_edges in edges_by_vertex.values():
            for edge_id in connected_edges:
                adjacency[edge_id].update(other for other in connected_edges if other != edge_id)

        groups = []
        visited = set()
        for edge_id in sorted(boundary_data):
            if edge_id in visited:
                continue
            stack = [edge_id]
            group = []
            visited.add(edge_id)
            while stack:
                current = stack.pop()
                group.append(current)
                for neighbor in sorted(adjacency[current]):
                    if neighbor in visited:
                        continue
                    visited.add(neighbor)
                    stack.append(neighbor)
            if seed_edges.intersection(group):
                groups.append(sorted(group))
        return groups

    def _ordered_loop_vertices(edge_ids, boundary_data):
        adjacency = {}
        for edge_id in edge_ids:
            vertex_a, vertex_b = boundary_data[edge_id]
            adjacency.setdefault(vertex_a, []).append(vertex_b)
            adjacency.setdefault(vertex_b, []).append(vertex_a)
        if not adjacency:
            raise ValueError("Cannot order an empty boundary loop.")
        endpoint_vertices = sorted(vertex_id for vertex_id, neighbors in adjacency.items() if len(neighbors) == 1)
        if endpoint_vertices:
            if not allow_open_chains:
                raise ValueError("cap_boundary_loops requires closed border loops unless parameters.allow_open_chains is true.")
            start = endpoint_vertices[0]
        else:
            if any(len(neighbors) != 2 for neighbors in adjacency.values()):
                raise ValueError("cap_boundary_loops requires simple boundary loops where each vertex has two boundary neighbors.")
            start = min(adjacency)
        ordered = [start]
        previous = None
        current = start
        while True:
            candidates = sorted(vertex_id for vertex_id in adjacency[current] if vertex_id != previous)
            if not candidates:
                break
            next_vertex = candidates[0]
            if next_vertex == start:
                break
            if next_vertex in ordered:
                raise ValueError("Boundary loop has a branch or repeated vertex and cannot be capped safely.")
            ordered.append(next_vertex)
            previous, current = current, next_vertex
            if len(ordered) > len(adjacency):
                raise ValueError("Boundary loop ordering exceeded vertex count.")
        if len(ordered) != len(adjacency):
            raise ValueError("Boundary loop did not resolve to a single ordered chain.")
        return ordered, not endpoint_vertices

    def _changed(before, after, border_before, border_after):
        if any(before[key] != after[key] for key in before):
            return True
        return len(border_before) != len(border_after)

    def _poly_info_components_for(target_object, flag_name):
        flag_map = {
            "nonmanifold_edges": {"nonManifoldEdges": True},
            "nonmanifold_vertices": {"nonManifoldVertices": True},
        }
        lines = cmds.polyInfo(target_object, **flag_map[flag_name]) or []
        raw_components = []
        for line in lines:
            raw_components.extend(re.findall(r"\S+\.(?:e|vtx)\[\d+(?::\d+)?\]", line))
        return cmds.ls(raw_components, flatten=True) or []

    def _filtered_nonmanifold_counts(target_object, target_shape, component_prefix):
        boundary_data = _boundary_edge_data_for_shape(target_shape)
        boundary_edges = {_prefixed_component(component_prefix, "e", edge_id) for edge_id in boundary_data}
        boundary_vertices = {
            _prefixed_component(component_prefix, "vtx", vertex_id)
            for edge_vertices in boundary_data.values()
            for vertex_id in edge_vertices
        }
        raw_edges = _poly_info_components_for(target_object, "nonmanifold_edges")
        raw_vertices = _poly_info_components_for(target_object, "nonmanifold_vertices")
        edge_count = len([component for component in raw_edges if component not in boundary_edges])
        vertex_count = len([component for component in raw_vertices if component not in boundary_vertices])
        return {"nonmanifold_edges": edge_count, "nonmanifold_vertices": vertex_count}

    def _cap_groups_for_shape(target_shape, component_prefix, groups, target_boundary_data, cap_settings):
        cap_mode = cap_settings["cap_mode"]
        point_tolerance = cap_settings["point_tolerance"]
        reverse_winding = cap_settings["reverse_winding"]
        mesh_fn = om.MFnMesh(_mesh_dag(target_shape))
        mesh_points = mesh_fn.getPoints(om.MSpace.kObject)
        reports = []
        for group in groups:
            ordered_vertices, closed = _ordered_loop_vertices(group, target_boundary_data)
            if len(ordered_vertices) < 3:
                raise ValueError("cap_boundary_loops requires at least three ordered boundary vertices.")
            if reverse_winding:
                ordered_vertices = list(reversed(ordered_vertices))
            added_faces = []
            if cap_mode == "ngon":
                polygon_points = om.MPointArray([mesh_points[vertex_id] for vertex_id in ordered_vertices])
                added_faces.append(int(mesh_fn.addPolygon(polygon_points, True, point_tolerance)))
            else:
                center_point = om.MPoint()
                for vertex_id in ordered_vertices:
                    center_point += mesh_points[vertex_id]
                center_point = center_point / float(len(ordered_vertices))
                for index, vertex_id in enumerate(ordered_vertices):
                    next_vertex_id = ordered_vertices[(index + 1) % len(ordered_vertices)]
                    polygon_points = om.MPointArray([mesh_points[vertex_id], mesh_points[next_vertex_id], center_point])
                    added_faces.append(int(mesh_fn.addPolygon(polygon_points, True, point_tolerance)))
            try:
                mesh_fn.updateSurface()
            except Exception:
                pass
            reports.append({
                "edge_count": len(group),
                "ordered_vertex_count": len(ordered_vertices),
                "closed": bool(closed),
                "cap_mode": cap_mode,
                "added_face_count": len(added_faces),
                "added_faces_preview": [_prefixed_component(component_prefix, "f", face_id) for face_id in added_faces[:max_preview]],
            })
        return reports

    def _result(node_result, resolved, before_counts, before_border, extra=None):
        after_counts = _counts()
        after_border = sorted(_boundary_edge_data())
        if not _changed(before_counts, after_counts, before_border, after_border):
            raise RuntimeError(f"{operation} did not change mesh topology or boundary state.")
        current_selection = cmds.ls(selection=True, flatten=True) or []
        payload = {
            "success": True,
            "object_name": object_name,
            "operation": operation,
            "node": node_result,
            "input_component_count": len(resolved),
            "input_components_preview": resolved[:max_preview],
            "selected_after_count": len(current_selection),
            "selected_after_preview": current_selection[:max_preview],
            "counts_before": before_counts,
            "counts_after": after_counts,
            "border_edges_before_count": len(before_border),
            "border_edges_after_count": len(after_border),
            "border_edges_before_preview": [_component("e", edge_id) for edge_id in before_border[:max_preview]],
            "border_edges_after_preview": [_component("e", edge_id) for edge_id in after_border[:max_preview]],
        }
        if extra:
            payload.update(extra)
        return payload

    if not object_name:
        raise ValueError("object_name is required.")
    if not operation:
        raise ValueError("operation is required.")
    operation = operation.lower().strip()
    allowed = {"delete_faces", "delete_edges", "fill_holes", "cap_boundary_loops"}
    if operation not in allowed:
        raise ValueError(f"operation must be one of: {', '.join(sorted(allowed))}.")

    parameters = parameters or {}
    max_preview = _validate_int(max_preview, "max_preview", 1)
    shape_name = _mesh_shape(object_name)
    prefix_name = _prefix(shape_name)
    before_counts = _counts()
    before_border = sorted(_boundary_edge_data())
    construction_history = bool(parameters.get("construction_history", False))

    if operation == "delete_faces":
        faces = _convert(_resolve_components("face"), "face")
        if not faces:
            raise ValueError("delete_faces requires face components.")
        node = cmds.polyDelFacet(faces, constructionHistory=construction_history)
        return _result(node, faces, before_counts, before_border)

    if operation == "delete_edges":
        edges = _convert(_resolve_components("edge"), "edge")
        if not edges:
            raise ValueError("delete_edges requires edge components.")
        clean_vertices = bool(parameters.get("clean_vertices", False))
        node = cmds.polyDelEdge(
            edges,
            cleanVertices=clean_vertices,
            constructionHistory=construction_history,
        )
        return _result(node, edges, before_counts, before_border, {"clean_vertices": clean_vertices})

    if operation in {"fill_holes", "cap_boundary_loops"}:
        resolved = _resolve_components("edge", allow_empty=True)
        boundary_data = _boundary_edge_data()
        if not boundary_data:
            raise ValueError(f"{object_name} has no border edges to repair.")
        if resolved:
            edge_ids = _component_ids(_convert(resolved, "edge"), "e")
            border_edge_ids = [edge_id for edge_id in edge_ids if edge_id in boundary_data]
            if not border_edge_ids:
                raise ValueError(f"{operation} requires selected or indexed border edges.")
        else:
            fill_all = bool(parameters.get("fill_all_border_edges", True))
            if not fill_all:
                raise ValueError("No components resolved; set parameters.fill_all_border_edges true to repair all holes.")
            border_edge_ids = sorted(boundary_data)
            resolved = [_component("e", edge_id) for edge_id in border_edge_ids]

        groups = _edge_groups(border_edge_ids, boundary_data)
        target_edge_ids = []
        for group in groups:
            target_edge_ids.extend(group)
        target_edge_ids = sorted(dict.fromkeys(target_edge_ids))
        nodes = []
        cap_reports = []
        if operation == "fill_holes":
            for group in groups:
                loop_edges = [_component("e", edge_id) for edge_id in group]
                nodes.append(cmds.polyCloseBorder(loop_edges, constructionHistory=construction_history))
        else:
            cap_mode = str(parameters.get("cap_mode", "ngon")).lower().strip()
            if cap_mode not in {"ngon", "triangle_fan"}:
                raise ValueError("parameters.cap_mode must be ngon or triangle_fan.")
            point_tolerance = _validate_scalar(parameters.get("point_tolerance", 1.0e-6), "point_tolerance")
            if point_tolerance < 0.0:
                raise ValueError("parameters.point_tolerance must be greater than or equal to zero.")
            reverse_winding = bool(parameters.get("reverse_winding", False))
            allow_open_chains = bool(parameters.get("allow_open_chains", False))
            validate_on_duplicate = bool(parameters.get("validate_on_duplicate", True))
            require_boundary_reduction = bool(parameters.get("require_boundary_reduction", True))
            allow_nonmanifold_result = bool(parameters.get("allow_nonmanifold_result", False))
            cap_settings = {
                "cap_mode": cap_mode,
                "point_tolerance": point_tolerance,
                "reverse_winding": reverse_winding,
            }
            if validate_on_duplicate:
                duplicate = cmds.duplicate(object_name, name=f"{object_name}_cap_boundary_preview_tmp")[0]
                try:
                    duplicate_shape = _mesh_shape(duplicate)
                    duplicate_prefix = _prefix(duplicate_shape)
                    duplicate_boundary_before = _boundary_edge_data_for_shape(duplicate_shape)
                    duplicate_nonmanifold_before = _filtered_nonmanifold_counts(duplicate, duplicate_shape, duplicate_prefix)
                    _cap_groups_for_shape(duplicate_shape, duplicate_prefix, groups, duplicate_boundary_before, cap_settings)
                    duplicate_boundary_after = _boundary_edge_data_for_shape(duplicate_shape)
                    duplicate_nonmanifold_after = _filtered_nonmanifold_counts(duplicate, duplicate_shape, duplicate_prefix)
                    if require_boundary_reduction and len(duplicate_boundary_after) >= len(duplicate_boundary_before):
                        raise RuntimeError(
                            "cap_boundary_loops preflight failed: boundary edge count did not decrease on duplicate mesh."
                        )
                    if not allow_nonmanifold_result:
                        if duplicate_nonmanifold_after["nonmanifold_edges"] > duplicate_nonmanifold_before["nonmanifold_edges"]:
                            raise RuntimeError("cap_boundary_loops preflight failed: nonmanifold edge count increased on duplicate mesh.")
                        if duplicate_nonmanifold_after["nonmanifold_vertices"] > duplicate_nonmanifold_before["nonmanifold_vertices"]:
                            raise RuntimeError("cap_boundary_loops preflight failed: nonmanifold vertex count increased on duplicate mesh.")
                finally:
                    if cmds.objExists(duplicate):
                        cmds.delete(duplicate)
            cap_reports = _cap_groups_for_shape(shape_name, prefix_name, groups, boundary_data, cap_settings)
        return _result(
            nodes,
            resolved,
            before_counts,
            before_border,
            {
                "filled_loop_count": len(groups),
                "seed_edge_count": len(border_edge_ids),
                "seed_edges_preview": [_component("e", edge_id) for edge_id in border_edge_ids[:max_preview]],
                "filled_edge_count": len(target_edge_ids),
                "filled_edges_preview": [_component("e", edge_id) for edge_id in target_edge_ids[:max_preview]],
                "cap_reports": cap_reports,
            },
        )

    raise ValueError(f"Unsupported operation: {operation}")
