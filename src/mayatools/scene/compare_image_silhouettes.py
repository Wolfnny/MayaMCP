from typing import Dict, List, Any


def compare_image_silhouettes(
    reference_image_path: str,
    candidate_image_path: str,
    output_path: str = None,
    reference_bbox_pixels: List[float] = None,
    candidate_bbox_pixels: List[float] = None,
    reference_bbox_normalized: List[float] = None,
    candidate_bbox_normalized: List[float] = None,
    mask_mode: str = "foreground",
    fill_holes: bool = True,
    background_color: List[float] = None,
    reference_background_color: List[float] = None,
    candidate_background_color: List[float] = None,
    background_tolerance: float = 0.08,
    alpha_threshold: float = 0.05,
    luminance_threshold: float = 0.5,
    invert_luminance: bool = False,
    compare_width: int = 256,
    compare_height: int = 512,
    align_mode: str = "bbox",
    scale_mode: str = "height",
    padding_fraction: float = 0.04,
    row_sample_count: int = 64,
    band_edges_normalized: List[float] = None,
    band_sample_count: int = 64,
    correction_profile_sample_count: int = 0,
    correction_profile_smoothing_radius: int = 1,
    correction_profile_min_width: float = 0.02,
    correction_profile_scale_range: List[float] = None,
    min_foreground_pixels: int = 8,
    auto_crop_reference: bool = False,
    auto_crop_candidate: bool = False,
    auto_crop_padding_pixels: int = 0,
    band_edges: List[float] = None,
    correction_profile_samples: int = None,
    scale_range: List[float] = None,
) -> Dict[str, Any]:
    """Compare two image silhouettes and optionally write an overlap diagnostic.

    The tool extracts binary masks from reference and candidate images using
    alpha, foreground-vs-background, or luminance thresholding. Masks can be
    normalized by their foreground bounding boxes or crop regions before
    comparison. By default the normalization preserves silhouette aspect by
    matching height, so width errors remain measurable instead of being hidden
    by a full x/y stretch. Hole filling is enabled by default so transparent or
    outlined objects can be compared as solid silhouettes. Returned metrics
    include IoU, overlap counts, aspect/centroid differences, per-row
    silhouette width error, optional vertical band width summaries, and
    optional width correction profiles that can drive generic profile-deform
    tools. This is useful for generic visual QA of modeled products, props,
    icons, sprites, masks, decals, or rendered assets against reference images.
    Optional foreground auto-cropping is useful when renders are centered on a
    larger preview canvas. reference_background_color and
    candidate_background_color can be used when the compared images use
    different studio backgrounds. band_edges, correction_profile_samples, and
    scale_range are convenience aliases for the normalized band/profile
    arguments.
    """
    import math
    import os

    try:
        from PySide6.QtGui import QImage, QColor
    except Exception:
        try:
            from PySide2.QtGui import QImage, QColor
        except Exception as exc:
            raise RuntimeError("PySide QImage is required to compare image silhouettes in Maya.") from exc

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
        color = _validate_vector(values, 3, arg_name)
        if max(color) > 1.0:
            color = [channel / 255.0 for channel in color]
        return [_clamp(channel) for channel in color]

    def _pixel_rgb_alpha(image, x, y):
        color = image.pixelColor(int(x), int(y))
        return color.redF(), color.greenF(), color.blueF(), color.alphaF()

    def _color_distance(a, b):
        dr = a[0] - b[0]
        dg = a[1] - b[1]
        db = a[2] - b[2]
        return math.sqrt(dr * dr + dg * dg + db * db)

    def _estimate_background(image, bbox):
        x0, y0, x1, y1 = bbox
        samples = []
        inset_x = max(1, int((x1 - x0 + 1) * 0.03))
        inset_y = max(1, int((y1 - y0 + 1) * 0.03))
        radius = max(1, min(inset_x, inset_y, 8))
        corners = [
            (x0 + inset_x, y0 + inset_y),
            (x1 - inset_x, y0 + inset_y),
            (x0 + inset_x, y1 - inset_y),
            (x1 - inset_x, y1 - inset_y),
        ]
        for corner_x, corner_y in corners:
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    x = max(x0, min(x1, corner_x + dx))
                    y = max(y0, min(y1, corner_y + dy))
                    samples.append(_pixel_rgb_alpha(image, x, y)[:3])
        if not samples:
            return [1.0, 1.0, 1.0]
        channels = []
        for index in range(3):
            values = sorted(sample[index] for sample in samples)
            channels.append(values[len(values) // 2])
        return channels

    def _mask_stats(mask, width, height):
        count = 0
        foreground_bbox = None
        for row in range(height):
            for column in range(width):
                if not mask[row][column]:
                    continue
                count += 1
                if foreground_bbox is None:
                    foreground_bbox = [column, row, column, row]
                else:
                    foreground_bbox[0] = min(foreground_bbox[0], column)
                    foreground_bbox[1] = min(foreground_bbox[1], row)
                    foreground_bbox[2] = max(foreground_bbox[2], column)
                    foreground_bbox[3] = max(foreground_bbox[3], row)
        return count, foreground_bbox

    def _is_foreground_pixel(red, green, blue, alpha, color):
        if alpha < alpha_threshold:
            return False
        if mask_mode == "alpha":
            return alpha >= alpha_threshold
        if mask_mode == "luminance":
            luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
            return luminance < luminance_threshold if invert_luminance else luminance >= luminance_threshold
        return _color_distance([red, green, blue], color) > background_tolerance

    def _auto_crop_bbox(image, search_bbox, color, padding_pixels, arg_prefix):
        x0, y0, x1, y1 = search_bbox
        width = image.width()
        height = image.height()
        min_x = width
        min_y = height
        max_x = -1
        max_y = -1
        foreground_pixels = 0
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                red, green, blue, alpha = _pixel_rgb_alpha(image, x, y)
                if not _is_foreground_pixel(red, green, blue, alpha, color):
                    continue
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
                foreground_pixels += 1
        if foreground_pixels < min_foreground_pixels:
            raise ValueError(
                f"Unable to auto-crop {arg_prefix}: not enough foreground pixels. "
                "Adjust background colors, tolerances, thresholds, or provide an explicit bbox."
            )
        return [
            max(0, min_x - padding_pixels),
            max(0, min_y - padding_pixels),
            min(width - 1, max_x + padding_pixels),
            min(height - 1, max_y + padding_pixels),
        ]

    def _fill_mask_holes(mask, width, height):
        visited = [bytearray(width) for _ in range(height)]
        stack = []

        def _add_background(column, row):
            if column < 0 or column >= width or row < 0 or row >= height:
                return
            if visited[row][column] or mask[row][column]:
                return
            visited[row][column] = 1
            stack.append((column, row))

        for column in range(width):
            _add_background(column, 0)
            _add_background(column, height - 1)
        for row in range(height):
            _add_background(0, row)
            _add_background(width - 1, row)

        while stack:
            column, row = stack.pop()
            _add_background(column + 1, row)
            _add_background(column - 1, row)
            _add_background(column, row + 1)
            _add_background(column, row - 1)

        filled = [bytearray(row) for row in mask]
        for row in range(height):
            for column in range(width):
                if not filled[row][column] and not visited[row][column]:
                    filled[row][column] = 1
        return filled

    def _resolve_bbox(image, bbox_pixels, bbox_normalized, arg_prefix):
        if bbox_pixels is not None and bbox_normalized is not None:
            raise ValueError(f"Provide only one of {arg_prefix}_bbox_pixels or {arg_prefix}_bbox_normalized.")
        width = image.width()
        height = image.height()
        if bbox_normalized is not None:
            bbox = _validate_vector(bbox_normalized, 4, f"{arg_prefix}_bbox_normalized")
            if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                raise ValueError(f"{arg_prefix}_bbox_normalized must be [min_x, min_y, max_x, max_y].")
            x0 = int(round(_clamp(bbox[0]) * (width - 1)))
            y0 = int(round(_clamp(bbox[1]) * (height - 1)))
            x1 = int(round(_clamp(bbox[2]) * (width - 1)))
            y1 = int(round(_clamp(bbox[3]) * (height - 1)))
        elif bbox_pixels is not None:
            bbox = _validate_vector(bbox_pixels, 4, f"{arg_prefix}_bbox_pixels")
            if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                raise ValueError(f"{arg_prefix}_bbox_pixels must be [min_x, min_y, max_x, max_y].")
            x0, y0, x1, y1 = [int(round(value)) for value in bbox]
        else:
            x0, y0, x1, y1 = 0, 0, width - 1, height - 1
        x0 = max(0, min(width - 1, x0))
        x1 = max(0, min(width - 1, x1))
        y0 = max(0, min(height - 1, y0))
        y1 = max(0, min(height - 1, y1))
        if x1 <= x0 or y1 <= y0:
            raise ValueError(f"Resolved {arg_prefix} crop bbox is empty.")
        return [x0, y0, x1, y1]

    def _mask_from_image(image, bbox, color):
        x0, y0, x1, y1 = bbox
        width = x1 - x0 + 1
        height = y1 - y0 + 1
        mask = [bytearray(width) for _ in range(height)]
        for row in range(height):
            source_y = y0 + row
            for column in range(width):
                source_x = x0 + column
                red, green, blue, alpha = _pixel_rgb_alpha(image, source_x, source_y)
                if not _is_foreground_pixel(red, green, blue, alpha, color):
                    continue
                mask[row][column] = 1
        if fill_holes:
            mask = _fill_mask_holes(mask, width, height)
        count, foreground_bbox = _mask_stats(mask, width, height)
        if count < min_foreground_pixels or foreground_bbox is None:
            raise ValueError("Not enough foreground pixels were found. Adjust bbox, mask_mode, background, tolerance, or thresholds.")
        return {
            "mask": mask,
            "width": width,
            "height": height,
            "foreground_pixels": count,
            "foreground_bbox": foreground_bbox,
        }

    def _resample_mask(mask_data):
        source = mask_data["mask"]
        source_width = mask_data["width"]
        source_height = mask_data["height"]
        if align_mode == "bbox":
            x0, y0, x1, y1 = mask_data["foreground_bbox"]
        else:
            x0, y0, x1, y1 = 0, 0, source_width - 1, source_height - 1
        source_region_width = max(1, x1 - x0 + 1)
        source_region_height = max(1, y1 - y0 + 1)
        source_span_x = max(1, source_region_width - 1)
        source_span_y = max(1, source_region_height - 1)

        pad_x = int(round(compare_width * padding_fraction))
        pad_y = int(round(compare_height * padding_fraction))
        target_width = max(1, compare_width - pad_x * 2)
        target_height = max(1, compare_height - pad_y * 2)
        if scale_mode == "stretch":
            mapped_width = target_width
            mapped_height = target_height
        else:
            height_scale = target_height / float(source_region_height)
            width_scale = target_width / float(source_region_width)
            scale = min(height_scale, width_scale) if scale_mode == "fit" else height_scale
            if source_region_width * scale > target_width:
                scale = width_scale
            mapped_width = max(1, int(round(source_region_width * scale)))
            mapped_height = max(1, int(round(source_region_height * scale)))
        target_x0 = max(0, min(compare_width - 1, int(round((compare_width - mapped_width) * 0.5))))
        target_y0 = max(0, min(compare_height - 1, int(round((compare_height - mapped_height) * 0.5))))
        target_x1 = max(target_x0, min(compare_width - 1, target_x0 + mapped_width - 1))
        target_y1 = max(target_y0, min(compare_height - 1, target_y0 + mapped_height - 1))

        result = [bytearray(compare_width) for _ in range(compare_height)]
        count = 0
        centroid_x = 0.0
        centroid_y = 0.0
        canvas_bbox = None
        for y in range(target_y0, target_y1 + 1):
            v = 0.0 if target_y1 == target_y0 else (y - target_y0) / float(target_y1 - target_y0)
            source_y = int(round(y0 + v * source_span_y))
            source_y = max(0, min(source_height - 1, source_y))
            for x in range(target_x0, target_x1 + 1):
                u = 0.0 if target_x1 == target_x0 else (x - target_x0) / float(target_x1 - target_x0)
                source_x = int(round(x0 + u * source_span_x))
                source_x = max(0, min(source_width - 1, source_x))
                if not source[source_y][source_x]:
                    continue
                result[y][x] = 1
                count += 1
                centroid_x += x
                centroid_y += y
                if canvas_bbox is None:
                    canvas_bbox = [x, y, x, y]
                else:
                    canvas_bbox[0] = min(canvas_bbox[0], x)
                    canvas_bbox[1] = min(canvas_bbox[1], y)
                    canvas_bbox[2] = max(canvas_bbox[2], x)
                    canvas_bbox[3] = max(canvas_bbox[3], y)
        centroid = [0.0, 0.0]
        if count:
            centroid = [
                centroid_x / float(count) / max(1.0, compare_width - 1),
                centroid_y / float(count) / max(1.0, compare_height - 1),
            ]
        return result, count, centroid, canvas_bbox or [0, 0, 0, 0]

    def _row_width(mask, row):
        xs = [index for index, value in enumerate(mask[row]) if value]
        if not xs:
            return 0.0
        return (max(xs) - min(xs) + 1) / float(compare_width)

    def _row_width_errors(reference_mask, candidate_mask):
        errors = []
        signed_errors = []
        samples = []
        for index in range(row_sample_count):
            row = int(round(index * (compare_height - 1) / float(max(1, row_sample_count - 1))))
            reference_width = _row_width(reference_mask, row)
            candidate_width = _row_width(candidate_mask, row)
            signed = candidate_width - reference_width
            errors.append(abs(signed))
            signed_errors.append(signed)
            samples.append({
                "row_normalized": 0.0 if compare_height == 1 else row / float(compare_height - 1),
                "reference_width": reference_width,
                "candidate_width": candidate_width,
                "signed_error": signed,
                "abs_error": abs(signed),
            })
        return {
            "mean_abs_width_error": sum(errors) / float(len(errors)) if errors else 0.0,
            "max_abs_width_error": max(errors) if errors else 0.0,
            "mean_signed_width_error": sum(signed_errors) / float(len(signed_errors)) if signed_errors else 0.0,
            "samples": samples,
        }

    def _band_width_errors(reference_mask, candidate_mask, edges):
        bands = []
        for index in range(len(edges) - 1):
            start = edges[index]
            end = edges[index + 1]
            if end <= start:
                raise ValueError("band_edges_normalized must be strictly increasing.")
            start_row = int(round(_clamp(start) * (compare_height - 1)))
            end_row = int(round(_clamp(end) * (compare_height - 1)))
            if end_row < start_row:
                start_row, end_row = end_row, start_row
            sample_total = max(2, band_sample_count)
            errors = []
            signed_errors = []
            reference_widths = []
            candidate_widths = []
            for sample_index in range(sample_total):
                if sample_total == 1 or end_row == start_row:
                    row = start_row
                else:
                    row = int(round(start_row + sample_index * (end_row - start_row) / float(sample_total - 1)))
                reference_width = _row_width(reference_mask, row)
                candidate_width = _row_width(candidate_mask, row)
                signed = candidate_width - reference_width
                errors.append(abs(signed))
                signed_errors.append(signed)
                reference_widths.append(reference_width)
                candidate_widths.append(candidate_width)
            bands.append({
                "index": index,
                "start_normalized": start,
                "end_normalized": end,
                "start_row": start_row,
                "end_row": end_row,
                "mean_reference_width": sum(reference_widths) / float(len(reference_widths)) if reference_widths else 0.0,
                "mean_candidate_width": sum(candidate_widths) / float(len(candidate_widths)) if candidate_widths else 0.0,
                "mean_abs_width_error": sum(errors) / float(len(errors)) if errors else 0.0,
                "max_abs_width_error": max(errors) if errors else 0.0,
                "mean_signed_width_error": sum(signed_errors) / float(len(signed_errors)) if signed_errors else 0.0,
            })
        return bands

    def _smooth_values(values, radius):
        if radius <= 0:
            return values[:]
        smoothed = []
        for index in range(len(values)):
            start = max(0, index - radius)
            end = min(len(values) - 1, index + radius)
            window = values[start:end + 1]
            smoothed.append(sum(window) / float(len(window)))
        return smoothed

    def _width_correction_profile(reference_mask, candidate_mask, reference_bbox, candidate_bbox):
        if correction_profile_sample_count <= 0:
            return {
                "samples_top_to_bottom": [],
                "axis_scale_profile_points": [],
                "image_scale_profile_points": [],
            }

        top = min(reference_bbox[1], candidate_bbox[1])
        bottom = max(reference_bbox[3], candidate_bbox[3])
        if bottom <= top:
            return {
                "samples_top_to_bottom": [],
                "axis_scale_profile_points": [],
                "image_scale_profile_points": [],
            }

        scale_min, scale_max = clean_correction_scale_range
        samples = []
        raw_scales = []
        for index in range(correction_profile_sample_count):
            t = index / float(max(1, correction_profile_sample_count - 1))
            row = int(round(top + t * (bottom - top)))
            reference_width = _row_width(reference_mask, row)
            candidate_width = _row_width(candidate_mask, row)
            valid = reference_width >= correction_profile_min_width and candidate_width >= correction_profile_min_width
            scale = reference_width / candidate_width if valid else 1.0
            scale = _clamp(scale, scale_min, scale_max)
            raw_scales.append(scale)
            samples.append({
                "row": row,
                "row_normalized_canvas": 0.0 if compare_height == 1 else row / float(compare_height - 1),
                "row_normalized_profile": t,
                "axis_normalized_profile": 1.0 - t,
                "reference_width": reference_width,
                "candidate_width": candidate_width,
                "signed_width_error": candidate_width - reference_width,
                "raw_scale": scale,
                "valid": valid,
            })

        smoothed_scales = _smooth_values(raw_scales, correction_profile_smoothing_radius)
        for index, sample in enumerate(samples):
            sample["scale"] = smoothed_scales[index]

        image_profile = [
            [sample["row_normalized_profile"], sample["scale"]]
            for sample in samples
        ]
        axis_profile = [
            [sample["axis_normalized_profile"], sample["scale"]]
            for sample in reversed(samples)
        ]
        return {
            "samples_top_to_bottom": samples,
            "axis_scale_profile_points": axis_profile,
            "image_scale_profile_points": image_profile,
        }

    def _write_overlay(path, reference_mask, candidate_mask):
        image = QImage(compare_width, compare_height, QImage.Format_ARGB32)
        for y in range(compare_height):
            for x in range(compare_width):
                reference_value = bool(reference_mask[y][x])
                candidate_value = bool(candidate_mask[y][x])
                if reference_value and candidate_value:
                    color = QColor(245, 245, 245, 255)
                elif reference_value:
                    color = QColor(255, 64, 64, 255)
                elif candidate_value:
                    color = QColor(64, 144, 255, 255)
                else:
                    color = QColor(24, 24, 24, 255)
                image.setPixelColor(x, y, color)
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        if not image.save(path):
            raise RuntimeError(f"Failed to save silhouette comparison overlay: {path}")

    if not reference_image_path:
        raise ValueError("reference_image_path is required.")
    if not candidate_image_path:
        raise ValueError("candidate_image_path is required.")
    reference_path = os.path.normpath(reference_image_path)
    candidate_path = os.path.normpath(candidate_image_path)
    if not os.path.isfile(reference_path):
        raise ValueError(f"Reference image path does not exist: {reference_image_path}")
    if not os.path.isfile(candidate_path):
        raise ValueError(f"Candidate image path does not exist: {candidate_image_path}")

    mask_mode = mask_mode.lower().strip()
    if mask_mode not in {"foreground", "alpha", "luminance"}:
        raise ValueError("mask_mode must be one of foreground, alpha, or luminance.")
    if not isinstance(fill_holes, bool):
        raise ValueError("fill_holes must be a boolean.")
    background_tolerance = _validate_scalar(background_tolerance, "background_tolerance")
    if background_tolerance > 1.0:
        background_tolerance /= 255.0
    if background_tolerance < 0.0:
        raise ValueError("background_tolerance must be greater than or equal to zero.")
    alpha_threshold = _clamp(_validate_scalar(alpha_threshold, "alpha_threshold"))
    luminance_threshold = _clamp(_validate_scalar(luminance_threshold, "luminance_threshold"))
    compare_width = _validate_int(compare_width, "compare_width", 8)
    compare_height = _validate_int(compare_height, "compare_height", 8)
    row_sample_count = _validate_int(row_sample_count, "row_sample_count", 2)
    band_sample_count = _validate_int(band_sample_count, "band_sample_count", 2)
    if band_edges is not None:
        if band_edges_normalized is not None:
            raise ValueError("Provide only one of band_edges or band_edges_normalized.")
        band_edges_normalized = band_edges
    if correction_profile_samples is not None:
        if correction_profile_sample_count != 0:
            raise ValueError("Provide only one of correction_profile_samples or correction_profile_sample_count.")
        correction_profile_sample_count = correction_profile_samples
    if scale_range is not None:
        if correction_profile_scale_range is not None:
            raise ValueError("Provide only one of scale_range or correction_profile_scale_range.")
        correction_profile_scale_range = scale_range

    correction_profile_sample_count = _validate_int(correction_profile_sample_count, "correction_profile_sample_count", 0)
    if correction_profile_sample_count == 1:
        raise ValueError("correction_profile_sample_count must be 0 or an integer greater than or equal to 2.")
    correction_profile_smoothing_radius = _validate_int(
        correction_profile_smoothing_radius,
        "correction_profile_smoothing_radius",
        0,
    )
    correction_profile_min_width = _validate_scalar(correction_profile_min_width, "correction_profile_min_width")
    if correction_profile_min_width < 0.0:
        raise ValueError("correction_profile_min_width must be greater than or equal to zero.")
    auto_crop_padding_pixels = _validate_int(auto_crop_padding_pixels, "auto_crop_padding_pixels", 0)
    if not isinstance(auto_crop_reference, bool):
        raise ValueError("auto_crop_reference must be a boolean.")
    if not isinstance(auto_crop_candidate, bool):
        raise ValueError("auto_crop_candidate must be a boolean.")
    clean_correction_scale_range = [0.75, 1.25]
    if correction_profile_scale_range is not None:
        clean_correction_scale_range = _validate_vector(correction_profile_scale_range, 2, "correction_profile_scale_range")
    if clean_correction_scale_range[0] <= 0.0 or clean_correction_scale_range[1] <= clean_correction_scale_range[0]:
        raise ValueError("correction_profile_scale_range must be [min_scale, max_scale] with 0 < min < max.")
    min_foreground_pixels = _validate_int(min_foreground_pixels, "min_foreground_pixels", 1)
    clean_band_edges = None
    if band_edges_normalized is not None:
        if not isinstance(band_edges_normalized, list) or len(band_edges_normalized) < 2:
            raise ValueError("band_edges_normalized must be a list with at least two numeric values.")
        clean_band_edges = []
        for value in band_edges_normalized:
            clean_value = _validate_scalar(value, "band_edges_normalized")
            if clean_value < 0.0 or clean_value > 1.0:
                raise ValueError("band_edges_normalized values must be in the range 0..1.")
            clean_band_edges.append(clean_value)
        for index in range(len(clean_band_edges) - 1):
            if clean_band_edges[index + 1] <= clean_band_edges[index]:
                raise ValueError("band_edges_normalized must be strictly increasing.")
    padding_fraction = _validate_scalar(padding_fraction, "padding_fraction")
    if padding_fraction < 0.0 or padding_fraction >= 0.45:
        raise ValueError("padding_fraction must be greater than or equal to 0 and less than 0.45.")
    align_mode = align_mode.lower().strip()
    if align_mode not in {"bbox", "crop"}:
        raise ValueError("align_mode must be one of bbox or crop.")
    scale_mode = scale_mode.lower().strip()
    if scale_mode not in {"height", "fit", "stretch"}:
        raise ValueError("scale_mode must be one of height, fit, or stretch.")

    reference_image = QImage(reference_path)
    candidate_image = QImage(candidate_path)
    if reference_image.isNull():
        raise ValueError(f"Unable to load reference image: {reference_image_path}")
    if candidate_image.isNull():
        raise ValueError(f"Unable to load candidate image: {candidate_image_path}")

    clean_background_color = _normalize_color(background_color, "background_color") if background_color else None
    clean_reference_background_color = (
        _normalize_color(reference_background_color, "reference_background_color")
        if reference_background_color
        else None
    )
    clean_candidate_background_color = (
        _normalize_color(candidate_background_color, "candidate_background_color")
        if candidate_background_color
        else None
    )
    reference_search_bbox = _resolve_bbox(reference_image, reference_bbox_pixels, reference_bbox_normalized, "reference")
    candidate_search_bbox = _resolve_bbox(candidate_image, candidate_bbox_pixels, candidate_bbox_normalized, "candidate")
    reference_background = (
        clean_reference_background_color
        or clean_background_color
        or _estimate_background(reference_image, reference_search_bbox)
    )
    candidate_background = (
        clean_candidate_background_color
        or clean_background_color
        or _estimate_background(candidate_image, candidate_search_bbox)
    )
    if auto_crop_reference and reference_bbox_pixels is None and reference_bbox_normalized is None:
        reference_bbox = _auto_crop_bbox(
            reference_image,
            reference_search_bbox,
            reference_background,
            auto_crop_padding_pixels,
            "reference_image_path",
        )
    else:
        reference_bbox = reference_search_bbox
    if auto_crop_candidate and candidate_bbox_pixels is None and candidate_bbox_normalized is None:
        candidate_bbox = _auto_crop_bbox(
            candidate_image,
            candidate_search_bbox,
            candidate_background,
            auto_crop_padding_pixels,
            "candidate_image_path",
        )
    else:
        candidate_bbox = candidate_search_bbox

    reference_data = _mask_from_image(reference_image, reference_bbox, reference_background)
    candidate_data = _mask_from_image(candidate_image, candidate_bbox, candidate_background)
    reference_mask, reference_count, reference_centroid, reference_canvas_bbox = _resample_mask(reference_data)
    candidate_mask, candidate_count, candidate_centroid, candidate_canvas_bbox = _resample_mask(candidate_data)

    intersection = 0
    union = 0
    false_positive = 0
    false_negative = 0
    for y in range(compare_height):
        for x in range(compare_width):
            reference_value = bool(reference_mask[y][x])
            candidate_value = bool(candidate_mask[y][x])
            if reference_value and candidate_value:
                intersection += 1
            if reference_value or candidate_value:
                union += 1
            if candidate_value and not reference_value:
                false_positive += 1
            if reference_value and not candidate_value:
                false_negative += 1
    iou = intersection / float(union) if union else 0.0
    precision = intersection / float(candidate_count) if candidate_count else 0.0
    recall = intersection / float(reference_count) if reference_count else 0.0
    width_metrics = _row_width_errors(reference_mask, candidate_mask)
    band_metrics = _band_width_errors(reference_mask, candidate_mask, clean_band_edges) if clean_band_edges else []
    correction_profile = _width_correction_profile(
        reference_mask,
        candidate_mask,
        reference_canvas_bbox,
        candidate_canvas_bbox,
    )

    if output_path:
        output_path = os.path.normpath(output_path)
        if not os.path.splitext(output_path)[1]:
            output_path += ".png"
        _write_overlay(output_path, reference_mask, candidate_mask)

    ref_bbox = reference_data["foreground_bbox"]
    cand_bbox = candidate_data["foreground_bbox"]
    ref_aspect = (ref_bbox[2] - ref_bbox[0] + 1) / float(max(1, ref_bbox[3] - ref_bbox[1] + 1))
    cand_aspect = (cand_bbox[2] - cand_bbox[0] + 1) / float(max(1, cand_bbox[3] - cand_bbox[1] + 1))

    return {
        "success": True,
        "reference_image_path": reference_path,
        "candidate_image_path": candidate_path,
        "output_path": output_path,
        "mask_mode": mask_mode,
        "fill_holes": fill_holes,
        "align_mode": align_mode,
        "scale_mode": scale_mode,
        "padding_fraction": padding_fraction,
        "compare_width": compare_width,
        "compare_height": compare_height,
        "band_edges_normalized": clean_band_edges,
        "band_sample_count": band_sample_count,
        "correction_profile_sample_count": correction_profile_sample_count,
        "correction_profile_smoothing_radius": correction_profile_smoothing_radius,
        "correction_profile_min_width": correction_profile_min_width,
        "correction_profile_scale_range": clean_correction_scale_range,
        "auto_crop_reference": auto_crop_reference,
        "auto_crop_candidate": auto_crop_candidate,
        "auto_crop_padding_pixels": auto_crop_padding_pixels,
        "reference_crop_bbox_pixels": reference_bbox,
        "candidate_crop_bbox_pixels": candidate_bbox,
        "reference_foreground_bbox_pixels": reference_data["foreground_bbox"],
        "candidate_foreground_bbox_pixels": candidate_data["foreground_bbox"],
        "reference_canvas_bbox_pixels": reference_canvas_bbox,
        "candidate_canvas_bbox_pixels": candidate_canvas_bbox,
        "reference_foreground_pixels": reference_data["foreground_pixels"],
        "candidate_foreground_pixels": candidate_data["foreground_pixels"],
        "reference_background_color": reference_background,
        "candidate_background_color": candidate_background,
        "reference_aspect": ref_aspect,
        "candidate_aspect": cand_aspect,
        "aspect_error": cand_aspect - ref_aspect,
        "reference_centroid_normalized": reference_centroid,
        "candidate_centroid_normalized": candidate_centroid,
        "centroid_error": [
            candidate_centroid[0] - reference_centroid[0],
            candidate_centroid[1] - reference_centroid[1],
        ],
        "intersection_pixels": intersection,
        "union_pixels": union,
        "false_positive_pixels": false_positive,
        "false_negative_pixels": false_negative,
        "iou": iou,
        "precision": precision,
        "recall": recall,
        "false_positive_rate_union": false_positive / float(union) if union else 0.0,
        "false_negative_rate_union": false_negative / float(union) if union else 0.0,
        "mean_abs_width_error": width_metrics["mean_abs_width_error"],
        "max_abs_width_error": width_metrics["max_abs_width_error"],
        "mean_signed_width_error": width_metrics["mean_signed_width_error"],
        "row_width_samples": width_metrics["samples"],
        "band_width_metrics": band_metrics,
        "correction_profile": correction_profile,
    }
