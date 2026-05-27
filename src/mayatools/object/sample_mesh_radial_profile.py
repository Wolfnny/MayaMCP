from typing import Dict, List, Any


def sample_mesh_radial_profile(
    object_name: str,
    center: List[float] = None,
    axis: str = "y",
    axis_range: List[float] = None,
    sample_count: int = 32,
    radius_stat: str = "max",
    percentile: float = 90.0,
    position_mode: str = "world",
    min_vertices_per_sample: int = 1,
) -> Dict[str, Any]:
    """Sample an axial radial profile from an existing polygon mesh.

    The tool bins mesh vertices along an axis and reports representative radii
    around a center point. It is useful for reverse-engineering approximate
    revolve profiles from existing bottles, cups, vases, liquid volumes, shells,
    pipes, and other near-axisymmetric meshes before rebuilding or comparing
    them with generic profile-based tools.
    """
    import math
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

    def _percentile(values, pct):
        if not values:
            return 0.0
        ordered = sorted(values)
        if len(ordered) == 1:
            return ordered[0]
        position = (max(0.0, min(100.0, pct)) / 100.0) * (len(ordered) - 1)
        lower = int(math.floor(position))
        upper = int(math.ceil(position))
        if lower == upper:
            return ordered[lower]
        t = position - lower
        return ordered[lower] + (ordered[upper] - ordered[lower]) * t

    if not cmds.objExists(object_name):
        raise ValueError(f"Object does not exist: {object_name}")

    axis = axis.lower().strip()
    axes = {
        "x": (0, 1, 2),
        "y": (1, 0, 2),
        "z": (2, 0, 1),
    }
    if axis not in axes:
        raise ValueError("axis must be one of x, y, or z.")
    axis_index, radial_a, radial_b = axes[axis]

    if not isinstance(sample_count, int) or isinstance(sample_count, bool) or sample_count < 2:
        raise ValueError("sample_count must be an integer greater than or equal to 2.")
    if not isinstance(min_vertices_per_sample, int) or isinstance(min_vertices_per_sample, bool) or min_vertices_per_sample < 1:
        raise ValueError("min_vertices_per_sample must be an integer greater than or equal to 1.")

    radius_stat = radius_stat.lower().strip()
    if radius_stat not in {"max", "mean", "min", "median", "percentile"}:
        raise ValueError("radius_stat must be one of max, mean, min, median, or percentile.")
    percentile = _validate_scalar(percentile, "percentile")
    if percentile < 0.0 or percentile > 100.0:
        raise ValueError("percentile must be in the range 0..100.")

    position_mode = position_mode.lower().strip()
    if position_mode not in {"world", "relative", "normalized"}:
        raise ValueError("position_mode must be world, relative, or normalized.")

    shapes = cmds.listRelatives(object_name, shapes=True, fullPath=True) or []
    if cmds.objectType(object_name) == "mesh":
        shapes = [object_name]
    if not any(cmds.objectType(shape) == "mesh" for shape in shapes):
        raise ValueError(f"{object_name} is not a polygon mesh transform or mesh shape.")

    bbox = cmds.exactWorldBoundingBox(object_name)
    if center is None:
        clean_center = [
            (bbox[0] + bbox[3]) * 0.5,
            (bbox[1] + bbox[4]) * 0.5,
            (bbox[2] + bbox[5]) * 0.5,
        ]
    else:
        clean_center = _validate_vector(center, 3, "center")

    if axis_range is None:
        clean_axis_range = [bbox[axis_index], bbox[axis_index + 3]]
    else:
        clean_axis_range = _validate_vector(axis_range, 2, "axis_range")
    if clean_axis_range[1] < clean_axis_range[0]:
        clean_axis_range = [clean_axis_range[1], clean_axis_range[0]]
    axis_span = clean_axis_range[1] - clean_axis_range[0]
    if axis_span <= 1e-9:
        raise ValueError("axis_range must have non-zero length.")

    vertices = cmds.ls(f"{object_name}.vtx[*]", flatten=True) or []
    if not vertices:
        raise ValueError(f"No vertices found on {object_name}.")

    samples = [
        {
            "axis_value_world": clean_axis_range[0] + axis_span * (index / float(sample_count - 1)),
            "radii": [],
        }
        for index in range(sample_count)
    ]

    band_count = sample_count - 1
    skipped_vertices = 0
    for vertex in vertices:
        position = cmds.xform(vertex, query=True, worldSpace=True, translation=True)
        axis_value = position[axis_index]
        if axis_value < clean_axis_range[0] or axis_value > clean_axis_range[1]:
            skipped_vertices += 1
            continue
        t = (axis_value - clean_axis_range[0]) / axis_span
        sample_index = int(round(t * band_count))
        sample_index = max(0, min(sample_count - 1, sample_index))
        delta_a = position[radial_a] - clean_center[radial_a]
        delta_b = position[radial_b] - clean_center[radial_b]
        samples[sample_index]["radii"].append(math.sqrt(delta_a * delta_a + delta_b * delta_b))

    valid_samples = []
    for index, sample in enumerate(samples):
        radii = sample["radii"]
        valid = len(radii) >= min_vertices_per_sample
        if valid:
            if radius_stat == "max":
                radius = max(radii)
            elif radius_stat == "min":
                radius = min(radii)
            elif radius_stat == "mean":
                radius = sum(radii) / float(len(radii))
            elif radius_stat == "median":
                radius = _percentile(radii, 50.0)
            else:
                radius = _percentile(radii, percentile)
            valid_samples.append((index, radius))
        sample["vertex_count"] = len(radii)
        sample["valid"] = valid
        sample["radius"] = None

    if not valid_samples:
        raise ValueError("No samples had enough vertices. Lower min_vertices_per_sample or expand axis_range.")

    for index, radius in valid_samples:
        samples[index]["radius"] = radius

    # Fill empty samples by nearest-neighbor interpolation so the returned
    # profile is directly usable by profile-based modeling tools.
    for index, sample in enumerate(samples):
        if sample["radius"] is not None:
            continue
        previous_valid = None
        next_valid = None
        for valid_index, radius in reversed(valid_samples):
            if valid_index < index:
                previous_valid = (valid_index, radius)
                break
        for valid_index, radius in valid_samples:
            if valid_index > index:
                next_valid = (valid_index, radius)
                break
        if previous_valid and next_valid:
            span = next_valid[0] - previous_valid[0]
            t = (index - previous_valid[0]) / float(span)
            sample["radius"] = previous_valid[1] + (next_valid[1] - previous_valid[1]) * t
        elif previous_valid:
            sample["radius"] = previous_valid[1]
        else:
            sample["radius"] = next_valid[1]

    profile_points = []
    for sample in samples:
        world_value = sample["axis_value_world"]
        if position_mode == "world":
            profile_position = world_value
        elif position_mode == "relative":
            profile_position = world_value - clean_center[axis_index]
        else:
            profile_position = (world_value - clean_axis_range[0]) / axis_span
        profile_points.append([profile_position, sample["radius"]])

    return {
        "success": True,
        "object_name": object_name,
        "axis": axis,
        "center": clean_center,
        "axis_range": clean_axis_range,
        "sample_count": sample_count,
        "radius_stat": radius_stat,
        "percentile": percentile,
        "position_mode": position_mode,
        "min_vertices_per_sample": min_vertices_per_sample,
        "skipped_vertices": skipped_vertices,
        "profile_points": profile_points,
        "samples": [
            {
                "axis_value_world": sample["axis_value_world"],
                "profile_position": profile_points[index][0],
                "radius": sample["radius"],
                "vertex_count": sample["vertex_count"],
                "valid": sample["valid"],
            }
            for index, sample in enumerate(samples)
        ],
    }
