from typing import Dict, List, Any, Union


def playblast_object_silhouette(
    name: str = "object_silhouette",
    target_objects: Union[str, List[str]] = None,
    output_path: str = None,
    view_direction: List[float] = None,
    up_axis: List[float] = None,
    silhouette_color: List[float] = None,
    background_color: List[float] = None,
    orthographic_width: float = None,
    padding_fraction: float = 0.08,
    image_width: int = 640,
    image_height: int = 960,
    use_isolate_select: bool = True,
    hide_non_target_transforms: bool = True,
) -> Dict[str, Any]:
    """Playblast a clean orthographic silhouette of target mesh objects.

    The tool duplicates the target mesh transforms into temporary proxy objects,
    assigns the proxies a flat high-contrast material, isolates them in a model
    panel, hides non-mesh viewport categories such as cameras and locators, and
    writes a single-frame playblast. It then removes all temporary proxy nodes.
    It returns the camera framing data needed by downstream QA tools to map
    silhouette errors back to components using the same projection. This gives
    repeatable silhouette QA without modifying the user's real materials, face
    assignments, selection, or scene geometry.
    """
    import math
    import os
    import re
    import maya.cmds as cmds
    import maya.api.OpenMaya as om

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(item) for item in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(item) for item in values]

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

    def _validate_image_size(value, arg_name):
        if not isinstance(value, int) or isinstance(value, bool) or value < 64:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to 64.")
        return int(value)

    def _safe_name(value, fallback):
        text = str(value or fallback).strip()
        text = re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_")
        return text or fallback

    def _normalize_vector(values, arg_name):
        vector = om.MVector(*_validate_vector(values, 3, arg_name))
        if vector.length() <= 1.0e-12:
            raise ValueError(f"{arg_name} must not be a zero vector.")
        vector.normalize()
        return vector

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

    def _mesh_parent_targets():
        targets = []
        seen = set()
        for shape in cmds.ls(type="mesh", long=True) or []:
            try:
                if cmds.attributeQuery("intermediateObject", node=shape, exists=True) and cmds.getAttr(f"{shape}.intermediateObject"):
                    continue
            except Exception:
                pass
            parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
            if not parents:
                continue
            parent = parents[0]
            if parent in seen or not _is_visible(shape) or not _is_visible(parent):
                continue
            seen.add(parent)
            targets.append(parent)
        return targets

    def _normalize_targets(value):
        if value is None:
            resolved = _mesh_parent_targets()
        elif isinstance(value, str):
            resolved = [value]
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            resolved = value[:]
        else:
            raise ValueError("target_objects must be a string, list of strings, or None.")
        if not resolved:
            raise ValueError("No target mesh objects found.")
        result = []
        seen = set()
        for target in resolved:
            if not cmds.objExists(target):
                raise ValueError(f"Target object does not exist: {target}")
            if target in seen:
                continue
            shapes = cmds.listRelatives(target, shapes=True, fullPath=True) or []
            if not any(cmds.objectType(shape) == "mesh" for shape in shapes):
                raise ValueError(f"Target object has no mesh shape: {target}")
            seen.add(target)
            result.append(target)
        return result

    def _bbox_corners(bbox):
        return [
            [bbox[xi], bbox[yi], bbox[zi]]
            for xi in (0, 3)
            for yi in (1, 4)
            for zi in (2, 5)
        ]

    def _combined_bbox(objects):
        bbox = list(cmds.exactWorldBoundingBox(objects[0]))
        for obj in objects[1:]:
            item = cmds.exactWorldBoundingBox(obj)
            bbox[0] = min(bbox[0], item[0])
            bbox[1] = min(bbox[1], item[1])
            bbox[2] = min(bbox[2], item[2])
            bbox[3] = max(bbox[3], item[3])
            bbox[4] = max(bbox[4], item[4])
            bbox[5] = max(bbox[5], item[5])
        return bbox

    def _projection_frame(view, up):
        clean_up = up - view * (up * view)
        if clean_up.length() <= 1.0e-12:
            raise ValueError("up_axis must not be parallel to view_direction.")
        clean_up.normalize()
        right = view ^ clean_up
        if right.length() <= 1.0e-12:
            raise ValueError("Unable to build camera projection frame.")
        right.normalize()
        return right, clean_up

    def _camera_width_from_bbox(bbox, view, right, up):
        corners = _bbox_corners(bbox)
        projected_x = []
        projected_y = []
        projected_z = []
        for corner in corners:
            vector = om.MVector(*corner)
            projected_x.append(float(vector * right))
            projected_y.append(float(vector * up))
            projected_z.append(float(vector * view))
        width = max(1.0e-6, max(projected_x) - min(projected_x))
        height = max(1.0e-6, max(projected_y) - min(projected_y))
        depth = max(1.0e-6, max(projected_z) - min(projected_z))
        aspect = float(clean_image_width) / float(clean_image_height)
        vertical_for_width = width / max(1.0e-6, aspect)
        clean_padding = max(0.0, clean_padding_fraction)
        return max(height, vertical_for_width) * (1.0 + clean_padding * 2.0), depth

    def _aim_camera(camera_transform, target):
        locator = cmds.spaceLocator(name=f"{safe_prefix}_aim_tmp")[0]
        cmds.xform(locator, translation=target, worldSpace=True)
        constraint = cmds.aimConstraint(
            locator,
            camera_transform,
            aimVector=[0, 0, -1],
            upVector=[0, 1, 0],
            worldUpType="scene",
        )
        cmds.delete(constraint)
        cmds.delete(locator)

    def _set_model_editor_flag(panel, **kwargs):
        try:
            cmds.modelEditor(panel, edit=True, **kwargs)
        except Exception:
            pass

    def _configure_panel(panel, camera):
        cmds.lookThru(panel, camera)
        _set_model_editor_flag(panel, rendererName="vp2Renderer")
        _set_model_editor_flag(
            panel,
            allObjects=False,
            polymeshes=True,
            displayAppearance="smoothShaded",
            displayTextures=False,
            useDefaultMaterial=False,
            wireframeOnShaded=False,
            grid=False,
            manipulators=False,
            hud=False,
            selectionHiliteDisplay=False,
        )
        for flag in [
            "cameras",
            "lights",
            "locators",
            "nurbsCurves",
            "nurbsSurfaces",
            "joints",
            "ikHandles",
            "deformers",
            "dynamics",
            "fluids",
            "hairSystems",
            "follicles",
            "nCloths",
            "pluginShapes",
            "dimensions",
            "handles",
            "strokes",
        ]:
            _set_model_editor_flag(panel, **{flag: False})

    def _create_material():
        shader = cmds.shadingNode("surfaceShader", asShader=True, name=f"{safe_prefix}_material")
        shading_group = cmds.sets(name=f"{safe_prefix}_materialSG", empty=True, renderable=True, noSurfaceShader=True)
        cmds.setAttr(f"{shader}.outColor", clean_silhouette_color[0], clean_silhouette_color[1], clean_silhouette_color[2], type="double3")
        cmds.connectAttr(f"{shader}.outColor", f"{shading_group}.surfaceShader", force=True)
        return shader, shading_group

    def _long_name(node):
        matches = cmds.ls(node, long=True) or []
        return matches[0] if matches else node

    def _hide_unwanted_transforms(keep_nodes):
        if not hide_non_target_transforms:
            return []
        keep = {_long_name(node) for node in keep_nodes if cmds.objExists(node)}
        hidden = []
        for transform in cmds.ls(type="transform", long=True) or []:
            if transform in keep:
                continue
            try:
                if not cmds.attributeQuery("visibility", node=transform, exists=True):
                    continue
                previous = bool(cmds.getAttr(f"{transform}.visibility"))
                if previous:
                    cmds.setAttr(f"{transform}.visibility", False)
                    hidden.append({"node": transform, "visibility": previous})
            except Exception:
                pass
        return hidden

    if not name:
        raise ValueError("name is required.")
    if not output_path:
        raise ValueError("output_path is required.")
    safe_prefix = _safe_name(name, "object_silhouette")
    clean_image_width = _validate_image_size(image_width, "image_width")
    clean_image_height = _validate_image_size(image_height, "image_height")
    clean_padding_fraction = _validate_scalar(padding_fraction, "padding_fraction")
    if clean_padding_fraction < 0.0:
        raise ValueError("padding_fraction must be greater than or equal to zero.")
    clean_view = _normalize_vector(view_direction if view_direction is not None else [0.0, 0.0, -1.0], "view_direction")
    clean_up = _normalize_vector(up_axis if up_axis is not None else [0.0, 1.0, 0.0], "up_axis")
    right_axis, up_vector = _projection_frame(clean_view, clean_up)
    clean_silhouette_color = _validate_vector(silhouette_color if silhouette_color is not None else [0.0, 0.0, 0.0], 3, "silhouette_color")
    clean_background_color = _validate_vector(background_color if background_color is not None else [1.0, 1.0, 1.0], 3, "background_color")
    if orthographic_width is not None:
        clean_orthographic_width = _validate_scalar(orthographic_width, "orthographic_width")
        if clean_orthographic_width <= 0.0:
            raise ValueError("orthographic_width must be greater than zero.")
    else:
        clean_orthographic_width = None

    targets = _normalize_targets(target_objects)
    original_modified = bool(cmds.file(query=True, modified=True))
    original_selection = cmds.ls(selection=True, long=True) or []
    original_background = {}
    for color_name in ["background", "backgroundTop", "backgroundBottom"]:
        try:
            original_background[color_name] = cmds.displayRGBColor(color_name, query=True)
        except Exception:
            pass

    panels = cmds.getPanel(type="modelPanel") or [cmds.modelPanel()]
    panel = panels[0]
    isolate_states = {}
    proxies = []
    temp_nodes = []
    hidden_visibility = []
    playblast_result = None

    try:
        target_bbox = _combined_bbox(targets)
        target_center = [
            (target_bbox[0] + target_bbox[3]) * 0.5,
            (target_bbox[1] + target_bbox[4]) * 0.5,
            (target_bbox[2] + target_bbox[5]) * 0.5,
        ]
        auto_width, target_depth = _camera_width_from_bbox(target_bbox, clean_view, right_axis, up_vector)
        resolved_orthographic_width = clean_orthographic_width or auto_width
        camera_distance = max(10.0, target_depth + resolved_orthographic_width * 2.0)
        camera_position = [
            target_center[0] - clean_view.x * camera_distance,
            target_center[1] - clean_view.y * camera_distance,
            target_center[2] - clean_view.z * camera_distance,
        ]

        shader, shading_group = _create_material()
        temp_nodes.extend([shader, shading_group])

        group = cmds.group(empty=True, name=f"{safe_prefix}_proxy_GRP")
        temp_nodes.append(group)
        for index, target in enumerate(targets):
            duplicate_name = f"{safe_prefix}_{index}_{_safe_name(target.rsplit('|', 1)[-1], 'target')}_proxy"
            duplicate = cmds.duplicate(target, name=duplicate_name, returnRootsOnly=True)[0]
            cmds.parent(duplicate, group)
            proxies.append(duplicate)
        if proxies:
            cmds.sets(proxies, edit=True, forceElement=shading_group)

        camera, camera_shape = cmds.camera(name=f"{safe_prefix}_camera")
        temp_nodes.extend([camera])
        cmds.xform(camera, translation=camera_position, worldSpace=True)
        cmds.setAttr(f"{camera_shape}.orthographic", True)
        cmds.setAttr(f"{camera_shape}.orthographicWidth", resolved_orthographic_width)
        cmds.setAttr(f"{camera_shape}.nearClipPlane", 0.01)
        cmds.setAttr(f"{camera_shape}.farClipPlane", 10000.0)
        _aim_camera(camera, target_center)

        hidden_visibility = _hide_unwanted_transforms([group] + proxies + [camera])

        for color_name in ["background", "backgroundTop", "backgroundBottom"]:
            try:
                cmds.displayRGBColor(color_name, clean_background_color[0], clean_background_color[1], clean_background_color[2])
            except Exception:
                pass

        for model_panel in panels:
            _configure_panel(model_panel, camera)
        if use_isolate_select:
            try:
                cmds.select(proxies, replace=True)
                for model_panel in panels:
                    try:
                        isolate_states[model_panel] = bool(cmds.isolateSelect(model_panel, query=True, state=True))
                    except Exception:
                        isolate_states[model_panel] = False
                    cmds.isolateSelect(model_panel, state=True)
                    cmds.isolateSelect(model_panel, addSelected=True)
            except Exception:
                pass

        try:
            cmds.select(clear=True)
        except Exception:
            pass
        try:
            cmds.setFocus(panel)
        except Exception:
            pass

        try:
            cmds.refresh(force=True)
        except Exception:
            pass

        normalized_output_path = os.path.normpath(output_path)
        output_dir = os.path.dirname(normalized_output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
        playblast_result = cmds.playblast(
            completeFilename=normalized_output_path,
            format="image",
            compression="png",
            frame=[1],
            widthHeight=[clean_image_width, clean_image_height],
            percent=100,
            quality=95,
            viewer=False,
            showOrnaments=False,
            forceOverwrite=True,
            offScreen=True,
        )
    finally:
        if use_isolate_select:
            for model_panel, previous_state in isolate_states.items():
                try:
                    cmds.isolateSelect(model_panel, state=previous_state)
                except Exception:
                    pass
        for node in reversed(temp_nodes):
            if cmds.objExists(node):
                try:
                    cmds.delete(node)
                except Exception:
                    pass
        for item in hidden_visibility:
            try:
                if cmds.objExists(item["node"]):
                    cmds.setAttr(f"{item['node']}.visibility", item["visibility"])
            except Exception:
                pass
        for color_name, color in original_background.items():
            try:
                cmds.displayRGBColor(color_name, color[0], color[1], color[2])
            except Exception:
                pass
        try:
            if original_selection:
                cmds.select(original_selection, replace=True)
            else:
                cmds.select(clear=True)
        except Exception:
            pass
        if not original_modified:
            try:
                cmds.file(modified=False)
            except Exception:
                pass

    return {
        "success": True,
        "name": name,
        "target_objects": targets,
        "output_path": playblast_result or os.path.normpath(output_path),
        "view_direction": [float(clean_view.x), float(clean_view.y), float(clean_view.z)],
        "up_axis": [float(up_vector.x), float(up_vector.y), float(up_vector.z)],
        "right_axis": [float(right_axis.x), float(right_axis.y), float(right_axis.z)],
        "silhouette_color": clean_silhouette_color,
        "background_color": clean_background_color,
        "bounding_box": target_bbox,
        "camera_center": target_center,
        "camera_position": camera_position,
        "orthographic_width": resolved_orthographic_width,
        "image_width": clean_image_width,
        "image_height": clean_image_height,
        "proxy_count": len(proxies),
        "isolated": bool(use_isolate_select),
        "hide_non_target_transforms": bool(hide_non_target_transforms),
    }
