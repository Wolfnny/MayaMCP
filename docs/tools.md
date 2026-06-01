# MayaMCP Tools

Generated from local tool signatures and docstrings.

## material

- `adjust_image_colors` - Adjust image texture color channels and optional alpha.
  Parameters: `alpha_bias`, `alpha_gain`, `alpha_threshold`, `background_color`, `background_tolerance`, `brightness`, `channel_bias`, `channel_gain`, `contrast`, `gamma`, `hue_range`, `image_path`, `luminance_range`, `mask_mode`, `mix`, `output_path`, `overwrite`, `preserve_alpha`, `saturation`, `saturation_range`, `value_gain`, `value_range`
- `assign_cylindrical_image_material` - Assign a textured material to mesh faces selected by cylindrical image sampling.
  Parameters: `angle_range_degrees`, `assign_above`, `axis`, `axis_range`, `center`, `color_attribute`, `dry_run`, `face_sample_mode`, `flip_u`, `flip_v`, `image_path`, `link_uv_set`, `material_name`, `material_type`, `min_assign_faces`, `name`, `object_name`, `opacity`, `outside_angle_mode`, `outside_axis_mode`, `sample_aggregation`, `sample_channel`, `threshold`, `use_alpha`, `uv_set`
- `assign_materials_by_uv_image` - Assign mesh faces to materials by sampling an image through existing UVs.
  Parameters: `create_if_missing`, `default_rule_index`, `dry_run`, `face_sample_mode`, `flip_v`, `image_path`, `match_mode`, `material_rules`, `max_preview`, `object_name`, `sample_aggregation`, `select_result`, `unmatched_mode`, `uv_set`, `wrap_u`, `wrap_v`
- `assign_mesh_region_material` - Assign a material to mesh faces selected by cylindrical/axial bounds.
  Parameters: `angle_range_degrees`, `axis`, `axis_range`, `center`, `include_partial_faces`, `invert`, `material_color`, `material_name`, `material_parameters`, `material_type`, `object_name`, `preview_only`, `radial_range`, `shading_group_name`
- `clean_image_alpha_edges` - Clean alpha-texture edge contamination and transparent RGB padding.
  Parameters: `alpha_threshold`, `background_color`, `erode_alpha_pixels`, `feather_alpha_pixels`, `fill_transparent_rgb`, `image_path`, `output_path`, `overwrite`, `unmatte_background`, `unmatte_strength`
- `compose_image_layers` - Compose multiple image layers into a single RGBA texture.
  Parameters: `background_color`, `height`, `layers`, `output_path`, `overwrite`, `width`
- `create_material` - Creates a material in the Maya scene and optionally assigns it to an object.
  Parameters: `assign_to`, `color`, `material_type`, `name`, `parameters`
- `create_pbr_material` - Create a physically-oriented material and optionally assign it to objects.
  Parameters: `assign_to`, `base_color`, `coat`, `coat_roughness`, `emission`, `emission_color`, `ior`, `metalness`, `name`, `opacity`, `parameters`, `preset`, `roughness`, `shader_type`, `specular`, `specular_color`, `thin_walled`, `transmission`, `transmission_color`
- `create_textured_material` - Create a material driven by an image texture and optionally assign it to objects.
  Parameters: `assign_to`, `color_attribute`, `material_type`, `name`, `offset_uv`, `repeat_uv`, `rotate_uv`, `texture_path`, `use_alpha`
- `draw_image_primitives` - Draw simple vector primitives into an RGBA image.
  Parameters: `background_color`, `height`, `output_path`, `overwrite`, `primitives`, `width`
- `edit_material_assignments` - Query, assign, and select material assignments on objects or mesh faces.
  Parameters: `assign_scope`, `component_type`, `components`, `create_if_missing`, `include_components`, `indices`, `material_color`, `material_name`, `material_parameters`, `material_type`, `max_preview`, `object_name`, `operation`, `select_result`, `shading_group_name`, `use_selection`
- `edit_material_properties` - Query or set existing Maya material node attributes in batches.
  Parameters: `attributes`, `disconnect_existing`, `include_connections`, `material_names`, `max_preview`, `object_names`, `operation`, `parameters`, `skip_missing`
- `extract_image_detail_mask` - Extract a grayscale detail mask from a reference image region.
  Parameters: `bbox_normalized`, `bbox_pixels`, `blur_radius`, `contrast`, `detail_mode`, `gamma`, `horizontal_remap`, `image_path`, `invert_output`, `output_alpha`, `output_height`, `output_path`, `output_width`, `overwrite`, `padding_pixels`, `remap_center_x`, `source_arc_degrees`, `stretch_to_output`, `threshold`, `threshold_softness`
