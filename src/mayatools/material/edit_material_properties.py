from typing import Dict, List, Any, Union


def edit_material_properties(
    operation: str = "query",
    material_names: Union[str, List[str]] = None,
    object_names: Union[str, List[str]] = None,
    attributes: List[str] = None,
    parameters: Dict[str, Any] = None,
    disconnect_existing: bool = False,
    skip_missing: bool = True,
    include_connections: bool = True,
    max_preview: int = 100,
) -> Dict[str, Any]:
    """Query or set existing Maya material node attributes in batches.

    Materials can be provided directly with material_names or resolved from
    object_names through their shadingEngine assignments. This is a generic
    material-editing workflow for inspecting and adjusting shader properties,
    transparency, PBR controls, texture utility values, and other dependency
    graph material attributes without recreating the material network.
    """
    import maya.cmds as cmds

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return int(value)

    def _as_list(value, arg_name):
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{arg_name} must be a string, list of strings, or None.")
        return value

    def _unique(values):
        result = []
        seen = set()
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def _surface_materials(shading_group):
        materials = []
        for plug in ["surfaceShader", "aiSurfaceShader", "volumeShader", "displacementShader"]:
            if cmds.attributeQuery(plug, node=shading_group, exists=True):
                materials.extend(cmds.listConnections(f"{shading_group}.{plug}", source=True, destination=False) or [])
        return materials

    def _renderable_shapes(node):
        if cmds.objectType(node, isAType="shape"):
            return [node]
        return cmds.listRelatives(node, shapes=True, fullPath=False) or []

    def _materials_from_objects(objects):
        materials = []
        for obj in objects:
            if not cmds.objExists(obj):
                raise ValueError(f"Object does not exist: {obj}")
            for shape in _renderable_shapes(obj):
                try:
                    if cmds.attributeQuery("intermediateObject", node=shape, exists=True) and cmds.getAttr(f"{shape}.intermediateObject"):
                        continue
                except Exception:
                    pass
                for shading_group in cmds.listConnections(shape, type="shadingEngine") or []:
                    materials.extend(_surface_materials(shading_group))
        return materials

    def _resolve_materials():
        direct = _as_list(material_names, "material_names")
        objects = _as_list(object_names, "object_names")
        for material in direct:
            if not cmds.objExists(material):
                raise ValueError(f"Material node does not exist: {material}")
        resolved = direct + _materials_from_objects(objects)
        resolved = _unique(resolved)
        if not resolved:
            raise ValueError("No materials resolved from material_names or object_names.")
        return resolved

    def _default_attributes(node):
        common = [
            "color",
            "baseColor",
            "transparency",
            "opacity",
            "ambientColor",
            "incandescence",
            "diffuse",
            "specular",
            "specularColor",
            "specularRoughness",
            "roughness",
            "eccentricity",
            "reflectivity",
            "metalness",
            "transmission",
            "transmissionColor",
            "specularIOR",
            "ior",
            "coat",
            "coatRoughness",
            "thinWalled",
            "emission",
            "emissionColor",
        ]
        return [attr for attr in common if cmds.attributeQuery(attr, node=node, exists=True)]

    def _connections_for(node, attr):
        if not include_connections:
            return []
        raw = cmds.listConnections(
            f"{node}.{attr}",
            source=True,
            destination=True,
            plugs=True,
            connections=True,
        ) or []
        pairs = []
        for index in range(0, len(raw), 2):
            pairs.append(
                {
                    "plug": raw[index],
                    "connected_plug": raw[index + 1] if index + 1 < len(raw) else None,
                }
            )
        return pairs[:max_preview]

    def _attr_value(node, attr):
        value = cmds.getAttr(f"{node}.{attr}")
        if isinstance(value, list) and len(value) == 1:
            value = value[0]
        return value

    def _attr_record(node, attr):
        if not cmds.attributeQuery(attr, node=node, exists=True):
            return {"attribute": attr, "exists": False}
        record = {
            "attribute": attr,
            "exists": True,
            "type": cmds.getAttr(f"{node}.{attr}", type=True),
            "settable": bool(cmds.getAttr(f"{node}.{attr}", settable=True)),
            "locked": bool(cmds.getAttr(f"{node}.{attr}", lock=True)),
            "value": None,
            "connections": _connections_for(node, attr),
        }
        try:
            record["value"] = _attr_value(node, attr)
        except Exception as exc:
            record["value_error"] = str(exc)
        return record

    def _disconnect_inputs(node, attr):
        plugs = [f"{node}.{attr}"]
        if cmds.attributeQuery(attr, node=node, exists=True):
            children = cmds.attributeQuery(attr, node=node, listChildren=True) or []
            plugs.extend(f"{node}.{child}" for child in children)
        disconnected = []
        for plug in plugs:
            for source in cmds.listConnections(plug, source=True, destination=False, plugs=True) or []:
                try:
                    cmds.disconnectAttr(source, plug)
                    disconnected.append({"source": source, "destination": plug})
                except Exception:
                    pass
        return disconnected

    def _set_attr(node, attr, value):
        if not cmds.attributeQuery(attr, node=node, exists=True):
            if skip_missing:
                return {"attribute": attr, "skipped": True, "reason": "missing"}
            raise ValueError(f"Attribute {attr} does not exist on {node}.")
        before = _attr_record(node, attr)
        attr_type = before.get("type")
        disconnected = _disconnect_inputs(node, attr) if disconnect_existing else []
        plug = f"{node}.{attr}"
        try:
            if attr_type in {"double3", "float3"}:
                if not isinstance(value, list) or len(value) != 3 or not all(_is_number(item) for item in value):
                    raise ValueError(f"{attr} requires a list of three numeric values.")
                cmds.setAttr(plug, float(value[0]), float(value[1]), float(value[2]), type=attr_type)
            elif attr_type == "string":
                cmds.setAttr(plug, str(value), type="string")
            elif attr_type == "bool":
                cmds.setAttr(plug, bool(value))
            elif attr_type == "enum":
                if isinstance(value, str):
                    enums = (cmds.attributeQuery(attr, node=node, listEnum=True) or [""])[0].split(":")
                    if value not in enums:
                        raise ValueError(f"{attr} enum value must be one of {enums}.")
                    cmds.setAttr(plug, enums.index(value))
                else:
                    cmds.setAttr(plug, int(value))
            elif _is_number(value):
                cmds.setAttr(plug, float(value))
            elif isinstance(value, list) and len(value) == 3 and all(_is_number(item) for item in value):
                cmds.setAttr(plug, float(value[0]), float(value[1]), float(value[2]))
            else:
                cmds.setAttr(plug, value)
        except Exception as exc:
            raise RuntimeError(f"Unable to set {plug}: {exc}")
        after = _attr_record(node, attr)
        return {
            "attribute": attr,
            "skipped": False,
            "before": before,
            "after": after,
            "disconnected_connections": disconnected,
        }

    clean_operation = (operation or "").lower().strip()
    if clean_operation not in {"query", "set"}:
        raise ValueError("operation must be query or set.")
    max_preview = _validate_int(max_preview, "max_preview", 1)
    parameters = parameters or {}
    if attributes is not None and (not isinstance(attributes, list) or not all(isinstance(item, str) for item in attributes)):
        raise ValueError("attributes must be a list of strings or None.")

    materials = _resolve_materials()
    material_results = []
    for material in materials:
        attrs_to_query = attributes if attributes is not None else _default_attributes(material)
        if clean_operation == "query":
            material_results.append(
                {
                    "material": material,
                    "node_type": cmds.objectType(material),
                    "attributes": [_attr_record(material, attr) for attr in attrs_to_query],
                }
            )
            continue
        set_results = []
        for attr, value in parameters.items():
            set_results.append(_set_attr(material, attr, value))
        query_after = attributes if attributes is not None else list(dict.fromkeys(list(parameters) + _default_attributes(material)))
        material_results.append(
            {
                "material": material,
                "node_type": cmds.objectType(material),
                "set_results": set_results,
                "attributes_after": [_attr_record(material, attr) for attr in query_after],
            }
        )

    return {
        "success": True,
        "operation": clean_operation,
        "materials": materials,
        "material_count": len(materials),
        "disconnect_existing": bool(disconnect_existing),
        "skip_missing": bool(skip_missing),
        "include_connections": bool(include_connections),
        "results": material_results,
    }
