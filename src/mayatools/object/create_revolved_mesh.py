from typing import Dict, List, Any


def create_revolved_mesh(
    name: str,
    profile: List[List[float]],
    radial_segments: int = 64,
    height_segments: int = 0,
    profile_interpolation: str = "linear",
    center: List[float] = [0.0, 0.0, 0.0],
    smooth: bool = True,
    cap_ends: bool = False,
    material_color: List[float] = None,
    material_name: str = None,
) -> Dict[str, Any]:
    """Create a UV-mapped polygon mesh by revolving a radius/height profile.

    Profile points are [height, radius] pairs in bottom-to-top order around the
    Y axis. Optional height_segments and profile_interpolation can resample a
    sparse control profile into a denser linear or smooth lathed contour. The
    generated side surface preserves a clean 0..1 UV layout, which makes it
    useful for bottles, cups, vases, lampshades, and similar forms that need
    texture placement.
    """
    import math
    import maya.cmds as cmds

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector(values, length, name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(v) for v in values):
            raise ValueError(f"{name} must be a list of {length} numeric values.")
        return [float(v) for v in values]

    def _validate_segments(value, name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{name} must be an integer greater than or equal to {minimum}.")
        return value

    def _profile_radius_at(clean_profile, height, interpolation):
        if height <= clean_profile[0][0]:
            return clean_profile[0][1]
        if height >= clean_profile[-1][0]:
            return clean_profile[-1][1]

        segment_index = 0
        for index in range(len(clean_profile) - 1):
            if clean_profile[index][0] <= height <= clean_profile[index + 1][0]:
                segment_index = index
                break

        h0, r0 = clean_profile[segment_index]
        h1, r1 = clean_profile[segment_index + 1]
        t = (height - h0) / max(1e-9, h1 - h0)
        if interpolation == "linear":
            return r0 + (r1 - r0) * t

        def _slope(point_index):
            if point_index <= 0:
                ha, ra = clean_profile[0]
                hb, rb = clean_profile[1]
            elif point_index >= len(clean_profile) - 1:
                ha, ra = clean_profile[-2]
                hb, rb = clean_profile[-1]
            else:
                ha, ra = clean_profile[point_index - 1]
                hb, rb = clean_profile[point_index + 1]
            return (rb - ra) / max(1e-9, hb - ha)

        m0 = _slope(segment_index)
        m1 = _slope(segment_index + 1)
        t2 = t * t
        t3 = t2 * t
        span = h1 - h0
        radius = (
            (2.0 * t3 - 3.0 * t2 + 1.0) * r0
            + (t3 - 2.0 * t2 + t) * span * m0
            + (-2.0 * t3 + 3.0 * t2) * r1
            + (t3 - t2) * span * m1
        )
        lower = min(r0, r1)
        upper = max(r0, r1)
        return max(0.0, min(upper, max(lower, radius)))

    def _sample_profile(clean_profile, requested_segments, interpolation):
        if requested_segments == 0:
            return [point[:] for point in clean_profile]
        start_height = clean_profile[0][0]
        end_height = clean_profile[-1][0]
        sampled = []
        for index in range(requested_segments + 1):
            t = index / float(requested_segments)
            height = start_height + (end_height - start_height) * t
            sampled.append([height, _profile_radius_at(clean_profile, height, interpolation)])
        return sampled

    if not name:
        raise ValueError("name is required.")
    if not isinstance(profile, list) or len(profile) < 2:
        raise ValueError("profile must contain at least two [height, radius] points.")
    radial_segments = _validate_segments(radial_segments, "radial_segments", 3)
    height_segments = _validate_segments(height_segments, "height_segments", 0)
    if not isinstance(profile_interpolation, str):
        raise ValueError("profile_interpolation must be one of linear or smooth.")
    profile_interpolation = profile_interpolation.lower()
    if profile_interpolation not in {"linear", "smooth"}:
        raise ValueError("profile_interpolation must be one of linear or smooth.")

    center = _validate_vector(center, 3, "center")

    clean_profile = []
    previous_height = None
    for point in profile:
        height, radius = _validate_vector(point, 2, "profile point")
        if radius < 0:
            raise ValueError("profile radii must be greater than or equal to zero.")
        if previous_height is not None and height <= previous_height:
            raise ValueError("profile heights must be strictly increasing from bottom to top.")
        clean_profile.append([height, radius])
        previous_height = height

    if not any(radius > 0 for _, radius in clean_profile):
        raise ValueError("profile must contain at least one radius greater than zero.")
    sampled_profile = _sample_profile(clean_profile, height_segments, profile_interpolation)

    mesh = cmds.polyPlane(
        name=name,
        width=1.0,
        height=1.0,
        subdivisionsX=radial_segments,
        subdivisionsY=len(sampled_profile) - 1,
        axis=[0, 0, 1],
        constructionHistory=False,
    )[0]

    max_profile_index = len(sampled_profile) - 1
    vertices = cmds.ls(f"{mesh}.vtx[*]", flatten=True) or []
    for vertex in vertices:
        x, y, _ = cmds.xform(vertex, query=True, objectSpace=True, translation=True)
        u = max(0.0, min(1.0, x + 0.5))
        profile_index = int(round((y + 0.5) * max_profile_index))
        profile_index = max(0, min(max_profile_index, profile_index))
        profile_height, radius = sampled_profile[profile_index]
        theta = math.tau * u
        world_x = center[0] + radius * math.sin(theta)
        world_y = center[1] + profile_height
        world_z = center[2] + radius * math.cos(theta)
        cmds.xform(vertex, worldSpace=True, translation=[world_x, world_y, world_z])

    if smooth:
        cmds.polySoftEdge(mesh, angle=180, constructionHistory=False)

    created = [mesh]
    caps = []
    if cap_ends:
        for cap_name, profile_index in [("bottom", 0), ("top", -1)]:
            height, radius = sampled_profile[profile_index]
            if radius <= 0:
                continue
            cap = cmds.polyCylinder(
                name=f"{name}_{cap_name}_cap",
                radius=radius,
                height=0.001,
                subdivisionsAxis=radial_segments,
                subdivisionsHeight=1,
                constructionHistory=False,
            )[0]
            cmds.setAttr(f"{cap}.translate", center[0], center[1] + height, center[2], type="double3")
            created.append(cap)
            caps.append(cap)
            if smooth:
                cmds.polySoftEdge(cap, angle=180, constructionHistory=False)

    material = None
    shading_group = None
    if material_color is not None:
        material_color = _validate_vector(material_color, 3, "material_color")
        material = cmds.shadingNode("lambert", asShader=True, name=material_name or f"{name}_mat")
        cmds.setAttr(f"{material}.color", material_color[0], material_color[1], material_color[2], type="double3")
        shading_group = cmds.sets(name=f"{material}SG", empty=True, renderable=True, noSurfaceShader=True)
        cmds.connectAttr(f"{material}.outColor", f"{shading_group}.surfaceShader", force=True)
        cmds.sets(created, edit=True, forceElement=shading_group)

    return {
        "success": True,
        "name": mesh,
        "created": created,
        "caps": caps,
        "profile": sampled_profile,
        "input_profile": clean_profile,
        "radial_segments": radial_segments,
        "height_segments": len(sampled_profile) - 1,
        "profile_interpolation": profile_interpolation,
        "center": center,
        "material": material,
        "shading_group": shading_group,
        "uv_range": {"min_u": 0.0, "max_u": 1.0, "min_v": 0.0, "max_v": 1.0},
    }
