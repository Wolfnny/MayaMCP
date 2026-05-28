from typing import Dict, List, Any


def select_mesh_rings_by_axis(
    object_name: str,
    result_type: str = "vertex",
    axis: str = "y",
    targets: List[float] = None,
    mode: str = "nearest",
    group_tolerance: float = 0.001,
    target_tolerance: float = None,
    min_components_per_group: int = 1,
    space: str = "world",
    selection_mode: str = "replace",
    select_result: bool = True,
    max_groups: int = 20,
    max_preview: int = 100,
) -> Dict[str, Any]:
    """Select coordinate-clustered mesh rows or component bands along an axis.

    Modes:
    - nearest: find the closest coordinate group for each target value
    - within: find all coordinate groups within target_tolerance of each target
    - all: report all coordinate groups, limited by max_groups

    This is a generic Maya-style component navigation tool for meshes with
    repeated rows or bands, such as bottles, cans, vases, characters, props, and
    gridded hard-surface models. It makes component rings explicit before
    localized transforms, edge sliding, normal edits, material assignment, or UV
    work.
    """
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

    def _axis_index(axis_name):
        clean_axis = (axis_name or "").lower().strip()
        if clean_axis not in {"x", "y", "z"}:
            raise ValueError("axis must be x, y, or z.")
        return {"x": 0, "y": 1, "z": 2}[clean_axis]

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

    def _dag_path(shape):
        selection = om.MSelectionList()
        selection.add(shape)
        return selection.getDagPath(0)

    def _prefix(shape):
        parents = cmds.listRelatives(shape, parent=True, fullPath=False) or []
        return parents[0] if parents else object_name

    def _point_values(point):
        return [float(point.x), float(point.y), float(point.z)]

    def _component_center(component_id):
        if clean_result_type == "vertex":
            return _point_values(points[component_id])
        if clean_result_type == "edge":
            vertex_ids = list(mesh_fn.getEdgeVertices(component_id))
        else:
            vertex_ids = list(mesh_fn.getPolygonVertices(component_id))
        center = [0.0, 0.0, 0.0]
        for vertex_id in vertex_ids:
            values = _point_values(points[int(vertex_id)])
            center[0] += values[0]
            center[1] += values[1]
            center[2] += values[2]
        scale = 1.0 / float(max(1, len(vertex_ids)))
        return [center[0] * scale, center[1] * scale, center[2] * scale]

    def _component_name(component_id):
        kind = {"vertex": "vtx", "edge": "e", "face": "f"}[clean_result_type]
        return f"{prefix_name}.{kind}[{component_id}]"

    def _build_groups():
        total = {
            "vertex": int(mesh_fn.numVertices),
            "edge": int(mesh_fn.numEdges),
            "face": int(mesh_fn.numPolygons),
        }[clean_result_type]
        records = []
        for component_id in range(total):
            center = _component_center(component_id)
            records.append(
                {
                    "id": component_id,
                    "axis_value": center[axis_idx],
                    "center": center,
                }
            )
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
            if len(group) < clean_min_components:
                continue
            values = [item["axis_value"] for item in group]
            ids = sorted(item["id"] for item in group)
            result.append(
                {
                    "group_index": group_index,
                    "axis_value": sum(values) / float(len(values)),
                    "axis_min": min(values),
                    "axis_max": max(values),
                    "component_count": len(group),
                    "component_ids": ids,
                }
            )
        return result

    def _pick_groups(groups):
        if clean_mode == "all":
            return groups[:clean_max_groups]
        if not clean_targets:
            raise ValueError("targets are required for nearest and within modes.")
        picked = []
        seen = set()
        tolerance = clean_target_tolerance
        for target in clean_targets:
            if clean_mode == "nearest":
                candidates = sorted(groups, key=lambda group: (abs(group["axis_value"] - target), group["axis_value"]))
                if not candidates:
                    continue
                group = candidates[0]
                distance = abs(group["axis_value"] - target)
                if tolerance is not None and distance > tolerance:
                    continue
                records = [dict(group)]
                records[0]["target"] = target
                records[0]["target_distance"] = distance
            else:
                records = []
                for group in groups:
                    distance = abs(group["axis_value"] - target)
                    if distance <= tolerance:
                        record = dict(group)
                        record["target"] = target
                        record["target_distance"] = distance
                        records.append(record)
            for record in records:
                key = record["group_index"]
                if key in seen:
                    continue
                seen.add(key)
                picked.append(record)
        picked.sort(key=lambda item: item["axis_value"])
        return picked[:clean_max_groups]

    def _apply_selection(items):
        mode_name = selection_mode.lower().strip()
        if mode_name not in {"replace", "add", "toggle", "deselect"}:
            raise ValueError("selection_mode must be replace, add, toggle, or deselect.")
        cmds.select(items, **{mode_name: True})

    if not object_name:
        raise ValueError("object_name is required.")
    clean_result_type = result_type.lower().strip()
    if clean_result_type not in {"vertex", "edge", "face"}:
        raise ValueError("result_type must be vertex, edge, or face.")
    clean_mode = mode.lower().strip()
    if clean_mode not in {"nearest", "within", "all"}:
        raise ValueError("mode must be nearest, within, or all.")
    clean_group_tolerance = _validate_scalar(group_tolerance, "group_tolerance")
    if clean_group_tolerance < 0.0:
        raise ValueError("group_tolerance must be greater than or equal to zero.")
    if target_tolerance is None:
        clean_target_tolerance = None if clean_mode == "nearest" else clean_group_tolerance
    else:
        clean_target_tolerance = _validate_scalar(target_tolerance, "target_tolerance")
        if clean_target_tolerance < 0.0:
            raise ValueError("target_tolerance must be greater than or equal to zero.")
    clean_min_components = _validate_int(min_components_per_group, "min_components_per_group", 1)
    clean_max_groups = _validate_int(max_groups, "max_groups", 1)
    max_preview = _validate_int(max_preview, "max_preview", 1)
    space = space.lower().strip()
    if space not in {"world", "object"}:
        raise ValueError("space must be world or object.")
    clean_targets = []
    if targets is not None:
        if not isinstance(targets, list) or not all(_is_number(item) for item in targets):
            raise ValueError("targets must be a list of numeric values.")
        clean_targets = [float(item) for item in targets]

    axis_idx = _axis_index(axis)
    shape_name = _mesh_shape(object_name)
    prefix_name = _prefix(shape_name)
    dag_path = _dag_path(shape_name)
    mesh_fn = om.MFnMesh(dag_path)
    om_space = om.MSpace.kWorld if space == "world" else om.MSpace.kObject
    points = mesh_fn.getPoints(om_space)

    all_groups = _build_groups()
    picked_groups = _pick_groups(all_groups)
    selected_components = []
    for group in picked_groups:
        components = [_component_name(component_id) for component_id in group["component_ids"]]
        selected_components.extend(components)
        group["components"] = components[:max_preview]
        group["truncated"] = len(components) > max_preview
        group["component_ids_preview"] = group["component_ids"][:max_preview]
        if len(group["component_ids"]) > max_preview:
            group["component_ids"] = group["component_ids"][:max_preview]

    if select_result and selected_components:
        _apply_selection(selected_components)
    elif select_result and selection_mode.lower().strip() == "replace":
        cmds.select(clear=True)

    return {
        "success": True,
        "object_name": object_name,
        "shape_name": shape_name,
        "result_type": clean_result_type,
        "axis": axis.lower().strip(),
        "space": space,
        "mode": clean_mode,
        "targets": clean_targets,
        "group_tolerance": clean_group_tolerance,
        "target_tolerance": clean_target_tolerance,
        "min_components_per_group": clean_min_components,
        "available_group_count": len(all_groups),
        "returned_group_count": len(picked_groups),
        "selected_component_count": len(selected_components),
        "selected_components": selected_components[:max_preview],
        "selected_components_truncated": len(selected_components) > max_preview,
        "selected": bool(select_result and selected_components),
        "selection_mode": selection_mode if select_result and selected_components else None,
        "groups": picked_groups,
    }
