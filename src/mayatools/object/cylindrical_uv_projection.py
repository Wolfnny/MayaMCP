from typing import Dict, List, Any


def cylindrical_uv_projection(
    object_name: str,
    uv_set: str = "map1",
    center: List[float] = [0.0, 0.0, 0.0],
    axis: str = "y",
    axis_range: List[float] = None,
    angle_range_degrees: List[float] = [0.0, 360.0],
    flip_u: bool = False,
    flip_v: bool = False,
    outside_angle_mode: str = "wrap",
    set_current: bool = True,
) -> Dict[str, Any]:
    """Create or replace UVs from world-space cylindrical coordinates.

    The selected mesh is sampled in world space around the chosen axis. U is
    derived from angular position and V from height along the axis. UVs are
    assigned per face-vertex instead of per shared vertex, so seams and partial
    angular ranges remain stable. This is useful for generic bottles, cans,
    cups, tubes, columns, and other lathed objects that need deterministic
    texture placement before material assignment, trimming, or texture-driven
    deformation.
    """
    import math
    import maya.cmds as cmds

    try:
        import maya.api.OpenMaya as om
    except Exception as exc:
        raise RuntimeError("maya.api.OpenMaya is required to edit mesh UVs.") from exc

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(value) for value in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(value) for value in values]

    def _clamp(value, lower=0.0, upper=1.0):
        return max(lower, min(upper, value))

    def _positive_span(start_degrees, end_degrees):
        span = (end_degrees - start_degrees) % 360.0
        return 360.0 if abs(span) < 1e-8 else span

    def _angle_delta(angle_degrees, start_degrees):
        return (angle_degrees - start_degrees) % 360.0

    def _angle_u(angle_degrees, start_degrees, span_degrees):
        delta = _angle_delta(angle_degrees, start_degrees)
        if span_degrees >= 360.0 - 1e-8:
            return delta / 360.0

        if delta <= span_degrees:
            return delta / span_degrees

        if outside_angle_mode == "wrap":
            return (delta / span_degrees) % 1.0
        if outside_angle_mode == "clamp":
            distance_to_start = min(delta, 360.0 - delta)
            distance_to_end = abs(delta - span_degrees)
            return 0.0 if distance_to_start < distance_to_end else 1.0
        return delta / span_degrees

    def _shape_dag_path(node_name):
        selection = om.MSelectionList()
        selection.add(node_name)
        dag_path = selection.getDagPath(0)
        if dag_path.node().hasFn(om.MFn.kTransform):
            dag_path.extendToShape()
        if not dag_path.node().hasFn(om.MFn.kMesh):
            raise ValueError(f"{object_name} is not a polygon mesh transform or mesh shape.")
        return dag_path

    if not object_name:
        raise ValueError("object_name is required.")
    if not cmds.objExists(object_name):
        raise ValueError(f"Object does not exist: {object_name}")
    if not uv_set:
        raise ValueError("uv_set is required.")

    center = _validate_vector(center, 3, "center")
    if axis_range is not None:
        axis_range = _validate_vector(axis_range, 2, "axis_range")
    angle_range_degrees = _validate_vector(angle_range_degrees, 2, "angle_range_degrees")

    axis = axis.lower().strip()
    axes = {
        "x": (0, 1, 2),
        "y": (1, 0, 2),
        "z": (2, 0, 1),
    }
    if axis not in axes:
        raise ValueError("axis must be one of x, y, or z.")
    axis_index, radial_a, radial_b = axes[axis]

    outside_angle_mode = outside_angle_mode.lower().strip()
    if outside_angle_mode not in {"wrap", "clamp", "extend"}:
        raise ValueError("outside_angle_mode must be wrap, clamp, or extend.")

    angle_start, angle_end = angle_range_degrees
    angle_span = _positive_span(angle_start, angle_end)

    dag_path = _shape_dag_path(object_name)
    mesh_fn = om.MFnMesh(dag_path)
    uv_sets = list(mesh_fn.getUVSetNames())
    if uv_set not in uv_sets:
        mesh_fn.createUVSet(uv_set)
    if set_current:
        try:
            mesh_fn.setCurrentUVSetName(uv_set)
        except Exception:
            cmds.polyUVSet(object_name, currentUVSet=True, uvSet=uv_set)

    points = mesh_fn.getPoints(om.MSpace.kWorld)
    face_counts, vertex_ids = mesh_fn.getVertices()
    if not face_counts:
        raise ValueError(f"No polygon faces found on {object_name}.")

    if axis_range is None:
        axis_values = [point[axis_index] - center[axis_index] for point in points]
        axis_start = min(axis_values)
        axis_end = max(axis_values)
    else:
        axis_start, axis_end = axis_range
        if axis_start > axis_end:
            axis_start, axis_end = axis_end, axis_start
    axis_span = axis_end - axis_start
    if axis_span <= 1e-12:
        raise ValueError("axis_range must cover a positive span.")

    u_values = []
    v_values = []
    uv_ids = []
    cursor = 0
    min_u = None
    max_u = None
    min_v = None
    max_v = None

    for count in face_counts:
        for _ in range(count):
            vertex_id = vertex_ids[cursor]
            point = points[vertex_id]
            delta_a = point[radial_a] - center[radial_a]
            delta_b = point[radial_b] - center[radial_b]
            angle_degrees = math.degrees(math.atan2(delta_a, delta_b))

            u = _angle_u(angle_degrees, angle_start, angle_span)
            v = (point[axis_index] - center[axis_index] - axis_start) / axis_span
            if flip_u:
                u = 1.0 - u
            if flip_v:
                v = 1.0 - v

            uv_ids.append(len(u_values))
            u_values.append(float(u))
            v_values.append(float(v))
            min_u = u if min_u is None else min(min_u, u)
            max_u = u if max_u is None else max(max_u, u)
            min_v = v if min_v is None else min(min_v, v)
            max_v = v if max_v is None else max(max_v, v)
            cursor += 1

    try:
        mesh_fn.clearUVs(uv_set)
    except Exception:
        pass
    mesh_fn.setUVs(u_values, v_values, uv_set)
    mesh_fn.assignUVs(face_counts, uv_ids, uv_set)
    mesh_fn.updateSurface()

    if set_current:
        try:
            cmds.polyUVSet(object_name, currentUVSet=True, uvSet=uv_set)
        except Exception:
            pass

    return {
        "success": True,
        "object_name": object_name,
        "uv_set": uv_set,
        "center": center,
        "axis": axis,
        "axis_range": [axis_start, axis_end],
        "angle_range_degrees": angle_range_degrees,
        "angle_span_degrees": angle_span,
        "flip_u": bool(flip_u),
        "flip_v": bool(flip_v),
        "outside_angle_mode": outside_angle_mode,
        "face_count": len(face_counts),
        "uv_count": len(u_values),
        "uv_range": {
            "min_u": _clamp(min_u) if outside_angle_mode != "extend" else min_u,
            "max_u": _clamp(max_u) if outside_angle_mode != "extend" else max_u,
            "min_v": min_v,
            "max_v": max_v,
        },
    }
