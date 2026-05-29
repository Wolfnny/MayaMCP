from typing import Dict, List, Any, Union


def transform_uv_components(
    object_name: str,
    operation: str = "translate",
    uv_indices: List[int] = None,
    components: Union[str, List[str]] = None,
    offset: List[float] = None,
    scale: List[float] = None,
    rotation_degrees: float = None,
    axis: str = None,
    value: float = None,
    value_mode: str = "explicit",
    start_value: float = None,
    end_value: float = None,
    target_box: List[float] = None,
    fit_mode: str = "independent",
    pivot: List[float] = None,
    pivot_mode: str = "selection_center",
    uv_set: str = None,
    expand_uv_shell: bool = False,
    select_result: bool = True,
    use_selection: bool = True,
    max_preview: int = 50,
) -> Dict[str, Any]:
    """Transform selected UV components with UV-editor style operations.

    Operations:
    - translate: add offset [u, v]
    - scale: scale UVs around a pivot
    - rotate: rotate UVs around a pivot in degrees
    - align_axis: set all selected UVs to one u or v coordinate
    - distribute_axis: evenly distribute selected UVs along u or v
    - fit_box: fit selected UVs into target_box [min_u, min_v, max_u, max_v]

    UVs can be passed by index, explicit UV components, converted from selected
    faces/edges/vertices, or expanded to their UV shell. This supports localized
    UV layout work for labels, decals, panels, seams, and texture islands
    without remapping an entire mesh.
    Set select_result=False for automated previews or high-volume edits where
    leaving thousands of UVs selected would obscure the viewport.
    """
    import math
    import re
    import maya.cmds as cmds

    def _is_number(value_to_check):
        return isinstance(value_to_check, (int, float)) and not isinstance(value_to_check, bool)

    def _validate_scalar(value_to_check, arg_name):
        if not _is_number(value_to_check):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value_to_check)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(item) for item in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(item) for item in values]

    def _validate_int(value_to_check, arg_name, minimum):
        if not isinstance(value_to_check, int) or isinstance(value_to_check, bool) or value_to_check < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return int(value_to_check)

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

    def _flatten(value_to_flatten):
        if value_to_flatten is None:
            return []
        if isinstance(value_to_flatten, str):
            value_to_flatten = [value_to_flatten]
        if not isinstance(value_to_flatten, list) or not all(isinstance(item, str) for item in value_to_flatten):
            raise ValueError("components must be a string, a list of strings, or None.")
        return cmds.ls(value_to_flatten, flatten=True) or []

    def _unique(items):
        seen = set()
        result = []
        for item in cmds.ls(items, flatten=True) or []:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result

    def _selected_components():
        if not use_selection:
            return []
        selected = cmds.ls(selection=True, flatten=True) or []
        object_tokens = {object_name, prefix_name, shape_name}
        return [item for item in selected if item.split(".", 1)[0] in object_tokens]

    def _uv_id(component):
        match = re.search(r"\.map\[(\d+)\]$", component)
        return int(match.group(1)) if match else None

    def _mesh_fn():
        try:
            import maya.api.OpenMaya as om
        except Exception as exc:
            raise RuntimeError("maya.api.OpenMaya is required for bulk UV edits.") from exc
        selection = om.MSelectionList()
        selection.add(shape_name)
        return om.MFnMesh(selection.getDagPath(0))

    def _resolve_uv_components():
        if uv_indices is not None:
            if not isinstance(uv_indices, list) or not all(isinstance(index, int) and not isinstance(index, bool) for index in uv_indices):
                raise ValueError("uv_indices must be a list of integers.")
            resolved = [f"{prefix_name}.map[{index}]" for index in uv_indices]
        elif components is not None:
            resolved = _flatten(components)
            if not all(".map[" in item for item in resolved):
                resolved = cmds.polyListComponentConversion(resolved, toUV=True) or []
        else:
            selected = _selected_components()
            if not selected:
                raise ValueError("No UV components resolved from uv_indices, components, or current selection.")
            resolved = selected if all(".map[" in item for item in selected) else cmds.polyListComponentConversion(selected, toUV=True) or []

        if expand_uv_shell:
            resolved = cmds.polyListComponentConversion(resolved, toUV=True, uvShell=True) or []
        uv_items = [item for item in _unique(resolved) if ".map[" in item]
        if not uv_items:
            raise ValueError("No UV components resolved.")
        return uv_items

    def _query_uvs(items):
        uv_ids = [_uv_id(component) for component in items]
        try:
            u_values, v_values = _mesh_fn().getUVs(active_uv_set)
            records = []
            for component, uv_id in zip(items, uv_ids):
                if uv_id is None or uv_id < 0 or uv_id >= len(u_values):
                    continue
                records.append(
                    {
                        "component": component,
                        "index": uv_id,
                        "uv": [float(u_values[uv_id]), float(v_values[uv_id])],
                    }
                )
            return records
        except Exception:
            values = cmds.polyEditUV(items, query=True) or []
            records = []
            for index, component in enumerate(items):
                value_index = index * 2
                if value_index + 1 >= len(values):
                    continue
                records.append(
                    {
                        "component": component,
                        "index": uv_ids[index],
                        "uv": [float(values[value_index]), float(values[value_index + 1])],
                    }
                )
            return records

    def _bounds(records):
        if not records:
            raise ValueError("Cannot compute UV bounds without UV records.")
        min_u = min(record["uv"][0] for record in records)
        min_v = min(record["uv"][1] for record in records)
        max_u = max(record["uv"][0] for record in records)
        max_v = max(record["uv"][1] for record in records)
        return {
            "min": [min_u, min_v],
            "max": [max_u, max_v],
            "center": [(min_u + max_u) * 0.5, (min_v + max_v) * 0.5],
            "size": [max_u - min_u, max_v - min_v],
        }

    def _pivot(bounds):
        if pivot is not None:
            return _validate_vector(pivot, 2, "pivot")
        mode = pivot_mode.lower().strip()
        if mode == "origin":
            return [0.0, 0.0]
        if mode == "selection_min":
            return bounds["min"][:]
        if mode == "selection_max":
            return bounds["max"][:]
        if mode == "selection_center":
            return bounds["center"][:]
        raise ValueError("pivot_mode must be origin, selection_min, selection_max, or selection_center.")

    def _axis_index(axis_name):
        clean_axis = (axis_name or "").lower().strip()
        if clean_axis not in {"u", "v"}:
            raise ValueError("axis must be u or v.")
        return 0 if clean_axis == "u" else 1

    def _target_axis_value(axis_index, bounds):
        mode = value_mode.lower().strip()
        if mode == "explicit":
            return _validate_scalar(value, "value")
        if mode == "selection_min":
            return bounds["min"][axis_index]
        if mode == "selection_max":
            return bounds["max"][axis_index]
        if mode == "selection_center":
            return bounds["center"][axis_index]
        raise ValueError("value_mode must be explicit, selection_min, selection_max, or selection_center.")

    def _set_uvs(updated_by_component):
        if not updated_by_component:
            return
        try:
            mesh_fn = _mesh_fn()
            u_values, v_values = mesh_fn.getUVs(active_uv_set)
            u_values = list(u_values)
            v_values = list(v_values)
            for component, uv_value in updated_by_component.items():
                uv_id = _uv_id(component)
                if uv_id is None or uv_id < 0 or uv_id >= len(u_values):
                    continue
                u_values[uv_id] = float(uv_value[0])
                v_values[uv_id] = float(uv_value[1])
            mesh_fn.setUVs(u_values, v_values, active_uv_set)
            mesh_fn.updateSurface()
            return
        except Exception:
            for component, uv_value in updated_by_component.items():
                cmds.polyEditUV(component, relative=False, uValue=uv_value[0], vValue=uv_value[1])

    def _fit_to_box(records, bounds):
        box = _validate_vector(target_box or [0.0, 0.0, 1.0, 1.0], 4, "target_box")
        if box[2] <= box[0] or box[3] <= box[1]:
            raise ValueError("target_box must be [min_u, min_v, max_u, max_v] with positive size.")
        source_size = bounds["size"]
        target_size = [box[2] - box[0], box[3] - box[1]]
        if source_size[0] <= 1e-9 or source_size[1] <= 1e-9:
            raise ValueError("Selected UVs must have non-zero width and height for fit_box.")
        mode = fit_mode.lower().strip()
        if mode == "independent":
            scales = [target_size[0] / source_size[0], target_size[1] / source_size[1]]
        elif mode in {"uniform_fit", "uniform_fill"}:
            candidates = [target_size[0] / source_size[0], target_size[1] / source_size[1]]
            uniform = min(candidates) if mode == "uniform_fit" else max(candidates)
            scales = [uniform, uniform]
        else:
            raise ValueError("fit_mode must be independent, uniform_fit, or uniform_fill.")
        target_center = [(box[0] + box[2]) * 0.5, (box[1] + box[3]) * 0.5]
        updated = {}
        for record in records:
            u_value, v_value = record["uv"]
            updated[record["component"]] = [
                target_center[0] + (u_value - bounds["center"][0]) * scales[0],
                target_center[1] + (v_value - bounds["center"][1]) * scales[1],
            ]
        return updated, {"target_box": box, "fit_mode": mode, "scale": scales}

    if not object_name:
        raise ValueError("object_name is required.")
    operation = operation.lower().strip()
    if operation not in {"translate", "scale", "rotate", "align_axis", "distribute_axis", "fit_box"}:
        raise ValueError("operation must be translate, scale, rotate, align_axis, distribute_axis, or fit_box.")
    max_preview = _validate_int(max_preview, "max_preview", 0)

    shape_name = _mesh_shape(object_name)
    prefix_name = _prefix(shape_name)
    all_uv_sets = cmds.polyUVSet(object_name, query=True, allUVSets=True) or []
    previous_uv_set = (cmds.polyUVSet(object_name, query=True, currentUVSet=True) or [None])[0]
    if uv_set:
        if uv_set not in all_uv_sets:
            raise ValueError(f"UV set {uv_set} does not exist on {object_name}.")
        cmds.polyUVSet(object_name, currentUVSet=True, uvSet=uv_set)
    active_uv_set = uv_set or previous_uv_set

    try:
        uv_items = _resolve_uv_components()
        before_records = _query_uvs(uv_items)
        bounds_before = _bounds(before_records)
        updated_uvs = {}
        applied = {}

        if operation == "translate":
            clean_offset = _validate_vector(offset, 2, "offset")
            for record in before_records:
                updated_uvs[record["component"]] = [record["uv"][0] + clean_offset[0], record["uv"][1] + clean_offset[1]]
            applied["offset"] = clean_offset

        elif operation == "scale":
            clean_scale = _validate_vector(scale, 2, "scale")
            pivot_value = _pivot(bounds_before)
            for record in before_records:
                updated_uvs[record["component"]] = [
                    pivot_value[0] + (record["uv"][0] - pivot_value[0]) * clean_scale[0],
                    pivot_value[1] + (record["uv"][1] - pivot_value[1]) * clean_scale[1],
                ]
            applied["scale"] = clean_scale
            applied["pivot"] = pivot_value

        elif operation == "rotate":
            degrees = _validate_scalar(rotation_degrees, "rotation_degrees")
            pivot_value = _pivot(bounds_before)
            radians = math.radians(degrees)
            cos_value = math.cos(radians)
            sin_value = math.sin(radians)
            for record in before_records:
                local_u = record["uv"][0] - pivot_value[0]
                local_v = record["uv"][1] - pivot_value[1]
                updated_uvs[record["component"]] = [
                    pivot_value[0] + local_u * cos_value - local_v * sin_value,
                    pivot_value[1] + local_u * sin_value + local_v * cos_value,
                ]
            applied["rotation_degrees"] = degrees
            applied["pivot"] = pivot_value

        elif operation == "align_axis":
            axis_idx = _axis_index(axis)
            target_value = _target_axis_value(axis_idx, bounds_before)
            for record in before_records:
                uv_value = record["uv"][:]
                uv_value[axis_idx] = target_value
                updated_uvs[record["component"]] = uv_value
            applied["axis"] = axis.lower().strip()
            applied["value"] = target_value
            applied["value_mode"] = value_mode

        elif operation == "distribute_axis":
            axis_idx = _axis_index(axis)
            ordered = sorted(before_records, key=lambda record: (record["uv"][axis_idx], record["index"]))
            start = bounds_before["min"][axis_idx] if start_value is None else _validate_scalar(start_value, "start_value")
            end = bounds_before["max"][axis_idx] if end_value is None else _validate_scalar(end_value, "end_value")
            denominator = max(1, len(ordered) - 1)
            for order_index, record in enumerate(ordered):
                uv_value = record["uv"][:]
                uv_value[axis_idx] = start + (end - start) * (order_index / float(denominator))
                updated_uvs[record["component"]] = uv_value
            applied["axis"] = axis.lower().strip()
            applied["start_value"] = start
            applied["end_value"] = end

        elif operation == "fit_box":
            updated_uvs, applied = _fit_to_box(before_records, bounds_before)

        _set_uvs(updated_uvs)
        after_records = _query_uvs(uv_items)
        bounds_after = _bounds(after_records)
        if select_result:
            cmds.select(uv_items, replace=True)

        return {
            "success": True,
            "object_name": object_name,
            "operation": operation,
            "uv_set": uv_set or previous_uv_set,
            "uv_count": len(uv_items),
            "expand_uv_shell": bool(expand_uv_shell),
            "select_result": bool(select_result),
            "bounds_before": bounds_before,
            "bounds_after": bounds_after,
            "applied": applied,
            "before_preview": before_records[:max_preview],
            "after_preview": after_records[:max_preview],
        }
    finally:
        if uv_set and previous_uv_set and previous_uv_set in all_uv_sets and cmds.objExists(object_name):
            try:
                cmds.polyUVSet(object_name, currentUVSet=True, uvSet=previous_uv_set)
            except Exception:
                pass
