from typing import Dict, List, Any


def create_cylindrical_surface_pattern(
    name: str,
    radius: float = 1.0,
    surface_profile: List[List[float]] = None,
    center: List[float] = [0.0, 0.0, 0.0],
    axis: str = "y",
    axis_range: List[float] = [0.0, 1.0],
    angle_range_degrees: List[float] = [-45.0, 45.0],
    axis_count: int = 6,
    angle_count: int = 8,
    patch_axis_radius: float = 0.03,
    patch_angle_radius_degrees: float = 2.0,
    patch_segments: int = 16,
    patch_rings: int = 2,
    surface_offset: float = 0.003,
    center_offset: float = None,
    dome_power: float = 2.0,
    stagger: bool = False,
    stagger_offset_degrees: float = 0.0,
    material_type: str = "phong",
    material_color: List[float] = None,
    material_parameters: Dict[str, Any] = None,
    material_name: str = None,
    smooth: bool = True,
) -> Dict[str, Any]:
    """Create repeated conformal patches on a cylindrical or lathed surface.

    The generated mesh contains elliptical surface patches arranged in an axial
    and angular grid. Patches can sit on a constant radius cylinder or follow a
    supplied [height, radius] surface profile, and their centers can be raised or
    recessed relative to their edges. This is useful for generic grip dots,
    molded dimples, rivets, vents, perforation markers, raised pads, inspection
    points, and other repeated details on bottles, cans, cups, knobs, handles,
    and similar near-axisymmetric models.
    """
    import math
    import maya.cmds as cmds

    try:
        import maya.api.OpenMaya as om
    except Exception as exc:
        raise RuntimeError("maya.api.OpenMaya is required to create patch meshes.") from exc

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

    def _validate_count(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return value

    def _positive_span(start_degrees, end_degrees):
        span = (end_degrees - start_degrees) % 360.0
        return 360.0 if abs(span) < 1e-8 else span

    def _validate_profile(profile):
        if profile is None:
            return None
        if not isinstance(profile, list) or len(profile) < 2:
            raise ValueError("surface_profile must contain at least two [height, radius] points.")
        clean = []
        previous_height = None
        for point in profile:
            height, point_radius = _validate_vector(point, 2, "surface_profile point")
            if point_radius < 0.0:
                raise ValueError("surface_profile radii must be greater than or equal to zero.")
            if previous_height is not None and height <= previous_height:
                raise ValueError("surface_profile heights must be strictly increasing.")
            clean.append([height, point_radius])
            previous_height = height
        return clean

    def _profile_radius_at(profile, height):
        if profile is None:
            return radius
        if height <= profile[0][0]:
            return profile[0][1]
        if height >= profile[-1][0]:
            return profile[-1][1]
        for index in range(len(profile) - 1):
            h0, r0 = profile[index]
            h1, r1 = profile[index + 1]
            if h0 <= height <= h1:
                t = (height - h0) / max(1e-9, h1 - h0)
                return r0 + (r1 - r0) * t
        return profile[-1][1]

    def _patch_offset(ring_fraction):
        if center_offset is None:
            return surface_offset
        weight = max(0.0, 1.0 - ring_fraction) ** dome_power
        return surface_offset + (center_offset - surface_offset) * weight

    def _surface_point(axis_value, angle_degrees, offset):
        local_radius = max(0.0, _profile_radius_at(clean_profile, axis_value) + offset)
        theta = math.radians(angle_degrees)
        point = [center[0], center[1], center[2]]
        point[axis_index] = center[axis_index] + axis_value
        point[radial_a] = center[radial_a] + local_radius * math.sin(theta)
        point[radial_b] = center[radial_b] + local_radius * math.cos(theta)
        return point

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
    radius = _validate_scalar(radius, "radius")
    if radius <= 0.0:
        raise ValueError("radius must be greater than zero.")
    center = _validate_vector(center, 3, "center")
    axis_range = _validate_vector(axis_range, 2, "axis_range")
    if axis_range[0] > axis_range[1]:
        axis_range = [axis_range[1], axis_range[0]]
    axis_span = axis_range[1] - axis_range[0]
    if axis_span <= 0.0:
        raise ValueError("axis_range must cover a positive span.")
    angle_range_degrees = _validate_vector(angle_range_degrees, 2, "angle_range_degrees")
    angle_span = _positive_span(angle_range_degrees[0], angle_range_degrees[1])
    axis_count = _validate_count(axis_count, "axis_count", 1)
    angle_count = _validate_count(angle_count, "angle_count", 1)
    patch_segments = _validate_count(patch_segments, "patch_segments", 3)
    patch_rings = _validate_count(patch_rings, "patch_rings", 1)
    patch_axis_radius = _validate_scalar(patch_axis_radius, "patch_axis_radius")
    patch_angle_radius_degrees = _validate_scalar(patch_angle_radius_degrees, "patch_angle_radius_degrees")
    surface_offset = _validate_scalar(surface_offset, "surface_offset")
    if center_offset is not None:
        center_offset = _validate_scalar(center_offset, "center_offset")
    dome_power = _validate_scalar(dome_power, "dome_power")
    stagger_offset_degrees = _validate_scalar(stagger_offset_degrees, "stagger_offset_degrees")
    if patch_axis_radius <= 0.0:
        raise ValueError("patch_axis_radius must be greater than zero.")
    if patch_angle_radius_degrees <= 0.0:
        raise ValueError("patch_angle_radius_degrees must be greater than zero.")
    if dome_power <= 0.0:
        raise ValueError("dome_power must be greater than zero.")

    clean_profile = _validate_profile(surface_profile)
    if clean_profile is not None:
        if axis_range[0] < clean_profile[0][0] or axis_range[1] > clean_profile[-1][0]:
            raise ValueError("axis_range must be within the supplied surface_profile height range.")

    axis = str(axis).lower().strip()
    axes = {
        "x": (0, 1, 2),
        "y": (1, 0, 2),
        "z": (2, 0, 1),
    }
    if axis not in axes:
        raise ValueError("axis must be one of x, y, or z.")
    axis_index, radial_a, radial_b = axes[axis]

    angle_spacing = angle_span / float(angle_count)
    if stagger and abs(stagger_offset_degrees) < 1e-8:
        stagger_offset_degrees = angle_spacing * 0.5

    feature_centers = []
    for row_index in range(axis_count):
        axis_t = (row_index + 0.5) / float(axis_count)
        axis_value = axis_range[0] + axis_span * axis_t
        row_offset = stagger_offset_degrees if stagger and row_index % 2 == 1 else 0.0
        for column_index in range(angle_count):
            angle_t = (column_index + 0.5) / float(angle_count)
            angle_value = angle_range_degrees[0] + angle_span * angle_t + row_offset
            feature_centers.append([axis_value, angle_value])

    vertices = []
    face_counts = []
    face_connects = []
    patch_summaries = []
    for feature_index, (axis_center, angle_center) in enumerate(feature_centers):
        center_index = len(vertices)
        vertices.append(_surface_point(axis_center, angle_center, _patch_offset(0.0)))
        rings = []
        for ring_index in range(1, patch_rings + 1):
            ring_fraction = ring_index / float(patch_rings)
            ring = []
            for segment_index in range(patch_segments):
                phi = math.tau * segment_index / float(patch_segments)
                point_axis = axis_center + math.cos(phi) * patch_axis_radius * ring_fraction
                point_angle = angle_center + math.sin(phi) * patch_angle_radius_degrees * ring_fraction
                ring.append(len(vertices))
                vertices.append(_surface_point(point_axis, point_angle, _patch_offset(ring_fraction)))
            rings.append(ring)

        first_ring = rings[0]
        for segment_index in range(patch_segments):
            next_segment = (segment_index + 1) % patch_segments
            face_counts.append(3)
            face_connects.extend([center_index, first_ring[next_segment], first_ring[segment_index]])
        for ring_index in range(1, len(rings)):
            inner = rings[ring_index - 1]
            outer = rings[ring_index]
            for segment_index in range(patch_segments):
                next_segment = (segment_index + 1) % patch_segments
                face_counts.append(4)
                face_connects.extend([
                    inner[segment_index],
                    inner[next_segment],
                    outer[next_segment],
                    outer[segment_index],
                ])
        patch_summaries.append({
            "index": feature_index,
            "axis_center": axis_center,
            "angle_center_degrees": angle_center,
        })

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
        raise RuntimeError(f"Unable to create cylindrical surface pattern mesh: {exc}") from exc

    if smooth:
        cmds.polySoftEdge(mesh_transform, angle=180, constructionHistory=False)

    material = None
    shading_group = None
    if material_color is not None:
        material, shading_group = _make_material(mesh_transform)

    return {
        "success": True,
        "name": mesh_transform,
        "feature_count": len(feature_centers),
        "axis": axis,
        "center": center,
        "radius": radius,
        "surface_profile_point_count": len(clean_profile) if clean_profile is not None else 0,
        "axis_range": axis_range,
        "angle_range_degrees": angle_range_degrees,
        "angle_span_degrees": angle_span,
        "axis_count": axis_count,
        "angle_count": angle_count,
        "patch_axis_radius": patch_axis_radius,
        "patch_angle_radius_degrees": patch_angle_radius_degrees,
        "patch_segments": patch_segments,
        "patch_rings": patch_rings,
        "surface_offset": surface_offset,
        "center_offset": center_offset,
        "dome_power": dome_power,
        "stagger": bool(stagger),
        "stagger_offset_degrees": stagger_offset_degrees,
        "vertex_count": len(vertices),
        "face_count": len(face_counts),
        "material": material,
        "shading_group": shading_group,
        "feature_centers_sample": patch_summaries[:50],
        "bounding_box": cmds.exactWorldBoundingBox(mesh_transform),
    }
