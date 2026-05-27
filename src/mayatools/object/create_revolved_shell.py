from typing import Dict, List, Any


def create_revolved_shell(
    name: str,
    outer_profile: List[List[float]],
    inner_profile: List[List[float]] = None,
    wall_thickness: float = 0.04,
    radial_segments: int = 64,
    height_segments: int = 0,
    profile_interpolation: str = "linear",
    center: List[float] = [0.0, 0.0, 0.0],
    connect_top: bool = True,
    connect_bottom: bool = True,
    smooth: bool = True,
    material_color: List[float] = None,
    material_name: str = None,
) -> Dict[str, Any]:
    """Create a UV-mapped hollow lathed shell from radius/height profiles.

    Outer and inner profile points are [height, radius] pairs around the Y axis.
    If inner_profile is omitted, it is derived from outer_profile by subtracting
    wall_thickness from each radius. Optional height_segments and
    profile_interpolation can resample sparse control profiles into denser
    linear or smooth lathed contours. The result is useful for generic
    thick-wall bottles, cups, shades, vessels, and similar lathed forms.
    """
    import math
    import maya.cmds as cmds

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(v) for v in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(v) for v in values]

    def _validate_profile(profile, arg_name):
        if not isinstance(profile, list) or len(profile) < 2:
            raise ValueError(f"{arg_name} must contain at least two [height, radius] points.")
        clean = []
        previous_height = None
        for point in profile:
            height, radius = _validate_vector(point, 2, f"{arg_name} point")
            if radius < 0:
                raise ValueError(f"{arg_name} radii must be greater than or equal to zero.")
            if previous_height is not None and height <= previous_height:
                raise ValueError(f"{arg_name} heights must be strictly increasing.")
            clean.append([height, radius])
            previous_height = height
        if not any(radius > 0 for _, radius in clean):
            raise ValueError(f"{arg_name} must contain at least one radius greater than zero.")
        return clean

    def _validate_segments(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return value

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

    def _sample_profile(profile, requested_segments, interpolation, heights=None):
        if heights is None:
            if requested_segments == 0:
                return [point[:] for point in profile]
            start_height = profile[0][0]
            end_height = profile[-1][0]
            heights = [
                start_height + (end_height - start_height) * (index / float(requested_segments))
                for index in range(requested_segments + 1)
            ]
        return [[height, _profile_radius_at(profile, height, interpolation)] for height in heights]

    if not name:
        raise ValueError("name is required.")
    radial_segments = _validate_segments(radial_segments, "radial_segments", 3)
    height_segments = _validate_segments(height_segments, "height_segments", 0)
    if not isinstance(profile_interpolation, str):
        raise ValueError("profile_interpolation must be one of linear or smooth.")
    profile_interpolation = profile_interpolation.lower()
    if profile_interpolation not in {"linear", "smooth"}:
        raise ValueError("profile_interpolation must be one of linear or smooth.")
    if not _is_number(wall_thickness) or wall_thickness <= 0:
        raise ValueError("wall_thickness must be a number greater than zero.")

    center = _validate_vector(center, 3, "center")
    clean_outer = _validate_profile(outer_profile, "outer_profile")
    sampled_outer = _sample_profile(clean_outer, height_segments, profile_interpolation)
    sample_heights = [height for height, _ in sampled_outer]
    if inner_profile is None:
        clean_inner = None
        sampled_inner = [[height, max(0.0, radius - float(wall_thickness))] for height, radius in sampled_outer]
    else:
        clean_inner = _validate_profile(inner_profile, "inner_profile")
        if abs(clean_inner[0][0] - clean_outer[0][0]) > 1e-6 or abs(clean_inner[-1][0] - clean_outer[-1][0]) > 1e-6:
            raise ValueError("inner_profile height range must match outer_profile height range.")
        sampled_inner = _sample_profile(clean_inner, height_segments, profile_interpolation, sample_heights)
        for outer, inner in zip(sampled_outer, sampled_inner):
            if inner[1] > outer[1]:
                raise ValueError("inner_profile radii cannot be greater than outer_profile radii.")

    if not any(outer[1] > inner[1] for outer, inner in zip(sampled_outer, sampled_inner)):
        raise ValueError("The shell must have positive radial thickness somewhere.")

    def _create_profile_surface(surface_name, profile):
        surface = cmds.polyPlane(
            name=surface_name,
            width=1.0,
            height=1.0,
            subdivisionsX=radial_segments,
            subdivisionsY=len(profile) - 1,
            axis=[0, 0, 1],
            constructionHistory=False,
        )[0]
        max_profile_index = len(profile) - 1
        vertices = cmds.ls(f"{surface}.vtx[*]", flatten=True) or []
        for vertex in vertices:
            x, y, _ = cmds.xform(vertex, query=True, objectSpace=True, translation=True)
            u = max(0.0, min(1.0, x + 0.5))
            profile_index = int(round((y + 0.5) * max_profile_index))
            profile_index = max(0, min(max_profile_index, profile_index))
            profile_height, radius = profile[profile_index]
            theta = math.tau * u
            world_x = center[0] + radius * math.sin(theta)
            world_y = center[1] + profile_height
            world_z = center[2] + radius * math.cos(theta)
            cmds.xform(vertex, worldSpace=True, translation=[world_x, world_y, world_z])
        if smooth:
            cmds.polySoftEdge(surface, angle=180, constructionHistory=False)
        return surface

    def _create_connector_surface(surface_name, outer_point, inner_point):
        outer_height, outer_radius = outer_point
        inner_height, inner_radius = inner_point
        connector = cmds.polyPlane(
            name=surface_name,
            width=1.0,
            height=1.0,
            subdivisionsX=radial_segments,
            subdivisionsY=1,
            axis=[0, 0, 1],
            constructionHistory=False,
        )[0]
        vertices = cmds.ls(f"{connector}.vtx[*]", flatten=True) or []
        for vertex in vertices:
            x, y, _ = cmds.xform(vertex, query=True, objectSpace=True, translation=True)
            u = max(0.0, min(1.0, x + 0.5))
            t = max(0.0, min(1.0, y + 0.5))
            radius = outer_radius + (inner_radius - outer_radius) * t
            height = outer_height + (inner_height - outer_height) * t
            theta = math.tau * u
            world_x = center[0] + radius * math.sin(theta)
            world_y = center[1] + height
            world_z = center[2] + radius * math.cos(theta)
            cmds.xform(vertex, worldSpace=True, translation=[world_x, world_y, world_z])
        if smooth:
            cmds.polySoftEdge(connector, angle=180, constructionHistory=False)
        return connector

    parts = [
        _create_profile_surface(f"{name}_outer_surface", sampled_outer),
        _create_profile_surface(f"{name}_inner_surface", sampled_inner),
    ]
    if connect_top:
        parts.append(_create_connector_surface(f"{name}_top_rim", sampled_outer[-1], sampled_inner[-1]))
    if connect_bottom:
        parts.append(_create_connector_surface(f"{name}_bottom_rim", sampled_outer[0], sampled_inner[0]))

    shell = parts[0]
    if len(parts) > 1:
        shell = cmds.polyUnite(parts, name=name, constructionHistory=False)[0]
        for part in parts:
            if part != shell and cmds.objExists(part):
                try:
                    cmds.delete(part)
                except Exception:
                    pass
    else:
        shell = cmds.rename(shell, name)

    try:
        cmds.delete(shell, constructionHistory=True)
    except Exception:
        pass
    if smooth:
        cmds.polySoftEdge(shell, angle=180, constructionHistory=False)

    material = None
    shading_group = None
    if material_color is not None:
        material_color = _validate_vector(material_color, 3, "material_color")
        material = cmds.shadingNode("lambert", asShader=True, name=material_name or f"{name}_mat")
        cmds.setAttr(f"{material}.color", material_color[0], material_color[1], material_color[2], type="double3")
        shading_group = cmds.sets(name=f"{material}SG", empty=True, renderable=True, noSurfaceShader=True)
        cmds.connectAttr(f"{material}.outColor", f"{shading_group}.surfaceShader", force=True)
        cmds.sets(shell, edit=True, forceElement=shading_group)

    return {
        "success": True,
        "name": shell,
        "outer_profile": sampled_outer,
        "inner_profile": sampled_inner,
        "input_outer_profile": clean_outer,
        "input_inner_profile": clean_inner,
        "wall_thickness": float(wall_thickness),
        "radial_segments": radial_segments,
        "height_segments": len(sampled_outer) - 1,
        "profile_interpolation": profile_interpolation,
        "center": center,
        "connect_top": connect_top,
        "connect_bottom": connect_bottom,
        "material": material,
        "shading_group": shading_group,
        "uv_range": {"min_u": 0.0, "max_u": 1.0, "min_v": 0.0, "max_v": 1.0},
    }
