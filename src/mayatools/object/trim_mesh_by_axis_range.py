from typing import Dict, List, Any


def trim_mesh_by_axis_range(
    object_name: str,
    axis: str = "y",
    axis_range: List[float] = None,
    keep_inside: bool = True,
    sample_mode: str = "center",
    min_keep_faces: int = 1,
    dry_run: bool = False,
    smooth: bool = True,
) -> Dict[str, Any]:
    """Delete mesh faces by testing their position along an axis.

    This is a generic mesh cleanup tool for clipping lathed shells, cylinders,
    pipes, labels, cards, terrain strips, scan fragments, and other polygon
    geometry to an axial range. Faces can be tested by center, all vertices, or
    any vertex. Use dry_run to inspect how many faces would be removed before
    editing the mesh.
    """
    import maya.cmds as cmds
    import maya.api.OpenMaya as om

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(value) for value in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(value) for value in values]

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return value

    if not cmds.objExists(object_name):
        raise ValueError(f"Object does not exist: {object_name}")
    if axis_range is None:
        raise ValueError("axis_range is required.")

    axis = axis.lower().strip()
    axis_indices = {"x": 0, "y": 1, "z": 2}
    if axis not in axis_indices:
        raise ValueError("axis must be one of x, y, or z.")
    axis_index = axis_indices[axis]

    clean_range = _validate_vector(axis_range, 2, "axis_range")
    if clean_range[1] < clean_range[0]:
        clean_range = [clean_range[1], clean_range[0]]
    if clean_range[1] == clean_range[0]:
        raise ValueError("axis_range must have non-zero length.")

    if not isinstance(keep_inside, bool):
        raise ValueError("keep_inside must be a boolean.")
    if not isinstance(dry_run, bool):
        raise ValueError("dry_run must be a boolean.")
    if not isinstance(smooth, bool):
        raise ValueError("smooth must be a boolean.")
    min_keep_faces = _validate_int(min_keep_faces, "min_keep_faces", 0)

    sample_mode = sample_mode.lower().strip()
    if sample_mode not in {"center", "all_vertices", "any_vertex"}:
        raise ValueError("sample_mode must be center, all_vertices, or any_vertex.")

    shapes = cmds.listRelatives(object_name, shapes=True, fullPath=True) or []
    if cmds.objectType(object_name) == "mesh":
        shapes = [object_name]
    mesh_shapes = [shape for shape in shapes if cmds.objectType(shape) == "mesh"]
    if not mesh_shapes:
        raise ValueError(f"{object_name} is not a polygon mesh transform or mesh shape.")

    selection = om.MSelectionList()
    selection.add(mesh_shapes[0])
    dag_path = selection.getDagPath(0)
    mesh_fn = om.MFnMesh(dag_path)
    points = mesh_fn.getPoints(om.MSpace.kWorld)
    face_count = mesh_fn.numPolygons
    if face_count < 1:
        raise ValueError(f"No polygon faces found on {object_name}.")

    def _inside(value):
        return clean_range[0] <= value <= clean_range[1]

    matched_faces = []
    kept_faces = 0
    min_sample_value = None
    max_sample_value = None
    for face_index in range(face_count):
        vertex_indices = mesh_fn.getPolygonVertices(face_index)
        values = [points[index][axis_index] for index in vertex_indices]
        if not values:
            continue
        min_value = min(values)
        max_value = max(values)
        min_sample_value = min(min_sample_value, min_value) if min_sample_value is not None else min_value
        max_sample_value = max(max_sample_value, max_value) if max_sample_value is not None else max_value

        if sample_mode == "center":
            face_is_inside = _inside(sum(values) / float(len(values)))
        elif sample_mode == "all_vertices":
            face_is_inside = all(_inside(value) for value in values)
        else:
            face_is_inside = any(_inside(value) for value in values)

        should_delete = face_is_inside != keep_inside
        if should_delete:
            matched_faces.append(face_index)
        else:
            kept_faces += 1

    if kept_faces < min_keep_faces:
        raise ValueError(
            f"Axis trim would leave {kept_faces} faces, which is below min_keep_faces={min_keep_faces}."
        )

    deleted_faces = []
    if matched_faces and not dry_run:
        target_transform = object_name
        if cmds.objectType(object_name) == "mesh":
            parents = cmds.listRelatives(object_name, parent=True, fullPath=False) or []
            target_transform = parents[0] if parents else object_name
        delete_components = [f"{target_transform}.f[{index}]" for index in matched_faces]
        cmds.delete(delete_components)
        deleted_faces = delete_components[:]
        if smooth and cmds.objExists(target_transform):
            try:
                cmds.polySoftEdge(target_transform, angle=180, constructionHistory=False)
            except Exception:
                pass

    return {
        "success": True,
        "object_name": object_name,
        "axis": axis,
        "axis_range": clean_range,
        "keep_inside": bool(keep_inside),
        "sample_mode": sample_mode,
        "dry_run": bool(dry_run),
        "face_count_before": face_count,
        "matched_face_count": len(matched_faces),
        "deleted_face_count": len(deleted_faces),
        "face_count_after": face_count if dry_run else face_count - len(deleted_faces),
        "min_keep_faces": min_keep_faces,
        "min_sample_value": min_sample_value,
        "max_sample_value": max_sample_value,
        "matched_faces_preview": [f"{object_name}.f[{index}]" for index in matched_faces[:20]],
    }
