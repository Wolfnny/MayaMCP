from typing import Dict, List, Any


def compare_image_appearance(
    reference_image_path: str,
    candidate_image_path: str,
    output_path: str = None,
    reference_bbox_pixels: List[float] = None,
    candidate_bbox_pixels: List[float] = None,
    reference_bbox_normalized: List[float] = None,
    candidate_bbox_normalized: List[float] = None,
    mask_mode: str = "foreground",
    comparison_mask_mode: str = "intersection",
    background_color: List[float] = None,
    reference_background_color: List[float] = None,
    candidate_background_color: List[float] = None,
    background_tolerance: float = 0.08,
    alpha_threshold: float = 0.05,
    compare_width: int = 256,
    compare_height: int = 512,
    min_compare_pixels: int = 16,
    band_edges_normalized: List[float] = None,
    grid_rows: int = 0,
    grid_columns: int = 0,
) -> Dict[str, Any]:
    """Compare aligned image appearance with color-error metrics.

    This is a generic visual QA tool for renders, textures, sprites, decals,
    product previews, and reference-matching workflows. It crops reference and
    candidate images, stretches both crops to a shared comparison size, builds
    optional alpha/foreground masks, computes RGB and luminance error metrics,
    optionally summarizes errors by vertical bands or a 2D grid, and can write
    a three-panel diagnostic image: reference, candidate, and heatmapped
    absolute difference.
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
            raise RuntimeError("PySide QImage is required to compare image appearance in Maya.") from exc

    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _validate_vector(values, length, arg_name):
        if not isinstance(values, list) or len(values) != length or not all(_is_number(value) for value in values):
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

    def _normalize_color(values, arg_name):
        if values is None:
            return None
        color = _validate_vector(values, 3, arg_name)
        if max(color) > 1.0:
            color = [channel / 255.0 for channel in color]
        return [_clamp(channel) for channel in color]

    def _pixel_rgb_alpha(image, x, y):
        color = image.pixelColor(int(x), int(y))
        return color.redF(), color.greenF(), color.blueF(), color.alphaF()

    def _make_color(red, green, blue, alpha=1.0):
        color = QColor()
        color.setRgbF(_clamp(red), _clamp(green), _clamp(blue), _clamp(alpha))
        return color

    def _color_distance(a, b):
        dr = a[0] - b[0]
        dg = a[1] - b[1]
        db = a[2] - b[2]
        return math.sqrt(dr * dr + dg * dg + db * db)

    def _luminance(rgb):
        return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]

    def _load_image(path, arg_name):
        if not path:
            raise ValueError(f"{arg_name} is required.")
        normalized = os.path.normpath(path)
        if not os.path.exists(normalized):
            raise ValueError(f"{arg_name} does not exist: {path}")
        image = QImage(normalized)
        if image.isNull():
            raise ValueError(f"Unable to load image: {path}")
        return normalized, image.convertToFormat(QImage.Format_ARGB32)

    def _bbox_from_args(image, pixels, normalized, pixels_arg, normalized_arg):
        width = image.width()
        height = image.height()
        if pixels is not None and normalized is not None:
            raise ValueError(f"Provide either {pixels_arg} or {normalized_arg}, not both.")
        if normalized is not None:
            values = _validate_vector(normalized, 4, normalized_arg)
            x0 = int(round(_clamp(values[0]) * (width - 1)))
            y0 = int(round(_clamp(values[1]) * (height - 1)))
            x1 = int(round(_clamp(values[2]) * (width - 1)))
            y1 = int(round(_clamp(values[3]) * (height - 1)))
        elif pixels is not None:
            values = _validate_vector(pixels, 4, pixels_arg)
            x0 = int(round(values[0]))
            y0 = int(round(values[1]))
            x1 = int(round(values[2]))
            y1 = int(round(values[3]))
        else:
            x0, y0, x1, y1 = 0, 0, width - 1, height - 1
        x0 = max(0, min(width - 1, x0))
        x1 = max(0, min(width - 1, x1))
        y0 = max(0, min(height - 1, y0))
        y1 = max(0, min(height - 1, y1))
        if x1 < x0 or y1 < y0:
            raise ValueError(f"{pixels_arg} must be [min_x, min_y, max_x, max_y].")
        return [x0, y0, x1, y1]

    def _estimate_background(image):
        width = image.width()
        height = image.height()
        radius = max(1, min(8, width // 24, height // 24))
        corners = [
            (radius, radius),
            (width - 1 - radius, radius),
            (radius, height - 1 - radius),
            (width - 1 - radius, height - 1 - radius),
        ]
        samples = []
        for corner_x, corner_y in corners:
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    x = max(0, min(width - 1, corner_x + dx))
                    y = max(0, min(height - 1, corner_y + dy))
                    samples.append(_pixel_rgb_alpha(image, x, y)[:3])
        channels = []
        for index in range(3):
            values = sorted(sample[index] for sample in samples)
            channels.append(values[len(values) // 2])
        return channels

    def _crop_and_scale(image, bbox):
        x0, y0, x1, y1 = bbox
        cropped = image.copy(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
        return cropped.scaled(compare_width, compare_height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    def _mask(image, bg_color):
        mask = []
        count = 0
        for y in range(compare_height):
            row = []
            for x in range(compare_width):
                red, green, blue, alpha = _pixel_rgb_alpha(image, x, y)
                keep = True
                if mask_mode == "alpha":
                    keep = alpha >= alpha_threshold
                elif mask_mode == "foreground":
                    keep = alpha >= alpha_threshold and _color_distance((red, green, blue), bg_color) > background_tolerance
                row.append(keep)
                if keep:
                    count += 1
            mask.append(row)
        return mask, count

    def _combine_masks(reference_mask, candidate_mask):
        combined = []
        count = 0
        for y in range(compare_height):
            row = []
            for x in range(compare_width):
                ref_value = reference_mask[y][x]
                candidate_value = candidate_mask[y][x]
                if comparison_mask_mode == "intersection":
                    keep = ref_value and candidate_value
                elif comparison_mask_mode == "union":
                    keep = ref_value or candidate_value
                elif comparison_mask_mode == "reference":
                    keep = ref_value
                elif comparison_mask_mode == "candidate":
                    keep = candidate_value
                else:
                    keep = True
                row.append(keep)
                if keep:
                    count += 1
            combined.append(row)
        return combined, count

    def _heat_color(error_value):
        heat = _clamp(error_value * 4.0)
        if heat < 0.5:
            return _make_color(heat * 2.0, 0.0, 0.0)
        if heat < 0.85:
            return _make_color(1.0, (heat - 0.5) / 0.35, 0.0)
        return _make_color(1.0, 1.0, (heat - 0.85) / 0.15)

    def _validate_band_edges(values):
        if values is None:
            return None
        if not isinstance(values, list) or len(values) < 2 or not all(_is_number(value) for value in values):
            raise ValueError("band_edges_normalized must be a list of at least two numeric values.")
        edges = [_clamp(float(value)) for value in values]
        if edges[0] != 0.0:
            edges.insert(0, 0.0)
        if edges[-1] != 1.0:
            edges.append(1.0)
        for index in range(len(edges) - 1):
            if edges[index + 1] <= edges[index]:
                raise ValueError("band_edges_normalized values must be strictly increasing.")
        return edges

    def _new_stats():
        return {
            "pixels": 0,
            "sum_abs": [0.0, 0.0, 0.0],
            "sum_squared": [0.0, 0.0, 0.0],
            "sum_signed": [0.0, 0.0, 0.0],
            "luminance_abs": 0.0,
            "luminance_squared": 0.0,
            "luminance_signed": 0.0,
            "max_abs_error": 0.0,
        }

    def _update_stats(stats, rgb_delta, luma_delta):
        stats["pixels"] += 1
        stats["luminance_abs"] += abs(luma_delta)
        stats["luminance_squared"] += luma_delta * luma_delta
        stats["luminance_signed"] += luma_delta
        for index in range(3):
            abs_delta = abs(rgb_delta[index])
            stats["sum_abs"][index] += abs_delta
            stats["sum_squared"][index] += rgb_delta[index] * rgb_delta[index]
            stats["sum_signed"][index] += rgb_delta[index]
            stats["max_abs_error"] = max(stats["max_abs_error"], abs_delta)

    def _finalize_stats(stats, extra=None):
        result = dict(extra or {})
        if stats["pixels"] <= 0:
            result.update({
                "pixels": 0,
                "mean_abs_error_rgb": [None, None, None],
                "mean_signed_error_rgb": [None, None, None],
                "rmse_rgb": [None, None, None],
                "mean_abs_error": None,
                "rmse": None,
                "max_abs_error": None,
                "mean_abs_luminance_error": None,
                "mean_signed_luminance_error": None,
                "luminance_rmse": None,
            })
            return result
        inv = 1.0 / stats["pixels"]
        mean_abs_rgb = [value * inv for value in stats["sum_abs"]]
        rmse_rgb_values = [math.sqrt(value * inv) for value in stats["sum_squared"]]
        result.update({
            "pixels": stats["pixels"],
            "mean_abs_error_rgb": mean_abs_rgb,
            "mean_signed_error_rgb": [value * inv for value in stats["sum_signed"]],
            "rmse_rgb": rmse_rgb_values,
            "mean_abs_error": sum(mean_abs_rgb) / 3.0,
            "rmse": math.sqrt(sum(value * inv for value in stats["sum_squared"]) / 3.0),
            "max_abs_error": stats["max_abs_error"],
            "mean_abs_luminance_error": stats["luminance_abs"] * inv,
            "mean_signed_luminance_error": stats["luminance_signed"] * inv,
            "luminance_rmse": math.sqrt(stats["luminance_squared"] * inv),
        })
        return result

    reference_path, reference_image = _load_image(reference_image_path, "reference_image_path")
    candidate_path, candidate_image = _load_image(candidate_image_path, "candidate_image_path")

    compare_width = _validate_int(compare_width, "compare_width", 8)
    compare_height = _validate_int(compare_height, "compare_height", 8)
    min_compare_pixels = _validate_int(min_compare_pixels, "min_compare_pixels", 1)
    if not isinstance(grid_rows, int) or isinstance(grid_rows, bool) or grid_rows < 0:
        raise ValueError("grid_rows must be an integer greater than or equal to zero.")
    if not isinstance(grid_columns, int) or isinstance(grid_columns, bool) or grid_columns < 0:
        raise ValueError("grid_columns must be an integer greater than or equal to zero.")
    if (grid_rows == 0) != (grid_columns == 0):
        raise ValueError("grid_rows and grid_columns must both be zero or both be greater than zero.")
    background_tolerance = _validate_scalar(background_tolerance, "background_tolerance")
    alpha_threshold = _validate_scalar(alpha_threshold, "alpha_threshold")
    if background_tolerance < 0.0:
        raise ValueError("background_tolerance must be greater than or equal to zero.")
    if alpha_threshold < 0.0 or alpha_threshold > 1.0:
        raise ValueError("alpha_threshold must be in the 0..1 range.")

    mask_mode = mask_mode.lower().strip()
    if mask_mode not in {"none", "alpha", "foreground"}:
        raise ValueError("mask_mode must be none, alpha, or foreground.")
    comparison_mask_mode = comparison_mask_mode.lower().strip()
    if comparison_mask_mode not in {"intersection", "union", "reference", "candidate", "all"}:
        raise ValueError("comparison_mask_mode must be intersection, union, reference, candidate, or all.")
    band_edges = _validate_band_edges(band_edges_normalized)

    shared_background = _normalize_color(background_color, "background_color")
    reference_background = _normalize_color(reference_background_color, "reference_background_color") or shared_background
    candidate_background = _normalize_color(candidate_background_color, "candidate_background_color") or shared_background

    reference_bbox = _bbox_from_args(
        reference_image,
        reference_bbox_pixels,
        reference_bbox_normalized,
        "reference_bbox_pixels",
        "reference_bbox_normalized",
    )
    candidate_bbox = _bbox_from_args(
        candidate_image,
        candidate_bbox_pixels,
        candidate_bbox_normalized,
        "candidate_bbox_pixels",
        "candidate_bbox_normalized",
    )

    reference_scaled = _crop_and_scale(reference_image, reference_bbox)
    candidate_scaled = _crop_and_scale(candidate_image, candidate_bbox)
    if reference_background is None:
        reference_background = _estimate_background(reference_scaled)
    if candidate_background is None:
        candidate_background = _estimate_background(candidate_scaled)

    if mask_mode == "none":
        reference_mask = [[True for _ in range(compare_width)] for _ in range(compare_height)]
        candidate_mask = [[True for _ in range(compare_width)] for _ in range(compare_height)]
        reference_mask_count = compare_width * compare_height
        candidate_mask_count = compare_width * compare_height
    else:
        reference_mask, reference_mask_count = _mask(reference_scaled, reference_background)
        candidate_mask, candidate_mask_count = _mask(candidate_scaled, candidate_background)
    compare_mask, compare_pixel_count = _combine_masks(reference_mask, candidate_mask)
    if compare_pixel_count < min_compare_pixels:
        raise ValueError("Not enough comparison pixels. Adjust masks, bboxes, tolerances, or min_compare_pixels.")

    sum_reference = [0.0, 0.0, 0.0]
    sum_candidate = [0.0, 0.0, 0.0]
    sum_signed = [0.0, 0.0, 0.0]
    sum_abs = [0.0, 0.0, 0.0]
    sum_squared = [0.0, 0.0, 0.0]
    max_abs_error = 0.0
    luminance_abs = 0.0
    luminance_squared = 0.0
    luminance_signed = 0.0
    band_stats = []
    if band_edges:
        for band_index in range(len(band_edges) - 1):
            band_stats.append(_new_stats())
    grid_stats = []
    if grid_rows and grid_columns:
        for row in range(grid_rows):
            grid_stats.append([])
            for column in range(grid_columns):
                grid_stats[row].append(_new_stats())

    diff_image = None
    if output_path:
        diff_image = QImage(compare_width * 3, compare_height, QImage.Format_ARGB32)
        diff_image.fill(_make_color(0.08, 0.08, 0.08))

    for y in range(compare_height):
        for x in range(compare_width):
            ref_rgb = _pixel_rgb_alpha(reference_scaled, x, y)[:3]
            candidate_rgb = _pixel_rgb_alpha(candidate_scaled, x, y)[:3]
            keep = compare_mask[y][x]
            if diff_image is not None:
                diff_image.setPixelColor(x, y, _make_color(ref_rgb[0], ref_rgb[1], ref_rgb[2], 1.0 if keep else 0.35))
                diff_image.setPixelColor(x + compare_width, y, _make_color(candidate_rgb[0], candidate_rgb[1], candidate_rgb[2], 1.0 if keep else 0.35))
            if not keep:
                if diff_image is not None:
                    diff_image.setPixelColor(x + compare_width * 2, y, _make_color(0.12, 0.12, 0.12))
                continue
            ref_luma = _luminance(ref_rgb)
            candidate_luma = _luminance(candidate_rgb)
            luma_delta = candidate_luma - ref_luma
            luminance_signed += luma_delta
            luminance_abs += abs(luma_delta)
            luminance_squared += luma_delta * luma_delta
            pixel_abs_sum = 0.0
            rgb_delta = [0.0, 0.0, 0.0]
            for index in range(3):
                delta = candidate_rgb[index] - ref_rgb[index]
                rgb_delta[index] = delta
                abs_delta = abs(delta)
                sum_reference[index] += ref_rgb[index]
                sum_candidate[index] += candidate_rgb[index]
                sum_signed[index] += delta
                sum_abs[index] += abs_delta
                sum_squared[index] += delta * delta
                max_abs_error = max(max_abs_error, abs_delta)
                pixel_abs_sum += abs_delta
            if band_edges:
                y_normalized = y / float(max(1, compare_height - 1))
                for band_index in range(len(band_edges) - 1):
                    if band_edges[band_index] <= y_normalized <= band_edges[band_index + 1]:
                        _update_stats(band_stats[band_index], rgb_delta, luma_delta)
                        break
            if grid_stats:
                grid_row = min(grid_rows - 1, int((y / float(compare_height)) * grid_rows))
                grid_column = min(grid_columns - 1, int((x / float(compare_width)) * grid_columns))
                _update_stats(grid_stats[grid_row][grid_column], rgb_delta, luma_delta)
            if diff_image is not None:
                diff_image.setPixelColor(x + compare_width * 2, y, _heat_color(pixel_abs_sum / 3.0))

    output_saved = None
    if diff_image is not None:
        normalized_output_path = os.path.normpath(output_path)
        directory = os.path.dirname(normalized_output_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
        if not diff_image.save(normalized_output_path):
            raise RuntimeError(f"Unable to save appearance comparison image: {output_path}")
        output_saved = normalized_output_path

    inv_count = 1.0 / compare_pixel_count
    mean_reference_rgb = [value * inv_count for value in sum_reference]
    mean_candidate_rgb = [value * inv_count for value in sum_candidate]
    mean_signed_error_rgb = [value * inv_count for value in sum_signed]
    mean_abs_error_rgb = [value * inv_count for value in sum_abs]
    rmse_rgb = [math.sqrt(value * inv_count) for value in sum_squared]
    mean_abs_error = sum(mean_abs_error_rgb) / 3.0
    rmse = math.sqrt(sum(value * inv_count for value in sum_squared) / 3.0)
    band_appearance_metrics = []
    if band_edges:
        for band_index, stats in enumerate(band_stats):
            band_appearance_metrics.append(_finalize_stats(stats, {
                "band_index": band_index,
                "y_min_normalized": band_edges[band_index],
                "y_max_normalized": band_edges[band_index + 1],
            }))
    grid_appearance_metrics = []
    if grid_stats:
        for row in range(grid_rows):
            for column in range(grid_columns):
                grid_appearance_metrics.append(_finalize_stats(grid_stats[row][column], {
                    "row": row,
                    "column": column,
                    "x_min_normalized": column / float(grid_columns),
                    "x_max_normalized": (column + 1) / float(grid_columns),
                    "y_min_normalized": row / float(grid_rows),
                    "y_max_normalized": (row + 1) / float(grid_rows),
                }))

    return {
        "success": True,
        "reference_image_path": reference_path,
        "candidate_image_path": candidate_path,
        "output_path": output_saved,
        "reference_crop_bbox_pixels": reference_bbox,
        "candidate_crop_bbox_pixels": candidate_bbox,
        "compare_width": compare_width,
        "compare_height": compare_height,
        "band_edges_normalized": band_edges,
        "grid_rows": grid_rows,
        "grid_columns": grid_columns,
        "mask_mode": mask_mode,
        "comparison_mask_mode": comparison_mask_mode,
        "reference_background_color": reference_background,
        "candidate_background_color": candidate_background,
        "reference_mask_pixels": reference_mask_count,
        "candidate_mask_pixels": candidate_mask_count,
        "compare_pixels": compare_pixel_count,
        "compare_coverage": compare_pixel_count / float(compare_width * compare_height),
        "mean_reference_rgb": mean_reference_rgb,
        "mean_candidate_rgb": mean_candidate_rgb,
        "mean_signed_error_rgb": mean_signed_error_rgb,
        "mean_abs_error_rgb": mean_abs_error_rgb,
        "mean_abs_error": mean_abs_error,
        "rmse_rgb": rmse_rgb,
        "rmse": rmse,
        "max_abs_error": max_abs_error,
        "mean_signed_luminance_error": luminance_signed * inv_count,
        "mean_abs_luminance_error": luminance_abs * inv_count,
        "luminance_rmse": math.sqrt(luminance_squared * inv_count),
        "band_appearance_metrics": band_appearance_metrics,
        "grid_appearance_metrics": grid_appearance_metrics,
    }