- `extract_image_matte_texture` - Extract a cropped texture with alpha matte derived from image regions.
  Parameters: `alpha_threshold`, `background_color`, `background_tolerance`, `bbox_normalized`, `bbox_pixels`, `color_tolerance`, `component_connectivity`, `component_selection`, `horizontal_remap`, `hue_tolerance`, `image_path`, `match_mode`, `matte_expand_pixels`, `matte_mode`, `min_component_pixels`, `output_height`, `output_path`, `output_width`, `overwrite`, `padding_pixels`, `remap_center_x`, `saturation_min`, `seed_normalized`, `seed_pixels`, `source_arc_degrees`, `stretch_to_output`, `target_color`, `value_min`
- `extract_image_region_texture` - Crop an image reference region into a reusable texture file.
  Parameters: `alpha_threshold`, `auto_bbox_mode`, `background_color`, `background_tolerance`, `bbox_normalized`, `bbox_pixels`, `horizontal_remap`, `image_path`, `mask_background`, `mask_background_mode`, `min_foreground_pixels`, `output_height`, `output_path`, `output_width`, `overwrite`, `padding_pixels`, `remap_center_x`, `source_arc_degrees`, `stretch_to_output`
- `get_material_assignments` - Report material and shading-group assignments for scene geometry.
  Parameters: `include_components`, `object_names`
- `refresh_file_textures` - Refresh Maya file texture nodes and viewport texture display.
  Parameters: `file_nodes`, `force_reload`, `normalize_paths`, `reset_viewport`, `validate_paths`
- `solidify_image_alpha` - Fill transparent pixels with nearby opaque color and optionally remove alpha.
  Parameters: `alpha_threshold`, `background_color`, `background_tolerance`, `image_path`, `output_path`, `overwrite`, `saturation_min`, `set_alpha`, `source_mode`, `value_min`

## object

- `assign_uv_rect_to_faces` - Assign selected mesh faces into a rectangular UV region.
  Parameters: `components`, `face_indices`, `flip_u`, `flip_v`, `max_preview`, `object_name`, `padding`, `preserve_aspect`, `select_result`, `separate_uvs`, `source_box`, `space`, `target_box`, `u_axis`, `use_selection`, `uv_set`, `v_axis`
- `create_advanced_model` - Creates an advanced model in the Maya scene.
  Parameters: `color`, `model_type`, `name`, `parameters`, `rotate`, `scale`, `translate`
- `create_curve` - Creates a curve in the Maya scene.
  Parameters: `curve_type`, `name`, `parameters`, `points`, `rotate`, `scale`, `translate`
- `create_curved_text` - Create text curves or tube geometry conformed to a cylindrical surface.
  Parameters: `angle_end`, `angle_start`, `axis`, `axis_center`, `bevel_radius`, `bevel_segments`, `center`, `create_geometry`, `fit_to_arc`, `font`, `geometry_mode`, `keep_curves`, `material_color`, `material_name`, `name`, `radius`, `surface_offset`, `text`, `text_height`, `text_rotation_degrees`
- `create_cylindrical_detail_band` - Create a UV-mapped cylindrical detail band with repeated radial features.
  Parameters: `axis`, `center`, `circumferential_amplitude`, `circumferential_cycles`, `circumferential_phase_degrees`, `circumferential_sharpness`, `height`, `height_segments`, `material_color`, `material_name`, `name`, `radial_segments`, `radius`, `smooth`, `twist_degrees`, `vertical_amplitude`, `vertical_cycles`, `vertical_phase_degrees`, `vertical_sharpness`, `waveform`
- `create_cylindrical_surface_pattern` - Create repeated conformal patches on a cylindrical or lathed surface.
  Parameters: `angle_count`, `angle_range_degrees`, `axis`, `axis_count`, `axis_range`, `center`, `center_offset`, `dome_power`, `material_color`, `material_name`, `material_parameters`, `material_type`, `name`, `patch_angle_radius_degrees`, `patch_axis_radius`, `patch_rings`, `patch_segments`, `radius`, `smooth`, `stagger`, `stagger_offset_degrees`, `surface_offset`, `surface_profile`
