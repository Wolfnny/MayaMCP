

# set an objects attribute
# if the object is a transform for a shape, the attribute may for the shape

from typing import Dict, Any, List


def set_object_attribute(
    object_name: str,
    attribute_name: str,
    attribute_value: Any,
    disconnect_existing: bool = False,
) -> Dict[str, Any]:
    """Set an object's attribute with a specific value.

    When disconnect_existing is true, incoming connections to the target
    attribute are disconnected before setting the value. This is useful for
    intentionally overriding shader or utility-node driven attributes.
    """
    import maya.cmds as cmds

    def _validate_vector3d(vec:List[float]):
        return isinstance(vec, list) and len(vec) == 3 and all([isinstance(v, (int, float)) and not isinstance(v, bool) for v in vec])

    if not cmds.objExists(object_name):
        raise ValueError(f"Error: {object_name} doesn't exist in the scene")

    if not cmds.attributeQuery(attribute_name, node=object_name, exists=True):
        # if the attribute doesn't exist, may exist on the child shape
        exist_on_shape = False
        if cmds.objectType(object_name) == 'transform':
            shapes = cmds.listRelatives(object_name, shapes=True)
            if shapes and len(shapes) >= 1:
                if cmds.attributeQuery(attribute_name, node=shapes[0], exists=True):
                    exist_on_shape = True
                    object_name = shapes[0]
        if not exist_on_shape:
            raise ValueError(f"Error: attribute {attribute_name} doesn't exist on {object_name}")

    attr_type = cmds.getAttr(f'{object_name}.{attribute_name}', type=True)
     
    vector_types = {"double3", "float3"}
    if attr_type in vector_types:
        if not _validate_vector3d(attribute_value):
            raise ValueError(f"{attribute_name} is a 3d vector and needs to be a list of 3 numeric values.")
        attribute_value = [float(attribute_value[0]), float(attribute_value[1]), float(attribute_value[2])]

    def _disconnect_inputs(node, attr, attr_type_value):
        plugs = [f"{node}.{attr}"]
        if attr_type_value in vector_types:
            for child in cmds.attributeQuery(attr, node=node, listChildren=True) or []:
                plugs.append(f"{node}.{child}")
        disconnected = []
        for plug in plugs:
            for source in cmds.listConnections(plug, source=True, destination=False, plugs=True) or []:
                try:
                    cmds.disconnectAttr(source, plug)
                    disconnected.append({"source": source, "destination": plug})
                except Exception:
                    pass
        return disconnected

    disconnected_connections = []
    if disconnect_existing:
        disconnected_connections = _disconnect_inputs(object_name, attribute_name, attr_type)

    try:
        if attr_type in vector_types:
            cmds.setAttr(f'{object_name}.{attribute_name}', attribute_value[0], attribute_value[1], attribute_value[2], type=attr_type)
        elif attr_type == 'bool':
            cmds.setAttr(f'{object_name}.{attribute_name}', 1 if attribute_value else 0)
        elif attr_type == "string":
            cmds.setAttr(f'{object_name}.{attribute_name}', str(attribute_value), type="string")
        else:
            cmds.setAttr(f'{object_name}.{attribute_name}', attribute_value)
        results = {
            "success": True,
            "object_name": object_name,
            "attribute_name": attribute_name,
            "disconnect_existing": bool(disconnect_existing),
            "disconnected_connections": disconnected_connections,
        }
    except Exception as e:
        raise RuntimeError(f"Error: Unable to update attribute {attribute_name} on object {object_name}: {e}")

    return results
    
