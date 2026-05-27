
from typing import Dict, List, Any


def create_object(
    name:str, 
    object_type:str, 
    translate:List[float]=[0.0, 0.0, 0.0], 
    rotate:List[float]=[0.0, 0.0, 0.0],
    parameters:Dict[str, Any]=None,
    material_color:List[float]=None,
    material_name:str=None,
) -> Dict[str, Any]:
    """ Creates an object in the Maya scene. Object types available are
        cube, cone, sphere, cylinder, camera, spotLight, pointLight, directionalLight.
        Rotate values are in degrees. Optional primitive parameters can set
        dimensions such as radius, height, width, depth, and subdivisions. """
    import maya.cmds as cmds

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector3d(vec:List[float]):
        return isinstance(vec, list) and len(vec) == 3 and all([_is_number(v) for v in vec])

    def _number_param(key, default, minimum=None):
        value = parameters.get(key, default)
        if not _is_number(value):
            raise ValueError(f"parameters.{key} must be numeric.")
        value = float(value)
        if minimum is not None and value < minimum:
            raise ValueError(f"parameters.{key} must be greater than or equal to {minimum}.")
        return value

    def _int_param(key, default, minimum=None):
        value = parameters.get(key, default)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"parameters.{key} must be an integer.")
        if minimum is not None and value < minimum:
            raise ValueError(f"parameters.{key} must be greater than or equal to {minimum}.")
        return value

    def _assign_material(transform):
        if material_color is None:
            return None, None
        if not _validate_vector3d(material_color):
            raise ValueError("material_color must be a list of 3 numeric values.")
        shader = cmds.shadingNode("lambert", asShader=True, name=material_name or f"{name}_mat")
        cmds.setAttr(f"{shader}.color", float(material_color[0]), float(material_color[1]), float(material_color[2]), type="double3")
        shading_group = cmds.sets(name=f"{shader}SG", empty=True, renderable=True, noSurfaceShader=True)
        cmds.connectAttr(f"{shader}.outColor", f"{shading_group}.surfaceShader", force=True)
        cmds.sets(transform, edit=True, forceElement=shading_group)
        return shader, shading_group

    if parameters is None:
        parameters = {}
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be a dictionary.")

    if not _validate_vector3d(translate):
        raise ValueError("Invalid translate format. Must be a list of 3 float values.")
    if not _validate_vector3d(rotate):
        raise ValueError("Invalid rotate format. Must be a list of 3 float values.")

    if object_type == "cube":
        obj = cmds.polyCube(
            name=name,
            width=_number_param("width", 1.0, 0.0),
            height=_number_param("height", 1.0, 0.0),
            depth=_number_param("depth", 1.0, 0.0),
            subdivisionsX=_int_param("subdivisionsX", 1, 1),
            subdivisionsY=_int_param("subdivisionsY", 1, 1),
            subdivisionsZ=_int_param("subdivisionsZ", 1, 1),
            constructionHistory=False,
        )
    elif object_type == "cone":
        obj = cmds.polyCone(
            name=name,
            radius=_number_param("radius", 1.0, 0.0),
            height=_number_param("height", 2.0, 0.0),
            subdivisionsAxis=_int_param("subdivisionsAxis", 20, 3),
            subdivisionsHeight=_int_param("subdivisionsHeight", 1, 1),
            subdivisionsCaps=_int_param("subdivisionsCaps", 0, 0),
            constructionHistory=False,
        )
    elif object_type == "sphere":
        obj = cmds.polySphere(
            name=name,
            radius=_number_param("radius", 1.0, 0.0),
            subdivisionsX=_int_param("subdivisionsX", 20, 3),
            subdivisionsY=_int_param("subdivisionsY", 20, 3),
            constructionHistory=False,
        )
    elif object_type == "cylinder":
        obj = cmds.polyCylinder(
            name=name,
            radius=_number_param("radius", 1.0, 0.0),
            height=_number_param("height", 2.0, 0.0),
            subdivisionsAxis=_int_param("subdivisionsAxis", 20, 3),
            subdivisionsHeight=_int_param("subdivisionsHeight", 1, 1),
            subdivisionsCaps=_int_param("subdivisionsCaps", 1, 0),
            constructionHistory=False,
        )
    elif object_type == "camera":
        obj = cmds.camera(name=name)
    elif object_type == "spotLight":
        obj = cmds.spotLight(name=name)
    elif object_type == "pointLight":
        obj = cmds.pointLight(name=name)
    elif object_type == "directionalLight":
        obj = cmds.directionalLight(name=name)
    else:
        raise ValueError(f"Error: unknown {object_type}, use one of these types: cube, cone, sphere, cylinder, camera, spotLight, pointLight, directionalLight")

    raw_node = obj[0] if isinstance(obj, (list, tuple)) else obj
    if cmds.objExists(raw_node) and cmds.objectType(raw_node) != "transform":
        parents = cmds.listRelatives(raw_node, parent=True) or []
        transform = parents[0] if parents else raw_node
    else:
        transform = raw_node
    shapes = cmds.listRelatives(transform, shapes=True) or []
    shape = shapes[0] if shapes else (obj[1] if isinstance(obj, (list, tuple)) and len(obj) > 1 else None)

    cmds.setAttr(transform+".translate", translate[0], translate[1], translate[2], type="double3")
    cmds.setAttr(transform+".rotate", rotate[0], rotate[1], rotate[2], type="double3")
    material, shading_group = _assign_material(transform)

    return {
        "success": True,
        "name": transform,
        "shape": shape,
        "object_type": object_type,
        "translate": translate,
        "rotate": rotate,
        "parameters": parameters,
        "material": material,
        "shading_group": shading_group,
    }
        