- `create_cylindrical_tube_paths` - Create tube geometry from cylindrical surface path coordinates.
  Parameters: `axis`, `cap_ends`, `center`, `closed`, `material_color`, `material_name`, `material_parameters`, `material_type`, `min_segment_length`, `name`, `paths`, `radial_segments`, `radius`, `smooth`, `surface_offset`, `surface_profile`, `tube_radius`
- `create_object` - Creates an object in the Maya scene. Object types available are
  Parameters: `material_color`, `material_name`, `name`, `object_type`, `parameters`, `rotate`, `translate`
- `create_revolved_liquid_volume` - Create an axisymmetric liquid volume inside a lathed container profile.
  Parameters: `angle_end`, `angle_start`, `bottom_height`, `cap_bottom`, `cap_thickness`, `cap_top`, `center`, `container_profile`, `fill_height`, `height_segments`, `material_color`, `material_name`, `name`, `profile_interpolation`, `radial_segments`, `radius_offset`, `smooth`
- `create_revolved_mesh` - Create a UV-mapped polygon mesh by revolving a radius/height profile.
  Parameters: `cap_ends`, `center`, `height_segments`, `material_color`, `material_name`, `name`, `profile`, `profile_interpolation`, `radial_segments`, `smooth`
- `create_revolved_shell` - Create a UV-mapped hollow lathed shell from radius/height profiles.
  Parameters: `center`, `connect_bottom`, `connect_top`, `height_segments`, `inner_profile`, `material_color`, `material_name`, `name`, `outer_profile`, `profile_interpolation`, `radial_segments`, `smooth`, `wall_thickness`
- `create_textured_label` - Create a UV-mapped curved label mesh and apply an image texture to it.
  Parameters: `angle_end`, `angle_start`, `center`, `height`, `material_name`, `name`, `offset`, `opacity`, `profile_interpolation`, `radius`, `segments_u`, `segments_v`, `surface_profile`, `target_object`, `texture_path`, `use_alpha`, `vertical_center`
- `create_tube_mesh_from_curves` - Create polygon tube geometry along one or more curves or point paths.
  Parameters: `cap_ends`, `curve_names`, `material_color`, `material_name`, `max_points_per_curve`, `min_segment_length`, `name`, `points`, `radial_segments`, `smooth`, `tube_radius`
- `curve_modeling` - Create geometry from curves using various modeling techniques.
  Parameters: `curves`, `name`, `operation`, `parameters`
- `cylindrical_component_deform` - Apply fitted image-mask components as local relief on a cylindrical mesh.
  Parameters: `amplitude`, `angle_range_degrees`, `axis`, `axis_range`, `black_point`, `blend_mode`, `center`, `component_connectivity`, `displacement_direction`, `falloff`, `feature_angle_scale`, `feature_axis_scale`, `flip_u`, `flip_v`, `image_path`, `invert`, `max_component_height`, `max_component_pixels`, `max_component_width`, `max_components`, `max_feature_angle_radius_degrees`, `max_feature_axis_radius`, `min_component_height`, `min_component_pixels`, `min_component_width`, `min_feature_angle_radius_degrees`, `min_feature_axis_radius`, `object_name`, `sample_channel`, `smooth`, `threshold`, `white_point`
- `cylindrical_image_deform` - Deform a cylindrical or lathed mesh from an image sampled in angle/height space.
  Parameters: `amplitude`, `angle_falloff_degrees`, `angle_range_degrees`, `axis`, `axis_falloff`, `axis_range`, `black_point`, `center`, `displacement_direction`, `flip_u`, `flip_v`, `gamma`, `image_path`, `invert`, `neutral_value`, `object_name`, `sample_channel`, `smooth`, `threshold`, `threshold_softness`, `white_point`
- `cylindrical_uv_projection` - Create or replace UVs from world-space cylindrical coordinates.
  Parameters: `angle_range_degrees`, `axis`, `axis_range`, `center`, `flip_u`, `flip_v`, `object_name`, `outside_angle_mode`, `set_current`, `uv_set`
- `edit_mesh_boundary` - Open, clean, and repair polygon mesh boundaries.
  Parameters: `component_type`, `components`, `indices`, `max_preview`, `object_name`, `operation`, `parameters`, `use_selection`
- `edit_mesh_creases` - Query and edit polygon subdivision crease weights.
  Parameters: `component_type`, `components`, `include_zero`, `indices`, `max_preview`, `object_name`, `operation`, `use_selection`, `value`
