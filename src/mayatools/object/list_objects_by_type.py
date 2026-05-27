from typing import List


def list_objects_by_type(
    filter_by: str = None,
    visible_only: bool = False,
    long_names: bool = False,
) -> List[str]:
    """List scene nodes by common Maya categories.

    Supported filters include objects/all, transforms, meshes, mesh_shapes,
    curves, curve_shapes, geometry, cameras, lights, materials, textures,
    file_textures, shading_groups, and shapes. The common mesh/curve filters
    return transform nodes so the results can be passed directly to modeling
    tools; use mesh_shapes or curve_shapes when shape nodes are required.
    """
    import maya.cmds as cmds

    def _unique(values):
        result = []
        seen = set()
        for value in values or []:
            if value not in seen:
                seen.add(value)
                result.append(value)
        return result

    def _is_visible(node):
        current = node
        while current:
            try:
                if cmds.attributeQuery("visibility", node=current, exists=True) and not cmds.getAttr(f"{current}.visibility"):
                    return False
            except Exception:
                pass
            parents = cmds.listRelatives(current, parent=True, fullPath=True) or []
            current = parents[0] if parents else None
        return True

    def _shape_parents(shape_type):
        parents = []
        for shape in cmds.ls(type=shape_type, long=long_names) or []:
            try:
                if cmds.attributeQuery("intermediateObject", node=shape, exists=True) and cmds.getAttr(f"{shape}.intermediateObject"):
                    continue
            except Exception:
                pass
            parent = cmds.listRelatives(shape, parent=True, fullPath=long_names) or []
            if parent:
                parents.append(parent[0])
        return _unique(parents)

    key = "objects" if filter_by in (None, "", "null") else str(filter_by).lower().strip()
    key = key.replace("-", "_")

    if key in {"object", "objects", "all", "dag"}:
        nodes = cmds.ls(dag=True, long=long_names) or []
    elif key in {"transform", "transforms"}:
        nodes = cmds.ls(type="transform", long=long_names) or []
    elif key in {"mesh", "meshes"}:
        nodes = _shape_parents("mesh")
    elif key in {"mesh_shape", "mesh_shapes"}:
        nodes = cmds.ls(type="mesh", long=long_names) or []
    elif key in {"curve", "curves", "nurbs_curve", "nurbs_curves"}:
        nodes = _shape_parents("nurbsCurve") + _shape_parents("bezierCurve")
    elif key in {"curve_shape", "curve_shapes", "nurbs_curve_shape", "nurbs_curve_shapes"}:
        nodes = (cmds.ls(type="nurbsCurve", long=long_names) or []) + (cmds.ls(type="bezierCurve", long=long_names) or [])
    elif key == "geometry":
        nodes = _shape_parents("mesh") + _shape_parents("nurbsCurve") + _shape_parents("bezierCurve")
    elif key in {"camera", "cameras"}:
        nodes = cmds.ls(cameras=True, long=long_names) or []
    elif key in {"light", "lights"}:
        nodes = cmds.ls(lights=True, long=long_names) or []
    elif key in {"material", "materials"}:
        nodes = cmds.ls(materials=True) or []
    elif key in {"texture", "textures"}:
        nodes = cmds.ls(textures=True) or []
    elif key in {"file", "files", "file_texture", "file_textures"}:
        nodes = cmds.ls(type="file") or []
    elif key in {"shading_group", "shading_groups", "shading_engine", "shading_engines"}:
        nodes = cmds.ls(type="shadingEngine") or []
    elif key in {"shape", "shapes"}:
        nodes = cmds.ls(shapes=True, long=long_names) or []
    else:
        supported = [
            "objects",
            "transforms",
            "meshes",
            "mesh_shapes",
            "curves",
            "curve_shapes",
            "geometry",
            "cameras",
            "lights",
            "materials",
            "textures",
            "file_textures",
            "shading_groups",
            "shapes",
        ]
        raise ValueError(f"Unsupported filter_by value: {filter_by}. Supported values: {', '.join(supported)}.")

    nodes = _unique(nodes)
    if visible_only and key not in {"material", "materials", "texture", "textures", "file", "files", "file_texture", "file_textures", "shading_group", "shading_groups", "shading_engine", "shading_engines"}:
        nodes = [node for node in nodes if _is_visible(node)]
    return nodes
