from typing import Dict, List, Any, Union


def select_mesh_by_uv_region(
    object_name: str,
    uv_box: List[float],
    result_type: str = "face",
    component_type: str = None,
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    sample_mode: str = "center",
    keep_inside: bool = True,
    uv_set: str = None,
    selection_mode: str = "replace",
    select_result: bool = True,
    use_selection: bool = True,
    max_preview: int = 200,
) -> Dict[str, Any]:
    """Filter mesh components by UV coordinates inside a rectangular region.

    Result types:
    - uv: select UVs whose coordinates are inside or outside uv_box
    - face: select faces by UV center, any UV, or all UVs
    - edge, vertex: convert matched faces or UVs to mesh edges or vertices

    This is a UV-editor style selection constraint for labels, decals, trim
    sheets, texture masks, material regions, and cleanup tasks where component
    ownership is clearer in UV space than in world space.
    """
    import re
    import maya.cmds as cmds
    import maya.api.OpenMaya as om

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_box(value):
        if not isinstance(value, list) or len(value) != 4 or not all(_is_number(item) for item in value):
            raise ValueError("uv_box must be [min_u, min_v, max_u, max_v].")
        clean = [float(item) for item in value]
        if clean[2] < clean[0]:
            clean[0], clean[2] = clean[2], clean[0]
        if clean[3] < clean[1]:
            clean[1], clean[3] = clean[3], clean[1]
        if clean[2] == clean[0] or clean[3] == clean[1]:
            raise ValueError("uv_box must have non-zero width and height.")
        return clean

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return int(value)

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

    def _components_from_indices(kind):
        if indices is None:
            return []
        if not isinstance(indices, list) or not all(isinstance(index, int) and not isinstance(index, bool) for index in indices):
            raise ValueError("indices must be a list of integers.")
        return [f"{prefix_name}.{kind}[{index}]" for index in indices]

    def _resolve_components(default_type=None):
        clean_type = (component_type or default_type or "").lower().strip()
        kind_map = {"vertex": "vtx", "edge": "e", "face": "f", "uv": "map", "vertex_face": "vtxFace"}
        if components is not None:
            return _flatten(components)
        if clean_type in kind_map and indices is not None:
            return _components_from_indices(kind_map[clean_type])
        return _selected_components()

    def _unique(items):
        seen = set()
        result = []
        for item in cmds.ls(items, flatten=True) or []:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    def _component_ids(items, kind):
        pattern = re.compile(rf"\.{kind}\[(\d+)\]$")
        ids = []
        for item in cmds.ls(items, flatten=True) or []:
            match = pattern.search(item)
            if match:
                ids.append(int(match.group(1)))
        return list(dict.fromkeys(ids))

    def _convert(items, target):
        flags = {
            "vertex": {"toVertex": True},
            "edge": {"toEdge": True},
            "face": {"toFace": True},
            "uv": {"toUV": True},
        }[target]
        return _unique(cmds.polyListComponentConversion(items, **flags) or [])

    def _uv_component(uv_id):
        return f"{prefix_name}.map[{uv_id}]"

    def _face_component(face_id):
        return f"{prefix_name}.f[{face_id}]"

    def _inside(uv):
        u_value, v_value = uv
        return clean_box[0] <= u_value <= clean_box[2] and clean_box[1] <= v_value <= clean_box[3]

    def _uv_value(uv_id):
        u_value, v_value = mesh_fn.getUV(int(uv_id), active_uv_set)
        return [float(u_value), float(v_value)]

    def _candidate_face_ids():
        source = _resolve_components("face")
        if not source:
            return list(range(int(mesh_fn.numPolygons)))
        return _component_ids(_convert(source, "face"), "f")

    def _candidate_uv_ids():
        source = _resolve_components("uv")
        if not source:
            return list(range(int(mesh_fn.numUVs(active_uv_set))))
        return _component_ids(_convert(source, "uv"), "map")

    def _face_uv_records(face_id):
        polygon_it.setIndex(int(face_id))
        records = []
        for local_index in range(int(polygon_it.polygonVertexCount())):
            try:
                uv_id = int(polygon_it.getUVIndex(local_index, active_uv_set))
                uv = _uv_value(uv_id)
            except Exception:
                continue
            records.append({"uv_id": uv_id, "uv": uv})
        return records

    def _face_matches(face_id):
        records = _face_uv_records(face_id)
        if not records:
            return False, []
        if clean_sample_mode == "center":
            center = [
                sum(record["uv"][0] for record in records) / float(len(records)),
                sum(record["uv"][1] for record in records) / float(len(records)),
            ]
            inside = _inside(center)
        elif clean_sample_mode == "any":
            inside = any(_inside(record["uv"]) for record in records)
        else:
            inside = all(_inside(record["uv"]) for record in records)
        return inside == bool(keep_inside), records

    def _selection_items():
        if clean_result_type == "uv":
            matched_uv_ids = []
            uv_records = []
            for uv_id in _candidate_uv_ids():
                uv = _uv_value(uv_id)
                matched = _inside(uv) == bool(keep_inside)
                if matched:
                    matched_uv_ids.append(uv_id)
                    uv_records.append({"component": _uv_component(uv_id), "index": uv_id, "uv": uv})
            return [_uv_component(uv_id) for uv_id in matched_uv_ids], uv_records, []

        matched_face_ids = []
        face_records = []
        for face_id in _candidate_face_ids():
            matched, uv_records = _face_matches(face_id)
            if not matched:
                continue
            matched_face_ids.append(face_id)
            center = None
            if uv_records:
                center = [
                    sum(record["uv"][0] for record in uv_records) / float(len(uv_records)),
                    sum(record["uv"][1] for record in uv_records) / float(len(uv_records)),
                ]
            face_records.append(
                {
                    "component": _face_component(face_id),
                    "index": face_id,
                    "uv_center": center,
                    "uv_count": len(uv_records),
                    "uvs": uv_records[:max_preview],
                }
            )
        face_components = [_face_component(face_id) for face_id in matched_face_ids]
        if clean_result_type == "face":
            return face_components, [], face_records
        converted = _convert(face_components, clean_result_type) if face_components else []
        return converted, [], face_records

    def _apply_selection(items):
        mode_name = selection_mode.lower().strip()
        if mode_name not in {"replace", "add", "toggle", "deselect"}:
            raise ValueError("selection_mode must be replace, add, toggle, or deselect.")
        if items:
            cmds.select(items, **{mode_name: True})
        elif mode_name == "replace":
            cmds.select(clear=True)

    if not object_name:
        raise ValueError("object_name is required.")
    clean_box = _validate_box(uv_box)
    clean_result_type = result_type.lower().strip()
    if clean_result_type not in {"uv", "face", "edge", "vertex"}:
        raise ValueError("result_type must be uv, face, edge, or vertex.")
    clean_sample_mode = sample_mode.lower().strip()
    if clean_sample_mode not in {"center", "any", "all"}:
        raise ValueError("sample_mode must be center, any, or all.")
    max_preview = _validate_int(max_preview, "max_preview", 1)

    shape_name = _mesh_shape(object_name)
    prefix_name = _prefix(shape_name)
    mesh_fn = _mesh_fn(shape_name)
    polygon_it = om.MItMeshPolygon(_dag_path(shape_name))

    all_uv_sets = cmds.polyUVSet(object_name, query=True, allUVSets=True) or []
    previous_uv_set = (cmds.polyUVSet(object_name, query=True, currentUVSet=True) or [None])[0]
    if uv_set:
        if uv_set not in all_uv_sets:
            raise ValueError(f"UV set {uv_set} does not exist on {object_name}.")
        cmds.polyUVSet(object_name, currentUVSet=True, uvSet=uv_set)
    active_uv_set = uv_set or previous_uv_set
    if not active_uv_set:
        raise ValueError(f"{object_name} has no active UV set.")

    try:
        matched_components, uv_records, face_records = _selection_items()
        if select_result:
            _apply_selection(matched_components)
        return {
            "success": True,
            "object_name": object_name,
            "shape_name": shape_name,
            "operation": "select_mesh_by_uv_region",
            "uv_set": active_uv_set,
            "uv_box": clean_box,
            "result_type": clean_result_type,
            "sample_mode": clean_sample_mode,
            "keep_inside": bool(keep_inside),
            "matched_count": len(matched_components),
            "components": matched_components[:max_preview],
            "truncated": len(matched_components) > max_preview,
            "selected": bool(select_result),
            "selection_mode": selection_mode if select_result else None,
            "uv_records": uv_records[:max_preview],
            "face_records": face_records[:max_preview],
            "records_truncated": len(uv_records) > max_preview or len(face_records) > max_preview,
        }
    finally:
        if uv_set and previous_uv_set and previous_uv_set in all_uv_sets and cmds.objExists(object_name):
            try:
                cmds.polyUVSet(object_name, currentUVSet=True, uvSet=previous_uv_set)
            except Exception:
                pass