- `edit_mesh_normals` - Query and edit polygon face, edge, and vertex normals.
  Parameters: `angle`, `component_type`, `components`, `construction_history`, `distance`, `include_boundary_edges`, `indices`, `max_angle`, `max_preview`, `min_angle`, `normal`, `normalize_vector`, `object_name`, `operation`, `use_selection`
- `edit_mesh_parts` - Extract, separate, and combine polygon mesh parts.
  Parameters: `component_type`, `components`, `indices`, `max_preview`, `object_name`, `operation`, `parameters`, `target_objects`, `use_selection`
- `edit_mesh_topology` - Run component-level polygon topology edits.
  Parameters: `component_type`, `components`, `indices`, `max_preview`, `object_name`, `operation`, `parameters`, `use_selection`
- `edit_mesh_weld` - Weld, merge, sew, or collapse polygon mesh components.
  Parameters: `component_type`, `components`, `indices`, `max_preview`, `object_name`, `operation`, `parameters`, `use_selection`
- `edit_uv_components` - Query and edit mesh UV components or project UVs onto selected faces.
  Parameters: `components`, `face_components`, `max_preview`, `object_name`, `offset`, `operation`, `parameters`, `use_selection`, `uv_indices`, `uv_set`, `values_by_uv`
- `edit_uv_shells` - Query, select, and arrange UV shells deterministically.
  Parameters: `components`, `grid_columns`, `max_preview`, `object_name`, `operation`, `padding`, `preserve_aspect`, `shell_ids`, `target_box`, `target_boxes`, `use_selection`, `uv_set`
- `edit_uv_topology` - Edit UV seams, shells, unfolding, and layout at component level.
  Parameters: `component_type`, `components`, `indices`, `max_preview`, `object_name`, `operation`, `parameters`, `use_selection`, `uv_set`
- `extract_image_color_regions` - Extract connected image regions that match a color or foreground mask.
  Parameters: `alpha_threshold`, `background_color`, `background_tolerance`, `color_tolerance`, `crop`, `hue_tolerance`, `image_path`, `match_mode`, `max_regions`, `min_band_row_pixels`, `min_component_height`, `min_component_pixels`, `min_component_width`, `reference_bbox_pixels`, `saturation_min`, `target_color`, `target_height`, `value_min`
- `extract_image_contours` - Extract image-mask component contours and optionally create Maya curves.
  Parameters: `alpha_threshold`, `angle_range_degrees`, `axis`, `axis_range`, `background_color`, `background_tolerance`, `bbox_normalized`, `bbox_pixels`, `center`, `close_contours`, `color_tolerance`, `component_connectivity`, `contour_ordering`, `create_curves`, `curve_mapping`, `curve_name_prefix`, `hue_tolerance`, `image_path`, `invert`, `match_mode`, `max_bbox_height_pixels`, `max_bbox_width_pixels`, `max_components`, `max_points_per_contour`, `min_bbox_height_pixels`, `min_bbox_width_pixels`, `min_boundary_points`, `min_component_pixels`, `min_contour_points`, `offset`, `plane_axis`, `plane_height`, `plane_width`, `profile_interpolation`, `radius`, `saturation_min`, `simplify_tolerance_pixels`, `surface_profile`, `target_color`, `threshold`, `value_min`
- `extract_revolved_profile_from_image` - Extract a lathe-ready radius/height profile from a product silhouette image.
  Parameters: `alpha_threshold`, `axis_x`, `background_color`, `background_tolerance`, `center`, `create_profile_curve`, `crop`, `curve_name`, `height_samples`, `image_path`, `min_row_pixels`, `radius_offset`, `radius_scale`, `side`, `smoothing_window`, `target_height`
- `fit_objects_to_bounds` - Fit one or more scene objects to target world-space bounds.
  Parameters: `anchor`, `apply_mode`, `axes`, `min_size`, `object_names`, `pivot`, `scale_mode`, `target_bounds`, `target_center`, `target_size`
- `get_node_connections` - Inspect dependency-graph connections for a Maya node or attribute.
  Parameters: `attribute_name`, `connections`, `destination`, `node_name`, `plugs`, `skip_conversion_nodes`, `source`
- `get_object_attributes` - Get a list of attributes on a Maya object. If the object type is a transform and it the
  Parameters: `object_name`
- `get_object_bounds` - Return world-space bounds for one or more scene objects.
  Parameters: `object_names`, `visible_only`
