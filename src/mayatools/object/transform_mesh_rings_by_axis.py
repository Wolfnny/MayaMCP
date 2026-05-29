from typing import Dict, List, Any


def transform_mesh_rings_by_axis(
    object_name: str,
    ring_edits: List[Dict[str, Any]],
    axis: str = "y",
    center: List[float] = [0.0, 0.0, 0.0],
    group_tolerance: float = 0.001,
    target_tolerance: float = None,
    radius_stat: str = "mean",
    space: str = "world",
    select_result: bool = False,
    max_preview: int = 20,
) -> Dict[str, Any]:
    """Batch-edit coordinate-clustered mesh rings around an axis.

    Each ring edit selects the nearest vertex row along the chosen axis and
    changes its radial distance around center. This is the batch equivalent of
    a Maya artist selecting several edge/vertex loops and scaling them one at a
    time while preserving each vertex's angular position.

    ring_edits entries support:
    - target: axis coordinate used to find the nearest ring
    - radius: explicit target radius
    - radius_offset: add to the current representative radius
    - radius_scale: multiply the current representative radius
    - axis_value: optional coordinate to move the ring to along the axis
    - label: optional note echoed in the report

    Exactly one of radius, radius_offset, or radius_scale must be provided for
    each edit.
    """
    import math
    import maya.cmds as cmds
    import maya.api.OpenMaya as om

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(item) for item in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(item) for item in values]

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return int(value)

    def _axis_index(axis_name):
        clean = (axis_name or "").lower().strip()
        if clean not in {"x", "y", "z"}:
            raise ValueError("axis must be x, y, or z.")
        return {"x": 0, "y": 1, "z": 2}[clean]

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

    def _mesh_fn(shape):
        selection = om.MSelectionList()
        selection.add(shape)
        return om.MFnMesh(selection.getDagPath(0))

    def _prefix(shape):
        parents = cmds.listRelatives(shape, parent=True, fullPath=False) or []
        return parents[0] if parents else object_name

    def _point_values(point):
        return [float(point.x), float(point.y), float(point.z)]

    def _radius(values):
        delta_a = values[radial_axes[0]] - clean_center[radial_axes[0]]
        delta_b = values[radial_axes[1]] - clean_center[radial_axes[1]]
        return math.sqrt(delta_a * delta_a + delta_b * delta_b)

    def _representative_radius(radii):
        if clean_radius_stat == "mean":
            return sum(radii) / float(len(radii))
        if clean_radius_stat == "min":
            return min(radii)
        if clean_radius_stat == "max":
            return max(radii)
        ordered = sorted(radii)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) * 0.5

    def _build_ring_groups():
        records = []
        for vertex_id, point in enumerate(points):
            values = _point_values(point)
            records.append({"id": vertex_id, "axis_value": values[axis_idx]})
        records.sort(key=lambda item: (item["axis_value"], item["id"]))

        groups = []
        current = []
        group_start = None
        for record in records:
            if not current or record["axis_value"] - group_start <= clean_group_tolerance:
                current.append(record)
                if group_start is None:
                    group_start = record["axis_value"]
                continue
            groups.append(current)
            current = [record]
            group_start = record["axis_value"]
        if current:
            groups.append(current)

        result = []
        for group_index, group in enumerate(groups):
            values = [item["axis_value"] for item in group]
            ids = sorted(item["id"] for item in group)
            result.append(
                {
                    "group_index": group_index,
                    "axis_value": sum(values) / float(len(values)),
                    "axis_min": min(values),
                    "axis_max": max(values),
                    "vertex_ids": ids,
                }
            )
        return result

    def _pick_group(target):
        candidates = sorted(ring_groups, key=lambda group: (abs(group["axis_value"] - target), group["axis_value"]))
        if not candidates:
            raise ValueError("No vertex rings found.")
        group = candidates[0]
        distance = abs(group["axis_value"] - target)
        if clean_target_tolerance is not None and distance > clean_target_tolerance:
            raise ValueError(f"No ring within target_tolerance for target {target}. Nearest distance was {distance}.")
        return group, distance

    def _target_radius(edit, current_radius):
        keys = [key for key in ("radius", "radius_offset", "radius_scale") if key in edit and edit[key] is not None]
        if len(keys) != 1:
            raise ValueError("Each ring edit must provide exactly one of radius, radius_offset, or radius_scale.")
        if keys[0] == "radius":
            radius = _validate_scalar(edit["radius"], "radius")
        elif keys[0] == "radius_offset":
            radius = current_radius + _validate_scalar(edit["radius_offset"], "radius_offset")
        else:
            radius = current_radius * _validate_scalar(edit["radius_scale"], "radius_scale")
        if radius < 0.0:
            raise ValueError("Target radius must be greater than or equal to zero.")
        return radius

    if not object_name:
        raise ValueError("object_name is required.")
    if not isinstance(ring_edits, list) or not ring_edits:
        raise ValueError("ring_edits must be a non-empty list.")

    axis_idx = _axis_index(axis)
    radial_axes = [index for index in range(3) if index != axis_idx]
    clean_center = _validate_vector(center, 3, "center")
    clean_group_tolerance = _validate_scalar(group_tolerance, "group_tolerance")
    if clean_group_tolerance < 0.0:
        raise ValueError("group_tolerance must be greater than or equal to zero.")
    clean_target_tolerance = None if target_tolerance is None else _validate_scalar(target_tolerance, "target_tolerance")
    if clean_target_tolerance is not None and clean_target_tolerance < 0.0:
        raise ValueError("target_tolerance must be greater than or equal to zero.")
    clean_radius_stat = (radius_stat or "").lower().strip()
    if clean_radius_stat not in {"mean", "min", "max", "median"}:
        raise ValueError("radius_stat must be mean, min, max, or median.")
    space = (space or "").lower().strip()
    if space not in {"world", "object"}:
        raise ValueError("space must be world or object.")
    max_preview = _validate_int(max_preview, "max_preview", 0)

    shape_name = _mesh_shape(object_name)
    mesh_fn = _mesh_fn(shape_name)
    prefix_name = _prefix(shape_name)
    om_space = om.MSpace.kWorld if space == "world" else om.MSpace.kObject
    points = mesh_fn.getPoints(om_space)
    ring_groups = _build_ring_groups()

    used_groups = set()
    edited_vertex_ids = []
    edits_report = []
    for edit_index, edit in enumerate(ring_edits):
        if not isinstance(edit, dict):
            raise ValueError("Each ring_edits entry must be a dictionary.")
        if "target" not in edit:
            raise ValueError("Each ring edit requires target.")
        target = _validate_scalar(edit["target"], "target")
        group, distance = _pick_group(target)
        if group["group_index"] in used_groups:
            raise ValueError(f"Multiple edits resolved to the same ring near axis value {group['axis_value']}.")
        used_groups.add(group["group_index"])

        vertex_ids = group["vertex_ids"]
        radii_before = [_radius(_point_values(points[vertex_id])) for vertex_id in vertex_ids]
        current_radius = _representative_radius(radii_before)
        target_radius = _target_radius(edit, current_radius)
        target_axis = edit.get("axis_value")
        if target_axis is not None:
            target_axis = _validate_scalar(target_axis, "axis_value")

        for vertex_id in vertex_ids:
            values = _point_values(points[vertex_id])
            delta_a = values[radial_axes[0]] - clean_center[radial_axes[0]]
            delta_b = values[radial_axes[1]] - clean_center[radial_axes[1]]
            current = math.sqrt(delta_a * delta_a + delta_b * delta_b)
            if current <= 1e-12:
                values[radial_axes[0]] = clean_center[radial_axes[0]] + target_radius
                values[radial_axes[1]] = clean_center[radial_axes[1]]
            else:
                scale_factor = target_radius / current
                values[radial_axes[0]] = clean_center[radial_axes[0]] + delta_a * scale_factor
                values[radial_axes[1]] = clean_center[radial_axes[1]] + delta_b * scale_factor
            if target_axis is not None:
                values[axis_idx] = target_axis
            points[vertex_id] = om.MPoint(values[0], values[1], values[2])

        edited_vertex_ids.extend(vertex_ids)
        edits_report.append(
            {
                "edit_index": edit_index,
                "label": edit.get("label"),
                "target": target,
                "resolved_axis_value": group["axis_value"],
                "target_distance": distance,
                "vertex_count": len(vertex_ids),
                "radius_before": current_radius,
                "radius_after": target_radius,
                "axis_value_after": target_axis if target_axis is not None else group["axis_value"],
                "vertex_ids_preview": vertex_ids[:max_preview],
            }
        )

    mesh_fn.setPoints(points, om_space)
    try:
        mesh_fn.updateSurface()
    except Exception:
        pass

    unique_vertex_ids = sorted(set(edited_vertex_ids))
    if select_result and unique_vertex_ids:
        cmds.select([f"{prefix_name}.vtx[{vertex_id}]" for vertex_id in unique_vertex_ids], replace=True)
    elif not select_result:
        cmds.select(clear=True)

    return {
        "success": True,
        "object_name": object_name,
        "shape_name": shape_name,
        "axis": axis.lower().strip(),
        "center": clean_center,
        "space": space,
        "group_tolerance": clean_group_tolerance,
        "target_tolerance": clean_target_tolerance,
        "available_ring_count": len(ring_groups),
        "edited_ring_count": len(edits_report),
        "edited_vertex_count": len(unique_vertex_ids),
        "select_result": bool(select_result),
        "edits": edits_report,
    }
