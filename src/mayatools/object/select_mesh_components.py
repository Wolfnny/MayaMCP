from typing import Dict, List, Any, Union


def select_mesh_components(
    object_name: str,
    operation: str = "query",
    component_type: str = None,
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    target_type: str = None,
    path_indices: List[int] = None,
    selection_mode: str = "replace",
    select_result: bool = True,
    use_selection: bool = True,
    options: Dict[str, Any] = None,
    max_components: int = 1000,
) -> Dict[str, Any]:
    """Resolve, convert, and select Maya polygon components.

    Operations:
    - query: report explicit, indexed, or currently selected components
    - select: select resolved components with replace/add/toggle/deselect mode
    - convert: convert components to vertex, edge, face, uv, or vertex_face
    - edge_loop, edge_ring, edge_border, edge_loop_or_border: select from seed edges
    - edge_loop_path, edge_ring_path: select a loop/ring path between two seed edges
    - extend_to_shell: select the connected polygon shell from seed faces
    - uv_shell: select the full UV shell from seed components
    - boundary: convert to border edges around the resolved component region

    This is a component selection/navigation tool for Maya-style polygon
    modeling. Use it to reliably target edge loops, rings, face shells, UV
    shells, or converted component sets before localized edits.
    """
    import re
    import maya.cmds as cmds

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

    def _components_from_indices(kind):
        if indices is None:
            return []
        if not isinstance(indices, list) or not all(isinstance(index, int) and not isinstance(index, bool) for index in indices):
            raise ValueError("indices must be a list of integers.")
        return [f"{prefix_name}.{kind}[{index}]" for index in indices]

    def _resolve_components(default_type=None):
        clean_type = (component_type or default_type or "").lower().strip()
        kind_map = {
            "vertex": "vtx",
            "edge": "e",
            "face": "f",
            "uv": "map",
            "vertex_face": "vtxFace",
        }
        if components is not None:
            resolved = _flatten(components)
        elif clean_type in kind_map and indices is not None:
            resolved = _components_from_indices(kind_map[clean_type])
        else:
            resolved = _selected_components()
        if not resolved:
            raise ValueError("No components resolved from components, indices, or current selection.")
        return _unique(resolved)

    def _component_ids(items, kind):
        pattern = re.compile(rf"\.{kind}\[(\d+)\]$")
        ids = []
        for item in cmds.ls(items, flatten=True) or []:
            match = pattern.search(item)
            if match:
                ids.append(int(match.group(1)))
        return list(dict.fromkeys(ids))

    def _edge_ids():
        resolved = _resolve_components("edge")
        edges = cmds.polyListComponentConversion(resolved, toEdge=True) or []
        edge_ids = _component_ids(edges, "e")
        if not edge_ids:
            raise ValueError("Operation requires edge components.")
        return edge_ids

    def _face_ids():
        resolved = _resolve_components("face")
        faces = cmds.polyListComponentConversion(resolved, toFace=True) or []
        face_ids = _component_ids(faces, "f")
        if not face_ids:
            raise ValueError("Operation requires face components.")
        return face_ids

    def _poly_select(flag_name, seed_ids, result_kind):
        results = []
        for seed_id in seed_ids:
            output = cmds.polySelect(
                object_name,
                asSelectString=True,
                noSelection=True,
                **{flag_name: int(seed_id)},
            ) or []
            for item in output:
                if isinstance(item, int):
                    results.append(f"{prefix_name}.{result_kind}[{item}]")
                else:
                    results.extend(_flatten(item))
        return _unique(results)

    def _poly_select_path(flag_name, seed_ids, result_kind):
        if len(seed_ids) != 2:
            raise ValueError(f"{flag_name} requires exactly two seed component indices.")
        output = cmds.polySelect(
            object_name,
            asSelectString=True,
            noSelection=True,
            **{flag_name: [int(seed_ids[0]), int(seed_ids[1])]},
        ) or []
        results = []
        for item in output:
            if isinstance(item, int):
                results.append(f"{prefix_name}.{result_kind}[{item}]")
            else:
                results.extend(_flatten(item))
        return _unique(results)

    def _convert(items, clean_target, convert_options):
        target_flags = {
            "vertex": {"toVertex": True},
            "edge": {"toEdge": True},
            "face": {"toFace": True},
            "uv": {"toUV": True},
            "vertex_face": {"toVertexFace": True},
        }
        if clean_target not in target_flags:
            raise ValueError("target_type must be vertex, edge, face, uv, or vertex_face.")
        kwargs = dict(target_flags[clean_target])
        if convert_options.get("border"):
            kwargs["border"] = True
        if convert_options.get("internal"):
            kwargs["internal"] = True
        if convert_options.get("uv_shell"):
            kwargs["uvShell"] = True
        if convert_options.get("vertex_face_all_edges"):
            kwargs["vertexFaceAllEdges"] = True
        converted = cmds.polyListComponentConversion(items, **kwargs) or []
        return _unique(converted)

    def _apply_selection(items):
        mode = selection_mode.lower().strip()
        if mode not in {"replace", "add", "toggle", "deselect"}:
            raise ValueError("selection_mode must be replace, add, toggle, or deselect.")
        kwargs = {mode: True}
        cmds.select(items, **kwargs)

    def _result(clean_operation, items, selected=False):
        truncated = len(items) > max_components
        preview = items[:max_components]
        return {
            "success": True,
            "object_name": object_name,
            "operation": clean_operation,
            "component_count": len(items),
            "components": preview,
            "truncated": truncated,
            "selected": bool(selected),
            "selection_mode": selection_mode if selected else None,
        }

    if not object_name:
        raise ValueError("object_name is required.")
    operation = operation.lower().strip()
    options = options or {}
    max_components = _validate_int(max_components, "max_components", 1)
    shape_name = _mesh_shape(object_name)
    prefix_name = _prefix(shape_name)

    if operation == "query":
        resolved = _resolve_components()
        return _result(operation, resolved, selected=False)

    if operation == "select":
        resolved = _resolve_components()
        _apply_selection(resolved)
        return _result(operation, resolved, selected=True)

    if operation == "convert":
        resolved = _resolve_components()
        converted = _convert(resolved, (target_type or "").lower().strip(), options)
        if select_result:
            _apply_selection(converted)
        return _result(operation, converted, selected=select_result)

    if operation == "boundary":
        resolved = _resolve_components()
        boundary_edges = _convert(resolved, "edge", {"border": True})
        if select_result:
            _apply_selection(boundary_edges)
        return _result(operation, boundary_edges, selected=select_result)

    if operation in {"edge_loop", "edge_ring", "edge_border", "edge_loop_or_border"}:
        flag_map = {
            "edge_loop": "edgeLoop",
            "edge_ring": "edgeRing",
            "edge_border": "edgeBorder",
            "edge_loop_or_border": "edgeLoopOrBorder",
        }
        selected = _poly_select(flag_map[operation], _edge_ids(), "e")
        if select_result:
            _apply_selection(selected)
        return _result(operation, selected, selected=select_result)

    if operation in {"edge_loop_path", "edge_ring_path"}:
        clean_path = path_indices if path_indices is not None else _edge_ids()[:2]
        if not isinstance(clean_path, list) or not all(isinstance(index, int) and not isinstance(index, bool) for index in clean_path):
            raise ValueError("path_indices must be a list of two edge indices.")
        flag_name = "edgeLoopPath" if operation == "edge_loop_path" else "edgeRingPath"
        selected = _poly_select_path(flag_name, clean_path, "e")
        if select_result:
            _apply_selection(selected)
        return _result(operation, selected, selected=select_result)

    if operation == "extend_to_shell":
        selected = _poly_select("extendToShell", _face_ids(), "f")
        if select_result:
            _apply_selection(selected)
        return _result(operation, selected, selected=select_result)

    if operation == "uv_shell":
        resolved = _resolve_components()
        uv_items = _convert(resolved, "uv", {"uv_shell": True})
        if select_result:
            _apply_selection(uv_items)
        return _result(operation, uv_items, selected=select_result)

    raise ValueError(
        "Unknown operation. Use query, select, convert, edge_loop, edge_ring, "
        "edge_border, edge_loop_or_border, edge_loop_path, edge_ring_path, "
        "extend_to_shell, uv_shell, or boundary."
    )
