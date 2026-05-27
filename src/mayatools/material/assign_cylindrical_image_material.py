from typing import Dict, List, Any


def assign_cylindrical_image_material(
    object_name: str,
    image_path: str,
    name: str = None,
    uv_set: str = "map1",
    center: List[float] = [0.0, 0.0, 0.0],
    axis: str = "y",
    axis_range: List[float] = None,
    angle_range_degrees: List[float] = [-60.0, 60.0],
    outside_axis_mode: str = "extend",
    outside_angle_mode: str = "ignore",
    sample_channel: str = "alpha",
    threshold: float = 0.05,
    assign_above: bool = True,
    face_sample_mode: str = "center",
    sample_aggregation: str = "mean",
    flip_u: bool = False,
    flip_v: bool = False,
    material_name: str = None,
    material_type: str = "lambert",
    color_attribute: str = "color",
    use_alpha: bool = False,
    link_uv_set: bool = True,
    min_assign_faces: int = 1,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Assign a textured material to mesh faces selected by cylindrical image sampling.

    The tool writes deterministic cylindrical UVs to the mesh, links the file
    texture to that UV set, samples an image in the same angle/axis space, and
    assigns a texture material only to faces whose sampled channel crosses the
    threshold. It is generic infrastructure for projection decals, labels,
    panels, surface markings, trim masks, partial wraps, and photo-to-surface
    workflows on bottles, cans, tubes, cups, and other near-lathed meshes
    without relying on separate floating cards.

    outside_axis_mode controls how samples beyond axis_range are handled:
    "extend" preserves unclamped coordinates, "clamp" pins them to the nearest
    edge, and "ignore" excludes out-of-range faces from material assignment.
    """
    import math
    import os
    import maya.cmds as cmds

    try:
        from PySide6.QtGui import QImage
    except Exception:
        try:
            from PySide2.QtGui import QImage
        except Exception as exc:
            raise RuntimeError("PySide QImage is required to sample image pixels in Maya.") from exc

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

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return value

    def _clamp(value, lower=0.0, upper=1.0):
        return max(lower, min(upper, value))

    def _positive_span(start_degrees, end_degrees):
        span = (end_degrees - start_degrees) % 360.0
        return 360.0 if abs(span) < 1e-8 else span

    def _angle_delta(angle_degrees, start_degrees):
        return (angle_degrees - start_degrees) % 360.0

    def _angle_t(angle_degrees, start_degrees, span_degrees):
        delta = _angle_delta(angle_degrees, start_degrees)
        if span_degrees >= 360.0 - 1e-8:
            return delta / 360.0
        if delta <= span_degrees:
            return delta / span_degrees
        if outside_angle_mode == "ignore":
            return None
        if outside_angle_mode == "wrap":
            return (delta / span_degrees) % 1.0
        if outside_angle_mode == "clamp":
            distance_to_start = min(delta, 360.0 - delta)
            distance_to_end = abs(delta - span_degrees)
            return 0.0 if distance_to_start < distance_to_end else 1.0
        return delta / span_degrees

    def _axis_t(local_axis, axis_start, axis_span):
        value = (local_axis - axis_start) / axis_span
        if 0.0 <= value <= 1.0:
            return value
        if outside_axis_mode == "ignore":
            return None
        if outside_axis_mode == "clamp":
            return _clamp(value)
        return value

    def _shape_dag_path(node_name):
        selection = om.MSelectionList()
        selection.add(node_name)
        dag_path = selection.getDagPath(0)
        if dag_path.node().hasFn(om.MFn.kTransform):
            dag_path.extendToShape()
        if not dag_path.node().hasFn(om.MFn.kMesh):
            raise ValueError(f"{object_name} is not a polygon mesh transform or mesh shape.")
        return dag_path

    def _mesh_shape_name():
        if cmds.objectType(object_name) == "mesh":
            return object_name
        shapes = cmds.listRelatives(object_name, shapes=True, fullPath=True) or []
        for shape in shapes:
            if cmds.objectType(shape) == "mesh":
                return shape
        raise ValueError(f"{object_name} is not a polygon mesh transform or mesh shape.")

    def _uv_set_plug(shape_name, uv_set_name):
        indices = cmds.getAttr(f"{shape_name}.uvSet", multiIndices=True) or []
        for index in indices:
            plug = f"{shape_name}.uvSet[{index}].uvSetName"
            try:
                if cmds.getAttr(plug) == uv_set_name:
                    return plug
            except Exception:
                continue
        uv_names = cmds.polyUVSet(object_name, query=True, allUVSets=True) or []
        if uv_set_name in uv_names:
            return f"{shape_name}.uvSet[{uv_names.index(uv_set_name)}].uvSetName"
        return None

    def _link_texture_to_uv_set(file_node_name):
        if not link_uv_set:
            return None, False
        shape_name = _mesh_shape_name()
        plug = _uv_set_plug(shape_name, uv_set)
        if not plug:
            raise ValueError(f"Unable to resolve UV set plug for {uv_set} on {object_name}.")
        try:
            cmds.uvLink(uvSet=plug, texture=file_node_name)
        except Exception as exc:
            if uv_set != "map1":
                raise RuntimeError(f"Unable to link texture {file_node_name} to UV set {uv_set}.") from exc
            return plug, False
        return plug, True

    def _pixel_rgb_alpha(image_value, x, y):
        color = image_value.pixelColor(int(x), int(y))
        return color.redF(), color.greenF(), color.blueF(), color.alphaF()

    def _sample_bilinear(image_value, u, v):
        width = image_value.width()
        height = image_value.height()
        u = _clamp(u)
        v = _clamp(v)
        x = u * float(width - 1)
        y = (1.0 - v) * float(height - 1)
        x0 = int(math.floor(x))
        y0 = int(math.floor(y))
        x1 = min(width - 1, x0 + 1)
        y1 = min(height - 1, y0 + 1)
        tx = x - x0
        ty = y - y0
        c00 = _pixel_rgb_alpha(image_value, x0, y0)
        c10 = _pixel_rgb_alpha(image_value, x1, y0)
        c01 = _pixel_rgb_alpha(image_value, x0, y1)
        c11 = _pixel_rgb_alpha(image_value, x1, y1)
        channels = []
        for index in range(4):
            top = c00[index] * (1.0 - tx) + c10[index] * tx
            bottom = c01[index] * (1.0 - tx) + c11[index] * tx
            channels.append(top * (1.0 - ty) + bottom * ty)
        return channels

    def _rgb_to_hsv(red, green, blue):
        max_value = max(red, green, blue)
        min_value = min(red, green, blue)
        delta = max_value - min_value
        if delta == 0.0:
            hue = 0.0
        elif max_value == red:
            hue = ((green - blue) / delta) % 6.0
        elif max_value == green:
            hue = ((blue - red) / delta) + 2.0
        else:
            hue = ((red - green) / delta) + 4.0
        hue /= 6.0
        saturation = 0.0 if max_value == 0.0 else delta / max_value
        return hue, saturation, max_value

    def _channel_value(channels):
        red, green, blue, alpha = channels
        if sample_channel == "red":
            return red
        if sample_channel == "green":
            return green
        if sample_channel == "blue":
            return blue
        if sample_channel == "alpha":
            return alpha
        if sample_channel == "value":
            return max(red, green, blue)
        if sample_channel == "saturation":
            return _rgb_to_hsv(red, green, blue)[1]
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    def _aggregate(values):
        if sample_aggregation == "min":
            return min(values)
        if sample_aggregation == "max":
            return max(values)
        return sum(values) / float(len(values))

    def _project_point(point):
        local_axis = point[axis_index] - center[axis_index]
        delta_a = point[radial_a] - center[radial_a]
        delta_b = point[radial_b] - center[radial_b]
        angle_degrees = math.degrees(math.atan2(delta_a, delta_b))
        u = _angle_t(angle_degrees, angle_start, angle_span)
        if u is None:
            return None
        v = _axis_t(local_axis, axis_start, axis_span)
        if v is None:
            return None
        if flip_u:
            u = 1.0 - u
        if flip_v:
            v = 1.0 - v
        return u, v

    def _make_texture_material(shader_name):
        shader = cmds.shadingNode(material_type, asShader=True, name=shader_name)
        file_node = cmds.shadingNode("file", asTexture=True, name=f"{shader_name}_file")
        place2d = cmds.shadingNode("place2dTexture", asUtility=True, name=f"{shader_name}_place2d")
        for attr in ["outUV", "outUvFilterSize"]:
            destination = "uvCoord" if attr == "outUV" else "uvFilterSize"
            cmds.connectAttr(f"{place2d}.{attr}", f"{file_node}.{destination}", force=True)
        for attr in [
            "coverage",
            "translateFrame",
            "rotateFrame",
            "mirrorU",
            "mirrorV",
            "stagger",
            "wrapU",
            "wrapV",
            "repeatUV",
            "offset",
            "rotateUV",
            "noiseUV",
            "vertexUvOne",
            "vertexUvTwo",
            "vertexUvThree",
            "vertexCameraOne",
        ]:
            if cmds.attributeQuery(attr, node=place2d, exists=True) and cmds.attributeQuery(attr, node=file_node, exists=True):
                cmds.connectAttr(f"{place2d}.{attr}", f"{file_node}.{attr}", force=True)
        cmds.setAttr(f"{file_node}.fileTextureName", normalized_image_path, type="string")
        target_attribute = "outColor" if material_type == "surfaceShader" else color_attribute
        if not cmds.attributeQuery(target_attribute, node=shader, exists=True):
            raise ValueError(f"Shader {shader} does not have attribute {target_attribute}.")
        cmds.connectAttr(f"{file_node}.outColor", f"{shader}.{target_attribute}", force=True)
        alpha_node = None
        if use_alpha and material_type != "surfaceShader" and cmds.attributeQuery("transparency", node=shader, exists=True):
            alpha_node = cmds.shadingNode("reverse", asUtility=True, name=f"{shader_name}_alpha_reverse")
            for channel in ["X", "Y", "Z"]:
                cmds.connectAttr(f"{file_node}.outAlpha", f"{alpha_node}.input{channel}", force=True)
            cmds.connectAttr(f"{alpha_node}.output", f"{shader}.transparency", force=True)
        shading_group = cmds.sets(name=f"{shader_name}SG", empty=True, renderable=True, noSurfaceShader=True)
        cmds.connectAttr(f"{shader}.outColor", f"{shading_group}.surfaceShader", force=True)
        uv_link_plug, uv_linked = _link_texture_to_uv_set(file_node)
        return shader, file_node, place2d, alpha_node, shading_group, uv_link_plug, uv_linked

    if not object_name:
        raise ValueError("object_name is required.")
    if not cmds.objExists(object_name):
        raise ValueError(f"Object does not exist: {object_name}")
    if not image_path:
        raise ValueError("image_path is required.")
    normalized_image_path = os.path.normpath(image_path)
    if not os.path.isfile(normalized_image_path):
        raise ValueError(f"Image path does not exist: {image_path}")
    if not uv_set:
        raise ValueError("uv_set is required.")

    center = _validate_vector(center, 3, "center")
    if axis_range is not None:
        axis_range = _validate_vector(axis_range, 2, "axis_range")
    angle_range_degrees = _validate_vector(angle_range_degrees, 2, "angle_range_degrees")
    threshold = _clamp(_validate_scalar(threshold, "threshold"))
    min_assign_faces = _validate_int(min_assign_faces, "min_assign_faces", 0)

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
    if outside_angle_mode not in {"ignore", "wrap", "clamp", "extend"}:
        raise ValueError("outside_angle_mode must be ignore, wrap, clamp, or extend.")
    outside_axis_mode = outside_axis_mode.lower().strip()
    if outside_axis_mode not in {"ignore", "clamp", "extend"}:
        raise ValueError("outside_axis_mode must be ignore, clamp, or extend.")
    sample_channel = sample_channel.lower().strip()
    if sample_channel not in {"alpha", "luminance", "red", "green", "blue", "value", "saturation"}:
        raise ValueError("sample_channel must be one of alpha, luminance, red, green, blue, value, or saturation.")
    face_sample_mode = face_sample_mode.lower().strip()
    if face_sample_mode not in {"center", "vertices", "center_vertices"}:
        raise ValueError("face_sample_mode must be center, vertices, or center_vertices.")
    sample_aggregation = sample_aggregation.lower().strip()
    if sample_aggregation not in {"mean", "min", "max"}:
        raise ValueError("sample_aggregation must be mean, min, or max.")
    material_type = material_type.strip()
    if material_type not in {"lambert", "phong", "blinn", "surfaceShader"}:
        raise ValueError("material_type must be lambert, phong, blinn, or surfaceShader.")

    image = QImage(normalized_image_path)
    if image.isNull():
        raise ValueError(f"Unable to load image: {image_path}")
    if image.width() < 2 or image.height() < 2:
        raise ValueError("image must be at least 2x2 pixels.")

    dag_path = _shape_dag_path(object_name)
    mesh_fn = om.MFnMesh(dag_path)
    uv_sets = list(mesh_fn.getUVSetNames())
    if uv_set not in uv_sets:
        mesh_fn.createUVSet(uv_set)
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

    angle_start, angle_end = angle_range_degrees
    angle_span = _positive_span(angle_start, angle_end)

    u_values = []
    v_values = []
    uv_ids = []
    matched_faces = []
    skipped_outside_faces = 0
    sample_values = []
    cursor = 0

    for face_index, count in enumerate(face_counts):
        projected_vertices = []
        positions = []
        for _ in range(count):
            vertex_id = vertex_ids[cursor]
            point = points[vertex_id]
            positions.append(point)
            projected = _project_point(point)
            if projected is None:
                if outside_angle_mode == "ignore":
                    projected = (0.0, (point[axis_index] - center[axis_index] - axis_start) / axis_span)
                else:
                    projected = (0.0, 0.0)
            u_values.append(float(projected[0]))
            v_values.append(float(projected[1]))
            uv_ids.append(len(u_values) - 1)
            projected_vertices.append(projected)
            cursor += 1

        center_point = om.MPoint()
        for point in positions:
            center_point += point
        center_point = center_point / float(len(positions))

        sample_uvs = []
        if face_sample_mode in {"center", "center_vertices"}:
            center_projected = _project_point(center_point)
            if center_projected is not None:
                sample_uvs.append(center_projected)
        if face_sample_mode in {"vertices", "center_vertices"}:
            sample_uvs.extend([
                projected
                for projected in (_project_point(point) for point in positions)
                if projected is not None
            ])

        if not sample_uvs:
            skipped_outside_faces += 1
            continue
        values = [_channel_value(_sample_bilinear(image, uv[0], uv[1])) for uv in sample_uvs]
        value = _aggregate(values)
        sample_values.append(value)
        matched = value >= threshold if assign_above else value <= threshold
        if matched:
            matched_faces.append(face_index)

    try:
        mesh_fn.clearUVs(uv_set)
    except Exception:
        pass
    mesh_fn.setUVs(u_values, v_values, uv_set)
    mesh_fn.assignUVs(face_counts, uv_ids, uv_set)
    mesh_fn.updateSurface()
    try:
        cmds.polyUVSet(object_name, currentUVSet=True, uvSet=uv_set)
    except Exception:
        pass

    if len(matched_faces) < min_assign_faces:
        raise ValueError(f"Only {len(matched_faces)} faces matched, below min_assign_faces={min_assign_faces}.")

    shader = None
    file_node = None
    place2d = None
    alpha_node = None
    shading_group = None
    uv_link_plug = None
    uv_linked = False
    assigned_components = []
    if matched_faces and not dry_run:
        if material_name is None:
            base_name = os.path.splitext(os.path.basename(normalized_image_path))[0] or "projected"
            material_name = name or f"{base_name}_cylindrical_projected_mat"
        shader, file_node, place2d, alpha_node, shading_group, uv_link_plug, uv_linked = _make_texture_material(material_name)
        for start in range(0, len(matched_faces), 1000):
            batch = matched_faces[start:start + 1000]
            components = [f"{object_name}.f[{face_index}]" for face_index in batch]
            cmds.sets(components, edit=True, forceElement=shading_group)
            assigned_components.extend(components)

    return {
        "success": True,
        "object_name": object_name,
        "image_path": normalized_image_path,
        "image_width": image.width(),
        "image_height": image.height(),
        "uv_set": uv_set,
        "center": center,
        "axis": axis,
        "axis_range": [axis_start, axis_end],
        "angle_range_degrees": angle_range_degrees,
        "angle_span_degrees": angle_span,
        "outside_axis_mode": outside_axis_mode,
        "outside_angle_mode": outside_angle_mode,
        "sample_channel": sample_channel,
        "threshold": threshold,
        "assign_above": bool(assign_above),
        "face_sample_mode": face_sample_mode,
        "sample_aggregation": sample_aggregation,
        "flip_u": bool(flip_u),
        "flip_v": bool(flip_v),
        "link_uv_set": bool(link_uv_set),
        "dry_run": bool(dry_run),
        "face_count": len(face_counts),
        "uv_count": len(u_values),
        "sampled_face_count": len(sample_values),
        "skipped_outside_face_count": skipped_outside_faces,
        "matched_face_count": len(matched_faces),
        "assigned_face_count": 0 if dry_run else len(assigned_components),
        "min_sample_value": min(sample_values) if sample_values else 0.0,
        "max_sample_value": max(sample_values) if sample_values else 0.0,
        "mean_sample_value": sum(sample_values) / float(len(sample_values)) if sample_values else 0.0,
        "material": shader,
        "file_node": file_node,
        "place2d": place2d,
        "alpha_node": alpha_node,
        "shading_group": shading_group,
        "uv_link_plug": uv_link_plug,
        "uv_linked": bool(uv_linked),
        "matched_faces_preview": matched_faces[:20],
    }
