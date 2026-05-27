from typing import Dict, List, Any


def create_revolved_mesh(
    name: str,
    profile: List[List[float]],
    radial_segments: int = 64,
    center: List[float] = [0.0, 0.0, 0.0],
    smooth: bool = True,
    cap_ends: bool = False,
    material_color: List[float] = None,
    material_name: str = None,
) -> Dict[str, Any]:
    """Create a UV-mapped polygon mesh by revolving a radius/height profile.

    Profile points are [height, radius] pairs in bottom-to-top order around the
    Y axis. The generated side surface preserves a clean 0..1 UV layout, which
    makes it useful for bottles, cups, vases, lampshades, and similar lathed
    forms that need texture placement.
    """
    import math
    import maya.cmds as cmds

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector(values, length, name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(v) for v in values):
            raise ValueError(f"{name} must be a list of {length} numeric values.")
        return [float(v) for v in values]

    if not name:
        raise ValueError("name is required.")
    if not isinstance(profile, list) or len(profile) < 2:
        raise ValueError("profile must contain at least two [height, radius] points.")
    if radial_segments < 3:
        raise ValueError("radial_segments must be at least 3.")

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

    mesh = cmds.polyPlane(
        name=name,
        width=1.0,
        height=1.0,
        subdivisionsX=radial_segments,
        subdivisionsY=len(clean_profile) - 1,
        axis=[0, 0, 1],
        constructionHistory=False,
    )[0]

    max_profile_index = len(clean_profile) - 1
    vertices = cmds.ls(f"{mesh}.vtx[*]", flatten=True) or []
    for vertex in vertices:
        x, y, _ = cmds.xform(vertex, query=True, objectSpace=True, translation=True)
        u = max(0.0, min(1.0, x + 0.5))
        profile_index = int(round((y + 0.5) * max_profile_index))
        profile_index = max(0, min(max_profile_index, profile_index))
        profile_height, radius = clean_profile[profile_index]
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
            height, radius = clean_profile[profile_index]
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
        "profile": clean_profile,
        "radial_segments": radial_segments,
        "center": center,
        "material": material,
        "shading_group": shading_group,
        "uv_range": {"min_u": 0.0, "max_u": 1.0, "min_v": 0.0, "max_v": 1.0},
    }
