from typing import Dict, Any


def verify_viewport_texture_display(
    output_path: str = None,
    image_width: int = 640,
    image_height: int = 480,
    checker_size: int = 256,
    checker_tiles: int = 8,
    min_channel_range: float = 0.35,
    min_chroma_delta: float = 0.18,
    isolate_scene: bool = True,
    cleanup: bool = True,
    panel: str = None,
) -> Dict[str, Any]:
    """Verify that Maya VP2/playblast is actually drawing file textures.

    The tool creates a temporary red/green checker texture, assigns it to a
    temporary plane, playblasts the configured model panel, and analyzes the
    captured pixels. It is intended as a generic QA probe for situations where
    modelEditor flags report textured display but the viewport or playblast
    silently falls back to flat grey/default materials.

    It restores hidden scene objects and removes temporary nodes by default.
    """
    import os
    import tempfile
    import maya.cmds as cmds
    import maya.mel as mel

    try:
        from PySide6.QtGui import QImage, QColor
    except Exception:
        try:
            from PySide2.QtGui import QImage, QColor
        except Exception as exc:
            raise RuntimeError("PySide QImage is required to verify viewport texture display.") from exc

    if not isinstance(image_width, int) or isinstance(image_width, bool) or image_width < 64:
        raise ValueError("image_width must be an integer greater than or equal to 64.")
    if not isinstance(image_height, int) or isinstance(image_height, bool) or image_height < 64:
        raise ValueError("image_height must be an integer greater than or equal to 64.")
    if not isinstance(checker_size, int) or isinstance(checker_size, bool) or checker_size < 16:
        raise ValueError("checker_size must be an integer greater than or equal to 16.")
    if not isinstance(checker_tiles, int) or isinstance(checker_tiles, bool) or checker_tiles < 2:
        raise ValueError("checker_tiles must be an integer greater than or equal to 2.")
    if not isinstance(min_channel_range, (int, float)) or isinstance(min_channel_range, bool):
        raise ValueError("min_channel_range must be numeric.")
    if not isinstance(min_chroma_delta, (int, float)) or isinstance(min_chroma_delta, bool):
        raise ValueError("min_chroma_delta must be numeric.")
    if not isinstance(isolate_scene, bool):
        raise ValueError("isolate_scene must be a boolean.")
    if not isinstance(cleanup, bool):
        raise ValueError("cleanup must be a boolean.")
    if panel is not None and not isinstance(panel, str):
        raise ValueError("panel must be a string or None.")

    temp_prefix = "mcp_viewport_texture_probe"
    temp_nodes = []
    visibility_state = {}

    def _qimage_format_argb32():
        return getattr(QImage, "Format_ARGB32", getattr(QImage.Format, "Format_ARGB32"))

    def _safe_delete(node):
        if cmds.objExists(node):
            try:
                cmds.delete(node)
            except Exception:
                pass

    def _connect_place2d(place2d, file_node):
        pairs = [
            ("coverage", "coverage"),
            ("translateFrame", "translateFrame"),
            ("rotateFrame", "rotateFrame"),
            ("mirrorU", "mirrorU"),
            ("mirrorV", "mirrorV"),
            ("stagger", "stagger"),
            ("wrapU", "wrapU"),
            ("wrapV", "wrapV"),
            ("repeatUV", "repeatUV"),
            ("offset", "offset"),
            ("rotateUV", "rotateUV"),
            ("noiseUV", "noiseUV"),
            ("vertexUvOne", "vertexUvOne"),
            ("vertexUvTwo", "vertexUvTwo"),
            ("vertexUvThree", "vertexUvThree"),
            ("vertexCameraOne", "vertexCameraOne"),
            ("outUV", "uvCoord"),
            ("outUvFilterSize", "uvFilterSize"),
        ]
        for source_attr, dest_attr in pairs:
            try:
                cmds.connectAttr(f"{place2d}.{source_attr}", f"{file_node}.{dest_attr}", force=True)
            except Exception:
                pass

    def _make_checker(path):
        image = QImage(checker_size, checker_size, _qimage_format_argb32())
        tile = max(1, int(checker_size / checker_tiles))
        red = QColor(255, 0, 0, 255)
        green = QColor(0, 255, 0, 255)
        for y in range(checker_size):
            for x in range(checker_size):
                color = red if ((x // tile) + (y // tile)) % 2 == 0 else green
                image.setPixelColor(x, y, color)
        if not image.save(path):
            raise RuntimeError(f"Failed to write temporary checker texture: {path}")

    def _capture_metrics(path):
        image = QImage(path)
        if image.isNull():
            raise RuntimeError(f"Failed to read playblast image: {path}")
        image = image.convertToFormat(_qimage_format_argb32())
        x0 = int(image.width() * 0.2)
        x1 = int(image.width() * 0.8)
        y0 = int(image.height() * 0.2)
        y1 = int(image.height() * 0.8)
        reds = []
        greens = []
        blues = []
        chroma = []
        step_x = max(1, int((x1 - x0) / 80))
        step_y = max(1, int((y1 - y0) / 80))
        for y in range(y0, y1, step_y):
            for x in range(x0, x1, step_x):
                color = image.pixelColor(x, y)
                r = color.redF()
                g = color.greenF()
                b = color.blueF()
                reds.append(r)
                greens.append(g)
                blues.append(b)
                chroma.append(abs(r - g) + abs(r - b) + abs(g - b))
        if not reds:
            raise RuntimeError("No pixels were sampled from playblast image.")
        channel_min = min(min(reds), min(greens), min(blues))
        channel_max = max(max(reds), max(greens), max(blues))
        mean_chroma = sum(chroma) / len(chroma)
        return {
            "sample_count": len(reds),
            "mean_rgb": [sum(reds) / len(reds), sum(greens) / len(greens), sum(blues) / len(blues)],
            "channel_range": channel_max - channel_min,
            "mean_chroma_delta": mean_chroma,
            "red_range": max(reds) - min(reds),
            "green_range": max(greens) - min(greens),
            "blue_range": max(blues) - min(blues),
        }

    try:
        for node in cmds.ls(f"{temp_prefix}*") or []:
            _safe_delete(node)

        temp_dir = tempfile.gettempdir()
        texture_path = os.path.join(temp_dir, f"{temp_prefix}_checker.png")
        if output_path:
            playblast_path = os.path.normpath(output_path)
        else:
            playblast_path = os.path.join(temp_dir, f"{temp_prefix}_playblast.png")
        output_dir = os.path.dirname(playblast_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        _make_checker(texture_path)

        plane = cmds.polyPlane(
            name=f"{temp_prefix}_plane",
            width=2.0,
            height=1.0,
            subdivisionsX=1,
            subdivisionsY=1,
            axis=[0, 0, 1],
        )[0]
        temp_nodes.append(plane)
        material = cmds.shadingNode("lambert", asShader=True, name=f"{temp_prefix}_mat")
        file_node = cmds.shadingNode("file", asTexture=True, isColorManaged=True, name=f"{temp_prefix}_file")
        place2d = cmds.shadingNode("place2dTexture", asUtility=True, name=f"{temp_prefix}_place2d")
        shading_group = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=f"{temp_prefix}_SG")
        temp_nodes.extend([material, file_node, place2d, shading_group])

        _connect_place2d(place2d, file_node)
        cmds.setAttr(f"{file_node}.fileTextureName", texture_path, type="string")
        if cmds.attributeQuery("disableFileLoad", node=file_node, exists=True):
            cmds.setAttr(f"{file_node}.disableFileLoad", 0)
        cmds.connectAttr(f"{file_node}.outColor", f"{material}.color", force=True)
        cmds.connectAttr(f"{material}.outColor", f"{shading_group}.surfaceShader", force=True)
        cmds.sets(plane, edit=True, forceElement=shading_group)

        if isolate_scene:
            for shape in cmds.ls(type="mesh", long=True) or []:
                try:
                    if cmds.getAttr(f"{shape}.intermediateObject"):
                        continue
                except Exception:
                    pass
                parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
                if not parents:
                    continue
                transform = parents[0]
                if transform in visibility_state:
                    continue
                plug = f"{transform}.visibility"
                if cmds.objExists(plug):
                    try:
                        visibility_state[transform] = bool(cmds.getAttr(plug))
                        cmds.setAttr(plug, transform.endswith("|" + plane) or transform == plane)
                    except Exception:
                        pass

        camera = cmds.camera(name=f"{temp_prefix}_camera")[0]
        temp_nodes.append(camera)
        cmds.xform(camera, translation=[0, 0, 4.0], worldSpace=True)

        panels = cmds.getPanel(type="modelPanel") or []
        selected_panel = panel if panel in panels else None
        if selected_panel is None:
            focused = cmds.getPanel(withFocus=True)
            selected_panel = focused if focused in panels else (panels[0] if panels else None)

        configured_panels = []
        for model_panel in panels:
            try:
                cmds.lookThru(model_panel, camera)
                try:
                    cmds.modelEditor(model_panel, edit=True, rendererName="vp2Renderer")
                except Exception:
                    pass
                cmds.modelEditor(
                    model_panel,
                    edit=True,
                    displayAppearance="smoothShaded",
                    displayTextures=True,
                    useDefaultMaterial=False,
                    wireframeOnShaded=False,
                    grid=False,
                )
                configured_panels.append(model_panel)
            except Exception:
                pass

        try:
            mel.eval("ogs -reset;")
            mel.eval("ogs -reloadTextures;")
        except Exception:
            pass
        try:
            cmds.refresh(force=True)
        except Exception:
            pass

        playblast_kwargs = {
            "completeFilename": playblast_path,
            "format": "image",
            "compression": "png",
            "frame": [1],
            "widthHeight": [image_width, image_height],
            "percent": 100,
            "quality": 95,
            "viewer": False,
            "showOrnaments": False,
            "forceOverwrite": True,
        }
        if selected_panel:
            playblast_kwargs["editorPanelName"] = selected_panel
        playblast_result = cmds.playblast(**playblast_kwargs) or playblast_path
        metrics = _capture_metrics(playblast_result)
        texture_display_ok = (
            metrics["channel_range"] >= float(min_channel_range)
            and metrics["mean_chroma_delta"] >= float(min_chroma_delta)
        )

        return {
            "success": True,
            "texture_display_ok": bool(texture_display_ok),
            "output_path": os.path.normpath(playblast_result),
            "texture_path": os.path.normpath(texture_path),
            "panel": selected_panel,
            "configured_panels": configured_panels,
            "metrics": metrics,
            "thresholds": {
                "min_channel_range": float(min_channel_range),
                "min_chroma_delta": float(min_chroma_delta),
            },
            "isolate_scene": isolate_scene,
            "cleanup": cleanup,
        }
    finally:
        for transform, visible in visibility_state.items():
            plug = f"{transform}.visibility"
            if cmds.objExists(plug):
                try:
                    cmds.setAttr(plug, visible)
                except Exception:
                    pass
        if cleanup:
            for node in reversed(temp_nodes):
                _safe_delete(node)
            for node in cmds.ls(f"{temp_prefix}*") or []:
                _safe_delete(node)
