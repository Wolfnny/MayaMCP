from typing import Dict, List, Any, Union


def edit_material_assignments(
    object_name: str,
    operation: str = "query",
    material_name: str = None,
    shading_group_name: str = None,
    material_type: str = "lambert",
    material_color: List[float] = None,
    material_parameters: Dict[str, Any] = None,
    component_type: str = None,
    indices: List[int] = None,
    components: Union[str, List[str]] = None,
    assign_scope: str = "components",
    create_if_missing: bool = True,
    use_selection: bool = True,
    select_result: bool = False,
    include_components: bool = True,
    max_preview: int = 50,
) -> Dict[str, Any]:
    """Query, assign, and select material assignments on objects or mesh faces.

    Operations:
    - query: report shadingEngine and material assignments for an object
    - assign: assign a material or shading group to an object or resolved faces
    - select_by_material: select members of a material assignment on the object

    This is the explicit Maya-style material assignment workflow: select faces,
    assign them to a shading group, and inspect or reselect those assignments.
    It complements region-based tools without encoding any product-specific
    selection logic.
    """
    import maya.cmds as cmds

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return int(value)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(item) for item in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(item) for item in values]

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
        result = []
        seen = set()
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

    def _resolve_components():
        scope = str(assign_scope or "components").lower().strip()
        if scope == "all":
            return [object_name]
        if scope != "components":
            raise ValueError("assign_scope must be components or all.")
        clean_type = (component_type or "face").lower().strip()
        kind_map = {"vertex": "vtx", "edge": "e", "face": "f", "uv": "map", "vertex_face": "vtxFace"}
        if components is not None:
            resolved = _flatten(components)
        elif clean_type in kind_map and indices is not None:
            resolved = _components_from_indices(kind_map[clean_type])
        else:
            resolved = _selected_components()
        if not resolved:
            raise ValueError("No components resolved from components, indices, or current selection.")
        faces = cmds.polyListComponentConversion(resolved, toFace=True) or []
        faces = _unique(faces)
        if not faces:
            raise ValueError("Material component assignment requires faces or components convertible to faces.")
        return faces

    def _surface_materials(shading_group):
        materials = []
        for plug in ["surfaceShader", "aiSurfaceShader"]:
            if cmds.attributeQuery(plug, node=shading_group, exists=True):
                materials.extend(cmds.listConnections(f"{shading_group}.{plug}", source=True, destination=False) or [])
        return list(dict.fromkeys(materials))

    def _filtered_members(shading_group):
        if not include_components:
            return []
        members = cmds.sets(shading_group, query=True) or []
        prefixes = [object_name, shape_name, prefix_name]
        filtered = []
        for member in members:
            flattened = cmds.ls(member, flatten=True) or [member]
            for item in flattened:
                clean_item = item.split("|")[-1]
                if any(clean_item == prefix or clean_item.startswith(f"{prefix}.") for prefix in prefixes if prefix):
                    filtered.append(clean_item)
        return list(dict.fromkeys(filtered))

    def _assignment_summary():
        shading_groups = list(dict.fromkeys(cmds.listConnections(shape_name, type="shadingEngine") or []))
        assignments = []
        for shading_group in shading_groups:
            members = _filtered_members(shading_group)
            assignments.append({
                "shading_group": shading_group,
                "materials": _surface_materials(shading_group),
                "member_count": len(members),
                "members_preview": members[:max_preview],
            })
        return assignments

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

    def _create_material(shader_name, sg_name=None):
        shader_type = str(material_type or "lambert").strip()
        clean_type = shader_type.lower()
        type_map = {
            "lambert": "lambert",
            "phong": "phong",
            "blinn": "blinn",
            "surface_shader": "surfaceShader",
            "surfaceshader": "surfaceShader",
            "ai_standard_surface": "aiStandardSurface",
            "aistandardsurface": "aiStandardSurface",
        }
        if clean_type not in type_map:
            raise ValueError("material_type must be lambert, phong, blinn, surface_shader, or ai_standard_surface.")
        node_type = type_map[clean_type]
        shader = cmds.shadingNode(node_type, asShader=True, name=shader_name)
        color = _validate_vector(material_color if material_color is not None else [0.5, 0.5, 0.5], 3, "material_color")
        if not _set_attr_if_exists(shader, "color", color):
            _set_attr_if_exists(shader, "baseColor", color)
        if node_type == "aiStandardSurface":
            _set_attr_if_exists(shader, "base", 1.0)
        for attr, value in (material_parameters or {}).items():
            _set_attr_if_exists(shader, attr, value)
        shading_group = cmds.sets(name=sg_name or f"{shader}SG", empty=True, renderable=True, noSurfaceShader=True)
        output_attr = "outColor" if cmds.attributeQuery("outColor", node=shader, exists=True) else "outValue"
        cmds.connectAttr(f"{shader}.{output_attr}", f"{shading_group}.surfaceShader", force=True)
        return shader, shading_group, True

    def _material_to_shading_group(shader):
        groups = cmds.listConnections(shader, type="shadingEngine") or []
        if groups:
            return groups[0], False
        shading_group = cmds.sets(name=f"{shader}SG", empty=True, renderable=True, noSurfaceShader=True)
        output_attr = "outColor" if cmds.attributeQuery("outColor", node=shader, exists=True) else "outValue"
        cmds.connectAttr(f"{shader}.{output_attr}", f"{shading_group}.surfaceShader", force=True)
        return shading_group, True

    def _resolve_shading_group():
        if shading_group_name:
            if cmds.objExists(shading_group_name):
                if cmds.objectType(shading_group_name) != "shadingEngine":
                    raise ValueError(f"{shading_group_name} is not a shadingEngine.")
                return None, shading_group_name, False
            if not create_if_missing:
                raise ValueError(f"Shading group does not exist: {shading_group_name}")
            shader_name = material_name or f"{shading_group_name}_mat"
            return _create_material(shader_name, shading_group_name)
        if material_name:
            if cmds.objExists(material_name):
                shading_group, created_group = _material_to_shading_group(material_name)
                return material_name, shading_group, created_group
            if not create_if_missing:
                raise ValueError(f"Material does not exist: {material_name}")
            return _create_material(material_name)
        if not create_if_missing:
            raise ValueError("material_name or shading_group_name is required when create_if_missing is false.")
        return _create_material(f"{prefix_name}_mat")

    if not object_name:
        raise ValueError("object_name is required.")
    if not operation:
        raise ValueError("operation is required.")
    operation = operation.lower().strip()
    if operation not in {"query", "assign", "select_by_material"}:
        raise ValueError("operation must be query, assign, or select_by_material.")
    max_preview = _validate_int(max_preview, "max_preview", 1)
    material_parameters = material_parameters or {}
    shape_name = _mesh_shape(object_name)
    prefix_name = _prefix(shape_name)

    if operation == "query":
        return {
            "success": True,
            "object_name": object_name,
            "shape_name": shape_name,
            "operation": operation,
            "assignments": _assignment_summary(),
        }

    material, shading_group, created = _resolve_shading_group()

    if operation == "select_by_material":
        members = _filtered_members(shading_group)
        if not members:
            raise RuntimeError(f"No members from {shading_group} found on {object_name}.")
        cmds.select(members, replace=True)
        return {
            "success": True,
            "object_name": object_name,
            "shape_name": shape_name,
            "operation": operation,
            "material": material,
            "shading_group": shading_group,
            "selected_count": len(members),
            "selected_preview": members[:max_preview],
        }

    before = _assignment_summary()
    targets = _resolve_components()
    cmds.sets(targets, edit=True, forceElement=shading_group)
    if select_result:
        cmds.select(targets, replace=True)
    after = _assignment_summary()
    return {
        "success": True,
        "object_name": object_name,
        "shape_name": shape_name,
        "operation": operation,
        "assign_scope": assign_scope,
        "material": material,
        "shading_group": shading_group,
        "created_material_or_group": bool(created),
        "assigned_count": len(targets),
        "assigned_preview": targets[:max_preview],
        "selected": bool(select_result),
        "assignments_before": before,
        "assignments_after": after,
    }
