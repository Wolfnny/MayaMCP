from typing import Dict, List, Any, Union


def edit_uv_shells(
    object_name: str,
    operation: str = "query",
    shell_ids: List[int] = None,
    components: Union[str, List[str]] = None,
    target_box: List[float] = None,
    target_boxes: Any = None,
    grid_columns: int = 0,
    padding: float = 0.02,
    preserve_aspect: bool = True,
    uv_set: str = None,
    use_selection: bool = True,
    max_preview: int = 50,
) -> Dict[str, Any]:
    """Query, select, and arrange UV shells deterministically.

    Operations:
    - query: report UV shell bounds, UV members, and related faces
    - select: select UVs belonging to resolved shell ids
    - fit_box: fit each resolved shell to target_box or per-shell target_boxes
    - layout_grid: place resolved shells into a deterministic grid inside target_box

    This is for UV-editor style organization where texture regions need clear
    shell-level ownership and repeatable placement, such as labels, decals,
    panels, and separate material regions.
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

    def _validate_box(value, arg_name):
        box = value if value is not None else [0.0, 0.0, 1.0, 1.0]
        if not isinstance(box, list) or len(box) != 4 or not all(_is_number(item) for item in box):
            raise ValueError(f"{arg_name} must be [min_u, min_v, max_u, max_v].")
        clean = [float(item) for item in box]
        if clean[2] <= clean[0] or clean[3] <= clean[1]:
            raise ValueError(f"{arg_name} must have positive width and height.")
        return clean

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

    def _dag_path(shape):
        selection = om.MSelectionList()
        selection.add(shape)
        return selection.getDagPath(0)

    def _prefix(shape):
        parents = cmds.listRelatives(shape, parent=True, fullPath=False) or []
        return parents[0] if parents else object_name

    def _flatten(value):
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("components must be a string, a list of strings, or None.")
        return cmds.ls(value, flatten=True) or []

    def _unique(items):
        seen = set()
        result = []
        for item in cmds.ls(items, flatten=True) or []:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    def _selected_components():
        if not use_selection:
            return []
        selected = cmds.ls(selection=True, flatten=True) or []
        object_tokens = {object_name, prefix_name, shape_name}
        return [item for item in selected if item.split(".", 1)[0] in object_tokens]

    def _component(name, kind, index):
        return f"{name}.{kind}[{index}]"

    def _uv_component(uv_id):
        return _component(prefix_name, "map", uv_id)

    def _face_component(face_id):
        return _component(prefix_name, "f", face_id)

    def _convert_to_uvs(items):
        converted = cmds.polyListComponentConversion(items, toUV=True) or []
        return [item for item in _unique(converted) if ".map[" in item]

    def _uv_id(component):
        marker = ".map["
        if marker not in component:
            return None
        try:
            return int(component.rsplit(marker, 1)[1].rstrip("]"))
        except Exception:
            return None

    def _uv_position(uv_id):
        values = cmds.polyEditUV(_uv_component(uv_id), query=True) or [0.0, 0.0]
        return [float(values[0]), float(values[1])]

    def _set_uv_position(uv_id, position):
        cmds.polyEditUV(_uv_component(uv_id), relative=False, uValue=float(position[0]), vValue=float(position[1]))

    def _bounds(uv_ids):
        positions = [_uv_position(uv_id) for uv_id in uv_ids]
        if not positions:
            return None
        min_u = min(position[0] for position in positions)
        min_v = min(position[1] for position in positions)
        max_u = max(position[0] for position in positions)
        max_v = max(position[1] for position in positions)
        return {
            "min": [min_u, min_v],
            "max": [max_u, max_v],
            "center": [(min_u + max_u) * 0.5, (min_v + max_v) * 0.5],
            "size": [max_u - min_u, max_v - min_v],
        }

    def _face_shell_memberships(uv_shell_ids):
        memberships = {}
        mixed_faces = []
        polygon_it = om.MItMeshPolygon(_dag_path(shape_name))
        while not polygon_it.isDone():
            face_id = int(polygon_it.index())
            face_shell_ids = set()
            for local_index in range(polygon_it.polygonVertexCount()):
                try:
                    uv_id = int(polygon_it.getUVIndex(local_index, active_uv_set))
                except Exception:
                    continue
                if 0 <= uv_id < len(uv_shell_ids):
                    face_shell_ids.add(int(uv_shell_ids[uv_id]))
            if len(face_shell_ids) > 1:
                mixed_faces.append(face_id)
            for shell_id in face_shell_ids:
                memberships.setdefault(shell_id, []).append(face_id)
            polygon_it.next()
        return memberships, mixed_faces

    def _shell_data():
        shell_count, shell_id_array = mesh_fn.getUvShellsIds(active_uv_set)
        uv_shell_ids = [int(item) for item in shell_id_array]
        shells = {index: {"id": index, "uv_ids": [], "face_ids": []} for index in range(int(shell_count))}
        for uv_id, shell_id in enumerate(uv_shell_ids):
            shells.setdefault(shell_id, {"id": shell_id, "uv_ids": [], "face_ids": []})
            shells[shell_id]["uv_ids"].append(uv_id)
        face_memberships, mixed_faces = _face_shell_memberships(uv_shell_ids)
        for shell_id, face_ids in face_memberships.items():
            shells.setdefault(shell_id, {"id": shell_id, "uv_ids": [], "face_ids": []})
            shells[shell_id]["face_ids"] = sorted(set(face_ids))
        return shells, mixed_faces

    def _shell_records(shells):
        records = []
        for shell_id in sorted(shells):
            uv_ids = sorted(shells[shell_id]["uv_ids"])
            face_ids = sorted(shells[shell_id]["face_ids"])
            bounds = _bounds(uv_ids)
            records.append({
                "id": int(shell_id),
                "uv_count": len(uv_ids),
                "face_count": len(face_ids),
                "bounds": bounds,
                "uv_components": [_uv_component(uv_id) for uv_id in uv_ids[:max_preview]],
                "face_components": [_face_component(face_id) for face_id in face_ids[:max_preview]],
                "truncated_uvs": len(uv_ids) > max_preview,
                "truncated_faces": len(face_ids) > max_preview,
            })
        return records

    def _resolve_shell_ids(shells, allow_all=True):
        if shell_ids is not None:
            if not isinstance(shell_ids, list) or not all(isinstance(item, int) and not isinstance(item, bool) for item in shell_ids):
                raise ValueError("shell_ids must be a list of integers.")
            resolved = list(dict.fromkeys(int(item) for item in shell_ids))
        else:
            source = _flatten(components) if components is not None else _selected_components()
            if source:
                uv_items = _convert_to_uvs(source)
                resolved = []
                for item in uv_items:
                    uv_index = _uv_id(item)
                    if uv_index is None:
                        continue
                    for shell_id, record in shells.items():
                        if uv_index in record["uv_ids"] and shell_id not in resolved:
                            resolved.append(shell_id)
                            break
            elif allow_all:
                resolved = sorted(shells)
            else:
                raise ValueError("No shell ids resolved from shell_ids, components, or current selection.")
        unknown = [item for item in resolved if item not in shells]
        if unknown:
            raise ValueError(f"Unknown shell_ids: {unknown}.")
        if not resolved:
            raise ValueError("No UV shells resolved.")
        return resolved

    def _box_for_shell(shell_id, shell_order_index, resolved_shell_ids):
        if target_boxes is None:
            return _validate_box(target_box, "target_box")
        if isinstance(target_boxes, dict):
            key = str(shell_id)
            if key not in target_boxes and shell_id not in target_boxes:
                raise ValueError(f"target_boxes is missing shell id {shell_id}.")
            return _validate_box(target_boxes.get(key, target_boxes.get(shell_id)), f"target_boxes[{shell_id}]")
        if isinstance(target_boxes, list):
            if len(target_boxes) != len(resolved_shell_ids):
                raise ValueError("target_boxes list length must match resolved shell count.")
            return _validate_box(target_boxes[shell_order_index], f"target_boxes[{shell_order_index}]")
        raise ValueError("target_boxes must be a dict, list, or None.")

    def _inner_box(box, pad):
        width = box[2] - box[0]
        height = box[3] - box[1]
        clean_pad = max(0.0, min(pad, width * 0.49, height * 0.49))
        return [box[0] + clean_pad, box[1] + clean_pad, box[2] - clean_pad, box[3] - clean_pad]

    def _fit_uv_ids_to_box(uv_ids, box):
        bounds = _bounds(uv_ids)
        if not bounds:
            return {"skipped": True, "reason": "empty_shell"}
        source_size = bounds["size"]
        target_size = [box[2] - box[0], box[3] - box[1]]
        target_center = [(box[0] + box[2]) * 0.5, (box[1] + box[3]) * 0.5]
        if source_size[0] <= 1e-12 and source_size[1] <= 1e-12:
            for uv_id in uv_ids:
                _set_uv_position(uv_id, target_center)
            return {"scale": [0.0, 0.0], "target_box": box}
        scale_u = target_size[0] / source_size[0] if source_size[0] > 1e-12 else 1.0
        scale_v = target_size[1] / source_size[1] if source_size[1] > 1e-12 else 1.0
        if preserve_aspect:
            scale = min(scale_u, scale_v)
            scale_u = scale
            scale_v = scale
        for uv_id in uv_ids:
            position = _uv_position(uv_id)
            _set_uv_position(uv_id, [
                target_center[0] + (position[0] - bounds["center"][0]) * scale_u,
                target_center[1] + (position[1] - bounds["center"][1]) * scale_v,
            ])
        return {"scale": [scale_u, scale_v], "target_box": box}

    def _layout_boxes(count):
        box = _validate_box(target_box, "target_box")
        columns = grid_columns if grid_columns and grid_columns > 0 else int(math.ceil(math.sqrt(float(count))))
        columns = max(1, columns)
        rows = int(math.ceil(count / float(columns)))
        cell_width = (box[2] - box[0]) / float(columns)
        cell_height = (box[3] - box[1]) / float(rows)
        boxes = []
        for index in range(count):
            column = index % columns
            row = index // columns
            min_u = box[0] + column * cell_width
            max_u = min_u + cell_width
            max_v = box[3] - row * cell_height
            min_v = max_v - cell_height
            boxes.append(_inner_box([min_u, min_v, max_u, max_v], clean_padding))
        return boxes, {"columns": columns, "rows": rows, "target_box": box, "padding": clean_padding}

    def _summary(shells, mixed_faces):
        records = _shell_records(shells)
        return {
            "uv_set": active_uv_set,
            "shell_count": len(records),
            "uv_count": int(cmds.polyEvaluate(object_name, uvcoord=True)),
            "mixed_face_count": len(mixed_faces),
            "mixed_faces_preview": [_face_component(face_id) for face_id in mixed_faces[:max_preview]],
            "shells": records[:max_preview],
            "truncated_shells": len(records) > max_preview,
        }

    if not object_name:
        raise ValueError("object_name is required.")
    operation = operation.lower().strip()
    allowed = {"query", "select", "fit_box", "layout_grid"}
    if operation not in allowed:
        raise ValueError(f"operation must be one of: {', '.join(sorted(allowed))}.")
    max_preview = _validate_int(max_preview, "max_preview", 1)
    clean_padding = _validate_scalar(padding, "padding")
    if clean_padding < 0.0:
        raise ValueError("padding must be greater than or equal to zero.")

    shape_name = _mesh_shape(object_name)
    prefix_name = _prefix(shape_name)
    mesh_fn = _mesh_fn(shape_name)
    all_uv_sets = cmds.polyUVSet(object_name, query=True, allUVSets=True) or []
    previous_uv_set = (cmds.polyUVSet(object_name, query=True, currentUVSet=True) or [None])[0]
    if uv_set:
        if uv_set not in all_uv_sets:
            raise ValueError(f"UV set {uv_set} does not exist on {object_name}.")
        cmds.polyUVSet(object_name, currentUVSet=True, uvSet=uv_set)
    active_uv_set = uv_set or previous_uv_set

    try:
        before_shells, before_mixed_faces = _shell_data()
        resolved_shell_ids = _resolve_shell_ids(before_shells, allow_all=True)

        if operation == "query":
            selected_shells = {shell_id: before_shells[shell_id] for shell_id in resolved_shell_ids}
            return {
                "success": True,
                "object_name": object_name,
                "operation": operation,
                "resolved_shell_ids": resolved_shell_ids,
                "summary": _summary(selected_shells, before_mixed_faces),
            }

        if operation == "select":
            uv_items = []
            for shell_id in resolved_shell_ids:
                uv_items.extend(_uv_component(uv_id) for uv_id in sorted(before_shells[shell_id]["uv_ids"]))
            cmds.select(uv_items, replace=True)
            return {
                "success": True,
                "object_name": object_name,
                "operation": operation,
                "resolved_shell_ids": resolved_shell_ids,
                "selected_uv_count": len(uv_items),
                "selected_uvs_preview": uv_items[:max_preview],
            }

        before_summary = _summary({shell_id: before_shells[shell_id] for shell_id in resolved_shell_ids}, before_mixed_faces)
        applied = []
        if operation == "fit_box":
            for index, shell_id in enumerate(resolved_shell_ids):
                box = _box_for_shell(shell_id, index, resolved_shell_ids)
                result = _fit_uv_ids_to_box(before_shells[shell_id]["uv_ids"], box)
                result["shell_id"] = shell_id
                applied.append(result)

        elif operation == "layout_grid":
            boxes, grid_info = _layout_boxes(len(resolved_shell_ids))
            for index, shell_id in enumerate(resolved_shell_ids):
                result = _fit_uv_ids_to_box(before_shells[shell_id]["uv_ids"], boxes[index])
                result["shell_id"] = shell_id
                applied.append(result)
            applied.append({"grid": grid_info})

        after_shells, after_mixed_faces = _shell_data()
        return {
            "success": True,
            "object_name": object_name,
            "operation": operation,
            "resolved_shell_ids": resolved_shell_ids,
            "preserve_aspect": bool(preserve_aspect),
            "applied": applied,
            "summary_before": before_summary,
            "summary_after": _summary({shell_id: after_shells[shell_id] for shell_id in resolved_shell_ids}, after_mixed_faces),
        }
    finally:
        if uv_set and previous_uv_set and previous_uv_set in all_uv_sets and cmds.objExists(object_name):
            try:
                cmds.polyUVSet(object_name, currentUVSet=True, uvSet=previous_uv_set)
            except Exception:
                pass
