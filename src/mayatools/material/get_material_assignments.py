from typing import Dict, List, Any, Union


def get_material_assignments(
    object_names: Union[str, List[str]] = None,
    include_components: bool = False,
) -> Dict[str, Any]:
    """Report material and shading-group assignments for scene geometry.

    This is a generic inspection tool for debugging product assets, imported
    models, procedural meshes, and textured scenes. It resolves transform or
    shape inputs to renderable shapes, reports connected shadingEngine nodes,
    the surface materials driving them, and optionally lists set members so
    per-face assignments can be diagnosed.
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

    def _shape_parent_targets():
        targets = []
        seen = set()
        for shape_type in ["mesh", "nurbsSurface", "subdiv", "nurbsCurve", "bezierCurve"]:
            for shape in cmds.ls(type=shape_type, long=False) or []:
                try:
                    if cmds.attributeQuery("intermediateObject", node=shape, exists=True) and cmds.getAttr(f"{shape}.intermediateObject"):
                        continue
                except Exception:
                    pass
                parents = cmds.listRelatives(shape, parent=True, fullPath=False) or []
                target = parents[0] if parents else shape
                if target not in seen:
                    seen.add(target)
                    targets.append(target)
        return targets

    def _normalize_objects(values):
        if values is None:
            return _shape_parent_targets()
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError("object_names must be a string, a list of strings, or None.")
        for value in values:
            if not cmds.objExists(value):
                raise ValueError(f"Object does not exist: {value}")
        return values

    def _renderable_shapes(node):
        if cmds.objectType(node, isAType="shape"):
            shapes = [node]
        else:
            shapes = cmds.listRelatives(node, shapes=True, fullPath=False) or []
        result = []
        for shape in shapes:
            try:
                if cmds.attributeQuery("intermediateObject", node=shape, exists=True) and cmds.getAttr(f"{shape}.intermediateObject"):
                    continue
            except Exception:
                pass
            result.append(shape)
        return result

    def _surface_materials(shading_group):
        materials = []
        for plug in ["surfaceShader", "aiSurfaceShader"]:
            if cmds.attributeQuery(plug, node=shading_group, exists=True):
                materials.extend(cmds.listConnections(f"{shading_group}.{plug}", source=True, destination=False) or [])
        return _unique(materials)

    def _filtered_members(shading_group, object_name, shape_name):
        if not include_components:
            return []
        members = cmds.sets(shading_group, query=True) or []
        filtered = []
        prefixes = [object_name, shape_name]
        parents = cmds.listRelatives(shape_name, parent=True, fullPath=False) or []
        prefixes.extend(parents)
        for member in members:
            clean_member = member.split("|")[-1]
            if any(clean_member == prefix or clean_member.startswith(f"{prefix}.") for prefix in prefixes if prefix):
                filtered.append(member)
        return filtered

    if not isinstance(include_components, bool):
        raise ValueError("include_components must be a boolean.")

    objects = _normalize_objects(object_names)
    results = []
    all_shading_groups = []
    all_materials = []

    for obj in objects:
        shape_results = []
        for shape in _renderable_shapes(obj):
            shading_groups = _unique(cmds.listConnections(shape, type="shadingEngine") or [])
            assignments = []
            for shading_group in shading_groups:
                materials = _surface_materials(shading_group)
                all_shading_groups.append(shading_group)
                all_materials.extend(materials)
                assignments.append({
                    "shading_group": shading_group,
                    "materials": materials,
                    "members": _filtered_members(shading_group, obj, shape),
                })
            shape_results.append({
                "shape": shape,
                "shape_type": cmds.objectType(shape),
                "assignments": assignments,
            })
        results.append({
            "object_name": obj,
            "shapes": shape_results,
        })

    return {
        "success": True,
        "object_names": objects,
        "include_components": bool(include_components),
        "objects": results,
        "shading_groups": _unique(all_shading_groups),
        "materials": _unique(all_materials),
    }
