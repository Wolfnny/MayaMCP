from typing import Dict, List, Any


def inspect_mesh_rings_by_axis(
    object_name: str,
    axis: str = "y",
    center: List[float] = None,
    group_tolerance: float = 0.001,
    mode: str = "all",
    targets: List[float] = None,
    target_tolerance: float = None,
    min_components_per_group: int = 1,
    max_groups: int = 100,
    max_preview: int = 20,
    space: str = "world",
    include_components: bool = True,
) -> Dict[str, Any]:
    """Inspect coordinate-clustered polygon vertex rings along an axis.

    The tool reports per-ring axis position, vertex counts, radius statistics,
    local bounding boxes, and optional component previews. It is intended for
    Maya-style modeling decisions before editing edge loops, cap bands, bottle
    shoulders, bevel supports, panel rows, or other repeated mesh rings. It
    only reads mesh data and does not modify selection, geometry, or materials.

    Modes:
    - all: return all detected rings up to max_groups
    - nearest: return the closest ring for each target value
    - within: return rings within target_tolerance of any target value
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

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return int(value)

    def _validate_bool(value, arg_name):
        if not isinstance(value, bool):
            raise ValueError(f"{arg_name} must be a boolean.")
        return value

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(item) for item in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(item) for item in values]

    def _axis_index(axis_name):
        clean = (axis_name or "").lower().strip()
        if clean not in {"x", "y", "z"}:
            raise ValueError("axis must be x, y, or z.")
        return {"x": 0, "y": 1, "z": 2}[clean], clean

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

    def _component_prefix(shape):
        parents = cmds.listRelatives(shape, parent=True, fullPath=False) or []
        return parents[0] if parents else object_name

    def _point_values(point):
        return [float(point.x), float(point.y), float(point.z)]

    def _median(values):
        ordered = sorted(values)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) * 0.5

    def _radius(values):
        delta_a = values[radial_axes[0]] - clean_center[radial_axes[0]]
        delta_b = values[radial_axes[1]] - clean_center[radial_axes[1]]
        return math.sqrt(delta_a * delta_a + delta_b * delta_b)

    def _build_groups():
        records = []
        for vertex_id, point in enumerate(points):
            values = _point_values(point)
            records.append({"id": vertex_id, "axis_value": values[axis_idx], "values": values})
        records.sort(key=lambda item: (item["axis_value"], item["id"]))

        raw_groups = []
        current = []
        group_start = None
        for record in records:
            if not current or record["axis_value"] - group_start <= clean_group_tolerance:
                current.append(record)
                if group_start is None:
                    group_start = record["axis_value"]
                continue
            raw_groups.append(current)
            current = [record]
            group_start = record["axis_value"]
        if current:
            raw_groups.append(current)

        groups = []
        for group_index, raw_group in enumerate(raw_groups):
            if len(raw_group) < clean_min_components:
                continue
            ids = sorted(item["id"] for item in raw_group)
            axis_values = [item["axis_value"] for item in raw_group]
            positions = [item["values"] for item in raw_group]
            radii = [_radius(item["values"]) for item in raw_group]
            radius_mean = sum(radii) / float(len(radii))
            variance = sum((radius - radius_mean) ** 2 for radius in radii) / float(len(radii))
            bounds_min = [min(position[index] for position in positions) for index in range(3)]
            bounds_max = [max(position[index] for position in positions) for index in range(3)]
            component_preview = [f"{prefix}.vtx[{vertex_id}]" for vertex_id in ids[:clean_max_preview]]
            groups.append(
                {
                    "group_index": group_index,
                    "axis_value": sum(axis_values) / float(len(axis_values)),
                    "axis_min": min(axis_values),
                    "axis_max": max(axis_values),
                    "component_count": len(ids),
                    "component_ids_preview": ids[:clean_max_preview],
                    "components": component_preview if include_components else [],
                    "truncated": len(ids) > clean_max_preview,
                    "radius_min": min(radii),
                    "radius_mean": radius_mean,
                    "radius_median": _median(radii),
                    "radius_max": max(radii),
                    "radius_range": max(radii) - min(radii),
                    "radius_stddev": math.sqrt(variance),
                    "bounds_min": bounds_min,
                    "bounds_max": bounds_max,
                }
            )
        return groups

    def _clean_targets():
        if targets is None:
            return []
        if not isinstance(targets, list) or not all(_is_number(item) for item in targets):
            raise ValueError("targets must be a list of numeric values.")
        return [float(item) for item in targets]

    def _filter_groups(groups):
        if clean_mode == "all":
            return groups[:clean_max_groups], []
        if not clean_targets:
            raise ValueError("targets must be provided when mode is nearest or within.")
        if clean_mode == "nearest":
            selected = []
            selected_indices = set()
            target_reports = []
            for target in clean_targets:
                nearest = min(groups, key=lambda item: (abs(item["axis_value"] - target), item["axis_value"]))
                distance = abs(nearest["axis_value"] - target)
                if clean_target_tolerance is not None and distance > clean_target_tolerance:
                    target_reports.append({"target": target, "matched": False, "nearest_axis_value": nearest["axis_value"], "distance": distance})
                    continue
                target_reports.append({"target": target, "matched": True, "group_index": nearest["group_index"], "axis_value": nearest["axis_value"], "distance": distance})
                if nearest["group_index"] not in selected_indices:
                    selected.append(nearest)
                    selected_indices.add(nearest["group_index"])
            return selected[:clean_max_groups], target_reports

        selected = []
        selected_indices = set()
        target_reports = []
        tolerance = clean_target_tolerance
        if tolerance is None:
            raise ValueError("target_tolerance must be provided when mode is within.")
        for target in clean_targets:
            matched = [group for group in groups if abs(group["axis_value"] - target) <= tolerance]
            target_reports.append(
                {
                    "target": target,
                    "matched_count": len(matched),
                    "matched_group_indices": [group["group_index"] for group in matched[:clean_max_preview]],
                    "truncated": len(matched) > clean_max_preview,
                }
            )
            for group in matched:
                if group["group_index"] in selected_indices:
                    continue
                selected.append(group)
                selected_indices.add(group["group_index"])
        selected.sort(key=lambda item: item["axis_value"])
        return selected[:clean_max_groups], target_reports

    if not object_name:
        raise ValueError("object_name is required.")
    axis_idx, clean_axis = _axis_index(axis)
    radial_axes = [index for index in range(3) if index != axis_idx]
    clean_center = _validate_vector(center if center is not None else [0.0, 0.0, 0.0], 3, "center")
    clean_group_tolerance = _validate_scalar(group_tolerance, "group_tolerance")
    if clean_group_tolerance < 0.0:
        raise ValueError("group_tolerance must be greater than or equal to zero.")
    clean_target_tolerance = None if target_tolerance is None else _validate_scalar(target_tolerance, "target_tolerance")
    if clean_target_tolerance is not None and clean_target_tolerance < 0.0:
        raise ValueError("target_tolerance must be greater than or equal to zero.")
    clean_min_components = _validate_int(min_components_per_group, "min_components_per_group", 1)
    clean_max_groups = _validate_int(max_groups, "max_groups", 1)
    clean_max_preview = _validate_int(max_preview, "max_preview", 0)
    include_components = _validate_bool(include_components, "include_components")
    clean_targets = _clean_targets()
    clean_mode = (mode or "").lower().strip()
    if clean_mode not in {"all", "nearest", "within"}:
        raise ValueError("mode must be all, nearest, or within.")
    clean_space = (space or "").lower().strip()
    if clean_space not in {"world", "object"}:
        raise ValueError("space must be world or object.")

    shape_name = _mesh_shape(object_name)
    mesh_fn = _mesh_fn(shape_name)
    prefix = _component_prefix(shape_name)
    om_space = om.MSpace.kWorld if clean_space == "world" else om.MSpace.kObject
    points = mesh_fn.getPoints(om_space)
    all_groups = _build_groups()
    returned_groups, target_reports = _filter_groups(all_groups)

    return {
        "success": True,
        "object_name": object_name,
        "shape_name": shape_name,
        "axis": clean_axis,
        "center": clean_center,
        "space": clean_space,
        "mode": clean_mode,
        "targets": clean_targets,
        "group_tolerance": clean_group_tolerance,
        "target_tolerance": clean_target_tolerance,
        "min_components_per_group": clean_min_components,
        "available_group_count": len(all_groups),
        "returned_group_count": len(returned_groups),
        "truncated_groups": len(all_groups) > len(returned_groups) and clean_mode == "all",
        "target_reports": target_reports,
        "groups": returned_groups,
    }
