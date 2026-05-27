from typing import Dict, List, Any, Union


def fit_objects_to_bounds(
    object_names: Union[str, List[str]],
    target_bounds: List[float] = None,
    target_center: List[float] = None,
    target_size: List[float] = None,
    axes: List[str] = None,
    scale_mode: str = "independent",
    anchor: str = "center",
    pivot: List[float] = None,
    apply_mode: str = "points",
    min_size: float = 1e-6,
) -> Dict[str, Any]:
    """Fit one or more scene objects to target world-space bounds.

    This is a generic bounds-fitting utility for resizing and positioning
    separate parts, labels, panels, cards, props, fixtures, and other geometry.
    It computes scale and translation from the current combined bounding box to
    a target bounding box or target center/size.

    With apply_mode="points", mesh vertices and curve CVs are transformed in
    world space. This preserves transform channels and is useful for fitted
    geometry layers. With apply_mode="transform", object transforms are moved
    and scaled, which is useful for simple transform-level fitting.

    scale_mode:
    - independent: scale each fitted axis independently.
    - uniform_fit: use the smallest fitted-axis scale on all fitted axes.
    - uniform_fill: use the largest fitted-axis scale on all fitted axes.

    anchor controls post-scale alignment to the target bounds: center, min, or
    max. Axes omitted from axes are left unchanged.
    """
    import maya.cmds as cmds

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(value) for value in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(value) for value in values]

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

    def _combined_bbox(objects):
        bbox = None
        for obj in objects:
            obj_bbox = cmds.exactWorldBoundingBox(obj)
            if bbox is None:
                bbox = obj_bbox[:]
            else:
                bbox[0] = min(bbox[0], obj_bbox[0])
                bbox[1] = min(bbox[1], obj_bbox[1])
                bbox[2] = min(bbox[2], obj_bbox[2])
                bbox[3] = max(bbox[3], obj_bbox[3])
                bbox[4] = max(bbox[4], obj_bbox[4])
                bbox[5] = max(bbox[5], obj_bbox[5])
        return bbox

    def _bbox_center_size(bbox):
        center = [
            (bbox[0] + bbox[3]) * 0.5,
            (bbox[1] + bbox[4]) * 0.5,
            (bbox[2] + bbox[5]) * 0.5,
        ]
        size = [
            bbox[3] - bbox[0],
            bbox[4] - bbox[1],
            bbox[5] - bbox[2],
        ]
        return center, size

    def _target_bbox():
        if target_bounds is not None:
            bounds = _validate_vector(target_bounds, 6, "target_bounds")
            if bounds[3] < bounds[0] or bounds[4] < bounds[1] or bounds[5] < bounds[2]:
                raise ValueError("target_bounds must be [min_x, min_y, min_z, max_x, max_y, max_z].")
            return bounds
        if target_center is None or target_size is None:
            raise ValueError("Provide target_bounds or both target_center and target_size.")
        center = _validate_vector(target_center, 3, "target_center")
        size = _validate_vector(target_size, 3, "target_size")
        if any(value < 0.0 for value in size):
            raise ValueError("target_size values must be greater than or equal to zero.")
        return [
            center[0] - size[0] * 0.5,
            center[1] - size[1] * 0.5,
            center[2] - size[2] * 0.5,
            center[0] + size[0] * 0.5,
            center[1] + size[1] * 0.5,
            center[2] + size[2] * 0.5,
        ]

    def _object_components(obj):
        components = []
        if cmds.objectType(obj) == "mesh":
            components.extend(cmds.ls(f"{obj}.vtx[*]", flatten=True) or [])
        else:
            shapes = cmds.listRelatives(obj, shapes=True, fullPath=True) or []
            for shape in shapes:
                shape_type = cmds.objectType(shape)
                if shape_type == "mesh":
                    components.extend(cmds.ls(f"{shape}.vtx[*]", flatten=True) or [])
                elif shape_type in {"nurbsCurve", "bezierCurve"}:
                    components.extend(cmds.ls(f"{shape}.cv[*]", flatten=True) or [])
        return components

    def _scale_translate_for_bbox(source_bbox, target_bbox, fit_axes):
        source_center, source_size = _bbox_center_size(source_bbox)
        target_center_value, target_size_value = _bbox_center_size(target_bbox)
        scales = [1.0, 1.0, 1.0]
        for index in fit_axes:
            if source_size[index] <= min_size:
                scales[index] = 1.0
            else:
                scales[index] = target_size_value[index] / source_size[index]
        if scale_mode != "independent" and fit_axes:
            axis_scales = [scales[index] for index in fit_axes]
            uniform = min(axis_scales) if scale_mode == "uniform_fit" else max(axis_scales)
            for index in fit_axes:
                scales[index] = uniform

        scale_pivot = clean_pivot or source_center
        scaled_min = []
        scaled_max = []
        for index in range(3):
            scaled_min.append(scale_pivot[index] + (source_bbox[index] - scale_pivot[index]) * scales[index])
            scaled_max.append(scale_pivot[index] + (source_bbox[index + 3] - scale_pivot[index]) * scales[index])

        translation = [0.0, 0.0, 0.0]
        for index in fit_axes:
            if anchor == "min":
                translation[index] = target_bbox[index] - scaled_min[index]
            elif anchor == "max":
                translation[index] = target_bbox[index + 3] - scaled_max[index]
            else:
                scaled_center = (scaled_min[index] + scaled_max[index]) * 0.5
                translation[index] = target_center_value[index] - scaled_center
        return scales, translation, scale_pivot

    if isinstance(object_names, str):
        objects = [object_names]
    elif isinstance(object_names, list) and object_names and all(isinstance(obj, str) for obj in object_names):
        objects = object_names[:]
    else:
        raise ValueError("object_names must be a string or a non-empty list of strings.")

    for obj in objects:
        if not cmds.objExists(obj):
            raise ValueError(f"Object does not exist: {obj}")

    axis_lookup = {"x": 0, "y": 1, "z": 2}
    if axes is None:
        axes = ["x", "y", "z"]
    if isinstance(axes, str):
        axes = [axes]
    if not isinstance(axes, list) or not axes:
        raise ValueError("axes must be a non-empty list containing x, y, and/or z.")
    fit_axes = []
    for axis in axes:
        axis = axis.lower().strip()
        if axis not in axis_lookup:
            raise ValueError("axes must contain only x, y, or z.")
        fit_axes.append(axis_lookup[axis])
    fit_axes = sorted(set(fit_axes))

    scale_mode = scale_mode.lower().strip()
    if scale_mode not in {"independent", "uniform_fit", "uniform_fill"}:
        raise ValueError("scale_mode must be independent, uniform_fit, or uniform_fill.")
    anchor = anchor.lower().strip()
    if anchor not in {"center", "min", "max"}:
        raise ValueError("anchor must be center, min, or max.")
    apply_mode = apply_mode.lower().strip()
    if apply_mode not in {"points", "transform"}:
        raise ValueError("apply_mode must be points or transform.")
    min_size = _validate_scalar(min_size, "min_size")
    if min_size < 0.0:
        raise ValueError("min_size must be greater than or equal to zero.")

    clean_pivot = _validate_vector(pivot, 3, "pivot") if pivot is not None else None
    target_bbox = _target_bbox()
    source_bbox = _combined_bbox(objects)
    scales, translation, scale_pivot = _scale_translate_for_bbox(source_bbox, target_bbox, fit_axes)

    transformed_points = 0
    transformed_objects = 0
    if apply_mode == "points":
        for obj in objects:
            components = _object_components(obj)
            if not components:
                raise ValueError(f"No supported mesh vertices or curve CVs found on {obj}.")
            for component in components:
                position = cmds.xform(component, query=True, worldSpace=True, translation=True)
                for index in fit_axes:
                    position[index] = scale_pivot[index] + (position[index] - scale_pivot[index]) * scales[index] + translation[index]
                cmds.xform(component, worldSpace=True, translation=position)
                transformed_points += 1
            transformed_objects += 1
            if cmds.objExists(obj):
                try:
                    cmds.polySoftEdge(obj, angle=180, constructionHistory=False)
                except Exception:
                    pass
    else:
        for obj in objects:
            current_scale = list(cmds.getAttr(f"{obj}.scale")[0])
            current_position = cmds.xform(obj, query=True, worldSpace=True, translation=True)
            for index in fit_axes:
                current_scale[index] *= scales[index]
                current_position[index] = scale_pivot[index] + (current_position[index] - scale_pivot[index]) * scales[index] + translation[index]
            cmds.setAttr(f"{obj}.scale", current_scale[0], current_scale[1], current_scale[2], type="double3")
            cmds.xform(obj, worldSpace=True, translation=current_position)
            transformed_objects += 1

    final_bbox = _combined_bbox(objects)
    return {
        "success": True,
        "object_names": objects,
        "apply_mode": apply_mode,
        "axes": axes,
        "scale_mode": scale_mode,
        "anchor": anchor,
        "source_bounds": source_bbox,
        "target_bounds": target_bbox,
        "final_bounds": final_bbox,
        "scale": scales,
        "translation": translation,
        "pivot": scale_pivot,
        "transformed_objects": transformed_objects,
        "transformed_points": transformed_points,
    }
