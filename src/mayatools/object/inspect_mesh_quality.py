from typing import Dict, List, Any


def inspect_mesh_quality(
    object_name: str,
    operation: str = "inspect",
    issue_types: List[str] = None,
    area_epsilon: float = 1.0e-8,
    edge_length_epsilon: float = 1.0e-5,
    face_aspect_threshold: float = 20.0,
    high_valence_threshold: int = 8,
    include_boundary_as_nonmanifold: bool = False,
    select_components: bool = False,
    max_items: int = 200,
) -> Dict[str, Any]:
    """Inspect polygon mesh quality and optionally select problem components.

    Reported issue types:
    - border_edges: boundary/open edges
    - boundary_vertices: vertices on boundary/open edges
    - nonmanifold_edges, nonmanifold_vertices, lamina_faces
    - invalid_edges, invalid_vertices
    - triangles, ngons
    - zero_area_faces, zero_uv_area_faces
    - short_edges, skinny_faces
    - isolated_vertices
    - high_valence_vertices

    Use this after component-level modeling edits to catch topology problems
    before they become shading, UV, bridge, bevel, or shrinkwrap failures.
    By default boundary components are reported separately and filtered out of
    Maya's raw nonmanifold edge/vertex results; set
    include_boundary_as_nonmanifold=True to preserve raw Maya polyInfo behavior.
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

    def _prefix(shape):
        parents = cmds.listRelatives(shape, parent=True, fullPath=False) or []
        return parents[0] if parents else object_name

    def _mesh_dag(shape):
        selection = om.MSelectionList()
        selection.add(shape)
        return selection.getDagPath(0)

    def _flatten_components(items):
        if not items:
            return []
        return cmds.ls(items, flatten=True) or []

    def _poly_info_components(flag_name):
        flag_map = {
            "nonmanifold_edges": {"nonManifoldEdges": True},
            "nonmanifold_vertices": {"nonManifoldVertices": True},
            "lamina_faces": {"laminaFaces": True},
            "invalid_edges": {"invalidEdges": True},
            "invalid_vertices": {"invalidVertices": True},
        }
        lines = cmds.polyInfo(object_name, **flag_map[flag_name]) or []
        raw_components = []
        for line in lines:
            raw_components.extend(re.findall(r"\S+\.(?:e|f|vtx)\[\d+(?::\d+)?\]", line))
        return _flatten_components(raw_components)

    def _issue_record(components, extra_records=None, raw_components=None):
        clean_components = list(dict.fromkeys(components))
        record = {
            "count": len(clean_components),
            "components": clean_components[:max_items],
            "truncated": len(clean_components) > max_items,
            "records": (extra_records or [])[:max_items],
        }
        if raw_components is not None:
            clean_raw_components = list(dict.fromkeys(raw_components))
            record["raw_count"] = len(clean_raw_components)
            record["filtered_count"] = len(clean_components)
        return record

    def _component(name, kind, index):
        return f"{prefix_name}.{kind}[{index}]"

    if not object_name:
        raise ValueError("object_name is required.")
    operation = operation.lower().strip()
    if operation not in {"inspect", "select"}:
        raise ValueError("operation must be inspect or select.")
    area_epsilon = _validate_scalar(area_epsilon, "area_epsilon")
    if area_epsilon < 0.0:
        raise ValueError("area_epsilon must be greater than or equal to zero.")
    edge_length_epsilon = _validate_scalar(edge_length_epsilon, "edge_length_epsilon")
    if edge_length_epsilon < 0.0:
        raise ValueError("edge_length_epsilon must be greater than or equal to zero.")
    face_aspect_threshold = _validate_scalar(face_aspect_threshold, "face_aspect_threshold")
    if face_aspect_threshold < 1.0:
        raise ValueError("face_aspect_threshold must be greater than or equal to 1.")
    high_valence_threshold = _validate_int(high_valence_threshold, "high_valence_threshold", 1)
    max_items = _validate_int(max_items, "max_items", 1)

    all_issue_types = [
        "border_edges",
        "boundary_vertices",
        "nonmanifold_edges",
        "nonmanifold_vertices",
        "lamina_faces",
        "invalid_edges",
        "invalid_vertices",
        "triangles",
        "ngons",
        "zero_area_faces",
        "zero_uv_area_faces",
        "short_edges",
        "skinny_faces",
        "isolated_vertices",
        "high_valence_vertices",
    ]
    if issue_types is None:
        clean_issue_types = all_issue_types
    else:
        if not isinstance(issue_types, list) or not all(isinstance(item, str) for item in issue_types):
            raise ValueError("issue_types must be a list of strings or None.")
        clean_issue_types = [item.lower().strip() for item in issue_types]
        unknown = sorted(set(clean_issue_types) - set(all_issue_types))
        if unknown:
            raise ValueError(f"Unknown issue_types: {unknown}.")

    shape_name = _mesh_shape(object_name)
    prefix_name = _prefix(shape_name)
    dag_path = _mesh_dag(shape_name)
    mesh_fn = om.MFnMesh(dag_path)

    counts = {
        "vertices": int(mesh_fn.numVertices),
        "edges": int(mesh_fn.numEdges),
        "faces": int(mesh_fn.numPolygons),
        "uvs": int(mesh_fn.numUVs(mesh_fn.currentUVSetName())) if mesh_fn.numUVs() else 0,
        "triangles": int(cmds.polyEvaluate(object_name, triangle=True)),
        "shells": int(cmds.polyEvaluate(object_name, shell=True)),
    }

    issues = {}

    points = mesh_fn.getPoints(om.MSpace.kWorld)
    edge_lengths = {}

    def _edge_length(edge_id):
        if edge_id not in edge_lengths:
            vertex_a, vertex_b = mesh_fn.getEdgeVertices(edge_id)
            point_a = points[int(vertex_a)]
            point_b = points[int(vertex_b)]
            edge_lengths[edge_id] = float(
                ((point_a.x - point_b.x) ** 2 + (point_a.y - point_b.y) ** 2 + (point_a.z - point_b.z) ** 2) ** 0.5
            )
        return edge_lengths[edge_id]

    def _boundary_components():
        edge_it = om.MItMeshEdge(dag_path)
        edge_components = []
        edge_records = []
        vertex_to_edges = {}
        while not edge_it.isDone():
            if edge_it.onBoundary():
                edge_id = int(edge_it.index())
                vertex_a = int(edge_it.vertexId(0))
                vertex_b = int(edge_it.vertexId(1))
                faces = list(edge_it.getConnectedFaces())
                edge_component = _component(prefix_name, "e", edge_id)
                edge_components.append(edge_component)
                edge_records.append({
                    "component": edge_component,
                    "vertices": [vertex_a, vertex_b],
                    "connected_faces": [int(face) for face in faces],
                })
                for vertex_id in [vertex_a, vertex_b]:
                    vertex_to_edges.setdefault(vertex_id, []).append(edge_id)
            edge_it.next()
        vertex_components = []
        vertex_records = []
        for vertex_id, edge_ids in sorted(vertex_to_edges.items()):
            vertex_component = _component(prefix_name, "vtx", vertex_id)
            vertex_components.append(vertex_component)
            vertex_records.append({
                "component": vertex_component,
                "boundary_edges": [_component(prefix_name, "e", edge_id) for edge_id in sorted(edge_ids)],
            })
        return edge_components, edge_records, vertex_components, vertex_records

    boundary_edge_components, boundary_edge_records, boundary_vertex_components, boundary_vertex_records = _boundary_components()
    boundary_edge_set = set(boundary_edge_components)
    boundary_vertex_set = set(boundary_vertex_components)

    if "border_edges" in clean_issue_types:
        issues["border_edges"] = _issue_record(boundary_edge_components, boundary_edge_records)

    if "boundary_vertices" in clean_issue_types:
        issues["boundary_vertices"] = _issue_record(boundary_vertex_components, boundary_vertex_records)

    if "short_edges" in clean_issue_types:
        edge_it = om.MItMeshEdge(dag_path)
        components = []
        records = []
        while not edge_it.isDone():
            edge_id = int(edge_it.index())
            length = _edge_length(edge_id)
            if length <= edge_length_epsilon:
                component = _component(prefix_name, "e", edge_id)
                vertex_a, vertex_b = mesh_fn.getEdgeVertices(edge_id)
                components.append(component)
                records.append(
                    {
                        "component": component,
                        "length": length,
                        "vertices": [int(vertex_a), int(vertex_b)],
                    }
                )
            edge_it.next()
        issues["short_edges"] = _issue_record(components, records)

    for poly_info_type in ["nonmanifold_edges", "nonmanifold_vertices", "lamina_faces", "invalid_edges", "invalid_vertices"]:
        if poly_info_type in clean_issue_types:
            raw_components = _poly_info_components(poly_info_type)
            components = raw_components
            if not include_boundary_as_nonmanifold and poly_info_type == "nonmanifold_edges":
                components = [component for component in raw_components if component not in boundary_edge_set]
            if not include_boundary_as_nonmanifold and poly_info_type == "nonmanifold_vertices":
                components = [component for component in raw_components if component not in boundary_vertex_set]
            raw_for_record = raw_components if components != raw_components else None
            issues[poly_info_type] = _issue_record(components, raw_components=raw_for_record)

    polygon_it = om.MItMeshPolygon(dag_path)
    triangle_components = []
    ngon_components = []
    zero_area_components = []
    zero_uv_area_components = []
    skinny_face_components = []
    triangle_records = []
    ngon_records = []
    zero_area_records = []
    zero_uv_records = []
    skinny_face_records = []
    while not polygon_it.isDone():
        face_id = int(polygon_it.index())
        face_component = _component(prefix_name, "f", face_id)
        vertex_count = int(polygon_it.polygonVertexCount())
        area = float(polygon_it.getArea(om.MSpace.kWorld))
        if "triangles" in clean_issue_types and vertex_count == 3:
            triangle_components.append(face_component)
            triangle_records.append({"component": face_component, "vertex_count": vertex_count, "area": area})
        if "ngons" in clean_issue_types and vertex_count > 4:
            ngon_components.append(face_component)
            ngon_records.append({"component": face_component, "vertex_count": vertex_count, "area": area})
        if "zero_area_faces" in clean_issue_types and (area <= area_epsilon or polygon_it.zeroArea()):
            zero_area_components.append(face_component)
            zero_area_records.append({"component": face_component, "vertex_count": vertex_count, "area": area})
        if "zero_uv_area_faces" in clean_issue_types:
            try:
                zero_uv = bool(polygon_it.zeroUVArea())
            except Exception:
                zero_uv = False
            if zero_uv:
                zero_uv_area_components.append(face_component)
                zero_uv_records.append({"component": face_component, "vertex_count": vertex_count})
        if "skinny_faces" in clean_issue_types:
            edge_ids = [int(edge_id) for edge_id in polygon_it.getEdges()]
            lengths = [_edge_length(edge_id) for edge_id in edge_ids]
            nonzero_lengths = [length for length in lengths if length > 1.0e-12]
            if nonzero_lengths:
                shortest = min(nonzero_lengths)
                longest = max(nonzero_lengths)
                aspect_ratio = longest / shortest
                if aspect_ratio >= face_aspect_threshold:
                    skinny_face_components.append(face_component)
                    skinny_face_records.append(
                        {
                            "component": face_component,
                            "vertex_count": vertex_count,
                            "area": area,
                            "shortest_edge_length": shortest,
                            "longest_edge_length": longest,
                            "aspect_ratio": aspect_ratio,
                            "edges": [_component(prefix_name, "e", edge_id) for edge_id in edge_ids],
                        }
                    )
        polygon_it.next()

    if "triangles" in clean_issue_types:
        issues["triangles"] = _issue_record(triangle_components, triangle_records)
    if "ngons" in clean_issue_types:
        issues["ngons"] = _issue_record(ngon_components, ngon_records)
    if "zero_area_faces" in clean_issue_types:
        issues["zero_area_faces"] = _issue_record(zero_area_components, zero_area_records)
    if "zero_uv_area_faces" in clean_issue_types:
        issues["zero_uv_area_faces"] = _issue_record(zero_uv_area_components, zero_uv_records)
    if "skinny_faces" in clean_issue_types:
        issues["skinny_faces"] = _issue_record(skinny_face_components, skinny_face_records)

    if "isolated_vertices" in clean_issue_types or "high_valence_vertices" in clean_issue_types:
        vertex_it = om.MItMeshVertex(dag_path)
        isolated_components = []
        high_valence_components = []
        isolated_records = []
        high_valence_records = []
        while not vertex_it.isDone():
            vertex_id = int(vertex_it.index())
            component = _component(prefix_name, "vtx", vertex_id)
            connected_edges = list(vertex_it.getConnectedEdges())
            connected_faces = list(vertex_it.getConnectedFaces())
            edge_count = int(vertex_it.numConnectedEdges())
            face_count = int(vertex_it.numConnectedFaces())
            if "isolated_vertices" in clean_issue_types and edge_count == 0 and face_count == 0:
                isolated_components.append(component)
                isolated_records.append({"component": component, "connected_edges": 0, "connected_faces": 0})
            if "high_valence_vertices" in clean_issue_types and edge_count > high_valence_threshold:
                high_valence_components.append(component)
                high_valence_records.append(
                    {
                        "component": component,
                        "connected_edge_count": edge_count,
                        "connected_face_count": face_count,
                        "connected_edges": [int(edge) for edge in connected_edges],
                        "connected_faces": [int(face) for face in connected_faces],
                    }
                )
            vertex_it.next()
        if "isolated_vertices" in clean_issue_types:
            issues["isolated_vertices"] = _issue_record(isolated_components, isolated_records)
        if "high_valence_vertices" in clean_issue_types:
            issues["high_valence_vertices"] = _issue_record(high_valence_components, high_valence_records)

    summary = {issue_type: issues[issue_type]["count"] for issue_type in issues}
    selected = []
    if operation == "select" or select_components:
        for issue_type in clean_issue_types:
            if issue_type in issues:
                selected.extend(issues[issue_type]["components"])
        selected = list(dict.fromkeys(selected))
        if selected:
            cmds.select(selected, replace=True)
        else:
            cmds.select(clear=True)

    return {
        "success": True,
        "object_name": object_name,
        "shape_name": shape_name,
        "operation": operation,
        "counts": counts,
        "area_epsilon": area_epsilon,
        "edge_length_epsilon": edge_length_epsilon,
        "face_aspect_threshold": face_aspect_threshold,
        "high_valence_threshold": high_valence_threshold,
        "include_boundary_as_nonmanifold": bool(include_boundary_as_nonmanifold),
        "issue_types": clean_issue_types,
        "summary": summary,
        "issues": issues,
        "selected_count": len(selected),
        "selected_preview": selected[:max_items],
    }
