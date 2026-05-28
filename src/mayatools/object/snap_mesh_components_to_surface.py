from typing import Dict, List, Any, Union


def snap_mesh_components_to_surface(
    object_name: str,
    target_object_name: str,
    component_type: str = "vertex",
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    projection_mode: str = "closest_point",
    ray_direction: List[float] = None,
    ray_both_directions: bool = False,
    max_distance: float = None,
    fallback_to_closest: bool = True,
    offset: float = 0.0,
    offset_direction: str = "target_normal",
    space: str = "world",
    use_selection: bool = True,
    max_preview: int = 20,
) -> Dict[str, Any]:
    """Snap source mesh components onto a target mesh surface.

    projection_mode:
    - closest_point: move each resolved source vertex to the closest point on
      target_object_name
    - ray: project each resolved source vertex along ray_direction and use the
      ray hit on target_object_name, optionally falling back to closest_point

    Edges and faces are converted to their unique vertices before snapping.
    offset can then move the snapped vertex along the target surface normal or
    along the source-to-hit direction. This is useful for shrinkwrap-style
    label, decal, panel, patch, retopology, and contact cleanup workflows.
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

    def _normalize(values, arg_name):
        vector = _validate_vector(values, 3, arg_name)
        length = math.sqrt(vector[0] * vector[0] + vector[1] * vector[1] + vector[2] * vector[2])
        if length <= 1e-9:
            raise ValueError(f"{arg_name} must not be a zero vector.")
        return [vector[0] / length, vector[1] / length, vector[2] / length]

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

    def _prefix(shape, fallback):
        parents = cmds.listRelatives(shape, parent=True, fullPath=False) or []
        return parents[0] if parents else fallback

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
        return [f"{source_prefix}.{kind}[{index}]" for index in indices]

    def _selected_components():
        if not use_selection:
            return []
        selected = cmds.ls(selection=True, flatten=True) or []
        object_tokens = {object_name, source_prefix, source_shape}
        return [item for item in selected if item.split(".", 1)[0] in object_tokens]

    def _resolve_components():
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
        return resolved

    def _vertex_ids_from_components(items):
        converted = cmds.polyListComponentConversion(items, toVertex=True) or []
        vertices = cmds.ls(converted, flatten=True) or []
        ids = []
        pattern = re.compile(r"\.vtx\[(\d+)\]$")
        for vertex in vertices:
            match = pattern.search(vertex)
            if match:
                ids.append(int(match.group(1)))
        return sorted(set(ids))

    def _point_list(point):
        return [float(point.x), float(point.y), float(point.z)]

    def _vector_list(vector):
        return [float(vector.x), float(vector.y), float(vector.z)]

    def _distance(a, b):
        return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)

    def _offset_point(source_point, hit_point, normal_vector):
        if abs(clean_offset) <= 1e-12:
            return om.MPoint(hit_point.x, hit_point.y, hit_point.z)
        if clean_offset_direction == "none":
            return om.MPoint(hit_point.x, hit_point.y, hit_point.z)
        if clean_offset_direction == "target_normal":
            direction = normal_vector.normal()
        elif clean_offset_direction == "source_to_hit":
            direction = om.MVector(hit_point.x - source_point.x, hit_point.y - source_point.y, hit_point.z - source_point.z)
            if direction.length() <= 1e-9:
                direction = normal_vector.normal()
            else:
                direction.normalize()
        elif clean_offset_direction == "hit_to_source":
            direction = om.MVector(source_point.x - hit_point.x, source_point.y - hit_point.y, source_point.z - hit_point.z)
            if direction.length() <= 1e-9:
                direction = normal_vector.normal()
            else:
                direction.normalize()
        else:
            raise ValueError("offset_direction must be none, target_normal, source_to_hit, or hit_to_source.")
        return om.MPoint(
            hit_point.x + direction.x * clean_offset,
            hit_point.y + direction.y * clean_offset,
            hit_point.z + direction.z * clean_offset,
        )

    def _closest_match(source_point):
        hit_point, hit_normal, face_id = target_fn.getClosestPointAndNormal(source_point, om_space)
        return {
            "mode": "closest_point",
            "hit_point": hit_point,
            "normal": hit_normal,
            "face_id": int(face_id),
            "distance": _distance(source_point, hit_point),
        }

    def _ray_match(source_point):
        hit = target_fn.closestIntersection(
            om.MFloatPoint(source_point.x, source_point.y, source_point.z),
            om.MFloatVector(clean_ray_direction[0], clean_ray_direction[1], clean_ray_direction[2]),
            om_space,
            clean_max_distance,
            bool(ray_both_directions),
        )
        if hit is None:
            return None
        hit_point = om.MPoint(hit[0])
        closest_point, hit_normal, face_id = target_fn.getClosestPointAndNormal(hit_point, om_space)
        return {
            "mode": "ray",
            "hit_point": hit_point,
            "normal": hit_normal,
            "face_id": int(face_id),
            "ray_param": float(hit[1]),
            "distance": _distance(source_point, hit_point),
            "closest_point_error": _distance(hit_point, closest_point),
        }

    def _preview_record(vertex_id, before_point, after_point, match):
        return {
            "index": vertex_id,
            "component": f"{source_prefix}.vtx[{vertex_id}]",
            "before": _point_list(before_point),
            "after": _point_list(after_point),
            "target_point": _point_list(match["hit_point"]),
            "target_normal": _vector_list(match["normal"]),
            "target_face": match["face_id"],
            "match_mode": match["mode"],
            "distance": match["distance"],
        }

    if not object_name:
        raise ValueError("object_name is required.")
    if not target_object_name:
        raise ValueError("target_object_name is required.")
    projection_mode = projection_mode.lower().strip()
    if projection_mode not in {"closest_point", "ray"}:
        raise ValueError("projection_mode must be closest_point or ray.")
    component_type = component_type.lower().strip()
    if component_type not in {"vertex", "edge", "face", "uv", "vertex_face"}:
        raise ValueError("component_type must be vertex, edge, face, uv, or vertex_face.")
    space = space.lower().strip()
    if space not in {"world", "object"}:
        raise ValueError("space must be world or object.")
    clean_offset = _validate_scalar(offset, "offset")
    clean_offset_direction = offset_direction.lower().strip()
    if clean_offset_direction not in {"none", "target_normal", "source_to_hit", "hit_to_source"}:
        raise ValueError("offset_direction must be none, target_normal, source_to_hit, or hit_to_source.")
    max_preview = _validate_int(max_preview, "max_preview", 0)
    clean_max_distance = float(max_distance) if max_distance is not None else 1.0e12
    if clean_max_distance <= 0.0:
        raise ValueError("max_distance must be greater than zero when provided.")
    clean_ray_direction = None
    if projection_mode == "ray":
        clean_ray_direction = _normalize(ray_direction, "ray_direction")

    source_shape = _mesh_shape(object_name)
    target_shape = _mesh_shape(target_object_name)
    source_prefix = _prefix(source_shape, object_name)
    source_fn = _mesh_fn(source_shape)
    target_fn = _mesh_fn(target_shape)
    om_space = om.MSpace.kWorld if space == "world" else om.MSpace.kObject

    resolved_components = _resolve_components()
    vertex_ids = _vertex_ids_from_components(resolved_components)
    if not vertex_ids:
        raise ValueError("No vertices resolved from components, indices, or current selection.")

    points = source_fn.getPoints(om_space)
    before_points = {vertex_id: om.MPoint(points[vertex_id]) for vertex_id in vertex_ids}
    preview = []
    skipped = []
    moved_count = 0

    for vertex_id in vertex_ids:
        source_point = points[vertex_id]
        match = None
        if projection_mode == "ray":
            match = _ray_match(source_point)
        if match is None and (projection_mode == "closest_point" or fallback_to_closest):
            match = _closest_match(source_point)
        if match is None:
            skipped.append({"index": vertex_id, "reason": "no_intersection"})
            continue
        if match["distance"] > clean_max_distance:
            skipped.append({"index": vertex_id, "reason": "beyond_max_distance", "distance": match["distance"]})
            continue
        snapped_point = _offset_point(source_point, match["hit_point"], match["normal"])
        points[vertex_id] = snapped_point
        moved_count += 1
        if len(preview) < max_preview:
            preview.append(_preview_record(vertex_id, before_points[vertex_id], snapped_point, match))

    if moved_count == 0:
        raise RuntimeError("No vertices were snapped to the target surface.")

    source_fn.setPoints(points, om_space)
    try:
        source_fn.updateSurface()
    except Exception:
        pass
    cmds.select([f"{source_prefix}.vtx[{vertex_id}]" for vertex_id in vertex_ids], replace=True)

    return {
        "success": True,
        "object_name": object_name,
        "target_object_name": target_object_name,
        "operation": "snap_mesh_components_to_surface",
        "projection_mode": projection_mode,
        "space": space,
        "resolved_vertex_count": len(vertex_ids),
        "moved_vertex_count": moved_count,
        "skipped_count": len(skipped),
        "skipped_preview": skipped[:max_preview],
        "offset": clean_offset,
        "offset_direction": clean_offset_direction,
        "ray_direction": clean_ray_direction,
        "ray_both_directions": bool(ray_both_directions),
        "max_distance": None if max_distance is None else clean_max_distance,
        "fallback_to_closest": bool(fallback_to_closest),
        "preview": preview,
    }
