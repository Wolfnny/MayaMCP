from typing import Any, Dict, List


def audit_scene_strings(
    pattern: str = None,
    preset: str = "cjk",
    categories: List[str] = None,
    include_default_nodes: bool = False,
    long_names: bool = True,
    case_sensitive: bool = True,
    max_results: int = 1000,
) -> Dict[str, Any]:
    """Audit scene names, node names, texture paths, and related strings.

    The tool reports values that match a configurable regular expression. It is
    useful for pipeline naming checks such as CJK characters, non-ASCII text,
    whitespace, or Maya-unsafe characters. It only inspects the scene and does
    not rename nodes, repair paths, or save files.
    """
    import os
    import re
    import maya.cmds as cmds

    preset_patterns = {
        "cjk": r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]",
        "non_ascii": r"[^\x00-\x7f]",
        "whitespace": r"\s",
        "maya_unsafe": r"[<>:\"/\\|?*\[\]{};]",
    }
    default_categories = [
        "scene",
        "dag",
        "dependency_nodes",
        "transforms",
        "shapes",
        "geometry",
        "cameras",
        "lights",
        "curves",
        "materials",
        "shading_groups",
        "textures",
        "file_textures",
        "namespaces",
        "references",
        "sets",
        "display_layers",
        "render_layers",
    ]
    category_aliases = {
        "all": "all",
        "*": "all",
        "dependency": "dependency_nodes",
        "dependency_node": "dependency_nodes",
        "dependency_nodes": "dependency_nodes",
        "dag_nodes": "dag",
        "object_sets": "sets",
        "object_set": "sets",
        "set": "sets",
        "display_layer": "display_layers",
        "render_layer": "render_layers",
        "render_layers": "render_layers",
        "shading_group": "shading_groups",
        "shading_engine": "shading_groups",
        "shading_engines": "shading_groups",
        "file": "file_textures",
        "files": "file_textures",
        "file_texture": "file_textures",
    }
    default_node_names = {
        "defaultColorMgtGlobals",
        "defaultHardwareRenderGlobals",
        "defaultLightList1",
        "defaultLightSet",
        "defaultObjectSet",
        "defaultRenderGlobals",
        "defaultRenderLayer",
        "defaultResolution",
        "defaultShaderList1",
        "defaultTextureList1",
        "defaultViewColorManager",
        "displayLayerManager",
        "front",
        "frontShape",
        "hardwareRenderGlobals",
        "hardwareRenderingGlobals",
        "initialParticleSE",
        "initialShadingGroup",
        "lambert1",
        "lightLinker1",
        "particleCloud1",
        "persp",
        "perspShape",
        "postProcessList1",
        "renderLayerManager",
        "renderPartition",
        "sequenceManager1",
        "shaderGlow1",
        "side",
        "sideShape",
        "standardSurface1",
        "time1",
        "top",
        "topShape",
        "UI",
        "shared",
    }
    default_prefixes = (
        "default",
        "initial",
        "lightLinker",
        "renderPartition",
        "shaderGlow",
        "time",
        "uiConfigurationScriptNode",
    )

    def _validate_int(value, arg_name, minimum):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{arg_name} must be an integer greater than or equal to {minimum}.")
        return int(value)

    def _as_categories(values):
        if values is None:
            return default_categories[:]
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError("categories must be a string, list of strings, or None.")
        normalized = []
        for value in values:
            key = value.lower().strip().replace("-", "_")
            key = category_aliases.get(key, key)
            if key == "all":
                return default_categories[:]
            if key not in default_categories:
                raise ValueError(f"Unsupported category: {value}. Supported categories: {', '.join(default_categories)}.")
            if key not in normalized:
                normalized.append(key)
        return normalized

    def _short_name(node):
        if not node:
            return node
        return str(node).split("|")[-1]

    def _base_name(node):
        short = _short_name(node)
        return short.split(":")[-1] if short else short

    def _is_default_node(node):
        clean = _base_name(node)
        return clean in default_node_names or any(clean.startswith(prefix) for prefix in default_prefixes)

    def _node_type(node):
        if not node or not cmds.objExists(node):
            return None
        try:
            return cmds.objectType(node)
        except Exception:
            return None

    def _unique(values):
        result = []
        seen = set()
        for value in values or []:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def _add_record(records, category, field, value, node=None, node_type=None, path_exists=None):
        if value is None:
            return
        value = str(value)
        if not value:
            return
        if node and not include_default_nodes and _is_default_node(node):
            return
        records.append(
            {
                "category": category,
                "field": field,
                "node": node,
                "node_type": node_type if node_type is not None else _node_type(node),
                "value": value,
                "path_exists": path_exists,
            }
        )

    def _add_node_name(records, category, node, field="node_name"):
        _add_record(records, category, field, node, node=node)

    def _add_dag_node(records, node):
        _add_record(records, "dag", "dag_path", node, node=node)
        short = _short_name(node)
        if short and short != node:
            _add_record(records, "dag", "short_name", short, node=node)
        for segment in [part for part in str(node).split("|") if part]:
            _add_record(records, "dag", "path_segment", segment, node=node)

    def _add_scene(records):
        scene_path = cmds.file(query=True, sceneName=True) or ""
        if scene_path:
            clean_path = os.path.normpath(scene_path).replace("\\", "/")
            _add_record(records, "scene", "scene_path", clean_path, path_exists=os.path.exists(clean_path))
            _add_record(records, "scene", "scene_basename", os.path.basename(clean_path), path_exists=os.path.exists(clean_path))
            scene_dir = os.path.dirname(clean_path)
            _add_record(records, "scene", "scene_directory", scene_dir, path_exists=os.path.isdir(scene_dir))

    def _add_nodes_by_ls(records, category, field, **kwargs):
        for node in _unique(cmds.ls(**kwargs) or []):
            _add_node_name(records, category, node, field)

    def _add_references(records):
        for ref_node in _unique(cmds.ls(type="reference") or []):
            if ref_node == "sharedReferenceNode" and not include_default_nodes:
                continue
            _add_node_name(records, "references", ref_node, "reference_node")
            try:
                ref_path = cmds.referenceQuery(ref_node, filename=True)
                if ref_path:
                    clean_path = os.path.normpath(ref_path).replace("\\", "/")
                    _add_record(records, "references", "reference_path", clean_path, node=ref_node, node_type="reference", path_exists=os.path.exists(clean_path))
                    _add_record(records, "references", "reference_basename", os.path.basename(clean_path), node=ref_node, node_type="reference", path_exists=os.path.exists(clean_path))
            except Exception:
                pass

    def _add_file_textures(records):
        for node in _unique(cmds.ls(type="file") or []):
            _add_node_name(records, "file_textures", node, "file_node")
            try:
                raw_path = cmds.getAttr(f"{node}.fileTextureName") or ""
            except Exception:
                raw_path = ""
            if raw_path:
                clean_path = os.path.normpath(raw_path).replace("\\", "/")
                _add_record(records, "file_textures", "fileTextureName", clean_path, node=node, node_type="file", path_exists=os.path.exists(clean_path))
                _add_record(records, "file_textures", "texture_basename", os.path.basename(clean_path), node=node, node_type="file", path_exists=os.path.exists(clean_path))
                texture_dir = os.path.dirname(clean_path)
                _add_record(records, "file_textures", "texture_directory", texture_dir, node=node, node_type="file", path_exists=os.path.isdir(texture_dir))

    def _add_namespaces(records):
        namespaces = []
        try:
            namespaces = cmds.namespaceInfo(listOnlyNamespaces=True, recurse=True) or []
        except Exception:
            pass
        for namespace in _unique(namespaces):
            if not include_default_nodes and namespace in {"UI", "shared"}:
                continue
            _add_record(records, "namespaces", "namespace", namespace)

    clean_preset = (preset or "cjk").lower().strip()
    if clean_preset == "custom":
        if not pattern:
            raise ValueError("pattern is required when preset is custom.")
        regex_pattern = pattern
    elif clean_preset in preset_patterns:
        if pattern:
            regex_pattern = pattern
        else:
            regex_pattern = preset_patterns[clean_preset]
    else:
        raise ValueError("preset must be cjk, non_ascii, whitespace, maya_unsafe, or custom.")

    max_results = _validate_int(max_results, "max_results", 1)
    flags = 0 if case_sensitive else re.IGNORECASE
    regex = re.compile(regex_pattern, flags)
    selected_categories = _as_categories(categories)

    records = []
    if "scene" in selected_categories:
        _add_scene(records)
    if "dag" in selected_categories:
        for node in _unique(cmds.ls(dag=True, long=bool(long_names)) or []):
            if include_default_nodes or not _is_default_node(node):
                _add_dag_node(records, node)
    if "dependency_nodes" in selected_categories:
        for node in _unique(cmds.ls(dependencyNodes=True) or []):
            _add_node_name(records, "dependency_nodes", node)
    if "transforms" in selected_categories:
        _add_nodes_by_ls(records, "transforms", "transform", type="transform", long=bool(long_names))
    if "shapes" in selected_categories:
        _add_nodes_by_ls(records, "shapes", "shape", shapes=True, long=bool(long_names))
    if "geometry" in selected_categories:
        for node_type_name in ["mesh", "nurbsSurface", "subdiv", "nurbsCurve", "bezierCurve"]:
            for node in _unique(cmds.ls(type=node_type_name, long=bool(long_names)) or []):
                _add_node_name(records, "geometry", node, node_type_name)
    if "cameras" in selected_categories:
        _add_nodes_by_ls(records, "cameras", "camera", cameras=True, long=bool(long_names))
    if "lights" in selected_categories:
        _add_nodes_by_ls(records, "lights", "light", lights=True, long=bool(long_names))
    if "curves" in selected_categories:
        for node_type_name in ["nurbsCurve", "bezierCurve"]:
            for node in _unique(cmds.ls(type=node_type_name, long=bool(long_names)) or []):
                _add_node_name(records, "curves", node, node_type_name)
    if "materials" in selected_categories:
        _add_nodes_by_ls(records, "materials", "material", materials=True)
    if "shading_groups" in selected_categories:
        _add_nodes_by_ls(records, "shading_groups", "shading_group", type="shadingEngine")
    if "textures" in selected_categories:
        _add_nodes_by_ls(records, "textures", "texture", textures=True)
    if "file_textures" in selected_categories:
        _add_file_textures(records)
    if "namespaces" in selected_categories:
        _add_namespaces(records)
    if "references" in selected_categories:
        _add_references(records)
    if "sets" in selected_categories:
        _add_nodes_by_ls(records, "sets", "object_set", type="objectSet")
    if "display_layers" in selected_categories:
        _add_nodes_by_ls(records, "display_layers", "display_layer", type="displayLayer")
    if "render_layers" in selected_categories:
        _add_nodes_by_ls(records, "render_layers", "render_layer", type="renderLayer")

    unique_records = []
    seen_records = set()
    for record in records:
        key = (record["category"], record["field"], record["node"], record["value"])
        if key in seen_records:
            continue
        seen_records.add(key)
        unique_records.append(record)

    matches = []
    match_count = 0
    for record in unique_records:
        match = regex.search(record["value"])
        if not match:
            continue
        match_count += 1
        if len(matches) < max_results:
            item = dict(record)
            item["matched_text"] = match.group(0)
            matches.append(item)

    return {
        "success": match_count == 0,
        "preset": clean_preset,
        "pattern": regex_pattern,
        "scanned_count": len(unique_records),
        "match_count": match_count,
        "truncated": match_count > len(matches),
        "categories_scanned": selected_categories,
        "matches": matches,
    }
