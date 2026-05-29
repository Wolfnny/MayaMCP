from typing import Dict, List, Any, Union


def inspect_mesh_boundaries(
    object_name: str,
    components: Union[str, List[str]] = None,
    min_edge_count: int = 0,
    max_edge_count: int = 0,
    sort_by: str = "edge_count_desc",
    select_components: bool = False,
    selection_mode: str = "replace",
    max_loops: int = 50,
    max_components_per_loop: int = 50,
    planarity_tolerance: float = 0.0001,
    position_tolerance: float = 0.00001,
) -> Dict[str, Any]:
    """Inspect polygon mesh boundary loops without modifying geometry.

    Reports connected border-edge groups with edge/vertex counts, whether the
    group is a closed loop or open chain, world-space center, bounding box,
    perimeter, ordered component previews, edge-length statistics, simple loop
    topology, duplicate position diagnostics, and planarity diagnostics.
    Components can be supplied as seed vertices/edges/faces to return only
    boundary loops touching those seeds. This is useful before fill-hole,
    bridge, sew, cap, delete-edge, or weld work so an artist can decide which
    openings are intentional and which are repair targets.
    """
    import re
    import maya.cmds as cmds
    import maya.api.OpenMaya as om

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return int(value)

    def _validate_float(value, arg_name, minimum):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or float(value) < minimum:
            raise ValueError(f"{arg_name} must be a number greater than or equal to {minimum}.")
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

    def _dag_path(node):
        selection = om.MSelectionList()
        selection.add(node)
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

    def _component_ids(items, kind):
        pattern = re.compile(rf"\.{kind}\[(\d+)\]$")
        ids = []
        for item in cmds.ls(items, flatten=True) or []:
            match = pattern.search(item)
            if match:
                ids.append(int(match.group(1)))
        return set(ids)

    def _seed_filters():
        flattened = _flatten(components)
        if not flattened:
            return None
        edge_ids = _component_ids(cmds.polyListComponentConversion(flattened, toEdge=True) or [], "e")
        vertex_ids = _component_ids(cmds.polyListComponentConversion(flattened, toVertex=True) or [], "vtx")
        return {"edges": edge_ids, "vertices": vertex_ids}

    def _component(kind, index):
        return f"{prefix_name}.{kind}[{int(index)}]"

    def _point_values(point):
        return [float(point.x), float(point.y), float(point.z)]

    def _other_vertex(edge_vertices, vertex_id):
        if edge_vertices[0] == vertex_id:
            return edge_vertices[1]
        if edge_vertices[1] == vertex_id:
            return edge_vertices[0]
        return None

    def _bbox(points):
        mins = [float("inf"), float("inf"), float("inf")]
        maxs = [float("-inf"), float("-inf"), float("-inf")]
        for point in points:
            values = [point.x, point.y, point.z]
            for index in range(3):
                mins[index] = min(mins[index], float(values[index]))
                maxs[index] = max(maxs[index], float(values[index]))
        return mins, maxs

    def _edge_length(edge_vertices, points):
        point_a = points[edge_vertices[0]]
        point_b = points[edge_vertices[1]]
        return float(
            ((point_a.x - point_b.x) ** 2 + (point_a.y - point_b.y) ** 2 + (point_a.z - point_b.z) ** 2) ** 0.5
        )

    def _length_stats(lengths):
        if not lengths:
            return {
                "min": 0.0,
                "max": 0.0,
                "mean": 0.0,
                "max_to_min_ratio": None,
            }
        min_length = min(lengths)
        max_length = max(lengths)
        return {
            "min": float(min_length),
            "max": float(max_length),
            "mean": float(sum(lengths) / len(lengths)),
            "max_to_min_ratio": float(max_length / min_length) if min_length > 0 else None,
        }

    def _ordered_walk(group, group_vertex_ids, group_edges_by_vertex, is_closed):
        group_set = set(group)
        if not group:
            return {
                "edge_ids": [],
                "vertex_ids": [],
                "complete": True,
                "closes_to_start": False,
                "unvisited_edge_count": 0,
                "warning": None,
            }

        degrees = {
            vertex_id: len([edge_id for edge_id in group_edges_by_vertex.get(vertex_id, []) if edge_id in group_set])
            for vertex_id in group_vertex_ids
        }
        endpoints = sorted(vertex_id for vertex_id, degree in degrees.items() if degree == 1)
        start_vertex = endpoints[0] if endpoints else min(group_vertex_ids)
        current_vertex = start_vertex
        visited_edges = set()
        ordered_edges = []
        ordered_vertices = [start_vertex]
        closes_to_start = False

        while len(visited_edges) < len(group):
            candidates = [
                edge_id
                for edge_id in group_edges_by_vertex.get(current_vertex, [])
                if edge_id in group_set and edge_id not in visited_edges
            ]
            if not candidates:
                break
            candidates = sorted(
                candidates,
                key=lambda edge_id: (_other_vertex(boundary_edges[edge_id]["vertices"], current_vertex), edge_id),
            )
            edge_id = candidates[0]
            next_vertex = _other_vertex(boundary_edges[edge_id]["vertices"], current_vertex)
            if next_vertex is None:
                break
            visited_edges.add(edge_id)
            ordered_edges.append(edge_id)
            if is_closed and next_vertex == start_vertex and len(visited_edges) == len(group):
                closes_to_start = True
                break
            ordered_vertices.append(next_vertex)
            current_vertex = next_vertex

        unvisited = len(group) - len(visited_edges)
        warning = None
        if unvisited:
            warning = "Boundary group could not be represented as one continuous ordered chain."
        elif is_closed and not closes_to_start:
            warning = "Closed boundary did not return to its starting vertex during ordered traversal."

        return {
            "edge_ids": ordered_edges,
            "vertex_ids": ordered_vertices,
            "complete": unvisited == 0 and (not is_closed or closes_to_start),
            "closes_to_start": closes_to_start,
            "unvisited_edge_count": unvisited,
            "warning": warning,
        }

    def _newell_normal(loop_points):
        if len(loop_points) < 3:
            return None
        normal = [0.0, 0.0, 0.0]
        for index, point in enumerate(loop_points):
            next_point = loop_points[(index + 1) % len(loop_points)]
            normal[0] += (point.y - next_point.y) * (point.z + next_point.z)
            normal[1] += (point.z - next_point.z) * (point.x + next_point.x)
            normal[2] += (point.x - next_point.x) * (point.y + next_point.y)
        length = (normal[0] ** 2 + normal[1] ** 2 + normal[2] ** 2) ** 0.5
        if length <= 0.0:
            return None
        return [float(normal[0] / length), float(normal[1] / length), float(normal[2] / length)]

    def _planarity(loop_vertex_ids, is_closed, tolerance):
        if not is_closed:
            return {
                "computed": False,
                "tolerance": tolerance,
                "is_planar": None,
                "normal": None,
                "max_distance": None,
                "mean_distance": None,
                "warning": "Planarity is computed only for closed boundary loops.",
            }
        if len(loop_vertex_ids) < 3:
            return {
                "computed": False,
                "tolerance": tolerance,
                "is_planar": None,
                "normal": None,
                "max_distance": None,
                "mean_distance": None,
                "warning": "At least three ordered vertices are required for planarity.",
            }
        loop_points = [points[vertex_id] for vertex_id in loop_vertex_ids]
        normal = _newell_normal(loop_points)
        if normal is None:
            return {
                "computed": False,
                "tolerance": tolerance,
                "is_planar": None,
                "normal": None,
                "max_distance": None,
                "mean_distance": None,
                "warning": "Could not compute a stable loop normal.",
            }
        center_point = [
            sum(float(getattr(point, axis)) for point in loop_points) / len(loop_points)
            for axis in ("x", "y", "z")
        ]
        distances = []
        for point in loop_points:
            distance = abs(
                (float(point.x) - center_point[0]) * normal[0]
                + (float(point.y) - center_point[1]) * normal[1]
                + (float(point.z) - center_point[2]) * normal[2]
            )
            distances.append(distance)
        max_distance = max(distances) if distances else 0.0
        mean_distance = sum(distances) / len(distances) if distances else 0.0
        return {
            "computed": True,
            "tolerance": tolerance,
            "is_planar": bool(max_distance <= tolerance),
            "normal": normal,
            "max_distance": float(max_distance),
            "mean_distance": float(mean_distance),
            "warning": None,
        }

    def _duplicate_positions(vertex_ids, tolerance, max_groups):
        if tolerance <= 0.0:
            return {
                "enabled": False,
                "tolerance": tolerance,
                "duplicate_vertex_count": 0,
                "duplicate_group_count": 0,
                "groups": [],
                "groups_truncated": False,
            }
        buckets = {}
        for vertex_id in vertex_ids:
            point = points[vertex_id]
            key = (
                int(round(float(point.x) / tolerance)),
                int(round(float(point.y) / tolerance)),
                int(round(float(point.z) / tolerance)),
            )
            buckets.setdefault(key, []).append(vertex_id)
        groups = []
        for bucket_vertices in buckets.values():
            if len(bucket_vertices) < 2:
                continue
            first_point = points[bucket_vertices[0]]
            groups.append({
                "position": _point_values(first_point),
                "vertex_components": [_component("vtx", vertex_id) for vertex_id in sorted(bucket_vertices)],
            })
        groups.sort(key=lambda item: (len(item["vertex_components"]), item["vertex_components"][0]), reverse=True)
        duplicate_vertex_count = sum(len(group["vertex_components"]) for group in groups)
        return {
            "enabled": True,
            "tolerance": tolerance,
            "duplicate_vertex_count": duplicate_vertex_count,
            "duplicate_group_count": len(groups),
            "groups": groups[:max_groups],
            "groups_truncated": len(groups) > max_groups,
        }

    if not object_name:
        raise ValueError("object_name is required.")
    clean_min_edge_count = _validate_int(min_edge_count, "min_edge_count", 0)
    clean_max_edge_count = _validate_int(max_edge_count, "max_edge_count", 0)
    clean_sort_by = (sort_by or "").lower().strip()
    if clean_sort_by not in {"edge_count_desc", "edge_count_asc", "perimeter_desc", "perimeter_asc", "center_y_desc", "center_y_asc"}:
        raise ValueError("sort_by must be edge_count_desc, edge_count_asc, perimeter_desc, perimeter_asc, center_y_desc, or center_y_asc.")
    clean_selection_mode = (selection_mode or "").lower().strip()
    if clean_selection_mode not in {"replace", "add", "toggle", "deselect"}:
        raise ValueError("selection_mode must be replace, add, toggle, or deselect.")
    clean_max_loops = _validate_int(max_loops, "max_loops", 1)
    clean_max_components_per_loop = _validate_int(max_components_per_loop, "max_components_per_loop", 1)
    clean_planarity_tolerance = _validate_float(planarity_tolerance, "planarity_tolerance", 0.0)
    clean_position_tolerance = _validate_float(position_tolerance, "position_tolerance", 0.0)

    shape_name = _mesh_shape(object_name)
    prefix_name = _prefix(shape_name)
    dag = _dag_path(shape_name)
    mesh_fn = om.MFnMesh(dag)
    points = mesh_fn.getPoints(om.MSpace.kWorld)
    seeds = _seed_filters()

    boundary_edges = {}
    edges_by_vertex = {}
    edge_it = om.MItMeshEdge(dag)
    while not edge_it.isDone():
        if edge_it.onBoundary():
            edge_id = int(edge_it.index())
            vertices = (int(edge_it.vertexId(0)), int(edge_it.vertexId(1)))
            faces = [int(face_id) for face_id in edge_it.getConnectedFaces()]
            boundary_edges[edge_id] = {"vertices": vertices, "faces": faces}
            for vertex_id in vertices:
                edges_by_vertex.setdefault(vertex_id, []).append(edge_id)
        edge_it.next()

    adjacency = {edge_id: set() for edge_id in boundary_edges}
    for connected_edges in edges_by_vertex.values():
        for edge_id in connected_edges:
            adjacency[edge_id].update(other for other in connected_edges if other != edge_id)

    loops = []
    visited = set()
    for edge_id in sorted(boundary_edges):
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
        group = sorted(group)
        vertex_ids = sorted({vertex_id for group_edge in group for vertex_id in boundary_edges[group_edge]["vertices"]})
        if seeds is not None and not (set(group).intersection(seeds["edges"]) or set(vertex_ids).intersection(seeds["vertices"])):
            continue
        if len(group) < clean_min_edge_count:
            continue
        if clean_max_edge_count and len(group) > clean_max_edge_count:
            continue
        degrees = {vertex_id: len([edge for edge in edges_by_vertex.get(vertex_id, []) if edge in group]) for vertex_id in vertex_ids}
        closed = bool(group) and all(degree == 2 for degree in degrees.values())
        vertex_points = [points[vertex_id] for vertex_id in vertex_ids]
        bbox_min, bbox_max = _bbox(vertex_points)
        axis_span = [float(bbox_max[index] - bbox_min[index]) for index in range(3)]
        center = [(bbox_min[index] + bbox_max[index]) * 0.5 for index in range(3)]
        edge_lengths = [_edge_length(boundary_edges[group_edge]["vertices"], points) for group_edge in group]
        perimeter = sum(edge_lengths)
        ordered = _ordered_walk(group, vertex_ids, edges_by_vertex, closed)
        ordered_vertex_ids = ordered["vertex_ids"]
        degree_histogram = {}
        for degree in degrees.values():
            degree_histogram[str(degree)] = degree_histogram.get(str(degree), 0) + 1
        branch_vertices = [vertex_id for vertex_id, degree in degrees.items() if degree > 2]
        endpoint_vertices = [vertex_id for vertex_id, degree in degrees.items() if degree == 1]
        duplicate_positions = _duplicate_positions(vertex_ids, clean_position_tolerance, clean_max_components_per_loop)
        planarity = _planarity(ordered_vertex_ids, closed and ordered["complete"], clean_planarity_tolerance)
        loops.append({
            "loop_index": len(loops),
            "closed": closed,
            "simple_loop": bool(closed and not branch_vertices and len(group) == len(vertex_ids) and ordered["complete"]),
            "edge_count": len(group),
            "vertex_count": len(vertex_ids),
            "perimeter": perimeter,
            "center": center,
            "bounding_box": {"min": bbox_min, "max": bbox_max},
            "axis_span": axis_span,
            "smallest_span_axis": ["x", "y", "z"][axis_span.index(min(axis_span))] if axis_span else None,
            "edge_length_stats": _length_stats(edge_lengths),
            "degree_histogram": degree_histogram,
            "endpoint_vertex_count": len(endpoint_vertices),
            "branch_vertex_count": len(branch_vertices),
            "branch_vertices": [_component("vtx", vertex_id) for vertex_id in sorted(branch_vertices)[:clean_max_components_per_loop]],
            "branch_vertices_truncated": len(branch_vertices) > clean_max_components_per_loop,
            "ordered_traversal": {
                "complete": ordered["complete"],
                "closes_to_start": ordered["closes_to_start"],
                "unvisited_edge_count": ordered["unvisited_edge_count"],
                "warning": ordered["warning"],
                "edge_components": [_component("e", edge_id) for edge_id in ordered["edge_ids"][:clean_max_components_per_loop]],
                "edge_components_truncated": len(ordered["edge_ids"]) > clean_max_components_per_loop,
                "vertex_components": [_component("vtx", vertex_id) for vertex_id in ordered_vertex_ids[:clean_max_components_per_loop]],
                "vertex_components_truncated": len(ordered_vertex_ids) > clean_max_components_per_loop,
            },
            "planarity": planarity,
            "duplicate_positions": duplicate_positions,
            "edge_components": [_component("e", edge_id) for edge_id in group[:clean_max_components_per_loop]],
            "edge_components_truncated": len(group) > clean_max_components_per_loop,
            "vertex_components": [_component("vtx", vertex_id) for vertex_id in vertex_ids[:clean_max_components_per_loop]],
            "vertex_components_truncated": len(vertex_ids) > clean_max_components_per_loop,
            "open_chain_endpoint_vertices": [
                _component("vtx", vertex_id)
                for vertex_id, degree in sorted(degrees.items())
                if degree == 1
            ][:clean_max_components_per_loop],
        })

    reverse = clean_sort_by.endswith("_desc")
    if clean_sort_by.startswith("edge_count"):
        loops.sort(key=lambda item: (item["edge_count"], item["loop_index"]), reverse=reverse)
    elif clean_sort_by.startswith("perimeter"):
        loops.sort(key=lambda item: (item["perimeter"], item["loop_index"]), reverse=reverse)
    else:
        loops.sort(key=lambda item: (item["center"][1], item["loop_index"]), reverse=reverse)
    for index, loop in enumerate(loops):
        loop["sorted_index"] = index

    selected = []
    if select_components:
        for loop in loops:
            selected.extend(loop["edge_components"])
        selected = list(dict.fromkeys(selected))
        if selected:
            cmds.select(selected, **{clean_selection_mode: True})
        elif clean_selection_mode == "replace":
            cmds.select(clear=True)

    returned_loops = loops[:clean_max_loops]
    return {
        "success": True,
        "object_name": object_name,
        "shape_name": shape_name,
        "boundary_edge_count": len(boundary_edges),
        "boundary_loop_count": len(loops),
        "returned_loop_count": len(returned_loops),
        "loops_truncated": len(loops) > clean_max_loops,
        "sort_by": clean_sort_by,
        "filters": {
            "has_seed_components": bool(seeds),
            "min_edge_count": clean_min_edge_count,
            "max_edge_count": clean_max_edge_count,
            "planarity_tolerance": clean_planarity_tolerance,
            "position_tolerance": clean_position_tolerance,
        },
        "loops": returned_loops,
        "selected": bool(select_components),
        "selection_mode": clean_selection_mode if select_components else None,
        "selected_edge_count": len(selected),
        "selected_edges_preview": selected[:clean_max_components_per_loop],
    }
