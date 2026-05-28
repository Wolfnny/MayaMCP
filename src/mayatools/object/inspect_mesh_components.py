from typing import Dict, List, Any, Union


def inspect_mesh_components(
    object_name: str,
    component_type: str = "summary",
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    max_items: int = 100,
    space: str = "world",
    include_positions: bool = True,
    include_normals: bool = True,
    include_topology: bool = True,
    include_uvs: bool = False,
    uv_set: str = None,
) -> Dict[str, Any]:
    """Inspect polygon mesh components at vertex, edge, face, UV, or summary level.

    This is a generic component-level query tool for Maya-style modeling. It
    reports mesh counts and can inspect selected or indexed vertices, edges,
    faces, and UVs with world/object positions, normals, topology, centers, and
    optional UV assignments. Use it before localized edits so component IDs,
    coordinates, face centers, and edge/vertex relationships are explicit.
    """
    import re
    import maya.cmds as cmds
    import maya.api.OpenMaya as om

    def _is_int(value):
        return isinstance(value, int) and not isinstance(value, bool)

    def _validate_int(value, arg_name, minimum):
        if not _is_int(value) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return value

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

    def _mesh_fn(shape):
        selection = om.MSelectionList()
        selection.add(shape)
        return om.MFnMesh(selection.getDagPath(0))

    def _component_prefix():
        parents = cmds.listRelatives(shape_name, parent=True, fullPath=False) or []
        return parents[0] if parents else object_name

    def _flatten_components(value):
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("components must be a string, a list of strings, or None.")
        return cmds.ls(value, flatten=True) or []

    def _indices_from_components(kind, value):
        pattern = re.compile(rf"\.{kind}\[(\d+)\]$")
        found = []
        for component in _flatten_components(value):
            match = pattern.search(component)
            if match:
                found.append(int(match.group(1)))
        return found

    def _component_indices(kind, count):
        if indices is not None:
            if not isinstance(indices, list) or not all(_is_int(index) for index in indices):
                raise ValueError("indices must be a list of integers.")
            clean = list(dict.fromkeys(indices))
        elif components is not None:
            clean = _indices_from_components(kind, components)
        else:
            selected = cmds.ls(selection=True, flatten=True) or []
            clean = _indices_from_components(kind, selected)
        for index in clean:
            if index < 0 or index >= count:
                raise ValueError(f"{kind}[{index}] is out of range 0..{count - 1}.")
        return clean[:max_items]

    def _component_id_list(items, kind):
        pattern = re.compile(rf"\.{kind}\[(\d+)\]$")
        ids = []
        for item in cmds.ls(items, flatten=True) or []:
            match = pattern.search(item)
            if match:
                ids.append(int(match.group(1)))
        return sorted(set(ids))

    def _point_list(points, index):
        point = points[index]
        return [float(point.x), float(point.y), float(point.z)]

    def _vector_list(vector):
        return [float(vector.x), float(vector.y), float(vector.z)]

    def _face_center(points, face_vertices):
        center = [0.0, 0.0, 0.0]
        for vertex_id in face_vertices:
            point = points[vertex_id]
            center[0] += point.x
            center[1] += point.y
            center[2] += point.z
        count = float(max(1, len(face_vertices)))
        return [center[0] / count, center[1] / count, center[2] / count]

    def _uv_values_for_face(face_id, face_vertices):
        if not include_uvs:
            return None
        face_uvs = []
        for local_index, vertex_id in enumerate(face_vertices):
            try:
                uv_id = mesh_fn.getPolygonUVid(face_id, local_index, clean_uv_set)
                u_value, v_value = mesh_fn.getUV(uv_id, clean_uv_set)
                face_uvs.append({"vertex_index": vertex_id, "uv_index": uv_id, "uv": [float(u_value), float(v_value)]})
            except Exception:
                face_uvs.append({"vertex_index": vertex_id, "uv_index": None, "uv": None})
        return face_uvs

    if not object_name:
        raise ValueError("object_name is required.")
    component_type = component_type.lower().strip()
    if component_type not in {"summary", "vertex", "edge", "face", "uv", "selection"}:
        raise ValueError("component_type must be summary, vertex, edge, face, uv, or selection.")
    max_items = _validate_int(max_items, "max_items", 1)
    space = space.lower().strip()
    if space not in {"world", "object"}:
        raise ValueError("space must be world or object.")
    om_space = om.MSpace.kWorld if space == "world" else om.MSpace.kObject

    shape_name = _mesh_shape(object_name)
    mesh_fn = _mesh_fn(shape_name)
    prefix = _component_prefix()
    points = mesh_fn.getPoints(om_space)
    clean_uv_set = uv_set or (mesh_fn.currentUVSetName() if mesh_fn.numUVs() else None)

    counts = {
        "vertices": int(mesh_fn.numVertices),
        "edges": int(mesh_fn.numEdges),
        "faces": int(mesh_fn.numPolygons),
        "uvs": int(mesh_fn.numUVs(clean_uv_set)) if clean_uv_set else 0,
    }

    result = {
        "success": True,
        "object_name": object_name,
        "shape_name": shape_name,
        "component_type": component_type,
        "space": space,
        "counts": counts,
        "uv_sets": list(mesh_fn.getUVSetNames()),
        "uv_set": clean_uv_set,
    }

    if component_type == "summary":
        result["bounding_box"] = cmds.exactWorldBoundingBox(object_name)
        return result

    if component_type == "selection":
        selection = cmds.ls(selection=True, flatten=True) or []
        result["selection"] = selection[:max_items]
        result["selection_count"] = len(selection)
        return result

    if component_type == "vertex":
        vertex_indices = _component_indices("vtx", counts["vertices"])
        items = []
        for vertex_id in vertex_indices:
            item = {"index": vertex_id, "component": f"{prefix}.vtx[{vertex_id}]"}
            if include_positions:
                item["position"] = _point_list(points, vertex_id)
            if include_normals:
                try:
                    item["normal"] = _vector_list(mesh_fn.getVertexNormal(vertex_id, True, om_space))
                except Exception:
                    item["normal"] = None
            if include_topology:
                vertex_component = f"{prefix}.vtx[{vertex_id}]"
                item["connected_edges"] = _component_id_list(
                    cmds.polyListComponentConversion(vertex_component, fromVertex=True, toEdge=True) or [],
                    "e",
                )
                item["connected_faces"] = _component_id_list(
                    cmds.polyListComponentConversion(vertex_component, fromVertex=True, toFace=True) or [],
                    "f",
                )
            items.append(item)
        result["vertices"] = items
        result["returned_count"] = len(items)
        return result

    if component_type == "edge":
        edge_indices = _component_indices("e", counts["edges"])
        items = []
        for edge_id in edge_indices:
            vertices = list(mesh_fn.getEdgeVertices(edge_id))
            item = {"index": edge_id, "component": f"{prefix}.e[{edge_id}]"}
            if include_topology:
                item["vertices"] = vertices
                item["connected_faces"] = _component_id_list(
                    cmds.polyListComponentConversion(f"{prefix}.e[{edge_id}]", fromEdge=True, toFace=True) or [],
                    "f",
                )
            if include_positions:
                item["points"] = [_point_list(points, vertex_id) for vertex_id in vertices]
                item["center"] = _face_center(points, vertices)
            items.append(item)
        result["edges"] = items
        result["returned_count"] = len(items)
        return result

    if component_type == "face":
        face_indices = _component_indices("f", counts["faces"])
        items = []
        for face_id in face_indices:
            vertices = list(mesh_fn.getPolygonVertices(face_id))
            item = {"index": face_id, "component": f"{prefix}.f[{face_id}]"}
            if include_topology:
                item["vertices"] = vertices
            if include_positions:
                item["center"] = _face_center(points, vertices)
                item["points"] = [_point_list(points, vertex_id) for vertex_id in vertices]
            if include_normals:
                try:
                    item["normal"] = _vector_list(mesh_fn.getPolygonNormal(face_id, om_space))
                except Exception:
                    item["normal"] = None
            if include_uvs:
                item["uvs"] = _uv_values_for_face(face_id, vertices)
            items.append(item)
        result["faces"] = items
        result["returned_count"] = len(items)
        return result

    uv_indices = _component_indices("map", counts["uvs"])
    items = []
    for uv_id in uv_indices:
        try:
            u_value, v_value = mesh_fn.getUV(uv_id, clean_uv_set)
            uv_value = [float(u_value), float(v_value)]
        except Exception:
            uv_value = None
        items.append({"index": uv_id, "component": f"{prefix}.map[{uv_id}]", "uv": uv_value})
    result["uvs"] = items
    result["returned_count"] = len(items)
    return result
