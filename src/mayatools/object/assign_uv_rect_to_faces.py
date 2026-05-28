from typing import Dict, List, Any, Union


def assign_uv_rect_to_faces(
    object_name: str,
    face_indices: List[int] = None,
    components: Union[str, List[str]] = None,
    uv_set: str = "map1",
    u_axis: str = "x",
    v_axis: str = "y",
    target_box: List[float] = None,
    source_box: List[float] = None,
    preserve_aspect: bool = False,
    padding: float = 0.0,
    flip_u: bool = False,
    flip_v: bool = False,
    separate_uvs: bool = True,
    space: str = "world",
    use_selection: bool = True,
    select_result: bool = True,
    max_preview: int = 50,
) -> Dict[str, Any]:
    """Assign selected mesh faces into a rectangular UV region.

    This is a direct UV-editor style operation for labels, decals, panels, and
    local face islands. Selected faces are projected from two mesh coordinate
    axes into target_box [min_u, min_v, max_u, max_v]. By default, selected
    face-vertices receive separate UV ids so the edited patch does not drag
    neighboring shells that shared UVs before the assignment.
    """
    import re
    import maya.cmds as cmds
    import maya.api.OpenMaya as om

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

    def _validate_box(value, arg_name, default):
        box = default if value is None else value
        if not isinstance(box, list) or len(box) != 4 or not all(_is_number(item) for item in box):
            raise ValueError(f"{arg_name} must be [min_u, min_v, max_u, max_v].")
        clean = [float(item) for item in box]
        if clean[2] <= clean[0] or clean[3] <= clean[1]:
            raise ValueError(f"{arg_name} must have positive width and height.")
        return clean

    def _axis_index(axis_name, arg_name):
        clean = (axis_name or "").lower().strip()
        if clean not in {"x", "y", "z"}:
            raise ValueError(f"{arg_name} must be x, y, or z.")
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

    def _dag_path(shape):
        selection = om.MSelectionList()
        selection.add(shape)
        return selection.getDagPath(0)

    def _mesh_fn(shape):
        return om.MFnMesh(_dag_path(shape))

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

    def _selected_components():
        if not use_selection:
            return []
        selected = cmds.ls(selection=True, flatten=True) or []
        object_tokens = {object_name, prefix_name, shape_name}
        return [item for item in selected if item.split(".", 1)[0] in object_tokens]

    def _component_ids(items, kind):
        pattern = re.compile(rf"\.{kind}\[(\d+)\]$")
        ids = []
        for item in cmds.ls(items, flatten=True) or []:
            match = pattern.search(item)
            if match:
                ids.append(int(match.group(1)))
        return list(dict.fromkeys(ids))

    def _resolve_face_ids():
        if face_indices is not None:
            if not isinstance(face_indices, list) or not all(isinstance(index, int) and not isinstance(index, bool) for index in face_indices):
                raise ValueError("face_indices must be a list of integers.")
            resolved = list(dict.fromkeys(face_indices))
        else:
            source = _flatten(components) if components is not None else _selected_components()
            faces = cmds.polyListComponentConversion(source, toFace=True) or []
            resolved = _component_ids(faces, "f")
        if not resolved:
            raise ValueError("No face components resolved from face_indices, components, or current selection.")
        for face_id in resolved:
            if face_id < 0 or face_id >= mesh_fn.numPolygons:
                raise ValueError(f"Face index {face_id} is out of range 0..{mesh_fn.numPolygons - 1}.")
        return sorted(set(resolved))

    def _inner_box(box, pad):
        width = box[2] - box[0]
        height = box[3] - box[1]
        clean_pad = max(0.0, min(pad, width * 0.49, height * 0.49))
        return [box[0] + clean_pad, box[1] + clean_pad, box[2] - clean_pad, box[3] - clean_pad]

    def _face_offsets(face_counts):
        offsets = []
        cursor = 0
        for count in face_counts:
            offsets.append(cursor)
            cursor += int(count)
        return offsets

    def _existing_assignments(face_counts):
        total_face_vertices = sum(int(count) for count in face_counts)
        try:
            assigned_counts, assigned_ids = mesh_fn.getAssignedUVs(uv_set)
            assigned_counts = [int(item) for item in assigned_counts]
            assigned_ids = [int(item) for item in assigned_ids]
            if assigned_counts == [int(item) for item in face_counts] and len(assigned_ids) == total_face_vertices and mesh_fn.numUVs(uv_set) > 0:
                u_values, v_values = mesh_fn.getUVs(uv_set)
                return [float(item) for item in u_values], [float(item) for item in v_values], assigned_ids
        except Exception:
            pass
        u_values = [0.0 for _ in range(total_face_vertices)]
        v_values = [0.0 for _ in range(total_face_vertices)]
        uv_ids = list(range(total_face_vertices))
        return u_values, v_values, uv_ids

    def _selected_uv_ids(uv_ids, face_counts, offsets, face_ids):
        result = []
        for face_id in face_ids:
            start = offsets[face_id]
            for local_index in range(int(face_counts[face_id])):
                result.append(int(uv_ids[start + local_index]))
        return result

    def _uv_range(u_values, v_values, uv_ids):
        clean_ids = [uv_id for uv_id in uv_ids if 0 <= uv_id < len(u_values)]
        if not clean_ids:
            return None
        us = [u_values[uv_id] for uv_id in clean_ids]
        vs = [v_values[uv_id] for uv_id in clean_ids]
        return {
            "min_u": min(us),
            "max_u": max(us),
            "min_v": min(vs),
            "max_v": max(vs),
        }

    def _project_values(face_ids, face_counts, offsets, vertex_ids, points):
        values = []
        for face_id in face_ids:
            start = offsets[face_id]
            for local_index in range(int(face_counts[face_id])):
                vertex_id = int(vertex_ids[start + local_index])
                point = points[vertex_id]
                coords = [float(point.x), float(point.y), float(point.z)]
                values.append((coords[u_axis_index], coords[v_axis_index]))
        return values

    def _source_box(projected):
        if source_box is not None:
            return _validate_box(source_box, "source_box", None)
        us = [item[0] for item in projected]
        vs = [item[1] for item in projected]
        min_u = min(us)
        max_u = max(us)
        min_v = min(vs)
        max_v = max(vs)
        if abs(max_u - min_u) <= 1.0e-12:
            min_u -= 0.5
            max_u += 0.5
        if abs(max_v - min_v) <= 1.0e-12:
            min_v -= 0.5
            max_v += 0.5
        return [min_u, min_v, max_u, max_v]

    def _map_to_uv(u_value, v_value, src_box, dst_box):
        if preserve_aspect:
            src_width = src_box[2] - src_box[0]
            src_height = src_box[3] - src_box[1]
            dst_width = dst_box[2] - dst_box[0]
            dst_height = dst_box[3] - dst_box[1]
            scale = min(dst_width / src_width, dst_height / src_height)
            dst_center = [(dst_box[0] + dst_box[2]) * 0.5, (dst_box[1] + dst_box[3]) * 0.5]
            src_center = [(src_box[0] + src_box[2]) * 0.5, (src_box[1] + src_box[3]) * 0.5]
            mapped_u = dst_center[0] + (u_value - src_center[0]) * scale
            mapped_v = dst_center[1] + (v_value - src_center[1]) * scale
        else:
            mapped_u = dst_box[0] + ((u_value - src_box[0]) / (src_box[2] - src_box[0])) * (dst_box[2] - dst_box[0])
            mapped_v = dst_box[1] + ((v_value - src_box[1]) / (src_box[3] - src_box[1])) * (dst_box[3] - dst_box[1])
        if flip_u:
            mapped_u = dst_box[0] + dst_box[2] - mapped_u
        if flip_v:
            mapped_v = dst_box[1] + dst_box[3] - mapped_v
        return mapped_u, mapped_v

    if not object_name:
        raise ValueError("object_name is required.")
    if not uv_set:
        raise ValueError("uv_set is required.")
    max_preview = _validate_int(max_preview, "max_preview", 0)
    clean_padding = _validate_scalar(padding, "padding")
    if clean_padding < 0.0:
        raise ValueError("padding must be greater than or equal to zero.")
    target = _inner_box(_validate_box(target_box, "target_box", [0.0, 0.0, 1.0, 1.0]), clean_padding)
    u_axis_index = _axis_index(u_axis, "u_axis")
    v_axis_index = _axis_index(v_axis, "v_axis")
    if u_axis_index == v_axis_index:
        raise ValueError("u_axis and v_axis must be different axes.")
    space = space.lower().strip()
    if space not in {"world", "object"}:
        raise ValueError("space must be world or object.")

    shape_name = _mesh_shape(object_name)
    prefix_name = _prefix(shape_name)
    all_uv_sets = cmds.polyUVSet(object_name, query=True, allUVSets=True) or []
    previous_uv_set = (cmds.polyUVSet(object_name, query=True, currentUVSet=True) or [None])[0]
    if uv_set not in all_uv_sets:
        cmds.polyUVSet(object_name, create=True, uvSet=uv_set)
    cmds.polyUVSet(object_name, currentUVSet=True, uvSet=uv_set)

    mesh_fn = _mesh_fn(shape_name)
    om_space = om.MSpace.kWorld if space == "world" else om.MSpace.kObject

    try:
        selected_faces = _resolve_face_ids()
        face_counts, vertex_ids = mesh_fn.getVertices()
        face_counts = [int(item) for item in face_counts]
        vertex_ids = [int(item) for item in vertex_ids]
        offsets = _face_offsets(face_counts)
        points = mesh_fn.getPoints(om_space)
        u_values, v_values, uv_ids = _existing_assignments(face_counts)
        selected_before_ids = _selected_uv_ids(uv_ids, face_counts, offsets, selected_faces)
        before_range = _uv_range(u_values, v_values, selected_before_ids)

        projected_values = _project_values(selected_faces, face_counts, offsets, vertex_ids, points)
        src = _source_box(projected_values)
        edit_records = []
        projected_cursor = 0
        for face_id in selected_faces:
            start = offsets[face_id]
            for local_index in range(face_counts[face_id]):
                projected_u, projected_v = projected_values[projected_cursor]
                mapped_u, mapped_v = _map_to_uv(projected_u, projected_v, src, target)
                assignment_index = start + local_index
                if separate_uvs:
                    uv_id = len(u_values)
                    u_values.append(mapped_u)
                    v_values.append(mapped_v)
                    uv_ids[assignment_index] = uv_id
                else:
                    uv_id = uv_ids[assignment_index]
                    if uv_id < 0 or uv_id >= len(u_values):
                        uv_id = len(u_values)
                        u_values.append(mapped_u)
                        v_values.append(mapped_v)
                        uv_ids[assignment_index] = uv_id
                    else:
                        u_values[uv_id] = mapped_u
                        v_values[uv_id] = mapped_v
                edit_records.append(
                    {
                        "face_index": int(face_id),
                        "local_vertex_index": int(local_index),
                        "vertex_index": int(vertex_ids[assignment_index]),
                        "uv_index": int(uv_id),
                        "uv": [float(mapped_u), float(mapped_v)],
                    }
                )
                projected_cursor += 1

        mesh_fn.setUVs(u_values, v_values, uv_set)
        mesh_fn.assignUVs(face_counts, uv_ids, uv_set)
        mesh_fn.updateSurface()

        selected_after_ids = _selected_uv_ids(uv_ids, face_counts, offsets, selected_faces)
        after_range = _uv_range(u_values, v_values, selected_after_ids)
        if select_result:
            cmds.select([f"{prefix_name}.map[{uv_id}]" for uv_id in selected_after_ids], replace=True)

        return {
            "success": True,
            "object_name": object_name,
            "shape_name": shape_name,
            "uv_set": uv_set,
            "face_count": len(selected_faces),
            "face_indices": selected_faces[:max_preview],
            "truncated_faces": len(selected_faces) > max_preview,
            "u_axis": u_axis.lower().strip(),
            "v_axis": v_axis.lower().strip(),
            "space": space,
            "target_box": target,
            "source_box": src,
            "preserve_aspect": bool(preserve_aspect),
            "flip_u": bool(flip_u),
            "flip_v": bool(flip_v),
            "separate_uvs": bool(separate_uvs),
            "uv_count_before": len(u_values) - (len(edit_records) if separate_uvs else 0),
            "uv_count_after": len(u_values),
            "selected_uv_range_before": before_range,
            "selected_uv_range_after": after_range,
            "edited_face_vertex_count": len(edit_records),
            "edited_preview": edit_records[:max_preview],
            "selected": bool(select_result),
        }
    finally:
        if previous_uv_set and previous_uv_set in (cmds.polyUVSet(object_name, query=True, allUVSets=True) or []) and cmds.objExists(object_name):
            try:
                cmds.polyUVSet(object_name, currentUVSet=True, uvSet=previous_uv_set)
            except Exception:
                pass
