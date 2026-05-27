from typing import Dict, List, Any


def uv_operations(
    object_name: str,
    operation: str,
    parameters: Dict[str, Any] = None,
    uv_set: str = None,
) -> Dict[str, Any]:
    """Manage and generate UVs for polygon meshes.

    Operations:
    - list: report UV sets, current UV set, UV count, and UV range
    - create_uv_set: create a UV set named uv_set
    - set_current_uv_set: set uv_set as current
    - delete_uv_set: delete uv_set
    - planar: run a planar projection
    - cylindrical: run a cylindrical projection
    - spherical: run a spherical projection
    - automatic: run Maya automatic projection
    - normalize: normalize UVs into tile space
    - layout: lay out UV shells
    """
    import maya.cmds as cmds

    if not cmds.objExists(object_name):
        raise ValueError(f"Object does not exist: {object_name}")

    shapes = cmds.listRelatives(object_name, shapes=True, fullPath=True) or []
    if cmds.objectType(object_name) == "mesh":
        shapes = [object_name]
    if not any(cmds.objectType(shape) == "mesh" for shape in shapes):
        raise ValueError(f"{object_name} is not a polygon mesh transform or mesh shape.")

    if parameters is None:
        parameters = {}

    operation = operation.lower()

    def _all_faces():
        return f"{object_name}.f[*]"

    def _uv_range():
        uv_components = cmds.ls(f"{object_name}.map[*]", flatten=True) or []
        if not uv_components:
            return None
        values = cmds.polyEditUV(uv_components, query=True) or []
        if not values:
            return None
        us = values[0::2]
        vs = values[1::2]
        return {
            "min_u": min(us),
            "max_u": max(us),
            "min_v": min(vs),
            "max_v": max(vs),
        }

    def _list_info():
        all_sets = cmds.polyUVSet(object_name, query=True, allUVSets=True) or []
        current = cmds.polyUVSet(object_name, query=True, currentUVSet=True) or []
        return {
            "success": True,
            "object_name": object_name,
            "uv_sets": all_sets,
            "current_uv_set": current[0] if current else None,
            "uv_count": cmds.polyEvaluate(object_name, uvcoord=True),
            "uv_range": _uv_range(),
        }

    if operation == "list":
        return _list_info()

    if operation == "create_uv_set":
        if not uv_set:
            raise ValueError("uv_set is required for create_uv_set.")
        existing = cmds.polyUVSet(object_name, query=True, allUVSets=True) or []
        if uv_set not in existing:
            cmds.polyUVSet(object_name, create=True, uvSet=uv_set)
        cmds.polyUVSet(object_name, currentUVSet=True, uvSet=uv_set)
        return _list_info()

    if operation == "set_current_uv_set":
        if not uv_set:
            raise ValueError("uv_set is required for set_current_uv_set.")
        existing = cmds.polyUVSet(object_name, query=True, allUVSets=True) or []
        if uv_set not in existing:
            raise ValueError(f"UV set {uv_set} does not exist on {object_name}.")
        cmds.polyUVSet(object_name, currentUVSet=True, uvSet=uv_set)
        return _list_info()

    if operation == "delete_uv_set":
        if not uv_set:
            raise ValueError("uv_set is required for delete_uv_set.")
        current = cmds.polyUVSet(object_name, query=True, currentUVSet=True) or []
        if current and current[0] == uv_set:
            raise ValueError("Cannot delete the current UV set. Switch to another UV set first.")
        cmds.polyUVSet(object_name, delete=True, uvSet=uv_set)
        return _list_info()

    create_new_map = bool(parameters.get("create_new_map", False))
    construction_history = bool(parameters.get("construction_history", True))
    world_space = bool(parameters.get("world_space", True))

    def _with_create_new_map(kwargs):
        if create_new_map:
            kwargs["createNewMap"] = True
        return kwargs

    if operation == "planar":
        result = cmds.polyPlanarProjection(
            _all_faces(),
            **_with_create_new_map({
                "mapDirection": parameters.get("map_direction", "y"),
                "projectionWidth": parameters.get("projection_width", 1.0),
                "projectionHeight": parameters.get("projection_height", 1.0),
                "imageCenter": parameters.get("image_center", [0.5, 0.5]),
                "imageScale": parameters.get("image_scale", [1.0, 1.0]),
                "rotate": parameters.get("rotate", [0.0, 0.0, 0.0]),
                "constructionHistory": construction_history,
                "worldSpace": world_space,
            }),
        )
        info = _list_info()
        info.update({"operation": operation, "projection_node": result})
        return info

    if operation == "cylindrical":
        result = cmds.polyCylindricalProjection(
            _all_faces(),
            **_with_create_new_map({
                "mapDirection": parameters.get("map_direction", "y"),
                "projectionWidth": parameters.get("projection_width", 1.0),
                "projectionHeight": parameters.get("projection_height", 1.0),
                "imageCenter": parameters.get("image_center", [0.5, 0.5]),
                "imageScale": parameters.get("image_scale", [1.0, 1.0]),
                "rotate": parameters.get("rotate", [0.0, 0.0, 0.0]),
                "constructionHistory": construction_history,
                "worldSpace": world_space,
            }),
        )
        info = _list_info()
        info.update({"operation": operation, "projection_node": result})
        return info

    if operation == "spherical":
        result = cmds.polySphericalProjection(
            _all_faces(),
            **_with_create_new_map({
                "mapDirection": parameters.get("map_direction", "y"),
                "projectionWidth": parameters.get("projection_width", 1.0),
                "projectionHeight": parameters.get("projection_height", 1.0),
                "imageCenter": parameters.get("image_center", [0.5, 0.5]),
                "imageScale": parameters.get("image_scale", [1.0, 1.0]),
                "rotate": parameters.get("rotate", [0.0, 0.0, 0.0]),
                "constructionHistory": construction_history,
                "worldSpace": world_space,
            }),
        )
        info = _list_info()
        info.update({"operation": operation, "projection_node": result})
        return info

    if operation == "automatic":
        result = cmds.polyAutoProjection(
            _all_faces(),
            **_with_create_new_map({
                "planes": int(parameters.get("planes", 6)),
                "layout": int(parameters.get("layout", 2)),
                "layoutMethod": int(parameters.get("layout_method", 1)),
                "percentageSpace": float(parameters.get("percentage_space", 2.0)),
                "optimize": int(parameters.get("optimize", 1)),
                "constructionHistory": construction_history,
                "worldSpace": world_space,
            }),
        )
        info = _list_info()
        info.update({"operation": operation, "projection_node": result})
        return info

    if operation == "normalize":
        result = cmds.polyNormalizeUV(
            _all_faces(),
            normalizeType=int(parameters.get("normalize_type", 0)),
            preserveAspectRatio=bool(parameters.get("preserve_aspect_ratio", True)),
            centerOnTile=bool(parameters.get("center_on_tile", False)),
            constructionHistory=construction_history,
            worldSpace=world_space,
        )
        info = _list_info()
        info.update({"operation": operation, "node": result})
        return info

    if operation == "layout":
        result = cmds.polyLayoutUV(
            _all_faces(),
            layout=int(parameters.get("layout", 2)),
            layoutMethod=int(parameters.get("layout_method", 1)),
            percentageSpace=float(parameters.get("percentage_space", 2.0)),
            rotateForBestFit=int(parameters.get("rotate_for_best_fit", 2)),
            scale=int(parameters.get("scale", 1)),
            constructionHistory=construction_history,
            worldSpace=world_space,
        )
        info = _list_info()
        info.update({"operation": operation, "node": result})
        return info

    raise ValueError(
        "Unknown UV operation. Use list, create_uv_set, set_current_uv_set, delete_uv_set, "
        "planar, cylindrical, spherical, automatic, normalize, or layout."
    )