- `insert_mesh_support_loop` - Insert one support loop from seed edges and report the new components.
  Parameters: `adjust_edge_flow`, `area_epsilon`, `axis`, `component_type`, `components`, `construction_history`, `edge_length_epsilon`, `expand`, `face_aspect_threshold`, `indices`, `insert_with_edge_flow`, `max_preview`, `object_name`, `offset`, `position_mode`, `quality_issue_types`, `result_type`, `rollback_on_quality_error`, `select_result`, `space`, `target_value`, `use_selection`, `validate_quality`
- `inspect_mesh_boundaries` - Inspect polygon mesh boundary loops without modifying geometry.
  Parameters: `components`, `max_components_per_loop`, `max_edge_count`, `max_loops`, `min_edge_count`, `object_name`, `planarity_tolerance`, `position_tolerance`, `select_components`, `selection_mode`, `sort_by`
- `inspect_mesh_components` - Inspect polygon mesh components at vertex, edge, face, UV, or summary level.
  Parameters: `component_type`, `components`, `include_normals`, `include_positions`, `include_topology`, `include_uvs`, `indices`, `max_items`, `object_name`, `space`, `uv_set`
- `inspect_mesh_quality` - Inspect polygon mesh quality and optionally select problem components.
  Parameters: `area_epsilon`, `edge_length_epsilon`, `face_aspect_threshold`, `high_valence_threshold`, `include_boundary_as_nonmanifold`, `issue_types`, `max_items`, `object_name`, `operation`, `select_components`
- `inspect_mesh_rings_by_axis` - Inspect coordinate-clustered polygon vertex rings along an axis.
  Parameters: `axis`, `axis_range`, `center`, `group_tolerance`, `include_components`, `max_groups`, `max_preview`, `min_components_per_group`, `mode`, `object_name`, `space`, `target_tolerance`, `targets`
- `linear_profile_deform` - Apply an axial profile deformation along one coordinate axis.
  Parameters: `axis`, `axis_range`, `blend`, `center`, `deform_axis`, `interpolation`, `max_abs_displacement`, `min_abs_delta`, `object_name`, `position_mode`, `profile_points`, `smooth`, `value_mode`
- `list_objects_by_type` - List scene nodes by common Maya categories.
  Parameters: `filter_by`, `long_names`, `visible_only`
- `localized_radial_pattern_deform` - Apply localized repeated radial features to a cylindrical or lathed mesh.
  Parameters: `amplitude`, `angle_count`, `angle_range_degrees`, `axis`, `axis_count`, `axis_range`, `center`, `falloff`, `feature_angle_radius_degrees`, `feature_axis_radius`, `object_name`, `smooth`, `stagger`, `stagger_offset_degrees`
- `mesh_component_operations` - Run common Maya polygon component operations.
  Parameters: `component_type`, `components`, `indices`, `object_name`, `operation`, `parameters`, `use_selection`
- `mesh_operations` - Perform mesh modeling operations on a polygon object.
  Parameters: `object_name`, `operation`, `parameters`, `select_components`
- `move_mesh_components` - Move or set polygon mesh components at vertex level.
  Parameters: `along_normal_distance`, `component_type`, `components`, `indices`, `max_preview`, `mode`, `object_name`, `positions_by_vertex`, `space`, `use_selection`, `vector`
- `organize_objects` - Organize objects in the scene through grouping, parenting, or layout operations.
  Parameters: `name`, `objects`, `operation`, `parameters`
- `polar_mesh_deform` - Apply coupled angular radial and axial deformation to a polygon mesh.
  Parameters: `axis`, `axis_amplitude`, `axis_falloff`, `axis_profile`, `axis_range`, `center`, `cycles`, `object_name`, `phase_degrees`, `radial_amplitude`, `radial_falloff`, `radial_profile`, `radial_range`, `sharpness`, `smooth`, `uniform_axis_amplitude`, `waveform`
- `radial_mesh_deform` - Apply a periodic radial deformation to a polygon mesh.
  Parameters: `amplitude`, `axis`, `axis_falloff`, `axis_profile`, `axis_range`, `center`, `cycles`, `object_name`, `phase_degrees`, `sharpness`, `smooth`, `waveform`
- `radial_profile_deform` - Apply an axial radial profile deformation to a polygon mesh.
  Parameters: `axis`, `axis_range`, `blend`, `center`, `interpolation`, `max_abs_displacement`, `min_radius`, `object_name`, `position_mode`, `profile_points`, `smooth`, `value_mode`
