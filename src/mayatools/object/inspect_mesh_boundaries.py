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
) -> Dict[str, Any]:
    """Inspect polygon mesh boundary loops without modifying geometry.

    Reports connected border-edge groups with edge/vertex counts, whether the
    group is a closed loop or open chain, world-space center, bounding box,
    perimeter, and component previews. Components can be supplied as seed
    vertices/edges/faces to return only boundary loops touching those seeds.
    This is useful before fill-hole, bridge, sew, cap, delete-edge, or weld
    work so an artist can decide which openings are intentional and which are
    repair targets.
    """
    import re
    import maya.cmds as cmds
    import maya.api.OpenMaya as om

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
        center = [(bbox_min[index] + bbox_max[index]) * 0.5 for index in range(3)]
        perimeter = sum(_edge_length(boundary_edges[group_edge]["vertices"], points) for group_edge in group)
        loops.append({
            "loop_index": len(loops),
            "closed": closed,
            "edge_count": len(group),
            "vertex_count": len(vertex_ids),
            "perimeter": perimeter,
            "center": center,
            "bounding_box": {"min": bbox_min, "max": bbox_max},
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
        },
        "loops": returned_loops,
        "selected": bool(select_components),
        "selection_mode": clean_selection_mode if select_components else None,
        "selected_edge_count": len(selected),
        "selected_edges_preview": selected[:clean_max_components_per_loop],
    }
