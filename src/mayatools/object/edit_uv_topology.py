from typing import Dict, List, Any, Union


def edit_uv_topology(
    object_name: str,
    operation: str,
    component_type: str = None,
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    uv_set: str = None,
    parameters: Dict[str, Any] = None,
    use_selection: bool = True,
    max_preview: int = 50,
) -> Dict[str, Any]:
    """Edit UV seams, shells, unfolding, and layout at component level.

    Operations:
    - cut_edges: cut UV shells along selected mesh edges
    - sew_edges: sew selected UV border edges without moving shells
    - sew_move_edges: sew selected UV border edges and move shells together
    - unitize_faces: map selected faces to 0..1 UV squares
    - unfold: unfold selected UVs or UV shells
    - layout: lay out selected UV shells
    - normalize: normalize selected UVs or UV shells into tile space

    Components can be explicit component strings, built from component_type and
    indices, or taken from the current selection. This is for UV-editor style
    work on localized seams, labels, decals, and texture islands.
    """
    import maya.cmds as cmds

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

    def _resolve_components(default_type=None, allow_all=False):
        scope = str(parameters.get("scope", "components")).lower().strip()
        clean_type = (component_type or default_type or "").lower().strip()
        kind_map = {"vertex": "vtx", "edge": "e", "face": "f", "uv": "map", "vertex_face": "vtxFace"}
        if allow_all and scope == "all":
            return [object_name]
        if components is not None:
            resolved = _flatten(components)
        elif clean_type in kind_map and indices is not None:
            resolved = _components_from_indices(kind_map[clean_type])
        else:
            resolved = _selected_components()
        if not resolved:
            raise ValueError("No components resolved from components, indices, current selection, or parameters.scope='all'.")
        return resolved

    def _convert(items, target):
        flags = {
            "vertex": {"toVertex": True},
            "edge": {"toEdge": True},
            "face": {"toFace": True},
            "uv": {"toUV": True},
        }[target]
        converted = cmds.polyListComponentConversion(items, **flags) or []
        return cmds.ls(converted, flatten=True) or []

    def _uv_components_for_signature():
        return cmds.ls(f"{prefix_name}.map[*]", flatten=True) or []

    def _uv_values(items):
        values = cmds.polyEditUV(items, query=True) or []
        coords = []
        for index in range(0, len(values), 2):
            if index + 1 < len(values):
                coords.append((round(float(values[index]), 6), round(float(values[index + 1]), 6)))
        return coords

    def _uv_range(coords):
        if not coords:
            return None
        us = [coord[0] for coord in coords]
        vs = [coord[1] for coord in coords]
        return {
            "min_u": min(us),
            "max_u": max(us),
            "min_v": min(vs),
            "max_v": max(vs),
        }

    def _uv_shell_count():
        kwargs = {"uvShell": True}
        if active_uv_set:
            kwargs["uvSetName"] = active_uv_set
        return int(cmds.polyEvaluate(object_name, **kwargs))

    def _uv_signature():
        uv_items = _uv_components_for_signature()
        coords = _uv_values(uv_items)
        return {
            "uv_count": int(cmds.polyEvaluate(object_name, uvcoord=True)),
            "uv_shell_count": _uv_shell_count(),
            "uv_range": _uv_range(coords),
            "coords": coords,
            "coord_checksum": round(sum((index + 1) * (coord[0] * 1.37 + coord[1] * 2.11) for index, coord in enumerate(coords)), 6),
        }

    def _public_signature(signature):
        return {
            "uv_count": signature["uv_count"],
            "uv_shell_count": signature["uv_shell_count"],
            "uv_range": signature["uv_range"],
            "coord_checksum": signature["coord_checksum"],
        }

    def _changed(before, after):
        return (
            before["uv_count"] != after["uv_count"]
            or before["uv_shell_count"] != after["uv_shell_count"]
            or before["coords"] != after["coords"]
        )

    def _result(node_result, resolved, before, extra=None):
        after = _uv_signature()
        changed = _changed(before, after)
        require_change = bool(parameters.get("require_change", True))
        if require_change and not changed:
            raise RuntimeError(f"{operation} did not change UV topology or coordinates.")
        current_selection = cmds.ls(selection=True, flatten=True) or []
        payload = {
            "success": True,
            "object_name": object_name,
            "operation": operation,
            "uv_set": active_uv_set,
            "node": node_result,
            "changed": changed,
            "input_component_count": len(resolved),
            "input_components_preview": resolved[:max_preview],
            "selected_after_count": len(current_selection),
            "selected_after_preview": current_selection[:max_preview],
            "uv_before": _public_signature(before),
            "uv_after": _public_signature(after),
        }
        if extra:
            payload.update(extra)
        return payload

    if not object_name:
        raise ValueError("object_name is required.")
    if not operation:
        raise ValueError("operation is required.")
    operation = operation.lower().strip()
    allowed = {
        "cut_edges",
        "sew_edges",
        "sew_move_edges",
        "unitize_faces",
        "unfold",
        "layout",
        "normalize",
    }
    if operation not in allowed:
        raise ValueError(f"operation must be one of: {', '.join(sorted(allowed))}.")

    parameters = parameters or {}
    max_preview = _validate_int(max_preview, "max_preview", 1)
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
        before_signature = _uv_signature()
        construction_history = bool(parameters.get("construction_history", False))

        if operation == "cut_edges":
            edges = _convert(_resolve_components("edge"), "edge")
            if not edges:
                raise ValueError("cut_edges requires edge components.")
            move_ratio = _validate_scalar(parameters.get("move_ratio", 0.0), "move_ratio")
            node = cmds.polyMapCut(
                edges,
                constructionHistory=construction_history,
                moveRatio=move_ratio,
                usePinning=bool(parameters.get("use_pinning", False)),
            )
            return _result(node, edges, before_signature, {"move_ratio": move_ratio})

        if operation == "sew_edges":
            edges = _convert(_resolve_components("edge"), "edge")
            if not edges:
                raise ValueError("sew_edges requires edge components.")
            node = cmds.polyMapSew(
                edges,
                constructionHistory=construction_history,
                usePinning=bool(parameters.get("use_pinning", False)),
            )
            return _result(node, edges, before_signature)

        if operation == "sew_move_edges":
            edges = _convert(_resolve_components("edge"), "edge")
            if not edges:
                raise ValueError("sew_move_edges requires edge components.")
            node = cmds.polyMapSewMove(
                edges,
                constructionHistory=construction_history,
                limitPieceSize=bool(parameters.get("limit_piece_size", False)),
                numberFaces=_validate_int(parameters.get("number_faces", 10), "number_faces", 0),
                uvSetName=active_uv_set,
                worldSpace=bool(parameters.get("world_space", True)),
            )
            return _result(node, edges, before_signature)

        if operation == "unitize_faces":
            faces = _convert(_resolve_components("face"), "face")
            if not faces:
                raise ValueError("unitize_faces requires face components.")
            node = cmds.polyForceUV(faces, unitize=True, uvSetName=active_uv_set)
            return _result(node, faces, before_signature)

        if operation == "unfold":
            uv_items = _convert(_resolve_components("uv", allow_all=True), "uv")
            if not uv_items:
                raise ValueError("unfold requires UVs or components convertible to UVs.")
            node = cmds.unfold(
                uv_items,
                iterations=_validate_int(parameters.get("iterations", 10), "iterations", 1),
                applyToShell=bool(parameters.get("apply_to_shell", True)),
                areaWeight=_validate_scalar(parameters.get("area_weight", 0.0), "area_weight"),
                globalBlend=_validate_scalar(parameters.get("global_blend", 0.0), "global_blend"),
                globalMethodBlend=_validate_scalar(parameters.get("global_method_blend", 0.5), "global_method_blend"),
                optimizeAxis=_validate_int(parameters.get("optimize_axis", 0), "optimize_axis", 0),
                pinSelected=bool(parameters.get("pin_selected", False)),
                pinUvBorder=bool(parameters.get("pin_uv_border", False)),
                scale=_validate_scalar(parameters.get("scale", 1.0), "scale"),
                stoppingThreshold=_validate_scalar(parameters.get("stopping_threshold", 0.001), "stopping_threshold"),
                useScale=bool(parameters.get("use_scale", False)),
            )
            return _result(node, uv_items, before_signature)

        if operation == "layout":
            uv_items = _convert(_resolve_components("uv", allow_all=True), "uv")
            if not uv_items:
                raise ValueError("layout requires UVs or components convertible to UVs.")
            node = cmds.polyLayoutUV(
                uv_items,
                layout=_validate_int(parameters.get("layout", 2), "layout", 0),
                layoutMethod=_validate_int(parameters.get("layout_method", 1), "layout_method", 0),
                percentageSpace=_validate_scalar(parameters.get("percentage_space", 2.0), "percentage_space"),
                rotateForBestFit=_validate_int(parameters.get("rotate_for_best_fit", 2), "rotate_for_best_fit", 0),
                scale=_validate_int(parameters.get("scale_mode", parameters.get("scale", 1)), "scale", 0),
                separate=_validate_int(parameters.get("separate", 0), "separate", 0),
                flipReversed=bool(parameters.get("flip_reversed", False)),
                gridU=_validate_int(parameters.get("grid_u", 1), "grid_u", 1),
                gridV=_validate_int(parameters.get("grid_v", 1), "grid_v", 1),
                uvSetName=active_uv_set,
                worldSpace=bool(parameters.get("world_space", True)),
                constructionHistory=construction_history,
            )
            return _result(node, uv_items, before_signature)

        if operation == "normalize":
            uv_items = _convert(_resolve_components("uv", allow_all=True), "uv")
            if not uv_items:
                raise ValueError("normalize requires UVs or components convertible to UVs.")
            node = cmds.polyNormalizeUV(
                uv_items,
                normalizeType=_validate_int(parameters.get("normalize_type", 0), "normalize_type", 0),
                normalizeDirection=_validate_int(parameters.get("normalize_direction", 0), "normalize_direction", 0),
                preserveAspectRatio=bool(parameters.get("preserve_aspect_ratio", True)),
                centerOnTile=bool(parameters.get("center_on_tile", False)),
                uvSetName=active_uv_set,
                worldSpace=bool(parameters.get("world_space", True)),
                constructionHistory=construction_history,
            )
            return _result(node, uv_items, before_signature)

        raise ValueError(f"Unsupported operation: {operation}")
    finally:
        if uv_set and previous_uv_set and previous_uv_set in all_uv_sets and cmds.objExists(object_name):
            try:
                cmds.polyUVSet(object_name, currentUVSet=True, uvSet=previous_uv_set)
            except Exception:
                pass
