from typing import Dict, List, Any, Union


def setup_product_preview_scene(
    name: str = "product_preview",
    target_objects: Union[str, List[str]] = None,
    camera_position: List[float] = None,
    target_position: List[float] = None,
    focal_length: float = 85.0,
    distance_multiplier: float = 3.0,
    background_color: List[float] = [0.45, 0.45, 0.45],
    key_light_intensity: float = 1.1,
    fill_light_intensity: float = 0.35,
    rim_light_intensity: float = 0.65,
    display_textures: bool = True,
    transparency_algorithm: str = "depthPeeling",
    display_curves: bool = False,
    refresh_textures: bool = False,
    playblast_path: str = None,
    image_width: int = 1200,
    image_height: int = 1600,
) -> Dict[str, Any]:
    """Set up a generic product-preview camera, lights, viewport, and snapshot.

    This is intended for evaluating modeled products, packaging, props, and
    transparent materials in a repeatable studio-like viewport. It can frame
    target objects from their bounding box, create simple three-point lighting,
    set a neutral background, configure model panels for shaded/textured display,
    optionally soft-refresh file texture nodes and reset the viewport cache,
    and optionally write a playblast image.
    """
    import math
    import os
    import maya.cmds as cmds
    import maya.mel as mel

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(v) for v in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(v) for v in values]

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

    def _validate_image_size(value, arg_name):
        if not isinstance(value, int) or isinstance(value, bool) or value < 64:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to 64.")
        return value

    def _safe_delete(node_name):
        if cmds.objExists(node_name):
            try:
                cmds.delete(node_name)
            except Exception:
                pass

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

    def _shape_parent_targets(shape_types):
        targets = []
        seen = set()
        for shape_type in shape_types:
            for shape in cmds.ls(type=shape_type, long=True) or []:
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

    def _default_targets():
        mesh_targets = _shape_parent_targets(["mesh"])
        if mesh_targets:
            return mesh_targets
        return _shape_parent_targets(["nurbsCurve", "bezierCurve"])

    def _normalize_targets(targets):
        if targets is None:
            return _default_targets()
        if isinstance(targets, str):
            targets = [targets]
        if not isinstance(targets, list) or not all(isinstance(item, str) for item in targets):
            raise ValueError("target_objects must be a string, a list of strings, or None.")
        for target in targets:
            if not cmds.objExists(target):
                raise ValueError(f"target object does not exist: {target}")
        return targets

    def _combined_bbox(objects):
        if not objects:
            return [-0.5, 0.0, -0.5, 0.5, 1.0, 0.5]
        first = cmds.exactWorldBoundingBox(objects[0])
        bbox = list(first)
        for obj in objects[1:]:
            obj_bbox = cmds.exactWorldBoundingBox(obj)
            bbox[0] = min(bbox[0], obj_bbox[0])
            bbox[1] = min(bbox[1], obj_bbox[1])
            bbox[2] = min(bbox[2], obj_bbox[2])
            bbox[3] = max(bbox[3], obj_bbox[3])
            bbox[4] = max(bbox[4], obj_bbox[4])
            bbox[5] = max(bbox[5], obj_bbox[5])
        return bbox

    def _frame_distance(size, focal_length_value, distance_multiplier_value):
        max_size = max(size)
        horizontal_aperture_mm = 36.0
        vertical_aperture_mm = 24.0
        horizontal_fov = 2.0 * math.atan(horizontal_aperture_mm / (2.0 * focal_length_value))
        vertical_fov = 2.0 * math.atan(vertical_aperture_mm / (2.0 * focal_length_value))
        distance_for_width = (size[0] * 0.5) / max(1e-6, math.tan(horizontal_fov * 0.5))
        distance_for_height = (size[1] * 0.5) / max(1e-6, math.tan(vertical_fov * 0.5))
        fov_distance = max(distance_for_width, distance_for_height) * 1.15 + size[2] * 0.5
        multiplier_distance = max_size * distance_multiplier_value
        return max(2.0, fov_distance, multiplier_distance)

    def _aim_camera(camera_transform, target):
        locator = cmds.spaceLocator(name=f"{name}_camera_target_tmp")[0]
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

    def _prepare_file_textures(force_refresh):
        def _mel_quote(value):
            return '"' + str(value).replace("\\", "/").replace('"', '\\"') + '"'

        def _reload_texture_callbacks(file_node, texture_path):
            actions = []
            if not texture_path:
                return actions
            try:
                mel.eval("source AEfileTemplate.mel")
            except Exception as exc:
                actions.append({"action": "source_AEfileTemplate", "error": str(exc)})
            try:
                mel.eval("AEfileTextureReloadCmd " + _mel_quote(f"{file_node}.fileTextureName"))
                actions.append({"action": "AEfileTextureReloadCmd"})
            except Exception as exc:
                actions.append({"action": "AEfileTextureReloadCmd", "error": str(exc)})
                try:
                    mel.eval("callbacks -executeCallbacks -hook textureReload " + _mel_quote(texture_path))
                    actions.append({"action": "textureReload_callback"})
                except Exception as callback_exc:
                    actions.append({"action": "textureReload_callback", "error": str(callback_exc)})
            return actions

        def _placeholder_texture_path():
            import base64
            placeholder_path = os.path.join(cmds.internalVar(userTmpDir=True) or os.getcwd(), "maya_mcp_texture_reload_placeholder.png")
            if not os.path.exists(placeholder_path):
                png_bytes = base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
                )
                with open(placeholder_path, "wb") as handle:
                    handle.write(png_bytes)
            return placeholder_path

        placeholder_texture = _placeholder_texture_path() if force_refresh else None
        file_nodes = cmds.ls(type="file") or []
        scene_texture_paths = []
        for node in file_nodes:
            try:
                node_path = cmds.getAttr(f"{node}.fileTextureName") or ""
                if node_path and os.path.exists(os.path.normpath(node_path)):
                    scene_texture_paths.append(node_path)
            except Exception:
                pass

        def _alternate_texture_path(original_path):
            original_norm = os.path.normcase(os.path.normpath(original_path))
            for candidate in scene_texture_paths:
                if os.path.normcase(os.path.normpath(candidate)) != original_norm:
                    return candidate
            return placeholder_texture

        prepared = []
        for file_node in file_nodes:
            item = {"node": file_node}
            try:
                path = cmds.getAttr(f"{file_node}.fileTextureName") or ""
                item["path"] = path
                item["exists"] = bool(path and os.path.exists(os.path.normpath(path)))
                if cmds.attributeQuery("disableFileLoad", node=file_node, exists=True):
                    cmds.setAttr(f"{file_node}.disableFileLoad", 0)
                if force_refresh:
                    if path:
                        try:
                            reload_path = _alternate_texture_path(path) or ""
                            cmds.setAttr(f"{file_node}.fileTextureName", reload_path, type="string")
                            cmds.setAttr(f"{file_node}.fileTextureName", path, type="string")
                            item["path_reloaded"] = True
                            item["reload_placeholder"] = reload_path
                            item["reload_actions"] = _reload_texture_callbacks(file_node, path)
                        except Exception as exc:
                            item["reload_error"] = str(exc)
                    try:
                        cmds.dgdirty(file_node)
                    except Exception:
                        pass
                prepared.append(item)
            except Exception as exc:
                item["error"] = str(exc)
                prepared.append(item)
        if force_refresh:
            try:
                cmds.refresh(force=True)
            except Exception:
                pass
        return prepared

    def _reset_viewport_cache():
        try:
            panels = cmds.ogs(reset=True) or []
            if isinstance(panels, str):
                panels = [panels]
            try:
                cmds.refresh(force=True)
            except Exception:
                pass
            return {"panels": panels}
        except Exception as exc:
            return {"error": str(exc), "panels": []}

    if not name:
        raise ValueError("name is required.")
    target_objects = _normalize_targets(target_objects)
    focal_length = _validate_scalar(focal_length, "focal_length")
    distance_multiplier = _validate_scalar(distance_multiplier, "distance_multiplier")
    if focal_length <= 0.0:
        raise ValueError("focal_length must be greater than zero.")
    if distance_multiplier <= 0.0:
        raise ValueError("distance_multiplier must be greater than zero.")
    background_color = _validate_vector(background_color, 3, "background_color")
    key_light_intensity = _validate_scalar(key_light_intensity, "key_light_intensity")
    fill_light_intensity = _validate_scalar(fill_light_intensity, "fill_light_intensity")
    rim_light_intensity = _validate_scalar(rim_light_intensity, "rim_light_intensity")
    image_width = _validate_image_size(image_width, "image_width")
    image_height = _validate_image_size(image_height, "image_height")
    if not isinstance(refresh_textures, bool):
        raise ValueError("refresh_textures must be a boolean.")
    transparency_algorithm = transparency_algorithm.strip()

    bbox = _combined_bbox(target_objects)
    bbox_center = [
        (bbox[0] + bbox[3]) * 0.5,
        (bbox[1] + bbox[4]) * 0.5,
        (bbox[2] + bbox[5]) * 0.5,
    ]
    bbox_size = [
        max(1e-6, bbox[3] - bbox[0]),
        max(1e-6, bbox[4] - bbox[1]),
        max(1e-6, bbox[5] - bbox[2]),
    ]
    if target_position is None:
        target_position = bbox_center
    else:
        target_position = _validate_vector(target_position, 3, "target_position")
    if camera_position is None:
        camera_distance = _frame_distance(bbox_size, focal_length, distance_multiplier)
        camera_position = [
            target_position[0],
            target_position[1] + bbox_size[1] * 0.05,
            target_position[2] + camera_distance,
        ]
    else:
        camera_position = _validate_vector(camera_position, 3, "camera_position")

    for suffix in ["camera", "key_light", "fill_light", "rim_light"]:
        _safe_delete(f"{name}_{suffix}")

    camera, camera_shape = cmds.camera(name=f"{name}_camera")
    cmds.xform(camera, translation=camera_position, worldSpace=True)
    cmds.setAttr(f"{camera_shape}.focalLength", focal_length)
    cmds.setAttr(f"{camera_shape}.nearClipPlane", 0.01)
    cmds.setAttr(f"{camera_shape}.farClipPlane", 10000.0)
    _aim_camera(camera, target_position)

    key_shape = cmds.directionalLight(name=f"{name}_key_light", intensity=key_light_intensity)
    key_light = cmds.listRelatives(key_shape, parent=True)[0]
    cmds.xform(key_light, rotation=[-35.0, 30.0, 0.0], worldSpace=True)

    fill_shape = cmds.ambientLight(name=f"{name}_fill_light", intensity=fill_light_intensity)
    fill_light = cmds.listRelatives(fill_shape, parent=True)[0]

    rim_shape = cmds.directionalLight(name=f"{name}_rim_light", intensity=rim_light_intensity)
    rim_light = cmds.listRelatives(rim_shape, parent=True)[0]
    cmds.xform(rim_light, rotation=[-15.0, -145.0, 0.0], worldSpace=True)

    try:
        cmds.displayRGBColor("background", background_color[0], background_color[1], background_color[2])
        cmds.displayRGBColor("backgroundTop", background_color[0], background_color[1], background_color[2])
        cmds.displayRGBColor("backgroundBottom", background_color[0], background_color[1], background_color[2])
    except Exception:
        pass

    refreshed_textures = []
    if not refresh_textures:
        _prepare_file_textures(False)
    panels = cmds.getPanel(type="modelPanel") or []
    configured_panels = []
    for panel in panels:
        try:
            cmds.lookThru(panel, camera)
            try:
                cmds.modelEditor(panel, edit=True, rendererName="vp2Renderer")
            except Exception:
                pass
            cmds.modelEditor(
                panel,
                edit=True,
                displayAppearance="smoothShaded",
                displayTextures=bool(display_textures),
                useDefaultMaterial=False,
                wireframeOnShaded=False,
                grid=False,
            )
            cmds.modelEditor(panel, edit=True, nurbsCurves=bool(display_curves), locators=False, cameras=False, lights=False, joints=False)
            try:
                cmds.modelEditor(panel, edit=True, transparencyAlgorithm=transparency_algorithm)
            except Exception:
                pass
            configured_panels.append(panel)
        except Exception:
            continue

    viewport_cache_reset = _reset_viewport_cache() if refresh_textures else {"panels": []}
    if refresh_textures:
        refreshed_textures = _prepare_file_textures(True)

    try:
        cmds.refresh(force=True)
    except Exception:
        pass

    playblast_result = None
    if playblast_path:
        normalized_path = os.path.normpath(playblast_path)
        directory = os.path.dirname(normalized_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
        playblast_result = cmds.playblast(
            completeFilename=normalized_path,
            format="image",
            compression="png",
            frame=[1],
            widthHeight=[image_width, image_height],
            percent=100,
            quality=95,
            viewer=False,
            showOrnaments=False,
            forceOverwrite=True,
        )

    return {
        "success": True,
        "name": name,
        "target_objects": target_objects,
        "bounding_box": bbox,
        "target_position": target_position,
        "camera": camera,
        "camera_shape": camera_shape,
        "camera_position": camera_position,
        "focal_length": focal_length,
        "lights": [key_light, fill_light, rim_light],
        "background_color": background_color,
        "transparency_algorithm": transparency_algorithm,
        "display_curves": bool(display_curves),
        "refresh_textures": bool(refresh_textures),
        "refreshed_textures": refreshed_textures if refresh_textures else [],
        "viewport_cache_reset": viewport_cache_reset,
        "image_width": image_width,
        "image_height": image_height,
        "configured_panels": configured_panels,
        "playblast_path": playblast_result,
    }
