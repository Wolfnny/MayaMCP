from typing import Dict, List, Any, Union


def edit_mesh_normals(
    object_name: str,
    operation: str = "query",
    component_type: str = None,
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    normal: List[float] = None,
    angle: float = 30.0,
    distance: float = 0.0,
    normalize_vector: bool = True,
    construction_history: bool = False,
    use_selection: bool = True,
    max_preview: int = 50,
) -> Dict[str, Any]:
    """Query and edit polygon face, edge, and vertex normals.

    Operations:
    - query: report face normals and per-vertex normals for resolved components
    - soften_edges: set selected edges or the object to 180 degree soft edges
    - harden_edges: set selected edges or the object to 0 degree hard edges
    - set_edge_softness: set selected edges or the object to angle
    - reverse_faces: reverse selected face normals
    - conform_faces: conform selected face normals to a consistent direction
    - set_to_face_normals: assign vertex normals from selected face normals
    - set_vertex_normals: set selected vertex normals to normal [x, y, z]
    - lock_normals: freeze selected vertex normals
    - unlock_normals: unfreeze selected vertex normals
    - average_normals: average selected vertex normals within distance

    This provides Maya-style normal control for localized shading and highlight
    cleanup without relying on object-wide smoothing shortcuts.
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

    def _normal_vector(values):
        vector = _validate_vector(values, 3, "normal")
        if normalize_vector:
            length = math.sqrt(sum(item * item for item in vector))
            if length <= 1e-9:
                raise ValueError("normal must not be a zero vector when normalize_vector is true.")
            vector = [item / length for item in vector]
        return vector

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

    def _resolve_components(default_type=None, allow_object=False):
        clean_type = (component_type or default_type or "").lower().strip()
        kind_map = {"vertex": "vtx", "edge": "e", "face": "f", "uv": "map", "vertex_face": "vtxFace"}
        if components is not None:
            resolved = _flatten(components)
        elif clean_type in kind_map and indices is not None:
            resolved = _components_from_indices(kind_map[clean_type])
        else:
            resolved = _selected_components()
        if not resolved and allow_object:
            return [object_name]
        if not resolved:
            raise ValueError("No components resolved from components, indices, or current selection.")
        return resolved

    def _component_ids(items, kind):
        pattern = re.compile(rf"\.{kind}\[(\d+)\]$")
        ids = []
        for item in cmds.ls(items, flatten=True) or []:
            match = pattern.search(item)
            if match:
                ids.append(int(match.group(1)))
        return sorted(set(ids))

    def _to_vertices(items):
        converted = cmds.polyListComponentConversion(items, toVertex=True) or []
        return cmds.ls(converted, flatten=True) or []

    def _to_edges(items):
        converted = cmds.polyListComponentConversion(items, toEdge=True) or []
        return cmds.ls(converted, flatten=True) or []

    def _to_faces(items):
        converted = cmds.polyListComponentConversion(items, toFace=True) or []
        return cmds.ls(converted, flatten=True) or []

    def _normal_triplets(values):
        triplets = []
        for index in range(0, len(values or []), 3):
            if index + 2 < len(values):
                triplets.append([float(values[index]), float(values[index + 1]), float(values[index + 2])])
        return triplets

    def _query_components(items):
        faces = _to_faces(items)
        vertices = _to_vertices(items)
        face_records = []
        for face_id in _component_ids(faces, "f")[:max_preview]:
            vector = mesh_fn.getPolygonNormal(face_id, om.MSpace.kWorld)
            face_records.append(
                {
                    "component": f"{prefix_name}.f[{face_id}]",
                    "index": face_id,
                    "normal": [float(vector.x), float(vector.y), float(vector.z)],
                }
            )

        vertex_records = []
        for vertex in vertices[:max_preview]:
            vertex_id_match = re.search(r"\.vtx\[(\d+)\]$", vertex)
            vertex_id = int(vertex_id_match.group(1)) if vertex_id_match else None
            normals = _normal_triplets(cmds.polyNormalPerVertex(vertex, query=True, xyz=True) or [])
            locked = cmds.polyNormalPerVertex(vertex, query=True, allLocked=True) or []
            vertex_records.append(
                {
                    "component": vertex,
                    "index": vertex_id,
                    "normals": normals,
                    "all_locked": bool(locked[0]) if locked else None,
                }
            )

        return {
            "faces": face_records,
            "vertices": vertex_records,
            "face_count": len(_component_ids(faces, "f")),
            "vertex_count": len(_component_ids(vertices, "vtx")),
        }

    def _counts():
        return {
            "vertices": int(cmds.polyEvaluate(object_name, vertex=True)),
            "edges": int(cmds.polyEvaluate(object_name, edge=True)),
            "faces": int(cmds.polyEvaluate(object_name, face=True)),
        }

    if not object_name:
        raise ValueError("object_name is required.")
    operation = operation.lower().strip()
    allowed = {
        "query",
        "soften_edges",
        "harden_edges",
        "set_edge_softness",
        "reverse_faces",
        "conform_faces",
        "set_to_face_normals",
        "set_vertex_normals",
        "lock_normals",
        "unlock_normals",
        "average_normals",
    }
    if operation not in allowed:
        raise ValueError(f"operation must be one of: {', '.join(sorted(allowed))}.")
    max_preview = _validate_int(max_preview, "max_preview", 0)
    shape_name = _mesh_shape(object_name)
    prefix_name = _prefix(shape_name)
    mesh_fn = _mesh_fn(shape_name)
    before_counts = _counts()

    if operation == "query":
        resolved = _resolve_components(allow_object=True)
        return {
            "success": True,
            "object_name": object_name,
            "operation": operation,
            "components_preview": resolved[:max_preview],
            "counts": before_counts,
            "query": _query_components(resolved),
        }

    if operation in {"soften_edges", "harden_edges", "set_edge_softness"}:
        if operation == "soften_edges":
            clean_angle = 180.0
        elif operation == "harden_edges":
            clean_angle = 0.0
        else:
            clean_angle = _validate_scalar(angle, "angle")
        resolved = _resolve_components("edge", allow_object=True)
        edge_targets = resolved if resolved == [object_name] else _to_edges(resolved)
        result = cmds.polySoftEdge(edge_targets, angle=clean_angle, constructionHistory=construction_history)
        return {
            "success": True,
            "object_name": object_name,
            "operation": operation,
            "angle": clean_angle,
            "component_count": len(edge_targets),
            "components_preview": edge_targets[:max_preview],
            "node": result,
            "counts_before": before_counts,
            "counts_after": _counts(),
        }

    if operation in {"reverse_faces", "conform_faces"}:
        resolved = _resolve_components("face", allow_object=True)
        face_targets = resolved if resolved == [object_name] else _to_faces(resolved)
        mode = 0 if operation == "reverse_faces" else 1
        result = cmds.polyNormal(face_targets, normalMode=mode, constructionHistory=construction_history)
        return {
            "success": True,
            "object_name": object_name,
            "operation": operation,
            "normal_mode": mode,
            "component_count": len(face_targets),
            "components_preview": face_targets[:max_preview],
            "node": result,
            "counts_before": before_counts,
            "counts_after": _counts(),
            "query_after": _query_components(face_targets),
        }

    if operation == "set_to_face_normals":
        resolved = _resolve_components("face")
        face_targets = _to_faces(resolved)
        if not face_targets:
            raise ValueError("set_to_face_normals requires face components.")
        result = cmds.polySetToFaceNormal(face_targets, setUserNormal=True)
        return {
            "success": True,
            "object_name": object_name,
            "operation": operation,
            "component_count": len(face_targets),
            "components_preview": face_targets[:max_preview],
            "node": result,
            "counts_before": before_counts,
            "counts_after": _counts(),
            "query_after": _query_components(face_targets),
        }

    if operation in {"set_vertex_normals", "lock_normals", "unlock_normals", "average_normals"}:
        resolved = _resolve_components("vertex")
        vertex_targets = _to_vertices(resolved)
        if not vertex_targets:
            raise ValueError(f"{operation} requires vertex, edge, or face components that resolve to vertices.")

        if operation == "set_vertex_normals":
            clean_normal = _normal_vector(normal)
            result = cmds.polyNormalPerVertex(vertex_targets, xyz=clean_normal)
            applied = {"normal": clean_normal, "normalize_vector": bool(normalize_vector)}
        elif operation == "lock_normals":
            result = cmds.polyNormalPerVertex(vertex_targets, freezeNormal=True)
            applied = {"freezeNormal": True}
        elif operation == "unlock_normals":
            result = cmds.polyNormalPerVertex(vertex_targets, unFreezeNormal=True)
            applied = {"unFreezeNormal": True}
        else:
            clean_distance = _validate_scalar(distance, "distance")
            result = cmds.polyAverageNormal(
                vertex_targets,
                distance=clean_distance,
                prenormalize=True,
                postnormalize=True,
                allowZeroNormal=False,
            )
            applied = {"distance": clean_distance, "prenormalize": True, "postnormalize": True}

        return {
            "success": True,
            "object_name": object_name,
            "operation": operation,
            "component_count": len(vertex_targets),
            "components_preview": vertex_targets[:max_preview],
            "node": result,
            "applied": applied,
            "counts_before": before_counts,
            "counts_after": _counts(),
            "query_after": _query_components(vertex_targets),
        }

    raise ValueError(f"Unsupported operation: {operation}")
