from typing import Dict, List, Any


def extract_image_detail_mask(
    image_path: str,
    output_path: str = None,
    bbox_pixels: List[float] = None,
    bbox_normalized: List[float] = None,
    padding_pixels: int = 0,
    output_width: int = 0,
    output_height: int = 0,
    stretch_to_output: bool = True,
    horizontal_remap: str = "none",
    source_arc_degrees: float = 120.0,
    remap_center_x: float = 0.5,
    detail_mode: str = "dark",
    blur_radius: int = 8,
    threshold: float = 0.08,
    threshold_softness: float = 0.08,
    contrast: float = 4.0,
    gamma: float = 1.0,
    invert_output: bool = False,
    output_alpha: bool = False,
    overwrite: bool = True,
) -> Dict[str, Any]:
    """Extract a grayscale detail mask from a reference image region.

    The tool removes broad lighting gradients with a local blur and keeps local
    dark details, bright details, absolute contrast, or edge magnitude. It is
    intended to prepare generic masks for photo-driven relief, emboss/deboss,
    texture cleanup, decal isolation, grip-dot fields, stamped text, scratches,
    dents, and other localized details before using them as texture or
    deformation input.
    """
    import math
    import os

    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage, QColor
    except Exception:
        try:
            from PySide2.QtCore import Qt
            from PySide2.QtGui import QImage, QColor
        except Exception as exc:
            raise RuntimeError("PySide QImage is required to extract image detail masks in Maya.") from exc

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(v) for v in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(value) for value in values]

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return value

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

    def _clamp(value, lower=0.0, upper=1.0):
        return max(lower, min(upper, value))

    def _smoothstep(edge0, edge1, value):
        if abs(edge1 - edge0) <= 1e-9:
            return 1.0 if value >= edge1 else 0.0
        t = _clamp((value - edge0) / (edge1 - edge0))
        return t * t * (3.0 - 2.0 * t)

    def _pixel_rgb_alpha(image, x, y):
        color = image.pixelColor(int(x), int(y))
        return [color.redF(), color.greenF(), color.blueF(), color.alphaF()]

    def _luminance(image, x, y):
        red, green, blue, _ = _pixel_rgb_alpha(image, x, y)
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    def _make_gray(value, alpha_value=1.0):
        color = QColor()
        if output_alpha:
            color.setRgbF(1.0, 1.0, 1.0, _clamp(alpha_value))
        else:
            color.setRgbF(_clamp(value), _clamp(value), _clamp(value), 1.0)
        return color

    def _sample_bilinear(image, x, y):
        width = image.width()
        height = image.height()
        x = max(0.0, min(float(width - 1), x))
        y = max(0.0, min(float(height - 1), y))
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
        color = QColor()
        color.setRgbF(_clamp(channels[0]), _clamp(channels[1]), _clamp(channels[2]), _clamp(channels[3]))
        return color

    def _remap_cylindrical_front(image, target_width, target_height, arc_degrees, center_x):
        arc_radians = math.radians(arc_degrees)
        half_arc = arc_radians * 0.5
        sin_half_arc = math.sin(half_arc)
        if sin_half_arc <= 1e-9:
            raise ValueError("source_arc_degrees is too small for cylindrical_front remap.")
        source_width = image.width()
        source_height = image.height()
        projected_center = center_x * float(source_width - 1)
        left_span = max(1e-9, projected_center)
        right_span = max(1e-9, float(source_width - 1) - projected_center)
        remapped = QImage(target_width, target_height, QImage.Format_ARGB32)
        remapped.fill(QColor(0, 0, 0, 0))
        for y in range(target_height):
            v = 0.0 if target_height == 1 else y / float(target_height - 1)
            source_y = v * float(source_height - 1)
            for x in range(target_width):
                u = 0.0 if target_width == 1 else x / float(target_width - 1)
                theta = (u - 0.5) * arc_radians
                projected = math.sin(theta) / sin_half_arc
                if projected < 0.0:
                    source_x = projected_center + projected * left_span
                else:
                    source_x = projected_center + projected * right_span
                remapped.setPixelColor(x, y, _sample_bilinear(image, source_x, source_y))
        return remapped

    def _scale_keep_aspect(image, target_width, target_height):
        scaled = image.scaled(target_width, target_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        canvas = QImage(target_width, target_height, QImage.Format_ARGB32)
        canvas.fill(QColor(0, 0, 0, 0))
        try:
            from PySide6.QtGui import QPainter
        except Exception:
            from PySide2.QtGui import QPainter
        painter = QPainter(canvas)
        painter.drawImage(int((target_width - scaled.width()) * 0.5), int((target_height - scaled.height()) * 0.5), scaled)
        painter.end()
        return canvas

    def _integral_image(values, width, height):
        integral = [[0.0] * (width + 1) for _ in range(height + 1)]
        for y in range(height):
            row_sum = 0.0
            row = values[y]
            integral_row = integral[y + 1]
            previous_integral_row = integral[y]
            for x in range(width):
                row_sum += row[x]
                integral_row[x + 1] = previous_integral_row[x + 1] + row_sum
        return integral

    def _box_average(integral, x0, y0, x1, y1):
        width = x1 - x0 + 1
        height = y1 - y0 + 1
        total = integral[y1 + 1][x1 + 1] - integral[y0][x1 + 1] - integral[y1 + 1][x0] + integral[y0][x0]
        return total / float(width * height)

    if not image_path:
        raise ValueError("image_path is required.")
    normalized_image_path = os.path.normpath(image_path)
    if not os.path.isfile(normalized_image_path):
        raise ValueError(f"Image path does not exist: {image_path}")
    if bbox_pixels is None and bbox_normalized is None:
        raise ValueError("bbox_pixels or bbox_normalized is required.")
    if bbox_pixels is not None and bbox_normalized is not None:
        raise ValueError("Provide only one of bbox_pixels or bbox_normalized.")

    padding_pixels = _validate_int(padding_pixels, "padding_pixels", 0)
    output_width = _validate_int(output_width, "output_width", 0)
    output_height = _validate_int(output_height, "output_height", 0)
    blur_radius = _validate_int(blur_radius, "blur_radius", 0)
    threshold = _validate_scalar(threshold, "threshold")
    threshold_softness = _validate_scalar(threshold_softness, "threshold_softness")
    contrast = _validate_scalar(contrast, "contrast")
    gamma = _validate_scalar(gamma, "gamma")
    if threshold_softness < 0.0:
        raise ValueError("threshold_softness must be greater than or equal to zero.")
    if contrast < 0.0:
        raise ValueError("contrast must be greater than or equal to zero.")
    if gamma <= 0.0:
        raise ValueError("gamma must be greater than zero.")

    horizontal_remap = horizontal_remap.lower().strip()
    if horizontal_remap not in {"none", "cylindrical_front"}:
        raise ValueError("horizontal_remap must be one of none or cylindrical_front.")
    source_arc_degrees = _validate_scalar(source_arc_degrees, "source_arc_degrees")
    if source_arc_degrees <= 0.0 or source_arc_degrees >= 180.0:
        raise ValueError("source_arc_degrees must be greater than 0 and less than 180.")
    remap_center_x = _validate_scalar(remap_center_x, "remap_center_x")
    if remap_center_x <= 0.0 or remap_center_x >= 1.0:
        raise ValueError("remap_center_x must be greater than 0 and less than 1.")
    detail_mode = detail_mode.lower().strip()
    if detail_mode not in {"dark", "bright", "absolute", "edge"}:
        raise ValueError("detail_mode must be one of dark, bright, absolute, or edge.")

    image = QImage(normalized_image_path)
    if image.isNull():
        raise ValueError(f"Unable to load image: {image_path}")
    source_width = image.width()
    source_height = image.height()
    if source_width < 2 or source_height < 2:
        raise ValueError("image must be at least 2x2 pixels.")

    if bbox_normalized is not None:
        bbox = _validate_vector(bbox_normalized, 4, "bbox_normalized")
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            raise ValueError("bbox_normalized must be [min_x, min_y, max_x, max_y].")
        x_min = int(round(_clamp(bbox[0]) * (source_width - 1)))
        y_min = int(round(_clamp(bbox[1]) * (source_height - 1)))
        x_max = int(round(_clamp(bbox[2]) * (source_width - 1)))
        y_max = int(round(_clamp(bbox[3]) * (source_height - 1)))
    else:
        bbox = _validate_vector(bbox_pixels, 4, "bbox_pixels")
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            raise ValueError("bbox_pixels must be [min_x, min_y, max_x, max_y].")
        x_min = int(round(bbox[0]))
        y_min = int(round(bbox[1]))
        x_max = int(round(bbox[2]))
        y_max = int(round(bbox[3]))

    x_min = max(0, min(source_width - 1, x_min - padding_pixels))
    y_min = max(0, min(source_height - 1, y_min - padding_pixels))
    x_max = max(0, min(source_width - 1, x_max + padding_pixels))
    y_max = max(0, min(source_height - 1, y_max + padding_pixels))
    if x_max <= x_min or y_max <= y_min:
        raise ValueError("Resolved crop bbox is empty.")

    crop_width = x_max - x_min + 1
    crop_height = y_max - y_min + 1
    cropped = image.copy(x_min, y_min, crop_width, crop_height).convertToFormat(QImage.Format_ARGB32)
    final_width = output_width or cropped.width()
    final_height = output_height or cropped.height()
    if output_width or output_height:
        if output_width == 0:
            final_width = max(1, int(round(cropped.width() * (output_height / float(cropped.height())))))
        if output_height == 0:
            final_height = max(1, int(round(cropped.height() * (output_width / float(cropped.width())))))
        if horizontal_remap == "cylindrical_front":
            cropped = _remap_cylindrical_front(cropped, final_width, final_height, source_arc_degrees, remap_center_x)
        elif stretch_to_output:
            cropped = cropped.scaled(final_width, final_height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        else:
            cropped = _scale_keep_aspect(cropped, final_width, final_height)
    elif horizontal_remap == "cylindrical_front":
        cropped = _remap_cylindrical_front(cropped, final_width, final_height, source_arc_degrees, remap_center_x)

    width = cropped.width()
    height = cropped.height()
    luminance = [[_luminance(cropped, x, y) for x in range(width)] for y in range(height)]
    integral = _integral_image(luminance, width, height)
    output = QImage(width, height, QImage.Format_ARGB32)
    output.fill(QColor(0, 0, 0, 0 if output_alpha else 255))

    raw_min = None
    raw_max = None
    mask_min = None
    mask_max = None
    mask_total = 0.0
    active_pixels = 0
    for y in range(height):
        for x in range(width):
            value = luminance[y][x]
            if detail_mode == "edge":
                left = luminance[y][max(0, x - 1)]
                right = luminance[y][min(width - 1, x + 1)]
                up = luminance[max(0, y - 1)][x]
                down = luminance[min(height - 1, y + 1)][x]
                raw = math.sqrt((right - left) * (right - left) + (down - up) * (down - up))
            else:
                x0 = max(0, x - blur_radius)
                y0 = max(0, y - blur_radius)
                x1 = min(width - 1, x + blur_radius)
                y1 = min(height - 1, y + blur_radius)
                local_average = _box_average(integral, x0, y0, x1, y1)
                if detail_mode == "dark":
                    raw = local_average - value
                elif detail_mode == "bright":
                    raw = value - local_average
                else:
                    raw = abs(value - local_average)
            raw = max(0.0, raw) * contrast
            raw_min = raw if raw_min is None else min(raw_min, raw)
            raw_max = raw if raw_max is None else max(raw_max, raw)
            if threshold_softness <= 0.0:
                mask_value = 1.0 if raw >= threshold else 0.0
            else:
                mask_value = _smoothstep(threshold - threshold_softness * 0.5, threshold + threshold_softness * 0.5, raw)
            if gamma != 1.0:
                mask_value = mask_value ** gamma
            if invert_output:
                mask_value = 1.0 - mask_value
            mask_value = _clamp(mask_value)
            if mask_value > 0.001:
                active_pixels += 1
            mask_total += mask_value
            mask_min = mask_value if mask_min is None else min(mask_min, mask_value)
            mask_max = mask_value if mask_max is None else max(mask_max, mask_value)
            output.setPixelColor(x, y, _make_gray(mask_value, mask_value))

    if output_path is None:
        base_name = os.path.splitext(os.path.basename(normalized_image_path))[0] or "image"
        output_path = os.path.join(os.path.dirname(normalized_image_path), f"{base_name}_detail_mask.png")
    normalized_output_path = os.path.normpath(output_path)
    if not os.path.splitext(normalized_output_path)[1]:
        normalized_output_path += ".png"
    output_dir = os.path.dirname(normalized_output_path)
    if output_dir and not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    if os.path.exists(normalized_output_path) and not overwrite:
        raise ValueError(f"Output path already exists: {output_path}")
    if not output.save(normalized_output_path):
        raise RuntimeError(f"Failed to save detail mask: {output_path}")

    return {
        "success": True,
        "image_path": normalized_image_path,
        "output_path": normalized_output_path,
        "source_image_width": source_width,
        "source_image_height": source_height,
        "crop_bbox_pixels": [x_min, y_min, x_max, y_max],
        "crop_width": crop_width,
        "crop_height": crop_height,
        "output_width": width,
        "output_height": height,
        "horizontal_remap": horizontal_remap,
        "source_arc_degrees": source_arc_degrees,
        "remap_center_x": remap_center_x,
        "detail_mode": detail_mode,
        "blur_radius": blur_radius,
        "threshold": threshold,
        "threshold_softness": threshold_softness,
        "contrast": contrast,
        "gamma": gamma,
        "invert_output": bool(invert_output),
        "output_alpha": bool(output_alpha),
        "raw_min": raw_min if raw_min is not None else 0.0,
        "raw_max": raw_max if raw_max is not None else 0.0,
        "mask_min": mask_min if mask_min is not None else 0.0,
        "mask_max": mask_max if mask_max is not None else 0.0,
        "mask_mean": mask_total / float(max(1, width * height)),
        "active_pixels": active_pixels,
    }
