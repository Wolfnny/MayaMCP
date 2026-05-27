from typing import Dict, List, Any


def create_revolved_liquid_volume(
    name: str,
    container_profile: List[List[float]],
    fill_height: float,
    bottom_height: float = None,
    radius_offset: float = -0.02,
    radial_segments: int = 96,
    height_segments: int = 0,
    profile_interpolation: str = "linear",
    center: List[float] = [0.0, 0.0, 0.0],
    cap_top: bool = True,
    cap_bottom: bool = True,
    cap_thickness: float = 0.001,
    smooth: bool = True,
    material_color: List[float] = None,
    material_name: str = None,
) -> Dict[str, Any]:
    """Create an axisymmetric liquid volume inside a lathed container profile.

    The container profile is a list of [height, radius] pairs around the Y axis.
    The generated liquid surface can be inset with radius_offset to avoid
    overlapping a container wall, and it can include flat top and bottom caps.
    This is useful for generic bottles, glasses, cups, jars, tanks, and other
    transparent or cutaway vessels that need a visible fill volume.
    """
    import math
    import maya.cmds as cmds

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(v) for v in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(v) for v in values]

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

    def _validate_segments(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return value

    def _validate_profile(profile):
        if not isinstance(profile, list) or len(profile) < 2:
            raise ValueError("container_profile must contain at least two [height, radius] points.")
        clean = []
        previous_height = None
        for point in profile:
            height, radius = _validate_vector(point, 2, "container_profile point")
            if radius < 0:
                raise ValueError("container_profile radii must be greater than or equal to zero.")
            if previous_height is not None and height <= previous_height:
                raise ValueError("container_profile heights must be strictly increasing.")
            clean.append([height, radius])
            previous_height = height
        if not any(radius > 0 for _, radius in clean):
            raise ValueError("container_profile must contain at least one positive radius.")
        return clean

    def _profile_radius_at(profile, height, interpolation):
        if height <= profile[0][0]:
            return profile[0][1]
        if height >= profile[-1][0]:
            return profile[-1][1]

        segment_index = 0
        for index in range(len(profile) - 1):
            if profile[index][0] <= height <= profile[index + 1][0]:
                segment_index = index
                break

        h0, r0 = profile[segment_index]
        h1, r1 = profile[segment_index + 1]
        t = (height - h0) / max(1e-9, h1 - h0)
        if interpolation == "linear":
            return r0 + (r1 - r0) * t

        def _slope(point_index):
            if point_index <= 0:
                ha, ra = profile[0]
                hb, rb = profile[1]
            elif point_index >= len(profile) - 1:
                ha, ra = profile[-2]
                hb, rb = profile[-1]
            else:
                ha, ra = profile[point_index - 1]
                hb, rb = profile[point_index + 1]
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

    def _liquid_radius_at(profile, height, interpolation):
        return max(0.0, _profile_radius_at(profile, height, interpolation) + radius_offset)

    def _sample_profile(profile, start_height, end_height, requested_segments, interpolation):
        if requested_segments > 0:
            return [
                [
                    start_height + (end_height - start_height) * (index / float(requested_segments)),
                    _liquid_radius_at(profile, start_height + (end_height - start_height) * (index / float(requested_segments)), interpolation),
                ]
                for index in range(requested_segments + 1)
            ]

        sampled = [[start_height, _liquid_radius_at(profile, start_height, interpolation)]]
        for height, _ in profile:
            if start_height < height < end_height:
                sampled.append([height, _liquid_radius_at(profile, height, interpolation)])
        sampled.append([end_height, _liquid_radius_at(profile, end_height, interpolation)])
        return sampled

    if not name:
        raise ValueError("name is required.")
    clean_profile = _validate_profile(container_profile)
    fill_height = _validate_scalar(fill_height, "fill_height")
    if bottom_height is None:
        bottom_height = clean_profile[0][0]
    bottom_height = _validate_scalar(bottom_height, "bottom_height")
    radius_offset = _validate_scalar(radius_offset, "radius_offset")
    radial_segments = _validate_segments(radial_segments, "radial_segments", 3)
    height_segments = _validate_segments(height_segments, "height_segments", 0)
    cap_thickness = _validate_scalar(cap_thickness, "cap_thickness")
    if cap_thickness <= 0.0:
        raise ValueError("cap_thickness must be greater than zero.")

    if not isinstance(profile_interpolation, str):
        raise ValueError("profile_interpolation must be one of linear or smooth.")
    profile_interpolation = profile_interpolation.lower()
    if profile_interpolation not in {"linear", "smooth"}:
        raise ValueError("profile_interpolation must be one of linear or smooth.")
    center = _validate_vector(center, 3, "center")

    profile_min = clean_profile[0][0]
    profile_max = clean_profile[-1][0]
    if bottom_height < profile_min or bottom_height > profile_max:
        raise ValueError("bottom_height must be within the container_profile height range.")
    if fill_height < profile_min or fill_height > profile_max:
        raise ValueError("fill_height must be within the container_profile height range.")
    if fill_height <= bottom_height:
        raise ValueError("fill_height must be greater than bottom_height.")

    sampled_profile = _sample_profile(clean_profile, bottom_height, fill_height, height_segments, profile_interpolation)
    if not any(radius > 0.0 for _, radius in sampled_profile):
        raise ValueError("Liquid radius is zero throughout the requested fill range.")

    side = cmds.polyPlane(
        name=f"{name}_side",
        width=1.0,
        height=1.0,
        subdivisionsX=radial_segments,
        subdivisionsY=len(sampled_profile) - 1,
        axis=[0, 0, 1],
        constructionHistory=False,
    )[0]

    max_profile_index = len(sampled_profile) - 1
    vertices = cmds.ls(f"{side}.vtx[*]", flatten=True) or []
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

    parts = [side]
    caps = []
    if cap_top:
        top_radius = sampled_profile[-1][1]
        if top_radius > 0.0:
            top = cmds.polyCylinder(
                name=f"{name}_top_surface",
                radius=top_radius,
                height=cap_thickness,
                subdivisionsAxis=radial_segments,
                subdivisionsHeight=1,
                constructionHistory=False,
            )[0]
            cmds.setAttr(f"{top}.translate", center[0], center[1] + fill_height, center[2], type="double3")
            parts.append(top)
            caps.append(top)
    if cap_bottom:
        bottom_radius = sampled_profile[0][1]
        if bottom_radius > 0.0:
            bottom = cmds.polyCylinder(
                name=f"{name}_bottom_surface",
                radius=bottom_radius,
                height=cap_thickness,
                subdivisionsAxis=radial_segments,
                subdivisionsHeight=1,
                constructionHistory=False,
            )[0]
            cmds.setAttr(f"{bottom}.translate", center[0], center[1] + bottom_height, center[2], type="double3")
            parts.append(bottom)
            caps.append(bottom)

    if smooth:
        for part in parts:
            cmds.polySoftEdge(part, angle=180, constructionHistory=False)

    source_part_count = len(parts)
    cap_count = len(caps)
    liquid = side
    if len(parts) > 1:
        liquid = cmds.polyUnite(parts, name=name, constructionHistory=False)[0]
        for part in parts:
            if part != liquid and cmds.objExists(part):
                try:
                    cmds.delete(part)
                except Exception:
                    pass
        try:
            cmds.delete(liquid, constructionHistory=True)
        except Exception:
            pass
        if smooth:
            cmds.polySoftEdge(liquid, angle=180, constructionHistory=False)
    else:
        liquid = cmds.rename(side, name)

    material = None
    shading_group = None
    if material_color is not None:
        material_color = _validate_vector(material_color, 3, "material_color")
        material = cmds.shadingNode("lambert", asShader=True, name=material_name or f"{name}_mat")
        cmds.setAttr(f"{material}.color", material_color[0], material_color[1], material_color[2], type="double3")
        shading_group = cmds.sets(name=f"{material}SG", empty=True, renderable=True, noSurfaceShader=True)
        cmds.connectAttr(f"{material}.outColor", f"{shading_group}.surfaceShader", force=True)
        cmds.sets(liquid, edit=True, forceElement=shading_group)

    return {
        "success": True,
        "name": liquid,
        "created": [liquid],
        "source_part_count": source_part_count,
        "cap_count": cap_count,
        "container_profile": clean_profile,
        "liquid_profile": sampled_profile,
        "fill_height": fill_height,
        "bottom_height": bottom_height,
        "radius_offset": radius_offset,
        "radial_segments": radial_segments,
        "height_segments": len(sampled_profile) - 1,
        "profile_interpolation": profile_interpolation,
        "cap_top": cap_top,
        "cap_bottom": cap_bottom,
        "cap_thickness": cap_thickness,
        "material": material,
        "shading_group": shading_group,
        "uv_range": {"min_u": 0.0, "max_u": 1.0, "min_v": 0.0, "max_v": 1.0},
    }