- `sample_mesh_radial_profile` - Sample an axial radial profile from an existing polygon mesh.
  Parameters: `axis`, `axis_range`, `center`, `min_vertices_per_sample`, `object_name`, `percentile`, `position_mode`, `radius_stat`, `sample_count`
- `sculpt_mesh_components` - Locally smooth, relax, or inflate polygon mesh components.
  Parameters: `component_type`, `components`, `distance`, `indices`, `iterations`, `max_preview`, `object_name`, `operation`, `preserve_boundary`, `select_result`, `space`, `strength`, `use_selection`
- `select_mesh_by_cylindrical_pattern` - Select mesh components by repeated cylindrical coordinate bands.
  Parameters: `angle_range_degrees`, `angular_count`, `angular_duty_cycle`, `angular_phase_degrees`, `axis`, `axis_count`, `axis_duty_cycle`, `axis_phase`, `axis_range`, `center`, `component_type`, `components`, `indices`, `invert`, `max_preview`, `object_name`, `result_type`, `sample_mode`, `select_result`, `selection_mode`, `space`, `use_selection`
- `select_mesh_by_region` - Filter mesh vertices, edges, or faces by spatial and normal criteria.
  Parameters: `angle_range_degrees`, `axis`, `axis_range`, `box_max`, `box_min`, `center`, `component_type`, `components`, `indices`, `max_preview`, `normal`, `normal_angle_degrees`, `object_name`, `radial_axis`, `radial_range`, `result_type`, `sample_mode`, `select_result`, `selection_mode`, `space`, `use_selection`
- `select_mesh_by_uv_region` - Filter mesh components by UV coordinates inside a rectangular region.
  Parameters: `component_type`, `components`, `indices`, `keep_inside`, `max_preview`, `object_name`, `result_type`, `sample_mode`, `select_result`, `selection_mode`, `use_selection`, `uv_box`, `uv_set`
- `select_mesh_components` - Resolve, convert, and select Maya polygon components.
  Parameters: `component_type`, `components`, `indices`, `max_components`, `object_name`, `operation`, `options`, `path_indices`, `select_result`, `selection_mode`, `target_type`, `use_selection`
- `select_mesh_rings_by_axis` - Select coordinate-clustered mesh rows or component bands along an axis.
  Parameters: `axis`, `axis_range`, `group_tolerance`, `max_groups`, `max_preview`, `min_components_per_group`, `mode`, `object_name`, `result_type`, `select_result`, `selection_mode`, `space`, `target_tolerance`, `targets`
- `select_mesh_silhouette_components` - Select mesh components that define a view-dependent silhouette.
  Parameters: `axis`, `axis_range`, `bin_count`, `box_max`, `box_min`, `camera_name`, `center`, `extreme_count`, `extreme_sides`, `include_boundary_edges`, `max_preview`, `method`, `min_projected_width`, `normal_dot_tolerance`, `object_name`, `result_type`, `screen_y_range`, `select_result`, `selection_mode`, `space`, `up_axis`, `view_direction`
- `set_mesh_vertex_positions` - Set exact polygon mesh vertex positions.
  Parameters: `coordinate_mask`, `max_preview`, `object_name`, `select_result`, `space`, `vertex_positions`
- `set_object_attribute` - Set an object's attribute with a specific value.
  Parameters: `attribute_name`, `attribute_value`, `disconnect_existing`, `object_name`
- `set_object_transform_attributes` - set an objects transform attributes. Only specify which attribute needs to change.
  Parameters: `object_name`, `rotate`, `scale`, `translate`
- `slide_mesh_components` - Slide resolved mesh vertices along their connected topology.
  Parameters: `axis`, `component_type`, `components`, `direction`, `distance`, `factor`, `indices`, `max_preview`, `object_name`, `prefer_unselected_neighbors`, `preserve_boundary`, `select_result`, `space`, `target_point`, `use_selection`
- `snap_mesh_components_to_surface` - Snap source mesh components onto a target mesh surface.
  Parameters: `component_type`, `components`, `fallback_to_closest`, `indices`, `max_distance`, `max_preview`, `object_name`, `offset`, `offset_direction`, `projection_mode`, `ray_both_directions`, `ray_direction`, `space`, `target_object_name`, `use_selection`
- `soft_transform_mesh_components` - Apply soft-selection style transforms around resolved mesh components.
  Parameters: `affect_all_vertices`, `axis`, `center`, `center_mode`, `component_type`, `components`, `falloff_curve`, `falloff_mode`, `falloff_radius`, `indices`, `max_preview`, `object_name`, `offset`, `operation`, `pivot`, `pivot_mode`, `preserve_boundary`, `radius_mode`, `rotation`, `scale`, `select_result`, `space`, `strength`, `topology_depth`, `use_selection`, `value`, `vector`
