from typing import Dict, List, Any


def create_cylindrical_tube_paths(
    name: str,
    paths: List[List[List[float]]],
    radius: float = 1.0,
    surface_profile: List[List[float]] = None,
    center: List[float] = [0.0, 0.0, 0.0],
    axis: str = "y",
    surface_offset: float = 0.02,
    tube_radius: float = 0.01,
    radial_segments: int = 8,
    cap_ends: bool = True,
    closed: bool = False,
    min_segment_length: float = 0.0001,
    material_type: str = "phong",
    material_color: List[float] = None,
    material_parameters: Dict[str, Any] = None,
    material_name: str = None,
    smooth: bool = True,
) -> Dict[str, Any]:
    """Create tube geometry from cylindrical surface path coordinates.

    Each path point is [axis_value, angle_degrees] or
    [axis_value, angle_degrees, point_surface_offset]. The generated polygon
    tubes follow either a constant radius cylinder or a supplied
    [axis_value, radius] profile, making the tool useful for generic molded
    scripts, raised seams, engraved guide lines, grip outlines, weld beads,
    routed wires, and other surface-following line details on bottles, cans,
    handles, knobs, and similar near-axisymmetric forms.
    """
    import math
    import maya.cmds as cmds

    try:
        import maya.api.OpenMaya as om
    except Exception as exc:
        raise RuntimeError("maya.api.OpenMaya is required to create tube meshes.") from exc

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(value) for value in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(value) for value in values]

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return int(value)

    def _validate_profile(profile):
        if profile is None:
            return None
        if not isinstance(profile, list) or len(profile) < 2:
            raise ValueError("surface_profile must contain at least two [axis_value, radius] points.")
        clean = []
        previous_axis_value = None
        for point in profile:
            axis_value, point_radius = _validate_vector(point, 2, "surface_profile point")
            if point_radius < 0.0:
                raise ValueError("surface_profile radii must be greater than or equal to zero.")
            if previous_axis_value is not None and axis_value <= previous_axis_value:
                raise ValueError("surface_profile axis values must be strictly increasing.")
            clean.append([axis_value, point_radius])
            previous_axis_value = axis_value
        return clean

    def _profile_radius_at(profile, axis_value):
        if profile is None:
            return radius
        if axis_value <= profile[0][0]:
            return profile[0][1]
        if axis_value >= profile[-1][0]:
            return profile[-1][1]
        for index in range(len(profile) - 1):
            value0, radius0 = profile[index]
            value1, radius1 = profile[index + 1]
            if value0 <= axis_value <= value1:
                t = (axis_value - value0) / max(1e-9, value1 - value0)
                return radius0 + (radius1 - radius0) * t
        return profile[-1][1]

    def _surface_point(axis_value, angle_degrees, point_offset):
        local_radius = max(0.0, _profile_radius_at(clean_profile, axis_value) + surface_offset + point_offset)
        theta = math.radians(angle_degrees)
        point = [center[0], center[1], center[2]]
        point[axis_index] = center[axis_index] + axis_value
        point[radial_a] = center[radial_a] + local_radius * math.sin(theta)
        point[radial_b] = center[radial_b] + local_radius * math.cos(theta)
        return point

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

    def _initial_frame(tangent):
        reference = [0.0, 1.0, 0.0]
        if abs(_dot(reference, tangent)) > 0.9:
            reference = [1.0, 0.0, 0.0]
        normal = _normalize(_cross(reference, tangent))
        if normal is None:
            normal = [1.0, 0.0, 0.0]
        binormal = _normalize(_cross(tangent, normal)) or [0.0, 0.0, 1.0]
        return normal, binormal

    def _path_tangent(path_points, index, is_closed):
        count = len(path_points)
        if is_closed:
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

    def _clean_surface_path(surface_path):
        if not isinstance(surface_path, list) or len(surface_path) < 2:
            raise ValueError("Each path must contain at least two points.")
        clean = []
        for point in surface_path:
            if not isinstance(point, list) or len(point) not in {2, 3}:
                raise ValueError("Path points must be [axis_value, angle_degrees] or [axis_value, angle_degrees, offset].")
            axis_value = _validate_scalar(point[0], "path point axis_value")
            angle_degrees = _validate_scalar(point[1], "path point angle_degrees")
            point_offset = _validate_scalar(point[2], "path point offset") if len(point) == 3 else 0.0
            world_point = _surface_point(axis_value, angle_degrees, point_offset)
            if clean and _distance(clean[-1], world_point) < min_segment_length:
                continue
            clean.append(world_point)
        path_closed = bool(closed)
        if len(clean) >= 3 and _distance(clean[0], clean[-1]) < min_segment_length:
            clean.pop()
            path_closed = True
        return clean, path_closed

    def _append_tube(path_points, path_closed, path_index):
        start_vertex_count = len(vertices)
        start_face_count = len(face_counts)
        ring_indices = []
        previous_normal = None
        for point_index, point in enumerate(path_points):
            tangent = _path_tangent(path_points, point_index, path_closed)
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

        segment_count = len(ring_indices) if path_closed else len(ring_indices) - 1
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

        if cap_ends and not path_closed:
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
            "path_index": path_index,
            "input_points": len(path_points),
            "closed": bool(path_closed),
            "vertices": len(vertices) - start_vertex_count,
            "faces": len(face_counts) - start_face_count,
        }

    def _make_material(mesh_transform):
        if material_color is None:
            return None, None
        shader_type = str(material_type or "phong").lower().strip()
        if shader_type not in {"lambert", "phong", "blinn"}:
            raise ValueError("material_type must be one of lambert, phong, or blinn.")
        color = _validate_vector(material_color, 3, "material_color")
        shader = cmds.shadingNode(shader_type, asShader=True, name=material_name or f"{name}_mat")
        cmds.setAttr(f"{shader}.color", color[0], color[1], color[2], type="double3")
        for attr, value in (material_parameters or {}).items():
            if not cmds.attributeQuery(attr, node=shader, exists=True):
                continue
            if isinstance(value, list) and len(value) == 3 and all(_is_number(item) for item in value):
                attr_type = cmds.getAttr(f"{shader}.{attr}", type=True)
                cmds.setAttr(f"{shader}.{attr}", float(value[0]), float(value[1]), float(value[2]), type=attr_type)
            else:
                cmds.setAttr(f"{shader}.{attr}", value)
        shading_group = cmds.sets(name=f"{shader}SG", empty=True, renderable=True, noSurfaceShader=True)
        cmds.connectAttr(f"{shader}.outColor", f"{shading_group}.surfaceShader", force=True)
        cmds.sets(mesh_transform, edit=True, forceElement=shading_group)
        return shader, shading_group

    if not name:
        raise ValueError("name is required.")
    if not isinstance(paths, list) or not paths:
        raise ValueError("paths must be a non-empty list of paths.")
    radius = _validate_scalar(radius, "radius")
    if radius <= 0.0:
        raise ValueError("radius must be greater than zero.")
    center = _validate_vector(center, 3, "center")
    surface_offset = _validate_scalar(surface_offset, "surface_offset")
    tube_radius = _validate_scalar(tube_radius, "tube_radius")
    if tube_radius <= 0.0:
        raise ValueError("tube_radius must be greater than zero.")
    radial_segments = _validate_int(radial_segments, "radial_segments", 3)
    min_segment_length = _validate_scalar(min_segment_length, "min_segment_length")
    if min_segment_length < 0.0:
        raise ValueError("min_segment_length must be greater than or equal to zero.")

    clean_profile = _validate_profile(surface_profile)
    axis = str(axis).lower().strip()
    axes = {
        "x": (0, 1, 2),
        "y": (1, 0, 2),
        "z": (2, 0, 1),
    }
    if axis not in axes:
        raise ValueError("axis must be one of x, y, or z.")
    axis_index, radial_a, radial_b = axes[axis]

    vertices = []
    face_counts = []
    face_connects = []
    path_summaries = []
    skipped_paths = []
    for path_index, surface_path in enumerate(paths):
        path_points, path_closed = _clean_surface_path(surface_path)
        if len(path_points) < 2 or (path_closed and len(path_points) < 3):
            skipped_paths.append({"path_index": path_index, "reason": "fewer than two usable points"})
            continue
        path_summaries.append(_append_tube(path_points, path_closed, path_index))

    if not vertices or not face_counts:
        raise ValueError("No tube geometry could be created from the provided paths.")

    try:
        mesh_fn = om.MFnMesh()
        mesh_fn.create(
            [om.MPoint(point[0], point[1], point[2]) for point in vertices],
            face_counts,
            face_connects,
        )
        mesh_shape = mesh_fn.fullPathName()
        parents = cmds.listRelatives(mesh_shape, parent=True, fullPath=False) or []
        mesh_transform = parents[0] if parents else mesh_shape
        mesh_transform = cmds.rename(mesh_transform, name)
    except Exception as exc:
        raise RuntimeError(f"Unable to create cylindrical tube path mesh: {exc}") from exc

    if smooth:
        cmds.polySoftEdge(mesh_transform, angle=180, constructionHistory=False)

    material = None
    shading_group = None
    if material_color is not None:
        material, shading_group = _make_material(mesh_transform)

    return {
        "success": True,
        "name": mesh_transform,
        "path_count": len(path_summaries),
        "skipped_paths": skipped_paths,
        "tube_radius": tube_radius,
        "radial_segments": radial_segments,
        "cap_ends": bool(cap_ends),
        "closed": bool(closed),
        "axis": axis,
        "center": center,
        "radius": radius,
        "surface_profile_point_count": len(clean_profile) if clean_profile is not None else 0,
        "surface_offset": surface_offset,
        "vertex_count": len(vertices),
        "face_count": len(face_counts),
        "paths": path_summaries,
        "material": material,
        "shading_group": shading_group,
        "bounding_box": cmds.exactWorldBoundingBox(mesh_transform),
    }
