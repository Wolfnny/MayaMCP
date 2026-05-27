from typing import Dict, List, Any, Union


def get_object_bounds(
    object_names: Union[str, List[str]],
    visible_only: bool = False,
) -> Dict[str, Any]:
    """Return world-space bounds for one or more scene objects.

    This is a generic measurement utility for modeling and layout workflows. It
    reports each object's exact world-space bounding box, plus the combined
    bounds, center, and size for the requested set. The output can be used to
    fit parts, map image/profile measurements onto geometry, or validate object
    placement without relying on ad hoc Maya scripts.
    """
    import maya.cmds as cmds

    if isinstance(object_names, str):
        objects = [object_names]
    elif isinstance(object_names, list) and object_names and all(isinstance(obj, str) for obj in object_names):
        objects = object_names[:]
    else:
        raise ValueError("object_names must be a string or a non-empty list of strings.")

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

    def _center_size(bounds):
        center = [
            (bounds[0] + bounds[3]) * 0.5,
            (bounds[1] + bounds[4]) * 0.5,
            (bounds[2] + bounds[5]) * 0.5,
        ]
        size = [
            bounds[3] - bounds[0],
            bounds[4] - bounds[1],
            bounds[5] - bounds[2],
        ]
        return center, size

    item_bounds = []
    combined_bounds = None
    skipped_hidden = []
    for obj in objects:
        if not cmds.objExists(obj):
            raise ValueError(f"Object does not exist: {obj}")
        if visible_only and not _is_visible(obj):
            skipped_hidden.append(obj)
            continue

        bounds = [float(value) for value in cmds.exactWorldBoundingBox(obj)]
        center, size = _center_size(bounds)
        item_bounds.append({
            "object_name": obj,
            "bounds": bounds,
            "center": center,
            "size": size,
        })

        if combined_bounds is None:
            combined_bounds = bounds[:]
        else:
            combined_bounds[0] = min(combined_bounds[0], bounds[0])
            combined_bounds[1] = min(combined_bounds[1], bounds[1])
            combined_bounds[2] = min(combined_bounds[2], bounds[2])
            combined_bounds[3] = max(combined_bounds[3], bounds[3])
            combined_bounds[4] = max(combined_bounds[4], bounds[4])
            combined_bounds[5] = max(combined_bounds[5], bounds[5])

    if combined_bounds is None:
        raise ValueError("No visible objects remain after filtering.")

    combined_center, combined_size = _center_size(combined_bounds)
    return {
        "success": True,
        "object_names": objects,
        "visible_only": bool(visible_only),
        "skipped_hidden": skipped_hidden,
        "objects": item_bounds,
        "combined_bounds": combined_bounds,
        "combined_center": combined_center,
        "combined_size": combined_size,
    }