- `symmetrize_mesh_components` - Mirror or symmetrize selected polygon mesh components by vertex pairs.
  Parameters: `axis`, `center`, `center_mode`, `component_type`, `components`, `direction`, `indices`, `max_preview`, `object_name`, `operation`, `select_result`, `snap_center_vertices`, `space`, `tolerance`, `unique_pairs`, `use_selection`
- `transform_mesh_components` - Transform selected polygon components by editing mesh vertices.
  Parameters: `axis`, `center`, `component_type`, `components`, `end_value`, `indices`, `max_preview`, `object_name`, `operation`, `pivot`, `pivot_mode`, `plane_normal`, `plane_point`, `radius_mode`, `rotation`, `scale`, `select_result`, `space`, `start_value`, `use_selection`, `value`, `value_mode`, `vector`
- `transform_mesh_rings_by_axis` - Batch-edit coordinate-clustered mesh rings around an axis.
  Parameters: `axis`, `center`, `group_tolerance`, `max_preview`, `object_name`, `preserve_radius_variation`, `radius_stat`, `ring_edits`, `select_result`, `space`, `target_tolerance`
- `transform_uv_components` - Transform selected UV components with UV-editor style operations.
  Parameters: `axis`, `components`, `end_value`, `expand_uv_shell`, `fit_mode`, `max_preview`, `object_name`, `offset`, `operation`, `pivot`, `pivot_mode`, `rotation_degrees`, `scale`, `select_result`, `start_value`, `target_box`, `use_selection`, `uv_indices`, `uv_set`, `value`, `value_mode`
- `trim_mesh_by_axis_range` - Delete mesh faces by testing their position along an axis.
  Parameters: `axis`, `axis_range`, `dry_run`, `keep_inside`, `min_keep_faces`, `object_name`, `sample_mode`, `smooth`
- `trim_mesh_by_texture` - Delete polygon faces by sampling an image through mesh UVs.
  Parameters: `delete_below`, `dry_run`, `flip_v`, `image_path`, `min_keep_faces`, `object_name`, `sample_aggregation`, `sample_channel`, `smooth`, `threshold`, `uv_sample_mode`, `uv_set`, `wrap_u`, `wrap_v`
- `uv_operations` - Manage and generate UVs for polygon meshes.
  Parameters: `object_name`, `operation`, `parameters`, `uv_set`
- `uv_texture_deform` - Deform a UV-mapped polygon mesh by sampling an image through vertex UVs.
  Parameters: `amplitude`, `black_point`, `center`, `direction`, `flip_v`, `gamma`, `image_path`, `invert`, `min_abs_displacement`, `neutral_value`, `object_name`, `radial_axis`, `sample_channel`, `smooth`, `threshold`, `threshold_softness`, `uv_set`, `white_point`, `wrap_u`, `wrap_v`

## scene

- `audit_scene_strings` - Audit scene names, node names, texture paths, and related strings.
  Parameters: `case_sensitive`, `categories`, `include_default_nodes`, `long_names`, `max_results`, `pattern`, `preset`
- `clear_selection_list` - Clear the user selection list of objects.
- `compare_image_appearance` - Compare aligned image appearance with color-error metrics.
  Parameters: `alpha_threshold`, `auto_crop_candidate`, `auto_crop_padding_pixels`, `auto_crop_reference`, `background_color`, `background_tolerance`, `band_edges_normalized`, `candidate_background_color`, `candidate_bbox_normalized`, `candidate_bbox_pixels`, `candidate_image_path`, `compare_height`, `compare_width`, `comparison_mask_mode`, `grid_columns`, `grid_rows`, `mask_mode`, `min_compare_pixels`, `output_path`, `reference_background_color`, `reference_bbox_normalized`, `reference_bbox_pixels`, `reference_image_path`
