from typing import Dict, List, Any


def assign_materials_by_uv_image(
    object_name: str,
    image_path: str,
    material_rules: List[Dict[str, Any]],
    uv_set: str = None,
    match_mode: str = "nearest",
    unmatched_mode: str = "skip",
    default_rule_index: int = None,
    face_sample_mode: str = "center",
    sample_aggregation: str = "mean",
    flip_v: bool = True,
    wrap_u: bool = False,
    wrap_v: bool = False,
    create_if_missing: bool = True,
    dry_run: bool = False,
    select_result: bool = False,
    max_preview: int = 50,
) -> Dict[str, Any]:
    """Assign mesh faces to materials by sampling an image through existing UVs.

    This is a generic UV/material workflow tool for Maya-style face-level work:
    labels, decals, low-poly texture previews, color-ID masks, surface panels,
    and viewport-stable material bakes. It does not create or reshape geometry.
    It reads each face's UVs, samples image color, classifies the face against
    user-provided material rules, and assigns the matched faces to shading
    groups.

    material_rules entries support:
    - name: optional rule label
    - target_color: RGB list in 0..1 or 0..255 space
    - tolerance: color distance for tolerance modes
    - material_name: material to use or create
    - shading_group_name: shading group to use or create
    - material_type: lambert, blinn, phong, surface_shader, ai_standard_surface
    - material_color: RGB material color, defaults to target_color
    - material_parameters: optional shader attributes to set on creation

    match_mode:
    - nearest: assign every sampled face to the nearest target color
    - tolerance: assign to the first rule whose color distance is within tolerance
    - nearest_with_tolerance: assign to nearest rule only if within tolerance

    unmatched_mode controls faces not matched by tolerance modes: skip, error,
    or default. default_rule_index is used only when unmatched_mode is default.
    """
    import math
    import os
    import re
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
        raise RuntimeError("maya.api.OpenMaya is required to inspect mesh UVs.") from exc

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return int(value)

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(item) for item in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(item) for item in values]

    def _clamp(value, lower=0.0, upper=1.0):
        return max(lower, min(upper, value))

    def _normalize_color(values, arg_name):
        color = _validate_vector(values, 3, arg_name)
        if max(color) > 1.0:
            color = [item / 255.0 for item in color]
        return [_clamp(item) for item in color]

    def _normalize_tolerance(value):
        tolerance = _validate_scalar(value, "tolerance")
        if tolerance > 1.0:
            tolerance /= 255.0
        if tolerance < 0.0:
            raise ValueError("tolerance values must be greater than or equal to zero.")
        return tolerance

    def _safe_name(value, fallback):
        text = str(value or fallback).strip()
        text = re.sub(r"[^A-Za-z0-9_]+", "_", text)
        text = text.strip("_")
        return text or fallback

    def _mesh_shape(node):
        if not cmds.objExists(node):
            raise ValueError(f"Object does not exist: {node}")
        if cmds.objectType(node) == "mesh":
            return node
        shapes = cmds.listRelatives(node, shapes=True, fullPath=True) or []
        mesh_shapes = []
        for shape in shapes:
            if cmds.objectType(shape) != "mesh":
                continue
            try:
                if cmds.attributeQuery("intermediateObject", node=shape, exists=True) and cmds.getAttr(f"{shape}.intermediateObject"):
                    continue
            except Exception:
                pass
            mesh_shapes.append(shape)
        if not mesh_shapes:
            raise ValueError(f"{node} is not a polygon mesh transform or mesh shape.")
        return mesh_shapes[0]

    def _prefix(shape):
        parents = cmds.listRelatives(shape, parent=True, fullPath=False) or []
        return parents[0] if parents else object_name

    def _mesh_fn(shape):
        selection = om.MSelectionList()
        selection.add(shape)
        return om.MFnMesh(selection.getDagPath(0))

    def _wrap_or_clamp(value, wrap):
        return value % 1.0 if wrap else _clamp(value)

    def _pixel_rgb_alpha(image_value, x, y):
        color = image_value.pixelColor(int(x), int(y))
        return color.redF(), color.greenF(), color.blueF(), color.alphaF()

    def _sample_bilinear(image_value, u_value, v_value):
        width = image_value.width()
        height = image_value.height()
        u_value = _wrap_or_clamp(u_value, wrap_u)
        v_value = _wrap_or_clamp(v_value, wrap_v)
        if flip_v:
            v_value = 1.0 - v_value
        x = u_value * float(width - 1)
        y = v_value * float(height - 1)
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
        result = []
        for index in range(4):
            top = c00[index] * (1.0 - tx) + c10[index] * tx
            bottom = c01[index] * (1.0 - tx) + c11[index] * tx
            result.append(top * (1.0 - ty) + bottom * ty)
        return result

    def _mean_uv(pairs):
        return (
            sum(pair[0] for pair in pairs) / float(len(pairs)),
            sum(pair[1] for pair in pairs) / float(len(pairs)),
        )

    def _face_uv_samples(face_id):
        vertices = mesh_fn.getPolygonVertices(face_id)
        pairs = []
        for local_index in range(len(vertices)):
            try:
                uv_id = mesh_fn.getPolygonUVid(face_id, local_index, active_uv_set)
                u_value, v_value = mesh_fn.getUV(uv_id, active_uv_set)
                pairs.append((float(u_value), float(v_value)))
            except Exception:
                pass
        if not pairs:
            return []
        center = _mean_uv(pairs)
        if face_sample_mode == "center":
            return [center]
        if face_sample_mode == "vertices":
            return pairs
        return [center] + pairs

    def _aggregate_colors(colors):
        if not colors:
            return None
        if sample_aggregation == "mean":
            return [sum(color[index] for color in colors) / float(len(colors)) for index in range(4)]
        if sample_aggregation == "min":
            return [min(color[index] for color in colors) for index in range(4)]
        return [max(color[index] for color in colors) for index in range(4)]

    def _distance(color_a, color_b):
        dr = color_a[0] - color_b[0]
        dg = color_a[1] - color_b[1]
        db = color_a[2] - color_b[2]
        return (dr * dr + dg * dg + db * db) ** 0.5

    def _set_attr_if_exists(node, attr, value):
        if not cmds.attributeQuery(attr, node=node, exists=True):
            return False
        if isinstance(value, list) and len(value) == 3 and all(_is_number(item) for item in value):
            attr_type = cmds.getAttr(f"{node}.{attr}", type=True)
            if attr_type in {"double3", "float3"}:
                cmds.setAttr(f"{node}.{attr}", float(value[0]), float(value[1]), float(value[2]), type=attr_type)
            else:
                cmds.setAttr(f"{node}.{attr}", float(value[0]), float(value[1]), float(value[2]))
        else:
            cmds.setAttr(f"{node}.{attr}", value)
        return True

    def _create_material(shader_name, sg_name, rule):
        shader_type = str(rule.get("material_type", "lambert") or "lambert").strip().lower()
        type_map = {
            "lambert": "lambert",
            "blinn": "blinn",
            "phong": "phong",
            "surface_shader": "surfaceShader",
            "surfaceshader": "surfaceShader",
            "ai_standard_surface": "aiStandardSurface",
            "aistandardsurface": "aiStandardSurface",
        }
        if shader_type not in type_map:
            raise ValueError("material_type must be lambert, blinn, phong, surface_shader, or ai_standard_surface.")
        node_type = type_map[shader_type]
        shader = cmds.shadingNode(node_type, asShader=True, name=shader_name)
        material_color = rule.get("material_color", rule["target_color"])
        color = _normalize_color(material_color, "material_color")
        if not _set_attr_if_exists(shader, "color", color):
            _set_attr_if_exists(shader, "baseColor", color)
        if node_type == "aiStandardSurface":
            _set_attr_if_exists(shader, "base", 1.0)
        for attr, value in (rule.get("material_parameters") or {}).items():
            _set_attr_if_exists(shader, attr, value)
        shading_group = cmds.sets(name=sg_name, empty=True, renderable=True, noSurfaceShader=True)
        output_attr = "outColor" if cmds.attributeQuery("outColor", node=shader, exists=True) else "outValue"
        cmds.connectAttr(f"{shader}.{output_attr}", f"{shading_group}.surfaceShader", force=True)
        return shader, shading_group, True

    def _material_to_shading_group(shader, sg_name):
        groups = cmds.listConnections(shader, type="shadingEngine") or []
        if groups:
            return groups[0], False
        shading_group = cmds.sets(name=sg_name, empty=True, renderable=True, noSurfaceShader=True)
        output_attr = "outColor" if cmds.attributeQuery("outColor", node=shader, exists=True) else "outValue"
        cmds.connectAttr(f"{shader}.{output_attr}", f"{shading_group}.surfaceShader", force=True)
        return shading_group, True

    def _resolve_rule_material(rule, index):
        if dry_run:
            planned_name = rule.get("shading_group_name") or f"{rule['material_name']}SG"
            return rule["material_name"], planned_name, False
        sg_name = rule.get("shading_group_name")
        if sg_name and cmds.objExists(sg_name):
            if cmds.objectType(sg_name) != "shadingEngine":
                raise ValueError(f"{sg_name} is not a shadingEngine.")
            return None, sg_name, False
        material_name = rule["material_name"]
        if cmds.objExists(material_name):
            sg, created_sg = _material_to_shading_group(material_name, sg_name or f"{material_name}SG")
            return material_name, sg, created_sg
        if not create_if_missing:
            raise ValueError(f"Material does not exist: {material_name}")
        shader, sg, created = _create_material(material_name, sg_name or f"{material_name}SG", rule)
        return shader, sg, created

    def _prepare_rules():
        if not isinstance(material_rules, list) or not material_rules:
            raise ValueError("material_rules must be a non-empty list.")
        prepared = []
        for index, rule in enumerate(material_rules):
            if not isinstance(rule, dict):
                raise ValueError("Each material_rules entry must be a dictionary.")
            if "target_color" not in rule:
                raise ValueError("Each material_rules entry requires target_color.")
            name = _safe_name(rule.get("name"), f"rule_{index}")
            target_color = _normalize_color(rule.get("target_color"), f"material_rules[{index}].target_color")
            clean_rule = dict(rule)
            clean_rule["index"] = index
            clean_rule["name"] = name
            clean_rule["target_color"] = target_color
            clean_rule["tolerance"] = _normalize_tolerance(rule.get("tolerance", 0.12))
            clean_rule["material_name"] = rule.get("material_name") or f"{_safe_name(object_name, 'mesh')}_{name}_mat"
            prepared.append(clean_rule)
        return prepared

    def _match_rule(color):
        distances = [(_distance(color, rule["target_color"]), rule) for rule in rules]
        distances.sort(key=lambda item: (item[0], item[1]["index"]))
        nearest_distance, nearest_rule = distances[0]
        if match_mode == "nearest":
            return nearest_rule, nearest_distance
        if match_mode == "nearest_with_tolerance":
            return (nearest_rule, nearest_distance) if nearest_distance <= nearest_rule["tolerance"] else (None, nearest_distance)
        for rule in rules:
            distance = _distance(color, rule["target_color"])
            if distance <= rule["tolerance"]:
                return rule, distance
        return None, nearest_distance

    def _assign_components(components, shading_group):
        if dry_run or not components:
            return
        for start in range(0, len(components), 5000):
            cmds.sets(components[start:start + 5000], edit=True, forceElement=shading_group)

    if not object_name:
        raise ValueError("object_name is required.")
    if not image_path:
        raise ValueError("image_path is required.")
    normalized_image_path = os.path.normpath(image_path)
    if not os.path.isfile(normalized_image_path):
        raise ValueError(f"Image path does not exist: {image_path}")
    match_mode = match_mode.lower().strip()
    if match_mode not in {"nearest", "tolerance", "nearest_with_tolerance"}:
        raise ValueError("match_mode must be nearest, tolerance, or nearest_with_tolerance.")
    unmatched_mode = unmatched_mode.lower().strip()
    if unmatched_mode not in {"skip", "error", "default"}:
        raise ValueError("unmatched_mode must be skip, error, or default.")
    face_sample_mode = face_sample_mode.lower().strip()
    if face_sample_mode not in {"center", "vertices", "center_vertices"}:
        raise ValueError("face_sample_mode must be center, vertices, or center_vertices.")
    sample_aggregation = sample_aggregation.lower().strip()
    if sample_aggregation not in {"mean", "min", "max"}:
        raise ValueError("sample_aggregation must be mean, min, or max.")
    max_preview = _validate_int(max_preview, "max_preview", 1)

    rules = _prepare_rules()
    if default_rule_index is not None:
        default_rule_index = _validate_int(default_rule_index, "default_rule_index", 0)
        if default_rule_index >= len(rules):
            raise ValueError(f"default_rule_index must be in range 0..{len(rules) - 1}.")
    elif unmatched_mode == "default":
        raise ValueError("default_rule_index is required when unmatched_mode is default.")

    image = QImage(normalized_image_path)
    if image.isNull():
        raise ValueError(f"Unable to load image: {image_path}")
    if image.width() < 2 or image.height() < 2:
        raise ValueError("image must be at least 2x2 pixels.")

    shape_name = _mesh_shape(object_name)
    prefix_name = _prefix(shape_name)
    mesh_fn = _mesh_fn(shape_name)
    uv_sets = list(mesh_fn.getUVSetNames())
    active_uv_set = uv_set or (mesh_fn.currentUVSetName() if uv_sets else None)
    if not active_uv_set or active_uv_set not in uv_sets:
        raise ValueError(f"UV set does not exist on {object_name}: {active_uv_set}")
    if mesh_fn.numUVs(active_uv_set) <= 0:
        raise ValueError(f"UV set has no UVs: {active_uv_set}")

    rule_components = {rule["index"]: [] for rule in rules}
    rule_records = {rule["index"]: [] for rule in rules}
    unmatched = []
    sampled_count = 0

    for face_id in range(int(mesh_fn.numPolygons)):
        samples = _face_uv_samples(face_id)
        if not samples:
            unmatched.append({"face": face_id, "reason": "missing_uv"})
            continue
        colors = [_sample_bilinear(image, sample[0], sample[1]) for sample in samples]
        color = _aggregate_colors(colors)
        sampled_count += 1
        rule, distance = _match_rule(color)
        if rule is None:
            if unmatched_mode == "error":
                raise ValueError(f"Face {face_id} did not match any material rule.")
            if unmatched_mode == "default":
                rule = rules[default_rule_index]
            else:
                unmatched.append({"face": face_id, "reason": "no_match", "sample_color": color[:3], "nearest_distance": distance})
                continue
        component = f"{prefix_name}.f[{face_id}]"
        rule_components[rule["index"]].append(component)
        if len(rule_records[rule["index"]]) < max_preview:
            rule_records[rule["index"]].append({
                "face": face_id,
                "component": component,
                "sample_color": color[:3],
                "distance": distance,
            })

    resolved_materials = {}
    assignments = []
    assigned_components = []
    for rule in rules:
        components = rule_components[rule["index"]]
        material_name, shading_group, created = _resolve_rule_material(rule, rule["index"])
        _assign_components(components, shading_group)
        assigned_components.extend(components)
        resolved_materials[rule["index"]] = {"material": material_name, "shading_group": shading_group}
        assignments.append({
            "rule_index": rule["index"],
            "rule_name": rule["name"],
            "target_color": rule["target_color"],
            "tolerance": rule["tolerance"],
            "material_name": material_name,
            "shading_group_name": shading_group,
            "created_material_or_shading_group": bool(created),
            "face_count": len(components),
            "faces_preview": rule_records[rule["index"]],
        })

    if select_result and assigned_components and not dry_run:
        cmds.select(assigned_components, replace=True)

    return {
        "success": True,
        "object_name": object_name,
        "shape_name": shape_name,
        "image_path": normalized_image_path,
        "uv_set": active_uv_set,
        "match_mode": match_mode,
        "unmatched_mode": unmatched_mode,
        "face_sample_mode": face_sample_mode,
        "sample_aggregation": sample_aggregation,
        "dry_run": dry_run,
        "sampled_face_count": sampled_count,
        "assigned_face_count": sum(item["face_count"] for item in assignments),
        "unmatched_face_count": len(unmatched),
        "unmatched_preview": unmatched[:max_preview],
        "assignments": assignments,
    }
