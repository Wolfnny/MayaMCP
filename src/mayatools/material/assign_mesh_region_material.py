from typing import Dict, List, Any


def assign_mesh_region_material(
    object_name: str,
    material_name: str = None,
    shading_group_name: str = None,
    material_type: str = "phong",
    material_color: List[float] = None,
    material_parameters: Dict[str, Any] = None,
    center: List[float] = [0.0, 0.0, 0.0],
    axis: str = "y",
    axis_range: List[float] = None,
    angle_range_degrees: List[float] = None,
    radial_range: List[float] = None,
    include_partial_faces: bool = False,
    invert: bool = False,
    preview_only: bool = False,
) -> Dict[str, Any]:
    """Assign a material to mesh faces selected by cylindrical/axial bounds.

    Faces are selected by testing their center, or optionally any vertex, against
    an axis range, angular range around a center, and/or radial range. This is
    generic infrastructure for local material overrides on lathed or cylindrical
    assets: bottle shoulders, lower bands, caps, panel zones, grip areas, trim,
    inserts, or any mesh region that should be material-tuned without replacing
    the whole object or relying on image masks.
    """
    import math
    import maya.cmds as cmds

    try:
        import maya.api.OpenMaya as om
    except Exception as exc:
        raise RuntimeError("maya.api.OpenMaya is required to inspect mesh faces.") from exc

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(value) for value in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(value) for value in values]

    def _validate_range(values, arg_name):
        clean = _validate_vector(values, 2, arg_name)
        if clean[0] > clean[1]:
            clean = [clean[1], clean[0]]
        return clean

    def _positive_span(start_degrees, end_degrees):
        span = (end_degrees - start_degrees) % 360.0
        return 360.0 if abs(span) < 1e-8 else span

    def _angle_in_range(angle, start_degrees, span_degrees):
        delta = (angle - start_degrees) % 360.0
        return delta <= span_degrees + 1e-8

    def _point_metrics(point):
        values = [point.x, point.y, point.z]
        axis_value = values[axis_index] - center[axis_index]
        delta_a = values[radial_a] - center[radial_a]
        delta_b = values[radial_b] - center[radial_b]
        radius = math.sqrt(delta_a * delta_a + delta_b * delta_b)
        angle = math.degrees(math.atan2(delta_a, delta_b))
        return axis_value, radius, angle

    def _matches(point):
        axis_value, radius, angle = _point_metrics(point)
        if clean_axis_range is not None and not (clean_axis_range[0] <= axis_value <= clean_axis_range[1]):
            return False
        if clean_radial_range is not None and not (clean_radial_range[0] <= radius <= clean_radial_range[1]):
            return False
        if clean_angle_range is not None and not _angle_in_range(angle, clean_angle_range[0], angle_span):
            return False
        return True

    def _make_material():
        shader_type = str(material_type or "phong").lower().strip()
        if shader_type not in {"lambert", "phong", "blinn"}:
            raise ValueError("material_type must be one of lambert, phong, or blinn.")
        color = material_color if material_color is not None else [0.5, 0.5, 0.5]
        color = _validate_vector(color, 3, "material_color")
        shader = cmds.shadingNode(shader_type, asShader=True, name=material_name or f"{object_name}_region_mat")
        cmds.setAttr(f"{shader}.color", color[0], color[1], color[2], type="double3")
        if shader_type in {"phong", "blinn"}:
            if cmds.attributeQuery("specularColor", node=shader, exists=True):
                cmds.setAttr(f"{shader}.specularColor", 0.5, 0.5, 0.5, type="double3")
            if cmds.attributeQuery("reflectivity", node=shader, exists=True):
                cmds.setAttr(f"{shader}.reflectivity", 0.2)
        for attr, value in (material_parameters or {}).items():
            if not cmds.attributeQuery(attr, node=shader, exists=True):
                continue
            if isinstance(value, list) and len(value) == 3 and all(_is_number(item) for item in value):
                attr_type = cmds.getAttr(f"{shader}.{attr}", type=True)
                cmds.setAttr(f"{shader}.{attr}", float(value[0]), float(value[1]), float(value[2]), type=attr_type)
            else:
                cmds.setAttr(f"{shader}.{attr}", value)
        sg = cmds.sets(name=shading_group_name or f"{shader}SG", empty=True, renderable=True, noSurfaceShader=True)
        cmds.connectAttr(f"{shader}.outColor", f"{sg}.surfaceShader", force=True)
        return shader, sg, True

    def _resolve_material():
        if shading_group_name:
            if not cmds.objExists(shading_group_name):
                raise ValueError(f"Shading group does not exist: {shading_group_name}")
            return None, shading_group_name, False
        if material_name and cmds.objExists(material_name):
            groups = cmds.listConnections(material_name, type="shadingEngine") or []
            if groups:
                return material_name, groups[0], False
            sg = cmds.sets(name=f"{material_name}SG", empty=True, renderable=True, noSurfaceShader=True)
            cmds.connectAttr(f"{material_name}.outColor", f"{sg}.surfaceShader", force=True)
            return material_name, sg, False
        return _make_material()

    if not object_name:
        raise ValueError("object_name is required.")
    if not cmds.objExists(object_name):
        raise ValueError(f"Object does not exist: {object_name}")

    center = _validate_vector(center, 3, "center")
    clean_axis_range = _validate_range(axis_range, "axis_range") if axis_range is not None else None
    clean_radial_range = _validate_range(radial_range, "radial_range") if radial_range is not None else None
    clean_angle_range = _validate_vector(angle_range_degrees, 2, "angle_range_degrees") if angle_range_degrees is not None else None
    angle_span = _positive_span(clean_angle_range[0], clean_angle_range[1]) if clean_angle_range is not None else None
    if clean_axis_range is None and clean_radial_range is None and clean_angle_range is None:
        raise ValueError("At least one of axis_range, radial_range, or angle_range_degrees is required.")

    axis = str(axis).lower().strip()
    axes = {
        "x": (0, 1, 2),
        "y": (1, 0, 2),
        "z": (2, 0, 1),
    }
    if axis not in axes:
        raise ValueError("axis must be one of x, y, or z.")
    axis_index, radial_a, radial_b = axes[axis]

    if cmds.objectType(object_name) == "mesh":
        mesh_shape = object_name
        component_prefix = object_name
    else:
        shapes = cmds.listRelatives(object_name, shapes=True, fullPath=True) or []
        mesh_shapes = [shape for shape in shapes if cmds.objectType(shape) == "mesh"]
        if not mesh_shapes:
            raise ValueError(f"{object_name} is not a polygon mesh transform or mesh shape.")
        mesh_shape = mesh_shapes[0]
        component_prefix = object_name

    selection = om.MSelectionList()
    selection.add(mesh_shape)
    dag_path = selection.getDagPath(0)
    mesh_fn = om.MFnMesh(dag_path)
    points = mesh_fn.getPoints(om.MSpace.kWorld)
    face_counts, vertex_ids = mesh_fn.getVertices()

    matched_faces = []
    matched_axis_values = []
    matched_radii = []
    matched_angles = []
    cursor = 0
    for face_index, count in enumerate(face_counts):
        face_vertex_ids = vertex_ids[cursor: cursor + count]
        cursor += count
        face_points = [points[vertex_id] for vertex_id in face_vertex_ids]
        if include_partial_faces:
            is_match = any(_matches(point) for point in face_points)
            metric_points = [point for point in face_points if _matches(point)] or face_points
        else:
            center_point = om.MPoint()
            for point in face_points:
                center_point += point
            center_point = center_point / float(max(1, len(face_points)))
            is_match = _matches(center_point)
            metric_points = [center_point]
        if bool(is_match) == bool(invert):
            continue
        matched_faces.append(face_index)
        for point in metric_points:
            axis_value, radius, angle = _point_metrics(point)
            matched_axis_values.append(axis_value)
            matched_radii.append(radius)
            matched_angles.append(angle)

    material = None
    shading_group = None
    created_material = False
    assigned_components = []
    if matched_faces and not preview_only:
        material, shading_group, created_material = _resolve_material()
        assigned_components = [f"{component_prefix}.f[{face_index}]" for face_index in matched_faces]
        cmds.sets(assigned_components, edit=True, forceElement=shading_group)

    return {
        "success": True,
        "object_name": object_name,
        "mesh_shape": mesh_shape,
        "axis": axis,
        "center": center,
        "axis_range": clean_axis_range,
        "angle_range_degrees": clean_angle_range,
        "angle_span_degrees": angle_span,
        "radial_range": clean_radial_range,
        "include_partial_faces": bool(include_partial_faces),
        "invert": bool(invert),
        "preview_only": bool(preview_only),
        "total_face_count": int(mesh_fn.numPolygons),
        "matched_face_count": len(matched_faces),
        "matched_faces_sample": matched_faces[:50],
        "material": material,
        "shading_group": shading_group,
        "created_material": created_material,
        "assigned_component_count": len(assigned_components),
        "matched_axis_min": min(matched_axis_values) if matched_axis_values else None,
        "matched_axis_max": max(matched_axis_values) if matched_axis_values else None,
        "matched_radius_min": min(matched_radii) if matched_radii else None,
        "matched_radius_max": max(matched_radii) if matched_radii else None,
        "matched_angle_min": min(matched_angles) if matched_angles else None,
        "matched_angle_max": max(matched_angles) if matched_angles else None,
    }