- `compare_image_silhouettes` - Compare two image silhouettes and optionally write an overlap diagnostic.
  Parameters: `align_mode`, `alpha_threshold`, `auto_crop_candidate`, `auto_crop_padding_pixels`, `auto_crop_reference`, `background_color`, `background_tolerance`, `band_edges`, `band_edges_normalized`, `band_sample_count`, `candidate_background_color`, `candidate_background_tolerance`, `candidate_bbox_normalized`, `candidate_bbox_pixels`, `candidate_image_path`, `compare_height`, `compare_width`, `correction_profile_min_width`, `correction_profile_sample_count`, `correction_profile_samples`, `correction_profile_scale_range`, `correction_profile_smoothing_radius`, `fill_holes`, `include_correction_profile_samples`, `include_row_samples`, `invert_luminance`, `luminance_threshold`, `mask_mode`, `max_row_samples`, `min_foreground_pixels`, `output_path`, `padding_fraction`, `reference_background_color`, `reference_background_tolerance`, `reference_bbox_normalized`, `reference_bbox_pixels`, `reference_image_path`, `row_sample_count`, `row_sample_min_abs_error`, `row_sample_sort`, `scale_mode`, `scale_range`, `summary_only`
- `create_reference_image_plane` - Create a world-space textured reference image plane.
  Parameters: `center`, `fit_padding`, `fit_to_targets`, `height`, `image_aspect`, `image_path`, `lock_transform`, `material_name`, `name`, `offset`, `opacity`, `plane_axis`, `replace_existing`, `subdivisions_x`, `subdivisions_y`, `target_objects`, `use_alpha`, `width`
- `delete_objects` - Delete scene nodes by name with explicit reporting and safety guards.
  Parameters: `dry_run`, `ignore_missing`, `include_default_nodes`, `object_names`, `skip_referenced`
- `generate_scene` - Generate a complete 3D scene with multiple objects arranged according to a theme.
  Parameters: `name`, `parameters`, `scene_type`
- `map_silhouette_errors_to_components` - Map image silhouette width errors back to Maya mesh components.
  Parameters: `align_mode`, `camera_center`, `candidate_canvas_bbox_pixels`, `candidate_crop_bbox_pixels`, `candidate_foreground_bbox_pixels`, `compare_height`, `compare_width`, `component_detail`, `extreme_count`, `image_height`, `image_width`, `max_components_per_row_object`, `max_preview`, `max_rows`, `min_abs_error`, `orthographic_width`, `padding_fraction`, `row_band_pixels`, `row_width_samples`, `select_components`, `selection_mode`, `selection_scope`, `side_component_band_world`, `target_objects`, `up_axis`, `view_direction`
- `playblast_object_silhouette` - Playblast a clean orthographic silhouette of target mesh objects.
  Parameters: `background_color`, `hide_non_target_transforms`, `image_height`, `image_width`, `name`, `orthographic_width`, `output_path`, `padding_fraction`, `silhouette_color`, `target_objects`, `up_axis`, `use_isolate_select`, `view_direction`
- `scene_new` - Create a new scene in Maya. Use the force argument to force a new scene when
  Parameters: `force`
- `scene_open` - Load a scene into Maya.
  Parameters: `filename`, `force`, `namespace`
- `scene_save` - Save the current scene. If the filename is not specified, it will save it as its current name.
  Parameters: `filename`
- `select_object` - Select an object in the scene.
  Parameters: `object_name`
- `setup_product_preview_scene` - Set up a generic product-preview camera, lights, viewport, and snapshot.
  Parameters: `background_color`, `camera_position`, `display_curves`, `display_textures`, `distance_multiplier`, `fill_light_intensity`, `focal_length`, `image_height`, `image_width`, `key_light_intensity`, `name`, `playblast_path`, `refresh_textures`, `rim_light_intensity`, `target_objects`, `target_position`, `transparency_algorithm`
- `setup_turntable_preview_scene` - Render a generic multi-angle product preview turntable.
  Parameters: `analyze_foreground`, `angles_degrees`, `annotate_contact_sheet`, `background_color`, `contact_sheet_columns`, `contact_sheet_path`, `display_curves`, `display_textures`, `distance_multiplier`, `elevation_fraction`, `fill_light_intensity`, `focal_length`, `foreground_tolerance`, `image_height`, `image_prefix`, `image_width`, `key_light_intensity`, `name`, `output_directory`, `refresh_textures`, `rim_light_intensity`, `target_objects`, `target_position`, `transparency_algorithm`
- `verify_viewport_texture_display` - Verify that Maya VP2/playblast is actually drawing file textures.
  Parameters: `checker_size`, `checker_tiles`, `cleanup`, `image_height`, `image_width`, `isolate_scene`, `min_channel_range`, `min_chroma_delta`, `output_path`, `panel`
- `viewport_focus` - Center and fit the viewport to focus on an object in the scene.
  Parameters: `object_name`
