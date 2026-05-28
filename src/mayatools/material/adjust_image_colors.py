from typing import Dict, List, Any


def adjust_image_colors(
    image_path: str,
    output_path: str = None,
    channel_gain: List[float] = [1.0, 1.0, 1.0],
    channel_bias: List[float] = [0.0, 0.0, 0.0],
    gamma: List[float] = [1.0, 1.0, 1.0],
    brightness: float = 0.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
    value_gain: float = 1.0,
    alpha_gain: float = 1.0,
    alpha_bias: float = 0.0,
    preserve_alpha: bool = True,
    mask_mode: str = "alpha",
    alpha_threshold: float = 0.0,
    background_color: List[float] = None,
    background_tolerance: float = 0.06,
    luminance_range: List[float] = None,
    hue_range: List[float] = None,
    saturation_range: List[float] = None,
    value_range: List[float] = None,
    mix: float = 1.0,
    overwrite: bool = True,
) -> Dict[str, Any]:
    """Adjust image texture color channels and optional alpha.

    This is a generic texture-prep tool for decals, cards, product-photo
    cutouts, labels, sprites, reference projections, and other image textures.
    It writes an adjusted copy of an image using channel gain/bias, brightness,
    contrast, saturation, value gain, gamma, and optional alpha adjustment.
    Pixels can be limited by alpha, foreground/background color, luminance
    range, or HSV ranges so local texture tuning does not require editing the
    original source image.
    """
    import colorsys
    import os

    try:
        from PySide6.QtGui import QImage, QColor
    except Exception:
        try:
            from PySide2.QtGui import QImage, QColor
        except Exception as exc:
            raise RuntimeError("PySide QImage is required to adjust image colors.") from exc

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _clamp(value, lower=0.0, upper=1.0):
        return max(lower, min(upper, value))

    def _validate_scalar(value, arg_name):
        if not _is_number(value):
            raise ValueError(f"{arg_name} must be numeric.")
        return float(value)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(value) for value in values):
            raise ValueError(f"{arg_name} must be a list of {length} numeric values.")
        return [float(value) for value in values]

    def _validate_color(values, arg_name):
        color = _validate_vector(values, 3, arg_name)
        if max(color) > 1.0:
            color = [value / 255.0 for value in color]
        return [_clamp(value) for value in color]

    def _validate_range(values, arg_name):
        if values is None:
            return None
        clean = _validate_vector(values, 2, arg_name)
        if clean[0] > clean[1]:
            clean = [clean[1], clean[0]]
        return [_clamp(clean[0]), _clamp(clean[1])]

    def _estimate_background(image_value):
        width = image_value.width()
        height = image_value.height()
        samples = []
        radius = max(1, min(width, height, 8))
        corners = [
            (0, 0),
            (width - 1, 0),
            (0, height - 1),
            (width - 1, height - 1),
        ]
        for corner_x, corner_y in corners:
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    x = max(0, min(width - 1, corner_x + dx))
                    y = max(0, min(height - 1, corner_y + dy))
                    color = image_value.pixelColor(x, y)
                    if color.alphaF() > 0.0:
                        samples.append([color.redF(), color.greenF(), color.blueF()])
        if not samples:
            return [1.0, 1.0, 1.0]
        result = []
        for index in range(3):
            values = sorted(sample[index] for sample in samples)
            result.append(values[len(values) // 2])
        return result

    def _color_distance(color_a, color_b):
        dr = color_a[0] - color_b[0]
        dg = color_a[1] - color_b[1]
        db = color_a[2] - color_b[2]
        return (dr * dr + dg * dg + db * db) ** 0.5

    def _in_range(value, value_range):
        if value_range is None:
            return True
        return value_range[0] <= value <= value_range[1]

    def _in_hue_range(value, value_range):
        if value_range is None:
            return True
        start, end = value_range
        if start <= end:
            return start <= value <= end
        return value >= start or value <= end

    def _matches_mask(red, green, blue, alpha, background):
        if alpha < alpha_threshold:
            return False
        if mask_mode == "all":
            return True
        if mask_mode == "alpha":
            return True
        luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
        hue, hsv_saturation, hsv_value = colorsys.rgb_to_hsv(red, green, blue)
        if mask_mode == "foreground":
            return _color_distance([red, green, blue], background) > background_tolerance
        if mask_mode == "luminance_range":
            return _in_range(luminance, clean_luminance_range)
        if mask_mode == "hsv_range":
            return (
                _in_hue_range(hue, clean_hue_range)
                and _in_range(hsv_saturation, clean_saturation_range)
                and _in_range(hsv_value, clean_value_range)
            )
        return False

    if not image_path:
        raise ValueError("image_path is required.")
    normalized_image_path = os.path.normpath(image_path)
    if not os.path.isfile(normalized_image_path):
        raise ValueError(f"Image path does not exist: {image_path}")
    if output_path is None:
        root, _ = os.path.splitext(normalized_image_path)
        output_path = f"{root}_adjusted.png"
    normalized_output_path = os.path.normpath(output_path)
    if os.path.exists(normalized_output_path) and not overwrite:
        raise ValueError(f"Output path already exists: {output_path}")

    channel_gain = _validate_vector(channel_gain, 3, "channel_gain")
    channel_bias = _validate_vector(channel_bias, 3, "channel_bias")
    gamma = _validate_vector(gamma, 3, "gamma")
    if any(value <= 0.0 for value in gamma):
        raise ValueError("gamma values must be greater than zero.")
    brightness = _validate_scalar(brightness, "brightness")
    contrast = _validate_scalar(contrast, "contrast")
    if contrast < 0.0:
        raise ValueError("contrast must be greater than or equal to zero.")
    saturation = _validate_scalar(saturation, "saturation")
    if saturation < 0.0:
        raise ValueError("saturation must be greater than or equal to zero.")
    value_gain = _validate_scalar(value_gain, "value_gain")
    if value_gain < 0.0:
        raise ValueError("value_gain must be greater than or equal to zero.")
    alpha_gain = _validate_scalar(alpha_gain, "alpha_gain")
    alpha_bias = _validate_scalar(alpha_bias, "alpha_bias")
    if not isinstance(preserve_alpha, bool):
        raise ValueError("preserve_alpha must be a boolean.")
    mask_mode = mask_mode.lower().strip()
    if mask_mode not in {"all", "alpha", "foreground", "luminance_range", "hsv_range"}:
        raise ValueError("mask_mode must be all, alpha, foreground, luminance_range, or hsv_range.")
    alpha_threshold = _clamp(_validate_scalar(alpha_threshold, "alpha_threshold"))
    background_tolerance = _validate_scalar(background_tolerance, "background_tolerance")
    if background_tolerance < 0.0:
        raise ValueError("background_tolerance must be greater than or equal to zero.")
    clean_luminance_range = _validate_range(luminance_range, "luminance_range")
    clean_hue_range = _validate_range(hue_range, "hue_range")
    clean_saturation_range = _validate_range(saturation_range, "saturation_range")
    clean_value_range = _validate_range(value_range, "value_range")
    mix = _clamp(_validate_scalar(mix, "mix"))

    image = QImage(normalized_image_path)
    if image.isNull():
        raise ValueError(f"Unable to load image: {image_path}")
    image = image.convertToFormat(QImage.Format_ARGB32)

    clean_background = (
        _validate_color(background_color, "background_color")
        if background_color is not None
        else _estimate_background(image)
    )

    modified_pixels = 0
    skipped_pixels = 0
    before_rgb_sum = [0.0, 0.0, 0.0]
    after_rgb_sum = [0.0, 0.0, 0.0]
    before_alpha_sum = 0.0
    after_alpha_sum = 0.0

    width = image.width()
    height = image.height()
    for y in range(height):
        for x in range(width):
            pixel = image.pixelColor(x, y)
            red = pixel.redF()
            green = pixel.greenF()
            blue = pixel.blueF()
            alpha = pixel.alphaF()
            if not _matches_mask(red, green, blue, alpha, clean_background):
                skipped_pixels += 1
                continue

            original = [red, green, blue]
            adjusted = [red, green, blue]
            for index in range(3):
                adjusted[index] = adjusted[index] * channel_gain[index] + channel_bias[index]
                adjusted[index] = (adjusted[index] - 0.5) * contrast + 0.5 + brightness

            luminance = 0.2126 * adjusted[0] + 0.7152 * adjusted[1] + 0.0722 * adjusted[2]
            for index in range(3):
                adjusted[index] = luminance + (adjusted[index] - luminance) * saturation
                adjusted[index] *= value_gain
                adjusted[index] = _clamp(adjusted[index])
                adjusted[index] = _clamp(pow(adjusted[index], 1.0 / gamma[index]))
                adjusted[index] = original[index] * (1.0 - mix) + adjusted[index] * mix

            adjusted_alpha = alpha
            if not preserve_alpha:
                adjusted_alpha = _clamp(alpha * alpha_gain + alpha_bias)
                adjusted_alpha = alpha * (1.0 - mix) + adjusted_alpha * mix

            out = QColor()
            out.setRgbF(
                _clamp(adjusted[0]),
                _clamp(adjusted[1]),
                _clamp(adjusted[2]),
                _clamp(adjusted_alpha),
            )
            image.setPixelColor(x, y, out)

            modified_pixels += 1
            before_alpha_sum += alpha
            after_alpha_sum += adjusted_alpha
            for index in range(3):
                before_rgb_sum[index] += original[index]
                after_rgb_sum[index] += adjusted[index]

    output_directory = os.path.dirname(normalized_output_path)
    if output_directory and not os.path.isdir(output_directory):
        os.makedirs(output_directory)
    if not image.save(normalized_output_path):
        raise RuntimeError(f"Failed to save adjusted image: {output_path}")

    inv = 1.0 / float(modified_pixels) if modified_pixels else 0.0
    return {
        "success": True,
        "image_path": normalized_image_path,
        "output_path": normalized_output_path,
        "width": width,
        "height": height,
        "modified_pixels": modified_pixels,
        "skipped_pixels": skipped_pixels,
        "mask_mode": mask_mode,
        "background_color": clean_background,
        "alpha_threshold": alpha_threshold,
        "luminance_range": clean_luminance_range,
        "hue_range": clean_hue_range,
        "saturation_range": clean_saturation_range,
        "value_range": clean_value_range,
        "channel_gain": channel_gain,
        "channel_bias": channel_bias,
        "gamma": gamma,
        "brightness": brightness,
        "contrast": contrast,
        "saturation": saturation,
        "value_gain": value_gain,
        "alpha_gain": alpha_gain,
        "alpha_bias": alpha_bias,
        "preserve_alpha": preserve_alpha,
        "mix": mix,
        "mean_before_rgb": [value * inv for value in before_rgb_sum],
        "mean_after_rgb": [value * inv for value in after_rgb_sum],
        "mean_before_alpha": before_alpha_sum * inv,
        "mean_after_alpha": after_alpha_sum * inv,
    }
