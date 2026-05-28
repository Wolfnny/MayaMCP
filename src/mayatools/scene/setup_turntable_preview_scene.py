from typing import Dict, List, Any, Union


def setup_turntable_preview_scene(
    name: str = "turntable_preview",
    target_objects: Union[str, List[str]] = None,
    angles_degrees: List[float] = None,
    target_position: List[float] = None,
    focal_length: float = 85.0,
    distance_multiplier: float = 3.0,
    elevation_fraction: float = 0.05,
    background_color: List[float] = [0.45, 0.45, 0.45],
    key_light_intensity: float = 1.1,
    fill_light_intensity: float = 0.35,
    rim_light_intensity: float = 0.65,
    display_textures: bool = True,
    transparency_algorithm: str = "depthPeeling",
    display_curves: bool = False,
    refresh_textures: bool = False,
    output_directory: str = None,
    image_prefix: str = None,
    contact_sheet_path: str = None,
    contact_sheet_columns: int = 0,
    annotate_contact_sheet: bool = False,
    analyze_foreground: bool = False,
    foreground_tolerance: float = 0.16,
    image_width: int = 900,
    image_height: int = 1200,
) -> Dict[str, Any]:
    """Render a generic multi-angle product preview turntable.

    The tool frames one or more target objects from their combined bounding box,
    configures a simple viewport preview scene, renders one playblast per yaw
    angle, and can optionally combine the frames into a contact sheet. It is a
    generic visual QA utility for checking whether product, prop, packaging,
    decal, transparent-material, or relief work holds up beyond a single front
    view. It can soft-refresh file texture nodes before the sequence when
    requested. Optional annotations label contact-sheet angles, and optional
    foreground analysis reports each frame's bbox, aspect, and coverage.
    """
    import math
    import os
    import re
    import maya.cmds as cmds

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
        bbox = list(cmds.exactWorldBoundingBox(objects[0]))
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

    def _safe_filename_angle(angle):
        label = f"{float(angle):.3f}".rstrip("0").rstrip(".")
        label = label.replace("-", "m").replace(".", "p")
        return re.sub(r"[^A-Za-z0-9_\\-]", "_", label)

    def _refresh_file_textures():
        refreshed = []
        for file_node in cmds.ls(type="file") or []:
            try:
                path = cmds.getAttr(f"{file_node}.fileTextureName") or ""
                if cmds.attributeQuery("disableFileLoad", node=file_node, exists=True):
                    cmds.setAttr(f"{file_node}.disableFileLoad", 0)
                try:
                    cmds.dgdirty(file_node)
                except Exception:
                    pass
                refreshed.append({"node": file_node, "path": path, "exists": bool(path and os.path.exists(os.path.normpath(path)))})
            except Exception as exc:
                refreshed.append({"node": file_node, "error": str(exc)})
        try:
            cmds.refresh(force=True)
        except Exception:
            pass
        return refreshed

    def _make_contact_sheet(frame_items, destination, columns):
        try:
            from PySide6.QtGui import QImage, QPainter, QColor, QFont
        except Exception:
            try:
                from PySide2.QtGui import QImage, QPainter, QColor, QFont
            except Exception as exc:
                raise RuntimeError("PySide QImage is required to write a contact sheet in Maya.") from exc

        if not frame_items:
            return None
        columns = max(1, columns)
        rows = int(math.ceil(len(frame_items) / float(columns)))
        sheet = QImage(image_width * columns, image_height * rows, QImage.Format_ARGB32)
        color = QColor()
        color.setRgbF(background_color[0], background_color[1], background_color[2], 1.0)
        sheet.fill(color)
        painter = QPainter(sheet)
        if annotate_contact_sheet:
            font = QFont()
            font.setPointSize(max(8, int(min(image_width, image_height) * 0.025)))
            font.setBold(True)
            painter.setFont(font)
        for index, frame_item in enumerate(frame_items):
            path = frame_item.get("playblast_path")
            image = QImage(path)
            if image.isNull():
                continue
            x = (index % columns) * image_width
            y = (index // columns) * image_height
            painter.drawImage(x, y, image)
            if annotate_contact_sheet:
                label = f"{index:02d} angle {frame_item.get('angle_degrees', 0.0):.1f} deg"
                painter.fillRect(x, y, image_width, max(24, int(image_height * 0.05)), QColor(0, 0, 0, 150))
                painter.setPen(QColor(255, 255, 255, 255))
                painter.drawText(x + 8, y + max(18, int(image_height * 0.035)), label)
        painter.end()
        directory = os.path.dirname(destination)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
        if not sheet.save(destination):
            raise RuntimeError(f"Unable to write contact sheet: {destination}")
        return destination

    def _foreground_metrics(image_path):
        try:
            from PySide6.QtGui import QImage
        except Exception:
            try:
                from PySide2.QtGui import QImage
            except Exception as exc:
                raise RuntimeError("PySide QImage is required to analyze turntable foreground frames in Maya.") from exc

        image = QImage(image_path)
        if image.isNull():
            return {
                "image_path": image_path,
                "foreground_pixels": 0,
                "foreground_coverage": 0.0,
                "foreground_bbox_pixels": None,
                "foreground_bbox_normalized": None,
                "foreground_aspect": None,
            }

        width = image.width()
        height = image.height()
        min_x = width
        min_y = height
        max_x = -1
        max_y = -1
        count = 0
        for y in range(height):
            for x in range(width):
                color = image.pixelColor(x, y)
                if color.alphaF() < 0.05:
                    continue
                red = color.redF()
                green = color.greenF()
                blue = color.blueF()
                dr = red - background_color[0]
                dg = green - background_color[1]
                db = blue - background_color[2]
                if math.sqrt(dr * dr + dg * dg + db * db) <= foreground_tolerance:
                    continue
                count += 1
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)

        if count <= 0:
            bbox = None
            normalized = None
            aspect = None
        else:
            bbox = [min_x, min_y, max_x, max_y]
            normalized = [
                min_x / float(max(1, width - 1)),
                min_y / float(max(1, height - 1)),
                max_x / float(max(1, width - 1)),
                max_y / float(max(1, height - 1)),
            ]
            bbox_width = max_x - min_x + 1
            bbox_height = max_y - min_y + 1
            aspect = bbox_width / float(max(1, bbox_height))

        return {
            "image_path": image_path,
            "foreground_pixels": count,
            "foreground_coverage": count / float(max(1, width * height)),
            "foreground_bbox_pixels": bbox,
            "foreground_bbox_normalized": normalized,
            "foreground_aspect": aspect,
        }

    if not name:
        raise ValueError("name is required.")
    target_objects = _normalize_targets(target_objects)
    if angles_degrees is None:
        angles_degrees = [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0]
    if not isinstance(angles_degrees, list) or not angles_degrees or not all(_is_number(value) for value in angles_degrees):
        raise ValueError("angles_degrees must be a non-empty list of numeric values.")
    angles_degrees = [float(value) for value in angles_degrees]

    focal_length = _validate_scalar(focal_length, "focal_length")
    distance_multiplier = _validate_scalar(distance_multiplier, "distance_multiplier")
    elevation_fraction = _validate_scalar(elevation_fraction, "elevation_fraction")
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
    if not isinstance(contact_sheet_columns, int) or isinstance(contact_sheet_columns, bool) or contact_sheet_columns < 0:
        raise ValueError("contact_sheet_columns must be an integer greater than or equal to zero.")
    if not isinstance(refresh_textures, bool):
        raise ValueError("refresh_textures must be a boolean.")
    if not isinstance(annotate_contact_sheet, bool):
        raise ValueError("annotate_contact_sheet must be a boolean.")
    if not isinstance(analyze_foreground, bool):
        raise ValueError("analyze_foreground must be a boolean.")
    foreground_tolerance = _validate_scalar(foreground_tolerance, "foreground_tolerance")
    if foreground_tolerance < 0.0:
        raise ValueError("foreground_tolerance must be greater than or equal to zero.")
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
    camera_distance = _frame_distance(bbox_size, focal_length, distance_multiplier)
    camera_y = target_position[1] + bbox_size[1] * elevation_fraction

    if output_directory is None and contact_sheet_path:
        output_directory = os.path.dirname(os.path.normpath(contact_sheet_path))
    if output_directory:
        output_directory = os.path.normpath(output_directory)
        if not os.path.exists(output_directory):
            os.makedirs(output_directory)
    if image_prefix is None:
        image_prefix = name

    for suffix in ["camera", "key_light", "fill_light", "rim_light"]:
        _safe_delete(f"{name}_{suffix}")

    camera, camera_shape = cmds.camera(name=f"{name}_camera")
    cmds.setAttr(f"{camera_shape}.focalLength", focal_length)
    cmds.setAttr(f"{camera_shape}.nearClipPlane", 0.01)
    cmds.setAttr(f"{camera_shape}.farClipPlane", 10000.0)

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

    refreshed_textures = _refresh_file_textures() if refresh_textures else []

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

    frame_results = []
    image_paths = []
    for index, angle in enumerate(angles_degrees):
        radians = math.radians(angle)
        camera_position = [
            target_position[0] + math.sin(radians) * camera_distance,
            camera_y,
            target_position[2] + math.cos(radians) * camera_distance,
        ]
        cmds.xform(camera, translation=camera_position, worldSpace=True)
        _aim_camera(camera, target_position)
        try:
            cmds.refresh(force=True)
        except Exception:
            pass

        frame_path = None
        playblast_result = None
        if output_directory:
            frame_path = os.path.join(
                output_directory,
                f"{image_prefix}_{index:02d}_{_safe_filename_angle(angle)}.png",
            )
            playblast_result = cmds.playblast(
                completeFilename=frame_path,
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
            image_paths.append(playblast_result or frame_path)

        foreground_metrics = None
        if analyze_foreground and (playblast_result or frame_path):
            foreground_metrics = _foreground_metrics(playblast_result or frame_path)

        frame_results.append(
            {
                "index": index,
                "angle_degrees": angle,
                "camera_position": camera_position,
                "playblast_path": playblast_result or frame_path,
                "foreground_metrics": foreground_metrics,
            }
        )

    written_contact_sheet = None
    if contact_sheet_path:
        normalized_contact_sheet_path = os.path.normpath(contact_sheet_path)
        columns = contact_sheet_columns if contact_sheet_columns > 0 else int(math.ceil(math.sqrt(len(image_paths))))
        written_contact_sheet = _make_contact_sheet(frame_results, normalized_contact_sheet_path, columns)

    return {
        "success": True,
        "name": name,
        "target_objects": target_objects,
        "bounding_box": bbox,
        "target_position": target_position,
        "camera": camera,
        "camera_shape": camera_shape,
        "camera_distance": camera_distance,
        "focal_length": focal_length,
        "lights": [key_light, fill_light, rim_light],
        "background_color": background_color,
        "transparency_algorithm": transparency_algorithm,
        "display_curves": bool(display_curves),
        "refresh_textures": bool(refresh_textures),
        "refreshed_textures": refreshed_textures,
        "annotate_contact_sheet": bool(annotate_contact_sheet),
        "analyze_foreground": bool(analyze_foreground),
        "foreground_tolerance": foreground_tolerance,
        "image_width": image_width,
        "image_height": image_height,
        "configured_panels": configured_panels,
        "frames": frame_results,
        "contact_sheet_path": written_contact_sheet,
    }
