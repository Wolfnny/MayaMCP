from typing import Dict, List, Any


def trim_mesh_by_texture(
    object_name: str,
    image_path: str,
    uv_set: str = None,
    sample_channel: str = "alpha",
    threshold: float = 0.5,
    delete_below: bool = True,
    flip_v: bool = True,
    wrap_u: bool = False,
    wrap_v: bool = False,
    min_keep_faces: int = 1,
    dry_run: bool = False,
    smooth: bool = True,
) -> Dict[str, Any]:
    """Delete polygon faces by sampling an image through mesh UVs.

    Each face is sampled at its average UV coordinate against the provided
    image. Faces whose sampled channel falls below or above the threshold can
    be removed. This is useful for generic alpha-cut labels, decals, panels,
    cloth cards, leaf cards, vents, grates, masks, and other textured meshes
    where transparent or masked texture regions should become real cutout
    geometry instead of relying on viewport or material transparency sorting.
    """
    import math
    import os
    import maya.cmds as cmds

    try:
        from PySide6.QtGui import QImage
    except Exception:
        try:
            from PySide2.QtGui import QImage
        except Exception as exc:
            raise RuntimeError("PySide QImage is required to sample image pixels in Maya.") from exc

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return value

    def _clamp(value, lower=0.0, upper=1.0):
        return max(lower, min(upper, value))

    def _wrap_or_clamp(value, wrap):
        if wrap:
            return value % 1.0
        return _clamp(value)

    def _pixel_rgb_alpha(image, x, y):
        color = image.pixelColor(int(x), int(y))
        return color.redF(), color.greenF(), color.blueF(), color.alphaF()

    def _sample_bilinear(image, u, v):
        width = image.width()
        height = image.height()
        u = _wrap_or_clamp(u, wrap_u)
        v = _wrap_or_clamp(v, wrap_v)
        if flip_v:
            v = 1.0 - v
        x = u * float(width - 1)
        y = v * float(height - 1)
        x0 = int(math.floor(x))
        y0 = int(math.floor(y))
        x1 = min(width - 1, x0 + 1)
        y1 = min(height - 1, y0 + 1)
        tx = x - x0
        ty = y - y0
        c00 = _pixel_rgb_alpha(image, x0, y0)
        c10 = _pixel_rgb_alpha(image, x1, y0)
        c01 = _pixel_rgb_alpha(image, x0, y1)
        c11 = _pixel_rgb_alpha(image, x1, y1)
        channels = []
        for index in range(4):
            top = c00[index] * (1.0 - tx) + c10[index] * tx
            bottom = c01[index] * (1.0 - tx) + c11[index] * tx
            channels.append(top * (1.0 - ty) + bottom * ty)
        return channels

    def _rgb_to_hsv(red, green, blue):
        max_value = max(red, green, blue)
        min_value = min(red, green, blue)
        delta = max_value - min_value
        if delta == 0.0:
            hue = 0.0
        elif max_value == red:
            hue = ((green - blue) / delta) % 6.0
        elif max_value == green:
            hue = ((blue - red) / delta) + 2.0
        else:
            hue = ((red - green) / delta) + 4.0
        hue /= 6.0
        saturation = 0.0 if max_value == 0.0 else delta / max_value
        return hue, saturation, max_value

    def _channel_value(channels):
        red, green, blue, alpha = channels
        if sample_channel == "red":
            return red
        if sample_channel == "green":
            return green
        if sample_channel == "blue":
            return blue
        if sample_channel == "alpha":
            return alpha
        if sample_channel == "value":
            return max(red, green, blue)
        if sample_channel == "saturation":
            return _rgb_to_hsv(red, green, blue)[1]
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    def _face_uv_center(face):
        uv_components = cmds.polyListComponentConversion(face, fromFace=True, toUV=True) or []
        uv_components = cmds.ls(uv_components, flatten=True) or []
        if not uv_components:
            return None
        values = cmds.polyEditUV(uv_components, query=True) or []
        if len(values) < 2:
            return None
        us = values[0::2]
        vs = values[1::2]
        return sum(us) / float(len(us)), sum(vs) / float(len(vs))

    if not cmds.objExists(object_name):
        raise ValueError(f"Object does not exist: {object_name}")
    if not image_path:
        raise ValueError("image_path is required.")
    normalized_image_path = os.path.normpath(image_path)
    if not os.path.isfile(normalized_image_path):
        raise ValueError(f"Image path does not exist: {image_path}")

    threshold = _clamp(_validate_scalar(threshold, "threshold"))
    min_keep_faces = _validate_int(min_keep_faces, "min_keep_faces", 0)

    sample_channel = sample_channel.lower().strip()
    if sample_channel not in {"alpha", "luminance", "red", "green", "blue", "value", "saturation"}:
        raise ValueError("sample_channel must be one of alpha, luminance, red, green, blue, value, or saturation.")

    shapes = cmds.listRelatives(object_name, shapes=True, fullPath=True) or []
    if cmds.objectType(object_name) == "mesh":
        shapes = [object_name]
    if not any(cmds.objectType(shape) == "mesh" for shape in shapes):
        raise ValueError(f"{object_name} is not a polygon mesh transform or mesh shape.")

    all_uv_sets = cmds.polyUVSet(object_name, query=True, allUVSets=True) or []
    previous_uv_set = None
    current_uv = cmds.polyUVSet(object_name, query=True, currentUVSet=True) or []
    if current_uv:
        previous_uv_set = current_uv[0]
    if uv_set:
        if uv_set not in all_uv_sets:
            raise ValueError(f"UV set {uv_set} does not exist on {object_name}.")
        cmds.polyUVSet(object_name, currentUVSet=True, uvSet=uv_set)
    else:
        uv_set = previous_uv_set

    image = QImage(normalized_image_path)
    if image.isNull():
        raise ValueError(f"Unable to load image: {image_path}")
    if image.width() < 2 or image.height() < 2:
        raise ValueError("image must be at least 2x2 pixels.")

    face_count = cmds.polyEvaluate(object_name, face=True)
    if face_count < 1:
        raise ValueError(f"No polygon faces found on {object_name}.")

    sampled_faces = []
    delete_faces = []
    skipped_faces = []
    sample_values = []
    for index in range(face_count):
        face = f"{object_name}.f[{index}]"
        uv_center = _face_uv_center(face)
        if uv_center is None:
            skipped_faces.append(face)
            continue
        value = _channel_value(_sample_bilinear(image, uv_center[0], uv_center[1]))
        should_delete = value < threshold if delete_below else value > threshold
        sample_values.append(value)
        face_record = {
            "face": face,
            "uv": [uv_center[0], uv_center[1]],
            "value": value,
            "delete": should_delete,
        }
        sampled_faces.append(face_record)
        if should_delete:
            delete_faces.append(face)

    keep_count = face_count - len(delete_faces)
    if keep_count < min_keep_faces:
        raise ValueError(
            f"Texture trim would leave {keep_count} faces, which is below min_keep_faces={min_keep_faces}."
        )

    deleted_faces = []
    if delete_faces and not dry_run:
        cmds.delete(delete_faces)
        deleted_faces = delete_faces[:]
        if smooth and cmds.objExists(object_name):
            cmds.polySoftEdge(object_name, angle=180, constructionHistory=False)

    if previous_uv_set and previous_uv_set in all_uv_sets and previous_uv_set != uv_set and cmds.objExists(object_name):
        try:
            cmds.polyUVSet(object_name, currentUVSet=True, uvSet=previous_uv_set)
        except Exception:
            pass

    return {
        "success": True,
        "object_name": object_name,
        "image_path": normalized_image_path,
        "image_width": image.width(),
        "image_height": image.height(),
        "uv_set": uv_set,
        "sample_channel": sample_channel,
        "threshold": threshold,
        "delete_below": bool(delete_below),
        "flip_v": bool(flip_v),
        "wrap_u": bool(wrap_u),
        "wrap_v": bool(wrap_v),
        "dry_run": bool(dry_run),
        "face_count_before": face_count,
        "sampled_face_count": len(sampled_faces),
        "skipped_face_count": len(skipped_faces),
        "matched_face_count": len(delete_faces),
        "deleted_face_count": len(deleted_faces),
        "face_count_after": face_count if dry_run else face_count - len(deleted_faces),
        "min_sample_value": min(sample_values) if sample_values else 0.0,
        "max_sample_value": max(sample_values) if sample_values else 0.0,
        "mean_sample_value": sum(sample_values) / float(len(sample_values)) if sample_values else 0.0,
        "sampled_faces_preview": sampled_faces[:20],
        "skipped_faces_preview": skipped_faces[:20],
    }
