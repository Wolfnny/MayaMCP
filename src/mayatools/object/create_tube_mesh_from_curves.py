from typing import Dict, List, Any


def create_tube_mesh_from_curves(
    name: str,
    curve_names: List[str] = None,
    points: List[List[float]] = None,
    tube_radius: float = 0.01,
    radial_segments: int = 8,
    cap_ends: bool = True,
    min_segment_length: float = 0.0001,
    max_points_per_curve: int = 0,
    material_color: List[float] = None,
    material_name: str = None,
    smooth: bool = True,
) -> Dict[str, Any]:
    """Create polygon tube geometry along one or more curves or point paths.

    The tool reads world-space CV positions from existing Maya curves and/or a
    direct point list, then generates a polygon tube mesh following each path.
    It is useful for turning reference-derived curves into visible geometry:
    generic raised or recessed outlines, trim wires, seams, engravings, molded
    marks, veins, routes, annotations, cables, pipes, or decorative strokes.
    """
    import math
    import maya.cmds as cmds

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(v) for v in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(value) for value in values]

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return value

    def _sub(a, b):
        return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]

    def _add(a, b):
        return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]

    def _mul(a, scalar):
        return [a[0] * scalar, a[1] * scalar, a[2] * scalar]

    def _dot(a, b):
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

    def _cross(a, b):
        return [
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        ]

    def _length(a):
        return math.sqrt(_dot(a, a))

    def _normalize(a):
        length = _length(a)
        if length <= 1e-12:
            return None
        return [a[0] / length, a[1] / length, a[2] / length]

    def _distance(a, b):
        return _length(_sub(a, b))

    def _resample_points(path_points, max_points):
        if max_points <= 0 or len(path_points) <= max_points:
            return [point[:] for point in path_points]
        if max_points < 2:
            return [path_points[0][:]]
        return [
            path_points[int(round(index * (len(path_points) - 1) / float(max_points - 1)))][:]
            for index in range(max_points)
        ]

    def _curve_points(curve_name):
        if not cmds.objExists(curve_name):
            raise ValueError(f"Curve does not exist: {curve_name}")
        shapes = cmds.listRelatives(curve_name, shapes=True, fullPath=True) or []
        if cmds.objectType(curve_name) == "nurbsCurve":
            shapes = [curve_name]
        if not any(cmds.objectType(shape) == "nurbsCurve" for shape in shapes):
            raise ValueError(f"{curve_name} is not a NURBS curve transform or shape.")
        cvs = cmds.ls(f"{curve_name}.cv[*]", flatten=True) or []
        if not cvs and shapes:
            cvs = cmds.ls(f"{shapes[0]}.cv[*]", flatten=True) or []
        return [cmds.pointPosition(cv, world=True) for cv in cvs]

    def _clean_path(path_points):
        clean = []
        for point in path_points:
            clean_point = _validate_vector(point, 3, "path point")
            if clean and _distance(clean[-1], clean_point) < min_segment_length:
                continue
            clean.append(clean_point)
        if len(clean) >= 3 and _distance(clean[0], clean[-1]) < min_segment_length:
            clean.pop()
            return clean, True
        return clean, False

    def _initial_frame(tangent):
        reference = [0.0, 1.0, 0.0]
        if abs(_dot(reference, tangent)) > 0.9:
            reference = [1.0, 0.0, 0.0]
        normal = _normalize(_cross(reference, tangent))
        if normal is None:
            normal = [1.0, 0.0, 0.0]
        binormal = _normalize(_cross(tangent, normal)) or [0.0, 0.0, 1.0]
        return normal, binormal

    def _path_tangent(path_points, index, closed):
        count = len(path_points)
        if closed:
            previous_point = path_points[(index - 1) % count]
            next_point = path_points[(index + 1) % count]
            tangent = _normalize(_sub(next_point, previous_point))
        elif index == 0:
            tangent = _normalize(_sub(path_points[1], path_points[0]))
        elif index == count - 1:
            tangent = _normalize(_sub(path_points[-1], path_points[-2]))
        else:
            tangent = _normalize(_sub(path_points[index + 1], path_points[index - 1]))
        return tangent or [0.0, 1.0, 0.0]

    def _append_tube(path_points, closed, source_name):
        start_vertex_count = len(vertices)
        start_face_count = len(face_counts)
        ring_indices = []
        previous_normal = None
        for point_index, point in enumerate(path_points):
            tangent = _path_tangent(path_points, point_index, closed)
            if previous_normal is None:
                normal, binormal = _initial_frame(tangent)
            else:
                projected = _sub(previous_normal, _mul(tangent, _dot(previous_normal, tangent)))
                normal = _normalize(projected)
                if normal is None:
                    normal, binormal = _initial_frame(tangent)
                else:
                    binormal = _normalize(_cross(tangent, normal)) or [0.0, 0.0, 1.0]
            previous_normal = normal
            ring = []
            for segment_index in range(radial_segments):
                angle = math.tau * segment_index / float(radial_segments)
                offset_vector = _add(
                    _mul(normal, math.cos(angle) * tube_radius),
                    _mul(binormal, math.sin(angle) * tube_radius),
                )
                vertices.append(_add(point, offset_vector))
                ring.append(len(vertices) - 1)
            ring_indices.append(ring)

        segment_count = len(ring_indices) if closed else len(ring_indices) - 1
        for ring_index in range(segment_count):
            next_ring_index = (ring_index + 1) % len(ring_indices)
            for segment_index in range(radial_segments):
                next_segment_index = (segment_index + 1) % radial_segments
                face_counts.append(4)
                face_connects.extend([
                    ring_indices[ring_index][segment_index],
                    ring_indices[ring_index][next_segment_index],
                    ring_indices[next_ring_index][next_segment_index],
                    ring_indices[next_ring_index][segment_index],
                ])

        if cap_ends and not closed:
            start_center = len(vertices)
            vertices.append(path_points[0][:])
            end_center = len(vertices)
            vertices.append(path_points[-1][:])
            first_ring = ring_indices[0]
            last_ring = ring_indices[-1]
            for segment_index in range(radial_segments):
                next_segment_index = (segment_index + 1) % radial_segments
                face_counts.append(3)
                face_connects.extend([start_center, first_ring[segment_index], first_ring[next_segment_index]])
                face_counts.append(3)
                face_connects.extend([end_center, last_ring[next_segment_index], last_ring[segment_index]])

        return {
            "source": source_name,
            "input_points": len(path_points),
            "closed": bool(closed),
            "vertices": len(vertices) - start_vertex_count,
            "faces": len(face_counts) - start_face_count,
        }

    if not name:
        raise ValueError("name is required.")
    tube_radius = _validate_scalar(tube_radius, "tube_radius")
    if tube_radius <= 0.0:
        raise ValueError("tube_radius must be greater than zero.")
    radial_segments = _validate_int(radial_segments, "radial_segments", 3)
    max_points_per_curve = _validate_int(max_points_per_curve, "max_points_per_curve", 0)
    min_segment_length = _validate_scalar(min_segment_length, "min_segment_length")
    if min_segment_length < 0.0:
        raise ValueError("min_segment_length must be greater than or equal to zero.")

    sources = []
    if curve_names is not None:
        if not isinstance(curve_names, list) or not all(isinstance(item, str) for item in curve_names):
            raise ValueError("curve_names must be a list of curve names.")
        for curve_name in curve_names:
            sources.append((curve_name, _curve_points(curve_name)))
    if points is not None:
        if not isinstance(points, list) or len(points) < 2:
            raise ValueError("points must contain at least two [x, y, z] points.")
        sources.append(("points", points))
    if not sources:
        raise ValueError("Provide curve_names and/or points.")

    vertices = []
    face_counts = []
    face_connects = []
    source_summaries = []
    skipped_sources = []
    for source_name, source_points in sources:
        resampled_points = _resample_points(source_points, max_points_per_curve)
        path_points, closed = _clean_path(resampled_points)
        if len(path_points) < 2:
            skipped_sources.append({"source": source_name, "reason": "fewer than two usable points"})
            continue
        source_summaries.append(_append_tube(path_points, closed, source_name))

    if not vertices or not face_counts:
        raise ValueError("No tube geometry could be created from the provided paths.")

    try:
        import maya.api.OpenMaya as om
        mesh_fn = om.MFnMesh()
        mesh_fn.create([om.MPoint(point[0], point[1], point[2]) for point in vertices], face_counts, face_connects)
        mesh_shape = mesh_fn.fullPathName()
        parents = cmds.listRelatives(mesh_shape, parent=True, fullPath=False) or []
        mesh_transform = parents[0] if parents else mesh_shape
        mesh_transform = cmds.rename(mesh_transform, name)
    except Exception as exc:
        raise RuntimeError(f"Unable to create tube mesh: {exc}") from exc

    if smooth:
        cmds.polySoftEdge(mesh_transform, angle=180, constructionHistory=False)

    material = None
    shading_group = None
    if material_color is not None:
        material_color = _validate_vector(material_color, 3, "material_color")
        material = cmds.shadingNode("lambert", asShader=True, name=material_name or f"{name}_mat")
        cmds.setAttr(f"{material}.color", material_color[0], material_color[1], material_color[2], type="double3")
        shading_group = cmds.sets(name=f"{material}SG", empty=True, renderable=True, noSurfaceShader=True)
        cmds.connectAttr(f"{material}.outColor", f"{shading_group}.surfaceShader", force=True)
        cmds.sets(mesh_transform, edit=True, forceElement=shading_group)

    return {
        "success": True,
        "name": mesh_transform,
        "curve_names": curve_names or [],
        "used_source_count": len(source_summaries),
        "skipped_sources": skipped_sources,
        "tube_radius": tube_radius,
        "radial_segments": radial_segments,
        "cap_ends": bool(cap_ends),
        "vertex_count": len(vertices),
        "face_count": len(face_counts),
        "sources": source_summaries,
        "material": material,
        "shading_group": shading_group,
        "bounding_box": cmds.exactWorldBoundingBox(mesh_transform),
    }
